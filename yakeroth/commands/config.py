"""Config management commands: config-set."""

import click
import re
from pathlib import Path

from ..git_utils import (
    get_repo,
    stage_all,
    commit as git_commit,
    ensure_clean_working_tree,
)


def register(cli):
    """Register config commands with the CLI group."""

    @cli.command()
    @click.argument("site")
    @click.argument("key")
    @click.argument("value")
    @click.pass_context
    def config_set(ctx: click.Context, site: str, key: str, value: str):
        """Set env var in env/.env (auto-converts to AC_ naming convention)."""
        from ..cli import get_site_dir, console

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

        # Read existing
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