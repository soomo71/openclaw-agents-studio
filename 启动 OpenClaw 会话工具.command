#!/bin/zsh
SCRIPT_DIR="${0:A:h}"
REMOTE_SCRIPT="$SCRIPT_DIR/启动 手机远程访问.command"

echo "OpenClaw 智能体工作室一键启动中..."
echo "这会同时启动："
echo "- 本机 OpenClaw 智能体工作室"
echo "- 手机远程访问 Cloudflare 临时隧道"
echo ""

if [ ! -f "$REMOTE_SCRIPT" ]; then
  echo "找不到远程访问启动脚本：$REMOTE_SCRIPT"
  read "?按回车关闭窗口..."
  exit 1
fi

chmod +x "$REMOTE_SCRIPT" >/dev/null 2>&1 || true
export OPENCLAW_OPEN_LOCAL_VIEWER=1
exec "$REMOTE_SCRIPT"
