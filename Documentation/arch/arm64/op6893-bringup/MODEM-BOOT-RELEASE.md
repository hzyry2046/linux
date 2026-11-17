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
   `pc=0x91823b66 addr=0x90d18620`）。`md1rom` 基址为 `0x90000000`，两个地址
   都落在基带镜像自身，说明不是 FS 应答格式问题。
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
没有改变 MPU 异常。LK 还提供 `md_mpu_inf`（216 B，9 条）与 `md_mpu_num`，
对应厂商用 `mtk_emimpu` 为 MD 编程的 EMI MPU 区域表——这是目前唯一已知的、
AP 侧尚未实现的同板 MD 保护配置，是下一个候选。

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
