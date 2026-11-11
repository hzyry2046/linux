# MT6635 TOP070：固定值写入/恢复实验

2026-11-04。AI 辅助源码审计、实现及主机测试；无外部提交或 AI DCO。
本文件描述 `adie-pad-cycle` 的实验边界，不代表 Wi-Fi 或电气 HighZ 已验证。

## 源码依据与限制

本地 6.6 模块树的
`conninfra/conn_drv/connv2/platform/mt6893/mt6893_pos.c`：

- `connsys_a_die_cfg_mt6893()` 在 efuse/thermal 之后将
  `ATOP_RG_ENCAL_WBTAC_IF_SW`（TOP070）整字写为 `0x80000000`，
  注释为 WF_PAD HighZ。随后依次配置 CAL LDO、XTAL 和 THADC。
- `connsys_afe_wbg_cal_mt6893()` 执行 RC/TX 校准并关闭触发后，将
  同一寄存器写为 `0x5`，注释要求在 WBG cal 后初始化 BT path。
- `consys_spi_write_mt6893()` 获取 RFSPI semaphore，调用底层写函数后释放。
  底层检查 busy、写地址及数据、再次检查 busy；没有目标寄存器读回。
  上述两个调用点不检查写函数返回值，不能直接当作可靠恢复实现。

`/data/src/6.6-exp/android_kernel_oplus_mt6893` 与
`/data/src/kernel_oddo_mt6893` 的 MT6893 源码具有相同两次写入。
这些实现有共同来源，不能视为独立硬件规范。

新增交叉依据：后一个树的 `platform/mt6983/mt6983_pos_gen.c`，
`connsys_afe_wbg_cal_mt6983_gen()` 的 **ADIE_6635 分支**在校准前写
`0x80000000`，校准后写 `0x5`，后者注释为 `restore CR initial value`。
它支持这对固定值的使用，但没有证明本机当前值为 5，也没有证明
跳过校准的往返在电气层面等价。不可将 MT6637 分支或 MT6895 的相同
数值当作 MT6635 位定义。未找到 TOP070 的逐位定义、W1C/自清属性说明、
任意旧值回写流程或异常恢复流程。现有逆向 REPORT 没有补足这些内容。

## 已实现的有界实验

新增 root-only、每次启动仅一次的 `adie-pad-cycle`，保留 `adie-pad-read`。
复用第90轮全部准备、efuse/handoff/清除、thermal 和新鲜 trim no-op 检查。
重复 TOP070 读取完成后必须**完整等于 0x5**，才允许写入；其他基线拒绝。
不把历史读数或前一次启动的 no-op 结果当作本轮前提。

1. 写固定 TOP070=`0x80000000`；触发前置 dirty。
2. ID→TOP070→ID→CTRL，要求独立响应、目标整字相等和控制值稳定。
3. 写固定 TOP070=`0x5`；不允许调用方传入地址、掩码或旧值。
4. ID→TOP070→ID→CTRL，要求恢复整字相等、最后 guard 通过后清 dirty。
5. 完成原有父资源清理。

新增十笔传输（两写、八读）。每次写地址后检查地址读回；写 busy 不替代
目标读回。任意失败停止，不重试应用或猜测恢复；置 unsafe，保留父资源
直至设备复位。即使恢复读回为5，后续 CTRL/guard 失败仍不清 dirty。
基线拒绝也沿用现有保守保留策略；它不是一次成功完成的周期。

状态仅报告基线是否为公开常数5、写 issued 位图、applied/restored/dirty，
临时响应显式清除。`pad_target_match` 仍描述写入**之前**的基线比较；
`pad_applied` 才描述新写入的验证。`pad_complete` 对 cycle 表示往返完成，
不表示将 HighZ 配置保留给后续校准，更不证明实际 pad 电压或驱动状态。

共享数据阶段预算仍为2秒，起点不变、不在恢复时重新计时。第90轮实测
已用约1.554秒；这只提供样本余量，不保证新增流程一定能在截止前完成。
超时同样保留资源，不能因“正在恢复”绕过 deadline 或所有权检查。

## 验证边界

`tools/test_conn_adie_pad_cycle_integration.py` 提取真实 C，嵌套沿用
前序模型。覆盖正常往返、三个非支持基线、新鲜 trim 拒绝、20处丢写、
80处 guard 失效、10处 SPI 超时、两次目标读回错误、两次 deadline、
两次 CTRL 改变、15处父资源清理失败、无 busy 脉冲、一次性拒绝及清除。
模型只能验证软件控制流，不能替代模拟电路行为或实机验证。

本轮不执行 CAL LDO/AFE 校准，不启动固件。后续必须将实际基线拒绝、
传输完成但读回不符、超时和成功往返分别记录，不能统称 Wi-Fi 初始化成功。

## 后续修订（attempt92-94）

attempt91 因基线不是0x5被拒绝；实测基线为0x0。门限和恢复值已改为实测0x0，
该命令的数据预算改为3秒（只读命令仍为2秒）。attempt94 实机往返通过。
上文关于“基线必须为0x5”的描述仅反映attempt91的设计。
