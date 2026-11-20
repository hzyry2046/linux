# op6893 本机 boot 分区定位

2026-11-20 在同一台设备上交叉验证：

| 环境 | 分区路径 | 分区号 |
| --- | --- | --- |
| Android | `/dev/block/by-name/boot` → `/dev/block/sdc48` | 48 |
| 主线 `57e6fb81cf4b` | `/dev/disk/by-partlabel/boot` → `/dev/sdc48` | 48 |

两边 sysfs 均报告 `PARTNAME=boot`、`PARTN=48`、`start=2473984`、
`size=65536`。sysfs 的 start/size 以 512 字节为单位，分区容量为
32 MiB；fastboot 的 `partition-size:boot` 返回十六进制 `2000000`。
主线父盘是 `11270000.ufs` 上的 LUN 2，逻辑块大小为 4096 字节。

主线优先使用 `/dev/disk/by-partlabel/boot`，不要依赖 `sdc` 的枚举顺序。
没有标签链接时可检查 `/sys/class/block/*/uevent`，要求唯一一项
精确匹配 `PARTNAME=boot`，再核对 `partition`、`start` 和 `size`。

刷入后在主线只读计算整个分区的 SHA-256，与 32 MiB 的
`57e6fb81cf4b/boot.img` 完全一致：

```text
f66f3c5a8fa97ea3b2cd181867d6bab671010c682b6eab4c6d894667d829b8be
```

主线仍报告主备 GPT 分区条目数组 CRC 不同，符合本机现有布局。
本次只通过 fastboot 刷写 `boot`，没有修正 GPT 或更新 Android 备份。
