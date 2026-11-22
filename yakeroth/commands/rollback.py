"""Rollback, history, and status commands."""

import click
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..models import ImageTagsManifest, ImageTagEntry
from ..git_utils import (
    get_repo,
    reset_hard,
    clean_untracked,
    log_oneline,
    tag as git_tag,
    get_status,
)
from ..docker_utils import (
    DockerError,
    mysql_restore_all,
)
from ..common import get_site_dir, get_project_name, console, load_image_tags


@click.command()
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


@click.command()
@click.argument("site")
@click.pass_context
def history(ctx: click.Context, site: str):
    """Show site operation history."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    repo = get_repo(site_dir)

    entries = log_oneline(repo, max_count=30)
    for entry in entries:
        console.print(entry)


@click.command()
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


# Collect all commands for registration
ROLLBACK_COMMANDS = [
    rollback,
    history,
    status,
]


def register_rollback_commands(cli_group):
    """Register all rollback/history/status commands with the CLI group."""
    for cmd in ROLLBACK_COMMANDS:
        cli_group.add_command(cmd)