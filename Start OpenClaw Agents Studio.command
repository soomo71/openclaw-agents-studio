#!/bin/zsh
SCRIPT_DIR="${0:A:h}"
TARGET="$SCRIPT_DIR/启动 OpenClaw 会话工具.command"

if [ ! -f "$TARGET" ]; then
  echo "Cannot find launcher: $TARGET"
  read "?Press Enter to close..."
  exit 1
fi

chmod +x "$TARGET" >/dev/null 2>&1 || true
exec "$TARGET"
