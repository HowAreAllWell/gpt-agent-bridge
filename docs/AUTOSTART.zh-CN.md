[English](AUTOSTART.md) | **简体中文**

<a id="bridge--secure-mcp-tunnel-autostart"></a>

# Bridge + Secure MCP Tunnel 自动启动

**第一次安装？**请按[入门指南](GETTING-STARTED.zh-CN.md)操作，选择**原生 Ubuntu Desktop** 或 **Windows + WSL2** 路线。本页解释后台运行方式，并提供进阶全新手动安装与移除步骤，不是正常安装后还要执行一次的清单。

**当前预发布版：**[v0.1.0-rc.5](https://github.com/HowAreAllWell/gpt-agent-bridge/releases/tag/v0.1.0-rc.5) 已提供完整安装包。
旧 `v0.1.0-rc.4` ZIP 不含这些修复；下载和最新步骤见[在线入门指南](GETTING-STARTED.zh-CN.md#download-the-complete-package)。

<a id="already-completed-prepare-start-here"></a>

## 已经完成 `./prepare`？从这里看

在支持的 Linux 上，`./prepare` 会创建自己的应用副本和 Python venv，并**安装、启用和启动两个服务**。Chrome 提醒文件只在之后选择 `reminders` 时才准备，不属于默认设置。venv 就是该应用独立的 Python 包文件夹。不要再次执行下方手动安装块，也不要在已有服务旁再启动前台 Bridge/Tunnel。不要使用 `sudo ./prepare`。

只想查看启动状态、不改任何设置：原生 Ubuntu 打开 **终端**；Windows 打开选定 WSL2 发行版的 **Ubuntu Bash**。使用普通 Linux 用户，当前目录不限：

```bash
systemctl show gpt-agent-bridge-autostart.service -p ActiveState --value
systemctl is-enabled gpt-agent-bridge-autostart.service
systemctl show gpt-agent-bridge-tunnel.service -p ActiveState --value
systemctl is-enabled gpt-agent-bridge-tunnel.service
```

**准备完成后应依次显示：**`active`、`enabled`、`active`、`enabled`。这只检查本地服务。单元不存在、命令失败或值不同，应先检查结果，不要重装、删除状态或反复 start。`./prepare` 安装请保留同一个发行包/路径，并参考[入门排错](GETTING-STARTED.zh-CN.md#if-a-step-stops)。
不要用手动克隆检出的安装器去操作准备流程管理的应用文件。实际 Web 连接另按[第 7 步](#7-verify-local-state-then-the-operators-chatgpt-connection)验证。

<a id="what-automatic-startup-means"></a>

### 自动启动到底是什么

**服务（service）**是无需打开终端也能由 Linux 运行的程序。**systemd** 是 Linux 服务管理器；这些安装器要求它已是第一个系统进程，即 **PID 1**。**单元（unit）**是保存的服务定义。**Enable（启用）**安排以后开机启动；**start（启动）**是现在运行。**Disable（禁用）**取消以后开机启动，但不会停止已运行的程序；**stop（停止）**才会现在结束它。

| 平台 | 谁启动 Bridge 和 Tunnel | 你仍需做什么 |
| --- | --- | --- |
| **原生 Ubuntu Desktop** | 两个已启用的 systemd 服务随 Ubuntu 开机启动。不需要 WSL、PowerShell 或 Windows 任务。 | 在 Ubuntu 浏览器中使用；需要委派时自行启动 Herdr 和已授权 Agents。 |
| **Windows + WSL2** | 该 Linux 发行版启动时，systemd 启动两个服务。可选 Windows 登录助手负责打开并保持同一发行版运行。 | 需要时有意识地配置 [Windows 专用助手](#windows-owner-logon-anchor-optional)，自行启动 Herdr/Agents。仅有服务不会保持 WSL 存活。 |
| **Ubuntu Server / 无桌面** | 同样的 Linux 服务方式是预期进阶路线。 | 单独验证 Herdr/Agent 会话管理。远端浏览器可能通过 Tunnel 使用工具，但不能假定浏览器提醒能访问服务器回环接口。 |

自动启动不会恢复 Work、重放提示、恢复 Agent 终端或启动 Herdr，且依赖电脑未睡眠并已联网。**全新原生 Ubuntu 安装/重启，以及 Windows 登录/云端验收，尚未在新用户机器完成**；源码与合成测试不能证明这些结果。不保证 Windows 登录前、注销后、挂起时或全天候运行。

<a id="need-the-manual-service-route-instead"></a>

### 确实要改用手动服务路线？

只在完成源码依赖安装、并明确授权**全新手动安装**后执行[下方第 1–7 步](#1-prepare-and-choose-the-owner)。它们把计划、安装、私密凭据、启用和启动拆开，让你逐项检查。行动失败或结果未知就停止；未知不代表没有发生修改，也不授权重试。

安全和移除细节见进阶 [Bridge 组件参考](#bridge-component-contract)与 [Tunnel 组件参考](#tunnel-component-contract)。它们是组合步骤的替代，不是额外安装。[前台路线](QUICKSTART.zh-CN.md#foreground-secure-mcp-tunnel)也是另一种选择；不要在服务旁再运行第二个客户端。

<a id="1-prepare-and-choose-the-owner"></a>

## 1. 准备并选择所有者

**在哪里：**原生 Ubuntu 使用 Ubuntu 终端；Windows 使用选定 WSL Ubuntu Bash。以将拥有该安装的 Linux 账户运行，不开 root shell。第 1–7 步保持同一终端，后续块需要其中的变量和函数。`set -euo pipefail` 会让错误停止序列，可能退出该 shell；退出后先检查，不要未核对状态就重新拼接步骤继续。

两个平台都要求 Linux 已使用 systemd 作为 PID 1。若不满足就停止，这些脚本不配置操作系统。原生 Ubuntu 不需要 Windows 助手；WSL 的 [Microsoft systemd 设置](https://learn.microsoft.com/windows/wsl/systemd)属于另行决定的系统操作。

在**长期保留的 Linux 主目录检出**中完成[快速开始依赖设置](QUICKSTART.zh-CN.md#2-clone-and-install-direct-dependencies)，将其 src 包安装到该检出的 `.venv`。运行时使用 `.venv/bin/python -I -B -m gpt_agent_bridge`。选择长期保留的发布检出；适合时另选一个已有 Git 工作区。两个根目录都必须精确对应非裸 Git 检出的根目录。

全程使用同一个明确的非 root 账户、UID、主 GID 和 HOME。代码、工作区、主目录、解释器/venv/依赖及选定的 Herdr 二进制必须满足组件信任检查：由 root 或选定所有者控制，不允许组/其他用户写入，不允许代码/配置符号链接、代码硬链接或不安全的上级路径。Bridge 路径拒绝空格、元字符和 `/mnt/`；支持经检查的 venv Python 符号链接。Tunnel 的整树扫描对可写上级目录更严格；不适合部署在共享 `/tmp` 中。路径、查找根或清单上限不受支持时应停止，不能放宽权限或检查。

按照 [Herdr 兼容性指南](QUICKSTART.zh-CN.md#herdr-compatibility-and-version-selection) 选择兼容的 Herdr v0.9.0 二进制；复用可用安装。Herdr 可以保持停止：不要只为 Bridge 就绪而启动它。取得并独立验证完整官方 [v0.0.16 Tunnel 包](QUICKSTART.zh-CN.md#3-obtain-and-verify-the-pinned-linux-client)，再由管理员放到可信的 root 所有位置。仅有经审核的二进制摘要不能证明其官方来源。这些安装器不执行下载、Herdr 启动或账户操作。

**仅限全新手动安装：**如果存在前台 Bridge/Tunnel、其他服务单元、未知单元/drop-in、先前安装/快照目录、占用端口、已有 Tunnel 配置，或必须保留的代理/CA/mTLS 设置，须先由操作者明确决定。此流程不会检查进程环境、导入密钥、终止进程、更改 App 绑定或接管运行中的部署。

第一块运行前，将**所有示例值**换成实际值：

| 变量 | 填什么 |
| --- | --- |
| `bridge_user`、`bridge_home` | 非 root Linux 登录名及主目录，不是 Windows 用户名。`id -un` 显示当前 Linux 登录名。 |
| `bridge_repo` | 长期保留的 Bridge 源码文件夹，其中已有准备好的 `.venv`。 |
| `bridge_workspace` | 准备授权的现有 Git 项目根目录，不是子目录或 Windows 盘路径；可与源码文件夹不同。 |
| `herdr_bin` | 已验证的 Linux Herdr v0.9.0 可执行文件绝对路径。 |
| `client_binary`、`client_sha256` | 管理员放置的 root 所有、已验证 v0.0.16 客户端，以及独立审核的**二进制文件** SHA256；不是密钥，也不是 ZIP 哈希。 |
| `bridge_installer`、`tunnel_installer` | 两个新的 root 私有审核路径。分别保留，不复用已有快照目录。 |

UID 和 GID 是 Linux 的数字用户/组身份，代码块从当前账户读取；HOME 必须匹配该账户。在同一 Bash 会话中分别执行完整代码块，每一步检查后再继续：

```bash
# gate: combined-plans
set -euo pipefail
bridge_user='your_linux_user'
bridge_home='/home/your_linux_user'
bridge_repo='/home/your_linux_user/gpt-agent-bridge'
bridge_workspace='/home/your_linux_user/your-git-project'
herdr_bin='/home/your_linux_user/.local/bin/herdr'
client_binary='/opt/openai-tunnel-client-v0.0.16/tunnel-client'
client_sha256='REPLACE_WITH_INDEPENDENTLY_REVIEWED_BINARY_SHA256'
bridge_installer='/root/gpt-agent-bridge-autostart-setup/installer.py'
tunnel_installer='/root/gpt-agent-bridge-tunnel-review-v1/installer.py'
[[ "$(id -un)" == "$bridge_user" && "$(id -u)" != 0 && "$HOME" == "$bridge_home" ]] || exit 1
bridge_uid="$(id -u)"
bridge_gid="$(id -g)"
[[ "$(getent passwd "$bridge_user" | cut -d: -f6)" == "$bridge_home" ]] || exit 1
/usr/bin/python3 -I -B "$bridge_repo/scripts/install-bridge-autostart.py" plan \
  --user "$bridge_user" --repo "$bridge_repo" --workspace "$bridge_workspace" \
  --herdr-bin "$herdr_bin" --port 8765 || exit 1
/usr/bin/python3 -I -B "$bridge_repo/scripts/install-bridge-tunnel-autostart.py" plan \
  --user "$bridge_user" --client "$client_binary" --client-sha256 "$client_sha256" \
  --health-socket health.sock --ttl 10m || exit 1
```

**检查结果：**两个 `plan` 命令都须成功，比较其中的 user/UID/GID/HOME 和路径是否正是预期安装。缺少前提、保留占位符或路径被拒绝时，安装前先停止修正计划。不要放宽所有权或权限强行通过。计划是非秘密的只读观察，不能认证运行时就绪。TTL 默认为 10m；60m 是明确可选值，不是无限连接。

<a id="2-define-fail-stop-observations"></a>

## 2. 定义失败即停的观察检查

在**同一 Linux 终端**粘贴完整块，定义后续使用的 `require_*` 辅助函数。仅定义函数不会改变服务，通常没有输出；后续调用会比较实际与预期状态，不匹配即停止。粘贴失败时不能跳过这些检查。

这些 shell 检查只做观察，不是另一个安装器或监督程序。修改命令退出零或返回 `command_completed` **不能**证明已达到请求的状态。观察缺失、为假、未知或处于过渡状态时，停止此序列。不要重试效果不确定的修改。有界的只读 status/probe 观察可用于诊断启动；这里不要求轮询循环。

```bash
# gate: observations
set -euo pipefail
require_unit_policy() {
  local observed
  observed="$(/usr/bin/systemctl show "$1" -p LoadState --value)" || return 1
  [[ "$observed" == loaded ]] || return 1
  observed="$(/usr/bin/systemctl show "$1" -p FragmentPath --value)" || return 1
  [[ "$observed" == "/etc/systemd/system/$1" ]] || return 1
  observed="$(/usr/bin/systemctl show "$1" -p DropInPaths --value)" || return 1
  [[ -z "$observed" ]]
}
require_bridge() {
  require_unit_policy gpt-agent-bridge-autostart.service || return 1
  sudo /usr/bin/python3 -I -B "$bridge_installer" status |
    /usr/bin/python3 -I -B -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if isinstance(d,dict) and d.get("service")==sys.argv[1] and d.get("enabled")==sys.argv[2] else 1)' "$1" "$2"
}
require_bridge_health() {
  "$bridge_repo/.venv/bin/python" -I -B /usr/local/lib/gpt-agent-bridge-autostart/runner.py probe |
    /usr/bin/python3 -I -B -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if isinstance(d,dict) and d.get("bridge_mcp")=="initialized_healthy" and d.get("herdr") in ("reachable","unavailable","unknown") and d.get("work_resume")=="not_established" else 1)'
}
require_tunnel() {
  require_unit_policy gpt-agent-bridge-tunnel.service || return 1
  /usr/bin/python3 -I -B /usr/local/lib/gpt-agent-bridge-tunnel-autostart/runner.py status |
    /usr/bin/python3 -I -B -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if isinstance(d,dict) and d.get("process")==sys.argv[1] and d.get("boot_activation")==sys.argv[2] and (not sys.argv[3] or d.get("tunnel_startup")==sys.argv[3]) else 1)' "$1" "$2" "${3:-}"
}
```

完成初始化的 Bridge 探测检查精确身份和布尔值 `ok=true`；`ok=1` 无效。Herdr 不可用不阻止此路线。Install 报告成功前也会自行精确检查 fragment/drop-in/disabled/inactive。上述观察还保护各操作者阶段之间的边界。

<a id="3-review-separate-privileged-snapshots"></a>

## 3. 审核独立的特权快照

在**同一 Linux 终端**中，先审核两个安装脚本及服务模板，再批准管理员权限。这里的快照是与可编辑检出分开放置的已审核文件固定副本。下方块会**以 root 创建并复制文件**；`cmp` 无输出表示副本一致。密码提示是系统 sudo 授权，不是 Tunnel 密钥。目录已存在或任何复制/比较失败就停止并保留现场，不要删除它，也不要只继续剩余命令。

先审核两个控制器和生产模板。不要以 root 运行用户控制的检出或其 venv。只把审核过的安装资源复制到**两个新的 root 私有目录**，绝不覆盖旧快照：

```bash
# gate: combined-snapshots
set -euo pipefail
sudo mkdir -m 0700 -- "$(dirname "$bridge_installer")" || exit 1
sudo /usr/bin/install -o root -g root -m 0700 "$bridge_repo/scripts/install-bridge-autostart.py" "$bridge_installer" || exit 1
sudo /usr/bin/cmp -- "$bridge_repo/scripts/install-bridge-autostart.py" "$bridge_installer" || exit 1
sudo mkdir -m 0700 -- "$(dirname "$tunnel_installer")" || exit 1
sudo /usr/bin/install -o root -g root -m 0600 "$bridge_repo/scripts/install-bridge-tunnel-autostart.py" "$tunnel_installer" || exit 1
sudo /usr/bin/install -o root -g root -m 0600 "$bridge_repo/systemd/gpt-agent-bridge-tunnel.service.template" "$(dirname "$tunnel_installer")/service.template" || exit 1
sudo /usr/bin/cmp -- "$bridge_repo/scripts/install-bridge-tunnel-autostart.py" "$tunnel_installer" || exit 1
sudo /usr/bin/cmp -- "$bridge_repo/systemd/gpt-agent-bridge-tunnel.service.template" "$(dirname "$tunnel_installer")/service.template" || exit 1
```

在私密环境下将字节/摘要与批准的发布版本比较。Bridge 从选定代码根验证固定模板哈希。这些复制操作本身不授予安装权限。

<a id="4-install-disabled-and-inactive-then-configure-privately"></a>

## 4. 安装为禁用且未运行，再私密配置

分别明确授权每个安装。Bridge 生成一个稳定 token，Tunnel 复用它，不再生成第二个 token。在**同一 Linux 终端**执行第一块，安装 Bridge 文件并检查 **inactive + disabled**，即已安装但现在不运行、以后也未安排开机启动。这是手动阶段的预期结果，与完整 `./prepare` 流程不同。失败或回读未知时，应在安装 Tunnel 前停止：

```bash
# gate: bridge-install
set -euo pipefail
sudo /usr/bin/python3 -I -B "$bridge_installer" install \
  --user "$bridge_user" --repo "$bridge_repo" --workspace "$bridge_workspace" \
  --herdr-bin "$herdr_bin" --port 8765 || exit 1
require_bridge inactive disabled || exit 1
```

只有完成该回读确认后，才在同一终端单独授权 Tunnel 安装。预期 Tunnel 也是 **inactive + disabled**。检查失败就停在输入凭据之前，不要重跑任一安装：

```bash
# gate: tunnel-install
set -euo pipefail
require_bridge inactive disabled || exit 1
sudo /usr/bin/python3 -I -B "$tunnel_installer" install \
  --user "$bridge_user" --client "$client_binary" --client-sha256 "$client_sha256" \
  --health-socket health.sock --ttl 10m || exit 1
require_tunnel inactive disabled || exit 1
```

两个组件的 unit、manifest、loader、state 和 root 快照路径相互独立；见组件文件表。使用**同一所有者**在私密 TTY 中配置，不用 sudo。私密输入你自己的 Tunnel ID 和运行时密钥。这个密钥与 Bridge token 不同，也与模型 API 推理收费不同。私密 TTY 指你自己控制、不共享屏幕或录制的交互式终端。在两个隐藏输入提示中填自己的 Tunnel ID 和运行密钥，输入不会回显。不要放进代码块、Chat 或跟踪文件。配置结束后 Tunnel 应仍 inactive 且 disabled；没有提示、被拒绝或检查失败都应停止。

```bash
# gate: combined-configure
set -euo pipefail
[[ "$(id -u)" == "$bridge_uid" && "$(id -g)" == "$bridge_gid" && "$HOME" == "$bridge_home" ]] || exit 1
/usr/bin/python3 -I -B /usr/local/lib/gpt-agent-bridge-tunnel-autostart/runner.py configure || exit 1
require_tunnel inactive disabled || exit 1
```

密钥不会进入 argv、仓库片段或公共日志。Tunnel 在运行时读取 Bridge 的受保护清单/设置，并在内存中构建能力 URL；没有第二份 token 存储，也不保存重复的后端 URL。当前 Tunnel 的 install/configure/enable/start 不预先验证 Bridge 契约；验证发生在运行时。这里的顺序和检查是明确的操作者门禁，不是隐藏的 CLI 保证。

<a id="5-opt-into-bridge-boot-activation-and-start"></a>

## 5. 自愿启用 Bridge 开机激活并启动

启用和立即启动是不同选择。下列每个代码块都需要单独明确授权。检查失败后不要进入下一个代码块。在**同一 Linux 终端**，第一块启用 Bridge 开机启动，预期 **inactive + enabled**，还不应立即运行：

```bash
# gate: bridge-enable
set -euo pipefail
require_bridge inactive disabled || exit 1
sudo /usr/bin/python3 -I -B "$bridge_installer" enable || exit 1
require_bridge inactive enabled || exit 1
```

接着在同一终端，下一块**立即启动 Bridge**。预期 **active + enabled**，并且已初始化健康探测通过。失败就先私下观察状态再决定修复，不能另开前台副本。

```bash
# gate: bridge-start
set -euo pipefail
require_bridge inactive enabled || exit 1
sudo /usr/bin/python3 -I -B "$bridge_installer" start || exit 1
require_bridge active enabled || exit 1
require_bridge_health || exit 1
```

除非已确认完成初始化的 Bridge 健康状态，否则在此停止。Herdr 不必运行。失败或待定的检查不允许启动另一个 Bridge，也不允许盲目重发 start。

<a id="6-opt-into-tunnel-boot-activation-and-start"></a>

## 6. 自愿启用 Tunnel 开机激活并启动

留在**同一 Linux 终端**。第一块检查已正常运行的 Bridge，并启用 Tunnel 开机启动；预期 Tunnel **inactive + enabled**，还不立即运行。任何检查失败即停止。

```bash
# gate: tunnel-enable
set -euo pipefail
require_bridge active enabled || exit 1
require_bridge_health || exit 1
require_tunnel inactive disabled || exit 1
sudo /usr/bin/python3 -I -B "$tunnel_installer" enable || exit 1
require_tunnel inactive enabled || exit 1
```

然后才另行批准立即启动 Tunnel。下一块预期 **active + enabled + ready**。启动待定或未知就按下文停止检查，不要反复发送 start。

```bash
# gate: tunnel-start
set -euo pipefail
require_bridge active enabled || exit 1
require_bridge_health || exit 1
require_tunnel inactive enabled || exit 1
sudo /usr/bin/python3 -I -B "$tunnel_installer" start || exit 1
require_tunnel active enabled ready || exit 1
```

start 返回时，启动仍可能待定。待定或未知的观察会停止此序列；保留证据，用有界只读 status 诊断，而不是再次 start。单元有 `After=Bridge network-online.target`，没有 `Wants`、`Requires` 或 `BindsTo`；两个服务都不启动 Herdr 或 Agents。两个单元必须各自启用。重启不会恢复 Work。

<a id="7-verify-local-state-then-the-operators-chatgpt-connection"></a>

## 7. 先验证本地状态，再验证操作者的 ChatGPT 连接

**本地检查：**同一 Linux 终端中，上面的观察应显示两个服务都 active 且 enabled。本地 Tunnel `ready` 不等于云端认证、远程可达性或 Web App 就绪。

**浏览器检查：**打开目标**普通 ChatGPT Web Project Chat**，使用已有授权 Bridge App，只请求只读 `bridge_health`。按入门指南分别检查工具发现和四个原生 Skills。Work/本地 Codex 成功、设置里四个蓝色开关，都不证明它们已在这个 Chat 中可用。这个支持目标不代表平台强制 Web 专属显示。

单独验证你自己的账户/工作区权限和 [ChatGPT 连接](GETTING-STARTED.zh-CN.md#5-connect-the-tunnel-to-your-private-chatgpt-plugin)。不要自动更新已有 App 绑定。需要本地委派时手动打开 Herdr 和 Agents。真实开机/登录/云端验收需要之后单独授权的目标主机试验。

**原生 Ubuntu：**跳过 Windows 助手。两个已启用单元的预期行为是随 Ubuntu 开机启动；之后另行授权的重启测试须验证本地健康和真实 Web 调用。以上手动步骤没有执行该测试。

**仅 Windows + WSL2：**使用一个可选的当前所有者 SID 驻留任务，使用同一发行版和 Linux 所有者：按 [Windows 驻留步骤](#windows-owner-logon-anchor-optional) 操作。其 Install 保持禁用；Enable 和读回确认另行执行。它在**两个已启用 Linux 单元**启动时保持 WSL 生命周期，不是第二个 Tunnel 任务。只有服务不能保持 WSL 运行。这里不证明真实 Windows/PowerShell 执行结果。

<a id="pause-and-remove-deliberately"></a>

## 有意暂停和移除

**停止或移除前，先选清楚效果。**Stop 是现在结束进程，disable 是阻止以后自动启动。删除文件是另一项操作，不是修复未知启动结果的办法。先记录脱敏状态并保留私有证据，不要发布带令牌的诊断。

分别禁用后续开机激活并停止各单元，先 Tunnel 后 Bridge。每次组件卸载前，用上述观察确认 inactive/disabled。Tunnel 移除保留私密凭据/状态证据，不吊销密钥；Bridge 移除另有严格的文件清单和 token 删除契约。参见 [Tunnel 移除](#provision-privately-then-explicitly-enable-and-start) 和 [Bridge 移除](#pause-removal-and-unknown-outcomes)。不要盲目重装，也不要删除未知或不属于本安装的部分发布。Windows 驻留任务的 Disable/StopAnchor/Uninstall 是独立层，不等于 Linux 的 disable/stop/uninstall；结束驻留任务可能随着 WSL 退出而中断两个服务。

<a id="bridge-component-contract"></a>

## Bridge 组件契约

**进阶参考，不是新用户的另一张清单。**继续使用你上面选定的路线。下方细节供维护者或操作者审核手动更改，解释精确检查和保存的文件。

以下单组件参考是组合步骤的替代方案，不是在组合步骤之后再安装一次。每个 enable/start/移除命令都须分别授权；失败或结果未知时停止。

<a id="choose-the-correct-installer"></a>

### 选择正确安装器

- 此[首次安装脚本](../scripts/install-bridge-autostart.py) 不要求已有 Bridge 进程，创建独立的 `gpt-agent-bridge-autostart.service`。
- 单独的[接管器](../scripts/install-bridge-system-service.sh) 检查该检出已运行的 Bridge，安装自己的单元，但从不启动或启用它。不要组合使用这两种服务安装。

先完成[依赖安装](QUICKSTART.zh-CN.md#2-clone-and-install-direct-dependencies)，并选择兼容的 Herdr 可执行文件。使用一个明确的非 root Linux 账户、该账户已有的检出、其拥有的 Git 工作区和 Linux 文件系统路径。这个小型 v0 拒绝符号链接检出/Herdr/配置路径、`/mnt/` 路径，以及 Linux 路径中的空格和元字符。允许普通 venv Python 符号链接。它不安装依赖，也不授予 Bridge 工具 sudo 权限。推荐 Herdr v0.9.0 二进制；它可以保持停止。按公共 [Herdr 兼容性指南](QUICKSTART.zh-CN.md#herdr-compatibility-and-version-selection) 操作并复用可用安装。

代码、工作区、账户主目录、Herdr 及控制它们的目录必须由所选服务账户或 root 拥有，且不允许组/其他用户写入。调用解释器前会检查源码包和整个 venv 依赖树（含 `.pth` 文件与解析后的解释器）。允许私有检出上方存在 root 所有且带 sticky 位的临时祖先目录；拒绝共享可写的 home/code/venv 目录。意外依赖符号链接、外部所有者或超过安全上限的文件清单需要操作者审核。发布前、enable/start 前以及运行时执行前都会再次检查。它们防止其他账户修改启动输入，不防止恶意的选定账户或 root 在检查间修改文件。

唯一受支持的入口是检出的 `.venv/bin/python -m gpt_agent_bridge`；加载器和运行时加上 `-I -B` 隔离标志，使继承的 Python 路径/用户 site 设置或工作目录不能改变已检查的包来源。按快速开始说明，使用 `pip install -e .` 将此 src 包安装到该精确 venv。不回退到根目录 `server.py` 或其他旧入口。代码根和 `BRIDGE_WORKSPACE` 都必须是明确、绝对、已存在的非裸 Git 检出根；子目录会被拒绝。包来源检查使用 `python -I -B` 和 `importlib.util.find_spec`，不导入配置的 server 代码。若通过 sudo 调用，这些用户控制的检查将以所选非 root 账户、清空补充组并使用最小环境运行。

<a id="linux-plan-install-enable-and-start"></a>

### Linux 计划、安装、启用和启动

在 **Ubuntu 终端 / WSL Ubuntu Bash** 中，以普通所有者账户进入已批准 Bridge 检出根目录。这是单组件替代路线，不是 `./prepare` 或组合安装后的步骤。替换所有示例路径和用户名。下一块只制定计划，预期计划成功且所有者/路径正确；缺少输入或被拒绝就停止：

```bash
# gate: component-bridge-plan
bridge_user='your_linux_user'
bridge_repo='/absolute/linux/path/gpt-agent-bridge'
bridge_workspace='/absolute/linux/path/your-git-project'
herdr_bin='/absolute/linux/path/to/herdr'
python3 -I -B "$bridge_repo/scripts/install-bridge-autostart.py" plan \
  --user "$bridge_user" --repo "$bridge_repo" \
  --workspace "$bridge_workspace" --herdr-bin "$herdr_bin" --port 8765 || exit 1
```

Plan 验证本地输入，不调用 systemctl、网络探测、凭据读取、文件写入或服务操作。其路径是配置，不是运行进程扫描。验证工作区是预期的 Bridge 注册权限来源；通过[入门：连接自己的项目](GETTING-STARTED.zh-CN.md#8-connect-your-existing-git-repository-and-merge-its-binding) 明确连接每个项目。

安装前，由操作者停止占用此端口的前台 Bridge。脚本拒绝已占用监听端口、已有接管器单元、未知单元/drop-in 或已有安装文件。它绝不停止或接管未知进程。发布前，它按有限支持列表检查管理器的单元查找路径、root 目录权限、磁盘单元名称、别名、依赖链接（即使悬空）和 unit/dash-prefix/`service.d` drop-in。外部或不确定的激活策略会被拒绝；绝不删除这些文件。此设计有意拒绝继承的自定义配置。WSL 必须已使用 systemd 作为 PID 1；参见 [Microsoft systemd 说明](https://learn.microsoft.com/windows/wsl/systemd)。脚本不更新 WSL 或编辑其配置。

以下每条命令都是**单独、明确的操作者行动**。先审核安装器字节，再仅将该脚本复制到操作者拥有的私有 root 目录。特权安装器拒绝用户所有的源码脚本或非私有源码目录；不要直接对用户检出运行 sudo。`install` 需要 sudo，一次生成新的稳定能力 token，验证暂存单元，并在不覆盖的前提下发布文件。它不启用或启动单元。

```bash
# gate: component-bridge-install
installer='/root/gpt-agent-bridge-autostart-setup/installer.py'
# mkdir fails if a prior/unknown setup directory exists: do not overwrite it.
sudo mkdir --mode=0700 -- "$(dirname "$installer")" || exit 1
sudo install -o root -g root -m 0700 "$bridge_repo/scripts/install-bridge-autostart.py" "$installer" || exit 1
# Privately compare this copy with the reviewed source before proceeding.
sudo cmp -- "$bridge_repo/scripts/install-bridge-autostart.py" "$installer" || exit 1
sudo python3 -I -B "$installer" install \
  --user "$bridge_user" --repo "$bridge_repo" \
  --workspace "$bridge_workspace" --herdr-bin "$herdr_bin" --port 8765 || exit 1
```

只有 install 报告精确的已加载 fragment、没有额外 drop-in、状态 inactive 且 enablement 为 disabled 后才继续。任何失败或未知结果都会停止此序列：保留发布证据，供操作者私密检查。启用开机启动必须是另一次有意识的选择：

```bash
# gate: component-bridge-enable
sudo python3 -I -B "$installer" enable || exit 1
```

enable 成功后，立即启动仍是另一项独立选择：

```bash
# gate: component-bridge-start
sudo python3 -I -B "$installer" start || exit 1
```

使用全新的 root 设置目录，不覆盖先前或未知的安装器。上述复制命令是操作者行动，不是自动设置。只对审核过、root 所有的副本运行 sudo。发布前按 SHA256 对安装器校验其固定服务模板。用户所有的应用代码仍以所选非 root 账户运行。已安装的 root 所有加载器和单元固定不变；运行时配置是 JSON，绝不作为 shell 代码 source。root 所有且可读的清单固定公共运行路径/身份；所有者可写设置不能重定向启动器、工作区或 Herdr 路径。能力 token 只保存在所有者私有设置中。已安装 runner 由 root 拥有。单元使用 `Restart=on-failure`、五秒延迟和 60 秒内五次的启动限制。有意 `stop` 后保持停止，直到明确 start 或下次已启用的开机。`disable` 取消后续开机启用，但不停止活动服务。`NoNewPrivileges=true` 表示这个 v0 不支持产品内通过 sudo 重启服务。

<a id="private-token-and-client-handoff"></a>

### 私有 token 与客户端交接

`/var/lib/gpt-agent-bridge-autostart/` 权限为 0700，由服务用户拥有；`settings.json` 为 0600，包含稳定的路径 token。加载器读取前检查所有权、符号链接、类型、硬链接和权限。只传递最小运行时变量，不复制无关 shell 凭据/代理。应用 stdout/stderr 进入 `null`，因为传输诊断可能包含秘密 URL。Systemd 仍记录单元状态。调试需要停止服务后另行批准的私密前台会话，不应依靠公共日志。

全新安装生成一个稳定 token，Tunnel 使用同一个 token；不要再生成第二个客户端 token。

使用替代的前台健康检查 + Tunnel 流程时，以服务所有者（不是 sudo）创建明确的临时交接文件。无人值守的[组合路线](#1-prepare-and-choose-the-owner) 直接读取受保护记录，不需要交接文件：

```bash
# gate: component-bridge-handoff
"$bridge_repo/.venv/bin/python" -I -B /usr/local/lib/gpt-agent-bridge-autostart/runner.py handoff || exit 1
```

它在私有状态目录内创建交接文件，只打印路径名，不打印 token 或完整 MCP URL；从不使用 shell 的 `TMPDIR` 检出。文件包含 exports，必须保密。在同一发行版和检出中，将该路径用于 [Tunnel 组合第 4 步](QUICKSTART.zh-CN.md#combined-step-4)，**不要生成 token 或另启 Bridge**。该指南在同一子 shell 中 source/删除交接文件，并保留健康检查 + Tunnel。只运行一个 Tunnel 客户端；此助手不启动它，也不使其持久运行。卸载前，未使用的交接文件必须由所有者移除。Tunnel 控制面密钥是另一项凭据，绝不能放入此服务配置。

<a id="read-only-status-and-initialized-mcp-health"></a>

### 只读状态与已初始化 MCP 健康检查

用于**本页的手动安装**：使用同一所有者的 Ubuntu 终端 / WSL Ubuntu Bash，`bridge_repo` 仍设为已安装代码根目录。第一条查看服务状态，第二条调用本地只读 `bridge_health`。两者都不启动或修复任何内容。按下方分类检查；缺失/无效结果应检查，不是重启。

```bash
# gate: component-bridge-status
python3 -I -B "$bridge_repo/scripts/install-bridge-autostart.py" status || exit 1
"$bridge_repo/.venv/bin/python" -I -B /usr/local/lib/gpt-agent-bridge-autostart/runner.py probe || exit 1
```

Status 读取 systemd 状态，不读取私有配置或进行修复。Probe 以服务所有者运行，读取受保护设置，进入 MCP 客户端 initialize 上下文，只调用 `bridge_health`。它输出有界分类，从不输出原始传输异常、能力 URL、Agent 详情或 Herdr 错误文本：

- `bridge_mcp=initialized_healthy` 要求初始化后的字典响应、精确的 `bridge=gpt-agent-bridge` 和布尔值 `ok=true`（不能用其他真值代替）。
- `herdr=reachable` / `unavailable` 单独报告；外层 `ok` 不足以证明就绪。
- `unavailable_or_invalid` / `unknown` 表示需要检查，不是自动重试或重启。
- `work_resume=not_established` 始终如此；健康不等于 Work 完成或恢复。

`bridge_mcp=initialized_healthy` 时，Probe 退出零，包括 Herdr 为 `unavailable` 或 `unknown` 的情况；Herdr 是独立且不阻塞的就绪分类。初始化 Bridge 响应缺失或无效时退出非零。它不启动任何内容；`bridge_health` 可能执行 Herdr 只读快照。远程 ChatGPT App 必须独立确认；本地 MCP 不能证明 Tunnel/宿主可用。

<a id="windows-owner-logon-anchor-optional"></a>

### Windows 所有者登录驻留任务（可选）

**原生 Ubuntu Desktop/Server 跳过整节。**这里的驻留任务（anchor）指只负责保持选定 WSL 发行版打开的 Windows 登录任务，不是 Linux 服务安装器。已经有此任务时，使用其审核过的 Status 检查，不要再次 Install。

在 Windows 10 build 19041+ 或 Windows 11 上，使用所有者的 Windows PowerShell 5.1+、WSL2 和 ScheduledTasks。此助手不以 SYSTEM 运行、不保存密码、不绕过执行策略、不配置 WSL。若本地策略禁止脚本或任务，应停止并取得操作者批准，不要绕过。Install/Enable 前，明确打开选定发行版并验证其非 root 用户和 systemd。助手只对已经运行的发行版发出只读检查；Plan 从不启动发行版。

使用实际的 `wsl -l -v` 发行版名和实际 Linux 用户名；示例是 PowerShell，**不是 Bash**。脚本路径应指向审核过、Windows 可访问的助手副本（例如通过发行版的 `\\wsl.localhost\` 共享）：

```powershell
# gate: component-windows-anchor
$helper = '\\wsl.localhost\Ubuntu\home\your_linux_user\gpt-agent-bridge\scripts\install-bridge-wsl-logon-task.ps1'
& $helper -Action Plan -Distro 'Ubuntu' -LinuxUser 'your_linux_user'
if (-not $?) { throw 'Previous helper result failed or is uncertain; stop and inspect.' }
& $helper -Action Install -Distro 'Ubuntu' -LinuxUser 'your_linux_user'
if (-not $?) { throw 'Previous helper result failed or is uncertain; stop and inspect.' }
& $helper -Action Status -Distro 'Ubuntu' -LinuxUser 'your_linux_user'
if (-not $?) { throw 'Previous helper result failed or is uncertain; stop and inspect.' }
& $helper -Action Enable -Distro 'Ubuntu' -LinuxUser 'your_linux_user'
if (-not $?) { throw 'Previous helper result failed or is uncertain; stop and inspect.' }
```

Install 使用文档规定的 `New-ScheduledTaskSettingsSet -Disable`，读回 XML 和任务状态后才报告 **disabled**。Enable/Disable 同样读回请求状态和精确的归属策略。Enable 选择当前用户登录调度，不显式运行任务。Task Scheduler 重启也可能触发已登录且匹配的用户，因此不能绝对承诺等待下一次全新登录。唯一固定动作直接调用系统的 `wsl.exe --distribution "Ubuntu" --user "your_linux_user" --exec /usr/bin/sleep infinity`。任务中不含 shell 插值、密码、token 或执行绕过。它使用当前用户 LogonTrigger/InteractiveToken/LeastPrivilege，**任务设置**使用 `PT0S`，使用 `IgnoreNew`，并允许电池供电运行。这不能证明触发器特定的有效限制为零；助手拒绝显式非零触发器限制，但省略限制仍需真实 Windows 验收。不保证 >72 小时生命周期。未知发行版/用户、非 WSL2、未知已有任务或不支持宿主都会被拒绝。含引号/反斜杠/元字符的名称不受支持，不能猜测处理。

驻留任务旨在 Linux systemd 管理 Bridge 时保持 WSL 活动。[Microsoft 明确说明，只有 systemd 服务不会让 WSL 保持运行](https://learn.microsoft.com/windows/wsl/systemd#how-does-enabling-systemd-affect-wsl-architecture)。助手拒绝未知任务结构，在 XML 和 CIM 中检查描述，并验证所有者 SID、InteractiveToken/LeastPrivilege、电池策略、唯一 action/trigger/principal 和请求的启用状态。意外 XML 序列化或 HKCU 发行版注册表表示会触发拒绝，而不能证明不存在。任务级 `PT0S` 不能认证所有生命周期限制；触发器特定上限及真实 >72 小时的登录触发执行需要验收。`IgnoreNew` 只对同一任务的实例去重，不对其他任务名去重。

无窗口执行、sleep-infinity 生命周期、精确的注册表/任务 XML 兼容性、注销和挂起行为，**必须在目标 Windows 上验证**。这不是登录前或全天候设计。强制关闭 WSL 会结束驻留任务，不保证另一次登录前自动恢复。这里没有任务重启/重连魔法承诺。注销不同于锁定/解锁；不能把交互会话生命周期宣传为注销后仍继续托管。WSL 启动还可能运行已有已启用单元/启动命令：须单独审核发行版开机策略。组合路线有意启用 Tunnel；Herdr/Agent 启动和其他已有启动策略不属于此次设置。不要另装竞争性的登录任务来启动相同服务。

<a id="pause-removal-and-unknown-outcomes"></a>

### 暂停、移除与未知结果

对于**手动 Bridge 安装**，在仍保留 `installer` 的 Linux Bash 会话执行下块：依次取消以后开机启动、立即停止 Bridge、移除已识别安装及其令牌。先按上文停止/移除 Tunnel，明确批准三个效果后才运行。每个失败都应停止，不要删除残留，也不能把部分结果当成回滚完成。

```bash
# gate: component-bridge-remove
sudo python3 -I -B "$installer" disable || exit 1
sudo python3 -I -B "$installer" stop || exit 1
sudo python3 -I -B "$installer" uninstall || exit 1
```

Uninstall 要求服务 disabled + inactive、root 所有安装文件匹配，且目录中没有额外文件。它只移除此安装（包括 token），绝不移除其他单元或配置。不删除项目中的服务数据。发布前验证失败只清理新的暂存文件；单元发布后，管理器结果不确定时保留证据供检查。清理检查已记录的 inode/类型/所有者/权限/内容，绝不递归删除未知文件；更改或外来内容会保留供操作者审核。不要盲目重跑 install、覆盖文件或重试不确定的服务行动。

**仅 Windows：**在同一所有者的 PowerShell，确认 `$helper` 指向审核脚本。下块禁用并停止登录驻留任务，再移除已识别任务；移除前应确认 disabled/stopped。状态未知就停，不能注销猜测的任务。

```powershell
# gate: component-windows-remove
& $helper -Action Disable -Distro 'Ubuntu' -LinuxUser 'your_linux_user' -StopAnchor
if (-not $?) { throw 'Previous helper result failed or is uncertain; stop and inspect.' }
& $helper -Action Uninstall -Distro 'Ubuntu' -LinuxUser 'your_linux_user'
if (-not $?) { throw 'Previous helper result failed or is uncertain; stop and inspect.' }
```

没有 `-StopAnchor` 时，Disable 只移除后续触发，运行中的驻留任务继续。移除运行中或排队的任务需要明确 `-StopAnchor`；未知状态拒绝移除。Uninstall 先禁用并验证该状态，再检查任务状态和 COM 实例枚举后注销任务。可选 StopAnchor 也需要 disabled/状态/零实例读回；仅发出停止请求不能证明已终止。拒绝不授权盲目重试。此操作不调用 WSL shutdown 或直接停止 Linux 服务。结束最后一个驻留任务可能间接允许 WSL 关闭并中断 Bridge；确切关闭时间尚未验证。应有意暂停两个层面。任务在运行本身不证明 Bridge 健康。此组件任务不直接启动 Tunnel/Herdr；组合路线由 systemd 启动单独启用的 Tunnel 单元。

<a id="acceptance-before-relying-on-persistence"></a>

### 依赖持久运行之前的验收

合成测试覆盖权限、不覆盖、输入安全、单元渲染、失败门禁、秘密脱敏和已初始化健康分类，不运行真实 systemd 或 Windows。操作者验收须分别覆盖 Linux 重启、有意停止与崩溃、占用端口、Herdr 不可用、Tunnel 缺失、任务禁用/启用、所有者登录/重新登录、>72 小时生命周期、无可见控制台、电池/挂起/注销、未知发行版/用户和有意 WSL 关闭。独立检查 Bridge MCP、Herdr 和 Tunnel/ChatGPT。Work token 和运行的 Agent 终端属于进程/会话状态；这些检查都不构成恢复工作证明。

参考：[WSL 命令](https://learn.microsoft.com/windows/wsl/basic-commands)、[任务执行限制](https://learn.microsoft.com/windows/win32/taskschd/tasksettings-executiontimelimit)、[任务主体](https://learn.microsoft.com/powershell/module/scheduledtasks/new-scheduledtaskprincipal)。

单元策略清单遵循 systemd 有限的系统管理器查找及 drop-in/依赖规则；自定义查找根不受支持，不能猜测。参见 [systemd.unit](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html)。

官方任务契约：[禁用设置构造](https://learn.microsoft.com/powershell/module/scheduledtasks/new-scheduledtasksettingsset)、[LogonTrigger](https://learn.microsoft.com/windows/win32/taskschd/logontrigger)、[交互登录类型](https://learn.microsoft.com/windows/win32/api/taskschd/ne-taskschd-task_logon_type)。这些契约不能证明本助手已通过真实 Windows 验收。

<a id="tunnel-component-contract"></a>

## Tunnel 组件契约

此组件参考使用自己审核过的快照变量。不要在组合序列后再次运行它的安装序列，也不要在此伴随服务旁运行前台客户端。

<a id="two-linux-services-one-wsl-anchor"></a>

<a id="两个-linux-服务一个-wsl-驻留任务"></a>

<a id="two-linux-services-optional-windows-wsl-helper"></a>

### 两个 Linux 服务；可选 Windows WSL 助手

**原生 Ubuntu：**systemd 直接管理两个单元，Desktop 和 Server 都不需要 Windows 助手。**Windows + WSL2：**额外登录助手只负责 WSL 生命周期，细节如下。

服务为 `gpt-agent-bridge-tunnel.service`，与 `gpt-agent-bridge-autostart.service` 分开。两者必须在同一 Linux 发行版中明确启用。**在 Windows + WSL2 上**，已有当前所有者登录任务负责唤醒并保持该发行版运行，不需要额外 Windows 任务。只有 systemd 服务不能保持 WSL 运行。这是所有者登录之后的设计，不保证登录前或 Windows 睡眠期间可用。

Tunnel 单元有 `After=Bridge network-online.target`，但**没有 Wants、Requires 或 Herdr 依赖**。启动它不会启动 Bridge。所有者侧启动器最多等待 60 秒，要求已初始化 MCP，以及精确 Bridge 身份和 **`ok` 为布尔 true** 的有效 `bridge_health` 结果；允许 `herdr.status=unavailable`。连接或 initialize 超时属于暂时问题：服务在十秒后重试，不设置短时启动突发截止限制。畸形响应、工具错误、身份错误、`ok` 缺失/为假/非布尔或本地配置无效，会以退出码 78 拒绝。启动器持有的锁在子进程生命周期内防止第二个伴随实例。

只接受经验证的 OpenAI `tunnel-client` **v0.0.16**。客户端自行处理控制面轮询重试，进程监督处理意外客户端退出。`network-online.target`、systemd `active` 和客户端 `/readyz` 不证明远程授权或 ChatGPT 可用。尤其是 v0.0.16 在 MCP 探测超时后仍可能报告启动 ready。Status 明确报告这些限制，不检查远程账户状态。

<a id="security-and-stored-files"></a>

### 安全与存储文件

root 所有的安装包含加载器、单元和非秘密清单：

| 文件 | 所有者与权限 | 用途 |
| --- | --- | --- |
| `/usr/local/lib/gpt-agent-bridge-tunnel-autostart/runner.py` | root，0644 | 非 root 运行时；检查 root 来源 |
| `/usr/local/lib/gpt-agent-bridge-tunnel-autostart/installation.json` | root，0644 | 精确所有者、客户端哈希/版本及安装哈希 |
| `/etc/systemd/system/gpt-agent-bridge-tunnel.service` | root，0644 | 不内嵌秘密 |
| `/var/lib/gpt-agent-bridge-tunnel-autostart/credentials.json` | 选定非 root 所有者，0600 | 用户自己的 Tunnel ID 和运行时密钥 |
| `/var/lib/gpt-agent-bridge-tunnel-autostart/runtime.lock` | 选定非 root 所有者，0600 | 伴随实例锁 |

私有状态目录为 0700。单元在 `/run/gpt-agent-bridge-tunnel-autostart` 下另建 0700 运行时目录；选定私有 Unix 健康套接字位于其中。绝不假设 TCP 8080 空闲而使用它。已有套接字或路径会被拒绝。Systemd 停止时移除其运行时目录；外部遗留或未管理对象需要操作者审核，不会自动删除。

已有 Bridge token 仅留在 Bridge 受保护设置中。启动器在内存中构造回环 `/mcp/<token>` URL，经 stdin 传给 MCP 就绪子进程，并通过最小环境传给 Tunnel。Tunnel ID/密钥绝不作为命令行参数。子进程 argv 仅包含经验证的绝对客户端路径和 `run`。

环境仅包含 HOME、PATH、LANG、CONTROL_PLANE_TUNNEL_ID、CONTROL_PLANE_API_KEY、MCP_SERVER_URL、HEALTH_UNIX_SOCKET 和 MCP_CONNECTION_MAX_TTL。没有 OPENAI_API_KEY 回退，也不继承 profile、代理、证书、调试或 shell 环境。需要代理/CA/mTLS 配置的企业部署须另行审核扩展；不要为了适配这条最小路线而丢弃已有部署设置。

原始 **Tunnel 客户端** stdout/stderr 被丢弃，并禁用 core dump。配套 runner 只把固定、非秘密的结果/原因码写入 system journal，其 stderr 被丢弃。控制器错误同样使用固定原因码。所有者侧健康读取器丢弃原始就绪原因。通过环境传递**不能**对 root 或同一 Linux 账户隐藏凭据。未来在受支持 systemd 中集成 LoadCredential 可改进交付，但仍须适配此客户端的运行时环境接口。

<a id="prepare-a-reviewed-installation-operator-actions-only"></a>

### 准备经审核的安装（仅操作者行动）

安装、启用和启动各自需要明确操作者授权。合成测试不会对真实服务安装执行这些命令。

先按[手动指南的包验证](QUICKSTART.zh-CN.md#3-obtain-and-verify-the-pinned-linux-client) 取得并验证精确官方 v0.0.16 包。管理员必须将审核过的完整包副本放到新的 root 所有目录，例如 `/opt/openai-tunnel-client-v0.0.16`。保留用户所有的原始包及任何运行中的 Tunnel。选定二进制的所有上级目录必须由 root 拥有，且不允许组/其他用户写入；拒绝符号链接、硬链接、setuid/setgid 位和文件 capabilities。CLI 要求独立审核的二进制 SHA256，不接受“哈希任意本地文件就证明官方来源”的说法。此安装器不下载。版本观察只以非 root 所有者运行。

此为**单组件替代路线**：所有者在 **Ubuntu 终端 / WSL Ubuntu Bash** 进入审核过的 Bridge 源码根目录，保持该 shell 供后续变量使用。替换示例客户端路径及二进制摘要。下一条只做计划；预期所有者、客户端和摘要正确，被拒绝就停：

```bash
# gate: component-tunnel-plan
set -euo pipefail
owner_name="$(id -un)" || exit 1
client_binary=/opt/openai-tunnel-client-v0.0.16/tunnel-client
# Set this to the binary digest from your verified package review, not a token.
client_sha256=REPLACE_WITH_REVIEWED_BINARY_SHA256
/usr/bin/python3 -I -B scripts/install-bridge-tunnel-autostart.py plan \
  --user "$owner_name" --client "$client_binary" \
  --client-sha256 "$client_sha256" --health-socket health.sock --ttl 10m || exit 1
```

Plan 哈希普通的非秘密二进制字节，但不执行它，不读凭据，不联系服务/网络，不写文件。它把 Bridge 适配器和非 root 版本观察标为未验证。

绝不以 root 运行用户所有的检出或其 venv。特权管理时，把两个已审核资源复制到**新的** root 所有 0700 审核目录。在同一 Bash 会话中，将每个完整块作为独立阶段运行，检查结果后再继续。任何命令失败都应停止并审查未知影响；不要继续后续块或盲目重试。绝不绕过失败的 mkdir 只挑复制命令执行。控制器要求自身及旁边的 `service.template` 均由 root 拥有、权限 0600，且上级路径可信、不可写：

```bash
# gate: component-tunnel-snapshot
set -euo pipefail
# mkdir refuses an existing review directory; do not retry blindly.
sudo mkdir -m 0700 /root/gpt-agent-bridge-tunnel-review-v1 || exit 1
sudo /usr/bin/install -m 0600 scripts/install-bridge-tunnel-autostart.py \
  /root/gpt-agent-bridge-tunnel-review-v1/installer.py || exit 1
sudo /usr/bin/install -m 0600 systemd/gpt-agent-bridge-tunnel.service.template \
  /root/gpt-agent-bridge-tunnel-review-v1/service.template || exit 1
sudo /usr/bin/cmp -- scripts/install-bridge-tunnel-autostart.py \
  /root/gpt-agent-bridge-tunnel-review-v1/installer.py || exit 1
sudo /usr/bin/cmp -- systemd/gpt-agent-bridge-tunnel.service.template \
  /root/gpt-agent-bridge-tunnel-review-v1/service.template || exit 1
```

执行特权代码前，将这些精确快照字节与独立审核候选及记录哈希比较。复制/比较成功不是安装授权。安装是独立阶段；plan 中的非秘密 owner/client/hash 变量仍须已设置：

```bash
# gate: component-tunnel-install
set -euo pipefail
sudo /usr/bin/python3 -I -B /root/gpt-agent-bridge-tunnel-review-v1/installer.py install \
  --user "$owner_name" --client "$client_binary" --client-sha256 "$client_sha256" \
  --health-socket health.sock --ttl 10m || exit 1
```

Install 在暂存前枚举管理器 UnitPath 及支持的持久/运行时/vendor 路径。不存在的可选 systemd 目录会跳过；已有符号链接、无权限访问的路径和真实冲突仍会拒绝。拒绝别名、过期 target wants/requires 链接、精确/dash-prefix/按类型继承的 drop-in、不安全上级路径和已有路径。未发布的 `service.d` 配置和未知发现条件都是 HOLD。它使用 systemd-analyze 验证暂存单元，不替换已有目标地发布新文件，重新加载单元发现，再检查 disabled 和 inactive。它不启用或启动任何内容。修改结果不确定时，已发布文件保留作为证据；清理只删除已证明归属的暂存对象。不要自动重试或删除未知部分状态。

<a id="provision-privately-then-explicitly-enable-and-start"></a>

### 私密配置，再明确启用和启动

用户必须已拥有自己的 Tunnel ID（`tunnel_` 加精确 32 个小写 ASCII 字母/数字）、运行时 API 密钥和合格的账户/工作区权限。在 **Ubuntu 终端 / WSL Ubuntu Bash** 中，以配置的非 root 所有者使用私密交互式终端，不用 sudo。应出现两个隐藏提示并成功配置；提示缺失或被拒绝就停。这会在本地保存凭据，但不验证云端权限、不启动 Tunnel：

```bash
# gate: component-tunnel-configure
set -euo pipefail
/usr/bin/python3 -I -B /usr/local/lib/gpt-agent-bridge-tunnel-autostart/runner.py configure || exit 1
```

两项输入均隐藏。非 TTY 输入和 getpass 回退会被拒绝。不裁剪输入或推断身份。可选的 `configure
--credentials-file /absolute/private/input.json` 读取 0700 目录内、所有者拥有的 0600 普通文件，文件恰好含 `tunnel_id` 和 `runtime_api_key`。该输入由用户私密创建，绝不放在 Git 检出中。本地运行时密钥限制为 16–4096 个 ASCII 字母/数字/下划线/连字符；这是输入安全上限，不证明提供方有效性。Configure 不覆盖凭据、不启动服务、不注册任何内容，也不验证远程权限。

只有单独安装的 Bridge 契约已验证，且任何旧 Tunnel 管理器已由其所有者明确处理之后：

```bash
# gate: component-tunnel-enable
set -euo pipefail
sudo /usr/bin/python3 -I -B /root/gpt-agent-bridge-tunnel-review-v1/installer.py enable || exit 1
```

检查启用结果。立即启动是另一项获准阶段：

```bash
# gate: component-tunnel-start
set -euo pipefail
# Starting now is a separate explicit action, not implied by enabling at boot.
sudo /usr/bin/python3 -I -B /root/gpt-agent-bridge-tunnel-review-v1/installer.py start || exit 1
```

在**同一 Linux 终端**单独观察。检查进程、开机、启动状态分类；未知/待定就检查，不是重发 start。Status 不是连接验收测试：

```bash
# gate: component-tunnel-status
set -euo pipefail
/usr/bin/python3 -I -B /usr/local/lib/gpt-agent-bridge-tunnel-autostart/runner.py status || exit 1
```

Bridge 开机启用仍是其审核过安装器中的独立操作。两个 Linux 单元都启用后，原生 Ubuntu 的设计目标是随开机启动、不需要前台终端。**仅 Windows**还可选择 WSL 所有者驻留任务，让发行版在登录后被唤醒并保持运行。这仍需真实 Linux 和 WSL 重启验收。委派前手动检查 Herdr 可用性和 Agent 就绪。

`stop`、`disable` 和 `uninstall` 是通过同一审核过特权快照执行的明确行动。Stop 只影响此 Tunnel 单元；disable 只影响其开机激活。Uninstall 要求 disabled/inactive 和精确已知代码清单。捕获的原始 inode 保持打开；逐个对象复查身份、所有者、权限、链接数和精确字节，移入私有隔离区，再在 unlink 前复查。替换对象和未知隔离区内容保留供操作者审核。它保留私密凭据/锁/状态，不吊销密钥，也不修改 App。保留状态有意阻止盲目全新重装。

<a id="bridge-contract-adapter-and-remaining-acceptance"></a>

### Bridge 契约适配器与剩余验收

适配器要求 root 所有、0644 的 `/usr/local/lib/gpt-agent-bridge-autostart/installation.json`，非秘密字段恰好为 `format`、`plan`、`unit_sha256` 和 `runner_sha256`；以及位于 0700 私有父目录下、所选所有者拥有、0600 的 `/var/lib/gpt-agent-bridge-autostart/settings.json`。设置必须等于完整清单 plan，仅额外包含 `token`。plan 的精确字段为 format、user、uid、gid、home、repo、workspace、herdr_bin、port 和 entrypoint。匹配的所有者字段含 user、uid、gid、home 和 `entrypoint=module`；设置还要求整数 port、绝对 repo 和 32–256 字符的路径 token。清单和 plan 必须使用独立验证的 Bridge 格式标识 `gpt-agent-bridge-autostart-v1`，已直接针对 SHA256 为 `17ef82d1f6ac15fd91cc5061f187857391117bb06946cf92f30cc61e4668eb12` 的冻结 Bridge 安装器验证。未知格式会被拒绝；适配器绝不从私有设置文件推断格式。**读取 token 之前**先验证已知 root 所有的 Bridge runner/unit 哈希。适配器为已初始化 MCP 子进程推导 `repo/.venv/bin/python`。只有这个 venv 解释器接缝允许解析后的 Python 符号链接；会检查其上级路径和目标。每次调用解释器前，root/所选所有者的元数据遍历重新验证整个源码/venv 代码树，包括 site-packages 和依赖 `.pth` 文件。它拒绝组/其他用户可写或外部所有条目、不安全文件/硬链接，以及除已检查 Python 别名外的外部符号链接。上限为 30,000 项，扫描预算十秒。顶层 `.git`、`.principal` 和实际 `.app.json` 是排除的非代码状态，从不打开；指向这些状态的符号链接会被拒绝。初始化文件必须仅含惰性的字符串/文档字符串语句。隔离的非 root find_spec 必须在不导入 server 的情况下解析到此检出的 src 包。不修改源码或 Bridge 设置。

源码标记和写入结构通过跨组件合成测试检查。测试调用实际冻结安装器，模拟宿主/特权/服务操作，将所有输出导向临时沙盒，再将生成记录、设置、runner 和 unit 字节送入实际 Tunnel 适配器。它验证精确 plan、记录哈希及 token 不变，不持久保存后端 URL。此源码树默认使用自身经过哈希验证的 Bridge 控制器，无需选择加入，也不以此跳过测试。`BRIDGE_FROZEN_INSTALLER_SOURCE` 可选定具有同一固定哈希的明确源码。组合回归也使用两个不可变生产模板；宿主操作和所有权仍为合成，实际发布/适配器/策略检查则真正运行。这**不**构成真实 Bridge/真实 Tunnel 验收。在依赖部署安装之前，仍须独立审核和目标主机验收。不匹配就是 HOLD，不是自行发明 token、扩大权限、猜测替代路径或把秘密复制到别处的许可。

默认 TTL 为该标签客户端的 10 分钟。`--ttl 60m` 是明确替代值；两者都不会使连接无限或恢复 Work。不调用现有 YAML TTL 暂存脚本。轮询可在网络故障后恢复；凭据被吊销时需要用户有意处理。

全新安装只使用新状态。已有用户必须保留精确绑定、已有 Bridge token 和所需私有配置。不实现自动 profile 导入、运行进程检查、停止、接管、密钥创建、重新授权或 App 安装。运行时锁和本地 unit/socket 检查不能证明其他未管理或远程客户端没有使用相同 Tunnel 身份。

合成测试检查受保护的生命周期行动、不覆盖/身份竞态、暂存 SIGHUP/TERM 行为、隐藏输入配置、精确环境、Bridge 初始化及 Herdr 不可用情况。不证明真实 systemd 兼容性、包资源完整性、中断请求恢复、Windows 重启/登录行为、Platform 授权或 ChatGPT 连接验收。这些是在部署前需要独立审核且明确授权的隔离验收门禁。

<a id="official-references"></a>

### 官方参考

- [OpenAI Secure MCP Tunnels](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [v0.0.16 systemd 部署模式](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/deployment/systemd-vm.md)
- [v0.0.16 环境配置与 TTL](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/runtimeconfig/config.go)
- [v0.0.16 轮询重试](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/controlplane/internal/poller.go)
- [v0.0.16 就绪语义](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/runtimehealth/health.go)
- [Microsoft WSL systemd 与实例生命周期](https://learn.microsoft.com/en-us/windows/wsl/systemd)
