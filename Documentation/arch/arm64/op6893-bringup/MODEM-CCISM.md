<!-- SPDX-License-Identifier: GPL-2.0-only -->
# CCISM 后置握手与 SCP 客户端

2026-11-16，AI 辅助实现。本轮完成默认关闭的 CCISM 协议状态机，以及现有
常驻 SCP 的真实 APCCCI 客户端接口。实际 C sanitizer 和 ARM64 构建验证见
[evidence/modem-ccism-validation.json](evidence/modem-ccism-validation.json)。
**未连接最终 MD owner 启动路径，未新增 CCIF2 映射/时钟 owner、系统端口 TX
或 CCISM 内存映射，也没有上机、刷写、放行 MD CPU 或真实 CCISM 验收。**

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
- 三个等待阶段各60秒，时间倒退/溢出失败。caller必须定期调用tick并在事件
  到达时处理；core本身没有Linux timer/work，不能宣称有已运行的超时worker。
- 每个前向副作用失败即停止后续动作，不回滚或自动重试；保留已触及桥资源，
  等待owner诊断与实际停止。不会在失败时猜测SCP或MD已停止。
- `stop(md_stopped=false)` 返回EBUSY，零清理。owner确认MD CPU/DMA停止后，
  才能发MD-invalid并等待当前代际的SCP STOP；收到后才执行bridge_off。
  后者必须先ACK两个CCIF2视图，再关钟。STOP最多尝试一次，3秒超时保留桥。
  原始error和cleanup_error分开保留；正常完成后的迟到事件返回ESHUTDOWN。

回调所需的CCIF2 clocks/SMC13、精确WC clear和系统端口TX仍待Linux owner实现，
core当前没有硬件调用者或自动开始入口。不能把模型中的callback当成已经
接好硬件后端。SCP transport回调可使用下述客户端API。

## 真实 SCP 客户端与锁

`ccci-scp-client.c` 通过未来consumer的 `mediatek,scp` phandle查找既有
boot-lifetime SCP provider，取得device引用和managed device link；create
只分配和建立生命周期关联，没有MMIO/SMC/awake或SCP启动。当前DT没有添加
该属性，也没有构造调用者；device-link/OF构造路径经过ARM64编译，未作真机验收。

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
释放context；device link不替代该停止契约。后续Linux桥必须实现有界事件
队列/worker/timer，并把SCP错误传到MD停止流程，不能直接在notify里发送IPI。

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
下一组实现唯一CCIF2 owner、SMEM映射和system-port TX/RX，将标量队列/worker/
定时器连接到此core和SCP client；同时准备真实能力表及FS/RPC/NVRAM服务。
首次MD释放前验证这些准备条件，HS2后执行CCISM。合并通信测试，不为尚无
完整对端的callback core单独刷机。
