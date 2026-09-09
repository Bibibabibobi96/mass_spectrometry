# MR-TOF Candidate SIMION 路径

本页说明活动 SIMION 实现与操作边界；当前资格、有效证据和开放任务以
[项目状态](../docs/PROJECT.md)为准。源码具备三组件几何生成与事件完整性校验，不代表完整装配、
脉冲注入、双程棱镜或探测链已经通过验证；旧 PA/IOB 不因源码修复自动恢复有效性。

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
原生平板终止与Lua命中事件面的对应关系仍须验证。

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

## 尚未闭合的飞行接口

当前[mrtof_candidate.lua](mrtof_candidate.lua)仍有以下物理限制，事件完整性PASS并不消除它们：

- 主程序现已绑定[mirror_cycle_counter.lua](mirror_cycle_counter.lua)：P1 后先记录负镜预反射，
  随后通过 P2 和正侧 Stripe 区；首个`v_y>0`正侧镜转折建立主漂移相位原点。
  此后每个“正侧转折→负侧转折→正侧转折”增加一个完整周期，并在每个同侧转折发布整数K相位样本；
  只有同侧正镜转折同时满足`y=0,v_y<0`才是严格相位返回。若轨迹在两个相位样本之间穿越`y=0`，
  只发布坐标返回诊断，并由相邻同侧周期计算连续圈数，绝不把它冒充整数K相位闭合。`z=0`穿越只保留为
  Poincare/周期诊断，不再拥有周期相位。第50次镜转折
  不会主动截停；真正成功终止仍由探测器命中负责。该状态机已有SIMION 2020 Lua合成轨迹回归，但尚无
  合格K=25返回证据，因而不构成真实三维完整引出或探测证据。
- 棱镜16（路径 P1）和棱镜17（路径 P2）均在主漂移前；二者之间存在真实负镜预反射。棱镜只记录
  `prism_pass`/`prism_entry`，绝不以`v_z`反号伪装棱镜事件。约4-keV轴向能量不是棱镜电压；活动
  有限三维射击在百伏量级校正P1/P2。旧P2=`0 V`仅是被取代的几何审查显示值；
  加速器同样未实现脉冲时序与源时钟闭合。
- Lua已按合同改在探测器`+z`外表面接收沿`-z`入射，保留初始步并对中央面采用半开区间和插值；
  纯Lua回归通过，但实际平板终止与检测事件的对应仍待全装配飞行复核。
- `sim_segment_global=1`已启用。SIMION 2020（8.2.0.11）同一N=2原生生命周期回归确认：关闭时仅记录PA内
  粒子终止，开启后PA内与PA外各一个粒子均有终态；不需`early_access`。这不代替旧漏记录束团的重新飞行。
- [run_iob_flight.lua](run_iob_flight.lua)要求IOB同名的Lua、Fly2、operating-point、voltage-map和
  mirror-cycle-counter sidecar。
  [run_three_component_center_flight.ps1](run_three_component_center_flight.ps1)是唯一的N=1中心粒子入口：
  它从已审计P1/P2工作点冻结代码、合同与完整中心源，并把已电压化的分析器/加速器PA及零势探测器PA
  以只读路径装入run-local IOB；既不复制约1 GiB PA载荷，也不执行PA save，且构建和飞行前后核对三份
  上游PA哈希。入口拒绝IOB同名Fly2与冻结源字节不一致。入口只发布全终态事件链的
  `candidate_prototype_event_chain_only` receipt；不运行束团、不产生分辨率结论，也不修改上游PA或P1/P2 run。

受管run `20260909_041000__sim__simion__mrtof-center-n1-readonly-pa-fractional-return`首次越过上述
只读装配、源身份和事件完整性门禁：P1/P2分别为`+177.661775543/-180.055454662 V`，不是4 kV；
慢向转折为`258.778899196 mm`，坐标返回为`K=19.014224397`，其后在P2屏蔽附近碰撞，探测数为0。
因此它确认了完整中心源、只读PA复用和事件链功能，同时否决当前电压点的`L=340 mm、K=25`物理闭合。

[run_two_prism_trial.ps1](run_two_prism_trial.ps1)现同时服务P1/P2交接局部试点和后续四坐标下游试点：
可选Stripe1/Stripe2电压必须成对给出，`-ContinueMainDrift`要求同时观察相位原点、首个慢向转折和
连续返回K。入口不再把约1-GB电压化PA0复制进每个run，也不在逐步回调中重复Fast Adjust；它从
不可变分析器family在系统临时目录只合成一次PA0，建立临时IOB并飞行，逐项核对源PA哈希后删除临时
PA/IOB。artifact保留冻结小输入、完整日志、四残差、临时PA哈希和重建方法。
它现在也可显式给出同一时刻的P1/P2提取态电压。静态PA0仍承载镜、Stripe和注入态棱镜电压；
SIMION `segment.fast_adjust`只重组发生切换的电极16/17基数组，其他约18张分析器basis不进入逐段计算，
也不执行refine或保存上游PA。切换时刻、电极ID、注入态和提取态均写入run-local sidecar及manifest；
全分析器Fast Adjust与该单电极路径互斥。该实现是提取诊断能力，不表示提取电压已经闭合。
提取试算还必须给出一个已成功主漂移run作为`ReferenceTransportRunPath`：入口验证其manifest，直接继承
该run的Stripe电压和P1/P2注入态，并从其唯一`drift_coordinate_return`事件自动取得切换时刻。任何回落到
理论Stripe初值、改变注入棱镜电压或手工给出不一致切换时刻的请求都会失败关闭。

2026-09-10首轮切换诊断把P1/P2注入态固定为`+177.537401235/-179.126593079 V`，在中心离子
`y=0`坐标返回`773.579816892 us`切换；这里的约`180 V`来自5-eV慢向/约4-keV快向能量的有限三维
校正，`4 kV`只属于加速器净增益和镜轴向能量，绝不是棱镜电压。P2提取态`0,-30,-65,-70,-75,
-90,-100,-120,-135,-140,-160,-170 V`及`+140 V`的有界诊断均未命中探测器，但已经区分了P2屏蔽、
25-mm加速器孔边和加速器环/框等不同终止边界。`P1=0/100/140 V`与`P2=-140 V`也已验证P1是独立的
回程控制量。当前只能据此建立双变量提取射击问题，不能从任一单点发布工作电压、探测率或分辨率。
日志新增双向`detector_plane`相空间样本；探测器成功仍只接受其合同规定的`+z`外表面沿`-z`入射。
受管run `20260910_080000__sim__simion__detector-chain-event-audit-n1`首次完整审计动态链路可达：
在`K=24.9995073622`的坐标返回面将P1/P2切到`0/-140 V`后，中心离子最终于
`t=1654.71284613 us`、`(x,y,z)=(0.03616,-43.16221,97) mm`命中独立探测器。切换到命中历时
`881.133029238 us`且有59个额外镜面转折；日志恰有一个detector和一个`splat=1`事件。该结果只是
`prototype event chain`证据，不是目标K=25提取解，也不能用于分辨率声明。
随后受管run `20260910_093000__sim__simion__p1-minus60-p2-minus140-extraction-n1`
把提取态改为`P1/P2=-60/-140 V`，在切换后`83.327634611 us`、6个额外镜面转折处即命中；
命中点为`(x,y)=(-0.56926,-64.97622) mm`，位于50x50-mm有效面内并接近`y=-62 mm`中心。
这是当前最短且三维无碰撞的N=1提取Candidate，但尚未做局部电压中心化、束团或步长/网格对照。
随后以`center_precision`重新求得的精确中心根
`20260910_153500__sim__simion__near-target-k-local-root-dt0p00002-n1`为唯一参考，受管run
`20260910_160000__sim__simion__exact-k-rebound-extraction-dt0p00002-n1`在
`773.59367622 us`自动切换到`P1/P2=-59.533/-140 V`，并于`856.910310086 us`命中探测器；
切换后为`83.316633866 us`和5个额外镜面转折，命中`(x,y)=(-0.569330,-60.693342) mm`。
该run同时报告`K-25=+1.04e-8`和慢向折返`y=340.000250717 mm`，只闭合固定1-mm场网格的
中心粒子事件链，不授予网格收敛、束团传输或分辨率资格。
[run_downstream_voltage_definition.ps1](../analysis/run_downstream_voltage_definition.ps1)只读消费一个基点和
四个有序单轴SIMION run，构造缩放4x4 Jacobian并报告秩、零空间、条件数和未阻尼线性修正；它本身
不启动求解器，也不授权执行外推步。当前受管审计为
`20260909_062000__analysis__python__downstream-voltage-definition`：局部满秩但条件数约323，线性修正远超
0.2-V差分邻域，故仍未产生新的下游工作点。

[run_three_component_first_prism_flight.ps1](run_three_component_first_prism_flight.ps1)是独立的N=1首棱镜
接口诊断：它用已审查几何run中的同一三份PA0／PA#、同一合同派生原点，复制并重命名已保存电压的 IOB，
`mrtof_first_prism_l0.iob`，使 IOB basename 与 `mrtof_first_prism_l0.lua`、其 operating-point、voltage-map
及同名4-keV `-z` Fly2一致。重载后重新检查三实例和保存电压，并以字节身份核对该 Fly2 与描述性的
`mrtof_first_prism_entry_center.fly2`。结果只可由`first_prism_l0_result.py`发布
`prototype_first_prism_interface_only`，不代表加速器提取、第二棱镜、K=25、传输、时间焦点或分辨率。
该入口向`run_iob_flight.lua`直接传入 IOB 路径（没有多余的`--`），因为后者的唯一参数就是 IOB。

[run_accelerator_focus_flight.ps1](run_accelerator_focus_flight.ps1)复用同一已审查三实例IOB和只读
加速器PA-family，不会重新refine任何PA。可选`-FirstGapDropV`只建立run-local候选合同：中心提取能量和
释放位置固定时，它自动派生repeller/intermediate及五个第二级环电压；机械坐标始终来自已审查合同，
不会随解析焦距重新布置。随后[voltageize_accelerator_pa0.lua](voltageize_accelerator_pa0.lua)从只读family
执行SIMION原生`pa:fast_adjust()`并另存一个run-local PA0，receipt验证源PA0前后哈希不变且没有refine。
入口再把run-local同名Program换成
[mrtof_accelerator_focus.lua](mrtof_accelerator_focus.lua)，选择中心或轴向束团Fly2，并在离子首次穿过
项目`z=0`时插值记录时间和速度后停止。随后
[accelerator_focus_simion_analysis.py](../analysis/accelerator_focus_simion_analysis.py)将数值时间与独立
`orthogonal_accelerator`一维解析参考逐粒子比较；解析传播距离使用已审查的真实exit-to-`z=0`距离，
而非随候选电压移动的理想焦距。结果报告有限区间时间极差、线性斜率、二次系数和最大解析误差。
该receipt只验证二区加速器的静态首时间焦点，不授予棱镜、Stripe、K=25、探测或分辨率资格。

## 数值执行边界

积分设置由候选合同的具名 `trajectory_profiles` 单向解析；运行入口只选择 profile ID，不接受游离的
时间步数值。默认 `center_screening` 为 `trajectory_quality=8`、`maximum_step_us=0.002`，用于中心粒子
拓扑和电压筛查；`center_refined` (`0.0002 us`) 与 `center_precision` (`0.00002 us`) 只用于同一固定
物理点的事件顺序和连续 K 数值收敛。三者共享同一场网格，不能替代后续三档 PA 网格收敛，也不能把
较细时间步本身当成物理通过证据。更重要的是，已查明一次异常慢飞行的主因不是离子物理 TOF、网格或
`sim_segment_global`：旧 Program 会在**每个积分段**调用 `analyser:fast_adjust()`，反复合成20张
约669 MB的分析器 basis PA。IOB 构建器本已按同一 operating point 执行一次 `fast_adjust → save`；GUI
Fly 正是使用该持久化 PA0。故正式飞行默认 `runtime_fast_adjust_enable=0`，只读取保存的 PA0；若交互式
改电压，必须先重新 Fast Adjust 并保存 PA0，不能在运行段内隐式重算。1-us 原生 profile 在关闭全局回调
时仍为43段、约6.16 s，而在已保存 PA0 上为同43段、约0.00 s，确认根因。
同一规则也适用于独立的`mrtof_first_prism_l0.lua`：其静态单粒子接口诊断不再在每个积分段重合PA family。

分析器空间收敛由
[`analyzer_local_refinement_plan.py`](../analysis/analyzer_local_refinement_plan.py)
从resolved几何派生。当前全域`1/1/1 mm/gu`的22文件family约为`14.72 GB`；直接全域
`0.5/0.5/0.5 mm/gu`估算约`117.28 GB`，不得绕过容量门禁强行生成。局部方案不是两个独立零边界场的
叠加。每个补丁都必须保存完整的8组独立响应（镜B--E、Stripe 1/2、P1/P2），不能因为某电极实体在
补丁外就删掉它的边界响应；连同raw geometry与PA0，两补丁在`1/0.5/0.25 mm`三档合计约为
`0.938/7.405/58.833 GB`。对每个可调电压basis，必须把已验证全局basis插值到局部PA六个面并标为Dirichlet边界，再保留
子域内同一resolved几何进行Refine。Workbench中局部实例优先级高于全局实例，局部场只作替换；所有
接缝的电势与法向场连续性、三档网格和逐档重新求中心电压根均通过后，局部PA才可进入粒子飞行。
局部GEM由
[`analyzer_local_patch_geometry.py`](../analysis/analyzer_local_patch_geometry.py)从同一resolved实体发射并由
PA边界自然裁剪；不得复制或另写一套几何常量。设备无关的电极ID重映射和粗场边界插值分别位于
[`common/simion/remap_pa_electrode_ids.lua`](../../../common/simion/remap_pa_electrode_ids.lua)与
[`common/simion/build_dirichlet_patch_basis.lua`](../../../common/simion/build_dirichlet_patch_basis.lua)。
前者把物理1--20命名空间按合同压缩为8个Fast-Adjust响应组并保留零电势实体，后者用SIMION原生
`potential_vc`在六个面采样粗basis、保留局部实体后执行Refine。二者是构建原语；在受管runner、
容量预检、接缝验证和IOB优先级装配完成前，不能手工生成PA后直接用于性能结论。
[run_analyzer_local_pa_family.ps1](run_analyzer_local_pa_family.ps1)现已闭合受管构建器：它先证明当前
baseline生成的全局GEM与已审查源逐字节相同，再派生局域GEM、完整八响应recipe和公共内容寻址identity；
cache miss才调用SIMION，hit则不Refine。2026-09-10已实际发布中央区与正镜转折区的1-mm及0.5-mm族。
正镜族后续以合同刚体对称变换复用于负镜，不另建第二份几何参数。当前这些run只证明局域basis构建和
缓存发布；IOB重叠优先级、中心根和飞行尚未验证。

[`common/simion/compare_dirichlet_patch_interface.lua`](../../../common/simion/compare_dirichlet_patch_interface.lua)
现按两种采样检查接缝：`matched_lattice`在1 mm与0.5 mm族上使用相同物理坐标，
`native_all_nodes`则遍历各自六个面的全部原生节点。Dirichlet电势只在真空面节点比较；实体面节点由
电极边界条件所有，不能把solution-array的电极/basis编码误当成真空电势。法向场只在面节点及其内侧
相邻节点均为真空时比较，同时分别记录实体面节点和贴近实体而被排除的真空节点。
受管run `20260910_193000__analysis__simion__analyzer-local-interface-convergence`实际检查了96个
region/group/face组合，以及1-mm档`2,531,592`和0.5-mm档`10,206,096`个原生真空面节点；所有
Dirichlet真空节点的最大电势差为`1.4552e-11 V`。但是法向场最大值只有55/96项随细化下降，RMS只有
58/96项下降；最差项位于切过实体或电极边缘的整面，而不是已证明的离子穿越窗口。故当前大盒子不
能通过空间收敛门禁，也不应直接耗费约58.8 GB生成同边界的0.25-mm族。下一步先从冻结中心轨迹与
后续束团包络派生可穿越真空portal，使局域替代边界避开电极边缘；非portal面须由轨迹包含门禁证明
不会被离子穿越。完成该边界重构后才构建第三档并逐网格重新求中心电压根。论文没有给出此数值接口
的接受阈值，因此上述run只作measured Candidate证据，不自行宣布通过。

受管run `20260910_211000__sim__simion__screening-patch-portal-envelope-n1`进一步用现行全局
`1/1/1 mm/gu`场和已闭合的中心注入／K=25／脉冲引出链，逐段插值记录了三个候选局部PA盒子的
全部18个边界面。221次有效穿越只落在4个`z`面：中央补丁`z=-105/+102 mm`分别55/53次，
正镜补丁`z=+97 mm`为55次，反射复用的负镜补丁`z=-97 mm`为58次；所有`x/y`面及两块镜的外侧
`z`面均未穿越。最大横向中心轨迹包络约为`|x|<=0.602 mm`，慢漂移坐标总体覆盖
`y=-113.21--339.99 mm`。这只是一条中心轨迹的portal种子，不能代替后续固定束团的接受包络。

因此活动精化策略保持全局分析器1-mm等长网格作为远场与装配基线，并仅以更高优先级局部PA替换
真实轨迹访问的镜转折区和中央Stripe／棱镜区。两个局部盒在`z`方向各重叠5 mm；实际Workbench
切换面由实例优先级决定，不能把记录到的4个几何边界都误称为4个场切换面。进入IOB之前必须先在
拟定的两个优先级切换面上比较**中央局部场与镜局部场**，而不只分别与全局场比较；同时用固定束团
扩张portal并证明其余边界未被接受粒子穿越。若0.5-mm结果仍不收敛，第三档只细化这些高梯度局部
PA或增加一个覆盖接缝的真空portal补丁，不改变resolved机械几何，也不把整个14.72-GB全域缩到
0.25 mm。

后续局部—局部portal比较还发现并修正了一个先于网格判断的构建缺陷：SIMION全局solution basis的
实际激励由源PA给出，当前为`10000 V`；旧局部构建器却把局部实体电极写成`1 V`，同时原样复制
`10000 V`尺度的Dirichlet边界。故先前四个局部族及其`20260910_193000`整面场比较不能再作为空间
收敛证据。公共构建器现在逐源PA读取并交叉核对非零实体basis电压，不再硬编码归一化；修复后的
1/0.5-mm中央和镜族分别由受管run
`20260910_223000__build__simion__analyzer-local-central-1mm-normalized`、
`20260910_224000__build__simion__analyzer-local-mirror-1mm-normalized`、
`20260910_225000__build__simion__analyzer-local-central-0p5mm-normalized`和
`20260910_230000__build__simion__analyzer-local-mirror-0p5mm-normalized`重新生成并以新源码哈希发布缓存。

受管run `20260911_013000__analysis__simion__analyzer-local-portal-interface-weighted-r05`随后在两个实际
优先级候选切换面、32个basis/scale/seam组合上比较中央局部场与镜局部场。basis归一化由每档raw PA
的真实活动电极节点测得为`10000 V`，再以冻结注入工作点的8组电压作逐样点线性组合。1-mm档的最大
工作点电势差／法向场差为`0.1201 V / 0.7203 V/mm`；0.5-mm档为
`0.3189 V / 0.3430 V/mm`。法向场差下降约一半，但电势差不单调，因此0.5 mm尚不能宣称足够，
也不能用同盒0.25-mm蛮力构建推断会闭合。下一步优先设计同时包含Stripe端部和镜内侧实体的专用
接缝PA，把它与中央／镜局部PA的边界移到低梯度真空区；仍须用固定束团扩张portal并执行第三档对照。
上述工作点组合使用注入态P1/P2；脉冲引出态须在同一basis上另行组合检查。

后续按同一resolved几何新增了覆盖Stripe端部到内镜A/B间隙的局域桥接PA；全局分析器仍保持
`1/1/1 mm/gu`。正、负z桥接区必须分别构建：镜与Stripe自身可对称，但两只离轴棱镜破坏了整个
分析器关于z的可复用性。直接把正侧桥接PA反射到负侧时，运行
`20260911_044500__analysis__simion__analyzer-local-bridge-interface-r05`在负侧测得约
`20.94 V / 5.70 V/mm`的工作点不连续；分别构建负侧后，边界误差降至与正侧同量级。

局域PA不在自己的Dirichlet外边界切换。合同从相邻盒子的真重叠区自动计算四个切换面：
`z=-72,+72,-131,+131 mm`。中心轨迹run
`20260911_070000__sim__simion__overlap-handoff-envelope-n1`证明四面均被穿越且未触及x/y边界；
`20260911_073000__analysis__simion__analyzer-local-overlap-interface-r05`随后完成64个
basis/scale/seam比较。0.5-mm工作点的最大电势差为`0.01654 V`，最大法向场差为
`0.003503 V/mm`；中央—桥接两面更低至约`1.52e-6 V / 9.30e-7 V/mm`。这是中心粒子
Candidate接口证据，不是束团或分辨率验收。下一步用显式`instance_adjust`按这四个面选择局域实例，
再运行中心粒子和冻结小束团；0.25-mm只在束团接口或飞行收敛仍不够时构建。

修复后的实际中心粒子全装配 Fly 已在约0.06 s终止并完成事件对账；它在 `t=333.722473491 us`、
`z=-97.0000004 mm`、`y=0.515455 mm` 时以 electrode collision (`splat=-1`) 损失，仅记录24次转折
（overtone `K=12`），没有探测命中或 K=25。因此性能问题已经解除，但当前静态 Candidate 的几何/注入/
棱镜传输仍未闭合；不得从该运行报告 TOF 峰宽或质量分辨率。

后续必须将“中心粒子事件链贯通”的宽松数值profile和“步长／网格三档收敛”的严格profile作为
不同冻结run：前者只确认事件序列、碰撞和接口，不报告分辨率；后者固定物理和源后才比较误差。
不得用宽松profile的TOF或峰宽替代严格profile结果，也不得修改已启动run的合同或把运行时长归因于
镜、Stripe或棱镜物理。

先关闭上述接口，再按中心粒子→冻结小束团执行受控飞行。不得由GEM编译、PA生成、IOB加载或统计脚本
PASS推断双Stripe返回、25圈目标比例、探测率、第一时间焦点或质量分辨率；更不能据此声明Formal。

## 官方支持路径

2026-09-03核对的官方依据包括
[simion.wb API](https://simion.com/info/lua_simion.wb.html)、
[simion.pas API](https://simion.com/info/lua_simion.pas.html)和
[SIMION编程API的命令行入口](https://simion.com/info/api.html#command-line-interface)。
在线页面目前描述较新版本，完整接口说明应与本机SIMION 2020的Help／Supplemental Documentation交叉核对。
动态棱镜路径另核对了官方[time-dependent fields](https://simion.com/info/time_dependent_field.html)、
[PA types](https://simion.com/info/potential_array_types.html)和[FAQ](https://simion.com/info/faq.html)：
`segment.fast_adjust`是脉冲电压的支持路径，回调只依赖当前保留变量，且数值步长必须解析切换时刻。
本项目仍以本机SIMION 2020实际N=1运行作为版本适用证据。

本机官方示例相对于SIMION 2020安装目录为：
`examples/geometry/parallel_plate_capacitor_2d.gem`（节点对齐理想栅）、
`examples/collision_hs1/make.lua`（`pa:potential` setter及PA保存）、
`examples/field_dump/field_dump.lua`和`fielddumplib.lua`（场读取）。
本项目以这些官方接口实现几何／零电压掩码处理；示例本身不证明本项目三维场、原生检测或飞行已经验证。
