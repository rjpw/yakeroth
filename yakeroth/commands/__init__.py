"""Command modules for yakeroth CLI."""

from .site import register_site_commands
from .modules import register_module_commands
from .config import register_config_commands
from .database import register_database_commands
from .images import register_images_commands
from .rollback import register_rollback_commands


def register_all(cli):
    """Register all command groups with the CLI."""
    register_site_commands(cli)
    register_module_commands(cli)
    register_config_commands(cli)
    register_database_commands(cli)
    register_images_commands(cli)
    register_rollback_commands(cli)