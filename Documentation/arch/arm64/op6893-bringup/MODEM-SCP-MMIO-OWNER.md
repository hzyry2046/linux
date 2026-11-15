<!-- SPDX-License-Identifier: GPL-2.0-only -->
# SCP MMIO 映射接入唯一资源 owner

2026-11-15，HEAD `6db0f4606d6e` 工作树，AI 辅助实现、分析及测试。
接续 [MMIO 离线后端](MODEM-SCP-MMIO.md)。当前只接入映射，不调用 prepare、
RX/completion/ACK、不清继承消息、不启用 IRQ、不建立 generation/READY。
实机验证状态见文末；编译通过不计作 SCP/基带已支持。

## 唯一 owner 的映射选择

新增默认关闭的 `OP6893_CCCI_SCP_MMIO_RESERVE`，依赖既有 MMIO 后端和
NO_AUTOEN IRQ owner，且与 `OP6893_CCCI_SCP_PENDING_OBSERVE` 互斥。
独立后端选项仍只编译，不自动映射；另选 RESERVE 才在资源 owner 中接入。

probe 的相关顺序为：持有26 MHz时钟、全局唯一 claim、六页 non-posted
映射、申请五个 NO_AUTOEN IRQ、发布只读状态。原 cfg-only 分支只在未选择
新映射选项时编译/执行。不是先映射旧 cfg 再建立别名，也不创建第二个设备。
新路径的 owner->cfg 保持 NULL，owner->mmio 独占六页映射和状态。

DT/binding 的资源扩展为完整 cfg 与 mbox0–4 六个4 KiB页：
`0x10724000`、`0x107fb000`、`0x107fc000`、`0x107fd000`、`0x107fe000`、
`0x107ff000`。新 binding 要求六组名称/窗口，旧的单 cfg 实验 DT 需同步更新。
默认两个实验节点仍 disabled，默认内核不编入实验 owner。

旧 pending observer 的描述仍保留，供之前的只读诊断配置使用；新选项不
编译其映射路径，避免映射同一 mailbox 页的普通与 non-posted 别名。
Kconfig 同时请求两者时拒绝 MMIO_RESERVE；切换新路径须显式关闭 pending。
core0/header/bootstrap observer 可继续使用，与这六页不重叠。

任一资源冲突或映射失败直接终止 probe，不尝试 fallback/retry，不发送
SMC release。映射发生在 IRQ 之前，故映射失败不会留下 IRQ action。
IRQ 失败的既有 stop action 先关闭排队/同步，再由 devres 释放已申请 action
和映射，最后释放全局 claim；没有新的 RX worker 或客户端需要排空。
内建 owner 仍不开放 unbind。

## 状态与初始封闭条件

在 `/sys/devices/platform/10724000.scp-resource-hold/`：

- `mmio`：映射6页、24576字节、nonposted=1，累计寄存器读写数，prepared、
  generation、fault；此属性在 owner mutex 下只读取软件状态，不访问寄存器。
- `cfg`：保持原状态格式，报告 cfg 4096字节归属、实际 cfg 写计数和
  completion_enabled；新路径使用 MMIO 对象状态，不依赖旧 cfg 指针。
- `irq`：仍来自既有 owner 的五个专用 action，应保持 requested=5、
  gic_masked=5、unexpected/work_runs=0、arm_supported=0。
- `state`/`pin`：保留原先显式一次26M资源投票流程；probe 不发送 SMC。

新对象初始 `prepared=0 generation=0 fault=1`，这是既有后端主动封闭、未
建立代际的状态，不是一次硬件操作失败。所有实际寄存器计数应为0，
completion_enabled=0、ready_known=0。没有 sysfs prepare/clear/arm 入口。
MMIO/cfg 计数在实际访问后累计，不在 prepare/invalidate 时清零；这些是
驱动自身操作计数，不是固件或总线访问的硬件计数器。nonposted=1 描述实际
选用的映射 API，不是对本机 fabric 应答位置或协议清位的实测证明。

## 已完成验证

- `test_modem_scp_mmio_owner.py` 提取真实 owner probe、cfg/mmio show、
  unclaim，分别编译两条配置路径，ASan/UBSan 检查互斥分支、映射先于IRQ、
  每处失败传播及 claim 清理、状态串行化。外部 clock/devres/IRQ/mapping
  依赖为模型，不能代替实机或 Linux 完整 devres 并发验证。
- 真实 MMIO/RX/queue/drain sanitizer 回归，含累计访问计数；原 IRQ/queue/
  drain/RX/cfg/resource 回归通过。
- 实际 Kconfig 检查：同时请求 pending observer 时 RESERVE 不可用；关闭
  pending 后可选新路径。临时配置已恢复。
- 启用 Image.gz/modules、默认 Image.gz/modules 构建通过，无新增编译器
  告警；保留已有 FW_LOADER/VT defconfig 重赋值提示。
- 更新 binding 的 dt-doc-validate，通过；启用/默认 board 与合并后 DTB
  的三份定向 schema 及完整六页/cfg/IRQ 资源检查通过。此处不是整板全部
  binding 验证；部分 schema 集合不提供无关既有节点的类型信息。
- 新增/修改的 MMIO C/H 和 resource owner 全文件 strict checkpatch 0/0/0。
  默认节点仍 disabled，默认 vmlinux 不含实验 MMIO/IRQ/resource owner。

测试镜像 `fba1be648ead`，release `7.3.0-op6893-d1-fba1be648ead+`：
`/data/src/mainline/mt6893-direct/dist/fba1be648ead/boot.img`。
boot SHA256 `5c25d72cc9fadacc0b3ce0756f6e8e9393897c6596d591d5d7fdd562b9349160`。
构建包装脚本已恢复 DTS/defconfig，默认输出也已重建。
证据位于 `/data/src/mainline/mt6893-direct/evidence/scp-mmio-reserve`，结构化
结果见 [验证记录](evidence/modem-scp-mmio-owner-validation.json)。

## 上机与接续

已通过提前排队boot-only flash/reboot、sync+SysRq及用户拦截fastboot刷入
`fba1be648ead`，boot分区SHA256回读一致。六个完整页在 `/proc/iomem` 中均
归属 `10724000.scp-resource-hold`，不是只报告DT元数据。USB三轮和Wi-Fi
三轮读取均为mapped=6、nonposted=1、register_reads/writes=0、prepared=0、
generation=0、fault=1。该fault值表示初始未prepared的主动封闭状态。

五个IRQ action对应GIC hwirq468–472，均masked，所有CPU中断计数0，
unexpected/work_runs=0。旧pending observer已编译关闭，实际没有pending
sysfs属性，读取返回ENOENT；先前预期EOPNOTSUPP不准确，未执行寄存器读取。
本轮不采集新的pending值，不以payload或清位证明映射可用。

资源只读查询后显式一次26M pin，SCP user1、mask=0x02、pin_verified=1、
resource fault=0；CCF引用3/3、rate=26M。原core0/header/mux观测稳定，
USB/Wi-Fi SSH、8核、三UFS LUN只读、cache ext4 ro/norecovery、lower
squashfs只读及overlay根目录回归通过；限定故障关键字扫描无匹配。
没有测试真实MMIO事务、IRQ送达、按键/温度或USB故障切换。

设备保留该主线镜像及boot-lifetime pin，恢复备份和分区表未修改。映射归属
验收通过不代表SCP/基带启动、真实消息接收或READY。
映射验收以后才接真实 prerequisite、全部 RX/queue/drain、可开启IRQ/worker
的锁与disable深度、入队generation和STOP，再实现受控reset/旧消息隔离。
数字代号、继承状态和空pending均不建立本代READY，不能据此启动SCP/MD。
