"""Command modules for yakeroth CLI."""

from .site import register as register_site_commands
from .modules import register as register_module_commands
from .config import register as register_config_commands
from .database import register as register_database_commands
from .images import register as register_images_commands
from .rollback import register as register_rollback_commands


def register_all(cli):
    """Register all command groups with the CLI."""
    register_site_commands(cli)
    register_module_commands(cli)
    register_config_commands(cli)
    register_database_commands(cli)
    register_images_commands(cli)
    register_rollback_commands(cli)