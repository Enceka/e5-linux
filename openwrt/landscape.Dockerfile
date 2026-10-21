# Build environment for Landscape's static aarch64 daemon (build-landscape.sh).
#
# arm64, the device's own architecture.  The build is upstream's own
# scripts/build_musl_static.sh, which is what produced the release artifacts:
# cargo-zigbuild with a sysroot assembled from Alpine's musl libelf/zlib/zstd,
# because zig bundles a libc but not libelf.  The glibc libraries of this image
# are only for the host side of libbpf-sys; the target links musl out of the
# sysroot.
#
# The toolchain is 1.98.0 to match the rust-toolchain.toml of the pinned
# commit.  A mismatched image toolchain makes rustup fetch 1.98.0 without the
# musl target, and the build then dies with "can't find crate for `core`".
FROM --platform=linux/arm64 rust:1.98.0-bookworm

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        clang llvm libelf-dev pkg-config zlib1g-dev libzstd-dev linux-libc-dev \
        file git ca-certificates wget binutils python3 python3-pip cmake \
 && rm -rf /var/lib/apt/lists/*

# zig cc is the cross linker cargo-zigbuild drives; the pip package is the
# same compiler upstream's script documents (pip3 install ziglang==0.16.0).
RUN pip3 install --break-system-packages --no-cache-dir ziglang==0.16.0

RUN export PATH=/usr/local/cargo/bin:$PATH CARGO_TARGET_DIR=/tmp/cargo-install \
 && cargo install --locked cargo-zigbuild \
 && rm -rf /tmp/cargo-install

# The pinned commit's rust-toolchain.toml selects 1.98.0, so the target must be
# added to that toolchain and not to the image's default.
RUN export PATH=/usr/local/cargo/bin:$PATH \
 && rustup toolchain install 1.98.0 --profile minimal \
 && rustup target add --toolchain 1.98.0 aarch64-unknown-linux-musl

ENV CARGO_TERM_COLOR=never \
    CARGO_NET_RETRY=5
WORKDIR /src
