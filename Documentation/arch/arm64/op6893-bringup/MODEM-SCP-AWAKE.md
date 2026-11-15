<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 SCP RV：共享 awake 后端与下一次上机边界

2026-11-15，基于 `6db0f4606d6e` 工作树，AI 辅助源码分析、实现和主机测试。
用户要求继续离线推进到需要实机测试的位置。实现阶段不连接设备，不运行 adb、
fastboot 或设备 SSH，不重启/刷写，也不占用其他 agent 的 Android 分析环境。
随后用户允许检查，并说明设备运行 6.6、暂不刷入；只读观测见文末接续记录。
接续 [协议布局](MODEM-SCP.md) 和 [TCM 内存契约](MODEM-SCP-MEMORY.md)。

## 已实现的共享后端

`drivers/misc/mediatek/ccci/ccci-scp-awake.{c,h}` 由新增 bool
`OP6893_CCCI_SCP_AWAKE` 控制，依赖协议 helper 与 REGMAP，默认关闭。
它不注册设备，没有现存调用者，不映射物理地址，不推断 READY，不改变时钟，
也没有自动复位或“失败即成功”的分支。构建启用不产生硬件访问。

未来 SCP provider 必须提供**现有 infracfg 节点的 uncached MMIO regmap**。
不能仿照旧驱动再创建一个覆盖 `0x10001000/0x1000` 的独占设备。
本后端不负责解析 phandle 或获取 syscon；获取过程本身的 clock/reset 行为
同样需要 provider 审核，不能把“调用 syscon lookup”笼统当成无副作用。

provider 还必须做到：

- 每台 SCP 只有一份 AP awake 引用状态，所有 AP 消费者共享，不能每个 channel
  或每个客户端独立维护 users。CONNSYS bit 2/3 不属于本后端。
- 在整个 get/put 期间串行化所有 AP 请求、STOP/reset 和时钟变化。
  操作可睡眠，不能从 hard IRQ、持有 spinlock 或关中断上下文直接调用。
- 在 get/put **之前**确认本代真实 SCP READY；初始化 helper、发现 header、
  mailbox bit 清零或一次 ACK 都不等于 READY。初次加载固件的 bootstrap/TCM
  访问规则另行实现，不能用需要 READY 的 awake 路径证明自身启动前提。
- 收到 STOP/reset 时停止新请求，排空工作和旧引用，并 invalidate 后端。
  重新初始化必须在实证硬件复位且旧消费者全部排空后，不能用 init 清故障后重试。

接口行为：

|接口|行为|
|---|---|
|init|仅初始化内存，拒绝 null/error regmap，不访问寄存器|
|get，users 从 0 到 1|发送 LOCK 握手，全部成功后计数加 1|
|get，已有 users|仅加计数，拒绝 u32 上溢|
|put，users 大于 1|仅减计数|
|put，users 从 1 到 0|发送 UNLOCK 握手，全部成功后才减计数|
|put，users 为 0|报错，不发送任何请求|
|invalidate|不访问硬件，保留计数并禁止后续 get/put|

每个真实握手先读 SET，若 AP bit 0/1 已有请求，则拒绝，不覆盖或清掉它。
随后向 SET 写入 `0xa0 | bit`，读取 SET 等待该 bit 被 SCP 清零，并要求
`0xa0` marker 仍存在。轮询间隔 10 us、时间预算 1 s，接近 A 中
`100000 * 10 us` 的等待尺度；这是当前支持策略，不是固件响应时限的实测结论。
不读取旁边的 `+0xb10`，不以 `regmap_update_bits()` 操作 W1 SET/CLEAR。

一旦尝试过 SET，无论写入报告成功还是失败，都尝试向 CLEAR 写同一请求掩码。
写操作返回错误不能证明写入未到达硬件。原始错误与清理错误分别保留；若只有
清理失败则返回清理错误。任何握手错误都锁定故障，禁止后续重试；失败 get
保持 users=0，失败最终 put 保持 users=1。清理成功不证明固件内部 lease 已恢复，
所以仍不能重试或继续发 IPI。

这些规则不证明硬件事务能够被软件超时中断，也不证明真实 CONNSYS 并发时序。
它们只限制软件请求、计数与错误传播。最终 provider 仍需真实 firmware/reset
代际管理；本后端没有全局 READY、notifier 或 remoteproc 实现。

## A/V 源码与时钟缺口

A 为本机 Android 4.19 的 `drivers/misc/mediatek/scp/rv/`，V 为已可用的
6.6 同板移植的同目录。源码指纹见本轮验证清单。

A 的 `scp_ipi_table.h` 把 `scp_awake_lock/unlock` 注册为发送的 pre/post
callback；`scp_awake.c` 先检查 `is_scp_ready()`。直接寄存器为：

|用途|相对 infracfg 偏移|掩码|
|---|---|---|
|发送请求与读取应答|0xb14|marker 0xa0，AP LOCK bit 0 / UNLOCK bit 1|
|请求清理|0xb18|与本次请求相同的 marker + bit|

V 支持 syscon regmap 和可选读取 `+0xb10` STATUS，并增加 LPM 请求、WDT
检查和 SMC awake 通知。不能只因名称相似就照搬这些新路径或 SMC；本轮后端
仅实现 A 的旧 SET 读取协议。V 还修复过 clock provider 占用 infracfg 节点、
导致另一 platform driver 根本不 probe 而留下空指针的问题。

本轮离线读取保存的 `ack-live.dtb`（**不是设备当前状态**）确认：

- `/scp@10700000` 无 `scp-read-infra-irq-status`、`scp-scpsys-regmap` 或
  `awake-timeout`；`twohart=0`、TCM size `0x180000`、`secure_dump=disable`。
- `/scp_dvfs` 为 `scp-dvfs-feature=enable`、`scp-clk-hw-ver=v1`，并带
  `do-ulposc-cali`。这些属性只说明请求的配置，不证明初始化已经成功。

保存 DT 中 DVFS clocks 指向 TOPCK 的以下 ID，按名称顺序排列：

|clock-name|vendor ID|A 中对应来源|
|---|---|---|
|clk_mux|191|scp_sel|
|clk_pll_0|100|tck_26m_mx9_ck|
|clk_pll_1|34|univpll_d5|
|clk_pll_2|19|mainpll_d6_d2|
|clk_pll_3|18|mainpll_d6|
|clk_pll_4|39|univpll_d6|
|clk_pll_5|10|mainpll_d4_d2|
|clk_pll_6|15|mainpll_d5_d2|
|clk_pll_7|31|univpll_d4_d2|

A 的 `clk-mt6885.c` 中 `MT_CCF_MUX_DISABLE=0`，选中带 gate 的 SCP mux：
TOPCK `CLK_CFG_0=0x10`，selector bit 16..18、gate bit 23，SET/CLEAR
`0x14/0x18`，更新寄存器 `0x4` bit 2。相同文件里另一条不带 gate 的定义
属于未选中的条件分支，不能只搜索到第一条就照搬。

当前主线 TOPCK 子集尚未发布 SCP mux 及上述八路完整输入，MAINPLL 也只是
继承状态的只读观测。A 的 DVFS 初始化不仅查找时钟，还会 prepare/切 parent、
请求资源、校准 ULPOSC、交换 IPI。给缺失 ID 填 fixed clock 或只增加名字
不会补齐依赖。当前不能盲目把 mux 切到 26 MHz，也不能注册后让 unused
cleanup 关闭继承的 SCP 时钟；下一次需要先核实正在使用的启动契约。

## 已准备好的第一步上机检查

脚本 [collect_modem_scp_metadata.sh](tools/collect_modem_scp_metadata.sh)
只在显式执行时工作，离线实现阶段没有上传或执行。它不包含 adb/fastboot/SSH 命令，
不遍历 sysfs，不读 debugfs、不执行寄存器访问、不读取 `/dev/scp` 日志、
固件、TCM、cmdline、身份或校准数据。

在 Android 下的执行方式（以后设备空闲且允许访问时）：

```sh
sh /data/local/tmp/collect_modem_scp_metadata.sh
```

只读取 `/sys/class/misc/scp/scp_A_status` 两次，将结果规范化为 ready /
not-ready / unavailable / unrecognized；不回显未知内容。A 对应 show 函数
仅读取软件 `scp_ready` 标志。固定 DT 白名单包含 SCP 地址/IRQ、模式开关、
mailbox 表、DVFS clocks 和两类保留内存的几何信息。单项超过 1024 字节则
只报告 oversize，读取失败单独标记；硬件属性按 hex 输出，避免 shell
处理 NUL。不读取整棵 DT 或整份日志。

**不要替换为 cat 所有 SCP sysfs 文件**：A 中名字含 `awake_lock` 和
`awake_unlock` 的两个 RO 属性，其 show 回调实际会发送请求；寄存器状态、
IPI test、ramdump 和 reset 相关入口也不在此次采集范围。

第一步接受条件是：两次软件 READY 与配置可解释，核对模式是否符合 A。
脚本不识别运行中的内核二进制，源码对应关系仍需另行确认。
两次 ready 不能排除中间发生复位，不证明主线继承状态，
不能授权 awake、TCM 读取或固件恢复。缺失属性按缺失处理，不根据历史补值。
动态 share 无 reg 时仍是未闭合项，不能从 size/alignment 推导分配地址。

随后真正阻塞 provider/transport 接入的是：

1. **真实 firmware 元数据**：实际 TCM header 的 struct_size/版本，快照何时
   有效、加载来源及谁拥有启动/恢复责任。应优先在已运行的 ACK 内核内部
   读取缓存的 metadata 并只输出校验结果，不能裸读整个固件或转储 TCM。
   当前 collector 不获取这些字段；还没有可直接执行的 header 读取入口。
2. **可信保留区**：本次启动动态 share 的实际分配、本地 phandle、loader /
   firmware / regdump / 完整 DRAM mapping 的归属和不重叠证明。
3. **真实 READY/时钟责任**：ACK 运行状态不等于 LK 交给主线时 SCP 已 READY。
   必须区分继承与重新启动，确认 clock/awake 前提及复位代际；随后才设计
   主线 observation consumer，最后单独测试 awake 配对请求。

离线实现结束时停在第一个上机检查点。直接接入 IRQ/transport 或试启动 SCP/MD 会越过
这些尚缺的观测；默认 DT、defconfig 和设备启动状态均未因本轮改变。

## 主机验证

[test_modem_scp_awake.py](tools/test_modem_scp_awake.py) 编译实际后端 C，
用 ASan/UBSan 和失败注入 regmap 覆盖：首末引用、嵌套引用、计数上下溢、
LOCK/UNLOCK 每个 I/O 失败、SET 报错但实际已写入的清理、双错误保留、
超时、marker 异常、已有 AP pending、延迟 ACK、STOP 后无 I/O 重试拒绝。
寄存器 mock 断言仅访问 `0xb14/0xb18`，只写本次 `0xa1/0xa2` 掩码，
并检查邻接 CONNSYS bit 不被软件写掩码清除；不是实际并发硬件验收。

[test_modem_scp_observe.py](tools/test_modem_scp_observe.py) 用临时文件系统
验证采集脚本的固定白名单、READY 规范化、缺失/空/超长属性、OF fallback。
把有副作用的属性替换成 FIFO，任何误读都会超时；加入不应导出的 cmdline /
未知状态等 sentinel，确认不出现在报告中。没有调用 adb 或设备 I/O。

ARM64 显式启用与默认关闭 Image.gz/modules/modpost、符号存在/缺失、strict
checkpatch 与源码指纹记录在 [验证清单](evidence/modem-scp-awake-validation.json)。
外部构建器加入并归档两组新主机测试；本轮没有打包新 boot 镜像。

## 2026-11-15：现有 6.6 的首次被动观测

用户确认当前设备运行 6.6，允许检查但禁止刷入。现有 root ADB 返回 release
`6.6.30-4k-g6974e26f087e`；版本判断同时依据用户说明，不只依赖 uname。
核对 V 的 `scp_A_status_show()` 仍仅读取软件标志后，以 `adb shell -T sh`
通过 stdin 执行上述 collector，没有上传/安装文件，没有重启或刷写。

结果见 [6.6 被动观测](evidence/modem-scp-6.6-observation.json)：

- READY 前后两次均为 ready，仅表示当前 6.6 驱动的软件标志。
- 24 项存在的硬件属性字节内容与保存 ACK DT 相同，另 6 项均缺失。
  核对范围包括资源地址/IRQ、完整 mailbox 表、DVFS clock cells、核心配置和
  两类保留内存。相同的 clock phandle cells 尚未独立解析本次 provider。
- `core_nums=2`、core 0 启用、无 core 1；TCM `0x180000`，secure_dump 关闭；
  新 STATUS/regmap 模式开关与 awake-timeout 属性缺失。
- 静态 SCP 区仍为 `0x9fa00000/0x500000`。动态 share 的 DT 仍无 reg，
  只有 size/alignment/alloc-ranges；不能据此得出实际分配地址。

这一步完成了当前软件 READY 和 DT 对照，没有执行新 awake 后端，也没有
读取 TCM、固件或缓存 region header。真实 header ABI、动态分配和 LK→主线
交接状态仍未闭合，不将本次 ACK/6.6 的 ready 当作主线 SCP 已可运行。
另只读筛选了现有 dmesg 中三类特定内存初始化消息，未找到匹配行；可能是
未启用对应日志或早期记录已覆盖，不能推断未分配或初始化失败。


## 2026-11-15：缓存 header 与动态分配已取得

用户随后允许上机，通过临时 ACK 模块读取 CPU 缓存和保留区记账：
header 标称 68 字节；严格 68/72 解码复测通过；share 实际分配与驱动缓存
一致，loader/firmware/完整 DRAM mapping 位于静态保留区。regdump 不在
已确认窗口内，不授权映射。详见 [实测记录](MODEM-SCP-OBSERVATION.md)。
本轮没有测试 awake 握手。LK→主线 READY/时钟、加载/备份责任和正式共享
provider 仍缺，不能把上述缓存检查当作 get/put 或启动 MD 的前提已全部成立。
