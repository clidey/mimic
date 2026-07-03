FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install base packages (firefox excluded — installed from Mozilla PPA below)
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    fluxbox \
    xdotool \
    scrot \
    x11-utils \
    curl \
    ca-certificates \
    python3 \
    dbus-x11 \
    software-properties-common \
    gnupg \
    iptables \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Firefox from Mozilla PPA (snap version doesn't work in Docker)
RUN add-apt-repository -y ppa:mozillateam/ppa \
    && printf 'Package: *\nPin: release o=LP-PPA-mozillateam\nPin-Priority: 1001\n' \
       > /etc/apt/preferences.d/mozilla-firefox \
    && apt-get update \
    && apt-get install -y --no-install-recommends firefox \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CE (full daemon + CLI for Docker-in-Docker)
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] \
       https://download.docker.com/linux/ubuntu jammy stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io \
    && rm -rf /var/lib/apt/lists/*

# Suppress fluxbox wallpaper warning
RUN mkdir -p /root/.fluxbox && printf '[startup]\n' > /root/.fluxbox/startup

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV DISPLAY=:1

ENTRYPOINT ["/entrypoint.sh"]
