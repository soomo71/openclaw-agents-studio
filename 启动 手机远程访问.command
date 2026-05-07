#!/bin/zsh
set -u

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR" || exit 1

VIEWER_HOST="${OPENCLAW_SESSION_VIEWER_HOST:-127.0.0.1}"
VIEWER_PORT="${OPENCLAW_SESSION_VIEWER_PORT:-8766}"
LOCAL_URL="http://$VIEWER_HOST:$VIEWER_PORT"
SERVICE_PATH="$HOME/.openclaw/bin:$HOME/.openclaw/tools/node-v22.22.0/bin:$HOME/.openclaw/tools/node-v22.22.0/lib/node_modules/.bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
TOOLS_DIR="$SCRIPT_DIR/.tools"
CLOUDFLARED="$TOOLS_DIR/cloudflared"
STATE_DIR="$HOME/.openclaw/session-viewer-remote"
VIEWER_LOG="/tmp/openclaw-session-viewer.log"
TUNNEL_LOG="$STATE_DIR/cloudflared.log"
TUNNEL_PID_FILE="$STATE_DIR/cloudflared.pid"
TOKEN_FILE="$STATE_DIR/access-token.txt"
INFO_FILE="$STATE_DIR/remote-info.txt"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
VIEWER_PLIST="$LAUNCHD_DIR/ai.openclaw.sessionviewer.plist"
TUNNEL_PLIST="$LAUNCHD_DIR/ai.openclaw.sessionviewer.remote.plist"
LAUNCHD_DOMAIN="gui/$(id -u)"

mkdir -p "$TOOLS_DIR" "$STATE_DIR"
mkdir -p "$LAUNCHD_DIR"

echo "OpenClaw 手机远程访问启动中..."
echo "工具目录：$SCRIPT_DIR"
echo "本机地址：$LOCAL_URL"
echo ""

if ! command -v python3 >/dev/null 2>&1; then
  echo "缺少 Python 3，无法启动 OpenClaw 会话工具。"
  echo "建议先安装 Xcode Command Line Tools，或从 https://www.python.org/downloads/ 安装 Python 3。"
  read "?按回车关闭窗口..."
  exit 1
fi

ensure_access_token() {
  if [ ! -s "$TOKEN_FILE" ]; then
    /usr/bin/python3 - "$TOKEN_FILE" <<'PY'
import secrets
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(f"{secrets.randbelow(900000) + 100000}\n", encoding="utf-8")
try:
    path.chmod(0o600)
except OSError:
    pass
PY
  fi
  ACCESS_TOKEN="$(cat "$TOKEN_FILE" 2>/dev/null || true)"
  if [ -z "$ACCESS_TOKEN" ]; then
    echo "访问码生成失败：$TOKEN_FILE"
    read "?按回车关闭窗口..."
    exit 1
  fi
}

ensure_viewer() {
  if curl -fsS "$LOCAL_URL/api/health" >/dev/null 2>&1; then
    echo "OpenClaw 会话工具已经在运行。"
    return 0
  fi

  if lsof -tiTCP:"$VIEWER_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "端口 $VIEWER_PORT 已被其他程序占用，但不是可用的会话工具。"
    lsof -nP -iTCP:"$VIEWER_PORT" -sTCP:LISTEN
    read "?请关闭占用程序后再试。按回车关闭窗口..."
    exit 1
  fi

  echo "正在后台启动 OpenClaw 会话工具..."
  cat > "$VIEWER_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.openclaw.sessionviewer</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>-u</string>
    <string>$SCRIPT_DIR/openclaw_session_viewer.py</string>
  </array>
  <key>WorkingDirectory</key><string>$SCRIPT_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$SERVICE_PATH</string>
    <key>OPENCLAW_SESSION_VIEWER_HOST</key><string>$VIEWER_HOST</string>
    <key>OPENCLAW_SESSION_VIEWER_PORT</key><string>$VIEWER_PORT</string>
    <key>OPENCLAW_SESSION_VIEWER_OBSIDIAN_DIR</key><string>${OPENCLAW_SESSION_VIEWER_OBSIDIAN_DIR:-$HOME/Documents/Obsidian Vault/OpenClaw}</string>
  </dict>
  <key>StandardOutPath</key><string>$VIEWER_LOG</string>
  <key>StandardErrorPath</key><string>$VIEWER_LOG</string>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
PLIST
  launchctl bootout "$LAUNCHD_DOMAIN" "$VIEWER_PLIST" >/dev/null 2>&1 || true
  if ! launchctl bootstrap "$LAUNCHD_DOMAIN" "$VIEWER_PLIST" >/dev/null 2>&1; then
    echo "OpenClaw 会话工具后台服务启动失败。日志：$VIEWER_LOG"
    tail -80 "$VIEWER_LOG" 2>/dev/null
    read "?按回车关闭窗口..."
    exit 1
  fi

  for i in {1..30}; do
    if curl -fsS "$LOCAL_URL/api/health" >/dev/null 2>&1; then
      echo "OpenClaw 会话工具已启动。"
      return 0
    fi
    sleep 1
  done

  echo "OpenClaw 会话工具启动超时。日志：$VIEWER_LOG"
  tail -80 "$VIEWER_LOG" 2>/dev/null
  read "?按回车关闭窗口..."
  exit 1
}

install_cloudflared() {
  if [ -x "$CLOUDFLARED" ]; then
    return 0
  fi

  if command -v cloudflared >/dev/null 2>&1; then
    CLOUDFLARED="$(command -v cloudflared)"
    return 0
  fi

  ARCH="$(uname -m)"
  case "$ARCH" in
    arm64)
      ASSET="cloudflared-darwin-arm64.tgz"
      ;;
    x86_64)
      ASSET="cloudflared-darwin-amd64.tgz"
      ;;
    *)
      echo "暂不支持这个 Mac 架构：$ARCH"
      read "?按回车关闭窗口..."
      exit 1
      ;;
  esac

  URL="https://github.com/cloudflare/cloudflared/releases/latest/download/$ASSET"
  TMP_DIR="$(mktemp -d)"

  echo "第一次使用，需要下载 cloudflared。"
  echo "下载地址：$URL"
  echo "这一步可能需要几十秒。"

  if ! curl -L --fail --progress-bar "$URL" -o "$TMP_DIR/cloudflared.tgz"; then
    echo "cloudflared 下载失败。"
    echo "你可以稍后重试，或手动打开 Cloudflare 下载页："
    echo "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
    rm -rf "$TMP_DIR"
    read "?按回车关闭窗口..."
    exit 1
  fi

  if ! tar -xzf "$TMP_DIR/cloudflared.tgz" -C "$TMP_DIR"; then
    echo "cloudflared 解压失败。"
    rm -rf "$TMP_DIR"
    read "?按回车关闭窗口..."
    exit 1
  fi

  FOUND="$(find "$TMP_DIR" -type f -name 'cloudflared' | head -1)"
  if [ -z "$FOUND" ]; then
    echo "没有在下载包里找到 cloudflared。"
    rm -rf "$TMP_DIR"
    read "?按回车关闭窗口..."
    exit 1
  fi

  cp "$FOUND" "$CLOUDFLARED"
  chmod +x "$CLOUDFLARED"
  xattr -d com.apple.quarantine "$CLOUDFLARED" >/dev/null 2>&1 || true
  rm -rf "$TMP_DIR"
  echo "cloudflared 已安装到：$CLOUDFLARED"
}

stop_previous_tunnel() {
  launchctl bootout "$LAUNCHD_DOMAIN" "$TUNNEL_PLIST" >/dev/null 2>&1 || true
  MATCHING_PIDS="$(ps -ax -o pid=,command= | awk -v url="$LOCAL_URL" '/cloudflared tunnel --url/ && index($0, url) { print $1 }' || true)"
  if [ -f "$TUNNEL_PID_FILE" ]; then
    OLD_PID="$(cat "$TUNNEL_PID_FILE" 2>/dev/null || true)"
    if [ -n "${OLD_PID:-}" ] && kill -0 "$OLD_PID" >/dev/null 2>&1; then
      echo "检测到旧的远程访问隧道，正在关闭：$OLD_PID"
      kill "$OLD_PID" >/dev/null 2>&1 || true
      sleep 1
    fi
  fi
  for OLD_PID in ${(f)MATCHING_PIDS}; do
    if [ -n "${OLD_PID:-}" ] && kill -0 "$OLD_PID" >/dev/null 2>&1; then
      echo "检测到旧的远程访问隧道，正在关闭：$OLD_PID"
      kill "$OLD_PID" >/dev/null 2>&1 || true
      sleep 1
    fi
  done
}

start_tunnel() {
  : > "$TUNNEL_LOG"
  echo "正在启动 Cloudflare 临时隧道..."
  echo "说明：拿到远程地址后，这个窗口可以关闭；隧道会由 macOS 后台服务继续运行。"
  cat > "$TUNNEL_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.openclaw.sessionviewer.remote</string>
  <key>ProgramArguments</key>
  <array>
    <string>$CLOUDFLARED</string>
    <string>tunnel</string>
    <string>--url</string>
    <string>$LOCAL_URL</string>
  </array>
  <key>WorkingDirectory</key><string>$STATE_DIR</string>
  <key>StandardOutPath</key><string>$TUNNEL_LOG</string>
  <key>StandardErrorPath</key><string>$TUNNEL_LOG</string>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
PLIST
  if ! launchctl bootstrap "$LAUNCHD_DOMAIN" "$TUNNEL_PLIST" >/dev/null 2>&1; then
    echo "Cloudflare 隧道后台服务启动失败。日志："
    cat "$TUNNEL_LOG" 2>/dev/null
    read "?按回车关闭窗口..."
    exit 1
  fi

  REMOTE_URL=""
  for i in {1..60}; do
    REMOTE_URL="$(grep -Eo 'https://[-a-zA-Z0-9.]+\.trycloudflare\.com' "$TUNNEL_LOG" | tail -1 || true)"
    if [ -n "$REMOTE_URL" ]; then
      break
    fi
    if ! launchctl print "$LAUNCHD_DOMAIN/ai.openclaw.sessionviewer.remote" >/dev/null 2>&1; then
      echo "Cloudflare 隧道启动失败。日志："
      cat "$TUNNEL_LOG"
      read "?按回车关闭窗口..."
      exit 1
    fi
    sleep 1
  done

  if [ -z "$REMOTE_URL" ]; then
    echo "还没有拿到远程访问地址。日志："
    cat "$TUNNEL_LOG"
    read "?按回车关闭窗口..."
    exit 1
  fi

  REAL_PID="$(launchctl print "$LAUNCHD_DOMAIN/ai.openclaw.sessionviewer.remote" 2>/dev/null | awk '/pid = / {print $3; exit}' || true)"
  if [ -z "$REAL_PID" ]; then
    REAL_PID="$(ps -ax -o pid=,command= | awk -v url="$LOCAL_URL" '/cloudflared tunnel --url/ && index($0, url) { print $1 }' | tail -1 || true)"
  fi
  if [ -n "$REAL_PID" ]; then
    TUNNEL_PID="$REAL_PID"
    echo "$TUNNEL_PID" > "$TUNNEL_PID_FILE"
  fi

  echo ""
  echo "手机远程访问地址："
  echo "$REMOTE_URL"
  echo ""
  echo "访问码："
  echo "$ACCESS_TOKEN"
  echo ""
  {
    echo "OpenClaw 手机远程访问"
    echo "远程地址：$REMOTE_URL"
    echo "访问码：$ACCESS_TOKEN"
    echo "本机地址：$LOCAL_URL"
    echo "隧道 PID：$TUNNEL_PID"
    echo "日志：$TUNNEL_LOG"
    echo "更新时间：$(date '+%Y-%m-%d %H:%M:%S')"
  } > "$INFO_FILE"

  notify_channels() {
    if [ "${OPENCLAW_REMOTE_NOTIFY:-1}" = "0" ]; then
      echo "已跳过频道通知：OPENCLAW_REMOTE_NOTIFY=0"
      return 0
    fi

    echo "正在发送远程访问信息到个人微信和企业微信..."
    SERVICE_PATH="$SERVICE_PATH" /usr/bin/python3 - "$INFO_FILE" <<'PY'
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

info_file = Path(sys.argv[1]).expanduser()
home = Path.home()
openclaw_home = Path(os.environ.get("OPENCLAW_HOME", home / ".openclaw")).expanduser()
agents_dir = openclaw_home / "agents"
state_dir = openclaw_home / "session-viewer-remote"
notify_log = state_dir / "notify-last.json"

service_path = os.environ.get("SERVICE_PATH", "")
if service_path:
    os.environ["PATH"] = service_path + ":" + os.environ.get("PATH", "")
os.environ.setdefault("OPENCLAW_CONFIG_PATH", str(openclaw_home / "openclaw.json"))

def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def openclaw_bin():
    found = shutil.which("openclaw")
    if found:
        return found
    fallback = openclaw_home / "bin" / "openclaw"
    return str(fallback) if fallback.exists() else ""

def session_channel(value):
    origin = value.get("origin") or {}
    delivery = value.get("deliveryContext") or {}
    return value.get("lastChannel") or delivery.get("channel") or origin.get("provider") or ""

def session_target(value):
    origin = value.get("origin") or {}
    delivery = value.get("deliveryContext") or {}
    return value.get("lastTo") or delivery.get("to") or origin.get("to") or ""

def session_account(value):
    origin = value.get("origin") or {}
    delivery = value.get("deliveryContext") or {}
    return value.get("lastAccountId") or delivery.get("accountId") or origin.get("accountId") or ""

def session_chat_type(key, value):
    origin = value.get("origin") or {}
    return value.get("chatType") or origin.get("chatType") or ("group" if ":group:" in key else "direct")

def find_latest_direct(agent_id, channel):
    path = agents_dir / agent_id / "sessions" / "sessions.json"
    data = read_json(path)
    best = None
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        if session_channel(value) != channel:
            continue
        if session_chat_type(key, value) != "direct":
            continue
        target = session_target(value)
        if not target:
            continue
        row = {
            "agentId": agent_id,
            "channel": channel,
            "key": key,
            "target": target,
            "accountId": session_account(value),
            "updatedAt": value.get("updatedAt") or 0,
        }
        if best is None or row["updatedAt"] > best["updatedAt"]:
            best = row
    return best

def build_message():
    text = info_file.read_text(encoding="utf-8", errors="replace").strip() if info_file.exists() else ""
    lines = [line for line in text.splitlines() if line.strip()]
    values = {}
    for line in lines:
        if "：" in line:
            key, value = line.split("：", 1)
            values[key.strip()] = value.strip()
    return "\n".join([
        "OpenClaw 手机远程访问已启动",
        "",
        f"远程地址：{values.get('远程地址', '-')}",
        f"访问码：{values.get('访问码', '-')}",
        f"本机地址：{values.get('本机地址', '-')}",
        f"远程隧道状态：运行中，PID {values.get('隧道 PID', '-')}",
        f"更新时间：{values.get('更新时间', '-')}",
    ])

def send_message(target, message):
    cli = openclaw_bin()
    if not cli:
        return {"ok": False, "error": "missing openclaw cli"}
    cmd = [
        cli,
        "message",
        "send",
        "--channel",
        target["channel"],
        "--target",
        target["target"],
        "--message",
        message,
        "--json",
    ]
    if target.get("accountId"):
        cmd.extend(["--account", target["accountId"]])
    try:
        raw = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=60)
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[-1000:]}
        return {"ok": not payload.get("error"), "payload": payload}
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "error": (exc.output or str(exc))[-1000:]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

message = build_message()
targets = [
    ("个人微信", find_latest_direct("codex-agent", "openclaw-weixin")),
    ("企业微信", find_latest_direct("life-agent", "wecom")),
]
results = []
for label, target in targets:
    if not target:
        results.append({"label": label, "ok": False, "error": "没有找到可用 direct session"})
        continue
    result = send_message(target, message)
    result.update({"label": label, "channel": target["channel"], "sessionKey": target["key"]})
    results.append(result)

state_dir.mkdir(parents=True, exist_ok=True)
notify_log.write_text(json.dumps({"message": message, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
for item in results:
    status = "成功" if item.get("ok") else "失败"
    detail = item.get("error") or item.get("channel") or ""
    print(f"- {item['label']}通知{status} {detail}")
print(f"通知记录：{notify_log}")
PY
  }

  notify_channels

  printf "%s" "$REMOTE_URL" | pbcopy
  osascript -e "display notification \"访问码：$ACCESS_TOKEN，地址已复制\" with title \"OpenClaw 手机远程访问\"" >/dev/null 2>&1 || true
  echo "你可以把上面的网址发到手机浏览器打开，然后输入访问码。"
  echo "远程地址已复制到剪贴板。"
  echo "这次的信息已保存到：$INFO_FILE"
  echo "现在可以关闭这个终端窗口。"
  echo ""
  echo "隧道日志：$TUNNEL_LOG"
  echo "要停止远程访问，双击：停止 手机远程访问.command"
  echo ""

  if [ "${OPENCLAW_OPEN_LOCAL_VIEWER:-0}" = "1" ]; then
    open "$LOCAL_URL" >/dev/null 2>&1 || true
  else
    open "$REMOTE_URL" >/dev/null 2>&1 || true
  fi
}

ensure_access_token
ensure_viewer
install_cloudflared
stop_previous_tunnel
start_tunnel
