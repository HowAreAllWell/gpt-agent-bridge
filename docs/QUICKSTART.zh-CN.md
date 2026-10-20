<a id="developer-quickstart"></a>

# 开发者快速入门

[English](QUICKSTART.md) | [简体中文](QUICKSTART.zh-CN.md)

**第一次安装 Bridge？**请按[入门指南](GETTING-STARTED.zh-CN.md)操作，其中分别提供
**原生 Ubuntu Desktop** 和 **Windows + WSL2** 路线。完成入门后，无需再执行本页。

本页是**进阶的手动前台路线**：一个终端运行 Bridge，另一个终端运行用于 Web 连接的
Tunnel 客户端。关闭任一进程都会中断这条连接。需要检查源码安装或排错时才选择它，
不要把它当成第二轮安装步骤。

**已经完成 `./prepare`？**该命令会创建自己的应用副本、Python 环境和扩展文件，
然后在支持 systemd 的 Linux 上安装、启用并启动 **Bridge 和 Tunnel 两个服务**。
它是安装器，不只是前提检查。不要在这些服务旁再运行下面的前台副本。
管理服务请阅读[自动启动指南](AUTOSTART.zh-CN.md)。

<a id="choose-your-terminal"></a>

### 先选对终端

| 你的电脑 | 在哪里操作 |
| --- | --- |
| **直接安装的 Ubuntu Desktop** | 打开 **终端（Terminal）**，以普通 Linux 用户使用 Bash，文件放在主目录下。跳过所有 Windows/WSL 小节；不需要 WSL 或 PowerShell。 |
| **Windows + WSL2 Ubuntu** | 先看 [Windows 与 WSL2](#windows-and-wsl2)。以自己的 Linux 用户打开选定 Ubuntu 发行版，Bash 代码块都在里面执行。只有标为 PowerShell 的代码块才在 PowerShell 中执行。 |
| **Ubuntu Server / 无桌面** | 仅供进阶使用：在服务器上运行 Bash。Bridge、Herdr 和 Tunnel 客户端须处于同一 Linux 环境。远端 ChatGPT 浏览器可通过 Tunnel 使用工具，但不能假定其本地扩展能访问服务器的回环提醒接口；浏览器提醒须另行验证。 |

命令要求 Git、**Python 3.10+ 及 venv**、Bash 和 GNU coreutils。
venv 是独立的 Python 包环境，本页对应源码检出目录（Git 克隆生成的文件夹）里的 `.venv`。
Bridge 不安装 Herdr、Agent CLI，也不替你登录提供商。
本页不支持 Windows/macOS 原生 Bridge 或 WSL1。维护者已有 WSL 使用经验；
**全新原生 Ubuntu、全新 WSL2 及新账户 Web 设置尚未完成实机验收**。

<a id="pick-one-route-before-starting"></a>

### 开始前只选一条路线

- **正常安装：**转到[入门指南](GETTING-STARTED.zh-CN.md)，无需继续本页。
- **手动本地检查：**执行下方第 1–4 步。这检查本机，不验证 ChatGPT。
- **手动 Web 连接：**完成第 1–2 步和 [Tunnel 准备第 1–3 步](#foreground-secure-mcp-tunnel)，
  再运行下方第 3 步和[组合第 4 步](#combined-step-4)。**跳过独立第 4 步**：
  它会删除组合代码块需要的一次性私有令牌交接文件。
- **手动安装服务，替代前台运行：**完成第 1–2 步后转到[自动启动](AUTOSTART.zh-CN.md)，不要再启动前台进程。

Web 目标是普通 **ChatGPT Web Project Chat**。Work 或本地 Codex 成功不等于通过此检查；
这个支持目标不代表平台强制只在 Web 显示插件。

<a id="1-prepare-herdr-and-an-existing-agent"></a>

## 1. 准备 Herdr 和已有 Agent

你需要 Git、支持 `venv` 的 Python 3.10+，以及位于 Bridge 进程 `PATH` 中的 Herdr，或在启动 Bridge 前通过绝对路径 `BRIDGE_HERDR_BIN` 选择 Herdr。根据维护者现有的可用环境，**本发行版推荐 Herdr v0.9.0**；该环境报告 v0.9.3 不兼容。先按 [Herdr 兼容性指南](#herdr-compatibility-and-version-selection)检查已有安装，或选择独立安装且已校验摘要的 v0.9.0 二进制文件。不要重新安装已可用的 0.9.0 环境。通用官方安装器跟随最新版本，不会固定到这个版本。Herdr 是独立前提条件，不是 Python 依赖。

首次使用演示需要先在第 2 步克隆 Bridge 源码，并在启动 Agent 或注册前[准备独立的演示 Git 根目录](#bootstrap-your-own-disposable-git-repository)。演示的初始提交是可选的。[可选 Herdr/Codex 演示](#optional-demo-agent-with-herdr)说明如何安装、登录，并在已观察到的空闲 shell 窗格中启动。服务端和客户端步骤使用 Bridge 代码检出目录，演示 Agent 和 project_register 使用演示根目录；两者必须分开。

委派任务时（而非安装 Bridge 或检查健康状态时），需要 Herdr 已运行，并在你打算使用的 Git 检出目录中已有真实、已启动的 Herdr 管理的编码 Agents。选择提供商和模型，并确认有可用额度。Bridge 不会替你创建或启动 Agents。在 **Ubuntu 终端**或选定的 **WSL Ubuntu Bash** 中，以普通用户运行以下只读命令检查 CLI 和现有会话；这三个观察命令不要求特定当前目录：

```sh
command -v herdr
herdr --version
herdr api snapshot
```

**检查结果：**第一条应打印 Linux 可执行文件路径，第二条应报告 `0.9.0`，快照应成功。找不到程序或版本不符时，按上方兼容性小节处理，不要随意安装最新版。快照失败表示 Herdr 会话尚不可用，委派前应先在 Herdr 解决；不要分享原始输出。

委派前，快照必须成功，并显示预期的现有 Agents。可以先启动 Bridge 及其 Web 工具；之后再打开 Herdr 和启动 Agent 时，无需每天重新 prepare 或重启。仅在 `PATH` 找到 CLI 并不能证明会话可用或存在符合条件的项目 Agent。若会话输出含本地路径或终端信息，请保密。

<a id="2-clone-and-install-direct-dependencies"></a>

## 2. 克隆并安装直接依赖

在 **Ubuntu 终端 / WSL Ubuntu Bash** 中先回到 Linux 主目录（`cd ~`），不要在 Windows 盘或另一个 Bridge 检出中操作。下方代码块会新建 `gpt-agent-bridge` 文件夹、进入它、创建 `.venv` 并安装 Python 包。如果该文件夹已存在，先停止检查，不要覆盖克隆。也可替换成自己的 fork URL。

这是**源码克隆 + 手动 pip 安装**，不是完整发行包安装器。它不会生成完整安装 ZIP、配置 Chrome、安装服务、连接 ChatGPT 或安装四个 Skills。这些是[入门指南](GETTING-STARTED.zh-CN.md)中的独立步骤。不要中途改跑 `./prepare`，以为它不会影响前台设置。

```sh
git clone https://github.com/HowAreAllWell/gpt-agent-bridge.git
cd gpt-agent-bridge
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

**继续前检查：**创建环境前阅读打印的 Python 版本，须为 3.10 或更新。Pip 应成功结束，终端仍位于新 Bridge 文件夹。请逐行执行，第一处错误就停止。若缺少 Git、Python 或 venv，回到[入门指南](GETTING-STARTED.zh-CN.md)对应系统的前提步骤，经你同意后通过可信系统包管理器安装。不要用 `sudo pip` 或 `sudo ./prepare` 绕过错误。

**进阶依赖说明：**

[`pyproject.toml`](../pyproject.toml) 安装 `src/gpt_agent_bridge` 包，并与 [`requirements.txt`](../requirements.txt) 固定相同的、由产品源码导入的直接运行依赖：[mcp 2.0.0](https://pypi.org/project/mcp/2.0.0/)、[pydantic 2.13.4](https://pypi.org/project/pydantic/2.13.4/) 和 [typing-extensions 4.16.0](https://pypi.org/project/typing-extensions/4.16.0/)。这些固定版本与本地已安装包的 METADATA 一致，且各版本均存在于 PyPI。Pip 负责解析传递依赖。这是直接依赖的版本固定，不是传递依赖的哈希锁，也不保证跨平台完全可复现。不要把维护者完整 virtualenv 的 `pip freeze` 当作可移植锁文件。

<a id="3-run-the-local-server-in-the-foreground"></a>

## 3. 在前台运行本地服务

使用**终端 1：Ubuntu 终端 / WSL Ubuntu Bash**，留在第 2 步的 Bridge 文件夹。启动前在此 shell 选好 Herdr 程序。确认没有已安装服务或其他进程占用 8765；若已有，先选择一个部署，不要再启动第二个 Bridge。

此代码块启动 Bridge 后会**持续占用该终端**。它打印一个供终端 2 使用的私有文件路径，请仅在本地保留。文件内是秘密令牌（相当于允许访问的密码），不是应上传到 Chat 的附件。生成前关闭跟踪和历史记录，终端录制与日志须保密；不会打印令牌值：

```bash
set +x
set +o history
umask 077
export BRIDGE_WORKSPACE="$(pwd -P)"
export BRIDGE_PORT=8765
export BRIDGE_PATH_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
bridge_client_env="$(mktemp "${XDG_RUNTIME_DIR:-/tmp}/bridge-client-env.XXXXXXXX")"
printf 'export BRIDGE_PORT=%q\nexport BRIDGE_PATH_TOKEN=%q\n' \
  "$BRIDGE_PORT" "$BRIDGE_PATH_TOKEN" > "$bridge_client_env"
printf 'Private client environment file: %s\n' "$bridge_client_env"
"$BRIDGE_WORKSPACE/.venv/bin/python" -m gpt_agent_bridge
```

**检查结果：**出现 `Private client environment file:` 行，且 Bridge 持续运行。如果回到命令提示符或出现启动错误，表示服务没有保持运行；第 4 步前先私下检查。仅打印路径不能证明健康，需要第 4 步已初始化客户端检查。

`BRIDGE_WORKSPACE` 是必填项，必须准确指向已存在的非裸 Git 检出根目录的绝对路径，不能是 `src/`、包目录或 site-packages。调用模块前，先把包安装进此检出目录的 `.venv`。代码与注册工作区可以位于不同 Git 根目录。如果 8765 已被占用，选择可用端口，并保持客户端和中继设置一致。前台服务监听 `127.0.0.1:8765`，Streamable HTTP 路径为 `/mcp/<token>`。令牌是秘密能力凭据：实际值只能写入私有客户端或中继配置。绝不能将其值或带令牌的 URL 放进 README、跟踪文件、报告、共享终端录制或公开日志。`mktemp` 创建的临时文件位于检出目录之外，仅所有者可读（模式 0600），并且**包含秘密**，让第二个私有 shell 可以复用。将其视为敏感文件，本地检查后删除。生成另一个令牌不会匹配当前运行的服务。完成后使用 Ctrl-C 停止此前台进程。

<a id="4-check-through-an-initialized-mcp-client"></a>

## 4. 通过已初始化的 MCP 客户端检查

**在消耗令牌交接前作出选择：**若使用推荐的私有 OpenAI Secure MCP Tunnel 连接，请运行完整的[组合第 4 步](#combined-step-4)，**替代**下面独立的本地检查代码块。先完成该指南中的账户、访问权限及已验证客户端准备。组合方案会在同一个持有令牌的子 shell 中检查本地健康并启动隧道。

单独的 `curl GET` 不能证明 MCP 已初始化或工具调用成功。使用支持 Streamable HTTP 的 MCP 客户端。若只做本地只读检查，在**第二个私有 Bash shell** 中从检出目录运行本例。将引号中的 `bridge_client_env` 路径替换为第 3 步打印的私有文件路径（包括可能的空格）。source 前确认它是你自己刚创建的文件；绝不能 source 任意文件。子 shell 保留客户端的非零退出状态，即使客户端失败或 shell 提前退出，也会删除临时秘密文件。source 后，秘密保留在子 shell 环境中，直到子 shell 退出。示例不会导入 `gpt_agent_bridge.server` 或启动另一个服务。固定版本 SDK 的 `Client(..., mode="legacy")` 在进入异步上下文时执行 initialize 握手：

```bash
(
  set -e
  set +x
  set +o history
  bridge_client_env="/absolute/private/path/printed/in/step-3"
  [[ "$bridge_client_env" == */bridge-client-env.???????? &&
     -f "$bridge_client_env" && ! -L "$bridge_client_env" &&
     -O "$bridge_client_env" ]] || {
    printf 'Invalid or unowned client environment file\n' >&2
    exit 1
  }
  [[ "$(stat -c %a -- "$bridge_client_env")" == 600 ]] || {
    printf 'Client environment file must have mode 0600\n' >&2
    exit 1
  }
  trap 'rm -f -- "$bridge_client_env"' EXIT
  source "$bridge_client_env"
  rm -f -- "$bridge_client_env"  # Secret file is no longer needed.
  .venv/bin/python - <<'PY'
import asyncio
import os
from mcp import Client

async def main():
    port = os.environ.get("BRIDGE_PORT", "8765")
    token = os.environ["BRIDGE_PATH_TOKEN"]
    endpoint = f"http://127.0.0.1:{port}/mcp/{token}"
    async with Client(endpoint, mode="legacy") as client:
        result = await client.call_tool("bridge_health", {})
        if result.is_error:
            raise RuntimeError("bridge_health tool call failed")
        health = result.structured_content
        if not isinstance(health, dict):
            raise RuntimeError("bridge_health did not return structured data")
        status = health.get("herdr", {}).get("status")
        print("Herdr status:", status)
        if status != "reachable":
            print("Bridge is ready; start your Herdr session/Agent before delegation, then request fresh context.")

asyncio.run(main())
PY
)
```

**在终端 2 检查：**Herdr 运行时应显示 `Herdr status: reachable`。若显示 `Bridge is ready; start your Herdr session/Agent before delegation...`，表示本地 Bridge 有响应、Herdr 尚不可用，不代表可委派。出现 traceback 或非零退出时应停止并私下检查，不要对已删除的交接文件重跑代码块。

应检查 **`herdr.status == "reachable"`**，不能只看外层的 `ok:true`：即使 Herdr 不可用，Bridge 也会返回这个外层标志。此检查证明 Bridge 有响应及观察到了 Herdr 快照，不证明 Agent 就绪、任务成功、HTTPS 可达或 ChatGPT 已绑定的工具 schema。客户端错误日志也必须保密，因为传输错误可能含端点。

独立代码块会删除临时交接文件，并在令牌仅限于该子 shell 的状态下退出。之后的 shell 无法从已删除文件取回令牌。若你已经运行该块，现在需要隧道，请停止操作，选择另行授权的私有交接方式，从仍持有令牌的原始第一个 shell 交接，或有意识地选择重新启动 Bridge。绝不能新建不同的客户端令牌，并期望它匹配仍在运行的服务；这里不隐含自动重启。

<a id="5-connect-your-own-chatgpt-web-app-and-authorize-a-project"></a>

## 5. 连接自己的 ChatGPT Web App 并授权项目

组合 Tunnel 代码块运行后，切换到**浏览器**执行此步。App 是 ChatGPT 保存的 Bridge 工具连接；Skill 是另一项可复用的操作指令。两者不会互相安装。

ChatGPT Web 无法直接访问你的 loopback 地址。推荐的私有连接是 [OpenAI Secure MCP Tunnel](#foreground-secure-mcp-tunnel)：在独立代码块消耗交接前完成其组合第 4 步，再在 ChatGPT 的自定义 MCP 连接中选择你的隧道。需要账户权限、工作区关联和持续运行的客户端；源码检查不等于 Web 验收。

另一种方式是自行运行面向当前本地端点的公共 HTTPS 中继，并用该 HTTPS MCP 端点注册自己的 App。转发的 Host/Origin、认证及持续 SSE 可达性必须在实际环境中适配和检查。不能保证任意隧道都可用。保留 Streamable HTTP 路径和 SSE 支持；源码检查不能证明 Web 连接成功。

服务提供 `BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION`、`BRIDGE_MCP_ALLOWED_HOSTS` 和 `BRIDGE_MCP_ALLOWED_ORIGINS` 进行传输检查。若启用防护，请以 JSON 数组提供非空的精确允许 Hosts 和适当的精确 Origin 列表；这些值必须匹配服务通过中继实际收到的值。不要复制其他部署的允许列表。

实际点击步骤见[入门：连接 Tunnel](GETTING-STARTED.zh-CN.md#5-connect-the-tunnel-to-your-private-chatgpt-plugin)，之后继续 Skills 和 Project 步骤。在**普通 Web Project Chat** 中检查连接的工具列表并请求只读 `bridge_health` 调用，再单独确认**四个**原生 Skills 都可用。缺少 Plugin Creator 或连接控件时，需要核对计划/工作区管理员支持；不能用 Work/Codex 的结果代替，也不能声称 Web 设置已通过。

**进阶、可选的使用方文件配置：**正常 Web Plugin Creator 路线通过选择器选择已有授权 App，不要求手改 JSON。
[`../.app.example.json`](../.app.example.json) 展示了 `bridge` 别名和 `required: true`。其中的 `asdk_app_REPLACE_WITH_OWN_APP_ID` 是占位符，不是可用连接。如果某个使用方确实要求文件配置，请在你独立拥有的配置中，将新注册的 App ID 用于该使用方的 `.app.json`。不要覆盖其他开发者正在使用的绑定。版权名称不是 GitHub 登录名：应从实际仓库所有者处克隆。

注册 App 并通过它检查 `bridge_health` 后，用户必须明确授权 `project_register(project_ref, path)`，目标是已存在的绝对 Git 检出根目录。在 ChatGPT Project 侧应用返回的 Project Binding 指令。注册不授予任务权限。使用实际工具 schema 和现有规则文件，另行授权 `project_initialize(project_ref, seed)` 创建全新的连续性状态；见[项目连续性](PROJECT-CONTINUITY.zh-CN.md)。它不会修改已规范化的 manifest，遇到非规范的 `.principal/` 会拒绝而不是覆盖。仅注册 App 不会执行上述任一步骤。使用 `context(project_ref)` 发现真实且符合条件的 Agent 句柄，然后先授权有界任务，再调用 `delegate(project_ref, assignments=[...])`。报告可用是需要审查的证据，不是任务成功的证明。

<a id="optional-later-systemd-adoption"></a>

## 可选：之后接管为 systemd 服务

若是首次安装而不接管已运行进程，请使用独立的 [Bridge + Tunnel 自动启动指南](AUTOSTART.zh-CN.md)，明确分开 install/configure/enable/start 阶段并回读状态。不要把首次安装单元与下面运行进程的接管器混用。仅设置 Bridge 以及可选 WSL 启动锚点时，见 [Bridge 组件指南](AUTOSTART.zh-CN.md#bridge-component-contract)。

只有当此检出目录的 Bridge 进程已经运行时，操作员才能另行选择[技术参考](TECHNICAL-REFERENCE.zh-CN.md#optional-system-service-adoption)描述的安装器。接管要求严格使用第 3 步的绝对解释器启动方式：`/absolute/checkout/.venv/bin/python -m gpt_agent_bridge`，cwd 为该检出目录，包已安装在该 venv。相对解释器路径、控制台入口、标志和额外参数都会被拒绝。发布前安装器重新验证进程 cwd、可执行文件、以 NUL 分隔的 argv 和 starttime；这些检查防止误接管，不防范同 UID 的恶意进程，也不证明已加载代码可信。其他启动方式需要单独决定重新启动；安装器不会自动重启。

安装器接管该进程及其环境、安装并验证单元，但**不会启动或启用**。对于没有运行中 Bridge 的干净克隆，它无法完成引导。安装及之后的服务控制需要操作员明确操作；不是此前台快速入门的前提条件。

<a id="native-ubuntu-desktop-and-server"></a>

## 原生 Ubuntu Desktop 与 Server

在 **Ubuntu Desktop** 中，以普通用户打开终端、使用 Bash。源码检出和 `.venv` 放在 Linux 主目录。先执行第 1–2 步；需要 Web 时，在启动终端 1 前准备 Tunnel，再打开第二个 Ubuntu 终端执行组合健康检查/Tunnel 代码块。这条路线不需要 `wsl.exe`、PowerShell 或 `/mnt/c` 路径。需要可选扩展提醒时，使用同机浏览器，按入门指南加载扩展。

**Ubuntu Server** 无桌面时可能适合服务与 Tunnel 路线，但无头 Herdr/Agent 会话及远端浏览器提醒仍是独立验收缺口。浏览器的 `127.0.0.1` 指浏览器所在电脑，不是服务器。不要为了连通而公开暴露 Bridge 或提醒接口。本指南没有已验证的无头 Agent 启动配方。原生 Ubuntu 前台、开机和浏览器行为仍需实机验收。

<a id="windows-and-wsl2"></a>

## Windows 与 WSL2

**原生 Ubuntu 用户跳过整节。**尚未准备 WSL 的 Windows 用户先按[入门指南](GETTING-STARTED.zh-CN.md)操作。这些是进阶环境说明，不是另一套必需的新用户流程。Windows PowerShell 的 `wsl --list --verbose` 标识实际发行版及其 VERSION 2；`wsl --version` 描述组件，在旧主机上可能不可用。复用现有发行版和 Linux 用户。缺失的 WSL/发行版、WSL1 转换和 systemd 启用都必须由操作员根据 [Microsoft 指南](https://learn.microsoft.com/windows/wsl/install)明确决定，绝不是 Bridge 的隐式更改。支持的路线是 Linux/WSL2，而非 Windows 或 macOS 原生 Bridge。首次安装和重启验收仍未验证。列出发行版后，在 **PowerShell** 用 `wsl.exe --distribution Ubuntu --user your_linux_user` 打开选定环境（把两个示例值换成实际发行版名和 Linux 用户名）。看到该用户的 Linux 提示符才继续。发行版或用户不存在时，先解决 WSL 设置，不要改用不确定的默认发行版。

在同一个选定发行版中使用 Linux Git/Python 3.10+/venv/pip 和 Linux Herdr。开发检出目录及 venv 放在 Linux home，而不是 `/mnt/c`；见[文件系统指南](https://learn.microsoft.com/windows/wsl/filesystems)。仅在明确同意后通过可信 OS 包管理器安装缺失前提条件，再执行上面的第 1–2 步。Windows 的 `herdr.exe` 不是这里要求的 Linux 依赖。将 `BRIDGE_WORKSPACE` 设为实际 Linux 绝对 Git 根目录，而非盘符路径。独立演示根目录也要与 Bridge 代码分开。

前台 Web 使用应在独立第 4 步消耗令牌前选择[组合令牌交接](#combined-step-4)。两个 shell、客户端和服务必须处于选定的同一发行版和网络。Windows→WSL localhost 与 WSL→Windows 是不同路线；NAT/镜像模式、防火墙及 VPN 都可能改变它们。从实际客户端验证已初始化 MCP；不要通过扩大监听/允许列表或关闭防护来补偿。见 [WSL 网络](https://learn.microsoft.com/windows/wsl/networking)。持久运行请使用[自动启动](AUTOSTART.zh-CN.md)，而不是第二个前台客户端。Systemd 本身不会保持 WSL 存活。本地前台检查不带来 Windows 登录、重启或 24x7 保证。

<a id="herdr-compatibility-and-version-selection"></a>

## Herdr 兼容性与版本选择

**此 Bridge 发行版使用 Herdr v0.9.0。**维护者现有 WSL 环境报告 `herdr 0.9.0`、Bridge 健康及 Herdr 可达。Herdr v0.9.3 **在该环境中被报告为不兼容**；不表示所有 v0.9.3 场景都会失败。这个临时建议应仅在其他版本支持经过验证后更改。它是实机使用证据，不是首次安装或跨版本验收测试。

<a id="1-check-before-installing"></a>

### 1. 安装前检查

在准备运行 Bridge 的 Linux/WSL shell 中运行以下只读命令：

```bash
command -v herdr
herdr --version
```

若选定 CLI 已报告 **0.9.0**，且 Herdr 会话可用，**不要重新安装**。继续下面的会话检查。若 Herdr 缺失或选中了其他版本，以下可选说明安装独立二进制文件，不替换当前安装。

[官方安装指南](https://herdr.dev/docs/install/)仍是通用参考。其通用安装器跟随最新版本，不固定到 v0.9.0，因此这里的建议使用下面明确的发行资源。不要运行更新命令并期望它保持此固定版本。

<a id="2-optional-separate-v090-installation"></a>

### 2. 可选：独立安装 v0.9.0

这些是**由用户执行的安装说明**，不是 Bridge 执行的操作。使用 Ubuntu/Linux Bash，包括 WSL 内的 Bash；Windows 的 `herdr.exe` 不是此项前提。需要 `curl` 和 GNU `sha256sum`。在 Ubuntu 上，若缺失，可自行选择通过 `sudo apt install curl coreutils` 安装。

官方 [v0.9.0 发行版](https://github.com/herdrdev/herdr/releases/tag/v0.9.0)及其 [GitHub 发行元数据](https://api.github.com/repos/herdrdev/herdr/releases/tags/v0.9.0)发布了以下资源和 SHA256 摘要：

| `uname -m` | 官方资源 | SHA256 |
| --- | --- | --- |
| `x86_64` | [herdr-linux-x86_64](https://github.com/herdrdev/herdr/releases/download/v0.9.0/herdr-linux-x86_64) | `4fa1a01158dd8043da92d31b270780b0dcc10603038d9b61cac4d81ab63fb71f` |
| `aarch64` / `arm64` | [herdr-linux-aarch64](https://github.com/herdrdev/herdr/releases/download/v0.9.0/herdr-linux-aarch64) | `9c8db20fb7e7427b138d5367113f1621ffd319f2f65d6f009e2594029115f0d2` |

以下代码块拒绝已存在的目标，包括悬空符号链接。它在**检出目录之外**创建私有版本目录，下载到独立临时文件名，并在赋予可执行权限**之前**检查固定摘要。它不会执行 Herdr，也不修改持久 `PATH`。

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
  printf 'Verified binary installed in the new version directory.\n'
)
```

只有**整个代码块成功**后才能继续。失败会保留新目录供检查；不授予为重试而删除或覆盖它的权限。这些哈希核对文件是否对应已发布的资源元数据，不是对二进制文件的独立安全审查。

<a id="3-select-the-cli-and-check-the-actual-session"></a>

### 3. 选择 CLI 并检查实际会话

**只有独立安装成功后**，才为当前 shell 选择它。复用现有 v0.9.0 安装时，保留已经验证的选择，不要指向尚未创建的目录。

```bash
export BRIDGE_HERDR_BIN="$HOME/.local/opt/herdr-v0.9.0/herdr"
export PATH="$HOME/.local/opt/herdr-v0.9.0:$PATH"
hash -r
command -v herdr
"$BRIDGE_HERDR_BIN" --version
```

`BRIDGE_HERDR_BIN` 是 **Bridge 使用的 CLI 绝对路径**；启动 Bridge 前设置。临时的 `PATH` 选择让手动 `herdr` 命令使用同一个二进制文件。每个独立的 Bridge、Herdr 启动或控制 shell 都要重复选择：新终端不会继承另一个终端的 export。两种选择都不会改变已运行 Herdr 服务的版本。

若需要新会话，请按照[可选演示 Agent 设置](#optional-demo-agent-with-herdr)，自行用该选定版本打开 Herdr。不要自动停止、降级或重启已有会话。使用选定 CLI 私下检查会话：

```bash
herdr api snapshot
```

快照必须成功并显示预期真实 Agents。若 API 提供该字段，应检查连接服务的 `result.snapshot.version` 是否为 **0.9.0**，不能只看 CLI 的 `--version`。若不同或无法确定，委派前暂停并解决会话选择；不要从二进制路径推断兼容性。快照输出必须保密。

继续[快速入门](#1-prepare-herdr-and-an-existing-agent)。其已初始化 MCP 检查必须得到 `herdr.status == "reachable"`；仅健康状态不能证明 Agent 就绪或版本兼容。本指南没有为 Bridge 增加自动版本强制机制。检测 manifest 可能独立于二进制更新；此版本固定不是完整环境锁，也不会更改 Herdr 设置。

<a id="foreground-secure-mcp-tunnel"></a>

## 前台 Secure MCP Tunnel

本指南于 **2026-10-11** 审阅，提供[快速入门](QUICKSTART.zh-CN.md)后的私有连接路线。它尚未作为全新账户、全新 WSL、原生 Ubuntu 或部署验收测试执行。OpenAI 托管隧道端点；你在 Bridge 旁运行官方 Linux 客户端。此路线不需要独立公共 HTTPS 中继，但需要账户访问权限和持续运行的客户端。

```text
ChatGPT → OpenAI tunnel service ← outbound tunnel-client in Linux/WSL2
                                         ↓ local HTTP
                           Bridge on 127.0.0.1 → local Herdr/Agents
```

[官方隧道指南](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)说明默认向 api.openai.com:443 发起出站 HTTPS。企业控制平面的 mTLS 有独立要求。Bridge 不需要公开的入站监听器。

无人值守启动或所有者 WSL2 登录请使用 [Bridge + Secure MCP Tunnel 自动启动](AUTOSTART.zh-CN.md)。本页仍是前台传输和账户指南：组合第 4 步指本地健康检查加前台客户端。不要在配套服务旁再启动第二个客户端。

<a id="1-choose-the-combined-path-before-consuming-the-handoff"></a>

### 1. 在消耗交接前选择组合路线

**这次要准备什么：**终端 1 运行 Bridge，终端 2 运行一个 Tunnel 客户端。Tunnel 通过出站连接把工具请求传给 OpenAI，无需把 Bridge 暴露到互联网。这是临时前台演练，不是后台服务。

先完成**快速入门第 1–2 步**以及下面的账户和客户端准备。再在第一个私有 Linux Bash shell 中通过**快速入门第 3 步**启动 Bridge。它会生成一个令牌，并创建仅所有者可访问的临时交接文件。

在第二个私有 Bash shell 中运行下面完整的[组合第 4 步](#combined-step-4)，**替代独立的快速入门第 4 步**。独立第 4 步会 source 并删除交接文件，再退出其子 shell；之后的第三个 shell 无法从已删除文件获得该令牌。

若你已完成独立第 4 步，**停止操作**。不要读取不存在的文件，或为仍运行的 Bridge 生成另一个令牌。请选择另行授权的新私有交接，从**仍持有令牌的原始第一个 shell**交接；或有意识地选择重新启动 Bridge 并重做第 3 步。本指南不会自动恢复或重启。

**原生 Ubuntu：**继续用 Ubuntu 终端，跳过下一个 PowerShell 代码块。**仅 Windows 用户：**参阅 [Windows + WSL2](#windows-and-wsl2)，在 **PowerShell** 中检查：

```powershell
wsl --list --verbose
```

使用 version-2 发行版。以下所有步骤都应在 **Ubuntu/WSL Bash** 或 Linux Bash 中执行，而不是 PowerShell。Linux 客户端应与 Bridge 位于同一发行版和网络，其 localhost 必须能访问预期服务。Windows/macOS 原生 Bridge 和 WSL1 不是已验证路线。Bridge 保持 loopback 监听；实际 HTTP 端点是 http://127.0.0.1:<port>/mcp/<current private token>，不能只有 /mcp。

<a id="2-prepare-your-account-tunnel-and-permissions-first"></a>

### 2. 先准备账户、隧道和权限

在浏览器打开 [Platform 隧道设置](https://platform.openai.com/settings/organization/tunnels)。选择你自己的个人 Platform 组织，或管理员管理的目标组织。创建隧道，并私下保留返回的完整隧道 ID。将其关联到所属 Platform 组织，**以及你将创建和使用插件的 ChatGPT 工作区**。

[隧道权限](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/permissions.md)属于组织层级：创建或编辑需要 **Tunnels Read + Manage**；运行客户端和为 App 选择隧道需要 **Read + Use**。同时执行两类操作的人需要两项能力。ChatGPT 自定义 MCP 的工作区权限是独立要求。控件缺失或权限不足是阻碍，不是绕过政策的理由；仅有订阅不能证明符合使用条件。

在目标组织的 [Platform 运行密钥](https://platform.openai.com/settings/organization/api-keys)中创建 runtime API key，其 principal 必须拥有 Read + Use。使用运行密钥，而非管理密钥。这个**控制平面密钥用于隧道客户端认证**；Bridge 不要求另设 OpenAI 模型 API Principal，Principal 推理由 ChatGPT 提供。不要推断隧道或密钥使用免费或不限量；应检查当前账户条款。Agent 提供商的费用和额度另计。不要将密钥或私有标识符粘贴进 Chat、指令、跟踪文件、截图或已发布报告。

<a id="3-obtain-and-verify-the-pinned-linux-client"></a>

### 3. 获取并验证固定版本 Linux 客户端

下面的组合代码块专门针对 **tunnel-client v0.0.16** 检查。下载该官方[带标签发行版](https://github.com/openai/tunnel-client/releases/tag/v0.0.16)，或 Platform 设置提供的匹配 v0.0.16 下载。不要默默用另一版本执行此配方。选择匹配发行版架构的完整 Linux 包；在 Ubuntu 终端或 WSL Bash 用 `uname -m` 区分 x86_64/amd64 与 aarch64/arm64。遵循该发行版的校验和及来源验证说明。

解压到 Git 检出目录之外、你自己的 Linux 目录，保留包布局及配套文件。保留已验证可执行文件的**绝对路径**。若解压丢失执行权限，给该已验证文件添加可执行权限。不要将未知下载 URL 通过管道交给 shell，也不要猜测资源 URL。

在 **Ubuntu 终端 / WSL Ubuntu Bash** 中切换到解压后客户端所在目录，不是 Bridge 目录。开始快速入门第 3 步前先运行：

```bash
./tunnel-client --version
./tunnel-client help quickstart
```

**检查结果：**版本必须为 0.0.16（可以附带构建元数据），且 `help quickstart` 应显示帮助。程序不存在、版本不符或校验失败时应停止，取得匹配且验证过的完整包；不要猜参数或替换版本。组合代码块会再次检查。它不会安装依赖、运行 sudo、初始化 profile 或启动 Agent。企业代理、私有 CA 或 mTLS 环境需要另行审阅配方；下面的最小环境有意不继承这些覆盖项。

<a id="combined-step-4"></a>
<a id="4-combined-step-4-initialized-local-health-then-foreground-tunnel"></a>

### 4. 组合第 4 步：初始化本地健康检查，然后运行前台隧道

**这个特定代码块要求 Herdr 已运行且可达。**与正常 `./prepare` 及独立本地检查不同，这个保留的手动配方在 Herdr 不可用时会停止。健康调用不需要 Agent，之后委派才需要你已有且获授权的 Agents。

现在让 **Shell 1 中的快速入门第 3 步保持运行**。在 **Shell 2** 中切换到同一个已安装 .venv 的 Bridge 检出目录。使用不录制内容的私有终端，**在粘贴代码块前，于 Shell 2 关闭跟踪和历史记录**：

```bash
set +x
set +o history
```

复制**下面完整代码块**，包括两端圆括号。仅输入第 3 步打印的私有交接**路径名**，不要输入文件内容。确认它是你自己刚创建的文件。代码块只 source 一次并立即删除，检查已初始化 MCP 健康，然后在子 shell 退出前继续使用同一个令牌。不会生成令牌，也不向第三个 shell 交接。

```bash
(
  set -e
  set +x
  set +o history
  umask 077
  [[ -t 0 && -t 1 ]] || {
    printf 'FALSE: use a private interactive Bash terminal\n' >&2
    exit 1
  }
  read -r -p 'Private handoff pathname printed by Quickstart step 3: ' bridge_client_env
  [[ "$bridge_client_env" == */bridge-client-env.???????? &&
     -f "$bridge_client_env" && ! -L "$bridge_client_env" &&
     -O "$bridge_client_env" ]] || {
    printf 'FALSE: invalid or unowned handoff file\n' >&2
    exit 1
  }
  [[ "$(stat -c %a -- "$bridge_client_env")" == 600 ]] || {
    printf 'FALSE: handoff file must have mode 0600\n' >&2
    exit 1
  }

  bridge_tunnel_logs=""
  cleanup() {
    bridge_tunnel_status=$?
    trap - EXIT
    rm -f -- "$bridge_client_env"
    if [[ -n "$bridge_tunnel_logs" ]]; then
      rm -f -- "$bridge_tunnel_logs"/{health,version,doctor,run,setup}.log
      rmdir -- "$bridge_tunnel_logs"
    fi
    exit "$bridge_tunnel_status"
  }
  inspect_failure() {
    printf 'FALSE: %s\n' "$1" >&2
    printf 'Private diagnostic directory: %s\n' "$bridge_tunnel_logs" >&2
    printf 'Inspect locally in another private shell; never paste raw logs into Chat.\n' >&2
    read -r -t 120 -p 'Press Enter to delete logs now (automatic cleanup in 120 seconds): ' bridge_tunnel_ack || true
  }
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  source "$bridge_client_env"
  rm -f -- "$bridge_client_env"
  bridge_tunnel_logs="$(mktemp -d /tmp/bridge-tunnel-first-use.XXXXXXXX)"
  chmod 0700 "$bridge_tunnel_logs"
  export BRIDGE_TUNNEL_LOG_DIR="$bridge_tunnel_logs"

  if .venv/bin/python - > "$bridge_tunnel_logs/health.log" 2>&1 <<'PY'
import asyncio
import os
from mcp import Client

async def main():
    port = os.environ.get("BRIDGE_PORT", "8765")
    token = os.environ["BRIDGE_PATH_TOKEN"]
    endpoint = f"http://127.0.0.1:{port}/mcp/{token}"
    async with Client(endpoint, mode="legacy") as client:
        result = await client.call_tool("bridge_health", {})
        if result.is_error:
            raise RuntimeError("bridge_health tool call failed")
        health = result.structured_content
        if not isinstance(health, dict):
            raise RuntimeError("bridge_health did not return structured data")
        status = health.get("herdr", {}).get("status")
        print("Herdr status:", status)
        if status != "reachable":
            raise RuntimeError("Herdr is unavailable; check its session and PATH")

asyncio.run(main())
PY
  then
    printf 'Local initialized health: PASS\n'
  else
    inspect_failure 'local initialized health'
    exit 1
  fi

  if .venv/bin/python - <<'PY'
import getpass
import os
from pathlib import Path
import subprocess
import sys
import traceback
import warnings

logs = Path(os.environ["BRIDGE_TUNNEL_LOG_DIR"])

def private_log(name):
    handle = (logs / name).open("wb")
    os.chmod(logs / name, 0o600)
    return handle

def main():
    # Python's stdin is this heredoc, so interactive input must use the terminal.
    with open("/dev/tty", "r") as terminal_in, open("/dev/tty", "w") as terminal_out:
        print("Absolute path to your verified v0.0.16 Linux tunnel-client: ",
              end="", file=terminal_out, flush=True)
        binary = Path(terminal_in.readline().rstrip("\r\n"))
    if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError("An absolute executable file path is required")
    # No inherited client profile/config/debug, proxy, or model API variables.
    child_env = {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    with private_log("version.log") as output:
        check = subprocess.run([str(binary), "--version"], env=child_env,
                               stdout=output, stderr=subprocess.STDOUT)
    version = (logs / "version.log").read_text().strip().split()
    if check.returncode or not version or version[0].split("+", 1)[0].removeprefix("v") != "0.0.16":
        raise RuntimeError("This recipe requires the verified v0.0.16 release")

    warnings.filterwarnings("error", category=getpass.GetPassWarning)
    child_env["CONTROL_PLANE_TUNNEL_ID"] = getpass.getpass("Your complete tunnel ID: ")
    child_env["CONTROL_PLANE_API_KEY"] = getpass.getpass("Your runtime API key: ")
    if not child_env["CONTROL_PLANE_TUNNEL_ID"] or not child_env["CONTROL_PLANE_API_KEY"]:
        raise RuntimeError("Tunnel ID and runtime key must be nonempty")
    port = os.environ["BRIDGE_PORT"]
    token = os.environ["BRIDGE_PATH_TOKEN"]
    child_env["MCP_SERVER_URL"] = f"http://127.0.0.1:{port}/mcp/{token}"
    child_env["HEALTH_LISTEN_ADDR"] = "127.0.0.1:8080"
    with private_log("doctor.log") as output:
        doctor = subprocess.run([str(binary), "doctor", "--explain"], env=child_env,
                                stdout=output, stderr=subprocess.STDOUT)
    if doctor.returncode:
        raise RuntimeError("Doctor failed; foreground run was not started")
    print("Doctor: PASS. Starting foreground run; this is not readiness or Web acceptance.", flush=True)
    with private_log("run.log") as output:
        run = subprocess.run([str(binary), "run"], env=child_env,
                             stdout=output, stderr=subprocess.STDOUT)
    if run.returncode:
        raise RuntimeError("Foreground run exited unsuccessfully")
    print("Foreground run stopped; no remote success is implied.", flush=True)

try:
    main()
except KeyboardInterrupt:
    sys.exit(130)
except Exception:
    with private_log("setup.log") as output:
        output.write(traceback.format_exc().encode("utf-8"))
    sys.exit(1)
PY
  then
    :
  else
    inspect_failure 'tunnel setup or foreground run'
    exit 1
  fi
)
```

**检查终端 2：**先显示 `Local initialized health: PASS`，再显示 `Doctor: PASS. Starting foreground run; this is not readiness or Web acceptance.`。客户端运行期间终端会保持占用。这些只是中间检查；下一步还需检查本地 UI 和实际 Web Chat 调用。出现 `FALSE` 就停止，在提示的检查时间内私下查看诊断目录，不要发布日志，也不要对已消耗的令牌文件重跑。

健康检查部分有意匹配快速入门固定 SDK 的 legacy initialize 握手，并要求 **herdr.status == reachable**，不只是外层 ok 标志。它不会导入 Bridge 服务端或再次启动 Bridge。

[带标签版本的配置代码](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/runtimeconfig/config.go)支持 CONTROL_PLANE_TUNNEL_ID、CONTROL_PLANE_API_KEY、MCP_SERVER_URL 和 HEALTH_LISTEN_ADDR。[带标签版本的配置来源解析器](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/runtimeconfig/profile.go)在没有请求时不选择 profile/config。仅向子进程传递显式环境；秘密不作为子进程参数或 profile 字面量。**没有 init/profile 步骤**，不存储运行密钥，也不持久保留令牌文件。环境变量不能防止同用户特权进程检查；请使用可信本机。

<a id="5-observe-the-live-client-keep-both-shells-running"></a>

### 5. 观察实时客户端；保持两个 shell 运行

Doctor **可能打印实际端点**，因此它的完整 stdout/stderr 都写入私有日志。本地健康、版本和前台运行输出也分开保存。文件模式为 0600，位于仓库外新建的 0700 目录。失败时，代码块只打印安全标签和私有诊断目录，允许在删除前进行最多 120 秒的本地检查。不要共享原始日志。EXIT/INT/TERM 清理会删除交接文件及生成日志；SIGKILL、主机崩溃或断电无法运行 shell trap，因此应私下检查并清理残留。

客户端使用其已验证的默认 loopback 健康地址 127.0.0.1:8080。Doctor 在端口冲突时停止；不要通过杀死其他进程或扩大监听范围来修复。若 doctor 后出现冲突，run 仍可能失败。客户端运行时，在**同一 Ubuntu 电脑的浏览器**打开 http://127.0.0.1:8080/ui（Windows 则先验证 Windows 到 WSL 的 localhost 路线）。远端无头服务器上，这个浏览器地址不是服务器；不能假定可用，也不能扩大监听，须另行审核私密访问方式。先私下检查 UI 的健康、就绪和连接，再尝试 ChatGPT 发现。Doctor PASS 或打印的启动消息不证明守护进程已经就绪。

保持 Shell 1 的 Bridge 和 Shell 2 的隧道运行。Ctrl-C 结束前台演练并清理临时日志。WSL 挂起或关闭、Bridge 停止、客户端停止或出站 HTTPS 不可用都会中断路线。Systemd 本身不会保持 WSL 存活。本配方不承诺凭据持久化、自动监管、重启、TTL 重写或长任务验收。退出后若需重做，必须重新明确选择令牌交接或重启；不要针对已删除的交接文件重新运行。

账户和插件控件仅按[入门第 5 步](GETTING-STARTED.zh-CN.md#5-connect-the-tunnel-to-your-private-chatgpt-plugin)操作：Connection Tunnel、你自己的 Tunnel、MCP No authentication（Bridge 没有 OAuth 服务端）、风险审阅、安装，以及实际普通 Project Chat 的健康调用。本地就绪、Create as a plugin 和仅在 Work 中得到结果是不同检查。这不会安装四个原生 Skills 或 Core，不会注册项目，也不授予 Agent 输入权限。即使传输可用，也要将这些步骤分开。

<a id="7-diagnose-the-failing-layer"></a>

<a id="7-诊断失败层"></a>

<a id="6-diagnose-the-failing-layer"></a>

### 6. 诊断失败层

| 症状 | 在不削弱防护的情况下检查 |
| --- | --- |
| 创建隧道被拒绝 | 正确的 Platform 组织、Read + Manage、账户可用性 |
| ChatGPT 中没有隧道 | 预期工作区关联和创建者的 Read + Use |
| 运行被拒绝 | 密钥的组织/principal、Read + Use；绝不能替换成管理密钥 |
| 本地拒绝/404 | 同一发行版和网络、运行中的 Bridge、已 source 的当前令牌和端口 |
| Doctor 失败 | 私有日志；必需值、默认健康端口、本地 HTTP 可达性 |
| 有启动消息但隧道未就绪 | 实际 UI/就绪、出站 HTTPS、运行错误；不自动重做 |
| Host/Origin 被拒绝 | 将实际收到的值与 Bridge 精确配置的允许列表比较 |
| 发现可用但长流失败 | Streamable HTTP/SSE、断连、超时设置、WSL 生命周期 |
| 工具出现在其他界面而非 Project Chat | 目标界面选择和工作区政策 |
| 工具可用但 Skills 缺失 | 包安装和发现，与隧道传输分开检查 |

快速入门负责传输防护、认证和精确 Host/Origin 允许列表。不要猜测私有值、使用通配列表或关闭防护。诊断见[带标签版本的故障排查指南](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/troubleshooting.md)。企业网络例外需要操作员有意识地审阅，不能默默把继承的 debug/proxy/config 变量加入允许列表。

<a id="8-record-completion-and-choose-later-deployment-separately"></a>

<a id="8-记录完成情况之后另行选择部署"></a>

<a id="7-record-completion-and-choose-later-deployment-separately"></a>

### 7. 记录完成情况，之后另行选择部署

在脱敏记录中只记录观察到的版本、本地健康、客户端就绪、实际 Project Chat 工具结果及剩余缺口。绝不能发布密钥、带令牌 URL、私有标识符或原始日志。本文不是成功回执。操作员清理及之后的任何重启都是明确选择。

Secure MCP Tunnel 用于私有连接和测试，**不用于公共市场提交或分发**。公共插件需要稳定的公共 HTTPS 端点。替代的公共中继路线仍由用户独立管理，必须针对该部署检查实际认证、转发、流式传输和允许列表。

<a id="optional-invoice-demo"></a>

## 可选发票演示

**可在设置完成后练习，也可完全离线练习。**只想在自己现有仓库使用 Bridge，就跳过整节。这里的 fixture 指两个带故意失败测试的小型 Python 示例文件。练习会创建独立的可丢弃文件夹，不是安装检查。

这个仅使用标准库的合成 fixture 展示任务界定、有界委派和基于证据的验收。它包含**故意错误的基线**，不是修正后的实现。它的隔离测试失败是教学证据，不是 Bridge 产品失败。不使用财务记录、凭据或服务。这是小型解析练习，不是真实发票系统，也不是财务建议。

无需 Bridge、Herdr、插件或 Project 指令即可检查和测试它。若选择连接演练，先完成唯一的[入门指南](GETTING-STARTED.zh-CN.md)。此例不提供 Principal Core、主机设置或连续性种子。这些文件不意味着 Agent 已执行、修复后测试已通过或全新 Chat 恢复已完成。

<a id="bootstrap-your-own-disposable-git-repository"></a>

### 创建自己的可丢弃 Git 仓库

使用 Linux/WSL Bash、Git 2.28+ 和 Python 3.10+。从**含有本例的你自己的公共 Bridge 检出根目录**开始，绝不能使用私有 Bridge 开发检出目录。源检出目录保持只读。在 Linux home 下直接选择全新目标；不能将任一 Bridge 检出目录用作目标。使用没有自定义 `GIT_*` 环境覆盖的 shell。仅在你授权创建并复制到该可丢弃仓库时，才自行运行：

```bash
(
  set -e
  source_root="$(pwd -P)"
  demo_root="$HOME/bridge-first-use-demo"  # Choose a fresh name if this exists.
  if [[ -e "$demo_root" || -L "$demo_root" ]]; then
    printf 'Destination exists; stop and choose a new path.\n' >&2
    exit 1
  fi
  for file in invoice.py test_invoice.py; do
    [[ -f "$source_root/examples/first-use/$file" ]] || {
      printf 'Missing fixture file; check the public source checkout.\n' >&2
      exit 1
    }
  done
  umask 077
  mkdir -p -- "$demo_root"
  cp -n -- "$source_root/examples/first-use/invoice.py" \
    "$source_root/examples/first-use/test_invoice.py" "$demo_root/"
  git -C "$demo_root" init -b main --template=
  git -C "$demo_root" status --short
  if git -C "$demo_root" rev-parse --verify HEAD >/dev/null 2>&1; then
    printf 'Unexpected existing HEAD; stop and inspect the destination.\n' >&2
    exit 1
  fi
  printf 'Baseline: main, two untracked fixture files, HEAD absent.\n'
)
```

新根目录只包含 `invoice.py`、`test_invoice.py` 和它自己的 `.git/`；不需要子示例目录或 `__init__.py`。`cp -n` 避免覆盖文件。任何错误都应停止，不要在已部分创建的目标中重跑。私下记录实际状态。未诞生的 `HEAD` 是预期情况：Bridge 注册检查现有非裸 Git 根目录，不要求首次提交。不要把 Bridge 源检出目录注册为此演示项目。

在 **Ubuntu 终端 / WSL Ubuntu Bash** 中，创建块结束后仍在 Bridge 源码目录：它创建了演示，但没有改变当前 shell 的目录。下一块会在子 shell 中进入新的可丢弃项目，在那里运行测试，并使用不同的起始路径（若你选择其他名称，应一致替换路径）：

```bash
(
  cd -- "$HOME/bridge-first-use-demo" || exit 1
  python3 -B -m unittest discover -s . -p 'test_*.py' -v
)
```

随包基线有九个测试：**三个通过，六个故意失败**。非零测试退出状态是预期结果；导入或设置错误不属于验收失败。保留命令和实际结果，不要伪造通过回执。

注册不要求初始提交。仅在这个可丢弃根目录中获得单独暂存和提交授权后，初始提交才可以提供受跟踪基线；本例不授予 Git、项目注册、连续性或 Agent 输入权限。每项 Work 的报告发布都要与项目编辑分开明确授权。

<a id="optional-demo-agent-with-herdr"></a>

### 可选：使用 Herdr 的演示 Agent

这是针对该可丢弃练习的操作员设置，不是必需安装步骤或 Bridge 委派。若演示根目录已有符合条件的 Agent 运行，保留它并跳过另一个启动。否则选择兼容 Agent，私下完成提供商安装和登录；[官方 Codex CLI 指南](https://learn.chatgpt.com/docs/codex/cli)只是一个例子，不是必选提供商。不要把登录输出或凭据粘贴进 Chat。

每个启动和控制 shell 使用同一个选定的 Linux Herdr CLI；见 [Herdr 兼容性](#herdr-compatibility-and-version-selection)。在已准备的演示根目录中自行打开 Herdr，并保持该会话运行。Bridge 代码检出目录容纳服务及 venv；这个独立演示 Git 根目录容纳 fixture，是 Agent 的 cwd 和之后的注册目标。绝不能用 Bridge 检出目录替代。

仅在授权创建工作区后，才在 Linux/WSL Bash 中运行以下命令。[Herdr 自动化参考](https://herdr.dev/docs/agent-automation/)说明返回的 root-pane 字段。该命令不发送 Agent 任务：

```bash
demo_root="$HOME/bridge-first-use-demo"  # Use the exact root you prepared.
demo_root="$(cd -- "$demo_root" && pwd -P)" || exit 1
[[ -d "$demo_root/.git" && ! -L "$demo_root/.git" ]] || {
  printf 'Prepare the independent demo Git root first.\n' >&2
  exit 1
}
workspace_json="$(herdr workspace create --cwd "$demo_root" --label bridge-first-use --no-focus)" || exit 1
demo_pane="$(printf '%s\n' "$workspace_json" | python3 -c 'import json, sys; value = json.load(sys.stdin)["result"]["root_pane"]["pane_id"]; assert isinstance(value, str) and value; print(value)')" || exit 1
printf 'Observed root shell pane: %s\n' "$demo_pane"
```

检查实际窗格：必须是**空闲交互式 shell 提示符**，没有前台程序、编辑器或 Agent，其 cwd 必须是演示根目录。选择未使用的 Agent 名称。只有另行授权启动后，才从保留着 `demo_pane` 的同一个控制 shell 运行这个 Codex 示例以启动 Agent：

```bash
herdr agent start demo --kind codex --pane "$demo_pane"
```

若启动失败或结果不明，应先观察会话，再采取其他操作；不要盲目重启或发送提示来强迫它就绪。通过只读 Herdr 观察及新的 Bridge `context` 验证预期 Agent。使用实际 `agent_ref`；Herdr 名称或窗格不是可自行编造的 Bridge 句柄。注册、Chat 绑定和 Agent 输入仍是单独授权的操作。

<a id="acceptance-contract"></a>

### 验收合同

公共函数是 [invoice.py](../examples/first-use/invoice.py) 中的 `total_cents(amounts) -> int`。它接收由单个金额字符串组成的可迭代对象，并返回精确的整数分。金额语法有意严格限定：

- ASCII `0` 或非零数字后跟 ASCII 数字，可选小数点及一到两位 ASCII 小数：`0`、`2`、`12.3`、`0.29`。
- 不允许符号、空白、如 `01` 的前导零、指数、逗号、Unicode 数字、缺失整数或小数部分，或超过两位小数。
- 每个无效值，包括 `None`、空字符串、数值和布尔值，都必须抛出 `ValueError`。不能默默补零或返回部分合计。
- 对有效金额不能浮点转换、四舍五入或截断。保留每一分，包括下面的大数情形。空输入合计为零；输入列表保持不变。
- 保持函数纯净、签名不变，仅使用 Python 标准库。不能访问文件或网络，也不能新增依赖。仅通过测试不能证明纯净性。

以下独立规定的示例是验收证据：

| 输入 | 必需结果 |
| --- | --- |
| `[]` | `0` |
| `["0.10", "0.20"]` | `30` |
| `["0.29", "1.15"]` | `144`，不能损失任何一分 |
| `["90071992547409.93"]` | `9007199254740993` |
| `["1.00", None, "2.00"]` | `ValueError`，不能给出看似有效的合计 |
| `["1.005"]` 或 `["1e2"]` | `ValueError`，不能四舍五入或接受其他格式 |

[test_invoice.py](../examples/first-use/test_invoice.py) 包含九个验收测试，固定了预期值和拒绝情形。实现时保留这些测试；不要为了让测试通过而削弱合同。它们覆盖的是示例，不是每个可能输入。

<a id="optional-demo-evaluation"></a>

### 可选演示评估

委派前，按以上合同阅读原始 [invoice.py](../examples/first-use/invoice.py) 和 [test_invoice.py](../examples/first-use/test_invoice.py)。预测的失败和已执行测试回执是不同证据。本例不会派发实时任务。

**不复制示例时的替代检查：**在 **Bridge 源码检出根目录**打开 Ubuntu 终端或 WSL Ubuntu Bash。命令读取示例、仅运行它的隔离测试，不启动 Bridge 或 Agent：

```sh
python3 -B -m unittest discover -s examples/first-use -p 'test_*.py' -v
```

在复制后的根目录中改用 `-s .`。随包九测基线有三个通过和六个故意失败；设置或导入错误不属于该基线。在仅修复 `invoice.py` 获得授权后，重跑未改动的测试并记录实际命令、解释器、退出状态和结果。包中不附带修正后通过记录。普通产品测试发现不会收集这个独立 fixture。

若选择连接审查，先完成 Getting Started，在派工前绑定准确 Chat；只使用新 context 中观察到的、属于单独注册可丢弃根目录的 Agent。明确授权一个只读范围及其私有报告；投递结果未知不是重发理由。用哈希固定读取完整报告，并独立比较实际源码。报告缺失或 attention，与提醒或宿主继续运行，是不同观察。

实现需要新的明确权限。测试和合同保持不变；不包含 Bridge 编辑、暂存、提交、服务操作或其他项目影响。之后可由第二个 Agent 审查所得 diff；这种有依赖的审查是后续阶段，不是并行任务。若由同一 Agent 实现并复审，应如实标注。Bridge 没有通用测试执行端点。

<a id="truth-rubric"></a>

### 真实性判定表

| 证据 | 支持的主张 | 不支持的主张 |
| --- | --- | --- |
| 直接读取原始文件 | 观察到的字节和行所展示的内容 | 测试已执行，或之后文件不能改变 |
| 带有验收失败的基线命令 | 随包缺陷已在该解释器中被实际触发 | 产品回归或模型修复成功 |
| Agent A 的报告 | 报告中的实现及其主张 | 代码已验证、确实执行了测试或任务成功 |
| Agent B 的审查 | 第二份评估及其引用的反例 | 共识即正确，或审查者独立性有保证 |
| 修复后用户重跑未改动的九测套件 | 被检查版本在该解释器通过这些情形 | 所有输入、所有环境或安全属性都被证明 |
| Principal 阅读实际结果源码或 diff | 独立观察到的实现证据及推理 | Principal 通过 Bridge 亲自执行了测试 |
| 若已配置，读取新 Chat 的路由状态 | 已恢复记录的决策和边界 | 恢复活动 Work、自动恢复或宿主普遍支持 |

记录源码身份、精确测试回执、分歧和剩余限制。若源码与报告不一致，保留矛盾并寻找能区分结论的证据。不要捏造通过输出、审查分歧或耗时主张。这个玩具任务不隐含基准表现，也不表明优于单个 Agent。

<a id="optional-fresh-chat-continuity"></a>

### 可选：全新 Chat 连续性

只有用户已配置 Project 指令及项目本地连续性，并授权交接时，才通过现有工作流记录已接受或未解决的决策。新 Chat 随后可通过配置的路由读取恢复决策及其边界。不要仅为运行此 fixture 而初始化连续性。本例不读写任何 `.principal/` 文件，也不提供私有配置。录制演示时披露设置或剪辑；不要把三分钟演示说成有保证的安装或运行表现。真正检查新 Chat 时，接手者必须区分审查与实现，恢复下一动作的原因，并遵守权限边界。记录是否观察到这些情况；仅文件回读不能通过该检查。
