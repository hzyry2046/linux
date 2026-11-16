<!-- SPDX-License-Identifier: GPL-2.0-only -->
# 6297 共享内存布局与 MD 启动接续

2026-11-16，AI 辅助实现；接续已实测的 [SCP 常驻/awake](MODEM-SCP-RUNTIME.md)。
本轮只验证 CPU metadata 计算及内核构建，没有连接、重启或刷写设备。

## 为什么先补布局

本机可用 6.6 的 `ccci_util_md_mem.c:gen6297_noncacheable_tbl` 用两个 padding
把线性遍历结果恢复成 LK 的非线性布局：小子区从 +0x100000 开始，DFD 从
+0x1000000 开始，bank 总长0x1800000。直接复制通用默认表会破坏该关系。
本机4.19的 `ccci_modem.c:ccci_6297_md_smem_layout_config()` 则保留 LK 的
显式offset，再顺序补全未给offset的固定子区。本实现采用后者，不硬编码
本机 AP 物理地址，也不复制两个具有相同用户ID的padding条目。

历史4.19启动记录已明确缓存区的0x80000差值：

|aggregate|offset|size|
|---|---:|---:|
|MD_CONSYS（22）|0|0x180000|
|NVRAM_CACHE（32）|0x180000|0x700000|
|间隙|0x880000|0x80000|
|CCB aggregate（1）|0x900000|0x4000000|
|UDC descriptors（28）|0x4900000|0|
|USIP（24）|0x4900000|0x60000|

完整跨度为0x4960000，非重叠子区大小之和为0x48e0000；差值就是上述间隙，
不是少了一块新reservation。证据是本地
`/data/src/reverse-analysis/modem-runtime/ccci_dump-boot-excerpt.txt` 的
历史 `init_smem_regions` 输出，不是本轮主线观测。新解析器始终保留 LK 的
bank跨度，另算gap；CCB暂为单个aggregate，端口层拆分尚未实现，不能把
DHL/MDM/META别名重复计入总大小。

qqcandy 当前 `eccci/ccci_modem.c` 仍有其设备专用fallback常量，例如不同的
NVRAM-cache大小/offset及bank跨度。这些值没有移植到本机。这里只借鉴其
按LK条目恢复布局的方向，不把其相似表名当成相同硬件或固件ABI。

## 实现与支持范围

`ccci-smem.{c,h}` 提供 `ccci_smem_parse()`，先重新验证完整LK链表及粗布局，
再解码 `nc_smem_info_ext_num/ext`、`md1_bank4_cache_info/layout` 与厂商拼写的
`md1_smem_cahce_offset`。24-byte cached native结构的item_cnt字段在bank头
表示条目数，在条目中表示用户ID；不是紧凑20-byte数组。

- NC采用本机4.19 mt6885表（CCCI_USE_DFD_OFFSET_0，security SMEM关闭），
  要求LK提供非空DFD和Wi-Fi proxy锚点；其余固定条目按同板顺序计算。
  本版本要求显式AP/MD offset相等，不支持不同映射或额外NC用户ID。
- cached支持22/32/1/28/24五种aggregate；要求条目地址与bank+offset一致，
  拒绝重复ID、跨bank用户复用及非空区间别名，核对CCB与原ccb_info一致。
  必须有非空NVRAM-cache/CCB，runtime/CCISM满足同板最小长度。
- AP保留区、bank与MD视图分别检查跨度、对齐和溢出。MD地址保持同板
  bank4换算；不把AP物理地址直接当成MD地址，也不跟随未知tag内的值。
- 输出记录AP/MD地址、size、cached、首启保留/no-map和LK来源标记；失败
  输出清零。gap是未被非空aggregate占用的bank字节数，不是可自由分配内存。
- 不支持未知ID、新版layout或缺失必需tag时返回错误，不套用qqcandy常量
  或只靠非零物理地址继续。旧式仅ccb_info而没有cached布局的交接不支持。

默认关闭 `CONFIG_OP6893_CCCI_SMEM`，仅扩展现有显式LK inspector；启用后
也只在已验证的tag快照上计算。摘要只记录数量、跨度和gap。结果及快照随后
擦除，没有持久化共享owner或发布给CCIF/电源consumer；后续需把此API接入
统一MD owner。没有映射/清零SMEM、写NVRAM、请求MD IRQ或执行MD上电。
首启保留标记也不是清零许可，仍需MD停止及独占生命周期证明。

## 验证

`tools/test_modem_smem.py` 编译实际LK与SMEM C代码，ASan/UBSan通过。
纯合成输入以历史geometry为独立oracle，核对runtime +0x11e800、CCISM_SCP
+0x120000、MCU +0x139000、EXP +0x1ed400，以及完整cached跨度/gap。
同时覆盖重定位AP bank、非对齐CPU输入、截断/错误长度、计数上限、重复ID、
别名、未知用户、不同AP/MD offset、空必需区、CCB冲突、MD溢出和失败清零。
未知tag payload不解释。两个实际vendor树的enum及结构sizeof/offsetof另行
编译核对通过，不读取固件或设备私有内容。

启用LK_INSPECT+SMEM的ARM64 Image.gz/modules构建通过，strict C checkpatch
通过，默认源码DTS/defconfig未改，输出.config恢复。日志在
`/data/src/mainline/mt6893-direct/evidence/modem-smem/`。
**尚未验证本次LK真实子区tag是否满足所有严格条件**；不为此单独刷机，
合并到下一轮MD平台/CCIF测试镜像。一切新硬件支持仍按已有实测边界判断。

## 下一轮合并工作

1. 统一MD平台owner，保存本次LK布局/四路供电启动基线，接现有MD1 genpd；
   按本机6.6/4.19顺序整合电压恢复、SRCCLKENA/flight mode和普通CCIF时钟。
   MTCMOS上电与ATF放行MD CPU分开；不猜SMC18/19。
2. 接普通CCIF的SRAM/环和控制接收，独立管理CCIF2桥；以此布局生成runtime
   feature并连接已实测SCP transport，落实SHM_INIT_ACK→SHM_INIT→RBREADY→
   INIT_DONE，保留真实返回状态和超时。
3. 结合FS/NVRAM私有工作副本及用户态服务门控后才释放MD，验收HS1/HS2。
   将上述相关项作为功能组测试，不拆成多轮仅资源预留或只读刷机。
