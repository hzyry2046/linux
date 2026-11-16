<!-- SPDX-License-Identifier: GPL-2.0-only -->
# MT6893 Linux服务会话、后端入口与FS应答

2026-11-16，基于 `d8b5ad73f` 继续离线实现。本轮没有设备操作、打包或刷写。
没有MD CPU release、真实HS1/HS2、CCISM或蜂窝验收。默认关闭的
`CONFIG_OP6893_CCCI_SERVICES` 现在包含实际Linux会话、字符入口和显式FS runner；
**存在入口或后端已连接都不代表bootstrap服务已就绪。**

## Linux执行与生命周期

MD构造路径创建session和 `/dev/ccci-service-<device-name>`。构造只分配存储、
注册入口，不访问MD寄存器、不启动IRQ/会话或MD。原型端点为0600并要求
CAP_SYS_RAWIO，单后端独占打开。打开前后的准备仍由唯一MD owner负责。
新 dispatcher 已连接 accepted HS1 后的 arm，但尚无调用 dispatcher prepare/start
或 MD 释放的上层 caller，见[端口分发](MODEM-PORT-DISPATCH.md)。

session以私有有序工作队列串行执行router，32项有界输入队列复制请求/完整
回复。事件时间包含排队延迟；首片起60秒覆盖重组、后端与回复发布。
在后端提交及每片CCIF发送前再次核对期限与准入；BUSY/ENOSPC每10ms重试，
已发布片段不重放。队列满、超时、后端/协议故障关闭本代准入，异步调用
CCIF abort并报告首错，保留资源直到真实停止。

用户read每次取得一条完整canonical请求；短缓冲返回EMSGSIZE，copy_to_user
失败保留原请求。write先在内核校验generation/token/kind/slot/协议字段，
迟到/重复回复不入队；成功仅表示已复制排队，不是已送达MD。
后端关闭FD触发本代EPIPE与异步收发中止，不能在同代重连后继续旧事务。
原型不提供write-ready poll；poll用于请求可读及故障/断连通知。

端点另有独立文件操作mutex；submit/fault回调仅持队列spinlock，不拿父MD锁。
停止必须在真实MD CPU/DMA停止后进行，且调用者不持端点mutex：session先关
准入并join worker，再通过closing回调撤销后端、join文件操作和擦除存储。
stop(false)无副作用。父prepare/off/shutdown在服务仍armed时拒绝继续，
包括FAILED状态，不能用接收停止来证明MD已停止。

状态位于父设备只读 `services` 属性，始终显示 `experimental=1 service_ready=0`。
支持未启动/已停止对象的清理与打开FD的引用存活；主动移除活跃会话仍不支持，
拒绝销毁并保留callback存储。当前驱动内建、禁止bind属性且没有活跃启动 caller；
未来添加主动移除需同时解决父CCIF/电源资源与所有生产者生命周期，不能只释放端点。

## 私有实验记录格式

此接口是本树实验协议，未承诺稳定UAPI；没有兼容Android字符设备/ioctl的声明。
头固定32字节，所有字段little endian，不含指针或原生long：

| 偏移 | 类型 | 含义 |
|---:|---|---|
|0|u32|version，当前1|
|4|u32|kind：FS=0、RPC=1|
|8|u64|非零MD generation|
|16|u64|非零、逐请求不可复用token|
|24|u32|slot：FS0..4、RPC0..2|
|28|u32|后续canonical包长度|
|32|bytes|完整CCCI header及body，不是单片FS wire包|

FS完整包上限0x40c8、RPC2048。record/body两层长度与slot/channel必须一致，
FS MORE已清零。回复保留外层关联字段，内层改为对应TX channel；真实HIF
sequence/assert和FS分片仍由内核持有。不能把一次record拆成多次write，
也不能在短write后重试未知是否已接受的前缀。

## FS语义和显式runner

本轮对同一个AP `ccci_mdinit` 做离线静态分析，记录hash和函数/文件偏移，
没有搬入binary、反编译转储或私人文件。见[恢复的FS语义](MODEM-FS-SEMANTICS.md)。

- Move是普通文件复制，源保留；支持递归目标删除，按已证明flags处理只读错误，
  先完整暂存源数据再截断目标，不使用rename，不宣称原子替换或掉电持久性。
- GetFileDetail成功含24字节mtime/atime/ctime；错误中vendor未初始化字段清零。
- CMPT_Read完整五步/0x700路径支持真实阶段完成位图、错误、size/count/data四参数。
- FindFirst/Next/Close 已支持成功 DOSentry 和共享句柄，按本机 vendor 的特殊
  时间编码实现；XDelete 支持递归 flags 和删除数量返回，见 FS 语义文档。

`tools/modem_fs_wire.py`对canonical包及每个操作的参数宽度/长度先做完整检查，
再调用私有工作副本。`tools/modem_service_backend.py`仅在调用者显式提供
`--endpoint`、`--root`、`--generation`后运行，不由initramfs自动启动。
它每次读/写一个完整record，仅处理FS；RPC、未知语义、错误record或短IO
会关闭FD并结束，不伪造应答。根目录/标记等要求沿用[服务基础](MODEM-SERVICES.md)。
日志只用固定状态文本，不打印路径、payload或异常中的私有字段。

## 验证与接续

实际endpoint、session、router和两套codec联合编译的ASan/UBSan测试覆盖：
独占打开/RAWIO、短read/EFAULT保留、过期token/重复应答、RPC匹配、队列满、
后端断连、poll和停止擦除，以及打开FD/移除引用生命周期。锁、调度、misc
核心和MMIO由确定性模型替代，不能声称完整SMP或真机内核验收。
另有13项结构化FS测试、11项wire测试（含实际C codec）和10项显式runner测试。
启用服务/握手/CCISM的ARM64 Image.gz/modules和恢复基线构建通过。
首轮构建暴露current宏碰撞，已改名并在host shim加入同名宏防回归。
证据见[evidence/modem-service-endpoint-validation.json](evidence/modem-service-endpoint-validation.json)。

最新离线接续已增加后端 reservation、内核 typed RPC 分流及 accepted HS1/HS2
端口 dispatcher，见[集成与当前剩余条件](MODEM-PORT-DISPATCH.md)。当前仍无
活跃启动 caller、本机实际 RPC 事实或用户 RPC 后端、feature36 cache 策略、
真实 ready gate 和 CPU/DMA 停止原语，不能凭入口存在释放 MD。
