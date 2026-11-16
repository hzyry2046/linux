<!-- SPDX-License-Identifier: GPL-2.0-only -->
# MD 放行门槛、cache owner 与首次启动入口

2026-11-16，基于 `d99a965f6` 离线接续。新增默认关闭的
`CONFIG_OP6893_CCCI_NVRAM_CACHE` 与 `CONFIG_OP6893_CCCI_MD_BOOT`。
本轮没有刷机、SMC 放行、设备寄存器访问或蜂窝验收；设备仍运行 Android
厂商内核，最后已知主线镜像为 `8ec93b17bbb5`（MD1 OFF、MD CPU 未放行）。

## 新增的所有权

| 模块 | 责任 | 不做什么 |
|---|---|---|
| `ccci-nvram-cache.c` | 唯一映射 feature 36 的 cached user-32 窗口，按本机 A 首次启动策略清零一次 | 不加载 cache 镜像、不合成 header、不导出内容、不在重连时再次清零 |
| `ccci-rtc32k.c` | 从 `external-32k` nvmem cell 或显式板级 DT 事实取得 32k 晶体事实 | 不由 CONN 26 MHz、静态零或函数名推断 |
| `ccci-md-boot.c` | 唯一 ready gate、runtime offers、一次 `(6,0)` CPU 放行、停止顺序 | 不在 probe 自动动作；不接受软件状态作为停止证据 |

父 `ccci-md-platform` 仍持有电源、时钟、CCIF、SCP lease 与所有对象，
新增只读 `md_boot` 状态和写入口。

## Ready gate 与顺序

`md_boot prepare <generation>` 在父锁内按以下顺序执行，任一步失败即锁定
`failed`，不继续：

1. `ccci_ccif_prepare()`：格式化并校验 32 个环、复位 CCIF0、写入共享 SRAM
   footer；IRQ 保持 masked。
2. `ccci_nvram_cache_prepare()`：映射 cached user-32 窗口并整区清零，读回
   首尾字确认映射可用。
3. `ccci_runtime_bootstrap()`：用已验证的 LK 布局生成 64 槽 offers
   （0/1/2/6/14/27/28/36），32k 极性来自上表事实。
4. `ccci_port_dispatch_prepare()`：预留已连接的独占 FS 后端，并取得真实
   SCP/CCISM lease。

因此 `dispatch` 的 reserve 同时是“私有 FS runner 已连接”的门槛：
没有 runner 打开 `/dev/ccci-service-<devname>` 时 prepare 失败，不会放行 MD。

`md_boot release` 先启动普通 CCIF RX 与握手 controller（进入 WAIT_HS1），
然后才发 `MTK_SIP_KERNEL_CCCI_CONTROL(6,0)`。SMC 返回非零或
`NOT_SUPPORTED` 记为失败，不把“已启动接收”当成放行成功。

## 停止顺序与证据

物理约束：`ccci_ccif_stop()` 会写 CCIF 硬件，必须在时钟仍开启时完成；
dispatcher 的 endpoint/bridge 清理必须在 MD 真正停止后执行。因此父
`md_power off` 的活动路径为：

1. 读取 SPM PCM REG13（`0x10006110`）仅作诊断记录；bit2 为 0 表示
   vendor `spm_is_md1_sleep()` 语义下的 MD1 sleep。
2. `ccci_ccif_stop()`：停止 TX/RX/controller 并复位环。
3. `ccci_md_power_off()`：MD1 MTCMOS OFF，并以六个寄存器独立读回
   （PWR_STATUS bit0=0、PWR_ON/RESET_B=0、隔离=1、三组保护 ACK=1）
   作为硬件停止证据。
4. `ccci_md_boot_stop(true)`：dispatcher 的第二次 `ccci_ccif_stop()` 在
   `prepared=false` 时提前返回；随后停止 service endpoint、擦除请求与回复，
   再执行 bridge STOP、等待 SCP 回复并 offline。

RX 关闭、controller 故障、generation 变化或 SPM 单 bit 都不被接受为停止
证据；`md_boot stop` 只在父状态已是 `stopped` 时传入 `true`。

## 32k 事实来源（本轮核实）

- 本机 A `eccci/ccci_rtc.c` 读取 nvmem cell `external-32k` 的首字节；
  `ccci_modem.c:1798-1814` 在该值为 0 时把 feature 6 设为 MUST（无晶体）。
- 保存的 ACK live FDT 没有 `md_ccci_rtc` 节点，也没有 `external-32k`
  cell；`/proc/device-tree` 现场同样没有该节点，mddriver 也没有
  `nvmem-cell-names`。
- A 的 `mt6885/ccci_config.h` 与 `ccci_common_config.h` 都定义了
  `ENABLE_32K_CLK_LESS`；因此该机执行的 vendor 路径是静态零 → 无晶体。
- 据此在平台节点加入 `mediatek,no-external-32k;`，并在 binding 中声明为
  显式板级事实。驱动在既无 cell 又无该属性时返回 `-ENODATA`，不放行。

这不是把“默认零”当通用结论：属性只对本机、且来源记录在 binding 与本文。

## 验证

- 新 `tools/test_modem_md_boot.py`：实际 C 的 cache/boot/rtc32k 三模块，
  ASan/UBSan 通过。覆盖几何拒绝、一次清零与重连不清零、映射/读回故障锁定、
  gate 四阶段顺序与逐阶段失败、release 前启动接收、SMC 非零/不支持、
  `md_stopped=false` 零动作、停止顺序、PCM 诊断位、状态输出。
- 既有 dispatcher/platform/endpoint/session/router/FS/wire/RPC/CCIF/CCISM
  回归全部通过。
- 启用新组合的 ARM64 `Image.gz`/modules 构建 0 warning；恢复原配置后再次
  构建通过。日志与配置在 `evidence/modem-md-boot/`。
- binding YAML `dt-doc-validate` 通过；板级 DTB 中该节点无 schema 报错
  （板级其他既有节点的报错与本轮无关）。

## 首次上机步骤（尚未执行）

已离线构建测试镜像 `dist/1bf863e95714/boot.img`（release
`7.3.0-op6893-d1-1bf863e95714+`，SHA256
`637651f50fb4e1a378413ff5741eaa0ffd24ec2cbb54ee5d6a1d8b4ad95065f2`），
其 kernel config 含全部新选项，board DTB 中平台节点为 okay 且带
`mediatek,no-external-32k`。尚未刷入。

目标端 runner 前提：当前 Debian rootfs 没有 python3（`debian/packages.tsv`
与 squashfs 清单均无），而 `modem_service_backend.py` 及其依赖是 Python。
首次放行前必须先在目标 rootfs 部署 Python 3 与这些脚本（或等价的静态
后端）；否则 `md_boot prepare` 会在 dispatch reserve 处以未连接失败，这是
预期安全行为，但无法进入 HS1。

1. 用启用 `OP6893_CCCI_MD_BOOT` 的镜像启动；DT 打开 `modem-platform`，
   关闭互斥的 `modem-handoff`。
2. 准备标记过的私有工作副本，启动显式 runner：
   `modem_service_backend.py --endpoint /dev/ccci-service-10209000.modem-platform --root <私有副本> --generation <gen>`；
   需要用户 RPC 时另加 `--rpc-policy`。
3. `echo on > .../md_power`（冷上电，仍不放行 CPU）。
4. `echo prepare <gen> > .../md_boot`；期望 `md_boot` 为 `prepared`，
   `nvram_cache` 为 `prepared/cleared`，`dispatch` 为 prepared。
5. `echo release > .../md_boot`；观察 `handshake` 是否收到 HS1/HS2，
   `dispatch` 是否进入 HS2，`ccism` 是否开始后置协议。
6. 结束用 `echo off > .../md_power`（上述停止顺序），或直接看门狗复位。
   HS2/CCISM 完成仍不代表注册、通话或数据面可用。

## 仍未闭合

- ADC `0x4003` 的名称→通道完整表未取得；保持不可用。
- 真实用户 property/SAR 策略与私有工作副本内容需操作者准备，内核不猜。
- SCP/CCISM 真机状态、MD 固件 HS1/HS2、DPMAIF 与 radio 能力全部未验证。
- 活动 unbind 仍不支持；cache/boot 无回调，devres 清理直接释放。
