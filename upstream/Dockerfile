# Native arm64 build environment for the E5's mainline kernel (linux-lts-e5), gcc from Ubuntu 26.04
# (mu300-linux/upstream/Dockerfile, plus git and dtc).  The kernel repository is bind-mounted from the
# host, owned by another uid: git has to trust it, or setlocalversion loses the -g<commit> suffix.
FROM ubuntu:26.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential bc bison flex libssl-dev libelf-dev lz4 cpio kmod python3 curl device-tree-compiler xz-utils \
    ca-certificates git \
 && rm -rf /var/lib/apt/lists/* \
 && git config --system --add safe.directory '*'
