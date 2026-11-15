<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 SCP RV：TCM 元数据与恢复映射边界

2026-11-15，基于 `6db0f4606d6e` 工作树，AI 辅助源码分析和实现。
接续 [SCP mailbox/协议基础](MODEM-SCP.md)。

后续用户允许上机，6.6 缓存报告的 struct_size 实为 **68**。已经新增严格
68/72-byte 解码并在原设备复测；下文 72-only 为首次离线阶段的历史说明。
当前接口要求 length 为 68 或 72 且与 header struct_size 完全相等，
未知尾字段不解释；实际保留区/回归与剩余边界见
[缓存与内存实测](MODEM-SCP-OBSERVATION.md)。未读取 live TCM。用户已将设备恢复到 Android，
交由基带分析 agent 使用；本轮完全离线，不连接、不重启、不刷写设备。

## 本轮实现与适用范围

新增 `ccci-scp-memory.{c,h}`，沿用默认关闭的 `OP6893_CCCI_SCP_PROTOCOL`。
它只处理 CPU 内存中的有界快照，没有 ioremap、固件复制、SMC、复位、IRQ 或
READY 入口。尚未接入真实 transport/consumer，不能单独授权任何恢复操作。

`ccci_scp_decode_region()` 的输入必须是从 TCM + 4 开始的 **72 字节快照**，
不是整个 TCM；调用者读取前要另行证明 TCM 范围、时钟和访问权限。小端解码，
仅接受 `struct_size == 72`，失败清空结果。72 来自 A/V 当前结构，不是来自
设备本轮实测；若真实固件使用 0、较短或扩展结构，当前明确拒绝，不自动猜版本。

|字段|相对 header 偏移|当前用途|
|---|---|---|
|ap_loader_start / size|0 / 4|解析源地址和字节跨度|
|ap_firmware_start / size|8 / 12|仅记录有界字段，不实现固件加载|
|ap_dram_start / size|16 / 20|字节数，供恢复映射跨度计算|
|ap_dram_backup_start|24|保留原值，检查对齐；**不使用它计算/访问备份区**|
|struct_size|28|版本门槛，当前仅接受 72|
|regdump_start / size|44 / 48|解析跨度，随后仍需专用允许区域检查|
|其余字段|32..40、52..68|不解释、不跟随指针、不发布原始内容|

四组 address/size 要求同时为零或同时非零；非零必须按 4 字节对齐且整个跨度
在 u32 物理地址空间内。当前严格对齐是本实现的支持策略，不证明所有固件
都使用对齐长度。全零的 optional pair 可以通过结构解码，但不代表 loader、
regdump 或任何必需资源已可用，未来 consumer 要独立检查必需项。

`ccci_scp_span_allowed()` 检查非空 u32 跨度是否完整位于调用者提供的可信
窗口中，拒绝窗口溢出或 span 越界。窗口必须来自本次启动已验证的本地
memory-region/保留区，**不能直接从同一不可信 header 派生**；历史地址只能
作为测试 fixture。该函数不证明 CPU 可读、EMI 权限、独占所有权或缓存属性。

`ccci_scp_dram_span()` 计算 A/V 在双核配置下使用的映射总长度，并将**计算后
整个范围**交给允许窗口检查。空 DRAM pair 返回空 span；混合 pair、未对齐、
跨 u32 地址末端或不适合窗口则失败且清空输出。输入与输出不得重叠。

## 长度单位与备份关系

A 的 `scp_helper.h` 定义 `ROUNDUP(a,b) = (a + b - 1) & ~(b - 1)`。
`scp_recovery_init()` 映射：

```text
roundup(ap_dram_size_bytes, 1024) * 4
```

`scp_awake.c` 普通恢复分支把备份起点计算为：

```text
ap_dram_start + roundup(ap_dram_size_bytes, 1024) * core_nums
```

先清零 `roundup(size,1024) * core_nums` 字节，再从计算出的备份位置复制
`ap_dram_size` 字节。因此该字段按**字节**使用，乘 4 不是 word 转 byte。
历史 `core_nums=2` 时，映射长度覆盖两核运行跨度加等大的备份跨度。

新 helper 先使用 u64 进行对齐和乘法，再检查结果，不复制厂商 u32 加法的
潜在溢出。这里只提供两核历史布局的**映射上界**，不实现清零或恢复，不把
它泛化到不同 core 数。即使只有 core 0 启用，也不能直接把 core_nums 改成 1
而改变已有固件备份位置。

A/V 的普通恢复代码没有使用 header 的 `ap_dram_backup_start`；也没有在这条
路径使用 `ap_firmware_start/size` 加载固件。因此不强制 backup_start 等于
计算位置，不把 firmware 字段或一个可用文件名当作已闭合的加载协议。
loader 复制到 TCM 还必须单独检查目标容量，不能仅凭源跨度在保留区内就执行。
映射之间的别名、重叠、读写权限和 cacheability 尚需 consumer 明确处理。

## 保存 DT 与固件源码证据

离线读取保存的 ACK FDT（不是当前设备观测）得到：

- `secure_dump = "disable"`；`core_nums=2`；`core_0="enable"`；无 core_1。
- 静态 `mblock-21-SCP-reserved` 为 `0x9fa00000 / 0x500000`、no-map。
- 动态 `reserve-memory-scp_share` 只有 size `0x320000`、alignment `0x1000000`，
  **没有 reg**。不能用静态 SCP 区替代，也不能据请求大小猜物理分配地址。
- 保存的 `7576d31c76a4/merged-preview.dtb` 保留以上 reg/size/alignment，但按
  现有 FDT 白名单不导入 vendor compatible。静态 reserved 与动态 share
  因此需要后续本地 phandle 契约，不能靠兼容字符串找到一块内存就继续。

A RV 的 secure helper 在条件分支中包含直接返回 0 的占位函数；V 同名 helper
则发送 `MTK_SIP_TINYSYS_SCP_CONTROL` SMC。名称和枚举相似不能证明本机旧 ATF
支持 V 的调用，返回 0 也不能作为复位/恢复成功证据。结合保存 DT 的非 secure
配置，后续先核对直接寄存器路径和真实复位状态，不照搬成功桩或盲试 SMC。

mikuui 的 op6893 vendor 清单包含 `vendor/firmware/remoteproc_scp`。主机 `file`
仅识别为 data，本轮没有导出其内容或计算固件哈希；A/V RV 目录检索未发现
`request_firmware`/`rproc_alloc` 直接加载该文件的路径。以上不足以证明此文件
用途或 LK 实际加载来源。仍需明确启动固件由谁加载、来自哪个来源以及 Linux
应该继承、重新加载还是仅恢复；文件存在不等于可以交给通用 ELF remoteproc。

## 测试与构建

`tools/test_modem_scp_memory.py` 编译实际 C，用 ASan/UBSan 运行纯合成数据。
可选 A/V 头文件提取真实 `struct scp_region_info_st`，通过编译期 sizeof 和
offsetof 断言核对 72 字节 ABI 及上述字段，不读取固件或设备内存。

覆盖：精确快照长度与版本、非对齐 CPU 输入、四组地址/长度、空项/混合项、
u32 末端、未知字段不解释、失败输出清零、可信窗口和 u64 溢出候选；
1024 字节边界前/等于/之后的向上对齐、空 DRAM、乘 4 后越界；20,000 组
非法 header 和 10,000 组有效随机字节长度，ASan/UBSan 通过。

ARM64 显式启用与默认关闭构建、strict checkpatch 结果及源码指纹见
[验证清单](evidence/modem-scp-memory-validation.json)。外部构建器已加入并
归档 `modem-scp-memory-tests.log`；没有打包或刷入镜像。

## 待闭合契约及后续最小观测项

设备空闲、用户授权上机后，优先只读核对元数据，而非直接加载/复位：

1. 实际 header 的 struct_size 与版本是否符合当前解码；快照一致性、读取时
   SCP 是否运行、TCM 读取的 clock/awake 权限。只输出版本/边界检查结果，
   不输出 TCM 原文、固件、身份或校准数据。
2. 本次启动静态 SCP 保留区、动态 share 的实际分配及本地 phandle，分别验证
   loader/firmware/regdump/完整 DRAM mapping 是否包含其中。header 能解析
   与允许访问必须分开验收。
3. 两核内存跨度与启用核的区别、备份实际来源和有效期、loader 复制目标容量，
   以及这些区域是否被其他 owner 使用。
4. 固件来源和启动责任、正常 READY channel、复位后的 mailbox 布局和恢复
   成功判据；缺失任一项不能返回成功或启动 MD。

以上是后续观测计划，本轮不向设备发起操作，也没有要求其他 agent 执行它。
