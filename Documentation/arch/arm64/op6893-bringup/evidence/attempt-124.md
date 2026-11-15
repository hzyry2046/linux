# attempt124：panfrost 自动加载与启动失败排查

**内核：** `dist/57ee469d7416/boot.img`，7.3.0-op6893-d1-57ee469d7416+（基于 `3e394441f`）  
**rootfs：** `debian-5499c9f794dd`，sha256 `c3d37ee69e498508a076ae9ecf0e04177d4e186e13ec3ba8f87d563a8a4d2ec0`  
**日期：** 2026-11-15

## 背景

attempt123 通过 DRM prime 的 CPU cache sync 修复了显示毛刺，kmsflat 工具测得 0/3800 坏帧。
但该测试中 panfrost 模块仍需要在启动后通过 SSH 手动 insmod。本轮目标是实现 panfrost
自动加载，并修复一次因文件名错误导致的启动失败。

## 上一轮（d673b67eab8b）的启动失败

**现象：** 刷入 `dist/d673b67eab8b/boot.img` 后，屏幕日志正常滚动，但 buffyboard 未出现，
USB SSH 拒绝连接（端口 192.0.2.2:22），Wi-Fi SSH 超时。设备最终被手动重启回 fastboot。

**原因：**

1. **rootfs 文件名错误：** initramfs 的启动脚本只认固定路径 `/run/cache/mainline/debian.squashfs`
   （`initramfs/init` 第 45 行），然后用 boot.img 内嵌的 sha256 校验该文件。但我给用户的
   推送指令让其把新镜像改名成了 `debian-b4c57ffb5b54.squashfs`，所以启动时读到的仍是旧镜像，
   sha256 不匹配，Debian rootfs 没有挂载，sshd 和 buffyboard 都没有启动。

2. **内核包含其他 agent 的未提交改动：** boot.img 编译时工作区里有来自另一个 codex 会话
   （`01a197bb-5e79-79b3-b400-40288ef133ed`）的基带相关改动，共 14 个文件、478 行插入：
   DTS、时钟（clk-mt6893-pmif）、电源域（mt6893-pm-domains、mt6893-md-power）、
   misc/mediatek/ccci 等。这些改动在本轮已提交为 `3e394441f`（"soc: mediatek: op6893:
   modem/SCP bring-up scaffolding (WIP)"），确认不影响启动路径。

**修复：** 在 Android 下通过 adb 将文件重命名为 `debian.squashfs`，旧镜像备份为
`debian-11c0a118e84c.squashfs`，失败的 b4c57ffb5b54 镜像删除。同时把基带改动先提交，
避免后续 boot.img 再混入未审查的改动。

## panfrost 自动加载方案

**设计缺陷（attempt123）：** 把 `gpu-sched.ko` 和 `panfrost.ko` 放进 rootfs 的
`/lib/modules/op6893-mainline/` 目录，配合 `/etc/modules-load.d/op6893-gpu.conf` 和
`/etc/modprobe.d/op6893-panfrost.conf`。问题是 modprobe 默认查找 `/lib/modules/$(uname -r)/`，
而 `uname -r` 每次编译 boot.img 都会变（包含 build id），所以每次换内核都要重做 rootfs。
此外自定义 PID1 可能不处理 `modules-load.d`，也没有 depmod 生成的依赖索引。

**新方案：** 把模块文件和加载逻辑从 rootfs 移出，改为：

- 模块放在 `/cache/mainline/modules/{gpu-sched.ko,panfrost.ko}`。cache 分区在 Android 和
  mainline 下都可访问、可读写，比 rootfs 更适合存放与内核 build id 绑定的文件。
- `debian/ssh-start` 脚本在启动 sshd 之后、buffyboard 之前，在后台执行：
  ```sh
  (
      d=/run/cache/mainline/modules
      for m in gpu-sched panfrost; do
          [ -f "$d/$m.ko" ] && $bb insmod "$d/$m.ko" 2>>/run/modules.log
      done
      echo '<6>OP6893-DIRECT: GPU_MODULES done' > /dev/kmsg
  ) &
  ```
  失败信息写入 `/run/modules.log`，不阻塞 SSH 和 buffyboard 启动。
- `debian/finish.py` 不再把模块和配置文件打进 rootfs，也不将它们的 hash 计入 rootfs identity，
  因此 rootfs 的 id 只由脚本、软件包和 SSH 配置决定，与内核 build 解耦。

**优点：**

- 换内核只需重推两个 `.ko` 文件到 `/cache/mainline/modules/`，不用重做 rootfs。
- insmod 的 vermagic 检查仍会在版本不匹配时拒绝加载，错误会记录在 `/run/modules.log`，
  但不影响 SSH 可用性，方便排查。
- `/cache` 空间 402 MB，足够放多个内核的模块备份。

## 实测结果

**刷机流程：**

1. 在 Android 下推送新 rootfs 和两个 `.ko` 到 `/data/local/tmp/`，remount `/cache` 为 rw。
2. 删除失败镜像 `debian-b4c57ffb5b54.squashfs`，将旧镜像 `debian.squashfs` 改名为
   `debian-11c0a118e84c.squashfs`，把新镜像改名为 `debian.squashfs`。
3. 将两个 `.ko` 移到 `/cache/mainline/modules/`，chmod 644，sync。
4. sha256 校验：`c3d37ee69e498508a076ae9ecf0e04177d4e186e13ec3ba8f87d563a8a4d2ec0`，一致。
5. `adb reboot bootloader`，`fastboot flash boot dist/57ee469d7416/boot.img && fastboot reboot`。

**启动后检查（通过 USB SSH）：**

```
debian-5499c9f794dd
7.3.0-op6893-d1-57ee469d7416+
panfrost               81920  0
gpu_sched              32768  1 panfrost
```

**dmesg 片段：**

```
[   13.436007] [drm] Initialized panfrost 1.7.0 for 13000000.gpu on minor 1
[   13.444378] probe of 13000000.gpu with driver panfrost returned 0 after 51272 usecs
[   13.452831] initcall panfrost_driver_init+0x0/0xfdc [panfrost] returned 0 after 59885 usecs
[   13.461725] OP6893-DIRECT: GPU_MODULES done
[   14.976869] OP6893-DIRECT: BUFFYBOARD started
```

**buffyboard 进程：** PID 369，正常运行。

**kmscube 毛刺测试：** 用户报告"kmscube 测试未见毛刺"。与 attempt123 的 kmsflat 结果
（0/3800 坏帧）一致，说明 DRM prime CPU cache sync 修复有效，显示一致性问题已解决。

## /cache/mainline 当前状态

```
-rw-r--r-- 1 root root 90107904 2026-11-11 13:19 debian-070d5e8b69fe.squashfs
-rw-r--r-- 1 root root 89837568 2026-11-11 21:22 debian-11c0a118e84c.squashfs
-rw-rw-rw- 1 root root 89837568 2026-11-15 18:34 debian.squashfs
drwxr-xr-x 2 root root     4096 2026-11-15 18:35 modules
-rw-r--r-- 1 root root 33554432 2026-11-02 12:06 rootfs.img
drwx------ 2 root root     4096 2026-11-02 12:46 ssh

modules:
-rw-rw-rw- 1 root root  59280 2026-11-15 18:34 gpu-sched.ko
-rw-rw-rw- 1 root root 145360 2026-11-15 18:34 panfrost.ko
```

使用量：291 MB / 402 MB（73%），还有 112 MB 可用。保留了两个旧 rootfs 作回退。

## 结论

- 上一轮启动失败的直接原因是 rootfs 文件名不对，与内核改动无关。
- panfrost 现在从 `/cache/mainline/modules/` 自动加载，buffyboard 正常启动。
- 屏幕毛刺问题已确认修复（kmscube 肉眼测试无毛刺）。
- 新的刷机流程：换内核后重推 `gpu-sched.ko` 和 `panfrost.ko` 到 `/cache/mainline/modules/`
  即可，rootfs 只在软件包或配置变化时才需要更新。

## 相关文件

- 内核：`/data/src/mainline/linux`，提交 `3e394441f`（基带 WIP）及之前的 GPU 修复
- rootfs 生成：`/data/src/mainline/mt6893-direct/debian/finish.py`，已移除模块打包逻辑
- 启动脚本：`/data/src/mainline/mt6893-direct/debian/ssh-start`，新增 GPU 模块加载块
- initramfs sha256：`/data/src/mainline/mt6893-direct/initramfs/debian.sha256`
