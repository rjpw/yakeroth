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

```bash
# Install
pipx install git+https://github.com/rjpw/yakeroth

# Initialize a site
yakeroth init mysite

# Add modules
yakeroth module-add mysite "mod-playerbots@master"
yakeroth module-add mysite "mod-autobalance@master"

# Sync, build, start
yakeroth sync mysite
yakeroth build mysite
yakeroth up mysite
```

## Dual-Repo Design (Important)

**yakeroth is a tool; sites are data.** They live in separate git repositories:

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