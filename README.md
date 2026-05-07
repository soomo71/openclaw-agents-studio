# OpenClaw Agents Studio

[中文说明](README.zh-CN.md)

OpenClaw Agents Studio is a local-first web workspace for OpenClaw sessions. It lets you inspect session history, continue channel-originated conversations, open matching TUI sessions, write Obsidian handoff notes, and coordinate multiple OpenClaw agents through a compact "blackhole collaboration" panel.

The project is extracted from a real personal workflow and cleaned for open-source use. It is designed to be copied to any folder on macOS and launched with a double-click command file.

## Features

- Session list with live updates, latest-message previews, and channel-aware labels.
- Session detail view with message sending, TUI launch, search, handoff notes, and archiving.
- Optional mobile access through Cloudflare Quick Tunnel protected by a generated 6 digit access code.
- Blackhole collaboration mode: run several OpenClaw agents in separate sessions and aggregate their progress in one task view.
- Pixel studio status layer for agent activity without replacing the functional text cards.
- Archive-first cleanup flow for sessions and blackhole tasks.
- Upgrade Guard: pre-upgrade checks and local private backups for OpenClaw config, agents, extensions, and plugin snapshots.

## Requirements

- macOS
- Python 3
- OpenClaw CLI installed and configured

You should be able to run:

```bash
openclaw --version
openclaw status
```

Mobile remote access uses `cloudflared`. If it is missing, the launcher downloads it into the local `.tools/` directory. That directory is intentionally ignored by Git.

## Quick Start

Double-click:

```text
Start OpenClaw Agents Studio.command
```

This starts:

- Local web UI: `http://127.0.0.1:8766`
- Optional Cloudflare Quick Tunnel for mobile access

Chinese launchers are also kept for convenience:

```text
启动 OpenClaw 会话工具.command
启动 手机远程访问.command
停止 手机远程访问.command
查看 手机远程访问.command
```

To run only the local server:

```bash
python3 openclaw_session_viewer.py
```

Then open:

```text
http://127.0.0.1:8766
```

## Configuration

Defaults work for a single local user. Override them with environment variables when needed:

| Variable | Default | Purpose |
|---|---|---|
| `OPENCLAW_HOME` | `~/.openclaw` | OpenClaw data directory |
| `OPENCLAW_SESSION_VIEWER_HOST` | `127.0.0.1` | Local server bind host |
| `OPENCLAW_SESSION_VIEWER_PORT` | `8766` | Local server port |
| `OPENCLAW_SESSION_VIEWER_OBSIDIAN_DIR` | `~/Documents/Obsidian Vault/OpenClaw` | Handoff and blackhole workspace directory |

Example:

```bash
export OPENCLAW_SESSION_VIEWER_PORT=8777
export OPENCLAW_SESSION_VIEWER_OBSIDIAN_DIR="$HOME/Documents/MyVault/OpenClaw"
python3 openclaw_session_viewer.py
```

## Blackhole Collaboration

Default display order:

1. CEO
2. Guardian
3. Researcher
4. Assistant
5. Archivist

Display names are UI labels only. Keep stable OpenClaw agent IDs underneath so routing, sessions, and histories remain predictable.

If your agents use OpenAI models, prefer the subscription-based authentication flow when available. Configure a fallback model such as DeepSeek so a temporary OpenAI model/auth issue does not stop every agent.

## Setup Doctor

After the first launch, or after upgrading the project, open `Tools -> 配置自检`.

Setup Doctor checks local services, OpenClaw CLI/Gateway, session storage, multi-agent readiness, Obsidian handoff folders, and version state. Its safe fix action only creates missing support directories and records the current Studio version; it does not modify agents, models, auth profiles, API keys, or session history.

More details: [docs/SETUP_DOCTOR.md](docs/SETUP_DOCTOR.md)

## Upgrade Guard

Before upgrading OpenClaw, open `Tools -> 升级护航`.

Upgrade Guard gives you a read-only snapshot of the current OpenClaw CLI, Gateway, plugins, channel warnings, model fallback risks, and recent log signals. Its backup action copies key local OpenClaw files into `~/.openclaw/session-viewer-state/upgrade-backups/` for manual comparison or rollback. The backup may contain private auth and session data, so do not commit or share it.

More details: [docs/UPGRADE_GUARD.md](docs/UPGRADE_GUARD.md)

## Safety

- This tool reads local OpenClaw sessions, optional Obsidian notes, and local attachment cache files.
- Do not commit `.openclaw`, `.tools`, logs, access codes, API keys, or private notes.
- Cloudflare Quick Tunnel is suitable for temporary mobile access, not a hardened production deployment.
- For long-running public access, add stronger authentication and use a named tunnel, reverse proxy, or trusted private network.

## Project Layout

```text
.
├── openclaw_session_viewer.py
├── Start OpenClaw Agents Studio.command
├── Start Mobile Remote Access.command
├── Stop Mobile Remote Access.command
├── Show Mobile Remote Access.command
├── README.md
├── README.zh-CN.md
├── DESIGN.md
├── LICENSE
├── SECURITY.md
├── AUTHORS.md
├── CONTRIBUTING.md
└── docs/
    ├── OPEN_SOURCE_CHECKLIST.md
    ├── SETUP_DOCTOR.md
    └── UPGRADE_GUARD.md
```

## Development

Syntax check:

```bash
python3 -m py_compile openclaw_session_viewer.py
```

Privacy scan before publishing:

```bash
rg -n "password|passwd|token|secret|OPENCLAW_GATEWAY_TOKEN|trycloudflare|/Users/[^/]+|wxid_|@im.wechat|accountId|chat_id" .
```

## License

MIT License. See [LICENSE](LICENSE).
