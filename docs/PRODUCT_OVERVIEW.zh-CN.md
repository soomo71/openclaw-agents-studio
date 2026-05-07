# OpenClaw 智能体工作室介绍

OpenClaw 智能体工作室（OpenClaw Agents Studio）是一个本地优先的 OpenClaw / Codex 工作台。它不是单纯的会话查看器，而是把桌面、手机、个人微信、企业微信、OpenClaw TUI、Codex agent、多智能体协作和 Obsidian 接力记录连接起来的轻量控制台。

## 核心场景

- 从个人微信发起问题，回到电脑上继续同一条 `codex-agent` 会话。
- 从企业微信进入 `life-agent`，把生活助理、工作提醒、日程类问题集中处理。
- 在浏览器里查看 OpenClaw session 历史、模型、上下文占用和最近消息。
- 一键打开对应的 OpenClaw TUI，回到终端继续处理。
- 手机远程访问电脑上的本地工作室，启动后自动收到远程地址和访问码。
- 把长会话整理成 Obsidian 接力摘要，方便上下文满了以后继续。
- 用“黑洞协作”让多个智能体从不同角度处理同一个问题。

## 多智能体协作

黑洞协作模式会为每个参与 agent 使用独立 session，并在一个任务面板里聚合展示。默认角色包括：

- CEO：偏执行、决策、拆解任务。
- 守护者：偏审查、风险、边界、可靠性。
- 研究员：偏资料、背景、方案比较。
- 小助理：偏生活工作安排、提醒、日常执行。
- 档案师：偏记录、摘要、归档、接力。

这些名称是 UI 展示层，底层仍使用稳定的 OpenClaw agent ID，例如 `codex-agent`、`life-agent`、`memory-agent` 等，避免改名影响路由和历史。

黑洞任务不是一次性对话。任务创建后，可以在当前任务里继续追加指令；不带 `@` 时默认发给当前参与 agent，带 `@守护者`、`@研究员`、`@CEO`、`@all` 时只调度对应 agent。追加指令会写回任务 Markdown，并保留每个 agent 的历史轮次。

## 频道与模型

- 个人微信通道：`openclaw-weixin`，当前建议绑定到 `codex-agent`。
- 企业微信通道：`wecom`，当前建议绑定到 `life-agent`。
- Codex agent 可使用 OpenAI 订阅模型和 Codex runtime。
- 非关键或兜底场景建议配置 DeepSeek 等备用模型，避免某个云端模型不可用时全局停摆。

## 像素工作室

黑洞协作面板上方有一个很小的像素工作室。每个 agent 都有自己的工位：

- 未被调用：发呆、黑白灰状态。
- 被选中：工位被点亮。
- 正在运行：角色会有轻量动作，例如敲键盘、巡逻、翻书、贴便签。
- 完成、跳过、错误：用不同状态显示。

像素卡通只是状态层，不替代文字记录、按钮和任务文件，因此不会影响功能运行。

## 手机远程访问

启动脚本会启动本机 Web UI 和 Cloudflare 临时隧道，并生成 6 位访问码。远程地址和访问码会写入：

```text
~/.openclaw/session-viewer-remote/remote-info.txt
```

如果本机已有对应频道会话，启动后还会自动发送到最近的个人微信和企业微信直聊会话。需要关闭时可设置：

```bash
OPENCLAW_REMOTE_NOTIFY=0
```

## 安全边界

本工具会读取本机 OpenClaw session、Obsidian 目录和附件缓存。开源仓库不应包含：

- OpenClaw token 或访问码
- 微信、企业微信密钥
- Cloudflare 临时地址记录
- `.openclaw` 私人配置
- Obsidian 私人会话内容
- 本机日志和缓存

## 推荐名称

中文对外名称：OpenClaw 智能体工作室  
英文对外名称：OpenClaw Agents Studio  
旧称：OpenClaw 会话工具

旧称只作为历史备注保留；新文档、UI 和启动入口统一使用“智能体工作室”。
