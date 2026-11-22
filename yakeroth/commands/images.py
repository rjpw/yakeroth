"""Image management commands: image-info, verify-compatibility."""

import click
from pathlib import Path
from typing import Optional

from ..models import ImageTagsManifest
from ..docker_utils import (
    DockerError,
    get_client,
    get_image_labels,
    get_db_schema_version,
)
from ..git_utils import get_repo
from ..common import get_site_dir, get_project_name, console, load_image_tags


@click.command()
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
        from rich.table import Table
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


@click.command()
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
            import sys
            sys.exit(1)
    except DockerError as e:
        console.print(f"[yellow]Could not check database: {e}[/yellow]")


# Collect all commands for registration
IMAGES_COMMANDS = [
    image_info,
    verify_compatibility,
]


def register_images_commands(cli_group):
    """Register all image commands with the CLI group."""
    for cmd in IMAGES_COMMANDS:
        cli_group.add_command(cmd)