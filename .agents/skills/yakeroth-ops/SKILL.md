---
name: yakeroth-ops
description: Operate yakeroth sites -- git-tracked AzerothCore server compositions with declarative modules, versioned images, and coupled DB schema management
version: 1.0
---

# Yakeroth Operations Skill

## Purpose & When to Use

Use this skill when managing AzerothCore server deployments via yakeroth. Covers the full operational lifecycle: module management, config changes, building images, starting/stopping sites, database backup/restore, and rollback procedures.

**Key concept**: Every site (`sites/<name>/`) is a **git-tracked directory**. All mutating operations auto-commit and create milestone tags. Rollback is `git reset --hard` + optional DB restore.

---

## Dual-Repo Design (Critical)

**yakeroth is a tool; sites are data.** Two separate git repositories:

```
yakeroth/                    # <-- User clones THIS (the tool)
├── .git/                    # yakeroth tool history
├── .gitignore               # Contains: /sites/
├── yakeroth/                # Python package
└── sites/                   # <-- IGNORED by yakeroth repo
    └── mysite/              # <-- SEPARATE git repo (created by yakeroth init)
        ├── .git/            # mysite's OWN history
        ├── modules.yml
        ├── modules.lock.yml
        └── state/image-tags.yml
```

Action                    | yakeroth repo      | sites/mysite/ repo
--------------------------|--------------------|-------------------
git pull                  | Updates tool code  | Unaffected
yakeroth module-add       | No change          | New commit: site: add mod@branch
yakeroth sync             | No change          | New commit: site: sync modules
yakeroth build            | No change          | New tag: site/mysite/pre-build-<ts>
yakeroth up               | No change          | New tag: site/mysite/running-<ts>
yakeroth rollback         | No change          | git reset --hard in mysite

Key properties:
- Complete separation -- site git history never mixes with tool history
- Portable sites -- sites/mysite/ can be copied/moved independently
- Admin backs up sites/mysite/ (or pushes to private remote), not the yakeroth repo
- Multi-site -- Each sites/<name>/ is its own git repo with independent history
- Tool updates -- git pull in yakeroth repo gets new CLI features; sites keep working

For agent collaboration: all git operations target sites/mysite/.git/, not the parent repo.

---

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Site** | Directory under `sites/<name>/` with `modules.yml`, `docker-compose.override.yml`, `env/`, git repo |
| **modules.yml** | Source of truth -- human-editable declarative module list |
| **modules.lock.yml** | Generated lock file -- exact commit SHAs for reproducible builds (committed) |
| **Image tag** | `acore-<site>-worldserver:<site-sha>-<modules-lock-sha>` |
| **Image labels** | `org.azerothcore.site`, `.site-git-sha`, `.modules-lock-sha`, `.db-schema-version` |
| **Manifest** | `state/image-tags.yml` -- correlates git tags <-> image digests <-> DB backup prefixes |
| **Milestone tags** | `site/<site>/pre-build-<ts>`, `site/<site>/running-<ts>`, `site/<site>/db-restored-<ts>` |
| **Schema coupling** | Image label `db-schema-version` must match live DB `db_version` table on `up` |

---

## Operational Decision Trees

### Adding a Module
```
module-add -> sync -> build -> up
```
1. `yakeroth module-add <site> "mod-name@branch[:commit]"`
2. `yakeroth sync <site>` -- resolves, clones, generates CMake, copies SQL/configs
3. `yakeroth build <site> [--ac-ref branch] [--ac-repo url]`
4. `yakeroth up <site>` -- pre-update backup, compatibility check, starts containers

### Updating a Module
```
module-update -> sync -> build -> up
```
Same flow as add. Use `--to branch[:commit]` to pin.

### Removing a Module
```
module-remove -> sync -> build -> up
```

### Config Change Only (No Rebuild)
```
config-set -> up
```
```bash
yakeroth config-set <site> AllowTwoSide.Interaction.Calendar 1
# Writes AC_ALLOW_TWO_SIDE_INTERACTION_CALENDAR=1 to env/.env
yakeroth up <site>
```

### Schema Mismatch on Up
```
up fails -> verify-compatibility -> rollback --with-db
```
```bash
yakeroth verify-compatibility <site>  # Shows expected vs actual
yakeroth rollback <site> --to <running-tag> --with-db
```

---

## Command Reference

### Site Lifecycle
| Command | Description |
|---------|-------------|
| `yakeroth init <site>` | Create new site with templates, git repo, initial commit |
| `yakeroth build <site> [--no-cache] [--tag custom] [--ac-ref ref] [--ac-repo url]` | Build Docker image with versioned tags, labels, manifest entry |
| `yakeroth up <site> [--force]` | Start containers (compatibility check + pre-update backup + milestone tag) |
| `yakeroth down <site>` | Stop containers |
| `yakeroth logs <site>` | Follow container logs |

### Module Management
| Command | Description |
|---------|-------------|
| `yakeroth module-add <site> "name@branch[:commit]"` | Add module to modules.yml, auto-commit |
| `yakeroth module-update <site> <name> [--to branch[:commit]]` | Update module, auto-commit |
| `yakeroth module-remove <site> <name>` | Remove module, auto-commit |
| `yakeroth sync <site>` | Resolve commits, clone modules, generate ModulesSite.cmake, copy SQL/configs |

### Config
| Command | Description |
|---------|-------------|
| `yakeroth config-set <site> <key> <value>` | Set env var in env/.env (converts to AC_ naming) |

### Database
| Command | Description |
|---------|-------------|
| `yakeroth db-backup <site> [--label name]` | mysqldump all 3 DBs to `state/db-backups/<label>-<ts>-*` |
| `yakeroth db-restore <site> <backup-prefix>` | Stop containers, restore all 3 DBs, start containers |
| `yakeroth db-schema-version <site>` | Query live DB `db_version` table |

### Image Management
| Command | Description |
|---------|-------------|
| `yakeroth push <site> [--registry url]` | Push site images to registry |
| `yakeroth pull <site> [--registry url]` | Pull site images from registry |
| `yakeroth prune-images <site> [--keep N] [--dry-run]` | Remove old images per retention policy |
| `yakeroth image-info <site> [--tag tag]` | Show image labels, size, creation date |

### Verification & Rollback
| Command | Description |
|---------|-------------|
| `yakeroth verify-compatibility <site>` | Check image label vs live DB schema version |
| `yakeroth rollback <site> [--to tag/commit] [--with-db] [--clean/--no-clean]` | Git reset + optional DB restore + artifact cleanup |
| `yakeroth history <site>` | Show git log for site |
| `yakeroth status <site>` | Show git status (dirty, modified, untracked) |

---

## Guardrails

### Git Status Pre-Checks
**All mutating commands require clean working tree** (unless `--force`):
- `module-add`, `module-update`, `module-remove`
- `config-set`
- `build`, `up` (with `--force` bypass)
- `rollback`, `db-restore`

### Confirmation Gates (MUST Ask User)
Before executing these destructive operations:
- `rollback --with-db` -- **Destructive DB restore**. Ask: "This will OVERWRITE databases with backup data. Continue?"
- `db-restore` -- **Destructive DB restore**. Ask: "Restore databases from <prefix>? This will overwrite current data."
- `prune-images` without `--dry-run` -- **Permanent image deletion**. Ask: "Permanently remove N images?"
- Using `--force` to bypass dirty working tree or DB schema mismatch -- Explain risk, ask for confirmation.

### --force Semantics
- `build --force`: Not applicable (no `--force` on build)
- `up --force`: Bypass compatibility check AND force-recreate containers
- `module-* --force`: Bypass dirty working tree check
- `rollback --force`: Not a flag; use `--clean`/`--no-clean` for artifact handling

---

## Rollback Procedures

### Code Only (Default)
```bash
yakeroth rollback <site> --to HEAD~1           # Previous commit
yakeroth rollback <site> --to <tag>            # Specific tag
# Removes: modules/, sql/custom/, env/modules/ (via --clean default)
```

### Code + Database
```bash
yakeroth rollback <site> --to <running-tag> --with-db
# 1. Git reset to tag
# 2. Looks up backup_prefix from manifest for that tag
# 3. Restores all 3 DBs from matching backup files
# 4. Creates tag: site/<site>/db-restored-<timestamp>
```

**Prerequisite**: Backup must exist in `state/db-backups/` matching manifest entry.

---

## Verification Steps After Operations

| Operation | Verify |
|-----------|--------|
| `module-add` | `modules.yml` updated, git commit `site: add <name>@<branch>` |
| `sync` | Modules cloned to `modules/`, `modules.lock.yml` generated, `ModulesSite.cmake` created, SQL copied to `sql/custom/{db_auth,db_characters,db_world}/` |
| `build` | Image tagged `acore-<site>-worldserver:<sha>-<sha>`, labels present, git tag `pre-build-<ts>`, manifest updated |
| `up` | Containers running, compatibility check passes, git tag `running-<ts>`, manifest entry has `backup_prefix` |
| `db-backup` | 3 `.sql.gz` files in `state/db-backups/` |
| `rollback` | Site reverted, generated dirs cleaned (if `--clean`), DB restored if `--with-db` |
| `verify-compatibility` | Passes when matched, fails with clear message when mismatched |

---

## Failure Interpretation

| Error | Cause | Resolution |
|-------|-------|------------|
| "Working tree not clean" | Uncommitted changes | Commit/stash or use `--force` |
| "Could not resolve ref" | Module branch/tag doesn't exist | Check spelling, use `--ac-ref` for AC repo |
| "Build failed" | Module incompatible with AC version | Pin module commit, or change AC `--ac-ref` |
| "DB schema mismatch" | Image expects vX, DB has vY | `rollback --with-db` or `up --force` (risky) |
| "Backup prefix not found" | Manifest entry missing backup_prefix | Check `state/image-tags.yml`, ensure `up` ran successfully |
| "git ls-remote failed" | Network/auth issue | Check connectivity, GitHub token if private |

---

## Sidecar vs Local Mode

| Mode | Use Case | Command |
|------|----------|---------|
| **Local** | Development, manual ops | `yakeroth <cmd> <site>` |
| **Sidecar** | CI/CD, automation | `docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v /path/to/site:/site --user $(id -u):$(id -g) -e GIT_AUTHOR_NAME -e GIT_AUTHOR_EMAIL ghcr.io/rjpw/yakeroth:latest <cmd> <site>` |

**Sidecar gotchas handled in entrypoint:**
- Docker socket mount for build/push/image-info
- `git config --global --add safe.directory /site`
- UID/GID mapping via `--user $(id -u):$(id -g)`
- Git identity via `GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL`

---

## Config Naming Convention

`yakeroth config-set <site> <key> <value>` converts:
- `AllowTwoSide.Interaction.Calendar` -> `AC_ALLOW_TWO_SIDE_INTERACTION_CALENDAR`
- Rules: `AC_` prefix, dots/dashes -> underscores, camelCase -> snake_case

---

## Cross-Cutting Workflows

### Adding a Module with SQL
```bash
yakeroth module-add mysite "mod-playerbots@master"
# Edit modules.yml to add sql: paths if needed
yakeroth sync mysite
yakeroth build mysite
yakeroth up mysite
# Check worldserver logs for "Loading module mod-playerbots"
```

### Updating Module to Pinned Commit
```bash
yakeroth module-update mysite mod-playerbots --to master:abc123def456
yakeroth sync mysite
yakeroth build mysite
yakeroth up mysite
```

### Recovering from Failed Migration
```bash
yakeroth verify-compatibility mysite
# Shows: image expects 12345, database has 12340
yakeroth rollback mysite --to site/mysite/running-20261122-143500 --with-db
# Or if no backup: yakeroth rollback mysite --to site/mysite/pre-build-...
```


### mod-playerbots Fork Requirement

When using `mod-playerbots`, the standard AzerothCore repository will not work. You must use the Playerbots fork:

```bash
yakeroth build mysite --ac-repo https://github.com/mod-playerbots/azerothcore-wotlk.git --ac-ref Playerbot
```

Or configure globally in `~/.config/yakeroth/config.yml`:
```yaml
ac_repo: "https://github.com/mod-playerbots/azerothcore-wotlk.git"
ac_ref: "Playerbot"
```

The module source remains `https://github.com/mod-playerbots/mod-playerbots.git` — only the **core repo** changes.



## Hard Stops

**Never:**
- Edit `modules.lock.yml` manually -- always use `sync`
- Delete `state/image-tags.yml` -- it's the rollback manifest
- Run `git reset --hard` outside `yakeroth rollback` -- use the command
- Skip confirmation prompts for destructive ops
- Use `--force` without understanding the risk

**Always:**
- Verify `modules.yml` changes before `sync`
- Check `verify-compatibility` before `up` in production
- Keep `db-backup` retention configured (default 10)
- Test rollback procedures in staging first