# SIMION公共实现层

本目录保存不含器件身份、专用坐标系或运行模式假设的SIMION公共实现。`particle_source.py`接收已经由
上游适配器转换到工作台语义的beam或逐粒子状态并生成FLY2/Lua文本；多极杆的ION11和canonical字段映射
仍由`common/multipole/simion_particle_source.py`负责。

项目间连接的矩形开孔统一调用[`aperture.py`](aperture.py)：机械宽、高任一小于一个cell时失败关闭；
非整数cell倍数或孔边缘未落在网格节点时保留机械尺寸并输出机器可读离散警告；GEM减材固定使用
`exclude_shape_inside_or_on_v1`，不得用隐藏epsilon扩大机械孔。编译或缓存PA后，所有生产消费者还必须
通过[`aperture_topology_support.ps1`](aperture_topology_support.ps1)调用
[`verify_aperture_topology.lua`](verify_aperture_topology.lua)，确认法兰厚度方向至少有一条贯通非电极节点列，
并确认孔外四侧接地guard在法兰内部厚度节点仍存在（两端面连接相邻真空域，不作为侧壁判据）；FAIL禁止Fly。该入口面向仓库内所有未来SIMION项目连接，不绑定多极杆、
oaTOF、single-flight或具体电极编号。

`surface=fractional`只提高非对齐表面的场与边界表达精度，不保证连续几何精确，也不能替代真实PA拓扑审计
或网格敏感性验证。本层不选择PA/IOB和物理参数；商业进程仍由项目runner按统一预算与串行规则启动。

所有新建SIMION Workbench必须从[`assets/iob_instance_seeds/`](assets/iob_instance_seeds/README.md)
中与实际PA实例数一致的干净GUI种子派生。该公共目录提供1--10槽连续容器和唯一占位PA；派生器必须替换每一个槽，
不得创建空槽或保留占位实例。种子只用于生成运行目录或正式交付目录中的派生IOB，绝不原地修改。

[`resource_scheduler.py`](resource_scheduler.py)是独立粒子批次与相互独立完整case的唯一SIMION并发决策实现。
项目只提交总粒子数、独立性和网格、RF步数、trajectory quality、PA哈希等客观数值身份；CPU、内存、并发、
安全系数、观察时长和危险处置均由公共层固定，项目参数会被拒绝。粒子数只改变运行时间，不用来假定单进程
瞬时资源占用。资源允许的并发数决定同时活跃的进程数与同一数值身份的工作通道数；粒子数不构成
单进程资源上限。调度器在每个通道只安排完成其份额所需的批次，并使各通道的总粒子数尽可能相等，
避免没有物理或实测依据的单批粒子数上限及由此造成的额外分波。

完全相同的历史数值身份可直接复用单进程保守峰值并跳过观察。没有历史时，首个正式批次取
`ceil(N/min(N,10))`个粒子；它最多观察45秒但始终继续运行，若提前自然完成也直接保留结果。实测后按CPU
`floor((95%-后台占用)/max(10%,单进程实测))`和内存
`floor((当前可用内存-1 GiB)/单进程安全预算)`的较小值确定最终并发。Windows 设置页虽显示为
“GB”，但本公共合同按其二进制容量语义明确记为`GiB = 1024³ bytes`，避免歧义。首次正式观测与精确历史画像
都记录并使用`max(working set, private committed memory)`的峰值，再以其1.10倍作为单进程预算；旧的
`observed_peak_process_tree_working_set_bytes`仅为调用者兼容而保留，其数值同样已升级为该保守managed峰值。
每次错峰启动前还以仍在运行任务的新峰值重新计算一个进程的准入
余量，故后续内存增长会立即暂停扩容。观测时的可用内存已排除仍在运行的首批，因而内存/CPU计算的是可新增
槽位，调度器会再准确加上该首批；首批仍运行时占用一个槽位，剩余
粒子只分给其余槽位；首批结束后，该通道只补齐到与其余通道相同的总工作量。首批已完成时全部槽位
分配剩余粒子，绝不重跑首批。各进程相隔5秒启动；CPU高只暂停
新启动，不终止进程。即使可用内存不少于1 GiB，若仍不足`1 GiB + 下一worker的保守预算`，也只记录
`available_memory_below_dynamic_admission`并暂缓启动。低于0.5 GiB持续15秒才按“最晚启动优先”终止一个worker、
重新排队并降低并发；被终止批次置于队首，不能被平衡补偿批次插队。每次此类危险处置后，必须连续45秒满足
动态准入才恢复一个并发槽并重启队首工作；至多执行两次“终止—稳定观察—恢复”。若第二次恢复后再次发生持续
危险，调度器终止其余受管worker并以`memory_danger_recovery_attempts_exhausted`失败关闭，绝不无限回退或混同为
普通逐次降并发。

跨运行中断续算由[`batch_continuation.py`](batch_continuation.py)提供统一的不可变协议，有两种互斥策略：
`build_batch_continuation_plan`验证失败/中断父run的manifest、冻结run-config、批区间、合同、母cohort输入和原始输出SHA-256，
再把每个逻辑通道中无洞的已终态粒子前缀物化到新run，并只计划缺失后缀；
`build_whole_unit_replay_plan`则只复用每个独立工作单元的全部manifest绑定终态产物，未完整的单元整体重放。
前者的consumer必须提供本机TRACE语法、可复用终态定义和新run输入投影；后者的consumer只提供独立单元键及
run相对的终态产物清单。两者都不解析项目物理或替代结果物化。该协议与运行中的45秒观测、内存准入/重排互补，
均为全仓库SIMION运行器可接入的公共能力。

成功运行只保留紧凑调度收据，不保留逐秒探测文件。 [`resource_profile.py`](resource_profile.py)发布首个正式
批次的独立峰值并用run manifest及输入收据SHA-256复核；并行聚合峰值不得按进程数拆分。PA/IOB构建及没有独立粒子/可合并结果
合同的SIMION任务保持串行；未知case资源身份每次先运行一个正式case，只有同一完整输入的已观测峰值才可参与
后续case wave。已完成case campaign可以把画像写入manifest覆盖的summary；后续运行只发现这种受完整性保护的
画像，不接受裸日志或未受manifest覆盖的JSON。调度器不会发现、批准或启动campaign，也不会在外层campaign之上创建嵌套并发。

Windows能力依据（2026-08-26查阅）：Microsoft `MEMORYSTATUSEX/GlobalMemoryStatusEx`文档说明
`ullAvailPhys`表示可立即复用的物理内存，用于1 GiB/0.5 GiB门限；.NET `System.Diagnostics.Process`文档支持读取
`WorkingSet64`和`TotalProcessorTime`；Microsoft `taskkill /T`文档支持只终止选中PID及其子进程。采用这些接口
是为了测量真实SIMION进程族，并在持续内存危险时只回收最新批次。

- https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/ns-sysinfoapi-memorystatusex
- https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.process?view=net-10.0
- https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill
