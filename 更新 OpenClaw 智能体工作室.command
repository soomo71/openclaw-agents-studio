#!/bin/zsh
set -u

cd "$(dirname "$0")" || exit 1

echo "OpenClaw 智能体工作室更新中..."
echo "目录：$(pwd)"
echo

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR：没有找到 git。"
  echo "建议先安装 Xcode Command Line Tools：xcode-select --install"
  echo
  read "reply?按回车关闭窗口..."
  exit 1
fi

if [ ! -d ".git" ]; then
  echo "ERROR：当前目录不是 git 仓库，无法自动更新。"
  echo "建议从 GitHub 重新 clone openclaw-agents-studio，或确认脚本在项目根目录中。"
  echo
  read "reply?按回车关闭窗口..."
  exit 1
fi

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [ -z "$branch" ] || [ "$branch" = "HEAD" ]; then
  branch="main"
fi

echo "当前分支：$branch"
echo "当前版本：$(git describe --tags --always 2>/dev/null || git rev-parse --short HEAD)"
echo

dirty="$(git status --porcelain)"
if [ -n "$dirty" ]; then
  echo "ERROR：检测到本地有未提交改动，为避免覆盖你的文件，已停止更新。"
  echo
  echo "$dirty"
  echo
  echo "建议：先备份/提交这些改动，再重新运行本脚本。"
  read "reply?按回车关闭窗口..."
  exit 1
fi

echo "正在获取 GitHub 最新版本..."
git fetch --tags origin || {
  echo "ERROR：获取远程更新失败，请检查网络或 GitHub 权限。"
  read "reply?按回车关闭窗口..."
  exit 1
}

echo "正在快进更新..."
git pull --ff-only origin "$branch" || {
  echo "ERROR：无法快进更新。"
  echo "建议：确认当前分支与 GitHub main 分支一致，或重新 clone 一份干净版本。"
  read "reply?按回车关闭窗口..."
  exit 1
}

echo
echo "更新完成：$(git describe --tags --always 2>/dev/null || git rev-parse --short HEAD)"

viewer_label="ai.openclaw.sessionviewer"
if launchctl print "gui/$(id -u)/$viewer_label" >/dev/null 2>&1; then
  echo "正在重启本机智能体工作室服务..."
  launchctl kickstart -k "gui/$(id -u)/$viewer_label" >/dev/null 2>&1 || true
  echo "本机地址：http://127.0.0.1:8766"
else
  echo "没有检测到后台服务。需要时请双击“启动 OpenClaw 智能体工作室.command”。"
fi

echo
read "reply?按回车关闭窗口..."
