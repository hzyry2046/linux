<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 MD 平台 owner、LK 接管与冷启动

2026-11-16，AI 辅助实现。新增代码已通过离线测试及启用 ARM64 构建，
**尚未刷入或执行 MD 上下电**。当前设备仍为 `e8509e81dbc3`，本轮只经
Wi-Fi SSH 读取六个 AP 侧寄存器，没有执行 SMC、重启或更新 ACK 备份。

## 改变方案的实机证据

当前主线没有接管 MD1，但 LK 留下的域已经 ON：

|寄存器|地址|本次值|
|---|---|---|
|PWR_STATUS|0x1000616c|0x10580fff|
|MD1_PWR_CON|0x10006300|0x0000000d|
|MD_BUCK_ISO|0x10006398|0x00000000|
|保护1 ACK|0x10001228|0xe70c500e|
|保护2 ACK|0x10001b90|0x00000001|
|保护3 ACK|0x10001bc4|0x00050000|

这些值满足 ACK=1、RESET_B/PWR_ON=1、隔离=0、三组 MD 保护 ACK=0，
不能继续假设初始状态完全 OFF。它们只说明 MTCMOS 状态，不证明 MD CPU
是否仍在执行、LK 检查成功或固件可通信。此前“MD 未启动”应理解为 Linux
尚未发出 CPU 放行，而非 LK 从来没有给 MD 上电。

本机 A `mt6885/md_sys1_platform.c:md_start_platform()` 首启时先用
`CCCI_CONTROL(6,3)` 检查 LK/BROM 完成，最多100次、间隔20ms，然后关闭
MD1，随后才走正常启动。这里据此增加明确的 `takeover` 操作，未使用
`(6,0)` CPU boot、猜测的18/19或不同芯片的时钟清理流程。

## 所有权与操作

`CONFIG_OP6893_CCCI_MD_PLATFORM` 是 built-in、默认关闭；板级
`modem-platform` 与 `md1` 域也默认 disabled。平台节点与只读
`modem-handoff` 共用 tag buffer，不能同时启用；准备测试时也关闭旧
`modem-resources` 检查器。SID3、VPU、普通 CCIF 时钟提供者仍需按既有方案启用。

同一个 LK inspector 完成完整链和[子区校验](MODEM-SMEM.md)后，将布局复制
给 owner；tag 快照仍及时清理，不再丢弃后续 HIF 需要的 CPU 布局信息。
平台基础层不映射或清零 SMEM/NVRAM，不导出固件或原始 tag；后续可选
[CCIF扩展](MODEM-CCIF.md)仅映射/格式化 ID19/20 的普通环。

四路 regulator 取得真实引用，要求已启用、正电压、两次读取一致。记录本次
启动的 RG 电压（不是 DA），执行前再次核对；不设置电压或调用 regulator
enable/disable。这样只实现未改变基线的首次冷循环，不承诺 DVFS 后热重启。

平台节点本身不含 `power-domains`，避免 platform bus 在 probe 前自动上电。
lookup 子节点通过 `dev_pm_domain_attach_by_id()` 附着 MD1，虚拟设备初始
runtime-suspended，附着不调用上电。genpd 根据精确 OFF/ON 读回初始化软件
状态；混合状态拒绝接管。继承 ON 时，provider 拒绝 unused-domain 自动关断。
只有持有 active runtime 引用的显式接管者才能解除这一 veto。

启用实验后，`/sys/bus/platform/devices/10209000.modem-platform/md_power` 接受
（新增CCIF资源前的旧节点名为`modem-platform`）：

- `takeover`：仅适用于继承 ON。先 CHECK_DONE 与电压/域状态核对，再取得
  runtime 引用、解除继承 veto，执行 MD1 OFF→独立 OFF 读回→SRC CLK 清低
  字节→flight=true。未取得普通 CCIF enable 引用，因此不会替 LK 关闭这些门。
  成功后进入 cold，允许一次新的 ON/OFF；失败的 CHECK_DONE 不执行断电。
- `on`：仅适用于 cold。完全 OFF/电压核对→四个普通 CCIF 门→infra+0xf0c
  低字节0x21→SPM unlock/+8 bit21→SMC flight=false→runtime MD1 ON→独立
  ON 读回。不会发出 CPU 放行命令；可选CCIF扩展随后显式 prepare。
- `off`：仅适用于本 owner 的 powered。可选CCIF先完成stop；runtime MD1 OFF→独立 OFF 读回→
  SRC CLK 清低字节→flight=true→释放自己的四个 CCIF 门。保留四路 regulator
  状态和 SPM bit21，与本机 vendor OFF 行为一致。成功后不能再 ON。

状态输出的 clocks/domain 是最后成功步骤的记账，故障时不能当作实际硬件
状态；`cpu_release_issued=0` 仅表示本驱动没有发出放行命令。runtime PM 的
OFF 回调会忽略 genpd power-off 返回值，因此实际六寄存器读回不可省略。
写操作开始后失败锁定 FAULT，保留已取得的时钟/对象，不猜测回滚；runtime
put 已减少的 usage 不做虚假的补偿或自动重试。shutdown 不接管继承 ON，
只关闭本 owner 成功开启的域；FAULT 保持现场，需重启恢复。

## 验证与接续

[平台测试](tools/test_modem_platform.py)编译实际序列及逐字抽取的寄存器/
SMC/runtime-PM 回调，ASan/UBSan 覆盖正常循环、12个冷循环和7个接管失败点、
只读失败重试、写后锁定、相邻位保持、失效读回、SMC7与SMC6/3参数、100次
CHECK_DONE超时、电压漂移和 runtime-PM veto。抽取测试不覆盖 Linux device/
sysfs/genpd 调度；完整文件通过启用内核、modules/modpost 构建。
[域测试](tools/test_modem_power.py)增加上表真实 ON 初态、自动 OFF veto 和
显式解除后 OFF，原有顺序/ACK/错误注入继续通过。默认 DT 中域/owner 禁用，
binding 和 DT 校验通过。[结构化结果](evidence/modem-platform-validation.json)
区分离线测试与实机只读观测。

下一次刷机合并检验当前 LK 子区、接管/冷循环及普通 CCIF，避免为资源引用
或每个寄存器单独刷机。接续先做：

1. 在这个 owner 预留 AP/MD CCIF 两个4K窗口与SPI194/195，IRQ先保持 masked；
   上电后按 A 的 infra+0x150/+0x154 bit8 复位，清双方各512B SRAM，写入
   最后12B的0x7274626e、RAW_MDSS_DBG 的 MD 地址与大小。不能沿用 Q 的地址。
2. 接正常/异常 ring、IRQ/worker、控制通道和停止顺序；普通 HIF 与 CCIF2
   分开，后者专供 SCP/CCISM，避免重复复位和时钟归属。
3. 衔接 SCP 常驻、CCISM 及 FS/RPC/NVRAM 工作副本服务，齐备后再发 `(6,0)`
   验证 HS1/HS2。电源循环成功本身不代表基带 READY。

尚未验证真正的 MD1 开关、ATF CHECK_DONE/flight 返回契约、genpd 与本机
LK 的完整接管时序、冷循环电压是否足够或任何 CCIF/基带通信。
