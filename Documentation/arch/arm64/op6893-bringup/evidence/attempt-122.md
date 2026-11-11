# attempt122：Mesa panfrost 在 Mali-G77 上渲染

内核 `f10326ec67ee`，rootfs `debian-11c0a118e84c`。原始记录在
`mt6893-direct/evidence/attempt-122/`。

## Mesa

- 源码：Debian `mesa_26.2.6.orig.tar.xz`，取自清华镜像。sha256 与 Debian 签名的 `.dsc` 一致
  （`b9436b3e…`）。archive.mesa3d.org 的 TLS 连接不通。
- 补丁：`pan_model.c` 中增加 `PAN_PROD_ID(9, 0, 0)` "G77"，tilebuffer 32768
  （Exynos 990 移植的经验：16384 会出现 DATA_INVALID_FAULT）。补丁见
  `mt6893-direct/evidence/mesa-g77-0x9080.patch`。
- 编译：在 arm64 chroot（qemu）中进行，不依赖 LLVM；需要的 CL 工具（`mesa_clc`、`vtn_bindgen2`、
  `panfrost_compile`）取自第一次带 LLVM 的编译结果。驱动只包含 panfrost gallium 与 panvk，
  使用 glvnd。
- rootfs：删除 Debian 的 Mesa、libLLVM 和 libz3，用占位包 `op6893-mesa-shim`
  满足它们的依赖，`libegl-mesa0`/`libgbm1` 设为 hold。镜像大小 85.7 MiB。

## 结果

```
EGL driver name: panfrost
OpenGL ES profile renderer: Mali-G77 MC9 (Panfrost)
GL_VERSION OpenGL ES 3.1 Mesa 26.2.6
```

surfaceless EGL 下的离屏 GLES2 测试（256×256 FBO，画一个三角形后 glReadPixels）：

- 三角形内的像素 (10,10) = 255,128,0,255，背景 (240,240) = 0,0,255,255，与预期一致。
- 连续 2000 帧（每帧都 clear、draw、readback）用时 1.57 s，dmesg 里没有任何 panfrost
  fault、timeout 或 reset。

没有设置 `op6893-gpu-probe`，所以厂商的 MFG ASYNC/QCHANNEL 位一个都没写。

## Vulkan

panvk 26.2.6 只支持 arch 10/12/13，以及需要 env 开关的 6/7/14，v9（G57/G77）直接报
“not supported”。这是 panvk 的限制，不是本设备的问题。

## /cache 清理

启动链只用到 `debian.squashfs` 和 `rootfs.img`。4 个旧镜像和上一版 rootfs 已备份到
`mt6893-direct/backup/cache-mainline/`（附 SHA256SUMS，与设备上逐个核对一致）后删除；
`/cache/mainline` 只保留上一版 `debian-070d5e8b69fe.squashfs` 作为回退。

## 未做

- 显示仍然是 simple-framebuffer，没有 KMS，kmscube 无法使用。
- 没有 DVFS，频率固定在 350 MHz。
- 没有做长时间或多客户端的压力测试（Exynos 990 上的 fault 就是在 KWin 长时间运行时出现的）。
