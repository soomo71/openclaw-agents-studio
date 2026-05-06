# Contributing

Thanks for considering a contribution.

## Development Setup

1. Install and configure OpenClaw.
2. Make sure Python 3 is available.
3. Run the local server:

```bash
python3 openclaw_session_viewer.py
```

4. Open `http://127.0.0.1:8766`.

## Checks

Run:

```bash
python3 -m py_compile openclaw_session_viewer.py
```

Before publishing or opening a pull request, also run the privacy checklist in `docs/OPEN_SOURCE_CHECKLIST.md`.

## Pull Request Guidelines

- Keep local secrets, tokens, logs, tunnel state, and private notes out of commits.
- Preserve the local-first design.
- Keep mobile layout usable.
- Avoid breaking existing Chinese `.command` launchers.
- Add documentation when behavior changes.

## Design Changes

Follow `DESIGN.md`. The tool should stay compact, readable, and useful for repeated session work.
