# 多项目完成通知（0.4.1 候选）

一次 Bridge 和扩展安装支持最多 32 个明确授权的本地项目。使用发行目录的 `./prepare` 完成软件准备，之后 `./prepare project` 选择现有 Git 根目录；程序通过受保护的注册接口取得并核对映射，生成标识、配置和独立 Binding，无需手改 JSON。软件安装不要求先选项目。

打开明确选定的普通 ChatGPT Web / Project Chat，在 popup 选择本地项目，勾选自动通知授权并点“绑定当前 Chat 并启用”。一个本地项目只选一个目的地，不广播、不选最近标签。一个 Web Project/Chat 可以关联多个本地项目；标题、slug、会话 metadata 都不是映射。完整 URL（包括 Project 前缀）是目标身份，同一完整路径只能有一个普通非隐私标签页。首次绑定跳过之前已完成的事件；先绑定再派工。

每个项目/根有独立持久命名空间、游标、队列、意图与历史；同一 Chat 的实际发送操作串行，不同 Chat 可独立推进。项目 A 的状态读取异常/悬挂、页面忙、报告读失败或 unknown 不阻塞 B 的独立目标。共享配置或总存储故障仍可能影响全体。不同项目不合并，即使它们选择同一 Chat；同一项目同一 Chat 已就绪且未尝试的批次可合成短提醒。每次 delegate 的固定成员关系不变，不等待未完成批次，不合并报告正文。新 v4 正文带 `project_ref` 和完整原 Work 编号；旧 v1-v3 正文原样用于精确收据核对。

feed 内暂时读失败仍阻塞该项目后续序号；已入队候选可以跳过暂时不可读项。发送意图先落盘；worker/回执丢失与不明提交不重发。固定组在成功、失效、取消和抛错路径整体持久化。安全忙态回退须证明同一页面、绑定、当前编辑器和精确自有文字，且无外部 click/submit 干扰；宿主替换或用户编辑则保留 unknown，不能靠清字重投。

Bridge 报告按既有 epoch/容量/保留合同处理。关闭项目、失效、换 Chat 不删除历史；旧未解决意图会拒绝换目的地。删掉再加同一 ref/root 不重解释历史；同一 ref 换根在扩展保留旧命名空间并拒发，需另一个明确注册身份。离线仍可查看和关闭已有项目，不能凭缓存授权新发送。没有已处理确认机制；任意 report 读取不等于 Principal 已处理完。

准备入口生成私有 `~/.config/gpt-agent-bridge/browser-notifications.json`（v2、0600）和安装目录中的 `connection.js`。两者共享独立只读 feed capability，不是 MCP path token 或 Tunnel runtime key；源码 connection 保持 null。新增项目热读取配置，不必重启服务。服务目录仅公开已经授权且仍与注册根匹配的条目。网络固定 loopback 127.0.0.1:8765，manifest CSP/权限、连接配置和后端一致。

新安装 manifest key 固定 ID。旧安装须显式提供原加载目录；准备入口保留原 key/无 key 的路径身份、原秘密，并备份旧代码。安装准备器不操作浏览器存储。新 worker 将原键/正文原样导入扩展 IndexedDB，保留原 chrome.storage.local 记录作为迁移来源。受保护旧配置必须提供 ref+root+scope；仅有 ref 时旧历史进入不可发送隔离，状态查看/停用仍可用。先核实旧根身份并重新运行已授权更新，再明确绑定；不能拿同 ref 的新根继承旧 Chat 授权。版本不得借卸载、换加载路径或清存储绕过未知意图。若旧文件权限不安全或代码已被未知修改，停止并报告，不能默认覆盖。更新后 Chrome 本人确认 reload；源码候选测试不证明现有浏览器已更新。

持久状态用原生 IndexedDB 事务比较旧值与 revision 后提交，防止旧实例覆盖已确认变更；chrome.storage 的单向迁移见证会在事务库缺失时拒绝回退到旧备份。原生 Web Locks 覆盖每项目完整操作与同目标发送，跨 worker 实例共享。停用要等该项目正在执行的操作完成后才确认；未知正在提交的消息不能被停用“撤销”。worker 终止后锁释放，未完成事务按原生数据库语义完成或中止；已落盘 unknown 仍不重发。无 API 时拒发，不用定时抢锁或偷锁。该机制经事务模拟器验证，未在本轮真实 Chrome 中制造重叠 worker。
只读目录发现不占永久历史名额；32 是同时注册上限，累计历史不再冻结已绑定项目。未知历史不因容量被清理；真正存储配额耗尽会明确写入失败。
一次性合成诊断仅支持旧 `gpt-agent-bridge` 项目；其他项目在分配意图前明确拒绝，正常通知不受影响。已明确授权的延迟诊断按原 scope alarm 路由，重复回调不重发。

MV3 alarms 每分钟唤醒 worker；无需 Chrome MCP 或 Codex 常驻。Principal 读完整报告仍需 Bridge MCP。Chrome MCP 只是开发观察工具。页面忙态与回执是有限 DOM 观察，不是权威回合结束或服务端事务确认。当前英文 DOM 以外、真实工具等待、新版后台门槛、宿主节点替换/外部提交的真人时序，仍需实际环境验收；模拟用例不证明实机投递。未引入 Work Chat/API 替代路线。

在隔离发行候选先执行 `npm ci --ignore-scripts --prefix browser-extension`，再运行 `node --test browser-extension/tests/*.test.js`。fake-indexeddb 仅是锁文件固定的测试依赖，扩展运行只用浏览器原生 API。tests/fixtures/legacy-controls 和 repair/coalescing 用例保留旧行为与边界。详情见 [安装与人工检查](../docs/GETTING-STARTED.md)。

实现依据：[Chrome worker 生命周期](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle)、[Web Locks 的 bucket 范围与 worker 终止释放](https://w3c.github.io/web-locks/)、[IndexedDB 事务](https://w3c.github.io/IndexedDB/)。这些规范不等于本机真实投递验收。

0.4.2 的局部修复：无可信旧根证明的 legacy 行（含已有旧 index）持久保留重新授权要求；后来补 proof 不会恢复旧 enabled，只有成功的显式 enable 解除。事务存储初始化的 witness 读取、开建库和见证确认共用原生排他锁；数据库丢失仍拒绝重导入旧源。tick 与 arm/alarm/retry 在 route→project 锁内复核真实目的地，发生变化先释放再按新目标排队，连续变化则留到下次操作。以上是隔离回归验证，不代表真实 Chrome 生命周期或异常发送时序已验收。
