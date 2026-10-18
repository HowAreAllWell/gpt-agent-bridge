<a id="install-bridge-and-begin-in-an-ordinary-chatgpt-project-chat"></a>
# 安装 Bridge，并在普通 ChatGPT Project Chat 中开始使用

[English](GETTING-STARTED.md) | [简体中文](GETTING-STARTED.zh-CN.md)

按顺序完成本指南，准备**一套 Bridge、一套 Secure MCP Tunnel companion 和一个 Chrome 扩展，共同服务你的本地项目**。你提供账号、选择仓库并授权工作。Bridge 发现的是你自己启动的兼容 Agents；安装不会启动它们。

这份公开候选的**首次使用草稿**不代表全新安装已验收。Windows 本地扩展准备已在候选源码中实现；完整 Windows/账号流程、Chrome 加载和重启后行为仍需实机检查。真实脱敏截图用于说明控件，不证明你的机器已成功。无需 Work Chat、安装 Codex 或 API Principal。

<a id="1-obtain-the-complete-release-and-check-prerequisites"></a>
## 1. 获取完整发行包并核对前置条件

从 [Releases](https://github.com/HowAreAllWell/gpt-agent-bridge/releases) 下载**附带的完整安装 ZIP**。**v0.1.0-rc.1 已作为 Pre-release 发布**，并非稳定版，也未通过实机验收。选择当前经评审的 Release 附件；后续版本可能取代 rc.1。核对来源、源码和 [LICENSE（许可证原文）](../LICENSE)。完整解压目录，其中应有 `Start-Bridge.ps1`、`prepare`、`release-manifest.json`、`src/`、`scripts/`、`systemd/`、`browser-extension/`、`templates/` 及全部四个 `skills/*/SKILL.md`。保留该目录以便恢复。manifest 校验文件字节，不是独立发布者签名。

GitHub 自动生成的 **Source code (zip)** 和 **Code → Download ZIP** 缺少准备流程所需的 manifest 和 Git 元数据。如果没有授权的完整附件，停止并索取它；本指南不要求新手自己构建开发版。不可变的 rc.1 ZIP 早于此次文档修正，其中仍说完整 ZIP 尚未发布。当前可用性以其 Release 页面为准；main 分支的文档改动不会重写该附件。公开包不含可用的账号绑定或私有连接 token。

包含额外私有文件（如截图压缩包）的源码 checkout 不是干净的准备候选，准备程序会拒绝。不要为制作发行包而打包或上传这些私有文件。

开始准备前应具备：

- Windows 上已有的 **WSL2 Linux distro** 和 systemd，或带 systemd 的 Linux。Windows PowerShell 中的 `wsl --list --verbose` 可用于只读列举环境；记下要使用的 distro。此流程不支持 WSL1 或原生 Windows/macOS 服务安装。没有 WSL 时，先按 [Microsoft 的 WSL 说明](https://learn.microsoft.com/en-us/windows/wsl/install)准备。启动器不会启用 systemd 或转换 WSL 版本。
- 该 distro 中已有的 **Linux Herdr 0.9.0 可执行文件**，由你选择。复用可用安装；若缺少，先查看 [Herdr 前置条件](QUICKSTART.zh-CN.md#herdr-compatibility-and-version-selection)。Herdr session 可以关闭，也无需运行任何 Agent。Bridge 不安装、升级或打开 Herdr，也不安装或登录供应商的 Agent CLI。
- **Chrome 120 或更新版本**，以及允许你使用 Project Instructions、自定义 MCP 插件和 Plugin Creator 的 ChatGPT workspace。Workspace 权限与 Platform Tunnel 权限不同。订阅本身不证明具备访问权限。本指南始终使用普通 Web Chat。

**检查点：** 你拥有可信的完整目录、选定的 Linux 环境和 Herdr 可执行文件，并能访问所需账号控件。此时不要运行演示 Agent 或委派工作。

<a id="2-prepare-your-tunnel-and-restricted-runtime-key-privately"></a>
## 2. 私下准备 Tunnel 和受限 runtime key

在 [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels) 中选择正确的所属 **Platform organization**。复用合适的 Tunnel 或创建自己的 Tunnel。将其关联到预期的 **ChatGPT workspace** 和所属 organization。两者是不同的上下文；名称相同不证明关联。创建/编辑需要 **Tunnels Read + Manage**；运行客户端并在 ChatGPT 中选择 Tunnel 需要 **Read + Use**。参见 [OpenAI 的 Tunnel 权限与关联说明](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。

创建 Tunnel 时，填写 **Name** 和 **Description**，再从实际提供的控件中选择预期的 **Organizations** 和 **ChatGPT workspaces**。

![创建 Tunnel 表单，organization 和 workspace 标识已遮盖](assets/getting-started/platform-tunnel-workspace.png)

*Organization 和 workspace 是两个独立字段；此表单不表示 Tunnel 已创建完成。*

在该 organization 的 [Runtime API keys](https://platform.openai.com/settings/organization/api-keys) 中创建专用 runtime key。如果表单提供 **Project**，选择预期的 Platform API project；它与 ChatGPT Project 不同。
如果账号显示有效期选项，且你受控的专用服务凭据策略允许，选择 **Never**；否则遵循该策略，并在到期前安排替换。Bridge 不配置该设置。

![Runtime key 有效期菜单，可选 Never，project 值已遮盖](assets/getting-started/runtime-key-expiration.png)

*此处显示 Never 可选，不表示已保存或已生成 key。*

在 **Permissions** 下选择 **Restricted**，无关 scope 保持 **None**。不要选择顶层 **All** 或 Admin key。

![尚未选择 Tunnel 权限的 Restricted 权限表](assets/getting-started/runtime-key-restricted.png)

*初始状态：已选权限为零。仍需执行下一步赋予 Tunnel 访问权限。*

打开 **Tunnels** 权限菜单，分别勾选 **Read** 和 **Use**。创建 key 前，确认两者都已选中，其他 scope 均为 **None**。绝不把生成的 key 放进截图。

![Tunnels 权限菜单，Read 与 Use 均已勾选](assets/getting-started/runtime-key-tunnels.png)

*All selected 仅指这两个 Tunnels 子权限，不是顶层 All 权限模式。*

Key 的 principal 还必须具备所需 Tunnel role；勾选 scope 不能赋予缺失的 role。如有需要，联系 organization owner/RBAC 管理员。

私下保存 Tunnel ID 和 key，供第 4 步本地提示输入。不要放进 Chat、Instructions/Core、截图、CLI 参数、报告或发行文件。Key 用于 Tunnel runtime 身份验证。可复用合适的工作凭据，不必仅为本指南新建 Tunnel 或轮换 key。

**检查点：** 你知道哪个 Tunnel 属于选定的 organization/workspace，并持有具备所需 role 和最小 scope 的 runtime key。这些账号操作尚未建立 Bridge 服务或 Chat 连接。

<a id="3-start-preparation-and-confirm-the-exact-wsl2-distro"></a>
## 3. 开始准备并确认准确的 WSL2 distro

在解压后的发行目录打开 **Windows PowerShell**，运行：

```powershell
.\Start-Bridge.ps1
```

入口会列出经过核实的 WSL2 distributions。只有一个已安装 distro 时，核对 `Use WSL2 distro '…'? [Y/n]` 中的名字，按 Enter 确认，或输入 `n` 拒绝。有多个已安装 distro 时，输入所列 WSL2 distro 的**准确名称**。名称未知、WSL1、清单含糊或所选 distro 不可用都会停止准备。继续前核对后续 `Using WSL2 distro: …` 行。

此后每次 WSL runtime 调用都使用该选择及其默认 Linux 用户；不会修改 WSL 默认 distro、版本或 systemd 设置，也不重启 WSL。

若已有 WSL 但尚未安装 distro，入口会改为在你输入 `yes` 后才提供官方 Ubuntu 安装，可能涉及 Windows 提权/重启。完成 Linux 用户创建及要求的重启后，再运行同一入口。若 Windows 阻止脚本，不要全局关闭机器执行策略；核对 Properties / Unblock，或采用管理员正常的信任流程。

若缺少 Python 3/venv 或 Git，入口会显示所选 distro，并在 `sudo apt-get` 前征求许可。只批准该预期安装；sudo 要求时在本地输入 Linux 密码。非 apt distro 需要自己的可信包管理器。产品要求 Python 3.10+ 和 venv 支持。

**全新 Windows 配置**中，同一入口随后会询问 `Private Windows extension folder (existing parent, local NTFS)`。按 Enter 使用 `%LOCALAPPDATA%\GPT-Agent-Bridge-extension`，或输入固定本地 NTFS 驱动器上、**已有父目录下的新文件夹**的绝对路径，不加外层引号。输入 `yes` 确认显示的位置。

入口检查所有权、权限和路径安全；目标已占用或不安全会停止。记住此位置，供 Chrome 使用。Bridge 和 Tunnel 保留在选定 WSL distro；已有安装不会迁移或重新生成密钥身份。

**仅 Linux/WSL 准备**则从完整发行包运行 `./prepare`。该路径把扩展保留在 Linux，适用时输出已核实的 WSL UNC；不会选择 Windows 本地扩展目录。同一安装不要运行两个入口。

**检查点：** 所选 distro/用户正确、依赖可用，且入口已到达 `Trust this release and continue local preparation? [yes/no]`。审阅显示的范围，仅在同意时输入 `yes`。

<a id="4-follow-the-one-local-preparation-through-its-handoffs"></a>
## 4. 沿同一准备流程完成各项交接

入口将核对过的发行文件复制到专用产品目录，准备私有 Python 环境并安装依赖。它查找已有 Herdr，或询问其 Linux 可执行文件的绝对路径，并检查版本 0.9.0。它下载固定的 Secure MCP Tunnel runtime **0.0.16**，在使用前核对配置中的 SHA256；参见[固定的上游发行版](https://github.com/openai/tunnel-client/releases/tag/v0.0.16)。已完成且匹配的文件会复用。你的工作仓库不会迁移。

随后询问是否允许这个已安装扩展读取注册项目的 ref、canonical root 和完成元数据，包括未来授权注册的项目。仅在需要此本地发现 capability 时批准。它既不赋予报告正文访问权，也不授予任务权限；仍须在后文逐个明确绑定 Chat。

<a id="keep-the-early-private-extension-path"></a>
### 保存提前输出的私有扩展路径

全新 Windows 运行中，准备程序在受保护的 WSL 文件内只生成一次 pairing，再把相同扩展字节私下发布到所选 Windows 目录。你无需自行复制 token 或 `connection.js`。中间的 `Windows publication is pending` 消息不表示完成。

Windows 文件核验并确认发布后，**在服务安装与凭据提示之前**，终端输出：

- `Expected extension ID:` — 稍后与 Chrome 对照。
- `Private extension Windows path (copy into Chrome Load unpacked):`，下一行是完整的 **Windows 本地目录**。

保留此最终路径用于第 9 步。重新进入使用记录的目标和 pairing，不会另选位置或生成新身份来绕过失败。保留中止运行的文件，重试前观察错误。

仅 Linux/WSL 或已有记录的 Linux 准备会改为输出 `Private extension Linux path:`。在 WSL 上还会显示 `WSL distro:` 和同样的 Windows-path 标题，下一行是核实后的 `\\wsl.localhost\…`。Receipt 路径优先于猜测的 home 目录。如果显示 `Windows extension path: unavailable/unverified`，停止，不要编造路径。准备好的文件本身不证明 Chrome、服务、Tunnel 或 Chat 已连接。

<details>
<summary>准备文件存放位置（不要复制或编辑私有配置）</summary>

| 位置 | 用途 |
| --- | --- |
| 所选 WSL 用户的 `~/.local/share/bridge-release/` | Windows wrapper 核对过的发行暂存，不是 Chrome 加载目录 |
| `<Linux account home>/.local/share/gpt-agent-bridge/product/` 和 `product/.venv/` | 私有产品和 Python 环境；account home 来自 Linux 用户记录 |
| 所选 Windows 本地目录（默认 `%LOCALAPPDATA%\GPT-Agent-Bridge-extension`） | 全新 Windows Chrome 加载目录；保留其路径和身份 |
| `<Linux account home>/.local/share/gpt-agent-bridge/extension/` | Windows 发布的受保护源；仅 Linux/WSL 准备加载其 receipt 中输出的目录 |
| 准备后扩展目录中的 `connection.js` 和 `<Linux account home>/.config/gpt-agent-bridge/browser-notifications.json` | 生成的私有通知 pairing；绝不手动分享或复制内容 |
| `<Linux account home>/.local/share/gpt-agent-bridge/` | 扩展 receipt、pending 恢复记录、准备锁和 `Creator-attachments/` |
| `/var/lib/gpt-agent-bridge-tunnel-autostart/credentials.json` | 仅 owner 可读的持久 Tunnel 凭据，后续运行复用 |

严格安装器还会在 `/usr/local/lib/`、`/etc/systemd/system/` 下创建受保护的服务文件，并在 `/var/lib/gpt-agent-bridge-autostart/` 下存放 Bridge 私有设置。不要并发编辑生成文件。准备锁协调合作工具，不能阻止任意外部编辑器。

</details>

<a id="approve-services-then-enter-credentials-locally"></a>
### 批准服务操作，再在本地输入凭据

入口会为严格的 Bridge/Tunnel 安装器请求 sudo。它安装并激活 Bridge，再安装 Tunnel 服务，然后才询问凭据。全新安装要求端口 **8765** 可用；不会杀掉其他 listener。不支持的 systemd/账号布局、`/mnt` 服务路径、符号链接或安装器控制路径中的空格，都可能在此阻断。扩展路径已成功显示，不会绕过这些独立的服务检查。

若没有保存的 Tunnel 凭据，控制台会准确询问：

```text
Own Tunnel ID (hidden):
Own runtime API key (hidden):
```

在本地输入相应的完整值，不加引号或标签。字符不会回显。必须使用私有交互终端；不要重定向输入，也不要把任何值粘贴到 Chat。已有的有效本地凭据会复用，不再询问；本地格式/所有权检查不验证远程 role 或有效期。Runtime 私下接收 key；你无需把 Bridge 的秘密 MCP endpoint 复制进命令或 Chat。

入口随后启用/启动所属 Tunnel 服务并输出 `Local checks:`。查找 `"bridge_mcp": "initialized_healthy"`。它是完成初始化后的**本地 Bridge MCP 健康**；Herdr session 关闭时可以 unavailable。服务 `active` 是进程观察，不证明 Tunnel control-plane 或 Web 访问成功。此准备路径不会运行单独的 Tunnel readiness status probe。

继续完成软件交接。记下输出的**四个具名 Skill 附件和 LICENSE**目录。在可选的 native own-App ID 提示处按 **Enter**，改用第 6 步的 Web App 选择；不要从浏览器 URL 猜测 ID。入口显示 public Core 文件路径，最后输出：
`Software preparation is complete; no repository or running Herdr session/Agent is required. You may close this terminal.`

**检查点：** 准备正常结束，观察到了本地 MCP health，并取得扩展和 Skill 交接路径。这尚未安装 Web 插件/Skills、连接项目或授权通知投递。

<a id="5-connect-the-tunnel-to-your-private-chatgpt-plugin"></a>
## 5. 把 Tunnel 连接到自己的私有 ChatGPT 插件

在预期的 ChatGPT workspace 中打开 [Plugins](https://chatgpt.com/plugins)，使用加号控件和 **Add custom MCP server**。填写易辨认的名称、描述，设置 **Connection: Tunnel**，选择自己的 Tunnel。如果表单提供 ID 输入，只在这个官方字段中输入同一 ID，绝不要放在 Chat 消息中。不要把 runtime key 粘贴进表单。

![脱敏的 Add custom MCP server 表单，已选择 Tunnel](assets/getting-started/mcp-tunnel-form.png)

*真实表单示例；身份验证仍是默认 OAuth。*

对这个私有 Bridge 连接，将 MCP 身份验证改为 **No authentication**。Bridge 没有 OAuth server；Tunnel role 和 Bridge 受保护的本地 endpoint 仍适用。这不会创建公开的无验证 endpoint。阅读风险提示，仅在接受显示范围时选择 **I understand and want to continue** 和 **Create as a plugin**。

![脱敏表单，已选 No authentication，Tunnel ID 已遮盖](assets/getting-started/mcp-no-auth.png)

*真实表单配置，不表示插件已完成。*

审阅发现的工具，在提供时使用 **Install**。创建或打开你要使用的 ChatGPT Project，再在其中打开普通 Chat，通过 `@` 选择已安装的插件。

请求：“仅调用只读 bridge_health，并显示实际结果。不要注册项目、初始化状态或向 Agent 输入任务。”检查实际工具结果，而不只是“连接正常”的文字。参见[官方 Tunnel 连接流程](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。

**检查点：** 该普通 Project Chat 成功调用了 `bridge_health`。本地准备、插件卡片或工具名称本身不证明此结果。Tunnel 不显示或调用失败时使用下方排错表；不要重装 Bridge 来修复账号权限问题。

<a id="6-install-and-discover-all-four-native-skills"></a>
## 6. 安装并发现全部四个原生 Skills

**Create as a plugin 连接 MCP 工具，不会安装这四个 Skills。** 在普通 Web Chat 中，若可用，通过 `@` 选择 **Plugin Creator**。若实际提供且你授权编辑当前工作插件，保留其已有 App 映射；否则请 Creator 在私有组合插件中使用你已连接的 Bridge App。若有 host App picker 就使用它，不要猜测标识符。[OpenAI 创建指南](https://learn.chatgpt.com/docs/build-plugins)说明了依赖权限的流程，不保证账号具备资格。

附加输出的 `Creator-attachments/` 目录内四个分别具名的 Markdown 文件和 LICENSE。在 Windows 上，从同一个选定 WSL distro 的 Linux 文件系统浏览该目录；扩展目录不是附件目录。这些副本保持以下 canonical 源文件：

- [project-onboarding（未翻译的 canonical Skill）](../skills/project-onboarding/SKILL.md)
- [project-resume（未翻译的 canonical Skill）](../skills/project-resume/SKILL.md)
- [handoff-preparation（未翻译的 canonical Skill）](../skills/handoff-preparation/SKILL.md)
- [team-deliberation（未翻译的 canonical Skill）](../skills/team-deliberation/SKILL.md)

发送这段不含凭据的请求：

> 从我附加的四个文件添加四个独立原生 Skills，名称为 project-onboarding、project-resume、handoff-preparation、team-deliberation，保留完整文本、元数据和 LICENSE。使用我已有且已连接的 Bridge App。在我安装前，展示 App 映射和全部四个 Skill 正文供审阅。不要重建 MCP 连接、收集凭据、发布/分享、执行流程，也不要只把它们保留为参考附件。如不能准确打包为原生 Skills，停止。

审阅每个完整 Skill 正文和已有 App 映射。使用账号实际提供的控件完成创建/编辑和安装。不要只为复现示例而授予全部工具权限。

![裁剪后的开发者插件 Skills 区域，显示四个 Skills 已启用](assets/getting-started/plugin-installed-skills.png)

*脱敏开发者示例：四个 Skills 为开启状态，不证明自动导入或你的安装成功。*

在新的普通 Project Chat 中选择得到的插件，要求发现并阅读全部四个已安装的原生 Skill 正文，**不要执行它们**。与上方源文件比较名称和完整流程。上传、四名称摘要或 MCP 工具发现本身不足以证明安装。保留这个 Chat，用于后续项目连接和通知绑定。

**检查点：** 在目标 Web Chat 中已发现全部四个原生 Skills。若创建/发现不可用，记录“tools working; Skills unverified”，在此账号关卡停止完整产品配置。[Skills 打包与诊断](TECHNICAL-REFERENCE.zh-CN.md#attachment-and-discovery-diagnostics)可排查该层，无需第二次安装 Tunnel；仅 Work 中的结果不能通过普通 Web 检查。

<a id="7-put-the-public-core-in-project-instructions"></a>
## 7. 将 public Core 放入 Project Instructions

打开 [templates/WEB-PRINCIPAL-CORE.md（未翻译的 canonical Core）](../templates/WEB-PRINCIPAL-CORE.md)，阅读并复制其**完整公开文本**。在 ChatGPT **Project settings → Instructions** 中，把该文本与相关已有指令合并。它是 Principal 指令文本，不是安装器、可执行命令、Skill 附件或单条 Chat 消息。它不提供连接凭据或项目权限。

![Project settings，项目名和 Instructions 内容已遮盖](assets/getting-started/project-instructions.png)

*真实 Instructions 控件，私有文本已移除；截图未显示明确保存按钮。*

用实际存在的控件完成操作，再重新打开 Instructions，确认全文已保存且未截断、原有规则仍在。不要仅凭截图推断已保存。绝不要插入秘密或另一个项目的 Binding。

**检查点：** Project 持久 Instructions 包含完整 public Core 和保留规则。返回同一 Project 的普通 Chat，选择 Bridge 插件；单靠 Core 文本不会连接本地仓库。

<a id="8-connect-your-existing-git-repository-and-merge-its-binding"></a>
## 8. 连接已有 Git 仓库并合并其 Binding

告诉 Principal 使用 **project-onboarding**，提供你授权的准确已有 Linux Git root 和所选 project ref。例如先用自己的话说明这两个值，再说：

> 只用 project-onboarding 连接这个已有仓库。检查注册和 context；仅在需要时注册。返回 Project Binding，供我审阅并合并到此 Project 的 Instructions。不要初始化延续、创建仓库、启动 Agents、发送任务或编辑项目文件。

核对 Bridge 实际返回的注册 canonical root/ref。手动把返回的 **Project Binding（Host Binding）**与 Core 一起合并到同一 Project Instructions，保留无关指令。重新打开确认保存。ChatGPT Project 名称和本地仓库名称不能建立该映射。无需本地注册/同步命令。

**检查点：** 返回的 ref/root 与授权仓库匹配，Binding 位于预期 Project。仅连接到此结束；`project_initialize` 和延续种子需要另行明确请求。注册既不授予 Agent 任务，也不选择通知目的地。

<a id="9-load-the-private-extension-and-bind-this-exact-chat"></a>
## 9. 加载私有扩展并绑定这个准确 Chat

打开 Chrome `chrome://extensions`，启用 **Developer mode**，选择 **Load unpacked**，选取**第 4 步输出的私有准备后扩展目录**。通过 **Start-Bridge.ps1** 的全新配置，在目录选择器中选择**最终输出的 Windows 本地目录**。仅 Linux/WSL 准备则按浏览器所在 host 使用输出的 Linux 路径或经核实的 WSL UNC。

不要选 ZIP、公开/源码目录、用 WSL publication source 替代最终 Windows 目录、发行暂存目录或 `product/browser-extension/extension` 模板。对照 Chrome 扩展 ID 与输出的 expected ID。

保留此私有目录、`connection.js`、加载位置和 manifest 身份。已有安装保留原始加载目录和身份；全新安装流程不授权迁移它们。ID 不符或 Chrome 无法加载输出目录时停止；不要以搬移、卸载/重装或清空 storage 绕过。
**全新 Windows 本地安装、Chrome 从 WSL UNC 加载、重启后行为尚未通过实机验收。** 输出路径或文件发布成功不证明 Chrome 已接受。

在 Project 中打开一个准确、已存在、普通非隐私 Chat 标签页。同一完整目的地路由只保留一个普通标签。扩展 popup 中：

1. 在 **本地项目** 选择已注册仓库；核对身份/root。
2. 勾选 **允许向当前 Chat 自动发送完成提醒**。
3. 点击 **设为接收 Chat 并启用**。
4. 检查 **接收 Chat：当前 Chat** 和 **自动通知已启用**，并查看显示的错误。

**派工前绑定**：首次启用不重放旧完成事件。每个本地项目只有一个明确接收方；添加项目或打开另一个 Chat 不会选择它。更换时，明确选择新的当前 Chat 并再次授权启用。只有保存了有效路由、可证明从未尝试的 queued/waiting 提醒，才可跟随进行**首次发送**。旧的已尝试、结果不确定或冻结身份绝不迁移或重放，即使之后切回原 Chat、worker 重启或生产者 epoch 改变也一样。保留的原始 ID 抑制证据不会阻塞不同的新 Work，也不会产生常驻警告；不要清空 storage 绕过。128 上限针对实际未尝试的待处理提醒，不是已结束历史。

真正空白且安全的输入框可以自动发送固定通知一次。有文字、富内容或已上传文件的草稿则显示不修改内容的行内 **追加到输入框末尾（另起一行） / 忽略** 选项，打字或使用 IME 时也能显示。忽略保留当前草稿和附件不变。追加在当前 IME 组合结束后，只向当前绑定的编辑器末尾添加一段固定通知；不会点击 Send、替换草稿或把文件内容传给 worker。正常编辑及附件变化不需要静默等待。如果在异步追加执行前先提交消息，旧选择会被拒绝；请为当前消息重新选择。未选择的提醒在刷新/关闭后仍待处理；下一次普通轮询会重新检查准确 Chat，再次提供选项或走安全的空输入框路径。

本地 Send 点击或成功的显式选择只表示本地已处理一次，不证明 ChatGPT 收到消息或后端已确认。结果未知时不重试。不扫描对话/收件回执，也不以通知历史界面或旧未知常驻警告确认送达；仍保留当前错误及待处理诊断。

**检查点：** 预期项目和准确 Chat 显示为已启用。这是绑定状态，不证明提醒已投递。Adapter 目前只针对英文 ChatGPT Web/Project Chat DOM 验证；UI 变化或其他语言可能等待或拒绝。参见[扩展行为与恢复](LIFECYCLE-RESTART-CONTRACT.zh-CN.md#chrome-notification-authority-and-recovery)。

<a id="10-begin-daily-use-with-a-bounded-read-only-check"></a>
## 10. 从范围明确的只读检查开始日常使用

无需每天 `prepare`。Host/WSL 和网络在线时，已安装 Bridge/Tunnel 服务可在后台运行，无需打开准备终端或 Herdr session。Windows 注销、WSL 关闭/挂起和重启是独立可用性边界；未宣称已通过重启验收。[可选 WSL 登录 adapter](AUTOSTART.zh-CN.md)是独立 operator 决策。

自己在选定 Linux 环境打开 Herdr，进入授权 Git 仓库，在其中启动/登录选定的兼容 Agent。复用已有合格 session。供应商配置、模型选择和配额由你管理。可在启动 Agent 前后打开普通 Web Chat；Bridge 从不替你启动 Agent。要求 Principal 获取新鲜的 `context(project_ref)`，检查实际 Agent 可用性。错误/不完整观察表示未知，不证明没有 Agents。

小范围**只读**首次检查可明确授权 Principal 只查看已注册项目的 overview/context 和你指定的一个非秘密文件，再用源证据总结。要求不编辑、不执行命令/测试、不做 Git 操作、不初始化、不输入 Agent 任务。核对返回的 root/ref 和引用文件内容。这只证明实际走通的读取路径，不会创建 smoke Work 或通知。

真实委派时，说明任务、允许的改动和验收条件，并明确授权向实际观察到的合格 Agent 输入。Principal 使用新鲜 context handles 委派，读取完整 `work_report`，带完整 SHA pin 完成所有分页。提醒提供 project/Work refs，不是报告，也不证明成功。[发票示例](QUICKSTART.zh-CN.md#optional-invoice-demo)是可选的；它不授予启动演示 Agent 的权限。

**检查点：** 区分成功只读检查、后续委派、实际提醒投递和完整报告评审。通过其中一项不能证明其他项。如果没有授权真实任务，只读检查后停止。

<a id="if-a-step-stops"></a>
## 如果某一步停止

保留已完成文件和准确的非秘密错误。未知结果需要在再次变更前观察；不要通过重置、重放或重装来猜测。

| 观察 | 下一步安全动作 |
| --- | --- |
| Project Instructions 不可用、被拒绝或截断 | 核对实际账号控件和文本限制。保留原有规则，不要宣称部分 Core 已完成安装。 |
| 复制、依赖或扩展准备停止 | 检查指出的失败。仅在安全时使用相同 release/path/distro/user 重新进入：匹配文件/receipt 会复用，所属的部分 venv 可继续完成，未知文件变化会停止。不同 Release 不是自动升级。不要删除 receipt、生成的 key 或已有目录。 |
| Windows 本地发布停止 | 保留记录的目标与 staging 文件。不要另选目录、移动原扩展或手动复制秘密。再次尝试前查看固定诊断；较早运行可能已到服务配置阶段。 |
| 已显示扩展 Linux 路径，但 Windows 路径未经核实 | 检查所选 distro 和 path converter，保留文件。不要猜测 UNC，或当作已成功加载而继续到 Chrome。 |
| 服务安装/启动失败或状态未知 | 保留安装。按对应失败层的 [Bridge autostart](AUTOSTART.zh-CN.md#bridge-component-contract) 或 [Tunnel autostart](AUTOSTART.zh-CN.md#tunnel-component-contract) owner/status 指引排查。不要杀掉其他服务或重复未知结果的启动。 |
| 插件 picker 没有 Tunnel，或出现 403 | 核对所属 organization、目标 ChatGPT workspace 关联、operator/key principal 的 Tunnel role 和 Restricted Read + Use scope。修复账号关卡，不要另建本地安装。 |
| 保存的 key 错误/到期 | 使用下文同一 Release 的显式 credentials action；不要把替代值发送到 Chat。 |
| 工具可用，但缺少四个原生 Skills | 保留工作中的 MCP 连接；解决 Creator/安装权限，并在普通 Web Chat 核实原生发现。 |
| 项目注册未知或与已有路由冲突 | 查看只读注册观察，请 owner 协调。不要重定向路由或盲目再次注册。 |
| 提醒等待或结果未知 | 在准确绑定 Chat 中查看追加/忽略及当前 popup diagnostics。Stop、空编辑器中的活动 IME、上传或不安全的输入框状态可延迟自动 Send。旧未知 ID 是静默抑制证据，不是重放理由。不要清空 storage 或把 synthetic diagnostic 当首次使用测试。 |

仅用于恢复时，Windows `.\Start-Bridge.ps1 status`（Linux `./prepare status`）报告准备文件是否存在，**不是服务健康**。独立 Tunnel status 可以报告 `tunnel_startup: ready`，但仍明确 control-plane verification 和 Web readiness 尚未确立。实际 Project Chat 的 `bridge_health` 结果才是远程检查点；不要把重复 status 命令当作日常仪式。

保存的 key 必须替换时，从同一 Release 运行 `.\Start-Bridge.ps1 credentials`（Linux `./prepare credentials`）。确认替换，在本地隐藏提示输入。最初保持服务不变，随后单独询问是否允许用 sudo 停止/启动**仅所属 Tunnel 服务**。拒绝会推迟激活。任何后续变更前先观察未知结果；Bridge 自身无需重启。这是恢复，不是第二条首次使用路径。

Legacy 扩展 adoption 需要单独授权；保留原始路径、ID/key、token 和历史。[扩展参考](LIFECYCLE-RESTART-CONTRACT.zh-CN.md#chrome-notification-authority-and-recovery)与服务参考说明各自契约，不是另一套必需安装步骤。
