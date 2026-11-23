# Yakeroth: AzerothCore Server Composition Manager

Yakeroth eliminates the yak-shaving of manual module management for AzerothCore Docker deployments. It provides:

- **Declarative module management** via `modules.yml` (source of truth)
- **Reproducible builds** via `modules.lock.yml` (committed lock file)
- **Git-versioned sites** -- every change is a commit, rollback is `git reset`
- **Coupled image/DB schema** -- Docker image labels track schema version, compatibility verified on `up`
- **Database backup/restore** -- integrated with rollback via manifest
- **Sidecar container** -- identical CLI in CI and local development

---

## Quick Start

```bash
# Install yakeroth
pipx install git+https://github.com/rjpw/yakeroth

# Initialize a site
yakeroth init mysite

# Add modules
yakeroth module-add mysite "mod-playerbots@master"
yakeroth module-add mysite "mod-autobalance@master"

# Sync modules (clones, generates CMake, copies SQL/configs)
yakeroth sync mysite

# Build Docker image with site modules
yakeroth build mysite

# Start site
yakeroth up mysite
```

---

## Dual-Repo Design (Critical)

**yakeroth is a tool; sites are data.** Two separate git repositories:

```
yakeroth/                    # <-- YOU CLONE THIS (the tool)
├── .git/                    # yakeroth tool history
├── .gitignore               # Contains: /sites/
├── yakeroth/                # Python package
├── docker/
├── templates/
└── sites/                   # <-- IGNORED by yakeroth repo
    └── mysite/              # <-- SEPARATE git repo (created by yakeroth init)
        ├── .git/            # mysite's OWN history
        ├── modules.yml
        ├── modules.lock.yml
        └── state/image-tags.yml
```

| Action | yakeroth repo | sites/mysite/ repo |
|--------|---------------|---------------------|
| git pull | Updates tool code | Unaffected |
| yakeroth module-add | No change | New commit: site: add mod@branch |
| yakeroth sync | No change | New commit: site: sync modules |
| yakeroth build | No change | New tag: site/mysite/pre-build-<ts> |
| yakeroth up | No change | New tag: site/mysite/running-<ts> |
| yakeroth rollback | No change | git reset --hard in mysite |

Key properties:
- Complete separation -- site git history never mixes with tool history
- Portable sites -- sites/mysite/ can be copied/moved independently
- Admin backs up sites/mysite/ (or pushes to private remote), not the yakeroth repo
- Multi-site -- Each sites/<name>/ is its own git repo with independent history
- Tool updates -- git pull in yakeroth repo gets new CLI features; sites keep working

For agent collaboration: all git operations target sites/mysite/.git/, not the parent repo.

---

## Directory Structure

Each site lives in `sites/<site-name>/` (or custom location via `--site-dir`):

```
sites/
  mysite/
    .gitignore                    # Ignore built artifacts, not config
    docker-compose.override.yml   # Service overrides for this site
    modules.yml                   # Declarative module list (EDIT THIS)
    modules.lock.yml              # Resolved commit SHAs (GENERATED, COMMITTED)
    ModulesSite.cmake             # Generated CMake include (GENERATED)
    env/                          # Site-specific env files
      .env                        # Docker Compose env vars (loaded automatically)
      env.ac                      # AzerothCore server config (bind-mounted to /azerothcore/env/dist/etc)
      modules/                    # Module config files (GENERATED, bind-mounted)
    patches/                      # Optional patch files for modules
    scripts/                      # Optional custom scripts (backup-db.sh, etc.)
    sql/                          # Module SQL files (GENERATED)
      custom/
        db_auth/
        db_characters/
        db_world/
    state/                        # Runtime state (gitignored)
      last-build-sha
      container-ids
      db-schema-version
      db-backups/                 # mysqldump outputs (gitignored)
      image-tags.yml              # Manifest: git tags <-> image digests <-> backup prefixes
```

---

## Module Management

### `modules.yml` -- Source of Truth

 
```yaml
modules:
  - name: mod-playerbots
    source: https://github.com/mod-playerbots/mod-playerbots.git
    branch: master
    # commit: abc123def456  # Optional: pin to commit
    # build: static         # static|dynamic (default: static)
    # patch: playerbots.patch  # Optional: patches/playerbots.patch
    # sql:
    #   - data/sql/db_characters/mod_playerbots.sql
    #   - data/sql/db_world/mod_playerbots.sql
 
  - name: mod-autobalance
    source: https://github.com/azerothcore/mod-autobalance.git
    branch: master
```
 
> **⚠️ mod-playerbots Requires Custom AzerothCore Fork**
>
> The standard `azerothcore/azerothcore-wotlk` repository **will not work** with `mod-playerbots`. You must use the Playerbots fork at build time:
>
> ```bash
> yakeroth build mysite --ac-repo https://github.com/mod-playerbots/azerothcore-wotlk.git --ac-ref Playerbot
> ```
>
> Or set defaults in `~/.config/yakeroth/config.yml`:
> ```yaml
> ac_repo: "https://github.com/mod-playerbots/azerothcore-wotlk.git"
> ac_ref: "Playerbot"
> ```
>
> The module repository remains `https://github.com/mod-playerbots/mod-playerbots.git` — only the **core repository** changes.
>
 

**Fields:**
- `name` -- Module directory name (also used as CMake target)
- `source` -- Git repository URL
- `branch` -- Branch to track (default: `master`)
- `commit` -- Optional commit pin (resolved at sync time, written to lock file)
- `dirname` -- Custom directory name (default: `name`)
- `build` -- `static` or `dynamic` linkage (default: `static`)
- `patch` -- Patch file relative to `patches/`
- `sql` -- SQL files to copy to `sql/custom/{db_auth,db_characters,db_world}/`

### `modules.lock.yml` -- Generated Lock File

```yaml
modules:
  - name: mod-playerbots
    source: https://github.com/mod-playerbots/mod-playerbots.git
    branch: master
    commit: a1b2c3d4e5f6...  # Resolved at sync time
    dirname: mod-playerbots
    build: static
    sql:
      - data/sql/db_characters/mod_playerbots.sql
      - data/sql/db_world/mod_playerbots.sql
```

**Never edit manually.** Generated by `yakeroth sync`, committed for rollback fidelity.

### Module Commands

| Command | Description |
|---------|-------------|
| `yakeroth module-add <site> "name@branch[:commit]"` | Add module, auto-commit |
| `yakeroth module-update <site> <name> [--to branch[:commit]]` | Update module, auto-commit |
| `yakeroth module-remove <site> <name>` | Remove module, auto-commit |
| `yakeroth sync <site>` | Resolve, clone, generate CMake, copy SQL/configs |

---

## Building & Running

### Build

```bash
yakeroth build mysite [--no-cache] [--tag custom-tag] [--ac-ref master]
```

- Fetches AzerothCore source at `--ac-ref` (default: `master`)
- Builds worldserver with site modules baked in
- Tags image: `acore-mysite-worldserver:<site-sha>-<modules-lock-sha>`
- Embeds Docker labels: site, git SHAs, DB schema version
- Creates git tag: `site/mysite/pre-build-<timestamp>`
- Updates `state/image-tags.yml` manifest

### Up (Start)

```bash
yakeroth up mysite [--force]
```

1. **Compatibility check** -- Compares image's `db-schema-version` label with live DB
2. **Pre-update backup** -- `mysqldump` all 3 DBs to `state/db-backups/pre-<timestamp>-*`
3. **Start containers** -- `docker compose up -d`
4. **Git tag** -- `site/mysite/running-<timestamp>` with backup prefix in manifest

### Down (Stop)

```bash
yakeroth down mysite
```

### Logs

```bash
yakeroth logs mysite
```

---

## Image Versioning

**Tag format:** `acore-<site>-worldserver:<site-git-sha>-<modules-lock-sha>`

Example: `acore-mysite-worldserver:a1b2c3d-e5f6g7h`

**Labels embedded in image:**
```
org.azerothcore.site=mysite
org.azerothcore.site-git-sha=a1b2c3d4e5f6...
org.azerothcore.modules-lock-sha=e5f6g7h8i9j0...
org.azerothcore.db-schema-version=12345
org.opencontainers.image.created=2026-11-22T14:30:00Z
```

**Retention policy** (configurable via `SITE_IMAGE_RETENTION`):
- Keep last N successful builds (default: 5)
- Keep all milestone-tagged images (`running-*`, `pre-build-*`)
- `yakeroth prune-images mysite [--keep N] [--dry-run]`

---

## Database Management

### Schema Version Tracking

- Worldserver applies DB updates on startup (controlled by `AC_UPDATES_ENABLE_DATABASES`)
- In production: `0` (db-import container handles updates)
- In development: `1` (worldserver applies updates)
- Schema version written to `state/db-schema-version` by db-import
- Image label `org.azerothcore.db-schema-version` set at build time (updated after first db-import)

### Backup Strategy

```bash
# Manual labeled backup
yakeroth db-backup mysite --label pre-expansion

# Automatic pre-update backup (runs on yakeroth up)
# Creates: state/db-backups/pre-20261122-143000-{auth,characters,world}.sql.gz
```

**Retention:** Keep last N backups (default: 10), configurable via `SITE_DB_BACKUP_RETENTION`

### Restore

```bash
yakeroth db-restore mysite pre-20261122-143000
```

Stops containers, restores all 3 DBs, starts containers. Creates git tag `site/mysite/db-restored-<timestamp>`.

---

## Rollback

Rollback is a first-class operation. Every mutating command auto-commits and tags.

### Code Only

```bash
# Rollback to previous commit
yakeroth rollback mysite --to HEAD~1

# Rollback to specific tag
yakeroth rollback mysite --to site/mysite/pre-build-20261122-143000

# With --clean (default): removes modules/, sql/custom/, env/modules/
```

### Code + Database

```bash
# Rollback to running tag and restore matching DB backup
yakeroth rollback mysite --to site/mysite/running-20261122-143500 --with-db
```

Uses `backup_prefix` from manifest to restore exact backup files.

---

## Configuration

### Naming Convention

All server config uses `AC_` prefix with conversion:
- `AllowTwoSide.Interaction.Calendar` -> `AC_ALLOW_TWO_SIDE_INTERACTION_CALENDAR`
- `Rate.Health` -> `AC_RATE_HEALTH`
- `Log.Level` -> `AC_LOG_LEVEL`

```bash
yakeroth config-set mysite AllowTwoSide.Interaction.Calendar 1
# Writes AC_ALLOW_TWO_SIDE_INTERACTION_CALENDAR=1 to env/.env
```

### Files

| File | Purpose | Loaded By |
|------|---------|-----------|
| `env/.env` | Docker Compose env vars | `docker compose` automatically |
| `env/env.ac` | Server config (bind-mounted) | Worldserver/Authserver via `--config` |
| `env/modules/` | Module configs (generated) | Bind-mounted to `env/dist/etc/modules/` |

---

## Pre-built Database Image

Per official docs, use `acore/ac-wotlk-db:master` for instant DB startup:

```yaml
# docker-compose.override.yml
db:
  image: acore/ac-wotlk-db:master@sha256:ACTUAL_DIGEST  # Pin digest for reproducibility
```

**Volume naming:** `<project>_ac-database` (e.g., `acore-mysite_ac-database`)

---

## Sidecar Mode (CI/Automation)

Run yakeroth in a container with Docker socket access:

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

**Gotchas handled in entrypoint:**
- Docker socket mount for `build`/`push`/`image-info`
- Git identity via `GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL`
- UID/GID mapping via `--user $(id -u):$(id -g)`
- `git config --global --add safe.directory /site` on startup

---

## Agent Integration (yakeroth-ops Skill)

The `yakeroth-ops` skill teaches agents the operational workflow:

**Key decision trees:**
- Module added -> `sync` -> `build` -> `up`
- Config changed -> `up` (no rebuild)
- Schema mismatch -> `rollback --with-db`

**Guardrails:**
- Git status pre-checks on all mutating commands
- Confirmation prompts for destructive ops (`rollback --with-db`, `db-restore`, `prune-images`)
- `--force` semantics documented

**Verification steps after each operation:**
- Check logs for module load messages
- Verify git tags created
- Verify image digests in manifest
- Check `db-schema-version` matches

---

## Verification Checklist

After implementing a site:

1. `yakeroth init example` -> site created, git commit `site: init example`
2. `yakeroth module-add example "mod-playerbots@master"` -> modules.yml updated, committed
3. `yakeroth sync example` -> modules cloned, lock file generated, SQL copied, CMake generated
4. `yakeroth build example` -> image built with labels, git tag `pre-build-*`, manifest updated
5. `yakeroth up example` -> containers running, compatibility check passes, git tag `running-*`
6. Check worldserver logs for module load messages
7. `yakeroth db-backup example --label test` -> 3 backup files created
8. `yakeroth rollback example --to HEAD~1` -> code reverted, generated dirs cleaned
9. `yakeroth rollback example --to <running-tag> --with-db` -> code + DB restored
10. `yakeroth prune-images example --keep 2 --dry-run` -> correct images identified
11. `yakeroth verify-compatibility example` -> passes when matched, fails with clear message when mismatched
12. `yakeroth config-set example AllowTwoSide.Interaction.Calendar 1` -> env/.env has `AC_ALLOW_TWO_SIDE_INTERACTION_CALENDAR=1`
13. Sidecar mode works identically

---

## Assumptions & Contingencies

| Assumption | Contingency |
|------------|-------------|
| Modules compatible with AC master | Pin commit in `modules.yml` if build fails |
| Site dirs in `sites/` | Use `COMPOSE_SITE_DIR` env var |
| Static linking default | Support `build: dynamic` in `modules.yml` |
| No patches initially | Patch application in `yakeroth sync` |
| Admin's fork for version control | Support separate site repo via `SITE_GIT_REMOTE` env var |
| Docker layer caching works | `--no-cache` flag in `yakeroth build` |
| Git available on host | Document as hard requirement |
| Local disk for DB backups | `SITE_DB_BACKUP_PATH` for external storage |
| Single-host = no registry needed | `push`/`pull` for multi-host |
| `db_version` table accessible | Fallback to `state/db-schema-version` file |
| Modules may lack SQL files | Sync logs warning, continues |

---

## References

- [AzerothCore Install with Docker](https://www.azerothcore.org/wiki/install-with-docker)
- [AzerothCore Config Options](https://www.azerothcore.org/wiki/config-options)
- [Official Docker README](https://github.com/azerothcore/azerothcore-wotlk/tree/master/apps/docker)