<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 SCP bootstrap 时钟与共享资源边界

2026-11-15，基于 `6db0f4606d6e` 工作树，AI 辅助实现与源码核对。
接续 [mailbox pending 预检](MODEM-SCP-PENDING.md)。本文件的构建和硬件
验证状态以末尾记录为准，源码设计不代表 SCP 已运行。

## 受限的 TOPCK 输出

在现有 `clk-mt6893-pmif.c` 中增加默认关闭的
`COMMON_CLK_MT6893_SCP_BOOTSTRAP`，使用 vendor 的 `CLK_TOP_SCP=119`。
没有提供 `SCP_SEL=191` 的完整八父时钟 mux：其余 PLL 尚未归主线管理。
26 MHz 父引用使用 TOPCK 已有的 `clk26m` 输入，不新增固定频率占位时钟。

注册前检查输入确实为 26 MHz，selector[18:16]=0，gate[23]=0。CCF 首次
使能时，在现有 TOPCK mux spinlock 下两次检查该条件，只向 `CLK_CFG_0_CLR`
偏移0x18写 bit23，随后读回条件。任一读取或写入错误均返回；观察到其他
selector 或 gated 条件返回 EBUSY。不会写 mux、SET、UPDATE、reset 或 SCP。
共享 syscon 和既有 PMIF mux 使用同一 regmap/锁；可选 SCP 注册失败仅留下
不可用的 SCP 输出，不撤销已有 PMIF 时钟，避免破坏供电通信。

该输出保留 `CLK_IS_CRITICAL` 引用，disable 回调明确不关硬件；当前既没有
SCP STOP/reset 的完整 owner，也没有可证明安全的最后引用关钟条件。
consumer 失败/退出只平衡自己的引用。provider 与既有 TOPCK 一样内建、禁用
unbind；不实现挂起、频率调整或父时钟切换。失败时不尝试把已继承的时钟
关掉。该临时策略需要在真正的共享 SCP 生命周期实现后替换。

独立默认关闭 `OP6893_CCCI_SCP_BOOTSTRAP_HOLD` 使 observer 在发布 sysfs
之前用 `devm_clk_get_enabled()` 持有该输出，并检查实时 rate=26000000。
`bootstrap` 属性再次验证源/gate，输出 consumer_hold、provider_critical，
同时明确 spm_vote=0 和 ready_known=0。启用前置条件失败则不发布观测入口。
已有 core0/header/pending 的前后 mux、core0 核对仍保留。

CCF 引用只约束本驱动管理的 TOPCK 输出；不能阻止固件自行改变时钟，也不能
替代 SPM 对 oscillator 的资源投票或 DVFS。因而这一步尚未闭合全部访问前提。

## 必须分开的三条资源路径

|资源|同板 4.19 契约|后续管理责任|
|---|---|---|
|TOPCK 输出|CLK_CFG_0 16..18/23，CLR0x18|既有 TOPCK provider；本次仅继承26M的常驻 hold|
|SPM 26M vote|scp_dvfs.c 的 scp_resource_req(SCP_REQ_26M)|唯一共享 SCP owner 持有并管理释放，不能由各 mailbox 独立投票|
|RX completion|scp_awake.c 的 scp_clr_spm_reg()，SCP cfg+0x94 写1|唯一 SCP cfg owner，在 RX copy 后、mailbox ACK 前调用|
|AP awake|infracfg SET0xb14/CLEAR0xb18，lock/unlock bits|已有 awake backend，由共享 owner 在真实 READY 后统一串行调用|

SPM vote 通过 SMC，**不是**给 TOPCK 引用增加一次 enable：A 的 MT6893 分支
使用 SCP_DVFS_CTRL 的 RESOURCE_REQ 子命令，26M mask=bit0。V 同板6.6区分
legacy_support_v1，新旧 ABI 参数位置不同，缺失 scp-dvfs-disable 属性曾导致
初始化与初始资源请求被跳过。下一轮须核对本机实际 ABI/返回值及共享释放责任，
不能照搬默认成功或使用 bool 代替投票。此轮不发 SMC。

completion 与 AP awake 也不是同一个寄存器。A 的 cfg=0x10724000，completion
地址0x10724094。V 的 cfgreg_ap_en 改用 cfgreg_ap+0x18，ipc_wa 还清 GPR7；
当前历史 FDT 无这两个 opt-in，不能据 V 代码无条件引入它们。本轮不映射
SCP cfg，不写 completion。之后由同一个 owner 独占 cfg 资源，不为每个 RX
mailbox、CCCI 或 sensor 客户端分别建立重叠映射。

共享 owner 的 STOP/reset 顺序仍待实现：拒绝新事务，屏蔽接收 IRQ，停止并
排空 worker，使旧 generation 失效，再处理 awake/clock/vote 的生命周期；
硬件状态不明时进入 fault，不能重用旧 READY。completion 不能依赖 READY 后
的 awake，否则 READY 消息本身的处理会形成循环依赖。IRQ 回调只做必要的
屏蔽/调度，sleepable awake/vote 与事务放在受生命周期锁保护的 worker 中。

## 验证记录

新增主机用例 `tools/test_modem_scp_bootstrap.py` 编译实际时钟回调，用
ASan/UBSan 检查全部 selector/gate 组合、三处读取故障、写入故障、写后
条件变化、相邻字段、精确 bit23 写入与 disable 不关钟，以及 live rate
拒绝无效源。它不模拟完整 CCF 或证明 SPM 投票生效。

启用镜像 **6d783d7288f4**（`7.3.0-op6893-d1-6d783d7288f4+`）与默认
Image.gz/modules 构建通过。binding 文档、启用/默认 board/merged DTB 的
定向 schema、FDT 合并及既有 observer/core0/TCM/pending/RX/awake 主机
回归通过。编译器警告0；默认配置仍有已有 FW_LOADER/VT 重复赋值提示。
observer strict checkpatch 为0/0/0；clock 全文件有4处原有对齐 CHECK，
新增回调的对齐 CHECK 已修正，无 error/warning。

已预先排队 boot flash/reboot，用户配合 sync+SysRq 后的 fastboot 拦截。
boot 回读 SHA256 与 artifact 相同，不更改分区表或 ACK 恢复备份。

|实机项目|结果|
|---|---|
|bootstrap consumer / critical hold|均1，CCF nominal rate=26000000|
|consumer unbind 前 enable/prepare count|2/2|
|consumer unbind 后 enable/prepare count|1/1，CCF rate仍26M|
|consumer rebind 后 enable/prepare count|2/2，所有观测入口恢复|
|selector/gate|0/0，前后校验通过|
|68-byte header / core0 / 五组 pending|与前轮相同，pending/unknown均0|
|USB SSH / Wi-Fi SSH|均可读 bootstrap/pending|
|CPU / 存储 / rootfs|8核；sda/sdb/sdc RO=1；cache ext4 ro/norecovery，lower SquashFS，overlay根目录|
|最终 kernel fault 扫描|未见 BUG/Oops/SError/panic/Unable to handle 或 critical enable 失败关键词|

首次读取 clk_summary 时 debugfs 尚未挂载，未把读取失败算作验收；挂载后
取得上表真实计数并执行 unbind/rebind。重复 USB 与 Wi-Fi 观测成功。
这证明当前 CCF 引用与 consumer 生命周期符合本轮目标，不代表固件不能
改钟或 SPM vote 已生效。没有启动 SCP/MD、安装 IRQ、发送 awake 或接受
READY。未测试温度/按键/USB 故障切换。设备最终保留此主线镜像。

构建后 DTS/defconfig 已恢复：节点 disabled、两个选项默认关闭，默认
vmlinux 不含 observer/bootstrap 注册符号。运行镜像的原始源码快照保留在
不可变 dist artifact；本文的结果记录是构建后补充。

机器可读证据：[bootstrap runtime](evidence/modem-scp-bootstrap-runtime.json)。
下一步先审计并建立实际 SPM 26M vote 和共享 cfg 生命周期，再接 IRQ owner。
