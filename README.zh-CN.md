# OpenClaw 智能体工作室

英文名：OpenClaw Agents Studio。

这是一个面向 OpenClaw 和 Codex 工作流的本地智能体工作室。它把桌面端、手机端、个人微信、企业微信、OpenClaw TUI、Codex agent、多 agent 协作和 Obsidian 接力记录放在同一个轻量工作台里。

这个项目来自一个真实的个人工作流，开源版会尽量保持“复制到任意 Mac 文件夹后双击可用”，同时避免把本机二进制、访问码、日志和个人状态文件放进仓库。

更完整的产品介绍见：[docs/PRODUCT_OVERVIEW.zh-CN.md](docs/PRODUCT_OVERVIEW.zh-CN.md)

## 它适合做什么

- 在电脑上继续处理从个人微信或企业微信发起的 OpenClaw 对话。
- 在一个界面里查看多个 agent 的 session、历史、模型和上下文占用。
- 直接打开对应 OpenClaw TUI，回到更原生的终端操作模式。
- 用手机远程访问电脑上的工作室，并自动把临时访问地址和访问码发回微信端。
- 把重要会话整理成 Obsidian 接力摘要，让上下文满了以后也能继续。
- 用“黑洞协作”让多个智能体从不同角度看同一个问题。

## 功能

- OpenClaw 会话列表：优先显示常用频道会话，支持实时更新、最近消息摘要、上下文占用提示。
- 频道协同：识别个人微信 `openclaw-weixin`、企业微信 `wecom` 等频道会话，桌面发送时可同步回对应频道端。
- Codex 工作流：支持 `codex-agent`、OpenAI 订阅模型、Codex runtime 会话，并保留 DeepSeek 等备用模型策略。
- 会话详情：查看历史、发送消息、挂附件、打开对应 TUI、生成 Obsidian 接力摘要。
- 移动端访问：可通过 Cloudflare Quick Tunnel 临时开放给手机浏览器访问，并使用 6 位访问码保护。
- 远程访问启动通知：隧道启动后自动把远程地址和访问码发送到最近的个人微信与企业微信直聊会话。
- 黑洞协作：为多个 agent 创建独立 session，聚合展示任务进度和回复；已创建的黑洞可以继续追加指令。
- 多视角智能体：默认包含 Codex、CEO、守护者、研究员、小助理、档案师等角色，适合从总协调、执行、审查、研究、生活安排、档案整理等角度协同看问题。
- 像素工作室：用很小的像素卡通工位展示 agent 是否被调用、运行中、完成、跳过或发呆；它只是状态层，不替代文字记录和操作按钮。
- 归档机制：默认归档会话和黑洞任务，永久删除需要二次确认。
- 升级护航：升级 OpenClaw 前做状态检查，并创建本机私有备份用于对照或回滚。

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
启动 OpenClaw 智能体工作室.command
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

## 获取更新

如果是从 GitHub clone 的版本，后续更新可以双击：

```text
更新 OpenClaw 智能体工作室.command
```

它会检查本地是否有未提交改动；如果目录是干净的，会从 GitHub 快进更新并重启本机后台服务。为避免误覆盖，本地有改动时会停止并提示先备份或提交。

## 配置

默认配置适合单机使用。需要换目录、换端口或迁移用户时，可以通过环境变量覆盖：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `OPENCLAW_HOME` | `~/.openclaw` | OpenClaw 数据目录 |
| `OPENCLAW_SESSION_VIEWER_HOST` | `127.0.0.1` | 本机服务监听地址 |
| `OPENCLAW_SESSION_VIEWER_PORT` | `8766` | 本机服务端口 |
| `OPENCLAW_SESSION_VIEWER_OBSIDIAN_DIR` | `~/Documents/Obsidian Vault/OpenClaw` | 接力摘要和黑洞协作文件目录 |
| `OPENCLAW_REMOTE_NOTIFY` | `1` | 隧道启动后自动通知最近的频道会话；设为 `0` 可关闭 |

示例：

```bash
export OPENCLAW_SESSION_VIEWER_PORT=8777
export OPENCLAW_SESSION_VIEWER_OBSIDIAN_DIR="$HOME/Documents/MyVault/OpenClaw"
python3 openclaw_session_viewer.py
```

## 黑洞协作

默认角色顺序：

1. Codex
2. CEO
3. 守护者
4. 研究员
5. 小助理
6. 档案师

底层 agent ID 不应随显示名称变化而变化。显示名称只是 UI 品牌层，真实路由仍依赖 OpenClaw agent 配置。

如果涉及 OpenAI 模型，建议优先使用订阅认证方式；如订阅模型不可用，应配置 DeepSeek 等备用模型，避免所有 agent 同时瘫痪。

黑洞任务创建后，底部输入框会变成“向当前黑洞追加指令”。可以直接追加给当前参与 agent，也可以用 `@` 点名：

```text
@守护者 @研究员 重新检查风险和资料来源
@Codex 整合所有人的意见并收口
@CEO 收口，给我一个最终建议
@all 每个人用一句话补充
```

追加指令会写入任务文件，并保留每个 agent 的历史轮次，避免覆盖前一轮回复。

在黑洞输入框里输入 `@` 会弹出 agent 候选菜单；可以继续输入筛选，按 `↑/↓` 选择，按 `Enter` 或 `Tab` 补全。

## 配置自检

第一次启动或升级后，打开 `工具 -> 配置自检`。

配置自检会检查基础服务、OpenClaw CLI/Gateway、会话存储、多 agent 准备情况、Obsidian 接力目录和当前版本状态。安全修复按钮只会创建缺失的支持目录，并记录当前 Studio 版本；不会修改 agent、模型、认证配置、API key 或会话历史。

详细说明见：[docs/SETUP_DOCTOR.md](docs/SETUP_DOCTOR.md)

## 升级护航

升级 OpenClaw 前，打开 `工具 -> 升级护航`。

升级护航会只读检查当前 OpenClaw CLI、Gateway、插件、频道风险、模型兜底风险和最近日志信号。点击“创建升级前备份”会把关键 OpenClaw 文件复制到 `~/.openclaw/session-viewer-state/upgrade-backups/`，便于升级后人工对照或回滚。备份可能包含认证资料和会话索引，不要提交到 Git，也不要公开分享。

详细说明见：[docs/UPGRADE_GUARD.md](docs/UPGRADE_GUARD.md)

## 安全提醒

- 本工具会读取本机 OpenClaw session、Obsidian 目录和附件缓存。
- 不要把访问码、日志、`.openclaw`、`.tools`、`.env` 提交到 Git。
- Cloudflare Quick Tunnel 适合临时手机访问，不保证长期稳定。
- 如果要长期公网使用，建议改为带账号的 Cloudflare Tunnel、反向代理或内网穿透，并加上更严格的认证。

## 项目结构

```text
.
├── openclaw_session_viewer.py
├── 启动 OpenClaw 智能体工作室.command
├── 更新 OpenClaw 智能体工作室.command
├── 启动 手机远程访问.command
├── 停止 手机远程访问.command
├── 查看 手机远程访问.command
├── DESIGN.md
├── README.md
├── LICENSE
├── SECURITY.md
└── docs/
    ├── OPEN_SOURCE_CHECKLIST.md
    ├── PRODUCT_OVERVIEW.zh-CN.md
    ├── SETUP_DOCTOR.md
    └── UPGRADE_GUARD.md
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
