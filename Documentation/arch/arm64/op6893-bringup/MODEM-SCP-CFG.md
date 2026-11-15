<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 SCP cfg：与资源投票共用唯一所有者

2026-11-15，HEAD `6db0f4606d6e` 工作树，AI 辅助本地源码分析、实现和测试。
接续 [SPM 资源持有](MODEM-SCP-RESOURCE.md)。本轮只预留/映射资源；不执行
cfg 寄存器读取或写入，不处理消息，不建立 READY。实机状态以文末为准。

## 地址及完成操作的责任

同板 Android 4.19 `drivers/misc/mediatek/scp/rv/scp_reg.h` 定义
`SCP_TO_SPM_REG = cfg + 0x94`；`scp_awake.c:scp_clr_spm_reg()` 向它写1，
注释说明这是 AP 清除 SCP→SPM 通知的操作。`scp_ipi_table.h` 将它绑定为
mailbox post callback；`drivers/soc/mediatek/mtk-mbox.c` 的 ISR 在复制后调用
post callback，随后才写 mailbox CLR。该寄存器不是 AP awake 的 infracfg
SET/CLEAR，不允许用清通知冒充 awake 或 READY。

保存 ACK FDT 的 `/scp@10700000` 中 `scp_cfgreg` 资源为
`0x10724000/0x1000`。因此 completion 地址为 `0x10724094`。此处只检查
reg/reg-names 等必要元数据，不导出 firmware、设备标识或校准数据。

同板6.6的 `scp/rv/scp_awake.c` 还支持 `scp-cfgreg-ap-en` 下 AP cfg+0x18，
以及 `scp-ipc-wa` 下清 GPR7。历史本机 FDT 未启用它们；当前实现不提供这些
替代操作，节点上出现任一属性即拒绝。qqcandy 的同名函数仍为 cfg+0x94
写1，但它属于 MT6895，不能作为本机设备地址或上电时序的依据。

厂商 reset 路径另有写0xff；本轮没有照搬。复制后写1、reset写0xff、
mailbox按位ACK 和 AP awake 各自的用途不能合并。

## cfg 归属

新增默认关闭 `OP6893_CCCI_SCP_CFG_RESERVE`，依赖既有内建
`OP6893_CCCI_SCP_RESOURCE_HOLD`，没有创建第二个 platform owner 或 SMC caller。
同一个实例持有 CCF 引用、SPM pin 状态和 cfg 映射；后续 RX/STOP/reset 应复用
其串行化责任。当前的 mutex 只保护已实现的 vote/query；尚无 RX 并发调用。

DT 节点更名为 `scp-resource-hold@10724000`，增加 `reg` 和 `reg-names=scp-cfg`，
默认仍 disabled。新版本的 sysfs 位置对应
`/sys/devices/platform/10724000.scp-resource-hold/`；旧测试镜像仍使用旧路径。
这次板级实验 binding 要求完整 cfg 资源，旧的无 reg 实验节点需同步更新。

probe 先沿用全局唯一实例 claim，再核对命名资源的地址/大小，使用
`devm_ioremap_resource()` 申请整个4 KiB窗口。申请冲突或映射失败均终止 probe；
devres 清理本次引用/claim，不发送 SMC release、不关闭 provider 常驻时钟。
不会绕过资源管理器直接 ioremap，也不分别映射 completion 的4字节，让不同
客户端各自操作同一个 cfg。

该窗口预留并不等于固件放弃访问，也不能防止其他驱动绕过 request_mem_region。
当前不存在 cfg 读写 API。只读 `cfg` 属性仅报告内核映射是否成功及阶段能力：
`reserved=1 bytes=4096 register_reads=0 register_writes=0 completion_enabled=0 ready_known=0`。
这些零是当前代码不存在寄存器操作的描述，不是硬件访问计数器或清位成功证明。
未启用映射选项时 `cfg` 返回 EOPNOTSUPP；查询 cfg 不发送 SMC。

## 写入前还缺什么

1. 唯一 IRQ/worker owner：先不使能 IRQ，准备全部 RX 目的缓冲，未知位或
   持续触发时屏蔽，设置有限排空预算，并和 STOP/reset 同步。
2. completion callback 只能在本批所有 payload 已复制之后、精确 mailbox
   ACK 之前执行。不得通过 sysfs 试清继承的通知；不得依赖真实 READY 后的
   awake，否则 READY 消息自身接收形成循环依赖。
3. 明确 MMIO 排序/总线写完成的依据。厂商函数只有 writel，当前未证明
   CLR 可安全读回，也未确认某个同设备寄存器可以作为 flush。不能把
   通用内存屏障或任意寄存器读当作设备完成证据。参考内核
   `Documentation/driver-api/io_ordering.rst`；该通用文档不证明本机必须有
   某种特定 flush，也不证明本机任意跨窗口 read 会完成此前写入。
4. 持有26M与有效 SPM pin、reset generation、旧消息拒绝和失败失效策略。
   当前继承状态和空 pending 都不能建立本代 READY。接收路径闭合之后才
   推进受控 reset/启动；这一轮不解除 reset 或启动 SCP/MD。

## 验证

`tools/test_modem_scp_cfg.py` 提取实际 reserve/cfg_show 函数，ASan/UBSan
覆盖精确资源、两实例资源冲突、缺失资源、移位/缩短/扩大/倒置/溢出窗口、
两个替代属性的所有组合、映射错误传播和状态读取；模拟窗口保持未修改。
该测试没有模拟完整 devres、总线或固件，不能替代实机访问验证。

启用/默认 ARM64 Image.gz/modules、FDT merger 回归通过；保存的两种配置
board/merged DTB 均保持完整 cfg 资源，status 分别 okay/disabled，三份
binding 的定向 schema 检查通过。新增选项在启用 config 中为 y，默认 config
和 vmlinux 中实验实现关闭；临时 DTS/defconfig 已恢复。resource 与 RX
sanitizer 回归通过。resource owner 全文件 strict checkpatch 为0/0/0，编译器
无 warning；默认配置仍有已有 FW_LOADER/VT 重赋值提示。

离线证据：`/data/src/mainline/mt6893-direct/evidence/scp-cfg-offline/`。
实机镜像 `80e79074de00` 已刷 boot 并启动，boot 分区 SHA256 回读与
artifact 相同。`/proc/iomem` 的 `10724000-10724fff` 由
`10724000.scp-resource-hold scp-cfg` 占有；cfg 状态为 reserved=1、4096字节，
completion_enabled=0。没有以冲突 probe 故意扰动真机，资源冲突拒绝仅主机覆盖。

首次资源查询仍为6种资源、1用户、SCP缺失；随后显式写一次26m，注册有效
SCP user1，mask=0x02、pin_verified=1、fault=error=0。USB连续三次及Wi-Fi
读回稳定。CCF enable/prepare=3/3、rate=26M，core0/header/mux与前轮一致，
五组pending/unknown全0、irq_requested=ack_writes=0、READY未知。
USB/Wi-Fi SSH、8核、sda/b/c只读、cache ext4 ro/norecovery、lower SquashFS
ro和overlay根目录回归通过；指定故障关键字扫描无匹配。未测试温度、按键或
USB故障切换。没有读取/写入cfg寄存器、清通知、安装IRQ、发awake、解除reset
或启动SCP/MD；设备保留上述主线和常驻pin，ACK备份与分区表不变。

完整实机日志：`/data/src/mainline/mt6893-direct/evidence/scp-cfg-live/`。
结构化证据见 [cfg validation](evidence/modem-scp-cfg-validation.json)。
下一步先做唯一 IRQ/worker 的离线 containment/预算/generation 框架，并继续
核对 completion 写排序；未闭合这些条件前不通过试清通知推进。
