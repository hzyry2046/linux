# attempt116：MT6360 ADC 与电池电压 power_supply

内核 `fcd49a9c1418`。

## 硬件（4.19 DT，20615）

| 部件 | 芯片 | 主线 |
|---|---|---|
| 主充电 | MT6360 charger（i2c5） | `mt6360_charger`，未启用 |
| 快充电荷泵 | BQ25970（i2c7 @0x65） | 未处理 |
| VOOC MCU | RT5125（i2c7 @0x0e） | 无驱动 |
| 电量计 | 无独立芯片（`internal_gauge_with_asic`，MT6359 电量计） | 无驱动 |

## 结果

MT6360 ADC（插 USB，空闲）：VBUS 4.83 V，IBUS 432 mA，VSYS/VBAT 3.91 V，
CHG_VDDP 4.80 V，结温 33.6 °C。IBAT 在 0–30 mA 间跳动；7 核满载时 VBAT 降到约
3.85 V、IBAT 为 0，说明 IBAT 只测充电方向，放电电流读不到。

`adc-battery` 用 MT6359 BATADC：`VOLTAGE_NOW` 约 3.92 V，与 MT6360 VBAT 一致。
STATUS 恒为 Discharging（没有注册充电器 supply）。

## 下一步

在 Android 下导出 MT6360 充电寄存器，与主线 `mt6360_charger` probe 写入值比对，
再决定是否启用充电驱动。
