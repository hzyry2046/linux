# MT6635 thermal trim：位域语义审计

2026-11-04。接续 attempt87；本轮仅主机测试与本地编译产物反汇编，
没有刷写、触发新一次 CONN 实验或改变设备寄存器。设备仍运行
`4d408b45c192`，Wi-Fi 未可用。实现、测试与本文由 AI 辅助完成。

## 已确认的差异

厂商 `connsys_a_die_thermal_cal()` 使用第二个 efuse 结果字。三个模拟
寄存器操作均调用 `consys_spi_write_offset_range_nolock()`。该函数取值为：

```c
value >>= value_offset;
value = GET_BIT_RANGE(value, size, 0);
value <<= reg_offset;
reg_mask = GENMASK(reg_offset + size - 1, reg_offset);
data2 = (data & ~reg_mask) | value;
```

`GET_BIT_RANGE(data, end, begin)` 定义为 `data & GENMASK(end, begin)`，
包含两个端点。因此取值宽度为 size+1，而清除宽度为 size。
这不是对宏名的猜测：测试直接抽取实际函数和实际宏，使用合成输入执行。

| 条件 | 寄存器 | 参数 dst/src/size | 清除掩码 | 实际输入覆盖范围 | 可能额外置位 |
|---|---|---|---|---|---|
| efuse bit7 | TOP034 THADC_BG | 12/3/4 | 0x0000f000 | bits16:12 | bit16，来自有效位7 |
| efuse bit7 | TOP038 THADC | 23/0/3 | 0x03800000 | bits26:23 | bit26，来自数据位3 |
| efuse bit15 | TOP038 THADC | 26/13/2 | 0x0c000000 | bits28:26 | bit28，来自有效位15 |

这里“额外置位”指超出本次清除掩码；若原位已经是1，寄存器值可能没有
新增变化。不能据此断言这些位在硬件上无效、保留或禁止写入。
也不能直接将取值改为 size 位并认为已保持厂商行为。

两个 TOP038 操作有顺序依赖：第二次操作可能置位 bit26；如果 bit15
有效，第三次操作随后会清除 bits27:26 并按 efuse bits14:13 重写它们，
但会额外置位 bit28。单看最终值可能漏掉中间状态，不能合并后推断等价。

仅用于复现的合成向量（两个寄存器初始均为0，**不是本机 efuse**）：

| 合成 efuse | TOP034 最终 | TOP038 最终 | 说明 |
|---|---|---|---|
| 0x00000080 | 0x00010000 | 0 | bit7 导致 BG bit16 |
| 0x00000088 | 0x00011000 | 0x04000000 | 数据 bit3 同时影响 BG 字段与 ADC bit26 |
| 0x00008000 | 0 | 0x10000000 | bit15 导致 ADC bit28 |
| 0x00008088 | 0x00011000 | 0x10000000 | ADC 先为0x04000000，后为0x10000000 |

## 私有系数的来源

厂商代码将三个整数交给 `update_thermal_data_mt6893()`：

| 有效条件 | 数据 | 用途名称 |
|---|---|---|
| bit15 | bits12:8，无符号5位 | slop_molecule（原代码拼写） |
| bit23 | bits22:16，无符号7位 | thermal_b |
| bit31 | bits30:24，无符号7位 | offset |

整体无效或某有效位未置位时，对应值初始化为0。这里仅记录源码行为；
尚未确认0是否表示正确的主线回退策略，也未证明物理温度精度。
本机私有数据、系数、有效位分布及其哈希均未读取或发布。

## 证据与可复现测试

工具：[test_conn_thermal_trim_source.py](tools/test_conn_thermal_trim_source.py)。
参数 `--source` 指向 mt6893_pos.c，`--register-header` 指向对应
consys_reg_util.h。它抽取实际两个函数和宏，stub SPI 操作只访问主机数组。
使用 `-Wall -Wextra -Werror -fno-strict-overflow -fsanitize=undefined`。
`-fno-strict-overflow` 对齐内核编译语义，保留厂商源码的 `0x1 << 31`
表达式；没有通过重写该表达式改变待测源码。

对低16位穷举，并使用四种寄存器基线；高16位按确定模式组合，同时核对
软件系数。每棵源码262144个合成用例，其中98304个与“仅替换 size 位”
比较模型不同。另测整体无效、四个最小反例及逐次写入顺序。
这不是全部32位输入穷举；位域比较模型也不是建议的硬件修复。

三份源码均通过同一组测试：

- 6.6移植所用 connectivity 模块源码。
- `/data/src/6.6-exp/android_kernel_oplus_mt6893` 的4.19源码。
- `/data/src/kernel_oddo_mt6893` 的4.19源码。

输入哈希和执行结果见 [evidence/thermal-trim-audit](evidence/thermal-trim-audit/)。
两个4.19树的现存 `out/.../mt6893_pos.o` 中也存在相同调用参数和掩码算术。
本地编译产物不等于当前/先前 Android 实机镜像；未更新恢复备份。

以6.6-exp下4.19对象为例，helper位于.text+0x25a8：

- 0x2604/2608/2610/2614：保存 size/src/dst/value。
- 0x2660 `mvn w8,w24`；0x2674 `lsr x8,x11,x8`（x11全1）：
  AArch64可变64位移位只用低6位，故得到 size+1 个低位1。
- 0x265c/2664/2678/267c/2684：构造仅 size 位的清除掩码。
- 0x2680/2688/268c/2694：取值、移位、清除、OR，额外输入位没有再次屏蔽。
- 调用点0x1640–0x1694：034/12/3/4、038/23/0/3、038/26/13/2。

完整反汇编留在仓库外
`/data/src/mainline/mt6893-direct/evidence/thermal-trim-audit/`。
这是本地host侧驱动算术的证据，不是 Wi-Fi 固件协议或寄存器电气语义的证据。

## 对后续实现的约束

下一次实机实验先只读 TOP034/038：在87的受保护私有读取流程内，执行两轮
ID→目标→ID→CTRL，重复比较和完整控制状态核对；预算、错误保留和临时
清零继续适用。初始值也可能包含 bootloader/Android 留下的私有校准结果，
因此不发布原始寄存器值、目标值或哈希，只输出读取/比较/擦除元数据。

这个只读实验可以继续，不依赖选择上述两种写入语义。真正写入前仍需明确：

1. bits16/26/28 的硬件含义、读写/复位属性及共享消费者。
2. 是否必须严格复制厂商逐次操作，还是有足够证据采用限定宽度写入。
3. 已读基线是否可安全回写；模拟内部状态是否存在不可逆或读清副作用。
4. semaphore11持有、semaphore13被动观测及数字thermal稳定检查仍不是
   原子排他；需要定义写入期间的所有权和失败后恢复路径。

本轮没有在主线增加 trim 写入口，也未修改厂商源码或声称修复了厂商bug。
若需要补充逆向，优先核对实际ACK host驱动及寄存器定义/调用方，目标不是
笼统重做整份Wi-Fi固件分析；已有本地对象足以确认上述算术差异。

## Attempt88 只读实现

独立命令 `adie-thermal-read` 在87的SYSRAM交付清除成功后，读取TOP034/038
各两次。每项使用ID→目标→ID→CTRL，合计四次目标读取、16笔SPI传输。
固定地址白名单只扩展b034/b038读命令，触发WDAT始终为0；没有a034/a038
写命令。两字基线与响应仅存在临时结构，所有退出路径显式擦除；持续状态
仅保存issued/read/matched掩码、传输计数和complete/cleared标志。
使用原始私有读取阶段的2s总预算，未通过重置时钟隐式扩大时限。
清理前最后一次guard必须成功；失败保持全部外层资源且擦除软件临时数据。
此前已清除的SYSRAM槽保持零，但失败时硬件RDAT仍可能留有私有值。
本实验只验证重复读取，不能解决额外位含义、写入权限或模拟回滚语义。

## Attempt88：TOP034/038 私有只读重复验证通过

`adie-thermal-read` 在SYSRAM交付清除后，读取两个thermal模拟寄存器各两次，
16笔ID/目标/ID/CTRL传输，四次目标读取和两项比较通过。仅输出元数据，
临时值显式清零；总数据阶段1342856846ns，原2s预算未扩大。
全部外层清理成功，CONN关闭；USB SSH、八核、存储、ADC/17路LVTS及
引脚/九组缓存哈希回归通过。设备保持 `bf54e7cab5af`，恢复备份不变。
未写入trim或启动Wi-Fi。后续需明确额外位含义、所有权与恢复语义，
不能由读取一致直接推断可以回写。见 [88](evidence/attempt-88.md)。

## Attempt89 design: private candidate comparison, no trim write

`adie-thermal-plan` extends88's successful repeated reads with private
in-memory evaluation. The actual second efuse word and repeated thermal
baselines feed two candidate sequences: literal vendor size+1-bit extraction
and a size-bit-bounded comparison model. Three operations retain vendor order.
Each no-op flag requires every intermediate step to preserve its own prior
value; equivalent requires equality at every corresponding step, not merely
at the final state. No active operations counts as no-op/equivalent.
These are comparison results, not field-validity or write-safety certificates.

Only complete/cleared and three Boolean conclusions are exposed. Candidate
values, validity bits and hashes are not output. All candidate storage is
explicitly erased, and a final existing access/deadline guard must pass before
conclusions are published. The2s budget still starts before private reads.

The host planner test compares actual extracted production code with the
actual vendor function for262144 synthetic cases and a separate transient-only
counterexample. Broader mt76 references call the similar fields VRPI_SEL,
PGA_GAIN and LDO_CTRL for MT7975/7976, not MT6635: they are comparison material,
not sufficient evidence to assign our extra bits or adopt their masks.
The MT6893 thermal query holds semaphore13 while sampling, whereas our trim
preparation holds semaphore11 and only observes13; this remains a write-side
ownership question. `update_thermal_data_mt6893` also ORs digital THERMCR1
bits17:16;88's baseline already has both bits set, but this does not establish
ownership or analog calibration correctness.

## Attempt89：两种 trim 候选在本次基线下均无需写入

`adie-thermal-plan` 在私有内存按厂商顺序计算两种候选，实测
vendor_noop/bounded_noop/policies_equivalent均1，complete/cleared均1。
比较覆盖每个中间步骤，不只是最终值；没有写入trim，也未输出有效位或
校准值。此结果不区分“无有效操作”与“已有匹配配置”，不证明物理校准有效。
总数据阶段1343797846ns，全部清理与回归通过，CONN关闭。
设备保持 `9c7b04db21e4`，恢复备份未变，Wi-Fi仍不可用。
下一步以每次重新验证的no-op条件为前提推进后续初始化；条件不成立则拒绝，
不能硬编码跳过，也不据此放开trim写入。见 [89](evidence/attempt-89.md)。
