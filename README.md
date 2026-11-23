# yakeroth

## CAVEATS

> **AI Disclosure**: This project was developed with significant assistance from AI coding agents (Nemotron 3 Ultra, via the omp platform). All code has been reviewed by the human author but may contain AI-generated patterns or conventions.

> **Early Stage Warning**: This project is in a *very early stage* (pre-alpha). APIs, CLI commands, file formats, and internal architecture are subject to breaking changes without notice. Do not rely on stability.

> **Personal Project Notice**: This project is purely for **personal edification and entertainment**. It is not intended for production use, public servers, or any mission-critical deployments. Use at your own risk.

> **Non-Affiliation Statement**: The project's author is not affiliated with the AzerothCore team and makes no claims as to the suitability of this project with their much larger and more remarkable achievement.

## Dependencies

This tool **depends on** `https://github.com/azerothcore/azerothcore-wotlk` — it fetches AzerothCore source at build time and compiles against it. Any site you create with yakeroth will also depend on:

- The AzerothCore core (version/commit you specify via `--ac-ref`)
- Any third-party modules you declare in `modules.yml` (e.g., `mod-playerbots`, `mod-autobalance`, etc.)

**We are not responsible for the quality, stability, security, or maintenance of those external dependencies.** If AzerothCore introduces breaking changes, or a module repo disappears, or a module is incompatible with your chosen AC version — that is outside this project's control. You are responsible for pinning versions (via `--ac-ref` and module `commit:` pins) and verifying compatibility.

---

**AzerothCore Server Composition Manager** — declarative modules, git-versioned sites, coupled image/DB schema, rollback.

## Quick Start
## Quick Start

```bash
# Install (choose one)
pipx install git+https://github.com/rjpw/yakeroth
# OR
uv tool install git+https://github.com/rjpw/yakeroth

# Initialize a site
yakeroth init mysite

# Add modules
yakeroth module-add mysite "mod-playerbots@master"
yakeroth module-add mysite "mod-autobalance@master"

# Sync (populates AC repo cache from global config), build, start
yakeroth sync mysite
yakeroth build mysite
yakeroth up mysite
```


## mod-playerbots Requires Custom AzerothCore Fork

**Important:** The standard `azerothcore/azerothcore-wotlk` repository **will not work** with `mod-playerbots`. You must use the Playerbots fork at build time:

```bash
yakeroth build mysite --ac-repo https://github.com/mod-playerbots/azerothcore-wotlk.git --ac-ref Playerbot
```

Or set defaults in `~/.config/yakeroth/config.yml`:
```yaml
ac_repo: "https://github.com/mod-playerbots/azerothcore-wotlk.git"
ac_ref: "Playerbot"
```

The module repository remains `https://github.com/mod-playerbots/mod-playerbots.git` — only the **core repository** changes.


## AC Repo Cache & Build Reproducibility

To avoid re-fetching AzerothCore on every build and ensure reproducible builds:

- **Cache location**: `~/.cache/yakeroth/acore/<hash>/` (one per AC repo URL)
- **Populated by**: `yakeroth sync` -- resolves `ac_ref` to commit SHA, clones/fetches to cache
- **Stored in lock file**: `modules.lock.yml` now includes `ac_repo`, `ac_ref`, `ac_commit` fields
- **Build uses cache**: `yakeroth build` copies cached repo to `acore-source/` in build context
- **Dockerfile COPY**: Stage 1 (acore-fetch) now `COPY acore-source/ /acore/` instead of `git clone`
- **Commit verification**: Dockerfile verifies `git rev-parse HEAD` matches `AC_COMMIT` build arg
- **Build logs captured**: `cmake.log`, `build.log`, `install.log` copied to runtime image at `/home/acore/logs/`

**Precedence for AC repo/ref**: CLI flags (`--ac-repo`/`--ac-ref`) > Global config (`~/.config/yakeroth/config.yml`) > Defaults

### Global Configuration

`yakeroth` auto-loads global config from:
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

When config is used, `yakeroth sync` and `yakeroth build` will print:
```
Using global config: ~/.config/yakeroth/config.yml
```

### Build Log Streaming

`yakeroth build` now streams Docker build output to console. Last 100 lines returned for debugging.

### Manual Build Workflow

`yakeroth build` prints a two-step manual command for debugging:

```bash
# Step 1: Copy cached AC repo to build context (required for COPY in Dockerfile)
cp -r ~/.cache/yakeroth/acore/<hash> acore-source/

# Step 2: Build (AC_COMMIT from modules.lock.yml ensures reproducibility)
docker build \
  --build-arg AC_REPO=... \
  --build-arg AC_REF=... \
  --build-arg AC_COMMIT=... \
  ...
```




```
yakeroth/                    # <-- YOU CLONE THIS (the tool)
├── .git/                    # yakeroth tool history
├── .gitignore               # Contains: /sites/
├── yakeroth/                # Python package
├── docker/
├── templates/
└── sites/                   # <-- IGNORED by yakeroth repo
    └── mysite/              # <-- SEPARATE git repo (created by `yakeroth init`)
        ├── .git/            # mysite's OWN history
        ├── modules.yml      # Your module declarations
        ├── modules.lock.yml # Resolved commits (committed)
        ├── docker-compose.override.yml
        ├── env/
        ├── state/
        │   └── image-tags.yml  # Manifest: git tags <-> image digests <-> DB backups
        └── patches/
```

| What you do | Happens in |
|-------------|------------|
| `git pull` in yakeroth | Updates tool code only |
| `yakeroth module-add` | Commits to `sites/mysite/.git/` |
| `yakeroth build` | Tags `sites/mysite/.git/` |
| `yakeroth rollback` | `git reset --hard` in `sites/mysite/.git/` |

**Each `sites/<name>/` is a self-contained git repo** — portable, backuppable, pushable to your own private remote.

## Documentation

- [Full docs](docs/docker-compose-sites.md)
- [Agent skill](.agents/skills/yakeroth-ops/SKILL.md)
- [AGENTS.md](AGENTS.md) — for coding agents

## Commands

```bash
yakeroth --help              # All commands
yakeroth <command> --help    # Command-specific help
```

## License

MIT