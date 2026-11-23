# Dockerfile template for yakeroth site builds
DOCKERFILE_TEMPLATE = r"""# Yakeroth Site Worldserver Build
# Builds a worldserver image with site-specific modules baked in.
# Usage:
#   docker build \
#     --build-arg AC_REPO=https://github.com/azerothcore/azerothcore-wotlk.git \
#     --build-arg AC_REF=master \
#     --build-arg SITE_MODULES_DIR=modules \
#     --build-arg SITE_CMAKE_FILE=ModulesSite.cmake \
#     --build-arg SITE_SQL_DIR=sql \
#     --build-arg SITE_NAME=example \
#     --build-arg SITE_GIT_SHA=$(git -C /site rev-parse --short HEAD) \
#     --build-arg MODULES_LOCK_SHA=$(git -C /site rev-parse --short HEAD:modules.lock.yml) \
#     -t acore-example-worldserver:$(git -C /site rev-parse --short HEAD)-$(git -C /site rev-parse --short HEAD:modules.lock.yml) \
#     -f Dockerfile \
#     --target worldserver \
#     .
#
# NOTE: If build fails, try pinning AC_REF to a known-good tag:
#   --build-arg AC_REF=v1.0.0
#   or a specific commit SHA

# =============================================================================
# Stage 1: Fetch AzerothCore source
# =============================================================================
FROM alpine:3.20 AS acore-fetch

ARG AC_REPO=https://github.com/azerothcore/azerothcore-wotlk.git
ARG AC_REF=master
ARG AC_COMMIT
WORKDIR /acore

# AC repo is COPY'd from build context at /acore-source
# Note: .git directory is removed in build context to avoid submodule issues;
# commit verification is done on host during cache fetch (ensure_acore_cached)
COPY acore-source/ /acore/

# =============================================================================
# Stage 2: Build worldserver with site modules (public builder)
# =============================================================================
FROM ubuntu:22.04 AS worldserver-builder

# Build args from site
ARG SITE_MODULES_DIR
ARG SITE_CMAKE_FILE
ARG SITE_SQL_DIR
ARG SITE_NAME
ARG SITE_GIT_SHA
ARG MODULES_LOCK_SHA
ARG DB_SCHEMA_VERSION=0

# Install build dependencies
# NOTE: AzerothCore master may require additional dependencies.
# If build fails, consider pinning AC_REF to a known-good tag (e.g., v1.0.0).
RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake \
    gcc \
    g++ \
    make \
    git \
    libssl-dev \
    libmysqlclient-dev \
    libboost-system-dev \
    libboost-filesystem-dev \
    libboost-thread-dev \
    libboost-program-options-dev \
    libboost-regex-dev \
    libboost-iostreams-dev \
    libboost-atomic-dev \
    libboost-chrono-dev \
    libboost-date-time-dev \
    libreadline-dev \
    libace-dev \
    libgmp-dev \
    libfmt-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy AzerothCore source
COPY --from=acore-fetch /acore /azerothcore

# Copy site modules and generated files
COPY ${SITE_MODULES_DIR} /azerothcore/modules/
COPY ${SITE_CMAKE_FILE} /azerothcore/ModulesSite.cmake
COPY ${SITE_SQL_DIR} /azerothcore/sql/custom/

# Build with site modules included
WORKDIR /azerothcore/build

RUN set -euxo pipefail; \
    cmake \
    -DCMAKE_INSTALL_PREFIX=/azerothcore/install \
    -DSITE_MODULES_CMAKE=/azerothcore/ModulesSite.cmake \
    -DTOOLS=none \
    -DSCRIPTS=static \
    -DMODULES=static \
    -DSERVERS=static \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    -DCMAKE_POLICY_DEFAULT_CMP0148=OLD \
    /azerothcore \
    2>&1 | tee /azerothcore/cmake.log; \
    make -j$(nproc) 2>&1 | tee /azerothcore/build.log; \
    make install 2>&1 | tee /azerothcore/install.log; \
    ls -la /azerothcore/install/; \
    mkdir -p /azerothcore/install/share

# =============================================================================
# Stage 3: Runtime image
# =============================================================================
FROM ubuntu:22.04 AS worldserver

ARG SITE_NAME
ARG SITE_GIT_SHA
ARG MODULES_LOCK_SHA
ARG DB_SCHEMA_VERSION=0

LABEL org.azerothcore.site="${SITE_NAME}" \
      org.azerothcore.site-git-sha="${SITE_GIT_SHA}" \
      org.azerothcore.modules-lock-sha="${MODULES_LOCK_SHA}" \
      org.azerothcore.db-schema-version="${DB_SCHEMA_VERSION}" \
      org.opencontainers.image.source="https://github.com/rjpw/yakeroth" \
      org.opencontainers.image.title="AzerothCore Worldserver (${SITE_NAME})" \
      org.opencontainers.image.description="Yakeroth-managed site build"

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 \
    libmysqlclient21 \
    libboost-system1.74 \
    libboost-filesystem1.74 \
    libboost-thread1.74 \
    libboost-program-options1.74 \
    libboost-regex1.74 \
    libboost-iostreams1.74 \
    libboost-atomic1.74 \
    libboost-chrono1.74 \
    libboost-date-time1.74 \
    libreadline8 \
    libace-7.0.6 \
    libgmp10 \
    libfmt8 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create acore user
RUN groupadd -r acore && useradd -r -g acore -d /home/acore -s /bin/bash acore

# Copy built binaries and configs
COPY --from=worldserver-builder /azerothcore/install/bin/worldserver /home/acore/worldserver
COPY --from=worldserver-builder /azerothcore/install/etc /home/acore/etc
COPY --from=worldserver-builder /azerothcore/install/share /home/acore/share
# Copy SQL files for db-import container
COPY --from=worldserver-builder /azerothcore/sql /home/acore/sql

# Copy build logs for debugging
COPY --from=worldserver-builder /azerothcore/cmake.log /home/acore/logs/cmake.log
COPY --from=worldserver-builder /azerothcore/build.log /home/acore/logs/build.log
COPY --from=worldserver-builder /azerothcore/install.log /home/acore/logs/install.log

RUN chown -R acore:acore /home/acore

USER acore
WORKDIR /home/acore

ENTRYPOINT ["./worldserver"]
CMD ["-c", "etc/worldserver.conf"]
"""