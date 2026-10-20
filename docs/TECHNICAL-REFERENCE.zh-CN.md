<a id="technical-reference"></a>
# 技术参考

[English](TECHNICAL-REFERENCE.md) | [简体中文](TECHNICAL-REFERENCE.zh-CN.md)

想**弄清 Bridge 的各个部分、找到合适工具，或核对准确技术限制**时，使用本页。
不需要从头读到尾。

**第一次安装？** 先按[入门指南](GETTING-STARTED.zh-CN.md)操作。
指南平等提供原生 Ubuntu 桌面和 Windows+WSL2 路线，再进入同一套普通
ChatGPT 网页项目对话配置。本页供之后查阅，不是第二轮安装清单。

在已连接的项目对话中，可以先指定一个获授权文件，做小检查：

> 只读这个文件，解释相关行。展示实际结果和缺失证据。
> 不要编辑、执行命令/测试或发送 Agent 任务。

**成功标志：** 正确项目的真实内容支持解释。
**受阻状态：** 目标错误、缺少工具、页面不完整或访问错误，都应明确说明；
不要悄悄换项目或重复结果未知的操作。
下方源码契约描述实现行为，不认证当前服务、账号控件或全新安装。


<a id="document-owners-and-audiences"></a>
<a id="文档-owner-与读者"></a>
## 按需要选择文档

| 你要做什么 | 阅读哪页 | 谁需要 |
| --- | --- | --- |
| 了解产品 | [README](../README.zh-CN.md) | 判断 Bridge 是否适用的所有人 |
| 安装并建立首次连接 | [入门指南](GETTING-STARTED.zh-CN.md) | Ubuntu 桌面或 Windows+WSL2 新用户 |
| 手动运行进程或检查 Herdr 0.9.0 | [Quickstart](QUICKSTART.zh-CN.md) | 开发者、手动配置排错者 |
| 查能力和准确限制 | [技术参考](TECHNICAL-REFERENCE.zh-CN.md) | 查阅用户、核对契约的开发者 |
| 为下次对话保存决策 | [项目延续](PROJECT-CONTINUITY.zh-CN.md) | 授权项目笔记与恢复上下文的用户 |
| 理解任务完成、提醒或结果过期 | [生命周期](LIFECYCLE-RESTART-CONTRACT.zh-CN.md) | 判断任务结果的用户 |
| 检查或恢复后台服务 | [Autostart](AUTOSTART.zh-CN.md) | 管理自己安装的操作者 |
| 读取文件、改动、报告或原件 | [观察工具](OBSERVATION-TOOLS.zh-CN.md) | 核查证据的用户 |

[AGENTS](../AGENTS.md)是贡献者规则，阅读不分配角色或授予项目权限。
提供的 [Core](../templates/WEB-PRINCIPAL-CORE.md) 和四个 Skills 是指令输入。
公开包不含私有项目决策；安装插件不会注册仓库、初始化笔记、启动 Agents 或授权任务。

可直接跳到[工具](#tool-reference)、[指令与职责](#web-principal-layers)、
[缺少 Skills](#native-skills-and-app-binding)、[网页插件配置](#private-native-plugin-packaging)
或[进阶服务接管](#optional-system-service-adoption)。


<a id="original-overview-and-setup-context"></a>
<a id="原始概览与配置背景"></a>
## 这些部分怎样配合

**Web Principal** 指 ChatGPT 作为你的思考伙伴：
界定问题、比较方案、协调已授权工作并判断证据。它会使用以下部分：

| 名称 | 简单解释 | 要检查什么 |
| --- | --- | --- |
| **Core 和 Project Binding** | 保存的 ChatGPT 项目指令：如何工作、你授权哪个本地项目 | 完整文本保存到预期项目 |
| **MCP App / 插件** | ChatGPT 中选择的连接；MCP 是传递工具请求的协议 | 真实且成功的 `bridge_health` 调用 |
| **18 个工具** | 读取文件、派发任务等操作 | 实际可用的工具目录 |
| **四个原生 Skills** | 安装到插件的可复用指令流程 | 四份完整已安装正文，不只是附件 |
| **Herdr / 本地 Agent** | Herdr 管理终端会话；你在其中启动兼容 Agent | 新鲜项目上下文显示合格且已授权的 Agent |
| **Work** | Bridge 为已派发任务保留的记录 | 每项派发结果、最终分类和报告 |
| **Git 提交候选** | 为提交前评审捕获的暂存改动 | 准确选择内容及单独提交授权 |
| **Checkout** | 用作证据/操作目标的本地 Git 工作目录 | 准确目录和身份，不只是同名 |

ChatGPT 负责思考，Bridge 提供有界访问，Herdr 管理已有本地 Agents。
Skill 不是 Agent，也不是另一个工具。任何部分都不授予使用全部可用能力的权限。


<a id="getting-started"></a>
<a id="开始使用"></a>
## 从入门指南开始

从[入门指南](GETTING-STARTED.zh-CN.md)第 1 步开始，运行入口前先选电脑路线：

| 电脑 | 准备入口 | 浏览器/提醒位置 |
| --- | --- | --- |
| **原生 Ubuntu 桌面** | Ubuntu 终端，`./prepare` | 同一台 Ubuntu 电脑的 Chrome；不需要 WSL 或 PowerShell |
| **Windows+WSL2** | Windows PowerShell，`.\Start-Bridge.ps1` | Windows Chrome；使用最终输出的 Windows 本地扩展目录 |

指南解释已有 **Herdr 0.9.0**、账号权限、私有凭据和同意提示。
准备程序建立自己的 Python 环境和扩展文件，再在支持的 Linux 上
**安装、启用并启动 Bridge 和 Tunnel 两个 systemd 服务**（systemd 是 Linux 后台服务管理器）。
Bridge 不安装或启动 Herdr/Agents；仅准备时不必运行 Agent，浏览器提醒可选。

原生 Ubuntu 新手安装、全新 Windows/账号配置、Chrome 加载和重启后行为，
尚未在全新用户机器验收。Ubuntu Server/无桌面、浏览器在别处时，
没有经过验证的本地 Chrome 回环提醒路线；不要由 Tunnel 连通推断提醒可用。

[开发者 Quickstart](QUICKSTART.zh-CN.md)及其
[Windows+WSL2 小节](QUICKSTART.zh-CN.md#windows-and-wsl2)
是替代的手动路线，不是准备完成后的追加步骤；不要在已有服务旁启动重复进程。
打包示例在[开发者配置小节](#public-package-configuration)，新手无需编辑 App ID 文件。


<a id="what-bridge-adds"></a>
<a id="bridge-增加了什么"></a>
### 配置后可以做什么

- **派工前先思考。** 确定分工前，让 ChatGPT 质疑假设、比较方案。
- **协调合格本地 Agents。** 将独立、有界问题交给已获授权、受 Herdr 支持且可运行的 Agents。
- **核查真实证据。** 将完整报告与相关代码、diff 和已授权测试记录比较。
- **保留有用项目决策。** 明确保存原因和下一步边界，供后续对话使用；不会恢复运行中任务。
- **授权后才做窄范围改动。** 精确文本编辑和经评审的 Git 候选保持明确范围；
  有工具不等于有权限。

可选扩展可提醒你明确启用的准确对话。提醒不是报告、成功证明或模型唤醒保证。
这个自行运行的包提供源码、文档和合成测试，不提供已配置账号、供应商或私有项目笔记。


<a id="tool-reference"></a>
## 工具参考

**可以直接用自然语言请求。** 下表帮助辨认 ChatGPT 应使用的操作；
展开准确目录可查原有签名。

| 目标 | 应辨认的工具 | 重要边界 |
| --- | --- | --- |
| 检查连接或选择项目 | `bridge_health`、`bridge_overview`、`context` | 当前观察不授予权限、不恢复 Work。 |
| 连接已有仓库 | `project_register` | 不创建仓库、不授权任务、不绑定 Chat。 |
| 读取证据 | `read`、`search`、`list_entries`、`inspect_file`、`diff` | 明确范围，读完相关分页。 |
| 阅读任务报告或诊断 | `work_report`、`agent_terminal_read` | 终端尾部不是完整报告。 |
| 取回原文件 | `prepare_file_attachment` | 准备链接不上传或拼接文件。 |
| 派发工作 | `delegate` | 向已有 Agent 输入；逐项未知结果不能安全重发。 |
| 初始化或保存项目笔记 | `project_initialize`、`current_state_update` | 另行授权写入，遵守冲突检查。 |
| 编辑或提交 | `project_text_edit`、`commit_prepare`、`commit` | 选定路径的准备会暂存；提交需要明确授权。 |

源码目录定义 **18 个供 ChatGPT 调用的工具**；仍需在自己的对话检查实际目录。
旧名称没有兼容调用别名。
下方提供商发现中的 “Codex” 指本地 Agent CLI，不是正常的 ChatGPT 插件安装界面。
日常请求与不完整结果见[观察工具](OBSERVATION-TOOLS.zh-CN.md)。
<details>
<summary>进阶：准确 18 工具目录与退役名称</summary>

SOURCE 目录包含 18 个面向模型的 MCP 工具，带显式行为 annotations。已退役 widget 及其三个仅 App 使用的 watch/claim/feedback 工具均不存在，包括隐藏调用能力。浏览器完成通知使用独立 loopback capability，不是模型轮询工具或报告正文 endpoint。

目录描述的是 SOURCE 行为；部署和 host 验收需要独立证据。所有注册工具在执行前拒绝未知参数；annotations 描述行为，不是授权，也不保证客户端不会拒绝。通用发现支持 Pi、Codex 和其他 raw providers。没有旧工具以隐藏方式或旧名字保留可调用性；专用 managed start/resume/cancel/cleanup/recovery APIs 已删除。边界与重新读取见[观察契约](OBSERVATION-TOOLS.zh-CN.md)。

工具名迁移：公开接口为匹配名称、描述和作用而更名——collaboration_snapshot→bridge_overview（选择器 project_ref；默认视图显示 registered_project_refs）、workspace_register→project_register(project_ref, path)、checkpoint→current_state_update、agent_observe→agent_terminal_read、attach_file→prepare_file_attachment。

当前重设计还删除了 delegate 可选的 report selector；每个已接纳 Work 都请求报告。context、commit_prepare 及其他保留名称不变；面向模型的 await 工具已删除。commit_prepare 保留三种模式（stage paths + freeze / capture already-staged / page a saved candidate）。不存在可调用 aliases；使用当前工具名称和 schemas。

| 工具 | 用途 / owner |
| --- | --- |
| `context(project_ref)` | 选定项目定位：Git facts、容量、Agent handles、延续 pointers，以及有界、session 匹配的 continuation_inbox 观察；不恢复/读取 state-file 正文、不消费结果、不绑定 Chat |
| `delegate(project_ref, assignments=[{agent_ref, task}, ...])` | 派发 1..N 个必需报告的任务并返回逐项回执。若已配置浏览器通知，符合条件的新 Work 可组成成员固定的通知分组；不会创建 cohort 界面卡片。部分派发不是事务；投递未知不能安全重发 |
| `agent_terminal_read(project_ref, agent_ref, limit=120)` | 有界、当前且不归属于历史 Work 的 Agent 终端输出；不是进度/status/liveness 轮询通道 |
| `read(project_ref, path, offset=0, limit=4096, work_ref=None, start_line=None, expected_sha256=None, end_line=None)` | 带元数据的 UTF-8 文本和原生图片证据；PDF/DOCX 原文件通过 prepare_file_attachment 获取 |
| `work_report(project_ref, work_ref, offset=0, limit=4096, expected_sha256=None)` | 分页读取 terminal work_ref 的 Agent 发布报告；报告缺失或无效是错误；文本本身不代表任务成功 |
| `search(project_ref, query, ..., work_ref=None, match_offset=0, include_untracked=False)` | 默认搜索 tracked files；显式 opt-in 额外搜索 nonignored untracked 文本 |
| `list_entries(project_ref, path=".", work_ref=None, offset=0, limit=50)` | 一个目录中准确的子项名称和类型 |
| `inspect_file(project_ref, path, work_ref=None)` | 常规文件 mode/size/完整 SHA-256，不含正文 |
| `prepare_file_attachment(project_ref, path, work_ref=None, expected_sha256=None)` | Hash 当前源文件，为后续 resources/read 准备会过期的 ResourceLinks；尚未上传、host 导入、拼接或附加；multipart 额外返回一个 receipt |
| `diff(project_ref, ..., work_ref=None, base=None, target=None)` | 当前差异或固定 commit 差异 |
| `bridge_overview(project_ref=None)` | Bridge bootstrap/runtime diagnostics；默认 root 还显示注册 project refs、只读 persisted-versus-live 注册观察和控制文档 |
| `bridge_health()` | 响应中的 server registration 与观察到的 Herdr connectivity |
| `project_register(project_ref, path)` | 注册已有本地 Git 项目（准确的绝对现有 repository/checkout root）；不创建 repo/worktree/ChatGPT Project 或 continuity 文件，不授予任务权限。结果区分发布前无影响、已发布但持久性未知及只读 live-versus-persisted 观察 |
| `project_initialize(project_ref, seed)` | 为已注册项目发布全新 canonical `.principal/`，或已有 canonical manifest 时不操作。拒绝 non-canonical `.principal`，不注册、stage、commit 或授予任务权限 |
| `current_state_update(project_ref, expected_revision, content=None, edits=None)` | 仅替换/创建 manifest 路由的 current-state 文件；不保存历史或恢复点。可选 bridge-state-slot 是字节与 limit 身份检查，不摘要、不截断 |
| `project_text_edit(project_ref, path, expected_sha256, edits, work_ref=None)` | 对已有 UTF-8 文件做精确编辑；需要原文完整 hash |
| `commit_prepare(project_ref, paths=None, work_ref=None, candidate_id=None, view="summary", offset=0, limit=50)` | 提供 paths 时 stage 字面文件并冻结 candidate；省略时冻结已有 staged 内容；提供 candidate_id 时分页保存的 candidate，不 stage/重新捕获 |
| `commit(project_ref, candidate_id, message)` | 提交准确的 staged candidate；保留工作文件和 index 字节 |

</details>


<a id="project-selection-and-authority"></a>
### 项目选择与授权

告诉 ChatGPT 你授权的注册 `project_ref`，核对返回的本地目录。
ChatGPT 项目同名不证明选择正确。目标错误或身份未证明时停止，
不要让它改选另一仓库作为替代。
<details>
<summary>进阶：准确契约与实现限制</summary>

完整参数以实际客户端 schemas 为准。每个 project-scoped 调用需要明确授权的 ref，并重新验证注册 Git root。Project Instructions 定义有限的允许 project_ref 集；registry membership 本身不是任务授权。ChatGPT Project 身份仍是 not_exposed_or_unproven。不存在可变全局 current project、静默 root fallback、placement、migration 或自动重新提交丢失 Work。

</details>


<a id="delegation-and-completion-reminders"></a>
### 委派与完成提醒

授权任务后，分别检查每个 `delegate` 回执。例如：
“让这两个合格 Agents 在此范围内调查独立问题。”
可能一项已接纳，另一项被拒绝或结果不确定。
最后要读完整报告；已启用提醒只提供通知。
不要因响应或提醒丢失就重发任务。
<details>
<summary>进阶：准确契约与实现限制</summary>

`delegate` 接受明确 `project_ref` 和非空 `assignments` 列表，立即返回每项 dispatch receipt。List envelope 的 `ok:true` 不证明 admission、delivery 或任务成功；响应丢失不构成重放理由。继续有用的独立工作；若没有则结束当前 turn。不存在 widget、仅 App 的 watch 工具或第二次 watch-registration。

可选扩展观察每次 delegate 的固定保留成员关系。完成分类且可读后，同一项目和 Chat 中已就绪、未尝试批次可共用一条短提醒。不同项目/Chat 保留独立 queue、recipient 和 cursor。报告读取失败阻止该项目后续 feed entries；已排队的就绪 candidates 可跳过另一个暂不可读 candidate。Unknown sends 从不重放。完整 `work_report` 须另行阅读；提醒或报告读取不表示 Principal 已处理结果。参见[通知规则](LIFECYCLE-RESTART-CONTRACT.zh-CN.md#chrome-notification-authority-and-recovery)与[生命周期契约](LIFECYCLE-RESTART-CONTRACT.zh-CN.md)。

</details>


<a id="agent-reuse-work-lifetime-and-inbox"></a>
### Agent 复用、Work 生命周期与 inbox

**Work** 是一次派发任务的记录。**Inbox** 是当前请求会话可见的有限已分类结果，
不是持久记忆。

再次派工前刷新上下文，检查 attention/缺口提示。
读取相关报告或诊断，只记录有限的证据已提供事实，不证明问题已解决。
引用过期或缺失时，如实说明“不可用”，不要创建新任务或换目标。
<details>
<summary>进阶：准确契约与实现限制</summary>

复用已验证 Agent/resource 前，Bridge 扫描全部保留 terminal 历史。Abnormal/attention/uncertain 缺口会拒绝输入，直到针对未改变条件记录了合格、同 resource 的 terminal diagnostic 观察。较新 Work 的观察不能掩盖旧缺口。普通 result_ready 报告缺口不阻断，只增加一条 advisory 和其他缺口数。成功的非空 public report page 只记录较弱的 Work 级 evidence-serving 事实；classifier probes 不计入。Terminal 文本始终是当前输出，不归属于任何历史 Work。

这两种 marker 都不证明 review、resolution、任务成功或 safe retry，也不消费 delivery 或延长 evidence 寿命。这些 project/resource 卫生事实跨 Chat 共享；后来的读者不能擦除它们。Session-scoped inbox visibility 独立；关联不是身份认证。Expiry/restart 会丢失历史，不增加恢复能力。

Agents 可以共享 checkout。Work 在 prompt 前的 writer-gated refresh 捕获准确 execution identity；可选 work_ref 读取目标是被冻结的 checkout，不是原任务执行内容的真实性。每项目容量为 16 个 active Work、512 个 recent terminal receipts 和 512 个 expiry tombstones。Count pressure 下，terminal receipts 按最早 settled_at 优先过期，包括未读报告。通知/报告读取不 pin 或续期证据。已知过期返回 WorkRefExpired；其他缺失 refs 返回 WorkRefUnavailable。Capacity 只显示 counts，不暴露 refs。

另外，context 的 `continuation_inbox` 仅对匹配请求 `_meta["openai/session"]` 观察最多 50 个保留 classified Work refs、result classes 和分类时 report-status snapshots，持续可见到正常 expiry/discard。未知 sessions 只见未绑定的 retained-classified count，不见其他 session refs。此 process-local index 不增加 widget claim、follow-up、retry、discharge 或 retention protection。通知 receipt 不是处理结果；报告读取不消费结果。

`classification_report_status` 记录最终分类时的证据，不是当前报告可用性；attention Works 稍后可能发布可读报告，`work_report` 可观察它而不重新分类 Work。这不是持久恢复，也不证明 conversation identity。参见[请求范围 inbox 契约](LIFECYCLE-RESTART-CONTRACT.zh-CN.md#request-scoped-result-inbox-observation)。[Work 容量](LIFECYCLE-RESTART-CONTRACT.zh-CN.md#work-capacity-and-report-lifetime)负责生命周期与 handoff 边界。Terminal signals 不证明 writers 已停止。

</details>


<a id="checkout-observations"></a>
<a id="checkout-观察"></a>
### 辨认本地工作目录

两个 Agents 难以区分时，结合显示的工作区 ID 与标签/窗格提示，
再使用当前操作 handle（引用）。**Checkout** 是本地 Git 工作目录。
缺少显示信息可能只是观察被延后，不证明 Agent 消失。
显示的提交也不描述全部未提交文件。
<details>
<summary>进阶：准确契约与实现限制</summary>

context 和 bridge_overview 的 Agent rows 还显示 native `workspace_id`（没有证明 workspace name）与仅供显示的 `checkout` 摘要：status、root、branch、HEAD、dirty。用 workspace id 和 tab/pane hint 区分 workspace；`handle` 仍是操作 ref。Unknown/changed/deferred 观察的 checkout 值为 null；观察到 branch=null 表示 detached HEAD。每次 discovery 共用一秒显示预算，最多 16 个 checkout 观察、四个 workers，同一 checkout 复用一个结果。

每次有 guard 的 status 观察包含一次 configuration probe；默认 bootstrap 可能在同一预算内需要一个 display-identity 前提。预算耗尽会延后 metadata，不移除 Agent rows；native process cleanup 有额外有界宽限，OS calls 不可抢占。这不是原子 snapshot 或可写保证。HEAD 标识 commit，不是 dirty files 完整基线。Worktrees 不是 OS 安全隔离。

</details>


<a id="local-writes-and-exact-git-candidates"></a>
<a id="本地写入与准确-git-candidates"></a>
### 编辑文件与评审 Git 提交候选

先请求修改建议，再决定是否授权应用。
`project_text_edit` 使用完整源指纹修改已有文本文件。
Git 操作先评审改动：对选定路径的 `commit_prepare` **会暂存**，
`commit` 才提交经评审捕获的准确候选。没有通用 shell/测试工具。
拒绝或写入结果未知时，先检查再决定下一次变更。
详见[准确编辑/候选指南](OBSERVATION-TOOLS.zh-CN.md#candidate-version-actions)。
<details>
<summary>进阶：准确契约与实现限制</summary>

Public `run` 已从 SOURCE 删除，没有 alias 或通用命令替代。delegate 派发到已有 Agents，不等待；面向模型的 await 工具已删除。直接观察、current_state_update 和有界 project_text_edit 保留。

版本动作先 commit_prepare 再 commit。Selected-path preparation 会变更 index，可能写 objects；最终 commit 发布准确捕获的 tree，不重新读取 paths 或刷新 index。明确省略 paths 才是捕获已有 staged 内容。没有公开 commit_preview/stage_paths alias、command arguments 或 approval field。

project_text_edit 需要已有常规 UTF-8 文件的完整小写 SHA256，以及针对同一原文的 1..256 个准确、唯一、互不重叠编辑（文件/结果 <=1 MiB）。保留未触及字节、换行和 mode；不创建文件，不接受 links、binary/NUL、.git/traversal，不 stage 或执行命令。它和其他项目操作使用相同的 frozen Work target 与 writer gate。

commit_prepare 选择 1..2048 个字面常规文件路径（UTF-8 路径总字节 <=16 KiB，总内容 <=4 MiB），包括明确新文件/删除。拒绝 mixed staged/unstaged selection、selection 外 staging、clean/process filters、active index hooks 和内容转换设置。捕获字节通过一个 raw-object Git batch 写入；不逐文件调用 Git，也不为创建 objects 重新读取 worktree。Path ceiling 限制临时文件及验证工作；30 秒 operation deadline 和 candidate/cache 边界仍适用。

两种 gates 只覆盖合作中的 Bridge calls，不约束外部 writers。Unknown writes 不授权盲目重试。具体机械边界见 [candidate version actions](OBSERVATION-TOOLS.zh-CN.md#candidate-version-actions)。源码测试不认证运行中服务或客户端刷新。

</details>


<a id="text-and-native-image-reads"></a>
### 文本与原生图片读取

请求读取指定文本或图片。图片整张返回，上限 **5 MiB**；文本可能分页。
`read` 不提取 PDF/DOCX：`UnsupportedReadFormat` 指向原文件获取。
`BinaryFileUnsupported` 也不表示文档为空。
宿主能否显示或识别图片需要独立证据。
<details>
<summary>进阶：准确契约与实现限制</summary>

read 不再提取文档，只观察 UTF-8 文本和完整原生图片（PNG/JPEG/GIF/WebP，suffix 与 magic 匹配，上限 5 MiB）。PDF/DOCX 在访问正文前按验证后的 suffix 拒绝（`UnsupportedReadFormat`）；`prepare_file_attachment` 请求这些原文件，read 从不批准、解析或拼接。其他 binary/invalid-UTF-8 文件仍是 `BinaryFileUnsupported`，提供相同 prepare_file_attachment 指引。

read 现为唯一原生图片路径；旧 `view_image` 兼容工具已从 SOURCE 退役。统一 read 保留 native image serialization；源码与 wire 测试不认证 host 视觉识别。

</details>


<a id="mandatory-work-reports"></a>
### 必需的 Work 报告

每个已接纳任务都请求专用报告。某个 Work 进入终态，且其报告已发布并可读后，
就可用 `work_report` 读取该 Work 的全部报告分页，保持完整报告 SHA-256 指纹。
同批其他 Work 可能仍在运行，浏览器通知也可能未启用。
不要用终端尾部替代，也不要把 `result_ready` 当作结论正确。
报告缺失/无效需要处理；没有自动等待/重试或持久报告归档。
<details>
<summary>进阶：准确契约与实现限制</summary>

每个已接纳 Work 都请求报告。Bridge 追加私有临时报告（最多 1 MiB UTF-8）及其原子发布 staging file 的发布指令，不写入项目 checkout。该 Work 进入终态，且其报告已发布并可读后，就可用 `work_report` 读取该 Work 的报告，使用其 continuation 和完整报告 SHA-256 分页续读。其他 Work 可能仍在运行；无需等待批次通知就绪，通知也可能未启用。

Agents 必须能写入该私有位置；settlement 后缺失或无效报告是 `attention_required`，不是静默成功。`work_report` 不等待或重试。Bridge 在 latch 后、最终分类前探测专用报告一次：只有 `WorkReportMissing` 可再检查最多两次，约每秒一次，增加等待不超过五秒。可读报告加 `agent_turn_settled` 分类为 `result_ready`。这只证明 artifact 存在，不是任务成功。Artifact 是 Agent 编写的证据，不是任务验收或供应商 transcript。

发布后缀计入已有 16384-character task cap：接近上限的任务可能满足原 task bound，却在 prompt 前因必需报告准备失败而返回 `WorkReportPreparationFailed`。Bridge 不静默截断任务或扩大上限。委派发送的是调用者 task 加报告发布指令。Work/report retention 仍是 process-local；未增加 restart recovery 或 automatic retry。

</details>


<a id="original-file-attachments"></a>
## 原文件附件

需要**原文件**，包括无法作为文本读取的 PDF/DOCX 时，使用本节。
指定一个已授权文件，请求 `prepare_file_attachment`。

**应看到：** 临时获取链接，必要时还有按序分片回执。
“准备好”不等于上传、导入 ChatGPT 或成为附件。
**不超过 7 MiB** 使用一个链接；更大原件需要接收方获取、按回执顺序拼接，
核对完整大小/SHA-256。Bridge 没有自动网页组装器。
缺片、过期或内容变化时，应说明原件未核验，不把部分文件当成完整原件。
[实际获取指南](OBSERVATION-TOOLS.zh-CN.md)说明用户检查。
<details>
<summary>进阶：准确契约与实现限制</summary>

`prepare_file_attachment` 对最多 **7 MiB（7,340,032 bytes）**文件准确返回一个保留原 basename/MIME 的 ResourceLink，不带 TextContent metadata。更大文件返回有序 ResourceLinks，随后准确一个紧凑 JSON TextContent receipt：
`{"multipart":{"target":"original.bin","size":14680064,"sha256":"<full SHA-256>","parts":["<part 1 name>","<part 2 name>"]}}`。
Receipt 仅含 original basename、完整字节数、完整 SHA-256 和有序 materialized part names。TTL、retention、status、provenance 是内部信息，不出现在成功工具结果中。不新增 outputSchema、structuredContent、widget、blob/base64 或隐藏正文。

每 part 最多 7 MiB，使用 application/octet-stream，具有准确 raw size。名称为 `<shortened-basename>.bridge-<fullsha12>-part-0001-of-000N`，上限 255 UTF-8 bytes，不截断字符。小文件 URI 保持 `bridge://attach/{capability}`；multipart 为 `bridge://attach/{capability}/part/0001`。序号从 0001 开始，至少四个 ASCII digits（9999 后为 10000）；拒绝额外前导零。没有 ordinal 的 multipart group，或带 part ordinal 的 single file，均 fail closed。`export_file` 和 `bridge://export/` 仍已退役。

源码 part cap 为 **7 MiB**。假设序列化响应预算 **10,485,760 bytes（10 MiB）**，完整 part 的 base64 约 **9.33 MiB**（9,786,712 bytes），为 JSON/protocol overhead 留约 **0.67 MiB**。计算不是官方 raw-file 限制或已验收 relay 配置。应验证实际 client/relay 预算和 overhead：预算更小或 protocol envelope 更大仍可能拒绝 part。

任意的 **128 MiB** 原文件上限和 **128-entry** 附件数量上限/eviction 已移除。每个 binary resources/read 仍是单个 base64 response；MCP 没有为这一路径提供标准 streaming/range/reassembly。Bridge 使用有界内部 range reader。实际 observation deadlines 和 transport capacity 仍适用；去掉逻辑 size cap 不保证任意大 preparation/result 都能满足边界。

接收方利用 receipt part names 定位 host-materialized 文件，按顺序拼接为 original basename，验证完整 SHA-256 和 size 后才能认为收到原文件。Bridge 不增加自动 Web assembler 或 post-materialization hook。Preparation 与各 part fetch 成功不认证 host import 或 File Library presence。`readOnlyHint=true` 描述 filesystem observation；`idempotentHint=false` 表示生成新 opaque token。Bridge 不执行 upload。

</details>


<a id="resource-fetch-validation-and-wire-tests"></a>
<a id="resource-fetch-验证与-wire-测试"></a>
### 进阶：附件验证与传输测试

**开发者细节。** 下方解释准备后的临时链接为什么可能被拒绝，
不证明宿主已经导入原件。即使每片都获取成功，仍要核对最终原件完整指纹和大小。
保留失败事实，不绕过过期或变化的目标。
<details>
<summary>进阶：准确契约与实现限制</summary>

内部 PendingAttachments lookup 每个 original 保存一个 frozen metadata entry，不受 part count 影响；具有有限 expiry/GC（目前 15 分钟），读取不续期，重启不持久。不保留文件字节。Entry 绑定 project/Work/path/target key、full SHA/size、原 name/MIME、file stat、parent-directory identities，以及不可变 part index/offset/length/SHA。

Preparation 以有界读取流式扫描一次，同时计算 full 与每 part hashes。可选 expected_sha256 仍 pin 完整文件。Fetch 重新解析同一注册 project/frozen Work，使用 reader admission 和 no-follow 常规文件 descriptor walking，仅读取请求 part。核对保存的 device/inode/mode/link count/size/mtime/ctime 和 parent identities、读取前后 descriptor/stat/path binding、准确 part length/hash，并在观察后再次核对 lookup identity/expiry。

Traversal、symlinks、特殊文件、路径改变，以及 unknown/expired/wrong/noncanonical tokens 均不返回字节（-32602）。任何位置的普通变更会令后续 fetch 无效；恢复 mtime 也不够，因为同时检查 ctime。这些观察不是原子 snapshot：若 identity、size 和观察到的 timestamps 均被伪造，请求 part 外的编辑可能逃过该次 fetch 检查。最终完整文件 SHA 验证才是端到端检查。不新增格式解析。

MCP 2.0.0 template 有固定 MIME hint；窄范围 MCPServer.read_resource override 将 bridge://attach/ 路由到每次响应的 ReadResourceContents。Single-file fetch 保留原 MIME；multipart fetch 使用 application/octet-stream。两种 discovery templates 均声明 generic binary hint；其他 routes 使用 SDK。

默认 MCP memory transport 测试保留真实 7 MiB、7 MiB+1 物理边界、较小的真实 two-part 和 frozen-Work three-part roundtrips（使用 test-local part cap）、ordered raw bytes/full SHA、准确 wire shapes、有界读取与不保留正文。默认 metadata-seeded 128/129/130-entry 测试跨越真实 store count 边界，同时仍通过 MCP wire 准备和读取；原始 129-preparation wire sequence 保留为 opt-in stress。

完整 14 MiB/two-part 与 21 MiB/three-part wire roundtrips 仍在 maintainer lane。轻量 regressions 也覆盖：fake hashing 的 >128 MiB preparation 加真实 lower-layer open/early-EOF 检查，9999 以上 canonical ordinals，以及 5 MiB 和 417,431-byte Work/non-ASCII cases。

7 MiB raw part cap 为 base64 和 protocol overhead 留空间，但不保证任意 relay/host 都接受；需验证实际环境 response limits 与 file import 行为。ResourceLinks 准备原始字节，不证明 host materialization、approval behavior 或自动 attachment。接收方应按顺序拼接 parts 并验证完整 original size 和 SHA-256。

</details>


<a id="passive-catalog-diagnostics"></a>
<a id="被动目录诊断"></a>
## 进阶：工具目录诊断

**仅用于诊断：** 服务日志显示建立了工具目录，不证明 ChatGPT 收到它。
应在实际目标对话检查目录。只读提示的数量不是工具总数。
<details>
<summary>进阶：准确契约与实现限制</summary>

被动 `bridge.catalog_listing` INFO events 仅描述 handler catalog construction，不代表 client receipt。`read_only_count` 统计显式 True hints，不是工具总数。实现仍可用；不因此产生专门 observation task。

</details>


<a id="linked-checkouts-and-user-preplaced-agents"></a>
<a id="linked-checkouts-与用户预先放置的-agents"></a>
## 在关联工作目录中使用 Agents

关联工作目录（linked checkout）是同一 Git 仓库的另一个工作文件夹。
使用它时，自己选择并在那里启动已授权 Agent，再核对观察到的目标。
Bridge 不创建/移动目录，不启动或重新绑定 Agent；共享目录不是操作系统隔离。
<details>
<summary>进阶：准确契约与实现限制</summary>

Same-common-Git linked checkouts 是可选写入域，不是永久角色或 OS 隔离。Placement 在 launch 前完成；Bridge 没有公开 Agent-create/launch 或 worktree-create 工具，也不在 delegate 期间 rebind 已有 Agent。用户在了解 provider/model quota 可用性的前提下选择并启动实际 coding Agent；随后 discovery/delegation 面向选定项目中的该已有 resource。

明确选择目标 checkout 和 Agent。源码支持 linked checkouts，不授权移动已有 Agents，也不证明 live UI 行为。

</details>


<a id="verification-and-deployment-boundaries"></a>
<a id="验证与部署边界"></a>
## 进阶：源码测试与部署边界

**仅供维护者，不是安装步骤。** 源码测试检查测试场景，不验证当前 ChatGPT 配置。
在已授权开发检出目录使用下方原有命令前，先审阅源码和测试范围。
测试不授权部署、重启服务或向 Agent 输入；失败/不完整检查必须如实报告，不能当作实机验收。
<details>
<summary>进阶：准确契约与实现限制</summary>

按 [Quickstart](QUICKSTART.zh-CN.md#2-clone-and-install-direct-dependencies) 用 `pip install -e .` 把 package 安装到本 checkout 的 `.venv`。运行相关 tests，再运行剩余 full suite 和 diff 检查：

```sh
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m unittest discover -s tests -q
# Full-scale retention stress (opt-in maintainer lane):
BRIDGE_MAINTAINER_SUITE=1 ./.venv/bin/python -m unittest tests.test_work_retention.WorkRetentionTests.test_600_real_delegations_receipt_window_and_no_read_renewal -q
# Full-scale candidate and preparation stress (opt-in maintainer lane):
BRIDGE_MAINTAINER_SUITE=1 ./.venv/bin/python -m unittest tests.test_commit_candidate.CommitCandidateTests.test_unrelated_history_is_not_walked_and_unrelated_hooks_are_not_read tests.test_commit_prepare.CommitPrepareTests.test_query_count_stays_constant_through_2048_path_complexity_ceiling -q
# Full-size binary/patch and multipart/wire stress (opt-in maintainer lane):
BRIDGE_MAINTAINER_SUITE=1 ./.venv/bin/python -m unittest \
  tests.test_commit_candidate.CommitCandidateTests.test_large_binary_set_summary_patch_and_exact_commit \
  tests.test_commit_candidate.CommitCandidateTests.test_single_large_binary_file_is_previewed_and_committed \
  tests.test_commit_candidate.CommitCandidateTests.test_huge_text_patch_is_truncated_not_refused \
  tests.test_commit_candidate.CommitCandidateTests.test_many_files_aggregate_patch_truncation_and_bounded_creation \
  tests.test_file_attachment.FileAttachmentTests.test_fourteen_mib_two_part_memory_roundtrip \
  tests.test_file_attachment.FileAttachmentTests.test_twenty_one_mib_three_part_work_memory_roundtrip \
  tests.test_file_attachment.FileAttachmentTests.test_over_128_attachments_remain_readable_until_expiry_and_restart -q
git diff --check
```

默认套件在 512/513 边界保留小规模真实 retention sequence；完整 600-delegation loop 仅在上述 maintainer lane 运行。

两个 lanes 的 candidate tests 都使用真实临时 Git repositories。默认 history case 创建 8 个无关 loose objects、3 个 refs，禁止 repository directory enumeration 及读取无关 hook 正文，核验 preview 和准确 commit 且不执行 hook。保留原名称的 maintainer case 仍有 20,010 objects、300 refs，用于防止遍历整个 repository 的限制。

Preparation 默认检查 1 和 36 个真实 paths；保留原名称的 maintainer case 检查 1、36、256 和 `MAX_SELECTED_PATHS`（2,048），用于守住 complexity ceiling。两种 preparation lanes 都核对每项结果的 status、total、准确 path set、准确一次 `hash-object`，及低于 96 的固定 event count。默认套件还保留廉价的 2,049-path refusal、36-file exact bytes/mode/index，以及 hook、filter、frozen Git safety coverage。这些 fixture tests 不证明 live service 或已部署行为。

适用时将修改后的 Python 编译到临时目录。保留用户已有工作。测试通过不自动授权 commit、push、restart、deployment 或向其他 Agent 输入。Source registration、running process 和 client-bound schemas 是不同证据；暂时看见工具不等于完整 binding inventory。

</details>


<a id="optional-system-service-adoption"></a>
<a id="可选-system-service-adoption"></a>
## 进阶：接管已运行的 Bridge 服务

**仅供进阶操作者。** 已完成 `./prepare` 时，两个服务已经安装、启用并启动，
不要再运行另一个安装器；状态/恢复见 [Autostart](AUTOSTART.zh-CN.md)。

考虑提权命令前，先审阅[旧接管脚本](../scripts/install-bridge-system-service.sh)。
它是另一条需单独授权的路线，要求准确检出目录已有运行中进程。
与准备程序不同，它**不启用或启动**接管的单元，不能与双服务安装混用。
缺少进程或身份不支持时停止，不要强行执行提权命令。
原生 Ubuntu 无需 WSL anchor；这个可选 Windows 助手只保持选定 WSL 系统运行。
<details>
<summary>进阶：准确契约与实现限制</summary>

全新双独立服务安装使用 [Bridge + Secure MCP Tunnel autostart](AUTOSTART.zh-CN.md)。可选单 owner WSL anchor 保持 distro 运行，让 systemd 启动 enabled units。Herdr 和 Agents 仍手动启动，不恢复 Work 或 session。不将其 units 与此处 adopter 混用。

`scripts/` 包含可移植 service installer、environment allowlist library 和 tunnel TTL staging tool；`systemd/gpt-agent-bridge.service.template` 在安装时按所选用户和 checkout 渲染。机器路径、用户和代理由 installer inputs 提供。

仅在已有 Bridge process 为此 checkout 运行后，才可选用 `sudo scripts/install-bridge-system-service.sh --user USER --repo /path/to/gpt-agent-bridge [--proxy URL]` 安装 system service。Adopter 要求 package 以 editable 方式安装在本 checkout 的 `.venv`，并从此 checkout 准确运行 `/absolute/checkout/.venv/bin/python -m gpt_agent_bridge`。拒绝 root `server.py` launch、console entrypoints、flags 或额外 arguments；identity checks 无法认证已载入代码。

Installer 对运行中 Bridge 采取 fail-closed adoption，暂存私有 environment file、安装并验证 unit，但绝不启动或启用；启动服务仍是 operator 的显式动作。没有运行中 process 的干净 clone 不能靠它 bootstrap。

</details>


<a id="migration-risks"></a>
<a id="迁移风险"></a>
## 更改已有安装之前

修改源码不会更新运行中的应用。计划迁移前，分别检查当前安装包、进程、服务和连接，
保留已有身份与私有凭据，并取得明确切换授权。
停止 Bridge 会丢失进程内 Work/续接状态；重启不会恢复任务或授权重放。
本地健康也不证明网页验收。
<details>
<summary>进阶：准确契约与实现限制</summary>

磁盘 checkout 改动不迁移已安装 package、running process、service definition 或 ChatGPT connection。src layout 删除了 root module entrypoints：未来用 `server.py` 重启会失败。在另行授权 cutover 前，准备并验证目标 checkout 的 editable install 和 module origin。保留已有 capability token、App binding 和必需 transport configuration；两个 autostart installers 都不导入 live environment，也不支持自动 takeover。

首次安装服务拒绝被占端口、foreign units/drop-ins 和未知 partial installation。其 minimal environment 可能不适合已有 proxy/CA/mTLS 部署；迁移前停止并审查差异。停止 Bridge 会丢失 process-local Work、references 和 continuation state；重启不恢复 Agents，也不授权重放。Rollback 必须同时考虑 code、package 和 service configuration。

本地 initialized Bridge health 与 Tunnel readiness 不证明远程 ChatGPT 验收。Linux reboot、Windows login/no-window/lifetime 和新用户 endpoint 仍需独立 target-host 验收；这不否定已有 WSL 使用报告。

</details>


<a id="web-principal-layers"></a>
## Web Principal 层次

Web Principal 把 ChatGPT 网页、已保存项目指令、Bridge 工具/Skills
和你已有的 Herdr Agents 结合起来。它不是另一模型、供应商或一键托管应用。

提供的[完整 Core 文本](../templates/WEB-PRINCIPAL-CORE.md)引导判断和行为。
你要手动保存到项目指令，另行审阅识别本地项目的 Binding。
读取或发布源码文件不认证实时设置，不同步设置，也不完成全新安装。


<a id="what-the-principal-owns"></a>
### Principal 负责什么

Principal 帮你界定真正的问题、质疑假设、检查缺失证据、比较选择并综合判断。
委派 Agent 服务于这些思考，单纯汇报状态不算完成。

目标、范围、关键取舍和授权由你保留。已授权任务内，有用的可逆工作应持续推进，
不重复索取相同许可。遇到新的关键选择或权限边界，应带具体证据和建议交回你决定。


<a id="four-different-layers"></a>
### 四个不同层次

| 部分 | 放什么内容 | 不授予什么 |
| --- | --- | --- |
| 项目指令中的 **Core + 独立 Binding** | 如何思考/工作、你授权哪些项目 | 工具访问、认证所有权或执行隔离 |
| **四个原生 Skills** | 对应场景的可复用流程 | 角色、新任务权限或异步协议保证 |
| **工具 schemas/descriptors** | 实际参数、效果、限制与续读规则 | 使用所有操作的许可 |
| **本地规则、状态和记忆** | 项目特定决策、原因与恢复上下文 | 全局记忆、自动授权或实时运行状态 |

“Schema”是接受的参数结构，“descriptor”是工具说明。
本地 **manifest（清单）**指出项目笔记分别存在哪些文件，
独立于四个[可复用流程](#native-skills-and-app-binding)。
Core 不安装软件、连接 App 或发现 Skills。
按[入门指南](GETTING-STARTED.zh-CN.md)手动安装并审阅 Binding。
可复用 Core/Binding 中不要加入凭据或私有认知资料。
注册可返回 Binding 补充，但不保存 Instructions 或初始化文件。


<a id="delegation-reports-and-verification"></a>
### 委派、报告与验证

可请求：“读完报告，指出没有支持证据的主张，只核查我授权的证据。”
独立调查应改善判断，而不只是复述 Agent 结论。

按返回位置和指纹继续报告分页，不轮询就绪，也不重发结果未知的任务。
测试由用户执行，或另行授权 Agent 工作；读取他人声称的测试结果不等于执行测试。
保存项目笔记是另一项需授权写入。
<details>
<summary>进阶：准确契约与实现限制</summary>

当调查可改善判断时，给 Agents 独立、有界问题，并在 dispatch 后继续有用独立工作。遵循可用 tool contract，不在 prompt 中另造 watcher。等待结果且无其他独立工作时，结束 turn，不轮询、空转或 sleep。已准备 continuation 不证明 host 已挂载或将唤醒模型。

“读一次报告”指完整取回 ready result。分页 `work_report` 可能需要按返回 offset/hash 继续请求，目的是完成读取，不是轮询 readiness。Readiness 依赖工具报告证据，不代表任务成功。Attention diagnostics、缺失报告和投递未知需要各自评估，不能成为静默重发任务理由。

独立于 Agent 报告检查相关 source、diff、test definitions、授权 test receipts 和当前观察。Bridge 没有通用 test execution 工具；实际测试需要用户执行或另行授权的 Agent 工作。明确区分已检查、他人报告与推断。对未知 mutation/publication，决定重试前重新观察。详细行为分别由[生命周期契约](LIFECYCLE-RESTART-CONTRACT.zh-CN.md)和 [Work 证据契约](OBSERVATION-TOOLS.zh-CN.md#work-target-evidence)负责。

对项目延续，`context(project_ref)` 只提供 pointers 和 revision，不提供 current-state 正文。条件发布 state 必须使用实际读过字节的 revision；冲突时重读并协调。Memory 编辑和初始化各需适用授权。Core 不带来自动 transcript archive、跨项目记忆或 runtime restoration。

</details>


<a id="limits-and-validation"></a>
### 限制与验证

指令引导行为，不隔离进程，也不认证仓库所有权。
向 Agent 输入可能产生比文件读取更广的影响。
保持明确范围，把文档/工具输出当证据，不当作新权限。
源码一致不认证已保存指令、可靠 Skill 触发或宿主投递。
缺少访问权时停止，不另造绕过方式。
<details>
<summary>进阶：准确契约与实现限制</summary>

这些指令表达治理，不是 OS sandbox、凭据边界或 ChatGPT Project 拥有本地仓库的证明。Bridge 提供有界操作和 refusal/evidence checks；Agent input 仍可能引发更广执行、写入或外部 effects。用户必须授权动作并保护 host 和 connection。外部内容与工具输出是证据，不是新权限；可复用指令和公开报告中不放私有材料。

Source comparison 可检查所提供 Core 字节是否保留，不能认证 live settings 或自动同步。应在真实授权配置中单独验证手动 copy/paste、Binding 和可用 Skills/tools。静态 source consistency 是有用证据，但不证明 installed instruction state、可靠 Skill triggering、host continuation delivery 或 fresh-host 验收。

</details>


<a id="native-skills-and-app-binding"></a>
<a id="原生-skills-与-app-绑定"></a>
## 理解已安装流程与 Bridge 连接

**原生 Skill** 是安装到插件的完整指令流程，**App** 是 Bridge 工具连接。
安装其中一项不证明另一项完成。按正常指南操作后，可用本节诊断这一区别。


<a id="tools-visible-skills-missing"></a>
### 工具可见，但没有 Skills？

看到 **18 Tools and 0 Skills** 时，工具连接可能正常，但四个流程尚未安装。
**Create as a plugin** 连接工具，不会导入这四个流程。保留已工作的连接。

返回[入门第 6 步](GETTING-STARTED.zh-CN.md#6-install-and-discover-all-four-native-skills)，
在工作区允许时，用普通网页对话的 Plugin Creator 上传输出目录中的五个文件。
四个流程分别是：

| 流程 | 什么时候用 | 准备后的文件 |
| --- | --- | --- |
| [project-onboarding](../skills/project-onboarding/SKILL.md) | 连接已有仓库；仅在另行请求时初始化笔记 | `project-onboarding.md` |
| [project-resume](../skills/project-resume/SKILL.md) | 恢复已保存决策，重查相关实时事实 | `project-resume.md` |
| [handoff-preparation](../skills/handoff-preparation/SKILL.md) | 向合适本地笔记保存影响决策的交接 | `handoff-preparation.md` |
| [team-deliberation](../skills/team-deliberation/SKILL.md) | 独立视角可能改变判断时，协调多方调查 | `team-deliberation.md` |

第五个文件是 `LICENSE`。它们是指令文件，不是四个新本地 Agents 或额外 MCP 工具。
列表有 Skill 名称不证明完整正文已安装，也不保证可靠自动触发。
<details>
<summary>进阶：包布局、职责与退役 Methods</summary>

如果只创建 custom MCP connection，**18 Tools and 0 Skills** 符合 tools-only 连接状态。**Create as a plugin** 注册的是连接，不是四个源流程。[SOURCE 目录](#tool-reference)有 18 个面向模型工具（没有仅 App 使用的 widget continuation tools）；下方 Skills 不是额外 MCP 工具。

已有工作中 Web 连接时，从[入门第 6 步](GETTING-STARTED.zh-CN.md#6-install-and-discover-all-four-native-skills)开始。复用已有允许的 App；canonical Skill 正文与 Core 分开。源码打包或其他 host 的验收不证明目标 Web Project Chat 已安装。

仓库 root 是 canonical Bridge Plugin package source：`plugin.json` 使用 portable Agent Plugins manifest schema，`skills/<name>/SKILL.md` 提供四个分别触发的可复用流程。它们与 MCP integration 同属 GPT-Agent Bridge plugin。

| Skill 与 canonical 源文件（均未翻译） | 流程 | 准备后的附件名 |
| --- | --- | --- |
| [project-resume](../skills/project-resume/SKILL.md) | 恢复路由的当前判断，选择性重验 live facts | `project-resume.md` |
| [handoff-preparation](../skills/handoff-preparation/SKILL.md) | 只向合适本地层发布影响决策的 continuity delta | `handoff-preparation.md` |
| [project-onboarding](../skills/project-onboarding/SKILL.md) | 连接已有仓库，并在请求时建立真正全新的延续种子 | `project-onboarding.md` |
| [team-deliberation](../skills/team-deliberation/SKILL.md) | 当独立视角可改变关键判断时采用它们 | `team-deliberation.md` |

Project Instructions 保留权限与项目选择。本地 versionless manifest、state、memory、rules 仍是项目持久 cognition。Plugin Skills 拥有可复用 workflow prose；tool descriptors 拥有 capability/continuation 契约。Skills 不含 async watch/delegate sequencing rules；Skill activation 不分配角色。

Principal Methods 已退役。本地 route wrappers 已删除，continuity manifests 和 initialization seeds 拒绝 `methods`，即使为空或 null。Canonical 可复用流程只在 `skills/`，不提供 forwarding stubs 或替代 manifest routes。项目决策、原因和规则仍由本地 owners 负责。源码退役不会更新已安装 Skill 文本，也不认证自动触发可靠性。

</details>


<a id="attachment-and-discovery-diagnostics"></a>
### 附件与发现诊断

**在电脑上**，打开准备程序输出准确位置的 `Creator-attachments`。
使用四个分别具名的 `.md` 文件和 `LICENSE`，
不要另下载四个都叫 `SKILL.md` 的文件。
文件开头的 `name`、`description` 设置和完整正文必须保持不变。

**在 ChatGPT 网页**，等五个上传附件全部可见，再请 Creator 复用已有 Bridge 连接，
审阅四份完整已安装正文。[第 6 步](GETTING-STARTED.zh-CN.md#6-install-and-discover-all-four-native-skills)
提供点击和 Ubuntu/Windows 文件选择器路线。

**成功标志：** 新普通项目对话可见四份完整文本和真实 `bridge_health` 结果。
**受阻状态：** 保留连接，记录“tools working; Skills unverified”，
解决账号/安装访问问题，不重建 Tunnel、重建密钥或派任务来强迫发现。
简短列表、四个蓝色开关或 Work/Codex 测试，都不证明普通网页验收或自动触发。
<details>
<summary>进阶：准确附件与发现诊断</summary>

准备交接在 `Creator-attachments/` 提供四个名称唯一的副本。保留每个 canonical 文件的完整字节和 `name`、`description` frontmatter。仅重命名私有附件副本，不改 canonical Skill 文件夹/文件。Source URL 不证明正文已导入。若附件名称仍冲突，提供四份完整、各自标注的文本，确认每份到达且无截断。它们是输入，不是原生安装证据；不包含私有 cognition 或秘密。

在预期普通 Web Project Chat 中，分别检查**四个完整已安装原生 Skill 正文**和真实 **`bridge_health()` 结果**。单靠 health 不证明 Skill discovery；已安装 procedures 不证明 MCP connectivity。缩短的 per-turn listing 或四名称摘要不够：明确发现正文并与 canonical inputs 对照。

Tools 可用但 Skills 缺失时，保留工作中的 App/Tunnel，排查 native packaging 或 workspace permissions。不要重建凭据或发 task 强迫发现。记录 **tools working; Skills unverified**；只有 Core 指令另行核验后才加上 Core。Work/Codex 验收不确立普通 Web 可用性或自动 Skill triggering。

</details>


<a id="public-package-configuration"></a>
<a id="公开-package-配置"></a>
### 进阶：公开插件包布局

**仅供开发者。** [plugin.json](../plugin.json) 的 App 扩展指向
[root .app.json](../.app.json)。安全的公开示例
[.app.example.json](../.app.example.json)展示别名 `bridge`、`required: true`
和无效占位符 `asdk_app_REPLACE_WITH_OWN_APP_ID`。
示例不是可用连接。不要上传或公开真实私有 App 绑定；
普通用户在 Creator 中选择已有连接。

<details>
<summary>进阶：生成器输入与源码打包证据边界</summary>

仅供开发者实验的可选本地打包见[打包章节](#private-native-plugin-packaging)：[prepare-personal-plugin.py](../scripts/prepare-personal-plugin.py)将 public manifest、现有 LICENSE 和全部四个 Skill 文本复制进独立的 eight-file marketplace。Generator 从不读取 source App binding，也不安装 host plugin。只接受已验证 native App reference（`asdk_app_`、`connector_` 或 `templated_apps_`）；不转换浏览器 `plugin_asdk_app...` identifiers。Root placeholders 保持不变。在独立配置中使用自己注册的 App ID。Package 不添加 endpoint、credential、runtime Skill handler 或 marketplace configuration。

Source bundle 和 tests 证明 file layout 与 mapping shape，不证明 plugin distribution service 接受、App connection 可用、installed Skill discovery、automatic trigger reliability 或 fresh-chat usefulness。安装/分发前另查 host 当前 packaging requirements。源码测试不自动授权安装或发布。

Skills 独立于 project-local cognition。公开包不含实际项目 `.principal/` 目录。安装不接入项目、不启动服务/Agents、不授予任务权限。首次使用只走[入门指南](GETTING-STARTED.zh-CN.md)。

</details>


<a id="private-native-plugin-packaging"></a>
<a id="私有原生插件打包"></a>
## 网页插件配置与可选开发者打包

**全部 18 个工具和四个原生 Skills** 的支持目标是普通 **ChatGPT 网页项目对话**。
先走下面的正常路线。之后的开发者生成器属于可选实验打包，
不是必需安装步骤，也不能用来证明网页接受。


<a id="ordinary-web-project-chat-setup"></a>
### 普通 Web Project Chat 配置

1. 在普通 ChatGPT 网页，仅当目标工作区提供创建/编辑且你有权限时使用 Plugin Creator。
2. 复用**已有、私有且已授权的 Bridge 连接**，出现菜单时按名称选择。
   不猜测/转换 ID，不创建新凭据。
3. 上传准备程序生成的四份完整具名流程文件和 `LICENSE`，保留完整指令与设置。
4. 审阅四个独立完整 Skill 正文和选中的已有连接，只使用实际提供的完成/保存/安装控件。
5. 在**预期项目的新普通对话**检查真实成功的 `bridge_health()` 结果、
   [18 工具目录](#tool-reference)和四份完整已安装 Skill 正文，不执行这些流程。

可用下方[目标对话检查](#target-chat-skill-verification)单独核验。
准确的点击/上传路线见[入门第 6 步](GETTING-STARTED.zh-CN.md#6-install-and-discover-all-four-native-skills)。
控件或发现不可用时，保留连接，记录 **tools working; Skills unverified**，
在账号问题处停止。[OpenAI 创建指南](https://learn.chatgpt.com/docs/build-plugins)
描述依赖权限的控件，不证明你的账号具备资格。

Work/Codex 成功不是网页验收。**支持范围不等于隔离：**
插件或 Skills 没有已记录的 `web_only` 强制机制。
面向 Web 的指令/安装不会从技术上阻止跨界面可见。
官方文档描述[共享插件目录和多个界面](https://learn.chatgpt.com/docs/plugins)；
配置不需要手动在本地阻止 Codex。


<a id="developer-only-experimental-packaging"></a>
### 仅供开发者实验的打包

**仅供开发者，正常网页配置跳过。**
生成器只制作本地实验包，不安装到 ChatGPT Web。
必须使用已验证合格的原生 App 引用；浏览器 URL 或 Chrome 扩展 ID 不能转换成它。
不要用此路线绕过工作区限制。
<details>
<summary>进阶：未改动的开发者要求与示例</summary>

下方可选 generator 只供开发者使用已验证合格的 native App 和兼容的 local marketplace surface 进行打包实验。它不是普通用户安装路径，也不会把 Skills 安装进 Web Chat。浏览器 `plugin_asdk_app_` 表示不是 native `.app.json` ID；不裁掉 prefix 或根据字符串推断资格。Chrome extension ID 是完全不同的身份。

[共享 native ID check](https://developers.openai.com/plugins/deploy/submission-errors#mcp-server-reference-errors)允许 `asdk_app_`、`connector_` 或 `templated_apps_`，随后一个 ASCII 字母/数字，再跟 ASCII 字母/数字/下划线/连字符。允许大写和不同 suffix 长度。Generator 另加**本地总长 256-character 限制**，拒绝已知 public placeholder、browser IDs、URLs、whitespace、non-ASCII 和 controls。准确保留输入；没有 browser-to-native 转换。只有 browser URL 时，返回入门第 6 步的 Creator 路径，让 host 选择已有 App。

</details>


<a id="use-a-reviewed-licensed-public-source"></a>
<a id="使用经评审且带许可证的公开源"></a>
### 进阶：生成包前先审阅源码

**开发者实验，不是新手命令。**
先审阅链接的生成器、公开源和已有 LICENSE，
再在 Linux 终端（原生 Ubuntu 或选定 WSL Linux 系统）使用下方未改动示例。
命令只生成私有包，不安装也不证明网页接受。
源/许可证缺失、目标不安全或发布结果未知时停止。
<details>
<summary>进阶：未改动的开发者要求与示例</summary>

在 Linux/WSL 使用 Python 3.10+，先审阅 [generator](../scripts/prepare-personal-plugin.py)。Inputs 必须来自可信的**公开 source checkout，带已有 root LICENSE**、plugin.json 和四个 canonical Skills。经评审 public distribution 含 MIT notice 和 attribution；generator 复制准确 notice，不决定许可或生成 copyright text。

内部开发 checkout 没有 root LICENSE，因此默认 source 会 fail closed。不要在那里创建许可证来绕过检查。使用包含 generator 的经评审 public clone，或把已评审脚本明确指向该 public source。Public clone 若缺脚本，说明本地候选尚未进入其中，不要假定命令可用。

在含脚本的 public clone 中：

```bash
python3 scripts/prepare-personal-plugin.py \
  --marketplace-root "$HOME/bridge-personal-marketplace"
```

从其他位置运行已评审脚本时，明确选择经评审且带 LICENSE 的 public source（将 source path 改为实际 clone）：

```bash
python3 scripts/prepare-personal-plugin.py \
  --source "$HOME/gpt-agent-bridge-public" \
  --marketplace-root "$HOME/bridge-personal-marketplace"
```

在 source 外选择全新绝对 output directory。Parent 必须已存在、属于你，且 group/others 不可写。Paths 不含 symlinks 或 traversal。拒绝已有目标，包括空目录和 broken links；不合并或覆盖现有 marketplace。

Hidden prompt 只输入已验证 native App ID，不输入 API key、password、Tunnel ID 或 token URL。ID 不放在 arguments、shell history、public reports、screenshots 或 Project Instructions 中。拒绝 input echo fallback；ID 仅出现在生成的私有 `.app.json`。

非交互时，`--id-file /absolute/private/id-file` 接受一行准确 UTF-8 ID，可带末尾 LF。文件属于你，mode 为 0600 或 0400，无 symlink/hard link。仍适用总长 256-character ID 限制。用私有编辑器自行准备；generator 不写也不删该输入。绝不把真实 source `.app.json` 当输入文件。

</details>


<a id="exact-eight-file-result"></a>
<a id="准确八文件结果"></a>
### 进阶：检查生成的八文件包

生成成功应有下方准确八个文件，包括复制的许可证和完整 Skills，
但仍只是磁盘上的包，不是已安装插件。私下审阅。
持久性警告或意外遗留目录需要检查，不应覆盖或整体递归清理。
<details>
<summary>进阶：未改动的开发者要求与示例</summary>

```text
bridge-personal-marketplace/
├── .agents/plugins/marketplace.json
└── plugins/gpt-agent-bridge/
    ├── plugin.json
    ├── LICENSE
    ├── .app.json
    └── skills/
        ├── project-resume/SKILL.md
        ├── handoff-preparation/SKILL.md
        ├── project-onboarding/SKILL.md
        └── team-deliberation/SKILL.md
```

Manifest、LICENSE、四个 Skills 是 source bytes 的准确副本。LICENSE 缺失、为空、invalid UTF-8、不安全或在变化会停止发布；发布前再次对照 source snapshot 检查 notice。Generator 验证安全 notice text，不判断法律适用性；复制/分发前审阅 public source 实际许可。

生成 mapping 为 alias `bridge`、你的准确 native ID 和 `required: true`。Catalog 使用相对 marketplace root 的 `source.path="./plugins/gpt-agent-bridge"`，标为 AVAILABLE 和 ON_INSTALL authentication。保留 source version。不复制 hooks、compatibility overlay、runtime source、private docs、真实 source App binding 或 cognition。

在正常已测试 umask 下，directories 为 mode 0700，files 为 0600。私有临时 sibling 加 Linux `renameat2(RENAME_NOREPLACE)` 保证发布不 clobber 并发目标；不支持的环境 fail closed，没有 overwrite fallback。Cleanup 只删本次创建且身份已确认对象。Unknown/replaced 内容或 crash 可遗留私有 `.bridge-plugin-pending-*` sibling；手动检查，不做整体递归清理。Post-publication durability warning 要求重试前检查。这些检查不隔离恶意同用户进程。

</details>


<a id="explicit-host-installation"></a>
<a id="显式-host-安装"></a>
### 进阶：宿主安装是独立操作

生成不会安装到宿主。开发者安装实验需要另行授权和当前宿主说明。
普通用户回到[网页配置](#ordinary-web-project-chat-setup)，
路线中不包含 Work/Codex marketplace 安装。
政策阻止访问时，按工作区权限流程处理，不编辑缓存或配置绕过。
<details>
<summary>进阶：未改动的开发者要求与示例</summary>

生成不会安装 host plugin 或更改 host configuration。审阅实验包，对照 source 的 notice/Skills；开发者若要进行 host 安装实验，需要单独授权和当前 host 专用说明。这不确立普通 Web Project Chat 验收。普通用户遵循上方 [Web Chat 配置](#ordinary-web-project-chat-setup)，无需 Work/Codex marketplace 安装。

Account/workspace policy 可阻止创建、安装或 App access。不要编辑 host caches、global config、admin settings 或其他 marketplace 来绕过。Sharing/publication 需要单独 review 和 authority。

</details>


<a id="target-chat-skill-verification"></a>
<a id="目标-chat-skill-验证"></a>
## 在目标网页对话验证工具与流程

使用**预期 ChatGPT 项目中的新普通网页对话**，
通过实际界面选择得到的 Bridge 插件。
请求列出 18 个 Bridge 工具、展示四个完整已安装 Skill 正文而不执行，
并仅调用 `bridge_health`。

**只根据实际结果通过检查。** 四个名称或文字断言不够。
按返回内容检查 `herdr.status`；Herdr 关闭/不可用属于另一个 Agent 就绪问题，
不应只为检查网页连通而启动 Agent。
发现成功不证明自动 Skill 选择、可靠触发、项目延续或未来宿主投递。

失败时保留工作中的 App/Tunnel，解决准确的账号、目录或完整正文缺口。
Work/Codex 结果不能替代。下方提供详细检查提示。

<details>
<summary>详细只读检查提示（英文原文）</summary>

```text
Read-only check: inspect this chat's Bridge MCP tool catalog and compare
all 18 tools with the documented Tool reference. Do not invoke write tools.
Explicitly discover this chat's installed Skill catalog.
Find project-onboarding, project-resume, handoff-preparation and
team-deliberation under my Bridge plugin and compare their complete texts
with the canonical attachments I reviewed. Do not invoke these procedures,
register/initialize a project, delegate Agent input or change any files.
Separately call bridge_health and inspect the returned herdr.status.
```

</details>

工具和 Skills 核验后，若 Core 尚未检查，先完成
[入门第 7 步](GETTING-STARTED.zh-CN.md#7-put-the-public-core-in-project-instructions)，
再按[第 8 步](GETTING-STARTED.zh-CN.md#8-connect-your-existing-git-repository-and-merge-its-binding)
连接授权项目，完成[小范围首次检查](GETTING-STARTED.zh-CN.md#10-begin-daily-use-with-a-bounded-read-only-check)。
注册、初始化、Agent 输入和项目延续各保留独立权限。


<a id="native-execution-retirement"></a>
<a id="原生-execution-退役"></a>
## 已退役命令工具与可用替代

旧指令要求调用 `run` 或 `view_image` 时，不要猜别名。
`run` 已退役；使用已记录的窄范围能力，或另行授权 Agent 工作。
`read` 才是原生图片路线。不完整观察不表示干净，
并发任务也不证明其他写入者已停止。
<details>
<summary>进阶：未改动的开发者要求与示例</summary>

Public `run` 已从 SOURCE 删除，没有隐藏 alias 或任意命令替代。其专用 native_execution module 与 tests 已在 consumer inspection 后删除。Source inspection 和 tests 只证明本地契约；runtime deployment 和 host acceptance 需独立证据。[工具参考](#tool-reference)列出保留能力；[观察契约](OBSERVATION-TOOLS.zh-CN.md)负责准确 evidence/version mechanics。

不同 Agent resources 可在同一共享 checkout 同时持有 in-flight Work；但同一 Agent handle/resource 的 nonterminal Work 或未消费 handoff 仍拒绝重复 prompt。Terminal settlement 不证明手动/detached writers 已停止。Shared gates 与 dispatch identity checks 保留，见[生命周期](LIFECYCLE-RESTART-CONTRACT.zh-CN.md)。

Fixed Git observations 保留有界 byte capture、timeout 和等待完成的 cancellation cleanup，不暴露调用者 argv。Spawn/nonzero failures 和 incomplete captures 不是 clean observations。tests/test_fixed_git_lifecycle.py 覆盖 inherited pipes、TERM-resistant descendants、repeated cancellation、escaped pipe holders。Escaped processes 和不可抢占 OS operations 使无条件端到端 bound 无法保证。Query limits 与不支持配置见[观察工具](OBSERVATION-TOOLS.zh-CN.md)。

Shared admission regressions 在 tests/test_checkout_admission.py；实际 MCP retirement 与保留 evidence calls 由 tests/test_run_retirement.py 覆盖。Source tests 不认证 runtime 验收；单独验证配置服务与 client。公开 source 不包含私有 execution receipts。

</details>


<a id="license"></a>
## 许可证

按 [MIT License（未翻译的许可证原文）](../LICENSE)发布。Copyright (c) 2026 tomoyo。
