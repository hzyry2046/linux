# MT6635 E3：ID 之后的初始化边界

2026-11-03。attempt73 已在主线读到 `0x66358a11`；本文区分后续源码依据与
尚未实施的硬件步骤。AI 辅助分析、实现与测试，未作外部提交。

## 本地源码依据

6.6 ACK 的 `conninfra/conn_drv/connv2/platform/mt6893/mt6893_pos.c`
SHA256 `29cda08e028cff1b844f5fc66e4c728dc5e3c0d6d450caf946fe56008453693f`；
4.19 的 `drivers/misc/mediatek/connectivity/conninfra/platform/mt6893/mt6893_pos.c`
SHA256 `fb998ea09e10f18006cabf8a0b2a3312cace979386d55b251e0b84679be2512f`。
地址定义来自各自 `include/mt6893_consys_reg_offset.h`。

两份源码的 `connsys_a_die_cfg_mt6893()` 都按下面顺序执行。它们不是两个
独立硬件规范；相同代码不能证明未描述位的含义或复位值。

| 顺序 | 对象 | 厂商操作 / 含义 | 主线当前决策 |
|---|---|---|---|
| 1 | SYSRAM A-die ID mailbox | 写入读到的 ID | 尚未交付固件 |
| 2 | TOP 0x064 | 写 0x7700，WF SX 校准映射补丁 | attempt78 已验证目标读回与原值恢复 |
| 3 | TOP 0x0bc | 写 0x21，低功耗 DBDC/legacy 接口 | attempt78 已验证目标读回与原值恢复 |
| 4 | 数字 SPI 0x1800400c | 清除 mask 0x80ff | 需独立保存、验证、恢复 |
| 5 | 数字 thermal 0x18002018 | 写 0x50305a00 | 尚未接入 |
| 6 | TOP efuse 0x108 等 | 触发读取并应用 thermal 校准 | 有副作用，不归入被动快照 |
| 7 | TOP 0x070 | 写 0x80000000，WF pad HighZ | 后续会再写 0x5，不能视为普通存储 |
| 8 | TOP 0x380/0x390 | 写 0x000e8002，禁用 CAL LDO | 改变模拟供电，暂缓 |
| 9 | TOP 0xa18 | 写 0xf6e8fff5，XOBUF supply-V | 已验证读取，A18单项写/恢复见attempt75 |
| 10 | TOP 0xa1c | E1 写 0xd5555fff，E3 写 0x55555fff | 已验证读取，A18单项写/恢复见attempt75 |
| 11 | TOP 0x384/0x394 | 写 0x2008，THADC 初始 IR | 暂缓 |
| 12 | GPIO180 | 交还 CONN mux | 已有受控恢复路径 |

之后的 `connsys_afe_wbg_cal_mt6893()` 包括 AFE 配置、校准控制和延时，不能
把它当成普通寄存器初始化表直接执行。efuse 函数也不是简单读取：先改 0x108
控制位，再触发、轮询、读数据、更新 SYSRAM 并应用 thermal trim。未来实施时
必须分别检查传输失败、busy 超时和有效位，且不把原始校准数据写入公开日志。

## 下一项实验：两个固定 XTAL 地址

`connsys_bt_low_power_setting()` 对 `adie_e2_default` / `adie_e2_bt_only`
表中的 0xa18/0xa1c 做读改写，且明确将 0x66358a11 分到 E2/E3 表。
这是选择这两个地址的可读性依据；该函数同时请求 top clock，且运行阶段不同，
因此不能推断它证明了当前早期复位释放状态下的全部时序条件。
已有 ID 读成功提供了当前 TOP 通路的实机依据；仍须通过本轮有限实验验证。

新增 root-only 一次性 `adie-xtal-cycle`：沿用完整嵌套准备，先获取新鲜 ID，
再依次读 TOP 0xa18/0xa1c。仅使用读前缀 0xb000，零 WDAT 触发读取；无模拟
寄存器写命令，也无 efuse、固件或射频启用。原 `adie-id-cycle` 语义保留。

每笔读取单独记录触发前 RDAT、结果以及 busy 证据；不能借用 ID 那笔的 busy。
未观察到本笔 busy 且 RDAT 未变化则返回 EAGAIN，即使可能是真实相同值也不
宣称新响应。`xtal_read/xtal_valid/xtal_busy_mask` 是两个地址对应的位图；valid
仅表示满足传输证据条件，**不代表配置数值正确**。两个值相同但本笔观察到 busy
可以通过。本策略不是 SPI 总线抓包，也不能排除任意并发主控。

失败继续遵循 attempt73 的清理/保留规则：只有访问、所有权、idle 和复位状态
可确认时才恢复；先复位再恢复地址，之后才解锁和关闭外层资源。WDAT 不能恢复。
不确定状态保留至重启。顺序 guard 不能解决 MMIO 总线本身卡死。

## 主机验证

新增两个测试运行真实 C：独立 helper 覆盖逐笔 freshness、两处超时、所有 guard
及所有权采样点、9 个丢写点与45种写后状态故障；嵌套测试覆盖命令、一次性锁定、
9个丢写点、36种写后故障、两处超时、先复位后解锁以及外层恢复失败。
旧 ID、prepare 和底层测试随测试链一并运行。实机结果另记 attempt74，不能将
主机模型通过写成硬件通过。

## 实机结果

[attempt74](evidence/attempt-74.md) 已通过：0xa18=0xf668fff5，
0xa1c=0x55555fff，每笔 RDAT 变化，全部清理成功。没有观察到 busy 脉冲。
这些值不被宣称为通用冷复位默认值；Wi-Fi 尚不可用。

## 单寄存器写入与恢复实验（attempt75 设计）

本轮 `adie-write-cycle` 只接受新鲜 E3 ID、0xa18=0xf668fff5 和
0xa1c=0x55555fff；其他基线在任何模拟写入前返回 EINVAL。0xa18 的目标
0xf6e8fff5 来自上述两个厂商版本，TOP 写前缀0xa000来自其 spi_op_array。
与本机基线仅差 bit23，但这不证明物理电压，也不证明可以任意调整该位。

这是单寄存器传输/恢复实验，尚未沿用完整厂商初始化顺序。前置的低功耗接口、
efuse、WF pad 和 CAL LDO 配置均不执行；没有证据证明这些步骤可从正式
Wi-Fi 初始化中删除。选择该地址是因为已有源码读改写依据和主线读通的基线，
不把这种证据推广到只有写入依据的0x064/0x0bc。

在已验证 ID/XTAL 之后，固定执行五笔传输：

1. TOP 写0xa18=0xf6e8fff5；触发前标记 analog dirty。
2. TOP 读0xa18，要求独立响应证据和完整目标值一致，才标记 applied。
3. TOP 写0xa18=本次保存的基线值（目前严格限定为0xf668fff5）。
4. TOP 读芯片 ID，要求新响应和本次 ID 一致，打断 RDAT 残留。
5. TOP 读0xa18，要求新响应、完整基线值一致以及最后一次 idle/guard 通过，
   才清除 analog dirty。之后才执行原有复位、地址恢复、解锁和外层关断。

write_step=0..4对应上述传输；write_issued两位对应应用/恢复写触发，
write_read三位对应应用读回/ID隔离读/恢复读回，write_busy_mask五位对应
各笔观察到的busy。issued不证明写入成功。应用和恢复的busy不代替读回。
初始ID、XTAL和写实验各自记录响应证据，不能借用前一笔busy脉冲。

应用失败后不重试应用。如果模拟写可能已发出且访问仍可确认，仅尝试一次
上述恢复流程；有guard/所有权/忙超时问题则不再写任何寄存器，保留至重启。
恢复读不新鲜、值不符或ID隔离读失败，也保留dirty并阻止复位/解锁/关断。
最初应用错误与恢复错误分别记录。恢复验证只说明寄存器值，不证明内部
模拟瞬态或晶振品质；不宣称完成供电、时钟或射频功能验证。

主机测试使用独立的模拟寄存器模型，复位不自动清除其值；要求先恢复模拟
寄存器才能复位/解锁。覆盖19个MMIO丢写点、95种单项写后guard故障、所有
guard及所有权采样点、五笔忙超时、数据污染、旧RDAT、基线拒绝及双重故障。
嵌套测试另覆盖76种写后guard故障和外层恢复失败，防止只测到局部helper。

### attempt75 实测

[75](evidence/attempt-75.md) 通过：f668fff5 → f6e8fff5 → f668fff5，
应用读回、ID隔离读、恢复读回均满足新响应和完整值匹配。无busy采样，
模拟dirty及所有外层dirty/unsafe均清零；无efuse、校准或固件启动。

## 厂商前序：A-die ID mailbox（attempt76 设计）

在 `connsys_a_die_cfg_mt6893()` 中，芯片 ID 读取后、0x064/0x0bc 写入前，
厂商把 ID 放到 SYSRAM `CONN_INFRA_SYSRAM_SW_CR_A_DIE_CHIP_ID`。
本地4.19/6.6头文件定义均为0x2800，SYSRAM基址0x18050000，故地址为
0x18052800。这是共享 SRAM 的单个32位字，不是新的 efuse 或 TOP 寄存器。

`adie-mailbox-cycle` 在同一次准备、SYSRAM 全区清零/检查、GPIO180 高电平、
semaphore11 持有和新鲜 ID 读取后，要求 SYSRAM complete、4096字验证与扫描
完成、RGU四项仍应用。只映射 mailbox 四字节；要求旧内容为零，写入本次 ID，
完整读回，再清零并确认零。每步受 AP/CSR、A-die复位、semaphore报告、WB
及 SPI idle 条件保护。全部清理确认后才复位 A-die、恢复地址和释放外层资源。

零基线是本次主线初始化后的预期，不是声称 SRAM 上电值为零。遇到非零内容
立即保留现场，不输出其原值。写入可能发生即标记dirty；guard丢失、忙超时
或清零不匹配时保持dirty并阻止后续复位/解锁/断电。应用读回失败且访问仍
明确时允许一次清零，保留原错误。写入发出、值匹配、零恢复三个状态分开记录。

本轮结束会清除ID，尚未交付给固件。后续正式初始化须把“发布后保持”放进
固件的整个生命周期，不能照搬此实验的即时清零。0x064/0x0bc 仍未找到本机
可靠读回/复位语义，不能因已测通 XTAL 恢复就给它们套用相同回滚假设。

主机测试直接执行真实 C：7个丢写点、35种写后状态故障、所有guard/所有权
采样点、4个映射失败和6项前提拒绝。嵌套测试把mailbox映射到先前清零的
同一块SYSRAM模型，验证先清零再复位/解锁、28种写后故障、非零旧值保留、
双重失败保留首错和外层恢复失败；不使用独立的假mailbox掩盖集成错误。

### attempt76 实测

[76](evidence/attempt-76.md) 通过：mailbox 0 → 0x66358a11 → 0，
ID 与本次 TOP 读取一致，全部外层清理成功。本轮无模拟写入和固件启动。

## 前两项配置的读响应实验（attempt77 设计）

目前本地厂商资料明确0x064为WRI_CTR2、0x0bc为SMCTK11，初始化分别写
0x7700和0x21，但没有找到这两个地址的本机读回/复位规范。本轮不把缺失
资料当成禁止探索的结论，也不把寄存器名称当作无副作用证明，而是增加一个
明确限定的读响应实验，为后续配置验证收集主线证据。

`adie-config-read` 先运行既有完整准备和新鲜ID读取，再固定读取
[0x064,0x02c,0x0bc,0x02c,0x064,0x02c,0x0bc,0x02c]。八笔传输均使用
TOP读前缀0xb000和零WDAT；没有任意地址接口、TOP写命令或efuse访问。
本轮不运行mailbox/XTAL实验，不写0x7700/0x21。

每笔记录前RDAT、返回值、busy证据。未观察本笔busy且RDAT未变则EAGAIN；
ID隔离读必须等于本次ID，错误则ENODEV；第二轮与第一轮不一致则EIO。
config_read/valid/busy_mask逐位对应八笔，stable表示两轮全部一致；它不
代表配置正确、不代表无读取副作用，也不证明安全恢复或冷复位默认值。
穿插ID允许两个目标都返回零时仍逐笔检验新响应，不靠旧数据值判断成功。

失败沿用已验证的复位/地址恢复或guard丢失后的资源保留规则。重复值不一致
但访问仍明确时结束并清理，不擅自写回采样值。可能的读取副作用并不会因此
被证明逆转；若后续写实验需要更强语义，必须另行验证。

主机测试执行真实C，覆盖21个丢写点、105种写后guard故障、所有guard/所有权
采样点、八处忙超时、旧RDAT、坏ID、重复值变化和双重失败保留首错。
嵌套测试覆盖84种写后故障、八处超时、失败清理、外层恢复失败与一次性路由。

### attempt77 实测

[77](evidence/attempt-77.md) 通过：0x064两轮为0，0x0bc两轮为1，
四次ID隔离读均为0x66358a11；全部RDAT变化，无busy采样，完整清理成功。
这提供了本轮读响应证据，未验证写入、复位或内部状态可回滚。

## 前两项配置写入与 mailbox 持有（attempt78 设计）

`adie-config-cycle` 组合两轮配置基线读取与ID mailbox，但把mailbox的清零推迟到
模拟子事务结束之后。只接受新鲜E3 ID和两轮0x064=0、0x0bc=1；其他组合不会
触发模拟写入。SYSRAM仍须完整清零/验证，写入ID并读回后才进入子事务。

应用顺序来自厂商 `connsys_a_die_cfg_mt6893()`：0x064=0x7700，然后0x0bc=0x21。
两项之间增加独立读回。逆序恢复是本轮实验的清理策略，并非厂商已证明的通用
回滚协议：先恢复0x0bc=1，再恢复0x064=0，每项写后先读已知ID，再读目标，
必须有新响应及完整值匹配。它检验的是配置字值恢复，不证明内部模拟状态回到
原点、无瞬态影响、复位默认值或射频功能。后续FM/thermal/efuse步骤本轮不执行。

固定十笔SPI操作及状态编号：

| step | 操作 | 读结果槽 |
|---|---|---|
| 0 | 写0x064=0x7700 | — |
| 1 | 读0x064并验证0x7700 | 0 |
| 2 | 写0x0bc=0x21 | — |
| 3 | 读0x0bc并验证0x21 | 1 |
| 4 | 写0x0bc=1 | — |
| 5 | 读ID并验证 | 2 |
| 6 | 读0x0bc并验证1 | 3 |
| 7 | 写0x064=0 | — |
| 8 | 读ID并验证 | 4 |
| 9 | 读0x064并验证0 | 5 |

prefix_issued按step位记录四个写触发，成功全值0x95；prefix_read按六个读槽记录，
全值0x3f；prefix_busy_mask按十笔操作记录。applied/restored/dirty的bit0对应064、
bit1对应0bc。每个写触发前先置dirty；只有恢复读回、值匹配和额外guard通过才
清位。尚未可能写入的寄存器不做恢复；应用失败不重试应用。

每笔操作的guard除了已有AP/CSR、复位、semaphore、WB、SPI idle条件，还读回
mailbox确认ID一直存在。mailbox变更、guard丢失或恢复失败时保留模拟dirty和
mailbox，以及外层全部资源。只有模拟清理已确认后才清除mailbox，再复位/解锁。

未观察busy且RDAT未变的隔离ID读也必须拒绝：例如应用读回丢失，恢复写已发出，
但ID读仍与旧锁存相同时，不能据此宣称恢复完成；保留现场等待重启。这是有意的
保守响应策略，不在故障路径增加试探传输。最初应用错误与恢复错误分别记录。

独立实际C测试覆盖43个丢写点、215种写后状态故障、全部guard/所有权/mailbox
采样、十处SPI超时、基线不符、读回污染、旧RDAT与部分写入。嵌套测试使用共享
SYSRAM和独立模拟寄存器模型，覆盖172种写后故障，并断言先恢复模拟值再清空
mailbox和复位，验证双重失败保留首错及外层恢复失败。

### attempt78 实测

[78](evidence/attempt-78.md) 通过：mailbox持有期间064写7700、0bc写21，
独立读回匹配；逆序恢复1/0后才清mailbox、复位和解锁。全部dirty/unsafe清零，
读回均有RDAT变化，无busy采样。下一项为FM SPI格式与thermal SPI地址路由。

## FM / thermal 路由之前的数字基线（attempt79 设计）

审核 ACK `mt6893.c:consys_thermal_query()` 后，先把下一轮限定为只读。
该函数单独持有 semaphore13，先设置 `0x18002024[19]`（enable），
再设置 `0x18007038[0]`（GPT2），然后设置 `0x18002024[18]`（trigger）。
结束时清除 GPT2 bit0 和 enable bit19，但没有显式清除 trigger bit18；
源码还注明 GPT2 disable 在6893上无效。因此不能把 GPT2=0 或 RFSPI
semaphore11 已持有当作 thermal 引擎停止的充分条件，也不能未经验证就清位。
`update_thermal_data_mt6893()` 对 `0x18002004[17:16]` 置位，属于另一项
校准配置；这次只记录，不执行它。没有读取 efuse 数据或 SYSRAM 校准字。

新增一次性 `adie-route-read`：复用 `adie-config-cycle`，在两个模拟目标均
读回成功、mailbox保持期间，按下表读两轮，随后执行已有逆序恢复。

| 每轮槽 | 固定地址 | 本地厂商名称 / 读取依据 |
|---|---|---|
| 0 | 0x1800400c | FM_CTRL，初始化路径读改写 mask 0x80ff |
| 1 | 0x18002018 | THERM_AADDR，thermal query 的固定debug快照读取 |
| 2 | 0x18002004 | THERMCR1，thermal更新读改写及debug快照 |
| 3 | 0x18002024 | THERM_CAL_EN，thermal查询读改写及结果读取 |
| 4 | 0x18007038 | GPT2 thermal enable，thermal查询读改写 |

`route_sample=0..4` 为第一轮，5..9为第二轮；`route_read` 表示已执行采样，
全值0x3ff。每次采样前后检查AP/CSR、复位、SPI空闲、WB、mailbox和
semaphore11，同时要求四个被动报告中的semaphore13位全零。不读能获取
所有权的OWN_STA，不声称持有semaphore13。两轮值必须完整一致，且每次
CAL_EN采样bit19/18、GPT2采样bit0必须为零。成功设置`route_stable/idle`；
这里idle只表示已采样的条件通过，不是无并发主控、自动引擎停机或无读取
副作用的证明。读取是顺序采样而非原子快照，MMIO自身卡死仍靠看门狗。

新路径没有写FM/thermal/GPT2，没有校准/efuse/固件操作；外围模拟配置仍
包含前轮已验证的TOP写入和恢复，所以不能把整个命令称为“无写操作”。
映射失败且原保护条件有效时可恢复既有模拟配置并清理。发现thermal所有者、
启动位或两轮变化时标记unsafe，保留模拟配置、mailbox、锁与供电，等待重启；
不擅自清除触发位或尝试关闭可能活跃的引擎。

AI辅助实现与实际C主机测试；硬件结果另行记录，基线通过后再设计路由写入。

### attempt79 实测

[79](evidence/attempt-79.md) 通过：两轮FM_CTRL=801f、THERM_AADDR=50305a00、
THERMCR1=7f0300ff、THERM_CAL_EN=0、GPT2 thermal enable=0；thermal所有权
检查通过，模拟/mailbox与外层全部清理成功。路由目标已经匹配，后续只在
需要时设置；下一项先验证FM_CTRL清mask80ff和原值恢复。无固件启动。

## FM SPI读格式清位与恢复（attempt80 设计）

`adie-fm-cycle` 在attempt79两轮数字基线之后执行，只接受已测组合：
FM_CTRL=801f、THERM_AADDR=50305a00、THERMCR1=7f0300ff、CAL_EN=0、GPT2=0。
模拟064/0bc仍保持7700/21，ID mailbox仍有效。THERM_AADDR已经匹配厂商值，
本轮不写该寄存器，也不触发thermal、efuse、校准或固件。

重新读取FM_CTRL且与两轮基线一致后，计算`before & ~0x80ff`（本机为0），
标记dirty并写入，独立MMIO读回完整目标，再写回801f、读回确认。只有最后
一次保护检查通过才清dirty，随后才能逆序恢复模拟配置、清mailbox和释放外层。
两个写入前后和最后读回之后都会重新读取四个thermal字，要求仍等于已保存
基线；其间继续检查AP/CSR、复位、SPI idle、WB、mailbox和semaphore11/13。
thermal字或所有权变化即保留现场，不清启动位、不获取semaphore13。

`fm_issued`的bit0/1表示应用/恢复写已可能发出，不代表写入成功；`fm_read`
bit0/1/2表示即时原值/应用值/恢复值已读取。`fm_applied`表示目标读回匹配，
`fm_restored`还要求恢复后的保护检查通过。`fm_cleanup`独立记录清理错误，
保留最初失败阶段。FM写可能发生后即使应用读回失败，也只在保护条件仍明确时
尝试一次恢复；恢复不明则保持FM dirty和所有父资源至重启。原route/config
命令语义保留，新的FM命令同样每次启动仅允许一次。

FM_CTRL是数字MMIO配置字，写/读回策略不套用TOP RDAT的新响应规则；本机
目标与原值不同可揭示丢失的应用写与丢失的恢复写，但不是总线抓包或射频测量。
保护检查为顺序采样，没有原子地排除全部其他主控；某个thermal字读完之后
再变化可能不在当前检查中可见。主机测试据此覆盖已观察到的故障，不把
无法检测的采样间隙描述成已保证的安全性。

AI辅助实现和实际C故障注入测试；实机结果另记attempt80。

### attempt80 实测

[80](evidence/attempt-80.md) 通过：FM_CTRL 801f→0→801f，完整读回一致，
thermal地址/控制字与基线一致，fm dirty清零后才恢复模拟配置和mailbox。
全部外层清理成功，无thermal/efuse/校准/固件操作。下一厂商步骤为efuse读取
及thermal trim，须拆分状态机与错误处理，不直接移植厂商原始数据日志。

## Efuse控制状态读取（attempt81 设计）

厂商helper对TOP108执行读改写：先清bit30，再按mask43ff00c0设置读取模式
bits7:6=0、地址bits25:16=0并置kick bit30；轮询kick清零，检查valid bit29，
读取TOP130/134/138/13c四个私有字，并发布到SYSRAM和应用thermal trim。
本机尚无该控制寄存器的主线基线，不能直接沿用厂商未检查每次传输返回值、
超时后继续检查valid并输出原始数据的实现。

新增一次性`adie-efuse-ctrl-read`，复用完整FM事务，但在FM目标0读回后、
恢复801f之前增加固定四笔TOP读取：ID02c、CTRL108、ID02c、CTRL108。
保留064=7700/0bc=21和mailbox生命周期。每笔都有单独busy或RDAT变化证据；
不借用前一笔的busy。ID须匹配本次ID，两次完整控制字须一致。控制字bit30
为1或bits7:6非零则保留现场；不清kick，不改模式。bit29为1只说明采样到
valid状态，不代表本轮产生了新efuse结果。控制地址字段可被观察，不触发它。

四笔最后以控制字结束，使正常路径的模拟恢复ID隔离读能够从不同RDAT开始。
失败路径仍可能遇到旧ID锁存：未采到busy且读回未变化时拒绝“恢复成功”，
保留父资源等待重启，不为满足清理而放宽新响应条件。

每次传输前后继续检查thermal四字、FM目标仍为0、AP/CSR、复位、SPI idle、
WB、mailbox和semaphore报告。所有检查仍是顺序采样。出错后若访问与引擎
状态仍明确，沿既有FM/模拟/mailbox逆序清理；状态不明或SPI超时则不写恢复值。

状态`efuse_ctrl_read/valid/busy_mask`的bits0..3对应上述四笔，stable表示
全部检查及最后guard通过。两次CTRL输出只保留mask63ff00c0，覆盖kick、
valid、地址和模式；未解释低位不公开。没有TOP写前缀a108，没有读取四个
私有数据地址，没有efuse引擎触发、thermal trim或固件操作。SPI WDAT=0
用于触发TOP读取，与设置efuse kick是不同的操作。

AI辅助实现和实际C主机测试；实机结果另记attempt81。后续才设计固定地址0
的读取触发、独立截止时间、数据有效性、私有数据生命周期及校准交接。

控制字也可能残留在随后的模拟恢复ID读取的RDAT中；因此本命令下prefix
sample2的before/value同样掩码输出，并明确标为before_masked/value_masked。
这不会放宽内部完整ID匹配和新响应检查，也不修改旧命令的诊断格式。

### attempt81 实测

[81](evidence/attempt-81.md) 通过：两次完整CTRL字在内核内比较一致，公开的
mask63ff00c0字段均为0，kick/valid/mode/address均未置位。两次ID隔离读匹配，
四笔各有RDAT变化，无busy采样。FM、模拟/mailbox和所有外层清理成功。
未触发efuse或读取数据字；下一步设计固定地址0的触发与有界完成验证。

## 地址0 efuse读取引擎触发与完成（attempt82 设计）

`adie-efuse-cycle` 复用attempt81的控制字读取，只接受完整稳定且已知
mask63ff00c0字段全零的基线，即kick=0、valid=0、地址=0、读取模式=00。
保留基线其他位，只置bit30，通过固定a108地址发出一次读取kick。因已确认
kick=0，本实验不额外重复厂商的清kick写。没有任意地址或任意数据写接口，
不设置非读取模式，不访问TOP130/134/138/13c，也不应用trim。

发出WDAT前记录单调时间并设置pending/issued，可能已经启动就不允许外层
清理。随后固定执行ID02c、CTRL108的读取对，每笔独立验证busy或RDAT变化，
防止连续同值控制读被误认为新响应。CTRL除kick/valid外必须完整等于基线。
观察kick置位记engine_busy_seen；连续两次kick清零且valid置位才记complete，
并清pending。kick再次置位或valid为0会清确认计数；观察busy后却出现kick=0/
valid=0作为无效结果报ENODATA并保留。未观察busy、始终无valid时有界超时。

SPI传输沿用独立20ms忙轮询限制；引擎从发出kick开始有250ms实际时间截止，
每次保护检查前后核对，并限制最多70轮、轮间延迟30us。厂商注释约2ms且
最多70次30us等待；本实验有大量状态保护与额外ID/确认读取，因此250ms是
明确更宽的调试截止时间，不宣称达到了厂商2ms的物理完成时序。超时不可
被一次较晚的成功读取覆盖。MMIO本身卡死仍不能由软件deadline抢占。

complete只表示新valid从初始0出现、两次已采样的读取完成状态一致；kick
脉冲可能短到未采样。既不要求必须观察引擎busy，也不把SPI busy当引擎busy。
停止在控制状态，不读取新装载的私有数据，不清valid，不把控制字写回为旧值。
完成后才执行原有FM/模拟/mailbox/外层清理；任何未确认的启动、读取错误、
模式/地址/其他控制位变化均保留pending、父资源和供电，等待重启。

新增root-only缓存属性`efuse_status`：issued/pending/complete区分可能已发出
和完成；transfers记录本子事务触发次数，polls为新鲜CTRL响应次数，confirmed
为连续有效完成次数，engine_busy_seen与spi_busy_count分别记录两种busy。
flags仅mask63ff00c0，elapsed_ns记录截止检查时耗时；不包含私有数据。
原有adie_status的CTRL及继承RDAT掩码规则继续生效。

AI辅助实现和实际C主机测试；实机结果另记attempt82。顺序guard仍非原子排他，
完成不代表私有数据可用、校准正确或固件已经启动。

## Attempt82：efuse 触发后控制字变化，保护性停止

镜像 `89780a5bbea6` 实机只触发一次地址0读取；首轮观察到 kick=0、valid=1，
但完整控制字在这两个状态位以外发生变化，返回 EIO，未接受完成确认。
所有外层资源按设计保留，没有读取私有数据、强制清理或启动固件。
重复命令被拒绝，九组缓存状态哈希不变，USB SSH仍可用。
已复位恢复第81轮镜像，版本/boot哈希、CONN关闭及USB SSH通过；
下一步调查变化位与厂商控制字语义，不直接放宽检查。
这轮不是清理成功或Wi-Fi可用的证据。详见 [82](evidence/attempt-82.md)。

## Attempt83 design: changed-position diagnostic

Keep the attempt82 single-kick sequence, full nonstatus-bit equality check,
250ms deadline and containment unchanged. Cache the XOR of the control sample
and saved baseline, excluding kick30/valid29, as `efuse_status changed`.
This reports changed positions without raw before/after control values.
It does not identify the direction or semantics of those changes. No additional
hardware transaction, private data read or automatic retry is introduced.
The prerequisite already requires both status bits zero, so the XOR-based
comparison has the same acceptance rule as82. Mutation tests check every
nonstatus bit and cached status; zero remains expected on success.

## Attempt83：变化位定位

新镜像 `4434b68988c7` 只增加缓存变化掩码，实测首轮CTRL变化为 `0x3b`，
仅涉及bit0/1/3/4/5，其他非kick/valid位未变；严格检查继续返回EIO并保留资源。
未读取私有数据，重试被拒绝，九组缓存哈希不变。其他芯片将低6位定义为AOUT，
这是调查线索，尚不是MT6635语义证据。后续先确认语义或受限观察稳定性，
不直接放宽完成/清理条件。Wi-Fi仍未可用。见 [83](evidence/attempt-83.md)。

本轮已恢复第81轮主线；版本/boot哈希、CONN关闭、CPU0–7与USB SSH均通过。

## Attempt84 design: bounded observation, no cleanup eligibility

`adie-efuse-observe` is a separate one-shot command. After the existing zero
status/read-mode/address0 prerequisite and single kick, it samples at most
three ID-separated control responses, with the existing250ms deadline and
all parent/thermal/transport checks. Each sample must have kick0/valid1 and
no change above bit5 except valid29. Low-six-bit difference masks must agree
across all samples. Any mismatch stops immediately. Three matching samples
set only observe-stable and return EUCLEAN at adie-efuse-observe-held; pending
and unsafe stay set, complete/confirmed stay zero, no cleanup runs. Busy or
invalid responses are rejected rather than waited out in this observation.
Cached observed/delta0..2 report post-guard inspected samples, including a
rejected one; stable means three samples agree, not hardware completion or
a proven MT6635 output-address interpretation. No raw words are published.
This does not change the existing adie-efuse-cycle acceptance rule.

## Attempt84：低6位三次稳定观察

独立命令 `adie-efuse-observe` 实测三组新鲜ID/CTRL响应，变化掩码均为
`0x3b`，kick=0/valid=1，其余非状态位不变；耗时170531000ns（包含guard）。
只设置observe-stable，仍保持pending/unsafe，按设计返回EUCLEAN并保留资源。
未读私有数据，九组缓存哈希在拒绝重试后不变；USB SSH可用。
该结果支持下一轮单独测试“低6位稳定例外＋其余位严格比较”下的完成/清理，
不能称为MT6635字段定义或efuse数据有效性的证明。Wi-Fi仍未可用。
见 [84](evidence/attempt-84.md)。

已恢复第81轮主线，版本/boot哈希、CONN关闭、CPU0–7与USB SSH均通过。

## Attempt85 design: separate empirical stable completion experiment

`adie-efuse-stable-cycle` selects the same three-sample observation guards and
250ms deadline as84. Only after all three fresh controls have kick0/valid1,
identical low-six-bit state and no other nonstatus changes does it set
confirmed3/complete1 and clear pending. Existing FM, analog/mailbox and outer
cleanup then runs, preserving its own failures. E3 ID and all earlier
prerequisites still apply. This empirical exception is limited to this
diagnostic path; strict cycle and hold-only observe commands are unchanged.
No raw private data, control restoration, second kick or thermal trim.

## Attempt85：稳定状态完成＋完整清理通过

独立 `adie-efuse-stable-cycle` 在三次kick0/valid1、低6位变化稳定、其余位
严格一致后允许清理。本机E3实测delta均0x3b，confirmed3/complete1/pending0，
FM、模拟配置、mailbox和全部外层恢复成功，result/cleanup均0。
设备保留在 `68e4d632a8bb`，CONN关闭；USB SSH、存储、引脚、17组LVTS及
重试拒绝回归通过。该低位例外是本机经验规则，不是通用字段定义；
未读取私有数据、未应用trim或启动Wi-Fi。下一步先设计私有数据的临时存储、
诊断脱敏和清零，再实现受保护读取，thermal trim另行验证。
见 [85](evidence/attempt-85.md)。

## Attempt86 design: temporary data, repeatability and erasure

`adie-efuse-data-read` selects the85 stable-completion rule, then reads fixed
TOP130/134/138/13c twice. Each word uses ID→DATA→ID→CTRL; every response has
own busy-or-changed-RDAT freshness and the full CTRL must equal the accepted
post-kick value. Eight private reads/32 transfers, no additional kick. A
separate2s deadline includes nested guards; it is not physical read latency.

Raw data and before/response values remain in local temporary structures,
explicitly erased on every exit. Four repeated comparisons are represented
only by masks/counters, never raw values or hashes. A-die diagnostics for
this command expose only metadata; after the entire outer cleanup returns,
all inherited RDAT arrays/ID diagnostics are explicitly erased. The retained
control cache is reduced to validated public fields (or zero if completion
failed). On a private transfer failure the hardware RDAT may still contain
a private word until reset; software-erased does not mean hardware-erased.
No forced writes to RDAT/WDAT to erase it are attempted.

Any data read/freshness/ID/CTRL/deadline/repeatability error sets unsafe and
retains parents. All local data is still erased. Success permits existing
FM/analog/mailbox/outer cleanup, whose failures remain independent. No private
SYSRAM handoff, thermal trim or firmware startup. Runtime evidence follows
in attempt86; use local date2026-11-04 (UTC2026-11-03 late afternoon).

## Attempt86：私有结果重复读取、清零与完整清理通过

新命令 `adie-efuse-data-read` 在稳定完成后读取四个结果字两轮，八次读取、
32笔ID/DATA/ID/CTRL传输，四项比较全部一致；数据阶段809727923ns。
原始数据只在临时缓冲区，全部退出路径显式清零；该命令的A-die诊断只输出
元数据，外层清理后还擦除继承RDAT的缓存。未发布数据值或数据哈希。
全部外层恢复成功，CONN关闭，设备保留在 `6033b3cb705f`；USB、存储、
引脚、17组LVTS及九组缓存哈希/重试拒绝回归通过。尚未交付私有SYSRAM槽、
应用trim、校准或启动Wi-Fi。下一步单独验证私有SYSRAM交付与清除。
见 [86](evidence/attempt-86.md)。

## Attempt87 design: private SYSRAM handoff and verified erasure

`adie-efuse-handoff-cycle` adds a separate 16-byte mapping at physical
0x18052804, covering only the four vendor software-control efuse slots.
It reuses86's repeated private words, full control checks and2s data-stage
budget. Four initial slots must be zero; each write is guarded and read back.
All four are then cleared, read back and scanned once more before parent
cleanup. Dirty bits are set before writes and remain set until the entire
final scan and guard pass. Mapping failure, nonzero baseline, comparison,
guard or timeout failure sets unsafe and retains the enclosing resources.
No speculative further erasure occurs after a failure; private words may
remain in hardware until reset, while temporary software buffers are still
explicitly erased on every exit. Diagnostics expose masks only, no values
or private hashes. The firmware remains stopped; thermal trim is separate.

The host integration model shares the actual SYSRAM backing array with the
outer preparation code. Tests cover mapping and four baseline faults, all
eight dropped writes and deadlines,32 write-time guard losses,12 readback
and final-scan faults, zero-valued data, redaction, one-shot refusal and
verified erasure before mailbox/reset/resource release. These tests cannot
prove physical bus behavior or exclude an asynchronous hardware writer.

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

## Attempt90 design: guarded first post-efuse pad baseline

The vendor sequence after efuse/thermal writes TOP070=80000000 (WF_PAD HighZ),
then TOP380/390=e8002 (CAL LDO disable), XTAL A18/A1C, then384/394=2008.
This experiment advances only to the first register, using `adie-pad-read`.
A freshly completed private trim plan must report both sequences no-op and
equivalent; otherwise it refuses with EOPNOTSUPP and conservatively retains
all parents. Previous boot outcomes are never substituted for this check.

Two fixed TOP070 reads each use ID→target→ID→CTRL; eight additional SPI
transfers share the original2s total data budget. Compare both responses and,
only after final guards, report equality to the public vendor80000000 target.
Raw baselines remain temporary and are explicitly erased on every exit.
No a070 write or pad-mode change is issued. A match is register equality,
not electrical proof of HighZ; a mismatch is not permission to replay a full
vendor word without validating write ownership and recovery.

## Attempt90：新鲜 no-op 前提下 TOP070 重复读取通过

新命令 `adie-pad-read` 每次重新计算trim候选并要求两种序列均no-op且一致，
否则在TOP070访问前拒绝并保留资源。本轮前提再次成立；TOP070两次读取
一致，8笔传输通过，但不等于厂商80000000目标。没有写pad或trim配置，
临时数据清零；总数据阶段1554148616ns，全部清理/外设回归通过，CONN关闭。
刷写后的首次重启仍停fastboot，原因未确定；再次正常reboot后启动成功。
设备保持 `9d1e950c4d59`，恢复备份未变，Wi-Fi仍不可用。
下一步先设计独立pad写入/读回/恢复实验，核对所有权与恢复条件，不能把
读取稳定当作可以安全回写的证明。见 [90](evidence/attempt-90.md)。

## TOP070 下一步：限定基线的固定值往返

见 [PAD-CYCLE-AUDIT](PAD-CYCLE-AUDIT.md)。MT6983 的 MT6635 分支提供
`0x80000000` 后恢复 `0x5` 的附加源码依据，但不支持任意基线回写。
新增 `adie-pad-cycle` 要求本轮两次基线均为5，才写目标、验证、恢复5并
再次验证；沿用新鲜 trim no-op 前提及2秒总数据预算。硬件结果另记，
不能将第90轮读取通过当作本流程已通过。
