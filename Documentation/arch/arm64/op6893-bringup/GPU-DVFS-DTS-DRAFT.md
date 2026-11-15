# MT6893 GPU DVFS DTS Draft

为 MT6893 添加 GPU DVFS 支持的草稿。OPP 数据见 GPU-OPP-TABLES.md。

## 已确认的现状（mt6893-op6893-boot.dts）

GPU 节点已存在于板级 DTS（`gpu: gpu@13000000`，panfrost 已跑通 kmscube），
DVFS 应在该节点上增量添加，不要在 mt6893.dtsi 里另建节点（label 冲突）。

- 中断：GIC_SPI 364/363/362（job/mmu/gpu），已实测。
- power-domains：MFG1..MFG6（MFG0 是 MFG1 的父域，不直接挂给 GPU）。
- 电源：MFG0 domain-supply = `mt6315_7_vbuck1`（GPU 核心电压轨），
  MFG1 domain-supply = `mt6359_vsram_others`（SRAM）。
  **不是** mt6359 vgpu11。
- 时钟：`mfg_ck` 是 fixed-clock 350 MHz（沿用 LK 设定的 MFGPLL /8）。

## 前置条件

1. **MFGPLL 时钟驱动**：fixed-clock 无法调频，需要 apmixedsys 里 MFGPLL
   可设置频率，并让 mfg_sel mux 可控。没有它 OPP 表无意义。
2. **电压轨**：确认 mt6315_7_vbuck1 的 regulator 范围/步进能覆盖
   0.55–0.80 V；它目前作为 domain-supply 被 SPM 驱动使用，
   改成 `mali-supply` 时要处理两者共享 regulator 的问题。
3. **vsram**：下游 vsram_gpu 随 vgpu 联动；panfrost 不支持 `sram-supply`。
   短期把 vsram_others 固定在足够高的电压（需确认下游最高档要求）。
4. **Segment**：下游按 efuse `0x11C107B0[2:0]` 选 segment 表，
   先用 segment 1，之后再考虑 `opp-supported-hw`。

## DTS 框架（待前置条件满足后加到板级 gpu 节点）

```dts
&gpu {
	clocks = <&apmixedsys CLK_APMIXED_MFGPLL>;  /* 待时钟驱动 */
	mali-supply = <&mt6315_7_vbuck1>;
	operating-points-v2 = <&gpu_opp_table>;
	#cooling-cells = <2>;
};
```

OPP 表候选档位（segment 1）：350/390/451/512/593/675/755/836/886 MHz，
对应 0.55/0.5625/0.58125/0.60/0.625/0.65/0.70/0.75/0.80 V。

## 电压相关资料（4.19 本地源码）

- 4.19 DTS gpufreq 节点：`_vgpu-supply = <&mt6315_7_vbuck1>`，
  `_vsram_gpu-supply = <&mt_pmic_vsram_others_ldo_reg>`，与板级 MFG0/MFG1
  domain-supply 一致。
- mainline mt6315 buck：线性 0–0xbf，6.25 mV/步（0–1.19375 V），满足需求。
- vsram 规则：vgpu <= 0.75 V 时 vsram 固定 0.75 V；更高时 vsram = vgpu。
  约束 -100 mV <= vsram - vgpu <= 300 mV。
- Segment：efuse 0x11C107B0 `& 0x3`（注释写 [2:0]，代码掩码 0x3）。
  == 2 用 segment 2（MT6893_SEGMENT），否则 segment 1（MT6891_SEGMENT）。
  segment 2 低频电压更高（350 MHz 为 0.60 V，segment 1 为 0.55 V；
  675 MHz 及以上两表相同）。**本机属于哪个 segment 尚未确认**，确认前
  应按 segment 2（更保守）取电压。

## 下一步

1. 查 4.19 的 MFGPLL 设置流程（mtk_gpufreq_plat.c 中 PLL/posdiv 切换）
2. 查 mt6315 vbuck1 的 mainline regulator 定义
3. 实现 MFGPLL 时钟后再加 OPP 表，测试 devfreq 调频调压
