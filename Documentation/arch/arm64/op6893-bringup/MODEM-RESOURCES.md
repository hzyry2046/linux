<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 基带 M1：离线资源契约与补丁拆分

2026-11-14，AI 辅助源码审计。A/V/Q/M 的定义见 [总计划](MODEM-PLAN.md)。
本轮仅读取本地源码和保存的 ACK DTB，没有访问设备、调用 SMC、重启或刷写。
以下是驱动实现依据和候选边界。随后已完成
[R1/R2 第一批静态资源与依赖检查](MODEM-R1-R2.md)，默认不启用；
MD 电源控制、SCP 和完整 M1 仍未实现，没有主线基带运行验收。

建议把实现分成 MD 电源域、MD 平台控制、SCP RV 后端、CCISM 桥四部分。
电源域负责 MTCMOS 和总线保护；平台层负责供电生命周期、源时钟和 ATF
启动请求；SCP 后端负责 RV 固件及 mailbox；桥独占 CCIF2 与 CCISM 状态机。
CCIF AP↔MD HIF 与桥分别持有自己的资源，不能各自重置同一块硬件。

## 证据和复核方式

[资源审计清单](evidence/modem-resource-audit.json)保存选定源码 SHA256、
匹配符号的行号、历史 FDT 的白名单属性，以及解析后的时钟 provider/ID。
源码文件指纹反映工作树内容，HEAD 只用于标记底本；它们不证明实机行为。
早期 [清单](evidence/modem-kernel-audit.json)保持为当时快照：其中 SCP CM4
文件只是初始调查入口，本轮已经确认实际应追踪 **RV 分支**。

复核工具不连接设备，不哈希 DTB，也不导出未列入白名单的属性：

```sh
python3 Documentation/arch/arm64/op6893-bringup/tools/audit_modem_resources.py \
  --android /data/src/kernel_oddo_mt6893 \
  --vendor /data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/kernel/kernel_device_modules-6.6 \
  --mainline /data/src/mainline/linux \
  --qqcandy /data/src/mainline/linux-qqcandy-6.18 \
  --saved-dtb /data/src/mainline/mt6893-direct/evidence/ack-live.dtb \
  --date 2026-11-14
```

需要 Python `libfdt`。输出 reg 保留父总线的大端 cell 顺序，未做地址翻译；
本文涉及的历史根节点为两 address cells、两 size cells。IRQ 数字均指 GIC SPI
编号，不是 Linux virq。历史 `/scp@10700000/status` 的 `okay` 缺尾部 NUL，
工具单独标记；投影用于审计，不是建议原样复制 vendor DT。

## 资源所有权

|资源|ACK 事实|主线候选归属和约束|
|---|---|---|
|MD1 MTCMOS|`scp-sys-md1-main` 是 PGATE 包装的电源序列|由现有 scpsys provider 扩展 MD genpd；不能作为普通 gate 重复实现|
|SPM / infracfg|电源、保护、源时钟、SCP awake 共用寄存器块|通过现有 provider/syscon 分工，序列串行化；不能重复申请独占整个地址范围|
|SID3 VBUCK1/3/4|分别为 VMODEM、VNR、VSRAM_MD|MT6315 regulator provider + MD consumer；先明确停机/运行时电压所有权|
|MT6359P VPU|ACK 作为 VRFDIG 保存/恢复 VOSEL|第四路 MD supply；R1 随后补入默认 disabled 的 `buck_vpu` 本地节点|
|AP↔MD CCIF|AP `0x10209000`、MD `0x1020a000`，各 `0x1000`|单一 HIF owner；SPI 194/195；SMEM 就绪前不能 reset/清 SRAM|
|CCIF2|AP `0x1023c000`、MD `0x1023d000`，历史独立节点各 `0x1000`|CCISM 桥独占两个时钟及 ACK；不能继续由 HIF 同时管理|
|SCP RV|TCM、配置、mailbox、awake、DVFS、固件及保留内存|独立后端；真实 READY notifier 后才能进入 CCISM 握手|
|MD SMEM / CCISM|由 LK 布局及 region ID 确定|由布局层验证、HIF/桥按授权阶段使用；不能按 Q 的偏移静态切割|
|DPMAIF v2|四窗、SPI 209、两个时钟|数据面单独引入；不因控制面就绪而自动运行 DMA|

## 供电：三路 SID3 加 VRFDIG

A `drivers/regulator/mt6315-misc.c:mt6315_S3_default_vosel()` 第一次读取
**DA** VBUCK1/3/4 VOSEL，随后恢复到 **RG** VOSEL。其头文件将 DA 映射到
各路 `DBG0`，RG 映射到 `BUCK_TOP_ELR0/4/6`。M 的 MT6315 regulator
`get_voltage_sel` 读取 ELR 指令值；这与 DA 实际 DVFS 电压不是同一项观测。
V 的 `md_s3_vosel_restore()` 用 `regulator_get_voltage()` 保存/恢复三路，
不能据此声称已经逐字复现 A 的电压契约。

A `drivers/misc/mediatek/pmic/mt6359p/v1/pmic.c:vmd1_pmic_setting_on()`
在 SID3 处理之外，还恢复 `PMIC_RG_BUCK_VPU_VOSEL`，注释明确为 VRFDIG。
它的 off 函数只有日志，不能推导“MD 域关闭后 AP 应关闭这四路 regulator”。
通用 `mt6359.dtsi` 有 VPU 节点，但实际使用的是独立的
`mt6893-op6893-boot.dts`，其 regulator 子节点在审计时没有 VPU；不能把前者
存在当作 boot DT 已有 consumer phandle。M regulator 驱动已有 `buck_vpu`
描述，仍需检查实际 PMIC variant 和板级绑定。

拟补 SID3 `pmic@3`，使用现有 `mediatek,mt6315-regulator` 和
`reg = <3 SPMI_USID>`，描述 `vbuck1/3/4`，再补 VPU 的本地引用。
`md-vmodem/vnr/vsram/vdigrf-supply` 仅为待审 consumer 命名，尚非正式 binding。
驱动里的 `pvdd1/3/4` 是输入 supply，不能用来替代 MD consumer 的命名。

第一阶段不写固定启动电压，也不加未经确认的 min/max、always-on 约束。
但“只注册 regulator 一定零写入”仍需核对 driver probe 与 regulator core
约束路径，不能靠节点注释保证。V 的全局 `3_vbuck*` 名称补查、缺路后缓存
缺失、忽略写错误等策略不作为主线底本。

后续实现必须显式区分：LK 交接时可信启动快照、MD 停机状态、电源恢复阶段、
MD 运行时 DVFS。运行中的 MD 持有电压控制权，AP 不能任意写回第一次读值。
VMODEM/VSRAM_MD 的差压、上升/下降顺序、settle 时间及快照有效性尚未闭合，
因此目前只确定 provider/consumer 关系，不把电压恢复变成自动 probe 行为。

## MD 电源：AP MTCMOS 与 ATF 启动分开

A `drivers/clk/mediatek/clk-mt6885-pg.c:spm_mtcmos_ctrl_md1()` 由 AP 直接
操作 MTCMOS；V `clk-mt6893-pg.c` 恢复了这个 PGATE。V 平台代码还专门
处理“没有 dev.pm_domain 时改用 PGATE”的路径：没有附着域的 runtime PM
成功返回并不证明硬件上电。

MD1 的 SPM 控制为 `+0x300`，PWR_STATUS 的 bit 0，外部 buck 隔离为
SPM `+0x398` bits 0/1。总线保护相对 infracfg：

|步骤|SET / CLR / ACK offsets|mask|
|---|---|---|
|step1|`0x2a0 / 0x2a4 / 0x228`|bit 7|
|step2_0|`0xb84 / 0xb88 / 0xb90`|bits 10/21/29|
|step2_1|`0xbb8 / 0xbbc / 0xbc4`|bits 6/7|

A 先写 `POWERON_CONFIG_EN = (0xb16 << 16) | 1`。其开/关顺序如下：

1. ON：去外部 buck 隔离 → 置 RESET_B → 置 PWR_ON → 等待 power ACK →
   依次释放 step2_0、step2_1、step1。A 没有轮询保护释放 ACK。
2. OFF：依次设置 step1、step2_0、step2_1 并各自等 ACK → 清 PWR_ON →
   **等 power ACK 关闭** → 设置外部 buck 隔离 → 清 RESET_B。

M 通用非 secure `MODEM_PWRSEQ` 并不完全相同：
`scpsys_power_off_internal()` 提前设置外部隔离，
`scpsys_modem_pwrseq_off()` 又在等待 power ACK 前清 RESET_B。
因此需要局限于本 SoC 的序列实现或经审查的通用扩展；仅补 domain data/flags
还不足以复现 A。厂商无限轮询必须改为有界等待，并明确超时后哪些资源仍被
持有；不能超时后继续触碰已无响应的 MD MMIO，也不能随意倒序恢复未知状态。

平台 `md_cd_power_on()` 还包含 PMIC 恢复、MD_SRCCLKENA 低字节置 `0x21`、
SPM 解锁与 `+8` bit 21、条件性的 flight mode 请求、最后打开 MD PGATE。
`md_cd_let_md_go()` 才发 ATF 启动请求。A 的完整 `md_cd_start()` 在上电前后
还穿插 first-boot SMEM 清理、HIF 分阶段启动及 IRQ 使能，不能把上述局部序列
视为完整启动状态机。A 关机中对 APU/CONN CG_CLR 的全位写也不能未经核对照搬。

### ATF 调用契约

A ARM64 完整 function ID 为 `MTK_SIP_SMC_CMD(0x505)` = `0xc2000505`。
下表用 x1 表示请求号、x2 表示子请求，均来自调用方源码，未反向验证 ATF 实现。

|x1|x2 / 其余参数|ACK 用途与边界|
|---|---|---|
|0|debug register 请求|调试操作，不归类为无副作用查询|
|1/2/3/4|各 bank/SIB remap 参数|地址映射配置，M0/M1 资源枚举不执行|
|5|0：AP_MDSRC_REQ，x3 为 lock；2：settle；1：ACK|源时钟请求；A settle 仅接受 1..9，否则采用 3 ms 回退|
|6|0：KERNEL_BOOT_UP|释放/启动 MD，不是电源域 on 的替代|
|6|1：LK_BOOT_UP；2：CHECK_FLAG；3：CHECK_DONE；4：BOOT_STATUS|区分 boot 动作和状态查询；不能把整个 helper 当成只读|
|7|flight mode 布尔值|会改变状态；不能当 capability 探测|
|12|SCP_INFO_TO_SAVE|枚举存在，本轮在选定实际 A SCP/CCCI 路径未定位调用，暂不虚构必需步骤|
|13|SCP_CLK_SET_DONE|A 平台和 V 桥中有实际调用，需放到正确 CCIF2 生命周期|

A `mt_secure_call()` 仅返回 `res.a0`，而直接 `arm_smccc_smc()` 的路径有时
使用 a1..a3。新封装必须逐调用定义返回值，不能照抄忽略启动返回值的策略。
`md_start_platform()` 首次启动轮询 `(6,3)`（100 次、间隔 20 ms），读取
`(6,2)/(6,4)` 后会 **调用 MD power_off**；它不是被动状态检查入口。
Q/通用域的 secure enable/disable 18/19 不属于 A 已确认契约，不能试调用来
“确认支持”。现阶段既不调用这些接口，也不把未知返回值当成功。

## CCIF：六个 HIF 时钟，两个桥时钟

历史 ccifdriver 的八个 clock-names，在 A `ccci_hif_ccif.c` 中实际分为
六个 `ccif_clk_table` 和两个 `scp_clk_table`。MT6893 同样有 CCIF2 两窗：
历史 FDT 有独立 `ap_ccif2/md_ccif2` 节点；A 关钟函数又硬编码映射这两个
地址各 `0x20`，向 `ACK +0x14` 写 `0xffff` 后关钟。不能因 ccifdriver 仅有
两组 reg 就认为 CCIF2 是 Q 独有硬件。

下表为 A `clk-mt6885.c` 与历史 clock phandle 对照，ID 属于该树 infracfg：

|clock|ID|SET / CLR / STA offsets|bit|A 实现|
|---|---|---|---|---|
|CCIF AP / MD|33 / 35|`0x88 / 0x8c / 0x94`|23 / 26|普通 gate|
|CCIF1 AP / MD|28 / 29|同上|12 / 13|普通 gate|
|CCIF2 AP / MD|68 / 69|`0xc0 / 0xc4 / 0xc8`|16 / 17|`GATE_IFRAO4_IGN`，dummy ops|
|CCIF4 MD / CCIF5 MD|76 / 67|同上|29 / 10|同为 dummy ops|
|DPMAIF bus|39|`0xa4 / 0xa8 / 0xac`|3|普通 gate，parent `axi_ck`|
|DPMAIF main|74|`0xc0 / 0xc4 / 0xc8`|26|普通 gate，parent `dpmaif_main_ck`|

`GATE_IFRAO4_IGN` 的 enable/disable 不实际切换 gate，因此 vendor CCF 成功
不是这些位可安全切换的实测证据。首版不能把 dummy 直接替换成真实写操作。
新增时钟应扩展当前 infracfg provider，不能注册第二个重叠 provider；现有
AXI 频率观察节点也不等于已经实现可管理的 AXI mux/parent 链。

AP↔MD reset 在 `ccci_reset_ccif_hw()` 中使用 infracfg `0x150/0x154` bit 8，
随后清两侧 512 B SRAM 并写入末尾 debug SMEM magic/address/size。它有写内存
和暴露地址的副作用，必须等布局及所有权就绪。没有据此确认 CCIF2 的 reset
位，不能将 bit 8 外推给桥。桥的关钟 ACK 操作与 reset 操作也应分开。

V 将 CCIF2 两窗和时钟移到独立桥节点，但当前保存 ACK FDT 没有该桥节点。
主线需要本地描述和唯一 owner；CCF 引用计数不足以协调两个 owner 的 ACK、
SRAM 清理或 reset。资源缺失必须报依赖错误，不保留“空指针跳过也算成功”。

## SCP RV：映射、共享内存和固件边界

A `mt6893_defconfig` 开启 SCP，未开启 `CONFIG_MTK_TINYSYS_SCP_CM4_SUPPORT`；
V 的 SCP Makefile 在这种配置选择 `rv/`。不能套用 CM4 的 index 3=L1C：

|reg index|历史 reg-name|地址 / 长度|
|---|---|---|
|0|scp_sram_base|`0x10500000 / 0x180000`|
|1|scp_cfgreg|`0x10724000 / 0x1000`|
|2|scp_clkreg|`0x10721000 / 0x1000`|
|3 / 4|scp_cfgreg_core0 / core1|`0x10730000 / 0x1000`、`0x10740000 / 0x1000`|
|5|scp_bus_tracker|`0x10752000 / 0x1000`|
|6|scp_l1creg|`0x10760000 / 0x40000`|
|7|scp_cfgreg_sec|`0x107a5000 / 4`|
|8..27|五组 mailbox base/set/clr/init|base 从 `0x107fb000` 到 `0x107ff000`，步长 `0x1000`；详见投影|

SCP IRQ 为 SPI 434..440，level high；`core_0=enable`、`core_nums=2`，但没有
core_1 属性，不能仅因两组 core 寄存器或 core_nums 就自行启动第二核。
五组 mailbox 的 send/recv/legacy/feature/memory 表已保存为硬件属性投影，
需要按 RV 代码逐字段解释；feature ID 不能直接当数组顺序。V 针对本机已有
下划线旧属性、legacy memory pair 与新 triple 等兼容处理，要逐项保留语义。

`scp_clk_ctrl@10721000` 与 SCP index 2 重叠，`scp_infra@10001000` 与现有
infracfg 重叠；V 专门修过因 provider 已占用导致 SCP awake 地址为空的问题。
主线应使用共享 syscon/regmap 引用，协调 infracfg `+0xb10/+0xb14/+0xb18`
的 awake status/set/clear，不能再复制一个独占 platform device 来绕开冲突。
DVFS 的 mux 和 PLL0..7 时钟也要实际可用，不能仅改 compatible 后宣称 SCP ready。

内存有两种不同来源：历史 LK `mblock-21-SCP-reserved` 是静态
`0x9fa00000 / 0x500000`；`reserve-memory-scp_share` 是 size `0x320000`、
alignment `0x1000000` 的动态请求，没有静态 reg，且由 `scp_mem_key` 的
compatible 查找。二者不能直接合并，也不等于 MD 的 CCISM SMEM。
当前 FDT 合并不自动导入 vendor compatible，因此旧 SCP 内存查找代码不能
直接工作。后续采用本地 memory-region 引用，并校验实际分配、别名和保留区，
不根据 compatible 名字猜同一块内存。

RV `scp_region_info_init()/scp_recovery_init()` 读取 TCM region header，后续
会按其中的 `ap_loader_start/size`、regdump 和 AP DRAM 字段做物理映射，
包括 `ROUNDUP(ap_dram_size, 1024) * 4`。移植前必须校验长度单位、乘加溢出、
允许区域及映射权限，不能让固件提供的任意地址直接进入 ioremap。header
存在不证明固件正在运行；固件来源、LK 留存状态、加载和恢复职责仍待闭合。

## CCISM 握手不能用 ready 桩替代

注意：该CCISM交换在MD HS2/READY后发生，不能整体作为首次放行MD的前置
等待项。释放前准备真实SCP READY、资源/服务和consumer；随后执行下述交换。
后续实现与4.19/6.6时序差异见[CCISM](MODEM-CCISM.md)。

V `ccci_fsm_scp_c.c` 的实质流程是：

1. SCP READY notifier 注册 IPI，并建立 BOOTING 状态；AP 的 MD READY 事件
   等待支持的 SCP 状态、开启桥资源，然后向 MD 发 `CCISM_SHM_INIT`。
2. MD 返回 ACK 后定位 `SMEM_USER_CCISM_SCP`，**清整个区域**，再向 SCP
   发 `CCCI_OP_SHM_INIT`。这不是只读观察，必须先确认 EMI/SMEM 所有权。
3. SCP 返回 RBREADY，AP 才向 MD 发 `CCISM_SHM_INIT_DONE`；MD 完成后，
   AP 将 MD 状态经 IPI 发给 SCP。
4. SCP STOP 时还检查 MD 是否 READY；不能在 MD 运行时直接关 CCIF2。
   允许关钟时先 ACK，再释放时钟。

RV 使用 `mtk_ipi_register/send` 和 APCCCI channel 表；消息含 u16 md_id、
u16 op_id 与 data，长度由 send table 决定，有附加 magic 的形式，不能硬套
CM4 固定长度。V 的 SHM 地址发送仅取一个 u32，主线必须检查物理地址是否
可表达、AP/MD/SCP view 是否一致，不能在 arm64 隐式截断 `phys_addr_t`。
worker/notifier/IRQ 生命周期、停止时排空、超时和重启代际都需要显式实现。

## 可实施的补丁组与验收门槛

以下为待实施顺序，本轮不添加可执行的上电入口：

|组|改动范围|进入下一步前的验收|
|---|---|---|
|R1|SID3 三路和 VPU 描述，MD supply 引用及绑定草案|板级 phandle、PMIC variant 和 consumer 对齐；probe/约束副作用审查；电压 DA/RG 与生命周期单列|
|R2|扩展现有 infracfg 的必要时钟接口|ID/parent/寄存器对应；普通与 dummy 分开处理；不擅自接管未验证 gate|
|R3|MT6893 MD genpd 与平台控制分层|精确表达 ACK 隔离/复位顺序；有界等待、逐步故障和持有状态；不使用未知 18/19|
|R4|CCIF HIF / CCIF2 桥资源分离|每个 MMIO/reset/ACK 唯一 owner；错误传播、时钟失败回收、SMEM 布局门槛|
|R5|SCP RV 后端骨架、mailbox、保留区及固件契约|不重叠抢占 provider；有界 header/地址验证；真实 READY 和停止/恢复路径|
|R6|CCISM FSM 与 MD 控制面整合|真实 ACK/RBREADY/init-done 时序；IPI 长度/地址/状态负例；禁止伪造 READY|

R1/R2 可以先做默认不启用的离线补丁，R3 必须先决定通用 genpd 扩展方式；
R5 可与平台层分别推进，MD 首次放行前必须闭合 R4/R5/R6。
代码阶段再运行相应编译、DT schema 和故障路径测试；资源描述本身不代表
上电可测。用户态/固件分析结果尚未就绪，不在这里重复其二进制逆向任务。

当前阻塞首次启动的未决项：可信启动电压与差压/时序、SCP 固件和 memory
契约、实际 LK tag/layout 验收、缓存 SMEM `0x80000` 差值、CCIF2 gate 的真实
写权限、ATF 返回值语义及失败后硬件状态。现有 USB/Wi-Fi 恢复路径保持为
后续实机实验前提，以上问题闭合前不以“试启动一次”代替资源验证。


## 2026-11-15 接续说明

以上保留初始离线审计的事实与待办。随后 M0 实机 LK 解析和 R1/R2 四路供电、
四个普通 CCIF 引用已验收，见 [供电记录](MODEM-RAILS.md)。R3 电源代码已
编译，但未实例化 MD 域、未运行电源序列。

[R5.1](MODEM-SCP.md) 已实现并验证完整 mailbox 布局与 CCISM wire 基础。
本机 `send_table`/`recv_table` 分别为三/四 cells，而 V 新接口可支持七 cells
RX；不能使用早期桥中未参与实际解析的 `recv_item_num=5` 注释推断格式。
本机 TX3 为 mailbox1/offset0/IRQ0，RX7 为 mailbox1/word offset28/IRQ14；
完整表不可裁剪后重排。SCP 固件/内存/clock/transport、CCIF2 owner 和真实
CCISM FSM 尚未完成，不把 helper 的解码结果当作硬件 READY。
