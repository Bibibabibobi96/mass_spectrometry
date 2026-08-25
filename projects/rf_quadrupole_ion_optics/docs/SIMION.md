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

无加速N=100基线和全局cell `0.4→0.3 mm`空间敏感性档已在全部四段杆施加RF并按81.1 mm近接口
统计面计数；两档均为RF-on 100/100、zero-RF 21/100，RMS半径相对变化约`9.57%`。v3当前只授权
固定`0.3 mm`、`40→80`步/周期的时间敏感性档也已完成，RMS半径相对变化约`0.034%`。空间/时间
功能PASS不构成连续数值收敛；分段杆轴向加速baseline和N=100空间档均已完成，当前仅授权
出口孔板加速N=100 baseline和空间档均已完成，当前商业求解器授权已关闭。旧分段杆、
出口带孔接口板和显式多级证据只属历史，不代表当前PA收敛、与COMSOL数值等价或机械资格。接口
N=100双端100/100但相空间严格比较为FAIL。

RF四极杆离子光学→单次反射oa-TOF下游由本项目累积pulse_capture入口驱动，以COMSOL真实局部出口canonical
状态进入只读分析器；
SIMION未独立建立同等侧孔/连接器场。功能贯通不得解释为接口场或整机Formal闭合。

许可证不能处理SIMION 2026 `.wgem`时继续使用已验证的SIMION 2020 legacy-GEM路线；该公共开放项
不在项目软件文档重复维护。
