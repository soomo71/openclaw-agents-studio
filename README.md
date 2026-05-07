# OpenClaw Agents Studio

[中文说明](README.zh-CN.md)

OpenClaw Agents Studio is a local-first workspace for OpenClaw and Codex-powered agent workflows. It brings desktop use, mobile access, personal WeChat, WeCom, OpenClaw TUI, Codex agents, multi-agent collaboration, and Obsidian handoff notes into one compact operator console.

The project is extracted from a real personal workflow and cleaned for open-source use. It is designed to be copied to any folder on macOS and launched with a double-click command file.

For a fuller Chinese product overview, see [docs/PRODUCT_OVERVIEW.zh-CN.md](docs/PRODUCT_OVERVIEW.zh-CN.md).

## What It Helps With

- Continue OpenClaw conversations that started from personal WeChat or WeCom on your desktop.
- Inspect multiple agent sessions, histories, models, and context usage in one place.
- Open the matching OpenClaw TUI session when you need the native terminal flow.
- Expose the local workspace to your phone through a temporary Cloudflare Quick Tunnel.
- Send the temporary mobile URL and access code back to your latest WeChat and WeCom direct sessions.
- Keep Obsidian handoff notes so long-running work can survive context resets.
- Coordinate several specialized agents around the same task through the blackhole collaboration panel.

## Features

- Session list with live updates, latest-message previews, and channel-aware labels.
- Channel-aware desktop bridge for personal WeChat `openclaw-weixin`, WeCom `wecom`, and other OpenClaw channel sessions.
- Codex-oriented sessions for `codex-agent`, OpenAI subscription model usage, Codex runtime continuity, and fallback model planning.
- Session detail view with message sending, attachments, TUI launch, search, handoff notes, and archiving.
- Optional mobile access through Cloudflare Quick Tunnel protected by a generated 6 digit access code.
- Mobile remote startup notifications to the latest direct personal WeChat and WeCom sessions when those channels exist locally.
- Blackhole collaboration mode: run several OpenClaw agents in separate sessions, aggregate their progress in one task view, and continue an existing task with follow-up instructions.
- Multi-perspective agent roles such as CEO, Guardian, Researcher, Assistant, and Archivist.
- Pixel studio status layer: tiny workstation characters show whether an agent is called, running, done, skipped, or idle without replacing the functional text cards.
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
启动 OpenClaw 智能体工作室.command
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

## Updates

If you installed the project with Git, double-click:

```text
Update OpenClaw Agents Studio.command
```

The updater checks for local changes first. If the working tree is clean, it fast-forwards from GitHub and restarts the local background service. If local edits are present, it stops and asks you to back up or commit them before updating.

## Configuration

Defaults work for a single local user. Override them with environment variables when needed:

| Variable | Default | Purpose |
|---|---|---|
| `OPENCLAW_HOME` | `~/.openclaw` | OpenClaw data directory |
| `OPENCLAW_SESSION_VIEWER_HOST` | `127.0.0.1` | Local server bind host |
| `OPENCLAW_SESSION_VIEWER_PORT` | `8766` | Local server port |
| `OPENCLAW_SESSION_VIEWER_OBSIDIAN_DIR` | `~/Documents/Obsidian Vault/OpenClaw` | Handoff and blackhole workspace directory |
| `OPENCLAW_REMOTE_NOTIFY` | `1` | Send mobile remote URL/access code to recent channel sessions after tunnel startup. Set to `0` to disable |

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

After a blackhole task is created, the bottom composer continues the current task instead of creating a new one. Mention one or more agents to target the follow-up:

```text
@守护者 @研究员 re-check risks and sources
@CEO wrap this into a final recommendation
@all add one short note each
```

Follow-up instructions are written back to the task file, and each agent keeps a short round history so previous replies are not overwritten.

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
├── Update OpenClaw Agents Studio.command
├── 启动 OpenClaw 智能体工作室.command
├── 更新 OpenClaw 智能体工作室.command
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
    ├── PRODUCT_OVERVIEW.zh-CN.md
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
