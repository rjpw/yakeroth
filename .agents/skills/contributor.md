---
name: contributor
description: Development principles and conventions for contributing to yakeroth
version: 1.0
---

# Yakeroth Contributor Skill

## Purpose & When to Use

Use this skill when making code changes to the yakeroth tool itself (not operating sites). Covers development setup, code conventions, testing, and contribution workflow.

---

## Development Setup

```bash
# Clone and install in dev mode
git clone https://github.com/rjpw/yakeroth
cd yakeroth
python3 -m venv .venv
.venv/bin/pip install -e .[dev]

# Run CLI
.venv/bin/yakeroth --help

# Test
.venv/bin/pytest

# Lint
.venv/bin/ruff check .
.venv/bin/mypy yakeroth/
```

---

## Code Conventions

| Rule | Standard |
|------|----------|
| **Line length** | 100 (Ruff) |
| **Type hints** | Required on public functions |
| **Imports** | Absolute within package (`from yakeroth.models import ...`) |
| **Errors** | Custom exceptions (`SyncError`, `GitError`, `DockerError`) |
| **Mutating CLI pattern** | Check git status → execute → auto-commit → tag milestones |

### Project Structure

```
yakeroth/
├── cli.py                 # Click command groups & entry point
├── commands/
│   ├── site.py            # Site lifecycle commands (build, up, down, etc.)
│   ├── module.py          # Module management (add, update, remove, sync)
│   ├── config.py          # Config commands (config-set)
│   ├── db.py              # Database commands (backup, restore, schema)
│   ├── image.py           # Image commands (push, pull, prune, info)
│   └── rollback.py        # Rollback & history
├── models.py              # Pydantic models for config files
├── sync_modules.py        # Module resolution, cloning, CMake generation
├── git_utils.py           # Git operations (commit, tag, rollback)
├── docker_utils.py        # Docker SDK (build, compose, DB backup/restore)
├── dockerfile_template.py # Jinja2 template for site Dockerfile
├── embedded_templates.py  # Other Jinja2 templates (compose override, etc.)
├── common.py              # Shared utilities (config loading, paths)
└── templates/             # Jinja2 templates for `yakeroth init`
```

---

## Testing

- **Investigation**: Output is the proof; no tests needed.
- **Bug**: A failing test or user report is the repro; add regression test only when no existing test covers the path.
- **Feature**: Prove via throwaway script; new tests ONLY for uncertain edges or on request.
- **Azerothcore image build**: Don't assume you are on a beefy machine; where an image build is expected, ask for approval first.
- **New tests MUST**: Catch plausible consumer-visible bugs; be deterministic, isolated, full-suite-safe.
- **NEVER test**: Wiring, echoes, source text, incidental defaults, tautologies, bare not-throw, length-grew.
- **Tests your change breaks**: Update contract tests; delete wording/implementation ones regardless of author.

---

## CLI Command Patterns

### Mutating Commands (Auto-commit + Tag)

```python
@click.command()
@click.option("--force", is_flag=True, help="Bypass clean working tree check")
def my_command(site: str, force: bool):
    repo = get_repo(site_dir)
    if not force:
        ensure_clean_working_tree(repo)

    # ... execute operation ...

    # Auto-commit
    stage_all(repo)
    git_commit(repo, f"site: {description}")

    # Tag milestone
    git_tag(repo, f"site/{site}/milestone-{timestamp}", f"Description")
```

### Read-Only Commands

```python
@click.command()
def my_command(site: str):
    # No git status check needed
    # Just read and display
    pass
```

---

## Error Handling

```python
# Custom exceptions in yakeroth/exceptions.py (or inline)
class SyncError(Exception): pass
class GitError(Exception): pass
class DockerError(Exception): pass

# In commands: wrap and raise click.ClickException
try:
    result = risky_operation()
except DockerError as e:
    raise click.ClickException(f"Docker error: {e}") from e
```

---

## Docker Build Args & Labels

### Required Build Args (Passed to Dockerfile)

```python
build_args = {
    "AC_REPO": "...",           # AzerothCore repo URL
    "AC_REF": "...",            # AzerothCore git ref
    "SITE_MODULES_DIR": "modules",
    "SITE_CMAKE_FILE": "ModulesSite.cmake",
    "SITE_SQL_DIR": "sql",
    "SITE_NAME": site,
    "SITE_GIT_SHA": "...",
    "MODULES_LOCK_SHA": "...",
    "BUILD_DATE": "...",        # ISO8601 UTC
}
```

### Required Image Labels

```python
labels = {
    "org.azerothcore.site": site,
    "org.azerothcore.site-git-sha": "...",
    "org.azerothcore.modules-lock-sha": "...",
    "org.azerothcore.db-schema-version": "0",  # Updated after db-import
}
```

---

## Git Utilities (git_utils.py)

| Function | Purpose |
|----------|---------|
| `get_repo(path)` | Get `git.Repo` object |
| `ensure_clean_working_tree(repo)` | Raise if dirty |
| `get_short_sha(repo)` | Short commit SHA (12 chars) |
| `get_file_sha(repo, filepath)` | File SHA |
| `stage_all(repo)` | `git add -A` |
| `git_commit(repo, message)` | Commit with message |
| `git_tag(repo, tag, message)` | Annotated tag |
| `git_reset_hard(repo, target)` | Hard reset to tag/commit |

---

## Docker Utilities (docker_utils.py)

| Function | Purpose |
|----------|---------|
| `get_client()` | Docker SDK client |
| `build_image(client, context, dockerfile, tag, build_args, labels, no_cache)` | Build image, return (image_id, digest) |
| `compose_up(site_dir, project_name)` | `docker compose up -d` |
| `compose_down(site_dir, project_name)` | `docker compose down` |
| `backup_databases(site_dir, label)` | mysqldump all 3 DBs |
| `restore_databases(site_dir, prefix)` | Restore all 3 DBs |

---

## Common Utilities (common.py)

| Function | Purpose |
|----------|---------|
| `get_site_dir(site, base_dir)` | Resolve site directory (appends site name if base is parent sites dir) |
| `load_config(config_path)` | Load global config (`SiteConfig` model) |
| `load_image_tags(site_dir)` | Load manifest (`ImageTagsManifest`) |
| `save_image_tags(site_dir, manifest)` | Save manifest |

---

## Module Sync Flow (sync_modules.py)

1. **Read** `modules.yml` → `ModulesFile`
2. **Resolve** each module: `git ls-remote` to get commit SHA for branch
3. **Write** `modules.lock.yml` with exact commits → `ModulesLockFile`
4. **Clone** each module to `modules/<name>/` at locked commit
5. **Generate** `ModulesSite.cmake` with `add_subdirectory()` entries
6. **Copy** module SQL files to `sql/custom/{db_auth,db_characters,db_world}/`
7. **Copy** module configs to `env/modules/`

---

## Contribution Workflow

1. **Branch** from `main` with descriptive name (`feat/...`, `fix/...`, `docs/...`, `chore/...`)
2. **Develop** with dev install (`.venv/bin/pip install -e .[dev]`)
3. **Verify** changes:
   - `ruff check .`
   - `mypy yakeroth/`
   - `pytest`
   - Manual test with `yakeroth <cmd> ...`
4. **Commit** with conventional message:
   - `feat: <description>` — New feature
   - `fix: <description>` — Bug fix
   - `docs: <description>` — Documentation only
   - `chore: <description>` — Maintenance (deps, version bump, etc.)
   - `refactor: <description>` — Code restructuring
5. **Push** and open PR

---

## Version Bumping

```bash
# pyproject.toml and yakeroth/__init__.py must match
sed -i 's/version = "X.Y.Z"/version = "X.Y.Z"/' pyproject.toml
sed -i 's/__version__ = "X.Y.Z"/__version__ = "X.Y.Z"/' yakeroth/__init__.py
git commit -am "chore: bump version to X.Y.Z"
```

---

## Key Files Quick Reference

| File | Purpose |
|------|---------|
| `docker/Dockerfile` | Multi-stage site worldserver build (builder → runtime) |
| `templates/*.j2` | Jinja2 templates for `yakeroth init` (compose override, etc.) |
| `yakeroth/dockerfile_template.py` | Dockerfile template string (used by `init`) |
| `yakeroth/embedded_templates.py` | Other embedded templates |
| `docs/server-composition.md` | Full operational documentation |
| `README.md` | Quick start & overview |

---

## Hard Stops

- NEVER commit directly to `main` (use PRs)
- NEVER skip `ensure_clean_working_tree` on mutating commands (unless `--force` explicit)
- NEVER hardcode paths — use `get_site_dir()`, `site_dir.resolve()`, etc.
- NEVER use `sed`/`perl`/Python for file edits — use `edit` tool
- NEVER avoidable allocation/copying in compiled code paths
- Tests: NEVER test wiring, echoes, source text, tautologies, bare not-throw