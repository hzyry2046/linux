<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP TCM：精确长度 header 只读观测

2026-11-15，AI 辅助实现/测试，HEAD `6db0f4606d6e`。
接续 [core0 读回](MODEM-SCP-CORE0.md)，本轮不启动 SCP/MD。

## 同板契约与访问范围

同板 A/V 的 RV SCP 驱动将 TCM resource `0x10500000/0x180000` 映射为
Device MMIO，在 `scp_region_info_init()` 从 TCM+4 缓存 header。
`struct_size` 位于 header+28；既有 6.6 实机 CPU 缓存为 68 字节，当前
A/V 头文件为 72 字节，已审计公共字段偏移见 [memory helper](MODEM-SCP-MEMORY.md)。
厂商先请求 26M bootstrap 时钟再访问 SRAM；本轮沿用上一轮已验证的
继承 selector0/ungated 条件，不声称取得正式 clock ownership。

板级 observer 增加第二个 reg/名为 tcm，独立默认关闭开关
`OP6893_CCCI_SCP_TCM_OBSERVE` 只在 observer built-in、core0 和 protocol
helper 启用时可选。probe 校验完整资源几何后，仅申请 header 窗口
`0x10500004/72`，映射遵从页粒度，不能将它描述成硬件只映射了 72 字节。
软件显式读取范围严格限定在 header。无 probe 自动读取，不映射固件 DRAM、
share、regdump 或 core1，不跟随 metadata 中的地址。

`/sys/bus/platform/devices/10730000.scp-observe/header` 的一次读操作：

1. mutex 内执行现有 core0 reader，复查 mux 并取得稳定 reset alias/status。
2. 仅读 header+28 的 u32；不是 68/72 时立即拒绝，不读取其他 header 字段。
3. 按已知精确长度，用对齐 readl 取得两份 LE CPU 快照，再复读长度字。
   68 字节版本不会读取 header+68；两份任意字节变化或长度不符均拒绝。
4. 再执行 core0 reader；mux/解释位变化或 I/O 错误均拒绝。即使 header
   长度未知，也执行后置观察。失败清空输出长度，解码结构不保留旧结果。
5. 使用既有 decoder 解码，不解释未知字段。sysfs 仅输出尺寸、静态保留区
   包含/完整 DRAM 恢复跨度包含、payload 不重叠和 backup 地址公式比较。
   regdump 只比较其是否在 firmware/share 内，始终不映射。

完整 DRAM mapping 公式 `roundup(bytes,1024)*4`，backup 公式
`dram_base+roundup(bytes,1024)*2`；它们是历史双核布局元数据检查，
不表示本轮启用 core1 或备份有效。不重叠检查不等于窗口包含检查，各自输出。
缺少 DRAM 的合法空对可以解码成功，不能当作可启动固件。

前后采样不能排除中间瞬时变化，也没有硬件 generation 标记；两份一致
只说明该次有限观测一致。未请求 READY、IRQ、mailbox/awake 或写 reset。
MMIO 无可靠的软件总线超时保证；此前 core0 可读并不证明所有 TCM 可读。

## 验证与镜像

`tools/test_modem_scp_tcm.py` 编译实际 snapshot/core0/decoder/bounds 函数，
以独立真实 68-byte 对象及 72-byte 对象模拟 MMIO。ASan/UBSan 检查精确
读地址/顺序、所有字段逐字改变、未知长度只读一次、四个 regmap 错误和
前后 mux/core0 变化拒绝、解码失败及清空输出。此测试不模拟总线可达性。
既有 prerequisites/core0/memory 回归通过；strict checkpatch 0/0/0。

实验镜像 `3ccec64b58d4`，release `7.3.0-op6893-d1-3ccec64b58d4+`；
boot SHA256 `db21fd1441b9599583bbb4dbf29369f69b527b7ca3338a61c22885f2b0803078`。
启用 ARM64 Image.gz 和完整构建器回归通过，无新增编译警告；binding 文档及
启用 board/merged DTB 定向 schema 通过。DTS/defconfig 原始字节已恢复。
默认关闭的 Image.gz/modules、FDT merge 回归也通过；默认 vmlinux 不含
observer/decoder 符号，节点 disabled。默认配置仍有原有 FW_LOADER/VT
两条重复赋值提示，未改动。日志在 `mt6893-direct/evidence/scp-tcm-live/`。

## 真机结果

boot/reboot 提前排队，用户配合 sync+SysRq 复位后的 fastboot 拦截，刷写
成功。设备当前为主线 `3ccec64b58d4`，boot 分区 SHA256 与 artifact 一致。
未更新 ACK 恢复备份、修改分区表或使用 fastboot boot。

首次显式读取、随后四次 USB SSH 及一次 Wi-Fi SSH 读取均成功且结果一致：

|字段|结果|
|---|---|
|header 长度|68 字节，两份精确快照相同|
|loader|8192 字节，在本次静态 SCP 保留区内|
|firmware|1572864 字节，在同一保留区内|
|DRAM|305120 字节，在同一保留区内|
|完整 DRAM mapping|1220608 字节，在同一保留区内|
|payload 相互及与 share 重叠|无|
|backup 地址|与双核历史公式匹配|
|regdump|1048576 字节，不在 firmware/share 内，未映射|
|READY|unknown|

这些结果与此前 6.6 初始化后 CPU 缓存的必要字段检查一致，但这是本次
LK→主线后直接 TCM 的有限读取，不是复用 6.6 软件 READY。没有检查固件
内容、hash、签名、身份或 NVRAM，也没有证明 loader/backup 内容有效。

前后 core0 reset alias bit0/gated/halt 均0、两组稳定，mux selector0/
ungated。主线实际分配 firmware `0x9fa00000/0x500000`，share
`0x8d000000/0x320000`，未把 share 地址写死在驱动中。
AP-only state 的 scp_access=0 只描述那次 state 采样，不表示整个实验
没有 core0/TCM 读取；两个单独属性执行了文中限定访问。

USB/Wi-Fi SSH、8 核、sda/sdb/sdc RO=1、root overlay、cache ext4
ro/norecovery 和 lower SquashFS 通过；保存 dmesg 的 BUG/Oops/SError/
panic/Unable to handle 关键词扫描未见匹配，不声称日志完全无警告。
未执行温度/按键或 USB 故障切换测试，设备保留主线运行。
[机器可读证据](evidence/modem-scp-tcm-runtime.json)。

## 接续

成功解码后仍保持 READY unknown。先核对当前 metadata 与本次动态分配，
再规划 mailbox RX/IRQ、clock ownership、reset generation/STOP 失效和
独占启动者；loader/备份来源、有效期仍需单独证据。不能因 header 有效
而直接执行恢复复制、清零 DRAM、释放复位、发送 awake 或启动基带。
