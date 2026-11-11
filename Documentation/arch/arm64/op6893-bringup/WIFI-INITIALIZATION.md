# op6893 Wi-Fi 初始化：逆向结果复核与移植约定

> 2026-11-10：主线 Wi-Fi 已经改用厂商 gen4m 栈打通，见
> [CONNECTIVITY-STATUS](CONNECTIVITY-STATUS.md)。下文是寄存器级调查阶段的历史记录。

当前进展（attempt86）：四个efuse结果字各读取两次且一致，原始值临时保存并
清零，公开诊断脱敏，FM/模拟/mailbox/全部外层清理成功。设备运行
`6033b3cb705f`，CONN关闭；尚未完成私有SYSRAM交付、trim/校准、固件或Wi-Fi。
证据见 [attempt86](evidence/attempt-86.md)；以下早期记录保留历史语境。


2026-11-03，attempt56。分析输入来自
`/home/hzyry2046/src/conninfra-rev/REPORT.md`，原件保留不动。
报告及输入哈希见 [attempt56](evidence/attempt-56.md)。本文为经过复核的集成结论，
原报告里的协议补零、前缀 NUL 和 BT UART 下载路径结论已被下述证据修正。

attempt56 采集时设备运行用户恢复的 ACK `6.6.30-4k-g6974e26f087e #66`；boot 分区哈希与
已选恢复镜像 `455ed6ce…b4722c88` 一致。本轮没有刷写、重启、NVRAM 投递或
主动触发校准。最近通过回归的主线仍是 attempt54 `d873de3b8963`。

## NVRAM 协议：可以脱离 Android 实现

逆向报告提供了直接文件读取、尾部校验和、可选 MAC 覆盖和回调注册的证据。
本轮从 ACK 只读获取 WIFI 到主机内存，验证以下元数据，不保存原文：

| 项目 | 本机结果 |
|---|---|
| nvdata 文件 | `/mnt/vendor/nvdata/APCFG/APRDEB/WIFI` |
| 文件长度 | 6146 字节 |
| SHA256 | `0e221a8df227b32aafa2876317517715a6f55b7b02d6b5d74ee565792a3fe83d` |
| 记录 | 前 6144 字节，末字节为 OPLUS 版本 `0x02` |
| 磁盘尾部 | `0xAA` + 1 字节校验和；验证通过 |
| 可选文件 | `/data/vendor/macwifi`、`/data/vendor/nvramwifi` 本轮均不存在 |

校验和只覆盖记录：偶数下标字节相加，奇数下标字节异或，最后取低 8 位。
校验在 MAC 覆盖之前执行。没有默认校准替换、原文件写回或校验重算。

精确交付帧为：

```
[12 ASCII bytes: WR-BUF:NVRAM][6144 bytes: file[0:6144]]
```

**前缀不含 NUL，记录后没有补零。** write count=6156，handler 从偏移12取6144字节。
若显式指定有效 macwifi，只有记录偏移4..9被覆盖；本机现状不覆盖。
6144字节整体保留，不能截成 `WIFI_CFG_PARAM_STRUCT` 的静态2048字节大小。

独立核对 `wlan_assistant`（SHA256 `7ca456c5…a84c1d`）反汇编：
0x18e0 加12分配，0x1920/0x192c 拷贝12字节字符串，0x1938 指定负载偏移12，
0x193c/0x1948 读取 S-2 字节，0x1980/0x1984 写出 S-2+12 字节。
字符串 `WR-BUF:NVRAM` 自身已有12字符；原报告将它误数为11字符加NUL。
完整读取成功时，清零的分配空间恰好被前缀与记录填满，没有额外尾部空间。
ACK `WIFI_write()` 的 `count-12`/`buf+=12` 与此完全对应。

## 交付即可能触发上电，不能用作被动探测

原报告 ACK 日志中的 `WIFI_write` 入口25.385129与 WLAN callback 注册
25.385172相差43微秒；这是两条日志时间差，**不是 write 返回到校准的延迟**。
随后出现联合预校准调度、BT 成功、WLAN 成功及 EMI 结果备份日志。
本轮未重做这次校准；该证据来自逆向任务的只读日志采集。

- handler 就绪与字符设备出现是两件事；未注册时写入可在内核阻塞约200秒。
- NVRAM handler 会注册 WLAN callbacks，最后一个参与者可能自动触发校准。
- 初版保留真实 BT 校准参与；PRE_CAL_DONE、g_fgEverCal 与成功状态分别验证。
- 不假定插入模块或用户空间超时能保证无硬件动作/取消内核工作。
- 不复刻 Android 属性服务；使用明确状态和一次性交付流程，拒绝短写。
  未来发送器需根据设备 ABI 处理 EINTR，不能对部分写入盲目续写或自动重投。

## BT 固件：采用本机 BTIF 的48字节 EMI 头

原报告 B 的 UART/766x `PATCH_INFO_SIZE=30` 路径不适用于本机 BTIF。
实际源码调用链为 `btmtk_load_rom_patch_66xx()` -> `bgfsys_bt_patch_dl()` ->
`btif/btmtk_mt66xx.c::__download_patch_to_emi()`。保存的 ACK 目标文件里可见
减去0x30、负载指针加0x30以及 `conninfra_get_phy_addr` / `memcpy_toio` 调用。
这是保存的构建对象证据，本轮没有成功定位并匹配设备上已加载模块的原始文件。

`struct fw_patch_emi_hdr` 为48字节。只去掉外层48字节，保留其后内容；
不能把注释提到的内层 BT/MCU 头再自行剥离。EMI 偏移不是完整头部地址，
源码取 `emi_addr[2]<<16 | emi_addr[1]<<8`，忽略低字节和高字节：

| 固件 | 头部地址（小端） | 实际 BTIF EMI 偏移 | 去头负载长度 |
|---|---|---|---|
| `soc3_0_ram_mcu_1a_1_hdr.bin` | `0xf0000000` | `0x000000` | 165328 |
| `soc3_0_ram_bt_1a_1_hdr.bin` | `0xf0100011` | `0x100000` | 671992 |

两段按此转换都在源码声明的子区域和0x450000 CONN EMI内。
这只是离线边界检查，没有执行映射/下载，也没有证明主线加载成功。
尤其不能把 BT 文件低字节0x11加入 AP 偏移。
WLAN 容器仍按自己的 `ROM_EMI_HEADER` / 多段尾表路径处理，不能复用 BTIF 地址算法。
所有 EMI AP 基址必须来自本次保留内存分配，不复用 ACK 某次启动的历史物理地址。

## 本轮工具及后续实施

[主机端准备工具](tools/wifi-nvram-prepare.py) 默认只输出长度/哈希，严格校验本机
6146字节格式及尾部校验；可显式指定 MAC 文件。可选 `--output` 仅创建新的0600
本地文件，不覆盖既有路径、不向字符设备写入，没有设备发送功能。
完整 MAC、头部十六进制或校准原文不进入工具输出或仓库。
原分析脚本虽然有 MAC 字段打码，但 `head16` 会包含完整 MAC，因此不直接归档其
设备元数据或照搬该脚本。本轮新增工具不输出这些字段。

12项合成数据测试覆盖帧起止、版本字节、错误尺寸/校验、MAC 定点覆盖、特殊文件、
独占输出和 CLI 默认不生成负载；另外用实机只读记录在内存中验证精确6156字节帧。
设备运行的 Debian 当前没有 Python，本工具是主机侧准备/复核工具，不是板端启动服务。

当前可结束任务 A 的主要协议分析；无需等待固件内部指令逆向才继续移植。
B 中本机 BTIF 封装已修正，未知 CRC/内部头语义继续保持未知。
C 仍缺冷/暖启动与失败重试差异、结果共享语义，暂不缩减真实 BT 依赖。

下一阶段先解决真实上游供电、公共供电/voter 和 pinctrl，再做显式触发、有限超时的
CONN 电源/ID 实验；之后接入保留内存、固件和真实校准，最后才实际投递 NVRAM。
未来从 nvdata 直接读取时采用只读块设备及 ext4 `ro,norecovery`，按 PARTLABEL/身份
验证分区，不硬编码 `/dev/sdc14`，不修 GPT。也可保存单机私有校准副本到外置rootfs
的数据目录；原文不放入内核 Git 或通用镜像，具体存储接入尚未实施。

## 引脚与公共供电后续（attempt57）

[57](evidence/attempt-57.md) 已加入未引用的 active/idle DT 状态，明确共享drive
字段全部采用一致配置；编译/schema/离线模型通过，未实机激活。ACK 当前 PMIC
配置与RC分支一致，但未直接读取SPM标志。厂商公共供电函数在32个独立API
失败注入下仍返回0，后续事务必须逐步校验，不能直接用返回成功代替就绪。

## A-die ID 后续

见 [MT6635 E3 初始化边界](ADIE-POST-ID.md)：下一轮仅验证两个固定 XTAL
寄存器读取；efuse、模拟配置写入、AFE 校准和固件启动尚未实现。

[attempt75](evidence/attempt-75.md) 已验证单个 XTAL 寄存器的受控写入、
读回和原值恢复；尚未完成厂商顺序中的模拟初始化，更未启用 Wi-Fi。

[attempt76](evidence/attempt-76.md) 已验证 SYSRAM +0x2800 的 A-die ID
写入/读回/清零。正式固件交接还需保持 mailbox 生命周期；当前 Wi-Fi 仍不可用。

[attempt77](evidence/attempt-77.md) 获得前两项配置地址的稳定读响应：
TOP064=0、TOP0bc=1；尚未写入厂商目标7700/21，Wi-Fi仍不可用。

[attempt78](evidence/attempt-78.md) 已验证持有ID mailbox时按厂商顺序写入
TOP064=7700、TOP0bc=21，读回后逆序恢复原值并清理。后续FM/thermal路由、
efuse、校准和固件仍待接入，Wi-Fi尚不可用。

[attempt79](evidence/attempt-79.md) 已取得FM/thermal数字基线，发现thermal地址
已经是50305a00；CAL_EN/GPT2为0，thermal semaphore13被动报告检查通过。
两轮FM_CTRL为801f，下一轮验证清mask80ff及原值恢复，并继续检查thermal
条件；本轮无数字路由写入，尚未启动固件或提供Wi-Fi。

[attempt80](evidence/attempt-80.md) 已验证FM_CTRL清mask80ff：801f→0→801f，
应用/恢复读回通过，重复thermal检查及外层清理成功。下一步审核并拆分efuse
读取与thermal trim流程；本轮无efuse、校准或固件操作，Wi-Fi仍不可用。

[attempt81](evidence/attempt-81.md) 已获得efuse控制字的稳定主线基线：
两次完整值内部比较一致，公开kick/valid/mode/address字段为0，四笔响应
均满足新鲜性条件且完整清理成功。尚未触发efuse或读取私有数据；下一步
设计固定地址0读取触发、独立超时和有效性检查。Wi-Fi仍未启动。

## Attempt82：efuse 触发后控制字变化，保护性停止

镜像 `89780a5bbea6` 实机只触发一次地址0读取；首轮观察到 kick=0、valid=1，
但完整控制字在这两个状态位以外发生变化，返回 EIO，未接受完成确认。
所有外层资源按设计保留，没有读取私有数据、强制清理或启动固件。
重复命令被拒绝，九组缓存状态哈希不变，USB SSH仍可用。
已复位恢复第81轮镜像，版本/boot哈希、CONN关闭及USB SSH通过；
下一步调查变化位与厂商控制字语义，不直接放宽检查。
这轮不是清理成功或Wi-Fi可用的证据。详见 [82](evidence/attempt-82.md)。

## Attempt83：变化位定位

新镜像 `4434b68988c7` 只增加缓存变化掩码，实测首轮CTRL变化为 `0x3b`，
仅涉及bit0/1/3/4/5，其他非kick/valid位未变；严格检查继续返回EIO并保留资源。
未读取私有数据，重试被拒绝，九组缓存哈希不变。其他芯片将低6位定义为AOUT，
这是调查线索，尚不是MT6635语义证据。后续先确认语义或受限观察稳定性，
不直接放宽完成/清理条件。Wi-Fi仍未可用。见 [83](evidence/attempt-83.md)。

本轮已恢复第81轮主线；版本/boot哈希、CONN关闭、CPU0–7与USB SSH均通过。

## Attempt84：低6位三次稳定观察

独立命令 `adie-efuse-observe` 实测三组新鲜ID/CTRL响应，变化掩码均为
`0x3b`，kick=0/valid=1，其余非状态位不变；耗时170531000ns（包含guard）。
只设置observe-stable，仍保持pending/unsafe，按设计返回EUCLEAN并保留资源。
未读私有数据，九组缓存哈希在拒绝重试后不变；USB SSH可用。
该结果支持下一轮单独测试“低6位稳定例外＋其余位严格比较”下的完成/清理，
不能称为MT6635字段定义或efuse数据有效性的证明。Wi-Fi仍未可用。
见 [84](evidence/attempt-84.md)。

已恢复第81轮主线，版本/boot哈希、CONN关闭、CPU0–7与USB SSH均通过。

## Attempt85：稳定状态完成＋完整清理通过

独立 `adie-efuse-stable-cycle` 在三次kick0/valid1、低6位变化稳定、其余位
严格一致后允许清理。本机E3实测delta均0x3b，confirmed3/complete1/pending0，
FM、模拟配置、mailbox和全部外层恢复成功，result/cleanup均0。
设备保留在 `68e4d632a8bb`，CONN关闭；USB SSH、存储、引脚、17组LVTS及
重试拒绝回归通过。该低位例外是本机经验规则，不是通用字段定义；
未读取私有数据、未应用trim或启动Wi-Fi。下一步先设计私有数据的临时存储、
诊断脱敏和清零，再实现受保护读取，thermal trim另行验证。
见 [85](evidence/attempt-85.md)。

## Attempt86：私有结果重复读取、清零与完整清理通过

新命令 `adie-efuse-data-read` 在稳定完成后读取四个结果字两轮，八次读取、
32笔ID/DATA/ID/CTRL传输，四项比较全部一致；数据阶段809727923ns。
原始数据只在临时缓冲区，全部退出路径显式清零；该命令的A-die诊断只输出
元数据，外层清理后还擦除继承RDAT的缓存。未发布数据值或数据哈希。
全部外层恢复成功，CONN关闭，设备保留在 `6033b3cb705f`；USB、存储、
引脚、17组LVTS及九组缓存哈希/重试拒绝回归通过。尚未交付私有SYSRAM槽、
应用trim、校准或启动Wi-Fi。下一步单独验证私有SYSRAM交付与清除。
见 [86](evidence/attempt-86.md)。

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
