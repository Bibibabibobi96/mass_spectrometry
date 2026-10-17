# MR-TOF SIMION 实施说明

本页说明 SIMION 入口、输入和独立验收；当前工作点、资格、运行证据及开放任务见
[项目状态](../docs/PROJECT.md)，其他软件入口见[项目导航](../README.md)。
输入版本见[输入权威](../docs/PROJECT.md#输入权威与物理定义)，当前执行顺序见
[开放动作与关闭条件](../docs/PROJECT.md#开放动作与关闭条件)。
命令从仓库根 `simulation_repo/` 执行；尖括号为必须替换的占位路径。
工具版本、商业执行及资源准入统一遵守[操作指南](../../../docs/OPERATIONS.md)。

## 按任务查阅

| 任务 | 本页入口 |
|---|---|
| 确认几何、坐标与组件责任 | [输入与装配](#输入与装配) |
| 选择 native 或 COMSOL 场消费 | [场输入与碰撞](#场输入与碰撞) |
| 构建 native bank、重载 IOB 或保留 GUI | [构建与独立验收](#构建与独立验收) |
| 发布源、完整飞行和 P/S 调节 | [源与运行入口](#源与运行入口) |
| 断点续接或 N>1 批次恢复 | [恢复与资源](#恢复与资源) |
| 解释返回、碰撞及峰宽结果 | [事件与分析](#事件与分析) |
| 追溯旧工作台、结果和迁移过程 | [历史与来源](#历史与来源) |

## 输入与装配

### 加速器选择与接口准备

独立的准备入口为[run_prepare_accelerator_interface.ps1](../analysis/run_prepare_accelerator_interface.ps1)。
`-AcceleratorProvider orthogonal_accelerator`保留默认OA需求准备；
`-AcceleratorProvider dual_pressure_rectilinear_ion_processor`选择IP的实测出口和MR匹配需求。
选择映射由[accelerator_interfaces.json](../config/accelerator_interfaces.json)拥有，
不会改写既有OA运行器的默认值。两条初始准备路径均不启动求场或联合飞行。

```powershell
# 两者共用一个入口；ReferenceMrRunPath必须是所选MR工作点的原始封存run目录。
& ./projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_prepare_accelerator_interface.ps1 `
  -AcceleratorProvider orthogonal_accelerator -ReferenceMrRunPath '<reference-MR-run>'
& ./projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_prepare_accelerator_interface.ps1 `
  -AcceleratorProvider dual_pressure_rectilinear_ion_processor `
  -ReferenceMrRunPath '<reference-MR-run>' -IonProcessorRunPath '<successful-IP-run>'
```

IP路径由版本化[依赖](../config/ion_processor_dependency.json)冻结producer代码与实际源身份，
使用公共component_particle_state v1保留逐ID六维状态、仪器绝对时间、谱系和完整母群census。
刚体变换只改变位置／frame，速度、能量和到达时间不重新归一或清零。
[MR匹配需求](../config/ion_processor_matching_request.json)从所选冻结MR运行读取实际轴向出口能量与注入位置，
允许IP调节原生电压、几何和时序；修改后必须重新求场／实测验收，不在导入CSV中补加能量。

输出`results/accelerator_interface_preparation.json`、IP分支的`results/mrtof_handoff/`及`results/joint_flight/`供审阅。
后者包括`measured_source/`的17位FLY2、逐ID映射和时钟收据，`assembly/`的新GEM／数值场计划及器件候选配置，
`runtime/`的实测源程序、operating-point模板、优先级和`workbench_build.lua`装配请求。
`provider_execution_recipe.json`指向原IP的`run_functional.ps1 -ConfigurationDirectory`，后续可通过原公共调度器
自动并发验证候选N100，参数和默认基线隔离。准备阶段仅以SIMION 2020附带的普通`lua.exe`计算原电压时序，不调用求解器。

`build_native_corridor_iob.lua --measured-source <workbench_build.lua>`实现IP的四个角色
`global_fallback → native_corridor → ion_processor_collision → detector`；旧OA四角色协议保持。
独立IP细碰撞PA避免0.5/1/1 mm背景网格漏掉薄辅助电极；细网格0.05/0.10/0.05 mm覆盖完整15电极。
场输入必须全部来自替换OA后的新装配，不能混用旧OA的父场、中央层或镜边界。
全域碰撞GEM保留金属，移除数值边界接地面；网格表达不等于数值收敛资格。
模板的`field_assembly_verified`、`measured_source_matches_workpoint`为false，装配器与运行程序均拒绝提前执行。
先以候选配置重新求场／验证IP出口，再发布新的实测交接源，并求解封存全部新场和核验IOB重载优先级后，方可绑定真实资产。
初始模板`solver_ready=false`表示尚未绑定物理资产。已有新实测N100与新场后，沿同一入口执行：

```powershell
& ./projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_prepare_accelerator_interface.ps1 `
  -FinalizeJointWorkbench -AcceleratorProvider dual_pressure_rectilinear_ion_processor `
  -PreparedInterfaceRunPath '<prepared-design-run>' -JointFieldRunPath '<new-IP-assembly-field-run>' `
  -IonProcessorRunPath '<new-successful-IP-run>' -ReferenceMrRunPath '<same-reference-MR-run>'
```

该模式重新导出实测源、绑定全部新PA，调用SIMION CLI保存／重载IOB并检查三处实际重叠优先级；不执行Fly。
它保留原设计电压，不从新出口再次自动派生抬升。配置／场身份检查不代表能量或时间聚焦验收。
用户要求只报告能量差，`centroid_match_accepted=null`，六维匹配与时间聚焦均不赋予资格。

同一公共`run_native_static_field_provider.ps1`还接受ordinary IP细窗下游扩域请求：
在既有schema 1 provider request中声明
`reuse_source_levels=["parent","window_1","window_2","window_3"]`及
`ion_processor_local_domain_update={"solve_z_min_mm":-20,"active_z_min_mm":-10}`。
源必须是完整封存的ordinary IP候选；该模式禁止电压、响应库、几何、镜场或消费裁剪修改，
仅将IP细窗solve／active的z下界向下扩展，其余坐标、网格间距、优先级与停止条件保持原值。
新run只构建细场及同域IP碰撞PA，其余四层、普通碰撞及detector保持原owner和路径。
`local_domain_update`封存输入记录精确源binding与父manifest，加载器递归验证全部复用身份。
归一化binding的`manifest`仍是父PA owner，`descriptor_owner`则标识本次新细场／binding owner；
后续普通provider请求使用后者作为`source_field_manifest`。这是数值边界因果试验，
不授予连续捕获、接口一致性或匹配资格；新场须重新finalize准备baseline和IOB，再做受控验证。

扩域ordinary场所需的P1/P2纯响应可由同一provider仅重建fine：请求保留扩域ordinary的
`source_binding_path`、`source_field_manifest`和数值合同，声明`response_axis="p1"`或`"p2"`、
`reuse_response_basis_path="<原同轴完整response_basis.json>"`及上述四层`reuse_source_levels`。
该模式拒绝S1、候选电压、几何或额外域更改；先按旧bank自身来源严格验证，再核对复用四层的
几何、完整求解网格、父链、实际停止条件和全部纯激励电压。新fine以旧纯响应parent作Dirichlet边界，
其余四层保持旧owner；碰撞资产继承扩域ordinary场，不重建碰撞PA。新basis的source authority来自
扩域ordinary，`response_level_reuse`由新fine owner封存；最终仍须通过完整算子校验，且禁止直接Fly。
联合实测源飞行复用`run_two_prism_trial.ps1`，通过独立参数组消费已完成的联合准备包；OA旧参数组默认不变：

```powershell
& ./projects/parallel_mirror_dual_stripe_mr_tof/simion/run_two_prism_trial.ps1 `
  -PreparedJointWorkbenchRunPath '<completed-joint-workbench-preparation-run>' `
  -ContractPath '<same-frozen-trajectory-contract-with-explicit-recording>' -RunId '<new-run-id>'
```

该参数组允许增加轨迹观测配置，或通过原预算校验器显式增大累计候选上限；其余物理／数值字段必须一致。
准备收据分别记录原准备合同和实际执行合同身份，不能同时改变源、场、电压或积分设置。公共调度器先观测正式首批，再自动重规划；
每批独立FLY2和局部序号共享原instrument epoch，输出保留原始ID，合并不施加OA offset。
镜场可按冻结数值合同已有`stored_xmax_mm`派生显式`memory_consumer_crop`；源PA完整尺寸、
消费尺寸及完整插值halo均记录在本次收据。使用官方`pa:crop(...,false)`仅裁进程内的非Workbench镜场对象，
保留原active box、原点、实际pitch及fractional表面，不保存或Refine源PA；二次加载须复用裁后对象。
该消费范围不成为新的求解边界。指定`-TrajectoryEquivalenceReferenceRunPath`时，冻结已验证参考运行的首批记录，
在终态前比较同ID的全部事件和轨迹观测；这是消费表示验证，不代表Prism物理匹配。
依据为[官方PA API兼容记录](https://simion.com/info/lua_simion.pas.html)的8.1.1.22起crop表面信息保留／persist参数，
及本项目已实测的`crop_native_static_field.lua`路径（SIMION 2020，2026-10-16查阅）；不采用较新版本专有能力。
完整母群包括上游未交接粒子，不能用交接数替代初始母群分母。默认后处理产生Prism相空间、
自动分时空间云、母群与损失图及逐损失原始行证据；没有到达某观察面时报告缺失，不补造轨迹。
候选场重建的builder从独立`measured_source/source.fly2`读取粒子定义，在保存IOB后恢复运行用`joint.fly2`，
避免`wb:save`以种子定义覆写同名文件。原批次合并收据绑定实际Fly使用的FLY2、逐批收据、日志及完整ID覆盖；
默认诊断沿该收据验证逐粒子出生时间，只在内存中组合发射证据，不改写已冻结的准备输入。

IP分支采用`state_handoff`，继承实测六维状态和到达时刻，后段采用RF为零、提取脉冲保持的静态装配场。
这不是同一Fly内连续积分捕获／冷却到MR。分析入口为`measured_component_analysis.analyze_measured_component`，
以原始ID和全部母群闭合；不能再套OA批次offset恢复ID。z=0观察面不自动作为接地端口或时间焦点。

更换实测源或数值场后，源专属工程目标可由`measured_component_source.author_measured_centroid_prism_target`
消费已核验的同场birth／clean电势审计及控制投影，保留MR设计Ws并用原L0模型自洽反解fast／slow参考。
它显式扣除实际clean电势和x动能，沿原resolver重算角容差映射；只生成一个新目标版本及作者账本，
不改源、移动候选目标或另建闭合器。调用方须冻结输入与输出，清除旧目标列，并沿原入口导入新版本。

已发布的独立质心N1可作为原P→Stripe/phase→P复核→完整返回流程的实际锚点，入口仍为
`analysis/run_downstream_workpoint_iteration.ps1`。`-PreparedFieldBuildMode composition`为默认方式，
使用同算子的P1/P2响应；需要S1列而未提供S1响应时保存`needs_s1_response`检查点。
明确选择`refine`时，每个新候选沿同一公共`run_native_static_field_provider.ps1`完整求场，
不依赖额外S1响应；五层IP网格、15路IP工作点、固定MR电压和原数值身份仍须匹配。
它保留原实测质心的六维状态与时钟，不重飞输入锚点、不重采样原97粒子，不改变P/S残差或S2接地约束。

```powershell
& ./projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_downstream_workpoint_iteration.ps1 `
  -PreparedJointWorkbenchRunPath '<audited-prepared-IP-run>' `
  -PreparedPrism1ResponseBasisPath '<sealed-P1-response-descriptor>' `
  -PreparedPrism2ResponseBasisPath '<sealed-P2-response-descriptor>' `
  -PreparedInitialProposalPath '<frozen-initial-proposal.json>' `
  -PreparedTargetAuthorityPath '<explicit-design-target-authority.json>' `
  -PreparedSeedTrialManifest '<actual-N1-anchor-run_manifest.json>' `
  -PreparedFieldBuildMode refine -ContractPath '<same-frozen-trajectory-contract>' -RunId '<new-parent-run-id>'
```

续接同一目标时，在上述原入口增加`-ResumeParentCheckpoint '<sealed-parent-run>'`并使用新`RunId`；
它复用原分阶段检查点恢复，严格保持源、目标、数值合同、P响应及控制policy身份，保留已测列与预算。
若只增加执行候选总预算，可给`ContractPath`提供新封存合同，仅增加
`downstream_fixed_grid_workpoint_profile.automatic_iteration.maximum_iterations`；其他字段逐项必须相同，
advance、可信步长上限及物理容差不变。原目标作者及其轨迹合同SHA继续作为科学身份，
实际消费的执行合同与历史子运行原合同分别记录真实SHA；新parent冻结前后合同与变更收据，
继承累计candidate_count、history、pending与lineage，预算不会因新RunId清零。
新值是全链累计候选上限，不是额外候选数，也不授予收敛或N100资格。
修正慢转折目标时，显式增加`-PreparedTargetReanchor`，并提供新封存的
`PreparedTargetAuthorityPath`及旧lineage中成功子运行的`PreparedSeedTrialManifest`。
仅允许目标的`target_slow_turn_y_mm`改变；源、能量参考、数值、响应及policy身份保持。
入口先以旧目标核验完整旧历史，再沿原重锚函数清除响应列和预测，从所选锚点重新检查P阶段；
累计候选／飞行计划及旧历史保留。未执行的pending仅在原parent已封存中断、写入进程结束且
trial目录不存在时可显式放弃，并保存原计划和计数证据；已经创建的trial不能据此放弃。
同一lineage仅允许一次显式重锚，后续仍使用普通resume，以免覆盖已封存的弃飞计数证据。
原parent未声明Prism policy时，可在新parent显式传入`-PrismControllerPolicyPath`
指向未改动的`config/prism_controller_policy.json`；仅允许P阶段且没有pending trial时采用，
已声明policy须保持原SHA，不允许替换或撤销。先严格验证旧检查点，再将旧列、局部模型和预测缓存
记入`iteration_prism_policy_adoption.json`并清当前缓存；anchor、stage、step_factor及全部历史、lineage和累计预算保留。
恢复入口完成该转换后只发布一次完整检查点，后续重新测量两P列；原coarse上限、实测模型边界和预测质量门保持。
未显式传入policy时继续原行为；该采用过程不重解释旧决策，也不改科学输入或目标身份。
实际子运行完成后的身份／预测校验通过`iteration_prediction_input_<flight>.json`传递完整决策，
Python先核对冻结字节数与SHA再执行原校验，避免完整几何使Windows命令行超长；该文件随原检查点封存。
允许补入同算子的`PreparedStripe1ResponseBasisPath`；源／目标改变必须重新建立列。
已封存成功的pending子运行直接消费，不重飞；failed／interrupted子运行沿新身份重新飞行，
若其独立provider已成功且原电压／算子／数值仍严格匹配，则复用该完整场，未完成场不得消费。
历史列只读取封存的normalized投影，不因其PA已经合法退役而重建重型场。

场构建选择及完整候选请求模板进入本次冻结输入；`refine`请求移除响应组合、纯响应、复用层和消费视图指令，
仍由公共provider编译完整四电压候选并执行原GEM／Refine流程，不创建其他求场器。
不得同时声明`PreparedStripe1ResponseBasisPath`。公共容量准入和所有保留条件继续生效，
不能因少存一套响应而推定完整求场峰值一定可容纳。已消费且无未来场／GUI用途的中间候选，
按真实`compose`或`refine`身份沿原公共owner退役；准入、依赖或活动TTL拒绝时保存容量／生命周期检查点，
保留原保护与原始轨迹证据，不私自删除PA。最终完整闭合与N100验证仍为后续独立资格步骤。

官方接口依据（Pulsar Physics，SIMION在线说明／2020附带Lua，2026-10-16查阅）：
[Time](https://simion.com/info/time.html)定义TOB、绝对TOF及粒子年龄；
[User Programming Tricks](https://simion.com/docs/advanced_class/11-user_programming_tricks.pdf)的保留变量表限制TOF写入阶段。
本实现以FLY2保留逐离子TOB，在initialize只设置支持的初态／TOB，不写TOF；普通Lua回调测试不替代SIMION真实载入验收。
Workbench实际API沿现有装配入口复用，实际新包的重载证据按具名run收据查询。
实测源helper只接受显式ordinal并返回初态，保留变量的读写在Workbench的`segment.initialize`中执行；
普通`loadfile`模块不能假设继承Workbench环境。官方[Lua Variables](https://simion.com/info/lua_scope.html)说明环境隔离，
[变更记录](https://simion.com/info/changes.html)的8.0.4手册L-31条及本机SIMION 2020
`examples/collision_hs1/README.html`、`test2.lua`区分`simion.import`与普通加载（2026-10-16查阅）。
这里采用显式参数的纯数据模块，不让普通模块直接读写`ion_*`；在线页的较新标题不扩展为新版功能资格。

普通PA长度依据SIMION 2020安装包官方`lib/python/SIMION/PA.py`的load/save实现核对（Pulsar Physics，
2026-10-16查阅）：单位网格mode −1使用32字节头，非单位网格mode −2另存三个double间距，头长56字节。
场编译器据此预测节点载荷长度，保留严格长度核验；不因检测器单位网格而放宽格式检查。

[候选合同](../config/simion_candidate_two_zone.json)提供 MR 物理输入和机械约束，
[resolved_geometry.py](../analysis/resolved_geometry.py)生成求解器无关的毫米几何；
[native_system_geometry.py](../analysis/native_system_geometry.py)及
[native_corridor_geometry.py](../analysis/native_corridor_geometry.py)只派生 SIMION 副本。
GEM、PA、IOB 和 GUI 不持有下一轮可调几何真值；旧 PA 不因源码修复自动恢复有效性。

坐标固定为 `z` 快速反射、`y` 慢漂移、`x` 横向聚焦。`z=0` 是中央注入／第一时间焦点
交接面，不代表最终质量焦点或必然的空间束腰。活动完整返回使用静态 P1/P2 和关于
`z=0` 的非重合镜像去回程；离子在 `z>0` 沿 `-z` 命中朝 `+z` 的探测面。
首次安全离开加速器后禁止重入；回程不进入 P1，不切换棱镜电压。

四块 Stripe 的物理电压分组为 `(11,12)→S1`、`(13,14)→S2`，曲线来自合同 B-spline。
Stripe、中央接地件和棱镜屏蔽由完整实体扣除有限槽，保留真实端部连接材料；
不能另加桥接盒或因离散化改变孔槽。接地件使用物理 ID18/20，旧拆分 ID19/21 已退役。
`geometry_receipt` 绑定 resolved 几何、单位、坐标、电极 ID 和孔槽。

加速器局部理论、几何、PA 和电压由独立 OA provider 拥有；MR 通过
[accelerator_dependency.json](../config/accelerator_dependency.json)及
[run_accelerator_component_provider.ps1](run_accelerator_component_provider.ps1)消费统一
`mrtof_runtime_receipt.json`。出口、grid1、repeller 沿更大的 `+z` 排列，出射沿项目 `-z`。
OA PA 以 `x=0` 为镜像面，只存半域；实例原点必须保留镜像面，重载检查 `3dplanar[x]`。

`-AcceleratorProviderReceiptPath`传OA发布run的`results/mrtof_runtime_receipt.json`，
不是某次MR飞行`simion/`中的冻结副本：入口由收据位置定位原owner的manifest、plan及resolved campaign。
两份收据即使字节相同，也不能把MR副本的目录身份当成OA owner；子运行自行冻结消费副本。
`-BunchSourceReceiptPath`同样传原源发布run的receipt，绑定其CSV/Fly2；不传其他飞行中的收据副本。

加速器全局 y 由 `accelerator.focus_y_anchor.project_y_mm` 决定。装配读取 provider 的
实际 PA 原点及实体包络，并与 resolved Prism2 屏蔽件、Stripe 检查净间隙；
数值 PA 包络可为优先级而重叠，导体实体不得相交。位姿不属于独立 PA 的生成输入时，
只新建飞行身份并重新评估残差，不据此重建 corridor family。

## 场输入与碰撞

完整飞行复用四个 Workbench 角色，优先级为
`global_fallback → native_corridor → accelerator → detector`。
保存后必须重载并用实际重叠区 `wb:find_at` 检查，不能只相信合同表或显示顺序。

| 消费方式 | 场的来源 | 输入与限制 |
|---|---|---|
| native Fast Adjust | 已发布全走廊 response-bank，加独立 OA/detector PA | `-NativeCorridorBankRunPath` 与 `-NativeSystemRuntimeBundlePath` 配套；电压表按实际 bank 通道映射 |
| native 静态父／局域 PA | 固定工作电压的原生 Refine 场，通过有序局窗消费 | `-FieldBindingPath`；完整数值身份与独立碰撞角色绑定，不能对已裁剪 PA 重求原问题 |
| COMSOL 标量场 | 已封存标量 V、valid mask 及有序局窗，通过原生 `field_array` 消费 | `-FieldBindingPath`；完整电压、几何、网格及装配身份必须相符，不可只改 Fast Adjust 代替更新外场 |

native 路径中 corridor 承担可调分析器场，global fallback 提供低优先级完整几何。
COMSOL 路径使用独立碰撞 PA；其电极标签、Workbench 场查询和事件 `ion_volts`
不代表实际 COMSOL 电势。外场、碰撞几何和 detector 命中必须分别验证。

原生静态 provider 请求通过 `numerical_contract_path` 引用实际数值合同；停止值唯一来自
`simion.numerical_profiles.native_static_field.refine.convergence_v`，父场与局域场各执行一次 Refine。
加载、封存投影及同电压复用同时核对该数值身份；改变停止配置不能继续静默复用旧默认 PA。
当前接线与数值资格分别见 PROJECT，配置可执行不代表其精度已经验证。

历史算子祖先与当前实际消费PA分开验证：只有已完成、精确匹配公共退役收据且受原manifest绑定的历史标量／surface允许缺席。
读取器保留其原封存identity、几何、电压和完整算子来源；当前运行真正加载的PA仍逐项核验，不能用历史退役收据豁免。
历史binding原件及run-local冻结副本分别按各自实际owner的inputs／outputs封存记录校验bytes与SHA，随后要求完整JSON字典等价；
CRLF／LF等序列化差异须先通过各自字节身份，再比较完整JSON；不能冒用另一文件的record，也不能忽略身份。
该来源校验已完成真实退役后严格复验，算子及种子frozen_problem身份保持；后续运行manifest冻结所消费的来源投影。
这只维持非活动算子祖先的可追溯性；引用已退役PA的历史IOB须重新物化，不能据此宣称仍可直接重放。

探测器 GEM 使用 ID25 建立物质掩码；[build_component_pa.lua](build_component_pa.lua)
在 `INITIALIZE=0` 时置零电势并保留电极标志，不把 ID25 当成 25 V。
该数值终止面不等同于已验证的物理探测器，原生终止与事件面须逐次核对。

### COMSOL 标量、响应组合与固定点物化

本机当前会聚镜的普通冻结标量消费已通过真实N13与省略S参数的N1；这只证明该输入／消费链可运行，
不代表空间闭合、FEM收敛或束团性能。对应证据见[受控N13][scalar-n13]、[冻结场自动S的N1][scalar-n1]；
旧mesh3的响应/provider试验不能代替当前会聚mesh1/mesh2资格。
以下模块及runner接线随项目源码统一纳管；实际运行还须具备显式冻结的本机场资产。
复用命令前按冻结候选确认资产、模块和实际参数，不从源码可用推定物理资格。
`analysis/static_field_binding.py`解析已封存场，`simion/scalar_field_adapter.lua`只在有效支撑内查询。
局窗按有序列表、包含边界、首个匹配窗口接管；必须保留梯度支撑 halo。
窗内未知值不回退基场、不补零；覆盖越界、未知 mask 或非有限值是数值失败。

普通`-FieldBindingPath`消费以冻结场的完整电压为权威；省略`-Stripe1VoltageV/-Stripe2VoltageV`时，
当前工作区入口先取该场的S值，再检查接地线性Stripe条件，不提前采用旧Stripe种子的偏压。
显式S参数须成对提供且与场权威相符；这一缺省行为不放开改压，也不修改其他电压、源或观察定义。

| 能力 | 与普通固定场消费的区别／资格 |
|---|---|
| 冻结标量场消费 | 读取既有V/mask及局窗，使用原trial真实飞行；成功终态不代表轨迹闭合 |
| 变压provider与响应组合 | 分别生产新电压场、或组合已验证增量；须有对应几何、离散和实际电压范围的独立证据 |
| 固定点物化 | 将选定组合表示保存为新标量PA；计划生成不等于物化已执行，物化成功也不授FEM／性能资格 |

电极仿射组合在既有binding内声明基场、单因素增量及目标电压；
系数由实际电压差派生，逐项保持网格、mask、sheet、窗口和固定物理身份。
场线性不代表轨迹线性；新电压必须通过同一完整飞行入口检验。
固定点物化复用公共 standalone composer，输出新标量 PA，保留原 mask 和所有局窗。
两种组合表示均明确标为探索性；实际对照、速度、内存及资格见
[电场表示与数值资格](../docs/PROJECT.md#电场表示与数值资格)，不由文件存在推定。

以下命令只验证／解析 binding，或生成物化计划；不会运行 COMSOL、SIMION 或写 PA。
物化计划必须由受管运行执行和封存，再消费其 manifest；不得覆盖输入 PA。

```powershell
.\.venv\Scripts\python.exe -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding --binding '<binding.json>'
.\.venv\Scripts\python.exe -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding `
  --binding '<response-binding.json>' --composition-plan '<run>/inputs/composition-plan.json' `
  --composition-output-directory '<run>/simion'
```

同模块支持配对查询请求：`--compare-binding`、`--samples`、`--sampling-request`、
`--comparison-output` 必须成组提供，不能与物化计划混用；它只生成请求，不提供实际场对照。
GUI 对等不能由 `efield_adjust` 回调推定，最终交付仍须满足实际所用表示的独立验收。

## 构建与独立验收

[run_native_corridor_response_bank.ps1](run_native_corridor_response_bank.ps1)组织 native bank
生成，调用公共 PA transaction 完成 Refine、inventory、封存和发布。
底层 transaction 编排见 [run_native_corridor_qualification.ps1](run_native_corridor_qualification.ps1)。
[native_corridor_identity.py](../analysis/native_corridor_identity.py)定义项目 family 身份；
物理到局部 ID 映射和响应数量来自冻结 plan，不在本文固定某次 bank 的数量。

响应成员遵守原生 Fast Adjust 的 `10000 V` 参考归一化，不能把 1 V 文件当原生 `.paN`。
发布前在精确私有 family 上验证非零电压表及关闭／重开，最终 inventory 绑定持久字节和验证证据。
公共 transaction 是 payload、scratch、发布指针和容量账本的唯一 owner；
项目不维护第二份 PA 生命周期。缓存命中不得再做 GEM、Refine 或大 PA 复制。

原生响应固定点物化使用项目内的
[`standalone_pa_composition.py`](../analysis/standalone_pa_composition.py)，尚未取得跨项目公共化资格。
它按有界float64块组合普通`.pa`，保留电极标志，要求网格及fractional伴随数据一致；
不Refine、不读取原生family、不修改输入。新PA及sidecar关闭前各执行一次`flush()`和`os.fsync()`；
刷新失败由owner保留私有残留并失败收尾，不返回成功或重试。
[Python 3.11官方说明](https://docs.python.org/3.11/library/os.html#os.fsync)要求先刷新Python流，
Windows使用`_commit`（查阅2026-10-13）；这不保证硬件缓存持久化或场精度，发布仍由公共manifest负责。

[build_native_corridor_iob.lua](build_native_corridor_iob.lua)仅装配已封存四角色，
检查位姿、网格、对称性及真实重叠优先级。先保存 IOB，再做 Fast Adjust，
避免 Workbench 保存尝试回写脏 PA；日志中的保存错误即使进程 exit0 也判失败。
原生电压更新一次提交完整通道表，不逐区合成或保存 published PA。

`-RetainGuiWorkbench` 在共享 native runtime checkpoint 语境下保留
`simion/gui_workbench/` 的 IOB、Fly2、Lua 和小型收据，飞行后绑定稳定只读 PA。
没有要求的共享 checkpoint 时不得为 GUI 重建整套 family；实际模式限制以入口校验为准。
GUI 重载通过只证明装配可检查，不能代替场精度、飞行或性能资格。

[单中心步长对照](../analysis/run_single_center_timestep_convergence.ps1)要求三份 success
run 的几何、PA、电压、源、程序、脉冲和自然回程身份相同，仅最大 trajectory step 不同。
分析报告目标 K、回程转折及 detector 的相空间差，不自行设置通过阈值。
静态入口 [verify_project.ps1](../verify_project.ps1) 不启动商业软件；真实 SIMION、
GUI 重载及正式资格属于不同验证层，不能互相替代。

## 源与运行入口

所有入口消费本次冻结合同、源及 PA／field 身份；参数全集见各脚本 `param`。
下面标为飞行、建场或调焦的入口会运行商业软件；分析、源发布及计划生成不运行 SIMION。

| 任务 | 入口 | 必需输入与输出范围 |
|---|---|---|
| OA 组件验收 | [run_accelerator_component_provider.ps1](run_accelerator_component_provider.ps1) | provider 请求／receipt；不授予整机资格 |
| N=1 或 N>1 完整飞行 | [run_two_prism_trial.ps1](run_two_prism_trial.ps1) | 几何、镜、Stripe、OA receipt、P1/P2 电压及一种场消费输入 |
| 束团源发布 | [run_publish_bunch_source.ps1](../analysis/run_publish_bunch_source.ps1) | `-SourceDefinitionPath`、`-GeometryContractPath`、`-AcceleratorProviderReceiptPath`；发布 CSV/Fly2/receipt |
| P/S 四列单步审计 | [run_downstream_fixed_grid_workpoint.ps1](../analysis/run_downstream_fixed_grid_workpoint.ps1) | baseline 与四个独立单轴扰动 manifest，输出有界电压提议 |
| P/S 自动重闭合 | [run_downstream_workpoint_iteration.ps1](../analysis/run_downstream_workpoint_iteration.ps1) | 唯一初始工作点、seed 或 continuation；独立 child 飞行及控制器记录 |
| native 束团筛选 | [run_native_corridor_bunch_screening.ps1](../analysis/run_native_corridor_bunch_screening.ps1) | 同一 checkpoint、冻结静态 cohort；受控小样本不提供正式峰宽 |
| native Candidate／TE1 链 | [run_native_candidate_chain.ps1](../analysis/run_native_candidate_chain.ps1) | 已接受中心工作点、common 源及相同前缀的 baseline/调焦比较 |
| K/y campaign | [run_native_candidate_campaign.ps1](../analysis/run_native_candidate_campaign.ps1) | [工况表](../config/native_candidate_campaign_k_y_scan.json)；发布统一 comparison |
| 源 z／能量／末段时序分析 | [run_source_z_energy_timing_diagnostic.ps1](../analysis/run_source_z_energy_timing_diagnostic.ps1) | 完整 success flight；只读诊断，无新飞行 |
| 固定关断时钟冻结 | [run_freeze_bunch_pulse_schedule.ps1](../analysis/run_freeze_bunch_pulse_schedule.ps1) | 同源完整静态 pilot，发布 schedule；不证明脉冲已真实执行 |

P/S 单步审计的五个 manifest 参数为 `-BaselineManifest`、`-Stripe1PerturbationManifest`、
`-Stripe2PerturbationManifest`、`-Prism1PerturbationManifest`、`-Prism2PerturbationManifest`。
单轴场与轨迹须按该入口合同保持共同冻结问题；边界、尺度、信赖步及停机规则由
`downstream_fixed_grid_workpoint_profile` 派生，不从命令行另设一套数值。
提议不是通过资格，必须真实飞行检验。

自动迭代的 `-InitialWorkpointManifest`、`-SeedTrialManifest`、`-ContinuationRunManifest`
三选一。native 模式使用 bank/bundle；COMSOL 模式使用 `-FieldProviderRequestPath` 和冻结
`-CenterSourceReceiptPath`，不得混入 native family/checkpoint 或 OA pulse。
同目标已完成场可通过 `-CompletedFieldProviderManifest` 显式复用；
`-ResponseFieldBindingPath` 声明探索性 S 响应，不能据此外推其他未声明电压。
静态 seed 分阶段提取 P 前闭合、同锚 S 响应及完整返回；阶段通过不等于整机通过，
下游缺事件不补零，不把旧轨迹 Jacobian 当新锚点已验证导数。

native Candidate 链的受控焦点对及回退区间只供导数，不混入正式体积源峰宽。
实际 cohort、收集门槛和有限回退规则来自冻结合同；达到退出条件即停止该工况。
同一母队列前缀比较收集率、TOF 和 FWHM，不删损失、不去趋势、不凭单次最佳结果晋升。
活动任务的样本、TE1 范围及源参数见
[OA真实源与束团证据](../docs/PROJECT.md#oa真实源与束团证据)，不从历史配置推定。

解析电压链使用 [run_target_operating_point_chain.ps1](../analysis/run_target_operating_point_chain.ps1)，
从同一合同串接镜 exact-K 与双 Stripe 反演。P1/P2 分段射击继续使用
[coverage](../analysis/run_two_prism_segmented_coverage.ps1)、
[continuation](../analysis/run_two_prism_segmented_continuation.ps1)：continuation 只追踪
冻结的单一事件签名，理论覆盖点不能直接称为真实三维工作点。

### 源身份与诊断源

源表、Fly2、合同粒子数、预期 ID 及 SHA 在输入 manifest 中绑定；
母粒子数不能从已记录终态反推。改变释放分布只改变源／飞行身份，不重建 PA family。
正式体积源不夹受控参考粒子；Gaussian 的能量标准差、非正动能处理及共同母序列
由源合同和既有 publisher 定义，不在本文复制本次源数值。

| manifest source key | 诊断范围 |
|---|---|
| `mirror_internal_diagnostic_center_fly2`／`mirror_internal_diagnostic_bunch_fly2` | 分析器内释放，绕过 OA/P1/P2，只隔离镜／Stripe |
| `accelerator_focus_center_fly2`／`accelerator_focus_bunch_fly2` | 第一区由静止释放，检查加速器第一时间焦点，不能代替脉冲源 |
| `first_prism_entry_center_fly2` | 两区焦面处释放，只供首棱镜三维射击 |
| `full_mrtof_center_fly2` | 按审计工作点生成的完整源到 detector 链，N=1 与 N>1 使用同一事件定义 |

不同具名源不能合并统计。整机源位置须按 MR 装配与 OA provider release 合同派生；
位置、物种、速度、ID 和共同出生时刻原样继承。旧 schema 只能解释旧证据，不能补造新资格。

## 恢复与资源

完整束团仍由 `run_two_prism_trial.ps1 -BunchSourceReceiptPath ...` 执行；
receipt、状态表和 Fly2 必须是同一成功源 run 的唯一输出。
公共调度器选择资源和 batch，项目不设独立并发门槛；详见
[公共调度与恢复](../../../common/simion/README.md#调度与恢复)。

每批是连续全局 ID 区间，SIMION 内局部编号 `1..n`；合并仅用计划的
`simion_particle_id_offset` 还原，拒绝缺失／重叠，保留全部非完成日志，
只生成一个全局 Fly-completion。各批共用冻结场及 IOB，不逐批构建或 Refine。
`-BunchParticleIdMin/-BunchParticleIdMax` 只选冻结源连续区间，结果属于源选择诊断。

启动前先发布checkpoint；只有实际执行formal-first观察、可能重分批后才更新飞行前checkpoint，
已有资源profile且计划未变时不重复读写配置或写验。自然完成批次和最终发布仍完整验证；尚无端到端提速测量。
每个自然完成 batch 发布 manifest-bound checkpoint。新 run 使用
`-BatchContinuationRunPath` 导入连续完整批次前缀；未完成批次整批重放，
不更改原 run 身份、物理输入或调度规则。screening 的 pilot/cohort 分别传其恢复入口。
父 P/S workflow 恢复使用新 `RunId`。只有首个成功 child 时，可单独传
`-ResumeSuccessfulChildManifest`；后续轮须与 `-ResumeParentCheckpoint` 配对，
指定连续链末端。bootstrap 恢复使用父 checkpoint，不接受任意 child 覆盖。
恢复沿原状态机核对冻结输入、电压、观察和已完成 child，不扫描目录猜测可用结果，
不重飞已确认完成的步骤；精确参数组合由入口失败关闭。

native bank 的 `-TransactionCacheKey` 只恢复／复用指定事务；已发布 family 只读。
`-RecoverMembers` 指定失败成员；`-RecoverRetainedInventoryMembers` 和
`-CorrectPublishedInventoryMember` 仅处理有原 journal 证明的 inventory 问题，
不得借此重写物理输入、重建发布成员或伪称新求解验证。
公共 owner 负责单写者、库存、封存及退休；身份不符保留证据并停止，不静默重建。
运行中断保留受管 checkpoint，恢复复用仍有效的 payload 身份和容量记录。

长 PA 输入复用[公共短路径支持](../../../common/simion/short_pa_path_support.ps1)；
先查[已关闭的长路径结论](../../../docs/SIMION_REFERENCE.md#长pa输入路径)，
不要另建项目私有实现。只读、Junction、硬链接或复制本身不保证 native family 写隔离。
published PA 不是 runtime 写目标；私有 family、standalone PA 的具体装配与封存由公共机制负责。
不反复复制／哈希已由受管只读机制保护的重型资产；容量、保留和清理由其唯一 owner 处理。

## 事件与分析

[mrtof_candidate.lua](mrtof_candidate.lua)及[mirror_cycle_counter.lua](mirror_cycle_counter.lua)
以 P2 后正镜转折定义快相位原点，后续每次真实镜转折增加半周期。
目标 K 与返回镜侧来自 `target_drift_period_ratio/fast_path_symmetry`，不在代码中固定数值。
中央 `z=0` 或提前 `y=0` 穿越仅作诊断；目标镜转折才产生严格相位返回。
返回应经 P2、必要的正镜转折后沿 `v_z<0` 命中 detector；只有解析镜区可以令 `v_z` 反号。

碰撞、程序拓扑拒绝、未知场支撑失败和未到达须分别报告，不能按终态坐标猜测部件。
缺 target-K 或完整返回的观察不得补造有效 Jacobian；完整通过与阶段观察分开保留。
`sim_segment_global=1` 用于捕获 PA 外终态，仍须逐粒子核对唯一结束和日志完整性。
[run_iob_flight.lua](run_iob_flight.lua)要求同名 Program/Fly2/operating-point/voltage-map/
mirror-cycle-counter 伴随文件，实际源必须匹配冻结字节；zero-exit 错误日志仍判失败。

同一进程先构建／重载IOB再Fly时，launcher按`simion.pas[1..#simion.pas]`的完整`path`
复用已加载的普通碰撞PA：零匹配才open，一个匹配复用，多匹配在Fly前拒绝；不只比较basename。
新载入与复用都只在内存设置`refinable=false`并保留`--remove-pas=0`，不保存、关闭或重新求场。
依据为[官方PA接口](https://simion.com/info/lua_simion.pas.html)及本机SIMION 2020 Help的
`pa.filename`／`pa.path`定义：前者仅为basename，后者为完整路径（8.1.1.18加入）；Help示例打印
`c:/temp/test.pa test.pa`。`examples/field_array/solidworks_to_pa.lua`说明`refinable=false`
（2026-10-16查阅）。launcher记录库存的实际`filename`、`path`及匹配结果，供真实运行核对；
冷启动及旧`.pa0`路径保持原行为。

```powershell
.\.venv\Scripts\python.exe -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis `
  '<run>/stdout.log' '<run>/event_analysis.json' `
  --input-manifest '<run>/simion/prototype_input_manifest.json' `
  --source-key mirror_internal_diagnostic_bunch_fly2
```

示例 source key 仅适用于对应镜内诊断源；必须换成本次实际源。
目标 K 只从冻结 derived 合同读取。源身份变化、无唯一完成记录、计数不符、
缺失／重复／未知 ID 或截断事件均拒绝 PASS；完整性失败时性能字段为 null，CLI 返回 FAIL/1。
完整性通过返回 PASS/0 只代表该层检查，不自动授予分辨率资格。

镜像非重合支路诊断只对精确返回且内部 fast-turn 数为 `2K-1` 的事件首尾配对；
报告 y、`z_return+z_outbound` 及速度反向残差，未收敛前不臆定物理容差。
源 z／能量／末段时序分析的出口统计包含全部冻结粒子，下游配对只使用真实完整事件，
损失继续进入终态统计。斜率、相关和增量贡献是描述性诊断，不等于因果归因。
FWHM、分辨率和统计资格使用[统一验证口径](../../../docs/OPERATIONS.md#通用验证口径)。

### 积分与脉冲边界

逐步记录实现随项目源码纳管，资格与验证边界见PROJECT；完整逐步轨迹默认关闭。
需要时由同一`-ContractPath`的`simion.trajectory_recording`显式声明
`schema_version=1`、`mode=every_step`或`fixed_interval`、`retention_class=solver_review`、非空`reason`及正整数
`output_budget_bytes`；预算必须覆盖原始日志与CSV，不能沿用普通compact的轻证据承诺。
`fixed_interval`还须声明有限正数`interval_us`，选择每个绝对时钟桶跨界后的首个实际回调，
出生与终态必录；它不强制积分落点、不改变步长或关键事件，不声称记录精确等距。
该项目观测实现使用SIMION官方[轨迹回调](https://simion.com/info/trajectory_programming.html)
（8.1补充文档，2026-10-16查阅，SIMION 2020实测）：`initialize`记录出生，`other_actions`
逐积分步读取状态，`terminate`记录终态；不修改步长、场或粒子状态。
输出`results/trajectory_samples.csv`与收据，按实际回调顺序保留全局ID、仪器时间、三维位置和速度。
原生terminal若时钟回退且六维状态与末记录完全相同，保留原始次序及回退量；every_step仍要求精确前一回调时刻，
fixed_interval只接受回到相邻保留观测之间，稀疏记录不能证明该回退只有一个积分步。
不改写时钟或排序。旧完整性实测为N1，多离子交付还须核对全部预期ID集合。
开启模式通过公共owner封存dense载荷，封存成功后才报告入口PASS；封存失败单独报告并保留科学manifest。

积分设置由 `trajectory_profiles` 派生；`-TrajectoryProfileId` 选择具名 profile，
`-TrajectoryStepScale` 或 screening 的 `-TrajectoryStepScaleOverride`
以有限正比例调整最大步长，不改变源、场或调度；实际步长为冻结profile的base乘scale。
较大步长需有对应路径的敏感性证据，不因参数可接受就取得精度资格；当前默认及已测范围见PROJECT。
底层 `static`、仅 N=1 的 `initial_exit_triggered_single_center`、
`fixed_global_time` 三种模式互斥；静态场消费不能接受 OA pulse。

固定时钟通过 `-AcceleratorPulseSchedulePath` 读取身份收据；
`tstep_adjust` 落到计划边界，记录计划与实际时刻，电极实体和碰撞保留。
schedule 冻结要求全部粒子唯一负 z 安全出口，按 `max(exit)+guard` 派生；
`guard_us` 显式给定且覆盖 pilot 的最大步长，绑定 source cohort 和 solver problem。
源发布和 schedule 生成不证明真实脉冲已执行，也不授予整机性能资格。

## 历史与来源

旧局域五区／八实例、旧拓扑、逐轮 Jacobian、native 缓存修复和旧束团结果均为只读历史，
不能恢复为活动入口。完整整理前原文见
[场响应工程里程碑归档](../docs/history/20261008__field-response-engineering-milestone.md)；
其他历史入口由[项目导航](../README.md#历史补充索引)集中索引。
官方 API 与已验证公共边界见[SIMION 参考](../../../docs/SIMION_REFERENCE.md)；
本次结果只从实际冻结 manifest 和原始日志读取。

[scalar-n13]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_093500__sim__simion__converging-mesh2-fixed-u-controlled-n13__r02/summary.json
[scalar-n1]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_092318__sim__simion__converging-mesh2-stripe-authority-n1/summary.json
