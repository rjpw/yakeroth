"""Shared CLI utilities."""

import click
from datetime import datetime
from pathlib import Path
from typing import Optional

from yakeroth.models import (
    ImageTagsManifest,
    ImageTagEntry,
    ModuleSpec,
    ModulesFile,
    SiteConfig,
)
from yakeroth.git_utils import (
    GitError,
    clean_untracked,
    commit as git_commit,
    get_file_sha,
    get_repo,
    get_short_sha,
    get_status,
    log_oneline,
    reset_hard,
    tag as git_tag,
    ensure_clean_working_tree,
    stage_all,
)
from yakeroth.docker_utils import (
    DockerError,
    build_image,
    compose_down,
    compose_logs,
    compose_up,
    get_client,
    get_db_schema_version,
    get_image_digest,
    get_image_labels,
    mysqldump_all,
    mysql_restore_all,
    prune_images,
    push_image,
    pull_image,
)
from yakeroth.sync_modules import SyncError, sync as sync_modules, load_modules_yml
from yakeroth.dockerfile_template import DOCKERFILE_TEMPLATE
from yakeroth import TEMPLATES

from rich.console import Console
from rich.logging import RichHandler
import logging

console = Console()


def setup_logging(json_output: bool = False, verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    if json_output:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            handlers=[logging.StreamHandler()],
        )
    else:
        logging.basicConfig(
            level=level,
            format="%(message)s",
            handlers=[RichHandler(console=console, rich_tracebacks=True)],
        )


def get_site_dir(site: str, site_dir: Optional[str] = None) -> Path:
    """Resolve site directory path."""
    if site_dir:
        base = Path(site_dir).resolve()
        # If the provided path already ends with the site name, use it as-is
        if base.name == site:
            return base
        # Otherwise append the site name
        return base / site

    cwd = Path.cwd()
    # If we're already in a site directory (contains modules.yml and .git), use parent/sites
    if (cwd / "modules.yml").exists() and (cwd / ".git").exists():
        # We're likely in the site directory, check if parent has sites/
        parent_sites = cwd.parent / "sites" / site
        if parent_sites.exists():
            return parent_sites.resolve()

    return (cwd / "sites" / site).resolve()


def get_project_name(site: str) -> str:
    """Generate docker-compose project name."""
    return f"acore-{site}"


def load_config(config_path: Optional[str] = None) -> SiteConfig:
    """Load global config."""
    from pathlib import Path
    import yaml
    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return SiteConfig.model_validate(data)
    return SiteConfig()


def load_image_tags(site_dir: Path) -> ImageTagsManifest:
    """Load image tags manifest."""
    import yaml
    manifest_file = site_dir / "state" / "image-tags.yml"
    if not manifest_file.exists():
        return ImageTagsManifest(entries=[])

    with open(manifest_file) as f:
        data = yaml.safe_load(f) or {}
    return ImageTagsManifest.model_validate({"entries": data})


def save_image_tags(site_dir: Path, manifest: ImageTagsManifest) -> None:
    """Save image tags manifest."""
    import yaml
    manifest_file = site_dir / "state" / "image-tags.yml"
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    data = [entry.model_dump() for entry in manifest.entries]
    with open(manifest_file, "w") as f:
        yaml.dump(data, f, sort_keys=False, default_flow_style=False)


def get_acore_cache_dir() -> Path:
    """Get AC repo cache directory (~/.cache/yakeroth/acore/)."""
    cache_base = Path.home() / ".cache" / "yakeroth" / "acore"
    cache_base.mkdir(parents=True, exist_ok=True)
    return cache_base


def get_acore_cache_key(ac_repo: str) -> str:
    """Generate cache key from repo URL (hash)."""
    import hashlib
    return hashlib.sha256(ac_repo.encode()).hexdigest()[:16]


def get_acore_cached_repo(ac_repo: str) -> Path:
    """Get path to cached AC repo."""
    return get_acore_cache_dir() / get_acore_cache_key(ac_repo)


def ensure_acore_cached(ac_repo: str, ac_ref: str) -> tuple[Path, str]:
    """Ensure AC repo is cached at specific commit. Returns (repo_path, commit_sha)."""
    import subprocess
    cache_path = get_acore_cached_repo(ac_repo)
    
    # Resolve ref to commit SHA
    result = subprocess.run(
        ["git", "ls-remote", ac_repo, ac_ref],
        capture_output=True, text=True, check=True
    )
    commit_sha = result.stdout.split()[0]
    
    # Clone or update cache
    if cache_path.exists():
        # Fetch latest and checkout commit
        subprocess.run(["git", "-C", str(cache_path), "fetch", "origin"], check=True)
        subprocess.run(["git", "-C", str(cache_path), "checkout", commit_sha], check=True)
    else:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--branch", ac_ref, ac_repo, str(cache_path)], check=True)
        subprocess.run(["git", "-C", str(cache_path), "checkout", commit_sha], check=True)
    
    return cache_path, commit_sha