# op6893 Wi-Fi 二进制分析任务

## 结论与范围

需要有针对性的二进制分析，当前最高优先级是 Android 用户空间的校准数据
交付流程；尚无证据表明必须先逆向 WLAN 固件内部才能移植现有驱动。
请先完成任务 A。任务 B 可做静态文件格式核对；任务 C 仅在源码不能解释
校准行为或运行时遇到具体阻塞时深入。无需修改固件、绕过签名或重写射频算法。

目标：让 Debian 主线环境以本机原有固件和校准数据初始化 Wi-Fi，不依赖
Android HAL、属性服务、nvram daemon 或屏幕亮灭事件。当前尚未启用 Wi-Fi。

## 结果已接收（2026-11-03）

原报告位于 `/home/hzyry2046/src/conninfra-rev/REPORT.md`。经过独立复核的
集成约定见 [WIFI-INITIALIZATION.md](WIFI-INITIALIZATION.md)：
前缀是12字节 ASCII、无NUL、无尾部补零；本机BTIF剥离48字节EMI头。
这几项修正优先于原报告。任务A主要协议已闭合，B/C仍保留明确的未知项。

## 输入文件及身份

固件与用户空间文件根目录：
`/data/src/mikuui/vendor/oplus/op6893/proprietary/vendor/`

同目录文档 `wifi-binary-manifest.json` 记录实际文件路径、长度和 SHA256。
请在报告中引用对应哈希，区分本次 mikuui 文件与历史 ACK 日志里的版本；
同名不保证内容一致。不把 proprietary 固件或本机 NVRAM 原文提交进内核仓库。

已确认的硬件/源码路径：MT6893、AXI、CONNAC2X2_SOC3_0、MT6635 模拟芯片。
驱动源码根目录：
`/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/vendor/mediatek/kernel_modules/connectivity/`

## A：优先分析 wlan_assistant 的 NVRAM 交付协议

入口：`bin/wlan_assistant`。本次 strings 已找到 `/dev/wmtWifi`、
`WR-BUF:NVRAM` 和 `/mnt/vendor/nvdata/APCFG/APRDEB`；这些只是入口线索，
不是已证明的调用顺序。

辅助文件：`lib64/libnvram.so`、`lib64/libcustom_nvram.so`、
`lib64/libwifi-hal-mtk.so`、`etc/init/wlan_assistant.rc`。
libcustom_nvram 中存在 WIFI、WIFI_CUSTOM 对应 nvdata 文件路径。

请回答：

1. 真正读取哪些文件/LID？WIFI 与 WIFI_CUSTOM 各自作用，大小如何确定？
   是否需要 NVM_GetFileDesc 等接口，还是直接 open/read？有哪些版本检查？
2. 写入 WR-BUF:NVRAM 的负载是否原样复制？是否拼接、去除文件头、重算校验、
   变更字节序、加入 MAC/板级选择/默认数据？给出确切偏移、长度、字段与算法。
3. 所有 write/ioctl 的顺序是什么？是否先送 DRVCFG/FWCFG/XONV，再送 NVRAM，
   最后写 1 或 STA？请区分初始化、正常上电、恢复、关机与工厂测试路径。
4. 等待哪些设备节点、属性、事件或回调？哪些可用 Debian 的文件存在检查、
   poll 或明确状态检查替代？超时、短写、EINTR 和重试如何处理？
5. 是否写回或修复 nvdata？区分读取本机校准与恢复默认值，初版只需读。
6. 哪些是量产通用数据、哪些是这台机器的校准？mikuui 中的默认 blob
   不能自动替代设备上的工厂数据。缺少实机文件时请列出需要采集的路径和长度，
   不猜填内容。

交付：带二进制哈希和函数地址/文件偏移的调用图、字段表、启动顺序、错误路径，
以及可实现为小型 Debian 工具的伪代码。若给提取脚本，默认只读并输出哈希/结构；
不打印完整 MAC、序列号或校准负载。当前无需在设备执行射频操作。

## B：固件封装与主机加载协议核对

文件：
- WIFI_RAM_CODE_soc3_0_1a_1.bin
- soc3_0_ram_wmmcu_1a_1_hdr.bin
- soc3_0_ram_wifi_1a_1_hdr.bin
- soc3_0_patch_wmmcu_1a_1_hdr.bin
- soc3_0_ram_mcu_1a_1_hdr.bin
- soc3_0_ram_bt_1a_1_hdr.bin
- conninfra.cfg、BT_FW.cfg

先对照 `wlan/core/gen4m/chips/soc3_0/soc3_0.c` 的下载路径和 BT mt66xx
下载实现，核对封装头、段长度、目标地址、入口、版本、压缩/加密标记和
校验字段。不预设处理器指令集、加载基址或压缩算法。源码已能解释的字段
无需逆向重做。说明每段是主机可解析的容器还是实际 MCU 指令。

交付：只读解析结果、边界/长度校验、与主机源码逐字段对照；未知字段标为未知。
区分固件内部地址与 AP 物理 EMI 地址，禁止根据字符串地址直接推导 AP 映射。

## C：条件性深入——BT/WLAN 联合预校准

当前源码已证明：conninfra 等待 BT 和 WLAN 两个真实回调，先上电两者，
执行 BT 校准，再执行 WLAN 校准并备份结果。BT 回调会发送真实固件命令。
因此初期保留完整回调参与，不用返回成功的空函数替代。

若希望进一步缩减蓝牙依赖，需要分析：
- btmtk_cif_send_calibration 对应的命令、事件、状态码和结果格式；
- BT 校准结果是否被 WLAN/共享 RF 使用，在哪里存储、恢复与判定有效；
- WLAN 预校准的固件命令、完成/失败事件、EMI 结果地址与生命周期；
- 冷启动、暖重启、失败后重试，是否需要不同处理。

结论必须标注“静态证据”“运行时证据”或“假设”；仅观察到一个成功状态码
不足以证明可以跳过蓝牙校准。若无法确定，继续沿用真实 BT 参与路径。

## 已知状态机陷阱，避免重复分析

详见 `evidence/attempt-50.md` 和对应编号源码摘录：
- conninfra PRE_CAL_DONE 与 WLAN g_fgEverCal 是两个独立标志。
- wlan_precal_docal_v1 在错误出口也设置 g_fgEverCal；完成不等于成功。
- NVRAM handler 会注册 WLAN 回调；最后一个参与者注册可能自动触发上电。
- nvram 模块参数虽有 request_firmware 路径，但在 adapter-start 中调用，
  尚不能确认它能绕过首次回调注册与预校准的先后依赖。
- wmtWifi 的 NVRAM handler 等待可达约200秒；用户空间超时不保证取消内核工作。

## 返回结果位置

请在 `/data/src/mainline/mt6893-direct/evidence/wifi-re/` 保存报告与只读脚本，
附所分析文件 SHA256、工具版本、地址/偏移引用、未解决问题。
不要修改正在工作的 ACK 或主线内核。优先返回任务 A，即使 B/C 尚未完成，
这样内核侧的电源域、PMIC、EMI 和编译适配可以继续独立推进。
