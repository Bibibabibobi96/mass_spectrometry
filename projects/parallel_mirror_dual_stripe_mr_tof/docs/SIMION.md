# MR-TOF SIMION 实施说明

本页说明 SIMION 入口、输入和独立验收；当前工作点、资格、运行证据及开放任务见
[项目状态](PROJECT.md)，其他软件入口见[项目导航](../README.md)。
输入版本见[输入权威](PROJECT.md#输入权威与物理定义)，当前执行顺序见
[开放动作与关闭条件](PROJECT.md#开放动作与关闭条件)。
命令从仓库根 `simulation_repo/` 执行；尖括号为必须替换的占位路径。
工具版本、商业执行及资源准入统一遵守[操作指南](../../../docs/OPERATIONS.md)。

## 按任务查阅

| 任务 | 本页入口 |
|---|---|
| 确认几何、坐标与组件责任 | [输入与装配](#输入与装配) |
| 跨项目OA／IP准备和联合执行 | [统一集成入口](../../../integrations/README.md)；本页保留MR提供者及局部科学操作 |
| 选择 native 或 COMSOL 场消费 | [场输入与碰撞](#场输入与碰撞) |
| 构建 native bank、重载 IOB 或保留 GUI | [构建与独立验收](#构建与独立验收) |
| 发布源、完整飞行和 P/S 调节 | [源与运行入口](#源与运行入口)；[实测源分阶段控制](#实测源的分阶段ps控制) |
| 断点续接或 N>1 批次恢复 | [恢复与资源](#恢复与资源) |
| 解释返回、碰撞及峰宽结果 | [事件与分析](#事件与分析) |
| 追溯旧工作台、结果和迁移过程 | [历史与来源](#历史与来源) |

## 输入与装配

### 加速器选择与接口准备

MR拥有分析器设计、匹配目标、场消费合同和P/S控制；跨项目装配、接口准备与联合飞行由
[integrations](../../../integrations/README.md)拥有。初始设计不启动求场或Fly；Finalize绑定实际新源、场并保存／重载IOB，仍不Fly。
源表、运行FLY2和工作台必须在实际绑定阶段一致生成；设计收据不替代执行资格。当前支持范围与实际资格只查下表状态入口。

| 任务 | 权威入口 | MR侧须提供或核对 |
|---|---|---|
| OA／IP接口设计及实际场／IOB绑定 | [接口准备与绑定](../../../integrations/docs/INTEGRATION.md#oaip接口准备与绑定)、[execute.ps1](../../../integrations/workflows/accelerator_interface/execute.ps1) | 显式provider、原始封存MR参考run；IP使用当前schema 3 matching request。Finalize消费设计阶段冻结输入，准备不等于Fly |
| 已准备IP→MR飞行、整批恢复或重新分析 | [联合飞行与分析](../../../integrations/docs/INTEGRATION.md#已准备ipmr联合飞行)、[prepared_joint入口](../../../integrations/workflows/prepared_joint/execute.ps1) | 已完成准备包、冻结轨迹合同；结果保留源ID、仪器clock和完整母群 |
| OA→MR完整飞行 | [OA→MR入口](../../../integrations/workflows/oa_mr/execute.ps1)及上述集成状态 | 冻结CompositionPlan及显式局部范围，OA receipt、源与MR科学合同 |

[accelerator_interfaces.json](../config/accelerator_interfaces.json)只声明MR支持的provider选择与依赖，
[IP依赖](../config/ion_processor_dependency.json)冻结producer代码与源身份；
[匹配请求示例](../config/ion_processor_matching_request.json)供显式作者输入，不从MR锚点反推位姿。
几何与实测六维状态使用同一直接位姿，源变换只应用一次：位置旋转平移，速度只旋转，能量与绝对时间保持。
能量差应报告；需调压时由提供者重新求场／实测，不能在导入CSV中补加能量。
`preserve_measured_workpoint`保留来源抬升电压，`provider_voltage_and_geometry`派生候选；
两者均须核验实际源、候选配置、时序和场身份，设计收据不授予物理匹配或时间聚焦资格。
替换OA后的场必须来自新装配，不能混用旧OA父场、中央层或镜边界。
IP采用`state_handoff`，继承实测状态与到达时刻，后段为RF为零、提取脉冲保持的静态场；
它不代表同一Fly内连续积分捕获／冷却到MR。完整母群包含上游未交接ID，不能以交接数替代分母。

### MR几何与OA提供者合同

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
[OA提供者入口](../../orthogonal_accelerator/simion/run_component_focus_workflow.ps1)消费统一
`mrtof_runtime_receipt.json`。出口、grid1、repeller 沿更大的 `+z` 排列，出射沿项目 `-z`。
组件验收直接调用该入口，显式传入本项目现有的
`-RequestPath config/accelerator_component_request_n100.json`与
`-ReleaseSpecPath config/accelerator_component_release_n100.json`（路径相对本项目根或使用绝对路径）。
OA PA 以 `x=0` 为镜像面，只存半域；实例原点必须保留镜像面，重载检查 `3dplanar[x]`。

`-AcceleratorProviderReceiptPath`传OA发布run的`results/mrtof_runtime_receipt.json`，
不是某次MR飞行`simion/`中的冻结副本：入口由收据位置定位原owner的manifest、plan及resolved campaign。
两份收据即使字节相同，也不能把MR副本的目录身份当成OA owner；子运行自行冻结消费副本。
`-BunchSourceReceiptPath`同样传原源发布run的receipt，绑定其CSV/Fly2；不传其他飞行中的收据副本。

加速器全局 y 由 `accelerator.focus_y_anchor.project_y_mm` 决定。装配读取 provider 的
实际 PA 原点及实体包络，并与 resolved Prism2 屏蔽件、Stripe 检查净间隙；
数值 PA 包络可为优先级而重叠，导体实体不得相交。位姿不属于独立 PA 的生成输入时，
只新建飞行身份并重新评估残差，不据此重建 corridor family。

### IP到P1的局部距离对照

`projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_ip_prism_distance_study.ps1 -RunId <new-run> -ContractPath <experiment.json>`
只求解IP出口与第一Prism的小域静电场，并在合同的`p1_exit`面停止，不进入镜组或整机闭合。
合同显式冻结五份封存来源（几何、电压、实测出口、完整母群、提取时序）、距离列表、局部盒／网格、
Refine精度、最大积分步长、观测面和容量承诺。`analysis/ip_prism_distance_study.py`验证并准备输入；
`ip_prism_local_geometry.py`复用canonical CSG，P1固定、IP与屏蔽延长段同步平移，保持1mm机械间隙。
距离指名义束轴处离轴三角电极的投影近端，不冒充尖锐的电场入口；实际场剖面随运行输出。

入口复用公共主机许可、资源画像和独立工作项调度；每工况原生GEM→普通PA Refine→保存重载IOB→Fly，
自动并发由首工况实测决定。同一进程分配多个工况时按公共计划串行执行，没有嵌套并行。
测得的出口六维状态与绝对时间保持，仅位置作刚体平移；原母群未交接离子继续登记为上游损失。
`ip_prism_local_diagnostics.py`自动输出全部损失原行身份、共同ID与各自到达群的相空间／时间宽度、
共同时间空间云及静态K+qV漂移；时间宽度采用人口SD，不据此给出整机R或高斯FWHM。
局部五面接地／x镜像边界是独立小域近似，截断导体清单显式保留，不继承旧几何父场；
它不验证近移屏蔽对上游捕获／引出状态的反馈，也不代表GUI、CAD或MR接受度资格。

### IP轮廓、时间焦点与接受度局部验证

同一局部入口接受schema version 5的`ip_prism_contour_focus_experiment`合同；它以每行明确的来源、几何、网格及步长，
消费B／C／D各自完整出口与母群，而不是把旧平板场用于新轮廓。来源诊断失败时，只有完整物理事件和
实际消费记录通过身份核验才允许交接；保留原producer状态，不将其改为成功。
电压通过冻结的IP原生Lua时序投影，不在Python复制电压公式。跨项目依赖由
`config/ion_processor_dependency.json`声明，实际进口源码闭包冻结进本次输入。

每行还须显式声明`lens_elements`列表；空列表保持无透镜几何。
有限圆杆四极透镜逐项声明`name、frame_id、center_mm、length_mm、inscribed_radius_mm、rod_radius_mm、voltage_v`，
x杆对为+V、y杆对为−V，由真实有限电极GEM求场，不能用角度kick代替。
准备阶段校验实体接触、屏蔽孔口、局部域和镜像条件；同一场ID的透镜、全部GEM及电压身份必须一致。

`field_sources`必须精确覆盖全部`field_case_id`：每项为`{action:'build'}`或
`{action:'reuse',source_run:<sealed-run>,source_field_case_id:<field-id>}`。复用来源可为success或failed，
但必须具备manifest绑定的完整有限值／编码范围／网格验证，编译出的GEM、原生电压及Refine身份必须一致。
PA及实际surface经公共机制复制到本次独立目录并核验目标SHA；不修改来源状态，不复用失败的飞行记录。
完整`field_owners`与实际需新建的`build_cases`分开；全部复用时跳过求场，仍验证所有场。
每个`field_case_id`仅建场或物化一次，完整载荷有限性／网格校验后再调度只读共享PA的Fly；
半步对照共享对应场。`validate-fields`自动生成实际PA节点与连续CSG的截面对照和逐节点表；
新准备保留科学case表顺序，另冻结按场节点数降序的建场／飞行顺序；最大场的首个正式工况自然完成后，
再用完整进程的实测峰值自动规划余项并发，避免用粗网格或GEM早期观测代替细网格的完整内存需求。
这复用公共`WaitForNaturalCompletionAfterObservation`机制，不把PA文件大小伪装成实测内存；已启动冻结运行不回写。
节点截面包括中心XZ、auxiliary中面XY、束轴YZ及RF／内外辅助电极的几何派生YZ位置，保留请求面与实际节点面。
这些图展示离散表示，不把fractional求场表面视为Fly的精确碰撞表面。
`validate-fields`还自动调用`ip_prism_field_theory.export_field_theory`，在Fly前输出全出口的无场协方差、
逐面束腰与理想薄透镜权衡，以及实际PA在恒速参考路径上的场／对角曲率探针；全部声明观察面和出生点均保留。
场探针不是实飞或SIMION力插值；电极／越界stencil显式记录，局部场保持的速度变化尺度不是积分偏转量或误差界。
理想准直与指定下游面最小束斑使用不同透镜强度，不据此宣称实际电压可达性能；普通单工作点PA不能识别单电极调压响应。
飞行后自动输出全母群损失、沿程时间宽度、共同ID比较、统一法向面与全局z面的配对结果，
以及明确位置／尺寸的虚拟y狭缝和圆孔比较。采样最小值若位于范围边缘或群体缺失，必须显式标记。
`sampled_minima.csv`保留时间宽度极小值；`sampled_spatial_minima.csv`使用同一完整支撑区间机制，
分别给出全局z面的σx／σy与参考法向面的局部横向束宽最小值、位置和边界标记，不将损失后的窄群当作原群束腰。
`time_focus`和`transport_widths`的同指标列跨工况使用统一x／y范围，保留全部原始曲线与到达数，
避免独立自动缩放掩盖束斑或角宽变化。历史封存图不原地重画。
虚拟筛选不改变场，不能替代有厚度实体孔及其边缘场的独立求解；两者分开报告。
新合同每行必须显式给出`physical_aperture`，无孔为`null`；实体孔完整声明中心、world-z法向、
板厚、有限外尺寸、孔径及电位／连接。当前只支持x镜像对称的z法向圆孔和有限x宽的y狭缝，
孔板必须位于实际出口和末观测面之间，并核验与屏蔽的真实接触及与P1实体的分离。
GEM切孔工具沿z延伸到局部域外一个网格，避免等长切孔工具在板面留下端帽；实际板厚、孔径和连续CSG不变。
该方式依照[官方GEM交集示例](https://simion.com/info/gem_geometry_file.html#intersecting-within-and-notin-inside)，
已在SIMION 2020 8.2.0.11以两孔形、两网格实际GEM2PA与PA:point验证；仍须逐个新场检查全厚度节点。
数值比较忽略派生切孔工具／网格说明，但保留真实板和孔CSG；场复用继续严格核对完整GEM身份。
旧schema version 1／2／3／4仅由已启动运行的冻结源码继续消费或读取历史记录，不用于新的求场准备。
version 3删除未执行的作者`limits`目录限额字段：旧运行保存该字段不代表执行了硬上限或周期检查。
真实资源准入仍由公共CPU／内存调度及`committed_new_bytes`容量承诺控制，不将启动容量预留称为持续目录上限监控。
`aperture_comparison.frame`显式选择`global_z`或`reference_normal`；z法向实体孔应与相同z面、中心和孔径的
虚拟筛选比较，不能把平面定义差异算作孔边缘场效应。
已有成功局部运行可通过同一Python入口的`prepare-recorded-analysis --run <new-analysis> --source-run <native-run>`
冻结实际观察记录再执行`analyze`；不读取PA、不重新飞行。可附`--contract <selection.json>`显式调整
虚拟筛选合同及claim，所有物理／数值输入必须与原native合同完全相同，原resolved也单独保留。
自动图包括时间焦点、法向面对照、虚拟接受度、出口相空间与时间—能量、共同时间空间云和沿程束宽／角宽／能散。
全程同时刻图按出生／终态及出口时刻自动取样，输出绝对XZ／YZ、生命周期状态和同active群的居中放大XZ／YZ。
`transport_time_census.csv`保留全部母ID与绝对位置，`display_zoom_centers.csv`记录仅供显示的均值与相同active ID；
未出生、上游未交接或已终止的粒子只有状态，不外推位置。居中显示不改变轨迹，也不证明冷却或聚焦。
局部重启不验证上游源对新场的反馈，也不授予完整MR分辨率或数值收敛资格。

跨运行的实体孔比较接口、科学结果与圆孔碰撞表示限制见[项目状态](PROJECT.md)。
接口复用同一Python入口的`prepare --contract <comparison.json>`及`analyze`，
作者role为`ip_prism_recorded_aperture_comparison`，在新建分析run中消费已封存的无孔和实体孔案例；
不通过上述原生模拟PowerShell入口，不求场、不Fly。每项`comparisons`明确`comparison_id`、
`baseline_case`／`physical_case`（各含`producer_run`及`case_id`）、`virtual_thin_plane`（front／center／back）
及`downstream_plane_name`；顶层还须给出schema version 1、`committed_new_bytes`与`claim`。
孔尺寸和三面位置只从实体案例的冻结几何派生；基线在声明孔面筛出的固定ID传递到同一实际下游观察面，
不在下游重新筛孔。未筛基线、虚拟群和实体群分别报告，并另列同ID配对结果及全部母群决定。
实体与薄虚拟孔的差异包含板厚与场变化，不能单独归因为边缘场；缺失状态不外推。

局部driver的`assemble`执行阶段只加载已有PA、检查源位置并保存重载IOB，不运行GEM、Refine或Fly。
Workbench保存会同时写伴随文件，driver按公共实现恢复并核验完整Lua及FLY2字节。
只在Fly前保存重载：本机8.2.0.11的headless命令接口Fly返回时会清空当前Workbench，
不得随后保存该空对象覆盖已验证IOB。该行为有实际三离子、两顺序case的生命周期证据；
保存前后同名Lua／FLY2仍按完整字节核验，GUI默认启用状态需另行独立进程复验。
程序在`initialize_run`飞行初始化设置合同Q值；独立GUI副本可显式声明
`frontend={schema_version=1,role='ip_prism_local_frontend',trajectory_image_control=0}`显示并保留轨迹，
未声明的批处理输入保持原来的3。0／3含义来自安装版官方`examples/child_particles/child80.lua`及
[Trajectory Programming](https://simion.com/info/trajectory_programming.html)（2026-10-20核对，SIMION 8.2）；
这是显示配置，不改变物理输入。IOB默认Program启用状态仍须独立副本无CLI覆盖重放验证。
本机2020及在线官方资料包含在`load`设置Q的例子，但本次headless `wb:load`／保存重载上下文实际拒绝该写入；
因此采用已实飞通过的`initialize_run`路径，不把这个上下文差异表述成所有`load`均禁止写Q。
依据为[官方initialize_run权限说明](https://simion.com/info/workbench_program_extensions.html#segment-initialize-run)
与安装版`examples/collision_rs/test.lua`／`examples/child_particles/child80.lua`（2026-10-20核对）。
终止记录函数不写`ion_splat`；只有`other_actions`中的主动出口／超时请求停止，原生`terminate`只记录原生终态。
该权限边界依据上述官方停止粒子示例及安装版2020的`examples/count_transmission/count.lua`与
`examples/child_particles/child80.lua`（2026-10-20核对），并由真实Lua回调权限fixture复现原缺陷。
交付副本必须独立于封存的case目录，因为手动Fly会重新写events／samples；不能用封存证据目录作为GUI工作目录。

同一PowerShell入口接受schema version 1的`ip_prism_local_replay_package`作者合同，顶层必须声明
`schema_version、role、cases、frontend、committed_new_bytes、scope`；每个case显式选择
`source_run`和`case_id`，允许来自多个已成功封存的轮廓运行；也允许明确失败于自动诊断、但完整原生飞行阶段
通过日志、资源收据和逐母终态闭合核验的封存来源，原failed身份保留。它冻结母群、实测状态、原配置与电压投影，
按来源manifest的精确库存私有复制普通PA及实际存在的surface侧车，再重建全部IOB路径。
公共大文件复制验证目标SHA，不硬链接或回写来源；容量会话在复制前进入，实际小文件与所需PA总量
超过作者承诺时拒绝复制。装配复用公共调度，按最大场完整正式观测决定并发，仅执行`assemble`。
准备成功只证明独立文件装配完成；无`--programs`、粒子或Q覆盖参数的原生重放仍需另行验证，不能以准备状态代替。
各交付的默认重放、具名来源、全部损失及资格边界见[项目状态](PROJECT.md)。
该证明不等同于GUI人工显示验收，也不自动授予以后修改的交付；每次改变控制、场或粒子后应重新验证。


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
该`refine`对象可显式声明Boolean `skipped_point`，沿父场CLI和局域`pa:refine`贯通，
并以`refine_skipped_point`纳入场／响应身份；省略时保留安装版默认，显式策略不与省略策略混用。
finalize的`-ContractPath`可显式运输这一Boolean策略变化，在`native_refine_change`记录前后解析身份，
随后核对实际新场的全部层与所选执行合同一致。省略、true和false保持不同身份；
convergence、网格与其余物理／数值字段不在这项允许变化内，不能把旧场绑定到新策略。
依据为SIMION 2020安装手册`docs/simion.chm::/lua_simion.pas.html`、`refine --help`及
[官方高级Refine选项](https://simion.com/info/calculation_time.html)（2026-10-19查阅）；
该受支持选项是数值诊断控制，不代表已证明能消除NaN或达到场精度。
新Refine标量场发布binding前自动逐块核验全部节点的有限性和合法电压编码，
保存`results/pa_payload_validation.json`；原生日志完成或很小的Delta不能替代这项检查。
场描述文件按原字节冻结并核验原owner，不以JSON重新排版替代其封存身份。
复用场不重复扫描；组合路径沿用已有逐块检查，碰撞占据数组仍走独立格式边界。
当前接线与数值资格分别见 PROJECT，配置可执行不代表其精度已经验证。

历史算子祖先与当前实际消费PA分开验证：只有已完成、精确匹配公共退役收据且受原manifest绑定的历史标量／surface允许缺席。
读取器保留其原封存identity、几何、电压和完整算子来源；当前运行真正加载的PA仍逐项核验，不能用历史退役收据豁免。
历史binding原件及run-local冻结副本分别按各自实际owner的inputs／outputs封存记录校验bytes与SHA，随后要求完整JSON字典等价；
CRLF／LF等序列化差异须先通过各自字节身份，再比较完整JSON；不能冒用另一文件的record，也不能忽略身份。
该来源校验已完成真实退役后严格复验，算子及种子frozen_problem身份保持；后续运行manifest冻结所消费的来源投影。
IP完整五层普通场、已物化场及纯响应的历史证明可以递归经过混合owner的细场扩域／响应复用。
每个退役owner仍须有精确五组scalar／surface的十项删除身份与有效公共收据，保留的元数据逐项核验；
读取器按新细场owner定位扩域声明，不把其旧parent owner当作整个声明的owner。
这条路径不允许用已退役响应参与新的PA组合，也不适用于OA局部载荷退役。
这只维持非活动算子祖先的可追溯性；引用已退役PA的历史IOB须重新物化，不能据此宣称仍可直接重放。

探测器 GEM 使用 ID25 建立物质掩码；[build_component_pa.lua](../simion/build_component_pa.lua)
在 `INITIALIZE=0` 时置零电势并保留电极标志，不把 ID25 当成 25 V。
该数值终止面不等同于已验证的物理探测器，原生终止与事件面须逐次核对。

### 局部数值域、碰撞与消费表示

以下是MR原生场提供者的请求合同，入口为
[run_native_static_field_provider.ps1](../simion/run_native_static_field_provider.ps1)；
跨项目Finalize和飞行仍由[接口准备与绑定](../../../integrations/docs/INTEGRATION.md#oaip接口准备与绑定)负责。

该provider若已完整发布并核验summary／manifest，仅最后的容量封存失败，保持原run及原终态，
不重新调用provider的`-Approved`入口。owner先确认本次writer已退出、host许可已释放且无活动容量保护，
再用冻结`run_config.json`中的owner、artifact root及原保留理由调用已有公共收尾：

```powershell
$configPath=(Resolve-Path '<既有run>/run_config.json').Path
$config=Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
python -B -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload `
  --artifact-root $config.capacity_ledger_lifecycle.artifact_root --run-config $configPath `
  --owner $config.project --confirm-writing-stopped --retention-reason $config.artifact_retention.reason
if($LASTEXITCODE-ne0){throw 'Provider capacity sealing remains incomplete.'}
```

这是同一原run的容量收尾，不执行GEM／Refine／Fly，不修改科学文件；`ready`只固定保留占用，
也不能把原命令的封存失败改称整轮成功。输入、输出或终态发布尚不完整时不能用此命令跳过验证。
后续科学运行仍建立新身份；`CompletedFieldProviderManifest`不是当前native provider的恢复参数。
公开封存命令的保护、幂等与保留合同见[公共容量收尾](../../../common/contracts/README.md)。
本项目终态边界保留原始ErrorRecord，释放／guard／发布／别名清理次错附在异常Data中。
正常或异常路径的host释放未确认为同token的`released`时，不清除租约引用，异常收尾再读取实际释放结果；
仍未确认时不发布终态或撤销容量／执行别名保护；
保留项由原owner确认写入停止后处理，不声称PowerShell退出后文件句柄锁仍持续存在。
长期软件回归组合实际PowerShell终态边界、公共retention／manifest核验和seal-only CLI，
验证失败后重入的0原生调用、原文件字节不变及重复封存不重复计账；不构成真实求场验收。

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

碰撞离散的局部修正沿同一`run_native_static_field_provider.ps1`声明`collision_overlay_update`：
指定`box_mm`、`pitch_mm`及金属／真空、盒内外的`priority_probes`，不与改压或几何请求混合。
原ordinary或materialized场先按原owner完整验证，新overlay独立封存源副本、完整分析器CSG、
网格、PA和fractional surface；只执行gem2pa，不Refine或Fast Adjust，不生成新的电场解。
补丁盒须在原碰撞域内，且不得与IP或检测器PA体积接触；禁止嵌套overlay或用单个疑似电极替代盒内全部实体。
新IOB须实际保存重载并核验第五实例的金属、真空和边界优先级；请求中期望值或纯测试不能代替原生验收。
方法依据为[官方多PA优先级说明](https://simion.com/info/multiple_pas.html)和
[GEM接口](https://simion.com/info/gem_geometry_file.html)，实际版本为SIMION 2020；这是基于官方接口的项目局部碰撞表示，
其适用范围由同源步长对照及修正后的真实飞行证据分别限定。

`build_native_corridor_iob.lua --measured-source <workbench_build.lua>`实现IP的四个角色
`global_fallback → native_corridor → ion_processor_collision → detector`；旧OA四角色协议保持。
局部碰撞网格对照可在原四角色后追加显式`analyzer_collision_patch`，使用已有五实例种子；
它在完整盒内接管碰撞判定，包括真空，实际电场仍由同一标量场回调提供。
独立IP细碰撞PA避免0.5/1/1 mm背景网格漏掉薄辅助电极；细网格0.05/0.10/0.05 mm覆盖完整15电极。
场输入必须全部来自替换OA后的新装配，不能混用旧OA的父场、中央层或镜边界。
全域碰撞GEM保留金属，移除数值边界接地面；网格表达不等于数值收敛资格。

镜场可按冻结数值合同已有`stored_xmax_mm`派生显式`memory_consumer_crop`；源PA完整尺寸、
消费尺寸及完整插值halo均记录在本次收据。使用官方`pa:crop(...,false)`仅裁进程内的非Workbench镜场对象，
保留原active box、原点、实际pitch及fractional表面，不保存或Refine源PA；二次加载须复用裁后对象。
该消费范围不成为新的求解边界。指定`-TrajectoryEquivalenceReferenceRunPath`时，冻结已验证参考运行的首批记录，
在终态前比较同ID的全部事件和轨迹观测；这是消费表示验证，不代表Prism物理匹配。
依据为[官方PA API兼容记录](https://simion.com/info/lua_simion.pas.html)的8.1.1.22起crop表面信息保留／persist参数，
及本项目已实测的`crop_native_static_field.lua`路径（SIMION 2020，2026-10-16查阅）；不采用较新版本专有能力。

普通PA长度依据SIMION 2020安装包官方`lib/python/SIMION/PA.py`的load/save实现核对（Pulsar Physics，
2026-10-16查阅）：单位网格mode −1使用32字节头，非单位网格mode −2另存三个double间距，头长56字节。
场编译器据此预测节点载荷长度，保留严格长度核验；不因检测器单位网格而放宽格式检查。

### COMSOL 标量、响应组合与固定点物化

普通冻结标量消费、响应组合和固定点物化分别核验，当前证据与资格见
[电场表示与数值资格](PROJECT.md#电场表示与数值资格)；旧mesh3试验不能替代会聚mesh1/mesh2资格。
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
[电场表示与数值资格](PROJECT.md#电场表示与数值资格)，不由文件存在推定。

已准备联合包的数值对照沿直属入口的`-ContractPath`声明，准备收据分别绑定原准备合同与执行合同。
只允许已实现的轨迹观测、累计候选预算或当前默认profile的`maximum_step_us`变化；
源、场、电压、profile选择、trajectory quality、超时及其余科学字段保持，不能借诊断改动重定义原问题。
编译结果写入实际master／batch sidecar并由SHA绑定，记录前后数值，不另加CLI数值权威。

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

[run_native_corridor_response_bank.ps1](../simion/run_native_corridor_response_bank.ps1)组织 native bank
生成，调用公共 PA transaction 完成 Refine、inventory、封存和发布。
底层 transaction 编排见 [run_native_corridor_qualification.ps1](../simion/run_native_corridor_qualification.ps1)。
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

[build_native_corridor_iob.lua](../simion/build_native_corridor_iob.lua)仅装配已封存四角色，
检查位姿、网格、对称性及真实重叠优先级。先保存 IOB，再做 Fast Adjust，
避免 Workbench 保存尝试回写脏 PA；日志中的保存错误即使进程 exit0 也判失败。
原生电压更新一次提交完整通道表，不逐区合成或保存 published PA。

`-RetainGuiWorkbench` 在共享 native runtime checkpoint 语境下保留
`simion/gui_workbench/` 的 IOB、Fly2、Lua 和小型收据，飞行后绑定稳定只读 PA。
没有要求的共享 checkpoint 时不得为 GUI 重建整套 family；实际模式限制以入口校验为准。
GUI 重载通过只证明装配可检查，不能代替场精度、飞行或性能资格。
候选场builder从独立`measured_source/source.fly2`读取粒子定义，保存IOB后恢复运行用`joint.fly2`，
避免`wb:save`覆写同名文件。批次合并收据绑定实际FLY2、逐批收据、日志及ID覆盖；
后处理只在内存组合发射证据并核验出生时间，不改写冻结准备输入。

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
| OA 组件验收 | [OA提供者入口](../../orthogonal_accelerator/simion/run_component_focus_workflow.ps1) | 显式使用本项目现有request／release；provider receipt不授予整机资格 |
| N=1 或 N>1 OA→MR完整飞行 | [直属oa_mr/execute.ps1](../../../integrations/workflows/oa_mr/execute.ps1) | 冻结装配plan、几何、镜、Stripe、OA receipt、P1/P2电压及一种场消费输入；资格见集成状态 |
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
[OA真实源与束团证据](PROJECT.md#oa真实源与束团证据)，不从历史配置推定。

解析电压链使用 [run_target_operating_point_chain.ps1](../analysis/run_target_operating_point_chain.ps1)，
从同一合同串接镜 exact-K 与双 Stripe 反演。P1/P2 分段射击继续使用
[coverage](../analysis/run_two_prism_segmented_coverage.ps1)、
[continuation](../analysis/run_two_prism_segmented_continuation.ps1)：continuation 只追踪
冻结的单一事件签名，理论覆盖点不能直接称为真实三维工作点。

### 控制器职责与普通S恢复策略

[downstream_workpoint_iteration.py](../analysis/downstream_workpoint_iteration.py)拥有物理残差、模型和有界提议；
[workpoint_controller_state.py](../analysis/workpoint_controller_state.py)统一计算电压档位、候选接受／回退、
档位复位及局部模型恢复状态转移。PowerShell负责身份验证、实际执行、冻结输入与检查点发布，不复制这些决策公式。
`Complete-StagedTrial`及其决策／provider核验helper显式接收Context；合同、目标、proposal、handoff、
run与artifact路径取自本次上下文，handoff复制后重绑冻结副本，不从同名脚本全局变量补取。

普通S局部模型恢复使用[local_model_recovery_policy.json](../config/local_model_recovery_policy.json)，
默认3轮、12探针预算；可由`-LocalModelRecoveryPolicyPath`显式选择经校验的策略，并冻结到本次run inputs。
步长与coarse／medium／fine的缩减比例仍由科学合同的`jacobian_relative_step_tiers`派生，
探针、预算和已接受锚点按检查点延续。该策略不用于下述prepared P/S分阶段控制；后者的候选预算和停止边界来自其冻结合同。
恢复版本与显式导入规则见[恢复与资源](#恢复与资源)。

### 实测源的分阶段P/S控制

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


IP实测源保持逐ID六维状态和仪器绝对时钟。分析由`measured_component_analysis.analyze_measured_component`
按原始ID和全部母群闭合，不能再套OA批次offset恢复ID；z=0观察面不自动成为接地端口或时间焦点。
需要检测峰宽与时间等效分辨率时，在原`peak_analysis`中保持公共KDE的方法、settings和定义，
声明`time_basis="instrument_arrival_minus_common_extraction_pulse_us"`及`common_time_reference`：
它包含源的`clock_epoch_id`、原生`native_timing.json`的标准文件记录`timing`和`field="pulse_start_us"`。
准备与实飞入口校验该记录的字节、SHA、epoch及脉冲先于全部交接时刻；所有检测命中减去同一个脉冲时刻，
不逐离子减交接时刻，也不把捕获／冷却等待计入TOF分子。默认诊断在`results/diagnostics/population/`
输出`detector_peak_samples.csv`、可计算时的`detector_peak_spectrum.csv`、英文PNG／SVG与metadata。
R仅表示检测幸存子群的时间等效值，和母群／交接群透过率同时报告；少于三命中或零方差时明确不可计算。

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

## 恢复与资源

跨项目完整束团执行和整批恢复的入口／资格见[集成状态](../../../integrations/docs/INTEGRATION.md#已准备ipmr联合飞行)。
receipt、状态表和Fly2必须是同一成功源run的唯一输出。
公共调度器选择资源和 batch，项目不设独立并发门槛；详见
[公共调度与恢复](../../../common/simion/README.md#调度与恢复)。

任何已启动且健康的本项目 SIMION worker 在父阶段失败或观察预算告警后继续自然完成；父流程停止启动新worker，等待已启动worker的原生终态并保留其日志。只有入口明示的硬超时或公共调度器确认的持续物理内存危险才可停止受管进程。

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

普通S恢复的日常状态只接受`recovery_policy_version=8`。旧v5／v6／v7仅在显式
`-ResumeParentCheckpoint`路径导入：先将原文件冻结到新run的`inputs/imported_recovery_checkpoint.json`，
再核对同一anchor／trigger并按当前谱系纠正证据，随后规范化为v8；原run及原探针记录保持不变。
v1–4和未知版本明确拒绝，不在日常prepare中猜测升级。新run同时冻结控制器源码与恢复策略；
改变策略不能静默重解释已有恢复状态。prepared P/S仍使用自身stage检查点，不能把此v8规则套到它的bootstrap。

native bank 的 `-TransactionCacheKey` 只恢复／复用指定事务；已发布 family 只读。
`-RecoverMembers` 指定失败成员；`-RecoverRetainedInventoryMembers` 和
`-CorrectPublishedInventoryMember` 仅处理有原 journal 证明的 inventory 问题，
不得借此重写物理输入、重建发布成员或伪称新求解验证。
公共 owner 负责单写者、库存、封存及退休；身份不符保留证据并停止，不静默重建。
运行中断保留受管 checkpoint，恢复复用仍有效的 payload 身份和容量记录。

长 PA 输入复用[公共短路径支持](../../../common/simion/short_pa_path_support.ps1)；
先查[已关闭的长路径结论](../../../docs/tools/SIMION_REFERENCE.md#长pa输入路径)，
不要另建项目私有实现。只读、Junction、硬链接或复制本身不保证 native family 写隔离。
published PA 不是 runtime 写目标；私有 family、standalone PA 的具体装配与封存由公共机制负责。
不反复复制／哈希已由受管只读机制保护的重型资产；容量、保留和清理由其唯一 owner 处理。

## 事件与分析

[mrtof_candidate.lua](../simion/mrtof_candidate.lua)及[mirror_cycle_counter.lua](../simion/mirror_cycle_counter.lua)
以 P2 后正镜转折定义快相位原点，后续每次真实镜转折增加半周期。
目标 K 与返回镜侧来自 `target_drift_period_ratio/fast_path_symmetry`，不在代码中固定数值。
中央 `z=0` 或提前 `y=0` 穿越仅作诊断；目标镜转折才产生严格相位返回。
返回应经 P2、必要的正镜转折后沿 `v_z<0` 命中 detector；只有解析镜区可以令 `v_z` 反号。

碰撞、程序拓扑拒绝、未知场支撑失败和未到达须分别报告，不能按终态坐标猜测部件。
实测源诊断以完整母群连接原交接状态、方向能量、首缺观察面及几何接触候选，输出`loss_acceptance.csv`；
无交接态或未到达观察面保留缺失，不补造轨迹。提前碰到detector仍不等于完整返回。
`mirror_domain_samples.csv`和`mirror_x_boundary_crossings.csv`保留细镜窗口内外状态及有符号跨界；
跨界本身不证明电场跳变，质心容差不作为整束接受度门槛。轮廓投影不冒充真实布尔截面。
缺 target-K 或完整返回的观察不得补造有效 Jacobian；完整通过与阶段观察分开保留。
`sim_segment_global=1` 用于捕获 PA 外终态，仍须逐粒子核对唯一结束和日志完整性。
[run_iob_flight.lua](../simion/run_iob_flight.lua)要求同名 Program/Fly2/operating-point/voltage-map/
mirror-cycle-counter 伴随文件，实际源必须匹配冻结字节；zero-exit 错误日志仍判失败。

同一进程先构建／重载IOB再Fly时，launcher按`simion.pas[1..#simion.pas]`的完整`path`
复用已加载的普通碰撞PA：零匹配才open，一个匹配复用，多匹配在Fly前拒绝；不只比较basename。
新载入与复用都只在内存设置`refinable=false`并保留`--remove-pas=0`，不保存、关闭或重新求场。
依据为[官方PA接口](https://simion.com/info/lua_simion.pas.html)及本机SIMION 2020 Help的
`pa.filename`／`pa.path`定义：前者仅为basename，后者为完整路径（8.1.1.18加入）；Help示例打印
`c:/temp/test.pa test.pa`。`examples/field_array/solidworks_to_pa.lua`说明`refinable=false`
（2026-10-16查阅）。launcher记录库存的实际`filename`、`path`及匹配结果，供真实运行核对；
冷启动及旧`.pa0`路径保持原行为。

检查已准备的工作台时，沿同一 launcher 使用 `load-workbench`，先复用上述碰撞预载，
再调用 `wb:load` 和 `wb:load_particles`。它只打开实例、Program 和指定粒子，不 Fly、
Refine、Fast Adjust 或保存 PA；装载后还核对碰撞 PA 仍是原来唯一的 RAM 对象且不可 Refine。
不要直接打开引用可 Refine 碰撞 PA 的 IOB，否则会绕过这项预载。先取得公共资源准入，
再使用 SIMION 2020／8.2 支持的交互 Lua 形式；以下路径必须指向已准备的工作台及其冻结来源：

```powershell
& '<SIMION-2020>/simion.exe' lua -i '<runtime>/run_iob_flight.lua' `
  '<workbench>/joint.iob' '<workbench>/joint.fly2' load-workbench
```

第三参数省略时仍执行同一 Fly 操作，粒子路径仍由第二参数或同名 Fly2 确定。
`lua -i` 是官方交互 GUI 形式，不能仅从省略 `--nogui` 推断脚本返回后的驻留行为。
官方依据（2026-10-27核对；在线标题较新，所用API均已在本机8.2.0.11支持）：
[8.1.2.8变更记录](https://simion.com/info/changes.html)明确交互形式，
[Workbench API](https://simion.com/info/lua_simion.wb.html)列出装载和8.2的粒子装载，
[CLI说明](https://simion.com/info/command_line_interface.html#fly-remove-pas-d)定义RAM保留选项。
该装载接口只保证同一运行设置；普通 PA 场查询仍不代表 `efield_adjust` 回调场，
不因此改变原生结果、数值精度或正式资格。手动 Fly 会写输出，仅为此准备独立可写的工作台
控制／日志目录并核对永久PA绑定；未变大PA继续只读复用，不因GUI装载而复制或重新求场。

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
[场响应工程里程碑归档](history/20261008__field-response-engineering-milestone.md)；
其他历史入口由[项目导航](../README.md#历史补充索引)集中索引。
旧历史中的`simion/README.md`为当时活动说明路径；当前说明统一迁到本页，
`加速器选择与接口准备`和`事件与分析`锚点保留。冻结历史正文与运行输入不改写。
官方 API 与已验证公共边界见[SIMION 参考](../../../docs/tools/SIMION_REFERENCE.md)；
本次结果只从实际冻结 manifest 和原始日志读取。
