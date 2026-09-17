# MR-TOF Candidate SIMION 路径

本页说明活动 SIMION 实现与操作边界；当前资格、有效证据和开放任务以
[项目状态](../docs/PROJECT.md)为准。项目只保留一条可执行整机路径：静态 P1/P2、关于 `z=0` 的非重合
镜像去回程，以及离子在 `z>0` 沿 `-z` 命中朝 `+z` 的探测面。首次安全离开加速器后禁止重入；旧的
沿 `+z` 穿过加速器命中、棱镜电压切换、回程进入 P1 和旧中央差分调压入口均已删除。旧 PA/IOB 不因
源码修复自动恢复有效性。

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

|组件|一次性 build staging 控制器|活动飞行 IOB 输入|当前网格 mm/gu|构建期求解范围|
|---|---|---|---|---|
|五镜双组、四Stripe、中央接地、两棱镜及屏蔽|`mrtof_analyzer.pa0`|`iob_input_analyzer.pa`及五个`iob_input_local_*.pa`|`1,1,1`|`pa1..pa20`|
|独立屏蔽二区加速器|`mrtof_accelerator.pa0`|`iob_input_accelerator.pa`|`0.25,0.25,0.1`|局部`pa1..pa9`|
|独立数值终止平板|不适用|`iob_input_detector.pa`|`1,1,1`|无Refine、无PA0、无basis|

分析器basis使用从1到最大ID20的完整命名空间；未使用ID19的零响应数组不是新增物理电极。
SIMION 2020会拒绝对不存在的ID执行Refine。构建器先扫描原始ID；对范围内的编号空缺以官方
`pa:potential` setter生成严格全零响应、保留材料掩码并保存为对应PA文件，存在的ID仍按默认Refine求解。
禁止请求高于物理最大ID的数组，不能为补齐编号增加虚构实体。
主分析器为`x/y/z=1/1/1 mm/gu`：CAD固定的30-mm镜束槽（边界`x=±15 mm`）与4-mm Stripe／接地／棱镜屏蔽槽（边界`x=±2 mm`）在同一个2-mm网格相位中不可同时精确表示，故`x=1 mm`是几何审查的硬约束；`z=1 mm`也使CAD给定的2-mm grounded-1—镜盖板净距包含真空节点。几何包络与孔槽不变。独立加速器当前为`0.25/0.25/0.1 mm/gu`，其中项目`z`是加速方向；该网格解析1-mm环／栅框厚度，但焦点、边缘场、时间与分辨率结论仍须至少三档网格收敛。
GEM直接编译的默认网格也由同一component mesh合同生成，不能留存旧`y=2`默认值。

分析器的 `1 mm` 全局 PA 只作几何兜底；当前轨迹所在五个局域替换区通常使用 `0.5 mm`。镜等时网格
诊断可只把两个镜转折区替换为固定工作点 `0.25 mm` PA，中央和两个桥接区继续复用 `0.5 mm`，不得把
这一混合工作台误写成完整分析器 0.25-mm family。活动入口
[`run_mirror_turn_fixed_grid_validation.ps1`](run_mirror_turn_fixed_grid_validation.ps1)从已解 0.5-mm
standalone 父场复制六面 Dirichlet 边界，只求当前镜电压的两个 0.25-mm 工作点；compact retention
保留场比较、周期结果和日志，不保留多 GB PA。该入口服务网格诊断，不提供 Fast Adjust 或正式飞行 IOB。
该入口的可选 `-NativeTransverseL1` 重用同一次固定场 IOB，以十个冻结横向探针直接在 SIMION 中记录
首次中央面返回的传输矩阵以及完整两镜返回的时间二阶项。它只复核 bare-mirror 的
稳定性、γ 与 $\overline T_{xx}$，不调整电压、不取代三能量等时验证，也不授予 Candidate 资格。
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

分析器与加速器各自拥有独立的 PA-family 构建缓存身份：在一次性 build staging 的 Refine 前，以冻结的
resolved geometry、组件 GEM、局部 ID namespace、mesh、PA 相位、`surface=none`、SIMION 可执行身份、
默认 Refine 策略及构建器哈希向
[`common/simion/pa_family_cache.py`](../../../common/simion/pa_family_cache.py)查询。原生 `.pa0/.paN` family
只允许在该新建 staging 中 Refine、Fast Adjust 或导出；发布后即使完整物化到私有目录，也不得再次交给
SIMION。活动飞行只消费构建期导出的、manifest 绑定的 standalone operating/response `.pa`。任何身份变化、
清单缺失或损坏均失败关闭并重建相应 build staging。探测器是未 Refine 的零电压终止掩码，不进入
field-basis 缓存。IOB 绝不复用：每次都从本 run 的 standalone PA 重新装配、保存和重载检查。

这三个构建入口按实际操作细分公共主机阶段：分析器局域 family、加速器 family 与三组件 IOB 的合同冻结、
缓存、复制、`gem2pa`、原生几何检查和纯 IOB 工作均使用各自未列名的轻量 `*_prepare` 阶段；只有调用内部
含 `pa:refine` 的 Lua 前切换到公共 `SIMION/pa_refine` 重阶段，并在该调用结束后立即切回轻量 prepare。
摘要、保留、容量终态和 manifest 发布使用未列名的轻量 `*_postprocess` 阶段。具体预算与并发决定仍只由
[主机资源调度](../../../docs/OPERATIONS.md#主机资源调度)负责，项目入口不复制容量或并发策略。

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
`iob_seed_placeholder_*.pa0` companion arrays，再装入上述三个组件的 staging PA。
它通过`wb:load()`／`wb:save()`保存IOB；三组平移只能由
`resolve_split_iob_origins()`从本次合同派生。保存IOB后，构建器复制同名的Lua、Fly2、
operating-point与voltage-map companion；这使包可由唯一飞行入口加载，但保存成功本身
仍不能作为任何粒子飞行或物理闭合结论。

仅在同一冻结几何身份的**新建、一次性 build staging** 内，可用
[run_three_component_candidate.ps1](run_three_component_candidate.ps1)建立可审计的**无飞行**装配包。
该入口冻结候选合同、镜L0/L1 receipt、两份**精确生成GEM**、两份已解PA0及其原始PA#、零电压探测器PA#和完整十一文件
IOB seed bundle；它在host execution lease内装配并重载检查IOB。它不构建或发布PA-family缓存，
也不调用`Fly`，因而只可发布`prototype_geometry_review_only`证据。任何中心粒子或N=100飞行必须由
后续专用运行器从这个已检查的run-local包开始，先在构建期导出并校验 standalone operating PA，再由
飞行入口重新绑定实际Fly2、原始日志和事件分析receipt；不得
以此入口的success manifest声称传输、K=25或分辨率。

在复制大型PA前，该入口通过`common/contracts/run_artifact_support.ps1`的
`Invoke-ArtifactCapacityGate`以实际待复制的冻结输入字节数预留容量，并保护新run；终态再以启动测量和
实际run目录大小复核同一水位。两份JSON receipt随run冻结。清理优先级、可删范围和缓存键保护仍只由
`common/contracts/reconcile_artifact_capacity.py`定义；本入口不定义第二套项目级删除规则。

电压映射只由[candidate_voltage_map.lua](candidate_voltage_map.lua)提供：materializer将其冻结为
`mrtof_candidate.voltage_map.lua`。上述无飞行几何审查入口只在新建 build staging 中让 IOB 构建器按
operating-point sidecar 对两张 PA0 执行`fast_adjust → save`；不得把已发布 cache family 物化后送入该路径。
活动飞行则加载已经导出的 standalone operating PA，并保持运行时 Fast Adjust 关闭。
IOB同名的Program、operating-point与voltage-map三份Lua伴随文件必须一起保留。
纯Lua回归已验证映射、调用顺序和伴随文件。重载检查器读取原始PA#的物理ID，为全部19个分析器和
9个加速器电极各检查一个真实材料节点的已存PA0电势；过程中禁止重新Fast Adjust，以免掩盖保存错误。
探测器检查所有节点严格零电势且存在材料，三个实例还须无旋转、scale=1。真实运行结果以本次报告为准。

八实例模板 `8_instance_seed.iob` 及其 `iob_seed_placeholder_*.pa0` 仅用于构建，不是可交付工作台；
运行结束清理短路径或 placeholder 后，单独打开该 seed 必然不能恢复实际 PA。GUI 审查包必须由
[run_analyzer_local_workbench.ps1](run_analyzer_local_workbench.ps1) 发布为
`mrtof_complete_3d_candidate_gui_review.iob`，并在同一 `simion/` 目录保留语义明确的
`iob_input_analyzer.pa`、五个 `iob_input_local_*.pa`、`iob_input_accelerator.pa` 和
`iob_input_detector.pa`。既有 r14 的同等持久包沿用历史名 `mrtof_local_replacement.iob`；它是可加载的
旧命名产物，不应与临时 seed 混淆。

单中心时间步三档对照由
[single_center_timestep_convergence.py](../analysis/single_center_timestep_convergence.py) 及受管入口
[run_single_center_timestep_convergence.ps1](../analysis/run_single_center_timestep_convergence.ps1) 完成。
分析器要求三个 success run 的几何、PA、电压、源、程序、脉冲和自然回程身份完全相同，只允许最大
trajectory step 不同；它报告目标 K 返回、正镜回程转折和最终探测终态的完整相空间差值，不自行设置
通过阈值。当前三档结果见项目状态页。

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
|`full_mrtof_center_fly2`|由已审计P1/P2工作点按run局部生成|完整源→P1→负镜预反射→P2→P2后参考截面→正镜转折(`y=0`)→Stripe→静态自然回程→探测器；N=1/N>1均走同一完整三维事件链，仍不授予性能资格|

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
精确目标K相位返回时，事件分析另将两个端点之间的`2K-1`个内部`fast_turn`首尾配对，输出
`mirrored_nonretracing_branch_turn_diagnostics`：同一y残差、`z_return+z_outbound`及速度反向残差。
它验证关于`z=0`的两条非重合镜像支路；未精确返回或内部转折数不是`2K-1`时拒绝配对，数值收敛前不赋容差。

## 飞行与求根入口

所有入口从已审计 run 消费冻结合同、源与 PA 身份；参数说明直接查看对应脚本的 `param` 定义。
以下入口具有不同资格，不能互相替代。仅以代码格式出现而没有链接的名称尚未随当前 Git 修订发布，
不能作为当前可调用入口。

| 任务 | 受管入口 | 结果范围 |
|---|---|---|
| N=1 或 N>1 完整飞行 | [run_two_prism_trial.ps1](run_two_prism_trial.ps1) | 四残差与 `P2 → 正镜 → z>0,v_z<0` 静态回程观测 |
| 首棱镜隔离诊断 | [run_three_component_first_prism_flight.ps1](run_three_component_first_prism_flight.ps1) | 首棱镜接口 |
| 静态第一时间焦点 | [run_accelerator_focus_flight.ps1](run_accelerator_focus_flight.ps1) | 独立加速器焦点，不是束团出口时钟 |
| 完整中心源的加速器首出口 | [run_accelerator_exit_flight.ps1](run_accelerator_exit_flight.ps1) | 真实源至独立加速器 PA 负向出口，不是 P1/P2 或整机结果 |
| N=100 冻结束团源发布 | [run_publish_bunch_source.ps1](../analysis/run_publish_bunch_source.ps1) | 只生成 CSV/Fly2/receipt，不运行 SIMION |
| N=100 全局关断时钟冻结 | [run_freeze_bunch_pulse_schedule.ps1](../analysis/run_freeze_bunch_pulse_schedule.ps1) | 消费同源 static pilot 的完整安全出口队列，不运行 SIMION |

局域工作台入口只复制或导出已求解 PA、线性合成 standalone 响应并装配检查 IOB，全程使用未列名的
轻量 `prepare` 阶段；它既不 `refine` 也不飞行。静态第一时间焦点入口消费已发布 standalone 响应，
通过公共合成和 operating PA cache 调压，已完成中心粒子实跑；物理验证范围见项目 PROJECT。
不得使用已发布原生 PA-family 的私有副本执行 Fast Adjust。缺少 standalone 响应时，只能在新的独立
构建 staging 中 Refine 并导出后发布，不能打开旧缓存补导出。准备与合成属轻量阶段；只有原生离子
飞行切换到 `flight` 重阶段，子进程退出后再切回轻量 `postprocess` 做分析与证据发布。
该入口显式接受 `GeometryReviewRunPath`、`AcceleratorFamilyRunPath`、`StandaloneComponentRunPath`
和 `SelectedNetGainCenterV`；首区压降缺省由理想二区时焦种子派生。生成源独立冻结，IOB 保存后再
复制为工作台伴随 Fly2，并在飞行前核对源字节及 receipt 哈希，防止模板源覆写。

加速器首出口入口以 `-CalibratedFocusRunPath <run>` 消费已验证焦点运行的三份 standalone PA、
reviewed 几何、实际电压 trial、装配位姿及积分控制；不重新 Refine、调压或移动源。
[accelerator_exit_simion_analysis.py](../analysis/accelerator_exit_simion_analysis.py)复用既有中心源生成与
相空间重建，读取冻结合同的质量、电荷和加速前慢能，生成沿 `+y` 的 N=1 释放。独立
[mrtof_accelerator_exit.lua](mrtof_accelerator_exit.lua)从实际 IOB 唯一识别加速器 PA，并核对源所在的
实际实例；负 `z` 出口面从 PA 网格及坐标变换派生，不固定为某个实例号或手填坐标。
分析同时核对实测出生状态、唯一安全出口、终止顺序和原生 Fly 完成记录。下游只消费插值出口事件的
完整位置、速度、时间及物种，不用 terminate 回调状态替代，也不向零初能焦点记录补慢向速度。
该工作流保留可 GUI 重开的 IOB，但成功仅代表中心源至加速器出口；不证明时焦导数、P1/P2 输运、
完整返回、束团时钟或质量分辨率。实际运行证据与限制只在 PROJECT 登记。

## 事件与脉冲合同

[mrtof_candidate.lua](mrtof_candidate.lua)与[mirror_cycle_counter.lua](mirror_cycle_counter.lua)以 P2 后正镜
转折定义快相位原点；每个后续真实镜转折增加半个周期。baseline 的
`target_drift_period_ratio` 与 `fast_path_symmetry` 唯一派生目标半周期数和返回镜侧，不在 Lua 或 Python
中固定某个 K。当前 25.5 自动对应 51 个半周期和负镜返回；改为另一正半整数不需要修改代码。
解析电压链使用 `analysis/run_target_operating_point_chain.ps1`，从同一 baseline 自动串接镜 exact-K
工作点和双 Stripe 反演；SIMION 只消费其后 materialize 的电压 receipt，不另存几何或 K 参数。
中央 `z=0` 穿越及提前出现的 `y=0` 只报告诊断，达到目标负镜转折才产生严格相位返回事件。实际坐标
残差与相位返回分开报告，目标事件不切换棱镜电压。
P1/P2 始终保持注入态；trial runner 已删除棱镜提取态与切换时刻公开参数，Lua 与分析器仍会对旧 receipt/sidecar 中非空切换字段失败关闭。
目标负镜转折后，离子以 `v_z>0` 自然通过 P2，再由必要的正镜转折把方向变为 `v_z<0`，随后直接朝
正 z 半空间内、法向为 `+z` 的检测面飞行；P1 只属于注入支路。Stripe、P1/P2 和漂移区不得改变
`v_z` 符号；只有
已解析的镜区转折可以反号。

删除旧拓扑入口后的真实 SIMION 2020 回归
`20260915_223500__sim__simion__mrtof-single-current-only-path-n1-r26` 已通过：中心离子达到
`K=25.5`，自然通过回程 P2，经正镜转折后在 `z=97 mm`、`v_z<0` 命中检测器，TOF 为
`789.250482694 us`；未出现回程 P1、加速器重入或棱镜电压切换。飞行入口现在只生成
`complete_three_dimensional_static_return`，旧截断和 x 对称约束字段不再接受为当前收据。

同一入口的当前代码 N=100 复核
`20260915_231500__sim__simion__mrtof-bunch-current-only-path-n100-r27` 完成 100/100 粒子并保持
100/100 目标 `K=25.5`、88/100 探测命中、12/100 真实电极碰撞。`-BunchParticleIdMin` 与
`-BunchParticleIdMax` 只允许从一份已验证冻结源收据选取连续区间作诊断；它不建立第二 runner，局部 SIMION
ID 在日志合并时严格恢复为原全局 ID，结果标记为非 Formal 的 source-selection diagnostic。
`-TrajectoryStepScale` 只可在 `(0,1]` 内缩小合同具名 profile 的最大步长。临界 ion 97/98 已分别以
`0.002 us`（r28）和 `0.001 us`（r29）复核，均保持 97 在 electrode-20 的 `z=-97 mm` 孔唇碰撞、
98 通过；因此后续应改善返回包络，不改动已加工孔径或过滤源粒子。

加速器有 `static`、仅 N=1 的 `initial_exit_triggered_single_center` 和 `fixed_global_time` 三种互斥模式。
固定时钟必须通过 `-AcceleratorPulseSchedulePath` 消费冻结收据，在共同 `tob=0` 的 `ion_time_of_flight`
上关闭 standalone 加速器实例的电场；`tstep_adjust` 落到计划边界，事件记录实际与计划时刻。电极实体与
碰撞几何始终由同一 PA 保留。禁止用裸时间参数替代身份收据。
`run_freeze_accelerator_pulse_schedule.ps1`目前仅能冻结
成功 N=1 首出口为 `single_center_diagnostic__not_a_bunch_schedule`。它不提供完整束团的最后安全出口与 guard。
[bunch_source_and_schedule.py](../analysis/bunch_source_and_schedule.py)提供求解器无关的确定性母束团前缀、
逐粒子唯一 `accelerator_safe_exit` 检查、`max(exit)+guard` 推导和 N 粒子共同关断事件校验。
[candidate_bunch_source_n100.json](../config/candidate_bunch_source_n100.json)冻结首个 Candidate 小展宽：
位置半径 `0.1 mm`、加速轴全宽 `0.2 mm`、`5.0 eV` 中心及 `0.1 eV` 全宽、角度 `0.2 deg`
全宽、`524 Th/+1`、共同 `tob=0`；中心数值必须与同一冻结几何合同自然派生的第一区 release 点一致。
[run_publish_bunch_source.ps1](../analysis/run_publish_bunch_source.ps1)把完整定义和几何合同复制为 run-local
输入并发布 N=100 CSV、逐粒子 Fly2 与 receipt，全程不运行 SIMION。该源已由唯一完整飞行入口通过公共
资源调度器执行 static pilot：100/100 粒子安全出射并达到目标 `K=25.5`，88/100 命中检测器，12 粒子发生
真实电极碰撞；这只证明静态 Candidate 束团链和事件完整性，不是固定时钟或分辨率资格。
[run_freeze_bunch_pulse_schedule.ps1](../analysis/run_freeze_bunch_pulse_schedule.ps1)是后续 static pilot 的
独立冻结边界：它完整验证 source/pilot 两份 manifest，要求 trial receipt 和原始日志确属 pilot 输出，
再对 N 个粒子的唯一负 `z` 安全出口逐一对账。`guard_us`没有脚本默认值，必须由调用者显式给定并写入
run config；其值至少覆盖 pilot 的一个冻结最大轨迹步。输出 schema-2 schedule 同时绑定 source cohort、
solver problem identity 与 `max(exit)+guard`，但本入口本身不飞行，也不证明固定时钟已在 SIMION 中执行。

`sim_segment_global=1`用于覆盖 PA 外终态；仍须逐粒子对账、唯一成功终止和原始日志完整性。
[run_iob_flight.lua](run_iob_flight.lua)要求 IOB 同名 Program、Fly2、operating-point、voltage-map 和
mirror-cycle-counter 伴随文件；实际源必须与冻结 Fly2 字节一致。旧不完整日志不能补造资格。

## 数值执行边界

积分设置只由候选合同的 `trajectory_profiles` 派生；入口选择 ID，不接受游离时间步。
`run_accelerator_focus_flight.ps1 -ExactKRunManifest <manifest> -TrajectoryProfileId <id>` 从已验证的
Stripe-on exact-K 收据自动读取轴向净增益，并从本次冻结 baseline 解析已有积分档位；省略档位时使用
其 `default_trajectory_profile_id`。`-SelectedNetGainCenterV` 仅保留给明确的部件诊断，和 exact-K manifest
严格互斥。实际净增益及其来源、quality、最大步长、档位和来源 SHA 写入 operating-point receipt 及
run config；只改变积分控制，不改变 PA 几何或位姿。
同一入口的 `-FocusCalibrationRunPath <run>` 消费已验证的完整焦点诊断 run，用器件理论的固定净增益
解析灵敏度生成一次首区压降建议；与 `-FirstGapDropV` 互斥。上游分析、trial、manifest 和理论源码随
本次输入冻结，粒子表必须保持相同；建议仍需本次真实飞行验证，不是已接受电压或严格局部焦点结论。
`center_screening` 用于中心筛查，更细 profile 用于同一物理点的步长敏感性，不能替代 PA 网格收敛。
静态飞行读取已保存的 standalone operating PA，默认 `runtime_fast_adjust_enable=0`；电压化在飞行前完成，
不能在每个积分段重算完整 basis。加速器脉冲也只绑定这一份 standalone operating PA：通电阶段保留其原场，
关断后由 `efield_adjust` 在加速器实例内把场三分量置零，同时保留同一 PA 的电极实体与碰撞几何；运行时不再
物化、打开或 Fast Adjust 加速器 `.pa#/.pa0/.paN` family。

[analyzer_local_refinement_plan.py](../analysis/analyzer_local_refinement_plan.py)及
[analyzer_local_patch_geometry.py](../analysis/analyzer_local_patch_geometry.py)从同一 resolved 几何派生局域计划与 GEM。
全局 1-mm 分析器作为远场回退，五个 0.5-mm 局域替代按合同重叠责任区接管；独立加速器和探测器保持各自 PA。
局域场替换全局场，不是两个零边界场相加。每区保留镜 B--E、S1/S2、P1/P2 八组响应与实测 basis 归一化，
六面边界从同源全局响应插值。正负局域场分别构建，不能因机械镜对称复用受离轴棱镜影响的场。

[run_analyzer_local_pa_family.ps1](run_analyzer_local_pa_family.ps1)调用公共缓存与 Dirichlet 原语。
入口不再直接消费 reviewed run 中的原生 `.paN`。先由
[run_prepare_reviewed_analyzer_source.ps1](run_prepare_reviewed_analyzer_source.ps1)一次性验证 22 件原生 family，
把实际需要的 14 个物理电极响应导出为 standalone `.responseN.pa`；原始 `.pa#` 作为独立、同源绑定的
只读 generation 发布。局域 family 缺失时仅从这 15 件冻结输入建立带活跃只读句柄的短路径副本，发布前和
清理前都复核实际被 SIMION 消费的副本；命中时不复制、不租用 SIMION、也不 Refine。

[run_analyzer_local_family_batch.ps1](run_analyzer_local_family_batch.ps1)用于同一批五区：先只根据 receipt 元数据
派生全部 cache key；缺失区共享同一批 15 件受保护输入副本，任一复制中途失败由创建函数立即清理此前副本。
每个局域 generation 只在其子 runner 中完整哈希一次，batch 预计划不再重复读取多 GB 命中 payload；各区仍按
自身几何分别 Refine，已命中区直接复用。容量门禁在清理前同时保护 reviewed standalone、raw geometry 和本批
全部局域 cache key。几何 provider 的 manifest 由 prepared receipt 的冻结哈希绑定，子 runner 只复核实际消费的
resolved contract、GEM 与 geometry review，不再为未消费的 14.7 GB 原生 family 重复全量哈希。
`instance_adjust` 只在合同从重叠区导出的半开责任区内接管；portal 真空穿越、非 portal 不穿越、电势/法向场、
事件拓扑和固定粒子轨迹必须分别验证。当前中心接口证据不能替代束团包络或第三档网格，每档须重新求中心根。

[run_mirror_real_field_voltage_family.ps1](run_mirror_real_field_voltage_family.ps1)只服务制造镜 B--E 的真实场
L0 电压族。首次模式显式传入一个成功的局域工作台，用 SIMION 从五个 `0.5 mm` family 的四组 standalone
镜响应采样同一轴线；后续模式显式传入成功的 response-basis run，验证其 manifest、输出哈希、网格和
cache generation 后直接复用 CSV，不再打开 PA 或调用 SIMION。两种模式都从 baseline 的
`real_3d_l0_voltage_family_profile` 读取采样间距、`y` 截面、E 切片数和求解数值参数，run-local 冻结该
baseline；runner 不提供同义数值 CLI。输出资格固定为轴向 `0.5 mm` surrogate，只能生成 L0 一维族，
不能替代真实轨迹的稳定性、`gamma`、`Tbar_xx`、峰值场或最终 `0.25 mm` 固定点复核。

`analyzer_local_z_compression_plan.py`是只读规划器：

```powershell
python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_z_compression_plan `
  --contract projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json `
  --scale-factor 0.5
```

它不调用 SIMION，不修改 PA/IOB。A 保留五责任区并收紧，B 收紧后合并三区，C 只合并不新增切面；
B/C 需要新的三局域实例合同。名义轴线真空不等于整面真空，现有实体见证尚未消除，`build_authorized=false`。
容量估算不授权构建；各向异性网格也须按区域敏感性验证，不能绕过失败接口。

## 缓存、短路径与发布

PA-family 与 working-point 缓存分开。`local_operating_pa_cache.py`
把五个 standalone operating PA 接入公共缓存，身份绑定基准场、响应、实测归一化、完整四电压及公共合成实现。
命中只物化私有可写 standalone PA；缺失按区流式合成后发布，每区临时响应副本在输出哈希后删除。
IOB、Fly2 和运行配置每 run 重新装配；相同文件名不构成缓存命中。

需要让同一电压态的多个粒子 cohort 共享局域场时，先运行
`run_local_operating_pa_prewarm.ps1`，显式给出一个已验证的局域工作台及完整
`[S1,S2,P1,P2]`。入口在命中时不合成；缺失时通过现有五个 composition lane 只生成一组标准命名 PA，
原子发布并再次验证为 exact hit。该 run 仅发布执行缓存，不运行离子、不产生物理资格；后续 flight 仍以
同一局域工作台和逐位相同的四电压调用 `run_two_prism_trial.ps1`。

完整 Stripe 回程灵敏度诊断由
`analysis/run_stripe_return_sensitivity_campaign.ps1` 统一编排：它冻结 r26--r29、显式电压扰动和成员
run-id 前缀，先为四个非基线状态各调用一次上述 prewarm，再逐条执行分析计划中的八个 cohort flight，
最后调用同一 `stripe_return_sensitivity.py` 分析器。基线 ion 1/97/98 直接复用 r27，不重复飞行；campaign
不设置并发数或第二套资源策略，每个子入口继续服从仓库公共调度器。
`-ReuseSuccessfulChildren` 只用于恢复已终止的 campaign：它仍逐项验证既有 prewarm/member 的完整
success manifest，并额外核对 prewarm 的四电压向量和局域工作台身份；未通过时失败关闭，不能用来绕过
子运行。首个完整发布为 `20260916_070000__analysis__python__stripe-return-sens-d0p25-r2`，复用了同前缀下
4 个已验证 prewarm 和 8 个已验证成员飞行。其三粒子 `delta=0.25 V` 导数不能代表全束团：后续
`20260916_073000__sim__simion__mrtof-stripe-s1-plus-d0p25-n100-r30` 在 100/100 达到目标 K 的同时只有
56/100 命中、44/100 碰撞；其中 36 个为 P2 孔唇，另 8 个已进入中央/Stripe 邻域的不同碰撞支路，
明确否定将该抽样方向提升为工作点。

只读、硬链接以及完整复制后的 family 都不是 SIMION family 写入的隔离边界。长路径输入通过
[公共 short_pa_path_support.ps1](../../../common/simion/short_pa_path_support.ps1)生成经过验证、可写、可丢弃且
无 `.paN` family 语义的短路径副本。原生 family 操作仅允许在新建 family 的一次性 build staging 中发生；
已发布 cache 及其物化副本中的 `.paN` 均不得由 SIMION 打开。构建/飞行后仍 probe 完整源 generation。
同 key 重建后从 `current_generation.json` 解析当前 generation，不修改旧 run 收据，也不依赖其失效的物理目录。

容量预检和终态门禁保护所有使用中的 generation 与 cache key，清理规则只由公共层维护；见
[公共 SIMION](../../../common/simion/README.md)与[运行规范](../../../docs/OPERATIONS.md)。
长 PA 输入和缓存回归只证明执行路径，不授予任何物理性能。

该链的真实闭环证据为：r135 成功发布/命中 reviewed source generations；r137 从同一 15 件受保护输入完成
`mirror_turn_negative, scale=0.5` 的 Refine 与发布；r138 直接命中同一局域 cache；r140 又经 batch 入口完成
同一区命中，未复制源、未调用 SIMION 或 Refine。r133 的空电极 19 导出错误和 r134 的 retention 输入错误均为
已修正的失败证据，不得写成成功。当前 r51 的 22 件 native family 只读复核为 22/22 与冻结记录一致；先前瞬时
读差异没有已确认写者，也不能归因于 SIMION。r41 继续作为本链可靠完成验证的 provider。

当前受管重建链为 r88--r90 的三个逐字节复现 generation、r91/r92 的两个 cache-hit provider，以及工作台
`20260917_010000__build__simion__mrtof-local-r55-detached-r94`。r94 的 IOB 仍只含全局分析器、五局域替代、
独立加速器和独立探测器八个运行 PA；原路径和长 artifact 路径检查均通过，且在检查后删除十个仅用于载入
seed 的 placeholder `.pa0`，共 `164034040 bytes`，清理收据保存在 run config/summary。此前工作台
`20260916_231000__build__simion__mrtof-local-r55-detached-r85` 和飞行
`20260916_235000__sim__simion__mrtof-r55-detached-flight-r87`。r87 的 compact IOB 只在临时目录绑定八个
短路径副本，飞行后删除；其 success manifest 保留上游 standalone PA 身份、实际日志、观测和本次 sidecar。
已封存 r85 不做原位修改。

## 历史与来源

旧几何审查、r50 首次自然命中、已删除的棱镜切换支路、局域网格试探和逐轮 Jacobian 记录统一见
整治前两页原文快照候选 `20260911__project-and-simion-status-freeze.md`；该快照尚未随当前 Git 修订发布。
官方 API 用法查[SIMION 参考](../../../docs/SIMION_REFERENCE.md)；执行结果只从本次受管 manifest 与日志读取。
### N>1 automatic single-wave dispatch

`run_two_prism_trial.ps1 -BunchSourceReceiptPath ...` remains the only full-flight
runner.  It verifies that the receipt, state table, and full Fly2 are unique
outputs of one successful source-run manifest.  The repository resource
scheduler consumes historical exact-identity profiles when available; otherwise
the first ten percent of the cohort is retained as formal work, observed for the
repository 45-second window, allowed to finish, and used to replan the remaining
single wave.  No project-local worker count or CPU floor exists.

Each planned batch is one contiguous global particle-ID interval and keeps the
source's common `tob=0`.  SIMION sees local IDs `1..n`; merge uses only the
planner's `simion_particle_id_offset`, rejects incomplete/overlapping coverage,
retains every non-completion line, and emits exactly one global Fly-completion
sentinel before the ordinary cohort analysis.  Parallel workers receive private
short-path standalone PA copies and private IOBs.  These copies reuse the one
already-composed operating field; no batch performs PA composition or Refine.
The first local-replacement batch assembles the eight-instance IOB once; later
batches copy that exact IOB and its invariant Lua companions into bundles that
still contain eight independent writable PA copies and one batch-specific Fly2.
Before flight, one relocated clone is reloaded while the template directory is
hidden, and the run receipt binds instance basenames/poses, companion hashes,
distinct Fly2 hashes, and every private PA hash before and after flight.
Before initial materialization and again after a formal-first replan, the
capacity gate reserves the total byte size of every planned private PA set.
The run manifest binds the source run manifest, scheduler request/profile/plan,
particle batch plan, resource usage, merge receipt, and retained raw logs.

### Fixed-grid mirror handoff to Stripe theory

`run_mirror_turn_fixed_grid_validation.ps1` consumes the reviewed analyzer GEM from the geometry
evidence run and the detached standalone source generation from the prepared-source run.  It does
not bind or reuse the mutable PA family from the geometry evidence run.  Fixed 0.25-mm operating
PA cache hits are materialized from the exact pinned generation recorded by the probe/publish
receipt; a later generation with the same logical key cannot silently replace it.  Snapshot-only
upstream run directories are not protected as multi-GB cache roots after their required evidence
has been copied into the run package.

The current successful mirror handoff is
`20260917_223000__sim__simion__mrtof-measured-chord-root-fixed-grid-r130`.  Its native period and L1
evidence can be consumed without rebuilding PA files:

```powershell
pwsh -NoProfile -File projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_dual_stripe_operating_seed.ps1 `
  -FixedGridRunManifest <r130-run-manifest>
```

This mode verifies the complete fixed-grid manifest, selected-energy voltage envelope, all three
period-slope gates, both native stability maps, and the `0.01 deg` gamma gate.  It derives W from
the average of the two native full periods and applies the native CAD-curve spatial-return inverse
to obtain S1/S2.  The nominal 5-eV slow-axis source energy is adjustable by the upstream
multipole/source transport: with the qualified mirror fixed, the analytic `T_D/T_0=K` relation
selects the nearby slow-energy centre, and the spatial-return/turning-energy inverse then selects
both Stripe biases.  The active r3 handoff gives `4.96113169188 eV`,
`v1=-25.22321875 V`, `v2=+50.18222993 V`, and analytic `K=25.5` without changing B--E.
It does not alter geometry, qualify P1/P2, or publish an exact-K three-dimensional operating point.
