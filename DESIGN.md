# Design Notes

OpenClaw Agents Studio should feel like a compact operator console, not a marketing page. The UI is built for repeated work: scanning conversations, continuing sessions, checking agent status, and switching between desktop and mobile.

## Principles

- Keep the session content first.
- Prefer dense but readable layouts.
- Preserve the same information structure across desktop and mobile.
- Make actions clear without letting buttons dominate the screen.
- Use playful status details only when they do not interfere with the task.

## Visual Direction

- Tone: calm, precise, slightly playful.
- Primary surface: light workspace with a dark navy header band.
- Accent: purple primary actions, used sparingly.
- Cards: low-radius, functional, and separated by subtle borders.
- Typography: compact system font stack; avoid oversized text in tool panels.

## Layout

Desktop:

- Left side: sessions or blackhole task list.
- Right side: selected session or task detail.
- Tool actions live behind a compact menu when space is tight.
- Search and navigation controls should not permanently consume header space.

Mobile:

- Avoid horizontal overflow.
- The input composer and send button must always remain visible.
- Menus should close when the user taps outside them.
- Session content should open near the latest message by default.

## Pixel Studio

The blackhole collaboration panel includes a small pixel studio strip.

Rules:

- Always show all configured agents in one row when possible.
- The pixel figures are status decoration, not the only source of information.
- Selected agents are visibly active in the lineup.
- Running agents show subtle motion or color.
- Unselected agents stay in a muted "idle" or "发呆" state.
- Text labels sit below the pixel scene and must not overlap the characters.
- The pixel scene should keep stable dimensions while cards adapt around it.

## Interaction

- Archive by default; permanent delete requires a second confirmation.
- Manual intervention controls should be available for stuck blackhole agents.
- Agent ordering should be explicit and visible when sequential execution is enabled.
- Channel sync should be inferred from session metadata when possible.

## Accessibility

- Buttons need clear labels or titles.
- Focus states should remain visible.
- Avoid using color as the only status signal.
- Keep tap targets comfortable on mobile.
