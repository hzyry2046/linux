<!-- SPDX-License-Identifier: GPL-2.0-only -->
# 普通 CCIF 接收层与握手包解码

2026-11-16，AI 辅助实现。本轮完成 IRQ/worker、正常环分发、SRAM HS1 和
CCCI 控制头解码的离线接入。实际 C 的 ASan/UBSan、启用 ARM64 构建与
原有 CCIF/电源/SMEM 回归通过。**本节原始阶段尚无启动此接收层的 consumer caller，
未刷机、未启用真机 CCIF IRQ、未收到真实 HS1/HS2，MD CPU 未放行。**
设备仍运行 `8ec93b17bbb5`，MD1 已关电；上一轮初始化实测结论见
[普通 CCIF](MODEM-CCIF.md)。不能把本轮模型收包计入蜂窝支持。

## 同板协议依据

参考本机 Android 4.19 的 `drivers/misc/mediatek/eccci/`，以及已修复可用的
6.6 `kernel_device_modules-6.6/drivers/misc/mediatek/eccci/`：

- `hif/ccci_hif_ccif.c` 的 `md_ccif_isr[0]`、`md_ccif_launch_work`、
  `md_ccif_sram_rx_work`：低16位数据通知，bit7 是 CCB，bit15 是 SRAM。
  q7/q15 没有普通 RX 数据区，不得从空槽收包。
- 6.6 同文件的 `md_ccif_isr1`：异常 ACK 为 `snapshot & (0xffff << 15)`，
  与数据 ACK 的 bit15 重叠。此处由同一 worker 处理两路 IRQ，对同一快照
  先保存完整 SRAM，数据 ACK `snapshot & 0xffff`，再异常 ACK
  `snapshot & 0x7fff0000`；bit15 只应答一次。不能照搬两个独立 ISR 重复
  清 bit15，也不能将第二次 RCHNUM 读取的新通知一并清除。
- `hif/ccci_hif_ccif.h` 的 `ccif_sram_layout` 与 `inc/ccci_modem.h` 的
  `md_query_ap_feature`：下载区从 AP `+0x100` 开始，共240B，包含16B头、
  4B查询头、64个特征字节、4B查询尾与152B保留区。查询头尾均为
  `0x49434343`；上传头从 `+0x1f0` 开始，本轮不写。
- 本机 `mt-plat/mtk_ccci_common.h` 的 `ccci_header` 与控制消息常量、
  `fsm/ccci_fsm.c` 的 `ccci_fsm_recv_control_packet`：低16位是通道，
  接下来的15位是序号，最高位是序号断言。`data[1]` 是消息号，不能当作
  RX 包长。channel0/message0/reserved=`0x5555ffff` 分类为 HS1，其余
  message0 分类为 HS2；**分类不等于状态机验收或 READY**。

采用显式小端解码，避免 C bitfield 和结构体 ABI 假设。HS1 必须精确240B、
控制通道和消息匹配、查询头尾正确。特征保留原始 support/version nibbles，
不在接收层猜测 AP 支持能力。保留区不解释、不导出；无固件或 NVRAM 数据
进入测试夹具或文档。异常控制消息只分类，尚无异常恢复状态机。

## IRQ、worker 和停止契约

`ccci-ccif-rx.c` 复用同一 CCIF owner 的 AP 映射、两路 IRQ 和正常环对象。
constructor 只分配240B SRAM副本、80KiB包缓冲及状态，无 MMIO、无 IRQ
申请或使能。现有 IRQ action 在构造完成后注册，保持 NO_AUTOEN 和
IRQ_DISABLE_UNLAZY。默认 DT/Kconfig 状态未改变。

未来 owner 在完成供电/时钟和 `prepare` 后调用 `ccci_ccif_receive_start()`，
安装独立的、可睡眠的 consumer。每次启动只允许一次接收尝试；没有用递增
数字代替硬件停止/旧消息清理，也不允许 STOP 后重启同一接收会话。

1. 初始先排 worker，两路 IRQ 仍屏蔽；由 worker 首次 drain 后统一开门。
2. IRQ handler 只在 gate spinlock 下平衡屏蔽深度并排 worker，不访问 MMIO。
   `scheduled` token 覆盖排队、执行和续跑期间；另一 CPU 上迟到的 IRQ
   不会额外排一个可能重复 unmask 的 worker。
3. worker 读取一次 RCHNUM，拒绝24位之外的未知通知。bit15 时先复制并
   校验 SRAM，再分别 ACK、读回冲刷，然后才调用 consumer；不会让回复
   等待一个尚未执行的 ACK。异常/CCB 通知优先于同时到达的 HS1。
4. 每轮最多消费32个包，循环轮询全部非零正常环。通知只是提示；不按某一
   位的触发次数限制包数，也不依赖某个队列一定有通知。达到预算续排自身，
   保持屏蔽；所有环空后才在同一 gate 下重开 IRQ。新到的硬件通知留给
   level IRQ；不把最后冲刷读出的新位拿来 ACK。
5. 包全部进入持久的 CPU 缓冲后，现有 ring helper 才发布 AP read 指针。
   consumer 返回0表示已接管/复制数据；非零锁存故障，没有隐式丢弃或重试。
   consumer 的 `-ENODATA` 不会被误当作空环；正返回值按协议错误处理。
   完整 producer 指针却只有不完整包同样停止，不无限忙轮询。
6. `ccci_ccif_stop()` 先关闭接收门、屏蔽两路 IRQ，依次 synchronize_irq、
   cancel_work_sync，再检查故障和 GIC masked、复位 SRAM，最后才由上层
   关电。故障时仍完成同步，但保留电源/时钟供诊断，不自动猜测恢复。

父 MD owner 在 start/stop 时持有自己的 mutex。**consumer 不得获取该
mutex，不得调用 start/stop**，否则会与 cancel_work_sync 死锁。consumer
可复制数据到自己管理的队列；其后续工作和电源/停止生命周期必须由未来
控制层另行闭合。STOP 返回之前允许已有 worker 完成；返回后无 consumer
回调或接收层 MMIO。两路 IRQ 的 mask depth 由接收层独占管理。

`ccif` 状态增加实际 `rx_error` / `irq_armed`，不再硬编码 irq_armed=0。
没有 sysfs RX-start 入口；当前内核路径仍只执行 prepare/stop，不能自行开门。

## 验证及接续

运行 `python3 Documentation/arch/arm64/op6893-bringup/tools/test_modem_ccif_rx.py`：
直接编译实际 protocol/ring/RX C，使用合成 peer、MMIO、IRQ/work 模型和
ASan/UBSan，覆盖以下内容：

- 全部65536通道、序号/assert字段、不对齐输入、HS1尺寸/标记/头损坏，
  HS1/HS2及异常分类；不以 `data[1]` 截断实际有效载荷。
- SRAM 60次字读取发生在 ACK 之前；ACK 后立即改写硬件 SRAM 仍能消费
  原副本；数据/异常分离应答、CCB通知、未知位拒绝、新通知不误清。
- 四个环80包的32包预算及公平续跑、无通知扫描、回绕由原有环测试覆盖；
  consumer故障保留CPU副本、坏包不发布指针、不完整包停止。
- 两处分配失败、排队失败、IRQ合并、最后开门边界的另CPU IRQ、STOP前后
  迟到IRQ、排队未执行即STOP、worker中止门及mask depth平衡。
- 原有实际 prepare/stop 测试增加 RX 故障时先同步、禁止复位/关电的检查。

模型不能证明 Linux SMP/GIC 实际时序或固件行为；新接收代码尚未上机。
构建及设备只读核对记录见
[evidence/modem-ccif-rx-validation.json](evidence/modem-ccif-rx-validation.json)。

下一组实现把 consumer 接到有状态的 HS1→runtime回复→HS2 流程，生成6297
runtime feature记录和 SRAM上传区，补 BUSY/doorbell TX，以及独立 CCIF2/
CCISM 与 SCP真实READY的衔接。控制FSM必须检查来源、顺序、重复/异常和
超时，不能见到一个 message0 就宣布基带READY。FS/RPC/NVRAM工作副本和
服务门控仍是放行MD的准备项。接好这些后安排合并通信测试，不为尚无对端
和consumer的空 IRQ 单独刷机。


2026-11-16后续：有状态consumer及runtime回复已离线接入，详见
[运行时握手](MODEM-RUNTIME-HANDSHAKE.md)。新增内部handshake_start API，
仍没有父owner启动调用者或sysfs start；STOP先关闭控制层并同步timer，再执行
本节RX同步。旧阶段验证记录保持原义，不新增真机CCIF/HS1/HS2验收。
