# attempt118：基于 OCV 表的电量估算

内核 `325d59924418`。

## 来源

厂商 DT `20615_common.dtsi` 引用 `mt6893_battery_table_ext_cupid.dtsi`，其中有
5 个温度（50/25/10/0/-10 °C）的 gauge profile。每行数据依次是：已放出电量
（0.1 mAh，满量程 43812，即约 4381 mAh）、OCV（0.1 mV）、内阻。取 25 °C 的
profile_t1，每 5 % 重采样一次，写入 `simple-battery` 的 `ocv-capacity-table-0`。
各温度曲线在 10–95 % 区间内相差不超过约 40 mV（15 % 处最大），所以只放了一张表。

## 驱动

`generic-adc-battery`：DT 有 `monitored-battery` 时新增 CAPACITY 属性，用
`power_supply_batinfo_ocv2cap()` 查表。电压没有做内阻补偿（缺电流通道）。

## 对照

| 系统 | 状态 | 电压 | 百分比 |
|---|---|---|---|
| Android（刷机前） | 充电，电流约 0 | 4.042 V | 49 % |
| 主线 | 充电（500 mA） | 3.985 V | 60 % |

Android 的数值由库仑计累计得出，主线的估算在充电时偏高。要得到真实对比，需要
在不接 USB、静置后的条件下再测一次。

## 其他

- MT6360 `0x19` = 0x3c，VINOVP = 6.5 V，与 attempt117 的推断一致。注意在主线上
  i2c5 的编号是 `/dev/i2c-1`。
- `ssh-wifi.sh` 经 wlan0（10.65.84.170）登录成功。
