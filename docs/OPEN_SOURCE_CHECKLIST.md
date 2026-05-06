# Open Source Checklist

Use this before publishing a release or pushing to a public repository.

## Privacy

- [ ] No personal passwords, API keys, gateway tokens, or access codes.
- [ ] No real Cloudflare tunnel URLs.
- [ ] No local `.openclaw` data.
- [ ] No private Obsidian notes.
- [ ] No screenshots with private chat content.
- [ ] No bundled `.tools/cloudflared` binary.

Suggested scan:

```bash
rg -n "password|passwd|token|secret|OPENCLAW_GATEWAY_TOKEN|trycloudflare|/Users/[^/]+|wxid_|@im.wechat|accountId|chat_id" .
```

## Function

- [ ] `python3 -m py_compile openclaw_session_viewer.py` passes.
- [ ] Local launch works.
- [ ] Remote launch prints URL and 6 digit access code.
- [ ] Mobile layout shows the send button.
- [ ] Session list and blackhole task list load.
- [ ] Archive and restore flows are tested.

## Documentation

- [ ] README explains requirements.
- [ ] README lists environment variables.
- [ ] SECURITY.md warns about remote exposure.
- [ ] LICENSE is included.
- [ ] DESIGN.md matches the current UI direction.

## Release

- [ ] Tag version, for example `v0.1.0`.
- [ ] Zip the source without ignored files.
- [ ] Keep personal daily-use copy separate from the open-source project.
