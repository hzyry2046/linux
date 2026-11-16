<!-- SPDX-License-Identifier: GPL-2.0-only -->
# CCISM 后置握手与 SCP 客户端

2026-11-16，AI 辅助实现。默认关闭的 CCISM core 已接入唯一 CCIF2 桥、
普通 system q0 TX，以及独立有界 session worker/timer。MD platform 在启用
`CONFIG_OP6893_CCCI_CCISM` 后构造 dormant bridge，预留资源并提供只读状态。
**仍无 arm/start 调用者、基带 CPU 释放入口或 FS/RPC/NVRAM 服务。本轮未操作
设备，未新增真实 CCISM、HS1/HS2 或蜂窝支持验收。**

本轮验证见 [bridge evidence](evidence/modem-ccism-bridge-validation.json)，
前一轮 core/client 验证见 [core evidence](evidence/modem-ccism-validation.json)。

## 修正启动顺序

依据本机 Android 4.19 的 `eccci/fsm/ccci_fsm_scp.c`、`port/port_proxy.c`
和可用6.6的 `eccci/fsm/ccci_fsm_scp_c.c`、`port/port_sysmsg.c`：

1. 放行 MD 前先建立实际 SCP hardware READY、同代际客户端、桥资源归属和
   FS/RPC/NVRAM 服务。此时没有 CCISM RBREADY，不等待它作为 CPU 释放条件。
2. MD 完成 HS2、owner 开放系统端口后，持有 CCIF2 时钟并执行 CCCI SMC13
   SCP_CLK_SET_DONE，再向 MD system channel3/q0 发 INIT `0x119`。
3. MD system channel2/q0 返回 ACK `0x11a` 后，清零完整已验证的 ID16
   CCISM_SCP 子区，向 SCP APCCCI 发 OP_SHM_INIT=2/data=**AP物理地址**。
4. 同一 SCP 代际返回 RBREADY，AP 向 MD 发 DONE `0x11b`。
5. 按可用6.6路径，MD 返回 DONE 后再向 SCP 发 OP_MD_STATE=1/data=2，
   完成 CCISM 协议里程碑。它不是运营商注册、AT、数据面或 radio READY。

因此，早期 TODO 中把“CCISM 完成”整体放在首次释放 MD CPU 之前的要求有
循环依赖，应改为“资源/服务和 SCP READY 预备完成，HS2 后再完成 CCISM”。
4.19在RBREADY时已发MD READY，6.6将它放在MD DONE回调；本实现采用已经在
本机修复可用的6.6顺序，实际固件对该序列的响应仍须后续合并上机验证。

系统端口有独立的 CCCI 消息号。不能把 `0x119/11a/11b` 当成 SCP op，
不能把 hardware READY 的 channel9/22 当成 APCCCI RBREADY，也不能把
AP/MD 两个地址视图混用。正常控制环来源和16B头由既有 decoder 重新校验。

## 协议 core

`ccci-ccism.{c,h}` 采用可序列化、可睡眠的回调，覆盖完整协议顺序：

`IDLE → ARMED → WAIT_MD_ACK → WAIT_RBREADY → WAIT_MD_DONE → RUNNING`

`arm` 只验证 plan 和 leased SCP generation/READY，不发包、不清内存、
不执行 SMC 或打开时钟；MD owner 必须在真实 HS2 后调用 `md_ready`。
ID16须在NC bank内、至少32KiB、可映射且AP/MD转换匹配；AP地址/完整跨度
必须能由u32表达。任一错误清空plan输出，不截断arm64物理地址。

- ACK只接受精确16B普通q0/channel2消息，不能提前、重复或错端口。
- 只在有效ACK后清整个plan范围，再发SHM_INIT；清零失败不通知SCP。
- RBREADY仅在WAIT_RBREADY接受，必须来自当前generation；SCP重启BOOTING、
  未请求的STOP、重复RBREADY或MD DONE顺序错误都锁存失败。
- 三个等待阶段各60秒，时间倒退/溢出失败。core仍由caller驱动tick；新增session在arm后由独立worker处理事件，并以
  最长1秒间隔及剩余deadline驱动超时。未arm时不调度工作。
- 每个前向副作用失败即停止后续动作，不回滚或自动重试；保留已触及桥资源，
  等待owner诊断与实际停止。不会在失败时猜测SCP或MD已停止。
- `stop(md_stopped=false)` 返回EBUSY，零清理。owner确认MD CPU/DMA停止后，
  才能发MD-invalid并等待当前代际的SCP STOP；收到后才执行bridge_off。
  后者必须先ACK两个CCIF2视图，再关钟。STOP最多尝试一次，3秒超时保留桥。
  原始error和cleanup_error分开保留；正常完成后的迟到事件返回ESHUTDOWN。

回调已由下述Linux bridge实现，但没有上层arm或MD启动调用者。后端经过
实际C离线测试及ARM64编译；没有真实固件协议验收。

## 真实 SCP 客户端与锁

`ccci-scp-client.c` 通过bridge consumer的 `mediatek,scp` phandle查找既有
boot-lifetime SCP provider，取得device引用和managed device link；create
只分配和建立生命周期关联，没有MMIO/SMC/awake或SCP启动。当前默认disabled的MD platform节点已添加
该属性及CCIF2资源。启用CCISM构建时构造bridge/client，仍无lease/start caller；
device-link/OF构造路径经过ARM64编译，未作真机验收。

`acquire` 需要实际active/READY、非零generation、无既有fault/cleanup错误。
每代仅允许一个client和一次lease，拒绝已有lease及继承的RBREADY，不能用
重绑对象制造“新一代”。原本的sysfs STOP及独立MD-invalid测试在lease期间
返回EBUSY；真实接收/awake/传输故障仍可撤销READY并异步停止SCP。

`send` 只接受codec已经支持的MD1 MD_STATE/SHM_INIT消息，先验证再取awake，
使用相同owner/awake实例、确切channel3/mailbox1/two words发送，最后配对put。
不重复映射mailbox或另建awake引用计数。BUSY零写，SET消费有界等待，不重试
或从AP清SCP接收位；完成只证明传输消费，不代表应用层ACK。原MD-invalid
测试继续调用同一后端的兼容wrapper。

owner收到严格校验的channel7状态后，向client提供generation/state/error
标量通知。首次错误通知一次并撤销READY；client transport失败也走既有fault
work，等当前锁释放后才join RX/双核SET。手动STOP保护的EBUSY不触发此清理，
真实awake握手的EBUSY仍必须清理，测试分别覆盖。

所有client API都是可睡眠的，锁顺序为 runtime.control→owner.lock。notify
在owner.lock下执行，**只能向consumer独立队列排标量事件，不能调用client
API、CCISM FSM或取得MD生命周期锁**。否则会与发送或STOP形成等待环。
owner先停止MD，再release关闭通知入口，最后join已排队consumer工作，才能
释放context；device link不替代该停止契约。Linux桥通过下述有界事件
队列/worker/timer接收通知；故障关闭普通CCIF TX/RX并保留资源。实际MD停止原语
仍待实现，不能直接在notify里发送IPI或把RX关闭当成MD CPU/DMA已经停止。

## 离线验证和接续

- `tools/test_modem_ccism.py` 编译实际protocol/CCISM C并包含既有runtime/
  controller/RX完整sanitizer测试；覆盖正常顺序、六处前向副作用失败、所有等待
  阶段超时、错来源/重复/重启/代际、STOP拒绝/超时/关桥失败和8类plan错误。
- `tools/test_modem_scp_client.py` 编译抽取的实际client及runtime生命周期/
  consumer；覆盖实际READY门槛、单lease、共享awake、STOP保护、同代通知、
  错代际、detach后禁止回调、五类硬件失败和故障清理。没有模拟真实线程竞争。
- `tools/test_modem_scp_runtime.py` 覆盖实际MMIO MD-invalid/MD-ready/SHM_INIT
  与codec，验证两字内容、屏障、SET、BUSY/超时/错误请求零I/O；没有复用
  peer私有数据或固件binary。

确定性模型不证明SMP、device link实际拆卸顺序、CCIF2时钟/SMC效果或固件状态。

## Linux bridge、系统端口与异步 session

`ccci-ccism-bridge.{c,h}` 是现有MD platform的唯一子owner，精确预留AP
`0x1023c000/0x1000`、MD `0x1023d000/0x1000`，以及解析所得ID16。要求ID16
AP地址和size整页对齐，独占WC映射，不扩大到相邻runtime/SMEM用户。constructor
只建立映射、时钟引用和SCP device link，不读写CCIF2、不清SMEM、不发SMC、
不取得SCP lease、不启动工作或处理器。

`arm`取得一次真实SCP lease和generation，随后arm session。acquire→arm窗口的
provider通知不会丢失：预arm通知锁存错误，arm前后检查，禁止遗失故障后继续启动。
未来调用者必须持parent生命周期锁，确认MD供电/时钟与CPU/DMA停止；本轮没有
调用者。只在controller已验证并接受的HS2回调中排MD_READY，不能由状态字符串
或任意system包触发。HS2先入队，随后同一RX工作流排ACK/DONE，避免回调重入。
其余端口必须由未来服务dispatcher路由，bridge本身返回EOPNOTSUPP。

`ccci-ccif.c`新增普通q0/channel3、精确16B的INIT/DONE发送：独立TX mutex和
停止门，15bit sequence/assert，BUSY或满环在发布前拒绝；partial publication
不重试并锁存fault。先完成WC ring publication，再BUSY/TCHNUM；STOP先关闭
发送门并等待在途sender，再quiesce controller/RX。发送不取controller/MD锁。

**CCIF2时钟是继承语义，不是已验证的硬件gate。** Android4.19与本机可用6.6
均使用dummy ops+IGNORE_UNUSED，未切换bank4。主线新增的两个1:1 clock alias
保持到observed AXI parent的逻辑引用，不写`0xc0/0xc4/0xc8`，不证明实际
bit16/17或桥时钟可控。当前头文件沿用4.19索引68/69；6.6同名宏为72/73，
不能跨树硬抄编号。进入协议时取得引用，然后只发一次CCCI SMC13，其他参数全零。
vendor仅打印a0，没有完整返回契约；本实现保守地仅接受a0=0，-1视为不支持，
其他非零失败并保留引用。此策略仍须真机验证，不声称已证明固件返回语义。

`ccci-ccism-session.{c,h}`在32槽固定队列复制标量和16B包，由一个delayed_work
在独立mutex下串行驱动core/硬件回调。provider回调只持队列spinlock复制，不调
client/FSM、不取MD或session mutex。溢出锁存错误、废弃不完整历史并关闭MD
收发，不自动重试。worker从事件处理后的实际单调时间驱动60秒阶段超时和3秒
STOP超时；首次故障调用普通CCIF abort，保留MD域和桥引用等待明确停止。

父驱动prepare、off、shutdown先检查bridge offline：任何已arm且未STOPPED的
会话都返回EBUSY，不能用FAILED或RX停止代替MD停机证明。未来真实停止流程是：
持parent锁确认MD CPU/DMA停止→session STOP→发MD-invalid→同代SCP STOP→
两个CCIF2视图ACK+0x14写0xffff→屏障→释放逻辑时钟引用→quiesce session→
release SCP lease→普通CCIF停止/复位→MD断电。STOP等待异步完成，不在父锁下
等待需要父锁的工作。重复STOP不清空已排队的STOP回复、不延长deadline。
未完成、超时或provider失败均保留资源并阻止断电。当前没有MD CPU停止原语，
因此尚不能把这套生命周期称为真机热停止支持。

session停止会丢弃尚未执行的前向事件，避免MD已停止后队列里的MD_READY才打开
bridge。quiesce在桥引用未清除时拒绝销毁，继续保留STOP接收。当前是built-in、
suppress_bind_attrs、无arm caller的boot-lifetime owner；devres仅用于dormant
probe失败回滚，顺序为client release→session destroy→clocks/maps释放。
未来增加remove/unbind必须先实现真实stop/join，WARN_ON不能阻止devres释放，
不能照搬现有失败probe路径处理活跃会话。

## 本轮验证与接续

- `test_modem_ccif_system_tx.py`：实际sender/ring的ASan/UBSan，BUSY/满环、
  序号回绕、所有ring失败位置和发布后错误；pthread sender/STOP竞争。
- `test_modem_ccism_session.py`：实际session/core及既有handshake/RX，复制后包
  生命周期、队列溢出、预arm故障竞态、代际/期限/STOP、重复STOP回复保留。
- `test_modem_ccism_bridge.py`：实际完整bridge、plan/protocol，假的底层client/
  session/clock/SMC；13类constructor失败无硬件I/O、精确ID16、SMC13参数、
  双ACK和屏障顺序、lease保留、offline拒绝、路由及故障通知。
- 原有CCIF/core/client/platform回归及启用/恢复原配置的ARM64构建。host模型不
  证明真实SMP调度、SMC效果、CCIF2可访问性或固件响应；未打包/刷写测试镜像。

下一组准备FS/RPC/NVRAM私有工作副本、端口dispatcher和真实能力表，再连接唯一
上层启动/停止owner。必须补足MD CPU/DMA停止证明后才能启用真实释放入口。
合并首次CPU释放、HS1/runtime/HS2、CCISM与停止测试，不为单纯资源预留刷机。
