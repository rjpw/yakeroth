# Yakeroth Design Specification

> "Plan to throw one away; you will anyway." — Fred Brooks, *The Mythical Man-Month*

## Vision

Yakeroth is a **mod manager for AzerothCore servers**, not a build tool. It manages the lifecycle of modular server compositions: discovery, resolution, assembly, and deployment. The build is an implementation detail.

### Core Principles

1. **Repos are loosely coupled from builds** — Source lives in canonical locations; builds consume immutable artifacts
2. **Symlink-based assembly** — Like Vortex, use hardlinks/symlinks to compose server from artifacts without copying
3. **Registry-first** — All metadata comes from a central registry (GitHub topics today, extensible)
4. **Declarative desired state** — `modules.yml` + `profiles.yml` describe what; yakeroth figures out how
5. **Reproducible, auditable** — Every deployment traces to exact commits, registry versions, and config

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              YAKEROTH CLI                                   │
├──────────────┬──────────────┬──────────────┬──────────────┬────────────────┤
│  module-*    │   profile    │    sync      │    build     │   deploy       │
│  (discover,  │  (switch,    │  (resolve,   │  (artifacts, │  (compose,     │
│   add, info) │   list)      │   assemble)  │   cache)     │   up, down)    │
└──────┬───────┴──────┬───────┴──────┬───────┴──────┬───────┴───────┬────────┘
       │              │              │              │               │
       ▼              ▼              ▼              ▼               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            CORE SERVICES                                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │  Registry   │  │  Resolver   │  │  Artifact   │  │  Assembly        │  │
│  │  (index,    │  │  (deps,     │  │  Cache      │  │  (symlink farm,  │  │
│  │   search,   │  │   conflicts,│  │  (build,    │  │   env gen,       │  │
│  │   metadata) │  │   versions) │  │   pull,     │  │   sql merge)     │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
       │              │              │              │               │
       ▼              ▼              ▼              ▼               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           STORAGE                                           │
│  ~/.cache/yakeroth/                                                         │
│  ├── registry/           # GitHub API cache (index, manifests)             │
│  ├── artifacts/          # Immutable build outputs                         │
│  │   ├── acore-base/<commit>/        # Pre-built core (bin, lib, sql)      │
│  │   ├── mod-playerbots/<commit>/    # Module .so + sql + config           │
│  │   └── mod-ah-bot/<commit>/        # ...                                 │
│  ├── repos/              # Bare git repos (shallow, updated on demand)     │
│  │   ├── acore/          # AzerothCore fork                               │
│  │   └── modules/        # Module repos                                   │
│  └── state/              # Per-site: image-tags.yml, db-backups/          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Concepts

### 1. Artifact Cache (The Symlink Foundation)

Instead of rebuilding from source every time, **build once, link many**.

```
~/.cache/yakeroth/artifacts/
├── acore-base/
│   └── be923cbc45c3f1fab657f91d51fda999f6b81cc5/   # AC commit
│       ├── bin/worldserver
│       ├── bin/authserver
│       ├── lib/
│       ├── etc/
│       └── sql/
├── mod-playerbots/
│   └── a1b2c3d4/                 # Module commit
│       ├── lib/playerbots.so
│       ├── sql/playerbots.sql
│       └── etc/playerbots.conf.dist
└── mod-ah-bot/
    └── e5f6g7h8/
        ├── lib/ahbot.so
        └── sql/ahbot.sql
```

**Site assembly** = symlink farm pointing to artifacts:

```
site-dir/
├── artifacts/                    # Symlinks (created by `yakeroth sync`)
│   ├── acore-base -> ~/.cache/.../acore-base/be923cbc/
│   ├── mod-playerbots -> ~/.cache/.../mod-playerbots/a1b2c3d4/
│   └── mod-ah-bot -> ~/.cache/.../mod-ah-bot/e5f6g7h8/
├── modules/                      # For CMake: symlinks to module source
│   ├── mod-playerbots -> ~/.cache/.../mod-playerbots/a1b2c3d4/
│   └── mod-ah-bot -> ~/.cache/.../mod-ah-bot/e5f6g7h8/
├── sql/custom/                   # Merged SQL (generated)
├── env/                          # Merged configs (generated)
└── Dockerfile                    # References artifacts/
```

### 2. Registry-Driven Metadata

GitHub topics are the **source of truth** for discovery. Module manifests (`module.json` in repo root) provide structured metadata:

```json
{
  "name": "mod-playerbots",
  "version": "1.15.0",
  "description": "Playerbots AI for AzerothCore",
  "ac_compatibility": ["acore-rev-1-x", "acore-rev-2-x"],
  "dependencies": [
    { "name": "mod-ah-bot", "version": "^2.0", "optional": true }
  ],
  "conflicts": ["mod-simple-ai"],
  "provides": ["playerbots", "ah-bot-api"],
  "sql_files": [
    { "file": "sql/playerbots.sql", "database": "world" }
  ],
  "config_schema": {
    "playerbots.enabled": { "type": "bool", "default": true },
    "playerbots.count": { "type": "int", "default": 50, "min": 0, "max": 200 }
  },
  "cmake_options": {
    "WITH_PLAYERBOTS": "ON"
  },
  "build": {
    "type": "static",
    "artifacts": ["lib/playerbots.so", "sql/*.sql", "etc/*.conf.dist"]
  }
}
```

### 3. Profiles (Vortex-Style)

```yaml
# profiles.yml (per site)
profiles:
  dev:
    description: "Local development with GM commands"
    modules:
      - mod-playerbots@^1.15
      - mod-gm-commands@master
      - mod-debug-tools@master
    config:
      playerbots.enabled: true
      playerbots.count: 10
    db: local

  prod:
    description: "Production server"
    modules:
      - mod-playerbots@^1.15
      - mod-ah-bot@^2.0
      - mod-anti-cheat@^1.0
    config:
      playerbots.enabled: true
      playerbots.count: 200
    db: remote

  minimal:
    description: "Vanilla-like, no bots"
    modules: []
    db: local
```

```bash
yakeroth profile use prod     # Switches modules.yml, regenerates assembly
yakeroth sync                 # Resolves, fetches artifacts, builds missing
yakeroth build                # Only builds missing artifacts
yakeroth up                   # docker compose up
```

---

## Command Flow

### Discovery & Selection
```
yakeroth module-search "playerbots"           # Search registry
yakeroth module-info mod-playerbots           # Show metadata
yakeroth module-add site mod-playerbots@^1.15 # Adds to modules.yml (profile-aware)
```

### Resolution & Assembly (`sync`)
```
yakeroth sync [--profile prod] [--dry-run]
```
1. **Load** `modules.yml` + `profiles.yml` (active profile)
2. **Resolve** versions via registry (semver, latest release, branch, commit)
3. **Topological sort** dependencies (if any)
4. **Detect conflicts** (CMake targets, SQL tables, config keys)
5. **Plan** artifact fetches + builds needed
6. **Execute** (or show plan with `--dry-run`):
   - `git fetch` missing repos to `~/.cache/yakeroth/repos/`
   - Checkout exact commits
   - Build missing artifacts → `~/.cache/yakeroth/artifacts/`
   - Create symlink farm in `site-dir/artifacts/` and `site-dir/modules/`
   - Generate merged `sql/custom/` and `env/`
   - Write `modules.lock.yml` with full resolution

### Build (`build`)
```
yakeroth build [--no-cache]
```
1. Read `modules.lock.yml`
2. For each artifact not in cache: **build in isolated container**
3. Store in `~/.cache/yakeroth/artifacts/<name>/<commit>/`
4. Update symlink farm

### Deploy (`up`/`down`)
```
yakeroth up [--profile prod]
```
1. `docker compose -f docker-compose.yml -f docker-compose.override.yml up -d`
2. Health checks, DB compatibility verification

---

## Docker Build Strategy

### Two-Stage: Base + Overlay

**Stage 1: Core Base Image** (built periodically, cached globally)
```dockerfile
# Dockerfile.acore-base
FROM ubuntu:22.04 AS builder
ARG AC_REPO, AC_REF, AC_COMMIT
# ... clone, cmake, make install ...
FROM ubuntu:22.04 AS runtime
COPY --from=builder /azerothcore/install/ /azerothcore/
# Push: ghcr.io/owner/acore-base:<ac_commit>
```

**Stage 2: Site Image** (fast, only modules)
```dockerfile
# Site Dockerfile (generated)
FROM ghcr.io/owner/acore-base:be923cbc45c3f1fab657f91d51fda999f6b81cc5
COPY artifacts/mod-playerbots/lib/playerbots.so /azerothcore/lib/
COPY artifacts/mod-playerbots/sql/playerbots.sql /azerothcore/sql/custom/
COPY artifacts/mod-ah-bot/lib/ahbot.so /azerothcore/lib/
# ... config, entrypoint ...
```

**Result**: Site builds take **2-5 minutes** (copy + link) vs **30-60 minutes** (full compile).

---

## Configuration Model

### Global Config (`~/.config/yakeroth/config.yml`)
```yaml
registry:
  github_token: "${GITHUB_TOKEN}"
  cache_ttl: 3600
artifacts:
  cache_dir: "~/.cache/yakeroth/artifacts"
  retention: 10  # keep last N commits per module
repos:
  cache_dir: "~/.cache/yakeroth/repos"
  shallow: true
docker:
  registry: "ghcr.io/owner"
  buildkit: true
```

### Site Config (`site-dir/yakeroth.yml`)
```yaml
site: yakamole
ac_repo: "https://github.com/mod-playerbots/azerothcore-wotlk.git"
ac_ref: "Playerbot"
profiles:
  active: prod
  available: [dev, prod, minimal]
modules:
  - mod-playerbots@^1.15
  - mod-ah-bot@^2.0
config:
  playerbots.count: 200
```

---

## Implementation Phases

| Phase | Goal | Deliverables |
|-------|------|--------------|
| **0** (current) | Stabilize build, add registry search | ✅ `module-search`, `module-info`, fixed cmake args |
| **1** | Artifact cache + symlink assembly | `sync` creates symlink farm, `build` populates cache |
| **2** | Profile support + config merge | `profile` commands, merged sql/env |
| **3** | Core base image + fast site builds | `acore-base` build/push, generated site Dockerfile |
| **4** | Dependency resolution + conflict detection | Topological sort, CMake/SQL/config conflict detection |
| **5** | Remote artifact cache (registry) | Push/pull artifacts to GHCR/S3 for team sharing |

---

## Migration from Current

| Current | New |
|---------|-----|
| `modules.yml` (git URLs) | `modules.yml` (registry refs) + `profiles.yml` |
| `sync` → clone → cmake → make | `sync` → resolve → symlink farm |
| `build` → full compile | `build` → build missing artifacts only |
| Single Dockerfile | Base image + generated site Dockerfile |
| No config merge | Merged sql/env from artifacts |

---

## Open Questions

1. **Module manifest format** — `module.json` in repo root? `module.yml`? Embedded in CMake?
2. **Private modules** — How to auth? GitHub App? SSH keys? Local paths?
3. **SQL merging strategy** — Concatenate? Schema-aware merge? Conflict detection?
4. **Config merge** — Layered (base + profile + local override)? TOML/JSON/YAML?
5. **Artifact signing/verification** — Cosign? Checksums in lock file?
6. **Cross-site artifact sharing** — Team registry (GHCR, S3, local Nexus)?

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Clean build time | 30-60 min | **2-5 min** (after base image cached) |
| Incremental build | 10-20 min | **<30 sec** (symlink only) |
| Module add/switch | Manual edit + full rebuild | `yakeroth module-add` + `sync` (seconds) |
| Profile switch | N/A | `yakeroth profile use prod` + `sync` |
| Reproducibility | Lock file only | Full: lock + artifact cache + base image digest |