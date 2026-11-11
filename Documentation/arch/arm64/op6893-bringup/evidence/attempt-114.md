# attempt114：buffyboard 屏幕键盘

内核 `7c08e2ae6276`，rootfs `debian-070d5e8b69fe`。

## rootfs

- 软件源改为清华镜像（trixie、trixie-updates、trixie-security），原文件保留为
  `/etc/apt/sources.list.orig`。
- trixie 没有 buffyboard，从 sid 装 `buffyboard 3.5.1+dfsg-2`（依赖 libinput10、
  libinih1、libudev1 用 trixie 版本）；另装 udev、evtest。
- `op6893-ssh-start` 在后台启动 `systemd-udevd --daemon` 和 buffyboard，日志
  `/run/buffyboard.log`。内核打开 `INPUT_UINPUT`。
- 旧 rootfs 在设备上保留为 `/cache/mainline/debian-1ed1b45c80c2.squashfs`。

## 点击不灵

现象：键盘出现，但大部分点击不生效。

1. 中断为下降沿时，空闲也有中断，但按下/抬起事件很少。改为 `IRQ_TYPE_LEVEL_LOW`。
2. 以 2 ms 轮询寄存器 0–8 发现：手指抬起后 FT3518 经常不发抬起事件（事件位 0x40），
   寄存器一直保持最后一个触点（TD_STATUS = 1），只有压力字节在手指真正按住时变化。
   于是 evdev 上约 1 秒才出现一对按下/抬起。
3. `edt-ft5x06` 对 FT3518 增加判断：报告连续 120 ms 完全不变即视为全部抬起，
   之后相同报告忽略直到数据变化。厂商驱动有同类 200 ms 检查（`fts_prc`，默认关闭）。

结果：慢速点按 20 秒共 15 次，每次都有一对按下/抬起，按住 0.05–0.17 s；用户确认
键盘点击灵敏、工作正常。

工具：`mt6893-direct/tools/ft-trace.c`。
