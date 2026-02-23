#!/usr/bin/env python3
"""Launch docs-agent on an AWS EC2 spot instance.

Usage:
    docs-agent-aws              # launch and exit
    docs-agent-aws --wait       # launch, poll, download results when done
    docs-agent-aws --cleanup    # terminate the instance if still running
"""

from __future__ import annotations

import argparse
import base64
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from docs_agent.runner_utils import AGENT_ROOT, load_env, package_agent_code, require

INSTANCE_TAG = "docsagent-runner"


# ---------------------------------------------------------------------------
# AWS helpers
# ---------------------------------------------------------------------------

def get_region(env: dict[str, str]) -> str:
    return require(env, "AWS_REGION")


def find_instance(ec2, tag_name: str = INSTANCE_TAG) -> dict | None:
    """Find a running/pending instance with our Name tag."""
    r = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Name", "Values": [tag_name]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
        ]
    )
    for reservation in r["Reservations"]:
        for inst in reservation["Instances"]:
            return inst
    return None


def lookup_ubuntu_ami(region: str) -> str:
    """Look up the latest Ubuntu 22.04 AMI via SSM parameter."""
    ssm = boto3.client("ssm", region_name=region)
    resp = ssm.get_parameter(
        Name="/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-store/ami-id"
    )
    return resp["Parameter"]["Value"]


# ---------------------------------------------------------------------------
# Startup script (runs on the EC2 instance)
# ---------------------------------------------------------------------------

def build_startup_script(env: dict[str, str]) -> str:
    api_key = require(env, "ANTHROPIC_API_KEY")
    bucket = require(env, "S3_BUCKET")
    region = get_region(env)
    agent_args = env.get("DOCS_AGENT_ARGS", "")
    profile = env.get("AWS_IAM_INSTANCE_PROFILE", "")

    # If no instance profile, bake credentials into the script
    cred_lines = ""
    if not profile:
        ak = env.get("AWS_ACCESS_KEY_ID", "")
        sk = env.get("AWS_SECRET_ACCESS_KEY", "")
        if ak and sk:
            cred_lines = f"""\
export AWS_ACCESS_KEY_ID="{ak}"
export AWS_SECRET_ACCESS_KEY="{sk}"
export AWS_DEFAULT_REGION="{region}"
"""
        else:
            print("Warning: No AWS_IAM_INSTANCE_PROFILE and no AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY.")
            print("         The instance will rely on its default role (if any) for S3 access.")

    return f"""\
#!/bin/bash
exec > /var/log/docsagent.log 2>&1
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)

# AWS credentials for S3 access (empty if using instance profile)
{cred_lines}
export AWS_DEFAULT_REGION="{region}"

# Always upload logs and shut down, even on failure
cleanup() {{
    echo "=== Uploading logs $(date) ==="
    aws s3 cp /var/log/docsagent.log s3://{bucket}/results/$TIMESTAMP/runner.log || true
    echo "=== Shutting down instance ==="
    shutdown -h now
}}
trap cleanup EXIT

echo "=== docs-agent startup $(date) ==="

# Install Docker + AWS CLI
apt-get update -qq
apt-get install -y -qq docker.io containerd curl awscli
systemctl start docker
systemctl enable docker

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source /root/.local/bin/env

# Download the agent code from S3
mkdir -p /opt/docsagent
aws s3 cp s3://{bucket}/docsagent-code.tar.gz /opt/docsagent/code.tar.gz
cd /opt/docsagent
tar xzf code.tar.gz

# Install dependencies
cd /opt/docsagent/docs-agent
uv sync

# Run the agent
export ANTHROPIC_API_KEY="{api_key}"
echo "=== Starting docs-agent $(date) ==="
uv run docs-agent {agent_args} || true
echo "=== docs-agent finished $(date) ==="

# Upload results to S3
if [ -d reports ]; then
    aws s3 sync reports/ s3://{bucket}/results/$TIMESTAMP/reports/
    echo "Results uploaded to s3://{bucket}/results/$TIMESTAMP/"
fi
"""


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_launch(env: dict[str, str]) -> None:
    region = get_region(env)
    bucket = require(env, "S3_BUCKET")
    instance_type = env.get("AWS_INSTANCE_TYPE", "m5.xlarge")
    disk_size = int(env.get("AWS_DISK_SIZE", "50"))
    use_spot = env.get("AWS_SPOT", "true").lower() == "true"
    profile_name = env.get("AWS_IAM_INSTANCE_PROFILE", "")
    key_pair = env.get("AWS_KEY_PAIR", "")
    security_group = env.get("AWS_SECURITY_GROUP", "")
    subnet_id = env.get("AWS_SUBNET_ID", "")

    ec2 = boto3.client("ec2", region_name=region)
    s3 = boto3.client("s3", region_name=region)

    # Clean up any existing instance from a previous run
    existing = find_instance(ec2)
    if existing:
        iid = existing["InstanceId"]
        print(f"Terminating existing instance {iid}...")
        ec2.terminate_instances(InstanceIds=[iid])
        waiter = ec2.get_waiter("instance_terminated")
        waiter.wait(InstanceIds=[iid])

    # Package the docs-agent code
    print("\n1. Packaging docs-agent code...")
    tar_path = package_agent_code()

    # Upload to S3
    print(f"\n2. Uploading to s3://{bucket}/docsagent-code.tar.gz...")
    s3.upload_file(str(tar_path), bucket, "docsagent-code.tar.gz")
    tar_path.unlink()

    # Look up AMI
    print("\n3. Looking up Ubuntu 22.04 AMI...")
    ami_id = lookup_ubuntu_ami(region)
    print(f"   AMI: {ami_id}")

    # Build startup script
    print("\n4. Building startup script...")
    startup = build_startup_script(env)
    user_data = base64.b64encode(startup.encode()).decode()

    # Build run_instances kwargs
    print(f"\n5. Launching EC2 instance ({instance_type}, region={region}, spot={use_spot})...")
    kwargs: dict = {
        "ImageId": ami_id,
        "InstanceType": instance_type,
        "MinCount": 1,
        "MaxCount": 1,
        "UserData": user_data,
        "InstanceInitiatedShutdownBehavior": "terminate",
        "BlockDeviceMappings": [
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {
                    "VolumeSize": disk_size,
                    "VolumeType": "gp3",
                    "DeleteOnTermination": True,
                },
            }
        ],
        "TagSpecifications": [
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": INSTANCE_TAG}],
            }
        ],
    }

    if use_spot:
        kwargs["InstanceMarketOptions"] = {
            "MarketType": "spot",
            "SpotOptions": {
                "SpotInstanceType": "one-time",
                "InstanceInterruptionBehavior": "terminate",
            },
        }

    if profile_name:
        kwargs["IamInstanceProfile"] = {"Name": profile_name}

    if key_pair:
        kwargs["KeyName"] = key_pair

    if security_group:
        kwargs["SecurityGroupIds"] = [security_group]

    if subnet_id:
        kwargs["SubnetId"] = subnet_id

    resp = ec2.run_instances(**kwargs)
    instance_id = resp["Instances"][0]["InstanceId"]

    print(f"""
Done! Instance {instance_id} is launching and will:
  1. Install Docker + uv + AWS CLI
  2. Download code from s3://{bucket}/docsagent-code.tar.gz
  3. Run docs-agent
  4. Upload results to s3://{bucket}/results/<timestamp>/
  5. Shut itself down (auto-terminates)

Monitor:
  aws ec2 describe-instances --instance-ids {instance_id} --region {region}
  aws s3 ls s3://{bucket}/results/
{f"  ssh -i <key>.pem ubuntu@<public-ip> tail -f /var/log/docsagent.log" if key_pair else ""}
Download results when done:
  aws s3 sync s3://{bucket}/results/<timestamp>/ ./results/
""")


def cmd_wait(env: dict[str, str]) -> None:
    region = get_region(env)
    bucket = require(env, "S3_BUCKET")
    ec2 = boto3.client("ec2", region_name=region)
    s3 = boto3.client("s3", region_name=region)

    inst = find_instance(ec2)
    if not inst:
        print("No running instance found. It may have already terminated.")
    else:
        instance_id = inst["InstanceId"]
        print(f"Waiting for instance {instance_id} to finish...")
        while True:
            r = ec2.describe_instances(InstanceIds=[instance_id])
            state = r["Reservations"][0]["Instances"][0]["State"]["Name"]
            if state in ("terminated", "shutting-down"):
                print(f"Instance {state}. Checking results...")
                break
            print(f"  Instance state: {state} — waiting 30s...")
            time.sleep(30)

    # Find latest results in S3
    print(f"\nListing results in s3://{bucket}/results/...")
    try:
        paginator = s3.get_paginator("list_objects_v2")
        prefixes: set[str] = set()
        for page in paginator.paginate(Bucket=bucket, Prefix="results/", Delimiter="/"):
            for cp in page.get("CommonPrefixes", []):
                prefixes.add(cp["Prefix"])
    except ClientError as e:
        print(f"Error listing S3 results: {e}")
        return

    if not prefixes:
        print("No results found in S3 bucket.")
        return

    latest = sorted(prefixes)[-1]
    print(f"Latest results: s3://{bucket}/{latest}")

    # Download results
    local_dir = AGENT_ROOT / "reports" / "aws-latest"
    local_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading to {local_dir}...")

    for page in paginator.paginate(Bucket=bucket, Prefix=latest):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel = key[len(latest):]
            if not rel:
                continue
            dest = local_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(dest))

    print(f"\nResults downloaded to {local_dir}")


def cmd_cleanup(env: dict[str, str]) -> None:
    region = get_region(env)
    ec2 = boto3.client("ec2", region_name=region)

    inst = find_instance(ec2)
    if not inst:
        print("No running instance found.")
        return

    instance_id = inst["InstanceId"]
    print(f"Terminating instance {instance_id}...")
    ec2.terminate_instances(InstanceIds=[instance_id])
    print("Terminate request sent.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run docs-agent on an AWS EC2 spot instance")
    parser.add_argument("--wait", action="store_true", help="Poll until done, then download results")
    parser.add_argument("--cleanup", action="store_true", help="Terminate the instance if still running")
    parser.add_argument("--env", default=str(AGENT_ROOT / ".env"), help="Path to .env file")
    args = parser.parse_args()

    env = load_env(Path(args.env))

    if args.cleanup:
        cmd_cleanup(env)
    elif args.wait:
        cmd_launch(env)
        cmd_wait(env)
    else:
        cmd_launch(env)


if __name__ == "__main__":
    main()
