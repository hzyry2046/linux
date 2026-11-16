<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 RPC 板级事实：来源、编号与完整性边界

2026-11-16，AI 辅助离线审计。接续 [RPC providers](MODEM-RPC-PROVIDERS.md)。
本轮只查主机源码及保存 FDT 的限定板级节点；未访问设备、身份接口、真实
NVRAM、校准数据或固件内容。本文不启用 provider，也不授权基带启动。

结论：保存的本机配置可以给 GPIO 编号、SIM EINT 属性和 DTSI 查询提供有界
快照。ADC 的实际生效路径忽略请求名，不能把未启用 legacy 驱动的命名表
直接作为完整 ADC namespace。下面区分“历史保存事实”和“本次启动已核对”：
前者不能自动替代后者，通用 mt6893 DTS 的空节点也不是本机不存在该功能的证据。

## 可追溯来源

路径缩写：

- `A` = `/data/src/kernel_oddo_mt6893`
- `V` = `/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/kernel/kernel_device_modules-6.6`
- `F` = `/data/src/mainline/mt6893-direct/evidence/ack-live.dtb`
- `F66` = `/data/src/6.6-exp/fdt`

下列 SHA256 固定本轮读取版本；源码行号以这些版本为准。

|来源|SHA256|
|---|---|
|`A/drivers/misc/mediatek/eccci/port/port_rpc.c`|`4319787e8a0523a0021ae653569af886f94263bf8cede3f55282f7e073fa11d5`|
|`A/drivers/misc/mediatek/eccci/port/port_rpc.h`|`4279770775f06b9de763a5037fd728114c77416c07576015edad2eb3b4c93e30`|
|`A/drivers/misc/mediatek/eccci/ccci_auxadc.c`|`d1c418aa661151f8468f7190245669cbb9a6cca635871583815ab606f7646108`|
|`A/drivers/misc/mediatek/auxadc/mtk_auxadc.c`|`5724e8b61a388da9d1fe510761b7a959bbe650396dec70a73f7b182d33a509ae`|
|`A/drivers/iio/adc/mt6577_auxadc.c`|`f2ec54f6d867ba0751c82d4457386add42eed8c6fb5bed841a1f17e61d5e8563`|
|`A/arch/arm64/boot/dts/oplus6893_20615/cust.dtsi`|`b0161279d28bc9d1ec3b8e06ae729a780008ac0714daaf174c4907dcddd3a5f2`|
|`A/arch/arm64/boot/dts/mediatek/oplus6893_20615_v1.dts`|`50e4d44b5779257ffc125ee72a0a0184a450292fbaee070af4a49699bbe9813d`|
|`A/arch/arm64/configs/mt6893_defconfig`|`7b0cb3b25947bb89304280925e9207e714cbd512b7189741ba0a0c13a4067643`|
|`V/drivers/misc/mediatek/eccci/port/port_rpc.c`|`c715e01fbb7537fdcc12f6889d1be04e5fd86590c9a04aa6818f157932486ca2`|
|`V/drivers/misc/mediatek/eccci/port/port_rpc.h`|`7bf91ff23571dde7e242d69bf8370c48904e5d5beda5cf9c0d69d1f2bb567574`|
|`V/arch/arm64/boot/dts/mediatek/mt6893.dtsi`|`99b179184856eb1695a5bf95f666d0e689a38cb6986bbd7e1bccfc12e444ab74`|
|`F`|`a71de7467be17736865302711eed5ef72e80ba165b842cee900d758d9b7cacb1`|
|`F66`|`ae2fe9628144f9b8b517bd754fd885231921a65782691dbb79f214a73233cd9f`|

`A/.../oplus6893_20615_v1.dts:22–28` 明确包括板级 common、PCBV1 和生成的
`oplus6893_20615/cust.dtsi`，但这不能单独证明设备采用 PCBV1。本文数值通过
F/F66 的对应节点再次核对，不从目录名推断硬件修订版。

`F66` 虽在 6.6 工作区，其对应节点仍为旧 DT 拼写和旧下划线属性；不能把它
说成由当前 V 通用 DTS 重新生成。`V/.../mt6893.dtsi:1730–1738` 的 GPIO mapping
为空，SIM 节点使用连字符且为空；不携带本机完整板级事实。V 的 RPC helper
新增属性拼写兼容及旧节点名 fallback，正是保留旧 DT 启动时需要的适配。

## GPIO：返回 MD-view，不返回 Linux GPIO 编号

`A/port_rpc.c:137–209` 先做固定别名转换，再按请求的属性名查
`mediatek,gpio_usage_mapping`。`get_gpio_id_from_dt():150–166` 用
`of_get_named_gpio()` 验证 AP GPIO，但另读该属性 **u32 index 1** 作为 MD-view。
`0x4002` 在 `:685–693` 明确把成功结果替换为 MD-view。不能使用动态 gpiochip
base、Linux 全局 GPIO 编号、GIC IRQ 或 phandle 作为返回值。

F/F66 的 `/gpio_usage_mapping` 有以下全部 11 个 GPIO 属性，均为三个 cell。
第一个 cell 是 `/pinctrl` 的 phandle，第二个 cell 才是下表数值，第三个为 0。
该 provider 有 `gpio-controller`、`#gpio-cells = 2`，compatible 为
`mediatek,mt6885-pinctrl`；F/F66 中无 `status = disabled`。

|准确属性名 / 可直接请求名|MD-view 值|
|---|---:|
|`GPIO_SIM1_HOT_PLUG`|43|
|`GPIO_SIM2_SCLK`|45|
|`GPIO_SIM2_SRST`|46|
|`GPIO_SIM2_SIO`|47|
|`GPIO_SIM1_SIO`|48|
|`GPIO_SIM1_SRST`|49|
|`GPIO_SIM1_SCLK`|50|
|`GPIO_FDD_BAND_SUPPORT_DETECT_1ST_PIN`|63|
|`GPIO_FDD_BAND_SUPPORT_DETECT_2ND_PIN`|64|
|`GPIO_FDD_BAND_SUPPORT_DETECT_3RD_PIN`|65|
|`GPIO_FDD_BAND_SUPPORT_DETECT_4TH_PIN`|66|

生成源码位置为 `A/.../oplus6893_20615/cust.dtsi:239–251`。F/F66 的 11 项逐项
一致。固定别名表 `A/port_rpc.c:47–70` 还产生以下四个成功请求名：

|MD 别名|MD-view 值|
|---|---:|
|`GPIO_FDD_Band_Support_Detection_1`|63|
|`GPIO_FDD_Band_Support_Detection_2`|64|
|`GPIO_FDD_Band_Support_Detection_3`|65|
|`GPIO_FDD_Band_Support_Detection_4`|66|

别名 5–9、A 和 `GPIO_RF_PWREN_RST_PIN` 的目标属性在 F/F66 中均不存在；
这是检查完整 mapping 节点后的有来源 absence，可以按 vendor `FS_FUNC_FAIL=-5`
响应。不能仅检查以上 11 个已知键就宣布其他可能的 GPIO 属性都不存在。

建议 GPIO 快照包含全部 15 个成功名字。原 vendor `strncmp(...,len)` 还接受
一些名字前缀；当前严格协议只承诺完整规范名字，不复制前缀匹配缺陷。
因此“完整 namespace”在此指全部规范请求名，而非每种畸形前缀的历史行为。
这些事实只支持 `0x4002` 编号查询，不支持 GPIO 电平、三态测量或引脚配置。

## ADC：板级 channel 2 可以证明，但完整命名表不能证明

生成板级配置 `A/.../cust.dtsi:12–23` 及 F/F66 对应节点一致：

|DT 属性|数值|legacy 驱动构造的名字|
|---|---:|---|
|`mediatek,temperature0`|0|`ADC_RFTMP`|
|`mediatek,temperature1`|1|`ADC_APTMP`|
|`mediatek,adc_fdd_rf_params_dynamic_custom_ch`|2|`ADC_FDD_Rf_Params_Dynamic_Custom`|

名字构造来自 `A/mtk_auxadc.c:1758–1789`，查找来自 `:528–547`。
但是 `A/.../mt6893_defconfig:2051,5012` 为 `CONFIG_MTK_AUXADC=n`、
`CONFIG_MEDIATEK_MT6577_AUXADC=y`。`A/port_rpc.c:121–134` 生效分支调用
`ccci_get_adc_num()`，**完全忽略请求名字**。V `port_rpc.c:135–143` 同样忽略名字。
上表只是未启用 legacy 路径的数据，不能据此让 `ADC_RFTMP` 返回 0。

F/F66 `/md_auxadc` 实际指定 `io-channel-names = "md-channel"`、
`io-channels = <&auxadc 2>`。`A/ccci_auxadc.c:24–52` 取得该 IIO channel，
把 `channel->channel` 保存为 `adc_num`，把 `iio_read_channel_raw()` 结果另外保存
为 `adc_val`；`:57–67` 分开返回二者。IIO provider
`A/drivers/iio/adc/mt6577_auxadc.c:64–88` 的索引 2 对应 `.channel = 2`。
因此历史配置的 MD channel 为 **2**，没有进行任何新采样。

现有 `struct ccci_rpc_provider` 的 `adc` 是有限的名字到编号表，表达不了
“所有通过报文校验的名字都返回同一个 channel 2”。只列一个常见 RF 名字却设
`adc_present=true` 会把 vendor 可成功的其他名字伪造成不存在。最小 provider
本轮应保持 `adc_present=false`；后续如需兼容本机，增加显式的、经过验证的
single-channel 模式，或明确收紧协议并记录兼容性限制。不得把 ADC 原始采样值、
毫伏、电池电压或采样时缓存误当编号，也不能因源码静态零初始化就宣称 channel0。

## EINT：SIM1 成功、SIM2 空节点、MD 错误码

`A/port_rpc.c:242–336` 定义七种属性及转换，规范请求名来自 `:253–257`。
F/F66 `/md1_sim1_hot_plug_eint` 与 `A/.../cust.dtsi:532–541` 一致：

|query type|读取来源|F/F66 原值|MD 返回值|
|---:|---|---|---:|
|0，NUM|`interrupts[0]`|0|0|
|1，DEBOUNCE|`debounce[1]`|10000 us|10 ms|
|2，POLA|`interrupts[1]`|8，LEVEL_LOW|0|
|3，SENS|`interrupts[1]`|8，LEVEL_LOW|0|
|4，SOCKET|`sockettype[1]`|0|0|
|5，DEDICATEDEN|`dedicated[1]`|0|0|
|6，SRCPIN|`src_pin[1]`|1|1|

因此规范请求名 `MD1_SIM1_HOT_PLUG_EINT` 的有序向量为
`[0, 10, 0, 0, 0, 0, 1]`。NUM=0 是协议的 MD EINT 编号，不是 Linux IRQ0。
转换规则是 debounce 整数除以 1000；合法 IRQ type 1/2/4/8 下，polarity 为
`!!(type & 5)`，sensitivity 为 `!!(type & 3)`。不要返回原始 IRQ flags。

F/F66 中 `/md1_sim2_hot_plug_eint` 只有 phandle，没有七种配置，不能把缺省
零值当成功。A 初始化会找到它，但每项记负查询错误，最终
`get_eint_attr_DTSVal():367–396` 返回 QUERY_STRING。SIM3/4 节点不存在；这不是
从空的 V 通用模板推断，而是核对保存的完整树得到的结果。规范 namespace
可使用 SIM1 的一条成功事实；SIM2/3/4 明确失败，不能报“插槽已实现”。

A `port_rpc.h:220–224` 和 V `port_rpc.h:242–246` 均为 C 自增 enum：

```text
NULL_POINTER = -13
QUERY_TYPE   = -12
QUERY_STRING = -11
```

不得误读为递减的 -13/-14/-15。越界 type 应返回 -12；名字不存在、或该名字
对应的属性为负值，应返回 -11。本文审计时 provider 的 -14/-15 常量与本机
不一致，已通知集成线程修正；部署前应以源码及回归为准。

旧 DT 小写节点名能被 A 找到，是因为 `A/include/linux/of.h:968` 使用
`strcasecmp`。V `port_rpc.c:364–402` 专门添加小写名称 fallback；不能在主线
只搜索大写节点名，然后把找不到误当 SIM1 不存在。

## DTSI 查询：完整属性集合包含 compatible 的历史行为

`A/port_rpc.c:405–431`、V `:451–477` 按 compatible
`mediatek,md_attr_node` 找节点，在 req=1 时执行
`of_property_read_u32(node, input->strName, ...)`。它不限制属性名，也不要求
属性长度恰好 4 byte。F/F66 `/md_attr_node` 只有以下三个属性：

|准确请求名|首个大端 u32 的主机整数值|意义|
|---|---:|---|
|`mediatek,md_product_name_model_id`|20615 (`0x5087`)|公开板级产品型号，非设备唯一标识|
|`mediatek,md_drdi_rf_set_idx`|0|保存启动配置的 RF set index|
|`compatible`|`0x6d656469`|字符串 `mediatek,...` 的前四字节 `medi`|

前两项在 F/F66 一致；未在本轮限定的 A/V 板级 DTS 里找到设置来源，可能为
启动链注入，**本文不推定注入者**。其可追溯来源是固定 SHA256 的保存 FDT，
不能仅凭文件名或产品目录就对所有设备/后续启动硬编码 RF set index。

若 provider 声称复现该节点的完整 u32 查询 namespace，只列两项后把
`compatible` 当缺失不准确。可把三项都纳入审计快照；若只支持两项业务属性，
必须明确它是协议 allowlist，不能标成 vendor 全等 namespace。
F/F66 此节点没有 phandle、status 或其他属性。缺失属性或不支持 req 时，
A `:1177–1181` 预填的 `0x0f0f0f0f` 保持不变，不是返回整数 15。

## 最小板级 provider 输入契约

建议初版仅接受显式、不可变、调用者持有至 session 停止的本机快照；在
reserve 前设置，之后不允许替换。不得由 modem 请求反向触发任意 DT 属性读取。

|字段|建议初值|前置证明|
|---|---|---|
|`gpio` / `gpio_count`|上表 11 个原名 + 4 个规范别名，共 15 项|核对完整 mapping 节点、所有引用的 gpio provider 和 MD-view cell；不查询电平|
|`gpio_present`|条件满足后 true|包括别名目标的明确缺失；完整规范名字策略已说明|
|`adc` / `adc_count` / `adc_present`|NULL / 0 / false|当前 finite-name ABI 无法忠实表达实际的 name-independent channel2|
|`eint` / `eint_count`|SIM1 向量一项|核对 SIM2 空节点和 SIM3/4 absence；先修正 -12/-11 错误码|
|`eint_present`|条件满足后 true|只表示完整查询结果已知，不表示实现热插拔 IRQ/通知|
|`dtsi` / `dtsi_count`|三项（含 compatible）|固定来源节点的完整属性集合；RF index 仅限该保存配置|
|`dtsi_present`|条件满足后 true|调用者明确选择保存快照且核对本次启动/板级适用性|

“条件满足后”不是本轮已经打开。历史 F/F66 的匹配证明这些候选事实来源
一致，不能证明当前主线 pinctrl 已 ready、GPIO 可采样、当前硬件修订相同或
当前启动链的 RF set 未变化。provider_available 也不能替代完整性审计。

## 本轮验证

使用主机 libfdt 对 F/F66 定点读取 `/md_attr_node`、`/gpio_usage_mapping`、
`/md_auxadc`、两处 SIM 节点及 GPIO/IIO 的 phandle provider；核对数值、
属性数量、cell 宽度和空节点。两份 FDT 的这些板级事实逐项一致。
检查旧 defconfig 排除了 legacy ADC 分支；检查 A/V 的 enum 与 EINT 转换源码。
未进行硬件测试；未修改 provider、endpoint、现有 runner 或启动配置。

## 后续实现：显式 op6893 常量 provider

同日新增 `drivers/misc/mediatek/ccci/ccci-rpc-op6893.{c,h}`，导出
`ccci_rpc_op6893_provider()`。返回值及全部表项为静态 const；GPIO 共 15 项，
SIM EINT 一项，DTSI 三项，ADC 仍为 NULL/0/false。源码保留 F 的 SHA256 和
本文引用，不从实时 GPIO 编号、DT 随意属性或 ADC 采样反推事实。

这个无参数 getter **不执行 machine 匹配**。平台调用者必须先限制到
`realme,op6893`，显式选择本机已审计快照，并遵守 reserve 前注入及全生命周期
不可变的契约；不能因任意 mt6893 设备能调用同一函数就复用这些常量。平台
matching、Makefile 接线及本次启动适用性检查由集成层负责。这是用户授权的
本机保存配置实现，不证明其他 PCB/RF set、其他机型或所有后续启动完全相同。

集成线程已将通用 EINT provider 错误码修正为 -12/-11。新增独立测试：

```sh
python3 Documentation/arch/arm64/op6893-bringup/tools/test_modem_rpc_board.py
```

测试编译实际板级表、通用 provider 和 RPC codec，通过 ASan/UBSan 检查完整
15 名的有/无末尾 NUL 请求、精确 MD-view 数值、缺失 GPIO 与名字前缀失败、
SIM1 全七种转换结果、SIM2/3/4 的全部七种失败及越界 type 的枚举值；同时
核对三项 DTSI 的真实 TX endian/identity、未知属性和 req 的 sentinel 不变、
ADC 及未实现硬件服务保持 `-EOPNOTSUPP` 且无输出修改。未运行设备测试。
新增 C/头文件 strict checkpatch 为 0 errors / 0 warnings / 0 checks。
