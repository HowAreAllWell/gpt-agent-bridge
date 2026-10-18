[English](LIFECYCLE-RESTART-CONTRACT.md) | **简体中文**

<a id="gpt-agent-bridge-lifecycle-and-restart-contract"></a>

# GPT-Agent Bridge 生命周期与重启契约

状态：保留的通用 Work 路径之源码契约。专用及兼容性 MCP 端点均已不存在，包括隐藏可调用性。本文描述当前源码行为及其证据限制。源码检查和测试不认证已部署服务、后端版本或客户端验收。

<a id="resource-and-work-identity"></a>

## 资源与 Work 身份

Agent 句柄指向明确注册项目中的一个精确当前资源：Herdr workspace/tab/pane/terminal，以及原始 kind/name。它是进程本地句柄，不是持久 Agent 身份。链接的执行检出只有位于注册项目精确的 Git common-dir 边界内才会被接受。身份缺失、畸形或有歧义时拒绝；不得推断为其他项目、资源或后端。

放置在启动/提示词输入前完成。`delegate(project_ref, assignments=[{agent_ref, task}, ...])` 重新验证注册表和精确资源，在修改提示词前预留 Work，再在绑定执行身份和派发之前，于写入门内立即刷新选定资源。资源身份稳定，而原生会话、前台进程和 CWD 属于执行证据。不存在委派时重新绑定、放置恢复、就绪迁移或回退。在这个已有写入门保护的绑定点捕获冻结的 evidence_checkout 元数据。捕获失败不改变派发语义。read/search/diff 独立于可变 Agent/交接状态，重新验证保存的目标；身份不可用或变化时绝不回退。

Work 注册表拥有不透明的 work- 引用。Delegate 始终接受 assignments，并立即返回逐项派发回执。每个保留项用 `work_ref` 标识其 Work。派发不确定时，尽可能返回可访问的 work_ref；提示词传输和调用方取消不能悄悄遗弃已预留 Work。内部交接观察器和资源门禁保留，因为 delegate 和内部观察器使用它们；不存在公共 handoff/join 或旧式透传。模型可见的 await 工具已移除。

每个获准 Work 都请求协作发布到唯一的私有报告位置，该位置在 Work 预留后、修改提示词前分配。单个任务后缀只授权最终报告及其命名的原子发布暂存文件，要求 Agent 在终端最终回复前发布完整 UTF-8 报告。发布后缀计入现有 16384 字符上限，因此接近上限的任务可能准备失败。准备失败会丢弃未提交预留，不截断任务文本。精确增强后的字节只进入普通派发和同一 Work 恢复接缝一次，绝不增加第二个后缀。它们不持久保存在回执或任务日志中。仅对可能回显增强字节/私有路径的提示词传输错误脱敏；已知无输入错误、提示词前重新验证和阻塞诊断保留有用消息。提交不确定性和重试权限不变。

报告存储精确定义为：惰性创建的每进程 0700 `/tmp/bridge-reports-*` 目录，保存随机最终文件名及 `.pending` 暂存文件；公共回执中不出现报告路径。整个服务器优雅关闭时（systemd SIGTERM；Uvicorn 在恢复/重新抛出信号前运行应用 lifespan shutdown），在正常 MCP/session-manager 拆卸后，ASGI/MCP lifespan 拆卸期间只关闭当前进程存储一次。崩溃/SIGKILL、断电、迟到写入者或权限错误仍可能留下孤立文件，这是接受的残余风险。没有启动扫描；重启不扫描、恢复或清除旧孤立文件，也不意味着启动 GC 或总磁盘上限。

`work_report` 要求精确项目/Work 绑定和终态 Work；它只检索发布的私有产物，不取窗格尾部或提供方对话记录。它既不等待发布，也不改变终态锁存。发布缺失或不合规是明确的证据错误，不是新的 Work 结果。单 assignment 的 delegate 回执保留派发字段和既有证据提示。内部 Work 记录保留结算状态、原因和提交证据；没有公共逐 Work await 工具或报告请求标志。结算不等待报告；报告字节可读只证明存在，绝不证明任务成功或真实性。

报告保留/清理遵循 [Work 容量](#work-capacity-and-report-lifetime)。不增加通用 Agent 启动或输出拦截。结算后立即调用 `work_report` 时，如果外部发布重命名刚好晚于结算，可能暂时报 WorkReportMissing。`work_report` 本身仍是每次调用观察一次，不等待发布或自动重试；缺失不证明永久不存在。分类在锁存后探测专用报告，不在 Work 注册表锁内睡眠。`WorkReportMissing` 是唯一暂时性候选：初次读取后，最多再复查两次，间隔约一秒。增加的重试等待总计不超过五秒。该上限约束注入的等待，不是 OS I/O 实际耗时。其他报告读取错误立即分类为 `invalid` 或 `unknown`。报告可读且为 `agent_turn_settled` 时是 `result_ready`。`needs_attention`、`continuity_lost`，以及报告缺失或无效，均为 `attention_required`。分类只设置一次。

<a id="submission-evidence"></a>

## 提交证据

Work 及其交接在终态锁存前后保留一个紧凑的 `submission_evidence` 对象。`not_attempted` 记录输入前的本地拒绝；`native_acknowledged` 要求 `agent_prompted` 回执标识完整匹配的稳定资源（kind/name、workspace/tab/pane/terminal）。回执身份缺失、畸形、无法识别或矛盾时仍为 `delivery_unknown`，原生错误、超时和取消也一样。非幂等调用之前就标记修改可能发生。已知原生错误码是有界 token，不是原始任务文本、路径或输出；没有任何错误码证明无效果。确认仅证明宿主接受或排队该请求，绝不证明 Agent 消费、Enter 送达、任务执行或完成。任何没有匹配确认的传输响应，都同步返回带 agent_ref、work_ref 和 submission_evidence 的 WorkDispatchTransportUncertain。mutation_possible=true 时，其结构化错误包含安全指令：进一步委派前读取 agent_terminal_read，不要重发任务。紧凑文本说明送达未知并指向该结构化指令。mutation_possible=false 时，错误保留具体后端原因，紧凑文本说明未发送提示词/输入；既不禁止重发，也不声称送达未知。Work 及其观察器仍可访问。取消在保留不确定性后继续传播。现有本地拒绝仍丢弃从未派发的预留。终态信号与报告分类独立于提交来源：之后的 agent_turn_settled 锁存若有可读专用报告，即使原始送达仍未知，也可得到 result_ready。这不会重写提交证据。原生版本兼容性和端到端归属尚未建立。

原生 AgentInfo 可省略可选 name：省略仅匹配预期未命名资源（None）。已命名资源省略/不匹配 name，或必需 locus/kind 字段缺失，仍视为确认未知；Work 保持可访问，不重试提示词。

只有权威 agent_kind 精确为 `agy` 时，一个已耗尽且无进展的激活观察预算才进入有界冷路径输入框恢复，而非立即转为需要关注。正常 AGY 派发不变：已有验证之后发送一次原生提示词，不依赖屏幕、不要求本地 Herdr manifest-override，也不增加热路径 Herdr 调用。原生确认只证明传输接受，不证明 AGY 回合已激活。AGY 状态依赖屏幕检测，因此无进展的 idle/done 观察本身无法区分输入丢失与检测不可见的回合。恢复只在 native_acknowledged 提交之后，且同时满足以下条件时重新送达：同一 execution/session/resource 仍为 idle/done、未阻塞，精确的派发前 `state_change_seq` 不变；Bridge 本地独占（同一 resource_key 或执行身份没有其他非终态交接或 Work，不论是否已消费送达；活动恢复窗口也经现有在途保护对称阻止同资源派发）；以及两次相隔约 300ms 的新鲜、有界、只读 `agent read --source detection` 观察，各自独立匹配已识别的已结算空输入框形态（单独的 `>` 输入行、框线分隔符、页脚锚点；queued 提示、esc-to-cancel 和权限提示特征均否决）。两次读取之间和之后复查 status/seq/identity，并在写入前立即复查独占性。调用方取消的 delegate 从不自动重发提示词：其观察器保留现有关注结果。只有全部满足后，才把精确的原任务通过同一原生提示词原语，为同一 Work/交接重发一次；原任务仅保存在内存观察器接缝中，绝不写入回执、交接条目或日志。不发送 Enter、不用低层粘贴、不修改任务或增加 nonce；随后只给一次新的有界激活窗口（激活后沿用普通 AGY 结算去抖）。任何不确定性——屏幕读取错误/超时/空或畸形结果、形态不匹配、seq/status 变化、独占歧义或恢复接缝缺失——都保留现有 `activation_observation_budget_exhausted` 关注状态；重发传输失败，或重发回执不满足与首次提示词相同的完整稳定资源确认匹配，则终结为 `agy_composer_recovery_reprompt_uncertain`（修改可能已经发生，绝不安全重试）；重发后仍无进展而到期，则终结为 `agy_composer_recovery_exhausted`。绝无第三次提示词或恢复循环。成功重发用交接和 Work 记录中的布尔 `agy_recovery_reprompt` 审计标记，不记录任务或屏幕文本。AGY 屏幕形态改变时，恢复保守失败并转现有关注状态，不影响普通 AGY 可用性。所有其他 kind 的行为完全不变；qodercli 输入框轻推恢复也不变。

<a id="agent-settlement-and-terminal-evidence"></a>

## Agent 结算与终态证据

每次首次终态锁存发出一个 bridge.work_terminal_latch：work_ref、有界 handoff_id、终态、reason、herdr_status、有界 watcher_error_code，以及从派发到锁存的 elapsed_ms。这些日志不含任务文本、终端内容或原始异常正文，是进程日志而非持久日志簿。重复锁存不再发出事件。

启动观察使用一个五秒单调时钟预算，包含精确重新验证和全部唤醒。原生状态等待排除当前观察到的过期 idle/done 状态：idle 等待 working/done/blocked；done 等待 working/idle/blocked。每次唤醒或原生到期都复查身份和序列；符合条件且已推进的终态序列无需观察 working 也可结算。原生 code=timeout 是正常到期；子进程/传输错误在重新验证后产生 startup_wait_uncertain。没有激活证据而耗尽时得到 activation_observation_budget_exhausted。只有权威 agent_kind 精确为 `qodercli`，一个窗口耗尽后仍为 idle/done 且精确序列未推进时，才进入用户授权的有界卡住输入框恢复：最后一次精确重新验证允许一次仅 Enter 的 send-keys 轻推（不含任务文本，绝不是第二次原生提示词，每回合最多一次）。连续性丢失、检出变化、观察不确定、阻塞或不确定状态、working 证据和序列推进均按原有分类或普通流程否决轻推。轻推送达后，为同一物理回合、Work 和交接重新开启一次新的有界窗口；仍未推进而到期得到 qoder_activation_nudge_exhausted，轻推传输失败得到 qoder_activation_nudge_uncertain，两者都诚实终结且绝不重试。不读取屏幕文本、Qoder 私有日志或任务文本启发式。这项观察预算不是 Agent 启动 SLA、提交失败证明、安全重试许可或无条件端到端 OS/清理时限。后续 working 屏障、等待者隔离和历史终态锁存保持不变。

首次终态锁存胜出。在有界进程本地 Work 记录保留期间，其状态和提交证据保持可用：

- `agent_turn_settled`：证明 `agent_turn_settlement_only`。
- `needs_attention`：证明 `attention_or_observation_condition_only`。
- `continuity_lost`：证明 `exact_continuity_contradiction_only`。

通用结算是符合条件的已观察转换，不是任务成功、脱离子进程完成或结果归属。Principal 通过直接仓库证据、专用 work_report 产物和有界 agent_terminal_read 输出验证实质。needs_attention 不证明 Agent 失败，也不证明新派发/故障转移安全。精确暂时码 `manual_candidate_read_unavailable`、`manual_candidate_observation_unavailable` 和 `manual_candidate_process_unavailable` 最多从头重新验证两次，约相隔一秒，总额外延迟不超过五秒。每次重试只读：无提示词、send-keys 或其他写入，也不解除终态 Work 锁存。下次尝试得到确定码时，立即沿用该码原有分类。暂时尝试耗尽仍锁存 `needs_attention` / `observation_unavailable`，仅证明 `attention_or_observation_condition_only`。候选有歧义或其他非暂时重新验证失败仍立即需要关注。可获得的前台进程指纹不相等证明连续性丢失。普通同组子进程变动和会话变动本身不等于执行替换。前台作业锚点是 PGID 加精确一个 leader PID/argv，不宣称 leader 就是 Agent。Herdr 可检测包装器的 Agent 子进程。有效的可选 aggregate/member CWD 观察另行分类：缺失、匹配执行或不同；非目标原始路径会脱敏，单独 CWD 变化不是进程替换。不把匹配子进程提升为锚点。形态/PID/argv/数量和唯一 leader 检查仍必需，也不授予包装器外部目录的权限。已派发 Work 保留选定 Git 检出：选择或已捕获 Git 身份变化会产生 execution_checkout_changed 关注，不会悄悄改目标或认定进程替换。Work 文件证据仍冻结，并独立重新验证该检出。Agent 资源报告读取始终是当前且未归属的观察，不是原 Work 结果。这些源码语义不识别任何实际 Pi 包装器、可执行文件或冲突路径。

2026-10-06 实际证据 `work-b26dd477fd704192`：一次暂时观察失败在 Agent 仍工作时将 Work 锁存为终态。之后的 `agent_terminal_read` 和文件 mtime 表明观察已恢复，Agent 继续执行。该记录说明错误终态机制，以及上文的有界只读重试。它不构成尚未发布源码修复的验收，也不表示任何 Agent 调度偏好。

终态 Work 释放内部交接门禁。每个精确 project_ref/registered-root 对允许 16 个活动 Work，并保留 512 条终态回执。锁存时，终态数量压力会按 settled_at 最早优先使回执和报告字节过期，包括未读或部分读取的报告。读取不续期。未知/非终态 Work 永不过期。内部交接准入仍以每项目 128 为上限；仅完成后运行的回调释放已锁存终态交接和观察器 Task 引用，不取消运行中的观察器。过期、墓碑、计数和候选依赖参见 [Work 容量](#work-capacity-and-report-lifetime)。共享 CPU/内存/故障域不隔离；结算或过期不证明外部写入者已停止。

<a id="unified-delegation-and-evidence-serving-reuse-checks"></a>

## 统一委派与证据提供后的复用检查

`delegate(project_ref, assignments=[{agent_ref, task}, ...])` 是唯一公开的 1..N 接口。新目录参数要求 project_ref 和非空 assignments，minItems=1，maxItems 等于现有 Work 保留界限。签名、公布参数和运行时验证都只要求 project_ref 与 assignments。标量调用和混合形式是协议错误；不存在隐藏兼容性。未知字段/非字符串值会被拒绝；空列表或重复缓存资源身份会在输入前拒绝。请求受现有 Work 保留上限限制。准入和写入门内重新验证仍逐项执行；后续拒绝或传输不确定不能回滚之前已发给外部的提示词。每项报告实际回执及 submitted/delivery_unknown/not_submitted 结果。拒绝中提及的旧 Work 是 existing_work_ref，绝不暗中视为新提交 Work。列表外层 ok 表示请求处理，不表示所有项成功。

一个请求本地预留列表只捕获此次调用在修改提示词之前的 Work。已丢弃无输入预留不在其中；不确定且保留的预留仍在。取消或意外异常继续传播；幸存 Work 在保留期内仍可观察。中止绝不重发提示词，也不证明响应到达。

继续有用的独立工作；没有可做工作则结束当前轮。明确启用的本地浏览器扩展可以送达报告就绪通知；否则仍需要用户提醒。

可选浏览器完成事件流按每次 delegate 调用，把配置项目/根中的新预留 Work 分组。派发退出时（包括异常/取消）封存成员，只有所有保留成员都有最终分类（或权威过期）后才分配一个序列号。未发送预留被移除；绝不接纳已有 Work 引用。事件流元数据包含成员 Work 引用、最终分类、当前报告可用性和可读 SHA256，不含报告正文或派发权限。浏览器发送含完整 batch/Work 引用的短提醒，不发送事件流诊断字段。暂时报告读取失败会阻塞该项目的事件序列及后续序列；其他项目有独立游标。排队后候选可分别复查；暂时不可读候选不延迟其他就绪候选。批次元数据附在保留 Work 上；过期成员不可用，全体成员丢失或重启会失去批次资格。它不增加保留保护或 widget。扩展持久保存完整 Chat 路由、游标、队列和发送前意图。发送时可合并同项目、同 Chat、已就绪且未尝试的批次，不改变 delegate 成员，也不等待未完成批次。首次修改前固定组成员、收件目标和通知版本；已有意图不增加成员。旧 v1/v2/v3 意图身份仍不可重放；新 v4 通知明确列出来源项目。就绪组在意图前检查，已尝试或不确定身份被抑制，绝不重放。预填后页面变忙而回撤时，要求撤回前后是同一实时编辑器和自有文本、绑定/编辑状态不变，且未观察到提交干扰。外部 Send/submit 干扰仍属未知，不能授权再次发送。这些是有界本地 DOM 观察，不是权威宿主回合或服务器事务保证。本地 Send 点击不是后端送达证明；之后不扫描对话/收件回执。显式草稿选择只表示本地已处理，不声称消息已提交。参见[扩展行为与本地设置](#chrome-notification-authority-and-recovery)。

在写入门保护的最终资源刷新时，扫描精确项目/根内具有相同稳定资源键的全部保留终态 Work。异常终态、提交不确定或最终报告关注条件优先。没有符合条件的后置状态诊断已提供事实时，PriorWorkDiagnosticsRequired 在交接预留/提示词输入前拒绝；回执说明无输入，并指引读取 agent_terminal_read。现有非终态/资源保护不变。否则，普通 result_ready 的证据缺口附加不阻塞的 prior_work_advisory。返回一个主要缺口和 additional_count，不返回无界历史，也不声称尚未读取。

成功且非空的公共 work_report 页面在 Work 范围标记 report_evidence_served，不区分 Chat/会话。内部报告探测、错误和空页永不标记。这是证据提供，不是完整报告覆盖、审核或确认；读取不续期。诊断读取在 I/O 前捕获相关同资源后置状态快照，之后核对保留对象/条件/资源身份。条件签名记录类型、终态信号和原因，不使用逐 Chat 台账或最后读取者覆盖。另一 Chat 不能抹掉该观察；条件变化或新 Work 不能复用它。读取期间到达的新条件不符合资格。这只是有限的当前终端证据提供，不是历史 Work 归属、解决或安全重试。提供标记不保存原始会话 ID 或证据正文；会话范围的 continuation_inbox 可见性另行处理。迟到报告永不修改 result_class/classification_report_status。读取迟到报告不解除异常诊断门禁。普通过期/重启会让标记与 Work 一起丢失，不假装有持久历史或恢复。

<a id="request-scoped-result-inbox-observation"></a>

## 请求范围的结果收件箱观察

每个预留 Work 都在修改提示词前自动注册一个轻量进程本地收件箱事件，键为精确 project_ref/registered-root 和来源不透明宿主会话关联；关联未知时进入未绑定桶。Work 最终分类将 result_class 及报告状态快照投影到该事件，不增加观察器、报告探测、重试，也不改变 Work 事实。从未提交的丢弃和普通 Work 过期会移除事件及空桶。收件箱条目不固定保留证据。

已安装 MCP 2.0.0 的 call_tool Context 携带 request_context.meta。Bridge 只从该逐请求映射读取 `_meta["openai/session"]`；支持最多 4096 字节的非空有效 UTF-8 字符串。缺失、畸形、超限或其他值形态都为未知，不回退到传输身份。以进程密钥计算 HMAC-SHA256，生成存储的不透明关联；此记账不保留原始 metadata/Context。受支持 SDK 工具调用周围的 ContextVar set/reset 隔离并发请求及异常/取消退出。关联通过复制上下文的 asyncio.to_thread 传播；任意线程或 executor 提交不会自动继承。不增加模型可见的 session/Context 参数。相同值只在当前进程内关联；元数据是调用方提供的关联，不是已认证对话身份、项目权限或宿主送达证明。实际宿主是否提供及稳定性尚未验收。

`context(project_ref).continuation_inbox` 只读。匹配的已知请求会话得到 binding="session"、classified_count、按预留顺序最多 50 个 retained_classified 条目（{work_ref, result_class, classification_report_status}）、has_more 和 proves="final_classification_only"。每个保留的最终已分类事件都有资格。`classification_report_status` 仅是最终分类变为不可变时观察到的报告证据，不是当前报告可用性。异常结算可能跳过报告探测，缺失或未知报告也可能之后可读。`work_report` 可观察这类迟到证据，但不修改 result_class 或 classification_report_status。报告检索不消除该条目。其他已知会话只看到自己的桶。未知请求只得到 binding="unknown" 和 unbound_classified_count，绝不暴露会话绑定或未绑定的 Work 引用。计数覆盖全部保留的最终已分类事件，不含活动预留或仍待定探测。不增加保留固定：普通 Work 过期/丢弃会移除事件，重启会丢失。本部分没有收件箱分页参数或消除端点。context 不处理结果、不续期、不调度分类。现有压力可在审核前让未读证据过期。收件箱不是持久恢复或继续执行的送达路径。

<a id="checkout-admission"></a>

## 检出准入

同一检出（包括别名）中已知非终态 Work 不再拒绝派发：不同 Agent 资源可在一个检出中并行持有在途 Work。同资源保护不变——同一 Agent 句柄/资源的非终态 Work 或未消费交接仍拒绝重复提示词。公共 run 退役后，派发准入周围的项目写入门和冻结目标重新验证仍保留。不引入新所有权注册表或无限期不确定性锁。通用结算、needs_attention 和 continuity_lost 不证明手动或脱离写入者已停止。[观察契约](OBSERVATION-TOOLS.zh-CN.md) 描述固定查询的证据限制；[工具参考](TECHNICAL-REFERENCE.zh-CN.md#tool-reference) 列出保留的效果边界。源码测试不是实际客户端验收，也不增加 Work 恢复。

已有候选页面和同消息已尝试回执重放具有独立的进程本地生命周期：当前项目授权和候选冻结路由/请求检查允许在 Work 过期后读取缓存历史，不进行候选 Git 修改/检查、Work 解析、重新捕获或重新绑定。入口仍先做当前项目授权/WorkspaceRegistry 身份验证，其中执行有界只读 Git 身份检查；整个调用并非完全不访问 Git。未尝试提交仍拒绝过期 Work。候选被逐出后，其历史不可用；Work GC 绝不释放未知尝试隔离。读取回执不证明外部停止或安全重试。参见 [Work 容量](#work-capacity-and-report-lifetime)。

<a id="restart-and-uncertainty"></a>

## 重启与不确定性

Work、不透明 Agent 引用、门禁、批次订阅和送达消费都是进程本地状态。未知 work_ref 返回 WorkRefUnavailable：可能从未在这里签发、重启后丢失，或过期后超出有界墓碑保留。已知过期回执返回 WorkRefExpired。两者都让外部工作命运保持未知。不要重新发现/绑定/提交/取消外部 Agent 来猜测发生了什么。delegate 响应丢失按契约也保留歧义；不会自动重新委派。Bridge 不增加持久 Work 恢复、调度器或平台唤醒。进程日志事件（批次等待/认领、Work 终态锁存）不是持久日志簿，不跨重启保存。项目本地 checkpoint 持久保存 Principal 提供的状态，不保存 Work 身份或恢复。替换不自动归档被覆盖且未提交的历史；参见 [docs/PROJECT-CONTINUITY.md 的中文版本](PROJECT-CONTINUITY.zh-CN.md)。当前验收需要单独的实时证据。

观察不确定和传输失败绝不授权外部中断、清理、重新提交或静默切换后端。受管理生命周期或专用 Codex/Pi start/resume/cancel/recovery API 都已不存在。源码退役不触碰用户会话、存储的数据/配置或已安装扩展。Herdr 是宿主边界；此部分不改变宿主/YOLO 操作，也不增加执行权限系统。

<a id="bootstrap-and-deployment-evidence"></a>

## 引导与部署证据

bridge_overview 默认使用配置根，并支持明确的已注册 project_ref。它与 context 共享紧凑通用候选发现，包括链接检出，区分发现不可用、部分覆盖和完整观察。它保留直接仓库、运行 Bridge PID/启动时间、系统服务 PID/启动时间及默认根控制文档指针。两个视图都要求当前后端覆盖计数：`out_of_project`、`invalid_or_unavailable` 和 `truncated`。经验证的外项目排除不降低覆盖；畸形/不可读/歧义候选及截断会降低。投影失败也计为不可用候选。计数缺失或畸形时拒绝，不回退到旧零计数，也不声称发现完整。已证明的外项目排除复用已有候选身份规则，包括报告 CWD 和前台 CWD 中受支持的同一 Git common-dir 链接检出；仅路径不等不是矛盾。所有原始 kind（包括 Pi）都在同一 Git 边界内独立验证两个 CWD，有前台 CWD 时选前台，否则选报告值。实际跨项目目标冲突、畸形 session/name/locus 和进程证据仍拒绝；进程 CWD 关系不重新定义选定 Git 目标。排除外项目不会查询外项目进程。

Context 的 agents_rejection_diagnostics 和 snapshot 的 observation.rejection_diagnostics 共享固定 stage/reason 计数，最多八个本地 kind/hint 详情、明确的 unlocalized/omitted-local 计数和候选截断。只有独立证明属于选定项目且 locus 有效才允许本地详情；歧义重复和外部/未知范围只返回计数。被拒候选不获得句柄。原始异常、路径、名称、argv、会话和任务文本不是诊断字段。诊断缺失或畸形表示不可用，不虚构零原因。公共投影失败计为未定位拒绝。整个 snapshot 失败仍不可用；畸形个别条目有 snapshot 原因计数。现有仅窗格候选在进程证据不可用时仍可见，并保留原连续性限制；拒绝诊断不重新定义名册或执行健康。诊断不增加宿主查询、候选注册表、端点或实时探测。不使用旧任务/会话所有权或 Pi 权限投影来驱动此名册。

Agent 行展示已验证的原生 workspace id（不推断 workspace 名），以及 tab/pane 提示和仅供显示的检出观察。复用已有发现 Git 事实，不增加 Git 身份调用；有界文件系统对象/指针检查围绕一次 porcelain-v2 branch/HEAD/status 命令，固定使用已验证 Git 目录和检出根。成功完整读取为 `observed`；失败/不完整为 `unknown`，检测到路径/对象变化为 `changed`，共享预算耗尽为 `deferred`。非 observed 值均为 null，包括 dirty；observed 时 branch 为 null 表示 detached HEAD。

一次发现共享 1 秒信息补充截止时间、最多 16 个唯一检出尝试和四个 worker。每个命令最多获得 0.25 秒及剩余预算。按 snapshot 顺序考虑唯一检出；并发 worker 防止一个慢树阻塞其他名额，不承诺跨调用调度公平。Deferred 元数据不移除 Agent 行或改变覆盖。截止/取消会等待原生进程清理（现有宽限最多 0.65 秒，受 OS 调度影响）；OS 调用和已有发现验证不受硬性实际耗时 SLA 约束。不保留后台信息补充。此显示优化不改变授权、绑定、派发重新验证或容量。它既不是原子文件系统基线，也不是可写保证；HEAD 只是当前提交，worktree 不是 OS 隔离。

bridge_health 区分 Bridge 响应与观察到的 Herdr 连接，报告实际注册工具，不含隐藏可调用性计数。

磁盘代码、运行中服务和客户端当前绑定的工具结构是不同证据。源码测试不证明部署或客户端刷新。任何单独授权的部署之前，应取得精确实时运行/Git 证据，并使用当前运维指令；绝不自动重启来从歧义恢复。

<a id="evidence-limits-and-retired-apis"></a>

## 证据限制与已退役 API

此公共源码树不包含私有验收产物或旧受管理生命周期实现。保留的发现、检出准入、在途保护和观察边界如上所述；源码测试检查其案例，不认证任何已部署宿主或客户端行为。

通用传输仍缺乏原子的 expected-instance 保护和 PID 出生身份。不重试是有意设计；通用结算既不证明任务成功，也不证明脱离子进程完成。移除 API 不增加更强保证。不保留 widget 等待片段或持久继续执行授权。扩展注入和提醒送达需要针对实际客户端绑定的独立实时证据。只有实际任务需要、证据和单独授权时才重新评估更强身份/连续性行为；已移除 API 不是恢复选项。

<a id="work-capacity-and-report-lifetime"></a>

## Work 容量与报告生命周期

每个精确且明确的 project_ref + 已注册 workspace_root 对有独立限制：

| 层 | 默认值 | 生命周期 |
| --- | ---: | --- |
| 活动 Work | 16（`MAX_ACTIVE_WORK_RECORDS`） | WORK_TERMINAL_STATES 之外的全部状态，包括预留和派发未知；绝不过期 |
| 终态回执 | 512（`MAX_TERMINAL_WORK_RECORDS`） | 数量压力下按 settled_at 最早优先过期，包括未读报告；相同时保留插入顺序 |
| 过期墓碑 | 512（`MAX_EXPIRED_WORK_RECORDS`） | 数量压力下移除最早过期项；只保留引用和项目/根绑定 |
| 内部交接 | 128（`MAX_HANDOFF_RECORDS`） | 观察器完成且终态锁存后允许立即释放引用 |

512 的默认值是有界运维选择，不是永久承诺或字节配额。没有 TTL 或保证的最短存留时间。报告读取和浏览器通知绝不续期。固定 delegate 通知批次只保留成员关系，不延长报告生命周期。顺序完成 Work 不会耗尽活动准入。未知/非终态 Work 仍计入活动准入。`_reserve_work` 在任何原生提示词前同步计数和插入，期间不 await。WorkRegistryFull 在提示词前报告 scope=project、dimension=work_active 及活动 count/limit。每个获准 Work 都分配专用报告。交接存储满时返回带 handoff_retained count/limit 的 WorkDispatchBlocked；从未派发的 Work 预留被丢弃。其他项目不占用此对的配额，不增加第二个全局记录池。

内部终态回执保留结算字段、提交不确定性、项目绑定、执行身份和 EvidenceCheckout。没有公共 await 端点或报告请求标志。内部重复回执在保留期间各字段相同。内部等待者已持有的 dict 即使注册表索引过期也仍有效；取消只分离该等待者。冻结检出身份不是文件内容快照；证据调用会重新验证它。

观察器完成回调只有在 Task 已完成且终态已锁存入 Work 后才释放交接。即使注入终态或压力先到，也从不取消运行 Task。回调注册处理快速完成并使用空回调上下文；注册表释放已完成 Task ContextVars 和候选快照的引用，不把 await 变成清理操作。仍运行的观察器保留交接，128 上限继续执行。

已知过期引用返回 WorkRefExpired。既无回执也无墓碑时（包括从未签发或重启丢失），WorkRefUnavailable 保留这些可能原因。错误项目的保留回执/墓碑返回 WorkRefProjectMismatch。过期只证明 Bridge 本地回执丢失，绝不证明任务成功/失败、外部停止、接受、取消或安全重试。不因此重新发现、改目标或重新提交。read/search/diff、新预览和未尝试提交共用此查找；过期引用绝不回退到 Agent 或注册根。在途证据持有已解析的冻结目标；后续查找/页面可能拒绝过期，但绝不悄悄另选目标。

候选存储和未知尝试隔离独立于 Work 保留。GC 既不移除候选，也不释放其隔离。已有 summary/patch/receipt 页面在当前项目授权之后，使用候选冻结目标和精确 project/work 路由。同消息已尝试回执重放返回完全相同的缓存结果。历史页面和重放都不进行候选 Git 修改/检查、Work 解析、重新捕获或重新绑定。入口仍先做当前项目授权/WorkspaceRegistry 身份验证，执行有界只读 Git 身份检查；整个调用并非不访问 Git。不同消息会被拒绝。WorkRefExpired 或 WorkRefUnavailable 后，此历史仍可读。未尝试提交仍要求 Work 被保留。候选在自身 8 条/32-MiB 策略下被逐出时返回 candidate-unavailable-no-recapture；未知尝试仍受保护。没有持久缓存，不固定延长 Work 生命周期，历史回执不证明外部停止或安全重试。新尝试期间过期仍保留现有拒绝/未知语义。

context 和 bridge_overview 的 project_state 展示紧凑 work_capacity 计数和策略，不在该容量字段列出引用。另行由 context 的 continuation_inbox 提供有界、匹配会话的保留分类视图，定义见[生命周期契约](#request-scoped-result-inbox-observation)。索引对每个保留 Work 存一个轻量事件，随已有 Work 丢弃/过期移除，不另设准入配额、送达所有者、保留固定、读取续期或消除机制。所有保留的已分类结果都可见，不论通知是否尝试或收到。可见不证明已检索报告或已处理结果。未知请求只暴露未绑定保留分类数量，绝不暴露其他会话引用。普通 Work 过期/丢弃仍移除事件；可见性不增加保护。这些观察是进程本地的，不是预留或 Git/Agent 原子快照。容量计数不认证内存字节、CPU 或跨进程隔离；记录数量上限不认证真实第二项目运行。没有 work_forget/prune 工具、持久 Work 存储、调度器或重启恢复。长期判断/证据属于项目记录，不应假设引用永久有效。

<a id="private-report-lifetime"></a>

### 私有报告生命周期

每个获准 Work 都请求向项目检出之外、惰性创建的每进程 0700 `/tmp/bridge-reports-*` 目录中的随机文件名发布报告。内部只保留该 Work 的私有文件名；公共回执和错误不暴露文件系统定位信息。Agent 从增强派发任务取得最终/暂存路径。能访问宿主私有路径是前提；Bridge 不配置沙盒或绕过发布拒绝。

`work_report` 验证项目身份和 Work 绑定，要求终态 Work，并通过不跟随符号链接、非阻塞的普通文件描述符，最多读取 1 MiB 加一个溢出检测字节。符号链接、特殊文件、多硬链接文件、无效 UTF-8、空报告、溢出或观察到文件替换/变化都会明确失败。Unicode 分页默认 4096、最大 16384 字符；expected_sha256 检查完整原始报告字节。前后 stat、路径绑定检查和哈希不隔离同用户 Agents，也不认证作者。发布报告不必与提供方最终消息相同。`work_report` 每次调用只观察一次，不等待发布或执行重试循环。锁存后、最终分类前，分类器探测 `WorkReportMissing`：初次读取后最多两次复查，约间隔一秒。增加的重试等待不超过五秒；该上限不保证 OS I/O 实际耗时。探测不续期。报告缺失或无效会分类为 `attention_required`。终态数量压力下，终态 Work 和报告（包括未读报告）按 settled_at 最早优先过期。浏览器队列不固定保留底层报告。

从未提交的 Work 丢弃和终态回执过期会尽可能 unlink 其最终/暂存文件。读取/清理串行化；过期与读取竞态可能让在途调用得到缺失报告，绝不会得到另一 Work 报告。读取不续期。整个服务器优雅关闭时，在正常 MCP/session-manager 拆卸之后、Uvicorn 重新抛出 SIGTERM 之前的 ASGI/MCP 应用 lifespan 拆卸期间，恰好关闭当前进程存储一次；幂等 close 仅 unlink 已知最终/暂存文件名，再尝试目录清理，atexit 作为次要的尽力安全网。崩溃、SIGKILL、断电、unlink/rmdir 失败、权限变化或迟到 Agent 写入仍可能留下孤立文件——此残余风险被明确接受；未知名称绝不移除，也不宣称安全擦除。没有启动扫描；重启从不扫描、恢复或清除旧孤立文件。没有持久存储、新 TTL、报告预留固定、自动重新提交或窗格回退。1 MiB 上限是读取/发布契约，不是针对外部写入者的 OS 磁盘配额。内部结算锁存保持不可变，独立于报告分类。读取报告既不消费送达资格，也不改变分配的分类。

回归覆盖：tests/test_work_retention.py、tests/test_work_capacity.py 和 Work/证据/候选测试套件检查合成后端与一次性 Git 行为。源码测试不认证已部署行为、实际提供方容量或外部写入者停止。

<a id="fixed-notification-batches"></a>

### 固定通知批次

一次 delegate 调用固定其通知成员。就绪批次可排队，同项目/同目标、已就绪且未尝试的提醒可合并。这不增加保留所有者、widget 认领、delivery-consumed 标志或确认 API。过期成员按现有报告契约保持不可用；不会重建或再次派发旧 Work 来补齐缺失证据。

<a id="chrome-notification-authority-and-recovery"></a>

## Chrome 通知权限与恢复

可选 MV3 扩展观察完成元数据，不观察报告正文或获得 Agent 执行权限。一个安装支持最多 32 个当前注册的本地项目。`prepare` 准备软件；通过 project-onboarding 注册及明确授权的 Project Binding 是独立操作。可信实时注册表提供规范 ref/root 身份，不需要另一个手动项目列表或重启。旧 v1/v2 配置在明确元数据范围迁移之前保留原范围；v3 授权未来注册。私有 0600 browser-notifications 配置和已安装 `connection.js` 共享独立的只读回环事件流能力，不是 MCP token 或运行时密钥。公共源码中的 connection 是 null。绝不发布这些私有字节。

用户选择已注册项目和一个精确的普通、非隐私 Chat（包含任何 Project 前缀），同意后点击**设为接收 Chat 并启用**。只能有一个普通标签页匹配完整路由。不猜最新标签页/标题/slug，不根据提示词自动绑定，也不广播。首次启用跳过更早完成事件：先绑定再委派。绑定只验证路由/文档身份，不输入或发送，也不证明页面可发送。弹窗显示收件目标/当前标签页/启用状态，不显示完整 URL，并提供当前可操作错误及未完成通知诊断。真实通知的已结束行、历史/回执控件和旧未知常驻警告已移除。Disable 保留待处理工作及抑制证据，等待该项目当前操作；它不能撤回不确定的在途修改。

明确选择新的当前 Chat 并授权启用，只更换未来接收方；切换期间不发送，也不重置游标/epoch。只有保存了有效路由、可证明从未尝试且没有意图/冻结证据的 queued/waiting 提醒，才可跟随首次发送。已尝试、不确定或冻结身份绝不迁移或重放，即使切回旧 Chat。已有真实历史安全规范化为原始 ID 抑制证据，而不是重新提供。被动旧未知记录，包括无法归属的旧尝试，不会暂停无关的新真实 Work。范围、游标、抑制 ID 畸形或真正有歧义的活动待处理状态仍会安全拒绝。

每个 ref/root 保留 epoch 范围内的事件流游标、仅活动未尝试或未选择队列，以及持久 consumed 原始 Work/batch ID。128 上限针对这个实际待处理队列，不是历史 deliveries。修改前先保存事件流进度；仅靠游标无法抑制 epoch 重置后再次出现的保留 ID。因此 consumed 身份跨 worker/浏览器重启、生产者 epoch 变化及明确接收方切换保留，不任意 GC。storage/配额失败仍会安全停止；不要清空证据绕过。

确认同步调用 Send.click() 后，本地只处理一次，绝不称为“ChatGPT 已收到”或服务器确认。点击后不扫描对话或验证用户消息回执。调用结果不确定时也抑制该身份，但不声称点击成功。这接受 ChatGPT 在点击后未投递而丢失通知的可能；两种情况都不授权自动重试。旧未知身份是静默证据，不占用历史行槽位。

真正空白且安全的输入框可自动发送一次。可见 Stop 表示繁忙；其他不安全输入框/路由/文档/控件条件按实际原因拒绝。活动 IME 阻止空编辑器自动 Send，但真实文字/富内容/文件附件草稿在打字或 IME 中也显示不抢焦点的 **追加到输入框末尾（另起一行） / 忽略** 选项。忽略保持当前草稿/文件不变。追加在活动组合结束后，只向当前绑定编辑器添加固定通知段落，不 Send、不压平内容，也不冻结草稿/File 快照；正常编辑及附件变化不需要静默计时器。不向 worker 发送草稿或文件内容。如果选择后、异步追加前用户先提交消息，旧选择会在修改前被拒绝。追加/ACK 结果未知时不重试。未选择的工作跨文档刷新/关闭保留；普通轮询会重新验证准确接收方并再次提供选项，或走当前安全的空编辑器路径。

不同项目绝不合并，即使同一 Chat。同项目/Chat 已就绪且未尝试的批次可共享固定通知，同时保留全部 Work 和批次身份。暂时报告失败阻塞该项目事件顺序；已排队候选可分别检查。任何 DOM 效果之前，持久意图先消费所选身份。旧通知版本仍可解析但不重放；新 v4 包含项目及完整 Work 引用。报告读取不等于 Principal 已处理的确认。

自动 Send 仍拒绝附件、归属未知的已选文件、错误/重复编辑器或主控件、绑定变化及并发编辑。安全撤回预填要求同一页面、绑定、编辑器和精确自有文本，且无外部提交干扰；节点/编辑变化或不确定效果仍被抑制。这些是本地 DOM 观察，不是服务器事务或未来恢复证明。commit 前或预填期间恢复的草稿会阻止 Send；点击前的 DOM 检查不能保证点击后不会恢复草稿。离线检查不授予发送权；缓存注册表数据不能授权新发送。根无效或同一 ref 改成其他根会拒绝，不继承 Chat 同意。storage 失败仍明确报告。

原生 IndexedDB 事务在发布前比较先前状态/修订值。单向 chrome.storage 迁移见证在数据库丢失时拒绝回退；原始旧存储仍是迁移来源。原生 Web Locks 将跨 worker 的 route→project 操作和同收件目标发送串行化。Worker 终止释放锁；数据库事务按原生语义完成或中止。没有 lock API 就拒绝，不按超时抢锁。暂停或旧的未知发送绝不因重启或迁移而变得安全。缺少可信旧根证明的旧记录保持禁用，等待重新授权；补充证明不会自动启用它们。诊断合成发送限于旧引导项目，保留原 scope/alarm；普通项目不获得诊断发送权限。

全新准备使用固定、带 key 的清单身份。旧安装接纳必须针对原加载目录单独授权：保留其 key 或无 key 路径身份、私有配对和历史，并备份审核代码。准备器从不修改浏览器存储；不安全权限或未知代码修改会停止更新。Chrome reload 是明确用户行动，不是源码测试结果。绝不要通过卸载、迁移或清空存储来绕过未知意图。

Alarm 通常每分钟唤醒 worker；不需要 Chrome MCP 或常驻 Codex。完整报告仍需要 Bridge MCP。合成 DOM/事务测试不证明真实送达、重叠 Chrome worker、宿主 UI 变化、非英语 DOM、后台门禁、节点替换或工具等待时序。实地验收仍须单独进行；不意味着 Work Chat/API 替代方案。参见[首次绑定](GETTING-STARTED.zh-CN.md#9-load-the-private-extension-and-bind-this-exact-chat)。
