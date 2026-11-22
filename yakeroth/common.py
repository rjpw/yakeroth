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

console = None  # Will be initialized in cli.py


def setup_logging(json_output: bool = False, verbose: bool = False) -> None:
    """Configure logging."""
    import logging
    from rich.logging import RichHandler
    from rich.console import Console

    global console
    level = logging.DEBUG if verbose else logging.INFO
    if json_output:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            handlers=[logging.StreamHandler()],
        )
        console = Console()
    else:
        logging.basicConfig(
            level=level,
            format="%(message)s",
            handlers=[RichHandler(console=Console(), rich_tracebacks=True)],
        )
        console = Console()


def get_site_dir(site: str, site_dir: Optional[str] = None) -> Path:
    """Resolve site directory path."""
    if site_dir:
        return Path(site_dir).resolve()

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