# GPT-Agent Bridge

GPT-Agent Bridge 连接 **ChatGPT Web Project 中的 Principal** 与本地 **Herdr 管理的 coding Agents**，提供项目范围内的工作委派、完整工作报告与来源证据核查。用户决定范围与授权；Principal 分析与核对结果，Agents 在本地项目中执行工作。

**第一次使用：[入门指南（Getting Started）](docs/GETTING-STARTED.md)**。安装、连接、Skills 与首次协作都以这一份指南为入口。

可选的 Chrome 扩展程序会把完成提醒送到用户明确绑定的 Chat；提醒本身不代表完整报告已被处理。

## 组件与安装形式

发行计划采用**一份完整 Release ZIP**；可用文件与获取方式以入门指南说明为准，本页不宣称完整 ZIP 已发布。

| 组件 | Windows 新安装配置 |
| --- | --- |
| ChatGPT Web Principal | 在 Project Chat 中使用 Bridge 工具、Core 与 Plugin Skills |
| Bridge 与 Secure MCP Tunnel | 运行于选定的 WSL Linux 环境 |
| Chrome 扩展程序（可选） | 安装到用户选定的 Windows 本地私有 NTFS 文件夹，以 unpacked 方式加载；不需要 Chrome Web Store |
| Herdr 与 coding Agents | 由用户准备并启动，Agent 在授权的本地项目中工作 |

Bridge 不会自动安装 Codex／Gemini，也不会替你启动 Agents。账号权限与 Agent 供应商的登录、配额由用户管理。

目前仍是候选流程；新的 Windows 安装与 Chrome 重启后行为仍需实机验收，不能以源代码检查代替。

## Core 与四个 Skills

[Project Instructions Core（请核对当前模板）](templates/WEB-PRINCIPAL-CORE.md) 与四个 Plugin Skills 分开核对及安装；本页不宣称公开 Core 已与当前 ChatGPT Project Instructions 同步。

四个 Skills 是 `project-onboarding`、`project-resume`、`handoff-preparation`、`team-deliberation`，各自提供可触发的工作流程，不应把 Skill 全文合并进 Core。具体操作见入门指南。

## 技术参考

- [技术参考](docs/TECHNICAL-REFERENCE.md)：工具、限制与验证方式。
- [项目延续](docs/PROJECT-CONTINUITY.md)：项目规则、状态与记忆的契约。
- [Chrome 通知扩展程序](browser-extension/README.zh-CN.md)：绑定、投递限制与恢复。
- [Bridge 服务参考](docs/BRIDGE-AUTOSTART.md)：服务安全与恢复契约，供进一步排查使用。

采用 [MIT License](LICENSE)。
