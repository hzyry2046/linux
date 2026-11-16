<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP 首次运行证据、SET判据更正和READY1

2026-11-16，设备运行 `7.3.0-op6893-d1-248c64a7dd23+`，
源码基于 `b705479df18f`。AI辅助源码分析、实验工具、驱动修正及验证。
本轮不重启、不刷写、不改分区表或ACK备份。通过tmpfs工具执行一次2秒
初始释放实验，结束时重新SET双核。获得SCP代码执行及READY1通知证据，
尚未接入正式IRQ/worker READY状态机，没有启动基带。

## 结论

上轮“SET后bit0应为1”判据错误：同板实测CLR释放后读回bit0=1，SET断言
后读回bit0=0。两核原始读回均为`0x0000ff00`，不是整寄存器为0。
因此上轮EIO来自实验判据，不能据此归因于SCP断电、访问权限或SET写失败。
本轮不需要额外供电/内部时钟写入或猜测SMC。

|本轮步骤|实测|
|---|---|
|显式资源条件|26M pin有效、SCP资源0x02、TOPCK selector/gate=0/0|
|核配置完整读回|两核CLR/SET=`0x0000ff00`，STATUS=0|
|直接SET对照|各写1后仍`0x0000ff00`，排除仅helper记账/映射造成的差异|
|首次释放前|五组mailbox pending全0，接收STOP、五IRQ masked、generation0|
|GPR设置|由本次reserved-memory读取share地址/大小，写core0 GPR1/2|
|core0 CLR=1|core0读回`0x0000ff01`，core1仍`0x0000ff00`|
|运行约2秒|10ms间隔采样，core0 PC变化64次；不输出PC或固件负载|
|约930ms通知|mailbox3 pending由0变为`0x00009000`|
|READY1核对|IRQ15→channel22、offset30；一个word为`0x00180000`，与TCM大小相等|
|另一通知|IRQ12→channel21，logger控制；未读取logger负载或回填地址|
|结束双核SET|core0/core1读回均`0x0000ff00`，恢复原AP GPR1/2|
|结束健康检查|USB/Wi-Fi SSH可用；header68和geometry有效；未见匹配内核故障|

核时钟页只读为：`0x10721000=0x100`、`+4=0`、`+8=0`、`+0x28=1`、
`+0x5c=0`、`+0x6c=0x100`、`+0x124=0`、`+0x128=0`。这些是限定偏移的
快照，不是完整电源或实际频率证明。本机4.19 reset worker没有新6.6的
`scp_lpm_req_dram()`；两套non-secure TIMEOUT/AWAKE均用同一双核SET顺序。
没有证据要求把新式SCP SMC枚举套给本机ATF，故未发送额外SMC。

## 首次启动与完整恢复的区别

实验采用A/V `reset_scp(SCP_ALL_ENABLE)`初始路径：GPR1/2、core0 CLR、DSB。
这依赖LK已放置的TCM/镜像，不清TCM、不从backup重建，不混入vendor完整
recovery worker。初始mailbox全0后才释放，只有这次短暂运行产生了新通知。
不ACK、不清pending、不启用Linux IRQ，也未发送MD/APCCCI消息。

工具为[scp-initial-kick.c](tools/scp-initial-kick.c)，独立静态AArch64用户程序，
通过`/dev/mem`做精确32位访问、DMB/DSB；不映射TCM/DRAM，不导出PC或负载。
`/run`独占标记限制一次尝试；SIGINT/SIGTERM走重新SET清理。
运行时内核receive已STOP且没有其他SCP操作者，不能作为与活动驱动并行的接口。
主机timeout或信号不能从总线卡死/SIGKILL保证恢复；当前调用正常完成清理。

已执行工具的源码快照为外部证据目录的`scp-initial-kick-tested.c`：它只检查
READY0，因此当时打印`ready0=0`。随后独立读取READY1的一个size word发现
匹配。仓库工具已补READY1和显式TOPCK门槛，重新编译通过，**没有再次运行**；
不把后补代码描述为最初实验已覆盖的检查。READY1通知不等于可推断core1
已独立release，也不等于完整SCP客户端、双核调度或基带可用。

当前mailbox3仍保留pending=`0x9000`。内核旧`reset_state.error=-5`是上轮
helper记录，不能表示外部工具最后动作；`core_tcm`计数也不包含直接访问。
今后正式启动前必须处理这些旧消息或从新启动环境建立代际，不能直接重用。

## 源码改动和验证

- `ccci-scp-reset`：修正为SET后bit0应0，保留两核完整读回，sysfs增加raw字段。
  检查仍不证明整个DMA/mailbox隔离，默认关闭，不添加自动release。
- `ccci_scp_decode_ready0`改为`ccci_scp_decode_ready`，接受channel9/22。
  两者必须一word、非response、精确4字节，size与本机TCM相等。
  A/V明确将两通道注册到相同handler；返回成功不建立generation或READY。
- 实际reset/owner ASan/UBSan验证active-low和保留高位；实际RX ASan/UBSan
  验证双READY通道、size不符/非READY拒绝；启用ARM64定向构建通过。
- kernel文件strict checkpatch通过。用户工具的volatile MMIO/sig_atomic_t及
  stdint类型触发kernel风格提示，属独立用户态工具有意用法；无编译警告。
- 修正版完整镜像构建状态见结构化记录；设备仍运行原248c64a7dd23，未为
  这一判据修正另刷机。未重复无关外设测试或默认/启用全矩阵。

修正版完整ARM64镜像已构建为`41b233803695`，boot SHA256为
`68f571f85929bfbb29ece0e5d4f509890ad3a1f426d206c6231724951284d1fc`，
路径`/data/src/mainline/mt6893-direct/dist/41b233803695/boot.img`，未刷写。
该镜像只有修正后的assert/decoder，没有自动启动SCP的caller。实验DTS和
defconfig源文件已恢复，out保留启用配置；用户态kick工具仍是单独tmpfs实验。

证据目录`/data/src/mainline/mt6893-direct/evidence/scp-reset-access/`，
包括clock-read.log、core-read.log、direct-set.log、initial-kick.log、
ready1-after-set.log、after-usb.log、after-wifi.log、定向测试和构建日志。
[结构化记录](evidence/modem-scp-initial-kick-validation.json)。

## 下一步

下一阶段直接整合唯一owner的一次初始启动：STOP/旧消息丢弃、不可复用代际、
解析本机完整mailbox表、准备全部RX队列，写GPR1/2并释放core0，接收READY0/1。
先按同板vendor接法支持logger消息的最小消费/关闭策略，避免队列堆满或
盲目把固件给出的地址当写入目标。出现READY后再接AP awake和CCCI通信。
将这些作为一个可运行里程碑构建和测试，不再逐个映射/只读入口刷机。
完整TCM/DRAM恢复保留到需要故障恢复时实现，首次启动不依赖先写恢复器。
