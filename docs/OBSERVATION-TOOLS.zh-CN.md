<a id="direct-observation-tools"></a>

# 直接观察工具

[English](OBSERVATION-TOOLS.md) | [简体中文](OBSERVATION-TOOLS.zh-CN.md)

想让 ChatGPT **核查某个文件、比较改动、阅读 Agent 完整报告，或取回原文件**时，阅读本页。
可以直接用自然语言提出请求；下面保留工具名称，方便你辨认实际结果。

**第一次使用 Bridge？** 先完成[入门指南](GETTING-STARTED.zh-CN.md)，
其中分别提供**原生 Ubuntu 桌面**和 **Windows+WSL2** 路线。
Ubuntu 不需要 WSL 或 PowerShell。两种路线都在普通 **ChatGPT 网页项目对话**
中选择已连接的插件。本页没有额外安装或终端命令。

例如，指定授权项目中的一个非秘密文件，请求：

> 只读取我指定的文件，解释相关行。显示实际文件位置，并说明缺失或不完整的结果。
> 不要编辑、执行命令/测试、搜索其他文件或发送 Agent 任务。

**有用的结果应当是：** 内容来自正确的本地项目，且引用的行足以支持解释。
一句“检查过了”不是证据。路径错误、访问被拒绝或只收到一部分时，
应停止据此下结论，并说明限制。

## 先选你要核查的证据

| 你想做什么 | 在已连接项目对话中可改写使用的请求 | 应看什么结果 |
| --- | --- | --- |
| 读一个文件 | “只读指定文件，解释这些行。” | `read` 返回内容、路径和文件指纹。 |
| 在允许范围找文字 | “只在我指定的目录找这段原文，再读相关匹配行。” | `search` 返回位置；片段不是完整文件。 |
| 比较改动 | “显示指定文件的改动，解释实际 patch，不暂存或提交。” | `diff` 说明所选范围、剩余分页及错误。 |
| 评审 Agent 结果 | “读完这个 Work 的完整报告，再用我授权的证据核查主张。” | `work_report` 返回已发布报告，可能分多页。 |
| 取回原文件 | “将指定 PDF 作为原文件准备获取，并说明是否确实收到。” | `prepare_file_attachment` 返回临时链接，不是提取的文字或上传证明。 |

这些示例不授权扫描整个目录树、搜索私有/未跟踪文件、写入或向 Agent 输入。
先说清项目和允许的文件。只有想查看该目录的直接子项名称时，才请求 `list_entries`；
它即使不读正文，也可能列出被忽略或未跟踪的名称。
`inspect_file` 只检查一个文件的大小与指纹，不返回内容。

## 请求前：选对项目，认识不完整证据

- **项目标识（`project_ref`）：** 为你已授权本地仓库注册的短名称。
  单凭 ChatGPT 项目标题不能选中它。
- **任务标识（`work_ref`）：** 一项委派任务的记录。
  提供它会选择该 Work 记录的 **checkout（Git 工作目录）**，
  不会恢复过去的文件字节，也不证明 Agent 实际执行了什么。
- **SHA-256：** 完整原始字节的内容指纹。续读时使用同一个指纹可发现普通内容变化，
  不证明作者身份、内容正确，或整个项目处在一个原子快照中。
- **分页：** 较长结果分批返回。“下一个 offset”告诉工具从哪里继续；
  收到第一页不等于取得完整文件或报告。

直接读取证明观察到了哪些字节；Agent 报告说明它发布了什么。
单靠其中任意一项都不证明测试成功执行。验收这类主张前，
请求相关代码、测试定义和已授权测试的实际记录，不要为填补证据缺口而扩大到秘密内容。

## 读取文件或比较改动

**在已连接的项目对话中**，指定准确文件和问题，先检查返回的项目/目录再使用内容。

1. 文本按 `content_next_offset` 续读，并把相同 `file_sha256`
   作为 `expected_sha256`，直到读完请求范围。让 ChatGPT 处理这些字段，无需自己计算位置。
2. 搜索匹配后，沿 `read_locator` 在同一个项目/Work 读取相关行。
   默认只搜索 Git 已跟踪文件；没有明确授权，不要加入未跟踪文本。
3. 区分比较的是**当前文件**还是**两个固定提交**。
   当前搜索/diff 的各页都是新观察，调用间可能变化，并非保存的快照。
   过滤范围内“干净”只适用于该范围。
4. 哈希变化时，分开旧、新结果并重新判断。
   错误、超限或不完整页面不等于“没有改动”。

图片通过 `read` 整张返回，不按文本分页。
PDF/DOCX 使用 `read` 会得到 `UnsupportedReadFormat`，应改走下方原文件获取路线。
其他二进制或无效 UTF-8 文件可能返回 `BinaryFileUnsupported`。
不会自动提取或解析文档。

**受阻时停止：** 说明准确的缺失文件、不支持格式、内容变化或比较不完整。
不要悄悄换到另一个工作目录、调用已退役命令工具或扩大搜索。

## 读完 Agent 的完整报告

**某个 Work 进入终态，且其报告已发布并可读后**，用 `work_report` 请求该 Work 的报告。
同批其他 Work 可能仍在运行，浏览器通知也可能未启用。
`result_ready` 表示报告当时可读且 Agent 回合已结束；仍需判断报告主张。

通过 `work_report` 读完全部分页，使用返回的续读位置和完整报告 SHA-256。
续读是读完同一报告，不是轮询任务是否就绪。
`agent_terminal_read` 返回的终端尾部是当前诊断，不代替完整报告或完整任务历史。

**成功标志：** 已取回完整发布报告，能指出哪些独立证据支持或反驳它。
**受阻状态：** 缺失/无效报告或 `attention_required` 需要诊断；
`WorkRefExpired` 或 `WorkRefUnavailable` 不会改选另一项目。
不要为了拿到报告重发任务。读取既不确认结果已处理，也不延长保留期。

## 取回 PDF 或其他原文件

**在已连接的项目对话中**，指定获授权文件，请求取回其原始字节。
**ResourceLink** 是 `prepare_file_attachment` 准备的临时获取链接；生成链接不会上传文件。

- **不超过 7 MiB** 返回一个保留原名称的链接。更大原件返回按序分片链接，
  和一份**回执**，列出原名称、完整大小、SHA-256 与分片名。
- 分别收到分片不等于收到原件。接收方必须找到实际生成的文件，
  按回执顺序拼接，再核对完整大小和 SHA-256。Bridge 没有自动网页组装器。
- 准备/获取成功不证明批准、ChatGPT 导入、附件或 File Library 中已出现文件；
  宿主必须实际支持并完成这些步骤。

**成功标志：** 原件或拼接后的原件在接收端存在，且已核验。
**受阻状态：** 链接过期、源文件变化、分片失败，或宿主无法导入/拼接时，
说明“尚未验证收到完整原文件”。再次准备前先检查现状，
不要把不完整且未核验的文件当成原件，也不要保证任意大文件都能传完。

## 精确读取与附件契约（进阶）

下列内容供开发者或需要核对准确限制、错误的人使用。
“源码契约”描述实现行为，不表示已经测试你当前的服务或 ChatGPT 账号。

<details>
<summary>进阶：准确工具目录、读取/搜索边界和原文件传输</summary>

这些是源码（SOURCE）合同；当前运行环境或宿主验收需要另行举证。SOURCE 目录注册了 18 个面向模型的工具；三个已退役、仅限 App 的 widget 工具不在其中。所有已注册工具都在实际 SDK 验证器中拒绝额外参数，再进入工具函数。Annotations 描述效果，不表示授权，也不保证客户端批准。

显式指定 project_ref。可选 work_ref 固定已有记录中的检出目录，不是文件快照，也不证明原任务内容真实。未知或被替换的 Work 不会回退主树。现有读取门和目标重新验证仍适用。

| 意图 | 工具与重读方式 |
| --- | --- |
| 发现目录 | list_entries(path=".", offset=0, limit=50)。仅直接子项；沿返回条目路径和 next_offset 继续。各页是新鲜观察，按 Unicode 名称排序。 |
| 读取文本 | read 默认 4096 个 Unicode 字符，最多 16384。用 content_next_offset 和 expected_sha256=file_sha256 继续，以拒绝原始字节变化。可选的绝对、从 1 开始且含末行的 end_line 将页限制在完整表示的该行内（超过 EOF 时钳制）；可单独使用、与 start_line 搭配，或用于非零 offset 续读。图像以完整原生块返回，最多 5 MiB，另加一个紧凑元数据文本块，没有 structuredContent。 |
| 拒绝 PDF/DOCX | read 在读取任何字节前按已验证后缀（不区分大小写）拒绝 PDF/DOCX（UnsupportedReadFormat），并指向 prepare_file_attachment 获取原文件；不批准、解析或组装附件。其他二进制或无效 UTF-8 内容仍返回 BinaryFileUnsupported，并给出相同引导。 |
| 获取完整 Agent 报告 | 每项获准 Work 都要求报告。某个 Work 进入终态，且其报告已发布并可读后，就可用 work_report 读取该 Work 的报告，以 Unicode offset/limit 和 expected_sha256 分页续读。其他 Work 可能仍在运行，浏览器通知也可能未启用。报告缺失或无效需要处理；只读取已发布的私有文件。 |
| 查找一行 | search 默认搜索跟踪文件。include_untracked=true 另搜索未被忽略的未跟踪文本。两条分支共享一个字面量模式查询验证（1..500 字符，无 NUL/LF，有效 UTF-8；模式以显式 `-e` 操作数和字面量 pathspec 传递），并返回每个匹配的原始前 ≤300 个 Unicode 字符（去除记录结尾 LF；保留 CR/空白，不添加虚构标记或省略号）、`line_text_truncated`，以及同一 project/work_ref 的 `read_locator` {path,start_line}。格式错误或非正数 grep 行记录，以及带有输出的无匹配状态都会被拒绝。片段不证明完整文件内容。 |
| 检查二进制或大型文本 | inspect_file 给出常规文件的 mode、byte_size 和完整原始字节 SHA-256，不返回内容。这不会使二进制文件可作为文本读取。 |
| 准备原始字节 | prepare_file_attachment 对当前源码文件计算哈希，并准备有期限的 ResourceLinks，供之后 resources/read 获取；此时尚未上传、导入宿主、组装或附加。<=7 MiB 返回一个原始名称/MIME 链接，不含 TextContent；否则返回按序 octet-stream 链接和仅含 multipart {target, size, sha256, parts} 的回执。内部元数据查找和有界分片获取保留源 stat/path 及分片哈希检查；源码机制见[附件合同](TECHNICAL-REFERENCE.zh-CN.md#original-file-attachments)；实际宿主验收需要独立检查。 |
| 发布连续性状态 | 先读取 manifest 状态，再调用 current_state_update，必须提供 expected_revision，并且只提供 content 或 edits 其中之一。这是状态发布，不是 Git 提交，也不验证给出的主张。选择加入的 bridge-state-slot 增加机械化的正文字节及限制身份拒绝检查；不自动总结或截断。 |
| 检查更改 | diff 使用[Work 证据](#work-target-evidence)中现有的当前或固定提交合同。未知不等于干净。 |

目录列举最多扫描 4096 个直接条目或 1 MiB 名称字节，每页最多返回 100 项，排除 .git。它列出被忽略及未跟踪名称，不打开内容。报告链接和特殊文件，不跟随它们。Inspect 以有界块最多哈希 64 MiB，检查前后 stat 和路径绑定；变化、过大、特殊或链接目标都会失败，不给出貌似完整的哈希。两种工具都将序列化结构化封装限制为 32 KiB；名称不会截断。协作式文件系统期限为 10 秒，不是内核阻塞 SLA。

显式加入的搜索使用两次固定 Git 查询，共享 5 秒期限、1 MiB 合计 stdout 和 4096 字节 stderr 上限；其中一次保留受跟踪但匹配忽略规则的文件。结果对匹配路径/行去重，并拒绝矛盾的重复行。每页最多 50 个匹配，片段 300 个 Unicode 字符，最大匹配 offset 为 100000；查询是 1..500 字符、无 NUL/LF 的单个字面量模式，以显式 `-e` 操作数和字面量 pathspec 传递。两个分支都显式关闭 grep 颜色及列输出（`--no-color`、`--no-column`），避免环境中的 `color.ui`/`color.grep`/`grep.column` 配置向路径或片段注入字节。带编号的 NUL 路径记录会被验证：不完整、非正数、过长行号或无匹配退出却有输出，都会失败且不声明覆盖完整。片段是原始解码前缀，不添加虚构截断标记。结构化封装最多 32 KiB。

搜索排除未跟踪且被忽略的文件、二进制内容及递归子模块工作树。目录和路径定位保留字面量名称，包括为根目录纯空白名称保留 ./。搜索和当前 diff 页面都是新鲜、未固定的观察，没有一致性令牌或保留快照。读取、图像及跟踪搜索的元数据不会请求检出目录脏状态，也不打开或哈希无关的脏文件及未跟踪内容。读取完整性使用所选文件的 SHA-256；历史 diff 页面可使用精确解析出的 base/target commit ID。

固定 Git 观察禁止传输协议（包括隐式 partial-clone fetch），关闭 fsmonitor/hooks/pager/textconv，遇到 clean/process filter 配置则返回 unsupported。不请求永久配置或索引写入：diff 观察还在命令级禁止 Git 的索引自动刷新写入（`diff.autoRefreshIndex=false`），因为即使用 --no-optional-locks，该刷新仍会重写实际索引，改变所选 prepare 冻结的精确暂存索引。Diff 输出不变；stat 标脏的条目仍比较内容，只是不写回。Status/diff 不检查嵌套子模块工作树脏状态。查询错误或溢出属于不完整观察；read 不请求 Git status 也仍可返回文件内容。探测、查询与文件系统检查不对外部写入者构成原子操作；不隐含 OS 安全隔离，也不保证整个工具的延迟或内存上限。

MCP structuredContent 将必要结构和内容传递一次。仅移除已证明序列化了相同载荷的文本；不同文本和原生图像块保留。`prepare_file_attachment` 对 <=7 MiB 返回一个 ResourceLink，不含 TextContent；否则返回按序分片链接和恰好一个仅含 multipart {target, size, sha256, parts} 的紧凑回执：原始 basename、完整字节数/SHA，以及按序物化分片名称。工具结果没有正文/base64、outputSchema 或 structuredContent。

原始分片上限仍为 7 MiB（7340032 字节）：约 9.33 MiB base64，在示例 10,485,760 字节中继响应预算下为开销留下约 0.67 MiB。这个余量不是官方原始文件大小限制。任意的 128 MiB 原文件上限及 128 项附件计数/淘汰已移除；实际期限和传输容量仍适用。resources/read 每个分片仍只返回一个 base64 结果。没有标准流式传输/重组或公共范围 API，只有有界内部读取器。

每个原文件对应一个内部 PendingAttachments 元数据项，有有限过期和 GC，不续期、不跨重启持久化，不含文件字节；成功结果不含 TTL/retention/status/provenance。准备时计算全文件及各分片哈希；expected_sha256 固定完整原件。获取时检查已保存的 stat/父级身份、分片哈希和长度，以及前后描述符/stat/path/查找的过期和身份。普通的任意位置修改会安全拒绝；若伪造所有被观察身份和时间戳，可能隐藏获取分片之外的编辑。最终仍必须验证完整 SHA。

单文件使用 bridge://attach/{capability}；多分片使用规范 /part/0001 序号（可超过 9999）和确定性名称。接收方按回执顺序拼接物化分片，并核对完整 SHA/大小。Bridge 不增加自动 Web 组装器或物化后钩子；组装仍需要 Web 侧编排。`view_image` 已从 SOURCE 退役；read 是原生图像路线（完整原生图像加一个紧凑 JSON 文本元数据块，无结构化结果）。源码和 wire 测试不证明宿主文件导入、批准行为或视觉识别。投递、attention、收束和退出码描述观察，不是任务验收。公共 run 已从 SOURCE 退役；现在由窄范围 commit_prepare/commit 实现版本操作。精确连续性 CAS 规则见[项目连续性](PROJECT-CONTINUITY.zh-CN.md)。

read、默认 search、当前/固定 diff 的读取租约持续到 worker 结束，即使反复取消也是如此；current_state_update 和 commit 复用同一个等待完成边界。若 worker 后来失败，仍保留原始取消结果。这不是 OS 期限。候选 summary/patch/receipt 页面包含捕获事实，而非今日的脏状态投影；见[候选版本操作](#candidate-version-actions)。

公共 read **没有文档提取路线**：它在读取任何字节前，按已验证后缀拒绝 PDF/DOCX（`UnsupportedReadFormat`），并指向 prepare_file_attachment 以获取原件。prepare_file_attachment 仅返回原文件链接/回执；不解析文档或生成可读文本，也不会被自动调用。仓库没有文档提取工具；历史提取行为不是现行公共合同。

`agent_terminal_read` 接受 1..400 行（默认 120），字符上限为 16 KiB。`truncated=false` 仅描述返回尾部的该项上限，不证明历史完整或报告内容完整。每项获准 Work 都请求专用报告；该 Work 进入终态，且其报告已发布并可读后，就可用 `work_report` 读取该 Work 的报告。其他 Work 可能仍在运行，浏览器通知也可能未启用。缺失或无效报告属于 attention，不是任务成功完成。

</details>

<a id="direct-project-text-edits"></a>

## 直接编辑项目文本

仅在你已授权修改某个已有文本文件时使用本节。要求查看文件本身不授予编辑权限。

可以先请求：“读取这个文件，展示准确的替换建议，先不要应用。”
审阅建议及原文件指纹后，再授权 `project_text_edit`。
它对已有 UTF-8 文件做准确替换，不是创建文件或执行命令的接口。

**成功标志：** 回执列出目标、修改前后哈希、字节数和编辑数量。
这证明有界编辑，不证明修改后的代码正确。
**受阻状态：** 哈希过期或替换含糊时，重新读取并协调建议；
写入后结果未知时，应先检查，不要盲目再次应用。

<details>
<summary>进阶：准确编辑签名、验证、竞态与状态槽边界</summary>

project_text_edit(project_ref, path, expected_sha256, edits, work_ref=None) 仅更改已存在的常规 UTF-8 项目文件。必须提供完整小写 64 位十六进制 SHA256，不带当前状态的 sha256: revision 前缀。使用实际读到字节的哈希。提供 1..256 个精确 {old_text,new_text} 对象：old_text 非空、在同一原件中唯一，且互不重叠；替换针对该原件一次应用。文件及结果 <=1 MiB，合计 old/new 编辑字节 <=2 MiB。拒绝 NUL/二进制、无效 UTF-8、链接/特殊文件、.git/路径穿越、创建、目录及模式变化。未改动字节、CRLF 和原始模式保留；不规范化、不执行命令/钩子、不暂存或提交。

显式 project_ref 和可选 work_ref 解析到与 read/search/diff 相同的冻结证据检出目录。现有写租约覆盖受取消屏蔽的 worker，直到清理完成。No-follow 描述符遍历固定父级绑定；原子替换前立即重新检查完整源哈希及文件身份/模式/时间戳。成功仅返回目标来源、哈希、字节数和编辑数量。替换后的观察/fsync 失败或确认丢失属于 unknown，绝不盲目重试。这些检查串行化协作 Bridge 写入者，不约束外部进程：检查与替换之间仍有竞态窗口。回执证明有界字节，不证明作者已认证、内容真实或验收通过。current_state_update 保持独立的仅限 manifest、65536 字节、完整内容/精确编辑及缺失时创建合同。

当状态文件选择加入一个 bridge-state-slot 时，同一次发布还会拒绝格式错误、移除、扩大、缩小或超限的 slot，不写入任何内容。此编辑器不改变 manifest 路由。project_text_edit 仍是精确编辑旁路。

</details>

<a id="candidate-version-actions"></a>

## 候选版本操作

仅在你明确要准备或完成 Git 提交时阅读。
**候选（candidate）**是捕获后供评审的暂存内容；**索引（index）**是 Git 暂存区；
**回执（receipt）**记录一次尝试的结果。

**准备可能改变暂存区。** 只读评审时不要请求它。
先说：“显示这些指定文件的当前改动，不暂存或提交。”
看完后，再授权某一种明确的准备模式。

| 模式 | 实际作用 |
| --- | --- |
| `commit_prepare` 提供 `paths` | 暂存选定的字面路径并固定候选，可能写入 Git 对象。 |
| `commit_prepare` 省略 `paths` | 捕获已有暂存内容，不改变仓库；空列表不代表此模式。 |
| `commit_prepare` 提供 `candidate_id` | 读取保存的候选页面，不重新捕获或暂存。 |
| `commit` | 使用已配置 Git 身份和明确消息，提交该准确候选。 |

先审阅保存的摘要和所有所需 patch 分页，再单独授权准确提交。
截断 patch 没有显示全部改动字节，二进制内容可能只有元数据。
候选 ID 和“可供评审”都不授予权限。

**成功标志：** 区分“候选已准备”与“提交已有回执”。
**拒绝/未知：** 查看已有候选回执和当前获授权证据。
响应丢失、ID 已使用、Work 过期或缓存缺失，不授权创建替代候选或重试变更。
下方精确规则对同一个已尝试请求只返回旧回执，不重新执行，也不提供跨重启恢复。

<details>
<summary>进阶：准确准备/提交模式、上限、索引验证与回执重读</summary>

commit_prepare(project_ref, paths=None, work_ref=None, candidate_id=None, view="summary", offset=0, limit=50) 有三种明确模式。提供 paths 时，准备 1..2048 个精确字面量的仓库相对常规文件路径（UTF-8 路径字节合计最多 16 KiB，捕获内容合计最多 4 MiB）。2048 路径复杂度上限约束临时 inode、捕获记录及重复文件系统验证；超出数量返回 selection-path-count-limit，与 Git 查询次数无关。支持普通跟踪修改、新文件和明确的跟踪删除；不允许 glob、pathspec magic、目录递归、.git/路径穿越、符号链接/特殊文件或任意 argv。实际文件名中的元字符保持字面含义。拒绝选择范围之外的暂存路径、所选内容混有暂存和未暂存状态、intent-to-add，以及所选 assume-unchanged/skip-worktree 标志；有意的部分 hunk 暂存保持完整。无关工作文件保留。

准备先私下复制真实索引，并在对象写入前捕获每个所选文件。私有临时目录仅保留捕获字节，存入最多 2048 个生成的常规文件。一次 hash-object -w --no-filters --stdin-paths 调用写入原始 blob；生成的 ASCII 名称通过 stdin 而非 argv 传递，避免随数量增加的 ARG_MAX 压力和用户路径引号/选项风险。每个返回 SHA-1 或 SHA-256 OID 都必须依序匹配捕获哈希。Git 创建对象时绝不重读所选工作树文件。删除不需要 blob，纯删除选择不调用 hash-object。正常或异常退出展开时删除临时副本。之后才更新私有索引。

候选、政策、选择和缓存验证先于真实索引安装。在 Bridge 写入门及 Git index.lock 下，重新检查所选字节/绑定、政策、目标、HEAD/分支和完整真实索引哈希，再原子安装已准备索引并确认快照。只有锁和外层准备目录都清理成功后，才插入缓存并发布 candidate-ID。安装前拒绝会保留真实索引不变，但对象可能残留。准备分别报告 index_updated/objects_may_remain/ref_updated，绝不移动 refs。安装或清理不确定时返回 unknown，不发出可发布候选，并在进程内隔离该检出目录/分支；既不回滚也不重试。不提供跨重启持久性或自动对账恢复。

所选路径准备暂存原始字节：明确拒绝所有已配置且非空的 clean/process filters，即使是无关驱动；也拒绝活动 post-index-change 钩子（除现有提交钩子外）、core.autocrlf 转换，以及所选 filter/text/eol/working-tree-encoding/ident 属性。不支持的助手会被拒绝，不会默默运行或省略。钩子准入检查后，私有 update-index 使用固定的禁钩子覆盖，防止检查与使用间隙中新引入的钩子运行；原始 hash-object 绝不调用内容过滤器。转换支持是未来范围决策，不是通用 Git add 逃生口。现有配置身份及 R3 仓库/存储限制仍适用。每个操作保留 30 秒期限和有界子进程输出。所选准备保留固定 96 次 Git 观察上限（已有暂存捕获仍为 64）；blob 写入无论文件数多少均只消耗一次调用。捕获内容总量溢出返回 selection-total-byte-limit，路径字节总量溢出返回 selection-path-byte-limit。

省略 paths（或用 null）时，不写仓库，仅捕获已有暂存索引；此明确模式保留现有部分 hunk 工作流。空列表会被拒绝。提供 candidate_id 时必须省略 paths：对不可变捕获的 summary/patch/receipt 分页，不查 Work、不取门、不观察 Git、不重新捕获，也不写仓库。新准备候选报告 "Commit candidate ready for review"，并列出 index_updated/ref/objects 效果事实；缓存候选分页报告保存的候选页，该响应不暂存或重新捕获；rejected/unknown 仍如实给出原因。初始状态 previewed 表示冻结候选可供审阅，不表示许可或任务验收。没有公共 commit_preview 或 stage_paths 兼容别名。

summary 按文件计数，列出每条暂存路径及 status、modes、object ids、暂存 blob 大小（gitlinks/缺失对象为 null）和由一次合计 numstat 查询得出的 binary 标志。patch 按 Unicode 字符计数，只是有界显示证据：二进制文件显示 Git 的 "Binary files ... differ" 行；合计文本超过显示上限时以显式截断标记停止（`patch_truncated`/`patch_complete`）；无效 UTF-8 以替换方式解码（`patch_decode_lossy`）；显示丢失则用原因标记 `patch_unavailable`。这些都不使冻结候选无效，不阻止 summary，也不阻止精确提交。候选身份是暂存索引/树/父提交/分支/政策快照，绝不是 patch 字节。limit 为 1..16384，文件/事件每页最多 100。用 candidate_id 和相同 project/work 路由继续；页面来自捕获候选，不是新的脏快照。需要今天的证据时仍可使用 read/diff。

commit(project_ref, candidate_id, message) 使用该暂存树、配置身份，以及明确的非空 UTF-8 message（最多 65536 字节，无 NUL）。它创建对象，以一次 mktree -z --batch 物化捕获的 mode/OID/name 条目（子树先于父树），检查每个返回 tree OID，再使用 commit-tree 和父 ref CAS。它绝不使用 write-tree，也不为 commit 刷新工作树或索引；工作文件与真实索引保持其字节，包括未暂存更改。每次调用包括回执重放，都适用现有项目检查。ID 不赋予权限；ID 缺失或目标变化不会重新捕获。已有暂存捕获使用读取门；所选准备和 commit 使用写入门，加精确候选目标、快照及索引/ref CAS 重新验证。worker 执行和清理在租约释放前完成，包括取消情形。

重复相同请求仅返回旧回执。rejected、unknown、committed 是不同结果；即使拒绝，对象仍可能残留，而 unknown 不证明 ref 是否变化，也不允许再尝试。取消或响应丢失时应检查现有候选回执，不是自动启动另一候选。缓存是进程本地的（8 项/32 MiB；unknown 尝试不淘汰），不是持久恢复或全局幂等机制。

实现支持有界的本地 Linux/files-ref 仓库，且需要已配置身份。遇到不支持的签名、fsmonitor、split-index、promisor/alternate storage、间接元数据，以及活动 pre-commit/prepare-commit-msg/commit-msg/post-commit 和 reference-transaction 钩子会拒绝，而不是压制它们。对于已有暂存捕获和最终提交，不拒绝 post-index-change 或 post-checkout：此暂存对象原语不会调用它们。所选准备按上述要求拒绝活动 post-index-change 钩子。已有暂存捕获/commit 不执行匹配的必需 process/clean filters；不是通过关闭过滤器配置来获得此行为。R2 的私有索引 write-tree 可能执行匹配的 process 助手，现已被替代。固定工作文件观察保持自身的不支持过滤器边界。这里的任何实现限制都不定义其他仓库的本地能力上限。

每条 Git 流最多 4 MiB；操作工作预算为 30 秒、最多 64 次查询；捕获的 mktree 批次与预期 OID 输出各有 4 MiB 上限，并计入缓存。清理或 OS 调用限制不是总延迟的硬 SLA。外部写入者及共享 refs/config 可能在检查之间竞态；工作树不构成 OS 安全隔离。没有增加公共 path/argv/env/approval-token 参数，也没有通用宿主命令替代。

最终提交准入只容忍一种实时索引变化：普通 status 式 stat-cache 刷新。有界 v2/v3/v4 索引解析器验证格式、末尾校验和及布局，包括条目模式（拒绝 040000 稀疏目录条目）；声明的名称长度必须等于各版本完整重构名称的长度（在 0xFFF 饱和，按 UTF-8 字节计）；名称约束及严格 (path, stage) 顺序；NUL v2/v3 填充；保留的扩展标志位；未知强制扩展（签名首字节非大写者；原生 Git 忽略首字节大写的未知扩展）；以及 split-index "link" / sparse-index "sdir" 扩展。它比较规范化身份，仅将各条目的 time/mtime/dev/ino/uid/gid/size 清零；路径、模式、OID、stage、assume-valid/skip-worktree/intent-to-add 标志、填充和原始扩展字节逐字节精确比较。v4 名称按 Git 从前一名称末端剥离的语义重构。

捕获时对锚点及 prepare 时实时原件各验证一次，因此即使原始索引字节没有分歧，不支持的布局也会被拒绝。加锁前的观察可以经历多次纯 stat 刷新；最终加锁准入时，验证最新符合条件的实时索引字节并封存为原始基线，随后关闭准入：从封存经过 mktree、commit-tree、update-ref 到 CAS 后重验证，每次检查都逐字节精确。首次封存后分歧在 ref 变更前拒绝；update-ref 后的分歧仍如实保持 unknown。捕获索引绝不重新安装，commit 本身不写索引。所选路径 prepare 安装及 preview 保持严格原始字节 CAS。

Work 路由使用有界进程本地回执：每个 project/root 保留最近 512 个终态，不因读取续期。过期 ref 拒绝且不回退目标；原因已不可知的缺失 ref 返回 WorkRefUnavailable。候选缓存和 unknown 尝试隔离在 Work 过期后仍保留。现有 summary/patch/receipt 页面在项目授权和精确 candidate project/work 匹配下，只读缓存并使用冻结目标。历史页及字段稳定、同 message 的已尝试回执重放，不做候选 Git 修改/检查、不解析 Work、不重新捕获或绑定。但入口仍先做当前项目授权和 WorkspaceRegistry 身份验证，这会执行有界只读 Git 身份检查；不能说整个调用完全不涉及 Git。不同 message 会拒绝。新的准备和未尝试提交仍需要 Work。候选淘汰返回 candidate-unavailable-no-recapture；这些历史缓存不意味着可安全重试。context/bootstrap 提供紧凑容量计数；不新增 Work 清理工具或破坏性 await 模式。见 [Work 容量](LIFECYCLE-RESTART-CONTRACT.zh-CN.md#work-capacity-and-report-lifetime)。

</details>

<a id="work-target-evidence"></a>

## Work 目标证据

文件来自错误位置、较长结果不完整，或想核对究竟检查了什么时，使用下面的索引。
整个读取过程都要明确保持同一项目/Work 选择。

### 选择项目或 Work 记录的目录

Work 选择记录中的目录，不是所有文件的历史副本。目录缺失、被替换或不可用时应失败，不能改选主项目。

<details>
<summary>进阶：目标准确身份与 read/search/diff 签名</summary>

`read`、`search`、`diff`、`list_entries` 和 `inspect_file` 接受可选 `work_ref`。省略时选择显式注册的 `project_ref` 根目录。提供的 Work 必须属于该精确 project/root，并携带不可变证据元数据：在现有写入门保护下绑定时、紧接交接或提示前捕获。`EvidenceCheckout` 只存检出路径和已有 `GitWorktreeIdentity` 字段。捕获失败使元数据不可用，不改变派发。通用 Pi 和其他提供商共享已报告/前台的同 common-Git 检出验证。有前台执行时选择它；会话元数据不会覆盖该检出目录或允许回退。Work 独立于后续 Agent 发现，冻结此精确链接检出目录；移动或替换仍安全拒绝。

`_resolve_evidence_target(project_ref: str, work_ref: str | None = None)` 返回 `EvidenceTarget | dict[str, Any]`（结构化错误）。它重新验证已注册项目身份、保存的检出身份，以及精确 Git common-dir 路径/设备/inode。绝不查询当前 Agent 或 handoff，不注册路径、创建检出目录或恢复 Work。在有界回执仍保留期间，终态 Work 在 handoff 清除后仍可用。较早或未绑定、没有元数据的 Work 不可用。未知 Work 如实表示从未发出或重启后丢失。检出目录缺失或被替换时，即使路径或仓库名称相同也会失败。使用目标现有读取门，取门后再次检查身份。

```python
read(project_ref, path, offset=0, limit=4096, work_ref=None, start_line=None,
     expected_sha256=None, end_line=None)
search(project_ref, query, path_prefix=None, max_matches=20,
       work_ref=None, match_offset=0, include_untracked=False)
diff(project_ref, path=None, view="summary", staged=False, offset=0, limit=32768,
     work_ref=None, base=None, target=None)
```

</details>

### 继续读文本，处理格式错误

沿返回的续读字段，使用同一原始字节指纹。被限制的结果只涵盖请求范围。readOnlyHint 一类客户端提示描述行为，不授予访问权限，也不保证出现批准对话框。

<details>
<summary>进阶：行/字符范围、图片格式与结果序列化</summary>

文本读取接受以 LF 分行、从 1 开始的 `start_line`，或 Unicode 字符 offset。非零 `offset` 与 `start_line` 同时提供有歧义，会被拒绝。可选 `end_line` 是完整表示中从 1 开始、包含在内的绝对末行；可单独使用、与 `start_line` 搭配（不能小于起始行），或用于非零 offset 续读。超过 EOF 时钳制到 EOF 而非失败。页绝不越过所选上限；续读用返回的 offset 重复同一 `end_line`，不提供 `start_line`；达到上限后 `content_next_offset` 为终止状态。输出包含 `content_offset`、`content_end_offset`、`content_start_line` 和从 1 开始的 `content_start_column`；用 `content_next_offset` 继续，不带 `start_line`；发送 `expected_sha256=file_sha256` 以拒绝读取之间的字节变化。全文件 SHA-256 覆盖原始字节，包括 CRLF。末尾 LF 会有一个空 EOF 行位置；请求超出最终位置会失败。图像保持原生整图响应，拒绝行/字符分页。PDF/DOCX 在读取正文前按已验证后缀拒绝（`UnsupportedReadFormat`）；其他二进制或无效 UTF-8 文件保持 `BinaryFileUnsupported`，附简短 prepare_file_attachment 引导。

`read` 为有界注册文件系统操作声明 `readOnlyHint=true`、`destructiveHint=false` 和 `openWorldHint=false`。这些是客户端提示，不是权限、许可政策或 UI 行为保证。它不发布 outputSchema；SDK 参数验证及额外参数拒绝不变，文本页和应用错误保留 structuredContent 元数据，私有元数据模型在序列化前验证每项结果。已证明重复的 JSON 文本被移除；独有解释与中性的简短摘要并存。图像成功返回原生图像内容及一个含完整元数据 dict 的紧凑文本块，无 structuredContent、元数据中无 base64，也没有结果包装器。原本缺失字段仍缺失；可空的续读/来源值仍为 null。

应用错误不会变成协议 `isError` 结果；SDK 参数/协议失败保持区分。所有已注册参数模型都拒绝额外字段。Offset 非负，文本 limit 为 1..16384 Unicode 字符，整图保持现有 5 MiB 上限。验证是结构性的，不证明任务成功或认知能力。源码变化之后，必须另行授权刷新运行环境/客户端，才能声称当前客户端显示已变化。

描述符与结果的区别遵循 [OpenAI 工具参考](https://developers.openai.com/plugins/reference)；[开发者模式](https://developers.openai.com/api/docs/guides/developer-mode)说明客户端如何使用 readOnlyHint。

`view_image` 曾是 Web 兼容路线：相同读取门、目标重验证、nofollow 描述符读取、后缀/magic 检查及 5 MiB 图像上限；不声明 outputSchema，成功返回一张原生图像加一个紧凑 JSON 文本元数据块，失败仅返回文本错误元数据。它已从 SOURCE 退役；read 保留该图像序列化器及文本/错误 structuredContent。Read 是唯一原生图像路线。SDK/wire 证据不证明 Web 客户端的视觉识别。

公共 read 不再提取 PDF/DOCX：此类请求在读取任何字节前，按已验证后缀（不区分大小写）以 `UnsupportedReadFormat` 失败；`prepare_file_attachment` 用于准备原件供之后获取，read 不批准、解析或组装原件。历史提取实现已退役，仓库没有提取工具。历史提取行为不是现行公共合同。上限和重读见[观察工具](OBSERVATION-TOOLS.zh-CN.md)。

</details>

### 理解报告何时可用

发布报告是 Agent 编写的证据。缺失或无效发布属于明确问题，已就绪分类不认证其内容。

<details>
<summary>进阶：报告签名、发布、分类与保留期</summary>

`work_report(project_ref, work_ref, offset=0, limit=4096, expected_sha256=None)` 仅在 Work 进入终态后，读取为该获准 Work 分配的私有报告。它验证当前注册项目及精确 Work 绑定，不验证当前 Agent 或检出内容。不公开原始路径选择器。发布指令还要求 Agent 在任务指定格式内，将结论、决定性证据和重要限制置于报告开头；Bridge 不解析、评分、认证或拒绝报告结构，文件仍是完整、自由格式的观察内容。1 MiB 原始字节的 SHA-256 固定 Unicode 续读（每页最多 16384 字符）。缺失、未请求、非终态、过大、空、无效 UTF-8、符号链接/非常规文件、已变化和不可用报告都是明确错误；不回退终端尾部。来源表示 Agent 发布的观察内容，不表示任务成功、作者已认证或与提供商逐字节一致的转录。

报告文件和 Work 都是进程本地的；[Work 容量](LIFECYCLE-RESTART-CONTRACT.zh-CN.md#work-capacity-and-report-lifetime)负责清理和过期。此工具不增加持久报告归档或文件发布端点。可选通知批次为 `result_ready` Works 指定 `work_report`，为 `attention_required` Works 指定 `agent_terminal_read`。这是通知中的引导，不是报告读取门槛：某个 Work 进入终态，且其报告已发布并可读后，`work_report` 就可读取该报告；其他 Work 可能仍在运行，通知也可能未启用。批次就绪及其通知都不认证任务成功。发布与收束是独立观察。`work_report` 本身不等待，也不运行自动重试循环。分类在 latch 之后、最终分类前探测专用报告：仅对 `WorkReportMissing`，初次读取后最多再检查两次，约间隔一秒，增加的等待在五秒以内。该上限约束注入等待，不是 OS I/O 实际耗时。其他错误立即分类。`readable` 加 `agent_turn_settled` 为 `result_ready`，仅证明存在。缺失或无效报告是 `attention_required`。探测不是自动 Principal 循环。

</details>

### 沿搜索位置继续读取

匹配指向待核查的一行；短片段可能缺少关键上下文，下一页也可能观察到之后的文件状态。

<details>
<summary>进阶：字面搜索、片段与新鲜分页边界</summary>

Search 在解码前解析 Git 的 filename-NUL/line-number-NUL/content-LF 记录，因此文件名中的冒号和换行不丢失匹配。每个匹配含 `read_locator`（`path`、`start_line`）；复用相同 project/work ref。它覆盖受跟踪的当前文件，包括匹配忽略规则的跟踪文件，默认排除未跟踪/二进制文件。显式 `include_untracked=true` 通过两次有界查询增加未被忽略的未跟踪文本，同时保留受跟踪但匹配忽略规则的文件。显式加入时的上限及目录/哈希工具见[观察工具](OBSERVATION-TOOLS.zh-CN.md)。

行片段是解码后行的原始前 300 个 Unicode 字符：排除记录结尾 LF，保留 CR 及其他空白，不添加虚构标记或省略号；当且仅当解码后的行长超过 300 字符时，`line_text_truncated` 为 true。默认与显式加入搜索共享字面量模式查询合同（1..500 字符，无 NUL/LF，有效 UTF-8），以显式 `-e` 操作数及字面量 pathspec 传递模式，显式关闭 grep 颜色和列输出，避免环境 `color.ui`/`color.grep`/`grep.column` 配置注入字节。根目录纯空白文件名前加 `./`，保持返回定位可跟随，并拒绝不完整/非正数/过长编号记录，或带有输出的无匹配状态。`match_next_offset` 继续有界结果页（最多 50 个匹配）；每页都是新鲜、未固定观察，没有保留的搜索快照或跨页一致性令牌。无效 UTF-8 片段用替换解码；因此严格 UTF-8 read 可能拒绝 search 能定位的文件。

</details>

### 比较当前改动或固定提交

比较当前文件时保留范围和不完整状态。比较历史时，后续分页继续用两个返回的完整提交 ID；分支名可能移动。

<details>
<summary>进阶：diff 模式、路径、Git 查询与不完整结果</summary>

Diff 默认观察当前未提交状态。提交比较要求同时提供 `base` 和 `target`，拒绝 `staged=True`，将各 revision 一次解析为完整 commit ID，并对这些 ID 运行 Git，不切分支。继续时使用返回的 `base_commit`/`target_commit`，即使分支名移动也能固定后续页。比较排除当前索引、工作树及未跟踪更改。路径是字面 Git 树路径，独立于当前符号链接。重命名表示为删除/新增；二进制差异只有元数据。`offset`/`limit` 对 patch 按字符、summary 按文件定位（100 文件上限）。当前 summary 也提供文件续页；普通当前 patch 仍排除未跟踪文件，除非显式未跟踪路径请求合成 patch。提交比较中缺失路径自然不产生差异。

当前 summary 在解码 UTF-8 路径前解析 porcelain-v1 `-z -uall` 和 numstat `-z` 记录。包含跟踪更改及单个未被忽略的未跟踪文件，包括嵌套文件。名称中的空格、tab、LF、引号和字面 ` -> ` 保持原样，不使用 Git 引号或拆成不同条目。对于 Git 识别的重命名/复制条目，`path` 为目标，`original_path` 为源；当前 summary 路径过滤匹配任一侧。复用 `path` 和相同 project/work ref 调用 `read`；现有路径/权限、文件类型和缺失文件限制仍适用（已删除源不必可读；现有 read 验证器仍拒绝全为空白的路径）。

即使 `staged=True`，当前 summary 仍合并索引和工作树的状态及计数；该标志为当前跟踪 patch 选择索引。Numstat 重命名记录使用目标路径、合并双方计数，二进制/未知计数保留为 null。未跟踪计数为 null。当前跟踪 patch 路径是字面量；Git diff 显式关闭 external diff、textconv 和颜色。当前跟踪 patch（未暂存与暂存）及 base/target commit patch 使用固定 `--unified=3` 和 `--inter-hunk-context=0`；summary、numstat 和合成未跟踪文件 patch 不使用它们，因此环境 `diff.context`/`diff.interHunkContext` 配置或继承的 `GIT_DIFF_OPTS` 不能扩大或融合 hunk。固定 Git 子进程接收移除了继承 `GIT_DIFF_OPTS` 的子环境；绝不修改父进程环境或持久 Git 配置。新的机器观察关闭 Git 可选锁；不暂存、不提交，也不执行钩子。

Git 失败、格式错误/未终止记录、非 UTF-8 路径，或当前 diff 的 Git stdout 超过 8 MiB，都会返回应用错误，不给出 `is_clean`、计数或完整覆盖主张。Summary 页保持 100 项上限；续页是新鲜观察。固定 Git 捕获在读取时实施 stdout 上限，stderr 另限 64 KiB。配置探测与查询共享单次期限。当前 diff 使用 NUL status 及索引/工作树两者的 numstat 观察确定范围和计数，另加请求的跟踪 patch 或所选未跟踪正文。它不对无关脏文件/未跟踪正文生成指纹，也不额外抽取文本 status 来构造元数据。

固定查询关闭 fsmonitor/hooks/pager/textconv 并禁止传输协议；clean/process-filter 配置产生 unsupported/unknown，不替换 Git 语义。读取/图像观察不请求检出 status；即使依赖过滤器的 Git 观察不受支持，所选文件内容仍可读取。不观察嵌套子模块工作树脏状态。不声明端到端时间/IO 上限或原子配置/文件系统快照。显式未跟踪合成 patch 读取复用有界文件读取器，保持现有 10 MiB 文件限制；过大文件失败，不返回带错误完成标记的部分 patch。

</details>

### 读懂证据标签

检查 project_root/execution_target 及 coverage/pagination，不要假定结果涵盖整个仓库。提交 ID 不是每个未提交文件的版本。

<details>
<summary>进阶：来源、版本与覆盖范围字段</summary>

成功封装区分 `project_root`、`execution_target`、`work_ref`、`target_kind`、`version`、`observation_mode`、`coverage` 和 `pagination`。读取/图像及跟踪搜索省略全局 `dirty` 和 `state_id` 元数据。其 `version.git_head` 是观察到的提交引用，不是文件版本，也不固定当前检出内容；直接读取完整性使用 `file_sha256` 和可选 `expected_sha256`。不会为构造元数据而打开或哈希无关脏文件或未跟踪正文。当前 diff 从必需的完整 status 观察保留检出 `dirty`；过滤 summary 的 `is_clean` 只适用于所选范围。搜索及当前 diff 续页仍是新鲜、未固定观察，没有替代令牌、快照或缓存。提交比较报告精确解析的 base/target commit ID，排除无关当前 dirty 标志。原生图像元数据携带相同目标来源。`canonical_root` 仍是实际证据检出目录。哈希标识观察到的内容，不是原子文件系统快照。读取 Agent 写的日志证明观察到的字节，不证明执行、测试成功、归属或日志主张真实。

</details>

<a id="evidence-and-current-status"></a>

### 证据与当前状态

开发者可沿下面的回归测试名称查找源码检查。它们只覆盖所述情形，不验证你现在使用的
服务或宿主。运行环境变更和实机验收需要另行授权。

<details>
<summary>进阶：回归覆盖与证据过期</summary>

规范证据回归位于 `tests/test_work_evidence.py` 和 `tests/test_read_contract.py`。它们覆盖精确 Work 目标、search/read 续页、固定 revision 差异及原生图像/结构化元数据保留。不认证实时客户端行为或 Agent 报告的真实性。

`tests/test_current_diff_paths.py` 覆盖主/链接检出目录的当前 summary 到 read 路径、重命名源与目标、numstat、分页及不完整观察。`tests/test_workspace_evidence.py` 检查直接变化的正文/哈希、匹配、当前/暂存 patch 内容、新鲜续页，以及拒绝打开无关正文及仅为元数据扫描 status/diff 的窄观察回归。NUL 安全解析覆盖当前 summary、search 和 commit-diff summary；其他 Git 使用方不变。较早未绑定 Work 仍不可用。上述捕获和快照限制是范围限制，不是另一个状态所有者。

项目连续性通过 manifest 路由。源码合同和合成测试不认证当前运行环境或客户端行为。

回执过期遵循 [Work 容量](LIFECYCLE-RESTART-CONTRACT.zh-CN.md#work-capacity-and-report-lifetime)。已知过期 work_ref 返回 WorkRefExpired；缺失回执或 tombstone 返回 WorkRefUnavailable。任何证据路径都不回退当前 Agent 或项目根目录。已解析的进行中目标保持冻结；后续查找可能因过期拒绝，但不改变之前的目标。

</details>
