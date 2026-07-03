"""Unified cloud runner — launch mimic on GCP or AWS.

Usage:
    mimic-cloud --cloud gcp --provider anthropic
    mimic-cloud --cloud aws --provider openai --wait
    mimic-cloud --cloud gcp --cleanup
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mimic.runner_utils import AGENT_ROOT, load_env


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mimic-cloud",
        description="Run mimic on a cloud spot instance (GCP or AWS)",
    )
    parser.add_argument("--cloud", required=True, choices=["gcp", "aws"], help="Cloud provider to launch on")
    parser.add_argument(
        "--provider", choices=["anthropic", "openai"], help="LLM provider (overrides AGENT_PROVIDER in .env)"
    )
    parser.add_argument("--wait", action="store_true", help="Poll until done, then download results")
    parser.add_argument("--cleanup", action="store_true", help="Terminate the instance if still running")
    parser.add_argument("--env", default=str(AGENT_ROOT / ".env"), help="Path to .env file")
    args = parser.parse_args()

    env = load_env(Path(args.env))
    if args.provider:
        env["AGENT_PROVIDER"] = args.provider

    if args.cloud == "gcp":
        from mimic.gcp import cmd_cleanup, cmd_launch, cmd_wait

        if args.cleanup:
            cmd_cleanup(env)
        elif args.wait:
            cmd_launch(env)
            cmd_wait(env)
        else:
            cmd_launch(env)

    elif args.cloud == "aws":
        from mimic.aws import cmd_cleanup, cmd_launch, cmd_wait

        if args.cleanup:
            cmd_cleanup(env)
        elif args.wait:
            cmd_launch(env)
            cmd_wait(env)
        else:
            cmd_launch(env)


if __name__ == "__main__":
    main()
