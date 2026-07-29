# 单次反射正交加速飞行时间质量分析器：SIMION实施与验证

本文只记录SIMION文本、PA/IOB、GUI和独立验收。当前项目资格、跨求解器结论与开放任务只见
[`PROJECT.md`](PROJECT.md)；2026-07-28以前的完整实施时间线冻结在
[`history/20260728__pre-document-consolidation-simion.md`](history/20260728__pre-document-consolidation-simion.md)。
同事复现参数见[`SIMION_REPRODUCTION_PARAMETERS.md`](SIMION_REPRODUCTION_PARAMETERS.md)。

## 活动入口与资产

- 文本入口：`../simion/workbench/formal/oatof_ideal_grounded.lua/.fly2`
- 交付构建：`../simion/workbench/build_formal_delivery.ps1`
- 参数化几何Candidate门禁：`../simion/workbench/run_parameterized_geometry_smoke.ps1`
- N=100源码构建与跟踪：`../tests/simion/run_n100_source_build_and_track.ps1`
- IOB运行时合同：`../simion/workbench/verify_iob_runtime_contract.ps1`
- 稳定资产身份：`../config/simion_stable_entry.json`
- 重命名前的只读Formal资产：工作区`artifacts/projects/oa_tof/formal/simion/`；不搬移、不改写、
  不追加新run
- vNext活动产物：工作区`artifacts/projects/single_reflection_oa_tof_mass_analyzer/`

当前项目处于`formal`。稳定清单绑定当前Formal SIMION交付包；重命名前和拆层前的Formal包只保留
可追溯身份。Candidate仍必须使用独立、已登记的非Formal IOB/CON模板，不能读取旧Formal或archive资产。

## 几何与数值合同

正式/候选文本由resolved生成；物理参数只来自`../config/baseline.json`与resolved，数值只来自
`../config/formal_solver_numerics.json`。四个GUI可见实例和优先级必须为：

1. flight tube；
2. reflectron；
3. accelerator；
4. detector。

Program不通过动态实例调整补救错误排序。正式trajectory quality为8；Program与Data Recording必须
同时开启。检测器PA只表示全局`z=0`、半径40 mm的GUI可见数值终止面，其吸收层厚度不是机械厚度。
本项目文档中的“SIMION detector marker”统一译为**数值终止标记**：它帮助GUI显示并产生终止事件，
不是机械探测器实体；有效探测面、数值标记和terminal事件三者不得互称。

日常加速器网格为`xy=0.25 mm,z=0.05 mm`，`z=0.025 mm`只作轴向收敛参考。透明栅网数值跨越距离
为`0.0001 mm`；除PROJECT所列重启条件外不继续扫描以追平单一指标。

## Candidate与交付纪律

Candidate文本由`workflows/design_candidate/prepare_candidate_consumers.py`生成；PA、IOB、Fly和run
生命周期必须由上层Candidate workflow冻结。非Formal模板只允许通过
`../simion/workbench/register_candidate_layout_template.ps1`登记的四槽IOB/CON；placeholder PA仅用于
GUI布局，必须在Fly前被真实Candidate PA替换。

`build_formal_delivery.ps1`只输出到run；晋升为独立事务。交付必须包含同basename Program/Fly2、四套
完整PA家族、固定ION、manifest和SHA清单。移动或重建后必须重新加载IOB并验证四实例、优先级、
trajectory quality和资产哈希。

## GUI验收

GUI必须可见并可编辑四实例、Fast Adjust电压、实例坐标、Fly2粒子和同名Program。Data Recording至少
记录Ion Number、TOF、X/Y/Z和Event；单一TOF列不能证明来自正确终止面。命令行只可改变线程、无GUI和
输出路径，不能覆盖GUI不可见物理参数。

## 当前限制

- `.wgem`受许可证限制时使用已验收的SIMION 2020 legacy-GEM模板；许可证升级并完成隔离GUI/结构复验
  前不迁移生产路线。
- 真实丝网局部单元尚未实现；理想栅网和真实丝网结果不得混为同一baseline。
- 已关闭的PA网格相位、跳转距离、Ez替换、宽质量timeout及性能缩放实验只从同日history快照与来源
  manifest追溯，不保留在current实施说明。
