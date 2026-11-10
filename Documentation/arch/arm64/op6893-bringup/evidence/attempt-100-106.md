# attempt100–106 摘要

原始日志在外部工作区 `mt6893-direct/evidence/attempt-N/`，没有复制进源码树。
结论汇总见 [CONNECTIVITY-STATUS](../CONNECTIVITY-STATUS.md)。

## attempt100：gen4m Wi-Fi 打通

镜像依次为 `2ef75858d902` → `abb806980b75` → `62b76e366f2b` → `2cb02d5fadbc`
→ `bb7e832e7511` → … → `b6475ed6a386` → `30c24b2a4684`。

- `2cb02d5fadbc`：reserved-memory 节点加上 `shared-dma-pool` 之后，BT 和 Wi-Fi 的
  conninfra 客户端都注册成功。
- `bb7e832e7511`：开机时 BT+Wi-Fi 预校准成功，BT inquiry 第一次找到已知设备。
- `b6475ed6a386`：`wlanDownloadFW` 失败（`0xc0000001`）定位到 EPA/ELNA NVRAM 缺失。
- `30c24b2a4684`：EPA/ELNA 缺失不再视为致命错误。固件下载完成，`wlan0` 注册，
  扫描、关联、DHCP、IPv6 都正常。
- `2e046f98a444`：注入本机 Android 的 `WIFI` NVRAM 和 `wifi.cfg`。

## attempt101：开机自动联网、校时、DNS

`fcde39d8a1cb`：开机自动关联，并在 Wi-Fi 上开第二个 SSH 监听，两次 clean boot
都确认生效。`bbce98901cc0`：DHCP 后改写 resolv.conf，NTP 以 `/run/time-synced`
是否存在决定是否重试，`apt update` 正常。

## attempt102：BLE 扫描定位

- 裸 HCI 二分：T9（扩展扫描 `0x2041`/`0x2042`）收到 1413–1571 条扩展广播报告；
  legacy 扫描（T0）收到 0 条。
- `0x1002` 原始读取：控制器的 octet 37 是 `0xff`。
- btmon 抓包：BlueZ 用的是 legacy `0x200b`/`0x200c`，全部返回 Success，但没有任何报告。

## attempt103：`HCI_SETUP` 修复

镜像 `f3d3a88c5cfa`。`cmds26=ff cmds37=ff use_ext=1`；`btmgmt find -l` 发现 90 个，
`btmgmt find` 发现 48 个；无 Oops。

## attempt104：去掉 APCF 重放和调试打印

镜像 `144c48dbb098`（只含 `8117d622c`）。`find -l` 发现 126 个，`find` 发现 68 个。
APCF 不是必需的。

## attempt105：从 proinfo 读出厂地址

镜像 `13fdd02be3d4`（`54dd59781`）。启动 5.6 s 时读取 proinfo；wlan0 和 hci0 都用
出厂地址（OUI `1c:d1:07`，Wi-Fi = BT + 1）。

## attempt106：rootfs 中的 BlueZ

rootfs `debian-1ed1b45c80c2`（sha256 `5c064880…6612`），在 Android 下写入 `/cache`。
内核 `24c0e33d5597`：SSH 10.7 s 就绪，bluetoothd 11.1 s 启动，Wi-Fi 30.9 s 拿到地址；
`bluetoothctl` 显示 Powered yes、public 地址；15 s 扫描发现 32 个设备；无 Oops。
