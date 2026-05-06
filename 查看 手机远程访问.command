#!/bin/zsh
STATE_DIR="$HOME/.openclaw/session-viewer-remote"
INFO_FILE="$STATE_DIR/remote-info.txt"
TOKEN_FILE="$STATE_DIR/access-token.txt"
TUNNEL_PID_FILE="$STATE_DIR/cloudflared.pid"

echo "OpenClaw 手机远程访问信息"
echo ""

if [ -f "$INFO_FILE" ]; then
  cat "$INFO_FILE"
else
  echo "还没有保存过远程访问地址。"
  echo "请先双击：启动 手机远程访问.command"
fi

echo ""
if [ -f "$TOKEN_FILE" ]; then
  echo "当前访问码：$(cat "$TOKEN_FILE")"
fi

if [ -f "$TUNNEL_PID_FILE" ]; then
  PID="$(cat "$TUNNEL_PID_FILE" 2>/dev/null || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" >/dev/null 2>&1; then
    echo "远程隧道状态：运行中，PID $PID"
  else
    echo "远程隧道状态：未运行或已失效"
  fi
else
  echo "远程隧道状态：未运行"
fi

echo ""
read "?按回车关闭窗口..."
