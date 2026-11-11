# attempt121：panfrost 在 Mali-G77 上 probe

内核 `fb8d6af02761`。原始记录在 `mt6893-direct/evidence/attempt-121/insmod.txt`。

## 加载

panfrost 编译为模块，按 `drm_shmem_helper` → `gpu-sched` → `panfrost` 的顺序手动
insmod（放在 `/run/gpumod`）。本次开机没有触发 `op6893-gpu-probe`，所以厂商的
MFG ASYNC/QCHANNEL 额外设置都没有写。

```
panfrost 13000000.gpu: clock rate = 350000000
panfrost 13000000.gpu: mali-g77 id 0x9080 major 0x0 minor 0x1 status 0x1
panfrost 13000000.gpu: features: 00000000,000019f7, issues: 00000001,80000400
panfrost 13000000.gpu: Features: L2:0x07120206 Shader:0x00000000 Tiler:0x00000809 Mem:0x301 MMU:0x00002830 AS:0xff JS:0x7
panfrost 13000000.gpu: shader_present=0x660067 l2_present=0x1
[drm] Initialized panfrost 1.7.0 for 13000000.gpu on minor 0
```

出现了 `/dev/dri/card0` 和 `renderD128`。

## 运行时电源管理与 ioctl

- 空闲时 MFG0–6 全部关闭（PWR_STATUS `0x10580e03`）。
- 通过 `GET_PARAM` 读到 PROD_ID 0x9080、REVISION 0x11、SHADER_PRESENT 0x660067、
  TILER 0x809；`CREATE_BO` 1 MiB 成功（GPU VA 0x2000000）。访问期间
  PWR_STATUS 为 `0x10580fff`。

## 操作教训

不要用 `tar -C /` 解压 `lib/...`：Debian rootfs 中 `/lib` 是指向 `usr/lib` 的
符号链接，tar 会把它替换成普通目录，导致所有动态链接的程序都无法运行，
SSH 随之中断。好在 rootfs 是内存 overlay，重启即可恢复。

## 未做

- rootfs 中还没有 Mesa（没有 `dri` 目录），GPU 还没有执行过任何作业。
- 没有 DVFS：频率固定在 LK 设置的 350 MHz。
- 显示仍是 simple-framebuffer，没有 KMS 输出。
