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
import jinja2
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
from .dockerfile_template import DOCKERFILE_TEMPLATE
from . import TEMPLATES

from .common import (
    console,
    get_site_dir,
    get_project_name,
    load_config,
    load_image_tags,
    save_image_tags,
    setup_logging,
)

from .commands import register_all

console = Console()


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


# Register all command groups
register_all(cli)


def main():
    cli(obj={})


if __name__ == "__main__":
    main()