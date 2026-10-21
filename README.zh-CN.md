# GPT-Agent Bridge

[English](README.md) | [简体中文](README.zh-CN.md)

**与 ChatGPT Web 一起思考，协调你的本地 Agent 团队。**

**Web Principal** 是普通 **ChatGPT 网页项目对话（Web Project Chat）**中的思考伙伴。
用提供的指令帮助你界定真正的问题、质疑假设、比较方案，
再协调本地 Agents 分别调查、实现和独立评审。

Bridge 把这段对话连接到项目，以及**任何已获你授权、受 Herdr 支持、可运行且由其管理的本地 Agent**，
包括来自不同供应商、使用不同模型的终端 Agents。
目标、范围和权限由你掌握；Bridge 不会替你安装供应商或提供 Agents。

**v0.1.0-rc.6 测试预发布版已提供。** [下载完整安装 ZIP](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/download/v0.1.0-rc.6/gpt-agent-bridge-v0.1.0-rc.6.zip) · [发布说明](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/tag/v0.1.0-rc.6)。
最终 ZIP 的 SHA256 和大小见[发布页面](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/tag/v0.1.0-rc.6)。Chrome 提醒仍是可选功能。
全新 Ubuntu/Windows WSL2 和 ChatGPT 网页/Skills 流程尚未通过实机验收。

**[从这里开始：完整配置指南 →](docs/GETTING-STARTED.zh-CN.md)**

| 你的电脑 | 核心准备 | 网页与可选提醒 |
| --- | --- | --- |
| **原生 Ubuntu 桌面** | [Ubuntu 终端：`./prepare`](docs/GETTING-STARTED.zh-CN.md#native-ubuntu-desktop) | ChatGPT 网页；可选同机 Chrome 提醒 |
| **Windows + WSL2** | [Windows PowerShell：`.\Start-Bridge.ps1 prepare`](docs/GETTING-STARTED.zh-CN.md#windows-and-wsl2) | 同一套网页步骤；可选 Windows Chrome 提醒；核心在 WSL2 内运行 |

使用命令前，先从指南第 1 步阅读。所选 Linux 环境需要已有 **Herdr 0.9.0**，
**安装本地软件前**，先检查 ChatGPT 工作区的自定义 MCP、Plugin Creator/Skills 和项目指令入口。
仅配置 Bridge 时，不需要运行 Agent。
两条路线随后使用相同的 ChatGPT 网页步骤；完成提醒是可选功能。

<a id="why-web-principal"></a>
## 为什么使用 Web Principal

- **派工前先审视问题。** 确定计划前，重新表述模糊请求、揭示缺失前提并比较替代方案。
- **协调多个独立 Agents。** 将有明确边界的问题并行交给已有 Herdr Agents，
  可跨供应商和模型协作。把实现与评审分开，让一个 Agent 质疑另一个的发现。
- **验收前先核查证据。** 阅读完整任务报告，检查真实代码、文件、diff 和测试证据，
  区分实际观察、他人声称、证据缺口和未知结果；意见一致本身不证明正确。
- **有意识地跨对话延续决策。** 经授权后，把决策、原因和下一步边界保存在项目笔记。
  不会自动恢复运行中的任务、重放任务或建立全局记忆。

例如，已有三个合格 Herdr Agents 可用时，先与 ChatGPT 分析一个存储设计决策。
让其中两个并行调查独立问题，再请第三个评审并质疑它们的发现。
最后对照相关代码、diff 和测试证据核查报告，再选择方案。
每项派工仍需要你的授权。

需要深入推理和决策时，可选用
[GPT-6 Pro](https://help.openai.com/en/articles/20001354-gpt-6-and-other-models-in-chatgpt)
担任 Web Principal，由 Herdr 管理的 Agents 实现和评审。
模型由你选择，访问资格取决于自己的 ChatGPT 套餐与工作区。
Bridge 不包含模型访问、不自动选模型，也不承诺相较其他模型的速度或质量。

<a id="how-it-works"></a>
## 如何运作

1. **准备电脑。** 指南解释你要批准的改动：专用 Python 环境，
   以及安装、设为自动启动并立即启动两个 Linux 后台服务（Bridge 和 Tunnel 连接）。
   Chrome 扩展只在之后选择提醒时才准备和加载。
2. **连接 ChatGPT。** 私有 **Secure MCP Tunnel（安全隧道）**把工具请求传到本机 Bridge。
   将连接安装为插件，再在普通网页对话中用 **Plugin Creator** 添加四个提供的
   **Skills（可重复使用的指令流程）**，分别用于连接、返回、交接和协调工作。
3. **选择项目与权限。** 将基础指令 **Core** 保存到 ChatGPT 项目。
   连接已有本地 Git 仓库，审阅返回的项目识别文本 **Binding**，
   保存在 Core 旁，再做一次小范围只读检查。

指南分别检查本地准备、网页连接、四个已安装 Skills 和正确仓库。
本地健康结果或截图中的四个蓝色开关，不能证明其他环节也已完成。
建立连接不会启动 Agents，也不授予项目任务权限。

Plugin Creator 和安装资格取决于套餐/工作区权限；缺少所需控件时，
在账号问题处停止。[第 6 步](docs/GETTING-STARTED.zh-CN.md#6-install-and-discover-all-four-native-skills)
明确列出要上传的五个文件，以及怎样在**新的普通项目对话**验证四个已安装流程。
Work/本地 Codex 不是受支持的安装路线，在那里成功也不能替代这项检查。
无需另设模型 API Principal。

可选 Chrome 扩展只向你明确选择的准确对话发送完成提醒。
Ubuntu 上扩展与 Bridge 在同一台电脑运行；
Windows 上加载可选提醒动作最终输出的私有 Windows 本地目录。
成功后才运行 `./prepare reminders` 或 `.\Start-Bridge.ps1 reminders`。
它保留草稿，追加提醒后不会代你点击发送。

<a id="after-setup-three-useful-steps"></a>
## 配置完成后：三个实用步骤

1. **确认位置：** 选择授权项目，请求当前上下文和对一个指定文件的只读检查，
   核对仓库。需要委派时，自己在 Herdr 启动兼容 Agent，再确认它实际可用。
2. **明确委派：** 说明问题、允许改动和验收条件；授权向实际观察到的合格 Agent 输入。
   它工作时，继续有用的独立思考。
3. **判断并保存：** 阅读完整报告，对照原始证据、解决矛盾，
   经授权后保存影响后续决策的项目笔记。提醒既不证明成功，也不证明评审完成。

账号、供应商登录、模型选择、费用和配额仍由你管理。

<a id="download-and-status"></a>
## 下载与状态

从 [v0.1.0-rc.6 预发布版](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/tag/v0.1.0-rc.6)下载 [**gpt-agent-bridge-v0.1.0-rc.6.zip**](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/download/v0.1.0-rc.6/gpt-agent-bridge-v0.1.0-rc.6.zip)。
完整解压；GitHub 的 **Source code ZIP** 和 **Code → Download ZIP** 不是安装包。
旧 rc.4 ZIP 不含安装修复；rc.6 也修正了 rc.5 包内过期的发布说明。本包指南与发布的 rc.6 源码一致。

此预发布版仅完成静态 ZIP/完整性验证；全新原生 Ubuntu Desktop、Windows WSL2、
普通 ChatGPT Web 自定义 MCP、Plugin Creator/四个 Skills、Chrome 和重启行为**尚未通过现场验收**。

**下一步：** [按新手指南操作](docs/GETTING-STARTED.zh-CN.md)。
Herdr 前提条件：[入门页内的简短安装说明](docs/GETTING-STARTED.zh-CN.md#herdr-090-prerequisite)。
进阶手动设置和可选示例：[Quickstart](docs/QUICKSTART.zh-CN.md)。
服务检查及进阶手动停止/移除：[自启动](docs/AUTOSTART.zh-CN.md)。
进阶契约和文档导航：[技术参考](docs/TECHNICAL-REFERENCE.zh-CN.md)。
项目笔记：[项目延续](docs/PROJECT-CONTINUITY.zh-CN.md)。
任务、提醒和重启限制：[生命周期](docs/LIFECYCLE-RESTART-CONTRACT.zh-CN.md)。

[MIT License（未翻译的许可证原文）](LICENSE)。
