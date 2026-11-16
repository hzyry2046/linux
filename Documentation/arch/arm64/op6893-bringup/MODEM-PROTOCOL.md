<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 基带：新增分析的接入与待实现协议

2026-11-14，AI 辅助核对。分析输入位于同机目录：

- `/data/src/reverse-analysis/op6893-modem-userspace-analysis.md`，重点
  §11、§12.6.9–14；
- `/data/src/reverse-analysis/op6893-modem-mainline-checklist.md`；
- `/data/src/reverse-analysis/modem-runtime/` 中去标识后的运行记录。

保留原分析目录作为底稿，本文件只记录影响实现的结论与源码复核结果。
没有复制固件、反编译全文、NVRAM 或原始 FS/AT 报文。这些资料中的 Android
运行证据不能视为主线支持；主线目前只完成 LK 交接检查。

## 新增的启动前置条件

MD 固件静态分析还原的查询表中，只有 id 0 是 MUST，其他多数为 OPTIONAL。
**这只描述协商请求，不表示协商之后缺少数据也能运行。** 报告定位了
BOOT_INFO、exception、CCIF、CCISM、CCISM_EXP 和 NVRAM cache 的消费/断言路径。
实际实现仍以 V 的可用启动栈为底本，建立各 region 的地址视图、长度、保留区
归属及清零生命周期，再生成对应 runtime feature；不能用非零地址或虚假的
SCP READY 替代资源。

尤其保留 `SMEM_USER_MD_NVRAM_CACHE`（feature 36），不能因为名字是 cache
就省略。早期 M0 仅校验粗粒度布局；后续 [SMEM](MODEM-SMEM.md) 已解析该子区、解释
缓存 `0x80000` 差值并上机核对。布局存在仍不证明 NVRAM/FS 服务实现，
不能新增重叠 DT reservation 或仅凭地址就宣称支持。

## 已对照源码的协议细节与报告冲突

源码路径 A 为 `/data/src/kernel_oddo_mt6893/drivers/misc/mediatek/eccci/`，
V 为 `/data/src/6.6-exp/android_kernel_modules_oneplus_mt6833/kernel/` 下的
`kernel_device_modules-6.6/drivers/misc/mediatek/eccci/`。

| 项目 | 复核结果及实施约束 |
|---|---|
| 特征 TLV | A/V `inc/ccci_modem.h:struct ccci_runtime_feature` 有 2 字节 reserved，len 在 +4，payload 在 +8。不能按紧凑的 6 字节头编码；reserved 清零，长度与剩余空间先检查 |
| 两个魔数 | MD 查询为 `0x49434343`，AP 查询为 `0x43434349`；按明确的小端字段编码，避免直接搬 C bitfield 作为通用 wire ABI |
| 64 槽与连续编号 | A `ccci_modem.c:ccci_md_prepare_runtime_data()` 遍历 FEATURE_COUNT=64，并为不支持项追加长度 0 的条目。固件静态分析要求至少连续 45 项；实现保留 64 槽，不只发送非空项 |
| `0xac` 与 `0x9c` | A `modem_sys1.c:md_cd_send_runtime_data_v2()` 将 `sizeof(ap_query_md_feature_v2_1)` 与 16 字节 CCCI header 相加。v2.1 结构为 0x9c，tail 在结构 +0x98，整包为 0xac。不能把 0xac 当作该结构自身大小，更不能把它当成 SMEM feature TLV 区总长 |
| RTC_32K_LESS 极性 | A `ccci_modem.c:config_ap_side_feature()` 在检测到 crystal 时设 NOT_SUPPORT，反之 MUST（ENABLE_32K_CLK_LESS 条件内）。新报告 §12.6.11/清单 §4 把 MUST 解释为“有晶振”，与源码相反；保留 MUST/NOT_SUPPORT 限制，但不能照搬该极性，也不能用 CONN 的 26 MHz strap 推导此项 |
| MUST 与空数据 | 报告提示共享内存消费端可能使用未初始化值。对有 payload 的 MUST 项必须提供有效长度和完整数据；NOT_SUPPORT 的空条目仍需发送。不要把“不支持”改成空 MUST |
| HS2 与通道 | A `fsm/ccci_fsm.c:ccci_fsm_recv_control_packet()` 在同一控制端口按 MD_INIT_START_BOOT 的 reserved 值区分 HS1/HS2。`AT_CHANNEL_NUM` 从 MD runtime data 读取用于 ioctl 查询（`fsm/ccci_fsm_ioctl.c`），不能据此直接推出“HS2 必须改为 MD 动态给出的 AT 通道”。报告对 MD 内部通道变量的解释仍需与控制端口/BOOT_INFO 对齐后采用 |
| 特征编号 | A 枚举到 id 38；V 还有后续项。使用本机固件 ABI，不把 V 新增项全设为支持；未知项仍保留空槽 |

报告对“MD 消费 21 项”的文字计数与其列出的编号不一致；当前列出 23 个编号。
实现按逐项的源码和数据结构复核，不用该计数作为循环上限。静态扫描“未发现
消费者”也不作为删除 wire 槽或跨固件保证的依据。

## 文件服务和用户态接续

新运行资料证实 `ccci_fsd` 是 `ccci_mdinit` 内部线程，正常启动就存在 NVRAM
写入，而不只是可选的日志服务。后续 Linux 用户态方案需做到：

1. 在 FS 服务和 NVRAM 工作目录准备完成前禁止释放 MD。若复用 Android
   二进制，保留 nvram_init Ready/Pre_Ready、进程名白名单与 ioctl 行为；自写
   管理器也必须实现同等门控，不能只发 DO_START_MD。
2. 首测在私有完整工作副本上服务 NVRAM，原始分区不作为可写后端。保留
   `_`、A、B 等所有文件；不按 LID 名称去重，不修改文件头、校验或记录内容。
3. FS 操作码、4 字节参数对齐、UTF-16LE 路径、分片和应答序号分别实现有界
   解析。句柄不能硬编码为 1；一次 trace 中恒为 1 不代表协议不允许并发句柄。
4. 正常启动观察到的 13 类操作是首批覆盖集合，不是全部协议。未知操作明确
   返回协议错误，不假成功；路径缺失用协议错误码而非 Linux errno 的裸值。
5. 保留 Close 在 Open flags 包含 `0x01000000/0x10000/0x20000` 时的 fsync
   语义，正确处理短读、短写、无效句柄和落盘失败。
6. AP libnvram 与 MD FS 访问同一目录而无跨进程文件锁。初期避免并行运行
   两套写入者；运行期写入、重启和恢复采用同一套后端所有权策略。

本机缺少证书/运营商配置时 Android 仍可注册，只能说明这些具体缺失不是该次
启动故障。不能把所有 FS ENOENT 当成功，也不能据此忽略必须的校准数据。
当前不搬入 RIL、Android 属性服务或 FS daemon；先完成供电/SCP/CCIF/FSM，
再根据目标 Linux rootfs 选择兼容运行环境或最小用户态实现。

## TODO

- [x] SID3 shutdown/启动电压生命周期与统一MD平台owner；接管/冷循环已实测。
- [x] 逐子区解析LK SMEM，包含NVRAM cache与0x80000差值，并已实测。
- [x] 有界runtime编解码、保留位/连续ID/版本/长度、0xac整包与v2.1结构边界，
  接入实际CCIF TX和有状态consumer，见[实现](MODEM-RUNTIME-HANDSHAKE.md)。
- [x] 对照BOOT_INFO控制RX0与HS2，区分AT_CHANNEL_NUM计数；尚需实际MD验证。
- [x] SCP client与后置CCISM协议core，见[实现](MODEM-CCISM.md)；不等待CCISM完成才放行MD。
- [x] CCIF2硬件/SMEM owner、system端口及有界事件worker/timer已离线整合，见[CCISM](MODEM-CCISM.md)；尚无arm caller或硬件通信验收。
- [x] FS/RPC codec、回复TX、有界generation/token路由与私有副本原型，见[服务基础](MODEM-SERVICES.md)。
- [ ] Linux服务入口/worker、完整FS语义与硬件RPC provider、真实能力门控及MD CPU/DMA停止原语。
- [ ] FS私有工作副本、RPC/端口服务和能力表，先合成请求测试，再合并放行MD。
- [ ] 真实HS1/HS2、异常/停止验收；当前仅离线consumer，不代表基带可用。
