# Yakeroth Site Worldserver Build
# Builds a worldserver image with site-specific modules baked in.
# Usage:
#   docker build \
#     --build-arg AC_REPO=https://github.com/azerothcore/azerothcore-wotlk.git \
#     --build-arg AC_REF=master \
#     --build-arg SITE_MODULES_DIR=/site/modules \
#     --build-arg SITE_CMAKE_FILE=/site/ModulesSite.cmake \
#     --build-arg SITE_SQL_DIR=/site/sql \
#     --build-arg SITE_NAME=example \
#     --build-arg SITE_GIT_SHA=$(git -C /site rev-parse --short HEAD) \
#     --build-arg MODULES_LOCK_SHA=$(git -C /site rev-parse --short HEAD:modules.lock.yml) \
#     -t acore-example-worldserver:$(git -C /site rev-parse --short HEAD)-$(git -C /site rev-parse --short HEAD:modules.lock.yml) \
#     -f docker/Dockerfile \
#     --target worldserver \
#     .

# =============================================================================
# Stage 1: Fetch AzerothCore source
# =============================================================================
FROM alpine:3.20 AS acore-fetch

ARG AC_REPO=https://github.com/azerothcore/azerothcore-wotlk.git
ARG AC_REF=master

RUN apk add --no-cache git

WORKDIR /acore
RUN git clone --depth 1 --branch "${AC_REF}" "${AC_REPO}" . \
    && git rev-parse HEAD > /acore-git-sha.txt

# =============================================================================
# Stage 2: Build worldserver with site modules
# =============================================================================
FROM azerothcore/ac-builder:latest AS worldserver-builder

# Build args from site
ARG SITE_MODULES_DIR
ARG SITE_CMAKE_FILE
ARG SITE_SQL_DIR
ARG SITE_NAME
ARG SITE_GIT_SHA
ARG MODULES_LOCK_SHA
ARG DB_SCHEMA_VERSION=0

# Copy AzerothCore source
COPY --from=acore-fetch /acore /azerothcore

# Copy site modules and generated files
COPY ${SITE_MODULES_DIR} /azerothcore/modules/
COPY ${SITE_CMAKE_FILE} /azerothcore/ModulesSite.cmake
COPY ${SITE_SQL_DIR} /azerothcore/sql/custom/

# Build with site modules included
WORKDIR /azerothcore/build

RUN cmake \
    -DCMAKE_INSTALL_PREFIX=/azerothcore/install \
    -DSITE_MODULES_CMAKE=/azerothcore/ModulesSite.cmake \
    -DTOOLS=0 \
    -DSCRIPTS=1 \
    -DMODULES=1 \
    -DSERVERS=1 \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    /azerothcore \
    && make -j$(nproc) \
    && make install

# =============================================================================
# Stage 3: Runtime image
# =============================================================================
FROM debian:bookworm-slim AS worldserver

ARG SITE_NAME
ARG SITE_GIT_SHA
ARG MODULES_LOCK_SHA
ARG DB_SCHEMA_VERSION=0

LABEL org.azerothcore.site="${SITE_NAME}" \
      org.azerothcore.site-git-sha="${SITE_GIT_SHA}" \
      org.azerothcore.modules-lock-sha="${MODULES_LOCK_SHA}" \
      org.azerothcore.db-schema-version="${DB_SCHEMA_VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
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

RUN chown -R acore:acore /home/acore

USER acore
WORKDIR /home/acore

ENTRYPOINT ["./worldserver"]
CMD ["-c", "etc/worldserver.conf"]