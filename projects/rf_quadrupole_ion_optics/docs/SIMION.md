# RF四极杆离子光学：SIMION实施与验证

本文只说明SIMION几何、Program、运行入口与独立验收。跨求解器状态和开放任务只见
[`PROJECT.md`](PROJECT.md)；2026-07-28以前的完整run、数值和故障链冻结在
[`history/20260728__pre-document-consolidation-simion.md`](history/20260728__pre-document-consolidation-simion.md)。
多极杆各轴向实体、事件面和`numerical_census_marker`只采用
[`../../../common/multipole/README.md`](../../../common/multipole/README.md)的统一术语。

## 几何与运行时权威

活动GEM由`../analysis/sync_simion_geometry.py`从具名profile编译的resolved发布生成，并嵌入发布
SHA-256；生成GEM不得手改。Workbench运行使用项目生成的单PA、Fly2和
`../simion/programs/quad_transport.lua`。共享模板、GUI复核、`.wgem`绕行和跨工作区可移植性状态
只由[`../../../common/multipole/README.md`](../../../common/multipole/README.md)登记。

Lua只实现RF-only或RF+DC Fast Adjust、静态电极、时间步上限、最长飞行、事件/轨迹和summary，不含
collision、drag、pressure或buffer-gas逻辑。物理量来自冻结resolved，数值量来自
`../config/simion_solver_numerics.json`的默认/资格基线，且实际采用的正数步数与trajectory quality会冻结
进run config与Lua。入口可用于探索性数值取值；非基线取值只标记为未资格的探索结果，不得冒充既有
baseline或资格证据。Program不得以未记录的默认值或命令行覆盖物理权威输入。

## 活动入口

| 科学问题 | 入口 |
|---|---|
| 接口就绪输运 | `../workflows/interface_readiness/run_simion.ps1` |
| 无碰撞部件回归 | `../workflows/no_collision_transport/run_simion.ps1` |
| RF+DC质量过滤 | `../workflows/mass_filter_reference/run_simion.ps1` |
| PA场分辨率诊断 | `../tests/simion/test_pa_field_convergence.ps1` |
| IOB结构检查 | `../simion/workbench/inspect_builtin_quad_reference.lua` |

接口入口只接受配对bundle中的canonical表示；质量过滤入口只接受显式基础ION11并生成逐质量配对表。
无碰撞入口的具名runtime profile可选择圆柱家族三种typed电气模式，但不接受自由design/source路径，
也不得选择矩形`official_transport` integration oracle。

接口就绪与质量过滤入口向公共 SIMION 调度器提交粒子总数和冻结数值身份；资源识别、并发与回收
由[公共实现](../../../common/simion/README.md)维护，项目不保存第二套调度参数。

## 输出与来源纪律

新运行输出canonical粒子事件表、稀疏轨迹、summary及run manifest。源事件、杆端、出口孔穿越、
规范交接、近接口统计和terminal事件均保持粒子ID、三维位置/速度、能量、RF相位和终止原因。
terminal只表示数值标记、撞壁、超时等终态分类，不是近接口统计面的别名。接口运行必须逐ID证明canonical与ION11
两种表示等价；质量过滤响应稳定文件名为`mass-response__simion.csv`。

IOB加载门禁必须检查：

- 单一项目PA实例及本地路径；
- 放置变换、尺寸、cell size和PA checksum；
- Program/Fly2与冻结run config一致；
- GUI中Program、Adjustables、粒子定义和PA实例可检查；
- 运行和分析失败按三件套失败关闭，不以文件存在判成功。

## 数值与资格边界

已完成的敏感性、资源终态及接口比较只以 [PROJECT](PROJECT.md) 和其资格合同为准。
旧数值表与已退役接口叙述保存在
[历史记录](history/20260911__solver-sensitivity-and-retired-interface.md)，不构成活动运行授权。

RF 多极杆到 oa-TOF 的连接由 integration 拥有；项目只提供端口与 canonical handoff。
公开入口由[项目 README](../README.md#工作流入口)导航，不再使用本项目旧 pulse_capture 链。

长 PA 输入和缓存隔离遵循[公共 SIMION 参考](../../../docs/SIMION_REFERENCE.md#长pa输入路径)。
