"""Yakeroth - AzerothCore server composition manager."""

__version__ = "0.3.0"

from .embedded_templates import TEMPLATES
from .dockerfile_template import DOCKERFILE_TEMPLATE

__all__ = ["main", "TEMPLATES", "DOCKERFILE_TEMPLATE"]