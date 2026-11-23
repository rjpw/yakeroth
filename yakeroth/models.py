"""Data models for yakeroth configuration files."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal
from pydantic import BaseModel, Field, field_validator


class ModuleCategory(str, Enum):
    """Module category from GitHub topics."""
    MODULE = "module"          # azerothcore-module
    TOOL = "tool"              # azerothcore-tools
    LUA = "lua"                # azerothcore-lua
    SQL = "sql"                # azerothcore-sql


class ModuleSpec(BaseModel):
    """Module specification from modules.yml (user-editable)."""

    name: str = Field(..., description="Module name (directory name)")
    source: str = Field(..., description="Git repository URL")
    branch: str = Field(default="master", description="Git branch")
    commit: str | None = Field(default=None, description="Optional commit pin (resolved to lock file)")
    dirname: str | None = Field(default=None, description="Custom directory name (defaults to name)")
    build: Literal["static", "dynamic"] = Field(default="static", description="Build linkage mode")
    patch: str | None = Field(default=None, description="Patch file relative to patches/")
    sql: list[str] = Field(default_factory=list, description="SQL files relative to module root")

    @field_validator("dirname", mode="before")
    @classmethod
    def _default_dirname(cls, v: str | None, info) -> str | None:
        if v is None and info.data.get("name"):
            return info.data["name"]
        return v


class ModuleLock(BaseModel):
    """Resolved module lock entry (generated, committed)."""

    name: str
    source: str
    branch: str
    commit: str = Field(..., description="Resolved commit SHA")
    dirname: str
    build: Literal["static", "dynamic"]
    sql: list[str] = Field(default_factory=list)

    @classmethod
    def from_spec(cls, spec: ModuleSpec, commit: str) -> "ModuleLock":
        return cls(
            name=spec.name,
            source=spec.source,
            branch=spec.branch,
            commit=commit,
            dirname=spec.dirname or spec.name,
            build=spec.build,
            sql=spec.sql,
        )


class ModulesFile(BaseModel):
    """modules.yml root."""

    modules: list[ModuleSpec] = Field(default_factory=list)


class ModulesLockFile(BaseModel):
    """modules.lock.yml root."""

    modules: list[ModuleLock] = Field(default_factory=list)
    ac_repo: str | None = Field(default=None, description="AzerothCore repository URL")
    ac_ref: str | None = Field(default=None, description="AzerothCore git ref (branch/tag)")
    ac_commit: str | None = Field(default=None, description="Resolved AzerothCore commit SHA")

    def get(self, name: str) -> ModuleLock | None:
        for m in self.modules:
            if m.name == name:
                return m
        return None


class ImageTagEntry(BaseModel):
    """Entry in state/image-tags.yml manifest."""

    git_tag: str
    image: str
    digest: str
    modules_lock_sha: str
    db_schema_version: int
    timestamp: str
    backup_prefix: str | None = None


class ImageTagsManifest(BaseModel):
    """state/image-tags.yml root."""

    entries: list[ImageTagEntry] = Field(default_factory=list)

    def get_latest_pre_build(self) -> ImageTagEntry | None:
        for entry in reversed(self.entries):
            if entry.git_tag.startswith("site/") and "/pre-build-" in entry.git_tag:
                return entry
        return None

    def get_latest_running(self) -> ImageTagEntry | None:
        for entry in reversed(self.entries):
            if entry.git_tag.startswith("site/") and "/running-" in entry.git_tag:
                return entry
        return None

    def get_by_tag(self, tag: str) -> ImageTagEntry | None:
        for entry in self.entries:
            if entry.git_tag == tag:
                return entry
        return None


class SiteConfig(BaseModel):
    """Global yakeroth configuration (optional)."""

    image_retention: int = 5
    db_backup_retention: int = 10
    db_backup_path: str | None = None
    compose_site_dir: str = "sites"
    ac_repo: str = "https://github.com/azerothcore/azerothcore-wotlk.git"
    ac_ref: str = "master"


class DependencySpec(BaseModel):
    """Module dependency specification."""
    name: str
    version: str = "*"
    optional: bool = False
    category: ModuleCategory = ModuleCategory.MODULE


class ReleaseInfo(BaseModel):
    """GitHub release information."""
    tag_name: str
    name: str | None = None
    prerelease: bool = False
    draft: bool = False
    published_at: datetime
    assets: list[str] = Field(default_factory=list)


class SQLFileSpec(BaseModel):
    """SQL file specification for a module."""
    file: str
    database: Literal["auth", "characters", "world"] = "world"
    optional: bool = False


class ConfigSpec(BaseModel):
    """Configuration option schema."""
    type: Literal["bool", "int", "float", "string"]
    default: str | int | float | bool | None = None
    description: str | None = None
    min: int | float | None = None
    max: int | float | None = None
    options: list[str] | None = None


class ModuleManifest(BaseModel):
    """Enriched module metadata from registry (GitHub)."""
    name: str
    full_name: str
    description: str | None = None
    homepage: str | None = None
    repository_url: str
    categories: list[ModuleCategory] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    latest_release: str | None = None
    releases: list[ReleaseInfo] = Field(default_factory=list)
    default_branch: str = "master"
    dependencies: list[DependencySpec] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    provides: list[str] = Field(default_factory=list)
    cmake_options: dict[str, str] = Field(default_factory=dict)
    sql_files: list[SQLFileSpec] = Field(default_factory=list)
    config_schema: dict[str, ConfigSpec] = Field(default_factory=dict)
    stars: int = 0
    updated_at: datetime | None = None
    license: str | None = None
    ac_compatibility: list[str] = Field(default_factory=list)

    def get_compatible_versions(self, constraint: str) -> list[str]:
        """Return release versions matching constraint (simple semver)."""
        from packaging.version import parse as parse_version
        from packaging.specifiers import SpecifierSet
        spec = SpecifierSet(constraint)
        return [r.tag_name for r in self.releases if parse_version(r.tag_name.lstrip("v")) in spec]


class ModuleSummary(BaseModel):
    """Lightweight summary for search results."""
    name: str
    full_name: str
    description: str | None = None
    stars: int
    updated_at: datetime | None = None
    latest_release: str | None = None
    categories: list[ModuleCategory] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class ResolvedModule(BaseModel):
    """Fully resolved module with pinned version."""
    manifest: ModuleManifest
    version: str
    source: str  # git URL or local path
    commit: str  # resolved commit SHA
    category: ModuleCategory


class ResolvedGraph(BaseModel):
    """Result of dependency resolution."""
    modules: list[ResolvedModule]  # Topologically sorted
    conflicts: list[str] = Field(default_factory=list)
    missing_deps: list[str] = Field(default_factory=list)