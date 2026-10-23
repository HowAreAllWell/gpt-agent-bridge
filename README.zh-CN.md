# GPT-Agent Bridge

[English](README.md) | [简体中文](README.zh-CN.md)

**与 ChatGPT Web 一起思考，协调你的本地 Agent 团队。**

GPT-Agent Bridge 把普通的 **ChatGPT 网页项目对话（Web Project Chat）**
变成你自己电脑上工作的思考伙伴和协调者——这就是 **Web Principal**。
你和 ChatGPT 一起界定真正的问题、定下目标；ChatGPT 把有边界的任务
派给你已经在 Herdr 里运行的本地 Agents；它们完成后，报告回到同一段对话，
由 ChatGPT 直接读取项目里真实的文件、diff 和图片核查，再走下一步。
目标、范围和权限始终由你掌握；Bridge 不会替你安装供应商或提供 Agents。

比如：“从两个角度分别调查这个失败的测试，再让第三个 Agent 评审修复方案。”
你的 Agents 工作时，你可以在对话里继续思考——也可以离开屏幕；
本地 Agent 结束时，可选的 Chrome 提醒可以送达绑定的那一个对话，
Web Principal 从那里接续。

## 实际演示

**演示 · ChatGPT Web ↔ Bridge ↔ 四个 Herdr Agents（2 倍速，60 fps，无音轨）**

https://github.com/user-attachments/assets/f1f3fb48-466e-4154-8b79-6d5a587ffd16

连续展示四路派发、本地 PDF 分析、报告核查与一个 Agent 的真实报错；可全屏查看终端文字。

## 一轮工作长什么样

**ChatGPT 决定 → 本地 Agents 执行 → 结果回到对话 → ChatGPT 查证证据 → 你继续推进。**

1. **决定。** 你和 ChatGPT 把问题问清楚、比较方案，定下范围和验收条件。
2. **派发。** ChatGPT 把有边界的任务发给你已授权的合格 Herdr Agents——可并行，可跨供应商和模型。
3. **回来。** 本地 Agent 完成后会把报告发布到同一段对话；可选的完成通知可以让该对话中的 Web Principal 接续处理。
4. **查证。** 在采信任何总结之前，ChatGPT 会去读它背后真实的文件、diff 和图片。
5. **继续。** 认可就进行下一步；有疑问就复查或改派——每次派发仍需你的授权。

## ChatGPT 能直接看到什么

- **直接读文本和图片。** ChatGPT 可以直接读取项目里的 UTF-8 文本
  （长文件分页读取）和原生 PNG/JPEG/GIF/WebP 图片（单张上限 5 MiB）——不用复制粘贴。
- **原地审查仓库。** 项目上下文、目录列表、文本搜索、diff 和文件元数据（大小、SHA-256）
  回答“代码实际长什么样”——只读，限于你连接的项目。
- **原文件按需取用。** PDF/DOCX/ZIP 这类原文件，由 ChatGPT 请 Bridge 准备好，
  再由它自己分片取回原始字节并核对 SHA-256——不用你反复手动上传附件。
  注意：准备不等于导入——ChatGPT 真正取回之前什么都没有被解析，
  普通 `read` 也从不提取 PDF/DOCX/ZIP 的内容。

## 离开屏幕，也要心里有数

本地 Agent 完成任务后，可选的 Chrome 扩展可以向已绑定并启用的那一个 ChatGPT 对话
自动发送简短完成通知（中文或英语）。该对话中的 Web Principal 收到后，
会读取可用的工作报告、核对实际结果，再判断下一步——你不必一直守在屏幕前。
它的前提是装有扩展的 Chrome、本机 Bridge 服务和那个对话本身都实际可用；
它不是永远在线的自动驾驶，任务完成也不等于任务成功。
页面忙碌时它拒绝发送；输入框有草稿时提供“追加到输入框末尾（另起一行）”或“忽略”，
绝不替你点发送；通知不会重复发送，无法确认效果的操作也不会自动重试。

<a id="why-web-principal"></a>
## 为什么使用 Web Principal

Bridge 不是“发一条命令然后祈祷”的单向按钮，也不是再建一个独立的编程面板：
你本来就在思考的那段对话，仍然是定目标、质疑结果、选择下一步的地方。

- **派工前先审视问题。** 确定计划前，重新表述模糊请求、揭示缺失前提并比较替代方案。
- **协调多个独立 Agents。** 将有明确边界的问题并行交给已有 Herdr Agents，
  可跨供应商和模型协作。把实现与评审分开，让一个 Agent 质疑另一个的发现。
- **验收前先核查证据。** 阅读完整任务报告，检查真实代码、文件、diff 和测试证据，
  区分实际观察、他人声称、证据缺口和未知结果；意见一致本身不证明正确。
- **有意识地跨对话延续决策。** 经授权后，把决策、原因和下一步边界保存在项目笔记，
  新对话可借助四个 Skills 接上这条思路。
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

**下载：**完整安装 ZIP [gpt-agent-bridge-v0.1.0-rc.8.zip](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/download/v0.1.0-rc.8/gpt-agent-bridge-v0.1.0-rc.8.zip) · [发布页面](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/tag/v0.1.0-rc.8)。

**[从这里开始：完整配置指南 →](docs/GETTING-STARTED.zh-CN.md)**

| 你的电脑 | 核心准备 | 网页与可选提醒 |
| --- | --- | --- |
| **原生 Ubuntu 桌面** | [Ubuntu 终端：`./prepare`](docs/GETTING-STARTED.zh-CN.md#native-ubuntu-desktop) | ChatGPT 网页；可选同机 Chrome 提醒 |
| **Windows + WSL2** | [Windows PowerShell：`.\Start-Bridge.ps1 prepare`](docs/GETTING-STARTED.zh-CN.md#windows-and-wsl2) | 同一套网页步骤；可选 Windows Chrome 提醒；核心在 WSL2 内运行 |

使用命令前，先从指南第 1 步阅读。所选 Linux 环境需要已有 **Herdr 0.9.0**，
**安装本地软件前**，先检查 ChatGPT 工作区的自定义 MCP、Plugin Creator/Skills 和项目指令入口。
仅配置 Bridge 时，不需要运行 Agent。
两条路线随后使用相同的 ChatGPT 网页步骤；完成提醒是可选功能。

<a id="how-it-works"></a>
## 如何运作

1. **准备电脑。** 指南解释你要批准的改动：专用 Python 环境，
   以及安装、设为自动启动并立即启动两个 Linux 后台服务（Bridge 和 Tunnel 连接）。
   Chrome 扩展只在之后选择提醒时才准备和加载。
2. **连接 ChatGPT。** 私有 **Secure MCP Tunnel（安全隧道）**把工具请求传到本机 Bridge。
   将连接安装为插件，再在普通网页对话中用 **Plugin Creator** 上传包内唯一的
   `Bridge-Skills.zip`，添加四个提供的 **Skills（可重复使用的指令流程）**，
   分别用于连接、返回、交接和协调工作。
3. **选择项目与权限。** 将基础指令 **Core** 保存到 ChatGPT 项目。
   连接已有本地 Git 仓库，审阅返回的项目识别文本 **Binding**，
   保存在 Core 旁。Bridge 未识别到可用连续性配置时，onboarding 会问一次是否设置笔记；
   拒绝就不写笔记。随后做一次小范围只读检查。

指南最后只需简单检查：一次可见的 `bridge_health` 调用，加上四个已安装 Skill 名称。
建立连接不会启动 Agents，也不授予项目任务权限。

Plugin Creator 和安装资格取决于套餐/工作区权限；缺少所需控件时，
在账号问题处停止。[第 6 步](docs/GETTING-STARTED.zh-CN.md#6-install-and-discover-all-four-native-skills)
只上传可见的 `Bridge-Skills.zip`，请 **Plugin Creator** 更新已有个人 Bridge 插件——
保留其 MCP 连接和名称——再确认四个 Skill 条目和**新的普通项目对话**健康调用。
全程不涉及隐藏文件夹或分开上传多个文件。Work/本地 Codex 不属于这套配置。
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

<a id="download"></a>
<a id="download-and-status"></a>
## 下载

下载完整安装 ZIP
[**gpt-agent-bridge-v0.1.0-rc.8.zip**](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/download/v0.1.0-rc.8/gpt-agent-bridge-v0.1.0-rc.8.zip)
（[v0.1.0-rc.8 发布页面](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/tag/v0.1.0-rc.8)）。
使用完整发行 ZIP；GitHub 的 **Source code ZIP** 和 **Code → Download ZIP** 不是安装包。
配置步骤所需的安装包，根目录必须在 `prepare`、`Start-Bridge.ps1`、`release-manifest.json`
旁边包含 `Bridge-Skills.zip`；解压后请先确认。

**下一步：** [按新手指南操作](docs/GETTING-STARTED.zh-CN.md)。
Herdr 前提条件：[入门页内的简短安装说明](docs/GETTING-STARTED.zh-CN.md#herdr-090-prerequisite)。
进阶手动设置和可选示例：[Quickstart](docs/QUICKSTART.zh-CN.md)。
服务检查及进阶手动停止/移除：[自启动](docs/AUTOSTART.zh-CN.md)。
进阶契约和文档导航：[技术参考](docs/TECHNICAL-REFERENCE.zh-CN.md)。
项目笔记：[项目延续](docs/PROJECT-CONTINUITY.zh-CN.md)。
任务、提醒和重启限制：[生命周期](docs/LIFECYCLE-RESTART-CONTRACT.zh-CN.md)。

[MIT License（未翻译的许可证原文）](LICENSE)。
