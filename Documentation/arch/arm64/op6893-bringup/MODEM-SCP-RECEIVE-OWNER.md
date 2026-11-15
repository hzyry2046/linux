<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP receive adapter 接入唯一 owner：静默阶段

2026-11-15，HEAD `6db0f4606d6e` 工作树；AI 辅助实现、分析和测试，
接续 [离线接收层](MODEM-SCP-RECEIVE.md)。本阶段仅替换 constructor，
不调用 start、不启用 IRQ、不读写 SCP 寄存器、不建立 READY 或启动 SCP/MD。

## 接入选择与资源生命周期

新增默认关闭 `OP6893_CCCI_SCP_RECEIVE_RESERVE`，依赖 RECEIVE，传递要求
MMIO_RESERVE、完整队列/drain 和五路 IRQ 校验代码。只开 RECEIVE 仍只编译
helper；另开 RECEIVE_RESERVE 才在既有资源 owner 的 probe 中使用新 constructor。

probe 先持有 26 MHz 时钟并取得全局唯一 claim，再映射六个 non-posted 页，
最后申请 receive adapter 的五个 NO_AUTOEN IRQ。原 IRQ reservation 放在
`#elif`，不会两次申请 action。旧 cfg-only、MMIO-only 路径均保留。
owner 的旧 irq 指针在新路径保持 NULL，receive 指针独占新 adapter。

receive 的 devres stop action 注册在自身分配和五个 IRQ action 之后，
晚于 MMIO、全局 claim、clock，因此逆序销毁时先关排队、同步 IRQ/worker，
然后释放 IRQ/transport 和映射，最后释放 claim/clock。任一 probe 失败
由同样的已申请部分清理路径处理；不 fallback/retry 或发送 SMC release。
仍为内建 boot-lifetime owner，未开放 unbind。

`irq` 只读属性按同一条件选择 receive_status 或旧 IRQ status。新格式报告
requested/gic_masked、armed/preparing/closing/fault、generation/queued_generation、
interrupts/unexpected/runs、queued/events/error 及 ready_known=0。
它查询 GIC mask 和软件状态，没有 mailbox pending/payload 或 SMC 访问；
GIC 采样与软件锁内快照不保证全局原子一致。cfg/mmio 属性仍用 owner mutex。

## prerequisite wrapper 与尚未建立的 reset 权限

新 wrapper 只在 process context、持有 owner mutex 时运行，lockdep 断言该条件。
它先拒绝零 generation 或与 owner reset_generation 不一致的请求。
**当前 reset_generation 始终为零：没有赋值、sysfs arm/start 或 reset caller。**
不能因为冷启动、继承 header/pending 或递增软件编号就授权实际接收。
constructor 不调用 wrapper；硬件上尚未验证下面的检查路径。

通过实际 reset 权限后，wrapper 才可调用 resource_check：时钟必须为26 MHz，
resource 已显式 pin 且无 fault；只读 bounded ATF query 验证 SCP 用户身份、
有效性和完整资源 mask。query 后再检查时钟，捕获采样期间的变化，失败
sticky invalidate，不自动 request/release/retry。transport 的 gate 还独立
检查 closing/armed/本代 token，且任何 check 错误都关闭接收并擦除 CPU 队列。
reset generation 仍须未来 reset owner 在完成旧消息隔离之后建立。

## 离线验证

- 实际 owner probe/status C 在 legacy cfg、MMIO-only、receive 三种编译路径
  下跑 ASan/UBSan，确认映射先于 IRQ、没有双重申请、状态选择及错误传播。
- 实际 owner wrapper 与实际 resource SMC 实现联动：零/错误代际无 SMC，
  未 pin 不查询，成功查询不再 request；前后时钟变化和 fault 均封闭。
  测试中的非零 reset_generation 只存在于 host 模型，不是设备操作。
- 实际 receive/MMIO/queue/RX/drain sanitizer 及 resource、IRQ、MMIO、queue、
  drain、RX 回归通过；启用/默认 ARM64 Image.gz/modules 均通过、无编译警告，
  默认 vmlinux 不含 receive 符号。相关 C/header strict checkpatch 为0/0/0。
- 打包镜像的 board 与 merged-preview DTB 六页资源检查通过；没有 binding
  或常驻 DT 更改，临时实验 DTS/defconfig 已按原字节恢复。没有重跑全板 schema。

模型不证明 Linux SMP、实际 GIC/workqueue 或硬件 MMIO 语义。新 wrapper
尚未在真实 generation 下执行；本阶段不增加基带支持验收。

## 测试镜像与实机验收

镜像 `4ed57fd98c40`，release `7.3.0-op6893-d1-4ed57fd98c40+`，
`/data/src/mainline/mt6893-direct/dist/4ed57fd98c40/boot.img`，SHA256：
`20c38c94c6fe372f443b5e6c992b8767068977341a2879f81af2edf73c69450d`。

上机前设备 `fba1be648ead` 的 USB/Wi-Fi 只读复查通过。提前排队 boot-only
flash/reboot，用户配合 sync + SysRq reboot 后拦截；已刷入并启动新镜像。
SSH reboot 命令在链路断开后超时，最终按 flash 日志、新 release 与分区回读
确认成功，不以 SSH 返回值作为重启完成证据。ACK 备份和分区表未更改。

首次状态：resources users=1、scp_present=0、attempted=0，确认 probe 没有
发送资源请求；五个 action 已从旧 `op6893-scp-mbox` 全部切换为
`op6893-scp-rx`，hwirq468–472 每个仅一个 action，所有CPU中断计数0。
新状态 requested=5/gic_masked=5、armed/preparing/closing/fault=0、
generation/queued_generation/interrupts/unexpected/runs/queued/events/error=0。
六个完整页的 iomem 均归同一 owner，MMIO读写0、prepared=0、generation=0；
MMIO初始fault=1表示未prepare的主动封闭，新transport初始fault=0。

显式执行一次26M pin 后，SCP user=1、mask=0x02、pin_verified=1、fault=0。
USB及Wi-Fi各三轮查询中上述零计数和五IRQ masked全部保持，CCF enable/
prepare引用3/3、rate=26000000；8核在线、sda/sdb/sdc RO=1、cache ext4
ro/norecovery、lower squashfs ro、overlay root正常，旧pending属性不存在。
boot分区SHA256与上述artifact一致；dmesg明确故障关键词扫描0匹配，不
据此声称所有日志无警告。未做按键/温度、USB故障切换或真实RX测试。

首次采集因debugfs未挂载而在clock_summary处停止；挂载debugfs后完成两条
路径的全部回归。全程未调用start、读写SCP cfg/mailbox/core0/TCM寄存器、
清pending或启动SCP/MD。设备最终保留新主线运行。

接续优先分析可控 reset、固件加载/旧消息隔离依据与跨代客户端约束。
在这些条件完成前，保留 start 无调用者、reset_generation=0。
证据目录 `/data/src/mainline/mt6893-direct/evidence/scp-receive-reserve/`。

结构化结果见 [实机与离线验证](evidence/modem-scp-receive-owner-validation.json)。
