<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP core0：限定复位/状态读回

2026-11-15，AI 辅助实现与测试。源码基线 HEAD `6db0f4606d6e`。
继 AP mux/保留区观察后，单独增加默认关闭的
`CONFIG_OP6893_CCCI_SCP_CORE0_OBSERVE`。本实验不启动 SCP/MD。

## 访问契约

同板 Android RV `scp_reg.h` 定义 core0 cfg `0x10730000/0x1000`，
CLR+0、SET+4、STATUS+0x70；STATUS bit0 gated、bit1 halt。
`scp_helper.c` 在正常诊断路径读取 SET/CLR，等待停止路径读取 halt。
停止写 SET=1，释放写 CLR=1；**本实现没有这些写操作**。

板级 observer 节点改为 `scp-observe@10730000`，默认 disabled；reg 描述
core0 cfg。额外开关启用时，probe 只校验地址/长度并取得独占资源映射，
不读取硬件。AP-only 模式不映射 core0，显式读 core0 返回 EOPNOTSUPP。
节点的 sysfs 路径因此变为
`/sys/bus/platform/devices/10730000.scp-observe/`。

显式读取 `core0` 属性时以 mutex 串行化：

1. 从既有 TOPCK syscon 读 +0x10；只允许 selector0 且 gate=0。
2. 读取 CLR、SET、STATUS 各两次，只保留 reset alias bit0/status bits0..1。
3. 重新核对 mux 条件；读错误或条件变化直接失败。
4. 两组已解释位不一致则返回 EAGAIN；成功仅输出这些位和 READY unknown。

这里的 CLR/SET 为 alias 读回，不能直接据此断言处理器正在复位或运行。
前后 AP mux 采样也不能排除中间瞬时变化，不提供频率实测、clock ownership
或其他总线/电源条件证明。当前实验要求没有其他 SCP consumer/控制者；
mutex 仅约束本观察器，未来有共享 provider 后必须重新设计访问所有权。
MMIO 若无法完成，软件没有可靠超时保护，因此先只验证此三个地址；
TCM、core1、PC/LR/SP、GRP1/GRP2、mailbox 和 awake 均不访问。

## 构建与验证

测试镜像 `0a53a32dd3b3`，release `7.3.0-op6893-d1-0a53a32dd3b3+`。
boot SHA256 `90b03d137eae9cf08525e2d8ea9006505cd7afc48a142e3d3a6597154ecbb6bd`。
完整 artifact 位于 `mt6893-direct/dist/0a53a32dd3b3/`；启用 Image.gz、
现有完整构建器回归、binding 文档及启用 board/merged DTB schema 均通过。
实验构建器恢复了 DTS/defconfig 原始字节。

`tools/test_modem_scp_core0.py` 编译实际 reader，以 ASan/UBSan 验证未映射
拒绝、所有不许可 mux 条件的前后拒绝、regmap 错误传播、六次 MMIO 的精确
地址/顺序、所有解释位组合及样本不稳定拒绝；错误不覆盖 caller 输出。
既有 AP observer 测试通过。strict checkpatch 为 0 errors/warnings/checks。
这些主机测试不证明实际总线访问能够完成。

默认关闭 Image.gz/modules 及默认 FDT merge 回归也通过，默认 vmlinux 没有
observer 符号，节点 disabled。编译器无新增 warning。

## 真机结果

用户建议并采用 sync + SysRq reboot，fastboot 拦截后已排队的 boot flash/
reboot 成功；设备运行 `0a53a32dd3b3`，boot 分区 SHA256 与 artifact 一致。
原 ACK 备份及分区表不变，不使用 fastboot boot。

首次显式读、随后四次 USB SSH 读取及一次 Wi-Fi SSH 读取均成功，每次得到：

```
reset_clr_bit=0 reset_set_bit=0 core_gated=0 core_halt=0 samples_equal=1 ready_known=0
```

前后 AP state 均 selector=0/gated=0/samples_equal=1。主线记账仍为
firmware `0x9fa00000/0x500000`、share `0x8d000000/0x320000`。
这仅验证三个指定寄存器的有限读回能够完成，未证明 reset alias 的完整
语义、TCM 可访问、固件已载入或 CPU READY。state 属性中的 scp_access=0
仅描述 AP-only 的该次采样，不能解读为本实验从未进行过 core0 MMIO。

USB/Wi-Fi SSH、8 核、sda/sdb/sdc RO=1、overlay root、cache ext4
ro/norecovery 及 lower SquashFS 正常。保存 dmesg 的明确故障关键词扫描
未见 BUG/Oops/SError/panic/Unable to handle；不据此声称所有日志没有警告。
本轮未进行温度/按键/USB 故障切换测试，最终保留主线运行。
完整本地日志在 `mt6893-direct/evidence/scp-core0-live/`；
[机器可读结果](evidence/modem-scp-core0-runtime.json)。

## 接续

先以真机 core0 读回决定下一轮是否允许 TCM bootstrap 观察。下一轮仅接受
struct_size 为 68/72 的精确 header 长度，使用已有 CPU snapshot decoder，
与本次主线 reserved-memory 记账比较，不导出原始固件/未知字段或映射
regdump。header 有效仍不能视作 READY。真正解除复位前仍需 RX/IRQ、
代际失效、独占启动责任以及真实 READY 事件路径。
