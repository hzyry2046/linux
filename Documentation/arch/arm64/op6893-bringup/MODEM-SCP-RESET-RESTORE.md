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

随后同镜像做了一组带服务操作号的对照。AP 首轮 MD 6801 先确认
packet attach，再激活 CID 1（CCMNI channel 0、UL queue 0）。
LTE AcT 7，IPv4 和 IPv6 DNS 均收到匹配回复，DPMAIF 上行完成
3 包、下行收到 4 包。退出时 CID、网口和策略路由均已清理，USB
管理路由正常，父平台完成停环和关电。

同一 AP 上的 MD 6802（SCP 第 2 代）第三次复现 HS1 后超时
（3525 次服务发送）。用户态共收到 1568 个请求，最后一个是
`CMPT_Read`（`0x1022`）；两轮在第 1568 个请求上的操作号相同，
回复均被内核端点接受。MD 6801 随即发出第 1569 个请求，
MD 6802 则不再发请求，直到会话被超时撤销。端点接受回复不代表
MD 已消费 CCIF 环中的回复。下一轮对照该事务的阶段掩码、状态、
长度和 CCIF 读指针，并区分 NVRAM 工作副本变化与传输停滞。日志见
`traced-first.log`、`traced-second.log` 和对应的 `*-ops.log`。

第二组同镜像对照再次确认 AP 首轮 LTE 双栈通过、热启 HS2 超时。
第 1568 个服务请求对应第 782 个 `CMPT_Read`；请求和 6512 字节回复
数据在两轮间逐字节一致（用一次性密钥的摘要比对，不导出原文）。
已采集的第 701–782 个 `CMPT_Read` 请求及回复数据也一致，最后一笔
请求掩码和完成掩码均为 `0x1f`，返回状态为 0。证据：
`backup/boot-write-md-rearm-716809b113d6/cmpt-*-ops.log`。

诊断镜像 `cba8916a22c2` 从主线直写 boot 后启动，版本和分区哈希
一致，boot 与父盘均恢复只读。首轮双栈通过；热启再次停在 3525 次
服务发送。MD 仍上电且超时尚未触发关电时，普通 FS TX queue 4
读指针与写指针均为 5120，AP busy bit 4 为 0。对照首轮 HS2 的
读写指针均为 20360，busy 同样为 0。失败样本没有滞留在该发送
队列的回复；这不能证明 MD 上层正确重组或处理了回复。设备正常
关电、SCP 停止、taint 为 0；此时诊断入口拒绝读取。
见 `backup/boot-write-md-rearm-cba8916a22c2/{ring-first,ring-second,final}.log`。

### 关射频后再关电的对照

从 Android 刷回 `cba8916a22c2`，确认运行版本和 boot 分区哈希。
首轮到达 HS2 后、打开 AT 前复现了 FS TX queue 4 的 `-EBADMSG`：
普通 ring bank 偏移 `0x7c0b4` 是 MD 写入的 TX 读指针，读值
`0x5bc` 在 `0x5000` 的环内但不是 8 字节对齐。同板 6.6
`ccci_ringbuf_move_rpointer()` 将读指针向上对齐到 8 字节；
保留现有对齐检查，暂不推断该读值的成因。此次正常关电且未强行
rearm，日志见 `rf-off-ring-fault.log`。

另一次 AP 启动，首轮确认附着并通过 LTE IPv4/IPv6 DNS。清理 PDP
后，`AT+CFUN=4` 收到 OK，读回复核 `CFUN: 4` 和 `CGATT: 0`；
关电前 PCM 也采到 `pcm_md1_sleep=1`。同一 AP 启动的第二轮
仍接受 HS1 后超时，服务发送计数为 3525，FS TX 读写指针均为
5120，busy bit 4 已清。已确认的射频关闭、分离及 MD sleep
不足以避免此故障。最终 MD 与 SCP 均停止，taint 为 0。
日志见同一备份目录的 `rf-confirm-{first,second,final}.log`。

### 还原用户态 FS 副本的对照

同一镜像、同一 AP 启动内，首轮 LTE 双栈通过并确认射频关闭和
packet detach。确认 MD1 OFF、旧服务 FD 断开和 SCP 停止后，
从与首轮相同的私有快照重建 `/tmp/op6893-fs`，聚合文件内容
哈希相同；保留内核与固件的正常热启路径，未清共享 NVRAM cache。
第二轮仍接受 HS1 后超时，服务发送计数 3525，FS TX 读写指针
均为 5120，busy 为 0。上一轮写回用户态 FS 文件不是该样本
超时的必要条件。MD、SCP 正常停止，taint 为 0。
见同一备份目录的 `fs-reseed-{first,second,final}.log`。

同板 6.6 的 `ap_md_mem.c` 在 `BOOT_WAITING_FOR_HS1` 执行
共享内存清理；其表项没有设置 `SMF_CLR_RESET`，额外清理仍只针对
CCB DHL 和 RAW DHL 前 1 KiB。另一个待核对的区别是 6.6 的
`md_cd_topclkgen_on/off()`：板上保存的 ACK DTB 没有
`mediatek,power-flow-config`，6.6 的默认值不跳过这两个操作；
主线没有相应的 MD clock-mode 处理。这个差异尚未在实机上与
HS2 超时建立关联。6.6 还接收独立 MD WDT IRQ，当前主线未接入。

同一镜像再做纯握手对照，两轮均不打开 AT、不启用射频，也不启动
DPMAIF。第一次首轮到 HS2 后约 705 ms 再现 FS TX queue 4 读指针
未对齐，值为 `0xadc`，错误锁存后 rearm 被拒，设备正常关停。
重做时，首轮和热启轮都到达 HS2/CCISM RUNNING，各保持 20 秒
再关电；热启轮完成 5789 次服务发送，最终 CCIF RX/TX 错误为零，
MD、SCP 均正常停止，taint 为 0。

因此该镜像在纯握手条件下仍可热启成功，但这既不能证明前一代
DPMAIF 使用是 HS2 超时的必要条件，也不能证明它足以触发超时。
下一组对照可只在首轮启停 DL 环、不打开射频，并保持相同的
HS2 后停留时间。读指针错误可独立出现于首轮、无需数据面。
证据见同一备份目录的 `hs-only-final.log` 和
`hs-only-repeat-{first,second,final}.log`。

在纯握手复测成功的同一次 AP 启动内继续跑 MD 6803 和 6804。
6803 到 HS2/CCISM RUNNING 后只启用 DPMAIF DL（BAT 8192、PIT
16384），UL 未启动、网口保持 down，未打开 AT、射频或 PDP。
保持 20 秒后正常关电，走常规 DPMAIF 停环及 AO/PD 复位。
紧接着的 6804 在 HS1 后重现 `-ETIMEDOUT`：服务发送 3525 次，
FS TX 读写指针均为 5120，busy 为 0，随后 MD 和 SCP 正常停止。
在该对照样本中，无需注册或实际 IP 流量即可复现；下一步区分
DL 自身的停环与关电后 AO/PD 复位的影响。证据见
`dl-only-{6803,6804,final}.log`。

### 仅执行关电后 DPMAIF 复位的对照（2026-11-21）

诊断镜像 `56728c660a71` 使用默认关闭的临时 `reset_unused` 参数。
MD 6801 只跑握手，到 HS2 后保持约 20 秒；未打开 AT、射频或 PDP，
未启用 DPMAIF 环。仅在关电前打开参数，日志确认执行
`post-OFF reset: rings used=0`，随后关闭参数。MD 6802 接受 HS1，
但等不到 HS2（`-ETIMEDOUT`），同样完成 3525 次服务发送。
MD 与 SCP 最终均停止，内核 taint 为 0。证据见
`backup/boot-write-md-rearm-56728c660a71/{first,after-reset,second,final}.log`。

这个样本表明复现不要求上一代实际使用 DMA 环。优先比较关电后的
AO/PD 复位、保护位和时钟顺序；单次样本还不能锁定具体操作。

同板 6.6 的 `fsm/ccci_fsm.c` 先在 `WAITING_TO_STOP` 停止队列，
调用 `ccci_md_stop()` 关电，再在 `GATED` 经
`hif/ccci_hif.c:ccci_hif_state_notification()` 调用 `dpmaif_stop()`。
因此最终硬件复位位于 MD 关电之后，与主线一致。v2 的 INFRA
保护位、复位寄存器和掩码也相同；区别是 6.6 在复位脉冲前释放
DPMAIF 两个时钟引用。另一个独立区别是 6.6 在
`BOOT_WAITING_FOR_HS1` 就启动 DPMAIF（置保护位、初始化硬件和环、
开 IRQ）；主线从 HS2 之后的实验流程按需启动数据面。

镜像 `03d140badce2` 在 MD 6801 握手成功、保持 20 秒并关电后，
在不持有 DPMAIF 时钟引用的情况下执行同一组 INFRA 写入，之后才
持钟读回并校验复位结果。首轮从未启用 DMA 环，也未打开 AT、射频
或 PDP。MD 6802 仍接受 HS1 后超时（`-110`）：服务发送 3525 次，
FS TX 读写指针均为 5120，busy 为 0。最终 MD/SCP 停止，taint 为 0。
证据见 `backup/boot-write-md-rearm-03d140badce2/{booted,cycle}.log`。
调整脉冲期间的时钟引用没有解决该样本的超时。该实验没有测量脉冲
期间的物理门控状态，也没有移植 6.6 的下一代 DPMAIF 启动顺序。

下一轮优先对照复位后、放行 MD CPU 前的状态。`fsm_routine_start()`
在 `ccci_md_start()` 之前广播 `BOOT_WAITING_FOR_HS1`，因此 6.6
此时已重新置位 INFRA AO MEM bit 10；主线的两个置位调用都在
DPMAIF 数据环启动路径中，当前纯握手试验不会走到。可先只在下一代
放行前恢复这一位，并记录复位前后及放行前的值；若仍超时，再分辨
v2 公共硬件初始化、时钟和环/IRQ 启动各自的影响。

### 放行 MD 前恢复 INFRA AO MEM bit 10

复用 `03d140badce2` 和既有 DPMAIF 调试接口，未刷写新镜像。
有效对照中，6801 到 HS2/CCISM RUNNING，保持 20 秒；关电后确认
执行无环复位。在 6802 prepare 完成且 CPU 尚未放行时，寄存器读值为
`0x00000b3c`，只置 bit 10，读回 `0x00000f3c`。6802 接受 HS1，
仍在 3525 次服务发送后超时，FS TX 读写指针均为 5120，busy 为 0。
MD 和 SCP 均停止，taint 为 0。单独恢复该位未消除故障。

另有两次未执行到置位：一次首轮放行前的 peek 读到 bit 10 已置位，
随后 HS1 后同样超时。该 peek 会短暂持有 DPMAIF 时钟，不能当作
完全无扰动的首启基线。另一次去掉首轮 peek 后，6801 到 HS2，
停留期间触发独立的 `-EBADMSG`，按门槛终止。以上日志见
`backup/boot-write-md-rearm-03d140badce2/` 下的
`prot-rearm-confirm/`、`prot-rearm/` 和 `prot-rearm-no-first-peek/`。

后续应对照 6.6 放行前的整套 DPMAIF 状态。优先将已有的 v2 公共
初始化与环分配解耦，测试在放行前应用配置并持钟至 HS2；结合只读的
MD 侧 remap 快照判断是否需要补地址重映射。独立的 CCIF `-EBADMSG`
仍需保留锁存，不能用跳过门槛增加有效样本。

### 放行前执行现有公共初始化并持钟

镜像 `e94ea3ffb075` 的诊断入口复用了下行启动中的公共配置
（INFRA AO MEM bit 10、CG_EN、WDMA、L1 掩码和 DL power 标志）。
6801 到 HS2/CCISM RUNNING，20 秒后关电并执行无环复位；
6802 在 prepare 后、CPU 放行前写入公共配置并持有两个时钟引用。
启动日志确认保护寄存器为 `0xf3c`。没有启用 DMA 环、DPMAIF IRQ、
射频或 PDP，也没有配置 MD 侧地址重映射。6802 接受 HS1，随后仍在
3525 次服务发送后超时；FS TX 读写均为 5120，busy 为 0。
MD/SCP 停止，taint 为 0。直写 boot 的哈希回读一致，重启后 boot
与父盘均只读。证据见
`backup/boot-write-md-rearm-e94ea3ffb075/{write,booted,cycle}.log`。

该次结果表明现有公共配置加持钟不足以恢复热启。下一项差异是
6.6 在 MD 放行前还会配置 MD 侧 remap 和 DMA 队列。可先对比工作
状态下的 6.6 与主线复位后的 remap 寄存器，再决定如何复现上电序列。

本轮结束、MD1 OFF 时，用既有只读调试窗口采样 AO_MD_DL：CFG1
为 `0x02`（remap 未使能）、DOMAIN 为 `0x0707`、CACHE/ALIGN/LOCK
及 BANK0、BANK1 的八个 MAP 寄存器均为零。LK 报告的 bank0 AP
区为 `0xe0000000+0x1e000000`，来自 `hdr_tbl_inf`。6.6 的
`get_md_resv_mem_info()` 返回 `md_resv_mem_addr`；其 LK 解析在
未预设保留区大小时使用同一个 tag，另有从 DT 保留区设置地址的路径。
因此应以运行中 6.6 的 remap 或 MD 内存日志确认实际基址，不复用
旧试验中的 `0x40000000` 假设。快照见同目录的 `remap-off.log`。

### 同板 6.6 的工作态 remap

启动已知镜像 `boot-review6.img`（实机版本
`6.6.30-4k-g061b7bdafc86`），用匹配 ABI 的临时只读模块采样
AO_MD_DL。实测 CFG1 为 `0x03`、DOMAIN 为 `0x0101`、CACHE
为 `0x0706`，ALIGN 和 LOCK 均为零。八个映射字依次为
`00e300e1 00e700e5 00eb00e9 00ef00ed 00f300f1 00f700f5
00fb00f9 00ff00fd`。用同板 v2 编码解出首窗口的 AP 基址为
`0xe0000000`，与主线 LK tag 一致。未调用受保护的 ACK 内核符号。

按 32 MiB 粒度解码后，16 个已使能窗口中 12 个与主线
`/proc/iomem` 的 System RAM 重叠。首窗也覆盖
`0xe1ff0000–0xe1ffffff`，最后一窗则超出 LK bank0 末端
`0xfe000000`。因此 LK 的 bank0 基址和长度不足以证明整组映射
可安全重放。后续先核对 DMA 可达范围与访问控制，或用现有主线
队列在放行前做对照，暂不写 ACK 的映射值。

只读模块已卸载，设备已恢复 `e94ea3ffb075`；boot 回读哈希与镜像
一致，boot 和父盘均只读。MD 尚未由主线放行，SCP 未启动。
记录见 `backup/boot-write-md-rearm-e94ea3ffb075/ack-remap/` 的
`snapshot.log`、`md-reserved.log` 和 `mainline-restored.log`。

### 放行前启动主线 DPMAIF 下行环

在同一 `e94ea3ffb075` 镜像上，6801 不启用数据环，达到
HS2/CCISM RUNNING 后保持 20 秒，关电并执行与前次对照相同的无环复位。
6802 在 prepare 后、放行 CPU 前，通过现有 `dl_start` 启用 8192 项
BAT、8192 项 fragment BAT 和 16384 项 PIT；UL、射频、PDP 和网口
保持未启用，未写 MD 侧 remap。两次 AP 启动中，6802 均越过此前
3525 次服务发送的卡点，到达 HS2 和 CCISM RUNNING。第一组再运行
20 秒，服务发送 5952 次，CCIF 无锁存错误，随后正常停机。

第二组达到 HS2 后，CCIF 报独立的 `-EBADMSG`，按门槛取消 6803。
两组均停环并确认 MD1 OFF 后执行常规复位，SCP 已停，taint 为 0。
因此提前启用下行环可重复地让这组热启到达 HS2，但尚未证明可连续
重启，也未验证热启后的 IP 流量。见
`backup/boot-write-md-rearm-e94ea3ffb075/` 下的
`pre-release-dl/cycle.log` 和 `pre-release-dl-repeat/cycle.log`。

第三组计划在 6802 成功后尽快关电，再验证 6803。6801 正常达到
HS2/CCISM RUNNING 并完成无环复位；6802 的 DL 启动返回
`-ETIMEDOUT`，终止于 CPU 放行前。自动停环和一次显式停环重试
均超时，驱动保留 DMA 缓冲。快照显示 BAT 和 PIT 命令都仍有 busy
位，停环失败寄存器为 `PIT_INIT (0x20)`；启动失败最初对应的寄存器
未单独保存，不能从停环的错误位置推定。MD 仍是 prepared、未放行。
保留缓冲直到 AP 复位，随后确认回到相同镜像，MD 为 idle、SCP 未启动、
boot 和父盘只读。见 `pre-release-dl-three/{cycle,stop-retry,recovered}.log`。

接续应分别抓取首次 BAT/PIT 初始化超时和清理失败时的状态，并核对
放行前时钟和复位状态。提前建环已改变握手结果，但当前不宜把它设成
默认热启流程；后续仍需通过连续启停及热启后的 LTE 双栈验证。

镜像 `fc11d511bfbe` 在清理前记录首次 DL 启动错误及 BAT/PIT
命令值。用常规生命周期做对照：6801 到 HS2 后启动下行环，20 秒后
停环并关电、执行常规复位；6802 在放行前启动下行环，达到 HS2 和
CCISM RUNNING，保持 20 秒，CCIF 未锁存错误，MD/SCP 正常停止。
没有使用强制无环复位参数，也未启用射频和 PDP。该样本说明上次
成功不依赖特殊复位选项；本轮建环成功，新增失败日志未触发。
证据见 `backup/boot-write-md-rearm-fc11d511bfbe/cycle.log`。

同一 AP boot ID 内继续跑 6803、6804、6805，每轮都在放行前启用
DL 环，均达到 HS2 和 CCISM RUNNING，随后正常停机。6803 的
射频回读未确认，6804 的首次射频开启命令没有得到 OK；两轮均未
尝试激活 PDP。6805 将 `CFUN=1` 和状态读回配对，前三次分别是
无终止应答、ERROR 且读回 0、OK 且读回 1。确认 LTE（AcT 7）
及附着后，CID 1 按当轮 LHIF 映射使用 channel 0、UL queue 0；
IPv4/IPv6 的接口绑定 DNS 探测都收到匹配应答。退出后 CID 1
已去激活、测试路由已清除，USB 管理路径仍可用；MD/SCP 均停止，
taint 为 0。日志见同目录下 `{third,fourth,fifth}-lte/cycle.log`。

这验证了同一次 AP 启动中五代 MD 的连续启动，以及最后一代
热启后的实际 LTE 双栈数据。此前的偶发 CCIF 和 DL 建环故障仍需
单独处理，不能由成功样本推断已消失。

在 `2b66a2bbed23` 上复测常规复位后的提前建环，首代成功，第二代
在放行前失败。新增清理前日志确认第一条普通 BAT 初始化命令
卡住：`BAT_INIT=0x80000001`，`PIT_INIT=0`；只有进入清理后
才看到 `PIT_INIT=0x80000000`。因此应先查 BAT 命令无法完成的
条件，不能用清理阶段的 `fail_reg=0x20` 判断启动顺序。该轮 CPU
未放行，驱动保留 DMA 缓冲；AP 复位后回到同一镜像，MD idle、SCP
未启动、boot 和父盘均只读。见
`backup/boot-write-md-rearm-2b66a2bbed23/{cycle,bat-timeout,recovered}.log`。

同一镜像对 CCIF 异常 TX 读指针记录原值、同组写指针和一次独立
复读。复读只用于区分瞬态与持续异常，即使复读恢复对齐也不会在
该次发送中写环或清除错误。主机测试覆盖复读仍错和复读恢复对齐，
两种情况均保持 `-EBADMSG`、未发布新的写指针。

恢复后另跑一次无 DMA 环、无 AT 的纯握手，到 HS2/CCISM RUNNING
后保持 30 秒并正常关停；未复现 CCIF 指针异常，因此尚未在真机
区分瞬态和持续异常。见同目录 `ccif-only/cycle.log`。

`8dd048819259` 在 HS2 后复现了 FS TX q4 读指针异常：
`read=0x73c write=0xa10 length=0x5000 reread=0x740`。这次异常
在一次独立读取内消失，尚不能确定固件如何写入该值。
候选镜像 `d87622ba2e27` 只在初值位于环内、偏离对齐边界 4 字节，
且复读实际返回紧邻的对齐边界时接受复读值。它仍校验 AP 写指针，
并拒绝从已判空的边界向前纠正；持续异常仍按原路径停发。主机测试
覆盖了两种结果，本次候选镜像实机未再捕获该瞬态。

候选镜像第二轮在放行前再次卡住首条 BAT 初始化。首轮成功与第二轮
失败时记录到的两个 gate 状态、TOPCKGEN 主时钟选源及 MD 时钟模式
均相同：`ifrao3=0x100 ifrao4=0x0 clk_cfg13=0xc030601 clk_mode=0`。
这排除了这几个采样字段上的静态差异，不能证明时钟在整个提交区间
持续有效。PIT 仍未开始初始化，CPU 未放行，停环失败后仍保留缓冲。
AP 重启后回到候选镜像，MD idle、SCP 未启动、boot 和父盘均只读。
证据见 `backup/boot-write-md-rearm-{8dd048819259,d87622ba2e27}/cycle.log`
及候选镜像同目录的 `recovered.log`。

### MD 上电后、CPU 放行前追加 DPMAIF 复位

复用 `d87622ba2e27`。6801 到 HS2 后建 DL 环并正常关电；后续
各代保留常规关电复位，另外在 `md_boot=prepare` 完成后确认 MD CPU
未放行，通过现有 DPMAIF `reset` 入口追加一次 AO/PD 复位。每次
复位读回通过后才启用 8192 项 BAT 和 16384 项 PIT，然后放行 CPU。
同一 AP boot ID 内 6802、6803、6804 三次热启均完成建环、达到
HS2 和 CCISM RUNNING，最后正常停环、关电，SCP 停止，taint 为 0。
没有启用 UL、射频或 PDP，未修改 remap。证据在
`backup/boot-write-md-rearm-d87622ba2e27/powered-reset/{cycle,continue}.log`。

同镜像此前在仅做关电复位时曾复现首条 BAT 命令卡死。追加复位的
三个样本支持复位时点影响建环的假设；由于原故障间歇出现，还不能
认为该流程已修复故障。后续应跨 AP 启动比较，并验证两次真实数据
会话之间的关停与恢复，再决定是否纳入内核生命周期。

另一次 AP 启动复用同镜像，6801 和 6802 都完成 LTE（AcT 7）接入、
CID 1 激活及接口绑定的 IPv4/IPv6 DNS 验证。首轮在 HS2 后建环；
首个数据会话退出并清理 PDP、网口及测试路由后，正常停环、关电、
停 SCP，再以新一代 SCP 和 FS/RPC 后端启动 6802。第二轮的追加
复位读回及提前建环均通过。两轮均在第三次 CFUN 尝试读回 1，
USB 管理路由保持可用，最终 MD/SCP 均停止，taint 为 0。

6802 到 HS2 约 260 ms 后，FS TX q4 读指针再次短暂未对齐：
`read=0x2d74 write=0x3058 reread=0x2d78`。候选逻辑使用了
复读所得的下一对齐边界，CCIF 无锁存错误，后续数据和关停成功。
这是真机对该瞬态分支的验证；未放宽对持续异常的拒绝，也不能据此
断言 BAT 超时已根治。见
`backup/boot-write-md-rearm-d87622ba2e27/powered-reset-dual-data/cycle.log`。

### 将放行前复位和建环接入 MD 启动

新入口 `md_boot=release-with-dl` 要求 MD1 已上电且读回通过，
MD 启动状态为 prepared。驱动在同一次操作内串行执行 DPMAIF AO/PD
复位与读回、DL 建环、CCIF RX 启动及 MD CPU 放行。手动环操作不能
插入建环和放行之间。任一步失败均不继续放行，也不允许本代回退到
普通 release；如果不能确认 DMA 停止，仍保留缓冲。普通 release 和
正常关电后的复位路径保留。

`820c10aab5d1` 从主线写入 boot，回读匹配，重启进入新镜像；boot 和
父盘恢复只读。同一次 AP 启动内，6801 用普通 release，HS2 后建
DL 环；关停后，6802 用新入口，在 CPU 放行前建立 8192 项 BAT、
8192 项 fragment BAT 和 16384 项 PIT。两轮均到 HS2 / CCISM RUNNING，
并通过 LTE（AcT 7）IPv4 与 IPv6 DNS；PDP、网口和策略路由按顺序清理，
USB 管理路由保持可用。结束后 MD 和 SCP 均停止，taint 为 0。
证据见 `backup/boot-write-md-rearm-820c10aab5d1/integrated-dual-data/cycle.log`。
这是新入口的一次双数据会话验证，不能排除间歇性建环超时。

保持同一个 AP boot ID、不重启或重刷，继续用新入口跑 6803、6804
和 6805。三轮均在放行前完成 DL 建环、到达 HS2 / CCISM RUNNING，
并在 LTE（AcT 7）上收到 IPv4 和 IPv6 DNS 应答。会话分别设置为
20、20 和 45 秒；每轮均关闭 CID 1，清理网口和策略路由，再关停
MD 和 SCP，USB 管理路由仍可用。最终 MD 已停止、SCP last_generation
为 5，taint 为 0。同一次 AP 启动合计五轮 LTE 双栈，其中后四轮
使用新入口。证据见同目录下 `integrated-repeat-data/cycle.log`。

新增三轮中，首次 `CFUN=1` 均未收到终止应答，紧接着也没有读回
模式；第二次返回 OK 并读回 1。这发生在 HS2 和 CCISM RUNNING
之后。后续应区分固件尚未就绪、未送达与迟到应答，在启用 PDP 前
以射频模式读回和 packet attach 为准。

同一个 AP boot ID 继续跑 6806，沿用 `release-with-dl`，由
`modem_data_session.py --enable-rf` 独立负责开启射频和附着等待。
第二次开启后读回模式 1，附着后激活 CID 1。75 秒会话首尾均报告
LTE（AcT 7），绑定 IPv4/IPv6 DNS 都收到匹配应答。退出时确认 PDP、
网口和路由清理，随后 MD 和 SCP 停止，taint 为 0。日志见同一镜像
备份目录的 `enable-rf/cycle.log`。本轮未重启 AP。

### 跨 AP 启动复测：放行前建环仍可能失败

在 `820c10aab5d1` 上，仅重启 AP 并重新下发 FS/RPC 工作副本和数据工具。
新 boot ID 的 6901 用普通 `release`，在 HS2 后建环；`--enable-rf` 在
第二次尝试确认模式 1。30 秒 LTE 会话通过绑定 IPv4/IPv6 DNS 和关停。

同一 AP 启动的 6902 用 `release-with-dl`，通过复位读回后仍卡在首条
BAT 命令：清理前 `BAT_INIT=0x80000001, PIT_INIT=0`，清理提交命令后
PIT 才变为 busy。首轮和失败轮采到的门控、选源和 MD 时钟模式一致。
驱动锁存 `-ETIMEDOUT`，未放行 CPU，CCIF IRQ 保持屏蔽；停环无法
确认，保留 DMA，常规关机被拒绝。计划的 180 秒热启流量检查未开始。
保存寄存器后重启 AP，确认同一镜像、MD idle、SCP 未启动、boot 和
父盘只读。日志见 `cold-warm-soak/{cycle,bat-failure,recovered}.log`。

同板 6.6 的 `fsm_routine_start()` 在 `ccci_md_start()` 前广播
`BOOT_WAITING_FOR_HS1`；该通知已调用 DPMAIF 启动，之后
`md_cd_start()` 才调用平台上电和 CPU 放行。因此 vendor 在 **MD
上电前** 已开始配置 AP 侧数据面，不能把它等同于当前主线的“上电
后、放行前”路径。v2 stop 的时钟释放、复位与主线也有顺序差异。
下一步先验证上电边界对 BAT 初始化的影响；禁止用未审计的 remap
替换试验，也不把“环为空”的读回当作 BAT 命令引擎已就绪。

### 在 MD1 上电前建下行环

`md_power=on-with-dl` 只接受已干净停机、关电复位和显式 rearm 的
会话。核对 MD1 OFF 后，沿用关电时的 DPMAIF 复位，先建 BAT/PIT，
再走 MD 上电；仍须 `md_boot=prepare` 和普通 `release` 才放行 CPU。
建环和上电由同一操作串行，失败时拒绝普通 power-on 绕过。DMA 停止
无法确认时保留缓冲。

`bc1eac7959be` 从主线写入 boot 并回读，设备从新镜像启动，boot 和
父盘只读。同一 AP 的 6901 用普通放行、HS2 后建 DL，通过 30 秒
LTE 双栈；6902 在 MD1 OFF 时完成 8192 BAT、8192 fragment BAT 和
16384 PIT 建环，然后上电、放行、达到 HS2 / CCISM RUNNING。
75 秒 LTE 会话的 IPv4/IPv6 DNS 均匹配，PDP 和策略路由清理完成，
MD/SCP 正常停止，taint 为 0。日志见
`backup/boot-write-md-rearm-bc1eac7959be/prepower/cycle.log`。
在同一镜像另一次 AP 启动（boot ID `69ceec9f-9e4d-4e2f-8efc-a50e2aafcb9a`）
中，常规首轮通过 30 秒 LTE 双栈，随后再次在 MD1 OFF 时完成建环。
第二轮跑完 180 秒 LTE 会话，禁止 PDP 自动重连；双栈就绪后第
20、50、80、110 和 140 秒，每个采样点的接口绑定 IPv4/IPv6 DNS
均收到匹配应答。PDP、网口和路由清理完成，MD/SCP 均停止，taint
为 0，USB 管理路由保持可用。日志见同一镜像备份目录的
`prepower-soak/{cycle.log,soak_dns.py}`。
保持这个 AP boot ID，连续追加 6903、6904、6905 三轮。每轮都在
MD1 OFF 时用 `on-with-dl` 建环，再走普通放行，达到 HS2 和
CCISM RUNNING；15 秒 LTE 会话均通过接口绑定的 IPv4/IPv6 DNS，
未启用 PDP 自动重连。每轮均清理 CID 1、网口和路由并正常停机。
同一次 AP 启动累计五轮双栈，其中后四轮使用上电前建环；加上前一次
AP 启动，上电前建环累计通过五次。最终 MD/SCP 已停止，taint 为 0。
日志见同一镜像备份目录的 `prepower-repeat/cycle.log`。
本轮未触发 BAT 超时，不能据此验证建环失败后的回收。

### 上电前失败的显式回收

`on-with-dl` 失败后仍拒绝普通上电。若上电序列尚未开始，显式
`md_power=off` 可在确认 MD1 OFF 后停环、执行关电复位并再次确认
MD1 OFF；全部通过才解除锁存。停环超时继续保留 DMA，若上电曾部分
执行则仍拒绝此恢复。主机测试覆盖停环失败、复位失败和 OFF 检查
失败，并检查失败时锁存不被清除。

真机一次性测试镜像 `29193a25d8e4` 在环已建好、MD1 仍 OFF 时注入
`-EIO`。普通 on 被拒绝；显式 off 清理环，随后同次 AP 启动内
成功重新建环、上电放行并到达 HS1。之后停在 3525 次服务发送，
FS TX 读写位置均为 5120，后端报告 BrokenPipeError；该签名在既往
未注入流程中也出现过，本次未验证联网恢复。此实验未注入真正的
BAT 命令超时。证据见 `backup/prepower-recovery-injection/cycle.log`。
随后恢复无注入镜像 `e44320e3bbef`。

无注入对照的首轮已到 HS2 / CCISM RUNNING 并完成建环，随后
FS TX q4 的 MD 读指针为 `0x148c`，AP 写指针为 `0x1620`，
环长 `0x5000`，复读仍为 `0x148c`。驱动按原规则锁存
`-EBADMSG`，随后干净停机，第二轮未开始。该失败发生在 HS2 后，
不能用来判定注入试验中 HS1 后的卡点是否由恢复流程引起。同板
6.6 的接收端更新函数按 8 字节对齐，现有证据不足以把未对齐值
直接向上取整计入可写空间。对照日志见
`backup/boot-write-md-rearm-e44320e3bbef/control/cycle.log`。

### CCIF 读指针的有界复读及真机对照

`4bb08228f2a5` 保留原有立即复读。只有复读仍等于初次读到的
半对齐值时，才额外复读最多四次，每次间隔 10 微秒。必须实际读到
紧邻的对齐边界才继续发送；持续异常仍锁存 `-EBADMSG`，不会修改
MD 的读指针或发布 AP 的写指针。日志分别记录恢复与拒绝，以及额外
复读次数。主机模型验证立即恢复、第三次延迟复读恢复、持续异常时
不发布，以及既有的 CCIF 收发故障路径。

主线写入 boot 并回读后，新镜像首轮通过 20 秒 LTE 双栈及正常关停，
未观察到该 CCIF 分支。第二轮用 `on-with-dl` 时，MD1 尚未开始
上电就卡在首条 BAT 命令（`BAT_INIT=0x80000001, PIT_INIT=0`）。
显式 off 也无法确认停环，DMA 缓冲仍保留，MD CPU 未放行。
保存寄存器后通过 AP 重启恢复；同一镜像重新启动，MD/SCP 未运行，
boot 和父盘只读。证据见
`backup/boot-write-md-rearm-4bb08228f2a5/reread/{cycle,bat-failure,recovered}.log`。
这次证实上电前建环也可能超时；不能将 MD1 已上电视为 BAT 超时的
必要条件。延迟复读对真机未对齐事件的效果仍待观察。

### DPMAIF 关电复位读回

`371bc765c104` 在原有环状态读回之外，记录复位前后的 AO 阈值、
PD 保留字和 BAT/PIT 初始化命令字；若任一命令复位后仍显示 busy，
拒绝继续。同一 AP 启动内，首轮常规启动与四轮上电前建环均通过
LTE IPv4/IPv6 DNS 和关停。保存到的关电复位样本一致：
AO 阈值 `0x80be207f → 0`、PD 保留字 `0xff → 0`，BAT/PIT
命令字在复位前后均为 0。这证实 AO/PD 中这些可观察的寄存器
确实被清除，但没有命令 busy 跨复位的样本，不能据此确认内部
命令状态也已复位。本轮未复现 BAT 超时。

第二轮另捕获一次 CCIF TX 读指针 `0x62c → 0x630`，第一次
立即复读即恢复（额外复读次数为 0），未影响后续数据。记录见
`backup/boot-write-md-rearm-371bc765c104/reset-evidence/{cycle,repeat}.log`。
