# op6893 电池与充电待办

更新：2026-11-11。现状见 [PERIPHERAL-STATUS](PERIPHERAL-STATUS.md) 中的
MT6360 行，以及证据 [116](evidence/attempt-116.md)、[117](evidence/attempt-117.md)、
[118](evidence/attempt-118.md)。

## 现状

- MT6360 ADC 可读；`mt6360-chg` 可以报告在线状态、充电状态和 USB 类型（SDP）。
  充电参数沿用 LK 的设置（500 mA / 4.38 V）。
- `fuel-gauge`（adc-battery）报告电压和充电状态，CAPACITY 按 25 °C OCV 表估算。

## 已知问题：电压估算在负载下严重偏低

attempt118 中亮屏、Wi-Fi 在线、拔掉 USB 后的记录（`mt6893-direct/evidence/attempt-118/rest.log`）：

| 时间 | 电压 | 估算 |
|---|---|---|
| 10:28 | 3.870 V | 47 % |
| 10:38 | 3.808 V | 35 % |
| 10:43 | 3.796 V | 31 % |

15 分钟下降 17 个百分点，相当于约 3 A 的平均放电电流，与实际负载不符。原因是
40–60 % 区间的 OCV 曲线很平，每 1 % 只对应几 mV，负载压降被放大成了电量变化。
随后进入 Android，读到 49 %、3.676 V、+1.8 A（充电中）。这个 49 % 与刷机前相同，
很可能是 Android 沿用了关机前保存的电量，所以这一组数据不能用来校准。

## 待办（按优先级）

1. **MT6359 库仑计**：参照厂商 `mtk_gauge` / `mtk_battery`（gm30），在主线上实现
   一个最小化的 gauge 驱动，读取 coulomb 计数和电池电流。这是得到可信电量的唯一
   途径，工作量大。
2. **IR 补偿**：有了电流之后，用 profile 中的内阻列修正负载压降。也可以先只在
   低负载时更新估算值。
3. **干净的对照测量**：在 Android 下静置、关屏 30 分钟后读数，然后立即进入主线读数。
4. **充电参数**：目前沿用 LK 的 500 mA。应按 SDP/DCP 类型设定 ICHG/AICR，
   CV 设为 4.4 V（厂商 4400 mV）；要有温度保护后再放开。
5. **VOOC / 电荷泵**：i2c7 上的 BQ25970 和 RT5125 不处理，保持 5 V 普通充电。
6. **多温度 OCV 表**：目前只放了 25 °C 的表；以后有了温度通道可以把其余 4 张表也加上。
7. **MT6360 其余功能**：LED、TCPC 等。

## 参考：厂商算法与 6.6 移植经验（用户提供的分析，2026-11-11）

来源：`~/src/reverse-analysis/op6893-battery-userspace-analysis.md`、
`op6893-6.6-ack-battery-analysis.md`（对 `libfgauge_gm30.so` 做静态逆向，结论属推断）。

- **算法在用户态闭源库里**：`fuelgauged` 只是 dlopen `libfgauge_gm30.so`（32 位 bionic），
  通过 `NETLINK_FGD=26` 与内核通信；不能搬到主线，只能复刻算法结构。
- **结构**：c_soc（库仑计）+ v_soc（OCV 表，`OCV = VBAT ± I·R(DOD,T)`）按差值门限融合，
  再做 UI 平滑（pseudo100、满电保持、低电保持、限速）。门限常数没有恢复。
- **MT6359P 库仑计寄存器**（6.6 `mt6359p-gauge.c`）：FGADC_CON1 `0xd0a`（SW_READ_PRE
  bit0 锁存、SW_CLEAR bit3），CAR `0xd16` 起，电流 `0xd8a`；`UNIT_CHARGE=85`、
  `UNIT_FGCURRENT=610352`，R_FG 5 mΩ（内部值 50），CAR_TUNE 0.95。这是第 1 项待办的起点。
- **6.6 项目实测：电池已老化**，满电到空约 2.85 Ah，profile 是 4.26–4.38 Ah（约 67%，
  363 次循环）。厂商的老化学习没有真正生效。因此库仑计 SOC 必须做运行时容量学习，
  不能照搬 profile 的 Qmax；纯 OCV 估算不受这一影响。
- pseudo100：20615 的 DT 覆盖为 97/95/95/93/93（分析文档给出的 98/96/96/93/93 是通用值）。
- 6.6 项目踩过的坑可以直接借鉴：只在电压达到 4282 mV 以上时才把充电结束当作满电
  （暖区、冷区是限压停充）；NTC 用 `/charger` auxadc3 的 166 点表（上拉 100 kΩ）；
  `vbatt_power_off` 3300 mV 规则。
