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
# Install (choose one)
pipx install git+https://github.com/rjpw/yakeroth
# OR
uv tool install git+https://github.com/rjpw/yakeroth

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

---

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

---

## Dual-Repo Design (Key Concept)

**yakeroth is a tool; sites are data.** Two separate git repositories:

```
yakeroth/                    # <-- YOU CLONE THIS (the tool)
├── .git/                    # yakeroth tool history
├── .gitignore               # Contains: /sites/
├── yakeroth/                # Python package
└── sites/                   # <-- IGNORED by yakeroth repo
    └── mysite/              # <-- SEPARATE git repo (created by `yakeroth init`)
        ├── .git/            # mysite's OWN history
        ├── modules.yml
        ├── modules.lock.yml
        └── state/image-tags.yml
```

| Action | yakeroth repo | `sites/mysite/` repo |
|--------|---------------|----------------------|
| `git pull` | Updates tool code | Unaffected |
| `yakeroth module-add` | No change | New commit: `site: add mod@branch` |
| `yakeroth build` | No change | New tag: `site/mysite/pre-build-<ts>` |
| `yakeroth rollback` | No change | `git reset --hard` in mysite |

Each `sites/<name>/` is a self-contained git repo — portable, backuppable, pushable to your own private remote.

---

## Documentation

- [Full reference: `docs/server-composition.md`](docs/server-composition.md)
- [Agent skill](.agents/skills/yakeroth-ops/SKILL.md)
- [AGENTS.md](AGENTS.md) — for coding agents

## Commands

```bash
yakeroth --help              # All commands
yakeroth <command> --help    # Command-specific help
```

## License

MIT