<a id="install-bridge-and-begin-in-an-ordinary-chatgpt-project-chat"></a>
<a id="安装-bridge并在普通-chatgpt-project-chat-中开始使用"></a>
# 配置 Bridge，在 ChatGPT 网页中开始使用

[English](GETTING-STARTED.md) | [简体中文](GETTING-STARTED.zh-CN.md)

先按这条简短路线走，点击链接查看具体按钮和提示。
配置时不需要运行 Agent，安装需要联网。

| 顺序 | 做什么 |
| --- | --- |
| 1 | [检查账号和电脑](#1-obtain-the-complete-release-and-check-prerequisites)，先准备 Linux Herdr **0.9.0**。 |
| 2 | [下载完整安装包](#download-the-complete-package)。 |
| 3 | [准备自己的 Tunnel 和受限运行密钥](#2-prepare-your-tunnel-and-restricted-runtime-key-privately)，不要发到对话里。 |
| 4 | 在解压目录里运行 [Ubuntu `./prepare`](#native-ubuntu-desktop) **或** [PowerShell `.\Start-Bridge.ps1 prepare`](#windows-and-wsl2)，准备两个服务。 |
| 5 | [在网页上添加连接，检查 bridge_health](#5-connect-the-tunnel-to-your-private-chatgpt-plugin)。 |
| 6 | [上传一个 `Bridge-Skills.zip`，安装全部四个 Skills](#6-install-and-discover-all-four-native-skills)。 |
| 7 | [保存 Core 和自己项目的 Binding](#7-put-the-public-core-in-project-instructions)。 |
| 8 | [读取一个指定文件，开始日常使用](#10-begin-daily-use-with-a-bounded-read-only-check)。 |

**成功后再选：**[Chrome 完成提醒](#9-load-the-private-extension-and-bind-this-exact-chat)。

<a id="choose-your-computer"></a>
<a id="1-obtain-the-complete-release-and-check-prerequisites"></a>
<a id="1-获取完整发行包并核对前置条件"></a>
## 1. 安装前，先确认账号和电脑

在**你准备使用的 ChatGPT 工作区**里，确认能做到这三件事：

- 打开 [Plugins](https://chatgpt.com/plugins)，添加 **custom MCP server（自定义 MCP 服务器）**。
- 在普通网页对话中使用 **Plugin Creator**，创建并安装原生 **Skills**。
- 打开 ChatGPT **Project（项目）**，编辑 **Instructions（项目指令）**。

入口取决于账号和工作区，按钮名称也可能与示例不同。缺少入口或被禁止时，
**先停在这里，向工作区管理员确认资格，再安装本地软件**。
能用 Work 或本地 Codex 不代表能完成这套网页设置。不需另设模型 API Principal；
下面的 Tunnel 需要自己的运行密钥。

| 你的电脑 | 本教程的安装路线 |
| --- | --- |
| **原生 Ubuntu 桌面** | 使用 Ubuntu 终端，systemd 已作为 PID 1 运行，Python 3.10+，Linux `x86_64` 或 `aarch64`。不需要 WSL 或 PowerShell。 |
| **Windows + WSL2 Ubuntu** | 从 Windows PowerShell 启动所选 WSL2 发行版，以其默认的非 root Linux 用户安装。里面同样需要 systemd、Python 和上述架构。 |

Windows 尚未准备好 WSL2 或 systemd 时，先单独完成
[Microsoft 的 WSL 设置](https://learn.microsoft.com/windows/wsl/install)和
[systemd 设置](https://learn.microsoft.com/windows/wsl/systemd)。
本教程不是原生 Windows/macOS 或 WSL1 路线；无桌面的 Ubuntu Server 属于
[进阶用法](QUICKSTART.zh-CN.md#native-ubuntu-desktop-and-server)，浏览器和 Agent 会话另有限制。

<a id="herdr-090-prerequisite"></a>
### Herdr 0.9.0 前提条件——不必启动服务或 Agent

原生 Ubuntu 打开**终端**；Windows 打开**选定的 Ubuntu 发行版**，
以稍后安装 Bridge 的同一 Linux 用户使用 Bash。
下面是 Linux 命令，不在 PowerShell 执行；Windows 的 `herdr.exe` 不能替代它。
先检查，并记下输出的可执行文件路径：

```bash
command -v herdr
herdr --version
```

如果显示 **0.9.0**，直接继续第 2 步；否则用下面的固定版本下载。
需要 `curl` 和 `sha256sum`，Ubuntu 缺少时先运行 `sudo apt install curl coreutils`。
通用 Herdr 安装器会跟随最新版，这里不要替换使用。
网址和摘要沿用[官方 v0.9.0 发行版](https://github.com/herdrdev/herdr/releases/tag/v0.9.0)
及其[发布元数据](https://api.github.com/repos/herdrdev/herdr/releases/tags/v0.9.0)。

整块复制执行：它会选择 `x86_64` 或 `aarch64`/`arm64`，在项目外新建私有版本目录，
**先校验 SHA256，再赋予执行权限**，最后显示版本和完整路径。
不覆盖已有目录，也不修改你保存的 PATH。

```bash
(
  set -euo pipefail
  umask 077
  command -v curl >/dev/null
  command -v sha256sum >/dev/null
  case "$(uname -m)" in
    x86_64)
      asset=herdr-linux-x86_64
      digest=4fa1a01158dd8043da92d31b270780b0dcc10603038d9b61cac4d81ab63fb71f
      ;;
    aarch64|arm64)
      asset=herdr-linux-aarch64
      digest=9c8db20fb7e7427b138d5367113f1621ffd319f2f65d6f009e2594029115f0d2
      ;;
    *) printf 'No pinned asset in this guide for this architecture.\n' >&2; exit 1 ;;
  esac
  [[ "$HOME" = /* ]] || { printf 'HOME must be an absolute path.\n' >&2; exit 1; }
  for parent in "$HOME" "$HOME/.local" "$HOME/.local/opt"; do
    if [[ -L "$parent" || ( -e "$parent" && ( ! -d "$parent" || ! -O "$parent" ) ) ]]; then
      printf 'Refusing an unsafe installation parent.\n' >&2
      exit 1
    fi
  done
  version_dir="$HOME/.local/opt/herdr-v0.9.0"
  if [[ -e "$version_dir" || -L "$version_dir" ]]; then
    printf 'Version directory already exists; stop and inspect it.\n' >&2
    exit 1
  fi
  mkdir -p -- "$HOME/.local/opt"
  mkdir -m 700 -- "$version_dir"
  cd -- "$version_dir"
  curl --fail --location --proto '=https' --proto-redir '=https' \
    --output herdr.download \
    "https://github.com/herdrdev/herdr/releases/download/v0.9.0/$asset"
  printf '%s  herdr.download\n' "$digest" | sha256sum -c -
  chmod 700 -- herdr.download
  mv -- herdr.download herdr
  ./herdr --version
  printf 'Herdr executable: %s/herdr\n' "$version_dir"
)
```

只有整块成功且显示 **0.9.0** 才继续。记下输出的**完整可执行文件路径**：
如果 Herdr 不在 PATH，prepare 询问位置时就填它。
**留在这份 Getting Started 入门页，继续第 2 步。仅安装 Bridge 不需要启动 Herdr 服务、
Agent、读取 snapshot 或登录 Agent 提供商。** Windows 到第 4 步运行 Bridge 命令时再回 PowerShell。

<a id="download-the-complete-package"></a>
## 2. 下载完整安装包

下载完整安装 ZIP
[**gpt-agent-bridge-v0.1.0-rc.8.zip**](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/download/v0.1.0-rc.8/gpt-agent-bridge-v0.1.0-rc.8.zip)
（[v0.1.0-rc.8 发布页面](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/tag/v0.1.0-rc.8)）。
使用完整发行 ZIP；GitHub 的 **Source code (zip)** 和 **Code → Download ZIP** 不是安装包。

把 **ZIP 完整解压**到自己的文件夹，保留所有文件。
根目录须有 `prepare`、`Start-Bridge.ps1`、`release-manifest.json` 和 `Bridge-Skills.zip`。
若解压后缺少 `Bridge-Skills.zip`，说明该下载不是这些步骤所需的完整安装包；
请从发布页面获取当前完整包。

<a id="2-prepare-your-tunnel-and-restricted-runtime-key-privately"></a>
<a id="2-私下准备-tunnel-和受限-runtime-key"></a>
## 3. 准备自己的 Tunnel 和运行密钥

打开 [Platform 隧道设置](https://platform.openai.com/settings/organization/tunnels)，
选对组织，创建自己的 Tunnel，并关联到**第 1 步选定的 ChatGPT 工作区**。
私下保留完整 Tunnel ID。创建、编辑需要 **Tunnels Read + Manage**；
运行、选择隧道需要 **Read + Use**。缺少选项时请找管理员。

在同一组织的 [API 密钥设置](https://platform.openai.com/settings/organization/api-keys)
创建 **Restricted（受限）运行密钥，只授予 Tunnels Read + Use**。
不要用 Admin key 或 All 权限。按自己的用途设置有效期并记住到期时间。
稍后只在安装器的**本地隐藏输入提示**里填 ID 和密钥，不发到对话、附件、截图或报告中。
账户费用与额度请另行确认。

<details>
<summary>账号设置示例图（你的按钮和可用选项可能不同）</summary>

![Tunnel 工作区关联示例](assets/getting-started/platform-tunnel-workspace.png)
![密钥有效期示例](assets/getting-started/runtime-key-expiration.png)
![Restricted 密钥选项示例](assets/getting-started/runtime-key-restricted.png)
![Tunnels 权限示例](assets/getting-started/runtime-key-tunnels.png)

</details>

<a id="3-start-preparation-and-confirm-the-exact-wsl2-distro"></a>
<a id="3-开始准备并确认准确的-wsl2-distro"></a>
## 4. 准备本地核心，只选一条路线

<a id="native-ubuntu-desktop"></a>
### 原生 Ubuntu 桌面

在**文件管理器（Files）**中双击打开解压后的文件夹，右键空白处，选择**在终端打开**。
如果没有这个选项，打开终端，用 `cd` 加上从文件管理器复制的完整目录路径，例如：

```bash
cd "/完整路径/解压后的文件夹"
./prepare
```

先替换示例路径，确认当前文件夹里有 `prepare`。使用自己的普通 Linux 用户，
**不要执行 `sudo ./prepare`**。

<a id="windows-and-wsl2"></a>
### Windows + WSL2

在**文件资源管理器**中双击打开解压后的文件夹，点击地址栏，输入 `powershell`
并回车，就会在**这个文件夹**打开 PowerShell。运行：

```powershell
.\Start-Bridge.ps1 prepare
```

选择装有 Linux Herdr 0.9.0 的那个 WSL2 发行版。它的**默认 Linux 用户**拥有此次安装；
核对程序显示的发行版和用户选择。若 WSL 要求先创建用户或重启，先完成这些步骤。
若 Windows 禁止运行脚本，请向管理员确认本地策略，不要绕过。
这不是原生 Windows Bridge 安装。

<a id="4-follow-the-one-local-preparation-through-its-handoffs"></a>
<a id="4-沿同一准备流程完成各项交接"></a>
<a id="approve-services-then-enter-credentials-locally"></a>
<a id="批准服务操作再在本地输入凭据"></a>
### 这一步会改什么，怎样才算本地准备完成

程序先询问是否信任安装包，征得同意后补齐缺少的 Python/venv/Git，
创建专用应用副本和 Python 环境，下载固定版本的 Tunnel 客户端。
经你的 sudo 授权，它会**安装、设为开机启动，并立即启动两个 Linux systemd 服务**：
`gpt-agent-bridge-autostart.service` 和 `gpt-agent-bridge-tunnel.service`。
sudo 密码是 Linux 用户密码；后面的隐藏输入才填 Tunnel ID 和运行密钥。
这些凭据保存在受保护的本地文件中。
Tunnel 安装阶段先显示 `inactive` / `disabled` 是中间状态，后面才输入凭据并启动；
最后是否完成，要看下面的最终检查。

默认准备**不会**生成或配置 Chrome 提醒扩展，不询问 Windows 扩展文件夹，也不问 App ID。
正常结束时，记下两处输出：

- **Skills upload:** 第 6 步直接选择自己解压的安装包根目录里的
  `Bridge-Skills.zip`，不用寻找隐藏文件夹。
- **Unchanged Web Principal Core:** 后面的公开指令文件，第 7 步要用。

`Local checks:` 中的 `"bridge_mcp": "initialized_healthy"` 只表示**本地** Bridge 能响应。
Herdr 关闭时可以显示不可用。服务检查通过，不代表 ChatGPT 或四个 Skills 已连好。
程序正常结束后可以关闭终端，继续网页步骤。中途停止则看[下面的排错](#if-a-step-stops)。

<a id="5-connect-the-tunnel-to-your-private-chatgpt-plugin"></a>
<a id="5-把-tunnel-连接到自己的私有-chatgpt-插件"></a>
## 5. 在网页上添加连接

1. 在同一工作区打开 **Plugins → + → Add custom MCP server**，为自己的 Bridge 连接起个好认的名字。
2. 选择 **Connection: Tunnel**，再选自己的 Tunnel。如果有官方 Tunnel ID 输入框，只在那里填 ID；运行密钥**不填进这个表单**。
3. 把默认 OAuth 改成 **No authentication（无需认证）**。Bridge 没有 OAuth 服务端，私有 Tunnel 权限和本地端点保护仍然生效。阅读风险提示后，按页面提供的 **Create as a plugin** 和 **Install** 完成创建、安装。
4. 在目标 ChatGPT Project 中打开普通对话，输入 `@` 选择 Bridge 插件，发送：

   > 只调用只读 bridge_health，展示实际工具结果。不要注册项目、修改文件或向 Agent 发任务。

只有这个网页对话里出现**成功且无错误的实际工具结果**，才继续。
插件卡片、本地服务 `active` 或一句“已连接”都不能代替它；Herdr 是否就绪另看。
看不到 Tunnel 时，核对组织、工作区关联与 Read + Use 权限，保留本地安装。

<details>
<summary>网页连接表单示例</summary>

![选了 Tunnel，默认 OAuth 仍需更改](assets/getting-started/mcp-tunnel-form.png)
![No authentication 选择示例](assets/getting-started/mcp-no-auth.png)

</details>

<a id="6-install-and-discover-all-four-native-skills"></a>
<a id="6-安装并发现全部四个原生-skills"></a>
## 6. 安装四个 Skills

在自己解压的安装包根目录选择 **Bridge-Skills.zip**。
在普通网页对话中 `@Plugin Creator`，**只上传这一个文件**。
Windows 直接在解压的 Windows 文件夹选择，不用到 WSL 里找隐藏路径。
这是素材 ZIP，内含四份规范的 `skills/<名称>/SKILL.md` 和 `LICENSE`，
不是完整插件包，也不包含新的 MCP 连接：

| ZIP 中的流程 | 用途 |
| --- | --- |
| `project-onboarding` | 连接已有 Git 项目，另行询问是否建立笔记 |
| `project-resume` | 在新 Chat 恢复项目上下文 |
| `handoff-preparation` | 离开前保存决策 |
| `team-deliberation` | 组织独立 Agent 工作 |

把占位文字替换为第 5 步 health 已成功的个人 Bridge 插件显示名，等 ZIP 上传完成后发送：

> 用这个 ZIP 更新我已有的个人 Bridge 插件【第 5 步 health 已成功的个人 Bridge 插件显示名】，
> 安装四个原生 Skills：project-onboarding、project-resume、handoff-preparation、team-deliberation。
> 完整保留所附 Skill 指令和 LICENSE，保持该插件现有的 MCP 连接和名称不变。
> 不新建插件或 MCP 连接，不向我索要密钥，不做项目操作。
> 无法唯一识别这个插件时先问我，不要猜。完成后简短列出插件名和四个 Skill 名称。

Creator 完成后，只使用页面实际提供的保存、完成或安装控件。打开插件列表并刷新
（没有刷新控件就关闭再打开列表；必要时刷新网页）。然后在目标 Project 新建**普通对话**，
`@` **同一个 Bridge 插件**，发送：

> 检查连接：调用 bridge_health，展示实际结果。不要注册项目、修改文件或向 Agent 派工。

健康调用成功即确认连接。再在插件的 Skill 列表确认四个已安装条目名称：
project-onboarding、project-resume、handoff-preparation、team-deliberation。
有这些名称和健康结果，就继续第 7 步。这里不需要手填 App ID 或修改配置。

<details>
<summary>已安装 Skills 的界面示例</summary>

![示例设置，不是你的对话发现结果](assets/getting-started/plugin-installed-skills.png)

</details>

<a id="7-put-the-public-core-in-project-instructions"></a>
<a id="7-将-public-core-放入-project-instructions"></a>
## 7. 保存基础指令，连接一次自己的项目

打开程序输出的 Core 文件，或[网页基础指令 Core](../templates/WEB-PRINCIPAL-CORE.md)。
把**全文**放入 ChatGPT Project 的 **Instructions（项目指令）**，保留已有的相关规则。
完成保存后重新打开，确认内容没有截断。这是项目设置，不是临时发一条对话消息，也不是 Skill 附件。

![项目指令入口示例](assets/getting-started/project-instructions.png)

<a id="8-connect-your-existing-git-repository-and-merge-its-binding"></a>
<a id="8-连接已有-git-仓库并合并其-binding"></a>
在该项目对话里，把路径和简短项目代号换成自己的：

> 用 project-onboarding 连接已有仓库 /absolute/linux/repo，项目代号 MY_PROJECT。
> 只注册并返回 Project Binding，不初始化笔记、不改项目文件、不向 Agent 派工。

核对返回的 **Project Binding（项目绑定指令）**，保存到 Core 和已有项目规则旁。
每个项目做一次。仅当连续性明确报告 `manifest_missing` 时，onboarding 会接着说明
“仓库已连通，但 Bridge 尚未识别到可用的项目连续性配置”，问一次**“要设置项目笔记吗？”**。
missing 不证明从未建立过笔记，也不允许覆盖非规范目录。
拒绝或不回答就不写笔记；仍可授权读取普通文件。

想建立时，再单独回复：

> 同意为 MY_PROJECT 建立项目笔记。先和我确认目标、当前进展和已确认的决定，
> 使用项目真实已有的规则文件；不要编造规则或覆盖已有笔记。

没有已有规则文件时必须停止并说明前提。已有笔记目录不规范或写入结果未知时，
先核查，不能强行初始化。只有核实路由和发布内容后才算连续性就绪；注册或读到一个文件不等于就绪。

<a id="10-begin-daily-use-with-a-bounded-read-only-check"></a>
<a id="10-从范围明确的只读检查开始日常使用"></a>
## 8. 先读一个文件，再开始日常使用

选择仓库里一个已知不含秘密的文件，替换下面的示例项目代号和文件名：

> 在项目 MY_PROJECT 中，只读取 README.md 并说明内容。不要编辑文件、执行命令、提交或向 Agent 派工。

核对实际项目和文件结果。这一步读取在项目笔记建立之前就能完成；
第 7 步的笔记设置在你需要时再做。
笔记就绪后，换 Chat 前说“对 MY_PROJECT 使用 handoff-preparation，保存已授权的判断和原因”；
在新项目对话 `@` 同一插件，说“对 MY_PROJECT 使用 project-resume，读笔记并说明下一项允许的行动”。
权限和结果未知的边界见[项目延续](PROJECT-CONTINUITY.zh-CN.md#before-changing-chats)。
没有 Chrome 提醒也可以使用这个网页对话。
以后需要委派时，自己打开 Herdr，在那个仓库启动获授权的 Agents，再请求新上下文，
选择实际可用的 Agent，说明任务与允许修改范围。投递结果未知时不要重发任务。
日常使用不需要再运行 prepare。

<a id="9-load-the-private-extension-and-bind-this-exact-chat"></a>
<a id="9-加载私有扩展并绑定这个准确-chat"></a>
<a id="keep-the-early-private-extension-path"></a>
<a id="保存提前输出的私有扩展路径"></a>
## 成功之后再选：Chrome 完成提醒

回到解压后的安装包文件夹，**只执行自己平台的命令**：

```bash
./prepare reminders
```

```powershell
.\Start-Bridge.ps1 reminders
```

这一步要求已完成核心安装，且支持 `reminders` 动作。
只有想要提醒时，才同意读取项目和完成事件元数据。
Windows 全新提醒设置会询问一个新的、私有的 Windows 本地 NTFS 文件夹；
已有提醒安装会保留原来的身份和加载目录。

记下输出的**私有扩展路径和预期扩展 ID**。
Chrome 打开 `chrome://extensions`，启用开发者模式，选择 **Load unpacked（加载已解压的扩展）**，
选那个准确文件夹，核对扩展 ID。Windows 要用最终 Windows 路径，不是 Linux 暂存目录。
不要加载源码模板，也不要为消除错误而移动或重建已有扩展。

扩展弹窗的**通知语言**默认中文，可切换为 English 或中文。偏好会持久保存，仅影响新提醒；切换不会重发或迁移已有通知，也不会改变 ChatGPT 网页界面的语言。

打开目标项目对话，在扩展中选中**这个准确标签页**，明确 **bind/enable（绑定并启用）**后再委派。
每个对话都要自己选择。提醒不代表任务成功或报告已读；已有草稿会保留，追加的提醒不会代你发送。
发送失败或结果未知时不能重放。非英文 ChatGPT 界面可能因主控识别受阻；
`PRIMARY_UNKNOWN_OR_AMBIGUOUS` 也可能由其他原因导致。先核对选中的准确对话和可见控件，
可临时切换 ChatGPT 英文界面排查语言因素。更多提醒限制见
[生命周期契约](LIFECYCLE-RESTART-CONTRACT.zh-CN.md#chrome-notification-authority-and-recovery)。

<a id="if-a-step-stops"></a>
<a id="如果某一步停止"></a>
## 某一步停止时

| 停在哪里 | 怎么处理 |
| --- | --- |
| 缺少账号入口 | 先问工作区管理员。本地重装不能开通网页 MCP 或 Skills 权限。 |
| 准备报告路径权限或服务错误 | 保留准确且不含秘密的错误码、阶段和路径供检查。诊断后只修明确指出、由自己控制的路径，不要改整个工作区的权限或替换生成文件。 |
| 本地检查通过，网页调用失败 | 核对同一工作区和 Tunnel 的关联、密钥有效期与权限。本地服务运行不代表远程认证成功。 |
| 工具能用，Skills 不能用 | 保留已连通的连接，检查 Creator 安装权限和四个已安装条目；重装 Tunnel 不能修好 Skill 发现。 |
| 可选提醒停止 | 保留记录的目录、配对和草稿。核心使用不要求提醒；不要重置身份或重试未知发送。 |

**只读查看服务状态**见[自启动页面](AUTOSTART.zh-CN.md#already-completed-prepare-start-here)。
请保密凭据，不要公开原始日志或含秘密的 URL。
[Quickstart](QUICKSTART.zh-CN.md) 是进阶手动前台路线，不是正常准备之后再做一遍的步骤。
