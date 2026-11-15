<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP 双核/header：统一 owner 受限只读观测

2026-11-15，HEAD `6db0f4606d6e` 工作树，接续
[core0/core1/TCM 静默映射](MODEM-SCP-CORE-TCM-OWNER.md)。Codex 根据“继续推进”
任务辅助源码比较、实现、测试、构建和实机验证；需人工审查，不加 AI Signed-off-by。

新主线 `cebf84a7d29e` 已通过双核和精确 header 读取验收，设备保留该镜像。
这是只读观测；两核 reset alias/status 全零不能证明 reset asserted、CPU/DMA
已停止或 mailbox 隔离。没有 reset、恢复复制、IRQ enable 或 SCP/基带启动。

## 实现和前后条件

新增默认关闭 `OP6893_CCCI_SCP_OWNER_OBSERVE`，依赖统一映射、纯 CPU restore
planner、OF reserved-memory 和 TOPCK syscon。只使用此前 owner 的三个映射，
不另做 ioremap；旧 core0/TCM/pending observer 仍由 Kconfig 排除。

`ccci-scp-inspect.{c,h}` 是该 owner 的只读 helper。constructor 只检查已有
映射指针和 DT 依赖，取得 TOPCK regmap、独立 firmware/share reservations，
不调用前提回调、读取 TOPCK/SCP/TCM、发 SMC 或 pin。所有运行时入口都使用
resource/receive owner 同一 mutex，lockdep 断言该锁已持有。

DT 的 resource owner 节点增加 TOPCK 和两个 reserved-memory phandle；检查
本次 no-map、非 reusable、available 的本地 reserved-memory 及非空、对齐、
u32 范围，firmware/share/固定 TCM 彼此不重叠。不从 header 反推可信窗口，
也不映射 firmware/DRAM 载荷。binding 保留旧六/九项兼容，新增属性组成完整
依赖组；缺其中任一项拒绝。一次预检发现 YAML flow list 中含逗号的属性名
需要引号，已修正并重新构建，实际刷入的是修正后的 `cebf84a7d29e`。

### `cores`

1. 在 owner 锁下调用资源前提回调：必须已有显式 pin 且未 fault；采样前后
   CCF 均为26MHz，bounded SMC GET 验证 SCP user/valid/full mask 不变。
   未 pin 时直接返回 `EAGAIN`，不查询固件或访问 SCP 窗口。
2. TOPCK `0x10` 仅接受 selector0、gate0。
3. 按 core0→core1 顺序各读取 `+0x0`、`+0x4`、`+0x70`，再完整读一遍。
   A4.19/V6.6 的 `scp/rv/scp_reg.h` 对两核这些偏移和 bit 定义一致。
   只保留 CLR/SET bit0、status gated/halt bits0..1；不读 WDT、debug PC、
   trace 或其他寄存器。两次共12个32位readl，无轮询和自动重试。
4. 再次验证投票、时钟和 TOPCK，双核两遍值一致后才输出。失败不输出样本。
   `stopped_known=0 ready_known=0` 始终保留。

两核采样是有界的顺序观测，不是原子硬件快照。前后相同不排除其间变化或
后台 DMA/总线主机活动；这些字段不能作为后续写入控制的停止证明。

### `header`

先执行上述完整双核观测；只在 TCM+4 读取 struct_size 字段，再接受精确
68/72字节版本的两份逐字32位快照，最后重读尺寸并比较。68字节版本共36次
TCM readl，72字节版本38次；60及未知版本只读一次尺寸就拒绝。

无论 copy 是否成功，都进行后置双核/资源/时钟/TOPCK 观测；两核前后必须
相同，快照必须稳定，decoder 必须接受。失败不输出 metadata。CPU snapshot
及第二份比较缓冲在返回前清零，不把原始 header/TCM 内容保存在 owner 或 sysfs。

成功只输出精确长度及 loader/firmware/DRAM/regdump 字节数，并调用既有
`ccci_scp_plan_restore()` 得到 `restore_geometry_valid/geometry_error`。
布局不合法可以报告错误码供分析，不执行任何恢复，也不把 plan 作为操作命令。
`source_valid_known=0 stopped_known=0 ready_known=0` 明确保留；几何通过不能
证明 inherited loader/backup 的身份、有效期、一致性、认证或可执行性。

`core_tcm` 属性只报告累计实际 readl 次数；包含失败观测，读取该属性自身不
做 MMIO/SMC。写计数仍静态为零，因为该 helper 完全没有写入路径。原六页
cfg/mailbox 的独立计数不受 core/header 读取影响。

## 离线验证

- `tools/test_modem_scp_owner_observe.py` 编译实际 constructor、reader、decoder
  和 planner，ASan/UBSan 通过：constructor 零 I/O、reserved-memory 缺失/
  不合法/重叠/溢出、双核精确 allowlist、所有前后回调及 mux 失败、精确
  68/72 bounds、每个 header word 变化、跨 header 双核变化、未知版本、
  decoder 失败、geometry-only错误报告和计数。主机模型不模拟总线完成时间。
- owner harness 扩展为五配置分支，验证 inspect constructor 在映射成功后、
  IRQ 安装前调用，constructor 失败不发布 sysfs/继续 IRQ；既有 core0/TCM/
  resource/MMIO/receive/restore 回归通过。
- 启用 Image.gz/modules 和默认 Image.gz/modules 通过；Kconfig 互斥成立，
  默认无 `ccci_scp_inspect_cores` 符号，输出配置恢复默认。strict checkpatch
  对 helper、头文件、owner及planner为0 errors/0 warnings/0 checks。
- binding、启用 board/merged DTB 验证通过；旧六项 DT 仍可用，缺失观察属性
  依赖组成员的三种 fixture 被拒绝。

## 实机结果

测试镜像：`/data/src/mainline/mt6893-direct/dist/cebf84a7d29e/boot.img`，
release `7.3.0-op6893-d1-cebf84a7d29e+`，SHA256：
`8b9d75bb70a594cdf1425e78747b5c40d5772a6a722fad1015d6ca913ba7313e`。
提前排队 boot-only flash/reboot，用户确认后 sync+SysRq reboot并拦截fastboot；
boot分区回读一致，没有操作分区表或ACK备份。

|步骤|观测|
|---|---|
|启动后、未 pin|`cores/header` 均 EAGAIN；前后core/TCM读数0；资源attempted0、SCP absent|
|一次26M pin|SCP user1、mask0x02、pin_verified1、fault0|
|首次 cores|两核 CLR/SET/gated/halt 均0且稳定；core reads12、TCM0|
|首次 header|68字节，loader8192、firmware1572864、DRAM305120、regdump1048576；geometry valid1/error0；累计core36/TCM36|
|USB/Wi-Fi各三轮|两核值及header元数据一致、geometry始终通过；每轮增加core36/TCM36，最终252/252，计数精确匹配|
|接收与写入|五IRQ全部masked且所有CPU计数0；worker/queued/events/generation0；core/TCM写0，cfg/mailbox读写0、未prepare|
|已有功能|USB/Wi-Fi、八核、CCF3/3@26MHz正常；UFS sda/b/c RO，cache ext4 ro,norecovery、lower squashfs ro、根overlay|

九块资源仍统一归 `10724000.scp-resource-hold`；legacy core0访问被拒绝，
旧header/pending未暴露。故障关键词扫描零命中。没有导出固件 binary、TCM
payload、设备身份或校准数据。原始日志、配置和构建证据：
`/data/src/mainline/mt6893-direct/evidence/scp-owner-observe/`；
[结构化验收](evidence/modem-scp-owner-observe-runtime.json)。

## 接续 TODO

1. 已完成统一映射和受限读取，下一步梳理两核 assert-only 控制的可执行契约：
   哪些源可能继续发送或 DMA，什么读回可证明停止，超时如何保留 fault。不能
   只凭本轮全零样本或 vendor void WFI wait 继续写寄存器。
2. 分别闭合 mailbox pending/completion、GIC 和 CPU worker/queue 的旧代消息
   丢弃条件。普通 RX ACK/drain 仍不是 reset discard 协议，CPU reset 不自动
   证明 mailbox 已清空，读到零也不证明旧源不会继续发送。
3. 跟进 LK loader/firmware/DRAM backup 来源和生命周期证据；目前 geometry
   已在本机 header 上通过，但没有 source validity，不开放恢复复制。
4. 上述条件成立后，才发布真实新 generation、prepare receive、使能 IRQ、
   释放core0并验收新代READY，随后衔接SCP↔CCCI/MD；当前仍无start caller。
