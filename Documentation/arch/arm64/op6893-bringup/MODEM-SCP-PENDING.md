<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP mailbox pending：只读实机预检

2026-11-15，基于 HEAD `6db0f4606d6e` 工作树，AI 辅助实现与验证。
接续 [RX 后端](MODEM-SCP-RX.md)，默认关闭
`OP6893_CCCI_SCP_PENDING_OBSERVE`；不是正式 mailbox/IRQ 驱动。

## 实现与边界

板级 observer 增加五个独立 CLR/pending 字资源：0x107fb10c、0x107fc10c、
0x107fd10c、0x107fe10c、0x107ff10c，各4字节。probe 只校验地址/长度并映射，
不读取或写入。底层映射遵从页粒度，软件仅读指定字；不映射 mailbox
数据区、SET 或 init。资源独占请求发生冲突则失败，不绕过已有 owner。

完整 14 TX/17 RX 表从保存的同板 ACK fixture 加入板级本地属性，驱动使用
既有严格布局 helper 计算各 RX 位，包含 response 和非 APCCCI/READY 通道。
既有板级 `scp-observe` 默认 disabled，没有导入 vendor compatible/phandle。
这张表用于解释位归属，不证明尚未运行的固件与表版本一定对应。

IRQ 通过名字定位，`of_irq_parse_one()` 核对 arm,gic-v3、可用 controller、
3 个参数、SPI436..440、level-high；返回的 controller node 引用释放。
没有调用 IRQ mapping/request/enable/wake，也不将 SPI 单元号称作 Linux IRQ。
核对当前 `drivers/of/platform.c:of_device_alloc()` 仅填充 MMIO resource，
不会因节点声明 interrupts 而替本实验申请 IRQ。解析描述成功不证明 GIC
路由、电平、中断响应或 ACK 硬件语义已工作。

显式读取 `/sys/bus/platform/devices/10730000.scp-observe/pending` 才访问：

1. 检查五个映射齐全，先调用 core0 reader，复查 mux 与两组解释位稳定。
2. 依次仅读五个 pending 字，再读一轮，共10次 pending MMIO。
3. 再调用 core0 reader；core0/mux 变化、I/O 错误或两轮 pending 不同则拒绝，
   返回清空的输出，不自动重试。无法完成的 MMIO 没有可靠软件超时。
4. 输出 pending、已知 RX mask、未知位，以及 no IRQ/ACK/READY 的边界。
   稳定未知位也只报告，不清除、不读对应 payload 或推断可接收。

前后采样不能排除瞬时状态变化；mutex 只序列化本观察器，没有取代正式
clock/reset owner。没有清 SCP→SPM 通知、执行 W1C ACK、释放 reset、发送
awake 或启动 SCP/MD。AP-only `state` 的 scp_access=0 仅指那次 state 采样，
不表示独立的 core0/header/pending 属性没有执行文中访问。

## 镜像与测试

测试镜像 `b4456f5c54a5`，release `7.3.0-op6893-d1-b4456f5c54a5+`。
boot SHA256 `0296d5ddc4dafece91b9834f6d52283e74323cfd427032a08e979d1aa363187b`。
实验构建后已恢复 DTS/defconfig 原字节。启用 Image.gz 和完整构建器回归、
默认关闭 Image.gz/modules、FDT merge、启用/默认 board/merged DTB 定向
schema 均通过；默认 vmlinux 没有 observer 符号，节点 disabled。
strict checkpatch 0/0/0，编译器无新增 warning；默认配置仍有既有
FW_LOADER/VT 两条重复赋值提示。

`tools/test_modem_scp_pending.py` 编译实际 reader 与 IRQ spec parser，
以 ASan/UBSan 检查10次精确读取、缺任一映射拒绝、四次 regmap 错误、
前后 mux/core0 转换、任一 mailbox 变化拒绝、未知位保留、错误 IRQ
controller/type/number/flags/参数数量及 node 引用释放。DTB 检查校验精确
资源、IRQ 单元和与完整历史 fixture 相同的表。既有 AP/core0/TCM/RX
主机测试均通过。这些用例不模拟 GIC 或总线完成。

## 实机结果

已提前排队 boot flash/reboot，用户配合 sync+SysRq 后的 fastboot 拦截。
刷写成功，boot 分区回读 SHA256 与 artifact 相同，最终保留主线运行。
不使用 fastboot boot、不改分区表、不更新 ACK 恢复备份。

首次、四次 USB SSH 重复及一次 Wi-Fi SSH 读取全部成功，两轮采样一致：

|mailbox|pending|完整表推导的 known RX mask|unknown|
|---|---|---|---|
|0|0|0x00000060|0|
|1|0|0x0cf0c000|0|
|2|0|0x00020000|0|
|3|0|0x00039080|0|
|4|0|0x00020000|0|

六次调用共60次限定 pending 字读取；每次前后 core0/mux 校验成功。
IRQ specifiers 5 组通过解析，irq_requested=0、ack_writes=0、READY unknown。
**没有待处理位不证明 SCP 运行，也不能证明硬件 ACK/IRQ 可用。**

68-byte header 及其 loader/firmware/DRAM 窗口检查结果与前轮相同；
core0 CLR/SET bit0、gated/halt 均0，两组稳定，mux selector0/ungated。
USB/Wi-Fi SSH、8 核、sda/sdb/sdc RO=1、overlay root、cache ext4
ro/norecovery、lower SquashFS 通过。保存 dmesg 的 BUG/Oops/SError/panic/
Unable to handle 关键词扫描未见匹配，不表示所有日志无警告。
未测温度/按键/USB 故障切换。

完整日志在 `mt6893-direct/evidence/scp-pending-live/`，机器可读结果见
[pending 实测](evidence/modem-scp-pending-runtime.json)。

## 接续顺序

1. 正式持有 bootstrap 26M 的 clock/provider 引用，定义共享寄存器 owner；
   不能无限依赖 bootloader 遗留 mux 状态。明确 SCP→SPM completion 与 AP
   awake 共用哪些资源，以及 STOP/reset 时如何序列化访问。
2. 将已验证 RX 后端接到可控的 IRQ owner：初始不使能，准备全部 RX 目的
   缓冲，处理未知位、排空预算、失败屏蔽、worker 注销和代际失效。
3. 确定唯一启动者与新的 reset generation。无 pending 不允许省略旧代
   防护；解除复位前须安装真正 READY0 接收，TCM size/事件代际通过后才
   接受 READY，再考虑 awake/CCISM。保留区 metadata 不取代固件来源和
   备份有效期的核对，仍不映射 regdump。
