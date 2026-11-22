"""Yakeroth CLI - AzerothCore server composition manager."""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
import yaml
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .models import (
    ImageTagsManifest,
    ImageTagEntry,
    ModuleSpec,
    ModulesFile,
    SiteConfig,
)
from .git_utils import (
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
from .docker_utils import (
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
from .sync_modules import SyncError, sync as sync_modules, load_modules_yml

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
        return Path(site_dir).resolve()
    return Path.cwd() / "sites" / site


def get_project_name(site: str) -> str:
    """Generate docker-compose project name."""
    return f"acore-{site}"


def load_config(config_path: Optional[str] = None) -> SiteConfig:
    """Load global config."""
    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return SiteConfig.model_validate(data)
    return SiteConfig()


def load_image_tags(site_dir: Path) -> ImageTagsManifest:
    """Load image tags manifest."""
    manifest_file = site_dir / "state" / "image-tags.yml"
    if not manifest_file.exists():
        return ImageTagsManifest(entries=[])

    with open(manifest_file) as f:
        data = yaml.safe_load(f) or {}
    return ImageTagsManifest.model_validate({"entries": data})


def save_image_tags(site_dir: Path, manifest: ImageTagsManifest) -> None:
    """Save image tags manifest."""
    manifest_file = site_dir / "state" / "image-tags.yml"
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    data = [entry.model_dump() for entry in manifest.entries]
    with open(manifest_file, "w") as f:
        yaml.dump(data, f, sort_keys=False, default_flow_style=False)


@click.group()
@click.option("--site-dir", envvar="YAKEROTH_SITE_DIR", help="Site directory (default: ./sites/<site>)")
@click.option("--config", envvar="YAKEROTH_CONFIG", help="Global config file")
@click.option("--json", "json_output", is_flag=True, help="JSON output")
@click.option("-v", "--verbose", is_flag=True, help="Verbose output")
@click.pass_context
def cli(
    ctx: click.Context,
    site_dir: Optional[str],
    config: Optional[str],
    json_output: bool,
    verbose: bool,
):
    """Yakeroth - AzerothCore server composition manager."""
    setup_logging(json_output, verbose)
    ctx.ensure_object(dict)
    ctx.obj["site_dir"] = site_dir
    ctx.obj["config_path"] = config
    ctx.obj["json"] = json_output
    ctx.obj["config"] = load_config(config)


@cli.command()
@click.argument("site")
@click.option("--force", is_flag=True, help="Overwrite existing site")
@click.pass_context
def init(ctx: click.Context, site: str, force: bool):
    """Initialize a new site directory with templates."""
    import jinja2

    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    if site_dir.exists() and not force:
        raise click.ClickException(f"Site directory exists: {site_dir}. Use --force to overwrite.")

    site_dir.mkdir(parents=True, exist_ok=True)

    # Initialize git repo
    repo = get_repo(site_dir) if (site_dir / ".git").exists() else None
    if not repo:
        from git import Repo
        repo = Repo.init(site_dir)
        # Initial commit
        (site_dir / "README.md").write_text(f"# Site: {site}\n\nManaged by yakeroth.\n")
        stage_all(repo)
        git_commit(repo, f"site: init {site}")

    # Render templates
    import importlib.resources
    templates = {
        "modules.yml.j2": site_dir / "modules.yml",
        "docker-compose.override.yml.j2": site_dir / "docker-compose.override.yml",
        ".gitignore.j2": site_dir / ".gitignore",
        "env/.env.j2": site_dir / "env" / ".env",
        "env/env.ac.j2": site_dir / "env" / "env.ac",
    }

    for template_name, target in templates.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        template_content = importlib.resources.read_text("yakeroth.templates", template_name)
        content = jinja2.Template(template_content).render(site=site, project_name=get_project_name(site))
        target.write_text(content)

    # Create directories
    for d in ["modules", "patches", "scripts", "sql/custom/db_auth", "sql/custom/db_characters", "sql/custom/db_world", "state/db-backups", "env/modules"]:
        (site_dir / d).mkdir(parents=True, exist_ok=True)

    if repo:
        stage_all(repo)
        git_commit(repo, f"site: init {site} (templates)")

    console.print(f"[green]Initialized site: {site_dir}[/green]")


@cli.command()
@click.argument("site")
@click.pass_context
def sync(ctx: click.Context, site: str):
    """Sync modules: resolve, clone, generate CMake, copy SQL/configs."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    try:
        sync_modules(site_dir)
        console.print(f"[green]Synced modules for {site}[/green]")
    except SyncError as e:
        raise click.ClickException(str(e)) from e


@cli.command()
@click.argument("site")
@click.option("--no-cache", is_flag=True, help="Disable Docker build cache")
@click.option("--tag", "custom_tag", help="Custom image tag")
@click.option("--ac-ref", help="AzerothCore git ref (branch/tag/commit)")
@click.option("--ac-repo", help="AzerothCore git repository URL")
@click.pass_context
def build(ctx: click.Context, site: str, no_cache: bool, custom_tag: Optional[str], ac_ref: Optional[str], ac_repo: Optional[str]):
    """Build Docker image with site modules."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    config = ctx.obj["config"]

    repo = get_repo(site_dir)
    ensure_clean_working_tree(repo)

    # Load lock file for modules SHA
    from .models import ModuleLockFile
    lock_file = site_dir / "modules.lock.yml"
    if not lock_file.exists():
        raise click.ClickException("modules.lock.yml not found. Run 'yakeroth sync' first.")

    with open(lock_file) as f:
        lock_data = yaml.safe_load(f) or {}
    modules_lock_sha = get_file_sha(repo, "modules.lock.yml")[:12]
    site_git_sha = get_short_sha(repo)[:12]

    # Image tag
    if custom_tag:
        image_tag = f"acore-{site}-worldserver:{custom_tag}"
    else:
        image_tag = f"acore-{site}-worldserver:{site_git_sha}-{modules_lock_sha}"

    # Build args
    build_args = {
        "AC_REPO": ac_repo or config.ac_repo,
        "AC_REF": ac_ref or config.ac_ref,
        "SITE_MODULES_DIR": str(site_dir / "modules"),
        "SITE_CMAKE_FILE": str(site_dir / "ModulesSite.cmake"),
        "SITE_SQL_DIR": str(site_dir / "sql"),
        "SITE_NAME": site,
        "SITE_GIT_SHA": site_git_sha,
        "MODULES_LOCK_SHA": modules_lock_sha,
    }

    # Labels
    labels = {
        "org.azerothcore.site": site,
        "org.azerothcore.site-git-sha": site_git_sha,
        "org.azerothcore.modules-lock-sha": modules_lock_sha,
        "org.azerothcore.db-schema-version": "0",  # Will be updated after db-import
    }

    client = get_client()
    dockerfile = Path(__file__).parent.parent / "docker" / "Dockerfile"
    build_path = Path(__file__).parent.parent  # yakeroth repo root

    console.print(f"Building [cyan]{image_tag}[/cyan]...")
    image_id, digest = build_image(
        client, build_path, dockerfile, image_tag, build_args, labels, no_cache
    )

    # Update manifest
    manifest = load_image_tags(site_dir)
    timestamp = datetime.utcnow().isoformat() + "Z"
    tag_name = f"site/{site}/pre-build-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    entry = ImageTagEntry(
        git_tag=tag_name,
        image=image_tag,
        digest=digest,
        modules_lock_sha=modules_lock_sha,
        db_schema_version=0,
        timestamp=timestamp,
    )
    manifest.entries.append(entry)
    save_image_tags(site_dir, manifest)

    # Git tag and commit
    git_tag(repo, tag_name, f"Pre-build for {image_tag}")
    stage_all(repo)
    git_commit(repo, f"site: build {image_tag}")

    console.print(f"[green]Built {image_tag}[/green]")
    console.print(f"  Digest: {digest}")
    console.print(f"  Git tag: {tag_name}")


@cli.command()
@click.argument("site")
@click.option("--registry", help="Registry URL (e.g., ghcr.io/owner)")
@click.pass_context
def push(ctx: click.Context, site: str, registry: Optional[str]):
    """Push site images to registry."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    manifest = load_image_tags(site_dir)

    client = get_client()
    pushed = []

    for entry in manifest.entries:
        if entry.git_tag.startswith(f"site/{site}/pre-build-") or entry.git_tag.startswith(f"site/{site}/running-"):
            console.print(f"Pushing {entry.image}...")
            tag = push_image(client, entry.image, registry)
            pushed.append(tag)

    console.print(f"[green]Pushed {len(pushed)} images[/green]")


@cli.command()
@click.argument("site")
@click.option("--registry", help="Registry URL")
@click.pass_context
def pull(ctx: click.Context, site: str, registry: Optional[str]):
    """Pull site images from registry."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    manifest = load_image_tags(site_dir)

    client = get_client()
    pulled = []

    for entry in manifest.entries:
        if entry.git_tag.startswith(f"site/{site}/pre-build-") or entry.git_tag.startswith(f"site/{site}/running-"):
            console.print(f"Pulling {entry.image}...")
            tag = pull_image(client, entry.image, registry)
            pulled.append(tag)

    console.print(f"[green]Pulled {len(pulled)} images[/green]")


@cli.command()
@click.argument("site")
@click.option("--keep", default=5, help="Number of recent builds to keep")
@click.option("--dry-run", is_flag=True, help="Show what would be removed")
@click.pass_context
def prune_images_cmd(ctx: click.Context, site: str, keep: int, dry_run: bool):
    """Prune old site images per retention policy."""
    client = get_client()
    removed = prune_images(client, site, keep, dry_run)

    if dry_run:
        console.print(f"[yellow]Would remove {len(removed)} images:[/yellow]")
        for img in removed:
            console.print(f"  {img[:12]}")
    else:
        console.print(f"[green]Removed {len(removed)} images[/green]")


@cli.command()
@click.argument("site")
@click.option("--force", is_flag=True, help="Bypass compatibility check")
@click.pass_context
def up(ctx: click.Context, site: str, force: bool):
    """Start site containers with compatibility check."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    project_name = get_project_name(site)
    manifest = load_image_tags(site_dir)

    # Compatibility check
    latest_running = manifest.get_latest_running()
    latest_pre_build = manifest.get_latest_pre_build()

    if not force and latest_pre_build:
        expected_version = latest_pre_build.db_schema_version
        if expected_version > 0:
            try:
                current_version = get_db_schema_version(site_dir, project_name)
                if current_version != expected_version:
                    raise click.ClickException(
                        f"DB schema mismatch: image expects {expected_version}, "
                        f"database has {current_version}. Use --force to override."
                    )
            except DockerError:
                pass  # DB not running yet, skip check

    # Pre-update backup
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup_prefix = f"pre-{timestamp}"
    console.print(f"Creating pre-update backup: {backup_prefix}")
    try:
        mysqldump_all(site_dir, project_name, site_dir / "state" / "db-backups", backup_prefix)
    except DockerError as e:
        console.print(f"[yellow]Backup failed (DB may not be running): {e}[/yellow]")

    # Start containers
    result = compose_up(site_dir, project_name, force)
    if result.returncode != 0:
        raise click.ClickException(f"docker compose up failed: {result.stderr}")

    # Update manifest with running tag
    timestamp_iso = datetime.utcnow().isoformat() + "Z"
    running_tag = f"site/{site}/running-{timestamp}"

    if latest_pre_build:
        entry = ImageTagEntry(
            git_tag=running_tag,
            image=latest_pre_build.image,
            digest=latest_pre_build.digest,
            modules_lock_sha=latest_pre_build.modules_lock_sha,
            db_schema_version=latest_pre_build.db_schema_version,
            timestamp=timestamp_iso,
            backup_prefix=backup_prefix,
        )
        manifest.entries.append(entry)
        save_image_tags(site_dir, manifest)

    # Git tag
    repo = get_repo(site_dir)
    git_tag(repo, running_tag, f"Running {latest_pre_build.image if latest_pre_build else 'unknown'}")

    console.print(f"[green]Site {site} started[/green]")


@cli.command()
@click.argument("site")
@click.pass_context
def down(ctx: click.Context, site: str):
    """Stop site containers."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    project_name = get_project_name(site)

    result = compose_down(site_dir, project_name)
    if result.returncode != 0:
        raise click.ClickException(f"docker compose down failed: {result.stderr}")

    console.print(f"[green]Site {site} stopped[/green]")


@cli.command()
@click.argument("site")
@click.pass_context
def logs(ctx: click.Context, site: str):
    """View container logs."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    project_name = get_project_name(site)

    result = compose_logs(site_dir, project_name, follow=True)
    if result.returncode != 0:
        console.print(result.stderr)


@cli.command()
@click.argument("site")
@click.argument("spec")
@click.pass_context
def module_add(ctx: click.Context, site: str, spec: str):
    """Add module to modules.yml (format: name@branch or name@branch:commit)."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    repo = get_repo(site_dir)
    ensure_clean_working_tree(repo)

    modules_file = load_modules_yml(site_dir)

    # Parse spec: name[@branch[:commit]]
    parts = spec.split("@")
    if len(parts) != 2:
        raise click.ClickException("Spec format: name@branch[:commit]")

    name = parts[0]
    ref_parts = parts[1].split(":")
    branch = ref_parts[0]
    commit = ref_parts[1] if len(ref_parts) > 1 else None

    # Check if already exists
    for m in modules_file.modules:
        if m.name == name:
            raise click.ClickException(f"Module {name} already exists")

    # Add module
    new_module = ModuleSpec(name=name, source=f"https://github.com/azerothcore/{name}.git", branch=branch, commit=commit)
    modules_file.modules.append(new_module)

    # Write modules.yml
    with open(site_dir / "modules.yml", "w") as f:
        data = modules_file.model_dump(exclude_none=True)
        yaml.dump(data, f, sort_keys=False, default_flow_style=False)

    # Commit
    stage_all(repo)
    git_commit(repo, f"site: add {name}@{branch}" + (f":{commit[:12]}" if commit else ""))

    console.print(f"[green]Added {name}@{branch}[/green]")


@cli.command()
@click.argument("site")
@click.argument("name")
@click.option("--to", "target", help="Branch or commit to update to")
@click.pass_context
def module_update(ctx: click.Context, site: str, name: str, target: Optional[str]):
    """Update module in modules.yml."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    repo = get_repo(site_dir)
    ensure_clean_working_tree(repo)

    modules_file = load_modules_yml(site_dir)

    for m in modules_file.modules:
        if m.name == name:
            old_branch = m.branch
            old_commit = m.commit

            if target:
                if ":" in target:
                    m.branch, m.commit = target.split(":", 1)
                else:
                    m.branch = target
                    m.commit = None
            else:
                m.commit = None  # Update to latest on branch

            with open(site_dir / "modules.yml", "w") as f:
                data = modules_file.model_dump(exclude_none=True)
                yaml.dump(data, f, sort_keys=False, default_flow_style=False)

            stage_all(repo)
            git_commit(repo, f"site: update {name} from {old_branch} to {m.branch}" + (f":{m.commit[:12]}" if m.commit else ""))
            console.print(f"[green]Updated {name}[/green]")
            return

    raise click.ClickException(f"Module {name} not found")


@cli.command()
@click.argument("site")
@click.argument("name")
@click.pass_context
def module_remove(ctx: click.Context, site: str, name: str):
    """Remove module from modules.yml."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    repo = get_repo(site_dir)
    ensure_clean_working_tree(repo)

    modules_file = load_modules_yml(site_dir)
    modules_file.modules = [m for m in modules_file.modules if m.name != name]

    with open(site_dir / "modules.yml", "w") as f:
        data = modules_file.model_dump(exclude_none=True)
        yaml.dump(data, f, sort_keys=False, default_flow_style=False)

    stage_all(repo)
    git_commit(repo, f"site: remove {name}")

    console.print(f"[green]Removed {name}[/green]")


@cli.command()
@click.argument("site")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, site: str, key: str, value: str):
    """Set env var in env/.env (auto-converts to AC_ naming convention)."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    repo = get_repo(site_dir)
    ensure_clean_working_tree(repo)

    env_file = site_dir / "env" / ".env"
    env_file.parent.mkdir(parents=True, exist_ok=True)

    # Convert to AC_ naming convention
    # AllowTwoSide.Interaction.Calendar -> AC_ALLOW_TWO_SIDE_INTERACTION_CALENDAR
    import re
    # Replace dots and dashes with underscores first
    key = key.replace(".", "_").replace("-", "_")
    # Handle camelCase -> snake_case
    # Insert underscore before capital letters preceded by lowercase/number
    key = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', key)
    # Handle sequences of capitals followed by lowercase (e.g., XMLParser -> XML_Parser)
    key = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', key)
    ac_key = "AC_" + key.upper()
    env_vars = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env_vars[k] = v

    env_vars[ac_key] = value

    # Write back
    lines = [f"{k}={v}" for k, v in sorted(env_vars.items())]
    env_file.write_text("\n".join(lines) + "\n")

    stage_all(repo)
    git_commit(repo, f"site: config-set {ac_key}={value}")

    console.print(f"[green]Set {ac_key}={value}[/green]")


@cli.command()
@click.argument("site")
@click.option("--label", help="Backup label")
@click.pass_context
def db_backup(ctx: click.Context, site: str, label: Optional[str]):
    """Create labeled DB backup (all three databases)."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    project_name = get_project_name(site)

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    prefix = f"{label}-{timestamp}" if label else f"manual-{timestamp}"

    files = mysqldump_all(site_dir, project_name, site_dir / "state" / "db-backups", prefix)
    console.print(f"[green]Created backup: {prefix}[/green]")
    for f in files:
        console.print(f"  {f.name}")


@cli.command()
@click.argument("site")
@click.argument("backup_prefix")
@click.pass_context
def db_restore(ctx: click.Context, site: str, backup_prefix: str):
    """Restore DB from backup (all three databases)."""
    if not click.confirm(f"Restore databases from {backup_prefix}? This will overwrite current data."):
        return

    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    project_name = get_project_name(site)

    backup_dir = site_dir / "state" / "db-backups"
    mysql_restore_all(site_dir, project_name, backup_dir, backup_prefix)

    # Git tag
    repo = get_repo(site_dir)
    tag_name = f"site/{site}/db-restored-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    git_tag(repo, tag_name, f"DB restored from {backup_prefix}")

    console.print(f"[green]Restored databases from {backup_prefix}[/green]")


@cli.command()
@click.argument("site")
@click.pass_context
def db_schema_version(ctx: click.Context, site: str):
    """Show current DB schema version."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    project_name = get_project_name(site)

    try:
        version = get_db_schema_version(site_dir, project_name)
        console.print(f"DB schema version: {version}")
    except DockerError as e:
        raise click.ClickException(str(e)) from e


@cli.command()
@click.argument("site")
@click.option("--tag", help="Specific image tag")
@click.pass_context
def image_info(ctx: click.Context, site: str, tag: Optional[str]):
    """Show image metadata."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    manifest = load_image_tags(site_dir)

    client = get_client()

    if tag:
        labels = get_image_labels(client, tag)
        console.print(f"Labels for {tag}:")
        for k, v in labels.items():
            console.print(f"  {k}: {v}")
    else:
        # Show all manifest entries
        table = Table(title=f"Image Tags for {site}")
        table.add_column("Git Tag")
        table.add_column("Image")
        table.add_column("Digest")
        table.add_column("DB Schema")
        table.add_column("Backup Prefix")

        for entry in manifest.entries:
            table.add_row(
                entry.git_tag,
                entry.image,
                entry.digest[:20] + "...",
                str(entry.db_schema_version),
                entry.backup_prefix or "-",
            )
        console.print(table)


@cli.command()
@click.argument("site")
@click.pass_context
def verify_compatibility(ctx: click.Context, site: str):
    """Check image/schema compatibility without starting."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    project_name = get_project_name(site)
    manifest = load_image_tags(site_dir)

    latest_pre_build = manifest.get_latest_pre_build()
    if not latest_pre_build:
        raise click.ClickException("No pre-build entry found. Run 'yakeroth build' first.")

    expected = latest_pre_build.db_schema_version
    if expected == 0:
        console.print("[yellow]Image has db_schema_version=0 (not set by db-import yet)[/yellow]")
        return

    try:
        current = get_db_schema_version(site_dir, project_name)
        if current == expected:
            console.print(f"[green]Compatible: image expects {expected}, database has {current}[/green]")
        else:
            console.print(f"[red]Mismatch: image expects {expected}, database has {current}[/red]")
            sys.exit(1)
    except DockerError as e:
        console.print(f"[yellow]Could not check database: {e}[/yellow]")


@cli.command()
@click.argument("site")
@click.option("--to", "target", help="Git tag or commit to rollback to")
@click.option("--with-db", is_flag=True, help="Also restore database from matching backup")
@click.option("--clean", is_flag=True, default=True, help="Remove untracked generated files")
@click.option("--no-clean", is_flag=True, help="Keep untracked files")
@click.pass_context
def rollback(ctx: click.Context, site: str, target: Optional[str], with_db: bool, clean: bool, no_clean: bool):
    """Reset site directory to previous state."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    repo = get_repo(site_dir)

    if with_db and not click.confirm("This will OVERWRITE databases with backup data. Continue?"):
        return

    if target:
        reset_hard(repo, target)
    else:
        reset_hard(repo, "HEAD~1")

    if clean and not no_clean:
        clean_untracked(repo, ["modules", "sql/custom", "env/modules"])

    if with_db:
        manifest = load_image_tags(site_dir)
        target_entry = manifest.get_by_tag(target) if target else manifest.get_latest_running()
        if target_entry and target_entry.backup_prefix:
            console.print(f"Restoring DB from {target_entry.backup_prefix}...")
            project_name = get_project_name(site)
            mysql_restore_all(site_dir, project_name, site_dir / "state" / "db-backups", target_entry.backup_prefix)
        else:
            console.print("[yellow]No backup prefix found for target[/yellow]")

    console.print(f"[green]Rolled back {site}[/green]")


@cli.command()
@click.argument("site")
@click.pass_context
def history(ctx: click.Context, site: str):
    """Show site operation history."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    repo = get_repo(site_dir)

    entries = log_oneline(repo, max_count=30)
    for entry in entries:
        console.print(entry)


@cli.command()
@click.argument("site")
@click.pass_context
def status(ctx: click.Context, site: str):
    """Show git status of site."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    repo = get_repo(site_dir)

    status_info = get_status(repo)
    console.print(f"Branch: {status_info['branch']}")
    console.print(f"HEAD: {status_info['head_sha']}")
    console.print(f"Dirty: {status_info['dirty']}")

    if status_info["modified"]:
        console.print("Modified:")
        for f in status_info["modified"]:
            console.print(f"  M {f}")

    if status_info["staged"]:
        console.print("Staged:")
        for f in status_info["staged"]:
            console.print(f"  A {f}")

    if status_info["untracked"]:
        console.print("Untracked:")
        for f in status_info["untracked"]:
            console.print(f"  ? {f}")


def main():
    cli(obj={})


if __name__ == "__main__":
    main()