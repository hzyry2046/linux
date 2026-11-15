<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 SCP RV：mailbox 布局与 CCISM 协议基础

2026-11-15，基于 `6db0f4606d6e` 的工作树，AI 辅助实现和验证。
接续 [资源契约](MODEM-RESOURCES.md) 和 [供电验收](MODEM-RAILS.md)。
本轮新增默认关闭的纯协议 helper，没有操作设备或打包/刷写新 boot 镜像。
该轮测试结束时设备运行 `7576d31c76a4`，其中不含本轮 helper。
后续用户已刷回 Android 供分析 agent 使用；当前只离线推进，不重启/刷写。
新增 [TCM 元数据与恢复映射校验](MODEM-SCP-MEMORY.md) 同样不含硬件入口。
随后完成 [共享 AP awake 后端及上机边界](MODEM-SCP-AWAKE.md)，没有现存
硬件调用者；下一步先核对真实 READY、固件与内存，不直接试发 IPI。

## 已实现的边界

`drivers/misc/mediatek/ccci/ccci-scp-protocol.{c,h}` 由独立 bool 选项
`OP6893_CCCI_SCP_PROTOCOL` 控制，默认 n。不依赖 M0/供电检查器，也没有
probe、IRQ、notifier、全局 READY 状态或 module init。

- `ccci_scp_build_layout()` 接收已转为本机端序的 TX 三元组与 RX 四元组。
  在分配偏移前检查完整元素数、邮箱数量、通道范围、非零消息长度、response
  标志和邮箱排序；拒绝同一方向重复 ID、容量超限和不完整表。失败清空输出。
- 按本机 RV 的 64 位规则布局：每条消息的 u32 word 数向上对齐为偶数，
  每个 mailbox 先放所有 TX，再放所有 RX，共用 64 words / 32 个 IRQ bit。
  IRQ index 为起始 word offset / 2，不能直接使用 channel ID。
- `ccci_scp_apccci_pins()` 从完整有效布局定位 TX channel 3 与 RX channel 7。
  TX 只接受已核实的 2 或 4 words，RX 只接受 2 words 且不是 response pin。
  缺失或不支持的格式明确报错，不返回替代 channel。
- `ccci_scp_encode()` 明确按小端编码 `u16 md_id=0`、`u16 op`、`u32 data`，
  支持 MD_STATE=1 与 SHM_INIT=2。2 words 是本机 8 字节消息；4 words 是 V
  桥已实现的附加 magic 格式，尾部依次为 `0xabcddcba`、`0xaabbccdd`，
  不能因支持该编码就改变本机 channel 的 2-word 配置。返回实际字节数，
  缓冲不足或非法参数时不修改目标；允许 CPU 缓冲区不对齐。
- `ccci_scp_decode_state()` 只接受 8 字节、md_id 0、op 0 和 BOOTING=1、
  RBREADY=2、STOP=3。输出只是校验后的消息值，**不接受 FSM 状态转移**，
  也不将解码 RBREADY 当作 SCP/CCISM 已就绪。
- `ccci_scp_shm_u32()` 校验非零且 4 字节对齐的地址/长度及整个跨度可由
  u32 表达，拒绝高位截断、末端越界或加法溢出。它不做 AP/MD/SCP 地址
  翻译，不证明区域的保留、EMI 权限或可写所有权；未来 consumer 必须先
  校验这些条件，再使用输出地址编码 SHM_INIT。

只支持本机已核实的 64 位 mailbox 与旧四单元 RX 格式，不推测 CM4、32 位
mailbox 或 V 新七单元 RX 配置。输入大小和 64 个 channel 的上限是本实现
的有界策略，不表示芯片恰好提供 64 个 IPI channel。

## 本机表的精确结果

保存的 ACK DT `/scp@10700000` 有 14 条 TX、17 条 RX，5 个 mailbox。
旧属性为 `send_table`、`recv_table`、`mbox_count`；V SCP helper 为旧属性提供
了下划线兼容读取，但 V CCCI 桥的发送长度查找直接使用 `send-table`。
后续主线 transport 应统一读取一次并发布验证后的布局，不能让桥重新以
另一组属性拼写解析出不同 channel 大小。这里的 helper 本身不查找 DT。

|mailbox|使用 words / 64|
|---|---|
|0|38|
|1|64|
|2|64|
|3|36|
|4|64|

|方向|channel|mailbox|word offset|字节 offset|IRQ bit|消息字节|
|---|---|---|---|---|---|---|
|AP → SCP APCCCI|3|1|0|0|0|8|
|SCP → AP APCCCI|7|1|28|112|14|8|

**必须保留整张表的布局**，即使第一批只注册 APCCCI handler，也不能删除
音频、DVFS、logger 等表项后重新分配偏移。mailbox 1 的 APCCCI RX 在所有
TX 之后，任意忽略其他 TX 的做法都会改变其起点。RX 中也存在与 TX 同 ID
的 response pin，因此去重仅限同一方向，不能跨方向拒绝所有重复 ID。

DT 表是保存的历史 fixture，不代表本次 SCP 固件已经启动或正使用这些表。
未来上机时仍需证明固件版本、启动方式和表的对应关系。

## 验证

`tools/test_modem_scp.py` 编译实际 helper C，通过 ASan/UBSan 运行；默认
使用已审计且不含固件数据的 DT 投影。可选保存 DTB 只读取三项 mailbox 表，
同时存在新旧拼写时要求一致，不读取任何物理内存。

```sh
python3 Documentation/arch/arm64/op6893-bringup/tools/test_modem_scp.py \
  --lk-dtb /data/src/mainline/mt6893-direct/evidence/ack-live.dtb \
  --vendor-scp /data/src/kernel_oddo_mt6893/drivers/misc/mediatek/scp/rv \
  --vendor-scp /data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/kernel/kernel_device_modules-6.6/drivers/misc/mediatek/scp/rv
```

- 对保存 DTB、审计投影及上述 mailbox 占用、APCCCI 两个精确位置分别断言。
- 直接编译 A、V 的实际 `mbox_setup_pin_table()` 为两个独立 oracle，对本机
  表及 10,000 组有效随机完整布局，逐 pin 比较 offset/IRQ index。
- 不完整/超长/null 表、0 或过多 mailbox、非法 ID/size/response、同向重复、
  未排序、总容量越界及最后合法 IRQ bit 31；失败输出清零。
- 20,000 组有界非法输入经过 sanitizers；APCCCI 缺失、错误消息字数和
  response 类型拒绝，跨方向同 ID response 允许。
- 独立 wire 字节向量验证 8/16 字节格式、magic、不对齐缓冲、短缓冲不写、
  非法 op、MD state 值与 SHM 地址；RX 要求精确长度、ID、op 和状态范围。
- u32 地址边界、整个跨度跨越 4 GiB、u64 溢出候选和未对齐地址/长度拒绝。

实际 ARM64 启用/默认关闭构建、checkpatch 和源码指纹记录在
[验证清单](evidence/modem-scp-validation.json)。外部构建器已加入本测试并归档
`modem-scp-tests.log`。这些主机用例不模拟 mailbox MMIO、IRQ、硬件锁、
固件消费、awake/DVFS 或跨核并发；编译 helper 也不证明 SCP 可运行。

## 下一阶段接入顺序

1. **资源与固件**：SCP SRAM、mailbox base/set/clr/init 独占范围；clock 和
   infracfg awake 通过共享 provider，不能重新占用已有 syscon 区域。核对
   TCM region header 的版本/单位和允许 DRAM 范围；区分静态 SCP mblock
   与动态 `scp_share` 分配。真实固件来源、加载/保留/恢复责任仍待闭合。
2. **mailbox transport**：消费一次验证的完整布局，按 pin offset/IRQ bit
   注册与收发；读写限于 pin 的长度，处理 busy/ACK、屏障、有界等待和
   中断排空。SCP awake 失败时不继续发送；不可用的时钟不能用成功桩替代。
3. **SCP 状态生命周期**：真实 READY IPI、BOOTING/RBREADY 与 remoteproc
   notifier 分开；STOP/重新加载时注销接收、排空 worker 并使旧代消息失效。
   尚无该状态机，当前 decoder 不对重排或跨重启事件作有效性承诺。
4. **CCIF2 与 CCISM**：唯一 owner 管理桥时钟与 ACK，MD 活动时拒绝关闭。
   真实 MD INIT_ACK 后，才允许在验证的 CCISM 区域执行清零并发 SHM_INIT；
   收到本代 RBREADY 后发 INIT_DONE，等待 MD 完成再同步状态。每个操作成功
   后再推进状态，失败不标记 ready；不复用 V 中忽略部分错误的处理方式。

在这些依赖与启动电压恢复闭合前，保持 MD 复位。下一轮先推进资源/固件
契约与 transport，不需要为本轮纯 helper 测试重启设备。
