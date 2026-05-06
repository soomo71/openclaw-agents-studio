#!/bin/zsh
STATE_DIR="$HOME/.openclaw/session-viewer-remote"
TUNNEL_PID_FILE="$STATE_DIR/cloudflared.pid"
VIEWER_HOST="${OPENCLAW_SESSION_VIEWER_HOST:-127.0.0.1}"
VIEWER_PORT="${OPENCLAW_SESSION_VIEWER_PORT:-8766}"
LOCAL_URL="http://$VIEWER_HOST:$VIEWER_PORT"
TUNNEL_PLIST="$HOME/Library/LaunchAgents/ai.openclaw.sessionviewer.remote.plist"
LAUNCHD_DOMAIN="gui/$(id -u)"

echo "正在停止 OpenClaw 手机远程访问..."

STOPPED=0

if launchctl bootout "$LAUNCHD_DOMAIN" "$TUNNEL_PLIST" >/dev/null 2>&1; then
  echo "已停止 Cloudflare 隧道后台服务。"
  STOPPED=1
fi

if [ -f "$TUNNEL_PID_FILE" ]; then
  PID="$(cat "$TUNNEL_PID_FILE" 2>/dev/null || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" >/dev/null 2>&1; then
    kill "$PID" >/dev/null 2>&1 || true
    echo "已停止 cloudflared 隧道：$PID"
    STOPPED=1
  else
    echo "没有发现正在运行的 cloudflared 隧道。"
  fi
  rm -f "$TUNNEL_PID_FILE"
else
  echo "没有找到远程访问 PID 文件。"
fi

MATCHING_PIDS="$(ps -ax -o pid=,command= | awk -v url="$LOCAL_URL" '/cloudflared tunnel --url/ && index($0, url) { print $1 }' || true)"
for PID in ${(f)MATCHING_PIDS}; do
  if [ -n "${PID:-}" ] && kill -0 "$PID" >/dev/null 2>&1; then
    kill "$PID" >/dev/null 2>&1 || true
    echo "已停止残留 cloudflared 隧道：$PID"
    STOPPED=1
  fi
done

if [ "$STOPPED" = "0" ]; then
  echo "没有找到正在运行的远程隧道。"
fi

read "?按回车关闭窗口..."
