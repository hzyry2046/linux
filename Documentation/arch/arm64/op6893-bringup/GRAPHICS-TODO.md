<!-- SPDX-License-Identifier: GPL-2.0-only -->
# op6893 图形环境与 GPU 待办

更新：2026-11-14。按当前任务安排，先为基带等大项目建立框架，再逐项完善；
下面的图形工作保留为后续事项。现状见 [attempt123](evidence/attempt-123.md)。
AI 辅助整理，未作外部提交。

1. **panfrost 自动加载**：将与启动内核匹配的模块及依赖纳入外置 rootfs，
   更新镜像哈希；验证冷启动、模块加载失败时控制台和 SSH 仍可用。
   当前记录中的模块为手工加载，不应把 `/run` 内的临时文件当作安装结果。
2. **图形程序与控制台切换**：明确 buffyboard、fbcon 和 KMS 程序的启动/退出
   顺序、VT/DRM master 所有权及触摸输入分配；程序退出或崩溃后恢复可用控制台。
   在这条路径稳定后再搭桌面或其他图形 shell。
3. **GPU runtime PM**：对照 MT6893 厂商 gpufreq/MFG 上下电与复位时序，
   解释断电后 GPU reset/L2 上电失败的原因。当前 `GPU_PM_NO_RT_SUSPEND`
   是常开供电的规避措施，恢复自动休眠前需做重复唤醒及渲染验证。
4. **DRM 公共缓存同步修改审查**：复查 `0fda547bf` 对 dma-buf attachment、
   map/unmap、begin/end CPU access、方向和锁的处理；扩大导入/导出与其他驱动
   的回归范围。当前只有本机 simpledrm/panfrost 路径的实测，不能推广为通用正确。
5. **GPU 压力与 DVFS**：补长期、多进程和内存压力测试及故障恢复；频率当前
   固定 350 MHz。明确时钟、电压、温度和 OPP 关系后再引入 DVFS。
6. **显示链路接管**：目前复用 LK 已初始化的链路，由 fbkick 定期刷新命令模式
   面板。完整主线 DRM/DSI/PHY/DSC/panel 接管、省电及系统休眠另行推进。
