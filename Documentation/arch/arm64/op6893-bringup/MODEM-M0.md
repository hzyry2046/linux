<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 基带 M0：交接与被动解析框架

2026-11-14，基于 `6db0f4606` 的工作树。AI 辅助实现与测试；未作外部提交。
本轮完成主机实现和编译，设备保持 Android，没有重启、刷写或启动主线基带。
这是本文件最初的离线阶段记录。随后实机验收已通过：实验镜像
`fe077e30d191` 的本次 LK 交接、20 项 tag、SMEM/CCB 解析成功，USB/Wi-Fi SSH
和外置 rootfs 回归通过；详见 [R3](MODEM-R3.md)。默认检查入口仍关闭。

## 实现范围

- `arch/arm64/kernel/op6893-fdt.c`：从本次 LK 的 `/chosen`、`/chosen@0`、
  `/mddriver` 白名单读取 `ccci,modem_info_v2`；多份存在时要求字节一致。
  校验 48 字节、小端 ABI、版本 2/3、MD1 加载状态、四个错误码、数量/长度
  上限和地址溢出。要求缓冲区同时属于原始 board DT 的 tag allowlist 和
  本次 LK 的静态保留区。缺失或不合法时省略属性，不阻止 AP 启动；删除
  board 中潜在的旧 header，避免缺失时沿用旧启动数据。
- `mt6893-op6893-boot.dts`：增加三个静态 no-map 保留区的本地引用与默认
  disabled 的 `modem-handoff`。节点名沿用历史 LK 的三个 mblock 名字，
  避免在当前布局下重复导入同一保留区。没有导入 vendor phandle 或设备节点。
- `drivers/misc/mediatek/ccci/`：独立的 tag/layout 解析器与可选检查模块。
  解析器限制 64 KiB、128 个 tag，检查名称终止、链环、重复、区间重叠、
  越界、已知字段最小长度，以及 SMEM/CCB 是否落在各自允许区域。
  不解释其他 payload，也不读取 payload 指向的物理地址。
- `CONFIG_OP6893_CCCI_LK_INSPECT` 默认关闭。显式打开配置并启用 DT 节点后，
  检查模块才会申请并读取 header 限定的 tag 区域。它读取两份快照，要求一致，
  解映射后在普通内存中解析；退出时清除快照和临时索引，仅记录阶段、错误码、
  版本、tag 数量、长度和 CCB 存在性。它没有 modem/SCP 的电源、复位、SMC、
  IRQ、DMA、共享环或端口操作，也不声称 MD READY。

运行时 driver 的检查阶段为 `regions`、`header`、`snapshot`、`tags/layout`。
目前细分失败原因由返回的 errno 区分；不会把未知 payload 或 tag 名写入日志。

## 当前 Android 的只读核对

通过 ADB 分别读取 `/proc/device-tree/chosen/ccci,modem_info_v2` 和
`/proc/device-tree/mddriver/ccci,modem_info_v2`，两份均 48 字节且一致：
基址 `0xbff70000`，有效长度 `0xa68`，版本 3，20 个 tag，load flag 1，
公共和四个 MD 错误码均为零。实际 C header 解码函数接受这份数据，并确认
落在板级 tag 保留区内。[核对记录](evidence/modem-m0-current-header.json)
只保存以上元数据，没有读取物理 tag、SMEM、固件或 NVRAM。

这证实当前 Android 保留了可用 header，不证明主线已获取它，也不证明真实
tag 链符合新解析器的全部规则。

## 主机验证

可复核的入口是 [test_modem_lk.py](tools/test_modem_lk.py)，编译实际 C 解析器
和 FDT 合并器，而不是另一套 Python 协议实现：

```sh
python3 Documentation/arch/arm64/op6893-bringup/tools/test_modem_lk.py \
  --board-dtb /data/src/mainline/mt6893-direct/out/arch/arm64/kernel/op6893-embed.dtb \
  --lk-dtb /data/src/mainline/mt6893-direct/evidence/ack-live.dtb
```

- header 长度、尾部填充、版本、加载错误、flag、地址/长度溢出用例通过。
- 合成 SMEM/CCB、未知 tag、短 payload、名称/链环/重叠、128 项链及后段回边
  用例通过；失败不返回部分 layout。
- 20,000 组确定性随机输入通过 ASan/UBSan；这不是完整模糊测试覆盖率证明。
- 实际 FDT 合并器通过单份/双份相同 header、chosen@0、冲突、损坏、缺失、
  不在 LK 保留区及 board 旧 header 用例，AP 合并仍成功。
- 原 `mt6893-direct/tests/test_fdt.py` 回归通过。主机 shim 已加入新共享 header
  的依赖；对三个本地 phandle 校验其仍来自 board，其他 vendor phandle 仍排除。
- ARM64 `Image.gz`、`vmlinux`、检查模块 `.ko` 构建与 modpost 通过，无编译警告；
  使用 `CONFIG_OP6893_CCCI_LK_INSPECT=m` 命令行覆盖，未写入默认 defconfig。
- 新 binding 的 `dt-doc-validate` 和限定此 binding 的 `dt-validate` 通过。
- 代码与 binding 分别执行 checkpatch；新增文件的通用 MAINTAINERS 提示不作为
  本地实验代码的实现错误。没有添加维护者条目或 Signed-off-by。

外部 `mt6893-direct/build.py` 已加入新测试并归档测试日志。默认构建保留
header 交接，但检查模块和 DT 节点仍关闭。构建日志位于该目录的
`modem-m0-build.log`，本轮没有打包或发布可刷写 boot 镜像。

## 尚需解决与下一步

1. 在安排主线实验前，核对真实 tag 链的终止形式、已知结构大小、是否有合法
   payload 别名。当前仅接受末项 next 为零或有效长度，SMEM/CCB 最少 40/16
   字节；这些是本机厂商 ABI 导出的保守规则，尚未经过真实 tag buffer 验收。
   遇到拒绝先定位规则与厂商布局，不直接放宽边界。
2. 对 tag 区域的读取仍需确认 AP 权限、映射属性和 LK/MD 所有权。两份快照
   相同不能证明 DMA 一致性或原子快照；保留区和资源申请也不能证明总线访问
   一定不会 fault。因此保持检查节点 disabled，不能自动加载后试读整块固件。
3. M0 主线实机验收包括：新启动的 header 确实保留、受限 tag/layout 检查通过，
   以及 USB/Wi-Fi/存储回归。本轮未做，等待用户安排重启窗口。
4. 无需等待用户态逆向即可继续 M1 源码工作：梳理 SID3 supplies、MD 域/时钟/
   复位、CCIF2 与 SCP 的资源所有权和 ATF 调用契约；先形成资源补丁，再接
   控制栈。当前缓存 SMEM 大小差异仍未解决，不进入 DMA 或基带启动实验。

上述离线资源梳理随后完成，见 [MODEM-RESOURCES.md](MODEM-RESOURCES.md)。
确认 SCP 为 RV、基带还有 VPU/VRFDIG 第四路供电，以及通用 MD 关机序列与
ACK 的差异；M1 控制代码与 M0 主线实机验收仍未完成。
