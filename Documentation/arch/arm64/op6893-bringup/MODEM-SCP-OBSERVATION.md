<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893：6.6 SCP 缓存与实际保留内存观测

2026-11-15，基于 `6db0f4606d6e` 工作树，AI 辅助实现与实机检查。
用户已允许上机测试。本轮利用设备现有 6.6，不重启、不刷写、不更新恢复备份。
这是 ACK 缓存/内核保留区的观测，不是主线 SCP/基带运行验收。

## 实机结果

设备 release 为 `6.6.30-4k-g6974e26f087e`。加载前逐字节比较设备
`/sys/module/scp/notes/.note.gnu.build-id` 与本地对应 `scp.ko` 的 ELF note，
结果相同。这个核对针对驱动模块，不是固件指纹；未采集固件内容或哈希。

一次性模块通过直接导入 `is_scp_ready()` 固定 provider 生命周期；只读取
`scp:scp_region_info_copy`、`scp:scp_mem_base_phys`、`scp:scp_mem_size`
这些普通 CPU 缓存，以及 `of_reserved_mem_lookup()` 的内核记账。
A/V 源码中 region 缓存只在初始化时复制，恢复路径使用这个缓存；两份样本一致、
前后软件 READY 均为 1。它不证明期间没有复位，也不是 live TCM 或启动代际校验。

|检查项|结果|
|---|---|
|缓存 header 的 `struct_size`|**68**，不是 A/V C 结构的 sizeof 72|
|原先只接受 72 的 decoder|返回 `-EPROTONOSUPPORT`，没有自动忽略版本|
|新增精确 68-byte 支持后|decode_result=0|
|静态 SCP 保留区查询|成功；loader / firmware / DRAM 及完整恢复 mapping 均被包含|
|动态 share 本次分配|`0x8d000000 / 0x320000`|
|share 内核记账与驱动缓存|base 和 size 相等|
|loader 长度|8192 字节|
|firmware 长度|1572864 字节|
|DRAM 长度|305120 字节|
|历史恢复 mapping 长度|1220608 字节，即 `roundup(305120,1024)*4`|
|恢复 mapping 与 loader / firmware / regdump / share|四项均不重叠|
|header 的 backup 地址|与双核公式 `base + roundup(bytes,1024)*2` 相等|
|regdump 长度及归属|1048576 字节，不在静态 SCP 或本次 share 内；**未授权映射**|

只输出必要的大小、share 几何信息和比较结果；没有输出 header 原文、
loader/firmware 内容、身份或校准字段。没有跟随 header 中的地址。
backup 公式吻合也不证明备份内容有效、可以清零或可以恢复。
不能把 6.6 本次动态地址硬编码进主线：主线必须使用它自己的实际分配结果。

## 68-byte 支持及读取边界

A/V 当前头文件均为 72 字节，并明确说明结构大小用于追加字段的兼容版本。
本轮实际缓存报告 68 字节；decoder 使用的最后一个字段是 offset 48 的
regdump_size，位于两个版本共有的前缀。A/V 已运行驱动也按这些前缀偏移使用
loader/DRAM/regdump。未知尾字段继续不解释、不跟随、不输出。
这是对已观测 68-byte 前缀的支持，不是确认完整固件 ABI 或推断尾字段内容。

`ccci_scp_decode_region()` 现在只接受 length 68 或 72，且 header 内
`struct_size` 必须与 length **完全相同**。68-byte header 加 72-byte
length 仍拒绝；不接受任意 `>=52` 的结构，不把版本检查删掉。
`CCCI_SCP_REGION_BYTES=72` 保持为最大缓存容量，新增
`CCCI_SCP_REGION_LEGACY_BYTES=68`。以后 TCM consumer 要先有独立访问契约，
读版本并验证后，再复制精确长度；本诊断读取的是已存在的 72-byte CPU 缓存，
不会借这个容量去额外访问 TCM。

ASan/UBSan 使用真正 68-byte 对象验证新版本，不以 72-byte 容量掩盖越界；
覆盖版本/length 错配、未知尾字段、失败清零，20,000 组随机候选及 10,000
组有效 mapping 计算在两个版本间轮换。A/V 实际头文件的 sizeof/offsetof
编译断言仍通过。诊断模块与 helper strict checkpatch 均为 0/0/0。
ARM64 启用协议/awake 与恢复默认配置的 Image.gz/modules 构建结果见证据。

## 诊断入口与加载过程

源码在 [scp-cache-observe](tools/scp-cache-observe/observe.c)，只用于临时诊断，
不加入主线 Kconfig、DT 或默认构建。构建器
[build_scp_cache_observe.py](tools/build_scp_cache_observe.py) 在新目录复制实际
memory helper C，使用 6.6 的 unaligned include 兼容头；不修改 ACK 驱动。
它只构建/可选签名，不连接设备或自动加载。需要匹配的 common/out、SCP
Module.symvers，且固定核对已审计的 release；加载前仍必须另验 SCP build ID。

缓存不是导出符号。诊断暂借一个 **disabled、无 handler** 的 kprobe 取得
`kallsyms_lookup_name` 入口，立即注销，再解析上述三个固定模块限定名。
只有私有 resolver 调用使用 `__nocfi`；不调用查到的 SCP 函数、不传入任意地址。
没有激活断点，没有持久 hook；这不是拟提交的主线接口或正式 provider。
正式实现应由 owner 提供生命周期明确的接口，而不是沿用此诊断机制。

首次未签名模块被 `CONFIG_MODULE_SIG_PROTECT` 以 protected symbol 拒绝，
init 未执行。随后按已有 ACK packaging 的 `sign-file sha1` 开发密钥/证书
流程签名，保持签名/CFI/SELinux 检查配置，成功加载、观测并卸载两轮：
第一轮发现 68-byte 拒绝，第二轮核对新增版本和边界。每次均删除上传的模块。
最终模块不存在，ADB 可用，SCP 软件状态仍为 ready。没有发送 awake/IPI、
操作时钟/电源、访问 MMIO/TCM、复位 SCP/MD、重启或刷写分区。

## 下一步

1. 确认 LK→主线交接时的 SCP 真实运行/复位、TCM 访问和时钟责任；不能把
   6.6 已初始化后的 READY/header 直接当作 LK 初始状态。
2. 为主线静态保留区与动态 share 建立本地引用，取得本次实际分配；只允许
   经边界校验的 loader/DRAM 用途。regdump 暂不接入，另核对专用允许区域。
3. 明确 loader/firmware 来源、备份有效期及 bootstrap/READY 责任后，再接
   observation consumer、共享 awake/clock provider 和 mailbox transport。
   正式 get/put 测试仍需唯一 owner、真实 READY、代际与稳定时钟，不能从
   本轮缓存检查直接跳到启动基带。

机器可读结果与主机/实机日志索引：
[modem-scp-cache-observation.json](evidence/modem-scp-cache-observation.json)。
