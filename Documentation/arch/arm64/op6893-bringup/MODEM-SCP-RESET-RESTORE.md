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
