# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

ARG AKERNEL_NODE_BASE_IMAGE=ubuntu:24.04
ARG AKERNEL_RUNTIME_IMAGE=akernel-runtime:local
ARG AKERNEL_RUNTIME_PROFILE=rrt
ARG SANDBOXD_BUILD_IMAGE=golang:1.25.5-bookworm
ARG DISTILL_FS_BUILD_IMAGE=rust:1.85.0-bookworm
ARG OPEN_YR_VERSION=0.9.7
ARG OPEN_YR_CORE_WHEEL_URL=
ARG OPEN_YR_CORE_WHEEL_SHA256=
ARG OPEN_YR_RELEASE_BASE_URL=https://github.com/openYuanrong-mirror/yuanrong/releases/download
ARG OPEN_YR_CORE_AMD64_SHA256=0a890db1785e349bfd625844a05059bdd494e32a429cea771cf969f09e3aba2c
ARG OPEN_YR_CORE_ARM64_SHA256=64e14233fcbbb3418311d2f242e164e7be6e7bee0315c7619b18d9c5ddd01a76
ARG GVISOR_RELEASE=release-20260706.0
ARG GVISOR_AMD64_SHA512=73938c145ebe554cf61a01da455688f4b732eebdf7b1b635bdef5b195868b363d8cb400e3d92ed1f377b78996805556c247a4849583910cb04e92b156053033e
ARG GVISOR_RELEASE_BASE_URL=https://storage.googleapis.com/gvisor/releases
ARG LIBNVIDIA_CONTAINER_VERSION=1.19.1-1
ARG KATA_BUILD_IMAGE=ubuntu:24.04
ARG KATA_RELEASE=4.0.0
ARG KATA_AMD64_SHA256=2c3b9dfeba355582b40aee462b12916c9740654d0230f696adf719d67b063a8c
ARG KATA_RELEASE_BASE_URL=https://github.com/kata-containers/kata-containers/releases/download
ARG OTELCOL_CONTRIB_VERSION=0.120.0
ARG OTELCOL_CONTRIB_SHA256=81bf885bc9a86705feb3c113c5a356571390e3601eb651ffcf2b3428f6571adb
ARG OTELCOL_CONTRIB_URL=https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v${OTELCOL_CONTRIB_VERSION}/otelcol-contrib_${OTELCOL_CONTRIB_VERSION}_linux_amd64.tar.gz
ARG AKERNEL_VERSION=unknown
ARG AKERNEL_REVISION=unknown
ARG AKERNEL_INCLUDE_KATA=true
ARG AKERNEL_INCLUDE_NVIDIA=true

FROM ${KATA_BUILD_IMAGE} AS kata-runtime
ARG AKERNEL_INCLUDE_KATA
ARG KATA_RELEASE
ARG KATA_AMD64_SHA256
ARG KATA_RELEASE_BASE_URL
ARG TARGETARCH
RUN --mount=type=bind,from=akernel-download-cache,target=/var/cache/akernel-downloads,ro \
    set -eux; \
    case "${AKERNEL_INCLUDE_KATA}" in true|false) ;; *) exit 1 ;; esac; \
    mkdir -p /kata/opt/kata; \
    if [ "${AKERNEL_INCLUDE_KATA}" = "false" ]; then \
      exit 0; \
    fi; \
    test "${TARGETARCH:-amd64}" = "amd64"; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl zstd; \
    rm -rf /var/lib/apt/lists/*; \
    archive="/tmp/kata-static-${KATA_RELEASE}-amd64.tar.zst"; \
    cache_archive="/var/cache/akernel-downloads/kata/${KATA_RELEASE}/amd64/${KATA_AMD64_SHA256}/kata-static-${KATA_RELEASE}-amd64.tar.zst"; \
    if [ -f "${cache_archive}" ]; then \
      echo "kata-cache-hit ${cache_archive}"; \
      cp "${cache_archive}" "${archive}"; \
    else \
      curl -fSL --retry 10 --retry-delay 2 --retry-all-errors \
        "${KATA_RELEASE_BASE_URL}/${KATA_RELEASE}/kata-static-${KATA_RELEASE}-amd64.tar.zst" \
        -o "${archive}"; \
    fi; \
    echo "${KATA_AMD64_SHA256}  ${archive}" | sha256sum -c -; \
    mkdir -p /kata; \
    tar --zstd -xf "${archive}" -C /kata \
      ./opt/kata/runtime-rs/bin/containerd-shim-kata-v2 \
      ./opt/kata/share/defaults/kata-containers/runtime-rs/configuration-dragonball.toml \
      ./opt/kata/share/kata-containers/vmlinux-dragonball-experimental.container \
      ./opt/kata/share/kata-containers/vmlinux-6.18.35-200-dragonball-experimental \
      ./opt/kata/share/kata-containers/kata-containers.img \
      ./opt/kata/share/kata-containers/kata-ubuntu-noble.image; \
    ln -sfn configuration-dragonball.toml \
      /kata/opt/kata/share/defaults/kata-containers/runtime-rs/configuration.toml; \
    mkdir -p /kata/opt/kata/share/licenses/kata-containers; \
    curl -fSL --retry 10 --retry-delay 2 --retry-all-errors \
      "https://raw.githubusercontent.com/kata-containers/kata-containers/${KATA_RELEASE}/LICENSE" \
      -o /kata/opt/kata/share/licenses/kata-containers/LICENSE; \
    rm -f "${archive}"

FROM ${AKERNEL_RUNTIME_IMAGE} AS runtime-image

FROM ${SANDBOXD_BUILD_IMAGE} AS sandboxd-builder
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        gcc \
        git \
        libc6-dev \
        make && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /src/sandboxd
COPY ./src/sandboxd/ ./
RUN make release

FROM ${DISTILL_FS_BUILD_IMAGE} AS distill-fs-builder
ENV DEBIAN_FRONTEND=noninteractive \
    CARGO_NET_GIT_FETCH_WITH_CLI=true \
    CARGO_NET_RETRY=5
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        cmake \
        g++ \
        gcc \
        git \
        make \
        perl \
        pkg-config && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /src/distill-fs
COPY ./src/distill-fs/ ./
RUN set -eux; \
    for attempt in 1 2 3; do \
        if cargo build --locked --release --bin distill_fs; then \
            exit 0; \
        fi; \
        if [ "${attempt}" -eq 3 ]; then \
            exit 1; \
        fi; \
        rm -rf /usr/local/cargo/git/db/nydus-* \
            /usr/local/cargo/git/checkouts/nydus-*; \
        sleep "$((attempt * 2))"; \
    done

FROM ${AKERNEL_NODE_BASE_IMAGE}
ARG AKERNEL_RUNTIME_PROFILE
ARG AKERNEL_VERSION
ARG AKERNEL_REVISION
ARG AKERNEL_INCLUDE_KATA
ARG AKERNEL_INCLUDE_NVIDIA
ARG OPEN_YR_VERSION
ARG OPEN_YR_CORE_WHEEL_URL
ARG OPEN_YR_CORE_WHEEL_SHA256
ARG OPEN_YR_RELEASE_BASE_URL
ARG OPEN_YR_CORE_AMD64_SHA256
ARG OPEN_YR_CORE_ARM64_SHA256
ARG GVISOR_RELEASE
ARG GVISOR_AMD64_SHA512
ARG GVISOR_RELEASE_BASE_URL
ARG LIBNVIDIA_CONTAINER_VERSION
ARG OTELCOL_CONTRIB_VERSION
ARG OTELCOL_CONTRIB_SHA256
ARG OTELCOL_CONTRIB_URL
ARG TARGETARCH
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        e2fsprogs \
        fuse3 \
        gnupg \
        iproute2 \
        iptables \
        jq \
        kmod \
        libgcc-s1 \
        logrotate \
        mount \
        openssl \
        patch \
        procps \
        python3 \
        python3-pip \
        systemd \
        systemd-sysv \
        tzdata \
        xfsprogs && \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    case "${AKERNEL_INCLUDE_NVIDIA}" in true|false) ;; *) exit 1 ;; esac; \
    if [ "${AKERNEL_INCLUDE_NVIDIA}" = "false" ]; then \
      exit 0; \
    fi; \
    curl -fsSL --retry 10 --retry-delay 2 --retry-all-errors \
      https://nvidia.github.io/libnvidia-container/gpgkey \
      | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg; \
    curl -fsSL --retry 10 --retry-delay 2 --retry-all-errors \
      https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
      | sed \
        's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
      > /etc/apt/sources.list.d/nvidia-container-toolkit.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      "libnvidia-container1=${LIBNVIDIA_CONTAINER_VERSION}" \
      "libnvidia-container-tools=${LIBNVIDIA_CONTAINER_VERSION}"; \
    rm -rf /var/lib/apt/lists/*

RUN if command -v update-alternatives >/dev/null 2>&1; then \
        update-alternatives --set iptables /usr/sbin/iptables-legacy || true; \
        update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy || true; \
    fi

RUN --mount=type=bind,from=akernel-download-cache,target=/var/cache/akernel-downloads,ro \
    set -eux; \
    case "${TARGETARCH:-}" in \
        amd64) gvisor_arch="x86_64" ;; \
        "") \
            [ "$(uname -m)" = "x86_64" ] || { echo "unsupported gVisor target architecture: $(uname -m)" >&2; exit 1; }; \
            gvisor_arch="x86_64" ;; \
        *) echo "unsupported gVisor target architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    gvisor_version="${GVISOR_RELEASE#release-}"; \
    if [ "${gvisor_version}" = "${GVISOR_RELEASE}" ]; then \
        echo "GVISOR_RELEASE must be an official tag such as release-20260706.0" >&2; \
        exit 1; \
    fi; \
    gvisor_url="${GVISOR_RELEASE_BASE_URL}/release/${gvisor_version}/${gvisor_arch}"; \
    mkdir -p /tmp/gvisor-release; \
    cd /tmp/gvisor-release; \
    cache_runsc="/var/cache/akernel-downloads/gvisor/${GVISOR_RELEASE}/x86_64/${GVISOR_AMD64_SHA512}/runsc"; \
    if [ -f "${cache_runsc}" ]; then \
      echo "gvisor-cache-hit ${cache_runsc}"; \
      cp "${cache_runsc}" runsc; \
    else \
      curl -fSL --retry 10 --retry-delay 2 --retry-all-errors \
        "${gvisor_url}/runsc" -o runsc; \
    fi; \
    echo "${GVISOR_AMD64_SHA512}  runsc" | sha512sum -c -; \
    install -m 0755 runsc /usr/local/bin/runsc; \
    rm -rf /tmp/gvisor-release

RUN if command -v systemctl >/dev/null 2>&1; then \
        systemctl mask \
            dev-hugepages.mount \
            dev-mqueue.mount \
            getty@.service \
            systemd-logind.service \
            systemd-remount-fs.service \
            systemd-tmpfiles-setup-dev.service || true; \
    fi

ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone


ENV YR_INSTALLATION_DIR=/home/yuanrong

# Install the complete, language-runtime-free openYuanRong control plane from
# its checksum-pinned core wheel. A URL and checksum pair may override the
# release asset when validating an unreleased daily build.
COPY ./builder/downloaders/download-openyuanrong-core.sh /usr/local/bin/
RUN set -eux; \
    download_dir=/tmp/openyuanrong-core-download; \
    mkdir -p "${download_dir}"; \
    chmod 0755 /usr/local/bin/download-openyuanrong-core.sh; \
    /usr/local/bin/download-openyuanrong-core.sh "${download_dir}"; \
    set -- "${download_dir}"/*.whl; \
    test "$#" -eq 1; \
    wheel="$1"; \
    test -f "${wheel}"; \
    target=/tmp/openyuanrong-core; \
    python3 -m pip install \
      --break-system-packages \
      --no-cache-dir \
      --no-deps \
      --target "${target}" \
      "${wheel}"; \
    test -x "${target}/yr/functionsystem/bin/yr"; \
    mkdir -p "${YR_INSTALLATION_DIR}"; \
    cp -a "${target}/yr/." "${YR_INSTALLATION_DIR}/"; \
    rm -rf "${target}" "${download_dir}"; \
    rm -f /usr/local/bin/download-openyuanrong-core.sh; \
    ln -sfn "${YR_INSTALLATION_DIR}/functionsystem/bin/yr" /usr/bin/yr

COPY ./builder/patches/openyuanrong-core-6dfa49681774-pause-resume-process.patch /usr/local/patches/
COPY ./builder/patches/openyuanrong-core-454473b64447-pause-resume-process.patch /usr/local/patches/
COPY ./builder/patches/openyuanrong-core-obs-snapshot-process.patch /usr/local/patches/
COPY ./builder/scripts/apply-openyuanrong-pause-resume-patch.sh /usr/local/bin/
COPY ./builder/scripts/apply-openyuanrong-obs-snapshot-patch.sh /usr/local/bin/
RUN set -eux; \
    chmod 0755 /usr/local/bin/apply-openyuanrong-pause-resume-patch.sh \
      /usr/local/bin/apply-openyuanrong-obs-snapshot-patch.sh; \
    if [ -n "${OPEN_YR_CORE_WHEEL_SHA256}" ]; then \
      /usr/local/bin/apply-openyuanrong-pause-resume-patch.sh \
        "${YR_INSTALLATION_DIR}" "${OPEN_YR_CORE_WHEEL_SHA256}"; \
    fi

COPY --from=runtime-image /yr-runtime-rootfs.img ${YR_INSTALLATION_DIR}/yr-runtime-rootfs.img

COPY --from=sandboxd-builder /src/sandboxd/output/sandboxd /usr/local/bin/sandboxd
COPY --from=sandboxd-builder /src/sandboxd/output/sbox /usr/local/bin/sbox
COPY --from=sandboxd-builder /src/sandboxd/output/sandbox-logger /usr/local/bin/sandbox-logger
COPY --from=distill-fs-builder /src/distill-fs/target/release/distill_fs /usr/local/bin/distill_fs
COPY --from=kata-runtime /kata/opt/kata /opt/kata
RUN set -eux; \
    case "${AKERNEL_INCLUDE_KATA}" in true|false) ;; *) exit 1 ;; esac; \
    if [ "${AKERNEL_INCLUDE_KATA}" = "true" ]; then \
      ln -sf /opt/kata/runtime-rs/bin/containerd-shim-kata-v2 \
        /usr/local/bin/containerd-shim-kata-v2; \
    fi

COPY ./builder/scripts/akernel-entrypoint.sh /usr/local/bin/akernel-entrypoint
COPY ./builder/scripts/ensure-component-cert.sh /usr/local/bin/ensure-component-cert
COPY ./builder/scripts/sandboxd_network_prepare.sh /usr/local/bin/sandboxd-network-prepare
RUN chmod 0755 \
        /usr/local/bin/runsc \
        /usr/local/bin/sandboxd \
        /usr/local/bin/sbox \
        /usr/local/bin/sandbox-logger \
        /usr/local/bin/distill_fs \
        /usr/local/bin/akernel-entrypoint \
        /usr/local/bin/ensure-component-cert \
        /usr/local/bin/sandboxd-network-prepare && \
    if [ "${AKERNEL_INCLUDE_KATA}" = "true" ]; then \
        chmod 0755 /usr/local/bin/containerd-shim-kata-v2; \
    fi

COPY ./builder/config/yr_services.yaml /tmp/yr_services_rrt.yaml
COPY ./builder/config/yr_services_python.yaml /tmp/yr_services_python.yaml
RUN set -eux; \
    case "${AKERNEL_RUNTIME_PROFILE}" in \
      rrt) services=/tmp/yr_services_rrt.yaml ;; \
      python) services=/tmp/yr_services_python.yaml ;; \
      *) echo "unsupported AKERNEL_RUNTIME_PROFILE: ${AKERNEL_RUNTIME_PROFILE}" >&2; exit 1 ;; \
    esac; \
    touch ${YR_INSTALLATION_DIR}/.akernel-rrt-capable; \
    install -D -m 0644 "${services}" ${YR_INSTALLATION_DIR}/deploy/process/services.yaml; \
    rm -f /tmp/yr_services_rrt.yaml /tmp/yr_services_python.yaml

RUN mkdir -p ${YR_INSTALLATION_DIR}/metrics ${YR_INSTALLATION_DIR}/trace
COPY ./builder/config/otel-collector-config.yaml ${YR_INSTALLATION_DIR}/otel_config.yaml
COPY ./builder/config/metrics_config.json ${YR_INSTALLATION_DIR}/metrics/metrics_config.json
COPY ./builder/config/trace_config.json ${YR_INSTALLATION_DIR}/trace/trace_config.json
COPY ./builder/config/logrotate.d/gvisor /etc/logrotate.d/gvisor
COPY ./builder/scripts/yr_node_bootstrap.sh ${YR_INSTALLATION_DIR}/yr_node_bootstrap.sh
COPY ./builder/scripts/master_entrypoint.sh ${YR_INSTALLATION_DIR}/entrypoint.sh
COPY ./builder/scripts/*.sh /root/
COPY ./builder/systemd_services/*.service /etc/systemd/system/

RUN --mount=type=bind,from=akernel-download-cache,target=/var/cache/akernel-downloads,ro \
    set -eux; \
    archive="/tmp/otelcol-contrib_${OTELCOL_CONTRIB_VERSION}_linux_amd64.tar.gz"; \
    cache_archive="/var/cache/akernel-downloads/otelcol-contrib/${OTELCOL_CONTRIB_VERSION}/linux-amd64/${OTELCOL_CONTRIB_SHA256}/otelcol-contrib_${OTELCOL_CONTRIB_VERSION}_linux_amd64.tar.gz"; \
    if [ -f "${cache_archive}" ]; then \
      echo "otelcol-cache-hit ${cache_archive}"; \
      cp "${cache_archive}" "${archive}"; \
    else \
      curl -fSL --retry 10 --retry-delay 2 --retry-all-errors \
        "${OTELCOL_CONTRIB_URL}" -o "${archive}"; \
    fi; \
    echo "${OTELCOL_CONTRIB_SHA256}  ${archive}" | sha256sum -c -; \
    tar -xzf "${archive}" -C /usr/local/bin otelcol-contrib; \
    chmod 0755 /usr/local/bin/otelcol-contrib; \
    rm -f "${archive}"

RUN mkdir -p ${YR_INSTALLATION_DIR}/logs ${YR_INSTALLATION_DIR}/metrics ${YR_INSTALLATION_DIR}/trace && \
    chmod 0755 ${YR_INSTALLATION_DIR}/yr_node_bootstrap.sh ${YR_INSTALLATION_DIR}/entrypoint.sh && \
    chmod 0644 /etc/logrotate.d/gvisor && \
    systemctl mask getty-static.service || true && \
    systemctl enable logrotate.timer && \
    systemctl enable otel_collector.service && \
    systemctl enable sandboxd.service && \
    systemctl enable yuanrong.service

LABEL org.opencontainers.image.version="${AKERNEL_VERSION}" \
      org.opencontainers.image.revision="${AKERNEL_REVISION}" \
      org.akernel.runtime.profile="${AKERNEL_RUNTIME_PROFILE}"

ENV YR_LOG_PATH=${YR_INSTALLATION_DIR}/logs
STOPSIGNAL SIGRTMIN+3
