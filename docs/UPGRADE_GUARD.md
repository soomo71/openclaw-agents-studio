# Upgrade Guard

Upgrade Guard is the pre-upgrade safety workflow for OpenClaw Agents Studio.

Open it from:

```text
Tools -> 升级护航
```

## Purpose

OpenClaw upgrades can change the host runtime, plugin loading behavior, channel plugins, model routing, and agent auth expectations. Upgrade Guard gives you a stable checklist before and after upgrading, without changing OpenClaw configuration automatically.

## Read-Only Checks

Upgrade Guard shows:

- OpenClaw CLI version
- Gateway port status
- whether `~/.openclaw/openclaw.json` is present
- whether a recent pre-upgrade backup exists
- configured plugins in `openclaw.json`
- extension and npm channel plugin snapshots
- recent log signals for common upgrade regressions
- channel binding warnings
- OpenAI model agents that lack DeepSeek fallback
- OpenAI API-key auth profiles that conflict with the subscription-first policy

## Pre-Upgrade Backup

The button `创建升级前备份` copies key local files into:

```text
~/.openclaw/session-viewer-state/upgrade-backups/<timestamp>/
```

It may include private data such as auth profiles and session indexes. Do not commit or share this directory.

The backup currently includes:

- `~/.openclaw/openclaw.json`
- `~/.openclaw/agents`
- `~/.openclaw/extensions`
- selected package manager lock files under `~/.openclaw/npm`
- `~/Library/LaunchAgents/ai.openclaw.gateway.plist`
- a `manifest.json` with a sanitized Upgrade Guard report

## Recommended Upgrade Flow

1. Open `Tools -> 升级护航`.
2. Create a pre-upgrade backup.
3. Record any existing warnings so you do not blame the upgrade for old issues.
4. Upgrade OpenClaw itself.
5. Restart or reload OpenClaw as required by the OpenClaw upgrade command.
6. Open Upgrade Guard again and compare the warnings.
7. Test Web UI, personal WeChat, WeCom, and blackhole collaboration separately.
8. If something breaks, use the backup for manual comparison or rollback.

## Safety Boundary

Upgrade Guard does **not**:

- upgrade OpenClaw
- restart Gateway
- edit OpenClaw config
- edit agents
- change model settings
- change auth profiles
- fix plugins automatically

It is a guardrail and backup helper, not an automatic migration tool.
