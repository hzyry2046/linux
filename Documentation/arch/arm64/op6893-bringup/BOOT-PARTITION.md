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

## 主线写盘试点：cache

2026-11-20 在同一镜像上，按标签找到同一 UFS LUN 的 `cache`：
第 55 项，起始扇区 22659072，容量 432 MiB。ext4 占满分区，
运行中的 squashfs 位于这套 ext4 上，loop 保持只读。试点使用专用
临时文件，不覆盖文件系统任何已分配给现有文件的块。

先完整备份 `cache` 到开发主机的私有目录
`mt6893-direct/backup/cache-write-pilot-20261120/`，在副本上运行
`e2fsck -fn`。所有同盘分区先各自设为只读，然后才解除父盘及
`cache` 的只读标志；父盘解锁后再次检查各分区仍只读，`boot`
在写入窗口中保持只读。短暂将 `/run/cache` 重挂为可写，沿用
`noload`，向专用临时目录写入 32 MiB 随机数据。直接 I/O 写入、
`fsync`、文件系统同步和直接 I/O 读回均成功，读回逐字节一致。

删除临时目录后同步并重挂只读，恢复父盘和 `cache` 的块设备只读
标志。再次完整读回，在副本上运行 `e2fsck -fn` 无报错；分别提取
前后副本的目录树，现有文件内容比较一致。ext4 元数据允许变化，
没有把清理后的分区宣称为逐字节还原。`boot` 的完整 SHA-256
仍与上节一致，内核未报告存储错误，taint 为 0。

这次验证的是主线经 ext4 向 UFS 写入、刷盘及绕过页缓存读回；
尚未验证裸分区写入或断电持久性。首次直接更新 `boot` 应先在主机
保留当前完整镜像和 fastboot 恢复路径，在设备内存中校验待写镜像的
大小与哈希；按标签和几何确认目标，仅解除该分区的只读保护，写完
刷盘后直接读回整个分区并核对哈希，恢复只读后再安排重启。
