<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 基带供电：SID3 生命周期与实机检查

2026-11-14，AI 辅助分析与测试。接续 [R1/R2](MODEM-R1-R2.md) 和
[资源契约](MODEM-RESOURCES.md)。资源绑定、电压观测和基带上下电分别验收。

## shutdown 策略

保留主线 `drivers/regulator/mt6315-regulator.c` 的现有 shutdown，不新增
SID3 特例，也不新增跳过 shutdown 的 DT 属性。本机 Android 4.19 的
`drivers/regulator/mt6315-regulator.c:mt6315_regulator_shutdown()` 与其一致：

|步骤|地址|操作|
|---|---|---|
|解锁高字节|`0x3a0`|写 `0x9c`|
|解锁低字节|`0x39f`|写 `0xea`|
|使能 PMIC 关机序列|`0x139`|置 bit 0，保留其他位|
|上锁低字节|`0x39f`|写 0|
|上锁高字节|`0x3a0`|写 0|

A 的 `MT6315_PMIC_RG_TOP2_RSV2_ADDR` 展开为 `MT6315_TOP2_ELR7`，即
`0x139`。主线使用不同宏名，但地址、值和顺序相同。这个源码对照支持
保留现有策略；不等价于已验证主线 SID3 shutdown 的实际执行和重启恢复。
普通 `reboot(2)` 经过 device shutdown，停止喂狗造成的硬件复位绕过它，
所以后者不能用来验收此回调。

MT6315 probe 本身没有厂商 misc 初始化，而是建立 regmap 并注册四路 buck。
当前命名节点没有 min/max、initial mode、boot-on、always-on 等约束；
regulator core 的 `machine_constraints_voltage()` 仅在满足 apply_uV 和
范围条件时设置电压。保留 `regulator_ignore_unused`，不在本轮顺便测试
unused rail 关闭。获取引用可能涉及父级 supply 解析，不能泛称整个框架零写入。

## 电压观测与后续恢复契约

|供电|provider|指令 VOSEL|实际 DA VOSEL|
|---|---|---|---|
|VMODEM|MT6315 SID3 VBUCK1|`0x1449`|`0x1499`|
|VNR|MT6315 SID3 VBUCK3|`0x144d`|`0x1599`|
|VSRAM_MD|MT6315 SID3 VBUCK4|`0x144f`|`0x1619`|
|VRFDIG|MT6359P VPU|按 MT6359 regulator descriptor|需单独核对|

主线 MT6315 `get_voltage_sel` 读取指令寄存器；sysfs `microvolts` 和普通
`regulator_get_voltage()` 因而**不能证明实时 DA 电压**。`state` 读取
BUCK_TOP_CON0 使能位，`status` 则走 DBG4 的实际输出状态。不要把这些
不同含义的字段合并为“供电正常”。无需为首次引用检查新增任意寄存器接口。

A 的 `mt6315_S3_default_vosel()` 首次从 DA 保存三路 selector，后续向 RG
恢复；V 的已可用补丁则通过 regulator 接口保存 RG 电压并恢复。两者的
采样源不同，V 的成功经验不能消除此差异。V 修复也明确表明运行中 DVFS
会改变电压，不能把初始化后很久才读到的数值标成 LK 启动电压。

平台 consumer 实现恢复前仍需闭合：

1. 在 Linux 尚未启动 MD/SCP、DVFS 尚未接管时采样，并检查采样错误与
   selector 范围；明确采用 DA 还是 RG，记录来源和有效期。
2. 保持 VMODEM/VSRAM_MD 差压和稳定时间，核对三路恢复顺序、第四路 VRFDIG
   以及恢复时 MD 电源域/复位/保护状态。
3. 统一由平台 consumer 管理，禁止绕过 regulator 的全局名字补查和并发写。
   DT 显式 supplies 为必需依赖，缺失、defer 和写失败必须向上传递。
4. 恢复前确认 MD quiescent，不允许在固件 DVFS 活动时强制同步；任何失败
   不释放复位，不把首次快照无条件跨 AP 启动或固件版本持久化。

## 显式资源测试镜像

外部构建脚本 `mt6893-direct/modem-resources-image.py` 临时启用 M0 inspector、
SID3 provider、VPU phandle、resource checker 和普通 CCIF gate；打包后逐字节
恢复板级 DTS/defconfig，默认仍关闭。没有 MD1 domain 节点、MMIO/IRQ/reset
consumer，也没有 MD/SCP 启动入口。

`7576d31c76a4` 已通过 ARM64 构建、M0/资源/R3 主机测试、原 FDT 及其他
构建器回归。资源测试工具新增 `--enabled-dtb`，显式检查测试变体中的节点
可用性，同时继续要求四路供电接线、四个时钟和无附加控制资源；`--dtb`
仍强制检查默认 disabled 状态。构建器对 board 和 merged DTB 使用相同模式。

## 实机结果与限制

`7576d31c76a4` 已经通过 `fastboot flash boot` + `fastboot reboot` 启动。
首次 probe 因 provider 未就绪 defer，随后正常重试成功：

```text
[1.291694] probe of 0-03 with driver mt6315-regulator returned 0
[1.863587] op6893-ccci-resources modem-resources: four supply and four clock references acquired; modem/SCP not started
```

四个显式 regulator supplier 链接存在；四个 clock consumer 名称符合 DT，
prepare/enable 计数均 0，硬件状态为继承的 enabled。四路 rail 的 `num_users`
也均 0；持有引用与已调用 enable 是不同状态。读数如下，两次启动均一致：

|rail|指令电压|state|status|
|---|---|---|---|
|VMODEM|800000 uV|enabled|on|
|VNR|800000 uV|enabled|on|
|VSRAM_MD|800000 uV|enabled|on|
|VRFDIG|700000 uV|enabled|on|

这些是开机后通过 regulator sysfs 读取的指令电压，不能称为 DA 快照或
固定启动目标。未执行任何 MD 电压设置、enable、CCIF 访问或 MD/SCP 启动。

随后执行 `sync; /bin/busybox reboot -f`，向内核发起正常重启请求；无需再次
刷写即返回同一镜像，boot_id 改变，资源检查再次成功。USB ECM/TAP SSH、
独立 Wi-Fi SSH、两次各 3 包外网 ping 零丢包；cache ext4 保持只读，
SquashFS/Overlay Debian rootfs 正常。ACK 备份和 GPT 均未修改。

**此结果仍未闭合 shutdown 的逐步硬件验收**：pstore console 只留下早期
启动片段，没有 SID3 shutdown 尾部，因此无法单独排除退出过程中由看门狗
兜底复位。现存 `dmesg-ramoops-1` 的 panic 明确属于旧镜像 `48fd636e6955`，
不是本次镜像；不清除或归因到本轮。后续若要求证明关机回调逐步完成，应先
提供能保留退出阶段记录的观测路径，而非仅凭最终再次启动就标记通过。

本镜像包含 R3 代码，但板级没有 MD1 域实例，未执行该电源序列。验收仅覆盖
资源绑定及两次启动的短时回归，不代表 CCIF 通信、SCP、基带或蜂窝可用。
见 [精简证据](evidence/modem-resources-runtime.json)；外部日志目录为
`mt6893-direct/evidence/modem-resources-live/`。
