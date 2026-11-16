<!-- SPDX-License-Identifier: GPL-2.0-only -->
# MT6893 FS/RPC 服务基础与接续边界

2026-11-16，基于 `82dbc5aa7` 完成离线实现。初始轮没有设备操作、打包或刷写，
没有新增 HS1/HS2、CCISM 或蜂窝支持验收。源格式与证据见
[服务审计](MODEM-SERVICES-AUDIT.md)，验证见
[evidence/modem-services-validation.json](evidence/modem-services-validation.json)。

最新接续已补Linux session/端点、FS wire及显式runner，并恢复部分此前未知操作，
见[服务入口与当前边界](MODEM-SERVICE-ENDPOINT.md)和[FS语义](MODEM-FS-SEMANTICS.md)。
仍无活跃MD启动caller、完整provider或服务就绪门控。

## 已实现的部分

- FS：普通 q4、RX14/TX15、五槽。每片重复 opcode，负载上限 `0xd80`；
  重组整包上限 `0x40c8`，最多六参数，严格检查长度与四字节对齐。
  最后一片提供 canonical header。线上没有片序号，因此不能凭格式发现同槽、
  同 opcode 中间片丢失或调序；不能把合成测试当成完整传输可靠性证明。
- RPC：普通 q1、RX32/TX33，整包最多 2048 字节、六参数、槽位 0..2。
  解析请求、编码回复、校验请求关联；按同板 4.19 区分用户态/内核归属，
  不直接继承 6.6 新增 opcode 的归属，也不为已知硬件查询伪造成功值。
- 普通 CCIF 回复发送：独立每通道 TX sequence、WAIT_HS2 assert 规则、
  BUSY/ENOSPC 不发布、发布错误粘滞及 STOP 同步。发送在 sleepable 上下文，
  输入不可变；实际 HS2 状态必须由可信 owner 提供，不能来自后端回复。
- 有界请求路由：五个 FS 槽、三个 RPC 槽，外部串行化；每次提交携带
  generation 和单调递增 64 位 token，防止同代槽位复用后的迟到回复误配。
  回复校验后保留不可变副本，FS 分片发送在 BUSY/ENOSPC 后从未发布处继续。
  从首片起 60 秒期限覆盖整个事务；超时、线上格式错误与回调故障保留首错。
  外部 abort 不执行 I/O、不释放仍属活跃 MD 的资源。
- 路由只能在真实 HS1/runtime 回复成功并进入 WAIT_HS2 后 begin；accepted HS2
  后由 owner 更新状态。退出这两个阶段前必须 abort/quiesce。close(false)
  不改变状态；只有真实 MD CPU/DMA 已停止才能 close(true)，擦除请求、回复
  与 scratch。代际标签、接收停止或 FAILED 状态均不能证明硬件已停止。

`CONFIG_OP6893_CCCI_SERVICES` 默认关闭。最新实现已加入Linux有序worker/timer、
独占字符入口和手动FS runner；submit复制、回调不重入及真实停止契约仍保留。
尚无活跃dispatcher/MD启动caller、硬件RPC provider或服务就绪门控，详见上方接续文档。

## 私有文件工作副本原型

`tools/modem_fs_backend.py` 是结构化参数后端，现已接canonical wire adapter与显式FS runner。
仅接受调用者预先准备的可丢弃工作副本：根目录归当前用户且权限 0700，
确认标记为 0600 的普通单链接文件。标记只是调用者确认，不能证明副本来源。
不提供原件导入、复制、恢复或直接挂载 Android 数据的操作。

支持 Open/Seek/Read/Write/Close/CreateDir/GetFileSize、两个已观察 GetDrive
查询、SetDiskFlag、普通文件Move、GetFileDetail及受限CMPT_Read成功/失败阶段。UTF-16LE 路径经逐层目录 fd
遍历，拒绝上跳、符号链接及特殊文件；写入前检查普通文件及单链接，Close
按已确认 flags 执行 fsync。每个请求先核对 generation，shutdown 先撤销代际
再关闭句柄。测试只使用临时合成树，没有访问真实 NVRAM。

下列项保留 UnsupportedOperation，不能序列化成猜测的 vendor errno：

- Move目标为目录时的递归XDelete语义。
- FindFirst成功DOS entry及查找；缺目录失败布局已恢复。
- CMPT非完整五步、非0x700 flags。
- 未观察GetDrive查询、其他opcode及目录/OTP/device/ioctl操作。

正常 Android 启动已有实际写入证据，因此只读原件不能替代可写私有工作副本。
本原型不是所有 bootstrap 请求均可服务的证明。

## 下一组实现

1. 完成仍未支持的FS语义；wire与已实现操作应答编码已接，按实际实现生成能力清单，
   未知语义阻止启动，不用通用 NO_OP 或零值代答。
2. Linux worker/队列和后端入口已接，继续连普通端口dispatcher，
   关联超时/断连/HS2/STOP；按真实 provider 准备内核与用户态 RPC。
   当前缺完整冷启动 RPC census，历史 flight 查询不能代替该清单。
3. 明确 runtime feature36 NVRAM cache 的填充策略；预留内存不是服务能力。
4. 补唯一 MD 启停 owner 与真实 CPU/DMA 停止原语，再合并首次 CPU 释放、
   HS1/runtime/HS2、后置 CCISM、异常与停止的硬件测试。

## 本轮验证的范围

实际 C 的 ASan/UBSan 覆盖 FS/RPC codec、路由、真实 CCIF ring/sender；
sender 包含 STOP pthread 竞争、最小 FS 尾片、最大 FS/RPC 包、序号回绕和
故障发布。路由覆盖 token 迟到应答、分片续传、期限、abort 和 stopped-close；
Python 后端覆盖合成工作树的正常操作与路径/链接/代际限制。
启用服务/握手/CCISM 的 ARM64 Image.gz/modules 及恢复基线配置构建均通过。
这些验证不能证明真实固件请求全集、SMP 调度、硬件顺序或蜂窝可用性。
