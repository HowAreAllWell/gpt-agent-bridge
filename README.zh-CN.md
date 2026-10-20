# GPT-Agent Bridge

[English](README.md) | [简体中文](README.zh-CN.md)

**与 ChatGPT Web 一起思考，协调你的本地 Agent 团队。**
在普通 **ChatGPT Web Project Chat** 中，让 Web Principal 帮你界定真正的问题、质疑假设、比较方案。将调查、实现和独立评审委派给**任何已获你授权、受 Herdr 支持、可运行且由其管理的本地 Agent**，包括来自不同供应商、使用不同模型的 CLI Agents。

Bridge 提供 MCP 工具与 Skills，Herdr 提供已有的本地 Agents。Web Principal 将报告与真实代码、文件、diff 和测试证据对照核验；目标、范围和权限始终由你掌握。

**[开始使用 →](docs/GETTING-STARTED.zh-CN.md)** — 一份涵盖准备、连接、指令、项目绑定和首次使用的指南。

<a id="why-web-principal"></a>
## 为什么使用 Web Principal

- **派工前先审视问题。** 确定计划前，重新表述模糊请求、揭示缺失前提并比较替代方案。
- **协调不同供应商和模型的独立 Agents。** 将研究、实现和评审拆成有明确边界的任务，交给已有的 Herdr Agents；当另一种视角可能改变决策时，让它们质疑彼此的结论。
- **验收前先核查证据。** 阅读完整 Work 报告，检查真实代码、文件、diff 和测试证据，区分实际观察、他人声称、证据缺口和未知结果；意见一致本身不证明正确。
- **有意识地跨 Chat 延续决策。** 显式项目延续保存决策、原因和下一步边界；不会自动恢复运行中的 Work、重放任务或建立全局记忆。

例如，已有三个合格的 Herdr Agents 可用时，Web Principal 可以先分析一个存储设计决策，向其中两个并行提出独立问题，再请第三个评审并质疑调查结果，最后亲自对照相关代码、diff 和测试证据核查报告，给出建议。

需要深入推理和决策时，可选用账号可用的 [GPT-6 Pro](https://help.openai.com/en/articles/20001354-gpt-6-and-other-models-in-chatgpt) 担任 Web Principal，由 Herdr 管理的 Agents 负责实现和独立评审。模型由你选择，访问资格取决于自己的 ChatGPT 套餐与工作区设置，不包含在 Bridge 中。

<a id="how-it-works"></a>
## 如何运作

在普通 **ChatGPT Web Project Chat** 中使用原样提供的 **Core** 和**四个独立的原生 Skills**。私有 **Secure MCP Tunnel** 把 Bridge 工具连接到本地 Bridge，以及你已在授权仓库中启动、由 **Herdr 管理的 Agents**。Windows 上，Bridge/Tunnel 运行于 WSL。可选 unpacked Chrome 扩展位于私有 Windows 本地文件夹，只提醒你绑定的准确 Chat。

MCP 连接、手动 Core 安装、Skill 发现和仓库绑定是独立检查；都不会启动 Agents 或授权任意工作。无需 API Principal，也不强制某家 Agent 供应商；账号访问、供应商登录和配额仍由你管理。

按照[开始使用第 6 步](docs/GETTING-STARTED.zh-CN.md#6-install-and-discover-all-four-native-skills)，在**普通 Web Chat 中使用 Plugin Creator**，复用已连接的 Bridge App 安装 Skills。在目标 Project Chat 中分别验证 Bridge 工具和全部四个原生 Skills。无需配置 Work/Codex，在这些界面成功也不能替代此检查。这里规定的是产品支持的使用场景，不代表平台强制将插件限定为 Web 可见。

<a id="after-setup-three-useful-steps"></a>
## 配置完成后：三个实用步骤

1. **确认位置：** 选择授权项目，请求当前 context 和一次只读源文件核查。核对仓库和可用 Agents。
2. **明确委派：** 说明问题、允许改动和验收条件；授权向实际观察到的合格 Agent 输入。它工作时，继续有用的独立思考。
3. **判断并保存：** 阅读完整报告，对照原始证据、解决矛盾，并在获得授权时保存影响后续决策的延续信息。提醒既不证明成功，也不证明评审完成。

<a id="download-and-status"></a>
## 下载与状态

在 [Releases 列表](https://github.com/HowAreAllWell/gpt-agent-bridge/releases)选择经评审的 **PRE-RELEASE**，下载其附加的**完整安装 ZIP**，不要使用 GitHub 自动生成的 **Source code ZIP**。核对该版本的源码提交、改动和限制；GitHub main 可能包含尚未进入附件 ZIP 的修复。

全新 Windows/账号安装、Chrome 加载和重启后行为**尚未通过实机验收**；完整 Python 套件并非全绿。源码/合成检查只证明实际覆盖的情形。已有安装不会自动迁移、重置或重新生成密钥身份。

进阶契约与文档导航：[技术参考](docs/TECHNICAL-REFERENCE.zh-CN.md)。项目记忆：[项目延续](docs/PROJECT-CONTINUITY.zh-CN.md)。Work、通知与重启限制：[生命周期](docs/LIFECYCLE-RESTART-CONTRACT.zh-CN.md)。

[MIT License（未翻译的许可证原文）](LICENSE)。
