# op6893 主线 Wi-Fi / Bluetooth 状态（attempt98–106）

更新：2026-11-10。设备运行内核 `24c0e33d5597`（`7.3.0-op6893-d1-24c0e33d5597+`），
外置 Debian 镜像 `debian-1ed1b45c80c2`。

本文汇总在 attempt97 之前的寄存器级 CONN 实验之后，主线如何改用厂商
连接栈打通 Wi-Fi 和 Bluetooth。路线按用户决定：先用厂商/qqcandy 栈的简单
路径打通，以后再逐步迁移到更标准的实现。下面只记录这台设备在主线上的
实测结果；ACK 或 qqcandy 上可用，不等于这里可用。

## 当前结论

| 功能 | 状态 | 已验证内容 | 限制 |
|---|---|---|---|
| CONN 上电（conninfra） | 部分，实测 | 厂商 conninfra 经 op6893 MTCMOS 序列上电；BT/Wi-Fi 两个客户端注册；开机时 BT+Wi-Fi 预校准成功 | 供电仍有一部分沿用 LK 留下的状态；关断/省电路径没有完整验证 |
| Wi-Fi（gen4m） | 实测可用 | 开机自动关联开放网络、DHCP、经 Wi-Fi 的 SSH、NTP 校时、DNS、HTTPS（`apt update`）| 只测了无密码网络；`wpa_supplicant`、省电、漫游都没测 |
| Wi-Fi 出厂 MAC | 实测 | 从 proinfo 0x6e 经 nvmem 读取 | — |
| Bluetooth HCI | 实测可用 | 开机 `hci0` 自动起来；HCI 初始化走主线标准流程；版本 12，厂商 70 | 有一处变通：`0x0c77/0x0c78` 在本地直接完成（固件不认识这两个命令） |
| Bluetooth 出厂地址 | 实测 | 从 proinfo 0x68 经 nvmem 读取，由内核 `set_bdaddr`（`0xfc1a`）在初始化前写入控制器；hciconfig、btmgmt 和 RFCOMM 源地址都是出厂地址（attempt108） | 每次上电都会重新写入（`NON_PERSISTENT_SETUP`） |
| BLE 扫描（BlueZ） | 实测可用 | `bluetoothctl scan on` 15 秒发现 32 个；`btmgmt find -l` 发现 90–126 个 | — |
| BR/EDR inquiry | 实测 | `btmgmt find` 能找到经典蓝牙设备 | — |
| 配对 / RFCOMM / OBEX | 实测 | 与 V35 ThinQ 完成 SSP 配对；l2ping 0% 丢包；RFCOMM 连接成功，OBEX OPP 推送约 21 KiB 文件成功（attempt107、108） | — |
| PAN（BNEP） | 实测 | 连接 V35 的蓝牙网络共享：bnep0、DHCP 获得地址、经 bnep0 ping 外网、HTTP 下载 140 KB 约 60 KB/s（attempt109） | 只测了 PANU 作为客户端；没有做长时间吞吐测试 |
| 音频（A2DP/HFP）、LE 连接 | 未测 | — | rootfs 里没有 PipeWire/PulseAudio |

完整地址和 NVRAM 内容属于本机私有数据，没有写进本文或证据文件。

## 源码

- `799a2531f`、`83f3be7f9`、`91db780a2`：导入厂商 MT6893 连接栈（connadp、
  connfem、conninfra、btif、BT mt66xx、gen4m Wi-Fi），并加上 Linux 7.3 兼容
  shim 和 op6893 MTCMOS 接线。
- `8117d622c`：BT 驱动不再自己清除 `HCI_SETUP`（见下文“BLE 扫描”）。
- `54dd59781`：新增 `partition-nvmem` 驱动，并在 DT 里描述 proinfo 中的 BT/Wi-Fi
  地址。
- `cb944eec1`：defconfig 打开 RFCOMM 和 BNEP。
- `f4f010b36`：BT 出厂地址改为通过内核 `set_bdaddr` 写入控制器。

## 关键问题与根因

### Bluetooth RX 收不到任何数据（attempt98–99）

主线 HCI 能发命令，但 inquiry 收不到响应。对比 Android 日志（`connport/BT-RX-DIFF.md`）
发现：Android 开机时由 `wlan_assistant` 触发 BT/Wi-Fi 共享的 A-die 预校准，
而主线当时的 Wi-Fi 只有 weak stub，预校准从来没有执行。修复方法是把 gen4m
Wi-Fi 一起导入，让预校准真正跑起来。

### gen4m Wi-Fi 打通过程（attempt100）

逐个镜像定位的结果：

1. reserved-memory 节点写错，probe 返回 `-EINVAL`；改正后又缺
   `compatible = "shared-dma-pool"`，导致 BT/Wi-Fi 的 conninfra 回调没有注册。
2. 补上之后，开机预校准成功，BT inquiry 第一次找到了已知设备。
3. 正常激活 Wi-Fi 时 `wlanDownloadFW` 返回 `0xc0000001`。最终定位到
   `wlanGetEpaElnaFromNvram` 因为没有 NVRAM 而返回 NULL，`wlanSendPhyAction`
   在申请 TX 资源之前就退出了。改为在 EPA/ELNA 数据缺失时用零长度的占位 tag
   继续，并去掉了开机时 123 秒的 NVRAM 重试。之后固件下载完成，`wlan0` 注册成功。
4. 注入本机 Android 的 `WIFI` NVRAM 和 `wifi.cfg` 之后，射频参数和 MAC 与
   Android 一致，Wi-Fi 能够关联。

### 时间与 DNS（attempt101）

设备没有 RTC，时间从 1970 开始，HTTPS 证书校验失败。rootfs 里的
`/etc/resolv.conf` 是 Tailscale 生成的，指向一个在这里不可达的地址。
修复：

- 时间早于 2025 时，先设成构建时间作为下限；
- DHCP 成功后改写 resolv.conf；
- NTP 以 `/run/time-synced` 是否存在为准反复重试，而不是看年份。

clean boot 后 NTP 校时成功，`apt update` 正常。

### BLE 扫描没有结果（attempt102–104）

现象：裸 HCI 发扩展扫描命令（`0x2041`/`0x2042`）能收到 1400–1600 条报告，
但 BlueZ 发现 0 个设备。btmon 显示 BlueZ 用的是 legacy 扫描
（`0x200b`/`0x200c`），命令全部返回 Success，却收不到任何报告。

根因：`btmtk_register_hci_device()` 在 `hci_register_dev()` 之后立即清除了
`HCI_SETUP`，并且手动发送 Index Added。主线中 Read Local Version 和
Read Local Supported Commands 的完成回调只有在 `HCI_SETUP` 置位时才保存结果，
所以 `hci_ver` 和 `hdev->commands[]` 一直是 0。连锁结果是：

- 内核跳过了 `0x1002`；
- `use_ext_scan()` 为假，于是走 legacy 扫描；
- LE 事件掩码里缺了 LE Advertising Report 位，legacy 扫描也收不到报告。

修复（`8117d622c`）：不再清除 `HCI_SETUP`，交给 `hci_power_on()` 处理；
仍然清除 `HCI_AUTO_OFF`，防止控制器在第一次上电后又被自动关闭。

还做过一次重放 Android 的 APCF 厂商命令（`0xfd53`/`0xfd57`）的实验。attempt104
证明扫描并不依赖这些命令，所以没有保留（它还会让开机多等约 16 秒）。

### 出厂地址（attempt105）

BT 和 Wi-Fi 驱动本来就会去找 nvmem cell，但 `CONFIG_NVMEM` 是关闭的，DT 里
也没有 provider，两边都等了 120 秒才放弃，BT 一直用种子地址。`partition-nvmem`
从 qqcandy 移植过来，把原来的 `/dev/disk/by-partlabel/` 路径查找改成在内核中
按 GPT 名称匹配块设备，因为这里没有 udev。分区只读、非独占地打开，并且在
第一次读取时才打开。

### rootfs 中的 BlueZ（attempt106）

Debian 镜像通过 qemu chroot 用 apt 装了 `bluez` 5.82 和 `dbus-daemon`。PID1
是 BusyBox 脚本，不是 systemd，所以由 `op6893-ssh-start` 在后台子 shell 里
启动 dbus 和 bluetoothd，不会阻塞 SSH。镜像是在 Android 下写入 `/cache` 的
（主线下 UFS 仍然只读），旧镜像保留为 `debian-9825862f46b0.squashfs`。

## 证据

- in-tree：[98](evidence/attempt-98.md)、[99](evidence/attempt-99.md)、
  [100–106 摘要](evidence/attempt-100-106.md)
- 原始日志（dmesg、btmon、HCI snoop、二分结果）在外部工作区
  `mt6893-direct/evidence/attempt-100` 到 `attempt-106`，没有复制进源码树。
