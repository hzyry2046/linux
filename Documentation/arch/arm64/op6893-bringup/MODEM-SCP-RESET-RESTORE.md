<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP reset / 非 secure 恢复：源码契约与布局检查

2026-11-15，HEAD `6db0f4606d6e` 工作树；AI 辅助源码分析、实现和测试，
按“继续推进”任务，接续 [静默 receive owner](MODEM-SCP-RECEIVE-OWNER.md)。
本轮完全离线，不连接、刷写、重启设备或接触固件 binary。上次验收设备为
`4ed57fd98c40`；没有新增硬件支持验收。

## 三套源码对照的结论

本文件中的 A 为 `/data/src/kernel_oddo_mt6893`；V 为
`/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/kernel/kernel_device_modules-6.6`；
Q 为 `/data/src/mainline/linux-qqcandy-6.18`。相关实现主要在
`drivers/misc/mediatek/scp/rv/{scp_helper.c,scp_helper.h,scp_awake.c,scp_reg.h}`，
以及 `drivers/soc/mediatek/mtk-mbox.c`。具体函数行号及文件/函数 SHA256
由 [源码审计脚本](tools/audit_modem_scp_reset.py) 复现并记录在
[结构化证据](evidence/modem-scp-reset-source-audit.json)。

|事项|A / V / Q 源码证据|移植决定|
|---|---|---|
|初始化 `reset_scp(SCP_ALL_ENABLE)`|通知 STOP、请求 bootstrap，写 share 地址/大小至 GPR1/2，CLR bit0 释放 core0；该函数没有直接 SET 或 full restore|不能将初始化成功解释为已执行完整 reset / 建立新代际|
|恢复 worker|先 SET core0/core1，后 `scp_sys_full_reset()`，再设置 GPR1/2、CLR core0|将“初始化释放”和“恢复重建”分开设计，不照搬函数名|
|halt 等待|检查 `B_CORE_HALT`，注释为 WFI；函数返回 void。V 超时按配置可能 BUG，A/Q 也不是有明确成功状态的 API|WFI 或函数返回不足以证明硬件 reset 完成、DMA 停止或旧消息隔离|
|普通恢复|清整个 TCM；复制 inherited loader；复制 CPU 缓存 header；清两核 live DRAM；从计算出的备份起点恢复一份 `ap_dram_size`|先验证全部源/目标跨度、所有权和备份来源，再考虑任何写操作|
|firmware 字段|helper/awake 没有 `request_firmware`；普通恢复未直接使用该字段加载 firmware|不能据固件文件存在或 span 合法就当作完成固件加载协议|
|mailbox probe|映射资源并 request_irq，没有显式写 pending clear|不能继承厂商 probe 就声称清除了旧 pending|
|恢复 worker 与 mailbox|没有显式 `mtk_mbox_clr_irq` 调用；核 reset 与 mailbox 的硬件复位关系未获得证据|SCP CPU reset 和 mailbox/GIC/CPU 队列的隔离须分别闭合|

以上为限定函数的源码控制流，不证明外部 LK/固件/其他驱动行为或芯片内部
复位连线。Q 的 secure release 会检查返回值，A 部分 secure helper 是直接
返回0的桩，V 则使用 SMC；不能根据相似枚举或成功返回互换 ABI。本机保存
DT 为 secure_dump disabled，本阶段 helper 只描述普通 non-secure 路径。
Q 的 generic `drivers/remoteproc/mtk_scp.c` match 表也没有 MT6893/MT6895，
不能直接把本机 raw 镜像交给通用 ELF loader 并认为加载路径相同。

### header ABI 差异

实际提取三套 `struct scp_region_info_st` 并编译 sizeof/offsetof：

|来源|编译结构尺寸|struct_size偏移|regdump字段偏移|
|---|---|---|---|
|A 4.19|72|28|44/48|
|V 6.6|72|28|44/48|
|Q mt6895|60|28|44/48|
|本机此前直接 TCM 实测|68|28|44/48 已按68-byte格式解码|

Q 的相同前缀不代表尾部兼容。最初把 Q 头加入现有 A/V 的72-byte静态断言
测试时被编译器拒绝；保留该失败日志，并用独立断言确认60，而不是放宽本机
decoder。普通 vendor restore 使用 `sizeof(scp_region_info_copy)`，主线未来
executor 应保留本次已验证快照的精确长度，不能凭另一棵树的 sizeof 填补尾部。
当前 decoder 和新 planner 仍只接受68/72；对60、未知版本或长度不一致均拒绝。

## 新增纯 CPU 恢复布局检查器

默认关闭 `OP6893_CCCI_SCP_RESTORE_PLAN`，依赖已有 PROTOCOL；只编译
`ccci-scp-restore.{c,h}`，没有 platform caller 或 sysfs 入口。
`ccci_scp_plan_restore()` 接受精确 CPU header 快照、核数以及独立可信的本次
firmware/share/TCM 窗口，成功仅返回几何跨度，不保存或导出原始 header。

检查策略：

1. 限定本机两核历史布局，TCM `0x10500000/0x180000`；三块可信窗口必须
   为非空、对齐且不溢出的32位物理范围，彼此不重叠。窗口不能从同一个
   不可信 header 中反推；检查器不能证明调用方的“可信”来源。
2. 使用既有68/72-byte decoder；loader、firmware、DRAM 必须存在。loader、
   firmware 和包含备份的完整 DRAM mapping 必须全部在 firmware reservation
   内且相互不重叠，防止只检查 live DRAM 而漏掉 backup 尾部。
3. loader 目标从 TCM 起点开始；header 目标从 TCM+4开始，长度等于输入
   快照长度。两者都需在容量内，header 完整位于 loader 目标内。header
   与 loader 的重叠是预期的顺序覆盖，未来须先复制 loader，再覆盖 header。
4. 先提升到u64，令 `R=roundup(ap_dram_size,1024)`：mapping=`4R`、
   live clear=`2R`、backup source=`dram_base+2R`、恢复复制长度仍仅为
   `ap_dram_size`。它不擅自复制第二份 core1 image 或把核数改1。
5. header backup_start 必须与计算结果相等，这是比普通 vendor 代码更严格
   的支持策略；不匹配就拒绝，不任选一条地址继续。regdump 仍不是恢复源，
   不为它提供映射；firmware span 只用于边界检查，不产生加载操作。
6. 任何失败清空完整输出。输入/输出不得重叠，成功也不建立 READY、
   reset_generation、映射权限、缓存一致性或备份有效性。

以合成的305120-byte DRAM举例：R=305152，live清零610304字节，完整映射
1220608字节；复制305120字节，从live后方的backup起点复制到live起点。
这些数字与此前实测尺寸一致，但本轮没有读取实际loader/backup内容。

**检查器不是可执行命令列表，更不授权 destructive 操作。** 没有 ioremap、
memcpy_toio/memset_io、SMC、reset/IRQ 操作，也不改变既有 transport。
源内容身份、有效期、固件认证、CPU/DMA 停止、EMI权限与内存映射属性仍须
未来 owner 单独建立。TCM 常量限制是本机支持策略，不是跨SoC通用接口。

## 必须闭合的真实 reset / 旧消息隔离流程

后续实现按以下顺序推进；不是本轮已执行的硬件步骤：

1. 合并 core0/core1/TCM 访问归属到唯一 owner，替换 observer 的既有窗口；
   不能在观察器仍持有 TCM header 页时另建整块、不同属性的别名。当前仅
   验证过 core0读回，core1和整块TCM访问能力尚未验收。
2. 关闭客户端新事务，使旧 READY/旧 owner generation 失效；调用 transport
   STOP，完成 IRQ/worker 同步、擦除队列、屏蔽全部源。保持bootstrap clock
   和boot-lifetime vote，不在reset间隙release共享资源。
3. 在已证明的同板控制语义下停止所有可能发送这些mailbox消息的核/总线主机，
   有限等待并取得停止证据；WFI、reset alias读回和单次SET写都不自动构成
   “全系统已停”的证明。超时应保持fault，不照搬继续恢复/BUG路径。
4. 只在旧发送源确实停止后，独立处理五组mailbox pending、completion及GIC
   状态，丢弃旧代CPU通知。尚无可执行的discard协议或核reset清mailbox证据；
   不能拿正常RX/drain当作清旧代工具，也不能读到零就认定不会再到达旧消息。
5. 确认本次LK载入的loader/firmware/DRAM备份来源、有效期、权限和映射一致性。
   布局planner只检查跨度；`remoteproc_scp`文件存在不填补这项证据。
   如果恢复，再按已验证长度和顺序完成TCM/DRAM操作及必要参数初始化。
6. 旧源与旧消息隔离成立后才发布owner的新generation、准备全部队列和消费者，
   在释放core0前确保新READY不会丢失；`receive_start()`只返回排队成功，
   不能把它当作已观测READY。GPR1/2应使用本次独立share保留区。
7. 释放reset后只接受本代正常READY事件；任何错误使全transport失效，保留
   IRQ屏蔽。是否重新assert reset、允许什么故障清理，仍需同一控制owner约束，
   不自动循环恢复。SCP_READY和CCCI RBREADY仍是两个不同阶段。

当前第1/3/4/5项都未闭合，因此保留reset_generation=0、start无调用者。
下一项具体实现是 core0/core1/TCM 资源统一与受限观测设计，随后才考虑
assert-only测试；不先放开release、恢复复制或未知pending清除。

## 验证及证据

- `test_modem_scp_restore.py` 编译实际decoder+planner，ASan/UBSan通过：
  精确68/72对象、60-byte拒绝、非对齐CPU输入、三块独立窗口/溢出/重叠、
  缺少必需映像、TCM/header边界、backup mismatch、1024字节边界、
  10000组合法随机布局与20000组header突变；错误输出全部清零。
- 既有memory测试（实际A/V结构）与protocol/layout回归通过；独立A/V/Q
  源码审计及72/72/60-byte编译断言通过。
- 显式启用和恢复默认ARM64 Image.gz/modules通过，编译日志无warning/error；
  启用vmlinux有planner符号、默认无，strict checkpatch为0/0/0。
- 没有DTS/binding更改，未打包新boot.img、未进行schema或实机验收。
  主机模型不证明硬件时序、总线可达性或固件有效性。

证据目录 `/data/src/mainline/mt6893-direct/evidence/scp-restore-plan/`；
[结构化验证](evidence/modem-scp-restore-validation.json)。


### 后续进度：R5.20

core0/core1/TCM 的静默资源归属已在 `db337399ee04` 实机验收，详见
[统一 owner](MODEM-SCP-CORE-TCM-OWNER.md)。旧 core0/header reader 已通过
配置互斥关闭，三个窗口尚无读写调用；受限读取迁移及双核停止证据仍待完成。
此更新不改变上文 R5.19 的离线验证范围，也未开放 reset/恢复或旧消息处理。

### 首启与停机之间的恢复源一致性

测试镜像 `caf2d7ca0e0e` 由主线直写 `boot` 后正常启动，USB SSH
和分区哈希一致，分区恢复只读。在显式 26 MHz pin 下，`start-check`
在释放 core0 前、双核 reset 别名读回为 asserted 时，校验首启 header
的布局；读完整个 8192 字节 loader 和 305120 字节 DRAM 备份，拒绝
全零或全 0xff，保留 header 快照和两段 CRC。检查失败不会放行 SCP。

两次实测：一次只启动 SCP 并收到 READY；另一次基带达到 HS2 和
CCISM RUNNING，先执行 `md_power off`，再停止 SCP。两次 STOP
后 `restore-check` 都返回成功，当前两段 CRC 与首启前一致。
CRC 只用于识别内容变化，没有导出 CRC、header 原文或固件字节。
本次不写恢复区，不证明内容认证、DMA 已停止或恢复后能收到新 READY。

### 干净停机后的 SCP 恢复执行

`runtime` 的 `restart` 只接在干净的 runtime stop 后：没有 SCP
租约、awake 引用或错误，接收 IRQ/work 已同步，且复核双核 reset
仍为 asserted、APCCCI 发送位空闲。分配新代之前，使用首启保存的
布局与 header，从原保留区读 loader/DRAM 备份到临时 CPU 缓冲区
并校验；清 TCM 和 live DRAM，恢复 loader/header/DRAM，然后读回
确认。不会改动备份源。丢弃复位前的已知入站通知并确认 pending 为零，
建立新的 RX 代次，释放 core0 后才接受 READY，并完成一次 awake 配对。

- `e923c18a14f6`：同一 AP 启动内，第二代 SCP 达到 READY；
  第三代租约通过真实基带的 HS2/CCISM RUNNING 和干净停机。
  随后的第四代恢复曾在 READY 前返回 `-EIO`，当时没有阶段诊断。
- `fd3f311a5e6e`：从主线直写 boot 后确认了新版本、只读标志和
  全分区哈希。第一代 SCP 上完成基带 HS2/CCISM、MD 关电和 SCP
  停机；同一 AP 启动内第 2 至 5 代均收到 READY、完成 awake 配对
  并能停机。taint 为 0，前一次 `-EIO` 未复现；镜像新增失败阶段
  和读回区域诊断，供下次复现使用。

### 基带关电后的 TCM 恢复失败

`5006e9c935c4` 和 `178ecc2ce674` 上，首轮 MD 达到 HS2 / CCISM RUNNING，
随后 MD1 确认 OFF、旧服务 FD 关闭，`md_boot=rearm` 成功。第二代 SCP 在
`restore-memory` 从 TCM 起始处读回 loader 不一致（`-EIO`）；两核保持
复位，未进行第二次 MD 上电或放行。`178ecc2ce674` 从主线写入 boot，
重启后版本、32 MiB 全分区哈希和只读标志均已复核。

`9d016e2a89aa` 使用与 vendor 一致的 32 位 TCM 写入和读回，仍在首字失败。
一次额外的 `restore-check` 通过，延时 3 秒也没有改变结果。
`178ecc2ce674` 的实验分支对照 4.19 等到两核 HALT 后再置复位并写 reboot
GPR；HALT 等待成功，但 loader 起始处仍读回不一致。这两项实验未合入。
停机本身的 CCIF BUSY 竞态通过推迟硬件 reset 到下一次 prepare 处理。

同一镜像在另一次 AP 启动内仅启动 SCP、确认 READY、STOP 并复核备份，
未接管或启动 MD；重新启动 SCP 仍在同一位置失败（`scp-only.log`）。
因此 MD 会话不是该故障的必要条件。下一步重点核查 4.19 的
SCP SRAM power-down 状态、时钟和互连资源。保留源 CRC、目标读回及
失败时不 release 的检查。证据见构建目录下
`backup/boot-write-md-rearm-v2/` 与 `backup/boot-write-md-rearm-178ecc2ce674/`。

### 同一 AP 启动内两次 MD 握手

`2281dbab1768` 将 TCM 校验移到 DRAM 写入之前；成功的 SCP-only
恢复通过了两阶段校验。随后 MD 关电后的 SCP 恢复在第一次 TCM 校验
就读回全零，确认该次故障不依赖后续 DRAM 写入。按实际地址重采后，
四个 SRAM power-down 寄存器在成功与失败样本均为零；SCP 内部
selector / sleep debug 分别为 `0x100 / 0x1` 与 `0x200 / 0x4`。
这只是相关性，不能单凭寄存器快照判定 TCM 实际供电。早期用拼接地址
采得的全零数据作废。

`99d53ce34639` 在 CCISM 停止、lease 释放后显式发送 vendor
`SCP_SLEEP_OFF`，随后成功恢复到第四代 READY。该次第二轮 MD 在
`cold-rails` 被阻止。新镜像 `b34941e0b420` 恢复首启指令电压，并
处理 SCP RX worker 在主动 STOP 时误报 `-ESHUTDOWN` 的竞态。

真机在同一 AP boot ID 内以 MD 第 6711/6712 代、SCP 第 1/2 代
分别到达 HS2 与 CCISM RUNNING；两轮最后均确认 MD1 OFF 和
CCISM STOPPED，SCP 停止后 taint 为 0。第二轮 HS2 后约 490 ms，
FS channel 15、普通 CCIF TX queue 4 的控制区校验返回
`-EBADMSG`。发送路径的该错误只来自 ring guard 或控制区的
长度/指针检查；本次没采到触发失败的字段。此故障仍锁存并阻止再次
rearm，未做第二代数据面或 IMS/VoLTE 发信和拨出测试。

镜像从主线写入 boot，重启后版本与全分区哈希一致，boot 与父盘均
恢复只读。外部证据：
`backup/boot-write-md-rearm-b34941e0b420/{booted,two-md}.log`，
以及 `backup/boot-write-md-rearm-2281dbab1768/{scp-clock,after-md-failure}.log`。

后续用带 CCIF 控制字诊断的 `716809b113d6` 在同一次 AP 启动内完成
MD 6711、6712、6713 三轮（SCP 第 1、2、3 代），每轮均达到 HS2 和
CCISM RUNNING，最后关电并关闭服务 FD。第三轮在 HS2 后保持 20 秒，
完成 5879 次服务发送，最终 CCIF RX/TX 和服务错误均为零；设备 taint
为 0。此前的 `-EBADMSG` 未复现，诊断保留，不能据此认定已修复。
蜂窝数据面跨 MD 重启待验。证据见
`backup/boot-write-md-rearm-716809b113d6/{booted,two-md,third-md,ring}.log`。

### 重建后的 AT、PDP 和 HS2 对照

仍用 `716809b113d6`，在上述同一 AP 启动内继续到 MD 6714–6717、
SCP 第 4–7 代。SCP 每轮都到 READY；前三轮也到 HS2 和 CCISM RUNNING。
MD 6714/6715 的 basic MUX 都收到 DLCI 3 的 UA，但读取 SIM1 的
`CFUN?` 超时；第二次在 HS2 后延迟 12 秒并重试，结果不变。
MD 6716 的旧版 AT 通道能应答并读回 `CFUN: 1`，DPMAIF DL 环启动，
随后采集脚本把 sysfs 的 `net` 目录误当作文件，未发出 PDP 激活命令。

MD 6717 接受了 HS1，完成 3525 次 FS/RPC 服务发送，之后等不到 HS2，
dispatch 和 CCIF 均记录 `-ETIMEDOUT`。为做对照，同镜像重启 AP，
重新下发测试用 FS/RPC 数据。首轮 MD 6801 到达 HS2/CCISM RUNNING，
旧版 AT 正常、射频打开、DL 环启动；立即激活 PDP 时 `CGACT` 失败，
该次未先确认 packet attach。第二轮 MD 6802 再次在 HS1 后停在同样的
3525 次发送，等不到 HS2，尚未进入 AT 测试。两次 HS2 超时均能正常
关电并停止 SCP。各轮均未记录 CCIF ring `-EBADMSG`；部分成功到达 HS2
的样本记录了服务 TX `-EBUSY`，该错误允许重试，与 ring 拒绝分开看。

这轮仅确认重建后旧版 AT 和 DPMAIF DL 初始化可以工作，未验收 PDP 或
双栈流量。优先比较 HS2 成功和失败两条路径在第 3525 次服务发送前后的
请求类别及回复状态（只记录类别、计数和错误码），并确认 MD 是否继续
发请求。随后在确认 packet attach 后再做 PDP 对照。未测试 IMS/VoLTE
发信或拨出。日志见 `backup/boot-write-md-rearm-716809b113d6/` 下的
`fourth-md-data.log` 至 `seventh-md-data.log`、`ap-control.log`、
`ap-second-data.log` 和 `ap-second-final.log`。
