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
|独立屏蔽二区加速器|`mrtof_accelerator.pa0`|`2,2,2`|局部`pa1..pa9`|
|独立数值终止平板|`mrtof_detector.pa#`|`1,1,1`|无Refine、无PA0、无basis|

分析器basis使用从1到最大ID20的完整命名空间；未使用ID19的零响应数组不是新增物理电极。
SIMION 2020会拒绝对不存在的ID执行Refine。构建器先扫描原始ID；对范围内的编号空缺以官方
`pa:potential` setter生成严格全零响应、保留材料掩码并保存为对应PA文件，存在的ID仍按默认Refine求解。
禁止请求高于物理最大ID的数组，不能为补齐编号增加虚构实体。
主分析器为`x/y/z=1/1/1 mm/gu`：CAD固定的30-mm镜束槽（边界`x=±15 mm`）与4-mm Stripe／接地／棱镜屏蔽槽（边界`x=±2 mm`）在同一个2-mm网格相位中不可同时精确表示，故`x=1 mm`是几何审查的硬约束；`z=1 mm`也使CAD给定的2-mm grounded-1—镜盖板净距包含真空节点。几何包络与孔槽不变。独立加速器当前为`2/2/2 mm/gu`，只服务GUI几何／电压复核；焦点、边缘场、时间与分辨率结论必须使用另一个显式的加密加速器运行包和网格收敛对照。
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

materializer在schema2的`prototype_input_manifest.json`中为五份Fly2分别冻结
`particle_count`、`particle_count_contract_key`、`expected_particle_ids`及其SHA-256，
并绑定Fly2和derived合同的SHA-256。ID由单个standard beam的合同粒子数派生为`1..N`；
分析不能从已记录终态数反推母粒子数。

|manifest source key|生成的Fly2|当前用途|
|---|---|---|
|`center_fly2`|`mrtof_candidate_center.fly2`|分析器内直接释放的4-keV中心粒子|
|`candidate_bunch_fly2`|`mrtof_candidate.fly2`|同一注入态的固定合同小束团|
|`accelerator_focus_center_fly2`|`mrtof_accelerator_focus_center.fly2`|第一区release平面的零KE中心粒子|
|`accelerator_focus_bunch_fly2`|`mrtof_accelerator_focus.fly2`|同一release平面的零KE横向小束团|
|`first_prism_entry_center_fly2`|`mrtof_first_prism_entry_center.fly2`|两区焦面处的4-keV中心粒子；仅首棱镜有限三维射击诊断|

当前首轮物种为524 Th／+1，中心源N=1、小束团N=100、半径0.1 mm；数值只来自`particle_source`合同。
此前100 Th输入仍属独立回归/历史证据，不与新首轮束团混合统计。
前两种是加速器后的理想注入假设，不是从repeller开始的提取证据。后两种可用于加速器穿越诊断，
但仍是静态电压下的释放，且圆盘不扰动提取方向的初始位置，不能单独证明第一焦点导数。
五种源不能合并统计或彼此替代。

有实际飞行日志后，从仓库根使用[simion_event_analysis.py](../analysis/simion_event_analysis.py)：

```powershell
python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis `
  '<run>/stdout.log' '<run>/event_analysis.json' `
  --input-manifest '<run>/simion/prototype_input_manifest.json' `
  --source-key candidate_bunch_fly2
```

路径应指向本次实际冻结文件；`--source-key`必须与实际飞行源相符。目标K只从已校验的derived合同读取，
不再接受独立`--target-k`默认值。源文件／合同身份改变、无唯一Fly完成记录、完成计数不符、
缺失／重复／未知粒子ID或截断事件都会拒绝PASS。保留原始诊断计数与到达时间，完整性失败时
检测率、目标K比例、FWHM和分辨率为`null`，CLI返回`FAIL/1`；只有完整性通过才返回`PASS/0`。
旧schema日志只能只读诊断，不能通过补造新source manifest恢复当前运行资格。

## 尚未闭合的飞行接口

当前[mrtof_candidate.lua](mrtof_candidate.lua)仍有以下物理限制，事件完整性PASS并不消除它们：

- 第50次任意`vz`变号会主动截停，`K=25`目前是镜内存活诊断，不是完整引出／探测；
  `target_k_handoff_tof`记录点实际为转折点，不能称为中央面或检测器TOF。
- 棱镜16（路径 P1）现在接收由冻结`prism_transport` L0硬边界关系派生的**静态初值**；棱镜17
  （路径 P2）为 `pre_stripe_injection_pending` 的审查用`0 V`。两者均在 Stripe 前；该初值尚未经
  有限三维单位场/轨迹射击，也没有双程棱镜事件；
  加速器同样未实现脉冲时序与源时钟闭合。
- Lua已按合同改在探测器`+z`外表面接收沿`-z`入射，保留初始步并对中央面采用半开区间和插值；
  纯Lua回归通过，但实际平板终止与检测事件的对应仍待全装配飞行复核。
- `sim_segment_global=1`已启用。SIMION 2020（8.2.0.11）同一N=2原生生命周期回归确认：关闭时仅记录PA内
  粒子终止，开启后PA内与PA外各一个粒子均有终态；不需`early_access`。这不代替旧漏记录束团的重新飞行。
- [run_iob_flight.lua](run_iob_flight.lua)要求IOB同名的Lua、Fly2和operating-point sidecar。
  [run_three_component_center_flight.ps1](run_three_component_center_flight.ps1)是唯一的N=1中心粒子入口：
  它从一个已完成的三组件几何审查run逐字节冻结IOB、三份已加载PA、结构报告、source manifest及
  `center_fly2`，并拒绝IOB重命名的Fly2与该选定源字节不一致。它只发布全终态事件链的
  `candidate_prototype_event_chain_only` receipt；不运行束团、不产生分辨率结论，也不修改源几何审查run。

[run_three_component_first_prism_flight.ps1](run_three_component_first_prism_flight.ps1)是独立的N=1首棱镜
接口诊断：它用已审查几何run中的同一三份PA0／PA#、同一合同派生原点，复制并重命名已保存电压的 IOB，
`mrtof_first_prism_l0.iob`，使 IOB basename 与 `mrtof_first_prism_l0.lua`、其 operating-point、voltage-map
及同名4-keV `-z` Fly2一致。重载后重新检查三实例和保存电压，并以字节身份核对该 Fly2 与描述性的
`mrtof_first_prism_entry_center.fly2`。结果只可由`first_prism_l0_result.py`发布
`prototype_first_prism_interface_only`，不代表加速器提取、第二棱镜、K=25、传输、时间焦点或分辨率。
该入口向`run_iob_flight.lua`直接传入 IOB 路径（没有多余的`--`），因为后者的唯一参数就是 IOB。

## 数值执行边界

`trajectory_quality=8`和`maximum_step_us=0.002`是当前冻结工作点的高精度数值设置，而不是首轮
功能链的合理吞吐设置。更重要的是，已查明一次异常慢飞行的主因不是离子物理 TOF、网格或
`sim_segment_global`：旧 Program 会在**每个积分段**调用 `analyser:fast_adjust()`，反复合成20张
约669 MB的分析器 basis PA。IOB 构建器本已按同一 operating point 执行一次 `fast_adjust → save`；GUI
Fly 正是使用该持久化 PA0。故正式飞行默认 `runtime_fast_adjust_enable=0`，只读取保存的 PA0；若交互式
改电压，必须先重新 Fast Adjust 并保存 PA0，不能在运行段内隐式重算。1-us 原生 profile 在关闭全局回调
时仍为43段、约6.16 s，而在已保存 PA0 上为同43段、约0.00 s，确认根因。
同一规则也适用于独立的`mrtof_first_prism_l0.lua`：其静态单粒子接口诊断不再在每个积分段重合PA family。

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

本机官方示例相对于SIMION 2020安装目录为：
`examples/geometry/parallel_plate_capacitor_2d.gem`（节点对齐理想栅）、
`examples/collision_hs1/make.lua`（`pa:potential` setter及PA保存）、
`examples/field_dump/field_dump.lua`和`fielddumplib.lua`（场读取）。
本项目以这些官方接口实现几何／零电压掩码处理；示例本身不证明本项目三维场、原生检测或飞行已经验证。
