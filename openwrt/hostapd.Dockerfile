FROM debian:trixie
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential ca-certificates clang curl file flex bison gawk gettext git \
    libncurses-dev libssl-dev patch pkg-config python3 python3-setuptools rsync \
    swig unzip wget xz-utils zlib1g-dev zstd util-linux \
    && rm -rf /var/lib/apt/lists/*
