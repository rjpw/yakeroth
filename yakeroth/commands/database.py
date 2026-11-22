"""Database management commands: backup, restore, schema-version."""

import click
from datetime import datetime
from pathlib import Path

from ..git_utils import (
    get_repo,
    tag as git_tag,
)
from ..docker_utils import (
    DockerError,
    mysqldump_all,
    mysql_restore_all,
    get_db_schema_version,
    compose_up,
)
from ..models import ImageTagsManifest, ImageTagEntry


def register(cli):
    """Register database commands with the CLI group."""

    @cli.command()
    @click.argument("site")
    @click.option("--label", help="Backup label")
    @click.pass_context
    def db_backup(ctx: click.Context, site: str, label: Optional[str]):
        """Create labeled DB backup (all three databases)."""
        from ..cli import get_site_dir, get_project_name, console

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
        from ..cli import get_site_dir, get_project_name, console

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
        from ..cli import get_site_dir, get_project_name, console

        site_dir = get_site_dir(site, ctx.obj["site_dir"])
        project_name = get_project_name(site)

        try:
            version = get_db_schema_version(site_dir, project_name)
            console.print(f"DB schema version: {version}")
        except DockerError as e:
            raise click.ClickException(str(e)) from e