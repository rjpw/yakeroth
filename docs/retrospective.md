# Yakeroth Retrospective

> "Plan to throw one away; you will anyway." — Fred Brooks, *The Mythical Man-Month*

This document captures lessons from building yakeroth v0.4.x. It's written to guide a potential rewrite (v1.0) and to be honest about what went wrong.

---

## What We Built

A CLI tool for managing AzerothCore server compositions via Docker Compose. Key features:
- Declarative module management (`modules.yml`)
- Git-versioned sites with auto-commit/tag
- Docker image building with module compilation baked in
- Database backup/restore with rollback
- Module registry search via GitHub topics

---

## What Worked

| Aspect | Why |
|--------|-----|
| **Git-versioned sites** | Every change auto-committed and tagged; full audit trail |
| **Lock file (`modules.lock.yml`)** | Reproducible builds with exact commits |
| **Database rollback** | `rollback --with-db` works; saved us multiple times |
| **Docker Compose integration** | Standard, familiar ops interface |
| **Registry search** | GitHub topics API gives live, authoritative module discovery |

---

## What Didn't Work

### 1. Build Times (The Original Goal, Failed)

**Goal**: "Reduce server image build times"

**Reality**: 30-60 minutes per build. Every `yakeroth build` recompiles the entire AzerothCore from source.

**Root cause**: Monolithic Dockerfile that clones + configures + compiles core + modules in one stage. No artifact reuse.

### 2. Cache Invalidation by Design

The `acore-source/` directory is copied fresh into the build context every build:
```python
# commands/site.py
shutil.rmtree(ac_cache_dst)
shutil.copytree(ac_cache_src, ac_cache_dst)
```
This changes file timestamps → Docker `COPY` cache miss → full recompile.

### 3. Wrong Abstraction Layer

We built a **build tool** when we needed a **mod manager**.

- `module-add` just writes to YAML
- `sync` clones repos but doesn't understand dependencies
- `build` compiles everything, no incremental artifact cache
- No concept of "installed modules" vs "available modules"

### 4. Docker SDK Bug Chasing

Docker SDK 7.2.0 has a `decode=True` bug (`AttributeError: 'dict' object has no attribute 'decode'`). We worked around it, but it consumed disproportionate debugging time.

### 5. Hardcoded CMake Args

Our Dockerfile assumed AzerothCore's CMake options (`SERVERS=static`, `TOOLS=none`). Modern AC uses `APPS_BUILD=all`, `TOOLS_BUILD=none`, `WITHOUT_GIT=ON`. The mod-playerbots fork exposed this.

### 6. No Dependency Resolution

Modules declare `build: static` but no dependency graph. `mod-playerbots` needs `mod-ah-bot` (optional) — we don't know this.

### 7. Config/SQL Merging is Manual

Each module has `sql/` and `conf/`. We copy them but don't merge, detect conflicts, or validate.

### 8. Single Dockerfile Template

One template for all sites. Can't customize per-site without forking the template.

---

## Architectural Mistakes

### Mistake 1: Conflating Source and Build Context

```
site-dir/
├── acore-source/          # Copied fresh every build (bad)
├── modules/               # Cloned by sync
├── Dockerfile             # References acore-source/
└── docker-compose.yml
```

**Correct**: Source lives in cache (`~/.cache/yakeroth/repos/`). Build context references **artifacts**, not source.

### Mistake 2: No Artifact Model

We treat "build" as a monolithic action. We should have:
```
Artifact = (name, commit, outputs: [bin/, lib/, sql/, etc/])
```

Build = produce artifact. Sync = assemble artifacts via symlinks.

### Mistake 3: Registry as Afterthought

We added registry search (v0.4.12) *after* building the module management. Should have started with registry as the source of truth.

### Mistake 4: Profile/Environment as Afterthought

Sites have one `modules.yml`. No dev/prod/staging profiles. No config layering.

### Mistake 5: Dockerfile as Template, Not Generated

The Dockerfile is a Jinja2 template written once at `init`. It should be **generated per site** from the resolved artifact graph.

---

## Lessons Learned

### 1. Start with the Data Model

Before any CLI commands, define:
- `Artifact` (immutable, content-addressed)
- `ModuleManifest` (metadata, deps, outputs)
- `Profile` (module set + config overrides)
- `ResolutionPlan` (topological sort + conflict detection)

### 2. Separate Concerns Ruthlessly

| Service | Responsibility |
|---------|----------------|
| Registry | Discovery, metadata, versions |
| Resolver | Deps, conflicts, versions → plan |
| Artifact Cache | Build, store, retrieve artifacts |
| Assembly | Symlink farm, config merge, SQL merge |
| Docker | Generate Dockerfile from assembly, build image |

### 3. Symlinks Are the Assembly Primitive

Vortex uses hardlinks/symlinks to compose a game install from mods without copying. We should do the same:
```
site/
├── artifacts/acore-base -> ~/.cache/artifacts/acore-base/<commit>/
├── artifacts/mod-playerbots -> ~/.cache/artifacts/mod-playerbots/<commit>/
└── modules/mod-playerbots -> ~/.cache/repos/mod-playerbots/ (for CMake)
```

### 4. Build Once, Link Many

Core base image (`acore-base:<ac_commit>`) built **once per AC commit**, pushed to registry. Site builds only compile **modules** and link against base.

### 5. Generated Dockerfile > Template

```dockerfile
# Generated per site from resolution plan
FROM ghcr.io/owner/acore-base:be923cbc45c3f1fab657f91d51fda999f6b81cc5
COPY artifacts/mod-playerbots/lib/playerbots.so /azerothcore/lib/
COPY artifacts/mod-playerbots/sql/playerbots.sql /azerothcore/sql/custom/
# ...
```

### 6. Registry-First Design

All module metadata comes from registry (GitHub topics + `module.json` in repo). Local `modules.yml` only pins versions and profiles.

### 7. Explicit Config/SQL Merging

- SQL: concatenate with conflict detection (same table/column)
- Config: layered merge (base + profile + local) with schema validation

---

## Recommendations for v1.0 (Rewrite)

### Phase 0: Data Model & Registry
1. Define Pydantic models: `Artifact`, `ModuleManifest`, `Profile`, `ResolutionPlan`
2. Registry client with `module.json` parser (fallback to GitHub topics)
3. Local cache: `~/.cache/yakeroth/{registry,artifacts,repos}`

### Phase 1: Artifact Cache + Symlink Assembly
1. `sync` → resolves plan → fetches/builds missing artifacts → creates symlink farm
2. `build` → builds single artifact (core or module) in isolation
3. Artifact layout: `~/.cache/yakeroth/artifacts/<name>/<commit>/{bin,lib,sql,etc}`

### Phase 2: Profile Support + Config Merge
1. `profiles.yml` with active profile
2. Layered config merge (base → profile → local)
3. SQL merge with conflict detection

### Phase 3: Core Base Image + Generated Dockerfile
1. `acore-base` build pipeline (separate CI job)
2. Site Dockerfile generated from assembly
3. Site build = `COPY` artifacts (2-5 min)

### Phase 4: Remote Artifact Cache
1. Push/pull artifacts to GHCR/S3
2. Team sharing, CI integration

### Phase 5: Polish
1. `yakeroth doctor` — validate environment, cache, registry
2. `yakeroth migrate` — v0.4 → v1.0 migration
3. Comprehensive tests

---

## What to Keep from v0.4

- Git-versioned sites with auto-commit/tag
- Lock file (`modules.lock.yml`) for reproducibility
- Database backup/restore/rollback
- Docker Compose integration
- CLI structure (Click-based, subcommands)

---

## What to Discard

- Monolithic Dockerfile template
- `acore-source/` copy in build context
- Hardcoded CMake args
- Module management without dependency resolution
- Single `modules.yml` without profiles
- Manual SQL/config copying

---

## Final Thought

We built a build tool. We needed a mod manager.

The distinction matters: a build tool compiles source; a mod manager **assembles artifacts**.

Yakeroth v1.0 should be a mod manager that happens to build artifacts when they're missing.

---

*Written after ~15 iterations on v0.4.x. If you're reading this before starting v1.0: trust the retrospective. The architecture in `DESIGN.md` is correct. Build that.*