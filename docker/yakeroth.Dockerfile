# Yakeroth Sidecar Container
# Runs yakeroth CLI inside a container with Docker socket access for CI/automation.
# Usage:
#   docker run --rm \
#     -v /var/run/docker.sock:/var/run/docker.sock \
#     -v /path/to/sites/example:/site \
#     --user $(id -u):$(id -g) \
#     -e GIT_AUTHOR_NAME \
#     -e GIT_AUTHOR_EMAIL \
#     ghcr.io/rjpw/yakeroth:latest \
#     sync example

FROM python:3.12-slim

# Install git and docker CLI (for docker SDK to work)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Configure git safe directory for mounted volumes
RUN git config --global --add safe.directory /site

WORKDIR /app

# Install yakeroth package
COPY pyproject.toml /app/
COPY yakeroth/ /app/yakeroth/
RUN pip install --no-cache-dir -e .

# Entry point
ENTRYPOINT ["yakeroth"]
CMD ["--help"]