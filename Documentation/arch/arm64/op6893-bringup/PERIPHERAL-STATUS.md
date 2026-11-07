# op6893 / MT6893 主线硬件与外设支持状态

更新基线：attempt97（TOPA18/384/394 往返写入/恢复通过）。设备当前运行主线，ACK 恢复备份按用户要求沿用原版本；
attempt67 进入测试前为用户恢复的实际4.19 Android，uname5.10.0为伪装，未更新备份；
当前实机镜像是 `9d1e950c4d59`，内核
`7.3.0-op6893-d1-9d1e950c4d59+`；trim no-op复核、TOP070重复读取与全部清理通过，源码检查点
`f12c1a18c` 加本地未提交修改。
外置 Debian 镜像 `9825862f46b0`。本文描述这台设备的主线实测结果，
不把 ACK 的功能、源码中存在的驱动或 DT 节点视为主线已经支持。

各行限制对应所引实验，后续集成进展见较新的行。
“实测”仅覆盖表中列出的行为；“部分”表示可用但仍依赖 LK 状态、临时配置
或缺少关键功能；“未启用”不表示硬件损坏或永远无法支持。

## 已运行与部分支持

| 硬件/功能 | 当前状态 | 已验证内容 | 限制与下一步 | 证据 |
|---|---|---|---|---|
| CONN XOBUF / THADC IR 写入/恢复 | 部分，实测 | TOPA18→0xf6e8fff5、TOP384/394→0x2008 各读回并恢复基线；TOPA1C基线已等于厂商值未写；30笔传输，总4.20s/8s | 仅寄存器读回；未保留配置；不证明模拟效果；Wi-Fi不可用 | [97](evidence/attempt-97.md) |
| CONN CAL LDO 写入/恢复 | 部分，实测 | TOP380/390 各写0xe8002读回、写回基线0xe0002读回；20笔传输，总2.87s；阶段独立预算；清理无残留 | 仅寄存器读回；不证明LDO实际关闭或模拟效果；TOP384/394未写；Wi-Fi不可用 | [96](evidence/attempt-96.md) |
| CONN CAL LDO / THADC 配置读取 | 部分，实测 | TOP380/390=0xe0002、TOP384/394=0x8，各读两次一致；与厂商目标各差一位；32笔传输，2.36s/4s，清理无残留 | 只读；位含义未确认；未写入；Wi-Fi不可用 | [95](evidence/attempt-95.md) |
| CONN WF_PAD 写入/恢复 | 部分，实测 | TOP070 基线0x0；写0x80000000读回、写回0x0读回，18笔传输，3s预算内完成，清理无残留 | 仅寄存器读回；不证明电气HighZ、复位值或校准有效；厂商校准后值0x5不是本板基线；Wi-Fi不可用 | [94](evidence/attempt-94.md)、[93](evidence/attempt-93.md)、[92](evidence/attempt-92.md) |
| CONN WF_PAD 配置读取 | 部分，实测 | 新鲜trim no-op前提下TOP070两次一致；不等于厂商目标；完整清理 | 未写pad配置，未验证电气HighZ或恢复语义；Wi-Fi不可用 | [90](evidence/attempt-90.md) |
| CONN thermal trim 候选比较 | 部分，实测 | 两种候选逐步均不改变本次基线，私有计算后擦除，完整清理 | 未执行trim写入；不证明校准有效；每次须重新验证no-op；Wi-Fi不可用 | [89](evidence/attempt-89.md) |
| CONN thermal 模拟寄存器读取 | 部分，实测 | TOP034/038各读两次一致；私有值不输出、临时清零、完整清理 | 未验证写入/trim/模拟恢复；额外位语义待定；Wi-Fi不可用 | [88](evidence/attempt-88.md) |
| CONN efuse 私有 SYSRAM 交付 | 部分，实测 | 四槽初始零、写入读回一致、清零复扫后完整清理；元数据诊断 | 实验结束即擦除，未验证固件消费或trim；Wi-Fi仍不可用 | [87](evidence/attempt-87.md) |
| CONN efuse 结果读取 | 部分，实测 | 四字各读两次且一致；私有值不输出，临时及诊断缓存擦除，全部外层恢复 | 未验证字段含义或trim；私有SYSRAM交付见87；Wi-Fi仍不可用 | [86](evidence/attempt-86.md) |
| CONN efuse 引擎 | 部分，完成/清理实测 | 三次kick0/valid1、低6位稳定例外，全部外层恢复，CONN关闭 | 本机E3经验规则；未读私有数据、应用trim或启动Wi-Fi | [85](evidence/attempt-85.md) |
| CONN efuse 控制状态 | 部分，实测 | 持有FM/模拟/mailbox时两次CTRL108完整比较一致；kick/valid/mode/address字段为0，ID隔离读通过 | 此行为attempt81基线；后续触发失败见82；未读数据字或应用trim；不代表Wi-Fi或校准可用 | [81](evidence/attempt-81.md) |
| CONN FM SPI 读格式配置 | 部分，实测 | FM_CTRL 801f→0→801f；thermal字反复核对，数字恢复先于模拟/mailbox清理 | 仅验证SPI格式字；未启用FM广播、Wi-Fi或固件，顺序保护不等于原子排他 | [80](evidence/attempt-80.md) |
| CONN FM / thermal 数字基线 | 部分，实测 | FM_CTRL=801f；thermal地址已为50305a00；两轮一致，CAL_EN/GPT2为0，thermal所有权检查通过 | 未写数字路由、未校准；被动检查不证明所有引擎静止，Wi-Fi不可用 | [79](evidence/attempt-79.md) |
| CONN 前两项模拟配置写入 | 部分，实测 | 持有ID mailbox，064写7700、0bc写21并读回；逆序恢复1/0后清mailbox和关断 | 只验证寄存器字值，不证明内部模拟状态完全回滚；未启动固件/Wi-Fi | [78](evidence/attempt-78.md) |
| CONN 前两项模拟配置读响应 | 部分，实测 | 0x064 两轮为0、0x0bc 两轮为1，四次ID隔离读一致；逐笔RDAT变化 | 未写厂商7700/21目标；不证明无读取副作用或复位/回滚语义 | [77](evidence/attempt-77.md) |
| CONN A-die ID mailbox | 部分，实测 | 新鲜 E3 ID 写入 SYSRAM +0x2800、读回、清零；完整清理成功 | 本轮清理后不保留给固件；尚未启动固件或 Wi-Fi | [76](evidence/attempt-76.md) |
| CONN TOP 单寄存器写入/恢复 | 部分，实测 | E3/精确基线限定，0xa18 写 f6e8fff5、独立读回并恢复 f668fff5；完整清理通过 | 不是完整模拟初始化或物理电压验证；尚无 Wi-Fi | [75](evidence/attempt-75.md) |
| CONN TOP XTAL 读取 | 部分，实测 | ID 后读取 0xa18=0xf668fff5、0xa1c=0x55555fff；逐笔 RDAT 变化，完整清理成功 | 无模拟写入/efuse/校准/固件；尚不能连接 Wi-Fi | [74](evidence/attempt-74.md) |
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
| CONN 只读预检 | 部分，实测 | root-only 接口；RC 位直接读为1；16次串行+4次并发、六路真实供电句柄；CONN/VCN 关闭 | 上游供电策略未解决，始终报告不可激活；未执行上电或访问 CONN MMIO | [58](evidence/attempt-58.md) |
| CONN 公共供电轨实验 | 部分，实测 | 显式一次性 VCN18→VCN13 开启、反序关闭；使能状态确认、配置恢复、重复请求拒绝 | VS1/VS2 各保留一个引用直到重启；外部输入仍继承/dummy；CONN 电源域未开启，未访问暗域；不代表 Wi-Fi 可用 | [59](evidence/attempt-59.md) |
| CONN 电源域 / 引脚实验 | 部分，实测 | 双电源 ACK、控制字0xd、host 请求；引脚切换后恢复，关断及供电清理成功；七点请求/ACK 追踪 | STA1 bit14 重新出现但请求保持0，机制未明；按方向检查后 ID 读取成功。上游供电仍继承，不是完整 genpd 驱动 | [61](evidence/attempt-61.md)、[63](evidence/attempt-63.md) |
| CONN HOST_CSR 诊断 | 部分，实测 | AP→CONN 检查后读取三项状态；内部 sleep ACK bit5=0、timeout bit0=1；关域及供电清理通过 | 62 为未重置的原始快照；63 已单独请求刷新并验证内部 ID，仍未启用 Wi-Fi | [62](evidence/attempt-62.md) |
| CONN 数字 ID | 部分，实测 | 时钟检测器刷新请求后检查 clocks/timeout/sleep；读得 HW=0x20010101、cfg=3，两字完整；关域及供电清理通过 | 一次性板级实验；无 D-die/SYSRAM 初始化、SPI/A-die、固件、DMA、校准或无线网络 | [63](evidence/attempt-63.md) |
| CONN 初始化基线 / EMI 分配 | 部分，实测，只读 | 从当前 Linux 保留区取得 EMI base/size；ID 后采集 RGU、SYSRAM 控制和 remap 共13项；关断清理通过 | 65 已验证临时 remap 写入并恢复；SYSRAM 软件字尚未初始化，不能作为无线电运行状态 | [64](evidence/attempt-64.md) |
| CONN remap 事务 | 部分，实测 | MCU EMI→本次分配地址、三路外设→ACK 目标；四项完整回读及反序恢复；关域和供电清理通过 | 测试后恢复原映射；未读写 EMI 负载、未验证 MPU/DMA/固件；恢复不确定时保留供电 | [65](evidence/attempt-65.md) |
| CONN RGU 内存硬件策略 | 部分，实测 | SYSRAM/共存内存电源与休眠四项 ACK 目标回读、反序恢复；关域和供电清理通过 | 原策略已恢复；不证明 SRAM 数据保留，不含清空、efuse/mailbox、SPI/A-die 或固件 | [66](evidence/attempt-66.md) |
| CONN SPI 初始化基线 | 部分，实测，只读 | A-die 控制、SPI/WB 状态和36项休眠命令配置完整采集；关断清理通过 | 26项配置不同于 ACK 目标；68已验证临时写入并恢复；尚未释放 A-die reset 或执行 RF SPI 传输 | [67](evidence/attempt-67.md) |
| CONN SPI 休眠命令配置 | 部分，实测 | 36项 ACK 掩码目标回读及原值恢复；命令长度最后写入、最先恢复；状态检查与关断清理通过 | 测试后恢复原配置；仅验证寄存器，不代表命令执行、RF SPI 或 A-die 支持 | [68](evidence/attempt-68.md) |
| CONN RF SPI 硬件信号量 | 部分，实测 | index11 单次获取返回1；M2 报告 bit11 为0→1→0，释放确认及关断清理通过 | 未验证多 master 争用、其他编号或 RF SPI 传输；所有权不确定时保留供电 | [69](evidence/attempt-69.md) |
| CONN SYSRAM 清零 | 部分，实测 | RGU 四项策略保持期间清零16 KiB，4096字逐项回读及全量复查通过；RGU 恢复和关断清理通过 | 不证明关断后的数据保持；未释放 A-die 复位，未运行固件或 Wi-Fi | [70](evidence/attempt-70.md) |
| CONN 26 MHz strap / GPIO180 | 部分，实测 | 预置高电平→GPIO→外设复用→低锁存→输入；6次选择、7组回读通过，共享字段保持，关断正常 | 仅配置回读；未测电气波形或 A-die strap 采样，未释放 A-die 复位 | [71](evidence/attempt-71.md) |
| CONN 初始化前置组合 | 部分，实测 | remap/RGU/SPI 配置保持期间清零 SYSRAM、设置 GPIO180 并获取/释放信号量；逐层恢复及关断通过 | A-die 复位始终保持；尚无 RF SPI 传输、A-die ID 或 Wi-Fi 固件运行 | [72](evidence/attempt-72.md) |
| MT6635 A-die / RF SPI TOP | 部分，实测 | 释放复位后单次读取 ID=0x66358a11（E3），RDAT 从0变化；重新拉回复位、地址/锁/外层配置恢复通过 | 未采样到 busy 脉冲；仅芯片 ID 读取，未模拟初始化、校准、固件或无线网络 | [73](evidence/attempt-73.md) |
| 电池电压 ADC | 部分 | IIO 原始值和电压比例，连续采样 | 未做外部仪表校准；没有电量百分比、充电控制、battery power_supply | [34](evidence/attempt-34.md) |
| PMIC 芯片温度 | 部分 | `in_temp2_input` 毫摄氏度；真实校准 shadow；与原始值换算对照 | 本机零有效斜率诊断；非法校准返回错误；无 thermal zone/trips/cooling，绝对精度未验证 | [36](evidence/attempt-36.md)、[37](evidence/attempt-37.md) |
| LK devinfo 校准传递 | 实测（基础设施） | 884字节与当次 ACK 一致；22个 LVTS 校准字解码 | 结构校验不等于传感器工作；还没有通用 NVMEM provider | [38](evidence/attempt-38.md)、[39](evidence/attempt-39.md) |

## 尚未启用或未完成验证

| 外设/能力 | 当前状态 | 已知依赖/下一步 |
|---|---|---|
| SoC LVTS / CPU、GPU 温度 | 未启用 | 7控制器17传感器布局已审查；时钟、复位、ID、17路 RCK 和校准写入已实测；周期采样、温度接口、中断和保护仍未完成；不要用 PMIC 温度替代 |
| 全 SoC 时钟、复位与电源域 | 未完成 | 当前只接管局部资源；热控 gate 实测已开、AXI 为 MAINPLL/14；寄存器推算 MAINPLL2184MHz、AXI156MHz，非实测频率，仍属启动环境状态 |
| PMIC regulator / CPU 供电 | provider 已注册，公共 VCN 供电轨循环已验证 | MT6359P 45路描述符注册；VCN18/13 显式使能和恢复实测，保留共享父轨引用；外部输入仍有 dummy，未调压或启动 CONN；MT6315/SPMI 与 CPU 轨待核对。见 [54](evidence/attempt-54.md)、[59](evidence/attempt-59.md) |
| CPUfreq / CPUidle / suspend | 配置关闭 | 先完成时钟、供电轨、SoC 热控与唤醒链路 |
| 充电器、Type-C 检测、USB PD | 未启用/未验证 | ACK MT6360/I2C 路径仅为调查线索；需要控制器时钟、引脚、IRQ 和芯片识别 |
| 电池电流、容量、SOC、完整电源状态 | 未启用 | 电池电压不等于 fuel gauge；本机 ADC 配置排除阻抗/电流测量 |
| 显示 / 背光 | 未启用 | DRM 关闭；需确认本机面板、DSI、供电与背光链路 |
| 触摸屏 | 未启用 | 需核对芯片、总线、供电和复位；GPIO20 是触摸复位线索，不应当作音量加 |
| GPU 加速 | 未启用 | GPU 驱动、时钟、电源域、供电、固件及热控待建立 |
| Wi-Fi / Bluetooth | 未启用；Wi-Fi 优先推进 | 主线已实读 MT6635 E3 ID；ACK 已确认 AXI / SOC3_0 固件路径；接续模拟初始化、校准和固件依赖，再验证独立 Wi-Fi SSH；Bluetooth 仍关闭。见 [49](evidence/attempt-49.md)、[逆向复核与初始化约定](WIFI-INITIALIZATION.md) |
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

以独立 Wi-Fi SSH 优先于 USB 接管为当前顺序：[只读审查55](evidence/attempt-55.md) 已确认 CONN 引脚仍在 GPIO 模式、
AP2CONN host-clock 请求未开启，XO 输出尚未验证。active/idle 引脚状态已落成未引用的 DT 配置，并通过编译与离线字段检查
（[57](evidence/attempt-57.md)），尚未在主线切换。先完成 CONN 时钟、引脚、
真实供电与受控电源域实验，再接入固件/NVRAM/校准。MT6359P provider 注册
已通过，但仍有 dummy 输入，尚不能据此启动无线。以下热控工作在依赖具备后推进。

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

### CONN 电源前置调查（attempt51）

实机只读快照确认 CONN 域关闭；现有主线 MT6893 电源域表与 ACK 的总线
保护位和顺序有差异，暂未启用。新增固定寄存器快照工具，未访问无线岛、
未上电或刷机。见 [51](evidence/attempt-51.md)。

### 无线供电映射（attempt52）

18项 PMIC 固定寄存器只读采集确认 MT6359P、四路 VCN 关闭、VS2 开启。
主线 VCN33 的 BT/Wi-Fi 名称是共享轨兼容包装；probe 有条件同步使能位，
不是无副作用注册。尚未启用 regulator provider 或无线供电。见 [52](evidence/attempt-52.md)。

### CONN 电源顺序主机验证（attempt53）

抽取并执行两套 ACK 的真实电源函数，模拟寄存器写入顺序一致；无应答场景
由测试工具终止，ACK 自身没有该等待上限。已核对实际编译分支。仅主机验证，
未在设备运行上电事务。见 [53](evidence/attempt-53.md)。

## Attempt87：私有 SYSRAM 交付、清除及完整清理通过

`adie-efuse-handoff-cycle` 实测四个槽位初始为零，写入和读回全部一致，
逐项清零、完整复扫及最终guard通过后才释放外层资源。
issued/verified/cleared均0xf，dirty0，数据阶段935372615ns；临时私有缓冲区
仍显式擦除，诊断只输出元数据。全部外层清理成功，CONN关闭；USB SSH、
八核、只读存储、ADC/17路LVTS、引脚及九组缓存哈希/重试拒绝回归通过。
设备保留在 `4d408b45c192`，恢复备份未更新。此实验结束即清除交付槽，
未为固件保留数据、应用trim或启动Wi-Fi。下一步私下解码thermal有效位和
目标掩码，并核对寄存器所有权/恢复条件，再单独验证trim写入。
见 [87](evidence/attempt-87.md)。

## Thermal trim 后续审计：写入位域存在额外一位

2026-11-04主机审计确认：厂商helper取值size+1位、清除size位，三个调用
可能额外置位TOP034 bit16和TOP038 bits26/28；两个TOP038操作还存在
中间状态/覆盖顺序。三棵源码各262144个合成用例通过，本地4.19编译对象
反汇编支持相同算术；尚未证明对象与设备Android镜像一致。
这不是硬件位定义或修复依据。下一轮先进行TOP034/038的私有只读重复验证，
写入前明确额外位含义和恢复条件。本轮未刷写，设备保持87，Wi-Fi仍不可用。
详见 [THERMAL-TRIM-AUDIT.md](THERMAL-TRIM-AUDIT.md)。

## Attempt88：TOP034/038 私有只读重复验证通过

`adie-thermal-read` 在SYSRAM交付清除后，读取两个thermal模拟寄存器各两次，
16笔ID/目标/ID/CTRL传输，四次目标读取和两项比较通过。仅输出元数据，
临时值显式清零；总数据阶段1342856846ns，原2s预算未扩大。
全部外层清理成功，CONN关闭；USB SSH、八核、存储、ADC/17路LVTS及
引脚/九组缓存哈希回归通过。设备保持 `bf54e7cab5af`，恢复备份不变。
未写入trim或启动Wi-Fi。后续需明确额外位含义、所有权与恢复语义，
不能由读取一致直接推断可以回写。见 [88](evidence/attempt-88.md)。

## Attempt89：两种 trim 候选在本次基线下均无需写入

`adie-thermal-plan` 在私有内存按厂商顺序计算两种候选，实测
vendor_noop/bounded_noop/policies_equivalent均1，complete/cleared均1。
比较覆盖每个中间步骤，不只是最终值；没有写入trim，也未输出有效位或
校准值。此结果不区分“无有效操作”与“已有匹配配置”，不证明物理校准有效。
总数据阶段1343797846ns，全部清理与回归通过，CONN关闭。
设备保持 `9c7b04db21e4`，恢复备份未变，Wi-Fi仍不可用。
下一步以每次重新验证的no-op条件为前提推进后续初始化；条件不成立则拒绝，
不能硬编码跳过，也不据此放开trim写入。见 [89](evidence/attempt-89.md)。

## Attempt90：新鲜 no-op 前提下 TOP070 重复读取通过

新命令 `adie-pad-read` 每次重新计算trim候选并要求两种序列均no-op且一致，
否则在TOP070访问前拒绝并保留资源。本轮前提再次成立；TOP070两次读取
一致，8笔传输通过，但不等于厂商80000000目标。没有写pad或trim配置，
临时数据清零；总数据阶段1554148616ns，全部清理/外设回归通过，CONN关闭。
刷写后的首次重启仍停fastboot，原因未确定；再次正常reboot后启动成功。
设备保持 `9d1e950c4d59`，恢复备份未变，Wi-Fi仍不可用。
下一步先设计独立pad写入/读回/恢复实验，核对所有权与恢复条件，不能把
读取稳定当作可以安全回写的证明。见 [90](evidence/attempt-90.md)。

## 2026-11-04：TOP070 固定值往返待实机验证

[attempt91](evidence/attempt-91.md) 已实现并构建 `adie-pad-cycle`，仅在新鲜
trim no-op 成立、重复基线为5时执行目标写入、读回及恢复。主机验证完成，
设备复位后正在等待 fastboot；尚未刷入或验证本轮，Wi-Fi 状态不变。

## Attempt91-94：TOP070 往返

91 被基线门限拒绝（板上基线非0x5）；92 新增 `pad_value` 输出，实测0x0；93 改为恢复实测基线0x0，
但共享2秒数据预算在第一次写后耗尽（保留资源，下次启动基线仍为0x0）；94 仅对该命令使用3秒预算，
实测写入、读回、恢复、读回全部通过，无残留。设备保持 `001e99b1fbd5`，ACK 备份未变。
下一步：厂商序列中的 CAL LDO(TOP380/390)、XOBUF(TOPA18)、XTAL(TOPA1C)、IR(TOP384/394)，
应逐项单独实验，不能把TOP070往返当作Wi-Fi初始化完成。见 [94](evidence/attempt-94.md)。

## Attempt95

`adie-cfg-read` 实测四个寄存器基线，均与厂商目标仅差一位。设备保持 `183cfc1cfb87`。见 [95](evidence/attempt-95.md)。

## Attempt96

数据预算改为阶段独立（前置2s、pad 2s、cfg 3s、cal 3s，总上限8s）。`adie-cal-cycle` 实测通过。设备保持 `7551df9a01e1`。见 [96](evidence/attempt-96.md)。

## Attempt97

`adie-ir-cycle` 实测通过；厂商序列中到 GPIO180 回切为止的固定写入均已逐项验证（均恢复，未保留）。设备保持 `7b4f9d238ef2`。见 [97](evidence/attempt-97.md)。
