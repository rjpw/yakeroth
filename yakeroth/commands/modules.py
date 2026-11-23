"""Module management commands: add, update, remove."""


import click
import yaml

from ..common import console, get_site_dir
from ..git_utils import (
    commit as git_commit,
)
from ..git_utils import (
    ensure_clean_working_tree,
    get_repo,
    stage_all,
)
from ..models import ModuleCategory, ModuleSpec
from ..registry import get_registry_client
from ..sync_modules import load_modules_yml


@click.command()
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


@click.command()
@click.argument("site")
@click.argument("name")
@click.option("--to", "target", help="Branch or commit to update to")
@click.pass_context
def module_update(ctx: click.Context, site: str, name: str, target: str | None):
    """Update module in modules.yml."""
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    repo = get_repo(site_dir)
    ensure_clean_working_tree(repo)

    modules_file = load_modules_yml(site_dir)

    for m in modules_file.modules:
        if m.name == name:
            old_branch = m.branch

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
            commit_msg = f"site: update {name} from {old_branch} to {m.branch}"
            if m.commit:
                commit_msg += f":{m.commit[:12]}"
            git_commit(repo, commit_msg)
            console.print(f"[green]Updated {name}[/green]")
            return

    raise click.ClickException(f"Module {name} not found")


@click.command()
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


@click.command()
@click.argument("query")
@click.option("--category", type=click.Choice(["module", "tool", "lua", "sql"]), default="module")
@click.option("--limit", default=20, help="Maximum results")
@click.pass_context
def module_search(ctx: click.Context, query: str, category: str, limit: int):
    """Search AzerothCore module registry (GitHub topics)."""
    client = get_registry_client()
    cat = ModuleCategory(category)
    results = client.search(query, category=cat, limit=limit)

    if not results:
        console.print("[yellow]No modules found[/yellow]")
        return

    for m in results:
        cats = ", ".join(c.value for c in m.categories) if m.categories else "module"
        rel = f" ({m.latest_release})" if m.latest_release else ""
        updated = f" · updated {m.updated_at.strftime('%Y-%m-%d')}" if m.updated_at else ""
        console.print(f"  [cyan]{m.name}[/cyan] ({cats}){rel} — {m.stars} ⭐{updated}")
        if m.description:
            desc = m.description[:80] + "..." if len(m.description) > 80 else m.description
            console.print(f"    [dim]{desc}[/dim]")


@click.command()
@click.argument("name")
@click.pass_context
def module_info(ctx: click.Context, name: str):
    """Show detailed module information from registry."""
    client = get_registry_client()
    manifest = client.get(name)

    if not manifest:
        raise click.ClickException(f"Module not found: {name}")

    cats = ", ".join(c.value for c in manifest.categories) if manifest.categories else "module"
    console.print(f"[bold]{manifest.name}[/bold] ({cats})")
    console.print(f"  Repo: {manifest.repository_url}")
    if manifest.description:
        console.print(f"  Description: {manifest.description}")
    if manifest.latest_release:
        console.print(f"  Latest release: {manifest.latest_release}")
    console.print(f"  Stars: {manifest.stars}")
    if manifest.updated_at:
        console.print(f"  Last updated: {manifest.updated_at.strftime('%Y-%m-%d')}")
    if manifest.ac_compatibility:
        console.print(f"  AC compatibility: {', '.join(manifest.ac_compatibility)}")
    if manifest.dependencies:
        console.print("  Dependencies:")
        for dep in manifest.dependencies:
            opt = " (optional)" if dep.optional else ""
            console.print(f"    - {dep.name}@{dep.version}{opt}")
    if manifest.conflicts:
        console.print(f"  Conflicts: {', '.join(manifest.conflicts)}")
    if manifest.sql_files:
        console.print("  SQL files:")
        for sql in manifest.sql_files:
            console.print(f"    - {sql.file} ({sql.database})")
    if manifest.cmake_options:
        console.print("  CMake options:")
        for k, v in manifest.cmake_options.items():
            console.print(f"    - {k}={v}")


# Collect all commands for registration
MODULE_COMMANDS = [
    module_add,
    module_update,
    module_remove,
    module_search,
    module_info,
]


def register_module_commands(cli_group):
    """Register all module commands with the CLI group."""
    for cmd in MODULE_COMMANDS:
        cli_group.add_command(cmd)
