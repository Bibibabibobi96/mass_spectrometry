# MR-TOF Candidate SIMION 路径

本页说明活动 SIMION 实现与操作边界；当前资格、有效证据和开放任务以
[项目状态](../docs/PROJECT.md)为准。当前 N=1 自然互易路径不授予束团或分辨率资格；旧 PA/IOB 不因源码修复自动恢复有效性。

## 输入、坐标与几何

[候选合同](../config/simion_candidate_two_zone.json)提供物理输入和机械约束，
[resolved_geometry.py](../analysis/resolved_geometry.py)生成求解器无关的毫米几何，
[split_candidate_geometry.py](../analysis/split_candidate_geometry.py)分别适配三份 GEM。
项目坐标固定为：`z`是快速反射方向、`y`是慢漂移方向、`x`是横向聚焦方向；
`z=0`是中央注入／第一时间焦点交接面，不是最终质量焦点或必然的空间束腰。

GEM、PA、IOB和Workbench GUI只读地接受冻结输入，不持有下一轮可调几何真值。
`geometry_receipt`记录resolved几何哈希、坐标、单位、电极ID和孔槽；各组件必须来自同一合同。
五电极镜保留30-mm束槽、有限长槽及内侧开槽／外侧闭合盖板。四块Stripe对应两套电压组：
`(11,12) -> v1`、`(13,14) -> v2`；曲线由合同中的B-spline参数生成。
Stripe、中央接地件及棱镜屏蔽由完整实体扣除有限矩形槽，端部连接材料自然保留，不能另加任意桥接盒。
`grounded-1`为单一`e(18)`、`grounded 2`为单一`e(20)`；旧人工拆分ID19/21已退役。

加速器局部理论与可复用几何来自独立`orthogonal_accelerator`项目，依赖通过
[accelerator_dependency.json](../config/accelerator_dependency.json)声明并随输入冻结。
MR只负责本项目尺寸、电压、装配变换及整机接口。离子从exit grid沿项目`-z`离开；
exit、grid1、repeller依次位于更大的`+z`。`y`由出口棱镜站位派生，不能强制为零。
第一焦距和各电极位置必须使用现行公式重新生成，不能复用旧焦距对应的PA原点。

## 三个独立 PA

活动网格的机器权威是候选合同的`simion.component_mesh_mm_per_gu`；以下数值只是当前合同摘要，
顺序均为项目`x,y,z`，构建与检查入口必须传递实际冻结值，不能从此表手填另一套参数。
旧单体`2×0.8×8`网格及旧单体构建命令不是活动首轮流程。

|组件|IOB加载文件|当前网格 mm/gu|Fast Adjust／求解范围|
|---|---|---|---|
|五镜双组、四Stripe、中央接地、两棱镜及屏蔽|`mrtof_analyzer.pa0`|`1,1,1`|`pa1..pa20`|
|独立屏蔽二区加速器|`mrtof_accelerator.pa0`|`0.25,0.25,0.1`|局部`pa1..pa9`|
|独立数值终止平板|`mrtof_detector.pa#`|`1,1,1`|无Refine、无PA0、无basis|

分析器basis使用从1到最大ID20的完整命名空间；未使用ID19的零响应数组不是新增物理电极。
SIMION 2020会拒绝对不存在的ID执行Refine。构建器先扫描原始ID；对范围内的编号空缺以官方
`pa:potential` setter生成严格全零响应、保留材料掩码并保存为对应PA文件，存在的ID仍按默认Refine求解。
禁止请求高于物理最大ID的数组，不能为补齐编号增加虚构实体。
主分析器为`x/y/z=1/1/1 mm/gu`：CAD固定的30-mm镜束槽（边界`x=±15 mm`）与4-mm Stripe／接地／棱镜屏蔽槽（边界`x=±2 mm`）在同一个2-mm网格相位中不可同时精确表示，故`x=1 mm`是几何审查的硬约束；`z=1 mm`也使CAD给定的2-mm grounded-1—镜盖板净距包含真空节点。几何包络与孔槽不变。独立加速器当前为`0.25/0.25/0.1 mm/gu`，其中项目`z`是加速方向；该网格解析1-mm环／栅框厚度，但焦点、边缘场、时间与分辨率结论仍须至少三档网格收敛。
GEM直接编译的默认网格也由同一component mesh合同生成，不能留存旧`y=2`默认值。
生成PA时检查的物理ID则由geometry receipt给出，不能把不存在的物理电极当作必需实体。
加速器使用独立的局部ID：
`ground/repeller/grid1/exit/rings = 1/2/3/4/5..9`，映射自项目ID
`15/22/23/24/26..30`。不得在独立加速器PA中查找`pa22..pa24`。

加速器的repeller及五个第二区加速环是合同派生的开框，当前外形为`x=40 mm、y=36 mm`、束孔25×25 mm；接地壳为`x=48 mm、y=44 mm`。其`y`尺寸从冻结的加速器出口棱镜中心线和CAD grounded-2的上边界共同派生，并由正净距合同拒绝任何再次相交；
grid1与exit是节点对齐的理想栅。五环位置与电压由区长、环数及端点电压派生。
它单独Refine，不和镜／Stripe／棱镜共用大PA。

探测器GEM先用稳定ID25建立物质掩码；[build_component_pa.lua](build_component_pa.lua)在
`INITIALIZE=0`时以`pa:potential(x,y,z,0)`把所有节点电势置零、保留电极标志并保存原始PA。
因此原始ID值不会被当成25 V，且没有静电求解数组。它不是已验证的物理探测器；
原生终止与事件面的一致性必须随每次飞行检查；当前 N=1 证据见项目状态。

## 构建与重新加载检查

先用[materialize_simion_prototype.py](../analysis/materialize_simion_prototype.py)冻结候选合同、
解析L0/L1镜电压receipt、提供者依赖、Program、operating-point sidecar和五份Fly2。
此步骤不会改变baseline，也不会启动商业求解器。三份GEM分别由同一入口的
`--component analyzer|accelerator|detector`生成；不再用单体GEM驱动活动装配。

[build_component_pa.lua](build_component_pa.lua)接收GEM、PA#、三个网格长度、实际物理ID清单和显式
`INITIALIZE`。分析器及加速器使用`1`生成PA0，探测器使用`0`；
[build_component_basis.lua](build_component_basis.lua)随后为前两者生成完整basis。
所有Refine均使用SIMION官方默认收敛设置，不传入convergence覆盖值。

分析器与加速器各自是独立的PA-family缓存消费者：在Refine前，以冻结的resolved geometry、组件GEM、
局部ID namespace、mesh、PA相位、`surface=none`、SIMION可执行身份、默认Refine策略及两份构建Lua的哈希
向[`common/simion/pa_family_cache.py`](../../../common/simion/pa_family_cache.py)查询。完整命中时只将已验证的
`.pa#/.pa0/basis`物化到本run；任何身份变化、清单缺失或损坏都必须miss并重新Refine。探测器是未Refine的零电压
终止掩码，不进入field-basis缓存。IOB绝不复用：每次都从本run PA重新加载、Fast Adjust、保存和重载检查。

缓存的项目适配入口是
[`simion_pa_family_cache.py`](../analysis/simion_pa_family_cache.py)，而不是另一份PA构建器。它只派生
本项目的组件ID、PA文件名和project-frame网格相位；内容寻址、逐字节验证和原子物化均由公共层执行。
每个新run先在已生成本run GEM之后运行`probe`。只有`hit`才运行`materialize`到已有的run-local
`simion/`目录（允许GEM/Lua/Fly2等无关冻结sidecar，拒绝覆盖任何同名PA）；`miss`才调用SIMION生成
PA#/PA0/basis，完成后对同一冻结输入运行`publish`。因此旧PA或旧缓存不会因文件名相同被误用。
发布还要求PA family旁的规范名`mrtof_<component>.gem`与请求GEM逐字节相同；诊断性别名（例如
`*_closed`）不能被混进规范family。该检查器本身的哈希也进入cache key，较早、未执行此绑定的 generation
不会被后续代码静默复用。

```powershell
$cache = 'C:\Users\Liao\mass_spectrometry\artifacts\common\simion\pa_family_cache'
$runSimion = 'C:\...\artifacts\projects\parallel_mirror_dual_stripe_mr_tof\runs\<run-id>\simion'
python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_pa_family_cache `
  --action probe --cache-root $cache --contract "$runSimion\simion_prototype_contract.json" `
  --component accelerator --gem "$runSimion\mrtof_accelerator.gem" `
  --simion-executable 'C:\Program Files\SIMION-2020\simion.exe' --simion-release 'SIMION 2020' `
  --run-simion-directory $runSimion
```

替换`--action materialize`或`publish`执行相应的命中物化或Refine后发布。缓存身份绑定实际GEM、resolved几何、
网格、原点/相位、完整basis命名空间、两份构建Lua、SIMION可执行文件字节及官方默认Refine策略；任一项变化都
必须miss。当前旧几何审查PA与现行resolved几何receipt不一致时，`probe`的`miss`是预期的安全结果，不是可绕过的错误。

[build_three_component_iob.lua](build_three_component_iob.lua)加载公共
`common/simion/assets/iob_instance_seeds/3_instance_seed.iob`及其十个
`iob_seed_placeholder_*.pa0` companion arrays，再装入表中三个PA。
它通过`wb:load()`／`wb:save()`保存IOB；三组平移只能由
`resolve_split_iob_origins()`从本次合同派生。保存IOB后，构建器复制同名的Lua、Fly2、
operating-point与voltage-map companion；这使包可由唯一飞行入口加载，但保存成功本身
仍不能作为任何粒子飞行或物理闭合结论。

对已在同一冻结几何身份下构建的三份PA，可用
[run_three_component_candidate.ps1](run_three_component_candidate.ps1)建立可审计的**无飞行**装配包。
该入口冻结候选合同、镜L0/L1 receipt、两份**精确生成GEM**、两份已解PA0及其原始PA#、零电压探测器PA#和完整十一文件
IOB seed bundle；它在host execution lease内装配并重载检查IOB。它不构建或发布PA-family缓存，
也不调用`Fly`，因而只可发布`prototype_geometry_review_only`证据。任何中心粒子或N=100飞行必须由
后续专用运行器从这个已检查的run-local包开始，重新绑定实际Fly2、原始日志和事件分析receipt；不得
以此入口的success manifest声称传输、K=25或分辨率。

在复制大型PA前，该入口通过`common/contracts/run_artifact_support.ps1`的
`Invoke-ArtifactCapacityGate`以实际待复制的冻结输入字节数预留容量，并保护新run；终态再以启动测量和
实际run目录大小复核同一水位。两份JSON receipt随run冻结。清理优先级、可删范围和缓存键保护仍只由
`common/contracts/reconcile_artifact_capacity.py`定义；本入口不定义第二套项目级删除规则。

电压映射只由[candidate_voltage_map.lua](candidate_voltage_map.lua)提供：materializer将其冻结为
`mrtof_candidate.voltage_map.lua`。飞行回调和IOB构建器共用此函数，构建器按operating-point
sidecar对两张PA0执行`fast_adjust → save`，再保存IOB，使几何审查不必先飞行才能施加电压。
IOB同名的Program、operating-point与voltage-map三份Lua伴随文件必须一起保留。
纯Lua回归已验证映射、调用顺序和伴随文件。重载检查器读取原始PA#的物理ID，为全部19个分析器和
9个加速器电极各检查一个真实材料节点的已存PA0电势；过程中禁止重新Fast Adjust，以免掩盖保存错误。
探测器检查所有节点严格零电势且存在材料，三个实例还须无旋转、scale=1。真实运行结果以本次报告为准。

重新加载检查是必需步骤。[inspect_three_component_iob.lua](inspect_three_component_iob.lua)
的参数签名如下；A/B/C依次是分析器、加速器和探测器：

```text
IOB REPORT AX AY AZ BX BY BZ CX CY CZ ADX ADY ADZ BDX BDY BDZ CDX CDY CDZ
```

必须提供合同派生的9个原点坐标和`component_mesh_mm_per_gu`中的9个网格长度；
不能只给原点或依赖检查器内部默认网格。负坐标前保留SIMION命令行所需的`--`分隔符。
检查器核对三个PA basename、三维原点、实际网格并记录数组尺寸，输出
`iob_structure_report.txt`，其中应有`STATUS=PASS`、`PHYSICAL_MODEL=false`和
`PARTICLE_FLY_EXECUTED=false`，另要求`POSE_RELOAD=PASS`和`VOLTAGE_RELOAD=PASS`。
逐电极抽查不表示所有场节点已验证；实例列表顺序也不等于已验证重叠区实际选择，后者仍需最小飞行。

[three_component_simion_run_manifest.py](../analysis/three_component_simion_run_manifest.py)要求
`--contract --run --iob --structure-report --output`，绑定geometry receipt、两份PA0及其完整basis、
原始零电压探测器PA#、IOB、三份同名Lua伴随文件和结构报告；报告必须是明确的无飞行PASS。
它发布的是`prototype_geometry_review_only`，不授予飞行、传输或分辨率资格。
该receipt的`record_artifact`采用同目录局部文件名，故活动输出必须写入 IOB 所在的run-local `simion/`
目录；写到`results/`的副本不能作为后续飞行receipt的工作台身份根。

实际飞行完成且`simion_event_analysis.py`已对完整固定粒子集合返回完整性PASS后，
[three_component_simion_flight_manifest.py](../analysis/three_component_simion_flight_manifest.py)才可把这份
无飞行几何审查、冻结source manifest/source key、原生SIMION日志和事件分析receipt绑定为一份
`candidate_prototype_flight_receipt`。该写入器逐字节检查IOB及三份伴随Lua、结构报告的
`STATUS=PASS`／`PHYSICAL_MODEL=false`／`PARTICLE_FLY_EXECUTED=false`，并拒绝无效事件或任何来源漂移。
它不复制、推断或发布TOF、传输、K=25比例或分辨率；这些数值仅保留在事件分析receipt中。

## 粒子来源与事件分析

materializer在schema3的`prototype_input_manifest.json`中为每份具名诊断Fly2分别冻结
`source_profile_id`、`particle_count`、`particle_count_contract_key`、`expected_particle_ids`及其SHA-256，
并绑定Fly2和derived合同的SHA-256。ID由单个standard beam的合同粒子数派生为`1..N`；
分析不能从已记录终态数反推母粒子数。

|manifest source key|生成的Fly2|当前用途|
|---|---|---|
|`mirror_internal_diagnostic_center_fly2`|`mrtof_mirror_internal_diagnostic_center.fly2`|分析器内直接释放的4-keV单粒子；只隔离诊断mirror/Stripe|
|`mirror_internal_diagnostic_bunch_fly2`|`mrtof_mirror_internal_diagnostic.fly2`|同一镜内诊断态的固定合同小束团；不是整机源|
|`accelerator_focus_center_fly2`|`mrtof_accelerator_focus_center.fly2`|第一区release平面的零KE中心粒子|
|`accelerator_focus_bunch_fly2`|`mrtof_accelerator_focus.fly2`|第一区内零KE轴向释放位置表；用于检验第一时间焦点|
|`first_prism_entry_center_fly2`|`mrtof_first_prism_entry_center.fly2`|两区焦面处的4-keV中心粒子；仅首棱镜有限三维射击诊断|
|`full_mrtof_center_fly2`|由已审计P1/P2工作点按run局部生成|完整源→P1→负镜预反射→P2→Stripe中心轨迹；当前仅允许N=1事件链诊断，不授予K=25或性能资格|

当前首轮物种为524 Th／+1，中心源N=1、小束团N=100。全分析器小束团半径为0.1 mm；
加速器焦点束团则把合同的`accelerator_focus_axial_full_width_mm=0.2 mm`均匀离散成100个
确定的第一区轴向释放位置，每个位置各用一个`n=1` standard beam，避免SIMION随机圆盘分布掩盖轴向导数。
这些数值只来自`particle_source`合同。
此前100 Th输入仍属独立回归/历史证据，不与新首轮束团混合统计。
镜内两种源绕过加速器和P1/P2，仅保留为部件隔离诊断，不能用于整机传输、探测TOF或分辨率。
加速器焦点两种源是静态电压下
从第一区由静止释放的独立诊断；轴向N=100源可测量有限宽度的一阶斜率、二阶曲率和时间极差，
但不代表真实脉冲源分布。
所有具名源不能合并统计或彼此替代；schema2旧名称仅供既有run只读分析。

有实际飞行日志后，从仓库根使用[simion_event_analysis.py](../analysis/simion_event_analysis.py)：

```powershell
python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis `
  '<run>/stdout.log' '<run>/event_analysis.json' `
  --input-manifest '<run>/simion/prototype_input_manifest.json' `
  --source-key mirror_internal_diagnostic_bunch_fly2
```

路径应指向本次实际冻结文件；`--source-key`必须与实际飞行源相符。目标K只从已校验的derived合同读取，
不再接受独立`--target-k`默认值。源文件／合同身份改变、无唯一Fly完成记录、完成计数不符、
缺失／重复／未知粒子ID或截断事件都会拒绝PASS。保留原始诊断计数与到达时间，完整性失败时
检测率、目标K比例、FWHM和分辨率为`null`，CLI返回`FAIL/1`；只有完整性通过才返回`PASS/0`。
旧schema日志只能只读诊断，不能通过补造新source manifest恢复当前运行资格。

## 飞行与求根入口

所有入口从已审计 run 消费冻结合同、源与 PA 身份；参数说明直接查看对应脚本的 `param` 定义。
以下入口具有不同资格，不能互相替代。

| 任务 | 受管入口 | 结果范围 |
|---|---|---|
| N=1 完整中心事件链 | [run_three_component_center_flight.ps1](run_three_component_center_flight.ps1) | 单中心原型事件诊断 |
| P1/P2 或 S1/S2/P1/P2 有限场试点 | [run_two_prism_trial.ps1](run_two_prism_trial.ps1) | 四残差与真实回程观测 |
| 新中心八条对称扰动及审计 | [run_downstream_central_difference_campaign.ps1](run_downstream_central_difference_campaign.ps1) | 同一冻结问题的局部 Jacobian |
| 只读中央差分审计 | [run_downstream_central_difference.ps1](../analysis/run_downstream_central_difference.ps1) | 定义性与导数诊断，不选择步长 |
| 实际步进下降审计 | [run_downstream_bounded_step.ps1](../analysis/run_downstream_bounded_step.ps1) | 对照真实与预测下降，不授予工作点 |
| 首棱镜隔离诊断 | [run_three_component_first_prism_flight.ps1](run_three_component_first_prism_flight.ps1) | 首棱镜接口 |
| 静态第一时间焦点 | [run_accelerator_focus_flight.ps1](run_accelerator_focus_flight.ps1) | 独立加速器焦点，不是束团出口时钟 |

中央差分 campaign 从中心 run 继承四电压及上游 run、局域工作台、trajectory profile 和脉冲模式；
调用者显式提供四个正对称步长和新 run 身份。它在八次飞行及审计全过程持有公共 host-execution lease。
每条 manifest 逐文件绑定几何/镜/Stripe/加速器/工作台、组件 PA、源、IOB builder/seed、Program/helper、
电压映射和飞行/合成实现；`solver_problem_identity` 按 bytes+SHA-256 比较。仅四电压与派生 operating PA 可变。

有界 proposal 由已验证 Jacobian 和显式 alpha 自动派生，不手工誊写四电压。proposal、真实试飞与下降审计是
三个独立步骤；迭代是否已完成只在[PROJECT](../docs/PROJECT.md)维护，不在本页累加试点时间线。

## 事件与脉冲合同

[mrtof_candidate.lua](mrtof_candidate.lua)与[mirror_cycle_counter.lua](mirror_cycle_counter.lua)按 P2 后同侧正镜
转折定义完整快周期；中央 `z=0` 穿越只作诊断。只有同侧转折同时回到 `y=0,v_y<0` 才是严格相位返回；
两个相位样本间穿越 `y=0` 只报告连续圈数。实际坐标返回后自然传播，不在目标 K 截停。
P1/P2 始终保持注入态，trial runner 对棱镜提取态及切换时刻参数失败关闭。

加速器有 `static`、仅 N=1 的 `initial_exit_triggered_single_center` 和 `fixed_global_time` 三种互斥模式。
固定时钟必须通过 `-AcceleratorPulseSchedulePath` 消费冻结收据，在共同 `tob=0` 的 `ion_time_of_flight`
上切换 ID 1--9；`tstep_adjust` 落到计划边界，事件记录实际与计划时刻。禁止用裸时间参数替代身份收据。
[run_freeze_accelerator_pulse_schedule.ps1](../analysis/run_freeze_accelerator_pulse_schedule.ps1)目前仅能冻结
成功 N=1 首出口为 `single_center_diagnostic__not_a_bunch_schedule`。它不提供完整束团的最后安全出口与 guard。

`sim_segment_global=1`用于覆盖 PA 外终态；仍须逐粒子对账、唯一成功终止和原始日志完整性。
[run_iob_flight.lua](run_iob_flight.lua)要求 IOB 同名 Program、Fly2、operating-point、voltage-map 和
mirror-cycle-counter 伴随文件；实际源必须与冻结 Fly2 字节一致。旧不完整日志不能补造资格。

## 数值执行边界

积分设置只由候选合同的 `trajectory_profiles` 派生；入口选择 ID，不接受游离时间步。
`center_screening` 用于中心筛查，更细 profile 用于同一物理点的步长敏感性，不能替代 PA 网格收敛。
静态飞行读取已保存 PA0，默认 `runtime_fast_adjust_enable=0`；电压化在飞行前完成，不能在每个积分段重算完整 basis。

[analyzer_local_refinement_plan.py](../analysis/analyzer_local_refinement_plan.py)及
[analyzer_local_patch_geometry.py](../analysis/analyzer_local_patch_geometry.py)从同一 resolved 几何派生局域计划与 GEM。
全局 1-mm 分析器作为远场回退，五个 0.5-mm 局域替代按合同重叠责任区接管；独立加速器和探测器保持各自 PA。
局域场替换全局场，不是两个零边界场相加。每区保留镜 B--E、S1/S2、P1/P2 八组响应与实测 basis 归一化，
六面边界从同源全局响应插值。正负局域场分别构建，不能因机械镜对称复用受离轴棱镜影响的场。

[run_analyzer_local_pa_family.ps1](run_analyzer_local_pa_family.ps1)调用公共缓存与 Dirichlet 原语。
每个原生 `.paN` 响应只在一次性 build staging 内产生；发布前由公共 exporter 写成真正 standalone 的
`.responseN.pa`，并与原生 family 一起进入同一 cache manifest。工作台和飞行器只读取这些 standalone
响应，不重新打开 cache 中的 `.paN`。
`instance_adjust` 只在合同从重叠区导出的半开责任区内接管；portal 真空穿越、非 portal 不穿越、电势/法向场、
事件拓扑和固定粒子轨迹必须分别验证。当前中心接口证据不能替代束团包络或第三档网格，每档须重新求中心根。

[analyzer_local_z_compression_plan.py](../analysis/analyzer_local_z_compression_plan.py)是只读规划器：

```powershell
python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_z_compression_plan `
  --contract projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json `
  --scale-factor 0.5
```

它不调用 SIMION，不修改 PA/IOB。A 保留五责任区并收紧，B 收紧后合并三区，C 只合并不新增切面；
B/C 需要新的三局域实例合同。名义轴线真空不等于整面真空，现有实体见证尚未消除，`build_authorized=false`。
容量估算不授权构建；各向异性网格也须按区域敏感性验证，不能绕过失败接口。

## 缓存、短路径与发布

PA-family 与 working-point 缓存分开。[local_operating_pa_cache.py](../analysis/local_operating_pa_cache.py)
把五个 operating PA0 接入公共缓存，身份绑定基准 PA0、响应、实测归一化、完整四电压及公共合成实现。
命中只物化私有可写 PA0；缺失按区流式合成后发布，每区临时响应副本在输出哈希后删除。
IOB、Fly2 和运行配置每 run 重新装配；相同文件名不构成缓存命中。

只读、硬链接以及完整复制后的 family 都不是 SIMION family 写入的隔离边界。长路径输入通过
[公共 short_pa_path_support.ps1](../../../common/simion/short_pa_path_support.ps1)生成经过验证、可写、可丢弃且
无 `.paN` family 语义的短路径副本。原生 family 操作仅允许在新建 family 的一次性 build staging 中发生；
已发布 cache 及其物化副本中的 `.paN` 均不得由 SIMION 打开。构建/飞行后仍 probe 完整源 generation。
同 key 重建后从 `current_generation.json` 解析当前 generation，不修改旧 run 收据，也不依赖其失效的物理目录。

容量预检和终态门禁保护所有使用中的 generation 与 cache key，清理规则只由公共层维护；见
[公共 SIMION](../../../common/simion/README.md)与[运行规范](../../../docs/OPERATIONS.md)。
长 PA 输入和缓存回归只证明执行路径，不授予任何物理性能。

## 历史与来源

旧几何审查、r50 首次自然命中、棱镜切换、局域网格试探和逐轮 Jacobian 记录统一见
[整治前两页原文快照](../docs/history/20260911__project-and-simion-status-freeze.md)。
官方 API 用法查[SIMION 参考](../../../docs/SIMION_REFERENCE.md)；执行结果只从本次受管 manifest 与日志读取。
