# Yakeroth — GitHub Copilot Instructions

## Project Overview

**Yakeroth** is a CLI tool for managing AzerothCore server compositions via Docker Compose. It provides declarative module management, git-versioned sites, coupled image/DB schema versioning, and database backup/restore with rollback.

- **Repository**: https://github.com/rjpw/yakeroth
- **Language**: Python 3.11+
- **Package**: `pipx install git+https://github.com/rjpw/yakeroth`
- **Entry point**: `yakeroth` (Click-based CLI)

## Key Files

| File | Purpose |
|------|---------|
| `yakeroth/cli.py` | All CLI commands (Click) |
| `yakeroth/models.py` | Pydantic models for config files |
| `yakeroth/sync_modules.py` | Module resolution, cloning, CMake generation |
| `yakeroth/git_utils.py` | Git operations (commit, tag, rollback) |
| `yakeroth/docker_utils.py` | Docker SDK (build, compose, DB backup/restore) |
| `docker/Dockerfile` | Multi-stage site worldserver build |
| `templates/*.j2` | Jinja2 templates for `yakeroth init` |

## Development Commands

```bash
# Install in dev mode
python3 -m venv .venv && .venv/bin/pip install -e .[dev]

# Run CLI
.venv/bin/yakeroth --help

# Test
.venv/bin/pytest

# Lint
.venv/bin/ruff check .
.venv/bin/mypy yakeroth/
```

## Code Conventions

- **Line length**: 100 (Ruff)
- **Type hints**: Required on public functions
- **Imports**: Absolute within package (`from yakeroth.models import ...`)
- **Errors**: Custom exceptions (`SyncError`, `GitError`, `DockerError`)
- **Mutating CLI pattern**: Check git status → execute → auto-commit → tag milestones

## Operational Workflow (for Agents)

When helping users operate yakeroth sites:

1. **Adding modules**: `module-add` → `sync` → `build` → `up`
2. **Config changes**: `config-set` → `up` (no rebuild)
3. **Schema mismatch**: `verify-compatibility` → `rollback --with-db`
4. **Rollback**: `rollback [--to tag] [--with-db] [--clean]`

**Guardrails**: All mutating commands require clean git working tree (or `--force`). Confirm before destructive ops (`--with-db`, `db-restore`, `prune-images`).

## References

- Full skill: `.agents/skills/yakeroth-ops/SKILL.md`
- Documentation: `docs/server-composition.md`
- AzerothCore Docker: https://www.azerothcore.org/wiki/install-with-docker