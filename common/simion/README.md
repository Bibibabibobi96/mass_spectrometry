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

[`resource_scheduler.py`](resource_scheduler.py)是独立粒子SIMION任务的唯一并发决策实现。项目runner只提交已
授权的工作负载、执行返回的batch plan，并负责本项目的输入格式转换和结果合并；不得自行选择固定批数或
并发数。请求必须明确RF（含steps/period）或静电模式和粒子数。每批CPU、并发上限和内存保留只有在具有
实测或运行环境依据时才声明；省略时调度器使用每批一核、零额外CPU保留，并由当前主机容量决定并发。运行时
必须以当前CPU与可用内存重新规划；准备阶段的计划只冻结资源身份、已声明上限和已测峰值证据。它只依据相同资源身份
的已完成峰值选择最大安全并发；无历史数据时只生成一个bootstrap波次，后续必须以观测峰值重新计划。
[`resource_profile.py`](resource_profile.py)只发布成功、单进程bootstrap run的峰值，并在使用前用run manifest
及输入收据的SHA-256复核；并行波次的聚合峰值不得拆分成单批画像。PA/IOB构建及没有独立粒子/可合并结果
合同的SIMION任务保持串行；调度器不会发现、批准或启动campaign，也不会在外层campaign之上创建嵌套并发。
