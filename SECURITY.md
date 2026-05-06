# Security Policy

OpenClaw Agents Studio is designed as a local-first helper tool. It can expose a temporary mobile web page and can read local OpenClaw session files, so treat it as a tool with access to private work data.

## Supported Use

- Local access through `127.0.0.1`.
- Temporary mobile access through Cloudflare Quick Tunnel plus the generated 6 digit access code.
- Personal or trusted-device workflows.

## Do Not Commit

Do not commit:

- `.openclaw` data
- `.tools/cloudflared`
- access tokens or remote tunnel state
- API keys
- local logs
- private Obsidian notes
- screenshots containing private conversations

## Reporting Issues

If you find a security issue, avoid posting secrets or exploit details in a public issue. Open a minimal issue first and ask for a private contact path, or use the repository owner's preferred private channel when one is available.

## Production Exposure

Cloudflare Quick Tunnel is convenient for testing, but it is not a full production access-control setup. For long-running public access, put this tool behind stronger authentication, a named tunnel, a reverse proxy, or a trusted private network.
