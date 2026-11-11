# attempt117：启用 MT6360 充电驱动

内核 `194b84a67025`。

## probe 前后寄存器比对

Android 下无 `/dev/i2c-*`，debugfs 未挂载，无法导出；以 LK 交接后的值为准
（主线此前不写这些寄存器）。

| 寄存器 | LK 值 | probe 写入 | 结果 |
|---|---|---|---|
| CTRL19 VINOVP | 6.5 V | 6.5 V（DT 明确写入） | 不变 |
| CTRL2 IINLMTSEL | AICR | AICR | 不变 |
| CTRL3 ILIM_EN | 0 | 0 | 不变 |
| CTRL10 OTG OC | 0xB | 0xF | 仅 OTG 模式生效 |
| DEVICE_TYPE USBCHGEN | 1 | 关后按 VBUS 重开 | 触发一次 BC1.2 |

不改：充电使能（开）、ICHG 500 mA、AICR 500 mA、CV 4.38 V、看门狗（关）。

## 结果

- `mt6360-chg`：ONLINE=1，STATUS=Charging，CHARGE_TYPE=Fast，USB_TYPE=SDP。
- `fuel-gauge` STATUS 由 Discharging 变为 Charging。
- BC1.2 检测期间 USB gadget 一直处于 configured，USB SSH 未断。

## Wi-Fi SSH 备用通道

新增 `mt6893-direct/ssh-wifi.sh`（默认地址取最近一次 DHCP，可用
`OP6893_WIFI_IP` 覆盖），用于 USB 断开时访问。
