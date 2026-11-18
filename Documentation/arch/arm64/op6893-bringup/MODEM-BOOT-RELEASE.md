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

已离线构建测试镜像 `dist/8e13583dbaa5/boot.img`（release
`7.3.0-op6893-d1-8e13583dbaa5+`，SHA256
`21a1c3147cfc9a3745e57c0f55ad33d2146ddc30613ac5c684cdb1dbfb9ee847`），
其 kernel config 含全部新选项，board DTB 中平台节点为 okay 且带
`mediatek,no-external-32k`，initramfs 的 `debian.sha256` 已指向新 rootfs。
尚未刷入。

目标端 runner：rootfs 现在由 `debian/finish.py` 直接从版本化的
`Documentation/arch/arm64/op6893-bringup/tools/` 取四个模块与
`op6893-modem-fs-runner` 包装，并把它们的 SHA256 计入内容寻址身份——否则
更新 runner 不会改变 rootfs id。当前镜像为 `debian-c45bf71e26f2`，squashfs
SHA256 `3f6938ff0debacad7205cf3d69961a5d158c725112101fae8d23139be1e0353e`
（121,339,904 字节），已安装到 `/cache/mainline/debian.squashfs`；旧回滚
`debian-5f8741f4101a.squashfs` 保留，更早的两个回滚按操作者授权删除。
`initramfs/debian.sha256` 已更新。

工作副本只接受显式空目录或调用者自己的数据；真实 NVRAM 仅在操作者明确
授权时以只读方式提取到标记的私有副本，且不得进入任何 git 树：

```sh
install -d -m 0700 /tmp/op6893-fs
printf 'PRIVATE DISPOSABLE MODEM FS WORKING COPY\n' > /tmp/op6893-fs/.op6893-fs-working-copy
chmod 0600 /tmp/op6893-fs/.op6893-fs-working-copy
```

runner 用法：

```sh
/usr/local/sbin/op6893-modem-fs-runner \
  --endpoint /dev/ccci-service-10209000.modem-platform \
  --root /tmp/op6893-fs --generation <gen>
```

1. 用启用 `OP6893_CCCI_MD_BOOT` 的镜像启动；DT 打开 `modem-platform`，
   关闭互斥的 `modem-handoff`。
2. 用上面的命令准备私有工作副本并启动 runner；需要用户 RPC 时另加
   `--rpc-policy <私有策略>`。
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

## 真实 NVRAM 上机结果（2026-11-17，镜像 6fd303197419）

操作者授权以只读方式提取本机 NVRAM 后，设备刷入
`dist/6fd303197419/boot.img`（SHA256
`c24d346c7b90af5f4b41b4a191583590ce9c8afb57568b8e1b30e9c3686b6619`），
rootfs 为 `debian-c45bf71e26f2`。提取与验证方式、逐项结果见
[FS 语义](MODEM-FS-SEMANTICS.md) 与 `evidence/modem-nvram-live-boot.json`。

要点：

1. 453 个文件、10,087,370 字节经 `adb exec-out tar` 只读导出，逐文件 SHA256
   与提取前的设备清单一致；原始来源没有任何写入。
2. 同一放行流程（SCP ready → takeover/on → prepare → release → SMC `(6,0)`
   `boot_ret=0`）到达 HS1，随后 MD 用真实数据完成整个启动扫描：
   859 个 FS 请求、964 次发送、`tx_error=0`、105 个不同路径、84 次写回。
   此前空工作副本下的 `nvram_io.c` 断言消失。
3. 结束时 MD 在 `Z:\NVRAM\NVD_DATA\MF04_003` 之后抛出致命 CPU 异常
   `ex_type=29`（MPU_NOT_ALLOW，class=fatal，
   `pc=0x91823b66 addr=0x90d18620`）。当时把 `md1rom` 基址当作
   `0x90000000` 并据此认为两个地址都在镜像内；后续用 `lk_regions` 查证到
   真实几何为 `bank0=0xe0000000+0x1e000000`，`md1rom` 分区 200 MB、镜像
   31.9 MB，而 MD 视图的镜像基址确实是 `0x90000000`（AP 侧偏移
   `0x50000000`）。因此两个地址仍落在已加载镜像内，但“基址 0x90000000”
   是 MD 视图而不是 AP 物理地址，不能再当作 AP 侧地址使用。
4. `handshake` 现在额外输出 HS1 原始 query 与协商结果：MD 只把 feature 0
   标为 must-support，其余全部 optional，因此“缺少 runtime feature”不是
   本轮的阻塞点。
5. 异常后 `md_power=off` 返回 `-EIO`（boot owner 拒绝停止已故障的活跃状态），
   用 `sync + SysRq` 复位；复位后 `state=lk-on`，设备停在干净状态。

### 两个同板有据的补齐与负结果

操作者授权读取 MD 调试区后，`md_dbg` 给出 MD 自己的 AFOUND 记录，与
`md_ee` 一致（`Fatal Error (0x1d, 0x91823b66, 0x90b2d7c2)`，6.26 s）。随后
按同板行为补了两项并各上机一次：

| 镜像 | 变更 | 结果 |
|---|---|---|
| `966546053c61` | 新增 feature 38 `MD_MEM_AP_VIEW_INF`，bank0 取自 LK `hdr_tbl_inf` | runtime 584→632 B，异常点不变（`tx=964`） |
| `8b1f973b5ff2` | 按厂商 `SMF_NCLR_FIRST` 表首次清零 SMEM（75,640,832 字节；排除 CCISM_SCP 与 NVRAM cache） | 异常点不变（`tx=964`） |

两项都通过 prepare 门并正常放行，说明它们自身正确、不破坏启动路径；但都
没有改变 MPU 异常。LK 还提供 `md_mpu_inf`（216 B）与 `md_mpu_num`，
当时据此把“为 MD 编程 EMI MPU”列为下一个候选。

### 为什么不再把 EMI MPU 当作缺失环节

按“可用工具查证的不靠推理”的要求，后续对这条候选做了三项查证，结论是
它不构成本轮的阻塞点，因此没有为此改动任何 EMI MPU 寄存器：

1. 异常类型不同。同板 `mdee_dumper_v5.h` 的枚举里 `MPU_NOT_ALLOW = 0x1D`
   是 CPU 核心异常码（来自 `cause[exccode]`），而 EMI MPU 违规是独立的
   `EMI_MPU_VIOLATION_EXCEPTION = 0x70`。本轮记录到的始终是 `0x1D`。
2. 厂商内核不应用这张表。4.19 里 `parse_mpu_setting()` 只把
   `md_mpu_inf` 读进 `s_g_md_mpu_cfg_list`，唯一消费者
   `get_mpu_region_cfg_info()` 在全树没有任何调用者；6.6 参考树只保留声明。
   厂商内核实际编程的只有 AP 自身区域（`protect_ap_region()`）。
3. 结构大小对不上。`struct _mpu_cfg` 是 20 字节，216 字节既不是它的整数倍，
   也不能在未解码的情况下当作“9 条区域”使用。真要使用必须先逐条解码并与
   内存几何核对，而第 2 点已经说明厂商并不需要它。

LK 在主线启动前已经跑过，所以即便 LK 编程过 EMI MPU，该状态在主线里依然
生效；主线不重配也不会清除它。EMI MPU 属于全 SoC 保护配置，在没有证据
指向它时改动它的风险远大于收益。

## 审计后的用户 RPC 事实（2026-11-17，镜像 0a007c93dc91）

前一轮停在 88 次发送，原因是 MD 查询 `0x400f`（`IPC_RPC_QUERY_AP_SYS_PROPERTY`）
时 runner 没有可用的属性事实而关闭端点。为了让 policy 有据可依，而不是
猜值，本轮按以下顺序取事实：

1. runner 新增显式 `--trace-rpc-names`，只打印请求 operation 与有界可打印
   的请求名，不打印任何取值；一次运行即得到 MD 的查询序列。
2. 回 Android 用 `getprop` 核实：`ro.build.version.svn.c`、
   `ro.build.version.svn`、`ro.build.version.ota` 在本机**不存在**（整个
   `getprop` 输出里没有任何 `ro.build.version.svn*` 键）。因此 Android
   `property_get()` 语义下它们的正确答复是长度 0 的空串，而不是“未知”。
3. 同一次 Android 会话把与 modem/构建相关的属性受控导出到
   `/data/src/op6893-private/android-props/`（0700/0600，不在任何 git 树内，
   并已剔除 serialno、IMEI/MEID、ICCID/IMSI、各类 MAC 等身份类键），
   供后续查询逐条审计。
4. policy 只包含从该导出核实过的事实：27 条真实取值（含
   `ro.build.version.release=16`、`ro.vendor.mediatek.version.release`、
   `ro.product.device=op6893` 等）与 9 条已核实缺失（null）。

结果：同一放行流程下 MD 通过全部属性查询，`services tx=964 tx_error=0`，
`dispatch state=3 (WAIT_HS2) error=0`，异常点与之前完全相同。也就是说
**属性查询不再是阻塞点**，阻塞点仍是 MD 自身的 `MPU_NOT_ALLOW`。

### 异常记录解码修正

同板 `ex_overview_t` 的 `ex_info` 位于 `main_reson[core_num]` 之后，而
`core_num` 是记录里的字段：本机为 12，不是头文件默认的 9。旧实现把偏移
硬编码为 `cores=12` 时的值，一旦记录里换成别的核心数就会读错字段。现在
`ccci-md-ee.c` 用纯函数按记录中的核心数推导全部偏移，超出
`CCCI_MD_EE_MAX_CORES` 或长度不足时返回 `-ENODATA` 而不是继续读。修正后
同一记录解码为：

```
version=0xab000005 cores=12 offender=MCU ex_type=29 class=fatal section=0
cadefa=1 code=0x1d,0x91823b66,0x90b2d7c2
sp=0x24ab42d0 pc=0x91823b66 lr=0x90b2d7c2 addr=0x90d18620 cause=0x74 status=0x2
```

`section=0` 表示不属于厂商 `ee_err_sec_str[]` 里任何只读代码段，`cause=0x74`
的 `exccode` 字段同样是 `0x1D`，与固件自己打印的 AFOUND 文本一致。

### LK 几何与 FS 尾部证据

`lk_regions` 给出本轮实际使用的几何：

```
bank0=0xe0000000+0x1e000000 noncached=0x8e000000+0x1800000
cached=0x88000000+0x4960000 users=23 cache_md_base=0x48000000
cache_gaps=524288 noncache_gaps=15681536
```

`md1rom` 分区（`/dev/sdc28`，200 MB）的 MTK 头给出镜像大小 `0x01febe00`
（31.9 MB），故障 `pc` 与 `addr` 分别位于镜像内 +24.1 MB 与 +13.1 MB，
所以不是“跳到了未加载的地址”。

runner 新增显式 `--trace-fs`（只打印 operation、路径、状态；写负载一律
折算成字节数，`0x1022` 只打印十个数值参数），得到的尾部序列说明 FS 侧
没有欠读：对 `MF04_003`（824 字节）的两次 `CMPT_Read` 是
`offset=0x40 size=0x17c` 与 `offset=0x1bc size=0x17c`，合计正好
`0x338` 到 EOF；`ICOR_000`/`ICOE_000`（4192 字节）同样以
`offset=0x40` 起、每块 `0x408` 精确覆盖到 EOF。MD 在把最后一个文件读完
之后才抛异常。

### 本轮仍未闭合

HS2 仍未到达，因此没有 CCISM 后置协议、没有 radio READY。当前阻塞点是
MD 内部的内存保护异常，已排除：FS 应答格式、真实 NVRAM 缺失、属性查询、
feature 38、首启 SMEM 内容、EMI MPU 表。要继续必须取得 MD 侧更多证据
（例如 MD 自身日志区里除 AFOUND 之外的内容），而不是继续在 AP 侧盲改。

## 首次上机结果（2026-11-16，镜像 de66138efb8e）

设备从 Android 经 watchdog 重启、拦截 fastboot 后刷入
`dist/de66138efb8e/boot.img`（SHA256
`5cf1a29073d07cdab40e94683b8f8f186185ac49eec8271d1db39757231938c8`），
rootfs 为 `debian-5f8741f4101a`。流程：

1. `pin=26m`、`runtime=start`：SCP `active=1 ready=1 generation=1`，
   READY1、awake 配对、无错误。
2. `md_power takeover` → `cold`，`on` → `powered-cpu-not-released`。
3. runner（generation 4676）连接端点后 `prepare 4676` 成功：
   cache 首次清零、runtime offers、dispatch reserve 全部通过。
4. `release`：SMC `(6,0)` 返回 `boot_ret=0`，MD CPU 首次放行。
5. HS1 到达并被接受（`bytes=584 rejected=64`），runtime 发布后 endpoint arm；
   MD 随后发出第一个 FS Open（queue 4、80 字节、op 0x1001、argc 2），
   runner 收到并回包；一次 EX_ACK（0x10000）被接受。
6. 结束时状态：`md_boot=released`、`dispatch state=3 (WAIT_HS2) error=0`、
   `handshake state=3 error=0 active=1 hs2_seen=0`、
   `services connected=1 armed=1 accepting=1 error=0`。

**HS2 尚未到达**，因此没有 CCISM 后置协议、没有 radio READY。MD 在
WAIT_HS2 等待，最可能停在后续 NVRAM/FS 数据（私有工作副本为空）。

硬件暴露并修正了三处离线模型与真实 wire 的差异：

- FS 请求的 operation 是裸 `0x1001`，不是 reply 形式的 `0xffff1001`；
- RPC `0x4005` 的 type 参数可长于 4 字节，name 字段可带零填充；
- CCIF EX_ACK（bit16）是已被 RX scanner ACK 的已知通知，不是未知包。

首次失败路径也已实测：无 runner 时 `prepare` 在 reserve 处 `-ENOTCONN`；
runner generation 不匹配时 endpoint 以 `-EPIPE` 中止；这些都不放行 CPU。

同一次上机随后执行了健康路径的 `off`：`ccif_stop`（时钟仍开）→ MD1
MTCMOS OFF 六寄存器读回 → dispatcher/endpoint 停止。结果
`off_rc=0`、`md_power state=stopped`、`dispatch state=6 (STOPPED)`、
`services stopped=1 error=0`；SCP 保持 `active=1 ready=1`，没有被误停。
这验证了停止顺序和硬件停止证据，不需要再为停止单独刷机。

## 后续真机结果（2026-11-17，镜像 a6025a735b61）

在首次放行之后，按 MD 实际请求逐项修正了 FS/RPC 线格式，MD 现在能完成
完整的 NVRAM 读取扫描，但停在 NVRAM 初始化（详见
[MODEM-FS-SEMANTICS.md](MODEM-FS-SEMANTICS.md) 的 live 小节和
`evidence/modem-fs-live-sequence.json`）。

关键修正：

- **FS 应答必须带 `0xffff0000 | op` 前缀**。MD 请求用裸 op，但它的
  `ccci_fs.c` 在应答 op 不匹配时断言；首次放行时 `para=0xffff1001,0x1001`
  就是这个原因。内核端点现在只接受带前缀的应答。
- 新增 `GetDiskInfo(0x100e)`、`GetAttributes(0x1010)`、`Restore(0x1021)`、
  `CMPT_Read` 的 `0x13` 变体、只读目录打开、盘符根路径。
- `0x4007`（ADC 值）按同板 `get_md_adc_val()` 的失败返回值回复两个 `-1`，
  不再以 `-EOPNOTSUPP` 终止会话。
- `handshake` 状态新增 `md_head`，`ccif` 新增服务发送计数/最后错误，
  `md_ee`/`md_ee_raw` 暴露 MD 异常记录头（offender、断言文件/行/参数）。
- bit16 的通知改判为 `D2H_EXCEPTION_INIT`（MD 断言），不再当作普通 ex-ack。

真机观察：HS1 之后 MD 依次完成 RPC、`md_nv_config.txt` 打开/取大小/关闭、
磁盘信息、属性、目录打开、约 350 次 `CMPT_Read`，随后 `Restore NV0S_000`
失败并在 `mcu/service/nvram/src/nvram_io.c:2394` 断言
（`para=0x1,0x4,0xf008`）。诊断性“假成功 Restore”不改变该断言，说明
MD 需要真实 NVRAM 内容或 bin-region 备份；按项目约束不导入。

## 操作者备忘：复位与刷机

- 需要 fastboot 时用 watchdog 复位。喂狗进程是 busybox `watchdog`
  （`/run/op6893-watchdog.pid`，本轮为 285，`/bin/busybox watchdog -F -t 5 -T 30
  /dev/watchdog0`）。正确做法是 `kill -STOP` 该进程后等硬件超时（本轮约
  41 秒进入 fastboot）。注意 `/proc` 里还有一个同名的内核线程
  （PPid 为 2，本轮 PID 64），对它发信号无效，不要误判为“喂狗没停”。
- 不需要 fastboot 的复位用 `sync` + SysRq `b`，回到同一张主线镜像。
- 从 Android 回 fastboot 用 `adb reboot bootloader`，不必等 watchdog。
- `/cache`（`/dev/sdc55`）在主线里挂到 `/run/cache` 且为只读；本轮可用空间
  125 MB，而 rootfs 为 121 MB，重建并安装新 rootfs 需要先删掉保留的回滚
  镜像，因此本轮没有为仅含诊断开关的 runner 变化重建 rootfs，跟踪开关是从
  `/tmp/op6893-modem` 覆盖运行的。

## 固化后的操作入口（2026-11-17）

此前每次实验都依赖 `/tmp` 里的临时脚本，开发机重启后就丢失了。现在这些
站点相关的操作脚本放在**非 git** 的构建工作区
`/data/src/mainline/mt6893-direct`，内核树里只保留文档和通用测试：

| 脚本 | 作用 |
|---|---|
| `md-release-cycle.py` | SysRq 复位 → 等 SSH → 推送标记过的私有工作副本、runner 模块、可选 policy |
| `md-release-run.sh` | 设备侧放行探针：pin/start SCP → takeover/on → 带两个跟踪开关跑 runner → 打印全部状态 |
| `md-rpc-policy.py` | 从审计过的 getprop 导出生成私有 policy（可复现上机用的 34 条事实：25 有值 + 9 已核实缺失） |
| `md-nvram-extract.py` | 只读 `adb exec-out tar` 生成新快照 + 标记 + 清单，拒绝不安全成员，从不写回源 |
| `md-nvram-recheck.py` | 活体源与快照逐文件比对，并打印设备侧 mtime/size 以便归因 |

同时确认：提交后的树在关闭全部实验选项下仍能构建
（`dist/f0b0f962e615`，SHA256
`26a9f86d2f9b5079e334bacafae70616d2551b17d71b5c51e5ae1e543cc57453`，
`MD_PLATFORM/MD_BOOT/SERVICES/DISPATCH/HANDSHAKE/SMEM` 全部未启用，
构建日志 0 error），`out/.config` 也随之回到基线配置。
详见 `evidence/modem-source-recheck-and-baseline.json`。

验证约定：`modem-release-image.py` 调用 `build.py` 时带 `OP6893_BUILD_FOCUSED=scp-initial`，
该模式会跳过与本次构建无关的回归日志，因此**不能只看构建是否通过**。收尾时
必须单独跑全量 `Documentation/arch/arm64/op6893-bringup/tools/test_modem_*.py`
（当前 52 组），本轮就是这样发现两个自早期提交起就失效的 harness：服务发送
模型缺少诊断引入的 printk，SCP owner harness 仍断言“完全不存在 RX start”
且仍从 `.c` 里取结构体。两者都已修好，并顺带修掉了发送忙路径上多读一次 AP
寄存器的问题。

### 恢复用的 Android 内核

从 2026-11-17 起，回 Android 时刷的是**设备当前实际在跑的那张镜像**，而不是
更早的 `evidence/ack-boot.img`：

```
/data/src/mainline/mt6893-direct/recovery/android-boot-current.img
sha256 d8c9c35f35f405117a640692cf409250af8fe50c0f3601af071a37852ccd8847
```

它是用 `adb exec-out dd if=/dev/block/sdc48` 只读流式导出、再按分区实际大小
（32 MiB）截断后取的；镜像里的内核版本串与运行中 `/proc/version` 完全一致，
所以确认就是当前在用的那一张，不是陈旧副本。旧的 `ack-boot.img`
（`455ed6ce…`）继续留在原处，因为 `build.py` 拿它当打包基底；只有**恢复角色**
换成了当前镜像。

注意 toybox 的 `dd` 会把记录统计写到 stdout，导出后必须按 65536×512 截断再
校验，否则哈希会包含那几行文本。
详见 `evidence/android-boot-recovery.json`。

## 快照 A/B 与 LK 标量（2026-11-17，镜像 09e7591adc6f）

**问题**：我们的 NVRAM 私有副本是时间点快照，设备上已有 11 个运行时文件被
Android 更新；会不会是"数据过时"导致 MD 走到坏指针？

**做法**：只读重新提取一份活体快照（`nvram-live-20261117`，453 文件，与冻结
快照差 11 个），用同一放行流程各跑一次。

**结果**：`tx=964`、`tx_error=0`、`ex_type=0x1d`、
`pc=0x91823b66 addr=0x90d18620 sp=0x24ab42d0`、最后一条仍是
`CMPT_Read MF04_003 offset=0x1bc size=0x17c`、CCISM 仍 `ARMED`
`bridge_touched=0`——**完全一致**。所以快照新旧不是原因，故障在三份不同快照/
镜像下都稳定复现。

同时把 LK 的单 u32 标量标签打进了启动日志（只加白名单标签，不新增 sysfs、
不打印任何载荷）：

```
md1img=33471260  hdr_count=1  retrieve_num=4  ccb_gear_id=12
md1_smem_cahce_offset=134217728 (0x8000000)  md_mpu_num=9  free_in_kernel=0
```

三项直接结论：

1. **镜像 31.92 MiB**（与 `md1rom` 分区头一致），而故障 `pc` 在镜像内
   +24.14 MiB、故障地址在 +13.10 MiB，所以不是"访问超出已加载镜像"。
2. **`cache_md_base` 得到独立确认**：`0x40000000 + 0x8000000 = 0x48000000`，
   与驱动发布的值、与厂商 `ccci_md_mem_inf_prepare()` 的公式完全一致。
3. **`md_mpu_num=9`、表 216 字节 ⇒ 每条 24 字节**，而厂商
   `struct _mpu_cfg` 是 20 字节——这进一步说明 LK 那张表不是该结构，不能
   当成"9 条区域"直接套用（本轮仍未写任何 EMI MPU 寄存器）。

MD 的只读/可写段划分由 LK 决定，内核侧拿不到，因此"故障地址属于代码段还是
数据段"这条无法用现有元数据判定。证据见
`evidence/modem-snapshot-ab-and-lk-scalars.json`。

## 与厂商自身启动日志的对照（2026-11-17）

设备在 Android 时可直接读厂商内核的运行时状态。两份既有采集提供了地面真相：
`/data/src/reverse-analysis/modem-runtime/ccci_dump-boot-excerpt.txt`（厂商 4.19
启动日志）与 `ccci-fs-request-sequence.txt`（对 `ccci_mdinit` 的 `/dev/ccci_fs`
抓取）。

### 先更正一条旧结论

此前写"厂商在 `MF04_003` 之后接着读 `UM12_005`，我们的 MD 在这里分叉"。查证
后不成立：那份抓取是**启动后约 10.4 秒才 attach** 的稳态序列，里面
`md_nv_config`/`INFO_FILE`/`NV0S_000`/`Restore`/`FAT6F*` 出现次数全是 0，
是 READY 之后的 NVRAM 巡检（21 秒内 2180 次 `CMPT_Read`），不是启动扫描。
我们启动阶段的那 859 个请求在该文件里没有对应物，旧比较作废。

### 厂商启动时间线（同一台设备）

| 时刻 | 事件 |
|---|---|
| 9.161 s | MD 启动 |
| 9.437 s | `prepare_runtime_data`，AP 声明 39 个 feature，随后发出 runtime data |
| 9.526–9.624 s | MD 经 RPC 查 GPIO/EINT 与 dtsi |
| **10.899 s** | `control message 0x0,0x0` → `md_state 3→4`，即 **WAIT_HS2 → READY** |

也就是说厂商 MD 在启动后约 1.7 秒就到 HS2，**在长时间 NVRAM 扫描之前**。我们
的 MD 则是先做完整 859 请求扫描、始终不到 HS2——这正是同板"首次启动重建
NVRAM cache"的路径（我们每次 Linux 启动都会清零，所以每次都走这条路）。

### 两项逐字段核对：都对

1. **AP runtime data v2.1**：厂商 `config_ap_runtime_data_v2_1()`
   （`eccci/modem_sys1.c`）填 `struct ap_query_md_feature_v2_1`，我们
   `ccci_runtime_upload()` 填同一结构。head/tail pattern、
   `feature_set[1]`（mask 0、version 1，其余为 0）、`share_memory_support=2`、
   runtime 地址/大小、以及 `noncached_mpu_*`/`cached_mpu_*`
   （`0x40000000+0x1800000`、`0x48000000+0x4960000`）**逐字段一致**。
2. **SMEM 区域表**：新增只读 `smem_users` 属性（只打印 id/AP/MD/size/标志，
   无载荷），与厂商启动日志的 `init_smem_regions` 逐条比对，24 个区域
   **全部一致**，包括 `RAW_MDSS_DBG 0x8e110800/0x40110800/0x3800`、
   `RAW_RUNTIME_DATA 0x8e11e800/0x4011e800/0x1000`、
   `MD_NVRAM_CACHE 0x88180000/0x48180000/0x700000`、CCISM 三个区、
   `RAW_MD_CONSYS` 与 CCB 聚合。

### 一个负结果：HS1 回复不能只发 MUST 记录

厂商 `append_runtime_feature()` 只为协商成 MUST_SUPPORT 的 feature 追加记录，
于是把我们的编码改成同样语义（回复从 632 字节降到 192 字节）。结果：

```
bytes=192  fs_requests=0  service_tx=0  hs2_seen=0  dispatch error=0
md_ee: 解码返回 -ENODATA（version 读到 0，没有异常记录）
```

MD **完全静默**：不再发任何 FS 请求，也不写异常记录。说明这块固件期望"对每个
被查询的 feature 都有一条应答记录"，稀疏布局对它不等价。改动已回退，基线恢复
（859 请求 / `tx=964` / 同一故障点 `pc=0x91823b66 addr=0x90d18620`）。

证据见 `evidence/modem-vendor-boot-comparison.json`。

## NVRAM cache 是否影响 MD 走快路径（2026-11-17，镜像 f6b889ccba7f）

厂商 1.7 秒到 HS2、且启动期没有长时间 NVRAM 扫描，而我们的 MD 每次先做 859
个请求的重建。一个自然的假设是：厂商基带在 Android 启动时留下的有效 cache
会让 MD 跳过重建。为此加了两个入口：

- `smem_cache`（只读）：打印 NVRAM cache 区的 AP/MD 视图、大小和前 64 字节；
- `smem_clear`（读写）：首启清零策略，`clear`（默认）或 `skip`。

### 观测

先刷恢复镜像让 Android 跑约 44 秒，再刷回主线、**在任何 prepare 之前**读
`smem_cache`：

```
ap=0x88180000 md=0x48180000 size=0x700000 head=
0a020000 20000000 00a20000 c0a20000 40ae0000 000b0000 40b90000 00283300 ...
```

非零且结构化（形如 offset/size 对：0x20、0xa200、0xa2c0、0xae40、0xb00、
0xb940、0x332800），说明厂商确实留下了已填充的 cache。

### 结果：假设不成立

把 `smem_clear` 设为 `skip`（驱动完全不清零）后跑完整放行：

| 项 | 值 |
|---|---|
| 跑完后 cache 头 | **全零**（64 字节全是 0） |
| FS 请求 / 发送 | 859 / 964 |
| dispatch | `state=3 WAIT_HS2 error=0` |
| 异常 | `ex_type=0x1d pc=0x91823b66 addr=0x90d18620` |

也就是说：**MD 自己在启动时把 cache 清零并从文件服务重建**。保留厂商填充的
cache 完全不改变行为，所以"我们每次清零"从来不是决定因素，重建也不是 HS2
不来的原因。这条线索关闭。

推论：MD 在选择"先重建再 HS2"还是"直接 HS2"时看的是别的 AP 侧输入，不是
cache 内容。证据见 `evidence/modem-nvram-cache-persistence.json`。

## MD DFD 区与 DBM 初始化（2026-11-17，镜像 0ae342c5bec9 / 12111f9c1462）

### 1. MD 侧日志：RAW_DFD 在这块固件上是空的

原以为 MD 会把内部日志写进 SMEM user 10（RAW_DFD，8 MiB），因此新增：

- `debugfs:op6893-md-dfd`（只读）：整区流式文本视图，可打印字节原样输出，
  其余连续段折叠成一个换行，按文件位置分页，8 MiB 不会一次性进内存；
- `md_dfd_info`（只读）：整区扫描，打印字节数、非零字节数、可打印字节数和
  首个非零偏移。

真机结果：

```
MD 启动前： bytes=8388608 nonzero=0 printable=0 first=-1
异常之后： bytes=8388608 nonzero=0 printable=0 first=-1
```

**整区全零**。也就是说这块固件不往 RAW_DFD 写日志，MD 侧取证目前没有可读
来源，这条线关闭。

同时更正一个来源误判：厂商启动摘录里的 `[1]NORMAL LOG REGION`、
`[1]CCCI MD INIT REGION` 等段落来自厂商**内核自身**的 CCCI 日志缓冲
（`ccci_private_log.c` 的 `format_separate_str()`），不是 RAW_DFD 内容。
所以那份摘录不能当作"MD 内部日志"的证据。

### 2. DBM 区：厂商会写，我们从来没写过

对照 `modem_sys1.c` 的 `md_cd_smem_sub_region_init()`：厂商在发 runtime 数据
之后、拉 `H2D_SRAM` 门铃之前，会往 SMEM user 0（RAW_DBM）写一个完整模式：

```
[0x44444444][0x44444444][ 160 字节清零主体 ][0x44444444][0x44444444]
```

我们此前完全没有写这个区域。现在在 `control_publish()` 里、`runtime_send()`
之前写同一模式，`handshake` 状态多一个字段可验证：

```
state=3 ... dbm=512 ...
```

第一次实现踩了一个坑：单独为 DBM 页 `devm_request_mem_region` 会返回 `-EBUSY`，
因为 runtime 的保留窗口已经是 `0x8e11e000-0x8e11ffff`，DBM 就在里面。改成
**复用同一窗口**，不再申请第二个区域（`/proc/iomem` 里不会出现 `ccci-dbm`）。

结果：`dbm=512` 确认写入生效，但 MD 行为完全不变——859 请求 / 964 发送 /
`state=3 WAIT_HS2` / 同一个 `ex_type=0x1d pc=0x91823b66 addr=0x90d18620`。
DBM 是一个我们确实缺失的 AP 侧输入，但它不是决定因素。

### 3. 剩下的最大差异：协商到的 feature 数量

真机 `handshake` 已经把 MD 的 query 和协商结果整份打印出来，解码后：

| 项 | 结果 |
|---|---|
| MD 声明 MUST 的 | 只有 0（BOOT_INFO） |
| MD 声明 OPTIONAL 的 | 1–40、42–44（41 为 NOT_SUPPORT） |
| 我们回 MUST 的 | 0、1、2、6、14、27、28、36、38（共 9 个） |
| 厂商 AP 回 MUST 的 | 约 35 个（`config_ap_side_feature()` 把绝大多数声明为 MUST） |

MD 对每一次拒绝都能容忍（HS1 从未失败），但主线是唯一只给 9 个 feature 的
协议栈。这已经是 AP 侧最后一个未对齐的大项。

证据见 `evidence/modem-md-dfd-and-dbm.json`。

## HS2 与 CCISM RUNNING 打通（2026-11-17，镜像 2cfc8943f254）

### 结论：决定 HS2 的是 runtime feature 集合，不是 cache、DBM 或任何单个字段

把 HS1 回复里 MD 能协商到的 feature 从 **9 个**扩到 **28 个**之后，MD 的行为
发生了根本变化：

| | 之前（9 个） | 之后（28 个） |
|---|---|---|
| 异常 | `ex_type=0x1d` `MPU_NOT_ALLOW` `pc=0x91823b66` | **无异常**（`md_ee error=-61`） |
| handshake | `state=3 WAIT_HS2` | **`state=4 HS2_SEEN error=0 hs2_seen=1`** |
| dispatch | `state=3` | **`state=4 HS2 error=0`** |
| CCISM | `state=1 ARMED`，一条消息都没发 | **`state=5 RUNNING`**（完整 INIT/ACK/DONE + SCP RBREADY） |
| FS 发送 | 964，随后即死 | 6041 且仍在增长，`tx_error=0` |
| 端口拒绝 | — | 0 次 |

时间线：HS1 在 22.1 s 被接受，**HS2 在 62.5 s 被接受**——MD 先花约 40 秒做
NVRAM 初始化，然后才发 HS2。之前我们在 30 秒窗口内就判定"没到 HS2"，这是
观测窗口太短造成的误判。

### 新增的 feature（全部有来源，不猜）

标量类（16/4 字节，值取自本机厂商内核日志）：`5 HIF_DMA_REMAP`（全零）、
`7 RANDOM_SEED`、`8 GPS_COCLOCK`（全零）、`9 SBP_ID`（`{0, 0x7d}`）、
`10 MISC_CCCI`（`{3}` = 序列检查 + 状态轮询）、`11 CLIB_TIME`（墙钟）、
`12 C2K`（`{0x4}`）、`19 EE_AFTER_EPOF`（全零）、`20 AP_CCMNI_MTU`（`{3568}`）、
`32 MD_MTEE`（`{0}`，本板无 MTEE）。

区域类（SMEM user 的 MD 视图 + 大小）：`17 DT_NETD`、`18 DT_USB`、
`26 AUDIO_RAW`、`30 MD_CONSYS`、`31 MD_USIP`、`35 MD_WIFI_PROXY`、
`16 DHL_RAW`（LK 的 CCB 聚合按厂商规则在 2 MiB 处切开）。
`25 LWA` 按厂商行为发显式空区域 `{0,0}`（该 feature 在厂商侧是 MUST，
即使没有 LWA 区也照发）。

### 仍然不发：feature 15（CCB）

新增 `runtime_mask`（十六进制 u64，位 N 屏蔽 offer N，发布前生效、单次尝试后
拒绝修改）后逐项二分：

| mask | 结果 |
|---|---|
| `0x18000`（15+16） | 无异常，MD 继续读 NVRAM（tx 2792，`tx_error=-16`） |
| `0x8000`（仅 15） | 无异常，MD 继续读 NVRAM（tx 2802），**最终到 HS2** |
| `0x0` | MD 在 `ccci_shm_bm.c` 断言（`ex_type=0x50`，带源码路径与行号） |

也就是说：**只要广播 CCB，MD 就在启动期断言**；不广播它，MD 正常到 HS2。
CCB 是数据通道用的，我们还没有 CCB 控制区/端口子系统，所以暂不广播，
把这条留到真正实现数据面时再解决。`13 MD_IMAGE_START_MEMORY` 同样暂缓：
它需要从镜像头解析大小，驱动目前不做这件事，猜一个值比诚实拒绝更糟。

### 端口策略：从"逐通道 fail-closed"改成"HS2 之后观察但不回包"

之前 MD 每打开一个新端口（AT 10、系统 2、PCM 4、`MD_DIRC_RX` 200 …），
我们返回 `-EOPNOTSUPP` 并让整个 generation 失败。现在：

- HS2 之后，任何小于 `CCCI_MAX_CH_NUM`(258) 的通道都只计数（64 以下每通道
  一位，之上一个计数器）并接受，**不回任何包**；
- AT/MUX 通道另有 `md_at`：默认只给计数，写 `on` 才在 48 字节上限内给出
  可打印预览；
- 仍然 fail-closed 的：控制通道消息、FS/RPC 语义、以及超出同板枚举的通道 id。

实测观察到的端口序列：`2`(系统) → `4`(PCM) → `10`(AT/MUX) → `59`/`61`
(`IMSDC_DL`/`ICUSB_TX`) → `200`(`MD_DIRC_RX`)。

### 还没做的

MD 现在活着并持续工作，但**无线电仍未就绪**：没有注册、没有 AT 对话、没有
数据面。下一步是让 AT/MUX 通道真正与用户态对话（而不是只观察），以及补
CCB/数据通道。证据见 `evidence/modem-hs2-and-ccism-running.json`。

## AT/MUX 传输通道（2026-11-17，镜像 a1957caf951d，未上机）

HS2 之后 MD 会在 AT/MUX 通道（CCCI UART2）上发起对话，而我们此前只观察不回包。
本轮把这条通道做成真正的双向字节管道。

### 厂商事实（决定实现形态）

- `port_cfg.c`：`{CCCI_UART2_TX, CCCI_UART2_RX, DATA_AT_CMD_Q, ...}`，
  以字符设备 `ttyC0` 暴露（minor 3）；
- 通道号 **TX 12 / RX 10**，队列 **`DATA_AT_CMD_Q` = 5**（`MD_GENERATION >= 6293`）。
  这个队列号与上一轮真机抓到的 `queue=5` **完全一致**，不是推测；
- `port_dev_write()` 对原始字符端口构造的头部是
  `data[0]=0, data[1]=payload+16, channel=tx_ch, reserved=0`；
- **厂商内核不做 0710 复用**，复用由用户态 `gsm0710muxd` 完成。所以内核侧
  保持成纯字节管道，复用和 AT 全在用户态。

### 内核侧

- 新增 `ccci-md-at.c/.h`：root-only `0600` 的 `ccci-at-<devname>` 字符设备，
  独占打开、16 KiB 接收环、分块发送、故障锁存、停止需要真实 MD 停止证据；
- `ccci_ccif_at_send()`：**由内核构造头部**（channel 12 / queue 5），用户态
  只提供 0710 字节流；把发送核心从 `ccci_ccif_service_send()` 抽成共享的
  `ccif_transmit()`，序列号/忙字/门铃规则只保留一份；
- 调度器：channel 10 的载荷交给管道；HS2 接受时 arm、故障时 abort、
  停止时随 generation 一起停、离线时一起离线；
- `md_at` 现在两行：第一行是调度器计数与可选预览，第二行是管道状态
  （`open/hs2/queued/rx_frames/tx_frames/error`）。

### 用户态

- `modem_at_mux.py`：**只做 0710 基本模式**——标志字节、字节填充、
  取反 CRC-8 FCS、SABM/UA/DM/DISC、单字节长度的 UIH，解码处处有界；
- `modem_at_probe.py`：先 SABM 等 UA，再用 UIH 发 AT 命令，打印 **MD 自己的
  应答**（有界、仅可打印）；`--self-test` 用内存模型跑同一套状态机。

### 测试抓到的两个真实缺陷

1. **HS2 之前的写入会把 `-ENOTCONN` 永久锁存**，等于一次过早写入就打死整条
   通道。现在 `-ENOTCONN` 与 `-EBUSY`/`-EAGAIN` 一样视为瞬时，只锁存真实
   传输故障。
2. **真实内核构建才发现缺 `<linux/poll.h>`**——host 桩自己声明了
   `poll_table`，把这个错误掩盖了。补上头文件后构建通过。

### 状态

镜像 `a1957caf951d`（sha256 `affe0c6e…`）**已构建、未刷机**：设备离线充电，
按约定停在这里。`nm out/vmlinux` 可见 `ccci_ccif_at_send`、`ccci_md_at_create`、
`ccci_md_at_hs2`、`ccci_md_at_receive`，确认代码确实进了镜像。

56 组 host 测试全通过，checkpatch 对新文件 0 error 0 warning。

**明确未验证**：MD 的 0710 实现是否与这个编解码一致、SABM/UA 在真机上是否
成功、任何 AT 命令是否有应答。证据见 `evidence/modem-at-mux-transport.json`。

### 下次上机的第一步

1. 刷 `a1957caf951d`，跑一次放行到 HS2（约 62 秒）；
2. `python3 modem_at_probe.py --device /dev/ccci-at-10209000.modem-platform --command AT --command 'AT+CPIN?' --command 'AT+CREG?'`；
3. 若 SABM 无 UA，先用 `md_at` 看管道计数与 `md_at` 预览，确认 MD 是否真的在
   发 0710 帧（首字节应是 `0xF9`）。

## 无线电就绪：AT 对话到 LTE 注册（2026-11-17，镜像 c96a4caab4b4）

### 首次真机 AT 对话

AT 通道打通后，第一次对话遇到一个**前置缺陷**：MD 通过 RPC（op `0x400f`）询问
`ro.oppo.operator`，策略里没有已审计答案，backend 按 fail-closed 退出，端点
关闭把整个 generation 以 `-EPIPE` 打断（`dispatch state=7 error=-32`，
`services pending=1`）。

查证：本机**完整未过滤**的 getprop 导出（1625 键，含
`ro.product.device=op6893`）里**完全没有 `ro.oppo.*` 键**。于是把它加入已审计
的 OBSERVED 集合、标记为已核实缺失；策略现在是 35 条事实（25 有值 + 10 缺失）。

### 对话结果

```
AT          -> OK
AT+CFUN?    -> +CFUN: 0                     （最小功能，飞行模式）
AT+CFUN=1   -> OK + 一串 URC
               (+ESMLSTATUS/+ECEMODE/+ECEVDP/+EHVOLTE/+ECAPABILITY/+EPOK/+ECT3G/+EUSIM/+ESIMECC)
AT+CPIN?    -> +CPIN: READY                  （SIM 已识别）
AT+CSQ      -> +CSQ: 17, 99                  （真实信号，不再是 99）
AT+COPS=?   -> (2,"CHN-CT","CT","46011",7) 为当前网络，移动/联通为 forbidden
```

### 注册状态

```
AT+CEREG?  -> +CEREG: 3,1,"9A17","03C341C3",7,0,0
AT+CGATT?  -> +CGATT: 1
AT+COPS?   -> +COPS: 0,0,"CHN-CT",7
AT+CSQ     -> +CSQ: 17, 99
AT+CREG?   -> +CREG: 3,0,"0000","00FFFFFFF",0,0,0
```

也就是说：**EPS 已注册到归属网络（stat=1，LTE，TAC 0x9A17，小区 0x03C341C3），
PS 已附着，运营商 CHN-CT**。`+CREG` 的 CS 域仍是 denied，这在没有配置 CS
fallback 的 LTE-only 附着下是预期的。

这是整条 bring-up 第一次拿到注册结果：从 MD 放行、HS1/HS2、CCISM RUNNING，
到 AT 通道可用、射频打开、SIM 识别、LTE 注册。

### 仍然没有的

**数据面**：既没有 CCMNI 网卡，也没有 CCB 通道，所以没有 PDP 上下文能承载流量；
语音/SMS 同样没有。下一步就是 CCB 控制区 + CCMNI netdev。

证据见 `evidence/modem-radio-registered.json`。

---

# CCMNI：LHIF 队列重映射与数据面传输的结论

本轮把「CCMNI 数据面为什么不通」查到了一个确定的答案，并且顺手补上了一个
必须应答的 RPC。

## 1. RPC 0x400d（LHIF 上行队列重映射）

`AT+CGACT=1,1` 成功之后，MD 通过 RPC 发来 `0x400d`，要求把 CCMNI0 的上行
映射到某个 LHIF 硬件队列。此前我们不认识这个 op，按 fail-closed 以
`-EOPNOTSUPP` 拒绝，整个 generation 直接以 `-95` 结束。

厂商语义（`port_rpc.c` / `port_rpc.h`）：

| 字段 | 值 |
|---|---|
| op | `IPC_RPC_CCCI_LHIF_MAPPING = 0x400D` |
| 载荷 | 一个 8 字节参数 `{u32 net_if; u32 lhif_q;}` |
| `LHIF_HWQ_AP_UL_Q0` = 2 | `txq_index = 0`，`txq_exp_index = 0xF1` |
| `LHIF_HWQ_AP_UL_Q1` = 3 | `txq_index = 3`，`txq_exp_index = 0xF3` |
| 非法队列 | 只打日志，**返回值被丢弃** |
| 应答 | 两个 0（`{0,0}`），MD 无法得知 AP 是否真的应用了 |

现在按同样方式应答，并把请求记录成一份可读状态（`md_net` 里的
`lhif_requests` / `lhif_ports` / `lhif0 net_if=… lhif_q=… queue=…`）。

真机上 MD 实际请求的是：`net_if=0, lhif_q=3` → **queue 3（AP 上行 Q1）**。
这也印证了队列是 MD 在运行时选的，不能写死。

顺带纠正一个数字：`port_cfg.c` 里 `DATA_TX_Q = DATA_RX_Q = 0`、
`DATA_TX_ACK_Q = 1` 是 `MD_GENERATION >= 6293`（本板 6297）的默认值；`3/3/4`
那组属于 ≤6292。所以默认队列 0 是对的，重映射是运行时的额外决定。

## 2. 决定性结论：本板的 CCMNI 不走 CCIF

`inc/ccci_hif.h`：

```c
#if (MD_GENERATION == 6293)
#define MD1_NET_HIF   CLDMA_HIF_ID
#else
#define MD1_NET_HIF   DPMAIF_HIF_ID     /* 本板 6297 走这条 */
#endif
```

也就是：**net 端口（CCMNI）的 HIF 是 DPMAIF**，CCIF 只承载 FS/RPC/AT/系统
消息这类"控制面"。这与 `mt6885/ccci_config.h` 里的 `DPMAIF_PKT_SIZE`、
`HW_FRG_FEATURE_ENABLE`、`DEBUG_FOR_CCB` 一致。

硬件上两边都验证过：

| 实验 | 队列 | PDP | 结果 |
|---|---|---|---|
| 放行 → 激活 PDP → 开闸 → 拉起网卡 | 3（MD 重映射后） | 已激活 | MD 在 `ccci_apis.c:1574` 断言，`para=0x16` |
| 无射频、无 PDP、无重映射 → 注入**单帧** 60 字节 | 0 | 无 | **同样**在同一行断言，`para=0x16` |

`0x16` 就是 22，CCMNI 发送通道。两次独立实验说明：**任何一帧走 CCIF
channel 22 都会被这个 MD 拒绝**，与队列和 PDP 状态无关。

MD 自己的转储：

```
BriefException: [EX Early Stage][core0,vpe0,tc0(vpe0)]
                Assert fail: ccci_apis.c 1574 0x16 0x0 0x0
SWVersion: NR15.R3.TC16.S.PR2.SP K6893V1_64_K419_20615S
```

所以上一轮"CCMNI 数据端口已经打通"的说法要收窄：**发送路径确实到达了 MD，
但 MD 不接受这条通道**。代码保留，但仍在 `md_net` 闸门之后，并在注释里写明
它不是本板的数据传输通道。

## 3. 顺序实验拿到的其它事实

- `AT+CFUN=1` 在一个新 generation 里的**第一次写入会被吞掉**（三次实验都是），
  紧接着重试即返回 `OK` 加完整 URC 串；这不是缺陷，是 MD 侧的行为。
- 射频打开后：`+CPIN: READY`、`+CSQ: 17`、`+CEREG: 3,1,"9A17","03C341C3",7`、
  `+CGATT: 1`，与上一轮一致。
- `AT+CGACT=1,0` → `ERROR`；`AT+CGACT=1,1` → `OK`，`+CGACT?` 显示 cid 1 已激活。
- `+CGCONTRDP` 显示激活出来的 APN 是 `sos.mnc011.mcc460.gprs`（应急 APN），
  地址字段是 16 个十进制字节；按字节读是 `240e:66:d800::21`，也就是**IPv6 上下文**。
  这一点只是按字节解读，没有规范层面的确认。

## 4. 下一步：DPMAIF

数据面必须实现在 DPMAIF 上。本板参数（`mt6893.dts`）：

| 项 | 值 |
|---|---|
| AO_UL | `0x10014000` |
| PD_UL | `0x1022D000` |
| PD_MD_MISC | `0x1022C000` |
| SRAM | `0x1022E000` |
| IRQ | `GIC_SPI 209` |
| capability | 14 |
| clocks | `CLK_IFRAO_DPMAIF_MAIN`, `CLK_IFRAO_DPMAIF` |

厂商侧这部分是 `ccci_hif_dpmaif.c` + `dpmaif_drv.c` 约 6.7k 行；mainline 里
已有同族实现 `drivers/net/wwan/t7xx/`（T700，PCIe 形态），寄存器语义可参考但
接入方式不同。这是一个新的子系统工程，不是一次补丁。

证据见 `evidence/modem-ccmni-lhif-remap-and-dpmaif.json`。

---

# DPMAIF 移植可行性考察（只考察，未开始移植）

结论先给：**6.6 那套明显更好移植**，而且它不是"别的板子的参考"，**它本身就已经是
op6893 的移植树**。

## 1. 6.6 树已经是 op6893 的移植树

6.6 树里有 145 个文件提到 `op6893`，CCCI 里带明确的 bring-up 注释，例如
`hif/ccci_dpmaif_com.c`：

```
op6893 6.6 bring-up: 4.19 DTB has no dpmaif-ver; MT6893 is v2
op6893 6.6 bring-up: ... without it the probe returns -1, so
    ccmni_ops.send_skb is never assigned, and every ccmni TX is dropped
op6893 6.6 bring-up: 4.19 DTB has no dpmaif-cap ... MT6893 official value 0x4
```

`fsm/md_sys1_platform.c` 把 `md_gen` 钉成 6297、`ap_plat_info` 钉成 6893，
`fsm/ccci_fsm_ioctl.c` 也写着 `md_gen = 6297`。也就是说这棵树已经把 DPMAIF 和
本板的 DTB、电源/时钟打通了。

## 2. 本板是 DPMAIF v2

- 6.6 `dpmaif_probe()` 在没有 `mediatek,dpmaif-ver` 时默认 `g_dpmf_ver = 2`；
- 6.6 `mt6833.dts` 的 dpmaif 节点与本板 `mt6893.dts` **地址映射完全相同**：
  AO_UL `0x10014000`、PD_UL `0x1022d000`、PD_MD_MISC `0x1022c000`、
  SRAM `0x1022e000`、`GIC_SPI 209`、clock `CLK_IFRAO_DPMAIF_MAIN` + `CLK_IFRAO_CLDMA_BCLK`；
- 6.6 该节点声明 `mediatek,dpmaif-ver = <2>`。

## 3. 寄存器一致率（脚本比对，按名字对齐偏移）

| 对比 | 公共名字 | 偏移相同 | 不同 |
|---|---|---|---|
| 4.19 vs 6.6 | 178 | **178** | 0 |
| 4.19 vs t7xx（补 `NRL2_` 前缀后） | 25 | 21 | 4 |

6.6 共定义 305 个 `NRL2_DPMAIF_*`，是 4.19 那 180 个的严格超集。

t7xx 的 4 处差异都在**上行每通道**寄存器：

| 寄存器 | 厂商 | t7xx |
|---|---|---|
| `AO_UL_CH0_STA` | `0x00` | `0x70` |
| `AO_UL_CHNL0_CON0` | `0x20` | `0x10` |
| `AO_UL_CHNL0_CON1` | `0x24` | `0x14` |
| `AO_UL_CHNL0_CON2` | `0x28` | `0x18` |

也就是：t7xx 与厂商共享 UL/DL BAT 与中断寄存器布局，但每通道上行寄存器被挪过，
是**同族不同修订**，不能直接当同款用。

## 4. 接入形态：6.6 简单得多

| | 4.19 | 6.6 |
|---|---|---|
| 挂接 | `port_net.c` → `ccmni_send_pkt` → `port_proxy` 取队列 → `ccci_hif_send_skb` → DPMAIF | `ccmni_ops.send_skb = &dpmaif_tx_send_skb_to_md`，一行函数指针 |
| 端口表 | 有（`port_cfg.c` 里 21 个 ccmni 端口） | **没有**（该树 `port_cfg.c` 里根本没有 CCMNI 条目） |

对我们来说这更贴合：我们已经有 netdev，只差一个 `send_skb` 实现。

## 5. 顺带一个好消息：数据面不需要 CCB

6.6 的 DPMAIF 与 `ccmni.c` 都**不引用** `ccci_shm_bm` / CCB；CCB 的使用者是另外
几个 CCIF 字符端口（`SMEM_USER_RAW_DBM`、`SMEM_USER_CCB_DHL`、`SMEM_USER_RAW_NETD`）。

也就是说，之前 feature 15 触发的 `ccci_shm_bm` 断言属于另一个子系统，
**DPMAIF 数据面不必等 CCB 解开**。

## 6. 规模

6.6 的 DPMAIF 是独立模块：`ccci_dpmaif_com.c` 3571、`drv_v3` 1864、`drv_v2` 1300、
`bat` 1236、`drv_v1` 759，加 debug/resv/page_pool 约 1000。本板只需要 **v2 + 共享部分**，
v1/v3 可以整块不带。4.19 则是单体 `ccci_hif_dpmaif.c` 4903 + `dpmaif_drv.c` 1835。

证据见 `evidence/modem-dpmaif-portability.json`。

---

# DPMAIF 只读核对：DT 与时钟依赖

在写任何驱动之前，先把 6.6 那套 DPMAIF 对 DT / 时钟的要求逐项查清，再和我们
现有的 mainline 树对比。

## 1. capability = 0x4，很多依赖因此不需要

6.6 `dpmaif_init_cap()` 在缺少 `mediatek,dpmaif-cap` 时回落到 **0x4**，注释写明
这是 MT6893 官方值；而 4.19 的 `mediatek,dpmaif_capability = <14>` **根本没有被
4.19 的 DPMAIF 驱动读取**（`ccci_hif_dpmaif.c` 里没有对应的 `of_property_read`）。

`mtk_ccci_common.h`：`0x4` = `MODEM_CAP_SGIO`（bit 2）。于是：

| 位 | 状态 | 后果 |
|---|---|---|
| `MODEM_CAP_LRO` (1<<4) | 关 | 单 RX 队列 |
| `MODEM_CAP_2RXQ` (1<<5) | 关 | `real_rxq_num = 1`、`max_pit_seq = 0xFE` |
| `MODEM_CAP_USE_RESV_MEM` (1<<6) | 关 | **不需要任何 reserved-memory 节点** |
| `MODEM_CAP_USE_MAX_BAT` (1<<7) | 关 | 分配阈值保持默认 |

也就是说 `mediatek,dpmaif-resv-cache-mem` / `-nocache-mem` 这两个节点**不用加**，
`ccci_dpmaif_resv_mem_init()` 会直接返回。

## 2. v2 初始化序列（6.6 `dpmaif_init_com`）

```
wakeup_source_register
dpmaif_init_register      iomap reg0=AO_UL, ao_dl=AO_UL+0x400, reg1=PD_UL, + infracfg regmap
dpmaif_init_cap           capability / rxq / max_pit_seq / dl_bat_entry_size
dpmaif_init_rx_irq_and_tasklet
ccci_dl_pool_init(real_rxq_num)
ccci_dpmaif_bat_init
ccci_dpmaif_debug_init, dma mask/parms
ccci_dpmaif_drv2_init
ccci_dpmaif_resv_mem_init   ← capability 0x4 时直接返回
dpmaif_init_clk
spd qos, ccci_hif_register, ccmni_ops.send_skb = dpmaif_tx_send_skb_to_md, net_speed
```

`ccci_dpmaif_drv2_init()` 本身只是**接线**：设三个派生基址
（`ao_md_dl = AO_UL+0x800`、`pd_rdma = PD_UL+0x200`、`pd_wdma = PD_UL+0x300`）
再挂一串函数指针，没有板级寄存器序列。真正的工作量在共享的 `com` / `bat` 里。

## 3. DT 依赖与我们的差距

| 项 | 6.6/4.19 需要 | mainline 现状 |
|---|---|---|
| dpmaif 节点 | 4 段寄存器（AO_UL `0x10014000`、PD_UL `0x1022d000`、PD_MD_MISC `0x1022c000`、SRAM `0x1022e000`）+ `GIC_SPI 209` | **不存在** |
| infracfg regmap | 写 `INFRA_DPMAIF_CTRL_REG`（`0xC00`）：置 `DPMAIF_IP_BUSY_MASK`（`0x3<<12`）、清 bit13（MD→AP wakeup） | 可复用 modem 节点已有的 `mediatek,infracfg = <&ufs_infracfg>` |
| 时钟门 `CLK_IFRAO_DPMAIF` | ifrao3 bank（`0xa4/0xa8/0xac`）shift 3，parent `axi_ck` | **缺** |
| 时钟门 `CLK_IFRAO_DPMAIF_MAIN` | ifrao4 bank（`0xc0/0xc4/0xc8`）shift 26，parent `dpmaif_main_ck` | **缺** |
| topckgen | `CLK_TOP_DPMAIF_MAIN`(171)、`_SEL`(243) | **缺** |
| `mediatek,mddriver` 查询 | 取 md_generation / ccci-infracfg | 不适用：我们是 `realme,op6893-modem-platform`，generation 已知为 6297 |

## 4. 时钟偏移的来源已经交叉验证

mainline `clk-mt6893-pmif.c` 现有 `ccif_gate_regs = {0x88, 0x8c, 0x94}`，
与 4.19 `clk-mt6885.c` 的 `ifrao1_cg_regs` **完全一致**。这说明 mainline 的偏移
就是从同一张厂商表推出来的，因此 DPMAIF 的两个门可以直接按 ifrao3/ifrao4 落位。

现有门策略是 `mtk_clk_gate_ops_setclr` + `CLK_IGNORE_UNUSED`（保留 LK 状态、
不主动关断），DPMAIF 的门可以沿用，不需要动 SCP 拥有的门状态。

## 5. 结论

**不需要引入新的子系统**：只差一个 DT 节点和两个时钟门，数字全部有来源。
真正的移植工作量在 `ccci_dpmaif_com.c` / `bat.c` 的共享逻辑，而不是板级适配。

证据见 `evidence/modem-dpmaif-dt-and-init-audit.json`。

---

# DPMAIF 第一步：时钟门、DT 节点与只读探测

按上一轮的核对结论，先做最小可验证的一步：把两个时钟门和 DT 节点补上，再写一个
**只读**探测驱动，确认时钟、映射、regmap 与寄存器读取全部可达。不动任何数据路径。

## 1. 时钟门

| 门 | 寄存器组 | shift | parent |
|---|---|---|---|
| `CLK_IFRAO_DPMAIF` (39) | ifrao3 `0xa4/0xa8/0xac` | 3 | 观察型 AXI |
| `CLK_IFRAO_DPMAIF_MAIN` (74) | ifrao4 `0xc0/0xc4/0xc8` | 26 | 观察型 AXI |

两者都是 `CLK_IGNORE_UNUSED`：注册不改变 LK 留下的门状态，消费者显式投票才动。

## 2. 真机抓到一个只有上机才会暴露的缺陷

第一张镜像 `cd289c3e79c1` probe 直接失败：

```
op6893-dpmaif 10014000.dpmaif: error -ENOENT: no dpmaif-main clock
```

原因不是门没注册，而是 **onecell 数组太小**：`clk-mt6893-pmif.c` 里
`num_clks = CLK_IFRAO_CCIF2_MD + 1 = 70`，而 DPMAIF_MAIN 是 **74**，超出范围后
`of_clk_hw_onecell_get` 返回空。改成取各已启用 id 范围的最大值即可。

host 测试看不到这个：它只在 provider 与 consumer 同时在世时才出现。

## 3. 只读探测结果（镜像 `6995dbbe7d35`）

```
op6893-dpmaif 10014000.dpmaif: dpmaif observed: irq=242, 4 blocks mapped, no register written

ao_ul=0x10014000 pd_ul=0x1022d000 pd_md_misc=0x1022c000 sram=0x1022e000 irq=242
clock_main=dpmaif-main clock_bus=dpmaif

ao_ul_chnl0_sta=0x00000000 ao_ul_chnl0_sta0=0x00000000 ao_ul_l2timr0=0x00000000
pd_ul_add_desc=0x00000000 pd_ul_add_desc_ch0=0x00000000
pd_md_ip_busy=0x00000000 pd_md_ip_busy_mask=0x00000001
sram_raw0=0x5d20c209 sram_raw1=0x5e56519b infra_ctrl=0x00003000
busy_mask_field=3 wakeup_event_bit=1 md_busy_mask_field=0
clk_main=156000000 clk_bus=156000000
```

读法：

- **两个门都能打开，父频 156 MHz** —— 时钟路径与映射是真的；
- UL 描述符与通道状态为 0，因为还没有任何东西初始化数据路径，这是**预期的初始化前状态**；
- `infra_ctrl = 0x3000`：两位 busy 字段是 3，且 **MD→AP wakeup 位仍然置着**，这是 LK
  留下的状态；
- SRAM 窗口读到非零残留字，说明该块已上电且可读，不是卡死；
- 连续三次读取（MD 停在 `lk-on`）结果完全一致。

## 4. 过程中修掉的一个语义错误

厂商的 `DPMAIF_IP_BUSY_MASK = 0x3 << 12` **包含 bit13**，而 bit13 随后被单独清掉。
我最初把 `wakeup_event_bit` 当成布尔去和这个掩码相与，host 测试立刻抓到了（两个常量
本来就重叠）。现在分别报告两位字段值和 wakeup 位，语义与厂商序列一致。

## 5. 尚未确认

**IRQ 编号**：DTS 请求 `GIC_SPI 209`，live devicetree 也确认是 `<0 209 4>`，但
`platform_get_irq` 报的是 **virq 242**。因为没申请中断，无法从 `/proc/interrupts`
的 hwirq 列反查，所以这一项留到**安装中断处理程序的那一步**再确认，不在本轮猜测。

数据路径本身（UL/DL 描述符环、BAT/PIT 表、中断处理）尚未实现。

证据见 `evidence/modem-dpmaif-recon-probe.json`。

---

# DPMAIF 第二步：上行路径打通（一帧进 MD）

这一轮把 DPMAIF 的上行环、门铃和完成中断实现出来，并在真机上让 MD 消费了 4 帧。

## 1. 实现

| 部分 | 做法（照同板 v2 驱动） |
|---|---|
| 环 | `dma_alloc_coherent` 2048 个两字描述符；每帧一个 message 描述符 + 一个 payload 描述符，最后一个清 `c_bit` |
| 编程 | `UL_DRBSIZE` bits15:0 写字数、`ULQSAR` 写基址低 32 位、bits31:24 写高字节，然后置 `CHNL_ARB0` 的 ready 与 arb 位 |
| 门铃 | 轮询 `ADD_DESC` 的 `NOT_READY`，写 `(字数 \| UPDATE)`，再轮询 `NOT_READY` 清零 |
| 中断 | 清状态锁存 → 清掩码位（置位=屏蔽）→ 仅在启动期间申请 IRQ → 回写已处理状态位 |
| 控制 | `ul_start "<queue> <bytes>"`、`tx_one <channel>`、`ul_stop` |

## 2. IRQ 编号已确认

上一轮留下的疑问解决了。启动 UL 后：

```
242:  ...  GICv3  241  Level  op6893-dpmaif
```

hwirq **241 = 32 + 209**，与 DTS 的 `GIC_SPI 209` 一致；之前的 242 只是 Linux 映射号。
`ul_stop` 后该行消失，说明 `free_irq` 正常。

## 3. 负向对照：MD 没运行时

MD 停在 `lk-on`，在 queue 0 上发一帧：

```
sent=1 done=0 irqs=1 err=1 last_status=0x00008400
```

`0x8400` = bit10（MD not ready）+ bit15（MD power not ready）——正是无基带时应有的状态。
这说明环、门铃、状态解码本身是通的，不依赖 MD。

## 4. 正向结果：MD 运行时

HS2 已接受（`state=4 hs2_seen=1`）、CCISM RUNNING、PDP 上下文 1 已激活，然后：

```
sent=4 done=4 irqs=4 err=0 not_ready=0 last_status=0x00000001
```

- 每帧**恰好一次**上行完成中断，无错误、无 MD-not-ready；
- `md_ee` 无异常记录，AT 仍能应答（`+CSQ: 18`）；
- `ul_stop` 后中断释放、掩码恢复 `0x01ffffff`、基址与大小清零。

**这是 AP→MD 数据第一次走在正确的传输通道上并被 MD 消费，且没有触发任何断言。**

## 5. 一个重要发现：映射是按上下文变的

| 上下文 | MD 的请求 | 结果 |
|---|---|---|
| 应急/IMS 上下文 | `net_if=0, lhif_q=3` | CCMNI0 → queue 3 |
| 本次 cid 1（ctnet） | `net_if=1, lhif_q=2` | **CCMNI1 → queue 0** |

也就是说 `cid ↔ CCMNI ↔ 队列` 三者是**逐上下文绑定**的，队列和 CCMNI 索引都不能写死。

## 6. 自己引入并修掉的一个隐患

`ul_stop` 最初只释放 DMA 环，却**没有清 ULQSAR/UL_DRBSIZE**，硬件里留下指向已释放内存的
基址。已在 stop 里清基址、大小、高字节并清状态。

诚实说明：修复后重跑能正常到 HS2；修复前只出现过一次 `-110` 握手超时。所以这个隐患是
真实存在的，但「-110 就是它造成的」只是**合理推断，未被证实**。

## 7. 没有做到的

- **帧是否被 MD 网络栈接受**：载荷是私有 ethertype + 合成 MAC，`done` 只证明传输层消费了
  描述符，不证明 MD 转发了它；
- **下行**：BAT/PIT 环、下行中断、接收路径都还没实现，所以没有任何包回来；
- **IP 流量**：没有配置地址，也没有观察到 PDP 载荷。

证据见 `evidence/modem-dpmaif-ul-path.json`。

# DPMAIF 下行环（2026-11-18）

上行打通后，下一步是下行：MD 通过 PIT 条目告诉 AP「某个 BAT 槽里有这么多字节」，
AP 读走并把槽还回去。本轮把这条环装上了，并把它拆掉过。

## 1. 装上之后的寄存器状态（镜像 `adf4e596e306`）

```
bat=256 pit=16384 buf=1664 frg=0/0 pit_rd=1024 bat_wr=0
irqs=0 pkts=0 bytes=0 msg_pits=0 frag_pits=0
err=0 mtu_err=0 overrun=0 pit_init_stuck=0 last_status=0x00000000
```

```
pd_dl_bat_init=0x00000001  con0=0x41600000 con1=0x00400100 add=0x00000100
pd_dl_pit_init=0x00000001  con0=0x41640000 con1=0x00004000
                          con2=0x00000400 con3=0x04000001 add=0x00000000
ao_dl_pit_sta0=0x41640000 sta1=0x00004000 sta2=0x00000400 sta3=0x04000001
ap_misc dl_status=0x00000000 dl_mask=0x000000be
```

四个延迟更新寄存器（BAT_INIT / BAT_ADD / PIT_INIT / PIT_ADD）全部 settle，状态锁存为 0，
中断已申请（hwirq 241）。`dl_stop` 之后中断释放、基址与大小清零、`PIT_STA3` 的索引位清掉，
MD 仍是 `state=4`，`AT+CSQ` 照常应答。

## 2. 真机上才暴露的四个阻塞点

**分片 BAT 环与 PIT 环互斥。** 先装分片 BAT 再装 PIT，`PIT_INIT` 的 NOT_READY 永远不清，
状态锁存 `PITCNT_LEN_ERR`；把顺序换成 BAT→PIT 并**完全不做分片环**，PIT 立刻 settle。
因此本轮把 MTU 收到单缓冲大小（1664），硬件不会需要分片；真出现分片条目按 overrun 计数丢弃。

**PIT 门铃不能再加满环。** init 已经把容量公布出去（AP 索引 1024 时剩余计数读回 `15359`），
再写 `PIT_ADD = 16384` 会溢出，门铃一直 busy。厂商启动时也不加，只在消费后补。

**PIT ready 位不清不是致命错误。** 两个厂商驱动里这个握手都是 `void`，超时只打日志。
之前把它当致命错误，于是环根本没装成。现在记成 `pit_init_stuck` 并继续。

**AP 索引与写索引必须相等。** 厂商的索引检查会把两者改成一致。现在 `PIT_INIT_CON3`
带 AP 索引、`PIT_INIT_CON2` 带写索引，软件读指针从硬件报回的写索引起步（实测 1024）。

## 3. 排除掉的假设（都做过，都不成立）

- 与 MD 是否运行无关：MD 停在 `lk-on` 和到 HS2 时是同一种失败；
- `INFRA_AO_MEM` bit10（DPMAIF 保护位）开机就是置位的（`0x00000f3c`），不是缺的前提；
- 清 MD 侧重排寄存器 `PD_MD_MISC+0x100` 无效；
- 打开全部 AP 侧时钟门（`AP_MISC_CG_EN=0xff`）无效；
- PIT 环 512 与 16384、AP 索引 0 与 1024、提前屏蔽下行事件，都无效；
- 厂商式 AO+PD 复位能把 `PIT_INIT` 拉回 0 且 MD 不受影响，但同样的编程会再次卡住——
  说明这条环从已知状态可复现，不是残留状态。

## 4. 明确没有做到的

**没有任何下行包。** 计数器全零，因为上行从未发过有效载荷，网络没有理由回包。
`pit_rd` 从硬件写索引起步这一选择来自厂商不变量，还没有被一个真实到达的包验证。
分片重组未实现；drain 只把有界头部复制进快照并回收缓冲，不把包交给协议栈。

证据见 `evidence/modem-dpmaif-dl-ring.json`。

# 下行数据尝试与一个 MD 侧故障（2026-11-18）

环装上之后，下一步是让 MD 真的往下发一个包。这一轮把能想到的变量都试了，
一个包也没下来；并且发现了一个会打死 MD 的组合。

## 1. 上行载荷格式（已从源码确认）

DPMAIF 的上行载荷就是**裸 IP 报文**，`lhif_header` 属于 CCIF/CLDMA 路径。
每包元数据在消息描述符里：`channel_id` 是 **CCMNI 索引**（`struct ccci_rpc_queue_mapping`
的注释写明 `net_if` 就是 ccmni index），`network_type` 来自 RIL 的 `SIOCSNETTYPE`，
默认 0。

队列映射同样不能写死：`ccci_rpc_remap_queue()` 把 `lhif_q=2`（`LHIF_HWQ_AP_UL_Q0`）
映射到 `MD_HW_NORMAL_Q = 0`，`lhif_q=3` 映射到 `MD_HW_IMS_Q = 3`。两种取值真机上都出现过。

## 2. 试过但都没有回包

| 尝试 | 结果 |
|---|---|
| IPv4 ICMP echo 到 PDN 的 DNS，源地址用 PDP 分配到的地址 | 上行描述符被消费（`sent=1 done=1 err=0`），下行 PIT 写索引不动 |
| IPv6 ICMP echo 到网关、到公网解析器 | 同上 |
| IPv6 ICMP echo 到自己的 PDP 地址 | 同上 |
| `network_type` 扫 0/1/2/3 | 无差别 |
| 补上厂商的 AP 索引通知（`PD_UL+0xAC=0xff`，再 `PD_MD_MISC+0x1C=bit0`） | 无差别 |

所以「描述符被消费」只证明传输层收下了描述符，**不证明 MD 转发了这个包**。

## 3. 下行环本身就会打死 MD（上一版结论已修正）

上一版把崩溃归因于「两个环同时运行」。用 `both_rings` 诊断开关复现后，这个归因是错的：

**只要下行环装上、且 MD 已放行，崩溃就会发生，完全不需要上行流量。**

```
offender=MCU ex_type=49 class=fatal pc=0x91831724 lr=0x91831764
cause=0x40800824 status=0x6002 code=0x305,0x88880302,0xcccccccc
addr 每次不同（0x86fc4c4b / 0xb294f00e / 0xb294f00f / 0x32b4f00f / 0x3296f00f）
```

| 场景 | 结果 |
|---|---|
| 已放行 + PDP 激活，只装下行环、不发任何上行 | **10 秒内出现上述致命异常** |
| 已放行、无 PDP，只装下行环 | 30 秒内出现另一种 MD 断言：`mcu/l1/cl1/common/cl1fr.c:973`，`para=0x13,0x13,0x20` |
| 下行环已装 + 上行发数据 | 另见过一次 `mcu/protocol/lte_sec/errc/lcel/protect/errc_lcel_paging_protect.c:591` 断言 |

所以上行不是触发条件，**互斥闸门并不保护任何东西**——下行环单独就足够。闸门保留只是
因为两个环都还不能用，不是因为它挡住了这个故障。

`ex_type=49` 是 `0x31 = SYS_FATALERR_EXT_TASK_EXCEPTION`，即 MD 任务主动上报的 fatal，
不是 CPU 原生异常，所以固定 pc 更可能是「上报点」。故障地址全部未对齐且都落在普通 AP
内存里（不在 `lk_regions` 报的两个 MD 保留 bank 内），`cause` 解出来是 MemManage
DACCVIOL + 栈解压错误 + 非对齐 + HFSR FORCED —— 即 MPU 拒绝访问后再次出错。

### 为什么 pc 反查不了

`md1img` 分区在主线里可读（`/dev/sdc28`），头 64 KiB 与留档的 `md1img-head-64k.bin`
逐字节一致，`FILE_INFO` 里的 SWVersion 也和 MD 自己异常转储里的对得上。但镜像主体是全
高熵（约 7.2 bit/byte），代码不能反汇编，只有少量明文串表（`ccismcore`、`dpmaif`）。
这次 fatal 记录 `file_supported=0`，MD 也没给源文件名。

### 找到但未证实的缺口

厂商 v2（4.19 与 6.6 两份实现完全相同）在 `drv_md_hw_bus_remap()` 里配了一整套 MD 域
总线重映射：`AO_MD_DL` 的 domain `0x0101`、cache bank `0x0607`、8 个 32 MiB 窗口（间隔
64 MiB，从 MD 保留内存基址起）、最后置 `CFG1` bit0。我们**从未写过**这些：实测
`CFG1=0x02`（重映射未使能）、`REMAP_DOMAIN=0x0707`、8 个 MAP 寄存器全 0。

用 `poke` 按厂商形状写入（假设基址 `0x40000000`）后寄存器读回完全一致，但故障仍在
60 秒内出现。所以重映射确实缺，但**要么基址不是 0x40000000，要么它不是这次故障的原因**。

另有一处实质差异：厂商 MTU 写 3080（`3*1024+8`）、`BAT_BID_MAXCNT=3`，我们写 1664、1
（因为去掉了分片环）。两者都是引擎参数，而故障在 MD CPU 侧，不足以解释。

真机验证过的闸门行为（保留为默认，非修复）：

```
dl_start 允许 → ul_start 被拒(-EBUSY) → dl_stop → ul_start 允许
→ dl_start 被拒(-EBUSY) → ul_stop → dl_start 允许
```

`both_rings=1` 可绕过闸门，仅供观察下复现该故障。

### 一个分配限制

本板 `dma_alloc_coherent` 拒绝 4096×1664（6.8 MB）与 8192×1664（13.6 MB），报 `-ENOMEM`，
而 256×1664（426 KB）成功（当时空闲 10.4 GB）。所以要测厂商的 8192 项 BAT 几何，必须改
成页分配 + `dma_map_single`，也就是厂商用 `__dev_alloc_skb` 的做法。

## 4. 工具

- `tx_hex`：按调用者给的字节串发上行，报文在主机上构造并自校验，不放进驱动；
- `peek`/`poke`/`reset`：限定五个已映射块、环运行时拒绝，加厂商的 AO/PD 复位序列。
  这把每个寄存器假设从一次刷机变成几秒钟；
- `modem-ip6-probe.py`：构造并自校验 IPv4/IPv6 回显请求；
- `ssh-wifi.sh`：USB gadget 掉线时用 Wi-Fi SSH（`10.65.84.170`）。两次 USB 消失期间
  设备一直在线，说明掉的是 USB gadget，不是设备。

证据见 `evidence/modem-dpmaif-dl-data-attempt.json`；崩溃归因修正与新增诊断开关见
`evidence/modem-dpmaif-md-fault-cause.json`。
