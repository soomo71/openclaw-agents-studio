# OpenClaw Agents Studio

一个面向 OpenClaw 的本地会话工作台：查看会话、继续发送消息、打开 TUI、整理接力摘要，并用“黑洞协作”把多个 agent 的独立会话聚合到同一个任务面板里。

这个项目来自一个真实的个人工作流，开源版会尽量保持“复制到任意 Mac 文件夹后双击可用”，同时避免把本机二进制、访问码、日志和个人状态文件放进仓库。

## 功能

- OpenClaw 会话列表：优先显示常用频道会话，支持实时更新和最近消息摘要。
- 会话详情：查看历史、发送消息、打开对应 TUI、生成 Obsidian 接力摘要。
- 移动端访问：可通过 Cloudflare Quick Tunnel 临时开放给手机浏览器访问，并使用 6 位访问码保护。
- 黑洞协作：为多个 agent 创建独立 session，聚合展示任务进度和回复。
- 像素工作室：用轻量状态层展示 agent 是否被调用、运行中、完成、跳过或发呆。
- 归档机制：默认归档会话和黑洞任务，永久删除需要二次确认。

## 运行环境

- macOS
- Python 3
- 已安装并配置好的 OpenClaw CLI
- 推荐可在终端执行：

```bash
openclaw --version
openclaw status
```

移动端远程访问还需要 `cloudflared`。双击启动脚本时如果缺少它，会自动下载到项目内的 `.tools/` 目录；该目录不会被提交到 Git。

## 快速开始

双击：

```text
启动 OpenClaw 会话工具.command
```

它会同时启动：

- 本机 Web 工具：`http://127.0.0.1:8766`
- 手机远程访问隧道：终端会显示远程域名和 6 位访问码

只想本机运行，也可以直接：

```bash
python3 openclaw_session_viewer.py
```

然后打开：

```text
http://127.0.0.1:8766
```

停止手机远程访问：

```text
停止 手机远程访问.command
```

查看当前远程访问地址和访问码：

```text
查看 手机远程访问.command
```

## 配置

默认配置适合单机使用。需要换目录、换端口或迁移用户时，可以通过环境变量覆盖：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `OPENCLAW_HOME` | `~/.openclaw` | OpenClaw 数据目录 |
| `OPENCLAW_SESSION_VIEWER_HOST` | `127.0.0.1` | 本机服务监听地址 |
| `OPENCLAW_SESSION_VIEWER_PORT` | `8766` | 本机服务端口 |
| `OPENCLAW_SESSION_VIEWER_OBSIDIAN_DIR` | `~/Documents/Obsidian Vault/OpenClaw` | 接力摘要和黑洞协作文件目录 |

示例：

```bash
export OPENCLAW_SESSION_VIEWER_PORT=8777
export OPENCLAW_SESSION_VIEWER_OBSIDIAN_DIR="$HOME/Documents/MyVault/OpenClaw"
python3 openclaw_session_viewer.py
```

## 黑洞协作

默认角色顺序：

1. CEO
2. 守护者
3. 研究员
4. 小助理
5. 档案师

底层 agent ID 不应随显示名称变化而变化。显示名称只是 UI 品牌层，真实路由仍依赖 OpenClaw agent 配置。

如果涉及 OpenAI 模型，建议优先使用订阅认证方式；如订阅模型不可用，应配置 DeepSeek 等备用模型，避免所有 agent 同时瘫痪。

## 配置自检

第一次启动或升级后，打开 `工具 -> 配置自检`。

配置自检会检查基础服务、OpenClaw CLI/Gateway、会话存储、多 agent 准备情况、Obsidian 接力目录和当前版本状态。安全修复按钮只会创建缺失的支持目录，并记录当前 Studio 版本；不会修改 agent、模型、认证配置、API key 或会话历史。

详细说明见：[docs/SETUP_DOCTOR.md](docs/SETUP_DOCTOR.md)

## 安全提醒

- 本工具会读取本机 OpenClaw session、Obsidian 目录和附件缓存。
- 不要把访问码、日志、`.openclaw`、`.tools`、`.env` 提交到 Git。
- Cloudflare Quick Tunnel 适合临时手机访问，不保证长期稳定。
- 如果要长期公网使用，建议改为带账号的 Cloudflare Tunnel、反向代理或内网穿透，并加上更严格的认证。

## 项目结构

```text
.
├── openclaw_session_viewer.py
├── 启动 OpenClaw 会话工具.command
├── 启动 手机远程访问.command
├── 停止 手机远程访问.command
├── 查看 手机远程访问.command
├── DESIGN.md
├── README.md
├── LICENSE
├── SECURITY.md
└── docs/
    ├── OPEN_SOURCE_CHECKLIST.md
    └── SETUP_DOCTOR.md
```

## 开发

语法检查：

```bash
python3 -m py_compile openclaw_session_viewer.py
```

隐私检查建议：

```bash
rg -n "password|token|OPENCLAW_GATEWAY_TOKEN|trycloudflare|/Users/你的用户名" .
```

## 许可证

MIT License。详见 `LICENSE`。
