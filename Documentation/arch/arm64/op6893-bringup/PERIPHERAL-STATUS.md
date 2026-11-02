# op6893 / MT6893 主线硬件与外设支持状态

更新基线：attempt48。当前实机镜像 `06374ef46937`，内核
`7.3.0-op6893-d1-06374ef46937+`；源码基线
`cbbddb6b08cc9900a87cccaa9b22bbe06aa4f50a` 加本地未提交修改。
外置 Debian 镜像 `9825862f46b0`。本文描述这台设备的主线实测结果，
不把 ACK 的功能、源码中存在的驱动或 DT 节点视为主线已经支持。

“实测”仅覆盖表中列出的行为；“部分”表示可用但仍依赖 LK 状态、临时配置
或缺少关键功能；“未启用”不表示硬件损坏或永远无法支持。

## 已运行与部分支持

| 硬件/功能 | 当前状态 | 已验证内容 | 限制与下一步 | 证据 |
|---|---|---|---|---|
| 直接启动、内存 | 实测 | 从 boot 分区启动主线，导入 LK 内存与保留区 | fastboot boot 不可靠；不改 GPT；仍是本机调试启动实现 | [39](evidence/attempt-39.md) |
| CPU / SMP | 部分 | CPU0–7 在线、用户空间与 SSH 运行 | 未完成 CPUfreq、CPUidle、热控或长期负载验证 | [39](evidence/attempt-39.md)、[40](evidence/attempt-40.md) |
| UFS / 块设备 | 部分 | 读取 cache 上 rootfs，核对镜像哈希 | 时钟/PHY 等仍继承 LK；当前磁盘只读策略，不代表写入、链路省电已验证 | [37](evidence/attempt-37.md)、[39](evidence/attempt-39.md) |
| USB device：ACM / ECM | 部分 | 串口枚举、USB 网络和 SSH；开发主机原生驱动可用 | 强制 VBUS；供电/时钟部分继承；USB host、Type-C 角色检测、充电协商未验证 | [34](evidence/attempt-34.md)、[39](evidence/attempt-39.md) |
| AP watchdog | 实测 | 周期喂狗；停止喂狗后复位，多次用于测试 | 不代表 suspend 唤醒或完整重启/关机路径已支持 | [39](evidence/attempt-39.md) |
| GPIO / pinctrl / EINT | 部分 | 控制器注册、已识别按键及 PMIC 中断路径 | 不是全部引脚复用、电气属性、唤醒能力的验证 | [25](evidence/attempt-25.md)、[26](evidence/attempt-26.md) |
| 音量减键 | 实测 | GPIO155 → EINT → evdev，KEY_VOLUMEDOWN 按下/松开 | 未验证 suspend 唤醒；当前轮只检查设备注册 | [26](evidence/attempt-26.md) |
| 音量加键 / 电源键 | 实测，另有硬件故障 | PMIC HOMEKEY / PWRKEY 事件；音量加与短按电源实测 | 用户报告电源键受潮、可能自触发；不能将自触发直接归因于驱动；未验证唤醒 | [29](evidence/attempt-29.md)、[32](evidence/attempt-32.md) |
| MT6885 PMIF / pwrap | 部分 | 专用寄存器布局、PMIC 读取、错误路径主机测试 | SPI 初始化仍继承 LK；wrapper 错误 IRQ 未接管、相关错误源保持屏蔽 | [33](evidence/attempt-33.md) |
| MAINPLL 只读 CCF | 部分，实测 | 实时寄存器换算 2184MHz，16次读取一致；刷写前后五项时钟寄存器相同 | 无 PLL 写入、调频或电源控制；不是物理测频，固件所有权未解决 | [42](evidence/attempt-42.md) |
| AXI 只读频率观测 | 部分，实测 | 选择器2对应 MAINPLL/14，CCF 156MHz；16轮交替查询正常 | 全部七种来源经主机测试；实机只测当前来源；parentless 观测，不是完整 mux 管理或测频 | [43](evidence/attempt-43.md) |
| Thermal gate | 部分，实测 | infra bit10，父 AXI 156MHz；critical 引用计数1/1，保持 LK 开启状态 | 未做实机关断；尚无 LVTS consumer、复位或测温；gate 频率依赖父时钟缓存 | [44](evidence/attempt-44.md) |
| LVTS 域复位 / 设备识别 | 部分，实测 | AP/MCU 精确掩码复位；七个设备 ID 0x81–0x87；结束后局部时钟、测温和保护关闭 | 一次性板级实验，硬编码资源；非完整 thermal 驱动；RCK/校准后续已验证，尚未采样 | [45](evidence/attempt-45.md) |
| LVTS 手动 RCK / EDATA | 部分，实测 | 17路 RC 2745–2774，未触发回退；17项 EDATA 与独立计算、读回一致 | 一次性校准实验；测量后局部时钟关闭；尚未采集 SoC 温度或启用保护 | [46](evidence/attempt-46.md) |
| LVTS 原始采样 / 温度换算 | 部分，实测 | 17路有效非零样本；本次启动39.431–44.471°C；换算与独立计算一致 | 一次性启动诊断，结束后停止测温；无持续温度接口、thermal zone 或保护；物理精度未校验 | [47](evidence/attempt-47.md) |
| LVTS 按需诊断接口 | 部分，实测 | root-only capture；完整17路、序号/采集区间；6次串行+4次并发通过 | 每次读取复位并重新校准；错误锁定直到重启；非低开销连续遥测或热保护 | [48](evidence/attempt-48.md) |
| PMIF 时钟 | 部分 | 实际 mux/factor/AP/TMR gate，四路引用 nominal26MHz | 仅 PMIF 子集；振荡器校准继承；未做频率测量或完整电源管理 | [32](evidence/attempt-32.md) |
| MT6359/MT6359P MFD / 按键中断 | 部分 | PMIC MFD、EINT222、嵌套按键 IRQ | 不表示所有 MFD 子设备和供电轨支持 | [29](evidence/attempt-29.md)、[37](evidence/attempt-37.md) |
| 电池电压 ADC | 部分 | IIO 原始值和电压比例，连续采样 | 未做外部仪表校准；没有电量百分比、充电控制、battery power_supply | [34](evidence/attempt-34.md) |
| PMIC 芯片温度 | 部分 | `in_temp2_input` 毫摄氏度；真实校准 shadow；与原始值换算对照 | 本机零有效斜率诊断；非法校准返回错误；无 thermal zone/trips/cooling，绝对精度未验证 | [36](evidence/attempt-36.md)、[37](evidence/attempt-37.md) |
| LK devinfo 校准传递 | 实测（基础设施） | 884字节与当次 ACK 一致；22个 LVTS 校准字解码 | 结构校验不等于传感器工作；还没有通用 NVMEM provider | [38](evidence/attempt-38.md)、[39](evidence/attempt-39.md) |

## 尚未启用或未完成验证

| 外设/能力 | 当前状态 | 已知依赖/下一步 |
|---|---|---|
| SoC LVTS / CPU、GPU 温度 | 未启用 | 7控制器17传感器布局已审查；时钟、复位、ID、17路 RCK 和校准写入已实测；周期采样、温度接口、中断和保护仍未完成；不要用 PMIC 温度替代 |
| 全 SoC 时钟、复位与电源域 | 未完成 | 当前只接管局部资源；热控 gate 实测已开、AXI 为 MAINPLL/14；寄存器推算 MAINPLL2184MHz、AXI156MHz，非实测频率，仍属启动环境状态 |
| PMIC 可调 regulator / CPU 供电 | 未启用对应供电控制 | MT6359 regulator 驱动关闭；存在固定供电描述不等于真实供电轨接管；MT6315/SPMI 与轨映射待核对 |
| CPUfreq / CPUidle / suspend | 配置关闭 | 先完成时钟、供电轨、SoC 热控与唤醒链路 |
| 充电器、Type-C 检测、USB PD | 未启用/未验证 | ACK MT6360/I2C 路径仅为调查线索；需要控制器时钟、引脚、IRQ 和芯片识别 |
| 电池电流、容量、SOC、完整电源状态 | 未启用 | 电池电压不等于 fuel gauge；本机 ADC 配置排除阻抗/电流测量 |
| 显示 / 背光 | 未启用 | DRM 关闭；需确认本机面板、DSI、供电与背光链路 |
| 触摸屏 | 未启用 | 需核对芯片、总线、供电和复位；GPIO20 是触摸复位线索，不应当作音量加 |
| GPU 加速 | 未启用 | GPU 驱动、时钟、电源域、供电、固件及热控待建立 |
| Wi-Fi / Bluetooth | 未启用；Wi-Fi 优先推进 | ACK 已确认 AXI / SOC3_0 固件 / MT6635 模拟芯片；先补 CONN 电源、PMIC 供电、EMI 与固件依赖，再验证独立 Wi-Fi SSH；Bluetooth 仍关闭。见 [49](evidence/attempt-49.md) |
| 音频 / 耳机检测 | 未启用 | codec、AFE、时钟/供电和路由待实现；accdet 尚未接入 |
| 摄像头 / ISP | 未启用 | 传感器型号、总线、供电、时钟、ISP 管线待调查 |
| RTC / 持久时间 | 未启用 | RTC_CLASS 关闭；不能用启动日志时间作为准确实时时钟 |
| modem / 蜂窝 / GNSS | 未启用 | 远端处理器、固件、共享内存和通信接口待调查 |
| NFC / 指纹 / 振动 / IMU 等传感器 | 未验证、未建立支持 | 需逐项识别本机硬件及资源，不能借用同品牌另一机型结论 |
| UFS 写入、USB host、运行时自动挂起 | 未验证 | 目前测试策略不覆盖这些行为 |
| pstore 故障恢复链路 | 历史不可靠，非保证能力 | 用户指出 fastboot oem peek 可读保留内存；不能把无 pstore 当作内核未执行的证明 |

## 当前用户空间与操作约束

- Debian13 arm64 SquashFS 位于 cache 的 `mainline/debian.squashfs`，外层 ext4
  以 `ro,norecovery` 挂载；根目录使用 tmpfs OverlayFS，运行时修改易失。
- BusyBox PID1 / watchdog 和 USB SSH 是调试基础；并非完整手机发行版体验。
- 保留 `clk_ignore_unused regulator_ignore_unused fw_devlink=off`；这些仍是
  bring-up 约束，不应在资源接管完成前简单删除。
- GPT 不一致是禁用 GenieZone、保留 EL2 的既定安排，不进行“自动修复”。
- 刷写用 `fastboot flash boot`，成功后立即 `fastboot reboot`。因电源键可能
  自触发，应预先排队串行命令，避免多个 fastboot 客户端竞争或无限重启循环。
- 需要回 ACK 时，使用当前备份 `evidence/ack-boot.img`（已按用户要求更新为设备上的 ACK，
  详见 [恢复基线](evidence/ACK-RESTORE-CURRENT.md)）；旧备份仅作历史归档。
- 旧启动尝试失败不推翻后续 USB/SSH 证据；同样，ACK 上可用不证明主线可用。

## 接下来的实施顺序

1. MAINPLL/AXI、thermal gate、LVTS AP/MCU 复位与 ID 路径已验证；继续实现初始化和 IRQ 资源。
2. 一次性采样与换算已通过；继续建立具有数据新鲜度语义的诊断接口，验证重复性与温度响应。
3. 根据实测结果再加入 SoC thermal zone / 保护策略，随后才考虑 DVFS/idle。
4. I2C、充电/Type-C、显示触摸等外设分别建立证据，避免同时引入多项未知变化。

最新资源审查：[attempt40](evidence/attempt-40.md)。按键物理测试日期/轮次见表中
证据，不将“本轮设备仍注册”写成“本轮重新按键通过”。新增支持后应同时更新本表
及对应 attempt 记录。以上支持仍是本机实验性移植，不等于可直接提交上游的完整实现。


MAINPLL 补充：[attempt41](evidence/attempt-41.md)。PCW 整数位必须显式设为8；
ACK 存在 FHCTL/MCUPM 管理路径，因此先设计只读 CCF 描述，不直接启用普通
PLL prepare/unprepare。attempt42 已加入并实测只读 provider，没有修改 PLL 或热控 gate。


[attempt42](evidence/attempt-42.md) 实机回归通过；设备保留在新主线运行。
后续 attempt43 已验证只读 AXI 观测；下一步接入 thermal gate 和复位资源。


[attempt43](evidence/attempt-43.md) 已实测只读 AXI 频率观测，设备运行
`9b805c863bf1`。它动态查询选择器及输入频率，不表示已建立完整的 CCF mux
层级或取得 AXI 控制权。thermal gate 随后由 attempt44 建立保持开启引用，
LVTS 复位与初始化尚未接管。


[attempt44](evidence/attempt-44.md) 已实测 thermal gate 的 critical 保持开启
引用，设备留在 `30a5bfb0c069`；这不代表 LVTS 初始化或 SoC 测温已支持。


[attempt45](evidence/attempt-45.md) 已实测一次性 AP/MCU 复位及七个 LVTS ID。
当前 `dfdd9316d585` 在时钟就绪后通过 deferred probe 自动完成识别，随后关闭
局部时钟；测温、校准写入、中断和保护仍未启用。


[attempt46](evidence/attempt-46.md) 已实测手动 RCK 和 EDATA 写入读回；设备
运行 `34b572808760`。17路校准一致，周期测温、中断与保护尚未启用。


[attempt47](evidence/attempt-47.md) 完成17路一次性温度采样；设备运行
`3e5080c359e5`。ACK 恢复备份已按用户要求更新为设备版本，完整校验与旧版
归档见[当前恢复基线](evidence/ACK-RESTORE-CURRENT.md)。


[attempt48](evidence/attempt-48.md) 已实测按需采集接口，设备运行 `06374ef46937`。
root 可执行：

```sh
cat /sys/bus/platform/devices/op6893-lvts-identify/capture
```

第一行包含序号及 boot-time 起止纳秒，后17行为传感器索引、MSR原始字、毫摄氏度。
每次读取都会复位并重新校准全部 LVTS；这是实验诊断操作，不要接入高频自动轮询。
失败返回错误且后续读取锁定到重启，不返回旧温度冒充新数据。成功后测温和局部
时钟关闭。当前不提供 thermal zone 或过热保护，绝对物理精度尚未校验。

## 推进顺序更新（attempt49）

先建立独立 Wi-Fi SSH 通道，验证断开 USB 数据连接仍能访问及掉线重连，
再改 USB/Type-C 的资源接管。当前实机基线仍为 attempt48；attempt49 仅完成
源码与历史 ACK 证据调查，没有启用 Wi-Fi、刷写镜像或改变设备供电状态。

### Wi-Fi 初始化依赖核对（attempt50）

当前厂商路径的预校准需要 BT 与 WLAN 两个真实参与者；NVRAM 交付会触发
WLAN 回调注册，随后可能自动上电。初期移植保留蓝牙校准所需底层组件，
不把配对服务作为目标。流程完成标志不等于校准成功，需单独核对返回值。
见 [50](evidence/attempt-50.md)。本轮仅源码审查，Wi-Fi 仍未启用。
