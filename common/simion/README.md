# SIMION公共实现层

本目录保存不含器件身份、专用坐标系或运行模式假设的SIMION公共实现。`particle_source.py`接收已经由
上游适配器转换到工作台语义的beam或逐粒子状态并生成FLY2/Lua文本；多极杆的ION11和canonical字段映射
仍由`common/multipole/simion_particle_source.py`负责。

项目间连接的矩形开孔统一调用[`aperture.py`](aperture.py)：机械宽、高任一小于一个cell时失败关闭；
非整数cell倍数或孔边缘未落在网格节点时保留机械尺寸并输出机器可读离散警告；GEM减材固定使用
`exclude_shape_inside_or_on_v1`，不得用隐藏epsilon扩大机械孔。编译或缓存PA后，所有生产消费者还必须
通过[`aperture_topology_support.ps1`](aperture_topology_support.ps1)调用
[`verify_aperture_topology.lua`](verify_aperture_topology.lua)，确认法兰厚度方向至少有一条贯通非电极节点列，
并确认孔外四侧接地guard仍存在；FAIL禁止Fly。该入口面向仓库内所有未来SIMION项目连接，不绑定多极杆、
oaTOF、single-flight或具体电极编号。

`surface=fractional`只提高非对齐表面的场与边界表达精度，不保证连续几何精确，也不能替代真实PA拓扑审计
或网格敏感性验证。本层不选择PA/IOB和物理参数；商业进程仍由项目runner按统一预算与串行规则启动。

[`resource_scheduler.py`](resource_scheduler.py)是独立粒子批次与相互独立完整case的唯一SIMION并发决策实现。
项目只提交总粒子数、独立性和网格、RF步数、trajectory quality、PA哈希等客观数值身份；CPU、内存、并发、
安全系数、观察时长和危险处置均由公共层固定，项目参数会被拒绝。粒子数只改变运行时间，不用来假定单进程
瞬时资源占用。资源允许的并发数决定同时活跃的进程数与同一数值身份的工作通道数；粒子数不构成
单进程资源上限。调度器在每个通道只安排完成其份额所需的批次，并使各通道的总粒子数尽可能相等，
避免没有物理或实测依据的单批粒子数上限及由此造成的额外分波。

完全相同的历史数值身份可直接复用单进程峰值并跳过观察。没有历史时，首个正式批次取
`ceil(N/min(N,10))`个粒子；它最多观察30秒但始终继续运行，若提前自然完成也直接保留结果。实测后按CPU
`floor((95%-后台占用)/max(10%,单进程实测))`和内存
`floor((当前可用内存-2 GiB)/单进程安全预算)`的较小值确定最终并发。Windows 设置页虽显示为
“GB”，但本公共合同按其二进制容量语义明确记为`GiB = 1024³ bytes`，避免歧义。首次正式观测与精确历史画像
都使用实测峰值的1.10倍作为单进程预算；每次错峰启动前还以仍在运行任务的新峰值重新计算一个进程的准入
余量，故后续内存增长会立即暂停扩容。观测时的可用内存已排除仍在运行的首批，因而内存/CPU计算的是可新增
槽位，调度器会再准确加上该首批；首批仍运行时占用一个槽位，剩余
粒子只分给其余槽位；首批结束后，该通道只补齐到与其余通道相同的总工作量。首批已完成时全部槽位
分配剩余粒子，绝不重跑首批。各进程相隔5秒启动；CPU高只暂停
新启动，不终止进程。可用内存低于2 GiB暂停启动；低于1 GiB持续15秒才按“最晚启动优先”逐个终止、重新排队并
降低并发，每次处置后等待5秒再判断。

成功运行只保留紧凑调度收据，不保留逐秒探测文件。 [`resource_profile.py`](resource_profile.py)发布首个正式
批次的独立峰值并用run manifest及输入收据SHA-256复核；并行聚合峰值不得按进程数拆分。PA/IOB构建及没有独立粒子/可合并结果
合同的SIMION任务保持串行；未知case资源身份每次先运行一个正式case，只有同一完整输入的已观测峰值才可参与
后续case wave。已完成case campaign可以把画像写入manifest覆盖的summary；后续运行只发现这种受完整性保护的
画像，不接受裸日志或未受manifest覆盖的JSON。调度器不会发现、批准或启动campaign，也不会在外层campaign之上创建嵌套并发。

Windows能力依据（2026-08-26查阅）：Microsoft `MEMORYSTATUSEX/GlobalMemoryStatusEx`文档说明
`ullAvailPhys`表示可立即复用的物理内存，用于2 GiB/1 GiB门限；.NET `System.Diagnostics.Process`文档支持读取
`WorkingSet64`和`TotalProcessorTime`；Microsoft `taskkill /T`文档支持只终止选中PID及其子进程。采用这些接口
是为了测量真实SIMION进程族，并在持续内存危险时只回收最新批次。

- https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/ns-sysinfoapi-memorystatusex
- https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.process?view=net-10.0
- https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill
