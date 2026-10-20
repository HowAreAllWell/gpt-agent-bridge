<a id="install-bridge-and-begin-in-an-ordinary-chatgpt-project-chat"></a>
<a id="安装-bridge并在普通-chatgpt-project-chat-中开始使用"></a>
# 配置 Bridge，在 ChatGPT 网页中开始使用

[English](GETTING-STARTED.md) | [简体中文](GETTING-STARTED.zh-CN.md)

按第 1–10 步依次操作：先在自己的电脑准备 Bridge，再连接到普通
**ChatGPT 网页项目对话（Web Project Chat）**。确认连接正常后，再决定授权哪些项目工作。

## 先选你的电脑

| 你的电脑 | Bridge 在哪里运行 | 在哪里打开 ChatGPT | 准备入口 |
| --- | --- | --- | --- |
| **原生 Ubuntu 桌面** | Ubuntu 本机 | 同一台 Ubuntu 电脑的 Chrome | [Ubuntu 终端](#native-ubuntu-desktop)，不需要 WSL 或 PowerShell |
| **Windows + WSL2** | 你选定的 WSL2 Linux 系统内 | Windows Chrome | [Windows PowerShell](#windows-and-wsl2)，需选对 Linux 系统 |

先从下面第 1 步开始；表中链接是第 3 步使用的入口。两条路线从第 5 步起共用同一套网页操作。
本指南不涵盖“Ubuntu 远程服务器运行 Bridge，另一台电脑打开浏览器”的情况。

**准备程序会改动什么：** 在你批准提示后，它会建立专用 Python 环境、下载经核对的依赖、
准备私有扩展文件，并**安装、设为自动启动且立即启动两个 Linux 后台服务**：
Bridge 和它的 Secure MCP Tunnel 连接。它不会安装 Herdr 或 Agent、登录供应商、
搬动项目或发送任务。第 9 步加载 Chrome 扩展、开启完成提醒是可选操作；
Bridge 工具和 Skills 不依赖浏览器提醒。

**验证范围：** 这些路线有当前源码依据。完整的原生 Ubuntu 新手流程、全新 Windows/账号配置、
Chrome 加载和重启后行为，尚未通过实机验收。截图仅展示示例控件，不证明你的配置成功。

下面会用到的几个名称：

| 名称 | 在这里是什么意思 |
| --- | --- |
| **Herdr / Agent** | Herdr 管理本地终端会话。Agent 是你在其中启动的编程或研究助手。 |
| **Tunnel（隧道）** | ChatGPT 与你电脑上 Bridge 之间的私有连接。 |
| **工具 / App / 插件** | 工具执行一项操作，例如读取文件。App 指 Bridge 连接；插件是你在 ChatGPT 中安装和选择的项目。 |
| **Skill（工作流程）** | 安装在插件内、可重复使用的一套指令；不是正在运行的本地 Agent。 |
| **Project / Core / Binding** | Project 是 ChatGPT 的项目，集中保存对话与指令。Core 是提供给你的基础指令；Binding 是补充文本，指出你允许使用的本地项目。 |

账号、仓库和权限由你掌握。全程使用普通网页对话；无需 Work、本地 Codex 或另设模型 API Principal。
模型访问、Agent 供应商登录、费用和配额仍由你管理。

<a id="1-obtain-the-complete-release-and-check-prerequisites"></a>
<a id="1-获取完整发行包并核对前置条件"></a>
## 1. 下载完整安装包，确认前提条件

**在浏览器中：** 打开
[Releases 列表](https://github.com/HowAreAllWell/gpt-agent-bridge/releases)，
选择经评审的 **PRE-RELEASE（预发布版）**，下载该版本附加的一个**完整安装 ZIP**。
先阅读对应的源码提交、改动、限制和 [LICENSE](../LICENSE)。完整解压，保留解压后的文件夹。

不要下载 GitHub 自动生成的 **Source code (zip/tar.gz)** 或 **Code → Download ZIP**。
这些是源码压缩包，不是完整安装包：缺少准备程序使用的清单和 Git 元数据。
完整文件夹应含 `Start-Bridge.ps1`、`prepare`、`release-manifest.json`、
`src/`、`scripts/`、`systemd/`、`browser-extension/`、`templates/`，
以及四个 `skills/*/SKILL.md` 文件。清单用于核对文件字节，不是独立的发布者签名。

若没有附加经授权的完整安装 ZIP，就在此停止并索取；不需要自行组装开发版本。
main 分支文档可能描述旧 ZIP 尚未包含的改动，阅读文档不会更新旧安装包。
不要把私有文件或截图归档加入发行文件夹。

**继续前，检查电脑和账号：**

- **Ubuntu：** 使用自己的普通用户，不要用 root；需要时应有管理员权限。
  系统必须已使用 **systemd**（Linux 后台服务管理器）。固定下载包覆盖 `x86_64`
  和 `aarch64`，不代表保证兼容所有 Ubuntu 版本和电脑。
- **Windows：** 使用已有的 **WSL2** Linux 系统及其普通默认用户，且已启用 systemd。
  WSL2 是 Windows 内运行 Linux 的方式。本指南不支持 WSL1、原生 Windows 服务安装
  或原生 macOS 安装。缺少 WSL 时先按
  [Microsoft 的说明](https://learn.microsoft.com/en-us/windows/wsl/install)准备。
  入口不会把 WSL1 转为 WSL2，也不会替你开启 systemd。
- **同一个 Linux 环境必须已有 Herdr 0.9.0。** 复用已有可用安装；若缺少，先阅读
  [兼容性检查](QUICKSTART.zh-CN.md#herdr-compatibility-and-version-selection)，
  必要时只执行其中的[固定版本 Herdr 安装小节](QUICKSTART.zh-CN.md#2-optional-separate-v090-installation)。
  这是你自行完成的前提条件，不是再安装一遍 Bridge。
  **仅配置 Bridge 时，无需打开 Herdr 或运行任何 Agent。**
- 本地需要 **Python 3.10+**、Python 的 `venv` 支持和 Git。
  准备程序可以先征求许可，再通过 `apt-get` 安装缺少的包；
  使用其他包管理器的系统需自行完成受支持的前提配置。
- 目标 ChatGPT 工作区需提供**项目指令（Project Instructions）**、自定义 MCP 连接
  和 **Plugin Creator**。工作区是 ChatGPT 中选择的个人或团队区域。
  是否可用取决于套餐和工作区政策；有订阅不等于已经具备权限。
- 本指南使用 **Chrome 120+**。可选提醒扩展需要它，扩展与 MCP 连接是两回事。

**可以继续的标志：** 已取得可信的完整安装包，选好 Linux 用户且已有兼容 Herdr，
账号也提供所需控件。缺少任意一项，先解决它；不要启动演示或派发任务。

<a id="2-prepare-your-tunnel-and-restricted-runtime-key-privately"></a>
<a id="2-私下准备-tunnel-和受限-runtime-key"></a>
## 2. 准备私有连接和专用密钥

**在 OpenAI Platform 网页：** 打开
[Tunnel 设置](https://platform.openai.com/settings/organization/tunnels)，
选择拥有此连接的 Platform **organization（组织）**。这是 Platform 管理账号的区域，
不同于 ChatGPT 项目。

1. 复用合适的 Tunnel，或创建自己的 Tunnel。新建时填写 **Name** 和 **Description**。
2. 在实际提供的控件中选择预期 **Organizations** 和 **ChatGPT workspaces**，
   将 Tunnel 关联到所属组织及你要使用的 ChatGPT 工作区。名称相同不等于已经关联。

![私有组织和工作区标识已遮盖的 Tunnel 表单](assets/getting-started/platform-tunnel-workspace.png)

*仅展示示例控件，图中未完成 Tunnel 创建。*

创建或编辑需要 **Tunnels Read + Manage**；运行连接和在 ChatGPT 中选择它需要
**Read + Use**。密钥所属账号也必须拥有该 Tunnel 角色；勾选密钥权限不能补足账号缺少的角色。
缺少控件或权限时，请联系组织所有者或管理员。
参见 [OpenAI 的 Tunnel 权限说明](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。

**在同一组织的 [Runtime API keys](https://platform.openai.com/settings/organization/api-keys) 页面：**

1. 创建专用 **runtime** key，不是 Admin key。若有 **Project** 选项，选择预期的
   Platform API 项目；它与 ChatGPT 项目不同。
2. 若有有效期选项，且你的专用服务凭据政策允许，可选 **Never**。
   否则遵循政策，在到期前安排更换；Bridge 不会替你设置有效期。

![显示 Never 选项的有效期菜单，私有项目值已遮盖](assets/getting-started/runtime-key-expiration.png)

*Never 是可选项，不表示已保存或已经生成密钥。*

3. **Permissions** 选择 **Restricted**。其他权限保持 **None**，
   不要选顶层的 **All**。

![尚未选择 Tunnel 权限的 Restricted 设置](assets/getting-started/runtime-key-restricted.png)

*此示例尚未授予 Tunnel 访问权。*

4. 展开 **Tunnels**，分别选中 **Read** 和 **Use**。
   确认两项均选中、其他权限仍为 **None**，再创建密钥。

![已选择 Read 和 Use 的 Tunnel 权限](assets/getting-started/runtime-key-tunnels.png)

*这里的 All 表示这两项 Tunnel 权限，不是顶层 All。*

**Tunnel ID 和 runtime key 都应保密**，仅用于第 4 步本地提示。
不要粘贴到 Chat、项目指令、命令、截图或报告。该 key 用于运行连接，不用于选择模型。
可复用合适且工作正常的凭据，不必仅为本指南新建 Tunnel 或轮换 key。

**可以继续的标志：** 已有正确的组织/工作区关联和角色，并取得最小所需权限的 runtime key。
若缺少角色或工作区关联，在这个账号问题处停止；重装本地程序不能解决它。

<a id="3-start-preparation-and-confirm-the-exact-wsl2-distro"></a>
<a id="3-开始准备并确认准确的-wsl2-distro"></a>
## 3. 启动本地准备，只选一条路线

先完成第 1–2 步。**下面的入口会在征得同意后安装、设为自动启动并启动服务。**
同一次配置不要运行两个入口。

<a id="native-ubuntu-desktop"></a>
### 原生 Ubuntu 桌面

**在 Ubuntu「文件」（Files）中：** 打开完整安装包解压后的文件夹。
在该文件夹打开 Ubuntu 终端；若右键菜单提供 **Open in Terminal（在终端打开）**，可直接使用。
确认终端当前目录含有 `prepare`，再运行：

```bash
./prepare
```

使用普通用户，不要使用 root 终端。若提示安装 Python/venv 和 Git，先阅读请求，
同意后才输入 `yes`；需要管理员权限时，在本地输入 Linux 密码。

**应看到：** 准备程序到达
`Trust this release and continue local preparation? [yes/no]`。
审阅列出的改动范围，仅在同意后输入 `yes`。

**若停止：** 保留准确且不含秘密的错误。找不到文件或文件不可执行时，
先核对安装包是否完整解压及文件权限。不要改用 root、删除已有安装文件，
或猜另一条命令强行继续。这条路线不需要 WSL、PowerShell 或 Windows 任务。

<a id="windows-and-wsl2"></a>
### Windows + WSL2

**在 Windows 文件资源管理器中：** 打开完整安装包解压后的文件夹，
点击地址栏，输入 `powershell` 并按 Enter，在该文件夹打开
**Windows PowerShell**，运行：

```powershell
.\Start-Bridge.ps1
```

1. 查看列出的 WSL2 Linux 系统。只有一个时，核对
   `Use WSL2 distro '…'? [Y/n]`，按 Enter 接受，或输入 `n` 拒绝。
   有多个时，输入列表中的**准确名称**。
2. 核对 `Using WSL2 distro: …`。之后使用该系统的默认 Linux 用户完成准备；
   入口不会改变 WSL 默认系统、版本或已有会话。
3. 缺少 Python/venv 或 Git 时，只对选定系统批准 `sudo apt-get`。
   若要求密码，在本地输入 Linux 密码。
4. 全新 Windows 配置到达
   `Private Windows extension folder (existing parent, local NTFS)` 时，
   可按 Enter 使用 `%LOCALAPPDATA%\GPT-Agent-Bridge-extension`；
   或指定本地 NTFS 磁盘上**已有父目录下的新文件夹**，不要加外层引号。
   输入 `yes` 确认位置。它供 Windows Chrome 使用；Bridge/Tunnel 仍在 Linux 内。

**应看到：** 选定 Linux 系统和用户正确，并出现信任提示。
已有安装不会迁移或重新生成密钥身份。

**若停止：** 名称不明、WSL1、系统不可用、扩展目录已被占用或不安全，都应先检查，
不要重置。完全没有已安装 Linux 系统时，入口可在你明确输入 `yes` 后提供 Ubuntu 安装，
可能要求 Windows 提权或重启。完成 Linux 用户创建及要求的重启后，再运行同一入口。
Windows 阻止脚本时，检查 Properties / Unblock，或遵循管理员正常的信任流程；
不要全局关闭执行策略。

<details>
<summary>进阶：仅在 WSL 内准备 Linux 文件</summary>

也可在 WSL 中运行已有的 `./prepare` 入口。它将扩展留在 Linux，
适用时输出经核实的 Windows 可访问路径，不会选择 Windows 本地扩展目录。
这是 Windows 入口的替代路线，不是第二个必做步骤。
正常的全新 Windows 配置请使用上面的 Start-Bridge.ps1。

</details>

<a id="4-follow-the-one-local-preparation-through-its-handoffs"></a>
<a id="4-沿同一准备流程完成各项交接"></a>
## 4. 完成准备，记下输出的位置

**留在同一个本地终端。** 准备程序会创建专用产品目录和 Python 环境、安装依赖、
查找已有 Herdr 0.9.0（或询问其 Linux 程序完整路径），并下载经核对的 Tunnel runtime
**0.0.16**。工作仓库不会搬动。
[固定的上游安装包](https://github.com/openai/tunnel-client/releases/tag/v0.0.16)与 Bridge 是两个产品。

阅读是否允许准备后的扩展查看已注册项目标识、准确的本地目录和完成元数据的请求，
范围也包括之后注册的项目；仅在接受该范围时批准。
这不提供报告正文访问权、不授予 Agent 任务权限，也不允许向任何 Chat 发送消息。
加载浏览器扩展和开启提醒仍是可选操作。

<a id="keep-the-early-private-extension-path"></a>
<a id="保存提前输出的私有扩展路径"></a>
### 将扩展目录与工作流程文件目录分开记下

服务安装前，找到 **Expected extension ID:**，以及对应路线的扩展目录标签：

| 路线 | 为可选第 9 步保留的输出 |
| --- | --- |
| 原生 Ubuntu | `Private extension Linux path:` |
| 全新 Windows 入口 | `Private extension Windows path (copy into Chrome Load unpacked):`，以及下一行完整的 Windows 本地路径 |

Windows 输出 `Windows publication is pending` 不表示完成，要等最终位置得到确认。
不要手动复制 token 或 `connection.js`。已有 Linux/仅 WSL 配置应使用输出的已核实路径，
不要猜测。若显示 `Windows extension path: unavailable/unverified`，先停止并解决路径问题。

<a id="approve-services-then-enter-credentials-locally"></a>
<a id="批准服务操作再在本地输入凭据"></a>
### 批准服务操作，在本地输入凭据，再检查结果

准备程序会为两个所属 Linux 服务请求管理员权限。它安装、启用并启动 Bridge，
再安装 Tunnel，完成配置后启用并启动 Tunnel。全新安装要求端口 **8765** 可用；
不会杀掉其他服务。不支持的 systemd/账号布局、不安全路径、符号链接、
安装器控制路径中的空格或 `/mnt` 服务路径，均可能导致停止。
显示了扩展目录不能绕过这些独立检查。

若尚未保存凭据，会出现以下本地隐藏提示：

```text
Own Tunnel ID (hidden):
Own runtime API key (hidden):
```

在本地输入完整值，不加引号或标签；字符不会回显。使用私有交互终端，
不要重定向输入或把秘密发到 Chat。已有且通过本地检查的凭据会复用，
但本地检查不证明远程角色或有效期。无需复制秘密 Bridge endpoint。

找到 **Local checks:** 和 `"bridge_mcp": "initialized_healthy"`。
它只证明本地 Bridge 完成初始化后作出了响应。Herdr 关闭时可能显示不可用，
不需要因此启动 Agent。服务正在运行不等于 Tunnel 远程访问正常，也不等于 ChatGPT 已连通。
此准备流程不会运行另一个独立的 Tunnel 就绪状态探测。

继续，直到看到：

- **Four unchanged, distinctly named Skill attachments and LICENSE:** 及其后的目录。
  为第 6 步记下它；这不是 Chrome 扩展目录。
- 可选的 **native own-App ID** 提示。**直接按 Enter**，改在第 6 步选择已有连接；
  不要从浏览器 URL 猜标识符。
- **Unchanged Web Principal Core:** 及其后的公开指令文件路径。
- `Software preparation is complete; no repository or running Herdr session/Agent is required. You may close this terminal.`

**可以继续的标志：** 准备正常结束，本地 Bridge 检查成功，并取得工作流程目录和 Core 位置。
需要提醒时，另保留扩展位置。该本地结果尚未完成 Web 插件/Skills 安装、仓库连接或提醒目的地选择。

**若停止：** 保留已完成文件和错误，参见[某一步停止时](#if-a-step-stops)。
不要叠加运行其他服务安装器，也不要重复结果未知的操作。

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

<a id="5-connect-the-tunnel-to-your-private-chatgpt-plugin"></a>
<a id="5-把-tunnel-连接到自己的私有-chatgpt-插件"></a>
## 5. 在 ChatGPT 网页连接 Bridge 并检查

**在你要使用的 ChatGPT 工作区：**

1. 打开 [Plugins](https://chatgpt.com/plugins)，使用加号控件和
   **Add custom MCP server**。起一个便于识别的名称，例如你自己的 Bridge 名称。
2. 设置 **Connection: Tunnel**，选择自己的 Tunnel。若有官方 ID 输入框，
   仅在该字段输入同一 Tunnel ID。不要把 runtime key 放进表单，也不要把二者放进 Chat 消息。

![选择了 Tunnel 的自定义连接表单示例](assets/getting-started/mcp-tunnel-form.png)

*图中身份验证仍是默认 OAuth，还未准备好。*

3. 对此私有 Bridge 连接，将 MCP 身份验证改为 **No authentication**。
   Bridge 没有 OAuth server；Tunnel 角色和受保护的本地 endpoint 仍然适用，
   不会因此建立公开的无验证 endpoint。
4. 阅读风险提示。仅在接受其范围后，选择 **I understand and want to continue**
   和 **Create as a plugin**。

![选择了 No authentication 的表单，私有 Tunnel ID 已遮盖](assets/getting-started/mcp-no-auth.png)

*只是配置示例，不证明插件已创建或安装。*

5. 审阅发现的工具，使用实际提供的 **Install** 控件。打开或创建预期 ChatGPT 项目，
   在其中打开普通对话，输入 `@` 并选择已安装的 Bridge 插件。
6. 发送下面的请求，检查实际工具结果：

> 仅调用只读 bridge_health，并显示实际结果。
> 不要注册项目、初始化状态或向 Agent 输入任务。

**应看到：** 这个普通项目对话成功返回 `bridge_health` 工具结果，且不是错误响应。
工具名、插件卡片或一句“连接正常”都不够；Herdr/Agent 是否就绪是另一项检查。

**Tunnel 缺失、访问被拒绝或调用失败时：** 核对第 2 步的工作区、组织关联与权限，
保留本地安装，不要靠重装修复账号问题。界面标签可能变化；缺少必要控件时，
在此停止并按工作区权限流程处理。
[官方 Tunnel 连接说明](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。

<a id="6-install-and-discover-all-four-native-skills"></a>
<a id="6-安装并发现全部四个原生-skills"></a>
## 6. 添加并检查四个可重复使用的工作流程

上一步连接的是**工具**。现在安装四个 **Skills**：它们分别指导连接项目、
返回项目、保存交接信息和组织独立 Agent 调查。必须成为已安装的工作流程，
不能只是对话附件。

### 找到要上传的五个文件

**在电脑上：** 打开第 4 步
**Four unchanged, distinctly named Skill attachments and LICENSE:** 后面输出的目录。
目录名为 `Creator-attachments`，准备程序已经生成，无需自己新建或拼装文件。

- **原生 Ubuntu：** 打开 **Files（文件）**，按 **Ctrl+L**，粘贴输出的目录路径，
  按 Enter。若逐层浏览时看不到 `.local`，用 **Show Hidden Files（显示隐藏文件）**
  或 **Ctrl+H** 显示。
- **Windows+WSL2：** 打开 **文件资源管理器 → Linux**，或在地址栏输入 `\\wsl$`。
  选择**第 3 步相同的 Linux 系统和用户**，再按输出的 Linux 路径找到目录。
  不要进入 Windows Chrome 扩展目录。

选择以下**五个文件**，不要选择整个目录或安装 ZIP：

| 上传的文件 | 安装后的工作流程名称 / 用途 |
| --- | --- |
| `project-onboarding.md` | `project-onboarding` — 连接已有本地项目 |
| `project-resume.md` | `project-resume` — 返回项目时恢复上下文 |
| `handoff-preparation.md` | `handoff-preparation` — 离开前保存重要信息 |
| `team-deliberation.md` | `team-deliberation` — 组织独立 Agent 工作 |
| `LICENSE` | 随工作流程保留提供的许可证 |

不要上传连接配置或私有项目笔记。目录或任意文件缺失时，停止并检查准备结果。

<details>
<summary>参考：提供的工作流程原文</summary>

具名上传文件保持以下原始指令文件不变：
[project-onboarding](../skills/project-onboarding/SKILL.md)、
[project-resume](../skills/project-resume/SKILL.md)、
[handoff-preparation](../skills/handoff-preparation/SKILL.md)、
[team-deliberation](../skills/team-deliberation/SKILL.md)。
请上传准备程序生成的具名副本，不要另下载四个都叫 `SKILL.md` 的文件。

</details>

### 打开 Plugin Creator，附加文件

**在 ChatGPT 网页：** 打开 **Plugins**，选择已有 Bridge 插件；
如果有 **Edit Plugin** 且你有编辑权限，使用它。否则打开普通对话，
输入 `@`，搜索并选择 **Plugin Creator**。
若 `@` 中没有，检查 Plugins 中是否提供，并仅在工作区允许时安装。
若不可用、被阻止，或只能在 Work 使用，就在这里停止。
[OpenAI 创建指南](https://learn.chatgpt.com/docs/build-plugins)说明了依赖权限的控件，
不保证你的账号具备资格。

点击消息输入框的**附件/添加按钮**，选择“从电脑上传文件”一类选项，
选中上面五个文件。等到**五个附件都可见且没有上传错误**，再发送：

> 请将这四个文件添加为我私有 Bridge 插件内四个独立、已安装的 Skills。
> 保留完整指令、名称、描述和 LICENSE。复用第 5 步已成功的 Bridge 连接。
> 在我完成前，展示四个完整 Skill 正文和选中的连接。
> 不要新建连接、索取密钥、分享插件、执行这些流程或发送 Agent 任务。
> 若这里无法完成，说明缺少什么并停止。

若无法编辑已有插件，可询问 Creator 能否让一个私有组合插件复用同一个已授权连接。
不要假定它一定支持，不要转换标识符、重建凭据或转到 Work/Codex 来代替本次网页配置。

### 审阅、完成，再用新的项目对话检查

1. 检查是否有**四个独立 Skills**，名称为 `project-onboarding`、`project-resume`、
   `handoff-preparation`、`team-deliberation`；安装后的名称不带 `.md`。
   将**完整正文**与提供的文件逐一比较。
2. 确认选中的 App/连接就是**第 5 步的同一个 Bridge 连接**。
   若出现连接菜单，按名称选择那个已有项目。
3. 使用实际提供的完成/保存和安装控件；安装入口可能是 **Install** 按钮，
   或插件详情中的**加号**。不要只为复现示例而授予全部工具权限。

![显示四个 Skills 已启用的开发者插件设置示例](assets/getting-started/plugin-installed-skills.png)

*蓝色开关只显示示例中的设置，不证明你已安装四个完整工作流程，
也不证明它们在普通对话可用。*

4. 在预期 ChatGPT 项目中打开一个**新的普通对话**，通过 `@` 选择得到的 Bridge 插件，发送：

   > 只读配置检查：列出这里可用的 Bridge 工具。
   > 找到已安装的 project-onboarding、project-resume、handoff-preparation、
   > team-deliberation Skills，分别显示完整指令，不要执行。
   > 仅调用 bridge_health 并显示真实结果。
   > 不要注册项目、改文件或发送 Agent 任务。

**可以继续的标志：** 实际项目对话中有 Bridge 工具（对照
[18 项工具参考](TECHNICAL-REFERENCE.zh-CN.md#tool-reference)）、真实 health 结果，
以及与提供文件一致的四个已安装 Skill 完整正文。
四个名称、上传附件或一句“已安装”都不足够；发现成功也不证明以后会可靠地自动触发。

**任意控件、上传或全文检查失败时：** 保留工作中的连接，
记录**“工具可用；四个工作流程尚未验证。”**，
保留准确且不含秘密的错误，向工作区管理员/所有者确认创建、安装或 App 访问权限。
不要重建 Tunnel 来强行发现 Skills。

Work/Codex 成功不能代替普通网页对话的检查。这是产品支持的目标场景，
不是平台强制隔离：官方文档没有给出可阻止跨界面可见性的 `web_only` 限制。
参见[打包诊断](TECHNICAL-REFERENCE.zh-CN.md#attachment-and-discovery-diagnostics)。

<a id="7-put-the-public-core-in-project-instructions"></a>
<a id="7-将-public-core-放入-project-instructions"></a>
## 7. 将基础指令保存到 ChatGPT 项目

**在浏览器中：** 打开提供的 [Web Principal Core 文本](../templates/WEB-PRINCIPAL-CORE.md)。
这是指导 ChatGPT 如何与你思考和协作的基础指令。

**在同一个 ChatGPT 项目：** 打开 **Project settings → Instructions（项目设置 → 指令）**。
把**完整公开 Core 文本**复制到该字段，同时保留相关已有规则，保持提供的文本完整。
这是保存于项目的设置，不是安装命令、Skill 附件或一条临时 Chat 消息；
它没有凭据，也不授予操作任意仓库的权限。

![私有内容已遮盖的项目 Instructions 示例](assets/getting-started/project-instructions.png)

*仅展示控件，图中没有明确保存按钮。*

使用实际存在的控件完成后，**重新打开 Instructions**，
确认全文已保存、未被截断且原有规则仍在。不要加入秘密或另一个项目的 Binding。

**应看到：** 预期项目的已保存指令含完整 Core 和保留规则。
**字段缺失、文本被拒绝或缩短时：** 停止并检查账号控件和限制；只粘贴一部分不算完成。

<a id="8-connect-your-existing-git-repository-and-merge-its-binding"></a>
<a id="8-连接已有-git-仓库并合并其-binding"></a>
## 8. 授权连接一个已有本地项目

选定要连接的**已有 Git 仓库文件夹**和简短项目标识（`project_ref`）。
使用其**完整 Linux 路径**：Ubuntu 用本机路径；Windows 用选定 WSL 系统内的路径。
Ubuntu 可在 Files 中打开项目文件夹，按 **Ctrl+L** 复制完整路径。
Windows 盘符路径或 `\\wsl$` 地址不是 Linux 路径；不确定时，先请仓库所有者确认
Linux 仓库根目录。仅有 ChatGPT 项目名称不能选中本地文件夹。

**在该项目已选择 Bridge 的普通对话中：** 用自己的话提供这两个值，再请求：

> 只用 project-onboarding 连接这个已有仓库。
> 检查注册，仅在需要时注册。返回 Project Binding 文本，供我审阅并保存到本项目指令。
> 不要创建仓库、初始化项目笔记、启动 Agents、发送任务或编辑项目文件。

返回的 **Project Binding（也称 Host Binding）**是告诉这个 ChatGPT 项目
“允许使用哪个本地仓库”的文本。将返回的目录、标识与自己的授权选择核对。
手动把它加到 **Project settings → Instructions** 的 Core 旁，
保留其他规则，再重新打开确认保存。不需要本地注册/同步命令。

**应看到：** 返回目录和标识匹配，且预期项目保存了对应 Binding。
**注册结果不确定或指向别处时：** 先查看返回的只读观察，请所有者协调；
不要悄悄重定向，也不要盲目再次注册。

若只授权连接，到此完成。用 `project_initialize` 创建初始本地状态/记忆
需要另行明确请求；注册既不授权 Agent 任务，也不选择提醒目的地。
[项目笔记与延续](PROJECT-CONTINUITY.zh-CN.md)说明这一独立层次。

<a id="9-load-the-private-extension-and-bind-this-exact-chat"></a>
<a id="9-加载私有扩展并绑定这个准确-chat"></a>
## 9. 可选：开启完成提醒

**不需要浏览器提醒，可跳到第 10 步。** Bridge 工具和 Skills 不依赖此扩展。
原生 Ubuntu 路线要求浏览器与 Bridge 在**同一台实体电脑**，才能使用此本地提醒。

**在所选电脑的 Chrome 中：**

1. 打开 `chrome://extensions`，启用 **Developer mode（开发者模式）**，
   选择 **Load unpacked（加载已解压的扩展程序）**。
2. 选**第 4 步输出的私有扩展目录**：
   **Ubuntu Chrome → 输出的 Linux 目录**；
   **Windows Chrome → 最终输出的 Windows 本地目录**。
   进阶的仅 Linux/WSL 路线，只使用输出且经过核实、适合浏览器所在系统的路径。
3. 将 Chrome 扩展 ID 与准备输出的 **Expected extension ID:** 对照。

不要选 ZIP、公开/源码目录、发行暂存目录或 `product/browser-extension/extension` 模板。
Windows 上不要用 WSL 中供发布使用的源目录替代最终 Windows 目录。
保留准备后的目录、`connection.js`、加载位置和身份，不要复制其秘密内容。
若 ID 不同或 Chrome 无法加载，停止；不要移动、卸载重装或清空存储来绕过。
全新 Ubuntu/Windows Chrome 加载、WSL UNC 加载和重启后行为尚未通过实机验收。

**在应接收提醒的准确、普通、非隐私项目对话中：**
同一个完整 Chat 路由只保留一个普通标签页。打开扩展弹出窗口：

1. 在 **本地项目** 选择注册的仓库，核对目录和身份。
2. 勾选 **允许向当前 Chat 自动发送完成提醒**。
3. 点击 **设为接收 Chat 并启用**。
4. 检查 **接收 Chat：当前 Chat** 和 **自动通知已启用**，阅读显示的错误。

在**派工前**启用，不会重放过去的完成事件。之后换对话，需要明确选择并启用那个准确对话。

真正空白且安全的输入框可自动发送一次固定提醒。有草稿或附件时，扩展会改为显示
**追加到输入框末尾（另起一行） / 忽略**。追加保留草稿，不点击 Send，
由你自行发送组合后的消息；忽略则保持草稿和文件不变。
提醒不证明任务成功，也不证明报告已评审。

**应看到：** 预期项目和准确对话显示已启用。
这只证明保存了接收方选择，不证明消息已送达。
目前仅针对**英文 ChatGPT 网页/项目对话的页面结构**验证过适配；
其他语言或界面变化可能使其等待或拒绝。
失败时查看弹出窗口的当前错误，参见
[提醒契约与恢复](LIFECYCLE-RESTART-CONTRACT.zh-CN.md#chrome-notification-authority-and-recovery)；
不要清空存储或重复结果未知的发送。

<details>
<summary>进阶：准确的投递、草稿与不重放边界</summary>

**派工前绑定**：首次启用不重放旧完成事件。每个本地项目只有一个明确接收方；添加项目或打开另一个 Chat 不会选择它。更换时，明确选择新的当前 Chat 并再次授权启用。只有保存了有效路由、可证明从未尝试的 queued/waiting 提醒，才可跟随进行**首次发送**。旧的已尝试、结果不确定或冻结身份绝不迁移或重放，即使之后切回原 Chat、worker 重启或生产者 epoch 改变也一样。保留的原始 ID 抑制证据不会阻塞不同的新 Work，也不会产生常驻警告；不要清空 storage 绕过。128 上限针对实际未尝试的待处理提醒，不是已结束历史。

真正空白且安全的输入框可以自动发送固定通知一次。有文字、富内容或已上传文件的草稿则显示不修改内容的行内 **追加到输入框末尾（另起一行） / 忽略** 选项，打字或使用 IME 时也能显示。忽略保留当前草稿和附件不变。追加在当前 IME 组合结束后，只向当前绑定的编辑器末尾添加一段固定通知；不会点击 Send、替换草稿或把文件内容传给 worker。正常编辑及附件变化不需要静默等待。如果在异步追加执行前先提交消息，旧选择会被拒绝；请为当前消息重新选择。未选择的提醒在刷新/关闭后仍待处理；下一次普通轮询会重新检查准确 Chat，再次提供选项或走安全的空输入框路径。

本地 Send 点击或成功的显式选择只表示本地已处理一次，不证明 ChatGPT 收到消息或后端已确认。结果未知时不重试。不扫描对话/收件回执，也不以通知历史界面或旧未知常驻警告确认送达；仍保留当前错误及待处理诊断。

</details>

<a id="10-begin-daily-use-with-a-bounded-read-only-check"></a>
<a id="10-从范围明确的只读检查开始日常使用"></a>
## 10. 先做一次小范围只读检查

**在已连接的普通项目对话中：** 指定授权仓库中的一个非秘密文件，请求：

> 只查看本项目当前上下文和我指定的文件，再总结能从中核实的内容。
> 不要改文件、执行命令/测试、做 Git 操作、初始化笔记或向 Agent 输入。

核对返回的目录/标识和引用内容。**应看到：** 确实从正确项目读取了指定文件。
这只验证实际读取路径，不会创建 Agent 任务或完成提醒。项目或文件不符时，
先停止并解决选择问题，再授权更多操作。

### 需要 Agents 做真实工作时

在**同一个选定 Linux 环境打开 Herdr**，进入授权 Git 文件夹，再启动并登录受支持的 Agent。
已有合适会话就复用。Bridge 不会替你安装或启动 Herdr、供应商或 Agents。
打开网页对话可以早于或晚于启动它们。

请 ChatGPT 刷新项目上下文，展示实际可用的 Agents。
观察失败或不完整表示未知，不表示“没有 Agents”。
再说明问题、允许的改动和验收条件，并明确授权向实际观察到的合格 Agent 输入。
ChatGPT 必须通过 `work_report` 读取完整报告，使用完整报告 SHA（内容指纹）固定内容并完成全部分页，
再检查相关代码、diff 和测试证据，才能验收结论。提醒不等于完成这些评审。
[发票演示](QUICKSTART.zh-CN.md#optional-invoice-demo)可选，不授予启动演示 Agent 的权限。

**不需要每天重新准备。** 电脑、网络和已安装服务可用时，
不必仅为 Bridge 连接而一直开着准备终端或 Herdr。
Ubuntu 重启/挂起、Windows 注销和 WSL 关闭/挂起是独立的可用性边界，
未声称已经通过重启验收。[可选的 Windows WSL 登录助手](AUTOSTART.zh-CN.md)
需要另行决定是否使用；原生 Ubuntu 不需要它。

**没有授权真实任务时，只读检查后就停止。**
工具访问、已安装指令或提醒设置都不会扩大授权。

<a id="if-a-step-stops"></a>
<a id="如果某一步停止"></a>
## 某一步停止时

保留已完成文件和准确的**非秘密**错误。不知道操作是否已经产生改动时，
先检查再尝试，不要靠重置、重放或重装猜测。

| 看到什么 | 下一步怎么做 |
| --- | --- |
| 项目 Instructions 缺失、拒绝文本或截断 | 检查实际账号控件和文本限制，保留原有规则；不要把部分 Core 粘贴算作完成。 |
| 复制或安装时准备停止 | 保留文件。先检查失败，再决定是否用同一发行版、路径和 Linux 用户重新进入；匹配文件会复用，所属的部分 Python 环境可继续完成，未知变化会停止。另一版本不是自动升级。不要删除准备记录、生成的 key 或目录。 |
| Windows 目录发布停止 | 保留记录的目标和暂存文件。不要另选目录、移动原扩展或手动复制秘密。重试前查看诊断；较早尝试可能已进入服务配置。 |
| 有 Linux 扩展路径，但 Windows 路径未经核实 | 检查所选 WSL 系统及路径转换，不要猜 Windows 路径，也不要当作 Chrome 已加载。 |
| 服务安装/启动失败或结果未知 | 保留安装，按对应层的 [Bridge 状态与归属指引](AUTOSTART.zh-CN.md#bridge-component-contract)或 [Tunnel 状态与归属指引](AUTOSTART.zh-CN.md#tunnel-component-contract)检查。不要杀掉其他服务或重复结果未知的启动。 |
| ChatGPT 没有 Tunnel，或出现 403 | 核对所属组织、目标工作区关联、操作账号/密钥所属账号的 Tunnel 角色，以及 Restricted Read + Use 权限。解决访问问题，不要另装一套本地程序。 |
| 工具可用，四个 Skills 不可用 | 保留连接，解决 Creator/安装权限，在普通网页对话核实已安装全文。 |
| 注册结果未知或与已有路由冲突 | 查看只读注册结果，请所有者协调；不要重定向或盲目再次注册。 |
| 提醒等待或结果未知 | 在准确绑定的对话查看追加/忽略和当前诊断。Stop、空输入框中的活动输入法组合、上传或不安全的输入框状态可延迟自动发送。旧未知 ID 是静默抑制记录，不是重放理由。不要清空存储或把模拟诊断当首次使用测试。 |
| 已保存密钥错误或过期 | 使用下方同一发行版的显式 credentials 操作；不要在 Chat 发送替代值。 |

<details>
<summary>进阶恢复：状态检查、凭据更换与旧安装</summary>

仅恢复时使用：Windows `.\Start-Bridge.ps1 status`（Linux `./prepare status`）
报告准备文件是否存在，**不是服务健康**。独立 Tunnel status 可报告
`tunnel_startup: ready`，但仍未建立控制面验证或网页就绪证明。
实际项目对话中的 `bridge_health` 结果才是远程检查点。
不要把重复状态命令变成每日仪式。

确需更换保存的 key 时，从同一发行版运行 `.\Start-Bridge.ps1 credentials`
（Linux `./prepare credentials`）。确认替换后，在本地隐藏提示输入。
最初不改变服务，之后另行询问是否允许用 sudo 停止/启动**仅所属 Tunnel 服务**；
拒绝会推迟激活。后续变更前先检查未知结果，Bridge 自身无需重启。
这是恢复操作，不是第二条首次使用路线。

旧扩展接管需要单独授权；保留原始路径、ID/key、token 和历史。
[扩展参考](LIFECYCLE-RESTART-CONTRACT.zh-CN.md#chrome-notification-authority-and-recovery)
与服务参考说明各自契约，不是另一套必做安装步骤。

</details>
