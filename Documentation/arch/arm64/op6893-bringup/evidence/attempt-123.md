# attempt123：simpledrm + kmscube，GPU 挂死与显示毛刺

内核 `7969e0599430`（提交 `00a0156e4`、`0fda547bf`、`89866da1e`），rootfs `debian-11c0a118e84c`，
panfrost 仍为手动加载的模块。测试程序源码在 `mt6893-direct/evidence/gpu-tools/`。

## 显示

`simple-framebuffer` 改由 simpledrm 驱动（`CONFIG_DRM_SIMPLEDRM`，fbcon 走 fbdev 仿真）。
Mesa 的 kmsro 在 simpledrm 上分配 dumb buffer，导出后由 panfrost 导入作为渲染目标；
simpledrm 在每次翻页时把它拷贝到 LK 的帧缓冲（`0x796fc000`），`op6893-fbkick` 每 33 ms
刷新一次命令模式面板。kmscube 能显示旋转的立方体。

## 问题一：GPU 挂死（runtime PM）

现象：

```
gpu soft reset timed out, attempting hard reset
gpu hard reset timed out
error powering up gpu L2 / shader / tiler
gpu sched timeout, js=1, config=0x7b00, status=0x8
```

每轮渲染 10 帧 1080×2400 离屏画面，轮间随机停 0.1–0.9 s：

| 设置 | 轮数 | job 超时 | 复位超时 |
|---|---|---|---|
| `power/control=auto`，每次复位前重写厂商 MFG ASYNC/QCHANNEL 位 | 150 | 10 | 40 |
| `power/control=on` | 150 | 0 | 0 |
| panfrost 自己禁止 runtime suspend（`00a0156e4`） | 200 | 0 | 0 |

不带 MFG 重写的 `auto` 只做过 60 轮（1 次超时，`on` 为 0 次），样本不足以单独下结论。
重写 MFG 位没有帮助，这个改动没有保留。真正的原因（MFG 电源域断电再上电之后缺少的
时序）没有查明；目前的做法是 `GPU_PM_NO_RT_SUSPEND`，驱动绑定期间 GPU 一直上电，
代价是空闲功耗。

## 问题二：显示毛刺（缓存一致性）

现象：屏幕上闪烁的短横线，主要在下 25%。抓取帧缓冲后看到的是单行、16 像素长、左端按
16 像素对齐的段（64 字节，一条 CPU cache line），内容是黑色或上一帧的颜色。

排查过程中排除的原因：

- GPU 渲染错误：离屏渲染后 `glReadPixels` 全部正确。（最初的“约 40% 坏帧”是测试程序把
  旋转方块的角算成了坏像素。）
- 拷贝早于渲染完成：等待 `dma_resv` 写栅栏后再拷贝，结果不变。
- fbkick/面板：只用 CPU 写帧缓冲时无错误。

原因有两个，都在 DRM 的 dma-buf 导出路径上（GPU 不是 DMA-coherent 设备）：

1. `drm_gem_map_dma_buf()` 用 `DMA_ATTR_SKIP_CPU_SYNC` 映射。dumb buffer 的页在分配时被
   清零，这些零还留在 CPU cache 里是脏的；GPU 写入内存之后，cache 行被写回，覆盖 GPU 的
   结果，成为固定在某一块缓冲区里的黑段。两块缓冲区一好一坏交替显示，看起来就是闪烁。
2. `drm_gem_fb_begin_cpu_access()` 只处理导入的缓冲区。simpledrm 读的是自己分配、被导出的
   缓冲区，没有任何同步，读到的是 cache 里的旧内容（上一帧的颜色）。

`0fda547bf` 的修改：映射时同步；把映射记在 attachment 上；给 `drm_gem_prime_dmabuf_ops`
增加 `begin/end_cpu_access`，对每个导入者做 `dma_sync_sgtable_for_cpu/device`；
framebuffer helper 对已导出的自有缓冲区也调用它们。

验证用 `kmsflat`：每帧把全屏清成一种新的纯色并翻页，翻页后从 `/dev/mem` 读回帧缓冲，
逐像素与屏幕中心像素比较。

| 内核 | 帧数 | 有错误像素的帧 |
|---|---|---|
| 只去掉 `SKIP_CPU_SYNC`（原因 1） | 300 | 228 |
| 完整修改 | 300 + 3000 + 500 | 0 |

未修改的内核没有跑过 `kmsflat`；它在 kmscube 下的表现是每隔一帧出现固定的黑段
（下 1/8 屏约 1574 个采样点）。完整修改后，kmscube 运行时对立方体以外的区域采样
500 次（间隔 137 ms），全部干净，期间没有 GPU 超时。

`PAN_MESA_DEBUG=nocrc`（关闭 transaction elimination）在修改前能让黑段消失，可作为旁证：
黑段所在的 tile 正是 GPU 认为“内容未变”而不重写的 tile。

## 未做

- runtime suspend 之后 GPU 无法复位的根因。
- panfrost 开机自动加载；buffyboard 与 KMS 客户端的切换。
- DVFS（固定 350 MHz）、长时间与多客户端压力测试。
- `0fda547bf` 改的是 DRM 公共代码，只在本机验证过，没有在其他驱动上回归。
