# Yakeroth — Agent Instructions

## Project Overview

**Yakeroth** is a CLI tool for managing AzerothCore server compositions via Docker Compose. It provides declarative module management, git-versioned sites, coupled image/DB schema versioning, and database backup/restore with rollback.

- **Repository**: https://github.com/rjpw/yakeroth
- **Language**: Python 3.11+
- **Package**: `pipx install git+https://github.com/rjpw/yakeroth`
- **Entry point**: `yakeroth` (Click-based CLI)

## Development Setup

```bash
# Clone and install in development mode
git clone https://github.com/rjpw/yakeroth
cd yakeroth
python3 -m venv .venv
.venv/bin/pip install -e .[dev]

# Run CLI
.venv/bin/yakeroth --help

# Run tests
.venv/bin/pytest

# Lint
.venv/bin/ruff check .
.venv/bin/mypy yakeroth/
```

## Dual-Repo Design (Critical)

**yakeroth is a tool; sites are data.** Two separate git repositories:

```
yakeroth/                    # ← User clones THIS (the tool)
├── .git/                    # yakeroth tool history
├── .gitignore               # Contains: /sites/
├── yakeroth/                # Python package
└── sites/                   # ← IGNORED by yakeroth repo
    └── mysite/              # ← SEPARATE git repo (created by `yakeroth init`)
        ├── .git/            # mysite's OWN history
        ├── modules.yml
        ├── modules.lock.yml
        └── state/image-tags.yml
```

| Action | yakeroth repo | `sites/mysite/` repo |
|--------|---------------|----------------------|
| `git pull` | Updates tool code | Unaffected |
| `yakeroth module-add` | No change | New commit: `site: add mod@branch` |
| `yakeroth sync` | No change | New commit: `site: sync modules` |
| `yakeroth build` | No change | New tag: `site/mysite/pre-build-<ts>` |
| `yakeroth up` | No change | New tag: `site/mysite/running-<ts>` |
| `yakeroth rollback` | No change | `git reset --hard` in mysite |

**Key properties:**
- Complete separation — site git history never mixes with tool history
- Portable sites — `sites/mysite/` can be copied/moved independently
- Admin backs up `sites/mysite/` (or pushes to private remote), not the yakeroth repo
- Multi-site — Each `sites/<name>/` is its own git repo with independent history
- Tool updates — `git pull` in yakeroth repo gets new CLI features; sites keep working

For agent collaboration: all git operations target `sites/mysite/.git/`, not the parent repo.

## Code Style & Conventions

| Tool | Config | Command |
|------|--------|---------|
| Ruff | `pyproject.toml` `[tool.ruff]` | `ruff check .` |
| MyPy | `pyproject.toml` `[tool.mypy]` | `mypy yakeroth/` |
| pytest | `pyproject.toml` `[tool.pytest.ini_options]` | `pytest` |

- **Line length**: 100
- **Type hints**: Required on all public functions (`disallow_untyped_defs = true`)
- **Imports**: Absolute imports within package (`from yakeroth.models import ...`)
- **Error handling**: Custom exceptions (`SyncError`, `GitError`, `DockerError`) with context

## Project Structure

```
yakeroth/
├── yakeroth/                 # Python package
│   ├── __init__.py           # Version export
│   ├── cli.py                # Click CLI — ALL commands here
│   ├── models.py             # Pydantic models (modules.yml, lock, manifest)
│   ├── git_utils.py          # Git operations (commit, tag, rollback, ls-remote)
│   ├── docker_utils.py       # Docker SDK (build, push, pull, compose, DB)
│   └── sync_modules.py       # Module sync (resolve, clone, CMake, SQL copy)
├── docker/
│   ├── Dockerfile            # Site worldserver build (fetches AC at build time)
│   └── yakeroth.Dockerfile   # Sidecar container for CI/automation
├── templates/                # Jinja2 templates for `yakeroth init`
│   ├── modules.yml.j2
│   ├── docker-compose.override.yml.j2
│   ├── .gitignore.j2
│   └── env/
│       ├── .env.j2
│       └── env.ac.j2
├── docs/
│   └── docker-compose-sites.md
├── pyproject.toml
├── README.md
├── LICENSE
└── AGENTS.md                 # This file
```
## Key Files & Responsibilities

| File | Responsibility |
|------|----------------|
| `cli.py` | All user-facing commands. Mutating commands: check git status → execute → auto-commit → tag milestones |
| `models.py` | Pydantic models for `modules.yml`, `modules.lock.yml`, `state/image-tags.yml`, `SiteConfig` |
| `sync_modules.py` | Resolves module specs → clones at locked commit → generates `ModulesSite.cmake` → copies SQL/configs. **Populates AC repo cache and writes `ac_repo`/`ac_ref`/`ac_commit` to lock file** |
| `git_utils.py` | Git operations: `ls_remote_commit`, `clone_or_update`, `commit`, `tag`, `reset_hard`, `clean_untracked` |
| `docker_utils.py` | Docker SDK: `build_image` (streams output when `stream_output=True`), `compose_up/down`, `mysqldump_all`, `mysql_restore_all`, `prune_images` |
| `common.py` | Shared utilities: `get_site_dir`, `load_config` (auto-loads from `--config` / `YAKEROTH_CONFIG` / `~/.config/yakeroth/config.yml`), AC repo cache management (`ensure_acore_cached`, `get_acore_cached_repo`) |
| `dockerfile_template.py` | Jinja2 template for site Dockerfile (COPYs cached AC repo from `acore-source/`, verifies `AC_COMMIT`, captures build logs to `/home/acore/logs/`) |
| `docker/Dockerfile` | Multi-stage build: acore-fetch (COPYs cached repo) → worldserver-builder (cmake, make, install, captures logs) → worldserver (copies logs) |
| `templates/*.j2` | Rendered by `yakeroth init` with `site` and `project_name` variables (`.gitignore.j2` includes `acore-source/`) |

## CLI Command Patterns

**All mutating commands follow this pattern:**
```python
@cli.command()
@click.argument("site")
@click.option("--force", is_flag=True, ...)
@click.pass_context
def command(ctx, site, force, ...):
    site_dir = get_site_dir(site, ctx.obj["site_dir"])
    repo = get_repo(site_dir)
    ensure_clean_working_tree(repo, force)  # Pre-check
    # ... execute operation ...
    stage_all(repo)
    git_commit(repo, f"site: <conventional message>")  # Auto-commit
    git_tag(repo, f"site/{site}/<milestone>-<timestamp>", ...)  # Milestone tags for build/up
```

**Common options:**
- `--site-dir` / `YAKEROTH_SITE_DIR` — Site directory (default: `./sites/<site>`)
- `--config` / `YAKEROTH_CONFIG` — Global config file
- `--json` — JSON output for programmatic use
- `-v/--verbose` — Debug logging

## Git Workflow for Sites

Each site directory (`sites/<site>/`) is a **git-tracked directory**:
- All site files committed (modules.yml, override, env, patches, scripts)
- `modules.lock.yml` committed for rollback fidelity
- Generated dirs gitignored: `modules/`, `sql/custom/`, `env/modules/`, `state/`
- `state/image-tags.yml` committed (manifest: git tag ↔ image digest ↔ backup prefix)
- Rollback = `git reset --hard` + optional DB restore from manifest

## Docker Image Versioning

- **Tag format**: `acore-<site>-worldserver:<site-git-sha>-<modules-lock-sha>`
- **Labels embedded**:
  - `org.azerothcore.site=<site>`
  - `org.azerothcore.site-git-sha=<full>`
  - `org.azerothcore.modules-lock-sha=<full>`
  - `org.azerothcore.db-schema-version=<int>`
  - `org.opencontainers.image.source=https://github.com/rjpw/yakeroth`
- **Milestone tags**: `site/<site>/pre-build-<ts>`, `site/<site>/running-<ts>`
- **Retention**: Keep last N builds (default 5) + all milestone tags
## AC Repo Cache & Build Reproducibility

To avoid re-fetching AzerothCore on every build and ensure reproducible builds:

- **Cache location**: `~/.cache/yakeroth/acore/<hash>/` (one per AC repo URL)
- **Populated by**: `yakeroth sync` — resolves `ac_ref` to commit SHA, clones/fetches to cache
- **Stored in lock file**: `modules.lock.yml` now includes `ac_repo`, `ac_ref`, `ac_commit` fields
- **Build uses cache**: `yakeroth build` copies cached repo to `acore-source/` in build context
- **Dockerfile COPY**: Stage 1 (acore-fetch) now `COPY acore-source/ /acore/` instead of `git clone`
- **Commit verification**: Dockerfile verifies `git rev-parse HEAD` matches `AC_COMMIT` build arg
- **Build logs captured**: `cmake.log`, `build.log`, `install.log` copied to runtime image at `/home/acore/logs/`

**Precedence for AC repo/ref**: CLI flags (`--ac-repo`/`--ac-ref`) > Global config (`~/.config/yakeroth/config.yml`) > Defaults

### Global Configuration

`load_config()` auto-loads from:
1. `--config /path/to/config.yml` (explicit CLI option)
2. `YAKEROTH_CONFIG` environment variable
3. `~/.config/yakeroth/config.yml` (default)
4. Built-in defaults

```yaml
# ~/.config/yakeroth/config.yml
ac_repo: "https://github.com/mod-playerbots/azerothcore-wotlk.git"
ac_ref: "Playerbot"
image_retention: 5
db_backup_retention: 10
```

### Build Log Streaming

`yakeroth build` now streams Docker build output to console (via `build_image(stream_output=True)`). Last 100 lines returned for debugging.

## Database Schema Coupling

- Image label `org.azerothcore.db-schema-version` set at build (0 initially, updated after db-import)
- `yakeroth up` verifies: image label vs live DB `db_version` table
- Pre-update backup: `mysqldump` all 3 DBs to `state/db-backups/pre-<ts>-*`
- Manifest (`state/image-tags.yml`) links running tag → backup prefix
- `rollback --with-db` restores exact backup from manifest

## Testing Guidelines

- **Unit tests**: Mock Docker/Git; test model validation, parsing, naming conversion
- **Integration tests**: Require Docker daemon; test `sync`, `build`, `up`/`down` cycles
- **No network calls in unit tests** — mock `git ls-remote`, Docker API
- **Test file naming**: `test_<module>.py` in `tests/`

## Common Tasks for Agents

### Adding a New CLI Command
1. Add function in `cli.py` with `@cli.command()` decorator
2. Follow mutating command pattern (git check → execute → commit → tag)
3. Add help text and option annotations
4. Update `docs/docker-compose-sites.md` with command documentation

### Modifying Module Sync Logic
1. Edit `sync_modules.py` — `resolve_module_commit`, `clone_module`, `copy_sql_files`, `generate_cmake`
2. Update `models.py` if `ModuleSpec`/`ModuleLock` fields change
3. Regenerate lock file format if schema changes (bump version)
### mod-playerbots Fork Requirement

When working with `mod-playerbots`, the standard AzerothCore repository will not work. The build must use the Playerbots fork:

```bash
yakeroth build <site> --ac-repo https://github.com/mod-playerbots/azerothcore-wotlk.git --ac-ref Playerbot
```

Or configure globally in `~/.config/yakeroth/config.yml`:
```yaml
ac_repo: "https://github.com/mod-playerbots/azerothcore-wotlk.git"
ac_ref: "Playerbot"
```

The module source remains `https://github.com/mod-playerbots/mod-playerbots.git` — only the **core repo** changes.


### Changing Docker Build
1. Edit `docker/Dockerfile` — multi-stage: acore-fetch → worldserver-builder → worldserver
2. Build args: `AC_REPO`, `AC_REF`, `SITE_MODULES_DIR`, `SITE_CMAKE_FILE`, `SITE_SQL_DIR`, `SITE_NAME`, `SITE_GIT_SHA`, `MODULES_LOCK_SHA`
3. Labels must include all `org.azerothcore.*` fields

### Updating Templates
1. Edit `templates/*.j2` — Jinja2 with `site` and `project_name` variables
2. Test with `yakeroth init testsite` and inspect generated files
3. Ensure `.gitignore.j2` covers all generated dirs

## Sidecar Mode (CI/Automation)

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /path/to/sites/mysite:/site \
  --user $(id -u):$(id -g) \
  -e GIT_AUTHOR_NAME \
  -e GIT_AUTHOR_EMAIL \
  ghcr.io/rjpw/yakeroth:latest \
  sync mysite
```

Handled in entrypoint:
- `git config --global --add safe.directory /site`
- UID/GID mapping via `--user`
- Git identity via env vars

## Configuration Naming Convention

`yakeroth config-set <site> <key> <value>` converts:
- `AllowTwoSide.Interaction.Calendar` → `AC_ALLOW_TWO_SIDE_INTERACTION_CALENDAR`
- Rules: `AC_` prefix, dots/dashes → underscores, camelCase → snake_case

Implementation in `cli.py:config_set` — uses regex for camelCase conversion.

## References

- [AzerothCore Install with Docker](https://www.azerothcore.org/wiki/install-with-docker)
- [AzerothCore Config Options](https://www.azerothcore.org/wiki/config-options)
- [Official Docker README](https://github.com/azerothcore/azerothcore-wotlk/tree/master/apps/docker)
- Project docs: `docs/docker-compose-sites.md`