<a id="technical-reference"></a>
# 技术参考

[English](TECHNICAL-REFERENCE.md) | [简体中文](TECHNICAL-REFERENCE.zh-CN.md)

本参考保留从产品首页移入的目录、契约、配置背景与验证材料。产品介绍见 [README](../README.zh-CN.md)；新用户只需遵循[入门指南](GETTING-STARTED.zh-CN.md)。各专门文档仍负责自身的详细契约。这里是源码文档，不是已部署 runtime 或 host 验收证据。

<a id="document-owners-and-audiences"></a>
## 文档 owner 与读者

| Owner | 读者与职责 |
| --- | --- |
| [README](../README.zh-CN.md) | 产品概览与入口导航 |
| [入门指南](GETTING-STARTED.zh-CN.md) | 唯一按时间顺序编排的新用户安装与首次使用路径 |
| [Quickstart](QUICKSTART.zh-CN.md) | 进阶/开发者前台配置、WSL、固定 Herdr 和可选演示 |
| [技术参考](TECHNICAL-REFERENCE.zh-CN.md) | 工具目录、Web Principal 层次、原生打包及进阶导航 |
| [项目延续](PROJECT-CONTINUITY.zh-CN.md) | Manifest 路由、state/memory 编写与条件发布 |
| [生命周期](LIFECYCLE-RESTART-CONTRACT.zh-CN.md) | 委派、容量、私有报告、通知、重启和未知结果 |
| [Autostart](AUTOSTART.zh-CN.md) | 所属 Bridge/Tunnel units、显式 operator gates 和可选 WSL anchor |
| [观察工具](OBSERVATION-TOOLS.zh-CN.md) | Work-target 证据、分页、原文件、有界编辑与 Git candidates |

[AGENTS（未翻译的机器规则）](../AGENTS.md)提供贡献者边界，不是产品手册或角色分配。[Core（未翻译的 canonical 指令）](../templates/WEB-PRINCIPAL-CORE.md)、四个 canonical Skills 和 continuity fixture 仍是拥有独立 owner 的机器/流程输入。公开树不含实际项目 cognition。安装 App 不会注册仓库、生成延续种子、启动 Agents 或赋予任务权限。

本参考内：[Web Principal 层次](#web-principal-layers)、[原生 Skills 与 App 绑定](#native-skills-and-app-binding)、[私有原生打包](#private-native-plugin-packaging)、[可选运行中服务 adoption](#optional-system-service-adoption)。

<a id="original-overview-and-setup-context"></a>
## 原始概览与配置背景

把 **ChatGPT Web 用作你机器上已运行 coding agents 的 Principal**。GPT-Agent Bridge 将 ChatGPT 连接到 Herdr 管理的本地 Agents，不替代它们的原生 CLI，也不强迫你换用另一套 Agent dashboard。

<a id="getting-started"></a>
## 开始使用

按时间顺序的[入门指南](GETTING-STARTED.zh-CN.md)是新手入口。[开发者 Quickstart](QUICKSTART.zh-CN.md)保留从 clone 到前台 MCP 检查的流程；[进阶 Windows + WSL2 参考](QUICKSTART.zh-CN.md#windows-and-wsl2)说明手动环境细节。它们不是额外的必需安装步骤。开发检查需要 Git、带 venv 的 Python 3.10+ 和 Herdr；委派还需要你已启动的合格 Agents。ChatGPT Web 也需要你自己的连接和 App。

Bridge 已用于 WSL；全新 WSL2 安装尚未验证。根目录 [`.app.json`](../.app.json) 和 [`.app.example.json`](../.app.example.json)包含明确无效的 App ID 占位符。在独立配置中使用你自己注册的 App ID。Copyright 名字不是 GitHub 登录账号；clone 时使用仓库实际 owner。

Principal 可向已有异构 Agents 委派工作，在它们运行期间继续推理，接收显式报告，并自行检查同一个本地项目的证据：源文件、搜索结果、diff、图片和原文件附件。项目本地 state 和 memory 让后续 Chat 恢复当前决策位置，而非从头开始。获得授权后，Bridge 还提供有界本地编辑、准确 Git candidate/commit 操作。

设计目标不是为了自治编排而编排。Agents 执行；ChatGPT 仍负责界定问题、决定委派内容、核查证据及最终判断。Herdr 提供本地 Agent 底座；Bridge 提供面向 ChatGPT 的 project、Work、证据、continuation 与项目延续层。

<a id="what-bridge-adds"></a>
### Bridge 增加了什么

- **ChatGPT Web + 已有本地 Agents。** 协调已在 Herdr 下使用的 sessions 和 Agent CLI，不必在终端间复制提示与输出。
- **以证据为基础的评审。** Agent 报告是主张，不是事实：接受结果前，ChatGPT 可独立检查仓库文本、diff、图片和文件。
- **完成提醒。** 委派固定批次、继续独立工作，由明确启用的扩展通知选定普通 Chat。
- **项目延续。** 仓库本地 rules、state、memory 和可复用 Plugin Skills 跨 Chat 保留影响决策的上下文，不把 transcript 变成第二个数据库。
- **有界本地动作。** 精确编辑和捕获的 Git candidates 让获授权 Principal 进行范围明确、可审阅的修改，同时保留无关工作。

Bridge 是面向开发者的 self-hosted 集成。公开源码包含产品代码、可移植文档和合成测试，不提供项目 cognition state、私有验收制品、可用 App 绑定或已配置服务。

<a id="tool-reference"></a>
## 工具参考

SOURCE 目录包含 18 个面向模型的 MCP 工具，带显式行为 annotations。已退役 widget 及其三个仅 App 使用的 watch/claim/feedback 工具均不存在，包括隐藏调用能力。浏览器完成通知使用独立 loopback capability，不是模型轮询工具或报告正文 endpoint。

目录描述的是 SOURCE 行为；部署和 host 验收需要独立证据。所有注册工具在执行前拒绝未知参数；annotations 描述行为，不是授权，也不保证客户端不会拒绝。通用发现支持 Pi、Codex 和其他 raw providers。没有旧工具以隐藏方式或旧名字保留可调用性；专用 managed start/resume/cancel/cleanup/recovery APIs 已删除。边界与重新读取见[观察契约](OBSERVATION-TOOLS.zh-CN.md)。

工具名迁移：公开接口为匹配名称、描述和作用而更名——collaboration_snapshot→bridge_overview（选择器 project_ref；默认视图显示 registered_project_refs）、workspace_register→project_register(project_ref, path)、checkpoint→current_state_update、agent_observe→agent_terminal_read、attach_file→prepare_file_attachment。

当前重设计还删除了 delegate 可选的 report selector；每个已接纳 Work 都请求报告。context、commit_prepare 及其他保留名称不变；面向模型的 await 工具已删除。commit_prepare 保留三种模式（stage paths + freeze / capture already-staged / page a saved candidate）。不存在可调用 aliases；使用当前工具名称和 schemas。

| 工具 | 用途 / owner |
| --- | --- |
| `context(project_ref)` | 选定项目定位：Git facts、容量、Agent handles、延续 pointers，以及有界、session 匹配的 continuation_inbox 观察；不恢复/读取 state-file 正文、不消费结果、不绑定 Chat |
| `delegate(project_ref, assignments=[{agent_ref, task}, ...])` | 派发 1..N 个必需报告的任务并返回逐项 receipts；自动为保留 Works 准备一个不可变 all-of cohort/card。部分派发不是事务；投递未知不能安全重发 |
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

<a id="project-selection-and-authority"></a>
### 项目选择与授权

完整参数以实际客户端 schemas 为准。每个 project-scoped 调用需要明确授权的 ref，并重新验证注册 Git root。Project Instructions 定义有限的允许 project_ref 集；registry membership 本身不是任务授权。ChatGPT Project 身份仍是 not_exposed_or_unproven。不存在可变全局 current project、静默 root fallback、placement、migration 或自动重新提交丢失 Work。

<a id="delegation-and-completion-reminders"></a>
### 委派与完成提醒

`delegate` 接受明确 `project_ref` 和非空 `assignments` 列表，立即返回每项 dispatch receipt。List envelope 的 `ok:true` 不证明 admission、delivery 或任务成功；响应丢失不构成重放理由。继续有用的独立工作；若没有则结束当前 turn。不存在 widget、仅 App 的 watch 工具或第二次 watch-registration。

可选扩展观察每次 delegate 的固定保留成员关系。完成分类且可读后，同一项目和 Chat 中已就绪、未尝试批次可共用一条短提醒。不同项目/Chat 保留独立 queue、recipient 和 cursor。报告读取失败阻止该项目后续 feed entries；已排队的就绪 candidates 可跳过另一个暂不可读 candidate。Unknown sends 从不重放。完整 `work_report` 须另行阅读；提醒或报告读取不表示 Principal 已处理结果。参见[通知规则](LIFECYCLE-RESTART-CONTRACT.zh-CN.md#chrome-notification-authority-and-recovery)与[生命周期契约](LIFECYCLE-RESTART-CONTRACT.zh-CN.md)。

<a id="agent-reuse-work-lifetime-and-inbox"></a>
### Agent 复用、Work 生命周期与 inbox

复用已验证 Agent/resource 前，Bridge 扫描全部保留 terminal 历史。Abnormal/attention/uncertain 缺口会拒绝输入，直到针对未改变条件记录了合格、同 resource 的 terminal diagnostic 观察。较新 Work 的观察不能掩盖旧缺口。普通 result_ready 报告缺口不阻断，只增加一条 advisory 和其他缺口数。成功的非空 public report page 只记录较弱的 Work 级 evidence-serving 事实；classifier probes 不计入。Terminal 文本始终是当前输出，不归属于任何历史 Work。

这两种 marker 都不证明 review、resolution、任务成功或 safe retry，也不消费 delivery 或延长 evidence 寿命。这些 project/resource 卫生事实跨 Chat 共享；后来的读者不能擦除它们。Session-scoped inbox visibility 独立；关联不是身份认证。Expiry/restart 会丢失历史，不增加恢复能力。

Agents 可以共享 checkout。Work 在 prompt 前的 writer-gated refresh 捕获准确 execution identity；可选 work_ref 读取目标是被冻结的 checkout，不是原任务执行内容的真实性。每项目容量为 16 个 active Work、512 个 recent terminal receipts 和 512 个 expiry tombstones。Count pressure 下，terminal receipts 按最早 settled_at 优先过期，包括未读报告。通知/报告读取不 pin 或续期证据。已知过期返回 WorkRefExpired；其他缺失 refs 返回 WorkRefUnavailable。Capacity 只显示 counts，不暴露 refs。

另外，context 的 `continuation_inbox` 仅对匹配请求 `_meta["openai/session"]` 观察最多 50 个保留 classified Work refs、result classes 和分类时 report-status snapshots，持续可见到正常 expiry/discard。未知 sessions 只见未绑定的 retained-classified count，不见其他 session refs。此 process-local index 不增加 widget claim、follow-up、retry、discharge 或 retention protection。通知 receipt 不是处理结果；报告读取不消费结果。

`classification_report_status` 记录最终分类时的证据，不是当前报告可用性；attention Works 稍后可能发布可读报告，`work_report` 可观察它而不重新分类 Work。这不是持久恢复，也不证明 conversation identity。参见[请求范围 inbox 契约](LIFECYCLE-RESTART-CONTRACT.zh-CN.md#request-scoped-result-inbox-observation)。[Work 容量](LIFECYCLE-RESTART-CONTRACT.zh-CN.md#work-capacity-and-report-lifetime)负责生命周期与 handoff 边界。Terminal signals 不证明 writers 已停止。

<a id="checkout-observations"></a>
### Checkout 观察

context 和 bridge_overview 的 Agent rows 还显示 native `workspace_id`（没有证明 workspace name）与仅供显示的 `checkout` 摘要：status、root、branch、HEAD、dirty。用 workspace id 和 tab/pane hint 区分 workspace；`handle` 仍是操作 ref。Unknown/changed/deferred 观察的 checkout 值为 null；观察到 branch=null 表示 detached HEAD。每次 discovery 共用一秒显示预算，最多 16 个 checkout 观察、四个 workers，同一 checkout 复用一个结果。

每次有 guard 的 status 观察包含一次 configuration probe；默认 bootstrap 可能在同一预算内需要一个 display-identity 前提。预算耗尽会延后 metadata，不移除 Agent rows；native process cleanup 有额外有界宽限，OS calls 不可抢占。这不是原子 snapshot 或可写保证。HEAD 标识 commit，不是 dirty files 完整基线。Worktrees 不是 OS 安全隔离。

<a id="local-writes-and-exact-git-candidates"></a>
### 本地写入与准确 Git candidates

Public `run` 已从 SOURCE 删除，没有 alias 或通用命令替代。delegate 派发到已有 Agents，不等待；面向模型的 await 工具已删除。直接观察、current_state_update 和有界 project_text_edit 保留。

版本动作先 commit_prepare 再 commit。Selected-path preparation 会变更 index，可能写 objects；最终 commit 发布准确捕获的 tree，不重新读取 paths 或刷新 index。明确省略 paths 才是捕获已有 staged 内容。没有公开 commit_preview/stage_paths alias、command arguments 或 approval field。

project_text_edit 需要已有常规 UTF-8 文件的完整小写 SHA256，以及针对同一原文的 1..256 个准确、唯一、互不重叠编辑（文件/结果 <=1 MiB）。保留未触及字节、换行和 mode；不创建文件，不接受 links、binary/NUL、.git/traversal，不 stage 或执行命令。它和其他项目操作使用相同的 frozen Work target 与 writer gate。

commit_prepare 选择 1..2048 个字面常规文件路径（UTF-8 路径总字节 <=16 KiB，总内容 <=4 MiB），包括明确新文件/删除。拒绝 mixed staged/unstaged selection、selection 外 staging、clean/process filters、active index hooks 和内容转换设置。捕获字节通过一个 raw-object Git batch 写入；不逐文件调用 Git，也不为创建 objects 重新读取 worktree。Path ceiling 限制临时文件及验证工作；30 秒 operation deadline 和 candidate/cache 边界仍适用。

两种 gates 只覆盖合作中的 Bridge calls，不约束外部 writers。Unknown writes 不授权盲目重试。具体机械边界见 [candidate version actions](OBSERVATION-TOOLS.zh-CN.md#candidate-version-actions)。源码测试不认证运行中服务或客户端刷新。

<a id="text-and-native-image-reads"></a>
### 文本与原生图片读取

read 不再提取文档，只观察 UTF-8 文本和完整原生图片（PNG/JPEG/GIF/WebP，suffix 与 magic 匹配，上限 5 MiB）。PDF/DOCX 在访问正文前按验证后的 suffix 拒绝（`UnsupportedReadFormat`）；`prepare_file_attachment` 请求这些原文件，read 从不批准、解析或拼接。其他 binary/invalid-UTF-8 文件仍是 `BinaryFileUnsupported`，提供相同 prepare_file_attachment 指引。

read 现为唯一原生图片路径；旧 `view_image` 兼容工具已从 SOURCE 退役。统一 read 保留 native image serialization；源码与 wire 测试不认证 host 视觉识别。

<a id="mandatory-work-reports"></a>
### 必需的 Work 报告

每个已接纳 Work 都请求报告。Bridge 追加私有临时报告（最多 1 MiB UTF-8）及其原子发布 staging file 的发布指令，不写入项目 checkout。Batch 分类指定 `work_report` 后，使用其 continuation 和完整报告 SHA-256 分页读取。

Agents 必须能写入该私有位置；settlement 后缺失或无效报告是 `attention_required`，不是静默成功。`work_report` 不等待或重试。Bridge 在 latch 后、最终分类前探测专用报告一次：只有 `WorkReportMissing` 可再检查最多两次，约每秒一次，增加等待不超过五秒。可读报告加 `agent_turn_settled` 分类为 `result_ready`。这只证明 artifact 存在，不是任务成功。Artifact 是 Agent 编写的证据，不是任务验收或供应商 transcript。

发布后缀计入已有 16384-character task cap：接近上限的任务可能满足原 task bound，却在 prompt 前因必需报告准备失败而返回 `WorkReportPreparationFailed`。Bridge 不静默截断任务或扩大上限。委派发送的是调用者 task 加报告发布指令。Work/report retention 仍是 process-local；未增加 restart recovery 或 automatic retry。

<a id="original-file-attachments"></a>
## 原文件附件

`prepare_file_attachment` 对最多 **7 MiB（7,340,032 bytes）**文件准确返回一个保留原 basename/MIME 的 ResourceLink，不带 TextContent metadata。更大文件返回有序 ResourceLinks，随后准确一个紧凑 JSON TextContent receipt：
`{"multipart":{"target":"original.bin","size":14680064,"sha256":"<full SHA-256>","parts":["<part 1 name>","<part 2 name>"]}}`。
Receipt 仅含 original basename、完整字节数、完整 SHA-256 和有序 materialized part names。TTL、retention、status、provenance 是内部信息，不出现在成功工具结果中。不新增 outputSchema、structuredContent、widget、blob/base64 或隐藏正文。

每 part 最多 7 MiB，使用 application/octet-stream，具有准确 raw size。名称为 `<shortened-basename>.bridge-<fullsha12>-part-0001-of-000N`，上限 255 UTF-8 bytes，不截断字符。小文件 URI 保持 `bridge://attach/{capability}`；multipart 为 `bridge://attach/{capability}/part/0001`。序号从 0001 开始，至少四个 ASCII digits（9999 后为 10000）；拒绝额外前导零。没有 ordinal 的 multipart group，或带 part ordinal 的 single file，均 fail closed。`export_file` 和 `bridge://export/` 仍已退役。

源码 part cap 为 **7 MiB**。假设序列化响应预算 **10,485,760 bytes（10 MiB）**，完整 part 的 base64 约 **9.33 MiB**（9,786,712 bytes），为 JSON/protocol overhead 留约 **0.67 MiB**。计算不是官方 raw-file 限制或已验收 relay 配置。应验证实际 client/relay 预算和 overhead：预算更小或 protocol envelope 更大仍可能拒绝 part。

任意的 **128 MiB** 原文件上限和 **128-entry** 附件数量上限/eviction 已移除。每个 binary resources/read 仍是单个 base64 response；MCP 没有为这一路径提供标准 streaming/range/reassembly。Bridge 使用有界内部 range reader。实际 observation deadlines 和 transport capacity 仍适用；去掉逻辑 size cap 不保证任意大 preparation/result 都能满足边界。

接收方利用 receipt part names 定位 host-materialized 文件，按顺序拼接为 original basename，验证完整 SHA-256 和 size 后才能认为收到原文件。Bridge 不增加自动 Web assembler 或 post-materialization hook。Preparation 与各 part fetch 成功不认证 host import 或 File Library presence。`readOnlyHint=true` 描述 filesystem observation；`idempotentHint=false` 表示生成新 opaque token。Bridge 不执行 upload。

<a id="resource-fetch-validation-and-wire-tests"></a>
### Resource fetch 验证与 wire 测试

内部 PendingAttachments lookup 每个 original 保存一个 frozen metadata entry，不受 part count 影响；具有有限 expiry/GC（目前 15 分钟），读取不续期，重启不持久。不保留文件字节。Entry 绑定 project/Work/path/target key、full SHA/size、原 name/MIME、file stat、parent-directory identities，以及不可变 part index/offset/length/SHA。

Preparation 以有界读取流式扫描一次，同时计算 full 与每 part hashes。可选 expected_sha256 仍 pin 完整文件。Fetch 重新解析同一注册 project/frozen Work，使用 reader admission 和 no-follow 常规文件 descriptor walking，仅读取请求 part。核对保存的 device/inode/mode/link count/size/mtime/ctime 和 parent identities、读取前后 descriptor/stat/path binding、准确 part length/hash，并在观察后再次核对 lookup identity/expiry。

Traversal、symlinks、特殊文件、路径改变，以及 unknown/expired/wrong/noncanonical tokens 均不返回字节（-32602）。任何位置的普通变更会令后续 fetch 无效；恢复 mtime 也不够，因为同时检查 ctime。这些观察不是原子 snapshot：若 identity、size 和观察到的 timestamps 均被伪造，请求 part 外的编辑可能逃过该次 fetch 检查。最终完整文件 SHA 验证才是端到端检查。不新增格式解析。

MCP 2.0.0 template 有固定 MIME hint；窄范围 MCPServer.read_resource override 将 bridge://attach/ 路由到每次响应的 ReadResourceContents。Single-file fetch 保留原 MIME；multipart fetch 使用 application/octet-stream。两种 discovery templates 均声明 generic binary hint；其他 routes 使用 SDK。

默认 MCP memory transport 测试保留真实 7 MiB、7 MiB+1 物理边界、较小的真实 two-part 和 frozen-Work three-part roundtrips（使用 test-local part cap）、ordered raw bytes/full SHA、准确 wire shapes、有界读取与不保留正文。默认 metadata-seeded 128/129/130-entry 测试跨越真实 store count 边界，同时仍通过 MCP wire 准备和读取；原始 129-preparation wire sequence 保留为 opt-in stress。

完整 14 MiB/two-part 与 21 MiB/three-part wire roundtrips 仍在 maintainer lane。轻量 regressions 也覆盖：fake hashing 的 >128 MiB preparation 加真实 lower-layer open/early-EOF 检查，9999 以上 canonical ordinals，以及 5 MiB 和 417,431-byte Work/non-ASCII cases。

7 MiB raw part cap 为 base64 和 protocol overhead 留空间，但不保证任意 relay/host 都接受；需验证实际环境 response limits 与 file import 行为。ResourceLinks 准备原始字节，不证明 host materialization、approval behavior 或自动 attachment。接收方应按顺序拼接 parts 并验证完整 original size 和 SHA-256。

<a id="passive-catalog-diagnostics"></a>
## 被动目录诊断

被动 `bridge.catalog_listing` INFO events 仅描述 handler catalog construction，不代表 client receipt。`read_only_count` 统计显式 True hints，不是工具总数。实现仍可用；不因此产生专门 observation task。

<a id="linked-checkouts-and-user-preplaced-agents"></a>
## Linked checkouts 与用户预先放置的 Agents

Same-common-Git linked checkouts 是可选写入域，不是永久角色或 OS 隔离。Placement 在 launch 前完成；Bridge 没有公开 Agent-create/launch 或 worktree-create 工具，也不在 delegate 期间 rebind 已有 Agent。用户在了解 provider/model quota 可用性的前提下选择并启动实际 coding Agent；随后 discovery/delegation 面向选定项目中的该已有 resource。

明确选择目标 checkout 和 Agent。源码支持 linked checkouts，不授权移动已有 Agents，也不证明 live UI 行为。

<a id="verification-and-deployment-boundaries"></a>
## 验证与部署边界

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

<a id="optional-system-service-adoption"></a>
## 可选 system service adoption

全新双独立服务安装使用 [Bridge + Secure MCP Tunnel autostart](AUTOSTART.zh-CN.md)。可选单 owner WSL anchor 保持 distro 运行，让 systemd 启动 enabled units。Herdr 和 Agents 仍手动启动，不恢复 Work 或 session。不将其 units 与此处 adopter 混用。

`scripts/` 包含可移植 service installer、environment allowlist library 和 tunnel TTL staging tool；`systemd/gpt-agent-bridge.service.template` 在安装时按所选用户和 checkout 渲染。机器路径、用户和代理由 installer inputs 提供。

仅在已有 Bridge process 为此 checkout 运行后，才可选用 `sudo scripts/install-bridge-system-service.sh --user USER --repo /path/to/gpt-agent-bridge [--proxy URL]` 安装 system service。Adopter 要求 package 以 editable 方式安装在本 checkout 的 `.venv`，并从此 checkout 准确运行 `/absolute/checkout/.venv/bin/python -m gpt_agent_bridge`。拒绝 root `server.py` launch、console entrypoints、flags 或额外 arguments；identity checks 无法认证已载入代码。

Installer 对运行中 Bridge 采取 fail-closed adoption，暂存私有 environment file、安装并验证 unit，但绝不启动或启用；启动服务仍是 operator 的显式动作。没有运行中 process 的干净 clone 不能靠它 bootstrap。

<a id="migration-risks"></a>
## 迁移风险

磁盘 checkout 改动不迁移已安装 package、running process、service definition 或 ChatGPT connection。src layout 删除了 root module entrypoints：未来用 `server.py` 重启会失败。在另行授权 cutover 前，准备并验证目标 checkout 的 editable install 和 module origin。保留已有 capability token、App binding 和必需 transport configuration；两个 autostart installers 都不导入 live environment，也不支持自动 takeover。

首次安装服务拒绝被占端口、foreign units/drop-ins 和未知 partial installation。其 minimal environment 可能不适合已有 proxy/CA/mTLS 部署；迁移前停止并审查差异。停止 Bridge 会丢失 process-local Work、references 和 continuation state；重启不恢复 Agents，也不授权重放。Rollback 必须同时考虑 code、package 和 service configuration。

本地 initialized Bridge health 与 Tunnel readiness 不证明远程 ChatGPT 验收。Linux reboot、Windows login/no-window/lifetime 和新用户 endpoint 仍需独立 target-host 验收；这不否定已有 WSL 使用报告。

<a id="web-principal-layers"></a>
## Web Principal 层次

Web Principal 是 **ChatGPT Web + Project Core + Bridge tools/Skills + Herdr** 的集成 self-hosted 工作方式。ChatGPT 提供推理，Core 引导判断与行为，Bridge 连接明确选择的本地项目和 Herdr 管理的 Agents。它不是独立推理引擎或一键托管 App。

[可复制粘贴的 Core 原文（未翻译）](../templates/WEB-PRINCIPAL-CORE.md)是此 checkpoint 中 Principal 从当前 ChatGPT Project Instructions 提供的完整正文。它记录收到的文本，不独立认证实时 Project settings，也不与其自动同步。手动安装和单独审阅的 Project Binding 是独立步骤。发布文件不更改已安装 Project，也不证明新 host 验收。

<a id="what-the-principal-owns"></a>
### Principal 负责什么

Principal 是用户的高层认知伙伴：界定问题、必要时重新表述；质疑假设、调查缺口、比较替代方案与取舍，并负责最终综合判断。委派服务于该判断；汇报 Agent 状态不是全部工作。

用户保留目标、范围、关键取舍和授权。已授权任务中，Principal 应持续推进有用工作，不重复请求相同许可。新的关键选择或授权边界应带具体证据与建议交回用户。

<a id="four-different-layers"></a>
### 四个不同层次

| 层次 | 职责 | 不能据此确立 |
| --- | --- | --- |
| Project Instructions：Core 和独立 Binding | 持续判断、行为、显式项目选择和适用边界 | Tool access、身份认证或执行隔离 |
| 四个 Plugin Skills | 相关情形触发的可复用流程 | 角色、新任务权限或 async protocol 行为 |
| Bridge tool schemas 和 descriptors | 可用操作、限制和 continuation/evidence 契约 | 执行所有技术上可用动作的许可 |
| 本地路由的 rules、current state、memory | 项目特定决策、持久原因和恢复上下文 | 全局记忆、自动授权或实时 runtime 真相 |

四个 [canonical procedures](#native-skills-and-app-binding)独立于 versionless continuity manifest。Core 不安装软件、暴露连接或发现原生 Skills。手动 Core 安装、四 Skill 检查及独立审阅 Binding 只遵循[入门指南](GETTING-STARTED.zh-CN.md)。凭据和私有 cognition 不进入 Core/Binding；选择必须明确，不能根据 Chat 或目录名推断。注册可返回 Binding amendment，但不应用 Instructions 或初始化文件。

<a id="delegation-reports-and-verification"></a>
### 委派、报告与验证

当调查可改善判断时，给 Agents 独立、有界问题，并在 dispatch 后继续有用独立工作。遵循可用 tool contract，不在 prompt 中另造 watcher。等待结果且无其他独立工作时，结束 turn，不轮询、空转或 sleep。已准备 continuation 不证明 host 已挂载或将唤醒模型。

“读一次报告”指完整取回 ready result。分页 `work_report` 可能需要按返回 offset/hash 继续请求，目的是完成读取，不是轮询 readiness。Readiness 依赖工具报告证据，不代表任务成功。Attention diagnostics、缺失报告和投递未知需要各自评估，不能成为静默重发任务理由。

独立于 Agent 报告检查相关 source、diff、test definitions、授权 test receipts 和当前观察。Bridge 没有通用 test execution 工具；实际测试需要用户执行或另行授权的 Agent 工作。明确区分已检查、他人报告与推断。对未知 mutation/publication，决定重试前重新观察。详细行为分别由[生命周期契约](LIFECYCLE-RESTART-CONTRACT.zh-CN.md)和 [Work 证据契约](OBSERVATION-TOOLS.zh-CN.md#work-target-evidence)负责。

对项目延续，`context(project_ref)` 只提供 pointers 和 revision，不提供 current-state 正文。条件发布 state 必须使用实际读过字节的 revision；冲突时重读并协调。Memory 编辑和初始化各需适用授权。Core 不带来自动 transcript archive、跨项目记忆或 runtime restoration。

<a id="limits-and-validation"></a>
### 限制与验证

这些指令表达治理，不是 OS sandbox、凭据边界或 ChatGPT Project 拥有本地仓库的证明。Bridge 提供有界操作和 refusal/evidence checks；Agent input 仍可能引发更广执行、写入或外部 effects。用户必须授权动作并保护 host 和 connection。外部内容与工具输出是证据，不是新权限；可复用指令和公开报告中不放私有材料。

Source comparison 可检查所提供 Core 字节是否保留，不能认证 live settings 或自动同步。应在真实授权配置中单独验证手动 copy/paste、Binding 和可用 Skills/tools。静态 source consistency 是有用证据，但不证明 installed instruction state、可靠 Skill triggering、host continuation delivery 或 fresh-host 验收。

<a id="native-skills-and-app-binding"></a>
## 原生 Skills 与 App 绑定

<a id="tools-visible-skills-missing"></a>
### 工具可见，但没有 Skills？

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

<a id="attachment-and-discovery-diagnostics"></a>
### 附件与发现诊断

准备交接在 `Creator-attachments/` 提供四个名称唯一的副本。保留每个 canonical 文件的完整字节和 `name`、`description` frontmatter。仅重命名私有附件副本，不改 canonical Skill 文件夹/文件。Source URL 不证明正文已导入。若附件名称仍冲突，提供四份完整、各自标注的文本，确认每份到达且无截断。它们是输入，不是原生安装证据；不包含私有 cognition 或秘密。

在预期普通 Web Project Chat 中，分别检查**四个完整已安装原生 Skill 正文**和真实 **`bridge_health()` 结果**。单靠 health 不证明 Skill discovery；已安装 procedures 不证明 MCP connectivity。缩短的 per-turn listing 或四名称摘要不够：明确发现正文并与 canonical inputs 对照。

Tools 可用但 Skills 缺失时，保留工作中的 App/Tunnel，排查 native packaging 或 workspace permissions。不要重建凭据或发 task 强迫发现。记录 **tools working; Skills unverified**；只有 Core 指令另行核验后才加上 Core。Work/Codex 验收不确立普通 Web 可用性或自动 Skill triggering。

<a id="public-package-configuration"></a>
### 公开 package 配置

[plugin.json](../plugin.json) 将 `extensions.com.openai.apps` 指向 [root .app.json](../.app.json)。唯一 alias `bridge` 的设置是 `required: true` 与明确无效占位符 `asdk_app_REPLACE_WITH_OWN_APP_ID`。[.app.example.json](../.app.example.json)给出相同 reference shape。

可选本地打包见[私有打包指南](#private-native-plugin-packaging)：[prepare-personal-plugin.py](../scripts/prepare-personal-plugin.py)将 public manifest、现有 LICENSE 和全部四个 Skill 文本复制进独立的 eight-file marketplace。Generator 从不读取 source App binding，也不安装 host plugin。只接受已验证 native App reference（`asdk_app_`、`connector_` 或 `templated_apps_`）；不转换浏览器 `plugin_asdk_app...` identifiers。Root placeholders 保持不变。在独立配置中使用自己注册的 App ID。Package 不添加 endpoint、credential、runtime Skill handler 或 marketplace configuration。

Source bundle 和 tests 证明 file layout 与 mapping shape，不证明 plugin distribution service 接受、App connection 可用、installed Skill discovery、automatic trigger reliability 或 fresh-chat usefulness。安装/分发前另查 host 当前 packaging requirements。源码测试不自动授权安装或发布。

Skills 独立于 project-local cognition。公开包不含实际项目 `.principal/` 目录。安装不接入项目、不启动服务/Agents、不授予任务权限。首次使用只走[入门指南](GETTING-STARTED.zh-CN.md)。

<a id="private-native-plugin-packaging"></a>
## 私有原生插件打包

此可选路径面向已验证合格 native App 和支持 local marketplace 的 surface，不会为所有 Web accounts 安装 Skills。唯一 Creator 路径见[入门第 6 步](GETTING-STARTED.zh-CN.md#6-install-and-discover-all-four-native-skills)。浏览器 `plugin_asdk_app_` 表示不是 native `.app.json` ID；不裁掉 prefix 或根据字符串推断资格。Chrome extension ID 是完全不同的身份。

[共享 native ID check](https://developers.openai.com/plugins/deploy/submission-errors#mcp-server-reference-errors)允许 `asdk_app_`、`connector_` 或 `templated_apps_`，随后一个 ASCII 字母/数字，再跟 ASCII 字母/数字/下划线/连字符。允许大写和不同 suffix 长度。Generator 另加**本地总长 256-character 限制**，拒绝已知 public placeholder、browser IDs、URLs、whitespace、non-ASCII 和 controls。准确保留输入；没有 browser-to-native 转换。只有 browser URL 时，返回入门第 6 步的 Creator 路径，让 host 选择已有 App。

<a id="use-a-reviewed-licensed-public-source"></a>
### 使用经评审且带许可证的公开源

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

<a id="exact-eight-file-result"></a>
### 准确八文件结果

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

<a id="explicit-host-installation"></a>
### 显式 host 安装

审阅私有生成包，对照 source 的 notice/Skills。生成尚未改变 host。若 client 支持[官方 local marketplace 流程](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli)，用户可显式添加此 marketplace root：

```bash
codex plugin marketplace add "$HOME/bridge-personal-marketplace"
```

此命令改变 host configuration；generator 从不运行它。在合格的本地 Work/Codex desktop surface 中，按当前说明刷新/重启 desktop app，打开 Plugins Directory，选择 Personal GPT-Agent Bridge 并安装 GPT-Agent Bridge。审阅 App authentication 与 permissions。这不是 Bridge/Tunnel 重启，也不是通用 Web Project Chat 安装路径。

Account/workspace policy 可阻止 local sources 或 App access。不要编辑 host caches、global config、admin settings 或其他 marketplace 来绕过。Sharing/publication 需要单独 review 和 authority。

<a id="target-chat-skill-verification"></a>
## 目标 Chat Skill 验证

完成任一支持安装路径后，在预期 Project 打开 fresh chat，在 UI 提供时选择/启用插件。请求：

```text
Read-only check: explicitly discover this chat's installed Skill catalog.
Find project-onboarding, project-resume, handoff-preparation and
team-deliberation under my Bridge plugin and compare their available texts
with the canonical attachments I reviewed. Do not invoke these procedures,
register/initialize a project, delegate Agent input or change any files.
Separately call bridge_health and inspect the returned Herdr.status.
```

依据实际结果，不依据文字断言或缩短的 per-turn listing。Work/Codex 测试不认证普通 Web Project Chat 可用性；discovery 不认证自动选择、trigger reliability 或 continuity。

在实际目标 surface 验证四个 Skills 后，返回[入门第 8 步](GETTING-STARTED.zh-CN.md#8-connect-your-existing-git-repository-and-merge-its-binding)和[有界首次使用检查](GETTING-STARTED.zh-CN.md#10-begin-daily-use-with-a-bounded-read-only-check)。Registration、initialization、Agent input 和 continuity 各保留独立权限。

<a id="native-execution-retirement"></a>
## 原生 execution 退役

Public `run` 已从 SOURCE 删除，没有隐藏 alias 或任意命令替代。其专用 native_execution module 与 tests 已在 consumer inspection 后删除。Source inspection 和 tests 只证明本地契约；runtime deployment 和 host acceptance 需独立证据。[工具参考](#tool-reference)列出保留能力；[观察契约](OBSERVATION-TOOLS.zh-CN.md)负责准确 evidence/version mechanics。

不同 Agent resources 可在同一共享 checkout 同时持有 in-flight Work；但同一 Agent handle/resource 的 nonterminal Work 或未消费 handoff 仍拒绝重复 prompt。Terminal settlement 不证明手动/detached writers 已停止。Shared gates 与 dispatch identity checks 保留，见[生命周期](LIFECYCLE-RESTART-CONTRACT.zh-CN.md)。

Fixed Git observations 保留有界 byte capture、timeout 和等待完成的 cancellation cleanup，不暴露调用者 argv。Spawn/nonzero failures 和 incomplete captures 不是 clean observations。tests/test_fixed_git_lifecycle.py 覆盖 inherited pipes、TERM-resistant descendants、repeated cancellation、escaped pipe holders。Escaped processes 和不可抢占 OS operations 使无条件端到端 bound 无法保证。Query limits 与不支持配置见[观察工具](OBSERVATION-TOOLS.zh-CN.md)。

Shared admission regressions 在 tests/test_checkout_admission.py；实际 MCP retirement 与保留 evidence calls 由 tests/test_run_retirement.py 覆盖。Source tests 不认证 runtime 验收；单独验证配置服务与 client。公开 source 不包含私有 execution receipts。

<a id="license"></a>
## 许可证

按 [MIT License（未翻译的许可证原文）](../LICENSE)发布。Copyright (c) 2026 tomoyo。
