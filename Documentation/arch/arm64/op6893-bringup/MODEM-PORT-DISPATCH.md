<!-- SPDX-License-Identifier: GPL-2.0-only -->
# MT6893 握手、服务与 CCISM 端口分发

2026-11-16，基于 `90fffa41c` 离线接续。新增默认关闭的
`CONFIG_OP6893_CCCI_DISPATCH`，依赖 SERVICES 与 CCISM。父 MD owner 只构造
分发器并提供只读 `dispatch` 状态，不调用 prepare/start，不释放 MD CPU。
本轮没有设备操作、镜像刷写或新增蜂窝验收，`service_ready=0` 保持不变。

后续已接本机部分RPC事实、用户RPC policy和typed runtime builder，并纠正cache
预填假设，见[最新接续](MODEM-BOOTSTRAP-PROFILE.md)。下文为原分发里程碑的边界。

## 生命周期与顺序

未来唯一 MD owner 必须持父生命周期锁，先证明 MD CPU/DMA 已停止、准备供电
和 CCIF 环，再调用 prepare(generation)。prepare 只允许一次：预留已打开的
独占后端、取得真实 SCP/CCISM lease。后端 reservation 与会话 arm 分开，避免
在 MD 放行前失去后端，又避免 runtime 未发布就接收文件请求。预留后断连立即
关闭 CCIF 准入，不能重新打开 FD 接续旧代际。

start 先安装故障通知再启动既有握手 controller，不执行 CPU release。进入
controller 前释放 dispatch mutex，允许控制回调按 controller→dispatch 顺序
执行。controller 只在 SRAM HS1 通过既有校验且 runtime/SRAM 回复发布成功后
转发 accepted HS1；此时端点 arm，允许 FS/RPC。发布失败、重复或乱序 HS1
不能开启服务。accepted HS2 先入 service 有序队列，再交 CCISM bridge，之后
system RX2 才能进入桥。普通 FS RX14、RPC RX32 进入同代 service endpoint。
未知端口、异常通知及错误状态关闭准入，不静默吞包或伪造成功回复。

controller 新增 pre-start 故障 callback；该 callback 在 controller mutex 下
只记录首错并排工作，不等待、不获取其他 mutex。计时器在 HS2 后继续检查
底层 RX 故障。dispatch fault worker abort 服务和 CCIF 一次，保留所有资源。

stop(false) 无操作。只有调用者提供真实 CPU/DMA 停止证明后，stop(true) 才按
CCIF RX/controller join → fault work join → endpoint stop/擦除 → bridge STOP/
SCP 回复与 offline 的顺序关闭。任一步失败继续阻止父 prepare/off/shutdown；
允许再次 stop 收尾，但不允许重新 prepare。RX 关闭、FAILED 或 generation
均不是硬件停止证明。主动 unbind 尚不支持；当前仅支持内建 dormant unwind，
未来活跃移除还必须覆盖父电源、映射和回调生产者的整体生命周期。

## RPC 与文件服务

endpoint 在私有有序 worker 中执行内核 RPC：只有本机 A 路由的 `0x400f/0x4010`
交给用户态。真正未知操作返回 vendor NO_OP=-1；已知但 provider 不可用则故障
封闭，不能冒充未知操作或改交用户态。GPIO/ADC 名称、EINT 属性和 MD DT 查询
的纯 typed provider 接受外部审计过的 immutable 完整 namespace；默认 NULL，
没有填入本机事实或执行硬件采样。set_rpc 仅可在 reserve/arm 前调用，调用者
必须保留表的存储直至 stopped cleanup。详见[RPC 能力边界](MODEM-RPC-PROVIDERS.md)。

私有工作副本补齐 FindFirst/Next/Close、vendor DOSentry、递归 XDelete 和 Move
目标删除；共享文件/搜索句柄上限 128。递归操作先预检整个私有树，禁止链接
和特殊文件；未承诺并发外部修改、原子性或掉电恢复。显式 FS runner 仍只处理
FS，收到用户 RPC 会退出，不能把它当成完整 bootstrap 后端。
见[恢复的语义和策略差异](MODEM-FS-SEMANTICS.md)。

## 验证与剩余工作

实际 dispatcher C 的 ASan/UBSan harness 检查构造失败、prepare/start 顺序、
同步 HS1 回调、HS1/HS2 门控、端口/故障路径、停止顺序、失败资源保留和单次
代际。依赖采用确定性模型，不证明 SMP 竞态或真实固件行为。独立实际 C 测试
覆盖 handshake/controller、endpoint/session/router/provider、CCIF TX 与 CCISM。
文件服务另有 19 项 backend、11 项 wire（含实际 C codec）及 10 项 runner 测试。
启用新组合和恢复原配置的 ARM64 Image.gz/modules 构建结果及日志哈希记录于
[evidence/modem-port-dispatch-validation.json](evidence/modem-port-dispatch-validation.json)。

接续为本机真实 RPC 事实与用户操作、feature36 cache 来源/填充、按实际服务
生成的 runtime offer/ready gate，以及唯一 MD CPU 启停 owner 与停止证明。
这些条件闭合后再做首次 CPU 放行、HS1/runtime/HS2、后置 CCISM、异常/停止
的合并上机测试；HS2 或 CCISM 完成仍不代表注册、通话或数据面可用。
