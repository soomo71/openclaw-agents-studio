#!/usr/bin/env python3
import cgi
import html
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import queue
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STUDIO_VERSION = "0.1.4"
TOOL_DIR = Path(__file__).resolve().parent
HOST = os.environ.get("OPENCLAW_SESSION_VIEWER_HOST", "127.0.0.1")
PORT = int(os.environ.get("OPENCLAW_SESSION_VIEWER_PORT", "8766"))
OPENCLAW_HOME = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")).expanduser()
AGENTS_DIR = OPENCLAW_HOME / "agents"
STUDIO_STATE_DIR = OPENCLAW_HOME / "session-viewer-state"
SETUP_STATE_FILE = STUDIO_STATE_DIR / "setup.json"
UPGRADE_BACKUP_DIR = STUDIO_STATE_DIR / "upgrade-backups"
REMOTE_STATE_DIR = OPENCLAW_HOME / "session-viewer-remote"
REMOTE_TOKEN_FILE = REMOTE_STATE_DIR / "access-token.txt"
AUTH_COOKIE_NAME = "openclaw_session_viewer_token"
OBSIDIAN_OPENCLAW_DIR = Path(
    os.environ.get(
        "OPENCLAW_SESSION_VIEWER_OBSIDIAN_DIR",
        Path.home() / "Documents" / "Obsidian Vault" / "OpenClaw",
    )
).expanduser()
HANDOVER_DIR = OBSIDIAN_OPENCLAW_DIR / "接力摘要"
AUTO_HANDOVER_DIR = HANDOVER_DIR / "自动更新"
AUTO_STATE_FILE = AUTO_HANDOVER_DIR / ".auto_handover_state.json"
AUTO_HANDOVER_RATIO = 0.75
AUTO_HANDOVER_CHECK_SECONDS = 60
AUTO_HANDOVER_MIN_SECONDS = 600
EVENT_WATCH_SECONDS = 1.0
ATTACHMENTS_DIR = OPENCLAW_HOME / "session-viewer-attachments"
ARCHIVE_STATE_DIR = OPENCLAW_HOME / "session-viewer-archive"
ARCHIVED_SESSIONS_INDEX = ARCHIVE_STATE_DIR / "sessions.json"
ARCHIVED_BLACKHOLE_INDEX = ARCHIVE_STATE_DIR / "blackhole-tasks.json"
BLACKHOLE_DIR = OBSIDIAN_OPENCLAW_DIR / "OpenClaw Agents黑洞"
BLACKHOLE_SHARED_DIR = BLACKHOLE_DIR / "共享协同空间"
BLACKHOLE_TASKS_DIR = BLACKHOLE_SHARED_DIR / "黑洞任务"
BLACKHOLE_ARCHIVE_DIR = BLACKHOLE_TASKS_DIR / "归档"
BLACKHOLE_STATE_DIR = OPENCLAW_HOME / "session-viewer-blackhole"
BLACKHOLE_TASKS_INDEX = BLACKHOLE_STATE_DIR / "tasks.json"
BLACKHOLE_LEGACY_TASKS_INDEX = BLACKHOLE_TASKS_DIR / "tasks.json"
EXTRA_PATHS = [
    str(OPENCLAW_HOME / "bin"),
    str(OPENCLAW_HOME / "tools" / "node-v22.22.0" / "bin"),
    str(OPENCLAW_HOME / "tools" / "node-v22.22.0" / "lib" / "node_modules" / ".bin"),
    str(Path.home() / "Library" / "pnpm" / "global" / "5" / "node_modules" / ".bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
]
os.environ["PATH"] = ":".join([path for path in EXTRA_PATHS if path]) + ":" + os.environ.get("PATH", "")
BLACKHOLE_AGENT_DEFS = [
    {"id": "executor-agent", "label": "CEO", "role": "executor"},
    {"id": "guardian-agent", "label": "守护者", "role": "guardian"},
    {"id": "researcher-agent", "label": "研究员", "role": "researcher"},
    {"id": "life-agent", "label": "小助理", "role": "life"},
    {"id": "memory-agent", "label": "档案师", "role": "memory"},
]
BLACKHOLE_DEFAULT_AGENTS = ["guardian-agent", "memory-agent", "researcher-agent"]
BLACKHOLE_REQUIRED_FALLBACK_MODEL = "deepseek/deepseek-v4-flash"
BLACKHOLE_FALLBACK_AGENT_ID = "main"
BLACKHOLE_TERMINAL_STATUSES = {"done", "error", "skipped", "cancelled"}


def run(cmd, timeout=180):
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        return exc.output or str(exc)
    except Exception as exc:
        return str(exc)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def archive_timestamp():
    return time.strftime("%Y%m%d-%H%M%S")


def unique_path(path):
    path = Path(path)
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    return parent / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"


def move_if_exists(source, target):
    source = Path(source)
    if not source.exists():
        return ""
    target = unique_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return str(target)


def openclaw_cli():
    found = shutil.which("openclaw")
    if found:
        return found
    fallback = OPENCLAW_HOME / "bin" / "openclaw"
    return str(fallback) if fallback.exists() else ""


def level_worst(items):
    order = {"ok": 0, "info": 0, "warn": 1, "error": 2}
    worst = "ok"
    for item in items:
        if order.get(item.get("level"), 0) > order.get(worst, 0):
            worst = item.get("level")
    return worst


def check_item(level, title, detail="", action="", fixable=False, key=""):
    return {
        "level": level,
        "title": title,
        "detail": detail,
        "action": action,
        "fixable": bool(fixable),
        "key": key,
    }


def can_connect_tcp(host, port, timeout=0.7):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def command_script_files():
    return sorted(TOOL_DIR.glob("*.command"))


def openclaw_status_ok(status_text):
    signals = (
        "Connectivity probe: ok",
        "Gateway online",
        "reachable",
        "LaunchAgent running",
        "Runtime: running",
        "Gateway: online",
    )
    return any(signal in status_text for signal in signals)


def auth_profiles_for_agent(agent_id):
    path = AGENTS_DIR / agent_id / "agent" / "auth-profiles.json"
    data = read_json(path) or {}
    return data.get("profiles") or {}


def has_openai_api_key_profile(agent_id):
    for profile in auth_profiles_for_agent(agent_id).values():
        if not isinstance(profile, dict):
            continue
        provider = (profile.get("provider") or "").lower()
        kind = (profile.get("type") or "").lower()
        if provider == "openai" and kind == "api_key":
            return True
    return False


def has_deepseek_profile(agent_id="main"):
    for profile in auth_profiles_for_agent(agent_id).values():
        if not isinstance(profile, dict):
            continue
        if (profile.get("provider") or "").lower() == "deepseek":
            return True
    return False


def path_write_state(path):
    path = Path(path)
    if path.exists():
        return "ok" if os.access(path, os.W_OK) else "error"
    parent = path.parent
    if parent.exists() and os.access(parent, os.W_OK):
        return "missing-fixable"
    return "missing"


def setup_state():
    return read_json(SETUP_STATE_FILE) or {}


def setup_doctor_report():
    state = setup_state()
    sections = []
    openclaw_bin = openclaw_cli()
    sessions = session_stores()
    session_count = sum(len(data) for _, _, data in sessions)
    needs_setup = not state.get("setupCompleted") or state.get("lastSeenVersion") != STUDIO_VERSION

    basic = [
        check_item("ok", "Python 3 可用", sys.version.split()[0]),
    ]
    if openclaw_bin:
        version = run([openclaw_bin, "--version"], timeout=8).strip()
        basic.append(check_item("ok", "OpenClaw CLI 已安装", version or openclaw_bin))
    else:
        basic.append(check_item(
            "error",
            "缺少 OpenClaw CLI",
            "没有在 PATH 中找到 openclaw 命令。",
            "安装 OpenClaw 后，打开新终端确认 openclaw --version 能正常输出。",
        ))
    if (TOOL_DIR / ".git").exists():
        remote = run(["git", "-C", str(TOOL_DIR), "remote", "get-url", "origin"], timeout=4).strip()
        basic.append(check_item("ok", "项目目录是 Git 仓库", remote or str(TOOL_DIR)))
    else:
        basic.append(check_item(
            "warn",
            "项目目录不是 Git 仓库",
            str(TOOL_DIR),
            "如果想一键升级，建议用 git clone 安装；下载 zip 也能使用，但不能直接 git pull。",
        ))
    bad_scripts = [path.name for path in command_script_files() if not os.access(path, os.X_OK)]
    if bad_scripts:
        basic.append(check_item(
            "warn",
            "部分启动脚本不可执行",
            "、".join(bad_scripts),
            "在终端运行 chmod +x *.command，或重新下载发布包。",
        ))
    else:
        basic.append(check_item("ok", "启动脚本权限正常", f"{len(command_script_files())} 个 .command 文件"))
    if can_connect_tcp("127.0.0.1", PORT):
        basic.append(check_item("ok", "小工具端口在线", f"127.0.0.1:{PORT}"))
    else:
        basic.append(check_item("warn", "小工具端口未检测到监听", f"127.0.0.1:{PORT}", "如果你正在看这个页面，可以忽略；否则请重新启动小工具。"))
    if can_connect_tcp("127.0.0.1", 18789):
        basic.append(check_item("ok", "OpenClaw Gateway 端口在线", "127.0.0.1:18789"))
    else:
        basic.append(check_item("warn", "OpenClaw Gateway 端口未在线", "127.0.0.1:18789", "如果发送失败，请运行 openclaw status 或启动 gateway。"))
    sections.append({"id": "basic", "title": "基础服务", "items": basic, "level": level_worst(basic)})

    config = []
    if OPENCLAW_HOME.exists():
        config.append(check_item("ok", "OpenClaw 数据目录存在", str(OPENCLAW_HOME)))
    else:
        config.append(check_item("error", "缺少 OpenClaw 数据目录", str(OPENCLAW_HOME), "先运行 openclaw setup 或完成一次 OpenClaw 配置。"))
    if sessions:
        config.append(check_item("ok", "已发现会话存储", f"{len(sessions)} 个 agent，{session_count} 个 session"))
    else:
        config.append(check_item("warn", "还没有发现 OpenClaw 会话", str(AGENTS_DIR), "先用 OpenClaw TUI、网页或频道端发起一次对话。"))
    if openclaw_bin:
        status_text = run([openclaw_bin, "status"], timeout=8)
        if openclaw_status_ok(status_text) or can_connect_tcp("127.0.0.1", 18789):
            config.append(check_item("ok", "Gateway 状态可用", "openclaw status 或端口探测通过。"))
        else:
            config.append(check_item("warn", "Gateway 状态需要确认", "没有识别到明确在线状态。", "运行 openclaw status 查看详情；必要时重启 gateway。"))
    if sys.platform == "darwin" and shutil.which("osascript"):
        config.append(check_item("ok", "TUI 打开能力可用", "macOS Terminal + osascript"))
    else:
        config.append(check_item("warn", "TUI 自动打开能力受限", sys.platform, "非 macOS 环境请手动复制 session key。"))
    if has_deepseek_profile("main"):
        config.append(check_item("ok", "DeepSeek 兜底可用", "main agent 存在 DeepSeek auth profile。"))
    else:
        config.append(check_item("warn", "DeepSeek 兜底未确认", "main agent 未发现 DeepSeek auth profile。", "建议至少给 main 配置 DeepSeek，OpenAI 订阅不可用时可兜底。"))
    sections.append({"id": "openclaw", "title": "OpenClaw 配置", "items": config, "level": level_worst(config)})

    multi = []
    for agent in BLACKHOLE_AGENT_DEFS:
        agent_id = agent["id"]
        agent_dir = AGENTS_DIR / agent_id
        sessions_file = agent_dir / "sessions" / "sessions.json"
        if agent_dir.exists():
            detail = "会话存储已存在" if sessions_file.exists() else "agent 目录存在，但 sessions.json 尚未生成"
            multi.append(check_item("ok" if sessions_file.exists() else "warn", f"{agent['label']} `{agent_id}`", detail, "首次运行该 agent 后会生成 session 记录。" if not sessions_file.exists() else ""))
        else:
            multi.append(check_item("warn", f"缺少 {agent['label']} `{agent_id}`", str(agent_dir), f"需要黑洞协作完整体验时，请先在 OpenClaw 中创建 {agent_id}。"))
        if has_openai_api_key_profile(agent_id):
            multi.append(check_item("error", f"{agent['label']} 检测到 OpenAI API key profile", agent_id, "本项目约定 OpenAI 模型必须走订阅方式；请移除该 agent 的 OpenAI API key profile。"))
    if BLACKHOLE_STATE_DIR.exists():
        multi.append(check_item("ok", "黑洞任务索引目录存在", str(BLACKHOLE_STATE_DIR)))
    else:
        multi.append(check_item("warn", "缺少黑洞任务索引目录", str(BLACKHOLE_STATE_DIR), "可以由配置自检创建。", True, "blackhole-state"))
    sections.append({"id": "multi-agent", "title": "多 Agent / 黑洞协作", "items": multi, "level": level_worst(multi)})

    obsidian = []
    obsidian_paths = [
        ("OpenClaw 笔记目录", OBSIDIAN_OPENCLAW_DIR, "obsidian-openclaw"),
        ("接力摘要目录", HANDOVER_DIR, "handover"),
        ("自动接力目录", AUTO_HANDOVER_DIR, "auto-handover"),
        ("黑洞共享空间", BLACKHOLE_SHARED_DIR, "blackhole-shared"),
        ("黑洞任务目录", BLACKHOLE_TASKS_DIR, "blackhole-tasks"),
        ("黑洞归档目录", BLACKHOLE_ARCHIVE_DIR, "blackhole-archive"),
    ]
    for title, path, key in obsidian_paths:
        state_text = path_write_state(path)
        if state_text == "ok":
            obsidian.append(check_item("ok", title, str(path)))
        elif state_text == "missing-fixable":
            obsidian.append(check_item("warn", f"缺少{title}", str(path), "可以由配置自检创建。", True, key))
        else:
            obsidian.append(check_item("warn", f"缺少{title}", str(path), "请先确认 Obsidian Vault 路径，或设置 OPENCLAW_SESSION_VIEWER_OBSIDIAN_DIR。"))
    sections.append({"id": "obsidian", "title": "Obsidian / 接力系统", "items": obsidian, "level": level_worst(obsidian)})

    state_items = []
    if needs_setup:
        reason = "首次使用" if not state.get("setupCompleted") else f"已从 {state.get('lastSeenVersion')} 升级到 {STUDIO_VERSION}"
        state_items.append(check_item("warn", "建议运行配置自检确认", reason, "点击“创建缺失目录并记录当前版本”完成本机初始化。", True, "state"))
    else:
        state_items.append(check_item("ok", "本机初始化记录正常", f"lastSeenVersion={state.get('lastSeenVersion')}"))
    sections.append({"id": "state", "title": "首次启动 / 升级状态", "items": state_items, "level": level_worst(state_items)})

    worst = level_worst([{"level": section["level"]} for section in sections])
    return {
        "ok": worst != "error",
        "level": worst,
        "version": STUDIO_VERSION,
        "needsSetup": needs_setup,
        "sections": sections,
        "paths": {
            "toolDir": str(TOOL_DIR),
            "openclawHome": str(OPENCLAW_HOME),
            "agentsDir": str(AGENTS_DIR),
            "obsidianDir": str(OBSIDIAN_OPENCLAW_DIR),
            "blackholeDir": str(BLACKHOLE_DIR),
            "setupStateFile": str(SETUP_STATE_FILE),
        },
    }


def setup_doctor_fix():
    created = []
    for path in [
        STUDIO_STATE_DIR,
        ATTACHMENTS_DIR,
        ARCHIVE_STATE_DIR,
        BLACKHOLE_STATE_DIR,
        OBSIDIAN_OPENCLAW_DIR,
        HANDOVER_DIR,
        AUTO_HANDOVER_DIR,
        BLACKHOLE_DIR,
        BLACKHOLE_SHARED_DIR,
        BLACKHOLE_TASKS_DIR,
        BLACKHOLE_ARCHIVE_DIR,
    ]:
        before = path.exists()
        path.mkdir(parents=True, exist_ok=True)
        if not before:
            created.append(str(path))
    state = setup_state()
    state.update({
        "version": 1,
        "setupCompleted": True,
        "lastSeenVersion": STUDIO_VERSION,
        "updatedAt": int(time.time() * 1000),
        "toolDir": str(TOOL_DIR),
        "openclawHome": str(OPENCLAW_HOME),
        "obsidianDir": str(OBSIDIAN_OPENCLAW_DIR),
    })
    write_json(SETUP_STATE_FILE, state)
    return {"ok": True, "created": created, "stateFile": str(SETUP_STATE_FILE), "report": setup_doctor_report()}


def scrub_private(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(word in lowered for word in ["secret", "token", "key", "password", "appid", "app_id", "botid", "bot_id"]):
                cleaned[key] = "***"
            else:
                cleaned[key] = scrub_private(item)
        return cleaned
    if isinstance(value, list):
        return [scrub_private(item) for item in value]
    return value


def openclaw_config():
    path = OPENCLAW_HOME / "openclaw.json"
    data = read_json(path)
    return data if isinstance(data, dict) else {}


def configured_plugins(config):
    entries = ((config.get("plugins") or {}).get("entries") or {})
    if not isinstance(entries, dict):
        return []
    rows = []
    for plugin_id, plugin_config in sorted(entries.items()):
        plugin_config = plugin_config if isinstance(plugin_config, dict) else {}
        rows.append({
            "id": plugin_id,
            "enabled": plugin_config.get("enabled") is not False,
            "source": "openclaw.json",
        })
    return rows


def package_version(path):
    data = read_json(path) or {}
    return data.get("version") or ""


def node_resolve_from(directory, package_name):
    if not directory.exists() or not shutil.which("node"):
        return {"ok": False, "detail": "node unavailable or directory missing"}
    raw = run([
        "node",
        "-e",
        f"try{{console.log(require.resolve('{package_name}'))}}catch(e){{console.log(e.code + ': ' + e.message)}}",
    ], timeout=8)
    ok = bool(raw.strip()) and not raw.strip().startswith(("MODULE_NOT_FOUND", "ERR_"))
    return {"ok": ok, "detail": raw.strip()}


def extension_plugin_report():
    rows = []
    extensions_dir = OPENCLAW_HOME / "extensions"
    if extensions_dir.exists():
        for manifest in sorted(extensions_dir.glob("*/openclaw.plugin.json")):
            plugin_dir = manifest.parent
            package_json = plugin_dir / "package.json"
            manifest_data = read_json(manifest) or {}
            rows.append({
                "id": manifest_data.get("id") or plugin_dir.name,
                "path": str(plugin_dir),
                "version": package_version(package_json),
                "channels": manifest_data.get("channels") or [],
                "hasChannelConfigs": bool(manifest_data.get("channelConfigs")),
                "source": "extensions",
            })
    weixin_package = OPENCLAW_HOME / "npm" / "node_modules" / "@tencent-weixin" / "openclaw-weixin" / "package.json"
    if weixin_package.exists():
        rows.append({
            "id": "@tencent-weixin/openclaw-weixin",
            "path": str(weixin_package.parent),
            "version": package_version(weixin_package),
            "channels": ["openclaw-weixin"],
            "hasChannelConfigs": True,
            "source": "npm",
        })
    return rows


def tail_text(path, max_bytes=1024 * 1024):
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(size - max_bytes, 0))
            return handle.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def recent_openclaw_log_matches():
    candidates = []
    for folder in (Path("/tmp/openclaw"), OPENCLAW_HOME / "logs"):
        if folder.exists():
            candidates.extend(sorted(folder.glob("*.log"), key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)[:6])
    patterns = [
        ("wecomPluginLoadFailed", re.compile(r"wecom-openclaw-plugin failed to load.*Cannot find package 'openclaw'", re.I)),
        ("weixinRuntimeTimeout", re.compile(r"Weixin runtime initialization timeout", re.I)),
        ("pluginAllowEmpty", re.compile(r"plugins\.allow is empty", re.I)),
    ]
    counts = {key: 0 for key, _ in patterns}
    examples = {key: "" for key, _ in patterns}
    for path in candidates:
        text = tail_text(path)
        for line in text.splitlines():
            for key, pattern in patterns:
                if pattern.search(line):
                    counts[key] += 1
                    examples[key] = line[-600:]
    return {"counts": counts, "examples": examples}


def agent_model_rows(config):
    defaults = ((config.get("agents") or {}).get("defaults") or {})
    default_model = defaults.get("model") if isinstance(defaults.get("model"), dict) else {}
    rows = []
    for agent in ((config.get("agents") or {}).get("list") or []):
        if not isinstance(agent, dict):
            continue
        model = agent.get("model") if isinstance(agent.get("model"), dict) else {}
        effective = model or default_model
        rows.append({
            "id": agent.get("id") or "",
            "name": agent.get("name") or agent.get("id") or "",
            "primary": effective.get("primary") or "",
            "fallbacks": effective.get("fallbacks") or [],
            "runtime": ((agent.get("agentRuntime") or {}).get("id") if isinstance(agent.get("agentRuntime"), dict) else ""),
        })
    return rows


def upgrade_guard_report():
    config = openclaw_config()
    openclaw_bin = openclaw_cli()
    log_state = recent_openclaw_log_matches()
    items = []
    backups = sorted(UPGRADE_BACKUP_DIR.glob("*"), key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True) if UPGRADE_BACKUP_DIR.exists() else []
    latest_backup = str(backups[0]) if backups else ""

    if openclaw_bin:
        version = run([openclaw_bin, "--version"], timeout=8).strip()
        items.append(check_item("ok", "OpenClaw CLI", version or openclaw_bin))
    else:
        items.append(check_item("error", "缺少 OpenClaw CLI", "找不到 openclaw 命令。", "升级前必须先确认 CLI 可用。"))

    config_path = OPENCLAW_HOME / "openclaw.json"
    if config_path.exists():
        items.append(check_item("ok", "主配置可备份", str(config_path)))
    else:
        items.append(check_item("error", "缺少主配置", str(config_path), "先完成 OpenClaw 初始化后再升级。"))

    if can_connect_tcp("127.0.0.1", 18789):
        items.append(check_item("ok", "Gateway 当前在线", "127.0.0.1:18789"))
    else:
        items.append(check_item("warn", "Gateway 当前未在线", "127.0.0.1:18789", "升级前建议记录当前状态，升级后再对比。"))

    if latest_backup:
        items.append(check_item("ok", "已有升级前备份", latest_backup))
    else:
        items.append(check_item("warn", "尚未创建升级前备份", str(UPGRADE_BACKUP_DIR), "升级前先点击“创建升级前备份”。"))

    if not (((config.get("plugins") or {}).get("allow") or [])):
        items.append(check_item("warn", "plugins.allow 为空", "非内置插件可能自动加载。", "稳定运行后建议固定可信插件列表。"))

    if log_state["counts"].get("wecomPluginLoadFailed"):
        items.append(check_item("error", "企业微信插件加载失败", "日志中发现 wecom-openclaw-plugin 找不到 openclaw 包。", "先修复插件依赖或安装方式，再验证 wecom。"))
    if log_state["counts"].get("weixinRuntimeTimeout"):
        items.append(check_item("warn", "个人微信运行时超时", "日志中发现 Weixin runtime initialization timeout。", "升级后要单独验证 openclaw-weixin 与微信客户端兼容性。"))

    channels = config.get("channels") if isinstance(config.get("channels"), dict) else {}
    bindings = config.get("bindings") if isinstance(config.get("bindings"), list) else []
    if channels.get("wecom", {}).get("enabled") and not any(((binding.get("match") or {}).get("channel") == "wecom") for binding in bindings if isinstance(binding, dict)):
        items.append(check_item("warn", "企业微信未绑定 agent", "channels.wecom 已启用，但 bindings 中没有 wecom 规则。", "插件恢复后再绑定到目标 agent。"))

    for row in agent_model_rows(config):
        if row["primary"].startswith("openai/") and not any(str(model).startswith("deepseek/") for model in row["fallbacks"]):
            items.append(check_item("warn", f"{row['name']} 缺少 DeepSeek 兜底", row["primary"], "OpenAI 订阅模型不可用时，建议有 DeepSeek fallback。"))
        if has_openai_api_key_profile(row["id"]):
            items.append(check_item("error", f"{row['name']} 检测到 OpenAI API key profile", row["id"], "项目约定 OpenAI 模型走订阅，不走 API key。"))

    sections = [
        {"id": "guard", "title": "升级前护栏", "items": items, "level": level_worst(items)},
        {
            "id": "plugins",
            "title": "插件快照",
            "items": [
                check_item("ok" if plugin.get("enabled", True) else "warn", plugin["id"], f"{plugin.get('source')} · {plugin.get('version') or '-'} · {plugin.get('path') or ''}")
                for plugin in configured_plugins(config)
            ] + [
                check_item("ok", plugin["id"], f"{plugin.get('source')} · {plugin.get('version') or '-'} · channels={','.join(plugin.get('channels') or []) or '-'}")
                for plugin in extension_plugin_report()
            ],
            "level": "ok",
        },
        {
            "id": "logs",
            "title": "最近日志信号",
            "items": [
                check_item("error" if key == "wecomPluginLoadFailed" and count else "warn" if count else "ok", key, f"{count} 条" + (f" · {log_state['examples'].get(key)}" if count else ""))
                for key, count in log_state["counts"].items()
            ],
            "level": "error" if log_state["counts"].get("wecomPluginLoadFailed") else "warn" if any(log_state["counts"].values()) else "ok",
        },
    ]
    return {
        "ok": level_worst([{"level": section["level"]} for section in sections]) != "error",
        "level": level_worst([{"level": section["level"]} for section in sections]),
        "version": STUDIO_VERSION,
        "latestBackup": latest_backup,
        "backupDir": str(UPGRADE_BACKUP_DIR),
        "openclawHome": str(OPENCLAW_HOME),
        "configPreview": scrub_private({
            "channels": config.get("channels"),
            "bindings": config.get("bindings"),
            "plugins": config.get("plugins"),
            "agents": config.get("agents"),
            "session": config.get("session"),
            "modelByChannel": config.get("modelByChannel"),
        }),
        "sections": sections,
    }


def copy_backup_item(source, backup_root, copied, missing):
    source = Path(source).expanduser()
    if not source.exists():
        missing.append(str(source))
        return
    if source.is_absolute():
        relative = Path(*source.parts[1:])
    else:
        relative = source
    target = backup_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        shutil.copy2(source, target)
    copied.append({"source": str(source), "target": str(target)})


def create_upgrade_backup():
    stamp = archive_timestamp()
    backup_root = UPGRADE_BACKUP_DIR / stamp
    copied = []
    missing = []
    backup_root.mkdir(parents=True, exist_ok=True)
    launch_agent = Path.home() / "Library" / "LaunchAgents" / "ai.openclaw.gateway.plist"
    for source in [
        OPENCLAW_HOME / "openclaw.json",
        AGENTS_DIR,
        OPENCLAW_HOME / "extensions",
        OPENCLAW_HOME / "npm" / "package.json",
        OPENCLAW_HOME / "npm" / "package-lock.json",
        OPENCLAW_HOME / "npm" / "pnpm-lock.yaml",
        launch_agent,
    ]:
        copy_backup_item(source, backup_root, copied, missing)
    manifest = {
        "version": 1,
        "createdAt": int(time.time() * 1000),
        "createdText": time.strftime("%Y-%m-%d %H:%M:%S"),
        "studioVersion": STUDIO_VERSION,
        "openclawHome": str(OPENCLAW_HOME),
        "copied": copied,
        "missing": missing,
        "report": upgrade_guard_report(),
        "note": "本目录是本机私有升级前备份，可能包含认证资料和会话历史，请勿提交到 Git 或分享。",
    }
    write_json(backup_root / "manifest.json", manifest)
    (backup_root / "README.txt").write_text(
        "OpenClaw Agents Studio 升级前备份\n\n"
        "此目录可能包含 OpenClaw 配置、agent 资料、认证资料和会话索引。\n"
        "请勿提交到 Git，也不要公开分享。\n\n"
        "建议用途：升级后如果插件、频道、agent 或会话异常，可用这里的文件人工对照或回滚。\n",
        encoding="utf-8",
    )
    return {"ok": True, "backupPath": str(backup_root), "copied": copied, "missing": missing, "report": upgrade_guard_report()}


def get_access_token():
    REMOTE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not REMOTE_TOKEN_FILE.exists() or not REMOTE_TOKEN_FILE.read_text(encoding="utf-8").strip():
        REMOTE_TOKEN_FILE.write_text(f"{secrets.randbelow(900000) + 100000}\n", encoding="utf-8")
        try:
            REMOTE_TOKEN_FILE.chmod(0o600)
        except OSError:
            pass
    return REMOTE_TOKEN_FILE.read_text(encoding="utf-8").strip()


def parse_cookies(header):
    cookies = {}
    for part in (header or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        cookies[key.strip()] = urllib.parse.unquote(value.strip())
    return cookies


class EventHub:
    def __init__(self):
        self._subscribers = set()
        self._lock = threading.Lock()

    def subscribe(self):
        subscriber = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber):
        with self._lock:
            self._subscribers.discard(subscriber)

    def publish(self, event_type, payload=None):
        payload = payload or {}
        with self._lock:
            subscribers = list(self._subscribers)
        dead = []
        for subscriber in subscribers:
            try:
                subscriber.put_nowait({"type": event_type, "payload": payload, "at": int(time.time())})
            except queue.Full:
                dead.append(subscriber)
        if dead:
            with self._lock:
                for subscriber in dead:
                    self._subscribers.discard(subscriber)


EVENT_HUB = EventHub()


def event_snapshot():
    snapshot = {}
    for _, sessions_file, data in session_stores():
        try:
            snapshot[str(sessions_file)] = sessions_file.stat().st_mtime_ns
        except OSError:
            continue
        for value in data.values():
            session_file = Path(value.get("sessionFile") or sessions_file.parent / f"{value.get('sessionId')}.jsonl")
            try:
                snapshot[str(session_file)] = session_file.stat().st_mtime_ns
            except OSError:
                continue
    if BLACKHOLE_TASKS_INDEX.exists():
        try:
            snapshot[str(BLACKHOLE_TASKS_INDEX)] = BLACKHOLE_TASKS_INDEX.stat().st_mtime_ns
        except OSError:
            pass
    if BLACKHOLE_LEGACY_TASKS_INDEX.exists():
        try:
            snapshot[str(BLACKHOLE_LEGACY_TASKS_INDEX)] = BLACKHOLE_LEGACY_TASKS_INDEX.stat().st_mtime_ns
        except OSError:
            pass
    if BLACKHOLE_TASKS_DIR.exists():
        for path in BLACKHOLE_TASKS_DIR.glob("*.md"):
            try:
                snapshot[str(path)] = path.stat().st_mtime_ns
            except OSError:
                continue
    return snapshot


def changed_session_keys(old_snapshot, new_snapshot):
    changed_paths = {
        path for path, mtime in new_snapshot.items()
        if old_snapshot.get(path) != mtime and path.endswith(".jsonl")
    }
    if not changed_paths:
        return []
    keys = []
    for session in list_sessions():
        if session["sessionFile"] in changed_paths:
            keys.append(session["key"])
    return keys


def event_watch_loop():
    previous = event_snapshot()
    while True:
        time.sleep(EVENT_WATCH_SECONDS)
        try:
            current = event_snapshot()
            if current == previous:
                continue
            session_index_paths = {
                path for path in set(previous) | set(current)
                if path.endswith("sessions.json")
            }
            if any(previous.get(path) != current.get(path) for path in session_index_paths):
                EVENT_HUB.publish("sessions", {})
            blackhole_paths = {
                path for path in set(previous) | set(current)
                if str(BLACKHOLE_TASKS_DIR) in path
            }
            if any(previous.get(path) != current.get(path) for path in blackhole_paths):
                EVENT_HUB.publish("blackhole", {})
            keys = changed_session_keys(previous, current)
            if keys:
                EVENT_HUB.publish("messages", {"keys": keys})
                EVENT_HUB.publish("sessions", {})
            previous = current
        except Exception as exc:
            EVENT_HUB.publish("status", {"level": "warn", "message": f"事件监听暂时异常：{exc}"})


def app_health():
    checks = []
    openclaw_bin = openclaw_cli()
    sessions = session_stores()
    session_count = sum(len(data) for _, _, data in sessions)
    state = setup_state()

    if not state.get("setupCompleted") or state.get("lastSeenVersion") != STUDIO_VERSION:
        detail = "首次使用或升级后建议运行一次完整检查。"
        if state.get("lastSeenVersion"):
            detail = f"已记录版本 {state.get('lastSeenVersion')}，当前版本 {STUDIO_VERSION}。"
        checks.append({
            "level": "warn",
            "title": "建议运行配置自检",
            "detail": detail,
            "action": "打开“工具 → 配置自检”，检查基础服务、多 agent、Obsidian 和共享工作空间。",
        })

    checks.append({
        "level": "ok",
        "title": "Python 3 可用",
        "detail": sys.version.split()[0],
        "action": "",
    })

    if openclaw_bin:
        version = run([openclaw_bin, "--version"], timeout=8).strip()
        checks.append({
            "level": "ok",
            "title": "OpenClaw CLI 已安装",
            "detail": version or openclaw_bin,
            "action": "",
        })
    else:
        checks.append({
            "level": "error",
            "title": "缺少 OpenClaw CLI",
            "detail": "没有在 PATH 中找到 openclaw 命令。",
            "action": "建议先安装 OpenClaw，然后打开新终端确认 openclaw --version 能正常输出。",
        })

    if OPENCLAW_HOME.exists():
        checks.append({
            "level": "ok",
            "title": "OpenClaw 数据目录存在",
            "detail": str(OPENCLAW_HOME),
            "action": "",
        })
    else:
        checks.append({
            "level": "error",
            "title": "缺少 ~/.openclaw 数据目录",
            "detail": str(OPENCLAW_HOME),
            "action": "建议先运行 openclaw setup 或完成一次 OpenClaw 配置。",
        })

    if sessions:
        checks.append({
            "level": "ok",
            "title": "发现 agent session 存储",
            "detail": f"{len(sessions)} 个 agent，{session_count} 个 session",
            "action": "",
        })
    else:
        checks.append({
            "level": "warn",
            "title": "还没有发现 OpenClaw 会话",
            "detail": str(AGENTS_DIR),
            "action": "建议先用 OpenClaw TUI、网页或微信入口发起一次对话，再刷新本工具。",
        })

    if sys.platform == "darwin" and shutil.which("osascript"):
        checks.append({
            "level": "ok",
            "title": "macOS Terminal TUI 可用",
            "detail": "可以用按钮打开 openclaw tui。",
            "action": "",
        })
    else:
        checks.append({
            "level": "warn",
            "title": "TUI 按钮仅完整支持 macOS Terminal",
            "detail": f"当前平台：{sys.platform}",
            "action": "在非 macOS 环境，请手动复制 session key 后运行 openclaw tui --session <key>。",
        })

    if openclaw_bin:
        status_text = run([openclaw_bin, "status"], timeout=8)
        if openclaw_status_ok(status_text) or can_connect_tcp("127.0.0.1", 18789):
            checks.append({
                "level": "ok",
                "title": "OpenClaw Gateway 看起来在线",
                "detail": "openclaw status 或端口探测检查通过。",
                "action": "",
            })
        else:
            checks.append({
                "level": "warn",
                "title": "OpenClaw Gateway 状态需要确认",
                "detail": "openclaw status 没有返回明确在线状态。",
                "action": "如果发送消息失败，先运行 openclaw status；必要时启动 gateway。",
            })

    worst = "ok"
    if any(check["level"] == "error" for check in checks):
        worst = "error"
    elif any(check["level"] == "warn" for check in checks):
        worst = "warn"
    return {
        "ok": worst != "error",
        "level": worst,
        "checks": checks,
        "paths": {
            "toolDir": str(TOOL_DIR),
            "openclawHome": str(OPENCLAW_HOME),
            "agentsDir": str(AGENTS_DIR),
        },
    }


def session_stores():
    stores = []
    if not AGENTS_DIR.exists():
        return stores
    for sessions_file in AGENTS_DIR.glob("*/sessions/sessions.json"):
        agent_id = sessions_file.parts[-3]
        data = read_json(sessions_file) or {}
        stores.append((agent_id, sessions_file, data))
    return stores


def load_archive_index(path):
    data = read_json(path) or {}
    items = data.get("items") if isinstance(data, dict) else []
    return items if isinstance(items, list) else []


def save_archive_index(path, items):
    write_json(path, {"version": 1, "updatedAt": int(time.time() * 1000), "items": items})


def find_session_record(key):
    for agent_id, sessions_file, data in session_stores():
        if key in data:
            return agent_id, sessions_file, data, data[key]
    return None, None, None, None


def public_archived_session(item):
    value = item.get("value") or {}
    session_id = item.get("sessionId") or value.get("sessionId") or ""
    session_file = item.get("archivedFile") or item.get("sessionFile") or ""
    updated_at = value.get("updatedAt") or item.get("archivedAt") or 0
    model = value.get("model") or ""
    provider = value.get("modelProvider") or ""
    origin = value.get("origin") or {}
    delivery = value.get("deliveryContext") or {}
    chat_type = value.get("chatType") or origin.get("chatType") or ("group" if ":group:" in (item.get("key") or "") else "direct")
    channel = value.get("lastChannel") or delivery.get("channel") or origin.get("provider") or ""
    return {
        "archiveId": item.get("archiveId"),
        "key": item.get("key"),
        "label": simplify_key(item.get("key") or ""),
        "preview": session_preview(session_file),
        "agentId": item.get("agentId"),
        "sessionId": session_id,
        "sessionFile": session_file,
        "chatType": chat_type,
        "channel": channel,
        "model": f"{provider}/{model}".strip("/"),
        "updatedAt": updated_at,
        "updatedText": fmt_time(updated_at),
        "archivedAt": item.get("archivedAt"),
        "archivedText": fmt_time(item.get("archivedAt")),
        "kind": "session",
    }


def list_archived_sessions():
    items = load_archive_index(ARCHIVED_SESSIONS_INDEX)
    items.sort(key=lambda item: item.get("archivedAt") or 0, reverse=True)
    return [public_archived_session(item) for item in items]


def archive_session(key):
    agent_id, sessions_file, data, value = find_session_record(key)
    if not value:
        return {"ok": False, "error": "session not found"}
    if value.get("isArchived"):
        return {"ok": False, "error": "session already archived"}
    timestamp = archive_timestamp()
    session_id = value.get("sessionId") or ""
    session_file = Path(value.get("sessionFile") or sessions_file.parent / f"{session_id}.jsonl")
    archived_file = ""
    if session_file.exists():
        archived_file = move_if_exists(session_file, session_file.with_name(f"{session_file.name}.archived.{timestamp}"))
    original_value = dict(value)
    data.pop(key, None)
    write_json(sessions_file, data)
    items = load_archive_index(ARCHIVED_SESSIONS_INDEX)
    items = [item for item in items if item.get("key") != key]
    archive_item = {
        "archiveId": str(uuid.uuid4()),
        "kind": "session",
        "key": key,
        "agentId": agent_id,
        "sessionsFile": str(sessions_file),
        "sessionId": session_id,
        "sessionFile": str(session_file),
        "archivedFile": archived_file,
        "value": original_value,
        "archivedAt": int(time.time() * 1000),
    }
    items.insert(0, archive_item)
    save_archive_index(ARCHIVED_SESSIONS_INDEX, items)
    EVENT_HUB.publish("sessions", {})
    return {"ok": True, "item": public_archived_session(archive_item)}


def restore_archived_session(archive_id):
    items = load_archive_index(ARCHIVED_SESSIONS_INDEX)
    item = next((entry for entry in items if entry.get("archiveId") == archive_id), None)
    if not item:
        return {"ok": False, "error": "archived session not found"}
    sessions_file_text = item.get("sessionsFile") or ""
    if not sessions_file_text:
        return {"ok": False, "error": "missing sessions file"}
    sessions_file = Path(sessions_file_text)
    data = read_json(sessions_file) or {}
    key = item.get("key") or ""
    if key in data:
        return {"ok": False, "error": "target session already exists"}
    value = dict(item.get("value") or {})
    session_file_text = item.get("sessionFile") or ""
    archived_file_text = item.get("archivedFile") or ""
    session_file = Path(session_file_text) if session_file_text else None
    archived_file = Path(archived_file_text) if archived_file_text else None
    if archived_file and archived_file.exists() and session_file:
        restored = move_if_exists(archived_file, session_file)
        value["sessionFile"] = restored
    elif session_file:
        value["sessionFile"] = str(session_file)
    data[key] = value
    write_json(sessions_file, data)
    items = [entry for entry in items if entry.get("archiveId") != archive_id]
    save_archive_index(ARCHIVED_SESSIONS_INDEX, items)
    EVENT_HUB.publish("sessions", {})
    return {"ok": True}


def delete_archived_session(archive_id, confirm=""):
    if confirm != "永久删除":
        return {"ok": False, "error": "永久删除需要确认文字：永久删除"}
    items = load_archive_index(ARCHIVED_SESSIONS_INDEX)
    item = next((entry for entry in items if entry.get("archiveId") == archive_id), None)
    if not item:
        return {"ok": False, "error": "archived session not found"}
    archived_file = item.get("archivedFile") or ""
    if archived_file:
        path = Path(archived_file)
        if path.exists() and path.is_file():
            path.unlink()
    items = [entry for entry in items if entry.get("archiveId") != archive_id]
    save_archive_index(ARCHIVED_SESSIONS_INDEX, items)
    EVENT_HUB.publish("sessions", {})
    return {"ok": True}


def simplify_key(key):
    key = key.replace("agent:", "")
    parts = key.split(":")
    if len(parts) >= 4:
        return " / ".join([parts[0], parts[1], parts[2], parts[3][:44]])
    return key


def estimate_tokens_from_file(session_file):
    messages = read_messages(session_file, limit=1000)
    chars = sum(len(message["text"]) for message in messages)
    return int(chars / 3.5) if chars else 0


def token_info(value, session_file):
    context_tokens = int(value.get("contextTokens") or 0)
    total_tokens = int(value.get("totalTokens") or 0)
    source = "openclaw"
    if not total_tokens:
        total_tokens = estimate_tokens_from_file(session_file)
        source = "estimated"
    ratio = 0
    if context_tokens and total_tokens:
        ratio = min(total_tokens / context_tokens, 1)
    level = "ok"
    if ratio >= 0.9:
        level = "critical"
    elif ratio >= AUTO_HANDOVER_RATIO:
        level = "warn"
    return {
        "contextTokens": context_tokens,
        "totalTokens": total_tokens,
        "tokenRatio": ratio,
        "tokenPercent": round(ratio * 100, 1),
        "tokenSource": source,
        "tokenLevel": level,
    }


def session_preview(session_file, max_chars=72):
    path = Path(session_file)
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    role_names = {
        "user": "用户",
        "assistant": "助手",
        "system": "系统",
        "tool": "工具",
    }
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        if event.get("type") != "message":
            continue
        msg = event.get("message") or {}
        text = re.sub(r"\s+", " ", content_to_preview_text(msg.get("content"))).strip()
        if not text:
            continue
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "..."
        role = role_names.get(msg.get("role") or "", msg.get("role") or "消息")
        return f"{role}：{text}"
    return ""


def list_sessions():
    rows = []
    for agent_id, sessions_file, data in session_stores():
        for key, value in data.items():
            session_id = value.get("sessionId")
            session_file = value.get("sessionFile") or str(sessions_file.parent / f"{session_id}.jsonl")
            origin = value.get("origin") or {}
            delivery = value.get("deliveryContext") or {}
            chat_type = value.get("chatType") or origin.get("chatType") or ("group" if ":group:" in key else "direct")
            channel = value.get("lastChannel") or delivery.get("channel") or origin.get("provider") or ""
            updated_at = value.get("updatedAt") or 0
            model = value.get("model") or ""
            provider = value.get("modelProvider") or ""
            harness = value.get("agentHarnessId") or ""
            tokens = token_info(value, session_file)
            rows.append({
                "key": key,
                "label": simplify_key(key),
                "preview": session_preview(session_file),
                "agentId": agent_id,
                "sessionId": session_id,
                "sessionFile": session_file,
                "chatType": chat_type,
                "channel": channel,
                "accountId": value.get("lastAccountId") or delivery.get("accountId") or origin.get("accountId") or "",
                "to": value.get("lastTo") or delivery.get("to") or origin.get("to") or "",
                "model": f"{provider}/{model}".strip("/"),
                "harness": harness,
                "updatedAt": updated_at,
                "updatedText": fmt_time(updated_at),
                **tokens,
                "isPhoneMain": agent_id == "codex-agent" and channel == "openclaw-weixin" and chat_type == "direct",
                "isGroup": chat_type == "group",
            })
    rows.sort(key=lambda item: (not item.get("isPhoneMain"), -(item.get("updatedAt") or 0)))
    return rows


def draft_explicit_session(agent_id="codex-agent"):
    session_id = str(uuid.uuid4())
    key = f"agent:{agent_id}:explicit:{session_id}"
    return {
        "key": key,
        "label": f"{agent_id} / 新会话",
        "preview": "等待发送第一条消息",
        "agentId": agent_id,
        "sessionId": session_id,
        "sessionFile": "",
        "chatType": "direct",
        "channel": "",
        "accountId": "",
        "to": "",
        "model": "openai/gpt-5.5",
        "harness": "codex",
        "updatedAt": int(time.time() * 1000),
        "updatedText": "草稿",
        "contextTokens": 0,
        "totalTokens": 0,
        "tokenRatio": 0,
        "tokenPercent": 0,
        "tokenSource": "draft",
        "tokenLevel": "ok",
        "isPhoneMain": False,
        "isGroup": False,
        "isDraft": True,
    }


def session_from_key(key):
    session = next((s for s in list_sessions() if s["key"] == key), None)
    if session:
        return session
    match = re.fullmatch(r"agent:([^:]+):explicit:([0-9a-fA-F-]{36})", key or "")
    if not match:
        return None
    agent_id, session_id = match.groups()
    session = draft_explicit_session(agent_id)
    session["key"] = key
    session["sessionId"] = session_id
    session["label"] = f"{agent_id} / 新会话"
    return session


def fmt_time(ms):
    if not ms:
        return "-"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ms / 1000))
    except Exception:
        return "-"


def content_to_text(content):
    if isinstance(content, str):
        return clean_text(content)
    if isinstance(content, list):
        chunks = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                chunks.append(item.get("text") or item.get("content") or item.get("type") or "")
        return clean_text("\n".join([chunk for chunk in chunks if chunk]))
    if isinstance(content, dict):
        return clean_text(content.get("text") or content.get("content") or json.dumps(content, ensure_ascii=False))
    return "" if content is None else clean_text(str(content))


def content_to_preview_text(content):
    if isinstance(content, str):
        return clean_text(content)
    if isinstance(content, list):
        chunks = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    chunks.append(str(text))
        return clean_text("\n".join(chunks))
    if isinstance(content, dict):
        return clean_text(content.get("text") or content.get("content") or "")
    return "" if content is None else clean_text(str(content))


def clean_text(text):
    text = text or ""
    text = re.sub(
        r"^(Conversation info|Sender) \(untrusted metadata\):\s*```(?:json)?\s*.*?```\s*",
        "",
        text,
        flags=re.DOTALL,
    )
    return text


def read_messages(session_file, limit=200):
    path = Path(session_file)
    messages = []
    if not path.exists():
        return messages
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return messages
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        if event.get("type") != "message":
            continue
        msg = event.get("message") or {}
        role = msg.get("role") or "unknown"
        text = content_to_text(msg.get("content"))
        if not text:
            continue
        messages.append({
            "role": role,
            "text": text,
            "timestamp": event.get("timestamp") or msg.get("timestamp") or "",
            "model": msg.get("model") or "",
            "provider": msg.get("provider") or "",
        })
    return messages[-limit:]


def safe_filename(value):
    value = re.sub(r"[^0-9A-Za-z._@一-龥-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:120] or "session"


def save_uploaded_file(field):
    raw_name = field.filename or "attachment"
    name = safe_filename(Path(raw_name).name)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target_dir = ATTACHMENTS_DIR / stamp
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name
    counter = 1
    while target.exists():
        stem = target.stem
        suffix = target.suffix
        target = target_dir / f"{stem}-{counter}{suffix}"
        counter += 1
    size = 0
    with target.open("wb") as output:
        while True:
            chunk = field.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            output.write(chunk)
    return {"name": name, "path": str(target), "size": size}


def blackhole_agent_label(agent_id):
    item = next((agent for agent in BLACKHOLE_AGENT_DEFS if agent["id"] == agent_id), None)
    return item.get("label") if item else agent_id


def blackhole_agent_role(agent_id):
    item = next((agent for agent in BLACKHOLE_AGENT_DEFS if agent["id"] == agent_id), None)
    return item.get("role") if item else agent_id


def blackhole_now_ms():
    return int(time.time() * 1000)


def parse_blackhole_time_ms(value):
    try:
        return int(time.mktime(time.strptime((value or "").strip(), "%Y-%m-%d %H:%M:%S")) * 1000)
    except Exception:
        return 0


def parse_blackhole_task_markdown(path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    task_id = (re.search(r"- Task ID: `([^`]+)`", text) or [None, ""])[1]
    if not task_id:
        return None
    title = (re.search(r"^# 黑洞协作任务：(.+)$", text, re.MULTILINE) or [None, path.stem])[1].strip()
    created = parse_blackhole_time_ms((re.search(r"- 创建时间: ([^\n]+)", text) or [None, ""])[1])
    updated = parse_blackhole_time_ms((re.search(r"- 更新时间: ([^\n]+)", text) or [None, ""])[1])
    status = (re.search(r"- 状态: `([^`]+)`", text) or [None, "created"])[1]
    agents_text = (re.search(r"- 参与 agent: ([^\n]+)", text) or [None, ""])[1]
    agents = [item.strip() for item in agents_text.split(",") if item.strip()]
    prompt = ""
    prompt_match = re.search(r"## 用户任务\s*(.*?)\s*## Agent Sessions", text, re.DOTALL)
    if prompt_match:
        prompt = prompt_match.group(1).strip()
    sessions = {}
    results = {}
    for block in re.finditer(r"### .*? `([^`]+)`\s*(.*?)(?=\n### |\n## 协作说明|\Z)", text, re.DOTALL):
        agent_id = block.group(1)
        body = block.group(2)
        key = (re.search(r"- Session key: `([^`]+)`", body) or [None, ""])[1]
        session_match = re.fullmatch(r"agent:[^:]+:explicit:([0-9a-fA-F-]{36})", key or "")
        session_id = session_match.group(1) if session_match else ""
        if session_id:
            sessions[agent_id] = {"sessionId": session_id, "key": key}
        agent_status = (re.search(r"- 状态: `([^`]+)`", body) or [None, "pending"])[1]
        result_text = (re.search(r"#### 最近回复\s*(.*)", body, re.DOTALL) or [None, ""])[1].strip()
        if result_text == "尚未运行。":
            result_text = ""
        results[agent_id] = {"status": agent_status, "text": result_text, "updatedAt": updated}
    return {
        "id": task_id,
        "title": title,
        "prompt": prompt,
        "agents": agents,
        "status": status,
        "createdAt": created or int(path.stat().st_mtime * 1000),
        "updatedAt": updated or int(path.stat().st_mtime * 1000),
        "sessions": sessions,
        "results": results,
        "path": str(path),
    }


def recover_blackhole_tasks_from_markdown(existing):
    tasks_by_id = {task.get("id"): task for task in existing if task.get("id")}
    if not BLACKHOLE_TASKS_DIR.exists():
        return list(tasks_by_id.values())
    for path in BLACKHOLE_TASKS_DIR.glob("*.md"):
        task = parse_blackhole_task_markdown(path)
        if task and task.get("id") not in tasks_by_id:
            tasks_by_id[task["id"]] = task
    return list(tasks_by_id.values())


def load_blackhole_tasks():
    tasks = []
    for index_path in (BLACKHOLE_TASKS_INDEX, BLACKHOLE_LEGACY_TASKS_INDEX):
        data = read_json(index_path) or {}
        current = data.get("tasks") if isinstance(data, dict) else []
        if isinstance(current, list):
            for task in current:
                if isinstance(task, dict) and task.get("id") and not any(item.get("id") == task.get("id") for item in tasks):
                    tasks.append(task)
    recovered = recover_blackhole_tasks_from_markdown(tasks)
    if len(recovered) != len(tasks) or (recovered and not BLACKHOLE_TASKS_INDEX.exists()):
        try:
            save_blackhole_tasks(recovered)
        except Exception:
            pass
    tasks = recovered
    reconcile_blackhole_tasks(tasks, persist=True)
    tasks.sort(key=lambda item: item.get("updatedAt") or item.get("createdAt") or 0, reverse=True)
    return tasks


def save_blackhole_tasks(tasks):
    BLACKHOLE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    write_json(BLACKHOLE_TASKS_INDEX, {"version": 1, "tasks": tasks})


def list_archived_blackhole_tasks():
    items = load_archive_index(ARCHIVED_BLACKHOLE_INDEX)
    items.sort(key=lambda item: item.get("archivedAt") or 0, reverse=True)
    rows = []
    for item in items:
        task = dict(item.get("task") or {})
        task.update({
            "archiveId": item.get("archiveId"),
            "kind": "blackhole",
            "archivedAt": item.get("archivedAt"),
            "archivedText": fmt_time(item.get("archivedAt")),
            "path": item.get("archivedPath") or task.get("path") or "",
        })
        rows.append(blackhole_task_public(task))
    return rows


def archive_blackhole_task(task_id):
    tasks = load_blackhole_tasks()
    task = next((item for item in tasks if item.get("id") == task_id), None)
    if not task:
        return {"ok": False, "error": "task not found"}
    timestamp = archive_timestamp()
    path = Path(task.get("path") or "")
    archived_path = ""
    if task.get("path") and path.exists():
        archived_path = move_if_exists(path, BLACKHOLE_ARCHIVE_DIR / path.name)
    task_snapshot = dict(task)
    tasks = [item for item in tasks if item.get("id") != task_id]
    save_blackhole_tasks(tasks)
    items = load_archive_index(ARCHIVED_BLACKHOLE_INDEX)
    items = [item for item in items if (item.get("task") or {}).get("id") != task_id]
    archive_item = {
        "archiveId": str(uuid.uuid4()),
        "kind": "blackhole",
        "task": task_snapshot,
        "originalPath": task.get("path") or "",
        "archivedPath": archived_path,
        "archivedAt": int(time.time() * 1000),
        "archivedStamp": timestamp,
    }
    items.insert(0, archive_item)
    save_archive_index(ARCHIVED_BLACKHOLE_INDEX, items)
    EVENT_HUB.publish("blackhole", {})
    return {"ok": True, "item": archive_item}


def restore_archived_blackhole_task(archive_id):
    items = load_archive_index(ARCHIVED_BLACKHOLE_INDEX)
    item = next((entry for entry in items if entry.get("archiveId") == archive_id), None)
    if not item:
        return {"ok": False, "error": "archived task not found"}
    task = dict(item.get("task") or {})
    tasks = load_blackhole_tasks()
    if any(existing.get("id") == task.get("id") for existing in tasks):
        return {"ok": False, "error": "target task already exists"}
    original_path = item.get("originalPath") or task.get("path") or ""
    archived_path = item.get("archivedPath") or ""
    if archived_path and Path(archived_path).exists() and original_path:
        task["path"] = move_if_exists(Path(archived_path), Path(original_path))
    elif original_path:
        task["path"] = original_path
    tasks.insert(0, task)
    save_blackhole_tasks(tasks)
    items = [entry for entry in items if entry.get("archiveId") != archive_id]
    save_archive_index(ARCHIVED_BLACKHOLE_INDEX, items)
    EVENT_HUB.publish("blackhole", {})
    return {"ok": True, "task": blackhole_task_public(task)}


def delete_archived_blackhole_task(archive_id, confirm=""):
    if confirm != "永久删除":
        return {"ok": False, "error": "永久删除需要确认文字：永久删除"}
    items = load_archive_index(ARCHIVED_BLACKHOLE_INDEX)
    item = next((entry for entry in items if entry.get("archiveId") == archive_id), None)
    if not item:
        return {"ok": False, "error": "archived task not found"}
    archived_path = item.get("archivedPath") or ""
    if archived_path:
        path = Path(archived_path)
        if path.exists() and path.is_file():
            path.unlink()
    items = [entry for entry in items if entry.get("archiveId") != archive_id]
    save_archive_index(ARCHIVED_BLACKHOLE_INDEX, items)
    EVENT_HUB.publish("blackhole", {})
    return {"ok": True}


def blackhole_task_path(task):
    path = task.get("path")
    if path:
        return Path(path)
    created = fmt_time(task.get("createdAt") or blackhole_now_ms()).replace(":", ".")
    name = safe_filename(task.get("title") or task.get("id") or "blackhole-task")
    return BLACKHOLE_TASKS_DIR / f"{created}-{name}.md"


def task_session_key(agent_id, session_id):
    return f"agent:{agent_id}:explicit:{session_id}"


def read_task_agent_messages(task, agent_id, limit=80):
    session_info = (task.get("sessions") or {}).get(agent_id) or {}
    session_id = session_info.get("sessionId")
    if not session_id:
        return []
    key = task_session_key(agent_id, session_id)
    session = next((item for item in list_sessions() if item["key"] == key), None)
    if not session:
        return []
    return read_messages(session["sessionFile"], limit=limit)


def completed_blackhole_text_from_messages(messages):
    for message in reversed(messages or []):
        if message.get("role") != "assistant":
            continue
        text = (message.get("text") or "").strip()
        if not text:
            continue
        compact = re.sub(r"\s+", " ", text).strip().lower()
        if compact in {"thinking", "thinking toolcall"} or compact.startswith("thinking toolcall"):
            continue
        text = re.sub(r"^thinking\s+", "", text, flags=re.IGNORECASE).strip()
        if text:
            return text
    return ""


def reconcile_blackhole_task(task):
    changed = False
    results = task.setdefault("results", {})
    now = blackhole_now_ms()
    for agent_id in task.get("agents", []):
        result = results.setdefault(agent_id, {})
        if result.get("status") in ("done", "error"):
            continue
        text = completed_blackhole_text_from_messages(read_task_agent_messages(task, agent_id, limit=20))
        if not text:
            continue
        result.update({
            "status": "done",
            "text": text,
            "error": "",
            "updatedAt": result.get("updatedAt") or now,
        })
        changed = True
    if task.get("agents"):
        all_done = all((results.get(agent_id) or {}).get("status") in BLACKHOLE_TERMINAL_STATUSES for agent_id in task.get("agents", []))
        if all_done and task.get("status") not in BLACKHOLE_TERMINAL_STATUSES:
            task["status"] = "done"
            changed = True
    if changed:
        task["updatedAt"] = now
    return changed


def reconcile_blackhole_tasks(tasks, persist=False):
    changed = False
    for task in tasks:
        changed = reconcile_blackhole_task(task) or changed
    if changed and persist:
        for task in tasks:
            try:
                write_blackhole_task_markdown(task)
            except Exception as exc:
                task["markdownError"] = str(exc)
        save_blackhole_tasks(tasks)
    return changed


def blackhole_task_public(task, include_messages=False):
    public = dict(task)
    public["agentDefs"] = BLACKHOLE_AGENT_DEFS
    public["defaultAgents"] = BLACKHOLE_DEFAULT_AGENTS
    if include_messages:
        messages = {}
        for agent_id in task.get("agents", []):
            messages[agent_id] = read_task_agent_messages(task, agent_id)
        public["messages"] = messages
    return public


def write_blackhole_task_markdown(task):
    BLACKHOLE_TASKS_DIR.mkdir(parents=True, exist_ok=True)
    path = blackhole_task_path(task)
    task["path"] = str(path)
    lines = [
        f"# 黑洞协作任务：{task.get('title') or task.get('id')}",
        "",
        f"- Task ID: `{task.get('id')}`",
        f"- 创建时间: {fmt_time(task.get('createdAt'))}",
        f"- 更新时间: {fmt_time(task.get('updatedAt'))}",
        f"- 状态: `{task.get('status')}`",
        f"- 参与 agent: {', '.join(task.get('agents', []))}",
        "",
        "## 用户任务",
        "",
        task.get("prompt") or "",
        "",
        "## Agent Sessions",
        "",
    ]
    for agent_id in task.get("agents", []):
        session_info = (task.get("sessions") or {}).get(agent_id) or {}
        session_id = session_info.get("sessionId") or "-"
        key = task_session_key(agent_id, session_id) if session_id != "-" else "-"
        result = ((task.get("results") or {}).get(agent_id) or {})
        lines.extend([
            f"### {blackhole_agent_label(agent_id)} `{agent_id}`",
            "",
            f"- 状态: `{result.get('status') or 'pending'}`",
            f"- Session key: `{key}`",
            f"- 更新时间: {fmt_time(result.get('updatedAt'))}",
            "",
            "#### 最近回复",
            "",
            (result.get("text") or "尚未运行。"),
            "",
        ])
    lines.extend([
        "## 协作说明",
        "",
        "- 每个 agent 使用独立 explicit session。",
        "- 本文件只记录协作任务索引和摘要，不替代完整 session 历史。",
        "- 高风险执行仍需要用户确认。",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def update_blackhole_task(task):
    tasks = load_blackhole_tasks()
    task["updatedAt"] = blackhole_now_ms()
    found = False
    for index, item in enumerate(tasks):
        if item.get("id") == task.get("id"):
            tasks[index] = task
            found = True
            break
    if not found:
        tasks.insert(0, task)
    try:
        write_blackhole_task_markdown(task)
        task.pop("markdownError", None)
    except Exception as exc:
        task["markdownError"] = str(exc)
    save_blackhole_tasks(tasks)
    EVENT_HUB.publish("blackhole", {"id": task.get("id")})
    return task


def list_blackhole_tasks():
    return [blackhole_task_public(task) for task in load_blackhole_tasks()]


def get_blackhole_task(task_id, include_messages=False):
    task = next((item for item in load_blackhole_tasks() if item.get("id") == task_id), None)
    return blackhole_task_public(task, include_messages=include_messages) if task else None


def finalize_blackhole_task_status(task):
    results = task.get("results") or {}
    if task.get("agents") and all((results.get(agent_id) or {}).get("status") in BLACKHOLE_TERMINAL_STATUSES for agent_id in task.get("agents", [])):
        if task.get("status") != "cancelled":
            task["status"] = "done"
    return task


def schedule_blackhole_worker(task_id):
    threading.Thread(target=run_blackhole_task_worker, args=(task_id,), daemon=True).start()


def set_blackhole_agent_status(task_id, agent_id, status, note=""):
    if status not in {"skipped", "done", "cancelled"}:
        return {"ok": False, "error": "unsupported status"}
    task = next((item for item in load_blackhole_tasks() if item.get("id") == task_id), None)
    if not task:
        return {"ok": False, "error": "task not found"}
    if agent_id not in task.get("agents", []):
        return {"ok": False, "error": "agent not in task"}
    result = task.setdefault("results", {}).setdefault(agent_id, {})
    text = note.strip() or {
        "skipped": "已由用户手动跳过。",
        "done": "已由用户手动标记完成。",
        "cancelled": "已由用户手动结束。",
    }[status]
    result.update({
        "status": status,
        "text": result.get("text") or text,
        "error": "",
        "updatedAt": blackhole_now_ms(),
        "manual": True,
    })
    task["updatedAt"] = blackhole_now_ms()
    finalize_blackhole_task_status(task)
    update_blackhole_task(task)
    if task.get("status") == "running":
        schedule_blackhole_worker(task_id)
    return {"ok": True, "task": blackhole_task_public(task, include_messages=True)}


def cancel_blackhole_task(task_id):
    task = next((item for item in load_blackhole_tasks() if item.get("id") == task_id), None)
    if not task:
        return {"ok": False, "error": "task not found"}
    now = blackhole_now_ms()
    for agent_id in task.get("agents", []):
        result = task.setdefault("results", {}).setdefault(agent_id, {})
        if result.get("status") not in BLACKHOLE_TERMINAL_STATUSES:
            result.update({
                "status": "cancelled",
                "text": result.get("text") or "任务已由用户手动结束。",
                "error": "",
                "updatedAt": now,
                "manual": True,
            })
    task["status"] = "cancelled"
    task["updatedAt"] = now
    update_blackhole_task(task)
    return {"ok": True, "task": blackhole_task_public(task, include_messages=True)}


def create_blackhole_task(title, prompt, agents):
    agents = [agent for agent in agents if any(item["id"] == agent for item in BLACKHOLE_AGENT_DEFS)]
    if not agents:
        agents = list(BLACKHOLE_DEFAULT_AGENTS)
    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "title": (title or prompt.splitlines()[0] or "黑洞协作任务")[:80],
        "prompt": prompt,
        "agents": agents,
        "status": "created",
        "createdAt": blackhole_now_ms(),
        "updatedAt": blackhole_now_ms(),
        "sessions": {
            agent_id: {
                "sessionId": str(uuid.uuid4()),
                "key": task_session_key(agent_id, str(uuid.uuid4())),
            }
            for agent_id in agents
        },
        "results": {},
    }
    for agent_id, info in task["sessions"].items():
        info["key"] = task_session_key(agent_id, info["sessionId"])
    update_blackhole_task(task)
    return blackhole_task_public(task, include_messages=True)


def blackhole_agent_prompt(task, agent_id):
    role = blackhole_agent_role(agent_id)
    label = blackhole_agent_label(agent_id)
    shared_dir = str(BLACKHOLE_SHARED_DIR)
    task_path = task.get("path") or str(blackhole_task_path(task))
    role_guidance = {
        "executor": "你是执行者。请给出可执行步骤、需要用户确认的动作、执行顺序和风险前置条件。不要直接承诺已执行，除非你真的执行了。",
        "guardian": "你是守护者。请从风险、权限、隐私、安全、成本、误操作、外部发送边界检查这个任务。",
        "memory": "你是记录者。请提炼任务背景、应记录到 Obsidian 的事项、接力摘要和后续归档结构。",
        "researcher": "你是研究者。请指出需要查证的事实、建议查证路径、已知不确定性和可验证来源类型。",
        "life": "你是生活助理。请从日常安排、节奏、习惯、提醒、生活影响角度给建议；不要替代医疗、法律、投资专业判断。",
    }
    return "\n".join([
        "你正在参与 OpenClaw Agents黑洞的多 agent 协作任务。",
        "",
        f"任务 ID：{task.get('id')}",
        f"任务标题：{task.get('title')}",
        f"你的身份：{label}（{agent_id}）",
        f"共享协同空间：{shared_dir}",
        f"任务记录文件：{task_path}",
        "",
        "用户原始任务：",
        task.get("prompt") or "",
        "",
        "你的本轮要求：",
        role_guidance.get(role, "请从你的角色角度给出清晰、可执行、可复核的意见。"),
        "",
        "输出要求：",
        "- 只从你的角色视角回答。",
        "- 明确列出结论、理由、风险或下一步。",
        "- 不要假装其他 agent 已经说过话。",
        "- 不要向外部频道发送消息。",
        "- 第一版由小工具负责写回任务文件和 tasks.json；除非用户明确要求，请不要直接编辑共享协同空间文件。",
        "- 涉及删除、卸载、账号、支付、远程控制、隐私文件时，必须提示需要用户确认。",
    ])


def run_blackhole_agent(task_id, agent_id):
    task = next((item for item in load_blackhole_tasks() if item.get("id") == task_id), None)
    if not task:
        return {"ok": False, "error": "task not found"}
    if task.get("status") == "cancelled":
        return {"ok": False, "error": "task cancelled"}
    if agent_id not in task.get("agents", []):
        return {"ok": False, "error": "agent not in task"}
    session_info = task.get("sessions", {}).get(agent_id) or {}
    session_id = session_info.get("sessionId") or str(uuid.uuid4())
    task.setdefault("sessions", {}).setdefault(agent_id, {
        "sessionId": session_id,
        "key": task_session_key(agent_id, session_id),
    })
    result_info = task.setdefault("results", {}).setdefault(agent_id, {})
    if result_info.get("status") in BLACKHOLE_TERMINAL_STATUSES:
        return {"ok": True, "task": blackhole_task_public(task, include_messages=True), "result": result_info}
    result_info.update({"status": "running", "updatedAt": blackhole_now_ms(), "error": ""})
    task["status"] = "running"
    update_blackhole_task(task)
    session = {
        "agentId": agent_id,
        "sessionId": session_id,
        "key": task_session_key(agent_id, session_id),
        "channel": "",
        "to": "",
        "accountId": "",
    }
    prompt = blackhole_agent_prompt(task, agent_id)
    result = send_to_session(session, prompt, deliver=False)
    used_fallback_model = ""
    if not result.get("ok") and agent_id in {"codex-agent", "executor-agent", "guardian-agent"}:
        result_info.update({
            "status": "running",
            "updatedAt": blackhole_now_ms(),
            "error": f"主模型失败，正在使用 {BLACKHOLE_REQUIRED_FALLBACK_MODEL} 兜底重试。",
        })
        update_blackhole_task(task)
        fallback_session = {
            "agentId": BLACKHOLE_FALLBACK_AGENT_ID,
            "sessionId": f"fallback-{agent_id}-{session_id}",
            "key": task_session_key(BLACKHOLE_FALLBACK_AGENT_ID, f"fallback-{agent_id}-{session_id}"),
            "channel": "",
            "to": "",
            "accountId": "",
        }
        fallback_prompt = "\n".join([
            f"你正在作为 {agent_id} 的 DeepSeek 兜底运行。",
            f"原 agent 的 OpenAI/Codex 订阅模型当前不可用，请严格按 {agent_id} 的角色要求完成任务。",
            "",
            prompt,
        ])
        result = send_to_session(fallback_session, fallback_prompt, deliver=False)
        if result.get("ok"):
            used_fallback_model = BLACKHOLE_REQUIRED_FALLBACK_MODEL
    task = next((item for item in load_blackhole_tasks() if item.get("id") == task_id), task)
    result_info = task.setdefault("results", {}).setdefault(agent_id, {})
    if task.get("status") == "cancelled" or result_info.get("status") in {"skipped", "cancelled"}:
        finalize_blackhole_task_status(task)
        update_blackhole_task(task)
        return {"ok": True, "task": blackhole_task_public(task, include_messages=True), "result": result_info}
    if result.get("ok"):
        result_info.update({
            "status": "done",
            "text": (f"【已使用 DeepSeek 兜底：{used_fallback_model}】\n\n" if used_fallback_model else "") + (result.get("text") or ""),
            "seconds": result.get("seconds"),
            "updatedAt": blackhole_now_ms(),
            "error": "",
            "fallbackModel": used_fallback_model,
        })
    else:
        result_info.update({
            "status": "error",
            "text": "",
            "seconds": result.get("seconds"),
            "updatedAt": blackhole_now_ms(),
            "error": result.get("error") or result.get("raw") or "运行失败",
        })
    all_results = task.get("results") or {}
    if all((all_results.get(agent_id) or {}).get("status") in BLACKHOLE_TERMINAL_STATUSES for agent_id in task.get("agents", [])):
        task["status"] = "done"
    update_blackhole_task(task)
    EVENT_HUB.publish("messages", {"keys": [task_session_key(agent_id, session_id)]})
    EVENT_HUB.publish("sessions", {})
    return {"ok": result.get("ok"), "task": blackhole_task_public(task, include_messages=True), "result": result_info}


def run_blackhole_task_worker(task_id):
    task = next((item for item in load_blackhole_tasks() if item.get("id") == task_id), None)
    if not task:
        return
    for agent_id in task.get("agents", []):
        current = next((item for item in load_blackhole_tasks() if item.get("id") == task_id), task)
        if current.get("status") in {"cancelled", "done"}:
            break
        status = ((current.get("results") or {}).get(agent_id) or {}).get("status")
        if status in BLACKHOLE_TERMINAL_STATUSES:
            continue
        if status == "running":
            break
        try:
            run_blackhole_agent(task_id, agent_id)
        except Exception as exc:
            current = next((item for item in load_blackhole_tasks() if item.get("id") == task_id), task)
            status = ((current.get("results") or {}).get(agent_id) or {}).get("status")
            if current.get("status") == "cancelled" or status in {"skipped", "cancelled"}:
                continue
            current.setdefault("results", {}).setdefault(agent_id, {}).update({
                "status": "error",
                "error": str(exc),
                "updatedAt": blackhole_now_ms(),
            })
            update_blackhole_task(current)


def start_blackhole_task(task_id):
    task = next((item for item in load_blackhole_tasks() if item.get("id") == task_id), None)
    if not task:
        return {"ok": False, "error": "task not found"}
    if task.get("status") == "running":
        schedule_blackhole_worker(task_id)
        return {"ok": True, "task": blackhole_task_public(task, include_messages=True), "message": "任务已在运行，已尝试接续调度。"}
    if task.get("status") == "cancelled":
        return {"ok": False, "error": "任务已手动结束，不能继续运行。可以新建一个黑洞任务。"}
    task["status"] = "running"
    for agent_id in task.get("agents", []):
        task.setdefault("results", {}).setdefault(agent_id, {"status": "pending"})
    update_blackhole_task(task)
    schedule_blackhole_worker(task_id)
    return {"ok": True, "task": blackhole_task_public(task, include_messages=True)}


def make_handover(session_key, auto=False, reason="manual"):
    session = next((s for s in list_sessions() if s["key"] == session_key), None)
    if not session:
        return {"ok": False, "error": "session not found"}
    messages = read_messages(session["sessionFile"], limit=80)
    target_dir = AUTO_HANDOVER_DIR if auto else HANDOVER_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if auto:
        short_id = safe_filename(session["sessionId"] or session["key"])[:24]
        file_name = f"当前-{safe_filename(session['agentId'])}-{safe_filename(session['chatType'])}-{short_id}.md"
    else:
        file_name = f"{stamp}-{safe_filename(session['agentId'])}-{safe_filename(session['chatType'])}.md"
    path = target_dir / file_name
    recent = messages[-20:]
    last_user = next((m for m in reversed(messages) if m["role"] == "user"), None)
    last_assistant = next((m for m in reversed(messages) if m["role"] == "assistant"), None)
    lines = [
        "# OpenClaw 接力摘要",
        "",
        f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Agent: `{session['agentId']}`",
        f"- Channel: `{session['channel'] or '-'}`",
        f"- Chat type: `{session['chatType']}`",
        f"- Account ID: `{session['accountId'] or '-'}`",
        f"- Session key: `{session['key']}`",
        f"- Session ID: `{session['sessionId']}`",
        f"- Model: `{session['model'] or '-'}`",
        f"- Harness: `{session['harness'] or '-'}`",
        f"- Context: `{session['totalTokens']}/{session['contextTokens']}` tokens ({session['tokenPercent']}%, {session['tokenSource']})",
        f"- Trigger: `{reason}`",
        f"- Session file: `{session['sessionFile']}`",
        "",
        "## 接续提示",
        "",
        "请根据这份 OpenClaw 接力摘要继续工作。优先保留目标、关键路径、当前 session key、已完成事项和下一步；不要要求重新解释全部历史。",
        "",
        "## 当前状态",
        "",
        "- 当前目标: 待在新会话中补充或由接续 agent 根据最近消息判断",
        "- 已完成事项: 参考下面的最近关键对话",
        "- 下一步: 先确认本摘要中的 session key 和最近用户意图，再继续执行",
        "",
        "## 最近用户消息",
        "",
        (last_user["text"] if last_user else "无"),
        "",
        "## 最近助手回复",
        "",
        (last_assistant["text"] if last_assistant else "无"),
        "",
        "## 最近关键对话",
        "",
    ]
    for message in recent:
        text = message["text"].strip()
        if len(text) > 1800:
            text = text[:1800].rstrip() + "\n...[已截断]"
        lines.extend([
            f"### {message['role']}" + (f" · {message['model']}" if message.get("model") else ""),
            "",
            text,
            "",
        ])
    lines.extend([
        "## 使用方式",
        "",
        "在新会话中发送：",
        "",
        "```text",
        "请读取这份 OpenClaw 接力摘要，并从“下一步”继续。需要时可以根据 session key 回到原 OpenClaw TUI 或网页工具查看完整历史。",
        "```",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    prompt = (
        "请读取这份 OpenClaw 接力摘要，并从“下一步”继续。"
        f"\n摘要文件：{path}"
        f"\n原 session key：{session['key']}"
    )
    return {"ok": True, "path": str(path), "dir": str(target_dir), "prompt": prompt}


def open_path(path):
    if sys.platform != "darwin":
        return {"ok": False, "error": "自动打开文件夹目前只支持 macOS。路径：" + str(path)}
    subprocess.Popen(["open", str(path)])
    return {"ok": True}


def auto_handover_status():
    state = read_json(AUTO_STATE_FILE) or {}
    rows = []
    for session in list_sessions():
        should_auto = session["tokenRatio"] >= AUTO_HANDOVER_RATIO
        last = state.get(session["key"]) or {}
        rows.append({
            "key": session["key"],
            "label": session["label"],
            "agentId": session["agentId"],
            "chatType": session["chatType"],
            "updatedText": session["updatedText"],
            "tokenPercent": session["tokenPercent"],
            "totalTokens": session["totalTokens"],
            "contextTokens": session["contextTokens"],
            "tokenLevel": session["tokenLevel"],
            "shouldAutoHandover": should_auto,
            "lastAutoAt": last.get("at"),
            "lastAutoText": fmt_time((last.get("at") or 0) * 1000),
            "lastPath": last.get("path") or "",
        })
    return {
        "enabled": True,
        "thresholdPercent": int(AUTO_HANDOVER_RATIO * 100),
        "checkSeconds": AUTO_HANDOVER_CHECK_SECONDS,
        "directory": str(AUTO_HANDOVER_DIR),
        "sessions": rows,
    }


def run_auto_handover_once():
    state = read_json(AUTO_STATE_FILE) or {}
    now = int(time.time())
    changed = False
    generated = []
    for session in list_sessions():
        if session["tokenRatio"] < AUTO_HANDOVER_RATIO:
            continue
        if not session.get("updatedAt"):
            continue
        last = state.get(session["key"]) or {}
        last_at = int(last.get("at") or 0)
        last_updated_at = int(last.get("sessionUpdatedAt") or 0)
        if now - last_at < AUTO_HANDOVER_MIN_SECONDS and session["updatedAt"] == last_updated_at:
            continue
        reason = f"auto-context-{session['tokenPercent']}%"
        result = make_handover(session["key"], auto=True, reason=reason)
        if result.get("ok"):
            state[session["key"]] = {
                "at": now,
                "path": result["path"],
                "tokenPercent": session["tokenPercent"],
                "totalTokens": session["totalTokens"],
                "contextTokens": session["contextTokens"],
                "sessionUpdatedAt": session["updatedAt"],
            }
            generated.append(result)
            changed = True
    if changed:
        write_json(AUTO_STATE_FILE, state)
    return {"ok": True, "generated": generated}


def auto_handover_loop():
    while True:
        try:
            run_auto_handover_once()
        except Exception as exc:
            print(f"auto handover check failed: {exc}")
        time.sleep(AUTO_HANDOVER_CHECK_SECONDS)


def send_channel_message(session, message, media_paths=None):
    openclaw_bin = openclaw_cli()
    if not openclaw_bin:
        return {"ok": False, "error": "缺少 openclaw 命令，无法同步到频道端。"}
    channel = session.get("channel") or ""
    account_id = session.get("accountId") or ""
    target = session.get("to") or ""
    if not channel or not target:
        return {"ok": False, "error": "当前 session 缺少 channel 或 target，无法同步到频道端。"}
    media_paths = [path for path in (media_paths or []) if path]
    results = []

    def run_message_send(body="", media_path=""):
        cmd = [
            openclaw_bin,
            "message",
            "send",
            "--channel",
            channel,
            "--target",
            target,
            "--json",
        ]
        if body:
            cmd.extend(["--message", body])
        if media_path:
            cmd.extend(["--media", media_path])
        if account_id:
            cmd.extend(["--account", account_id])
        raw = run(cmd, timeout=120)
        try:
            data = json.loads(raw)
        except Exception:
            return {"ok": False, "raw": raw}
        return {"ok": not data.get("error"), "raw": data}

    if message.strip():
        results.append(run_message_send(message))
    for media_path in media_paths:
        caption = f"【桌面端附件】{Path(media_path).name}"
        results.append(run_message_send(caption, media_path))
    if not results:
        return {"ok": False, "error": "没有可同步到频道端的消息或附件。"}
    failed = next((item for item in results if not item.get("ok")), None)
    return {"ok": failed is None, "results": results, "raw": results[-1].get("raw")}


def send_to_session(session, message, deliver=False, mirror_user_message=False, attachments=None, model_override=None):
    openclaw_bin = openclaw_cli()
    if not openclaw_bin:
        return {
            "ok": False,
            "error": "缺少 openclaw 命令。请先安装并配置 OpenClaw CLI，再重新打开这个工具。",
        }
    mirror_result = None
    attachments = attachments or []
    if deliver and mirror_user_message:
        mirror_text = "【桌面端发送】\n" + message
        media_paths = [item.get("path") for item in attachments if isinstance(item, dict)]
        mirror_result = send_channel_message(session, mirror_text, media_paths=media_paths)
    cmd = [
        openclaw_bin,
        "agent",
        "--agent",
        session["agentId"],
        "--session-id",
        session["sessionId"],
        "--message",
        message,
        "--json",
    ]
    if deliver:
        cmd.append("--deliver")
    if model_override:
        cmd.extend(["--model", model_override])
    started = time.time()
    raw = run(cmd, timeout=600)
    elapsed = time.time() - started
    try:
        data = json.loads(raw)
    except Exception:
        return {"ok": False, "raw": raw, "seconds": elapsed}
    text = ""
    payloads = (((data.get("result") or {}).get("payloads")) or [])
    if payloads:
        text = "\n".join([p.get("text", "") for p in payloads if p.get("text")])
    meta = ((data.get("result") or {}).get("meta")) or {}
    return {
        "ok": data.get("status") == "ok",
        "text": text or meta.get("finalAssistantVisibleText") or "",
        "meta": meta,
        "seconds": elapsed,
        "mirror": mirror_result,
        "raw": data,
    }


def open_tui_in_terminal(session_key):
    openclaw_bin = openclaw_cli()
    if not openclaw_bin:
        return {"ok": False, "error": "缺少 openclaw 命令，无法打开 TUI。"}
    if sys.platform != "darwin" or not shutil.which("osascript"):
        return {
            "ok": False,
            "error": "自动打开 Terminal 目前只支持 macOS。请手动运行：openclaw tui --session " + session_key,
        }
    command = " ".join([
        "cd",
        shlex.quote(os.getcwd()),
        "&&",
        shlex.quote(openclaw_bin),
        "tui",
        "--session",
        shlex.quote(session_key),
    ])
    apple_command = command.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.Popen([
        "osascript",
        "-e",
        f'tell application "Terminal" to do script "{apple_command}"',
        "-e",
        'tell application "Terminal" to activate',
    ])
    return {"ok": True, "command": command}


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpenClaw 智能体工作室</title>
  <style>
    :root {
      color-scheme: light;
      --primary: #5645d4;
      --primary-pressed: #4534b3;
      --brand-navy: #0a1530;
      --brand-navy-deep: #070f24;
      --brand-navy-mid: #1a2a52;
      --link-blue: #0075de;
      --orange: #dd5b00;
      --pink: #ff64c8;
      --purple: #7b3ff2;
      --teal: #2a9d99;
      --green: #1aae39;
      --yellow: #f5d75e;
      --canvas: #ffffff;
      --surface: #f6f5f4;
      --surface-soft: #fafaf9;
      --hairline: #e5e3df;
      --hairline-soft: #ede9e4;
      --hairline-strong: #c8c4be;
      --ink: #1a1a1a;
      --charcoal: #37352f;
      --slate: #5d5b54;
      --steel: #787671;
      --muted: #bbb8b1;
      --peach: #ffe8d4;
      --rose: #fde0ec;
      --mint: #d9f3e1;
      --lavender: #e6e0f5;
      --sky: #dcecfa;
      --cream: #f8f5e8;
      --error: #e03131;
      font-family: "Notion Sans", Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
    }
    * { box-sizing: border-box; }
    html, body { width: 100%; max-width: 100%; overflow: hidden; }
    body { margin: 0; background: var(--surface); color: var(--ink); }
    main { width: 100%; max-width: 100%; height: 100vh; height: 100dvh; min-height: 0; min-width: 0; display: grid; grid-template-columns: minmax(300px, 360px) minmax(0, 1fr); transition: grid-template-columns .18s ease; background: var(--surface); overflow: hidden; }
    main.sidebarCollapsed { grid-template-columns: 68px 1fr; }
    aside { border-right: 1px solid var(--hairline); background: var(--surface-soft); overflow: auto; min-width: 0; max-width: 100%; }
    section { display: grid; grid-template-rows: auto auto auto auto auto 1fr auto; min-width: 0; min-height: 0; height: 100vh; height: 100dvh; overflow: hidden; background: var(--canvas); }
    header { padding: 14px 16px; border-bottom: 1px solid var(--hairline); display: flex; gap: 10px; align-items: center; justify-content: space-between; min-width: 0; max-width: 100%; }
    .mainHeader { padding: 12px 18px; min-height: 64px; background: var(--canvas); }
    .mainHeader > div:first-child { min-width: 0; max-width: 100%; overflow: hidden; }
    .mainHeader h1 { font-size: 18px; line-height: 1.25; font-weight: 600; color: var(--ink); overflow-wrap: anywhere; word-break: break-word; }
    .sideHeader { align-items: flex-start; background: var(--brand-navy); color: #fff; border-bottom: 0; }
    .sideActions { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
    .modeSwitch { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
    .modeBtn { padding: 6px 10px; font-size: 12px; background: transparent; color: #fff; border: 1px solid rgba(255,255,255,.3); }
    .modeBtn.active { background: #fff; color: var(--brand-navy); border-color: #fff; }
    .collapseBtn { width: 38px; height: 38px; padding: 0; font-size: 18px; line-height: 1; }
    main.sidebarCollapsed aside { overflow: auto; background: var(--brand-navy); }
    main.sidebarCollapsed .sideHeader { padding: 10px 7px; justify-content: center; }
    main.sidebarCollapsed .sideTitle, main.sidebarCollapsed #newBlackhole { display: none; }
    main.sidebarCollapsed .collapseBtn { transform: rotate(180deg); }
    h1 { font-size: 20px; margin: 0; font-weight: 600; line-height: 1.25; letter-spacing: 0; }
    .sideTitle h1 { color: #fff; font-size: 22px; }
    .sub { color: var(--steel); font-size: 12px; margin-top: 4px; line-height: 1.4; overflow-wrap: anywhere; word-break: break-word; }
    .sideHeader .sub { color: rgba(255,255,255,.68); }
    button { border: 0; border-radius: 8px; background: var(--primary); color: #fff; font-weight: 500; padding: 9px 12px; cursor: pointer; font-size: 13px; line-height: 1.3; font-family: inherit; }
    button:hover { background: var(--primary-pressed); }
    button.secondary { background: var(--canvas); color: var(--ink); border: 1px solid var(--hairline-strong); }
    button.secondary:hover { background: var(--surface); }
    .sideHeader button.secondary { background: rgba(255,255,255,.12); color: #fff; border-color: rgba(255,255,255,.25); }
    .sideHeader button.secondary:hover { background: rgba(255,255,255,.2); }
    button.small { padding: 6px 9px; font-size: 12px; background: var(--primary); }
    button.danger { background: #fff; color: var(--error); border: 1px solid #f4b8b8; }
    button.danger:hover { background: #fff5f5; }
    button:disabled { opacity: .55; cursor: wait; }
    .session { padding: 12px 14px; border-bottom: 1px solid var(--hairline); cursor: pointer; background: var(--surface-soft); }
    .session:hover { background: #fff; }
    .session.active { background: var(--lavender); box-shadow: inset 3px 0 0 var(--primary); }
    .sessionIcon { display: none; }
    main.sidebarCollapsed .session { padding: 8px 0; min-height: 48px; display: flex; align-items: center; justify-content: center; background: var(--brand-navy); border-color: rgba(255,255,255,.1); }
    main.sidebarCollapsed .sessionTop, main.sidebarCollapsed .meta { display: none; }
    main.sidebarCollapsed .sessionIcon { display: flex; width: 38px; height: 38px; align-items: center; justify-content: center; border-radius: 12px; background: rgba(255,255,255,.12); color: #fff; font-weight: 700; font-size: 13px; border: 1px solid transparent; }
    main.sidebarCollapsed .session.active .sessionIcon { border-color: #fff; background: var(--primary); color: #fff; }
    main.sidebarCollapsed .sessionIcon.phone { background: var(--green); color: #fff; }
    main.sidebarCollapsed .sessionIcon.group { background: var(--orange); color: #fff; }
    main.sidebarCollapsed .sessionIcon.draft { background: var(--purple); color: #fff; }
    main.sidebarCollapsed .sessionIcon.blackhole { background: var(--brand-navy-mid); color: #fff; }
    .sessionTop { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
    .title { font-weight: 600; overflow-wrap: anywhere; line-height: 1.3; min-width: 0; font-size: 14px; color: var(--ink); }
    .meta { color: var(--steel); font-size: 11px; margin-top: 6px; line-height: 1.4; overflow-wrap: anywhere; }
    .metaLine { margin-top: 4px; }
    .preview { color: var(--slate); font-size: 12px; margin-top: 6px; line-height: 1.35; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .badge { display: inline-block; padding: 2px 7px; border-radius: 999px; background: var(--cream); color: var(--charcoal); margin: 0 4px 4px 0; font-size: 11px; border: 1px solid var(--hairline-soft); }
    .badge.green { background: var(--mint); color: #116329; border-color: #bfe7ca; }
    .badge.orange { background: var(--peach); color: #793400; border-color: #ffd1ad; }
    .health { border-bottom: 1px solid var(--hairline); padding: 12px 18px; background: var(--cream); }
    .health.ok { display: none; }
    .health.warn { background: #fef7d6; }
    .health.error { background: #fff0f0; }
    .healthTitle { font-weight: 600; margin-bottom: 8px; }
    .healthItem { border-top: 1px solid rgba(55,53,47,.1); padding: 7px 0; color: var(--charcoal); font-size: 12px; line-height: 1.4; }
    .healthItem:first-of-type { border-top: 0; }
    .healthLevel { display: inline-block; min-width: 42px; font-weight: 600; }
    .healthLevel.ok { color: var(--green); }
    .healthLevel.warn { color: var(--orange); }
    .healthLevel.error { color: var(--error); }
    .handover { border-bottom: 1px solid var(--hairline); padding: 10px 18px; background: var(--sky); display: none; color: var(--charcoal); font-size: 12px; line-height: 1.45; }
    .handover.show { display: block; }
    .handover code { color: var(--brand-navy); overflow-wrap: anywhere; }
    .blackholeWorkshopSlot { display: none; border-bottom: 0; padding: 5px 18px 0; background: var(--surface-soft); overflow-x: auto; }
    .blackholeWorkshopSlot.show { display: block; }
    .autoStatus { border-bottom: 1px solid var(--hairline); padding: 6px 18px 8px; color: var(--slate); font-size: 11px; background: var(--surface-soft); overflow-wrap: anywhere; word-break: break-word; }
    .syncStatus { color: var(--steel); font-size: 11px; margin-top: 4px; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .topBar { display: flex; gap: 8px; align-items: center; justify-content: flex-end; flex-shrink: 0; }
    .toolsMenu { position: relative; }
    .toolsMenu summary { list-style: none; border-radius: 8px; background: var(--brand-navy); color: #fff; font-weight: 600; padding: 9px 10px; cursor: pointer; font-size: 18px; min-width: 42px; text-align: center; white-space: nowrap; line-height: 1; }
    .toolsMenu summary::-webkit-details-marker { display: none; }
    .toolsPanel { position: absolute; right: 0; top: 40px; display: grid; gap: 8px; min-width: 280px; padding: 10px; border: 1px solid var(--hairline); border-radius: 12px; background: var(--canvas); box-shadow: 0 18px 50px rgba(10,21,48,.16); z-index: 20; }
    .toolGroup { border-top: 1px solid var(--hairline); padding-top: 8px; display: grid; gap: 7px; }
    .toolGroup:first-child { border-top: 0; padding-top: 0; }
    .toolSearchRow { display: grid; grid-template-columns: 1fr auto; gap: 7px; align-items: center; }
    .toolButtonRow { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
    .toolsPanel input { min-width: 0; border: 1px solid var(--hairline-strong); border-radius: 8px; padding: 8px 10px; background: var(--surface-soft); color: var(--ink); font: inherit; font-size: 13px; }
    .searchCount { color: var(--steel); font-size: 11px; min-width: 54px; text-align: center; }
    .token.warn { color: var(--orange); }
    .token.critical { color: var(--error); }
    #messages { padding: 14px 18px; overflow: auto; overflow-x: hidden; min-height: 0; min-width: 0; font-size: 14px; background: linear-gradient(180deg, var(--canvas) 0%, var(--surface-soft) 100%); }
    .msg { width: fit-content; max-width: min(820px, 88%); min-width: 0; margin: 0 0 10px; padding: 10px 12px; border: 1px solid var(--hairline); border-radius: 12px; background: var(--canvas); line-height: 1.5; color: var(--charcoal); box-shadow: 0 1px 2px rgba(10,21,48,.04); overflow-wrap: anywhere; word-break: break-word; }
    .msg.user { margin-left: auto; background: var(--brand-navy); border-color: var(--brand-navy); color: #fff; }
    .messageText { white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word; }
    .jumpTools { display: none; }
    .newMessageBtn { display: none; background: var(--green); }
    .newMessageBtn.show { display: inline-block; }
    mark { background: var(--yellow); color: var(--ink); border-radius: 3px; padding: 0 2px; }
    section { position: relative; }
    .msg.pending { border-color: var(--primary); box-shadow: 0 0 0 1px rgba(86,69,212,.16) inset; }
    .msg.system { max-width: none; background: var(--cream); color: var(--charcoal); border-style: dashed; }
    .role { color: var(--steel); font-size: 11px; font-weight: 600; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0; }
    .msg.user .role { color: rgba(255,255,255,.7); }
    .msg.compact .role { display: inline; margin: 0 8px 0 0; }
    .msg.compact .messageText { display: inline; }
    .blackholeCreate { border: 1px solid var(--hairline); border-radius: 12px; padding: 16px; background: var(--lavender); margin-bottom: 10px; }
    .agentChecks { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
    .agentCheck { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--hairline-strong); border-radius: 999px; padding: 6px 9px; background: var(--canvas); font-size: 12px; color: var(--charcoal); }
    .agentCheck input { accent-color: var(--primary); }
    .workshopPanel { border: 1px solid var(--hairline); border-radius: 10px; background: linear-gradient(180deg, #fbfaf8 0%, #f4f1ec 100%); padding: 5px; box-shadow: inset 0 1px 0 rgba(255,255,255,.9); }
    .workshopHeader { display: none; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 7px; color: var(--steel); font-size: 11px; }
    .workshopTitle { font-weight: 700; color: var(--charcoal); }
    .workshopGrid { display: grid; grid-template-columns: repeat(5, minmax(62px, 1fr)); gap: 5px; min-width: 0; }
    .workstation { position: relative; min-width: 0; min-height: 50px; border: 1px solid var(--hairline-strong); border-radius: 7px; background: #f7f6f3; overflow: hidden; padding: 4px; box-shadow: 0 1px 2px rgba(10,21,48,.025); filter: grayscale(1) saturate(.15); transition: filter .16s ease, background .16s ease, box-shadow .16s ease, border-color .16s ease; }
    .workstation::before { content: ""; position: absolute; inset: auto 0 0; height: 12px; background: repeating-linear-gradient(90deg, #d9d6cf 0 5px, #ccc7bf 5px 10px); opacity: .72; }
    .workstation[data-status="running"] { filter: none; background: #fff; border-color: rgba(86,69,212,.55); box-shadow: 0 0 0 2px rgba(86,69,212,.1), 0 8px 20px rgba(86,69,212,.08); }
    .workstation[data-status="done"] { filter: grayscale(.4) saturate(.65); background: linear-gradient(180deg, #ffffff 0%, #eef8f0 100%); }
    .workstation[data-status="error"] { filter: none; background: linear-gradient(180deg, #ffffff 0%, #fff0f0 100%); border-color: #f3a4a4; }
    .workstation[data-status="skipped"], .workstation[data-status="cancelled"] { opacity: .58; filter: grayscale(1) saturate(0); }
    .workstation[data-called="true"]:not([data-status="running"]) { border-color: #bcb6ad; background: #fff; }
    .workstation[data-status="resting"] { opacity: .72; }
    .stationLamp { position: absolute; right: 4px; top: 4px; width: 6px; height: 6px; border-radius: 50%; background: var(--muted); box-shadow: 0 0 0 2px rgba(187,184,177,.12); }
    .workstation[data-status="running"] .stationLamp { background: var(--primary); animation: lampPulse 1.1s infinite; }
    .workstation[data-status="done"] .stationLamp { background: var(--green); }
    .workstation[data-status="error"] .stationLamp { background: var(--error); }
    .stationLabel { position: absolute; left: 4px; right: 4px; bottom: 2px; z-index: 3; height: 10px; display: flex; align-items: center; justify-content: center; gap: 3px; font-size: 8px; color: var(--steel); line-height: 1; white-space: nowrap; overflow: hidden; text-align: center; background: rgba(247,246,243,.82); }
    .stationName { display: inline; color: var(--ink); font-weight: 700; font-size: 8px; min-width: 0; max-width: 50%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: right; }
    .stationStatus { flex: 0 0 auto; color: var(--steel); font-size: 8px; }
    .stationScene { position: absolute; left: 50%; top: 12px; width: 56px; height: 24px; transform: translateX(-50%); }
    .desk { position: absolute; left: 15px; bottom: 4px; width: 38px; height: 7px; background: #9c7152; border: 1px solid #624330; box-shadow: inset 0 -2px 0 rgba(0,0,0,.12); }
    .desk::before { content: ""; position: absolute; left: 3px; top: -7px; width: 13px; height: 7px; background: #c8d7e8; border: 1px solid #52647a; box-shadow: inset 0 -2px 0 rgba(82,100,122,.22); }
    .desk::after { content: ""; position: absolute; right: 3px; top: -6px; width: 8px; height: 4px; background: var(--yellow); border: 1px solid #8a7331; }
    .pixelAgent { position: absolute; left: 0; bottom: 4px; width: 14px; height: 18px; image-rendering: pixelated; }
    .pixelAgent::before { content: ""; position: absolute; left: 4px; top: 0; width: 8px; height: 8px; background: #f2b48d; border: 1px solid #503226; box-shadow: 0 8px 0 1px var(--brand-navy-mid), -3px 12px 0 -1px #503226, 12px 12px 0 -1px #503226; }
    .pixelAgent::after { content: ""; position: absolute; left: 6px; top: 3px; width: 1px; height: 1px; background: #222; box-shadow: 4px 0 0 #222; }
    .pixelAgent.executor::before { box-shadow: 0 8px 0 1px var(--orange), -3px 12px 0 -1px #503226, 12px 12px 0 -1px #503226; }
    .pixelAgent.guardian::before { box-shadow: 0 8px 0 1px var(--primary), -3px 12px 0 -1px #503226, 12px 12px 0 -1px #503226; }
    .pixelAgent.memory::before { box-shadow: 0 8px 0 1px var(--green), -3px 12px 0 -1px #503226, 12px 12px 0 -1px #503226; }
    .pixelAgent.researcher::before { box-shadow: 0 8px 0 1px var(--teal), -3px 12px 0 -1px #503226, 12px 12px 0 -1px #503226; }
    .pixelAgent.life::before { box-shadow: 0 8px 0 1px var(--pink), -3px 12px 0 -1px #503226, 12px 12px 0 -1px #503226; }
    .workProp { position: absolute; z-index: 2; }
    .workProp.executor { right: 10px; bottom: 13px; width: 7px; height: 5px; background: var(--orange); border: 1px solid #6e310b; }
    .workProp.guardian { right: 10px; bottom: 12px; width: 7px; height: 10px; background: var(--primary); border: 1px solid var(--brand-navy); border-radius: 4px 4px 5px 5px; }
    .workProp.memory { right: 9px; bottom: 12px; width: 8px; height: 7px; background: var(--mint); border: 1px solid #377b48; box-shadow: 2px 2px 0 #d9f3e1; }
    .workProp.researcher { right: 9px; bottom: 13px; width: 7px; height: 7px; border: 2px solid var(--teal); border-radius: 50%; }
    .workProp.researcher::after { content: ""; position: absolute; right: -5px; bottom: -4px; width: 6px; height: 2px; background: var(--teal); transform: rotate(45deg); }
    .workProp.life { right: 8px; bottom: 12px; width: 9px; height: 9px; background: var(--rose); border: 1px solid #9c3a68; }
    .workProp.life::before { content: ""; position: absolute; left: 1px; right: 1px; top: 3px; height: 1px; background: #9c3a68; box-shadow: 0 3px 0 #9c3a68; }
    .workstation[data-status="running"] .pixelAgent { animation: workerBob .7s steps(2, end) infinite; }
    .workstation[data-status="running"] .desk::before { animation: screenGlow .9s infinite alternate; }
    .workstation[data-status="running"] .workProp.executor { animation: toolTap .45s steps(2, end) infinite; }
    .workstation[data-status="running"] .workProp.guardian { animation: shieldWatch .8s steps(2, end) infinite; }
    .workstation[data-status="running"] .workProp.memory { animation: noteStick .8s steps(2, end) infinite; }
    .workstation[data-status="running"] .workProp.researcher { animation: scanLens .9s steps(3, end) infinite; }
    .workstation[data-status="running"] .workProp.life { animation: calendarFlip 1s steps(2, end) infinite; }
    .workstation[data-status="done"] .pixelAgent { transform: translateY(-2px); }
    .workstation[data-status="error"] .pixelAgent { animation: workerShake .24s linear 4; }
    @keyframes workerBob { 50% { transform: translateY(-2px); } }
    @keyframes workerShake { 25% { transform: translateX(-2px); } 75% { transform: translateX(2px); } }
    @keyframes lampPulse { 50% { box-shadow: 0 0 0 4px rgba(86,69,212,.2); } }
    @keyframes screenGlow { from { filter: brightness(1); } to { filter: brightness(1.18); } }
    @keyframes toolTap { 50% { transform: translateY(3px); } }
    @keyframes shieldWatch { 50% { transform: translateX(-4px); } }
    @keyframes noteStick { 50% { transform: translateY(-3px) rotate(-2deg); } }
    @keyframes scanLens { 50% { transform: translateX(5px); } }
    @keyframes calendarFlip { 50% { transform: rotateX(18deg); } }
    .blackholeGrid { display: grid; gap: 10px; }
    .agentCard { border: 1px solid var(--hairline); border-radius: 12px; background: var(--canvas); padding: 12px; box-shadow: 0 1px 2px rgba(10,21,48,.04); }
    .agentCardHeader { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 8px; }
    .agentName { font-weight: 900; }
    .agentStatus { color: var(--steel); font-size: 12px; }
    .agentStatus.done { color: var(--green); }
    .agentStatus.error { color: var(--error); }
    .agentStatus.running { color: var(--orange); }
    .agentText { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.5; color: var(--charcoal); }
    .archiveList { display: grid; gap: 10px; }
    .archiveItem { border: 1px solid var(--hairline); border-radius: 12px; background: var(--canvas); padding: 12px; }
    .archiveItemHeader { display: flex; justify-content: space-between; gap: 10px; align-items: start; }
    .archiveActions { display: flex; gap: 7px; flex-wrap: wrap; justify-content: flex-end; }
    .doctorPage { display: grid; gap: 12px; }
    .doctorHero { border: 1px solid var(--hairline); border-radius: 12px; background: var(--surface-soft); padding: 14px; }
    .doctorHero h2 { margin: 0 0 6px; font-size: 18px; line-height: 1.3; }
    .doctorHero p { margin: 0; color: var(--slate); line-height: 1.5; }
    .doctorActions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
    .doctorSection { border: 1px solid var(--hairline); border-radius: 12px; background: var(--canvas); overflow: hidden; }
    .doctorSectionHeader { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 11px 12px; border-bottom: 1px solid var(--hairline); background: var(--surface-soft); }
    .doctorSectionTitle { font-weight: 700; }
    .doctorPill { border-radius: 999px; padding: 3px 8px; font-size: 11px; font-weight: 700; border: 1px solid var(--hairline); background: var(--cream); color: var(--charcoal); }
    .doctorPill.ok { background: var(--mint); color: #116329; border-color: #bfe7ca; }
    .doctorPill.warn { background: var(--peach); color: #793400; border-color: #ffd1ad; }
    .doctorPill.error { background: #fff0f0; color: var(--error); border-color: #f4b8b8; }
    .doctorItem { padding: 10px 12px; border-top: 1px solid var(--hairline-soft); display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px; }
    .doctorItem:first-child { border-top: 0; }
    .doctorMark { width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 800; background: var(--cream); color: var(--charcoal); }
    .doctorMark.ok { background: var(--mint); color: #116329; }
    .doctorMark.warn { background: var(--peach); color: #793400; }
    .doctorMark.error { background: #fff0f0; color: var(--error); }
    .doctorItemTitle { font-weight: 700; line-height: 1.4; }
    .doctorDetail { color: var(--slate); font-size: 12px; line-height: 1.45; overflow-wrap: anywhere; }
    .doctorAction { color: var(--steel); font-size: 12px; line-height: 1.45; margin-top: 3px; }
    .doctorPaths { white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; color: var(--slate); background: var(--surface-soft); border: 1px solid var(--hairline); border-radius: 10px; padding: 10px; overflow-wrap: anywhere; }
    form { border-top: 1px solid var(--hairline); padding: 10px 14px calc(16px + env(safe-area-inset-bottom)); background: var(--canvas); min-width: 0; max-width: 100%; overflow: hidden; }
    .composer { position: relative; border: 1px solid var(--hairline-strong); border-radius: 16px; background: var(--canvas); overflow: hidden; box-shadow: 0 4px 18px rgba(10,21,48,.08); min-width: 0; max-width: 100%; }
    textarea { width: 100%; box-sizing: border-box; min-height: 56px; max-height: 220px; resize: none; border: 0; padding: 12px 12px 8px 44px; background: transparent; color: var(--ink); font: inherit; font-size: 14px; outline: none; }
    .resizeHandle { position: absolute; left: 10px; top: 10px; width: 28px; height: 28px; padding: 0; border-radius: 7px; background: transparent; color: var(--steel); border: 1px solid transparent; cursor: ns-resize; z-index: 2; font-size: 17px; line-height: 1; }
    .resizeHandle:hover { background: var(--surface); border-color: var(--hairline); color: var(--ink); }
    .composerToolbar { min-height: 38px; border-top: 1px solid var(--hairline-soft); display: flex; align-items: center; gap: 7px; padding: 6px 8px; min-width: 0; }
    .iconButton { width: 34px; height: 34px; flex: 0 0 34px; padding: 0; border-radius: 8px; background: transparent; color: var(--steel); border: 1px solid transparent; font-size: 18px; line-height: 1; }
    .iconButton:hover { background: var(--surface); border-color: var(--hairline); }
    .iconButton[disabled] { opacity: .45; cursor: not-allowed; }
    .sendIconButton { width: 42px; height: 34px; flex: 0 0 42px; padding: 0; border-radius: 8px; font-size: 18px; line-height: 1; }
    .toolbarSpacer { flex: 1 1 auto; min-width: 4px; }
    .attachmentList { display: none; gap: 6px; flex-wrap: wrap; padding: 0 10px 8px; }
    .attachmentList.show { display: flex; }
    .attachmentChip { display: inline-flex; gap: 6px; align-items: center; max-width: 260px; border: 1px solid var(--hairline); border-radius: 999px; padding: 5px 8px; background: var(--surface-soft); color: var(--charcoal); font-size: 12px; }
    .attachmentName { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .removeAttachment { border: 0; background: transparent; color: var(--steel); padding: 0 2px; font-size: 15px; }
    .removeAttachment:hover { color: var(--error); background: transparent; }
    label { color: var(--slate); font-size: 13px; user-select: none; }
    .deliverStatus { color: var(--steel); font-size: 11px; line-height: 1.35; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 240px; min-width: 0; }
    .deliverStatus.active { color: #116329; }
    .empty { color: var(--steel); padding: 24px; }
    .authOverlay { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; background: rgba(10, 21, 48, .72); backdrop-filter: blur(10px); padding: 18px; }
    .authOverlay[hidden] { display: none; }
    .authCard { width: min(420px, 100%); border: 1px solid var(--hairline); border-radius: 16px; background: var(--canvas); box-shadow: 0 24px 80px rgba(10,21,48,.28); padding: 24px; }
    .authCard h2 { margin: 0 0 8px; font-size: 18px; }
    .authCard p { margin: 0 0 16px; color: var(--slate); line-height: 1.5; }
    .authInput { width: 100%; box-sizing: border-box; border: 1px solid var(--hairline-strong); border-radius: 10px; padding: 11px 12px; background: var(--surface-soft); color: var(--ink); font: inherit; margin-bottom: 12px; }
    .authError { min-height: 18px; color: var(--error); font-size: 12px; margin-top: 10px; }
    @media (max-width: 860px) {
      body { overflow: hidden; }
      main { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(176px, 34dvh) minmax(0, 1fr); }
      main.sidebarCollapsed { grid-template-columns: 1fr; grid-template-rows: 56px 1fr; }
      aside { max-height: none; border-right: 0; border-bottom: 1px solid var(--hairline); }
      section { height: auto; min-height: 0; width: 100%; max-width: 100vw; overflow: hidden; }
      header { padding: 10px 12px; }
      .mainHeader { min-height: 56px; align-items: flex-start; gap: 8px; }
      .mainHeader h1 { font-size: 15px; max-height: 2.5em; overflow: hidden; }
      .sideTitle h1 { font-size: 18px; }
      .sub, .syncStatus { font-size: 11px; }
      .modeSwitch { margin-top: 8px; }
      #sessions { display: flex; overflow-x: auto; overflow-y: hidden; height: calc(100% - 88px); }
      .session { min-width: min(310px, 82vw); border-right: 1px solid var(--hairline); border-bottom: 0; }
      main.sidebarCollapsed aside { max-height: none; }
      main.sidebarCollapsed #sessions { display: none; }
      main.sidebarCollapsed .sideHeader { height: 56px; justify-content: flex-start; }
      .toolsPanel { position: fixed; top: 64px; right: 12px; left: 12px; min-width: 0; max-height: calc(100dvh - 120px); overflow: auto; }
      #messages { padding: 10px 12px; font-size: 13px; display: flex; flex-direction: column; overflow-x: hidden; }
      .msg { width: auto; max-width: calc(100vw - 36px); align-self: flex-start; }
      .msg.user { margin-left: 0; align-self: flex-end; }
      .msg.system { max-width: calc(100vw - 36px); }
      form { padding: 8px calc(10px + env(safe-area-inset-right)) calc(12px + env(safe-area-inset-bottom)) calc(10px + env(safe-area-inset-left)); width: 100%; }
      textarea { min-height: 50px; font-size: 13px; }
      .deliverStatus { max-width: 38vw; }
      .composerToolbar { gap: 5px; }
      .blackholeWorkshopSlot { padding: 5px 10px 0; }
      .workshopPanel { padding: 5px; }
      .workshopGrid { grid-template-columns: repeat(5, minmax(62px, 1fr)); gap: 5px; }
      .workstation { min-height: 50px; padding: 4px; }
      .stationScene { left: 50%; right: auto; top: 12px; width: 56px; height: 24px; transform: translateX(-50%); }
      .desk { left: 15px; right: auto; width: 38px; }
      .stationName { font-size: 8px; }
      .archiveItemHeader, .agentCardHeader { align-items: flex-start; }
    }
    @media (max-width: 390px) {
      .workshopGrid { grid-template-columns: repeat(5, 62px); }
    }
  </style>
</head>
<body>
<div id="authOverlay" class="authOverlay" hidden>
  <div class="authCard">
    <h2>输入访问码</h2>
    <p>手机远程访问需要访问码。本机直接打开 127.0.0.1 不需要输入。</p>
    <input id="authToken" class="authInput" type="password" autocomplete="current-password" placeholder="访问码">
    <button id="authLogin" type="button">进入智能体工作室</button>
    <div id="authError" class="authError"></div>
  </div>
</div>
<main id="layout">
  <aside>
    <header class="sideHeader">
      <div class="sideTitle">
        <h1>OpenClaw 智能体工作室</h1>
        <div class="sub">Codex · OpenClaw · 个人微信 · 企业微信 · 多 agent 协作</div>
        <div class="modeSwitch">
          <button id="sessionsMode" class="modeBtn active">会话</button>
          <button id="blackholeMode" class="modeBtn">黑洞</button>
        </div>
      </div>
      <div class="sideActions">
        <button id="collapseSidebar" class="secondary collapseBtn" title="收起/展开侧边栏">‹</button>
        <button id="newBlackhole" class="secondary">新黑洞</button>
      </div>
    </header>
    <div id="sessions"></div>
  </aside>
  <section>
    <header class="mainHeader">
      <div>
        <h1 id="sessionTitle">请选择一个会话</h1>
        <div id="sessionMeta" class="sub"></div>
        <div id="syncStatus" class="syncStatus">自动同步：等待选择会话</div>
      </div>
      <div class="topBar">
        <details id="toolsMenu" class="toolsMenu">
          <summary title="工具">•••</summary>
          <div class="toolsPanel">
            <div class="toolGroup">
              <button id="openTui" class="secondary">打开 TUI</button>
              <button id="runBlackhole" class="secondary">运行黑洞协作</button>
              <button id="cancelBlackhole" class="secondary">结束黑洞任务</button>
              <button id="openBlackholeFile" class="secondary">打开任务文件</button>
              <button id="reloadMessages" class="secondary">重载消息</button>
              <button id="makeHandover" class="secondary">生成接力摘要</button>
              <button id="openHandoverDir" class="secondary">接力文件夹</button>
              <button id="showSetupDoctor" class="secondary">配置自检</button>
              <button id="showUpgradeGuard" class="secondary">升级护航</button>
              <button id="archiveCurrentSession" class="secondary">归档会话</button>
              <button id="archiveCurrentTask" class="secondary">归档任务</button>
              <button id="showArchiveList" class="secondary">已归档列表</button>
            </div>
            <div class="toolGroup">
              <div class="toolSearchRow">
                <input id="searchBox" type="search" placeholder="查找当前会话记录...">
                <span id="searchCount" class="searchCount">0/0</span>
              </div>
              <div class="toolButtonRow">
                <button id="searchPrev" class="small">上一个</button>
                <button id="searchNext" class="small">下一个</button>
              </div>
              <div class="toolButtonRow">
                <button id="jumpTop" class="small">顶部</button>
                <button id="jumpBottom" class="small">底部</button>
              </div>
              <button id="newMessageBtn" class="small newMessageBtn">新消息</button>
            </div>
          </div>
        </details>
      </div>
    </header>
    <div id="health" class="health ok"></div>
    <div id="handover" class="handover"></div>
    <div id="blackholeWorkshopSlot" class="blackholeWorkshopSlot"></div>
    <div id="autoStatus" class="autoStatus">自动接力摘要检查中...</div>
    <div id="messages"><div class="empty">左侧选择手机私聊主会话后，可以在这里继续同一条 OpenClaw 后端会话。</div></div>
    <form id="sendForm">
      <div class="composer">
        <button id="resizeComposer" class="resizeHandle" type="button" title="拖动调整输入框高度">⌟</button>
        <textarea id="message" placeholder="Message Assistant (Enter to send)"></textarea>
        <div id="attachmentList" class="attachmentList"></div>
        <div class="composerToolbar">
          <input id="attachmentInput" type="file" multiple hidden>
          <button id="attachBtn" class="iconButton" type="button" title="添加附件">📎</button>
          <div id="deliverStatus" class="deliverStatus">选择会话后自动判断是否同步到频道端</div>
          <span class="toolbarSpacer"></span>
          <button id="newSessionBtn" class="iconButton" type="button" title="新建会话">＋</button>
          <button id="sendBtn" class="sendIconButton" type="submit" title="发送">↗</button>
        </div>
      </div>
    </form>
  </section>
</main>
<script>
  let sessions = [];
  let current = null;
  const $ = (id) => document.getElementById(id);
  const nativeFetch = window.fetch.bind(window);
  let appStarted = false;
  let authVisible = false;
  const sidebarKey = "openclawSessionViewer.sidebarCollapsed";
  const draftPrefix = "openclawSessionViewer.draft.";
  const attachmentDrafts = new Map();
  let attachments = [];
  let lastHandover = null;
  let lastMessagesSignature = "";
  let isLoadingMessages = false;
  let isLoadingSessions = false;
  const fallbackPollMs = 60000;
  let currentMessages = [];
  let searchMatches = [];
  let searchIndex = -1;
  let eventSource = null;
  let pushConnected = false;
  let draftSessions = [];
  let viewMode = "sessions";
  let blackholeTasks = [];
  let currentTask = null;

  function showAuth(message = "") {
    authVisible = true;
    $("authOverlay").hidden = false;
    $("authError").textContent = message;
    setTimeout(() => $("authToken").focus(), 30);
  }

  function hideAuth() {
    authVisible = false;
    $("authOverlay").hidden = true;
    $("authError").textContent = "";
  }

  async function authFetch(url, options = {}) {
    const response = await nativeFetch(url, options);
    if (response.status === 401) {
      showAuth("访问码已失效或缺失，请重新输入。");
      throw new Error("unauthorized");
    }
    return response;
  }

  window.fetch = authFetch;

  async function checkAuth() {
    try {
      const status = await nativeFetch("/api/auth/status").then(r => r.json());
      if (status.required && !status.authenticated) {
        showAuth("请输入启动脚本终端里显示的访问码。");
        return false;
      }
      hideAuth();
      return true;
    } catch (error) {
      showAuth("无法检查访问状态，请确认智能体工作室正在运行。");
      return false;
    }
  }

  async function loginWithToken() {
    const token = $("authToken").value.trim();
    if (!token) {
      $("authError").textContent = "请先输入访问码。";
      return;
    }
    $("authLogin").disabled = true;
    $("authLogin").textContent = "验证中";
    try {
      const result = await nativeFetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      }).then(r => r.json());
      if (!result.ok) {
        $("authError").textContent = result.error || "访问码不正确。";
        return;
      }
      $("authToken").value = "";
      hideAuth();
      startApp();
    } catch (error) {
      $("authError").textContent = "验证失败，请稍后重试。";
    } finally {
      $("authLogin").disabled = false;
      $("authLogin").textContent = "进入智能体工作室";
    }
  }
  const blackholeAgents = [
    { id: "executor-agent", label: "CEO" },
    { id: "guardian-agent", label: "守护者" },
    { id: "researcher-agent", label: "研究员" },
    { id: "life-agent", label: "小助理" },
    { id: "memory-agent", label: "档案师" },
  ];
  const defaultBlackholeAgents = ["guardian-agent", "memory-agent", "researcher-agent"];
  let blackholeAgentOrder = blackholeAgents.map(agent => agent.id);
  let blackholeSelectedAgents = new Set(defaultBlackholeAgents);

  function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  }

  function sessionIcon(session) {
    if (session.isDraft) return "+";
    if (session.isPhoneMain) return "微";
    if (session.isGroup) return "群";
    if (session.agentId === "codex-agent") return "C";
    if (session.agentId === "main") return "M";
    return (session.agentId || session.label || "?").slice(0, 1).toUpperCase();
  }

  function sessionIconClass(session) {
    return [
      "sessionIcon",
      session.isDraft ? "draft" : "",
      session.isPhoneMain ? "phone" : "",
      session.isGroup ? "group" : "",
    ].filter(Boolean).join(" ");
  }

  function setMode(mode) {
    saveCurrentDraft();
    saveCurrentAttachments();
    viewMode = mode;
    $("sessionsMode").classList.toggle("active", mode === "sessions");
    $("blackholeMode").classList.toggle("active", mode === "blackhole");
    $("newBlackhole").style.display = mode === "blackhole" ? "" : "none";
    $("searchBox").disabled = mode === "blackhole";
    $("reloadMessages").disabled = mode === "blackhole";
    if (mode === "sessions") {
      currentTask = null;
      $("blackholeWorkshopSlot").className = "blackholeWorkshopSlot";
      $("blackholeWorkshopSlot").innerHTML = "";
      $("message").placeholder = current ? `向 ${current.label} 发送消息...` : "向当前 OpenClaw session 发送消息...";
      loadSessions();
      if (current) loadMessages({ force: true, reason: "事件推送：正在打开会话..." });
    } else {
      current = null;
      currentMessages = [];
      $("message").placeholder = "描述要让多个 agent 协作处理的问题...";
      clearCurrentAttachments();
      loadBlackholeTasks();
      renderBlackholeTask();
    }
    updateToolButtons();
  }

  function updateToolButtons() {
    const isBlackhole = viewMode === "blackhole";
    $("openTui").style.display = isBlackhole ? "none" : "";
    $("reloadMessages").style.display = isBlackhole ? "none" : "";
    $("makeHandover").style.display = isBlackhole ? "none" : "";
    $("archiveCurrentSession").style.display = isBlackhole ? "none" : "";
    $("runBlackhole").style.display = isBlackhole ? "" : "none";
    $("cancelBlackhole").style.display = isBlackhole ? "" : "none";
    $("openBlackholeFile").style.display = isBlackhole ? "" : "none";
    $("archiveCurrentTask").style.display = isBlackhole ? "" : "none";
  }

  function draftKey(sessionKey) {
    return draftPrefix + encodeURIComponent(sessionKey || "");
  }

  function saveCurrentDraft() {
    if (!current) return;
    const value = $("message").value;
    if (value) {
      localStorage.setItem(draftKey(current.key), value);
    } else {
      localStorage.removeItem(draftKey(current.key));
    }
  }

  function restoreDraft(session) {
    $("message").value = session ? (localStorage.getItem(draftKey(session.key)) || "") : "";
    $("message").placeholder = session ? `向 ${session.label} 发送消息...` : "向当前 OpenClaw session 发送消息...";
  }

  function clearCurrentDraft() {
    if (!current) return;
    localStorage.removeItem(draftKey(current.key));
    $("message").value = "";
  }

  function fileSizeText(size) {
    if (!size) return "";
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
  }

  function renderAttachments() {
    const box = $("attachmentList");
    if (!attachments.length) {
      box.className = "attachmentList";
      box.innerHTML = "";
      return;
    }
    box.className = "attachmentList show";
    box.innerHTML = attachments.map((item, i) => `
      <span class="attachmentChip" title="${esc(item.path)}">
        <span class="attachmentName">${esc(item.name)}</span>
        <span>${esc(fileSizeText(item.size))}</span>
        <button class="removeAttachment" type="button" data-remove-attachment="${i}" title="移除附件">×</button>
      </span>
    `).join("");
  }

  function saveCurrentAttachments() {
    if (!current) return;
    if (attachments.length) {
      attachmentDrafts.set(current.key, attachments.slice());
    } else {
      attachmentDrafts.delete(current.key);
    }
  }

  function restoreAttachments(session) {
    attachments = session ? (attachmentDrafts.get(session.key) || []).slice() : [];
    renderAttachments();
  }

  function clearCurrentAttachments() {
    if (current) attachmentDrafts.delete(current.key);
    attachments = [];
    renderAttachments();
  }

  function messageWithAttachments(message, files) {
    if (!files.length) return message;
    const lines = [message, "", "附件："];
    files.forEach((file) => {
      lines.push(`- ${file.name}: ${file.path}`);
    });
    return lines.join("\n");
  }

  function createDraftSession() {
    saveCurrentDraft();
    saveCurrentAttachments();
    const id = crypto.randomUUID();
    const session = {
      key: `agent:codex-agent:explicit:${id}`,
      label: "codex-agent / 新会话",
      preview: "等待发送第一条消息",
      agentId: "codex-agent",
      sessionId: id,
      sessionFile: "",
      chatType: "direct",
      channel: "",
      accountId: "",
      to: "",
      model: "openai/gpt-5.5",
      harness: "codex",
      updatedAt: Date.now(),
      updatedText: "草稿",
      contextTokens: 0,
      totalTokens: 0,
      tokenRatio: 0,
      tokenPercent: 0,
      tokenSource: "draft",
      tokenLevel: "ok",
      isPhoneMain: false,
      isGroup: false,
      isDraft: true,
    };
    draftSessions.unshift(session);
    current = session;
    currentMessages = [];
    lastMessagesSignature = "";
    restoreDraft(current);
    restoreAttachments(current);
    updateDeliverStatus();
    $("sessionTitle").textContent = current.label;
    $("sessionMeta").textContent = `${current.key} | ${current.model} | sessionId=${current.sessionId}`;
    renderMessages({ forceBottom: true });
    loadSessions({ silent: true });
    $("message").focus();
  }

  function channelName(channel) {
    const names = {
      "wecom": "企业微信",
      "openclaw-weixin": "个人微信",
      "feishu": "飞书",
      "lark": "飞书",
      "dingtalk": "钉钉",
      "telegram": "Telegram",
      "slack": "Slack",
      "discord": "Discord",
      "whatsapp": "WhatsApp",
    };
    return names[channel] || channel || "频道";
  }

  function shouldAutoDeliver(session) {
    if (!session) return false;
    if (!session.channel || !session.to) return false;
    return !["webchat", "dashboard"].includes(session.channel);
  }

  function updateDeliverStatus() {
    const box = $("deliverStatus");
    if (!current) {
      box.className = "deliverStatus";
      box.textContent = "选择会话后自动判断是否同步到频道端";
      return;
    }
    if (shouldAutoDeliver(current)) {
      box.className = "deliverStatus active";
      box.textContent = `自动同步到${channelName(current.channel)}端`;
    } else if (current.isDraft) {
      box.className = "deliverStatus";
      box.textContent = "新会话：发送第一条消息后创建";
    } else {
      box.className = "deliverStatus";
      box.textContent = "当前为本地/网页会话，不同步到外部频道";
    }
  }

  function scrollMessagesToBottom() {
    const box = $("messages");
    requestAnimationFrame(() => {
      box.scrollTop = box.scrollHeight;
      requestAnimationFrame(() => {
        box.scrollTop = box.scrollHeight;
      });
    });
  }

  function highlightedText(text) {
    const query = $("searchBox") ? $("searchBox").value.trim() : "";
    if (!query) return esc(text);
    const lower = String(text || "").toLowerCase();
    const needle = query.toLowerCase();
    let out = "";
    let pos = 0;
    while (true) {
      const idx = lower.indexOf(needle, pos);
      if (idx === -1) break;
      out += esc(text.slice(pos, idx));
      out += `<mark>${esc(text.slice(idx, idx + query.length))}</mark>`;
      pos = idx + query.length;
    }
    return out + esc(text.slice(pos));
  }

  function renderMessage(m, i) {
    const isCompact = (m.text || "").length <= 120 && !(m.text || "").includes("\n");
    return `
      <div class="msg ${m.role === "user" ? "user" : ""} ${isCompact ? "compact" : ""}" data-msg="${i}">
        <div class="role">${esc(m.role)} ${m.model ? " · " + esc(m.model) : ""}</div>
        <div class="messageText">${highlightedText(m.text)}</div>
      </div>`;
  }

  function renderMessages({ forceBottom = false } = {}) {
    const box = $("messages");
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
    const emptyText = current && current.isDraft ? "这是一个新会话草稿。输入第一条消息并发送后，会创建到 OpenClaw。" : "这个 session 还没有可显示消息。";
    box.innerHTML = currentMessages.map(renderMessage).join("") || `<div class="empty">${esc(emptyText)}</div>`;
    updateSearchMatches();
    if (forceBottom || nearBottom) {
      scrollMessagesToBottom();
      $("newMessageBtn").classList.remove("show");
    } else {
      $("newMessageBtn").classList.add("show");
    }
  }

  function updateSearchMatches() {
    const query = $("searchBox").value.trim().toLowerCase();
    searchMatches = [];
    if (query) {
      currentMessages.forEach((m, i) => {
        if ((m.text || "").toLowerCase().includes(query)) searchMatches.push(i);
      });
    }
    if (!searchMatches.length) searchIndex = -1;
    if (searchIndex >= searchMatches.length) searchIndex = searchMatches.length - 1;
    $("searchCount").textContent = searchMatches.length ? `${searchIndex + 1 || 1}/${searchMatches.length}` : "0/0";
  }

  function jumpSearch(delta) {
    updateSearchMatches();
    if (!searchMatches.length) return;
    searchIndex = searchIndex === -1 ? 0 : (searchIndex + delta + searchMatches.length) % searchMatches.length;
    $("searchCount").textContent = `${searchIndex + 1}/${searchMatches.length}`;
    const node = $(`messages`).querySelector(`[data-msg="${searchMatches[searchIndex]}"]`);
    if (node) {
      node.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }

  function setSyncStatus(text) {
    $("syncStatus").textContent = text;
  }

  function blackholeStatusText(status) {
    return {
      created: "已创建",
      running: "运行中",
      done: "已完成",
      error: "有错误",
      skipped: "已跳过",
      cancelled: "已结束",
      resting: "发呆",
      pending: "等待",
    }[status] || status || "等待";
  }

  function blackholeTerminalStatus(status) {
    return ["done", "error", "skipped", "cancelled"].includes(status);
  }

  function blackholeAgentLabel(agentId) {
    const item = blackholeAgents.find(agent => agent.id === agentId);
    return item ? item.label : agentId;
  }

  function blackholeAgentRoleClass(agentId) {
    return {
      "executor-agent": "executor",
      "guardian-agent": "guardian",
      "memory-agent": "memory",
      "researcher-agent": "researcher",
      "life-agent": "life",
    }[agentId] || "memory";
  }

  function renderBlackholeWorkshop(task) {
    const results = task.results || {};
    const calledAgents = new Set(task.agents || []);
    const stations = blackholeAgents.map((agent, index) => {
      const agentId = agent.id;
      const called = calledAgents.has(agentId);
      const status = called ? ((results[agentId] || {}).status || "pending") : "resting";
      const roleClass = blackholeAgentRoleClass(agentId);
      return `
        <div class="workstation" data-status="${esc(status)}" data-called="${called ? "true" : "false"}" title="${esc(blackholeAgentLabel(agentId))} · ${esc(blackholeStatusText(status))}">
          <div class="stationLamp"></div>
          <div class="stationLabel">
            <span class="stationName">${index + 1}. ${esc(blackholeAgentLabel(agentId))}</span>
            <span class="stationStatus">${esc(blackholeStatusText(status))}</span>
          </div>
          <div class="stationScene">
            <div class="desk"></div>
            <div class="pixelAgent ${esc(roleClass)}"></div>
            <div class="workProp ${esc(roleClass)}"></div>
          </div>
        </div>`;
    }).join("");
    return `
      <div class="workshopPanel">
        <div class="workshopHeader">
          <span class="workshopTitle">黑洞小工作室</span>
          <span>角色只展示状态，不参与调度</span>
        </div>
        <div class="workshopGrid">${stations || '<div class="empty">暂无工位。</div>'}</div>
      </div>`;
  }

  function blackholeAgentChecks() {
    const labels = Object.fromEntries(blackholeAgents.map(agent => [agent.id, agent.label]));
    return `
      <div class="agentChecks">
        ${blackholeAgentOrder.map((agentId, index) => `
          <label class="agentCheck">
            <input type="checkbox" data-blackhole-agent="${esc(agentId)}" ${blackholeSelectedAgents.has(agentId) ? "checked" : ""}>
            <span>${index + 1}. ${esc(labels[agentId] || agentId)}</span>
            <button class="small" type="button" data-agent-order="up" data-agent-id="${esc(agentId)}" title="提前" ${index === 0 ? "disabled" : ""}>↑</button>
            <button class="small" type="button" data-agent-order="down" data-agent-id="${esc(agentId)}" title="后移" ${index === blackholeAgentOrder.length - 1 ? "disabled" : ""}>↓</button>
          </label>
        `).join("")}
      </div>`;
  }

  function selectedBlackholeAgents() {
    const checked = blackholeAgentOrder.filter(agentId => blackholeSelectedAgents.has(agentId));
    return checked.length ? checked : defaultBlackholeAgents.slice();
  }

  function moveBlackholeAgent(agentId, direction) {
    const index = blackholeAgentOrder.indexOf(agentId);
    if (index === -1) return;
    const next = direction === "up" ? index - 1 : index + 1;
    if (next < 0 || next >= blackholeAgentOrder.length) return;
    [blackholeAgentOrder[index], blackholeAgentOrder[next]] = [blackholeAgentOrder[next], blackholeAgentOrder[index]];
    renderBlackholeTask();
  }

  async function loadBlackholeTasks({ silent = false } = {}) {
    blackholeTasks = await fetch("/api/blackhole/tasks").then(r => r.json());
    renderBlackholeList();
    if (currentTask) {
      const fresh = blackholeTasks.find(task => task.id === currentTask.id);
      if (fresh) {
        currentTask = await fetch(`/api/blackhole/task?id=${encodeURIComponent(fresh.id)}`).then(r => r.json());
        renderBlackholeTask();
      }
    }
    if (!silent) setSyncStatus("黑洞协作：任务变化会通过事件推送自动更新。");
  }

  function renderBlackholeList() {
    $("sessions").innerHTML = blackholeTasks.map((task, i) => `
      <div class="session ${currentTask && currentTask.id === task.id ? "active" : ""}" data-task="${i}" title="${esc(task.title)}">
        <div class="sessionIcon blackhole">洞</div>
        <div class="sessionTop">
          <div class="title">黑洞 · ${esc(task.title)}</div>
        </div>
        <div class="meta">
          <span class="badge">黑洞协作</span><span class="badge">${esc(blackholeStatusText(task.status))}</span>
          <div class="preview" title="${esc(task.prompt || "")}">${esc(task.prompt || "等待任务描述")}</div>
          <div class="metaLine">${esc((task.agents || []).map(blackholeAgentLabel).join("、") || "-")}</div>
          <div class="metaLine">${esc(task.updatedAt ? new Date(task.updatedAt).toLocaleString() : "-")}</div>
        </div>
      </div>`).join("") || '<div class="empty">暂无黑洞协作任务。点击“新黑洞”后输入任务。</div>';
  }

  function renderBlackholeTask() {
    updateToolButtons();
    $("handover").className = "handover";
    $("autoStatus").textContent = "黑洞协作模式：每个 agent 使用独立 session，小工具聚合展示。";
    $("searchBox").value = "";
    $("searchCount").textContent = "0/0";
    if (!currentTask) {
      $("sessionTitle").textContent = "黑洞协作";
      $("sessionMeta").textContent = "输入任务后会创建独立协作窗口，并为每个 agent 建立独立 session。";
      $("blackholeWorkshopSlot").className = "blackholeWorkshopSlot";
      $("blackholeWorkshopSlot").innerHTML = "";
      $("messages").innerHTML = `
        <div class="blackholeCreate">
          <div class="role">黑洞协作任务</div>
          <div class="messageText">在下方输入任务描述，选择参与 agent，发送后会创建一个黑洞协作任务并开始运行。</div>
          ${blackholeAgentChecks()}
        </div>`;
      return;
    }
    $("sessionTitle").textContent = `黑洞协作 · ${currentTask.title}`;
    $("sessionMeta").textContent = `${currentTask.id} | ${blackholeStatusText(currentTask.status)} | ${currentTask.path || ""}`;
    $("blackholeWorkshopSlot").className = "blackholeWorkshopSlot show";
    $("blackholeWorkshopSlot").innerHTML = renderBlackholeWorkshop(currentTask);
    const messages = currentTask.messages || {};
    const cards = (currentTask.agents || []).map(agentId => {
      const result = (currentTask.results || {})[agentId] || {};
      const agentMessages = messages[agentId] || [];
      const lastAssistant = [...agentMessages].reverse().find(m => m.role === "assistant");
      const text = result.error || result.text || (lastAssistant && lastAssistant.text) || "等待运行。";
      const session = (currentTask.sessions || {})[agentId] || {};
      const key = session.key || (session.sessionId ? `agent:${agentId}:explicit:${session.sessionId}` : "");
      const status = result.status || "pending";
      const controls = [
        key ? `<button class="small" data-task-tui="${esc(key)}">TUI</button>` : "",
        !blackholeTerminalStatus(status) ? `<button class="small" data-agent-done="${esc(agentId)}">标记完成</button>` : "",
        !blackholeTerminalStatus(status) ? `<button class="small" data-agent-skip="${esc(agentId)}">跳过</button>` : "",
      ].filter(Boolean).join("");
      return `
        <div class="agentCard">
          <div class="agentCardHeader">
            <div>
              <div class="agentName">${esc(blackholeAgentLabel(agentId))} · ${esc(agentId)}</div>
              <div class="agentStatus ${esc(status)}">${esc(blackholeStatusText(status))}${result.seconds ? ` · ${Number(result.seconds).toFixed(1)}s` : ""}</div>
            </div>
            <div class="archiveActions">${controls}</div>
          </div>
          <div class="agentText">${highlightedText(text)}</div>
        </div>`;
    }).join("");
    $("messages").innerHTML = `
      <div class="blackholeGrid">
        <div class="msg system">
          <div class="role">task</div>
          <div class="messageText">${esc(currentTask.prompt || "")}</div>
        </div>
        ${cards || '<div class="empty">这个黑洞任务还没有 agent。</div>'}
      </div>`;
    scrollMessagesToBottom();
  }

  async function createAndRunBlackholeTask(message) {
    const agents = selectedBlackholeAgents();
    const title = message.split(/\n/)[0].replace(/^\/黑洞\s*/, "").slice(0, 60) || "黑洞协作任务";
    $("sendBtn").disabled = true;
    $("sendBtn").textContent = "...";
    try {
      setSyncStatus("黑洞协作：正在创建任务...");
      const createdResponse = await fetch("/api/blackhole/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, prompt: message, agents }),
      });
      const created = await createdResponse.json();
      if (!created.ok) return alert(created.error || "创建黑洞任务失败");
      currentTask = created.task;
      $("message").value = "";
      renderBlackholeTask();
      await loadBlackholeTasks({ silent: true });
      setSyncStatus("黑洞协作：任务已创建，正在启动各 agent...");
      const startedResponse = await fetch("/api/blackhole/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: currentTask.id }),
      });
      const started = await startedResponse.json();
      if (!started.ok) alert(started.error || "启动黑洞协作失败");
      setSyncStatus("黑洞协作：已启动，各 agent 会陆续写回结果。");
    } catch (error) {
      const message = `黑洞协作：创建或启动失败：${error}`;
      setSyncStatus(message);
      alert(message);
    } finally {
      $("sendBtn").disabled = false;
      $("sendBtn").textContent = "↗";
    }
  }

  async function archiveCurrentSession() {
    if (!current) return alert("先选一个 session");
    if (current.isDraft) return alert("新会话草稿还没有创建到 OpenClaw，不需要归档。");
    if (!confirm(`归档这个会话？\n\n${current.label}\n\n归档后左侧不再显示，但可以在“已归档列表”恢复。`)) return;
    const result = await fetch("/api/session/archive", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: current.key }),
    }).then(r => r.json());
    if (!result.ok) return alert(result.error || "归档失败");
    current = null;
    currentMessages = [];
    lastMessagesSignature = "";
    $("sessionTitle").textContent = "请选择一个会话";
    $("sessionMeta").textContent = "";
    $("messages").innerHTML = '<div class="empty">会话已归档。可在“工具 → 已归档列表”中恢复或永久删除。</div>';
    await loadSessions({ silent: true });
    setSyncStatus("已归档会话。");
  }

  async function archiveCurrentBlackholeTask() {
    if (!currentTask) return alert("先选择一个黑洞任务");
    if (!confirm(`归档这个黑洞任务？\n\n${currentTask.title}\n\n归档后左侧不再显示，但可以在“已归档列表”恢复。`)) return;
    const result = await fetch("/api/blackhole/archive", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: currentTask.id }),
    }).then(r => r.json());
    if (!result.ok) return alert(result.error || "归档失败");
    currentTask = null;
    await loadBlackholeTasks({ silent: true });
    renderBlackholeTask();
    setSyncStatus("已归档黑洞任务。");
  }

  async function setCurrentBlackholeAgentStatus(agentId, status) {
    if (!currentTask) return;
    const label = blackholeAgentLabel(agentId);
    const actionText = status === "skipped" ? "跳过" : "标记完成";
    if (!confirm(`${actionText} ${label}？\n\n这会更新任务索引和 Obsidian 任务文件。`)) return;
    const result = await fetch("/api/blackhole/agent-status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: currentTask.id, agentId, status }),
    }).then(r => r.json());
    if (!result.ok) return alert(result.error || "更新失败");
    currentTask = result.task;
    await loadBlackholeTasks({ silent: true });
    renderBlackholeTask();
    setSyncStatus(`已${actionText} ${label}。`);
  }

  async function cancelCurrentBlackholeTask() {
    if (!currentTask) return alert("先选择一个黑洞任务");
    if (!confirm(`结束这个黑洞任务？\n\n${currentTask.title}\n\n未完成的 agent 会标记为“已结束”。已经在后台运行的 OpenClaw 调用可能会自然返回，但小工具不会再采用它覆盖手动状态。`)) return;
    const result = await fetch("/api/blackhole/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: currentTask.id }),
    }).then(r => r.json());
    if (!result.ok) return alert(result.error || "结束失败");
    currentTask = result.task;
    await loadBlackholeTasks({ silent: true });
    renderBlackholeTask();
    setSyncStatus("黑洞任务已手动结束。");
  }

  function archivedItemHtml(item) {
    const isTask = item.kind === "blackhole";
    const title = isTask ? `黑洞 · ${item.title || item.id}` : item.label;
    const meta = isTask
      ? `${(item.agents || []).map(blackholeAgentLabel).join("、") || "-"} · ${item.archivedText || "-"}`
      : `${item.agentId || "-"} · ${item.model || "-"} · ${item.archivedText || "-"}`;
    const preview = isTask ? (item.prompt || "") : (item.preview || "");
    return `
      <div class="archiveItem">
        <div class="archiveItemHeader">
          <div>
            <div class="agentName">${esc(title)}</div>
            <div class="agentStatus">${esc(meta)}</div>
            ${preview ? `<div class="preview" title="${esc(preview)}">${esc(preview)}</div>` : ""}
          </div>
          <div class="archiveActions">
            <button class="small" data-archive-restore="${esc(item.archiveId)}" data-archive-kind="${esc(item.kind)}">恢复</button>
            <button class="small danger" data-archive-delete="${esc(item.archiveId)}" data-archive-kind="${esc(item.kind)}">永久删除</button>
          </div>
        </div>
      </div>`;
  }

  async function showArchiveList() {
    const archive = await fetch("/api/archive").then(r => r.json());
    const sessions = archive.sessions || [];
    const tasks = archive.blackholeTasks || [];
    $("sessionTitle").textContent = "已归档列表";
    $("sessionMeta").textContent = "默认只是归档；永久删除需要二次确认。";
    setSyncStatus(`已归档：${sessions.length} 个会话，${tasks.length} 个黑洞任务。`);
    $("messages").innerHTML = `
      <div class="archiveList">
        <div class="msg system">
          <div class="role">已归档会话</div>
          <div class="messageText">${sessions.length ? "" : "暂无已归档会话。"}</div>
        </div>
        ${sessions.map(archivedItemHtml).join("")}
        <div class="msg system">
          <div class="role">已归档黑洞任务</div>
          <div class="messageText">${tasks.length ? "" : "暂无已归档黑洞任务。"}</div>
        </div>
        ${tasks.map(archivedItemHtml).join("")}
      </div>`;
  }

  function doctorLevelText(level) {
    return { ok: "正常", warn: "提醒", error: "错误" }[level] || level || "-";
  }

  function doctorMark(level) {
    return { ok: "✓", warn: "!", error: "×" }[level] || "·";
  }

  function renderSetupDoctor(report) {
    $("sessionTitle").textContent = "配置自检";
    $("sessionMeta").textContent = `Setup Doctor · 当前版本 ${report.version || "-"} · ${report.needsSetup ? "建议确认本机初始化" : "本机初始化已记录"}`;
    setSyncStatus("配置自检：检查基础服务、OpenClaw、多 agent、Obsidian 和升级状态。");
    $("handover").className = "handover";
    $("blackholeWorkshopSlot").className = "blackholeWorkshopSlot";
    $("blackholeWorkshopSlot").innerHTML = "";
    const pathText = Object.entries(report.paths || {}).map(([key, value]) => `${key}: ${value}`).join("\n");
    $("messages").innerHTML = `
      <div class="doctorPage">
        <div class="doctorHero">
          <h2>Setup Doctor / 配置自检</h2>
          <p>这里用于第一次安装、迁移到新电脑、升级后检查环境。默认只读；点击修复按钮只会创建缺失目录并记录当前版本，不会改 OpenClaw agent、模型或密钥配置。</p>
          <div class="doctorActions">
            <button id="refreshSetupDoctor" type="button">重新检查</button>
            <button id="fixSetupDoctor" class="secondary" type="button">创建缺失目录并记录当前版本</button>
          </div>
        </div>
        ${(report.sections || []).map(section => `
          <div class="doctorSection">
            <div class="doctorSectionHeader">
              <div class="doctorSectionTitle">${esc(section.title)}</div>
              <span class="doctorPill ${esc(section.level)}">${esc(doctorLevelText(section.level))}</span>
            </div>
            ${(section.items || []).map(item => `
              <div class="doctorItem">
                <span class="doctorMark ${esc(item.level)}">${esc(doctorMark(item.level))}</span>
                <div>
                  <div class="doctorItemTitle">${esc(item.title)}</div>
                  ${item.detail ? `<div class="doctorDetail">${esc(item.detail)}</div>` : ""}
                  ${item.action ? `<div class="doctorAction">${esc(item.action)}</div>` : ""}
                </div>
              </div>
            `).join("")}
          </div>
        `).join("")}
        <div class="doctorPaths">${esc(pathText)}</div>
      </div>`;
  }

  async function showSetupDoctor() {
    const report = await fetch("/api/setup-doctor").then(r => r.json());
    renderSetupDoctor(report);
  }

  async function fixSetupDoctor() {
    if (!confirm("创建缺失目录并记录当前版本？\n\n这个操作不会改 OpenClaw agent、模型或密钥配置。")) return;
    const result = await fetch("/api/setup-doctor/fix", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }).then(r => r.json());
    if (!result.ok) return alert(result.error || "修复失败");
    renderSetupDoctor(result.report);
    setSyncStatus(`配置自检：已创建 ${result.created.length} 个目录，并记录当前版本。`);
    await loadHealth();
  }

  function renderUpgradeGuard(report) {
    $("sessionTitle").textContent = "升级护航";
    $("sessionMeta").textContent = `Upgrade Guard · Studio ${report.version || "-"} · ${report.latestBackup ? "已有升级前备份" : "尚未备份"}`;
    setSyncStatus("升级护航：升级前冻结现场，升级后对照插件、频道、agent 和日志状态。");
    $("handover").className = "handover";
    $("blackholeWorkshopSlot").className = "blackholeWorkshopSlot";
    $("blackholeWorkshopSlot").innerHTML = "";
    const previewText = JSON.stringify(report.configPreview || {}, null, 2);
    $("messages").innerHTML = `
      <div class="doctorPage">
        <div class="doctorHero">
          <h2>Upgrade Guard / 升级护航</h2>
          <p>这里用于升级 OpenClaw 前后做对照。检查默认只读；“创建升级前备份”只把关键文件复制到本机私有备份目录，不修改 OpenClaw 配置、插件、agent 或会话。</p>
          <div class="doctorActions">
            <button id="refreshUpgradeGuard" type="button">重新检查</button>
            <button id="createUpgradeBackup" class="secondary" type="button">创建升级前备份</button>
            ${report.latestBackup ? `<button class="secondary" data-open-path="${esc(report.latestBackup)}" type="button">打开最近备份</button>` : ""}
          </div>
        </div>
        ${(report.sections || []).map(section => `
          <div class="doctorSection">
            <div class="doctorSectionHeader">
              <div class="doctorSectionTitle">${esc(section.title)}</div>
              <span class="doctorPill ${esc(section.level)}">${esc(doctorLevelText(section.level))}</span>
            </div>
            ${(section.items || []).map(item => `
              <div class="doctorItem">
                <span class="doctorMark ${esc(item.level)}">${esc(doctorMark(item.level))}</span>
                <div>
                  <div class="doctorItemTitle">${esc(item.title)}</div>
                  ${item.detail ? `<div class="doctorDetail">${esc(item.detail)}</div>` : ""}
                  ${item.action ? `<div class="doctorAction">${esc(item.action)}</div>` : ""}
                </div>
              </div>
            `).join("")}
          </div>
        `).join("")}
        <div class="doctorSection">
          <div class="doctorSectionHeader">
            <div class="doctorSectionTitle">已脱敏配置预览</div>
            <span class="doctorPill ok">只读</span>
          </div>
          <div class="doctorPaths">${esc(previewText)}</div>
        </div>
        <div class="doctorPaths">backupDir: ${esc(report.backupDir || "")}\nopenclawHome: ${esc(report.openclawHome || "")}</div>
      </div>`;
  }

  async function showUpgradeGuard() {
    const report = await fetch("/api/upgrade-guard").then(r => r.json());
    renderUpgradeGuard(report);
  }

  async function createUpgradeBackup() {
    if (!confirm("创建升级前备份？\n\n会复制 OpenClaw 主配置、agents、extensions 和 LaunchAgent plist 到本机私有备份目录。备份可能包含认证资料和会话索引，请勿提交或分享。")) return;
    const result = await fetch("/api/upgrade-guard/backup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }).then(r => r.json());
    if (!result.ok) return alert(result.error || "创建备份失败");
    renderUpgradeGuard(result.report);
    setSyncStatus(`升级护航：已创建备份 ${result.backupPath}`);
  }

  async function restoreArchive(kind, archiveId) {
    const path = kind === "blackhole" ? "/api/blackhole/restore" : "/api/session/restore";
    const result = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ archiveId }),
    }).then(r => r.json());
    if (!result.ok) return alert(result.error || "恢复失败");
    if (viewMode === "blackhole") await loadBlackholeTasks({ silent: true });
    else await loadSessions({ silent: true });
    await showArchiveList();
  }

  async function deleteArchive(kind, archiveId) {
    const typed = prompt("永久删除不可恢复。\n如果确认，请输入：永久删除");
    if (typed !== "永久删除") return;
    const path = kind === "blackhole" ? "/api/blackhole/delete-archived" : "/api/session/delete-archived";
    const result = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ archiveId, confirm: typed }),
    }).then(r => r.json());
    if (!result.ok) return alert(result.error || "永久删除失败");
    await showArchiveList();
  }

  async function loadSessions({ silent = false } = {}) {
    if (viewMode === "blackhole") {
      await loadBlackholeTasks({ silent });
      return;
    }
    if (isLoadingSessions) return;
    isLoadingSessions = true;
    const currentKey = current ? current.key : "";
    try {
      const storedSessions = await fetch("/api/sessions").then(r => r.json());
      const storedKeys = new Set(storedSessions.map(s => s.key));
      draftSessions = draftSessions.filter(s => !storedKeys.has(s.key));
      sessions = draftSessions.concat(storedSessions);
      if (currentKey) {
        const refreshedCurrent = sessions.find(s => s.key === currentKey);
        if (refreshedCurrent) current = refreshedCurrent;
      }
    } finally {
      isLoadingSessions = false;
    }
    $("sessions").innerHTML = sessions.map((s, i) => `
      <div class="session ${current && current.key === s.key ? "active" : ""}" data-i="${i}" title="${esc(s.label)}${s.preview ? " · " + esc(s.preview) : ""}">
        <div class="${esc(sessionIconClass(s))}">${esc(sessionIcon(s))}</div>
        <div class="sessionTop">
          <div class="title">${esc(s.label)}</div>
          ${s.isDraft ? "" : `<button class="small" data-open="${i}">TUI</button>`}
        </div>
        <div class="meta">
          ${s.isPhoneMain ? '<span class="badge green">手机私聊主会话</span>' : ''}
          ${s.isGroup ? '<span class="badge orange">群聊</span>' : ''}
          ${s.isDraft ? '<span class="badge">新会话草稿</span>' : ''}
          <span class="badge">${esc(s.agentId)}</span><span class="badge">${esc(s.chatType)}</span>
          ${s.preview ? `<div class="preview" title="${esc(s.preview)}">${esc(s.preview)}</div>` : ""}
          <div class="metaLine">${esc(s.model || "-")} ${s.harness ? " / " + esc(s.harness) : ""}</div>
          <div class="metaLine"><span class="token ${esc(s.tokenLevel)}">上下文 ${esc(s.tokenPercent)}% · ${esc(s.totalTokens)}/${esc(s.contextTokens || "?")}</span></div>
          <div class="metaLine">${esc(s.updatedText)}</div>
        </div>
      </div>`).join("") || '<div class="empty">暂无 session</div>';
    updateDeliverStatus();
    if (!silent && pushConnected) setSyncStatus("事件推送：已连接；会话变化会自动更新，低频兜底每 60 秒。");
  }

  async function loadHealth() {
    const health = await fetch("/api/health").then(r => r.json());
    const visibleChecks = health.checks.filter(c => c.level !== "ok");
    const box = $("health");
    box.className = `health ${health.level}`;
    if (!visibleChecks.length) {
      box.innerHTML = "";
      return;
    }
    const title = health.level === "error" ? "环境缺少必要配置" : "环境提示";
    box.innerHTML = `
      <div class="healthTitle">${esc(title)}</div>
      ${visibleChecks.map(c => `
        <div class="healthItem">
          <span class="healthLevel ${esc(c.level)}">${esc(c.level.toUpperCase())}</span>
          <strong>${esc(c.title)}</strong><br>
          ${esc(c.detail || "")}
          ${c.action ? `<br><span class="sub">${esc(c.action)}</span>` : ""}
        </div>
      `).join("")}
    `;
  }

  async function loadAutoStatus() {
    const status = await fetch("/api/auto-handover").then(r => r.json());
    const active = status.sessions.filter(s => s.shouldAutoHandover);
    if (!active.length) {
      $("autoStatus").textContent = `自动接力已开启：超过 ${status.thresholdPercent}% 会自动更新 Obsidian 摘要。当前没有接近上限的会话。`;
      return;
    }
    const first = active[0];
    $("autoStatus").innerHTML = `自动接力已开启：${active.length} 个会话超过 ${status.thresholdPercent}%。
      最近：${esc(first.label)} · ${esc(first.tokenPercent)}% · ${first.lastPath ? "已生成 " + esc(first.lastAutoText) : "等待生成"}`;
  }

  async function loadMessages({ force = false, silent = false, reason = "" } = {}) {
    if (!current) return;
    if (current.isDraft) {
      $("sessionTitle").textContent = current.label;
      $("sessionMeta").textContent = `${current.key} | ${current.model || "-"} | sessionId=${current.sessionId}`;
      currentMessages = [];
      lastMessagesSignature = "";
      renderMessages({ forceBottom: true });
      if (!silent) setSyncStatus("新会话草稿：发送第一条消息后创建到 OpenClaw。");
      return;
    }
    if (isLoadingMessages) return;
    isLoadingMessages = true;
    $("sessionTitle").textContent = current.label;
    $("sessionMeta").textContent = `${current.key} | ${current.model || "-"} | sessionId=${current.sessionId}`;
    if (!silent) setSyncStatus(reason || "事件推送：正在读取最新消息...");
    try {
      const messages = await fetch(`/api/messages?key=${encodeURIComponent(current.key)}`).then(r => r.json());
      const signature = JSON.stringify(messages.map(m => [m.role, m.model || "", m.text]));
      if (force || signature !== lastMessagesSignature) {
        currentMessages = messages;
        renderMessages({ forceBottom: force });
        lastMessagesSignature = signature;
      }
      if (!silent) setSyncStatus(pushConnected ? "事件推送：已连接；新消息会自动出现，低频兜底每 60 秒。" : "事件推送：未连接，已启用 60 秒兜底刷新。");
    } catch (error) {
      setSyncStatus("事件推送：读取失败，稍后会重试");
    } finally {
      isLoadingMessages = false;
    }
  }

  function startEventStream() {
    if (!window.EventSource) {
      setSyncStatus("事件推送：当前浏览器不支持，已启用 60 秒兜底刷新。");
      return;
    }
    eventSource = new EventSource("/api/events");
    eventSource.addEventListener("open", () => {
      pushConnected = true;
      setSyncStatus("事件推送：已连接；新消息会自动出现，低频兜底每 60 秒。");
    });
    eventSource.addEventListener("status", (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.message) setSyncStatus(data.message);
      } catch (_) {}
    });
    eventSource.addEventListener("sessions", async () => {
      await loadSessions({ silent: true });
    });
    eventSource.addEventListener("blackhole", async () => {
      if (viewMode === "blackhole") await loadBlackholeTasks({ silent: true });
    });
    eventSource.addEventListener("messages", async (event) => {
      let keys = [];
      try {
        keys = (JSON.parse(event.data).keys || []);
      } catch (_) {}
      await loadSessions({ silent: true });
      if (current && (!keys.length || keys.includes(current.key))) {
        await loadMessages({ silent: true });
      }
    });
    eventSource.onerror = () => {
      pushConnected = false;
      setSyncStatus("事件推送：连接中断，浏览器会自动重连；同时保留 60 秒兜底刷新。");
    };
  }

  function appendLocalMessage(role, text, detail = "") {
    const div = document.createElement("div");
    const compact = text.length <= 120 && !text.includes("\n");
    div.className = `msg ${role === "user" ? "user" : role === "system" ? "system" : ""} ${compact ? "compact" : ""} pending`;
    div.innerHTML = `<div class="role">${esc(role)}${detail ? " · " + esc(detail) : ""}</div><div class="messageText">${esc(text)}</div>`;
    $("messages").appendChild(div);
    $("messages").scrollTop = $("messages").scrollHeight;
    return div;
  }

  $("sessions").onclick = async (event) => {
    if (viewMode === "blackhole") {
      const item = event.target.closest("[data-task]");
      if (!item) return;
      const task = blackholeTasks[Number(item.dataset.task)];
      if (!task) return;
      currentTask = await fetch(`/api/blackhole/task?id=${encodeURIComponent(task.id)}`).then(r => r.json());
      renderBlackholeList();
      renderBlackholeTask();
      return;
    }
    const openBtn = event.target.closest("[data-open]");
    if (openBtn) {
      event.stopPropagation();
      const session = sessions[Number(openBtn.dataset.open)];
      await openTui(session);
      return;
    }
    const item = event.target.closest(".session");
    if (!item) return;
    saveCurrentDraft();
    saveCurrentAttachments();
    current = sessions[Number(item.dataset.i)];
    restoreDraft(current);
    restoreAttachments(current);
    updateDeliverStatus();
    lastMessagesSignature = "";
    searchIndex = -1;
    $("newMessageBtn").classList.remove("show");
    await loadSessions();
    await loadMessages({ force: true, reason: "事件推送：正在打开会话..." });
  };

  $("reloadMessages").onclick = () => loadMessages({ force: true, reason: "事件推送：正在手动重载..." });
  $("jumpTop").onclick = () => { $("messages").scrollTop = 0; };
  $("jumpBottom").onclick = () => {
    scrollMessagesToBottom();
    $("newMessageBtn").classList.remove("show");
  };
  $("newMessageBtn").onclick = $("jumpBottom").onclick;
  $("sessionsMode").onclick = () => setMode("sessions");
  $("blackholeMode").onclick = () => setMode("blackhole");
  $("newBlackhole").onclick = () => {
    setMode("blackhole");
    currentTask = null;
    renderBlackholeTask();
    $("message").focus();
  };
  $("searchBox").oninput = () => {
    searchIndex = -1;
    renderMessages();
    if ($("searchBox").value.trim()) jumpSearch(1);
  };
  $("searchPrev").onclick = () => jumpSearch(-1);
  $("searchNext").onclick = () => jumpSearch(1);
  $("message").addEventListener("input", saveCurrentDraft);
  $("resizeComposer").addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const textarea = $("message");
    const startY = event.clientY;
    const startHeight = textarea.offsetHeight;
    $("resizeComposer").setPointerCapture(event.pointerId);
    const onMove = (moveEvent) => {
      const next = Math.max(58, Math.min(220, startHeight - (moveEvent.clientY - startY)));
      textarea.style.height = `${next}px`;
    };
    const onUp = () => {
      $("resizeComposer").removeEventListener("pointermove", onMove);
      $("resizeComposer").removeEventListener("pointerup", onUp);
      $("resizeComposer").removeEventListener("pointercancel", onUp);
    };
    $("resizeComposer").addEventListener("pointermove", onMove);
    $("resizeComposer").addEventListener("pointerup", onUp);
    $("resizeComposer").addEventListener("pointercancel", onUp);
  });
  $("message").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("sendForm").requestSubmit();
    }
  });
  $("attachBtn").onclick = () => $("attachmentInput").click();
  $("newSessionBtn").onclick = createDraftSession;
  $("attachmentInput").onchange = async (event) => {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    if (!files.length) return;
    $("attachBtn").disabled = true;
    $("attachBtn").textContent = "...";
    const formData = new FormData();
    files.forEach(file => formData.append("files", file));
    try {
      const result = await fetch("/api/upload", { method: "POST", body: formData }).then(r => r.json());
      if (!result.ok) return alert(result.error || "附件上传失败");
      attachments = attachments.concat(result.files || []);
      saveCurrentAttachments();
      renderAttachments();
    } catch (error) {
      alert("附件上传失败：" + error);
    } finally {
      $("attachBtn").disabled = false;
      $("attachBtn").textContent = "📎";
    }
  };
  $("attachmentList").onclick = (event) => {
    const remove = event.target.closest("[data-remove-attachment]");
    if (!remove) return;
    attachments.splice(Number(remove.dataset.removeAttachment), 1);
    saveCurrentAttachments();
    renderAttachments();
  };
  $("messages").addEventListener("change", (event) => {
    const input = event.target.closest("[data-blackhole-agent]");
    if (!input) return;
    if (input.checked) {
      blackholeSelectedAgents.add(input.dataset.blackholeAgent);
    } else {
      blackholeSelectedAgents.delete(input.dataset.blackholeAgent);
    }
  });
  document.addEventListener("pointerdown", (event) => {
    const menu = $("toolsMenu");
    if (menu.open && !event.target.closest("#toolsMenu")) {
      menu.open = false;
    }
  });
  $("messages").onclick = async (event) => {
    if (event.target.closest("#refreshSetupDoctor")) {
      await showSetupDoctor();
      return;
    }
    if (event.target.closest("#fixSetupDoctor")) {
      await fixSetupDoctor();
      return;
    }
    if (event.target.closest("#refreshUpgradeGuard")) {
      await showUpgradeGuard();
      return;
    }
    if (event.target.closest("#createUpgradeBackup")) {
      await createUpgradeBackup();
      return;
    }
    const openPathButton = event.target.closest("[data-open-path]");
    if (openPathButton) {
      const result = await fetch("/api/open-path", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: openPathButton.dataset.openPath }),
      }).then(r => r.json());
      if (!result.ok) alert(result.error || "打开失败");
      return;
    }
    const restore = event.target.closest("[data-archive-restore]");
    if (restore) {
      await restoreArchive(restore.dataset.archiveKind, restore.dataset.archiveRestore);
      return;
    }
    const remove = event.target.closest("[data-archive-delete]");
    if (remove) {
      await deleteArchive(remove.dataset.archiveKind, remove.dataset.archiveDelete);
      return;
    }
    const orderButton = event.target.closest("[data-agent-order]");
    if (orderButton) {
      moveBlackholeAgent(orderButton.dataset.agentId, orderButton.dataset.agentOrder);
      return;
    }
    const doneButton = event.target.closest("[data-agent-done]");
    if (doneButton) {
      await setCurrentBlackholeAgentStatus(doneButton.dataset.agentDone, "done");
      return;
    }
    const skipButton = event.target.closest("[data-agent-skip]");
    if (skipButton) {
      await setCurrentBlackholeAgentStatus(skipButton.dataset.agentSkip, "skipped");
      return;
    }
    const tui = event.target.closest("[data-task-tui]");
    if (!tui) return;
    const result = await fetch("/api/open-tui-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: tui.dataset.taskTui }),
    }).then(r => r.json());
    if (!result.ok) alert(result.error || "打开 TUI 失败");
  };
  $("collapseSidebar").onclick = () => {
    const collapsed = !$("layout").classList.contains("sidebarCollapsed");
    $("layout").classList.toggle("sidebarCollapsed", collapsed);
    localStorage.setItem(sidebarKey, collapsed ? "1" : "0");
    $("collapseSidebar").title = collapsed ? "展开侧边栏" : "收起侧边栏";
  };
  $("openTui").onclick = async () => {
    if (!current) return alert("先选一个 session");
    if (current.isDraft) return alert("新会话草稿还没有创建到 OpenClaw。先发送第一条消息后再打开 TUI。");
    await openTui(current);
  };
  $("makeHandover").onclick = async () => {
    if (!current) return alert("先选一个 session");
    if (current.isDraft) return alert("新会话草稿还没有历史记录，先发送第一条消息后再生成摘要。");
    $("makeHandover").disabled = true;
    $("makeHandover").textContent = "生成中";
    const result = await fetch("/api/handover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: current.key }),
    }).then(r => r.json());
    $("makeHandover").disabled = false;
    $("makeHandover").textContent = "生成接力摘要";
    if (!result.ok) return alert(result.error || "生成失败");
    lastHandover = result;
    $("handover").className = "handover show";
    $("handover").innerHTML = `
      已生成：<code>${esc(result.path)}</code>
      <div style="display:flex; gap:8px; margin-top:8px; flex-wrap:wrap;">
        <button class="small" id="copyHandoverPrompt">复制接力提示</button>
        <button class="small" id="openHandoverFile">打开摘要文件</button>
      </div>
    `;
  };
  $("openHandoverDir").onclick = async () => {
    const result = await fetch("/api/open-handover-dir", { method: "POST" }).then(r => r.json());
    if (!result.ok) alert(result.error || "打开失败");
  };
  $("archiveCurrentSession").onclick = archiveCurrentSession;
  $("archiveCurrentTask").onclick = archiveCurrentBlackholeTask;
  $("cancelBlackhole").onclick = cancelCurrentBlackholeTask;
  $("showArchiveList").onclick = showArchiveList;
  $("showSetupDoctor").onclick = showSetupDoctor;
  $("showUpgradeGuard").onclick = showUpgradeGuard;
  $("runBlackhole").onclick = async () => {
    if (!currentTask) return alert("先创建或选择一个黑洞协作任务");
    const result = await fetch("/api/blackhole/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: currentTask.id }),
    }).then(r => r.json());
    if (!result.ok) return alert(result.error || "启动失败");
    currentTask = result.task;
    renderBlackholeTask();
  };
  $("openBlackholeFile").onclick = async () => {
    if (!currentTask || !currentTask.path) return alert("当前黑洞任务还没有任务文件");
    const result = await fetch("/api/open-path", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: currentTask.path }),
    }).then(r => r.json());
    if (!result.ok) alert(result.error || "打开失败");
  };
  $("handover").onclick = async (event) => {
    if (!lastHandover) return;
    if (event.target.id === "copyHandoverPrompt") {
      await navigator.clipboard.writeText(lastHandover.prompt);
      event.target.textContent = "已复制";
    }
    if (event.target.id === "openHandoverFile") {
      const result = await fetch("/api/open-path", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: lastHandover.path }),
      }).then(r => r.json());
      if (!result.ok) alert(result.error || "打开失败");
    }
  };

  $("authLogin").onclick = loginWithToken;
  $("authToken").addEventListener("keydown", (event) => {
    if (event.key === "Enter") loginWithToken();
  });

  async function openTui(session) {
    const result = await fetch("/api/open-tui", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: session.key }),
    }).then(r => r.json());
    if (!result.ok) alert(result.error || "打开 TUI 失败");
  }

  $("sendForm").onsubmit = async (event) => {
    event.preventDefault();
    if (viewMode === "blackhole") {
      const message = $("message").value.trim();
      if (!message) return alert("先输入要协作处理的问题");
      await createAndRunBlackholeTask(message);
      return;
    }
    if (!current) return alert("先选一个 session");
    const message = $("message").value.trim();
    if (!message && !attachments.length) return;
    const sendingSessionKey = current.key;
    const deliver = shouldAutoDeliver(current);
    const deliverName = channelName(current.channel);
    const wasDraft = !!current.isDraft;
    const sendingAttachments = attachments.slice();
    const outgoingMessage = messageWithAttachments(message || "请查看附件。", sendingAttachments);
    const userNode = appendLocalMessage("user", outgoingMessage, deliver ? `已提交，准备同步到${deliverName}` : "已提交");
    const statusNode = appendLocalMessage("system", deliver ? `正在同步到${deliverName}，并等待 OpenClaw 回复...` : "正在等待 OpenClaw 回复...");
    clearCurrentDraft();
    clearCurrentAttachments();
    $("sendBtn").disabled = true;
    $("sendBtn").textContent = "...";
    const body = {
      key: current.key,
      message: outgoingMessage,
      attachments: sendingAttachments,
      deliver,
      mirrorUserMessage: deliver,
    };
    const result = await fetch("/api/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(r => r.json());
    $("sendBtn").disabled = false;
    $("sendBtn").textContent = "↗";
    if (!result.ok) {
      statusNode.innerHTML = `<div class="role">system · 发送失败</div><div class="messageText">${esc(result.error || result.raw || "发送失败")}</div>`;
      localStorage.setItem(draftKey(sendingSessionKey), message);
      if (current && current.key === sendingSessionKey) $("message").value = message;
      attachmentDrafts.set(sendingSessionKey, sendingAttachments);
      if (current && current.key === sendingSessionKey) restoreAttachments(current);
      lastMessagesSignature = "";
      return;
    }
    if (wasDraft) {
      draftSessions = draftSessions.filter(s => s.key !== sendingSessionKey);
    }
    if (result.mirror && !result.mirror.ok) {
      statusNode.innerHTML = `<div class="role">system · 已回复，但频道同步原文失败</div><div class="messageText">${esc(result.mirror.error || result.mirror.raw || "频道同步失败")}</div>`;
    } else {
      statusNode.innerHTML = `<div class="role">system · 已完成</div><div class="messageText">${deliver ? `已同步桌面端原文到${deliverName}，并收到 OpenClaw 回复。` : "已收到 OpenClaw 回复。"}</div>`;
    }
    userNode.classList.remove("pending");
    await loadSessions();
    lastMessagesSignature = "";
    await loadMessages({ force: true, reason: "事件推送：正在读取发送后的最新记录..." });
  };

  async function startApp() {
    if (appStarted) return;
    const ok = await checkAuth();
    if (!ok) return;
    appStarted = true;
    if (localStorage.getItem(sidebarKey) === "1") {
      $("layout").classList.add("sidebarCollapsed");
      $("collapseSidebar").title = "展开侧边栏";
    }
    $("newBlackhole").style.display = "none";
    updateToolButtons();
    loadHealth();
    loadAutoStatus();
    loadSessions();
    startEventStream();
    setInterval(loadAutoStatus, 60000);
    setInterval(() => loadSessions({ silent: true }), fallbackPollMs);
    setInterval(() => {
      if (current) loadMessages({ silent: true });
    }, fallbackPollMs);
  }

  startApp();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        return

    def send_json(self, data, status=200, headers=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def read_body_json(self):
        length = int(self.headers.get("Content-Length") or "0")
        raw_body = self.rfile.read(length).decode("utf-8") if length else ""
        return json.loads(raw_body) if raw_body.strip() else {}

    def is_local_direct(self):
        host = (self.headers.get("Host") or "").lower()
        forwarded = (
            self.headers.get("CF-Connecting-IP")
            or self.headers.get("X-Forwarded-For")
            or self.headers.get("Forwarded")
        )
        local_hosts = (
            host.startswith("127.0.0.1"),
            host.startswith("localhost"),
            host.startswith("[::1]"),
            host.startswith("::1"),
        )
        return any(local_hosts) and not forwarded

    def is_authenticated(self):
        if self.is_local_direct():
            return True
        cookies = parse_cookies(self.headers.get("Cookie"))
        token = cookies.get(AUTH_COOKIE_NAME, "")
        return bool(token) and secrets.compare_digest(token, get_access_token())

    def auth_status(self):
        required = not self.is_local_direct()
        return {
            "ok": True,
            "required": required,
            "authenticated": self.is_authenticated(),
            "remote": required,
        }

    def require_auth(self):
        if self.is_authenticated():
            return True
        self.send_json({"ok": False, "error": "unauthorized"}, status=401)
        return False

    def send_event_stream(self):
        subscriber = EVENT_HUB.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def write_event(event_type, payload):
            body = f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            self.wfile.write(body.encode("utf-8"))
            self.wfile.flush()

        try:
            write_event("status", {
                "level": "ok",
                "message": "事件推送：已连接；新消息会自动出现，低频兜底每 60 秒。",
            })
            while True:
                try:
                    event = subscriber.get(timeout=20)
                    write_event(event["type"], event["payload"])
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            EVENT_HUB.unsubscribe(subscriber)

    def handle_upload(self):
        content_type = self.headers.get("Content-Type") or ""
        if "multipart/form-data" not in content_type:
            self.send_json({"ok": False, "error": "请使用 multipart/form-data 上传附件。"}, status=400)
            return
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": content_type,
                },
            )
            fields = form["files"] if "files" in form else []
            if not isinstance(fields, list):
                fields = [fields]
            files = []
            for field in fields:
                if not getattr(field, "filename", ""):
                    continue
                files.append(save_uploaded_file(field))
            if not files:
                self.send_json({"ok": False, "error": "没有收到可用附件。"}, status=400)
                return
            self.send_json({"ok": True, "files": files})
        except Exception as exc:
            self.send_json({"ok": False, "error": f"附件上传失败：{exc}"}, status=500)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/api/auth/status":
            self.send_json(self.auth_status())
        elif parsed.path == "/api/events":
            if not self.require_auth():
                return
            self.send_event_stream()
        elif parsed.path == "/api/sessions":
            if not self.require_auth():
                return
            self.send_json(list_sessions())
        elif parsed.path == "/api/health":
            if not self.require_auth():
                return
            self.send_json(app_health())
        elif parsed.path == "/api/setup-doctor":
            if not self.require_auth():
                return
            self.send_json(setup_doctor_report())
        elif parsed.path == "/api/upgrade-guard":
            if not self.require_auth():
                return
            self.send_json(upgrade_guard_report())
        elif parsed.path == "/api/auto-handover":
            if not self.require_auth():
                return
            self.send_json(auto_handover_status())
        elif parsed.path == "/api/blackhole/tasks":
            if not self.require_auth():
                return
            self.send_json(list_blackhole_tasks())
        elif parsed.path == "/api/blackhole/task":
            if not self.require_auth():
                return
            query = urllib.parse.parse_qs(parsed.query)
            task_id = (query.get("id") or [""])[0]
            task = get_blackhole_task(task_id, include_messages=True)
            if not task:
                self.send_json({"ok": False, "error": "task not found"}, status=404)
                return
            self.send_json(task)
        elif parsed.path == "/api/archive":
            if not self.require_auth():
                return
            self.send_json({
                "sessions": list_archived_sessions(),
                "blackholeTasks": list_archived_blackhole_tasks(),
            })
        elif parsed.path == "/api/messages":
            if not self.require_auth():
                return
            query = urllib.parse.parse_qs(parsed.query)
            key = (query.get("key") or [""])[0]
            session = session_from_key(key)
            if not session:
                self.send_json({"error": "session not found"}, status=404)
                return
            if session.get("isDraft"):
                self.send_json([])
                return
            self.send_json(read_messages(session["sessionFile"]))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/auth/login":
            try:
                data = self.read_body_json()
            except Exception:
                self.send_json({"ok": False, "error": "invalid json"}, status=400)
                return
            token = (data.get("token") or "").strip()
            if not token or not secrets.compare_digest(token, get_access_token()):
                self.send_json({"ok": False, "error": "访问码不正确。"}, status=401)
                return
            cookie = (
                f"{AUTH_COOKIE_NAME}={urllib.parse.quote(token)}; "
                "Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax"
            )
            self.send_json({"ok": True}, headers={"Set-Cookie": cookie})
            return
        if not self.require_auth():
            return
        if self.path == "/api/upload":
            self.handle_upload()
            return
        if self.path not in (
            "/api/send",
            "/api/open-tui",
            "/api/open-tui-key",
            "/api/handover",
            "/api/auto-handover-now",
            "/api/setup-doctor/fix",
            "/api/upgrade-guard/backup",
            "/api/open-handover-dir",
            "/api/open-path",
            "/api/session/archive",
            "/api/session/restore",
            "/api/session/delete-archived",
            "/api/blackhole/create",
            "/api/blackhole/run",
            "/api/blackhole/agent-status",
            "/api/blackhole/cancel",
            "/api/blackhole/archive",
            "/api/blackhole/restore",
            "/api/blackhole/delete-archived",
        ):
            self.send_response(404)
            self.end_headers()
            return
        try:
            data = self.read_body_json()
        except Exception:
            self.send_json({"ok": False, "error": "invalid json"}, status=400)
            return
        key = data.get("key") or ""
        message = data.get("message") or ""
        attachments = data.get("attachments") or []
        deliver = bool(data.get("deliver"))
        mirror_user_message = bool(data.get("mirrorUserMessage"))
        if self.path == "/api/open-handover-dir":
            self.send_json(open_path(HANDOVER_DIR))
            return
        if self.path == "/api/auto-handover-now":
            self.send_json(run_auto_handover_once())
            return
        if self.path == "/api/setup-doctor/fix":
            self.send_json(setup_doctor_fix())
            return
        if self.path == "/api/upgrade-guard/backup":
            self.send_json(create_upgrade_backup())
            return
        if self.path == "/api/open-path":
            target = Path(data.get("path") or "")
            if not target.exists():
                self.send_json({"ok": False, "error": "path not found"}, status=404)
                return
            self.send_json(open_path(target))
            return
        if self.path == "/api/session/archive":
            self.send_json(archive_session(data.get("key") or ""))
            return
        if self.path == "/api/session/restore":
            self.send_json(restore_archived_session(data.get("archiveId") or ""))
            return
        if self.path == "/api/session/delete-archived":
            self.send_json(delete_archived_session(data.get("archiveId") or "", data.get("confirm") or ""))
            return
        if self.path == "/api/blackhole/create":
            prompt = data.get("prompt") or data.get("message") or ""
            if not prompt.strip():
                self.send_json({"ok": False, "error": "empty blackhole task"}, status=400)
                return
            task = create_blackhole_task(data.get("title") or "", prompt.strip(), data.get("agents") or [])
            self.send_json({"ok": True, "task": task})
            return
        if self.path == "/api/blackhole/run":
            task_id = data.get("id") or ""
            self.send_json(start_blackhole_task(task_id))
            return
        if self.path == "/api/blackhole/agent-status":
            self.send_json(set_blackhole_agent_status(data.get("id") or "", data.get("agentId") or "", data.get("status") or "", data.get("note") or ""))
            return
        if self.path == "/api/blackhole/cancel":
            self.send_json(cancel_blackhole_task(data.get("id") or ""))
            return
        if self.path == "/api/blackhole/archive":
            self.send_json(archive_blackhole_task(data.get("id") or ""))
            return
        if self.path == "/api/blackhole/restore":
            self.send_json(restore_archived_blackhole_task(data.get("archiveId") or ""))
            return
        if self.path == "/api/blackhole/delete-archived":
            self.send_json(delete_archived_blackhole_task(data.get("archiveId") or "", data.get("confirm") or ""))
            return
        if self.path == "/api/open-tui-key":
            direct_key = data.get("key") or ""
            if not direct_key:
                self.send_json({"ok": False, "error": "empty session key"}, status=400)
                return
            self.send_json(open_tui_in_terminal(direct_key))
            return
        session = session_from_key(key)
        if not session:
            self.send_json({"ok": False, "error": "session not found"}, status=404)
            return
        if self.path == "/api/open-tui":
            self.send_json(open_tui_in_terminal(session["key"]))
            return
        if self.path == "/api/handover":
            self.send_json(make_handover(session["key"]))
            return
        if not message.strip():
            self.send_json({"ok": False, "error": "empty message"}, status=400)
            return
        result = send_to_session(
            session,
            message,
            deliver=deliver,
            mirror_user_message=mirror_user_message,
            attachments=attachments,
        )
        if result.get("ok"):
            EVENT_HUB.publish("messages", {"keys": [session["key"]]})
            EVENT_HUB.publish("sessions", {})
        self.send_json(result)


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc_type, _, _ = sys.exc_info()
        if exc_type in (BrokenPipeError, ConnectionResetError):
            return
        super().handle_error(request, client_address)


if __name__ == "__main__":
    try:
        print(f"OpenClaw Agents Studio running at http://{HOST}:{PORT}")
        threading.Thread(target=auto_handover_loop, daemon=True).start()
        threading.Thread(target=event_watch_loop, daemon=True).start()
        QuietThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except OSError as exc:
        if exc.errno == 48:
            print(f"端口 {PORT} 已经被占用，通常表示 OpenClaw 智能体工作室已经在运行。")
            print(f"请直接打开：http://{HOST}:{PORT}")
        else:
            raise
