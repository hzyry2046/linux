<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 SCP：SPM 26 MHz 资源持有

2026-11-15，基于 `6db0f4606d6e` 工作树，AI 辅助实现与本地源码/ATF
分析。接续 [TOPCK bootstrap](MODEM-SCP-BOOTSTRAP.md)。验证状态在文末。

## 本机 ABI，不能猜测 fallback

核对 A=`/data/src/kernel_oddo_mt6893` 的 `mt6893_defconfig`（MACH_MT6893、
SCP_RV）、`scp/rv/scp_dvfs.{c,h}` 和 `mtk_sip_svc.h`；V 为同板6.6的
`kernel_device_modules-6.6/drivers/misc/mediatek/scp/rv/scp_dvfs.c`。
V 缺失 scp-dvfs-disable 属性的修复保留默认启用初始化，避免初始请求被跳过。

另参考本地 `/data/src/tee/extracted/atf/decompiled.c` 与对应已提取 ATF 的
静态代码/指针表，仅核对控制流和 ABI，没有复制固件、反编译全文或固件哈希。
这份静态镜像不自动等于当前设备固件，实机必须通过严格 query/readback。

|位置|已核对契约|
|---|---|
|A SCP_DVFS_CTRL|SMC64 fast SiP `0xc2000232`|
|A MT6893 / V 非 legacy|x1=RESOURCE_REQ=1，x2=26M request bit0=1，x3..7=0|
|ATF dispatcher|0x82000232/0xc2000232 → `FUN_48c19c44(x1,x2,&a1)`，返回值放a0|
|ATF param1=0|VCORE 操作，不可当成 release 或能力查询|
|ATF param1=1, mask1..7|request bit0/1/2分别映射资源管理器bit1/2/3|
|ATF mask=0|调用该SCP用户的全部资源释放；不只是释放本次26M|
|ATF资源函数|注册"SCP"用户；request 对目标资源的 user bitmap 做OR，非替换|
|ATF注册失败|存在 a0=0 的提前返回；不能只看返回成功就认定持有|

ATF `FUN_48c1f900` 安装 `FUN_48c1f7ec`（添加用户位）和 `FUN_48c1f764`
（从全部资源清除用户位）；资源请求经全局锁执行。`FUN_48c19c44` 在
非零请求时仅调用前者。没有“先clear再set”步骤，故26M请求不撤销已有
INFRA/SYSPLL等占用。反之 release 会清除全部该用户占用，**本轮不提供**。

V 的 legacy ABI 把mask放x1，若对本机错用 `smc(fid,1,0,...)`，会被解析为
RESOURCE_REQ(mask=0)，导致释放。所以不探测两种ABI，不提供任意参数SMC接口。
本轮也不触发VCORE、ULPOSC校准、恢复、SCP/MD reset 或 IPI。

## 独立只读验证接口

A `lpm/inc/mtk_lpm_module.h`、`mtk_dbg_common_v1.h` 与
`lpm/modules/debug/mt6885/mt6885_dbg_spm_fs.c` 给出：

- `fid=0xc2000507`，`x1=0xda010000 | uid`（SPM debug 用户），`x2=GET=4`；
  x3=index，x4..7=0；数据由a0返回。
- 只用uid11资源数、14用户数、15有效用户bitmap、16用户名、13资源usage。
- 本机资源数6，资源管理器顺序为XO_FPM、CK_26M、INFRA、SYSPLL、DRAM_S0/S1。
  因此**请求mask的26M bit0**与**usage资源索引1**不相同。
- 最多32个用户。逐个名字只比较packed "SCP"，不导出其他名字/用户内容；
  usage只保留SCP自己的六位资源mask，不暴露完整其他用户bitmap。

ATF `0xc2000507` 与32位别名共享调度；SPM debug callback指针表项
`0x48c3c818` 指向 `FUN_48c2491c`，case11/13/14/15/16分别映射上述查询，
最后经 `FUN_48c1fa30` 返回u32。GET不会执行request/clear；部分查询可刷新
ATF内部汇总缓存，故“只读”描述为不改变资源投票，并非ATF内部绝无内存写入。
不调用 debug SET/CLR、bypass 或新用户注册功能。

## 实现与生命周期

新增默认关闭 `OP6893_CCCI_SCP_RESOURCE_HOLD` 与独立 disabled DT 节点
`scp-resource-hold`。内建唯一owner持有TOPCK的受限SCP输出；不与observer
混合，不映射SCP/MMIO，也不在probe发送SMC。禁止unbind，没有remove/shutdown
release；设备重启后重新建立本次boot的状态。当前内核没有第二个SCP vote
调用者。后续共享cfg/IRQ/STOP owner应整合此对象，而非再建平行SMC调用者。

- `state`显式执行两份有界snapshot。每份核对资源数6、用户数<=32、valid/
  usage不越界、SCP名字唯一，前后用户数/valid不变；两份SCP身份/占用一致。
- `pin`只接受字符串`26m`，在mutex下检查TOPCK rate=26M，记录before，
  发送至多一次确切请求，然后读取after并要求SCP存在且有效、既有身份不变，
  after mask恰等于before|CK_26M；成功后复核TOPCK rate。
- 已有SCP用户被bypass时拒绝；缺失SCP用户允许ATF在首次请求时延迟注册，
  但必须在after中查到且有26M占用。未知服务/ABI/截断/不稳定/无效返回均拒绝。
- a0/a1非零、query失败或after不符进入sticky fault；不重试，不发release
  作为rollback。即使错误返回，SMC也可能已产生效果，状态不会假定没请求过。
- pin成功后重复写只返回已有结果，不再次请求。后续state失去用户/资源/时钟
  条件或query失败会使owner失效，不通过重复写“恢复”。
- 该boot常驻pin避免“最后一个consumer退出就释放整个SCP用户”。未来正常
  STOP/reset仍需屏蔽IRQ、排空worker和generation管理后，明确哪些boot继承
  votes可以释放。当前无此证据，始终保留pin，无自动release。

bootstrap observer 的字段改为 `spm_vote_owned=0`，表示**该observer不拥有投票**；
系统投票是否成立以独立resource owner的state为准，避免新增owner后仍报全局0。
TOPCK观测、ATF资源bitmap、真实READY是三种不同证据，不能互相替代。

## 验证计划与记录

`tools/test_modem_scp_resource.py` 使用实际helper和sysfs回调，ASan/UBSan
验证6种资源mask的全部64组合×32用户位、精确SMC寄存器打包、全部查询故障、
错误返回、silent success、lazy registration、身份变化/重复/失效、snapshot变化、
不释放继承占用、sticky fault和时钟前后变化。firmware模型验证逻辑，不证明
设备固件与静态样本相同。新增C/H strict checkpatch为0/0/0。

启用实验镜像 `5393b5915579` 与默认 ARM64 Image.gz/modules 构建通过，
无新增编译警告；defconfig 原有 FW_LOADER/VT 重赋值提示保留。三份 binding
及启用/默认 board、merged DTB schema 检查通过；默认 DT 两个节点 disabled，
默认 config/vmlinux 不含 resource/observer/bootstrap 实验实现。构建临时修改已恢复。

实机先单独读取 state：resources=6、users=1、SCP 不存在，attempted/accepted/
pin_verified/fault 均0。确认后只写一次 `26m`，ATF 延迟注册 SCP user1，
users=2、valid=1、资源 mask=0x02，attempted=accepted=pin_verified=1，fault=error=0。
USB 连续三次、Wi-Fi 一次及最终健康检查均保持相同结果。此次证明当前固件
支持这个查询/请求组合；已有其他 SCP 资源的保留行为仅由静态审计和主机
2048 组合测试覆盖，未在真机额外申请 INFRA/SYSPLL 来制造测试条件。

CCF enable/prepare 均3、名义 rate=26000000；observer 的 spm_vote_owned=0
仍正确表示该 observer 自己不拥有投票。core0/header/mux 观测与前轮一致，
五组 pending/unknown 全0，irq_requested=ack_writes=0，READY 未知。
USB/Wi-Fi SSH、8核、UFS sda/b/c 只读、cache ext4 ro,norecovery、lower
SquashFS ro、overlay root 和 boot 分区完整哈希回读均通过。指定内核故障关键字
扫描无匹配；没有执行温度、按键或 USB 故障切换测试。

设备保留本轮主线及常驻 pin；没有启动 SCP/MD、释放 reset、发 awake、安装
IRQ 或释放资源。下一步建立唯一共享 SCP cfg/completion owner，核对精确写入
责任与 IRQ 屏蔽/排空预算，再接 RX 与 reset generation，最后验证真实 READY。
见 [结构化实测记录](evidence/modem-scp-resource-runtime.json)。
