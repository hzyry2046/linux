# attempt110–111：命令模式面板上的早期 framebuffer 控制台

面板：`oplus20615_samsung_ams643ye01_pvt_1080p_dsi_cmd`（Samsung AMS643YE01，1080×2400，
DSI 命令模式，4 lane，DSC 8bpc→8bpp，slice 540×8）。LK 的 `atag,videolfb`：base `0x78310000`，
size `0x1df0000`（3 块 1080×2400×4 缓冲）。

## 方案

沿用 LK 已经在运行的管线：双路 OVL（`OVL0_2L`/`OVL1_2L` 图层 0 = LK buffer 2 `0x796fc000`，
右半屏偏移 `0x870`）→ … → DSC → DSI0。`op6893-fbkick` 每 33 ms 重复 LK 的 direct-link 触发
（mutex0 EN、DSI CMDQ `0x002c3909`、DSI START），DSI 连续约 1 s 忙时重启该帧；序列参考
Mu-Silicium `Silicon/MediaTek/MT6893Pkg/Library/DisplayTriggerLib`。`simple-framebuffer`
覆盖同一块缓冲（行宽 1088×4）。`mblock-18-framebuffer` 加 `no-map`，否则 ioremap 拒绝映射 RAM。

## attempt110（`df0defa789ee`）：黑屏

fbkick 正常出帧（数千帧，无忙、无重启），fbcon 已注册，devmem 读到帧缓冲里有像素，
但屏幕全黑。

排查：用户态 `tools/dsi-dcs.c` 经 DSI CMDQ 发送 DCS，`0x28`/`0x29`/`0x51`/`0x23` 均正常应答；
`0x23`（all pixels on）时屏幕全白数秒——面板、供电、命令通道都正常，问题在像素通路。

根因：LK 给图层 0 打开了 per-pixel alpha（`L0_CON=0x21FF`），背景为不透明黑
（`ROI_BG=0xFF000000`）；simplefb 用 `x8r8g8b8` 时 alpha 字节为 0，像素被当作完全透明。
LK 的图层 1 缓冲（`0x78D06000`）内容全 0（透明），没有遮挡。

## attempt111（`c5ab183d4601`）：显示正确

simplefb 改为 `a8r8g8b8`。用户确认：fbcon 内核日志、`OP6893 MAINLINE FBCON TEST` 三行、
色条（白黄青绿品红红蓝黑）全部正确。fbkick 无错误，无 Oops。

内核提交 `e685422fe`。测试工具 `mt6893-direct/tools/{dsi-dcs.c,fb-bars.c}`。

## attempt112（`047c34605919`）：亮度与熄屏

fbkick 注册 backlight 设备 `/sys/class/backlight/panel`（raw，非线性，max 2047，默认 600）。
probe 时先发 `0x53 0x20` 选普通亮度范围；不用 HBM（4.19 驱动在 >2047 时发 `0x53 0xE0`）。

用法：

```
echo 300 > /sys/class/backlight/panel/brightness   # 调亮度，0–2047
echo 4   > /sys/class/backlight/panel/bl_power     # 熄屏（Display Off，暂停送帧）
echo 0   > /sys/class/backlight/panel/bl_power     # 亮屏（恢复亮度、Display On、恢复送帧）
```

实测：50 → 2047 → 600 亮度变化与预期一致（用户确认）；熄屏 3 s 期间帧计数不增长，
亮屏后 fbcon 内容恢复；无 DCS 超时，无 Oops。

## 限制

完全依赖 LK 留下的时钟、电源和管线配置；没有面板初始化或 DSC 配置，
LK 若未点亮面板（例如某些启动路径）则无输出。fbkick 在 LK 管线不处于命令模式运行时直接
退出，不动硬件。
