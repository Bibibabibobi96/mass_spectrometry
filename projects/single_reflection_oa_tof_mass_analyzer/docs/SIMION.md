# 单次反射正交加速飞行时间质量分析器：SIMION实施与验证

本文只记录SIMION文本、PA/IOB、GUI和独立验收。当前项目资格、跨求解器结论与开放任务只见
[`PROJECT.md`](PROJECT.md)；2026-07-28以前的完整实施时间线冻结在
[`history/20260728__pre-document-consolidation-simion.md`](history/20260728__pre-document-consolidation-simion.md)。
同事复现参数见[`SIMION_REPRODUCTION_PARAMETERS.md`](SIMION_REPRODUCTION_PARAMETERS.md)。

## 活动入口与资产

- 文本入口：`../simion/workbench/formal/oatof_ideal_grounded.lua/.fly2`
- 交付构建：`../simion/workbench/build_formal_delivery.ps1`
- 参数化几何Candidate门禁：`../simion/workbench/run_parameterized_geometry_smoke.ps1`
- 径向压缩与环数补偿：`../workflows/radial_compaction/run_campaign.py`，合同为
  `../config/radial_compaction_campaign.json`
- 反射器电压场补偿：`../workflows/reflectron_voltage_compensation/run_compensation.py`
- N=100源码构建与跟踪：`../tests/simion/run_n100_source_build_and_track.ps1`
- IOB运行时合同：`../simion/workbench/verify_iob_runtime_contract.ps1`
- 稳定资产身份：`../config/simion_stable_entry.json`
- 重命名前的只读Formal资产：工作区`artifacts/projects/single_reflection_oa_tof_mass_analyzer/archive/`
  `20260801_130003__migration-snapshot__repo__oa-tof/legacy-project-root/formal/simion/`；不改写、
  不追加新run
- vNext活动产物：工作区`artifacts/projects/single_reflection_oa_tof_mass_analyzer/`

当前项目处于`formal`。稳定清单绑定当前Formal SIMION交付包；重命名前和拆层前的Formal包只保留
可追溯身份。Candidate仍必须使用独立、已登记的非Formal IOB/CON模板，不能读取旧Formal或archive资产。
当前Formal是只读发布源：任何SIMION进程均不得以`formal/simion`为工作目录或直接打开其中IOB。
活动入口先逐项验证Formal manifest，再通过`analysis/stage_formal_simion_runtime.py`复制到项目scratch，
只运行该临时副本并在终止时清理；run以runtime receipt冻结实际消费的release与资产SHA。

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

日常加速器网格为`xy=0.25 mm,z=0.05 mm`，`z=0.025 mm`只作轴向收敛参考。当前生成链把
grid1、grid2、entgrid与midgrid统一声明为SIMION官方理想透明栅：**零grid-unit厚度的一行电极点**；
目标语义是参与Refine的Dirichlet边界且由SIMION原生穿过，Program不得用固定距离搬运粒子或补偿TOF。
Candidate SIMION门禁通过`run_parameterized_geometry_smoke.ps1`隔离构建正式加速器与反射器PA，使用官方
`simion.pas`/`pa:point()` API写出四栅raw-PA单行receipt，并要求冻结单粒子原生穿越计数为
`grid1/grid2/entgrid/midgrid=1/1/2/2`后命中探测器；TRACE方向判定只服务该冻结正向发射单粒子smoke，
不是通用轨迹事件定位器。该门禁直接读取正式numerics合同，固定加速器`0.25/0.25/0.05 mm`与反射器
`0.25/1.0 mm`网格，不提供粗网格fallback，并保存gem2pa、raw审计、refine、fast-adjust、反射器构建和
单粒子Fly的墙钟耗时receipt。真实丝网属于独立物理候选，须建立单独几何/profile并重新验证传输、场和收敛，
不能复用一行理想栅路径。

Candidate run `20260813_160656__gate__simion__native-ideal-grid__smoke`已真实PASS：四栅raw row依次为
`260/596/0/480`且各仅一行，单粒子原生穿越计数为`1/1/2/2`并命中探测器。加速器builder墙钟
`168.329 s`（其中Refine `164 s`），反射器builder `32.170 s`（Refine `32 s`），组合raw-PA receipt
`3.908 s`，单粒子Fly `0.472 s`。这是隔离的Candidate功能验收，不晋升或改写当前Formal包，也不证明
真实丝网、网格收敛、N=100/1000传输或分辨率资格。

反射器为二维轴对称PA；网格只查`../config/formal_solver_numerics.json`，制造约束只查
`../config/design_variables.json`。包含理想栅的加速器和反射器PA均使用SIMION官方ideal-grid示例采用的
PA级`surface=none`语义；四个零宽栅必须严格落在raw节点，普通厚环、背板和屏蔽罩边缘不对齐时记录
`reflectron_geometry_edge_not_on_grid_node`警告并按raw网格离散。`surface`是PA级选项，本项目不伪造
按电极混合surface元数据。

官方依据（查阅`2026-08-13`，目标版本SIMION 2020）为SIMION Grid/PA说明
<https://simion.com/info/grid.html>及本机随安装提供的
`examples/geometry/parallel_plate_capacitor_2d.gem`：官方示例以节点对齐的一行零宽电极和PA级
`surface=none`表达100%透明理想栅。本项目采用该路径；一行栅必须落在raw PA节点，真实丝网不在其适用域。

## Candidate与交付纪律

Candidate文本由`workflows/design_candidate/prepare_candidate_consumers.py`生成；PA、IOB、Fly和run
生命周期必须由上层Candidate workflow冻结。非Formal模板只允许通过
`../simion/workbench/register_candidate_layout_template.ps1`登记的四槽IOB/CON；placeholder PA仅用于
GUI布局，必须在Fly前被真实Candidate PA替换。

`build_formal_delivery.ps1`只输出到run；晋升为独立事务。交付必须包含同basename Program/Fly2、四套
完整PA家族、固定ION、manifest和SHA清单。移动或重建后必须重新加载IOB并验证四实例、优先级、
trajectory quality和资产哈希。

电压补偿入口从固定PA导出fast-adjust基函数，在入口/中间栅/背板电压固定且环电压单调的条件下，
最小化实际轴向电势与理论分段线性电势的偏差。无派生profile或功能关闭时使用原线性分压；开启时
SIMION校验环数、范围和单调性后应用profile。同一PA以5×200并行分别计算原场、补偿场和理想反射场，
合并N=1000后用direct-KDE验收。固定PA的静电响应线性，一次受约束求解即可；几何变化才重新导出基函数。

## GUI验收

GUI必须可见并可编辑四实例、Fast Adjust电压、实例坐标、Fly2粒子和同名Program。Data Recording至少
记录Ion Number、TOF、X/Y/Z和Event；单一TOF列不能证明来自正确终止面。命令行只可改变线程、无GUI和
输出路径，不能覆盖GUI不可见物理参数。

## 当前限制

- `.wgem`受许可证限制时使用已验收的SIMION 2020 legacy-GEM模板；许可证升级并完成隔离GUI/结构复验
  前不迁移生产路线。
- 真实丝网局部单元尚未实现；理想栅网和真实丝网结果不得混为同一baseline。
- SIMION 2020在真实分数表面反射器连续Refine至约`pa18`时可非确定性以`0xC0000005`退出；这不是
  二维PA尺寸或固定电极数硬上限。生产构建先初始化全部解数组，再让每个`paN`在独立SIMION进程中
  Refine，最后fast-adjust；恢复已有半成品时也必须逐个重新Refine，不能只凭文件存在判断收敛。
- 已关闭的PA网格相位、跳转距离、Ez替换、宽质量timeout及性能缩放实验只从同日history快照与来源
  manifest追溯，不保留在current实施说明。
