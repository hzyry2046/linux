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
