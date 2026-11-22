"""Module management commands: add, update, remove."""

import click
from pathlib import Path
from typing import Optional
import yaml

from ..models import ModuleSpec, ModulesFile
from ..git_utils import (
    GitError,
    get_repo,
    stage_all,
    commit as git_commit,
    ensure_clean_working_tree,
)
from ..sync_modules import SyncError, sync as sync_modules, load_modules_yml


def register(cli):
    """Register module management commands with the CLI group."""

    @cli.command()
    @click.argument("site")
    @click.argument("spec")
    @click.pass_context
    def module_add(ctx: click.Context, site: str, spec: str):
        """Add module to modules.yml (format: name@branch or name@branch:commit)."""
        from ..cli import get_site_dir, console

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
        new_module = ModuleSpec(
            name=name,
            source=f"https://github.com/azerothcore/{name}.git",
            branch=branch,
            commit=commit,
        )
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
        from ..cli import get_site_dir, console

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
        from ..cli import get_site_dir, console

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


def register(cli):
    """Register module commands with the CLI group."""
    pass  # Decorators already registered