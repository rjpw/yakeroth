"""Site lifecycle commands: init, build, up, down, logs."""

import click
from datetime import datetime
from pathlib import Path
from typing import Optional
import shutil

from ..models import ImageTagsManifest, ImageTagEntry, SiteConfig
from ..git_utils import (
    GitError,
    get_repo,
    get_short_sha,
    get_file_sha,
    stage_all,
    commit as git_commit,
    tag as git_tag,
    ensure_clean_working_tree,
)
from ..docker_utils import (
    DockerError,
    build_image,
    compose_up,
    compose_down,
    compose_logs,
    get_client,
    mysqldump_all,
    push_image,
    pull_image,
    prune_images,
)
from ..sync_modules import SyncError, sync as sync_modules, load_modules_yml
from .. import TEMPLATES, DOCKERFILE_TEMPLATE
from ..common import get_site_dir, get_project_name, console, load_image_tags, save_image_tags


@click.command()
@click.argument("site")
@click.option("--force", is_flag=True, help="Overwrite existing site")
@click.pass_context
def init(ctx: click.Context, site: str, force: bool):
    """Initialize a new site directory with templates."""
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
    templates = {
        "modules.yml.j2": site_dir / "modules.yml",
        "docker-compose.override.yml.j2": site_dir / "docker-compose.override.yml",
        ".gitignore.j2": site_dir / ".gitignore",
        "env/.env.j2": site_dir / "env" / ".env",
        "env/env.ac.j2": site_dir / "env" / "env.ac",
    }

    for template_name, target in templates.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        template_content = TEMPLATES[template_name]
        content = __import__("jinja2").Template(template_content).render(
            site=site, project_name=get_project_name(site)
        )
        target.write_text(content)

    # Write Dockerfile (not a jinja2 template, just a raw file)
    (site_dir / "Dockerfile").write_text(DOCKERFILE_TEMPLATE)

    # Create directories
    for d in ["modules", "patches", "scripts", "sql/custom/db_auth", "sql/custom/db_characters", "sql/custom/db_world", "state/db-backups", "env/modules"]:
        (site_dir / d).mkdir(parents=True, exist_ok=True)

    if repo:
        stage_all(repo)
        git_commit(repo, f"site: init {site} (templates)")

    console.print(f"[green]Initialized site: {site_dir}[/green]")


@click.command()
@click.argument("site")
@click.option("--ac-repo", help="AzerothCore git repository URL")
@click.option("--ac-ref", help="AzerothCore git ref (branch/tag/commit)")
@click.pass_context
def sync(ctx: click.Context, site: str, ac_repo: Optional[str], ac_ref: Optional[str]):
    """Sync modules: resolve, clone, generate CMake, copy SQL/configs."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    config = ctx.obj["config"]
    
    # Report config source
    config_path = ctx.obj.get("config_path")
    if config_path and Path(config_path).exists():
        console.print(f"[dim]Using global config: {config_path}[/dim]")
    elif (Path.home() / ".config" / "yakeroth" / "config.yml").exists():
        console.print(f"[dim]Using global config: ~/.config/yakeroth/config.yml[/dim]")
    
    # Pass global config from context for AC repo/ref defaults
    try:
        sync_modules(site_dir, ac_repo=ac_repo, ac_ref=ac_ref, config=config)
        console.print(f"[green]Synced modules for {site}[/green]")
    except SyncError as e:
        raise click.ClickException(str(e)) from e


@click.command()
@click.argument("site")
@click.option("--no-cache", is_flag=True, help="Disable Docker build cache")
@click.option("--tag", "custom_tag", help="Custom image tag")
@click.option("--ac-ref", help="AzerothCore git ref (branch/tag/commit)")
@click.option("--ac-repo", help="AzerothCore git repository URL")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def build(ctx: click.Context, site: str, no_cache: bool, custom_tag: Optional[str], ac_ref: Optional[str], ac_repo: Optional[str], yes: bool):
    """Build Docker image with site modules."""
    import yaml

    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    config = ctx.obj["config"]
    
    # Report config source
    config_path = ctx.obj.get("config_path")
    if config_path and Path(config_path).exists():
        console.print(f"[dim]Using global config: {config_path}[/dim]")
    elif (Path.home() / ".config" / "yakeroth" / "config.yml").exists():
        console.print(f"[dim]Using global config: ~/.config/yakeroth/config.yml[/dim]")

    repo = get_repo(site_dir)

    # Prepare AC repo cache in build context (before clean check, since it's gitignored)
    lock_file = site_dir / "modules.lock.yml"
    if lock_file.exists():
        with open(lock_file) as f:
            lock_data = yaml.safe_load(f) or {}
        ac_repo_from_lock = lock_data.get("ac_repo")
        ac_ref_from_lock = lock_data.get("ac_ref")
        ac_commit_from_lock = lock_data.get("ac_commit")
    else:
        lock_data = {}
        ac_repo_from_lock = ac_ref_from_lock = ac_commit_from_lock = None

    from yakeroth.common import get_acore_cached_repo
    ac_repo_for_cache = ac_repo_from_lock or ac_repo or config.ac_repo
    ac_cache_src = get_acore_cached_repo(ac_repo_for_cache)
    ac_cache_dst = site_dir / "acore-source"
    if ac_cache_dst.exists():
        shutil.rmtree(ac_cache_dst)
    if ac_cache_src.exists():
        shutil.copytree(ac_cache_src, ac_cache_dst)
        # Remove .git to prevent git from treating it as submodule
        git_dir = ac_cache_dst / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)
    # If only .gitignore is modified and acore-source is the only untracked (due to .gitignore not staged yet),
    # stage .gitignore first so acore-source becomes ignored
    if repo.is_dirty(untracked_files=True):
        dirty_files = [item.a_path for item in repo.index.diff(None)]
        untracked = repo.untracked_files
        all_dirty = set(dirty_files) | set(untracked)
        # Allow .gitignore modification + acore-source untracked (will be ignored once .gitignore staged)
        # Also allow just acore-source/ untracked (if .gitignore already staged)
        if all_dirty == {".gitignore", "acore-source/"} or all_dirty == {".gitignore"} or all_dirty == {"acore-source/"}:
            if ".gitignore" in dirty_files:
                repo.index.add([".gitignore"])
                console.print("[dim]Staged .gitignore update (acore-source ignore)[/dim]")
            # After staging .gitignore, acore-source/ may still show as untracked due to git index caching.
            # This is expected - accept it since acore-source/ is now gitignored.
        else:
            ensure_clean_working_tree(repo)

    if not lock_file.exists():
        raise click.ClickException("modules.lock.yml not found. Run 'yakeroth sync' first.")
    
    # Read AC repo info from lock file (populated by sync)
    ac_repo_from_lock = lock_data.get("ac_repo")
    ac_ref_from_lock = lock_data.get("ac_ref")
    ac_commit_from_lock = lock_data.get("ac_commit")
    modules_lock_sha = get_file_sha(repo, "modules.lock.yml")[:12]
    site_git_sha = get_short_sha(repo)[:12]

    # Image tag
    if custom_tag:
        image_tag = f"acore-{site}-worldserver:{custom_tag}"
    else:
        image_tag = f"acore-{site}-worldserver:{site_git_sha}-{modules_lock_sha}"

    # Build args (relative to site_dir build context)
    # Use lock file values for reproducibility (set by sync)
    build_args = {
        "AC_REPO": ac_repo_from_lock or ac_repo or config.ac_repo,
        "AC_REF": ac_ref_from_lock or ac_ref or config.ac_ref,
        "AC_COMMIT": ac_commit_from_lock or "",
        "SITE_MODULES_DIR": "modules",
        "SITE_CMAKE_FILE": "ModulesSite.cmake",
        "SITE_SQL_DIR": "sql",
        "SITE_NAME": site,
        "SITE_GIT_SHA": site_git_sha,
        "MODULES_LOCK_SHA": modules_lock_sha,
        "BUILD_DATE": datetime.utcnow().isoformat() + "Z",
    }


    # Labels
    labels = {
        "org.azerothcore.site": site,
        "org.azerothcore.site-git-sha": site_git_sha,
        "org.azerothcore.modules-lock-sha": modules_lock_sha,
        "org.azerothcore.db-schema-version": "0",  # Will be updated after db-import
    }

    client = get_client()
    # Use site directory as build context so COPY works with relative paths
    build_path = site_dir.resolve()
    # Dockerfile is in the site directory (written during init)
    dockerfile = (site_dir / "Dockerfile").resolve()
    # Make dockerfile path relative to build_path
    dockerfile_rel = dockerfile.relative_to(build_path)
    # Print manual docker build command for debugging
    # Print manual docker build command for debugging
    console.print(f"\n[dim]Manual build command (run from {build_path}):[/dim]")
    console.print(f"[dim]# Step 1: Copy cached AC repo to build context (required for COPY in Dockerfile)[/dim]")
    console.print(f"[dim]cp -r {get_acore_cached_repo(ac_repo_for_cache)} acore-source/[/dim]")
    console.print(f"[dim]# Step 2: Build (AC_COMMIT from modules.lock.yml ensures reproducibility)[/dim]")
    build_cmd = "docker build \\\n"
    for key, value in build_args.items():
        build_cmd += f"  --build-arg {key}={value} \\\n"
    build_cmd += f"  -t {image_tag} \\\n"
    build_cmd += f"  -f {dockerfile_rel} \\\n"
    if no_cache:
        build_cmd += f"  --no-cache \\\n"
    build_cmd += f"  --target worldserver \\\n"
    build_cmd += f"  --progress=plain \\\n"
    build_cmd += f"  ."
    console.print(f"[dim]{build_cmd}[/dim]\n")

    if not yes:
        import sys
        if sys.stdin.isatty():
            confirm = click.confirm("Build?", default=False)
            if not confirm:
                console.print("[yellow]Build cancelled[/yellow]")
                return
        else:
            # Non-interactive (piped input) - check for 'Y' or 'y' in stdin
            first_char = sys.stdin.read(1)
            if first_char.lower() != 'y':
                console.print("[yellow]Build cancelled (no 'Y' piped)[/yellow]")
                return

    console.print(f"Building [cyan]{image_tag}[/cyan]...")
    image_id, digest, build_log_tail = build_image(
        client, build_path, dockerfile_rel, image_tag, build_args, labels, no_cache,
        stream_output=True, log_tail=100
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


@click.command()
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


@click.command()
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


@click.command()
@click.argument("site")
@click.option("--keep", default=5, help="Number of recent builds to keep")
@click.option("--dry-run", is_flag=True, help="Show what would be removed")
@click.pass_context
def prune_images(ctx: click.Context, site: str, keep: int, dry_run: bool):
    """Prune old site images per retention policy."""
    client = get_client()
    removed = prune_images(client, site, keep, dry_run)

    if dry_run:
        console.print(f"[yellow]Would remove {len(removed)} images:[/yellow]")
        for img in removed:
            console.print(f"  {img[:12]}")
    else:
        console.print(f"[green]Removed {len(removed)} images[/green]")


@click.command()
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
                from yakeroth.docker_utils import get_db_schema_version
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
        manifest = load_image_tags(site_dir)
        manifest.entries.append(entry)
        save_image_tags(site_dir, manifest)

    # Git tag
    repo = get_repo(site_dir)
    git_tag(repo, running_tag, f"Running {latest_pre_build.image if latest_pre_build else 'unknown'}")

    console.print(f"[green]Site {site} started[/green]")


@click.command()
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


@click.command()
@click.argument("site")
@click.pass_context
def logs(ctx: click.Context, site: str):
    """View container logs."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    project_name = get_project_name(site)

    result = compose_logs(site_dir, project_name, follow=True)
    if result.returncode != 0:
        console.print(result.stderr)


# Collect all commands for registration
SITE_COMMANDS = [
    init,
    sync,
    build,
    push,
    pull,
    prune_images,
    up,
    down,
    logs,
]


def register_site_commands(cli_group):
    """Register all site commands with the CLI group."""
    for cmd in SITE_COMMANDS:
        cli_group.add_command(cmd)