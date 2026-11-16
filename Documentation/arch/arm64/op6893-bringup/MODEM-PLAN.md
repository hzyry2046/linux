<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 基带：内核对比与搭建计划

更新：2026-11-16。SCP 常驻RX/READY1、awake及一次MD-invalid传输已实测，
见[R5.25](MODEM-SCP-RUNTIME.md)。新增同板LK子区解析及统一平台owner，
实机只读确认LK留下MD1 ON，增加显式接管断电和一次冷循环；完成离线测试/
构建，未实际切换MD电源或放行CPU。下一步CCIF/CCISM，
不为纯计算或资源观测单独刷机。AI辅助源码分析与实现。历史阶段记录保留。
SID3 shutdown 对照及启动电压契约见 [供电生命周期](MODEM-RAILS.md)。
图形接续事项保存在 [GRAPHICS-TODO.md](GRAPHICS-TODO.md)，先推进基带框架。

## 结论与底本选择

采用分阶段移植厂商栈的路线：以本机 Android 4.19 为硬件和固件协议契约，
以本机已完成适配的 6.6 CCCI/SCP 为功能底本，选择性借用 qqcandy 的主线
API 适配、TTY 前端和诊断方法。先搭出 LK 交接、共享内存、平台资源、SCP、
CCIF、FSM、端口这几层，验收控制通道后再接 DPMAIF 数据面。

原因是本机已经有同板 6.6 移植记录，没必要从零重写整套固件协议；而 qqcandy
是另一代基带，不能整套照搬。主线 `drivers/net/wwan/t7xx/` 的入口是 PCI，
也不能通过添加一个 compatible 直接驱动本机的片上 CCIF/DPMAIF。

本轮以源码、历史移植记录和保存的 ACK FDT 为证据，不把其他树的注释、配置
片段或历史运行结果当作当前主线的实测结果。Android 用户空间由用户安排的
其他 agent 分析；这里整理它们需要对接的内核边界。

## 对比对象与可复核入口

以下路径均为分析时的本地工作树；提交号不能替代工作树文件内容。
[源码清单与 FDT 投影](evidence/modem-kernel-audit.json)记录选定源码的 SHA256，
以及不含设备身份、校准或 NVRAM 内容的硬件属性。

|代号|目录|分析时 HEAD|用途|
|---|---|---|---|
|M|`/data/src/mainline/linux`|`6db0f4606`|目标主线|
|A|`/data/src/kernel_oddo_mt6893`|`9e2043b0b`|本机 Android **4.19**，不能按伪装的 uname 判断版本|
|V|`/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833`|`4a9ae821`|同板 6.6 移植；驱动位于 `kernel/kernel_device_modules-6.6/`|
|Q|`/data/src/mainline/linux-qqcandy-6.18`|`3e9df2e46`|MT6895 参考，目录名不是硬件兼容性依据|

主要源码入口（相对各树根目录；V 先进入上述模块子目录）：

- A：`drivers/misc/mediatek/eccci/Makefile`、`mt6885/ccci_config.h`、
  `port/port_cfg.c`、`port/port_rpc.c`（后三项相对 `eccci/`），以及
  `drivers/misc/mediatek/ccci_util/ccci_util_lib_fo.c`。
- V：`drivers/misc/mediatek/eccci/fsm/md_sys1_platform.c`、
  `ccci_modem.c`、`fsm/ccci_fsm_scp_c.c`、`hif/ccci_hif_ccif.c`、
  `hif/ccci_dpmaif_drv_v2.c`（后四项相对 `eccci/`），以及 SCP 栈；
  具体文件见证据清单。
- Q：`drivers/misc/mediatek/ccci_util/ccci_util_lib_fo.c`、
  `ccci_core/ccci_main.c`、`eccci/port/port_tty.c`、`eccci/port/port_rpc.c`
  （后三项相对 `drivers/misc/mediatek/`），以及
  `arch/arm64/boot/dts/mediatek/mt6895-oplus-qqcandy.dts`。
- M：`arch/arm64/kernel/op6893-fdt.c`、
  `arch/arm64/boot/dts/mediatek/mt6893-op6893-boot.dts`（实际启动 DT）、
  `drivers/pmdomain/mediatek/mtk-pm-domains.c`。

辅助记录是 `/data/src/6.6-exp/mt6893-gki66/docs/modem-66-bringup.md` 与
`modem-66-dt-hardware-reference.md`。它们记载过去已达到 READY、双卡注册、
数据上网和基带断电后恢复，但部分机型称呼和建议仍需核对。
历史逆向目录现为 `/home/hzyry2046/src/reverse-analysis/conninfra-rev/modem/`，
其早期判断也要按当前源码复核。

## 硬件与接口差异

本机资源来自 `/data/src/mainline/mt6893-direct/evidence/ack-live.dtb` 的离线
解码，属于保存的历史 ACK 快照，不代表这次启动的 LK 交接内容。

|项目|本机 A / V|Q|移植决定|
|---|---|---|---|
|AP / MD 代际|MT6893 / 6297；A 的 Makefile 选 `mt6885` 平台目录|MT6895 / 6298|目录名、`md1_6297` 表名不能作为代际判据|
|实际 HIF|`mdhif_type=6`，bit1 CCIF + bit2 DPMAIF|同为 6|A 配置里的 CLDMA 名称不代表运行时走 CLDMA|
|CCIF AP / MD|`0x10209000` / `0x1020a000`，各 `0x1000`；本机也有 CCIF2 `0x1023c000/0x1023d000`|四窗在参考树按不同节点组织|硬件窗口与节点资源索引分别核对|
|CCIF IRQ|GIC SPI 194 / 195，level high|241 / 242|使用本机 IRQ|
|CCIF 时钟|节点八个；A 驱动分为 HIF 六个及 SCP/CCIF2 两个|ccifdriver 六个，另有 SCP 桥节点|CCIF2 由桥唯一管理；部分 vendor gate 为 dummy，不照搬门控掩码|
|MD watchdog|GIC SPI 78，edge rising|253|接入本机异常路径|
|mddriver reg|本机两组 CCIF 窗|MD L2 SRAM `0x0d124000/0x2000`|同名节点也有不同语义|
|DPMAIF|V 使用 v2；本机 IRQ SPI 209，两个时钟|v3，IRQ 256 / 760，三个时钟|复用 v2 后端，独立验收数据面|
|非缓存 SMEM|`0x8e000000 / 0x1800000`|`0x8e000000 / 0x120000`|不能照搬 Q 的大小和 region 偏移|
|缓存 SMEM|保留 `0x88000000 / 0x4960000`|CCB 在 `0x89000000 / 0x4000000`|以本机 LK 布局和 region ID 核对|
|LK tag 保留区|`0xbff70000 / 0x10000`|`0xbdbf0000`|地址必须来自本次交接并受保留区约束|
|主要基带电源|SID3：VBUCK1 VMODEM、VBUCK3 VNR、VBUCK4 VSRAM_MD；MT6359P VPU 作 VRFDIG|MT6363 的 VMODEM/VSRAM_MODEM/VDIGRF|不能照搬 Q 的 regulator 映射，也不能漏第四路|

本机 DPMAIF 四窗为 AO_UL `0x10014000`、PD_UL `0x1022d000`、
PD_MD_MISC `0x1022c000`、SRAM `0x1022e000`，各 `0x1000`。
A 的 `mediatek,dpmaif_capability=14` 与新代码的 `mediatek,dpmaif_cap=4`
不是同名属性，需追踪解释它们的代码，不能直接认为值冲突或相等。

控制、RPC、FS、AT 经 CCIF 共享内存环，包数据经 DPMAIF 到 ccmni。
A 的 `ttyC0` 实际使用 `char_port_ops`，不是标准 Linux TTY：UART2 RX/TX
通道为 10/12，minor 3。FS RX/TX 为 14/15，控制 RX/TX 为 0/1。
Q 的 `port_tty.c` 新增标准 `ttyCCCI0` 前端，并且仅在打开时转发接收数据；
TTY 注册成功本身不能证明固件处理过 AT。

## qqcandy 能借什么，不能证明什么

Q 同时保留两条路线：

1. `ccci_util` 加实验性的 `ccci_core/ccci_probe/ccci_smem_dump/ccci_diag`。
   `ccci_core/ccci_main.c` 在解析 tag、记录内存布局后直接设置
   `CCCI_STATE_READY`，这不代表 MD 完成 HS2。它要求
   `mediatek,ccci_tag_mem` 保留区，而本机现有 tag 节点没有该 compatible。
2. 完整 `eccci`、ccmni、SCP 桥和端口栈，附带近期主线适配及大量调试改动。
   `ccci_util_lib_fo.c:collect_lk_boot_arguments()` 已恢复真实 LK tag 解析；
   Kconfig/Makefile/文件头中“不解析、永久关闭”的注释存在过时情况。
   当前函数注释记载设备到 READY，但 AT/MIPC 和 SIM 仍未解决。

`qqcandy.config` 配置片段不能证明完整栈实际装载情况，也没有本轮对该设备的
运行验证。因此可借鉴 API 适配、TTY、分层状态观察和 CCIF 环诊断思路，
不把其 AT、SIM、上网能力视为已经解决的参考实现。

以下内容必须逐项审查：硬编码的 6298 布局、AO sequencer、时钟/保护位、
SMC 调用、空中断处理及 RPC 代答。`ccci_smem_dump` 虽有只读描述，实际包含
可选写操作；历史注释还记载读取 MD image 导致 AP fault、CCIF 访问挂死。
保留内存不等于 AP 有权读取，时钟开启也不等于电源/复位/防火墙已经满足。

## 当前主线缺口与第一批改动

M0 实现前的 FDT 合并仅导入经过校验的 `atag,devinfo`；保留内存合并只拷贝
`reg/size/alignment/alloc-ranges/no-map`，不导入外部 phandle/compatible。
保存的 `7969e0599430/merged-preview.dtb` 没有 CCCI 交接属性或 modem 节点。
板级保留区已在，但这些只能防止分配冲突，不能替代 LK 协议交接。

第一批实现应限定为以下可独立复核的框架：

- **交接**：在 `op6893-fdt.c` 增加明确的 CCCI 属性白名单，读取 LK 的
  `/chosen` 和 `/mddriver`；双份存在时要求一致。把验证过的原始小头保存到
  明确的目标节点，不复制整棵 vendor modem 节点或外部 phandle。
- **解析**：提供可禁用、默认不启动 MD 的有界 tag/layout 层；通过显式本地
  保留区引用限定映射，报告版本、布局校验结果和缺失依赖，不发布原始 payload。
- **资源契约**：整理本机 CCIF、DPMAIF、MD 电源、SID3 supplies、SCP/CCISM
  的绑定与所有权。先保留资源描述，依赖未就绪时不自动触发 probe 上电。
- **栈骨架**：将 V 的平台/HIF/FSM/port 分层移植，保留各层独立构建开关；
  让“能构建”“能解析”“能通信”“MD READY”成为不同验收项。

保存的 ACK `ccci,modem_info_v2` 同时出现在 `/chosen` 与 `/mddriver`，
两份均为 48 字节：基址 `0xbff70000`，有效大小 `0xa68`，版本 3，20 个 tag，
load flag 1，公共及四个 MD 错误码均为 0。这是历史样本，不能硬编码进驱动。
A 的 `_ccci_lk_info_v2` 为小端原生结构，44 字节字段加 4 字节尾部填充；
最后不是五个 MD 错误码。它也不是常规大端 FDT cell 数组。
v2 tag 使用 64 字节名称和三个 u32（offset/size/next），合计 76 字节；
本机 version 3 的处理应按已核实的厂商路径实现，不能只按结构名猜版本。

解析器需检查 header 长度、受支持版本、load/error、tag 数量上限、名称边界、
整数溢出、链环/重复、header 与 payload 的非法重叠、类型所需最小长度，
并检查所有地址及长度属于允许的保留区。校验失败即停止，不跟随任意物理地址，
不映射整块 MD 固件来“看看是否有数据”。

## 电源和 SCP 是前置项目

目标主线目前的 MT6893 power-domain 描述没有 MD 域，SPMI 板级节点只声明了
GPU/大核使用的 SID7，没有基带 SID3。上游 `mtk-pm-domains.c` 已有 CCCI
secure power-sequence 支持，也不证明本机旧 ATF 支持它的 enable/disable
子命令 18/19。

本轮进一步确认 A 使用 AP 直接操作的 MD MTCMOS，ATF 负责后续启动；
M 通用非 secure MD 关机顺序也与 A 不完全一致，不能只补域数据就启用。
SCP 应使用 RV 分支，旧 CM4 调查入口不适合作资源索引底本。寄存器、供电、
单一 CCIF2 owner 和补丁拆分详见 [资源契约](MODEM-RESOURCES.md)。

A 的 `MTK_SIP_KERNEL_CCCI_CONTROL` 由 `MTK_SIP_SMC_CMD(0x505)` 编码成完整
SMCCC function ID；参数枚举中的 MD_CLOCK_REQUEST=5、MD_POWER_CONFIG=6、
MD_FLIGHT_MODE_SET=7、SCP_INFO_TO_SAVE=12、SCP_CLK_SET_DONE=13 各有独立
语义。先核对实际调用路径，不能把未知的 6/18 等子命令当作只读探测。

V 的 `md_sys1_platform.c` 记录了复位失败的一个关键原因：MD DVFS 会降低
SID3 三路电压，重新启动需要恢复适当的启动电压；4.19 会保存首次 VOSEL。
V 通过 regulator 名字补查解决缺失 supply 的问题。主线应建立明确的 DT
supplies 和启动/运行电压生命周期，不能永久按第一次测到的值写回，或者把
查不到 regulator 当作成功。共享 SCP/MD 资源也不能被两个驱动分别强制重置。

SCP 需要固件、mailbox/IPI、时钟、电源及 `ccci_fsm_scp` 的 CCISM 桥。
M 的 `mtk_scp.c` 没有 MT6893 match，通用 remoteproc 不能直接替代这套厂商
协议。V 记录过 SCP 缺失时 HS1 后约 65 秒在 `ccismcore_ccci.c` assert；
这是历史故障特征，不是本机主线的固定超时。搭建时就应纳入依赖，不能用
“SCP ready”假返回把故障推迟到 AT/SIM 阶段。

## 分阶段 TODO 与验收

|阶段|工作项|验收证据|
|---|---|---|
|M0：被动框架|LK 属性保留、有界 tag/layout 解析、资源清单和失败分类|主机合成解析用例通过；实机只读 tag 解析；未触发 MD/SCP 上电或释放复位；USB/Wi-Fi/存储回归|
|M1：依赖层|SID3 supplies、MD 电源/时钟/复位、CCIF 资源；并行解决 SCP 固件和 CCISM 传输|资源实际归属明确；受控启动/停止 SCP 和平台层可复现，失败不会无限访问无响应 MMIO|
|M2：控制面|CCIF 环、FSM、runtime feature 协商、必要内核 RPC 及 FS/RPC 用户态边界|收到真实 HS1/HS2；记录协商结果与阻塞请求；SCP/CCISM 完成，超过历史延迟断言窗口仍稳定|
|M3：活 AT 与 SIM|端口 ABI、最小服务端、有效 AT 往返、SIM 属性/EINT 配置|请求确实发到 MD 且收到对应响应；SIM 识别和状态变化单独验证；节点出现不算成功|
|M4：数据面|DPMAIF v2、DMA/缓存/中断、ccmni 或后续 WWAN 接口、PDN 用户态|实际注册、建链、IP 和双向流量；关闭/再开启和异常恢复；无线数据链与 USB/Wi-Fi 分别验收|

TODO：

- [x] M0 主机实现：交接白名单、有界 parser、默认关闭的检查模块，合成测试及编译；
  详见 [M0 记录](MODEM-M0.md)；布局差值仍待解释。
- [x] M0：主线新启动的 CCCI header、真实 tag/layout 成功路径实机验收；
  `fe077e30d191` 检查通过，USB/Wi-Fi SSH 与存储回归通过，见 [R3](MODEM-R3.md)。
  错误分类保留主机合成测试，没有在实机注入损坏交接。
- [x] M0离线：历史4.19记录确认NVRAM末尾0x880000至CCB起点0x900000为0x80000间隙；新增有界LK子区解析，保留完整bank跨度，见[共享内存布局](MODEM-SMEM.md)。
- [ ] M0子区实机：与MD平台/CCIF功能组一起核对本次LK真实layout，不单独刷机。
- [ ] M1：形成 MD 电源、SID3、CCIF/CCIF2、SCP 的完整资源和所有权补丁组。
- [x] M1 离线审计：AP MTCMOS/ATF 分工、SID3 DA/RG 与第四路 VRFDIG、
  六加二时钟、SCP RV 映射和 CCISM 流程；见 [资源契约](MODEM-RESOURCES.md)。
- [x] R1/R2 第一批：SID3/VPU 默认关闭描述、本地 supplies、四个普通 CCIF
  gate、独立依赖检查模块及主机验证，见 [实现记录](MODEM-R1-R2.md)。
- [x] SID3 shutdown 源码对照：A 与主线同地址/值/顺序，保留现有策略；
  见 [供电生命周期](MODEM-RAILS.md)，实际关机回调和重启恢复仍待验证。
- [x] R1/R2 引用实机验收：`7576d31c76a4` 两次启动均绑定四路供电和
  四个 clock，USB/Wi-Fi/存储回归通过；见 [供电记录](MODEM-RAILS.md)。
- [ ] R1/R2 后续：shutdown 执行阶段观测、启动电压来源/恢复所有权、
  CCIF2/4/5 真实 gate 生命周期；引用通过不表示这些前置项完成。
- [x] R3 首版：本机 MD1 MTCMOS 有界序列和 genpd 接口、初态拒绝、失败锁定、
  逐步错误注入与 ARM64 编译；见 [R3](MODEM-R3.md)。未添加板级域节点，未实机上下电。
- [x] 吸收用户空间/MD 固件分析更新，核对 TLV 填充、整包/结构长度、32k 极性
  和 HS2 通道歧义，见 [协议接续](MODEM-PROTOCOL.md)。
- [ ] M1：关闭 SID3 shutdown/启动电压和 SCP 依赖缺口后，接平台 consumer，
  才添加 MD 域入口并实机测试受控上下电。
- [x] R5.1：有界完整 mailbox 布局、APCCCI 定位、CCISM wire 编解码与 u32
  SHM 地址表达性校验；A/V 实际布局函数交叉验证、ASan/UBSan 和 ARM64 构建。
  见 [SCP 协议基础](MODEM-SCP.md)，没有硬件/READY 入口。
- [x] R5.2：72-byte TCM header 的严格有界解码、可信窗口包含与双核历史
  DRAM 恢复映射跨度检查；A/V 结构 ABI、sanitizers 和 ARM64 构建验证。
  见 [SCP 内存契约](MODEM-SCP-MEMORY.md)，实际固件 header/来源尚未验收。
- [x] R5.3：共享 AP awake 引用/有界 SET 应答后端，错误清理与故障锁定，
  STOP 失效接口；真实 C 的失败注入/sanitizers 与 ARM64 构建验证。
  没有 provider/caller，默认关闭；见 [awake 与上机边界](MODEM-SCP-AWAKE.md)。
- [x] 用户允许后，在当前 6.6 上执行固定白名单 metadata collector：两次软件
  READY，24 项 DT 属性与保存 ACK 一致，6 项同为缺失；未重启/刷写。
  见 [被动观测](evidence/modem-scp-6.6-observation.json)，没有 awake/TCM 操作。
- [x] 用户允许上机后，在现有 6.6 加载/卸载临时缓存观测模块：实际缓存
  struct_size=68，动态 share 为本次分配的 0x8d000000/0x320000；新增严格
  68/72-byte 解码并复测，loader/firmware/完整 DRAM mapping 位于静态保留区。
  regdump 不在两个已确认窗口内，未映射；没有重启/刷写或 awake/IPI。
  见 [缓存与内存实测](MODEM-SCP-OBSERVATION.md)，不代表主线 SCP 验收。
- [x] R5.4 AP 侧 SCP observer：主线 c55ce7327907 实测 mux selector=0、
  gated=0，本次动态 share=0x8d000000/0x320000；USB/Wi-Fi SSH、8 核和
  存储/rootfs 回归通过。默认关闭，未访问 SCP/TCM 或发送 awake/IPI。
  见 [主线前提观测](MODEM-SCP-PREREQUISITES.md)。
- [x] R5.5：限定 core0 reset/status 在主线 0a53a32dd3b3 完成六次显式读回；
  reset alias bit0/status bits0..1 均0且两组稳定，USB/Wi-Fi 和存储回归通过。
- [x] R5.6：主线 3ccec64b58d4 实测精确 68-byte TCM header，两份一致；
  loader/firmware/DRAM 与完整 mapping 位于静态保留区，backup 公式匹配。
  regdump 不在 firmware/share，未映射；见 [TCM 实验](MODEM-SCP-TCM.md)。
- [ ] 接续：先核对 mailbox RX MMIO/IRQ 资源、完整布局、pending/ack 语义及
  时钟/唯一 owner/代际契约，再实现默认关闭的 RX transport；释放复位前
  必须具备真实 READY 接收路径。当前仍无 READY，不发送 awake。
- [ ] 后续闭合 LK→主线真实 READY/时钟、固件/备份来源和 regdump 归属，再接
  主线 observation consumer；主线使用自身动态分配，不硬编码 6.6 的地址。
- [ ] R5 后续：SCP 固件/备份有效期与 regdump 归属、共享 awake/clock provider、
  mailbox transport/IRQ/真实 READY/停止恢复；不删除其他 channel 后重排 APCCCI。
- [ ] R6：CCIF2 唯一 owner、真实 ACK/RBREADY/INIT_DONE、有界等待和重启代际。
- [ ] M1：核实本机 ATF 调用契约、SCP 固件来源及 mailbox/IPI 的实际运行配置。
- [ ] M2：移植控制栈，并与用户空间分析结果对齐必要请求和端口 ABI。
- [ ] M3：有效 AT、SIM，各自保留独立验收记录。
- [ ] M4：接 DPMAIF v2，最后验证移动网络与恢复。

每次失败至少区分：交接缺失、布局不合法、资源缺失、上电/复位失败、CCIF
无响应、HS1/HS2 超时、未处理 RPC/FS、SCP/CCISM 未完成、AT 无响应、SIM
失败、数据 DMA/PDN 失败。不要统一记录成“基带未启动”。

## 给用户空间分析的对接边界

需要对方产出的是每个服务与端口的对应关系、启动依赖、ioctl 编号/结构/指针
宽度、共享内存映射、消息头与通道、读写阻塞语义、FS/RPC 请求及返回格式。
特别区分 legacy `ttyC0` 字符设备与标准 TTY，不能仅凭名字选择 termios。

应先保留厂商内核 RPC 和用户态 RPC 的分工，再决定最小替代服务。Q 已将
AMMS DRDI 请求 `0x4014` 放进内核处理，这不意味着本机固件也需要同样代答；
A 的 QUERY_AP_SYS_PROPERTY、SAR 等用户态边界仍需跟分析结果核对。
未知请求明确失败并记录请求类型，不能一概返回成功，或把所有超时归因于
缺少 daemon。FSM READY、AT 回复、SIM 可用、注册、上网均是不同验收点。

固件是否由 LK 已加载、各映像版本/布局如何配套，要先做清单，再决定 Linux
加载职责。持久 NVRAM/校准先采用只读基线；如协议确实需要写入，先明确
私有工作副本、持久化和恢复方案，不能跨版本覆盖原始数据。日志只保留请求
类型、长度、状态、时序，不输出 IMEI、原始 NVRAM、校准内容或它们的哈希。


2026-11-15 设备使用约束：用户已刷回 Android 供基带分析 agent 使用。
当前只离线实现和验证；不重启、不刷写、不占用设备，后续上机等待用户通知。

随后用户允许被动检查，并更正当前内核为 6.6、暂不刷入；已完成上述软件
READY/DT 只读采集。当前继续保留 6.6，不触发 awake、重启或刷写。


### R5.5 core0 限定读回（2026-11-15）

新增默认关闭的 core0 reset alias/status observer，已完成 ARM64 实验镜像、
ASan/UBSan 拒绝路径与精确六读边界、binding/schema 和 strict checkpatch。
镜像 `0a53a32dd3b3`，真机读回成功；所有解释位均0、两组稳定。详见
[core0 实验](MODEM-SCP-CORE0.md)。下一轮进入精确 TCM header，仍不启动
SCP/MD、不发送 awake；READY/IRQ/代际管理保持未完成。


### R5.6 TCM header（2026-11-15）

主线 `3ccec64b58d4` 六次显式读取均为 68 字节，两份精确快照一致。
loader 8192、firmware 1572864、DRAM 305120、完整 mapping 1220608 字节，
均在本次静态 SCP 保留区；backup 公式和 payload 不重叠检查通过。
regdump 1048576 字节在 firmware/share 外，未映射。USB/Wi-Fi、8 核、
UFS RO/rootfs 回归通过。接续优先审计 READY0 所在 mailbox 的 RX/IRQ
接入、pending 的清除责任及 STOP/reset 失效，不通过试发 IPI 猜测 READY。


### R5.7 mailbox RX 后端（2026-11-15）

- [x] 保存 DT 的 mailbox data/SET/CLR/init 与 GIC SPI 审计；确认 READY0
  mailbox1/word40/bit20、TCM size 0x180000，与 APCCCI bit14 独立。
- [x] 默认关闭 RX 事务后端：精确 copy → 必需的板级 SPM completion →
  精确 ACK → 带 generation 交付；错误锁定、不重试未知 ACK，不接受 READY。
- [x] 真实 C 的 ASan/UBSan 错误注入、覆盖设备缓冲测试、完整表批次、
  READY0 payload 校验及启用/默认关闭 ARM64 Image.gz/modules 构建。
- [ ] 本次 mailbox pending 的无 ACK/无 IRQ 预检，随后补共享寄存器与时钟
  owner、IRQ mask/排空上界、全部 RX 目的缓冲及 STOP/reset 代际管理。

详见 [RX 实现和接续](MODEM-SCP-RX.md)。本轮未重启/刷写，设备仍为
`3ccec64b58d4`，没有 mailbox 硬件 caller，未收到真实 READY 或启动 SCP/MD。


### R5.8 mailbox pending 预检（2026-11-15）

- [x] 默认关闭的五个 CLR/pending 字只读 observer，以及无 Linux IRQ
  mapping/request 的 GIC specifier 校验；完整 TX/RX 表推导 known masks。
- [x] 主线 `b4456f5c54a5` 六次显式读取，五组 pending/unknown 全0，
  双采样及 core0/mux 稳定。USB/Wi-Fi、8 核、UFS RO/rootfs 回归通过。
- [x] 精确10读与所有前后错误/变化拒绝、IRQ 描述错误及引用释放的
  ASan/UBSan；启用/默认构建、DTB/schema 与回归通过。
- [ ] 正式 bootstrap 26M clock/provider 与共享 SCP→SPM completion owner，
  随后接初始不使能的 IRQ owner、全部 RX 目的缓冲及失败屏蔽/排空预算。
- [ ] 唯一启动者/reset generation、真正 READY0 接收；没有 pending 仍不
  等于 READY，不跳过旧代防护或直接发送 awake/启动 MD。

见 [pending 实测和边界](MODEM-SCP-PENDING.md)。设备保留上述主线镜像，
本轮无 ACK/payload/IRQ 注册，没有修改 ACK 备份和分区表。

### R5.9 bootstrap 时钟（2026-11-15）

- [x] 在既有 TOPCK provider 增加默认关闭的受限26M输出与常驻引用；observer 独立 opt-in 持有。
- [x] 梳理 TOPCK、SPM vote、RX completion 与 AP awake 的独立资源/共享生命周期，见 [bootstrap](MODEM-SCP-BOOTSTRAP.md)。
- [x] 启用/默认构建、schema 和实机验证：6d783d7288f4，CCF引用2→1→2、26M保持、USB/Wi-Fi及原观测通过；不代表 SPM vote 或 READY。
- [ ] 核对实际 SMC ABI，建立唯一 vote/共享 cfg owner 后再接 IRQ owner。

### R5.10 SPM 26M资源持有（2026-11-15）

- [x] A/V及本地ATF控制流复核：固定request ABI、追加语义、release清全部SCP占用；区分返回成功与实际投票。
- [x] 默认关闭唯一boot-lifetime owner、只读bounded query和显式一次26M pin；失败不retry/release，见 [SPM资源](MODEM-SCP-RESOURCE.md)。
- [x] 启用/默认构建、schema与实机query→pin→readback：5393b5915579，SCP延迟注册，mask=0x02、pin_verified=1；USB/Wi-Fi和存储回归通过，不能代替READY。
- [ ] 将vote与共享cfg/IRQ/generation生命周期整合，再接可控RX。


### R5.11 共享 cfg 资源归属（2026-11-15）

- [x] 同板 A/V 与 qqcandy 对照：cfg+0x94 写1属于 RX post completion；AP awake、替代 AP cfg/GPR7 与 reset 写0xff 独立。
- [x] 在已有资源 owner 内默认关闭地独占完整 cfg 窗口；不读写寄存器，不新增 SMC caller；sanitizer、启用/默认构建及 DT/schema 通过，见 [cfg](MODEM-SCP-CFG.md)。
- [x] 80e79074de00 实测完整 cfg 窗口预留；26M pin、USB/Wi-Fi、8核、存储/rootfs、boot回读和既有观测回归通过，cfg寄存器未读写。
- [ ] 明确 completion 写排序依据，接唯一 IRQ/worker、目的缓冲/预算和 STOP/reset generation，再处理真正 READY。


### R5.12 RX drain/lifetime 离线后端（2026-11-15）

- [x] 默认关闭，五组完整RX覆盖、总预算1–32轮、错误锁定全部RX、保留屏蔽及单独containment错误；不自动重试/重新排队。
- [x] 入队generation校验、STOP两阶段与代号单调性；实际C sanitizer及启用/默认ARM64构建通过，见 [drain框架](MODEM-SCP-DRAIN.md)。
- [ ] 真实IRQ/worker adapter及入队/STOP锁策略、全部目的缓冲/队列容量、completion写排序与硬件接线。
- [ ] 实际reset隔离旧消息后建立本代READY；软件递增generation不等于硬件旧代已清除。

本轮未刷写或重启，设备保持80e79074de00；后端未接硬件，不增加外设验收。


### R5.13 RX目的队列（2026-11-15）

- [x] 默认关闭CPU FIFO，覆盖全部17个RX pin；整批空间检查在硬件completion/ACK前，ACK后交付CPU快照，不再分配/调用外部客户端。
- [x] 队列满/任何硬件错误失效全部RX并擦除CPU队列；generation拒绝、容量与环形复用、实际RX/drain联动sanitizer及启用/默认ARM64构建通过，见 [目的队列](MODEM-SCP-QUEUE.md)。
- [ ] 将queue/drain纳入唯一owner的Linux IRQ/worker adapter，闭合入队/STOP锁与enable/disable深度、任何drain错误后的队列失效。
- [ ] completion MMIO排序与真实受控reset/READY，随后才推进SCP/MD启动。

本轮未刷写/重启；设备保持80e79074de00，新queue未接硬件，不增加支持验收。


### R5.14 mailbox IRQ初始归属（2026-11-15）

- [x] 既有cfg/SPM owner内实际申请五个专用IRQ，NO_AUTOEN，无arm/enable入口；OF/GIC编号与无sleeping bus-lock检查。
- [x] 意外handler只contain并排fault worker；closing gate、锁外IRQ/worker同步及devres/部分失败清理；实际C sanitizer与strict checkpatch通过，见 [IRQ边界](MODEM-SCP-IRQ.md)。
- [x] 启用/默认构建及schema通过；49092bac2836实机五action/GIC masked、计数0，26M pin、USB/Wi-Fi及原观测回归通过。
- [ ] 正常RX worker、可开启的IRQ深度平衡与入队代号、MMIO/completion、drain/queue/客户端和受控reset整合；当前没有建立generation或READY。


### R5.15 RX MMIO后端离线准备（2026-11-15）

- [x] 默认关闭的六个完整4 KiB资源 non-posted 映射 helper，无fallback；cfg和mailbox实际readl/writel与写后屏障，未接platform caller，见 [MMIO后端](MODEM-SCP-MMIO.md)。
- [x] 实际MMIO/queue/RX/drain联动ASan/UBSan；映射/前置检查失败、快照/ACK新消息和预算覆盖；启用/默认Image.gz/modules、符号隔离、ARM64屏障反汇编与strict checkpatch通过。
- [ ] 扩展DT/binding并在唯一owner中替换原cfg/pending映射，先验证资源独占/映射；不能同时映射不同页属性。
- [ ] 接真实prerequisite、可开启IRQ/worker、全部队列/客户端与STOP，再由真实受控reset建立代际和接收READY；数字递增和继承状态均不足。

本轮未刷写/重启，设备仍为49092bac2836，USB只读复查五IRQ masked、26M pin有效、cfg寄存器读写0。新后端尚无硬件验收。


### R5.16 唯一owner non-posted映射接入（2026-11-15）

- [x] 独立默认关闭MMIO_RESERVE opt-in，替换旧cfg分支，与pending observer互斥；DT/binding扩展完整六页；新状态属性只读软件计数。
- [x] 实际owner双路径sanitizer、MMIO及既有回归、Kconfig互斥检查、启用/默认Image.gz/modules及定向schema/DTB检查、strict checkpatch通过，见 [映射接入](MODEM-SCP-MMIO-OWNER.md)。
- [x] fba1be648ead实机六页iomem归属、零寄存器访问/未prepared、五IRQ masked；26M pin、USB/Wi-Fi、8核、存储/rootfs和boot回读通过。旧pending属性编译关闭，返回ENOENT。
- [ ] 实际prerequisite、可启用IRQ/worker和队列/客户端/STOP；真实reset和旧消息隔离后，才建立本代RX/READY。

### R5.17 Linux IRQ/work 接收 adapter 离线阶段（2026-11-15）

- [x] 默认关闭 adapter 组合 MMIO/queue/drain；单一 IRQ disable 深度、不可覆盖的排队代号、锁外 STOP 同步及新代际屏障，见 [接收层](MODEM-SCP-RECEIVE.md)。
- [x] process-context RX callback 契约与只读 resource prerequisite helper；实际 C 联动 ASan/UBSan、资源/既有回归、启用/默认 Image.gz/modules、符号隔离及 strict checkpatch 通过。
- [x] 唯一 owner prerequisite wrapper 与新 constructor 互斥替换接入；R5.18 已验证 dormant/no-I/O 状态，reset generation 仍0。
- [ ] 真实 reset 及旧消息隔离、客户端/固件条件完成后，才允许 start/IRQ enable/completion/ACK 与本代 READY。

本轮不刷写/重启；设备仍为 fba1be648ead，USB只读复查六页映射、零寄存器操作、五IRQ masked、26M pin有效。新 adapter 尚无 platform caller，不增加基带验收。

### R5.18 唯一 owner 接入静默 receive constructor（2026-11-15）

- [x] 默认关闭 RECEIVE_RESERVE，互斥替换旧 IRQ reservation；同一 owner 持有时钟、SPM、MMIO 与 transport，状态属性选择新 adapter，见 [静默接入](MODEM-SCP-RECEIVE-OWNER.md)。
- [x] 实际 prerequisite wrapper：owner mutex、reset generation gate、pin/26M只读检查及采样后时钟复查；当前 generation 始终0、无 start caller。
- [x] 三种 owner 路径与 callback/SMC sanitizer、既有回归、启用/默认 Image.gz/modules、符号隔离、两份打包DTB资源检查及strict checkpatch通过；实验DTS/defconfig恢复。
- [x] 4ed57fd98c40 上机：五个新action且masked，所有计数0、无prepare/寄存器访问；26M pin、USB/Wi-Fi各三轮、8核/存储/rootfs与boot回读通过，设备保留主线。
- [ ] 真正 reset/旧消息隔离及客户端条件完成后，才允许建立代际并调用 start；尚未启用IRQ或启动SCP/基带。

### R5.19 reset/恢复来源审计与纯CPU布局检查（2026-11-15）

- [x] 对照A/V/Q：初始化仅release、恢复双核SET→TCM/DRAM恢复→core0 release；WFI/void等待不是reset证明，mailbox没有显式代际隔离，见 [reset/恢复契约](MODEM-SCP-RESET-RESTORE.md)。
- [x] 实际结构编译确认header A/V/Q=72/72/60，本机68；新增默认关闭restore planner，仅几何检查，无caller或硬件动作。
- [x] 实际decoder/planner ASan/UBSan、10000合法布局/20000突变、A/V memory及protocol回归、启用/默认Image.gz/modules、符号隔离和strict checkpatch通过。
- [ ] 合并core0/core1/TCM资源归属，替换observer窗口；先受限观测/验证core1与访问条件，再设计assert-only步骤。
- [ ] 明确所有发送源停止证据、mailbox/completion/GIC旧消息隔离、LK loader与DRAM backup来源/有效期及缓存权限；之后才允许恢复复制、建立generation与release。

本轮完全离线，不连接/刷写/重启设备；没有新boot.img或硬件支持验收。reset_generation仍0，start无caller，不启动SCP/MD。


### R5.20 core0/core1/TCM 统一映射归属（2026-11-15）

- [x] 对照4.19与可用6.6，确认core0/core1/TCM精确资源；默认关闭新选项，在现有boot-lifetime owner取得完整三窗口non-posted映射，见 [资源归属](MODEM-SCP-CORE-TCM-OWNER.md)。
- [x] 新选项与legacy core0/TCM/pending reader互斥；全部几何先验、映射全集发布、失败devres回收；sysfs仅报告bookkeeping，零寄存器/TCM读写，无reset/start caller。
- [x] 实际C四分支ASan/UBSan、缺失/错误资源与各位置失败、Kconfig互斥、启用/默认Image.gz/modules、DT/schema/fixture和strict checkpatch通过。
- [x] db337399ee04实机：九块资源归唯一owner，五IRQ masked/CPU计数0、MMIO/TCM读写0、generation0；26M pin、USB/Wi-Fi各三轮、8核/RO存储和boot回读通过，设备保留主线。
- [ ] 迁移core0/精确header受限读取至同一owner；审查core1只读allowlist及双核采样前后条件，再上机验证，不重新启用legacy映射。
- [ ] 双核停止证据、mailbox/GIC/CPU旧消息隔离和固件备份来源仍未闭合；未做reset、restore、IRQ enable或启动SCP/MD。


### R5.21 统一 owner 双核/header 受限观测（2026-11-15）

- [x] 默认关闭 OWNER_OBSERVE，在既有映射和同一owner mutex下验证显式pin、26M/完整SPM投票和TOPCK前后条件；两核仅读0/4/0x70，精确68/72-byte header，见 [只读观测](MODEM-SCP-OWNER-OBSERVE.md)。
- [x] constructor零寄存器/TCM/SMC访问；独立DT保留区检查，CPU planner只报告geometry；不新建映射、不导出原始header、保留source/stopped/READY unknown。
- [x] 实际helper/constructor sanitizer、owner五分支及既有回归、启用/默认ARM64构建、Kconfig互斥、schema与strict checkpatch通过。
- [x] cebf84a7d29e实机：未pin两入口EAGAIN且零读；pin后两核受限值稳定0，header68、geometry valid1；USB/Wi-Fi各三轮计数精确，core/TCM最终252/252，所有写入与IRQ/worker事件0，已有功能和boot回读通过。
- [ ] 下一步建立双核assert-only的停止证据/超时契约和mailbox/GIC/CPU队列旧消息隔离；本轮样本不证明stopped，不加reset写或新generation。
- [ ] loader/backup来源及一致性仍待证明；无restore、IRQ enable、receive start或SCP/MD启动。

### R5.22 双核强制SET实测（2026-11-16）

- [x] 复核并保留GPU OPP/供电耦合、MFGPLL及LVTS/cooling更新。
- [x] 默认关闭assert接口：显式pin检查、锁外STOP、双核SET→DSB→读回；一次请求、不自动重试，见 [SET实测](MODEM-SCP-RESET-ASSERT.md)。
- [x] 实际后端/owner定向sanitizer、启用ARM64构建、strict checkpatch通过；减少无关回归及重复刷机。
- [x] 248c64a7dd23实际两次SET写；两核bit0仍0、EIO，不能验收reset成功；USB/Wi-Fi正常、IRQ全masked、TCM未写、generation0；匹配GPU模块临时加载成功，LVTS可读。
- [ ] 优先核对SCP内部时钟、供电/DRAM请求、AP访问权限及SET可读语义；合并相关修正和有效性验证，不拆多个纯观测刷机。
- [ ] reset有效后整合mailbox旧消息丢弃、generation/READY与恢复/释放；本次结果不足以直接进入restore/release。

### R5.23 初始释放与READY1（2026-11-16）

- [x] 不刷机，用当前主线完成一次2秒GPR1/2→core0 CLR实验；PC变化64次，新mailbox3通知0x9000，channel22 READY1的size=0x180000。结束重新SET双核，见[首次运行](MODEM-SCP-INITIAL-KICK.md)。
- [x] 实测CLR后bit0=1、SET后bit0=0；修正上一轮反向判据、保留raw读回，补channel9/22共同READY decoder；定向sanitizer/ARM64构建通过。
- [x] USB/Wi-Fi正常，IRQ仍masked、generation0；旧pending保留，未ACK，未启动MD。没有添加猜测的SMC或内部时钟写入。
- [ ] 合并一次初始启动owner：STOP/旧通知丢弃、代际、全RX队列与READY0/1、GPR1/2/CLR和最小logger策略；作为一个功能里程碑测试，不拆纯观测刷机。
- [ ] 正式READY后接AP awake/CCCI，再推进MD；完整restore不作为LK已载入镜像首次释放的前置项目。

### R5.24 整合初始启动 / IRQ / READY（2026-11-16）

- [x] 默认关闭 initial_boot 一次实验：统一 STOP、双核 SET、header/share、旧通知丢弃、generation、全 RX、core0 CLR 与 READY0/1 验证，见[集成启动](MODEM-SCP-INITIAL-BOOT.md)。
- [x] 各阶段失败、超时、错误代际及通知丢弃 ASan/UBSan 通过；不再拆资源映射或纯观测刷机。
- [x] b74f21c0411e/949a860a1a85 两轮实测新 READY1；修复 GIC lazy-disable 后 STOP 硬件 masked=5，双核SET、generation0、USB/Wi-Fi正常。硬件旧pending均0，非零丢弃路径为模型覆盖。
- [ ] 接持续事件消费、AP awake / APCCCI，然后进入 MD 初始化；首次启动不依赖完整备份恢复器。

### R5.25 SCP 常驻、AP awake 与受限 APCCCI（2026-11-16）

- [x] 常驻 RX-worker 消费、真实READY等待、共享awake get/put、受限一次MD-invalid TX及异步故障STOP/双核SET，见[常驻接入](MODEM-SCP-RUNTIME.md)。
- [x] 实际生命周期/consumer/TX/编码定向ASan/UBSan通过；包含错误代际、超时、握手失败、旧消息拒绝与GPR恢复。
- [x] e8509e81dbc3 实机常驻约49秒，READY1、awake三次配对、一次MD-invalid传输完成；无APCCCI应用层回复。STOP双核SET/GIC五路masked、USB/Wi-Fi及GPU/LVTS正常；未启动MD。
- [ ] 按反馈推进MD资源、电源/复位和CCIF/CCISM，恢复器不阻塞首次通信。


### R7 6297 SMEM 子区与bank跨度（2026-11-16）

- [x] 对照A/V/Q及历史4.19子区输出，解释缓存0x80000差值；实现完整LK链验证后的NC默认补全/cached aggregate解析及独立AP/MD边界，见[布局实现](MODEM-SMEM.md)。
- [x] runtime/CCISM/NVRAM-cache必需大小、别名/重复/截断/溢出与失败清零测试、实际vendor ABI核对、启用Image.gz/modules及strict checkpatch通过。
- [x] 统一MD owner保存布局/供电基线，显式附着genpd，增加继承LK ON的CHECK_DONE/接管断电及冷循环；完成离线验证，见[平台层](MODEM-PLATFORM.md)。未实测上下电。
- [ ] 接普通CCIF控制环；CCIF2保持单独桥归属，与SCP真实状态机整合。和MD接管/冷循环合并上机，不拆纯资源测试。
- [ ] 准备FS/NVRAM工作副本及服务门控，再释放MD验证HS1/HS2。新子区tag解析与MD电源切换仍待下一功能组实测，本轮未刷机。


### R7.1 普通 CCIF / 6297 环离线集成（2026-11-16）

- [x] 默认关闭CCIF扩展归同一MD owner：AP/MD精确窗口、两路IRQ始终masked、ID19/20联合WC映射，probe零I/O，见[CCIF](MODEM-CCIF.md)。
- [x] 本机A/V6297正常/异常各16槽，含零槽；实际CPU RX/TX回绕、元数据校验、成功发布指针及读写屏障。
- [x] 一次prepare整合环格式化/读回、CCIF0复位、双SRAM与ID13 debug footer；stop先验masked，故障保留电源/时钟。
- [x] 实际后端与抽取生命周期sanitizer、A/V表比对、平台/域/SMEM回归、启用ARM64 Image.gz/modules/modpost、默认DTB/schema和strict checkpatch通过。
- [ ] 合并LK布局→继承ON接管→冷上电→CCIF准备→关电实测；目前没有新硬件验收，不启IRQ或MD CPU。
- [ ] 接IRQ/worker、控制通道/异常与runtime握手；整合SCP/CCIF2/CCISM和FS/RPC/NVRAM服务后才放行MD及HS1/HS2。
