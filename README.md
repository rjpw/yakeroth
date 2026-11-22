# yakeroth

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
yakeroth/                    # ← YOU CLONE THIS (the tool)
├── .git/                    # yakeroth tool history
├── .gitignore               # Contains: /sites/
├── yakeroth/                # Python package
├── docker/
├── templates/
└── sites/                   # ← IGNORED by yakeroth repo
    └── mysite/              # ← SEPARATE git repo (created by `yakeroth init`)
        ├── .git/            # mysite's OWN history
        ├── modules.yml      # Your module declarations
        ├── modules.lock.yml # Resolved commits (committed)
        ├── docker-compose.override.yml
        ├── env/
        ├── state/
        │   └── image-tags.yml  # Manifest: git tags ↔ image digests ↔ DB backups
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