<!-- SPDX-License-Identifier: GPL-2.0-only -->
# 本机 bootstrap runtime 数据与服务接续

2026-11-16。基于 `7a7364b05` 离线接续，新增 typed runtime payload builder、
本机审计 RPC 常量及显式用户 RPC 后端。没有设备访问、刷机或 MD CPU release。
现有默认配置不变，新能力仍由默认关闭的 HANDSHAKE/SERVICES 选项控制。

## Typed runtime payload

`ccci_runtime_bootstrap()` 接受经既有 parser 验证且未修改的 SMEM layout 和明确
的启动信息，构建 64 个 offers；未知能力保留不支持。它只生成 metadata，不
映射、清零或宣称服务已准备。调用 owner 必须先完成对应窗口初始化、SCP lease、
私有 FS 与所需 RPC 后端，然后才可把这些 offers 用于启动。

|Feature|来源/布局|
|---:|---|
|0 BOOT_INFO|16B：control RX channel0、调用者明确提供 vendor booting_start_id、其余0|
|1 EXCEPTION|从 SMEM user12 起的 **64KiB**，不是 user12 自身的2KiB|
|2 CCIF|user19 普通环窗口的 MD 地址/大小|
|6 RTC_32K_LESS|明确无外部32k晶体时支持且16B payload全0；有晶体时不支持|
|14 CCISM|user16 的 MD 地址/大小|
|27 MULTI_MD_MPU|合法零 payload flag|
|28 CCISM_EXP|user20 的 MD 地址/大小|
|36 NVRAM_CACHE|cached user32 的 MD 地址/大小|

来源为本机 A `eccci/ccci_modem.c:1798–1814,2119–2151,2205,2248,2364,2453`
及 `eccci/ccci_common_config.h:26`（64KiB）。文件哈希沿用
[cache审计](MODEM-NVRAM-CACHE.md)和[板级RPC审计](MODEM-RPC-BOARD-FACTS.md)。
BOOT_INFO 起始值遵循 A `ccci_modem.c:1585–1646` 的 logging/wait/bootmode编码；
builder 不猜值。32k 策略遵循 vendor，而不是旧分析文字中相反的“有晶体即支持”
解释。A `ccci_rtc.c` 从 `external-32k` nvmem 取得事实；不能由 CONN 26MHz、
旧静态默认0或函数命名猜测，因此 UNKNOWN 输入直接失败。

builder 完整校验 AP/MD bank 和 region 对应、属性、非空、边界与广告窗口重叠，
exception 扩展64KiB还不得覆盖 CCIF/CCISM/NVRAM 窗口（其中 runtime/debug 小区
本来位于 exception aggregate 内）。全部输入先验证；失败清零整个 offers。
实际 C sanitizer 同时复用 handshake/controller/RX/TX 回归，检查 wire 小端、
有/无晶体协商结果、所有必需 region 故障、异常 aggregate 跨界/重叠。
尚无调用此 builder 的活跃 MD owner，也不把能生成包当成 ready gate。

## 本机 RPC 与用户后端

当 SERVICES 启用且 machine 为 `realme,op6893` 时，父构造路径在 reserve 前
安装不可变板级快照：15 个 GPIO规范请求名、SIM1 EINT向量、DTSI3项。
来源为本机保存 ACK FDT，与已用6.6保存FDT逐项一致；不是当前采样或任意
MT6893 的通用值。ADC名无关模式及其余硬件操作保持不可用。
见[事实来源和适用限制](MODEM-RPC-BOARD-FACTS.md)。

修正此前 EINT 错误码：C enum从 -13 **递增**，QUERY_TYPE=-12，
QUERY_STRING=-11。旧提交实际 C 在新 vendor-enum 测试下断言失败，修正后
provider/endpoint/board sanitizer通过；独立 fix commit 带 Fixes 指向原提交。

用户操作 `0x400f/0x4010` 已有纯 provider 与显式 runner 接线；不读 Android
property、不自动生成或选择 SAR 策略。`--rpc-policy` 可选，未指定时保留 FS-only
行为。指定时，在打开 WorkingCopy 和 endpoint 前一次性加载私有 JSON：普通
单链接文件、当前 UID、0600、至多64KiB、禁止符号链接和重复 JSON 字段。
它不会从权限或“文件存在”推断事实正确或服务已就绪。

配置 schema 为 `version:1`，可选 `properties`（准确 key→字符串，null只表示
调用者已核实不存在）、`sar`（`product_hw`、`regionmark`、完整 `projects` 表：
project→region→u32 index）。不提供真实示例值。所有字符串转UTF-8 bytes，
SAR表与属性快照 immutable；未知属性或缺失provider关闭endpoint而非伪答。
SAR已配置完整表但确实不匹配时，按 AP ELF 返回status0/index0xffff，绝非默认0。
完整适用 SAR 表和本机实际 property 输入仍需准备，不属于本轮已完成部署。
详见[用户RPC wire和策略证据](MODEM-USER-RPC.md)。

runner 保留 generation/token/slot/record 校验、一次完整read/write、短写不重试、
所有退出关闭endpoint和固定错误日志。新增混合FS/RPC合成测试及14项runner
回归；pure RPC另有7组测试，含 actual C codec 验证Python回复兼容性。

## Cache与下一步

[cache审计](MODEM-NVRAM-CACHE.md)撤销了未经证明的“AP必须预填cache”要求：
本机 A 首次启动整区清零、后续 reset 保留；feature36只发布地址/大小。
当前仍需唯一owner映射、首次清零及 stopped-only 生命周期，不能照搬qqcandy
原始分区loader，也不能发自造cache header。MD经FS管理cache是有来源推断，
全局header/重建时序仍未独立证明。

接续聚焦剩余实际调用路径：cache首次清零、32k事实取得、ADC单channel契约、
真实用户策略与私有工作副本准备、CPU/DMA启停和异常停止顺序。闭合后合并首次
MD放行/HS1/runtime/HS2/CCISM测试；无需为本轮 metadata 或纯provider单独刷机。
验证记录见[evidence/modem-bootstrap-contracts-validation.json](evidence/modem-bootstrap-contracts-validation.json)。
