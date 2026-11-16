<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP 常驻接收、AP awake 与 APCCCI MD-invalid

2026-11-16，AI 辅助实现。承接已实测的[初始启动](MODEM-SCP-INITIAL-BOOT.md)，
仍使用 LK 已载入的 SCP 镜像；不写 TCM/firmware，不启动 MD。

## 一个 owner 与持续 CPU 消费

默认关闭 `CONFIG_OP6893_CCCI_SCP_RUNTIME`，owner DT 节点保持 disabled。
`pin=26m` 后向 `runtime` 写 `start`，执行同板双核SET、header/share核对、
旧消息丢弃、不可复用 generation、全RX准备及GPR1/2/core0 CLR。
与 `initial_boot=test`、`reset_assert` 共用一次启动门闩。

常驻消费者直接在 RX worker 内取得所有 CPU 事件，使用既有 owner mutex，
不轮询、不调用 receive_pop、不在回调里 STOP。READY0/1 经严格解码后唤醒
启动等待者；logger 只计数消费，不跟随固件指针或提供日志 DRAM 地址。
APCCCI channel7 只接收精确 MD1/state 消息，记录 BOOTING/RBREADY/STOP，
不把任意状态值作为 MD 已启动或 CCISM 已可用的证明。其他消息计数后擦除。

receive/解码故障立即撤销 ready、屏蔽并擦除 RX，通过另一 work item 取得
生命周期锁，锁外同步 IRQ/worker，然后双核SET、撤销generation、恢复GPR。
显式 `runtime=stop` 走同一清理。错误和清理错误独立记录；失败不重试启动。

## AP awake 与一次受限 TX

infracfg 通过已有 `ufs_infracfg` syscon phandle取得，基址0x10001000，
没有重新占用 syscon 页。vendor 的变量叫 `scpreg.scpsys`，但实际匹配的是
`mediatek,scpinfra` 节点，不能误取0x10006000的SPM节点。

有效 READY 后 start 自动执行一次 awake get/put；另写 `runtime=awake`
可执行配对复测。沿用4.19的 infracfg+0xb14 SET读应答、+0xb18清理协议，
不使用新6.6可选STATUS或新增SMC。握手失败就停止SCP。

写 `runtime=md-invalid` 最多成功一次：get awake，使用完整board表确认
channel3/mailbox1/offset0/irq0/two words，编码 MD1 OP_MD_STATE=1/data0，
写入两个32位word，屏障后 SET+0x100 bit0。发送前拒绝busy，发送后有界等待
该位清除，不清除SCP的接收位、不重试；最后put awake。位清除只证明传输
被消费，不冒充应用层应答。该命令没有 SHM_INIT、CCISM写入或MD电源操作。

`runtime_state` 报告active/ready/generation、事件分类、APCCCI状态、awake
引用/配对次数、TX完成及独立错误。boot_state保留共同启动记录。

## 验证与后续

实际 runtime生命周期/consumer、MD-invalid MMIO及编码的 ASan/UBSan 通过：
持续消费、真实READY门槛、共享一次门闩、STOP/GPR恢复、timeout/stale/畸形
事件/awake错误/延后故障清理、TX busy/超时/不重试与失败仍put。
实际receive/MMIO/queue/drain consumer扩展和既有awake握手测试通过。
启用 ARM64 构建通过，测试镜像 `e8509e81dbc3`，boot SHA256：
`503817de4c1ba7522e150c8367812d713ed8c94e0bc2072d70900a23318684c6`。
打包后仅删除 resource-hold.c 一个多余空行，无语义变化。

2026-11-16 实机验收：

- start 返回0，收到 channel22 READY1；保持 active/ready/generation=1 约49秒。
- 共消费3个事件：READY1、logger1、其他1；IRQ3、worker4、unexpected0，队列空。
  这是短时常驻验收，没有持续事件流或长期稳定性证明。
- 自动awake、显式awake、TX包围awake共3次配对，users0、fault0、cleanup_error0。
- MD-invalid 返回0，tx_completed1，SET位被固件清除；APCCCI回复事件0，
  因而没有应用层状态应答证明，不将默认apccci_state0解释为收到STOP。
- 显式STOP及重复STOP均返回0；双核raw均0x0000ff00、latched1、generation0，
  五路GIC masked，error/cleanup_error0。STOP后的awake_fault1、MMIO fault1
  是主动invalidate，表示不可再使用，并非本轮握手或接收失败。
- USB/Wi-Fi SSH均正常；LVTS五个温度可读；匹配GPU模块从tmpfs加载并probe。
  内核无BUG/WARNING/Oops/Call trace。cache内旧GPU模块没有替换。

设备保留本镜像，SCP已停止、MD未启动。非零旧pending丢弃及错误清理路径仍是
模型覆盖，不冒充实机触发。原始日志位于
`/data/src/mainline/mt6893-direct/evidence/scp-runtime/`，结构化结果见
[evidence/modem-scp-runtime-validation.json](evidence/modem-scp-runtime-validation.json)。

下一步以实际常驻/握手/状态结果为依据连接 MD/CCIF/CCISM；不提前宣称基带可用。


2026-11-16后续离线扩展：增加真实SCP client及有界MD_STATE/SHM_INIT传输，
单代单lease、同owner awake、状态/错误标量通知和手动STOP保护。旧MD-invalid
命令保留兼容wrapper，未作新的真机验收。后续CCISM consumer必须排队处理
通知，不能在SCP owner锁下重入发送，详见[CCISM与client](MODEM-CCISM.md)。
