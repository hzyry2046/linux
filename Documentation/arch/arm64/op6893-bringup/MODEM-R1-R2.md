<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 基带 R1/R2：供电与普通 CCIF 时钟框架

2026-11-14，基于 `6db0f4606d6e` 的本地工作树，AI 辅助实现与验证。
以本机 A 的硬件映射和已可用 V 的供电/CCIF 分层为依据，接续
[资源契约](MODEM-RESOURCES.md)。本轮未连接或操作设备，没有刷写、SMC 或
基带运行验证。没有打包新 boot 镜像；M1 仍只是部分框架完成。

后续实机进度：显式变体 `7576d31c76a4` 已完成两次启动的资源引用验收；
shutdown 对照、电压语义与实测限制见 [供电生命周期](MODEM-RAILS.md)。
以下保留首版离线实现记录。

## 已实现

- 实际 boot DTS 新增 MT6315 SID3 的 `vbuck1/3/4`，分别命名为
  `vmodem/vnr/vsram_md`。整个 `pmic@3` 为 **disabled**，不枚举 SPMI 设备。
- 新增 MT6359P `buck_vpu` 本地 phandle，命名为 `vdigrf`，节点 **disabled**。
  它描述 ACK 的 VRFDIG 接线，没有 min/max、boot-on、always-on 或模式约束。
  MT6359 regulator driver 本来就遍历并注册整张 rail 描述表；disabled 子节点
  仅使其不匹配这个 DT 初始化描述，**不代表关闭物理 rail，也不阻止原有
  `buck_vpu` 描述符注册**。后续显式启用该子节点才会建立此 phandle 的关联。
- 新增 **disabled** 的 `modem-resources` 节点，四个 supply 均引用本地 rail。
  只引用四个普通 CCIF gate，不附着 power-domain、reset、MMIO 或 IRQ。
  此节点与 M0 的 LK metadata inspector 分开，没有改变 M0 的解析职责。
- `CONFIG_COMMON_CLK_MT6893_CCIF` 默认 n，启用后在**现有** infracfg
  provider 中注册四个普通 gate：ID 28/29/33/35，bank1 bits 12/13/23/26，
  SET/CLR/STA 为 `0x88/0x8c/0x94`。使用 `CLK_IGNORE_UNUSED`，不因未被
  consumer 使用就关闭 LK 留下的状态。注册失败回收新 gate 和原 PMIF gate。
- AXI parent 仍是现有的频率观察节点，不控制 mux/PLL；新 gate 也不代表
  MD 电源域已开。CCIF2/4/5 的 vendor dummy gate 和 DPMAIF 保持未支持，
  没有用固定 clock 或成功桩冒充可用资源。
- `CONFIG_OP6893_CCCI_RESOURCES` 默认 n，可构建为模块。probe 要求四个
  显式 supply 属性，通过 `devm_regulator_get_optional()` 获取必需引用，
  防止缺失供电被 dummy regulator 替代；随后批量获取四个 clock 引用。
  缺失或 defer 原样失败，只有全部获取成功才记录引用齐全。没有 enable、
  调压、rate/parent 修改、runtime PM、reset、IRQ、MMIO 或 SMC 调用。
- Kbuild 的 `mediatek/ccci/` 遍历不再依附于 Wi-Fi 或 LK inspector 选项；
  各 leaf module 由各自配置选择，可单独编译资源检查模块。

这个模块检查的是 framework 引用，不检查硬件电源状态、实际电压、CCIF
响应、SCP READY 或 MD READY。regulator lookup 可能触发 supply resolution
及待完成的 constraints，provider 还可能存在初始化/退出操作，因此没有
将“未调用 enable”写成对整个 regulator framework 的零写入保证。

## Provider 生命周期审查

MT6315 probe 建立 regmap 并注册四路 buck；仅命名的多电压 rail 在当前
regulator core 下不设置 apply_uV、initial_mode、boot-on 或 always-on。
不过驱动的 `mt6315_regulator_shutdown()` 会写 TMA key 和 `TOP2_ELR7`，
开启 PMIC 关机序列。这是首版保持 **整个 SID3 provider disabled** 的原因。
即使检查模块只获取引用，启用 SID3 后的系统重启仍可能走这个 shutdown。
不能把现有 SID7 已能工作的事实直接当作 SID3 shutdown 已验证。

因此本轮没有默认启用任何新 provider/consumer，也没有实现启动电压恢复。
SID3 DA 实际电压与 RG 指令值的差别、VRFDIG 恢复、VMODEM/VSRAM_MD 差压
和时序，以及 MD 运行时 DVFS 所有权继续按资源契约逐项闭合。

## 验证记录

[主机测试](tools/test_modem_resources.py)抽取实际 C probe、实际 clock
descriptor 和通用 set/clear ops 编译运行，没有另写一套行为模型替代实现：

```sh
python3 Documentation/arch/arm64/op6893-bringup/tools/test_modem_resources.py \
  --dtb /data/src/mainline/mt6893-direct/out/arch/arm64/kernel/op6893-embed.dtb \
  --dtb /data/src/mainline/mt6893-direct/evidence/merged-preview.dtb
```

- probe：分配失败、四种缺失 supply 属性、每路四种获取失败（含 defer）、
  clock 获取失败及成功路径通过；失败不打印引用齐全。
- gate：四个 vendor ID、寄存器 offsets、bitmask 和 IGNORE_UNUSED 校验通过；
  五种初始寄存器模式下实际 enable/disable ops 只改变目标位，UBSan 通过。
- board 和实际合并后 FDT：四个 rail 名称/本地 phandle、SID3 地址、clock
  provider/IDs、所有新增节点的 disabled 状态、无额外电压/模式约束通过。
- 原 FDT 合并、M0 合成 ABI/parser/20,000 组 ASan/UBSan 输入、AXI observer
  和 thermal gate 回归通过。
- 新 binding 和修改的 clock binding 通过 `dt-doc-validate`。包含通用
  `regulator.yaml` 依赖的 schema 集合用于限定验证，新增 resource、clock 和
  MT6315 binding 在 board/merged DTB 上无诊断；不把只加载单个 regulator
  schema 时的未解析 `$ref` 结果作为有效验证。
- 实际启用 `COMMON_CLK_MT6893_CCIF=y`、`OP6893_CCCI_RESOURCES=m` 后，
  ARM64 `Image.gz`、`vmlinux`、`ccci-resources.ko` 和 modpost 通过，无编译警告。
  验证时 LK inspector 为 n，确认资源模块可独立选择。随后恢复默认关闭配置，
  再编译检查关闭路径。没有修改默认 defconfig。
- code、binding/header、DTS 分别进行 strict checkpatch，均为 0 errors、
  0 warnings、0 checks；通用新增文件 MAINTAINERS 提示单独忽略。

外部构建器 `mt6893-direct/build.py` 已增加上述主机测试并归档日志。
构建日志和显式启用配置/对象保存于 `mt6893-direct/modem-r1-r2-*`，
测试与构建结果见 [验证清单](evidence/modem-r1-r2-validation.json)。
这些主机检查不模拟完整 CCF、regulator core、PMIC shutdown、ATF 或真实基带。

## 下一批改动

1. 按 A 和已可用 V 实现本 SoC 的 MD genpd 序列，处理保护 ACK、电源 ACK、
   隔离和 reset 的先后；先建立有界等待与失败状态，不添加自动上电入口。
2. 继续移植 SCP RV 的资源/保留内存和 mailbox 基础，明确 CCIF2 唯一 owner。
   在真实 SCP/CCISM 完成前，不放行 MD 首次启动。
3. 实机资源检查前先解决 SID3 shutdown 策略和启用范围，再准备一次只获取
   引用的镜像；不能直接用这个框架尝试基带启动。用户态/固件的新资料由用户
   后续提供，本轮无需等待，也未重复二进制逆向。


2026-11-16顺序更正：早期“真实SCP/CCISM完成前不放行MD”的表述将两阶段
混在了一起。前置是SCP hardware READY、桥资源和服务就绪；CCISM消息交换
依赖MD HS2之后的system端口，必须后置，见[CCISM契约](MODEM-CCISM.md)。
