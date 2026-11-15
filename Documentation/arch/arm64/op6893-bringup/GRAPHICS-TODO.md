# GPU / 图形 TODO 清单

## 当前状态（attempt124）

- **GPU：** panfrost 1.7.0 驱动 Mali-G77（MT6893，13000000.gpu）。probe 成功，minor 1。
- **自动加载：** `/cache/mainline/modules/{gpu-sched,panfrost}.ko` 由 `op6893-ssh-start` insmod。
- **显示：** simpledrm + Mesa kmsro（dumb buffer 导出/导入）+ fbkick 刷新命令模式面板。
- **验证：** kmscube 肉眼测试无毛刺；kmsflat 3800 帧 0 错误（attempt123）。
- **runtime PM 绕过：** `GPU_PM_NO_RT_SUSPEND` 禁止 runtime suspend，GPU 一直上电。

## 积压任务

### 1. runtime suspend 根因（高优先级）

**现象（attempt123）：**

启用 `power/control=auto` 时，GPU 空闲断电后无法恢复：

```
gpu soft reset timed out, attempting hard reset
gpu hard reset timed out
error powering up gpu L2 / shader / tiler
gpu sched timeout, js=1, config=0x7b00, status=0x8
```

测试结果：

| 设置 | 轮数 | job timeout | 复位超时 |
|---|---|---|---|
| `auto` + 厂商 MFG ASYNC/QCHANNEL 位重写 | 150 | 10 | 40 |
| `control=on` | 150 | 0 | 0 |
| `GPU_PM_NO_RT_SUSPEND`（当前） | 200 | 0 | 0 |

**需要查的地方：**

- MFG 电源域（`13f90000.syscon@mfg`）的 SRAM 配置（SRAM_CON）、下电/上电时序。
  对照 4.19 厂商代码和 6.6 ACK port 的 `gpufreq_mt6893.c` / `gpupm_mt6893.c`。
- L2 cache、shader core、tiler 的上电初始化是否需要额外寄存器配置。panfrost 的
  `panfrost_gpu_power_on()` 是否对 MT6893 足够？
- MFG 的 bus protection 时序。当前 DTS 的 `mediatek,infracfg` 和掩码是否正确？
- MTCMOS ACK 位。电源域驱动等待的 ACK 与 MFG 的实际 ACK 延迟是否匹配？
- 是否需要在断电前保存某些 GPU 寄存器（如 MFG 的 ASYNC/QCHANNEL，已测试过但无效）？

**参考：**

- `/home/hzyry2046/.claude/projects/-data-src-mainline-linux/memory/op6893-reference-trees.md`
  列出了厂商 4.19 和 ACK 6.6 的源码路径。
- `drivers/pmdomain/mediatek/mt6893-pm-domains.h`：当前主线的 MFG 电源域定义。
- attempt123 记录：重写 MFG ASYNC/QCHANNEL 让超时从 1/60 变成了 10/150，更差。

### 2. DVFS（中优先级）

GPU 当前固定在 350 MHz（panfrost 的 OPP 表只有一项）。需要：

- 确认 MT6893 GPU 的频点和对应电压（查 ACK 或 4.19 的 OPP 表）。
- 接入 MT6315-3 的 VGPU11 供电轨（SPMI PMIC，已有 DT 节点但未验证）。
- 在 DTS 中增加完整的 `operating-points-v2` 表。
- 确保 MFG 时钟（mfg_ref_sel mux、mfgpll）在 devfreq 调频时能跟随。
- **依赖：** 必须先解决 runtime suspend 问题，因为调频涉及电源状态切换。

### 3. 长期压力测试（中优先级）

当前测试（attempt123–124）最长只有 200 轮 × 10 帧，约几分钟。需要：

- 跑 30–60 分钟以上的连续渲染（kmscube 或 glmark2）。
- 监控 `dmesg` 里的 GPU timeout、MMU fault、OOM。
- 监控温度（需要先实现 LVTS 的 thermal zone，当前无温度接口）。
- 测试多客户端（多个 EGL 上下文、并发 job 提交）。
- **当前：** attempt124 正在进行 30 分钟 kmscube 测试，监控 GPU 错误。

### 4. DRM cache sync 上游化（低优先级）

`0fda547bf`（"drm/prime: keep exported GEM buffers coherent for non-coherent importers"）
修改了公共 DRM prime 代码。需要：

- 清理 commit message，说明非相干 GPU（如 panfrost on MT6893）+ dumb buffer 导出/导入
  的场景（kmsro）下为什么需要 CPU cache sync。
- 确认其他平台（如 Rockchip + panfrost、Exynos 等）是否也需要这个修改。
- 在 dri-devel 发 RFC patch，收集反馈后再决定是否提交上游。
- **注意：** 上游可能认为这是平台 integration 问题（即 SoC 应该把 GPU 设为 DMA-coherent），
  或者建议用其他方案（如 dma-buf heaps）。

### 5. 完整显示驱动（低优先级，不依赖 GPU）

当前 simpledrm 依赖 LK 状态和 `clk_ignore_unused`。完整驱动需要：

- MMSYS、SMI（IOMMU）、CMDQ（mailbox）、DISP（OVL/RDMA/COLOR/CCORR/AAL/GAMMA/DITHER/DSI）。
- DSC（Display Stream Compression，面板是 AMS643YE01，DSC 必需）。
- 面板初始化序列（DCS 命令，可参考 6.6 ACK 的 `panel-ams643ye01.c` 或提取 LK 的序列）。
- DRM atomic modesetting，替换 `op6893-fbkick` 的定时刷新。
- **参考：** 6.6 ACK port 的 `mediatek_v2` 驱动已点亮该面板，可作起点。

### 6. buffyboard 与 KMS 客户端切换

当前 buffyboard 和 kmscube 都渲染到 `/dev/fb0`（simpledrm 的 fbdev 仿真）。同时运行时
会冲突。需要：

- buffyboard 检测活跃的 DRM master，有 KMS 客户端时自动退到后台。
- 或者让 buffyboard 直接用 KMS + libinput，不走 fbdev。

### 7. 电池 / 充电相关（attempt116–118）

- IBAT 只反映充电电流，未实现放电电流测量。
- 没有库仑计，CAPACITY 只是按 OCV 表估算的电压百分比，充电时偏高约 10 个百分点。
- VOOC 快充和电荷泵（MT6360 内部）未处理。
- 充电参数（500 mA / 4.38 V）沿用 LK，未根据电池规格调整。

### 8. SoC 温度（LVTS）

7 个 thermal controller、17 个传感器的初始化、RCK、校准已实测（attempt45–48），
但没有持续采样接口、thermal zone 或保护策略。需要：

- 实现周期采样和 sysfs 温度接口。
- 建立 thermal zone（CPU、GPU、电池等）和 cooling device（CPUfreq、devfreq）。
- 配置 trip point 和保护动作。
- **依赖：** DVFS 依赖温度监控。

## 相关文件

- 当前 GPU 驱动：`drivers/gpu/drm/panfrost/panfrost_drv.c`（MT6893 compat）、
  `panfrost_device.c`（`GPU_PM_NO_RT_SUSPEND`）。
- DRM prime 修改：`drivers/gpu/drm/drm_prime.c`、`drm_gem_framebuffer_helper.c`、
  `include/drm/drm_prime.h`（`0fda547bf`）。
- DTS：`arch/arm64/boot/dts/mediatek/mt6893-op6893-boot.dts`（GPU 节点，单 OPP）。
- 电源域：`drivers/pmdomain/mediatek/mt6893-pm-domains.h`（MFG0–MFG6）。
- 测试工具：`/data/src/mainline/mt6893-direct/evidence/gpu-tools/{kmsflat,fbcount,fbrows,fbsnap}.c`。
- 文档：`Documentation/arch/arm64/op6893-bringup/evidence/attempt-{121,122,123,124}.md`。
