<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893：主线 AP 侧 SCP 前提观测

2026-11-15，基于 `6db0f4606d6e` 工作树，AI 辅助实现与实机测试。
用户授权自主上机，并明确包括刷主线。接续
[6.6 缓存/内存观测](MODEM-SCP-OBSERVATION.md)。

## 本轮实机结论

从当前 Android `6.6.30-4k-g061b7bdafc86` 重启到 fastboot，预先排队
`flash boot` 与紧接的 `reboot`，成功进入主线镜像 **`c55ce7327907`**：
`7.3.0-op6893-d1-c55ce7327907+`。没有使用不可靠的 fastboot boot。
只刷 boot，没有改分区表或恢复备份。旧 6.6 诊断模块未复用。

|项目|主线本次结果|
|---|---|
|TOPCK CLK_CFG_0 SCP selector|0，对应 vendor parent 0：26 MHz|
|SCP mux gate bit23|0，未关闭|
|连续两次只比较 SCP selector/gate|相等；跨 SSH 调用重复也相同|
|静态 firmware reservation|`0x9fa00000 / 0x500000`|
|本次主线动态 share 分配|`0x8d000000 / 0x320000`|
|SCP 寄存器 / TCM 访问|无|
|SCP READY|未知，明确输出 ready_known=0|
|USB ECM SSH / Wi-Fi SSH|均可用|
|CPU / rootfs|8 核；cache ext4、lower SquashFS、overlay 根目录正常|
|UFS sda / sdb / sdc|三者 RO=1|
|kernel fault 扫描|没有 panic / Oops / BUG / Unable to handle|

主线的 share 分配与前次 ACK 相同是本次结果，代码没有写死该地址。
selector/gate 观测不等于运行频率实测、时钟所有权、访问权限或 SCP 已启动；
更不能据此直接执行 AP awake 或启动 MD。没有注册 SCP mailbox IRQ、
读取固件、触发 IPI、改变 mux/gate、请求电源域或发送 SCP/MD reset。

第一次综合回归命令查询 thermal_zone0/temp 时该入口不存在，且 findmnt 的
多个 positional 参数没有产生预期输出；已改为明确查询挂载树并重复采集。
未将不存在的 thermal 入口视为本轮温度验收，最终结果只声明表中范围。

## 实现边界

新增默认关闭 `OP6893_CCCI_SCP_OBSERVE` 和
`drivers/misc/mediatek/ccci/ccci-scp-observe.c`；板级 `scp-observe` 节点默认
disabled。实验构建器仅临时启用该节点和选项，打包后恢复 DTS/defconfig。

两个 reserved-memory 节点带本地 label/phandle，并与 LK 同名，合并时沿用
既有的几何属性复制机制；不导入 vendor compatible/phandle。
动态 share 的 size/alignment/alloc-ranges 沿用本机 ACK 配置，仍由主线分配。
consumer 通过 `of_reserved_mem_lookup()` 读取本次内核记账，不映射内存。
拒绝非 reserved-memory 子节点、disabled、缺 no-map、reusable、未分配、
空地址/长度、超出 u32 的跨度以及两块保留区重叠。

TOPCK 通过已有共享 syscon regmap 访问，不创建重叠 platform owner；sysfs
`/sys/bus/platform/devices/scp-observe/state` 每次只读两次 `+0x10`。
只解释 bits16..18 与 bit23，不输出整寄存器。错误直接返回，变化标记
samples_equal=0；不缓存成功值、不写寄存器、不修改 clock framework 引用。

核对当前 syscon 实现：regcache 为默认无缓存，注册时可能获取/prepare 首个
clock 并 deassert 可选 reset。本板 TOPCK 第一个输入为无硬件控制的固定
ULPOSC，节点没有 resets；当前 PMIF clock driver 已使用同一个 syscon。
因此本诊断不增加 SCP clock 控制，不从“syscon”这个名字推断绝对无副作用。

新增 binding `realme,op6893-scp-observe.yaml` 为本地临时诊断契约，不是完整
SCP 硬件描述。没有拿 MT8192/MT8195 compatible 直接匹配本机。

## A/V 启动路径的进一步核对

A 的 `scp_dvfs.c:mt_scp_dvfs_pdrv_probe()` 先 enable scp_sel，并选择
26 MHz、请求 26M 资源，然后才校准/初始化。V 的 `scp_init()` 也明确在访问
SCP reg/SRAM 前请求 mux/26M。两者读取 TCM 缓存、注册 READY 接收 channel，
最后 `reset_scp(SCP_ALL_ENABLE)`，向 core0 GRP1/GRP2 写本次 share 地址/大小，
再向 `R_CORE0_SW_RSTN_CLR` 写 1 释放复位。

A/V 初次启动路径没有从 `remoteproc_scp` 文件通过 request_firmware 加载
固件；普通完整恢复则从保留区复制 loader、重写 metadata，并从 DRAM 备份
恢复运行区。这支持“启动依赖 LK 已放置的镜像/metadata”的后续调查方向，
**不证明**实际 LK 载入来源、当前 TCM 内容、初始 reset 状态或备份有效性。

A 的 READY handler 从 IPI_IN_SCP_READY_0/1 收到 TCM size，才走软件 READY
通知；当前 mainline observer 完全没有这个流程。A handler 在 image size
核对之前设 ready 的顺序也不能照搬为新状态机的验收条件。

同板 `scp_reg.h`：core0 cfg base 0x10730000，reset CLR+0 / SET+4，
STATUS+0x70 的 bit0 为 gated、bit1 为 halt。A 正常诊断路径多次读取
SET/CLR，停止路径写 SET=1，初始释放写 CLR=1，支持后续限定读回实验。
core1 未启用，本轮没有碰它。这里尚没有实测 reset/status，不能提前描述
SCP “已在 reset”或“正在运行”。

## 验证与下一步

新增主机测试编译实际 reservation/state 函数，以 ASan/UBSan 验证资源缺失、
边界、no-map/reusable/disabled、引用释放、两次 regmap 错误和变化判据。
它不模拟总线访问能否完成，也不是并发时钟控制的证明。
ARM64 启用 Image.gz、默认关闭 Image.gz/modules 构建及 strict checkpatch、
binding 文档和 board/merged DTB 定向 schema 检查通过；现有完整镜像构建器的
FDT、modem、SCP、PMIC、LVTS 主机回归和 boot 回读检查通过。
编译器无新增警告；恢复默认 defconfig 时仍有原有 FW_LOADER/VT 重复赋值
两条 Kconfig 提示，本轮没有改动这些配置。

后续独立实验：

1. 以当前 mux 26M/ungated 为运行时门槛，确认 core0 reset/status 的读回和
   core0 cfg/TCM 的独立映射边界，读取前后重新核对 mux。异常不强行访问。
2. 在 bootstrap 访问前提成立后，仅复制 header 的版本和精确 68/72 字节快照，
   私下解码并与本次静态保留区比较；不导出未知尾字段或映射 regdump。
3. 即使 header 有效，也继续保持 READY unknown；随后接 mailbox RX/IRQ、
   代际管理和独占启动责任，收到真实 READY 后才测试共享 awake。

设备最终保留在 c55ce7327907；本轮不触发 Wi-Fi/USB 的故障切换实验。
机器可读结果：[modem-scp-prerequisites-runtime.json](evidence/modem-scp-prerequisites-runtime.json)。
