# op6893 / MT6893 主线硬件与外设支持状态

2026-11-19 SIM/RAT 补充：主线已取得分卡 AT 响应，双卡同时在不同运营商
注册 LTE。会话工具已支持选卡，两张卡都通过了双栈短测。
SIM2 实测 LTE B3/B40 和 NR n41（AcT 11，与 SA 驻网一致）。相同 SIM 和
IPv4-only PDP 配置下，LTE 重复探测通过；NR 曾收到 DNS 回包，但后续复测
无下行。同一 NR PDP 下往返切换证明失败与选错 CCMNI 通道有关：通道 0
两轮均无 DNS 回包，实际分配的通道 1 两轮均通过。拨号工具可用
`--activation-mapping` 按本次 LHIF 请求选择通道。SIM2 在 NR n41 上
IPv4 重复探测通过；LTE 和 NR 的双栈 PDP 均收到 IPv4 和 IPv6 DNS 回包。
NR 两次主动停用 PDP 后，自动重连选到新通道并恢复双栈；射频关开后
也验证了先等待重新附着，再恢复双栈。
长期稳定性、自然掉网恢复、NSA 和锁频段仍待验证。
见 [SIM/RAT 实测](MODEM-SIM-RAT.md)。

2026-11-19 更新：主线已在真机通过 `ccmnidp0` 跑通 IPv4。绑定网卡的
普通 UDP socket 收到匹配的 DNS 回复，ping 5 发 4 收。暂由用户态完成
PDP 激活和地址配置。约 24 秒的并行 TCP/UDP DNS 与 1500 字节 IPv4
探测已完成，有少量丢包。双栈 PDP 上通过用户态处理 RA 配置 IPv6，
IPv6 DNS 与 ping 5/5 均已通过。长时间稳定性、通话和 GNSS 尚未验收。见
[基带放行与数据面记录](MODEM-BOOT-RELEASE.md)。

2026-11-17 MD首次真机放行与真实数据实测：SCP常驻→`takeover/on`冷上电→
`prepare`门→唯一一次`(6,0)`放行（`boot_ret=0`）→HS1被接受、runtime发布、
endpoint arm；随后在真实NVRAM私有副本上完成整轮FS扫描（859请求/964发送/
`tx_error=0`/105路径/84写回），审计后的用户RPC属性应答（25条有值+9条已核实
缺失）使同一流程从88次发送推进到964次。当前边界是MD自身的
`MPU_NOT_ALLOW`（`ex_type=0x1d`）致命异常，HS2未到达，因此**蜂窝仍未启用**、
无CCISM后置协议、无注册或数据面。该边界已排除FS形状、真实NVRAM、属性查询、
feature 38、首启SMEM与EMI MPU表；异常记录按记录内核心数解码，LK几何以只读
`lk_regions` 查证。见[放行与异常边界](MODEM-BOOT-RELEASE.md)、
`evidence/modem-rpc-policy-live-boot.json` 与
`evidence/modem-source-recheck-and-baseline.json`（源未被写入：453文件中442
逐字节一致，11个差异全部是Android自身在提取后更新的运行时项）。

2026-11-16 MD放行入口离线接续：新增默认关闭的cache唯一owner（首次清零、
重连不清零）、`external-32k`事实读取与显式板级无晶体声明、ready gate和
唯一一次`(6,0)`放行；停止以MD1 OFF六寄存器读回为证据，PCM bit仅诊断。
实际C sanitizer、既有服务回归及启用/恢复ARM64构建通过；未刷机、未发SMC，
蜂窝支持状态不变。见[放行门槛与步骤](MODEM-BOOT-RELEASE.md)。

2026-11-16 本机RPC/启动数据离线接续：匹配op6893的GPIO/EINT/DTSI静态事实、
显式用户属性/SAR应答与混合runner、typed runtime builder已接；EINT错码修复。
cache审计确认A首次清零/后续保留，撤销无证据的AP预填要求。sanitizer/合成
回归和启用/恢复ARM64构建通过；未访问设备、未启动MD，蜂窝支持状态不变。
见[剩余实际启动条件](MODEM-BOOTSTRAP-PROFILE.md)。

2026-11-16 服务分发离线整合：accepted HS1 在 runtime 发布后才 arm 服务，
HS2 顺序连接 service/CCISM，补 controller 故障通知、后端预留及父生命周期门控。
内核 typed RPC 与 A 用户 RPC 分流，FS 枚举/递归删除补齐；没有本机 RPC 事实、
完整用户后端或启动 ready gate。实际 C sanitizer/合成 FS 回归及启用/恢复 ARM64
构建通过；未操作设备、未放行 MD，蜂窝支持状态不变。
见[端口分发与下一步](MODEM-PORT-DISPATCH.md)。

2026-11-16 Linux服务入口离线接续：新增有序session、独占privileged字符端点、
父关电/prepare门控及显式FS runner；补普通文件Move、Detail、CMPT失败应答。
实际endpoint/session/router/codec联合sanitizer及ARM64启用/恢复构建通过。
无活跃dispatcher/arm/MD释放caller，无真实RPC provider或服务就绪能力，本轮
未操作设备；见[入口与剩余启动条件](MODEM-SERVICE-ENDPOINT.md)。

2026-11-16 FS/RPC离线服务基础：完成FS五槽分片、RPC三槽codec、普通CCIF
回复TX、generation/token请求路由和私有工作副本原型。实际C sanitizer、
发送/STOP竞争及ARM64启用/恢复构建通过。没有live caller/daemon/硬件RPC
provider或服务就绪门控；部分FS语义与NVRAM cache策略仍阻塞首次MD释放。
本轮未操作设备，蜂窝状态不变；见[服务基础与边界](MODEM-SERVICES.md)。

2026-11-16 CCIF2/CCISM离线整合：新增唯一桥owner、普通system TX与异步
session队列/worker/timer，连接真实SCP client API；父prepare/off/shutdown加入
活跃桥阻断。CCIF2时钟保留vendor dummy语义的逻辑引用，不控制真实gate。
启用构建和实际C sanitizer通过；没有arm/start或CPU释放caller，没有刷机、
真实CCISM或蜂窝运行证据。下一步FS/RPC/NVRAM服务与能力表、真实MD停止原语，
再合并通信测试。见[CCISM当前边界](MODEM-CCISM.md)。

2026-11-16 CCISM离线接续：实现后置INIT/ACK/SHM_INIT/RBREADY/DONE core及
同代SCP client，含共享awake、真实APCCCI传输、状态/首故障通知、STOP保护。
实际C sanitizer及ARM64构建通过；CCIF2硬件owner、system端口和Linux事件
队列/定时器仍待接入，无启动caller或真机验收，本轮未操作设备。修正“必须在
MD放行前完成CCISM”的循环依赖，HS2后才执行该协议；见[说明](MODEM-CCISM.md)。

2026-11-16 runtime握手离线接续：普通CCIF owner内新增默认关闭的runtime
映射、64槽协商、v2.1 SRAM回复/BUSY门铃和有状态HS1/HS2 consumer，含超时、
端口错误和STOP同步。实际C sanitizer、ARM64启用构建及关闭配置检查通过。
没有新镜像或刷机、没有MD CPU release caller或真实HS1/HS2，不能计作蜂窝
支持；下一步CCIF2/CCISM、FS/RPC/NVRAM服务与能力表，再合并通信测试。
见[实现与验证边界](MODEM-RUNTIME-HANDSHAKE.md)。

2026-11-16 CCIF接收离线接续：同一owner已补IRQ/worker/STOP同步、正常环公平
扫描、SRAM HS1快照/ACK及控制头解码，实际C sanitizer与ARM64构建通过。
尚无consumer/start caller，未刷机、未启用真机CCIF IRQ或放行MD；当前
8ec93b17bbb5的MD1仍为OFF。下一组接runtime回复/有状态控制层与CCISM，
再做合并通信测试，见[接收层及限制](MODEM-CCIF-RX.md)。

2026-11-16最新CCIF实测：修正版8ec93b17bbb5完成LK布局→继承ON接管关电→
冷上电→32环/共享SRAM初始化和读回→stop→MD1关电。最终两路GIC IRQ均
masked/计数0，clocks/domain均0，USB/Wi-Fi、8核、RO存储与boot哈希通过。
设备保留该主线；SCP未重新启动、MD CPU未放行。未验收CCIF现场包或蜂窝，
接续IRQ/worker和控制通道，见[完整实测](MODEM-CCIF.md)。

2026-11-16 CCIF首轮实测：420ed6e96546完成LK/SMEM校验、继承ON接管关电、
冷上电及32环校验；SRAM初始化后的双视图footer相同，被原来的MD全零判据
误判EIO。已复现并修正，后续修正版stop/off通过；首轮故障保留电源/时钟，
IRQ未启用、MD CPU未放行。USB/Wi-Fi与8核正常，见[CCIF实测](MODEM-CCIF.md)。

2026-11-16 CCIF离线接续：同一MD owner新增普通CCIF窗口/屏蔽IRQ/联合WC环映射、
6297正常/异常环CPU收发后端、CCIF0复位与SRAM初始化/读回及关电前stop。
定向sanitizer、A/V表核对和启用内核构建通过；尚未上机，IRQ不启用、MD CPU
不放行，不能算作CCIF通信或基带支持。下一次合并MD接管/电源/CCIF测试，见
[CCIF状态及限制](MODEM-CCIF.md)。

2026-11-16平台层接续：统一MD owner保留SMEM布局、四路供电基线/普通CCIF
时钟，增加显式genpd接管与冷循环。当前e8509e81dbc3六个AP寄存器只读确认
LK留下MD1 ON，故补CHECK_DONE/继承ON关断流程及unused OFF veto；新增
功能已通过sanitizer/ARM64构建，尚未刷入、切换MD电源或放行CPU。设备
继续运行原镜像。下轮合并普通CCIF功能测试，见[平台层](MODEM-PLATFORM.md)。

2026-11-16离线接续：新增6297 LK共享内存子区解析（runtime/CCISM/NVRAM
cache），保留bank跨度并计算间隙，解释历史cached 0x80000差值。定向
sanitizer、vendor ABI及启用内核构建通过；未新增实机验收，设备状态沿用
下条记录。下一次与MD平台/CCIF功能组一起测试，见[SMEM](MODEM-SMEM.md)。

2026-11-16最新接续：`e8509e81dbc3` 实测 SCP 常驻约49秒，Linux RX消费
READY1/logger/其他共3事件，无积压或异常中断；AP awake三次配对成功，
MD-invalid一次传输完成，但没有APCCCI应用层状态回复。显式STOP后双核
raw=0xff00、generation0、GIC五路masked。USB/Wi-Fi SSH、LVTS和tmpfs匹配
GPU模块正常。设备保留主线，SCP已停止、MD未启动；下一步MD电源/复位与
CCIF/CCISM。见[常驻接入实测](MODEM-SCP-RUNTIME.md)。

2026-11-16历史接续：`949a860a1a85` 已完成 SCP 初始启动→Linux IRQ/worker/
队列→READY1（channel22）→STOP/双核SET 的完整短时实验。IRQ2次、worker3次、
无unexpected，结束 GIC 五路屏蔽、generation0、两核raw=0xff00。修复了接收层
lazy-disable 导致软件停用但 GIC 未屏蔽的问题。USB/Wi-Fi SSH、LVTS正常；
匹配GPU模块从tmpfs加载并probe成功。SCP未常驻、基带未启动；下一步接持续
消费、AP awake/CCCI。见[集成启动记录](MODEM-SCP-INITIAL-BOOT.md)。以下
各版结论按历史记录理解。

2026-11-16接续：当前248c64a7dd23上已用一次2秒初始释放实验观测到SCP PC
变化及READY1（channel22、size0x180000），结束重新SET双核。确认SET读回
bit0=0为assert，上一轮EIO判据写反；源码已修正，运行镜像仍旧版。
正式接收/READY状态机、logger客户端及基带尚未启用；旧mailbox pending保留。
见[首次运行证据](MODEM-SCP-INITIAL-KICK.md)，以下初次SET结论为历史判读。

2026-11-16当前设备运行`248c64a7dd23`，本轮实际执行双核SCP SET，但两核
读回0、返回EIO，复位效果未确认，SCP/基带尚未启动。USB/Wi-Fi SSH正常，
LVTS五个温度接口可读；已构建并从tmpfs加载匹配的GPU模块，Panfrost probe
成功。保留近期MFGPLL、GPU OPP/供电耦合和LVTS/cooling更新，本轮未验收
DVFS或图形压力测试；cache内旧GPU模块仍需后续更新，重启不会保留tmpfs模块。
详见 [SCP SET实测及接续重点](MODEM-SCP-RESET-ASSERT.md)。以下基线编号及
各行实验限制按其历史记录理解，不能当作本轮镜像已完成全部重测。

更新基线：attempt106（Wi-Fi、Bluetooth 和 BlueZ 扫描实测可用，见
[CONNECTIVITY-STATUS](CONNECTIVITY-STATUS.md)）。当前实机镜像是 `24c0e33d5597`，内核
`7.3.0-op6893-d1-24c0e33d5597+`；外置 Debian 镜像 `debian-1ed1b45c80c2`。
attempt97 及之前的寄存器级 CONN 行为保留作历史记录。
本文描述这台设备的主线实测结果，
不把 ACK 的功能、源码中存在的驱动或 DT 节点视为主线已经支持。

各行限制对应所引实验，后续集成进展见较新的行。
“实测”仅覆盖表中列出的行为；“部分”表示可用但仍依赖 LK 状态、临时配置
或缺少关键功能；“未启用”不表示硬件损坏或永远无法支持。

2026-11-14 基带接续实测镜像为 `fe077e30d191`：只启用 LK metadata 检查，
USB/Wi-Fi SSH 和外置 rootfs 正常；MD/SCP 尚未启动。详见 [R3](MODEM-R3.md)。
上文 attempt106 镜像编号是历史连接性基线，后续各条按所引记录判断。

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
| Wi-Fi（厂商 gen4m） | 实测可用 | 开机自动关联开放网络、DHCP、Wi-Fi SSH、NTP、DNS、HTTPS；出厂 MAC 由 proinfo 经 nvmem 读取 | 只测了无密码网络；WPA、省电、漫游未测；使用厂商栈，不是上游驱动 | [CONNECTIVITY](CONNECTIVITY-STATUS.md)、[100–106](evidence/attempt-100-106.md) |
| Bluetooth（厂商 btif/mt66xx + BlueZ） | 实测可用 | 开机 hci0、标准 HCI 初始化；LE 扫描和 BR/EDR inquiry 能发现设备；与手机配对、RFCOMM、OBEX 推送、PAN 网络共享成功（attempt107–109） | 空中地址已是出厂地址（attempt108）；音频未测；`0x0c77/0x0c78` 在本地完成 | [CONNECTIVITY](CONNECTIVITY-STATUS.md)、[100–106](evidence/attempt-100-106.md) |
| 屏幕早期控制台（simplefb + fbkick） | 部分，实测 | 沿用 LK 已点亮的命令模式 AMOLED（AMS643YE01）与显示管线；每 33 ms 触发一帧，simplefb（a8r8g8b8）上的 fbcon 从 0.05 s 起显示内核日志；色条颜色和位置正确；`/sys/class/backlight/panel` 调亮度（DCS 0x51，0–2047）和熄屏（`bl_power`，熄屏时暂停送帧）实测 | 完全依赖 LK 状态和 clk_ignore_unused；没有真正的显示驱动或 DSC/面板初始化；不用 HBM；刷新方案参考 Mu-Silicium | [110–112](evidence/attempt-110-111.md) |
| 触摸屏（FT3518） | 实测 | i2c0 @0x38，主线 `edt-ft5x06`；供电 MT6360 LDO2（3.0 V，LK 不开，由主线 mt6360-regulator 打开）；开机自动 probe，滑动/点按坐标在 1080×2400 范围内、无越界；中断改为电平触发，FT3518 不报抬起时按 120 ms 报告不变补发抬起，buffyboard 屏幕键盘点击正常（attempt113–114） | I2C 时钟门控沿用 LK（引脚复用已由 DT 配置）；双指滑动偶见一次 24 ms 断触；i2c0 400 kHz（错位已修，见 attempt115）；长按与三指已测；未做手势/省电/唤醒 | [113](evidence/attempt-113.md)、[114](evidence/attempt-114.md)、[115](evidence/attempt-115.md) |
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
| MT6360 ADC / 充电 / 电池 power_supply | 部分，实测 | MT6360 ADC 可读 VBUS≈4.83 V、IBUS≈430 mA、VBAT≈3.91 V、结温；`mt6360-chg` 报在线、充电状态、USB 类型（SDP）；`fuel-gauge` 报电压，状态跟随充电器（Charging），并按厂商 25 °C OCV 表估算 CAPACITY（attempt116–118） | 充电参数沿用 LK（500 mA/4.38 V），未调；无库仑计，百分比只是电压估算（充电时偏高约 10 个百分点）；IBAT 只反映充电电流；VOOC/电荷泵未处理 | [116](evidence/attempt-116.md)、[117](evidence/attempt-117.md)、[118](evidence/attempt-118.md) |
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
| 显示（完整驱动）/ 亮度 | 未启用 | 早期控制台见上方 simplefb 行。完整驱动需要 MMSYS/SMI/IOMMU/CMDQ/DSC；6.6 port 的 mediatek_v2 已点亮该面板，可作参考；不依赖 GPU |
| 触摸屏 | 未启用 | 需核对芯片、总线、供电和复位；GPIO20 是触摸复位线索，不应当作音量加 |
| GPU 加速（panfrost + Mesa kmsro） | 部分，实测 | 开机自动加载 panfrost 和 gpu-sched；probe 成功（13.4 s），minor 1；kmscube 肉眼测试无毛刺；kmsflat 压测 3800 帧全部通过 CPU cache sync（attempt123–124） | 禁用了 runtime suspend（GPU_PM_NO_RT_SUSPEND），GPU 一直上电；根因未查；未做 DVFS、长期压测、温度监控；模块从 /cache/mainline/modules 加载，每次换内核需重推 .ko | [123](evidence/attempt-123.md)、[124](evidence/attempt-124.md) |
| 音频 / 耳机检测 | 未启用 | codec、AFE、时钟/供电和路由待实现；accdet 尚未接入 |
| 摄像头 / ISP | 未启用 | 传感器型号、总线、供电、时钟、ISP 管线待调查 |
| RTC / 持久时间 | 未启用 | RTC_CLASS 关闭；不能用启动日志时间作为准确实时时钟 |
| SCP | 短时常驻/awake实测 | READY1、持续CPU消费、awake三次配对、一次MD-invalid传输；STOP双核SET/GIC五路屏蔽 | 无APCCCI状态回复；未验证长期运行、core1独立运行或完整恢复 | [常驻接入](MODEM-SCP-RUNTIME.md) |
| MD平台与普通CCIF初始化 | 部分，实测 | LK接管、冷上电/关电、唯一一次`(6,0)`放行、HS1接受、runtime发布、真实CCIF RX/TX（964次发送、`tx_error=0`）、停止后GIC屏蔽 | HS2未到达；无热重启、无CCISM后置协议、无注册/数据面；MD异常为自身`MPU_NOT_ALLOW` | [CCIF](MODEM-CCIF.md)、[放行](MODEM-BOOT-RELEASE.md) |
| modem / 蜂窝 / GNSS | 部分支持 | HS2、CCISM、SIM、LTE 注册、PDP 和 `ccmnidp0` 的 IPv4/IPv6 ICMP 与 UDP DNS 已上机验证 | 用户态双栈会话已验证启停、有限重连和独立策略路由；长时间稳定性、通话和 GNSS 未验收 | [实测](MODEM-BOOT-RELEASE.md) |
| NFC / 指纹 / 振动 / IMU 等传感器 | 未验证、未建立支持 | 需逐项识别本机硬件及资源，不能借用同品牌另一机型结论 |
| UFS 写入、USB host、运行时自动挂起 | 未验证 | 目前测试策略不覆盖这些行为 |
| pstore 故障恢复链路 | 历史不可靠，非保证能力 | 用户指出 fastboot oem peek 可读保留内存；不能把无 pstore 当作内核未执行的证明 |

## 当前用户空间与操作约束

- Debian13 arm64 SquashFS 位于 cache 的 `mainline/debian.squashfs`（固定文件名，initramfs
  只认这个路径），外层 ext4 以 `ro,norecovery` 挂载；根目录使用 tmpfs OverlayFS，运行时修改易失。
  主线下不写 UFS，所以更新镜像要在 Android 下进行：先推到临时文件，校验哈希后再改名，
  旧镜像保留（当前回滚镜像为 `debian-11c0a118e84c.squashfs`）。
- GPU 模块（`gpu-sched.ko` / `panfrost.ko`）放在 `/cache/mainline/modules/`，由 `op6893-ssh-start`
  在后台 insmod。每次换内核后需要重推与新内核 vermagic 匹配的 `.ko` 文件，否则加载失败
  （错误写入 `/run/modules.log`，但不影响 SSH）。
- 开机由 `op6893-ssh-start` 依次启动 USB SSH、GPU 模块加载、Wi-Fi（`op6893-wifi-up`），
  以及 dbus、bluetoothd 和 buffyboard（后三者在后台运行）。
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

## Attempt98–106：Wi-Fi 与 Bluetooth

改用厂商连接栈之后，Wi-Fi 和 Bluetooth 都已实测可用：BLE 扫描的根因是 BT 驱动
提前清除了 `HCI_SETUP`；出厂地址由 proinfo 经 nvmem 读取；BlueZ 已装进 rootfs。
见 [CONNECTIVITY-STATUS](CONNECTIVITY-STATUS.md)。

## Attempt119：GPU 只读探测

GPU 是 Mali-G77 MC9 r0p1（`0x9080`）。LK 交接时 MFG0–6 全部断电，MFGPLL 停在
350 MHz。SPMI 与 MT6315 已接入，读到 vgpu 0.75 V 且处于开启状态。见
[119](evidence/attempt-119.md)。

## Attempt120：GPU 上电

修正主线 MT6893 MFG1 总线保护掩码（bit17|bit19，原为 17–19）之后，MFG0–6 能够
上电和下电，读到 GPU_ID `0x90800011` 和 SHADER_PRESENT `0x660067`。频率沿用 LK
的 350 MHz。见 [120](evidence/attempt-120.md)。

## Attempt121：panfrost

panfrost（模块，手动加载）在 G77 r0p1 上 probe 成功，有 `renderD128`；
运行时电源管理会关闭 GPU 电源域，GET_PARAM 和 CREATE_BO 均可用。还没有 Mesa，
GPU 尚未执行过作业。见 [121](evidence/attempt-121.md)。

## Attempt122：Mesa 渲染

打了 G77 补丁的 Mesa 26.2.6（panfrost、不依赖 LLVM）识别为 “Mali-G77 MC9 (Panfrost)”，
GLES 3.1。离屏三角形渲染像素正确，2000 帧无 GPU fault。panvk 不支持 v9。
见 [122](evidence/attempt-122.md)。

## Attempt123：simpledrm 与 kmscube

帧缓冲改由 simpledrm 驱动，kmscube 通过 kmsro（simpledrm dumb buffer + panfrost）显示。
修了两个问题：runtime suspend 之后 GPU 无法复位（暂时禁止 MT6893 的 GPU runtime
suspend，根因未明）；导出的 dumb buffer 与非 coherent 的 GPU 之间没有 cache 同步，
造成 16 像素长的闪烁短线（在 DRM prime 与 framebuffer helper 中补上同步）。
全屏纯色翻页测试 3800 帧无错误像素。见 [123](evidence/attempt-123.md)。

## 2026-11-14：基带方案分析，尚未启用

完成本机 Android 4.19、同板 6.6 移植与 qqcandy MT6895 的内核侧对比。
计划以本机硬件定义和 6.6 功能栈为底本，先建立 LK 交接/布局解析、平台资源、
SCP/CCISM、CCIF/FSM 和端口框架，再接 DPMAIF v2。当前没有主线基带运行证据；
其他树的 READY 或节点注册不计作本机支持。详见 [MODEM-PLAN](MODEM-PLAN.md)。
图形后续工作见 [GRAPHICS-TODO](GRAPHICS-TODO.md)。

基带 M0 随后完成交接和被动解析框架、合成输入/真实合并器测试及 ARM64 内核/
模块构建。Android 两份 header 只读核对通过；未重启刷写，检查节点默认关闭，
没有主线基带实测支持。见 [MODEM-M0](MODEM-M0.md)。

随后完成 [M1 离线资源审计](MODEM-RESOURCES.md)，校正 SCP RV 分支、
SID3 三路加 VPU/VRFDIG、六加二 CCIF 时钟及 AP MTCMOS/ATF 边界。
仅增加文档和离线审计工具，没有新增设备操作或基带支持验收。

后续完成 [R1/R2 第一批资源框架](MODEM-R1-R2.md)：SID3/VPU disabled 描述、
四个普通 CCIF gate、独立 supply/clock 引用检查模块。开关默认关闭，主机
测试和 ARM64 编译通过；没有设备操作，也不新增基带可用性结论。


## 2026-11-14：M0 主线实机验收与 MD1 电源首版

`fe077e30d191` 的本次 LK header 和真实 tag/layout 检查成功：version 3、
20 tags、2664 bytes、CCB 存在。USB ECM SSH、独立 Wi-Fi SSH、外网 ping、
cache ext4 + SquashFS/Overlay rootfs 回归通过。检查器没有启动 modem/SCP。

MD1 AP MTCMOS 序列与 genpd 接入已完成主机错误注入/超时测试和 ARM64 编译；
没有板级 MD 域节点，未刷入这批电源代码，不能记作基带上下电实测。SID3
shutdown、电压生命周期、SCP RV/CCISM 和控制栈仍待完成。见 [R3](MODEM-R3.md)、
[新分析接续及冲突](MODEM-PROTOCOL.md)。


## 2026-11-14：基带供电与普通 CCIF 引用实机验收

`7576d31c76a4` 显式启用 SID3/VPU 和引用检查，四路 regulator 与四个
clock 均绑定成功；两次启动均通过，未 enable/调压或启动 MD/SCP。USB ECM
SSH、独立 Wi-Fi SSH、外网 ping、只读 cache ext4 与 SquashFS/Overlay rootfs
回归通过。R3 代码已在镜像内，但没有 MD1 域实例，未实测其电源序列。

正常重启请求后返回同一镜像；pstore 未保留完整退出尾部，不能单独证明
SID3 shutdown 全部步骤已完成。sysfs 的 SID3 电压为 RG 指令值，不是 DA
实际值；启动电压恢复仍待实现。详见 [供电生命周期](MODEM-RAILS.md)。


## 2026-11-15：SCP mailbox 布局与 CCISM 协议基础

默认关闭的纯 helper 已实现并通过主机测试和 ARM64 编译：完整 mailbox
表的 64 位布局、APCCCI 通道定位、消息编解码和 u32 SHM 地址跨度校验。
本机 APCCCI RX 为 mailbox 1 / word offset 28 / IRQ bit 14，不能只保留
APCCCI 条目后重新分配布局。A/V 两份实际布局函数交叉验证通过。

本轮没有操作设备或打包新镜像；没有 SCP transport、固件加载、真实 READY
或 CCISM 状态机，仍不能启动主线基带。见 [SCP 记录](MODEM-SCP.md)。


## 2026-11-15：SCP TCM 元数据与恢复映射校验

新增默认关闭的纯 header 解码/跨度校验，核对 A/V 72-byte ABI、严格版本、
可信窗口与 `roundup(bytes,1024)*4` 边界；主机测试与 ARM64 构建通过。
没有读取设备 TCM、映射/加载固件、复位 SCP 或新增硬件支持验收。
用户已刷回 Android 供其他分析工作，本轮不连接、重启或刷写设备。
见 [SCP 内存契约](MODEM-SCP-MEMORY.md)。

2026-11-15 后续离线完成共享 AP awake 后端：首末引用握手、嵌套引用、
有界等待、W1 清理与故障锁定，默认关闭且没有 provider/caller。真实 C 的
失败注入、ASan/UBSan、ARM64 启用/关闭构建与 strict checkpatch 通过。
已准备仅采集软件 READY 和白名单 DT 属性的 Android 脚本，未上传或执行；
没有新增硬件支持验收，也未访问设备。下一步需要实机核对启动/固件/内存，
见 [awake 与上机边界](MODEM-SCP-AWAKE.md)。

2026-11-15 用户允许后完成当前 6.6 的被动检查：两次 SCP 软件 READY，
24 项存在 DT 属性与保存 ACK 一致，另 6 项同为缺失。动态 share 仍无 reg，
未获取实际分配或 TCM header。没有上传文件、awake 操作、重启或刷写；
设备保持 6.6，尚不新增主线 SCP 支持验收。
见 [6.6 被动观测](evidence/modem-scp-6.6-observation.json)。


## 2026-11-15：6.6 SCP 缓存与动态保留区实测

用户允许上机后，通过匹配 build ID 的 6.6 驱动缓存观测发现 header 标称
68 字节，原 72-only helper 正确拒绝。新增严格 68/72-byte 支持并复测成功；
动态 share 为本次分配的 0x8d000000/0x320000，与驱动缓存一致。loader、
firmware、DRAM 和完整恢复 mapping 位于静态 SCP 保留区，backup 地址符合
双核公式；regdump 不在两个已确认窗口内，未映射。主机 sanitizer、ACK 模块
和主线 ARM64 编译回归见证据。模块和上传文件已清理，设备保持 6.6；
没有 awake/IPI、TCM 访问、重启或刷写，尚未增加主线 SCP/基带硬件验收。
见 [缓存与内存观测](MODEM-SCP-OBSERVATION.md)。


## 2026-11-15：主线 SCP AP 侧前提观测

c55ce7327907 已刷 boot 并启动，AP TOPCK SCP selector=0（26M）、gate=0，
连续样本稳定；主线本次动态 share 为 0x8d000000/0x320000，与 ACK 相同但
没有硬编码地址。USB/Wi-Fi SSH、8 核、cache ext4/SquashFS/overlay、UFS
只读回归正常。默认关闭的新 observer 只读 AP TOPCK 和内核保留区记账，
没有 SCP/TCM、IRQ/awake/IPI/reset，READY 仍未知。设备保持主线；下一步
限定 core0 状态读回及精确 header 观测。见 [实测记录](MODEM-SCP-PREREQUISITES.md)。


2026-11-15 SCP core0 限定读回：当前设备运行 `0a53a32dd3b3`，仅显式读取
CLR/SET bit0 与 STATUS gated/halt，各两次；六次调用均稳定且解释位全0。
USB/Wi-Fi SSH、8 核、UFS RO、cache/rootfs 回归通过。尚未访问 TCM、建立
READY 或启动 SCP/MD。详见 [core0 结果](MODEM-SCP-CORE0.md)。


2026-11-15 SCP TCM header：当前主线 `3ccec64b58d4`，精确 68-byte
header 六次显式读取一致；loader/firmware/DRAM/完整 mapping 的静态保留区
包含、payload 不重叠与 backup 公式检查通过。regdump 位于 firmware/share
外，未映射。USB/Wi-Fi SSH、8 核、UFS RO/cache/rootfs 回归通过。未建立
READY、启动 SCP/MD 或发送 awake。见 [TCM 结果](MODEM-SCP-TCM.md)。


2026-11-15 SCP RX 离线准备：默认关闭的 copy/board-completion/ACK/deliver
后端及 READY0 payload 校验已完成 sanitizer 与 ARM64 构建。尚无硬件
MMIO/IRQ caller，不记作 mailbox 外设已支持。设备保持 `3ccec64b58d4`。
下一步先做无 ACK/无 IRQ 的 pending 预检，见 [RX 接续](MODEM-SCP-RX.md)。


2026-11-15 SCP mailbox pending：当前主线 `b4456f5c54a5`，六次读取五组
pending/unknown 均0，两轮及前后 core0/mux 稳定；GIC specifiers 通过解析。
未申请 IRQ、清位、读 mailbox payload 或建立 READY。USB/Wi-Fi、8 核、
存储/rootfs 回归通过，见 [pending 实测](MODEM-SCP-PENDING.md)。后续先补
clock/shared-register owner，再接可控 IRQ 与 reset generation。


2026-11-15 SCP bootstrap 时钟：当前主线 `6d783d7288f4`，已有 TOPCK
provider 内的受限26M输出已正式持有，consumer unbind/rebind 实测 CCF
引用2→1→2，provider常驻引用保留，源/gate与既有core0/header/pending稳定。
USB/Wi-Fi、8核、存储/rootfs和boot回读通过。默认构建仍关闭实验；SPM资源
投票、共享cfg/IRQ owner和真实READY仍未完成，未启动SCP/MD。
详见 [bootstrap 时钟与资源边界](MODEM-SCP-BOOTSTRAP.md)。


2026-11-15 SCP SPM 26M资源：当前主线 `5393b5915579`，先验证只读 ATF
查询，再显式请求一次26M；SCP用户从缺失变为有效user1，资源mask=0x02，
多次USB/Wi-Fi读回 pin_verified=1、fault=0。CCF引用3/3、26M保持，既有
core0/header/pending、8核、UFS RO/cache/rootfs与boot回读通过。启用/默认
构建、schema和sanitizer通过，实验默认关闭。未启动SCP/MD、安装IRQ、
发awake或建立READY；下一步共享cfg/completion唯一owner，再接IRQ与
reset generation。见 [SPM资源实测](MODEM-SCP-RESOURCE.md)。


2026-11-15 SCP cfg 资源归属：当前主线 `80e79074de00`，已有SPM资源
owner通过资源管理器占有完整 `0x10724000/0x1000` 窗口，cfg状态
reserved=1、completion_enabled=0；不读写cfg寄存器。26M pin保持有效，
USB/Wi-Fi、8核、UFS RO/cache/rootfs、原观测和boot回读通过；启用/默认
构建、schema及sanitizer通过。未安装IRQ或建立READY，SCP/MD未启动。
下一步唯一IRQ/worker的预算与generation框架、completion写排序审计。
详见 [cfg 实现与实测](MODEM-SCP-CFG.md)。


2026-11-15 SCP接收排空离线后端：新增默认关闭的五邮箱有界drain与
STOP两阶段/generation校验，sanitizer与启用/默认ARM64构建通过。
尚无真实IRQ/worker/MMIO caller、目的队列或READY状态转移；不计作新增
硬件支持。本轮未刷写/重启，设备保持 `80e79074de00`，被动查询26M pin
有效、cfg预留且completion关闭。见 [drain边界与接续](MODEM-SCP-DRAIN.md)。


2026-11-15 SCP RX目的队列离线准备：默认关闭CPU FIFO覆盖17个RX pin，
整批容量不足时在硬件completion/ACK前拒绝，故障时擦除CPU队列并失效
全部RX。实际RX/drain/queue联动sanitizer、启用/默认ARM64构建通过。
未接真实IRQ/worker/MMIO或READY，不增加硬件验收；本轮未刷写/重启，
设备保持 `80e79074de00`。见 [队列边界](MODEM-SCP-QUEUE.md)。


2026-11-15 SCP mailbox IRQ初始归属：当前主线 `49092bac2836`，唯一cfg/SPM
owner以NO_AUTOEN申请五个IRQ，GIC hwirq 468–472均masked，所有CPU中断
计数0，USB/Wi-Fi重复读取unexpected/work_runs均0。26M pin读回mask=0x02、
pin_verified=1，CCF引用3/3；cfg无寄存器读写、completion关闭，原观测、
8核、只读存储/rootfs和boot回读通过。启用/默认构建、schema、实际C
sanitizer与strict checkpatch通过。尚未连接正常RX/worker、启用IRQ、建立
reset generation或READY，SCP/MD未启动，不计作基带可用。接续MMIO/
completion排序与可启用IRQ的锁/深度平衡，再闭合受控reset和本代READY。
详见 [IRQ归属及实测](MODEM-SCP-IRQ.md)。


2026-11-15 SCP RX MMIO离线后端：默认关闭，准备六个完整4 KiB页的
non-posted映射和实际readl/writel操作，completion/ACK后加屏障，避免未证实
的cfg读回。实际MMIO/queue/RX/drain模型sanitizer、启用/默认ARM64构建、
屏障反汇编及strict checkpatch通过。尚无platform caller或DT资源接线，
未进行新映射/寄存器操作，不增加硬件验收；本轮未刷写/重启，设备仍为
`49092bac2836`。接续唯一owner映射替换、正常IRQ/work、受控reset和READY。
详见 [MMIO后端与限制](MODEM-SCP-MMIO.md)。


2026-11-15 SCP MMIO映射接入准备：新增默认关闭的唯一owner六页non-posted
预留路径，替换旧cfg映射并在Kconfig排除旧pending observer；不调用prepare
或寄存器操作，五IRQ仍NO_AUTOEN。owner双路径及后端sanitizer、启用/默认
构建、定向schema/DTB与strict checkpatch通过。测试镜像`fba1be648ead`已就绪，
尚待上机，不增加硬件支持验收；设备仍运行`49092bac2836`。
详见 [映射接入与测试边界](MODEM-SCP-MMIO-OWNER.md)。


2026-11-15 SCP MMIO映射实测：当前主线 `fba1be648ead`，六个完整页均由
唯一resource owner占有，USB/Wi-Fi重复查询寄存器读写0、prepared=0、
generation=0；初始fault=1表示未prepared的主动封闭。五IRQ保持masked，
所有CPU中断计数和异常计数0。旧pending observer编译关闭，属性不存在，
不读取/清理继承消息。26M pin、CCF引用3/3、原core0/header/mux、8核、只读
存储/rootfs及boot回读通过。未进行真实RX/completion/ACK、IRQ使能或SCP/MD
启动，不计作基带可用；下一步接真实prerequisite及正常IRQ/work/STOP。
详见 [实机映射验收](MODEM-SCP-MMIO-OWNER.md)。


2026-11-15 SCP Linux IRQ/work 接收层离线准备：默认关闭 adapter 组合现有
MMIO/queue/drain，完成 IRQ 深度平衡、排队代号及 STOP 同步屏障；新增只读
资源检查 helper。实际 C sanitizer/既有回归、启用/默认 ARM64 构建和 strict
checkpatch 通过。尚未替换平台 IRQ owner、启用 IRQ 或执行真实接收；本轮
不刷写/重启，USB只读复查设备仍为 `fba1be648ead`，六页零寄存器操作、
五IRQ masked、26M pin有效。下一步先接 dormant constructor/prerequisite，
再完成真实 reset/旧消息隔离；不计作 SCP/基带可用。
见 [接收 adapter 和验证范围](MODEM-SCP-RECEIVE.md)。


2026-11-15 SCP receive 静默接入实测：当前主线 `4ed57fd98c40`，唯一资源
owner 以新 adapter 互斥替换旧 IRQ reservation，五个 `op6893-scp-rx` action
均 masked、所有CPU中断及worker计数0；generation/queued/events=0，六页
MMIO读写0且未prepare。probe无SMC请求，一次显式26M pin后mask=0x02、
pin_verified=1，CCF引用3/3。USB/Wi-Fi各三轮、8核、UFS/cache/rootfs只读
状态及boot回读通过。新增owner prerequisite wrapper已有模型验证，实际
reset generation仍0，无start caller；不启动SCP/MD、不计作基带可用。
下一步推进真实reset/旧消息隔离与固件/客户端前提，再考虑启用接收。
见 [唯一owner接入与实机验收](MODEM-SCP-RECEIVE-OWNER.md)。


2026-11-15 SCP reset/恢复布局离线准备：核对A/V/Q初始化释放与恢复worker的
不同路径、双核TCM/DRAM恢复公式及独立mailbox隔离缺口。编译确认header
结构A/V/Q为72/72/60字节，本机先前实测68，不照搬Q尾部。新增默认关闭纯
CPU restore planner，检查完整源/目标范围、重叠、精确header长度与backup
公式；ASan/UBSan、源码审计、启用/默认ARM64构建及strict checkpatch通过。
无device caller/映射/复制/reset/IRQ操作，本轮不连接或刷写设备，不增加
基带验收；上次实机验收为 `4ed57fd98c40`。下一步统一core0/core1/TCM资源
归属，再规划受限停止观测；真实旧消息隔离和备份来源尚需闭合。
见 [reset与恢复契约](MODEM-SCP-RESET-RESTORE.md)。


2026-11-15 SCP core0/core1/TCM 统一映射实测：新增默认关闭选项，与旧
core0/TCM/pending reader互斥，在现有唯一owner取得三块完整non-posted窗口。
主线 `db337399ee04` 的 /proc/iomem 确认cfg/五mailbox/core0/core1/TCM共九块
均归同一owner；读写仍0，五IRQ masked且全部CPU计数0，generation0。
一次26M pin、USB/Wi-Fi各三轮、8核/RO存储与boot回读通过；sanitizer、
Kconfig互斥、启用/默认ARM64构建、schema与strict checkpatch通过。
本轮只验收映射，不证明core1/TCM读取、复位或停止语义；未启动SCP/MD。
下一步将受限core/header观测迁到同一owner，审查core1只读allowlist，
再闭合双核停止和旧消息隔离。见 [统一资源归属](MODEM-SCP-CORE-TCM-OWNER.md)。


2026-11-15 SCP 统一 owner 双核/header 只读实测：主线 `cebf84a7d29e`，
新默认关闭选项在原九块独占映射内、同一mutex下读取。未pin两入口EAGAIN且
零读；pin后core0/core1仅0/4/0x70受限位均稳定0，TCM header68字节，CPU恢复
布局geometry检查通过。USB/Wi-Fi各三轮，core/TCM最终252/252读数与预期一致；
写入、cfg/mailbox读写、IRQ/worker事件仍0，CCF/八核/RO存储和boot回读通过。
模型/构建/schema/checkpatch通过。设备保留该主线；不把读回解释为reset/停止
或固件有效，不启动SCP/MD。下一步双核停止和旧消息隔离契约，见
[统一owner只读观测](MODEM-SCP-OWNER-OBSERVE.md)。
