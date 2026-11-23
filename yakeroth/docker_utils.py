"""Docker utilities for yakeroth."""

import os
import subprocess
from pathlib import Path
from typing import Optional

import docker
from docker.errors import DockerException, ImageNotFound, NotFound

from .models import ImageTagEntry, ImageTagsManifest


class DockerError(Exception):
    """Docker operation failed."""
    pass


def get_client() -> docker.DockerClient:
    """Get Docker client from environment."""
    try:
        return docker.from_env()
    except DockerException as e:
        raise DockerError(f"Cannot connect to Docker daemon: {e}") from e


def build_image(
    client: docker.DockerClient,
    path: Path,
    dockerfile: Path,
    tag: str,
    build_args: dict[str, str],
    labels: dict[str, str],
    no_cache: bool = False,
    stream_output: bool = False,
    log_tail: int = 50,
) -> tuple[str, str, list[str]]:
    """Build Docker image and return (image_id, digest, log_tail_lines)."""
    from collections import deque
    try:
        image, logs = client.images.build(
            path=str(path),
            dockerfile=str(dockerfile),
            tag=tag,
            buildargs=build_args,
            labels=labels,
            nocache=no_cache,
            rm=True,
            forcerm=True,
            decode=True,
        )
        tail = deque(maxlen=log_tail)
        for chunk in logs:
            if "stream" in chunk:
                line = chunk["stream"].rstrip()
                tail.append(line)
                if stream_output:
                    from rich.console import Console
                    Console().print(f"[dim]{line}[/dim]")
            elif "errorDetail" in chunk:
                raise DockerError(f"Build failed: {chunk['errorDetail'].get('message', 'Unknown error')}")
        digest = image.attrs.get("RepoDigests", [image.id])[0]
        return image.id, digest, list(tail)
    except DockerException as e:
        raise DockerError(f"Build failed: {e}") from e


def get_image_digest(client: docker.DockerClient, tag: str) -> str:
    """Get image digest by tag."""
    try:
        image = client.images.get(tag)
        digests = image.attrs.get("RepoDigests", [])
        if digests:
            return digests[0]
        return image.id
    except ImageNotFound:
        raise DockerError(f"Image not found: {tag}")


def get_image_labels(client: docker.DockerClient, tag: str) -> dict[str, str]:
    """Get image labels."""
    try:
        image = client.images.get(tag)
        return image.attrs.get("Config", {}).get("Labels", {})
    except ImageNotFound:
        raise DockerError(f"Image not found: {tag}")


def push_image(client: docker.DockerClient, tag: str, registry: str | None = None) -> str:
    """Push image to registry."""
    if registry:
        # Tag for registry
        registry_tag = f"{registry}/{tag}"
        client.images.get(tag).tag(registry_tag)
        tag = registry_tag

    try:
        for line in client.api.push(tag, stream=True, decode=True):
            if "error" in line:
                raise DockerError(f"Push failed: {line['error']}")
        return tag
    except DockerException as e:
        raise DockerError(f"Push failed: {e}") from e


def pull_image(client: docker.DockerClient, tag: str, registry: str | None = None) -> str:
    """Pull image from registry."""
    if registry:
        tag = f"{registry}/{tag}"

    try:
        client.images.pull(tag)
        return tag
    except DockerException as e:
        raise DockerError(f"Pull failed: {e}") from e


def prune_images(
    client: docker.DockerClient,
    site_name: str,
    keep: int = 5,
    dry_run: bool = False,
) -> list[str]:
    """Prune old site images per retention policy."""
    filters = {"label": f"org.azerothcore.site={site_name}"}
    images = client.images.list(filters=filters)

    # Sort by creation date (newest first)
    images.sort(key=lambda img: img.attrs.get("Created", ""), reverse=True)

    # Keep milestone-tagged images and last N builds
    to_remove = []
    milestone_prefixes = ("running-", "pre-build-")

    for i, img in enumerate(images):
        tags = img.tags
        is_milestone = any(
            any(p in tag for p in milestone_prefixes) for tag in tags
        )
        if i >= keep and not is_milestone:
            to_remove.append(img.id)

    if dry_run:
        return [img.id for img in to_remove]

    removed = []
    for img_id in to_remove:
        try:
            client.images.remove(img_id, force=True)
            removed.append(img_id)
        except DockerException:
            pass  # Ignore removal errors

    return removed


def compose_up(site_dir: Path, project_name: str, force: bool = False) -> subprocess.CompletedProcess:
    """Run docker compose up -d."""
    cmd = ["docker", "compose", "-p", project_name, "up", "-d"]
    if force:
        cmd.append("--force-recreate")
    return subprocess.run(cmd, cwd=site_dir, capture_output=True, text=True)


def compose_down(site_dir: Path, project_name: str) -> subprocess.CompletedProcess:
    """Run docker compose down."""
    cmd = ["docker", "compose", "-p", project_name, "down"]
    return subprocess.run(cmd, cwd=site_dir, capture_output=True, text=True)


def compose_logs(site_dir: Path, project_name: str, follow: bool = True) -> subprocess.CompletedProcess:
    """Run docker compose logs."""
    cmd = ["docker", "compose", "-p", project_name, "logs"]
    if follow:
        cmd.append("-f")
    return subprocess.run(cmd, cwd=site_dir, capture_output=True, text=True)


def compose_exec(site_dir: Path, project_name: str, service: str, command: list[str]) -> subprocess.CompletedProcess:
    """Run docker compose exec."""
    cmd = ["docker", "compose", "-p", project_name, "exec", "-T", service, *command]
    return subprocess.run(cmd, cwd=site_dir, capture_output=True, text=True)


def get_db_schema_version(site_dir: Path, project_name: str) -> int:
    """Query db_version table from world database."""
    result = compose_exec(
        site_dir, project_name, "worldserver",
        ["mysql", "-h", "db", "-u", "acore", "-pacore", "acore_world", "-e", "SELECT version FROM db_version ORDER BY version DESC LIMIT 1;"]
    )
    if result.returncode != 0:
        raise DockerError(f"Failed to query db_version: {result.stderr}")

    # Parse output: version\n12345\n
    lines = result.stdout.strip().split("\n")
    for line in lines:
        if line.isdigit():
            return int(line)
    raise DockerError(f"Could not parse db_version from: {result.stdout}")


def mysqldump_all(site_dir: Path, project_name: str, output_dir: Path, prefix: str) -> list[Path]:
    """Dump all three databases to gzipped SQL files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    dbs = ["acore_auth", "acore_characters", "acore_world"]
    backup_files = []

    for db in dbs:
        outfile = output_dir / f"{prefix}-{db}.sql.gz"
        cmd = [
            "docker", "compose", "-p", project_name, "exec", "-T", "db",
            "mysqldump", "-u", "root", "-proot", db
        ]
        with open(outfile, "wb") as f:
            proc = subprocess.run(cmd, cwd=site_dir, stdout=subprocess.PIPE)
            import gzip
            f.write(gzip.compress(proc.stdout))
        backup_files.append(outfile)

    return backup_files


def mysql_restore_all(site_dir: Path, project_name: str, backup_dir: Path, prefix: str) -> None:
    """Restore all three databases from gzipped SQL files."""
    # Stop worldserver and authserver first
    compose_exec(site_dir, project_name, "worldserver", ["pkill", "-f", "worldserver"])
    compose_exec(site_dir, project_name, "authserver", ["pkill", "-f", "authserver"])

    dbs = ["acore_auth", "acore_characters", "acore_world"]
    for db in dbs:
        backup_file = backup_dir / f"{prefix}-{db}.sql.gz"
        if not backup_file.exists():
            raise DockerError(f"Backup file not found: {backup_file}")

        # Drop and recreate database
        drop_cmd = [
            "docker", "compose", "-p", project_name, "exec", "-T", "db",
            "mysql", "-u", "root", "-proot", "-e", f"DROP DATABASE IF EXISTS {db}; CREATE DATABASE {db};"
        ]
        subprocess.run(drop_cmd, cwd=site_dir, check=True)

        # Restore
        restore_cmd = [
            "docker", "compose", "-p", project_name, "exec", "-T", "db",
            "bash", "-c", f"gunzip -c | mysql -u root -proot {db}"
        ]
        with open(backup_file, "rb") as f:
            subprocess.run(restore_cmd, cwd=site_dir, stdin=f, check=True)

    # Restart containers
    compose_up(site_dir, project_name, force=True)