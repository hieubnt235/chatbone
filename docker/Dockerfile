# Use Ubuntu 22.04 as the base image
FROM mcr.microsoft.com/devcontainers/base:ubuntu-22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive

# Create a non-root user 'worker' with UID 1000
RUN useradd -m -u 1000 -s /bin/bash worker && \
    echo "worker ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Install necessary dependencies
RUN apt update && apt install -y \
    build-essential \
    cmake \
    ninja-build \
    g++ \
    clang \
    lldb \
    lcov \
    valgrind \
    gdb \
    pkg-config \
    libssl-dev \
    libsodium-dev \
    libgcrypt-dev \
    libcryptsetup-dev \
    cryptsetup \
    dmsetup \
    binutils \
    nasm \
    yasm \
    git \
    curl \
    wget \
    vim \
    neofetch \
    zsh \
    && rm -rf /var/lib/apt/lists/*

# Install Visual Studio Code Server
RUN curl -fsSL https://code-server.dev/install.sh | sh

# Set zsh as the default shell
RUN chsh -s /bin/zsh worker

# Set work directory
WORKDIR /home/worker

# Switch to 'worker' user
USER worker

# Install additional tools for development
RUN curl -fsSL https://get.docker.com | sh && \
    sudo apt install -y docker-compose

# Expose port for Visual Studio Code Server
EXPOSE 8080

# Set default command to launch code-server
CMD ["code-server", "--bind-addr", "0.0.0.0:8080", "/home/worker"]
