# Use an official Python image as the base
FROM python:3.12-slim

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PROJ_VERSION=9.6.2

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    curl \
    git \
    libsqlite3-dev \
    sqlite3 \
    libtiff-dev \
    libcurl4-openssl-dev \
    libboost-dev \
    libboost-system-dev \
    libboost-thread-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install PROJ from source
RUN curl -L https://download.osgeo.org/proj/proj-${PROJ_VERSION}.tar.gz | tar xz && \
    cd proj-${PROJ_VERSION} && \
    mkdir build && cd build && \
    cmake .. && \
    make -j$(nproc) && \
    make install && \
    ldconfig && \
    cd ../.. && rm -rf proj-${PROJ_VERSION}

# Set up a non-root user
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=1000
RUN groupadd --gid $USER_GID $USERNAME && \
    useradd --uid $USER_UID --gid $USER_GID -m $USERNAME && \
    chown -R $USERNAME:$USERNAME /home/$USERNAME

# Switch to the non-root user
USER $USERNAME

# Set the working directory
WORKDIR /workspaces/pyproj