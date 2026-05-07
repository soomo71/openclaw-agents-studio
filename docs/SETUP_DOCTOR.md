# Setup Doctor

Setup Doctor is the first-run and post-upgrade checklist for OpenClaw Agents Studio.

Open it from:

```text
Tools -> 配置自检
```

## What It Checks

- Basic services
  - Python 3
  - OpenClaw CLI
  - local Studio port
  - OpenClaw Gateway port
  - Git clone / zip install status
  - `.command` launcher permissions

- OpenClaw configuration
  - `~/.openclaw`
  - readable agent sessions
  - Terminal TUI support
  - Gateway status
  - DeepSeek fallback profile on `main`

- Multi-agent / blackhole collaboration
  - expected agent directories
  - independent session stores
  - OpenAI API-key profile detection
  - blackhole task index directory

- Obsidian / handoff system
  - OpenClaw note directory
  - handoff directories
  - blackhole shared workspace
  - task and archive directories

- First-run / upgrade state
  - records the last Studio version checked on this machine

## Safe Fix Action

The button `创建缺失目录并记录当前版本` only:

- creates missing Studio support directories
- creates missing Obsidian handoff / blackhole directories
- writes `~/.openclaw/session-viewer-state/setup.json`

It does **not** change:

- OpenClaw agents
- model settings
- auth profiles
- API keys
- session history

## OpenAI Policy

For this project, OpenAI models should use subscription-based auth when available. Setup Doctor flags any blackhole agent that has an OpenAI `api_key` auth profile, because those agents should not depend on OpenAI API keys by default.

DeepSeek should remain configured as a fallback, normally through the `main` agent.
