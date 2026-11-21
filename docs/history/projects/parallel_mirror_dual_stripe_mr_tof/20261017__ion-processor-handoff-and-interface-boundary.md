# Ion Processor 状态交接与局部场接口修复里程碑

DOC_STATUS: ARCHIVED_READ_ONLY

返回[项目导航](../../README.md)；当前决策以[PROJECT](../PROJECT.md)为准。
本文冻结2026-10-17的阶段演进；具名run的输入、manifest、日志和结构化收据仍是数据权威，本文不是第二份机器合同。
里程碑关闭的是“97实测出口可重放交接、负结果保留、局部fine／covered电势跳变定位并消除”；Prism／Stripe工作点和新N100验收仍开放。

## 来源与复核口径

迁移来源为`projects/parallel_mirror_dual_stripe_mr_tof/docs/PROJECT.md`当时WORKTREE正文，
完整源文件SHA-256为`94ad84a4d176876a00ea1fda572f9272c118bc1e8fe28b6dfdfa74793099484e`；摘录从“加速器接口准备现支持”起、到“主线为对称会聚双镜”之前，
其原始UTF-8文本（保留原换行）SHA-256为`804db0c3ad21ef8e46d3add450e24df1976ce89b338b492ccaef8c369974db51`。
下方原文仅将相对链接按history多一层的目录深度重定位；其中“当前”“下一步”均指迁移时点，后续修正由本篇下一节及现行PROJECT限定。
没有复制或改变原run输入、PA、CSV、损失证据或已冻结history。

## 局部接口缺陷的受控关闭

旧同点审计001500发现z=−0.25 mm处fine电势约11.55 V、covered约0 V，与234747事件账本的−11.474428 V突变相符。
002400的实际电极标志／电势节点排查确认出生与接口插值支撑为真空；covered保留E14高压金属及槽内非零场，
因此不能把这两处近零电势解释为接地金属，也不能归因于IP高压全部漏装。
003000只将fine求解下界−0.5→−20 mm、active下界−0.25→−10 mm，其余物理输入和共同场身份保留。
新的同点比较与实际轨迹点账本分别支持新接口连续：前者Δphi≈2.053×10⁻⁹ V，后者H/q差≈−2.06×10⁻⁹ V。
因此原局部约11.47 V跳变由局部数值域及其衔接引入，扩域已消除该已测缺陷；这不是对整条轨迹收敛性的替代证明。

004900重新发布当前加载包；005200以同源构造质心、同实际电压完成49快速转折，首次正镜y=−3.092355 mm、
慢转折y=339.201449 mm、返回相位K≈3.333337，仍偏离y=0／360 mm及K=24.5设计。
005055使用该候选自身birth为基准：source H/q=4364.533956 V、P1差+0.079784 V，后续237事件跨度0.041215 V。
源K(mean v)与mean K、冻结独立IP场与MR场的边界差异继续分开记账；没有修改97出口速度或以Psi替代phi。

005908依据实际clean点的phi与Ex、实际S1及冻结MR宽度／倾角生成新版本工程目标，两项严格导入和25项manifest核验通过。
clean参考Ez=4359.320021／Ey=5.213248 eV/q；保留Ws=5.374387143 eV/q、慢转折360 mm与K=24.5。
原0.01°角容差的能量映射重算为0.0524898 eV/q；它约束中心工程参考，未声明N100能量达标容差。
母源版本投影只调整设计参考的mother_source_receipt输入，原设计与原始母源身份均冻结保存，几何与源速度不缩放。
后续仍为原P→S相位四观测／三控制→P→完整轨迹→原N100，不新建三残差闭合；S2保持接地。

| 已完成证据 | 机器入口及适用范围 |
|---|---|
| 003000扩域场 | [结构化记录](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_003000__build__simion__ip-fine-domain-extension/results/field_binding.json) |
| 004700同点审计 | [结构化记录](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_004700__analysis__python__ip-fine-extension-interface/results/patch_interface_audit/patch_interface_comparison.json) |
| 004900 joint.iob | [结构化记录](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_004900__analysis__python__ip-fine-extension-workbench/results/joint_workbench/runtime/joint.iob) |
| 005200构造质心N1 | [结构化记录](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_005200__sim__simion__ip-fine-extension-centroid/run_manifest.json) |
| 005055实际场事件审计 | [结构化记录](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_005055__analysis__python__ip-fine-centroid-field-audit/results/event_phi_audit/event_energy_field_audit.json) |
| 005347实际轨迹点审计 | [结构化记录](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_005347__analysis__python__ip-fine-raw-interface/results/patch_interface_audit/patch_interface_comparison.json) |
| 005908冻结目标 | [结构化记录](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_005908__analysis__python__ip-centroid-target-authoring/results/target_authoring/target_authority.json) |

旧N100继承OA电压后的负结果仍有效：r05下游97/97自然终止、无P2注入，原100母群的三颗上游损失也保留。
其failed身份源于出生观测时钟核验，不抹除真实飞行；恢复仅派生诊断出生时刻，原日志不改、不重飞。
记录见[原r05完整manifest](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261016_200610__sim__simion__ion-processor-mrtof-joint-n100__r05/run_manifest.json)与[纯后处理恢复manifest](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261016_202353__analysis__python__ion-processor-joint-n100-diagnostics/run_manifest.json)。默认各时刻空间图和全部损失证据随模拟自动生成；能量仅报告差异，不给未声明的验收PASS。

此前17组旧PA／surface已沿公共owner处置释放99,342,635,580 B，冻结重建输入、小证据、唯一损失及用户GUI来源保留。
该阶段没有新增PA删除；历史IOB引用已退役PA时必须按冻结输入重物化，历史文字引用本身不意味着仍可直接加载。

## 迁移原文：接口准备、首轮负结果与因果排查

以下保留迁移前叙事，便于追溯失败及恢复边界；其中已过时的加载包、待验证扩域和测试数量不覆盖上述阶段终点。

加速器接口准备现支持明确选择`orthogonal_accelerator`或`dual_pressure_rectilinear_ion_processor`，默认OA不变。
准备入口与可执行边界见[操作说明](../../simion/README.md#加速器选择与接口准备)。
IP独立器件的用户GUI检查已通过并暂封存；MR需求不锁定其旧出射能量或几何。
接口准备阶段已完成实测源运行适配及场装配输入；当前按用户要求开始N100联合验证。从冻结040845工作点解析历史OA轴向出口种子4372.010347796 eV/q、y=-55 mm，
而非用当前作者合同的默认y=-50 mm或将理论净增益4000混作实际轴向目标。
允许后续调整IP抬升／引出电压、几何和时序，以实测出口匹配MR；不能缩放已有CSV伪造匹配。
准备包保留97个实测出口状态和100母群census，
按显式平移(0,-225,0) mm注册，绝对时间、速度、能量、原ID及三损失保持。
IP分支现已有实测FLY2／Lua初始化、原ID事件与完整母群分析、四角色IOB装配器，以及移除旧OA后的新父场／局域GEM输入。
耦合采用出口状态交接，不是同一Fly内从HP捕获到MR反射的连续求解；旧完整trial仍沿OA入口使用。
实测源逐粒子保留出生偏移及同一绝对时钟，既有三损失继续进入100母群分母。

MR匹配候选将抬升由4000改为4480.043790844389 V，按既有实测轴向能量差给出一阶种子。
LP长度80→61.5 mm，入口仍为器件world y=130 mm，下游端由210缩至191.5 mm，聚集／引出中心仍为170 mm；
尾端透镜装配后最大y=-33 mm，与原中央屏蔽件保留1 mm设计间隙。P1罩面延伸终点改为z=5.3 mm，
其余MR实体／孔槽保留。镜局域计划继承完整求解域，不将裁剪消费域冒充求解域；20路MR电压来自冻结实际运行侧文件。
原独立器件配置及用户验收GUI包不改写；候选配置可交给原器件自动并发入口独立验证。
新独立N100运行`20261016_152536__sim__simion__ion-processor-mr-match-n100-r02`已完成，
公共资源调度器自动选择最多9并发，10批100终态完整闭合，97引出，损失24/64/80全部保留。
出口z=0处Ez=4364.647136±44.654000 eV/q，总动能4364.822522±44.568125 eV/q（人口sigma）。
Ez均值相对名义4372.010348差−7.363212 eV/q；用户明确只报告差异，不设能量达标容差。
相对旧OA同名z=0记录的总动能4377.698809±46.821318 eV/q，新IP总动能均值差−12.876287 eV/q；
该原始动能差尚未补偿两种装配观察面的实际电势，不能直接当作总能量匹配残差。
冻结合同未声明IP的同面总动能目标，比较收据对此记录null，不把OA释放Ey加到轴向种子上另造目标。
旧独立器件的功能energy检查通过不构成MR能量验收；17组英文图和完整损失证据由新N100自动生成。
新装配场已由原生公共provider完成5层重新求解及3个占据／检测器PA，119项输出通过完整manifest核验；
联合IOB已完成真实保存／重载及三处重叠选择探针；真实联合飞行进度见下述独立记录。
初次新场`20261016_153652__build__simion__ip-mr-field-candidate`在父场Refine前失败：
检测器单位网格实际保存mode −1、32字节头，预测误按56字节头而多24 B。
已修正普通PA长度公式并保留严格校验，以新身份`20261016_154142__build__simion__ip-mr-field-candidate__r02`重建；
失败输入与日志保留，可重建碰撞PA沿公共机制退役。该错误不属于电极、时序或离子运动失败。
新场求解完成后的首次公共容量封存因账本读取／验证失败退出；当前账本复验有效，
确认写进程退出后沿原公共命令重试已成功，ready／pin保留33,986,852,774 B，无重求场或改写科学证据。
该次失败的具体瞬时原因未被日志记录，不断言永久账本损坏。
静态准备不授予旧P1/P2/Stripe工作点对新源的匹配、间隙网格精度或时空聚焦资格。

IP近零慢轴动能属于器件设计，不按旧OA释放Ey判失配。冻结040845第一Prism入射参考方向为[0,0,−1]，
P1、负镜预反射和P2共同改变yz方向；P2后参考面z=33 mm要求vy>0、vz>0，不能与IP出口混用。
静电段守恒K/q+phi，不是各轴动能；不同位置比较总动能须计入实际电势。
新装配保留完整20路MR电压，P1/P2为ID16/17（向量下标15/16），原候选p1/p2调节入口仍在。
联合验证从实测6D出口传播后检查设计位置／方向／镜区状态；继承OA电压的首轮已完成，当前按用户要求重新闭合IP的Prism／Stripe工作点。
当前基线加载包为[203535 joint.iob](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261016_203535__analysis__python__ip-joint-energy-audit-workbench/results/joint_workbench/runtime/joint.iob)，
54项输出通过完整manifest核验，含实际接口能量／电场审计及修正后的初始化程序；四实例为global、corridor、IP精细碰撞、detector，三处优先级探针均符合预期。
配套实测源来自152536新N100，保留97出口状态及完整100母群；PA持久引用154142新场，不复制或改写场文件。
该IOB从出口状态交接开始，不包含同一次Fly内的HP冷却；保存／重载不代表联合飞行、GUI或物理匹配验收。
原设计输入为[141429 IP准备包](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261016_141429__analysis__python__mrtof-accelerator-interface-ip-f38b8fc3/results/joint_flight/joint_preparation_receipt.json)，
59项输出核验记录保留。首次最终绑定184053因读取器漏查manifest已绑定run_config中的输入记录而失败；
已修正原验证入口并覆盖输入／配置篡改拒绝，新身份184610重新越过该点，未改写原设计包。
[140930 OA对照准备](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261016_140930__analysis__python__mrtof-accelerator-interface-oa-fcd28a8a/results/accelerator_interface_preparation.json)
保留默认选择。中间准备曾因同秒默认run ID冲突失败，失败记录保留；默认ID现含provider及随机后缀，两个分支并行准备已通过。
接口／源／场准备等74项专项测试通过；另13项装配计划及5项联合准备测试覆盖OA四角色、IP三角色、实际mock重载／优先级和非法输入拒绝。
旧单分支源码断言已更新为两分支合同；这些纯分析／普通Lua测试不代表真实SIMION载入或飞行验收。
全量分析1327项检查（9项跳过）发现1条旧夹具截取Lua分支不完整；已修正测试边界，相关12项定向回归通过，
生产字节和准备包不变。该轮L2失败日志保留，未为取得绿色状态重复整组检查；不将定向修复表述为完整L2重跑通过。

### IP联合飞行的执行边界

联合验证保留原N100母群：97个实测出口进入MR，入口损失ID24/64/80仍进入完整分母；
不重新抽样，不将下游97称为重新释放N100。合同继承040845的Q8与4 ns最大步长，
仅启用0.1 us记录桶和出生／终态强制记录；空间图的共同时间从实际记录自动选择。
默认诊断包含Prism相空间、分时空间云和全母群损失，损失文件保留每个粒子的全部原始日志行及行号。
P2的z=33 mm参考面、孔径和方向是设计检查位置；未穿越的粒子保留为缺失，不能填零角度或能量。
中心轨迹的角度／位置容差不作为N100逐粒子的验收门槛，能量仍遵守用户“只报告差异”的要求。

真实首批发现并修正Lua模块作用域：普通loadfile模块不直接访问Workbench的ion_*变量，
由segment.initialize传入序号并在Workbench环境赋值完整初态；绝对时间和源字节不变。
192703启动失败为零粒子，不作为运动损失。193407/r03和195514/r04各自然完成首10后，
因公共内存准入等待而正常中断；二者不是N100结果。两次首10的全部1369条事件／轨迹行逐行完全一致。
两镜只消费既有1.28 mm存储支持域，源PA的51节点、真实0.02 mm镜区z网格和全求解身份保持；
内存消费33节点不改active范围或重新求场。真实启动峰值仍约39.76 GiB，
仅凭crop后nx变小不能声称释放了进程内存。用户随后明确要求去掉额外安全余量、改为warning；
该政策由公共SIMION调度层实施，不建立项目私有预算或手改资源画像。

真实完整下游飞行为`20261016_200610__sim__simion__ion-processor-mrtof-joint-n100__r05`：
公共自动调度选择CPU容量9、内存容量1；首10＋余87均自然退出0，97个原始终态完整合并，
第二批没有再被内存准入等待阻塞。两批Fly墙钟61.960／78.662 s；波收据93.445 s是执行器后续波计时，
不能把它当作包含首批观测、初始化和全部后处理的总耗时。
97颗均通过P1并完成负镜预反射，P2入口／z=33 mm参考面、首次正镜转折及检测器均为0；
下游97颗终态均splat=-1、无timeout；连同上游3颗，完整N100当前无设计注入。
这不是独立IP的97颗引出失败，也不证明应改变IP慢轴能量。

| 下游数量 | 原始终态与冻结连续几何相容的位置 |
|---:|---|
| 38 | z约−107 mm、位于负镜内罩4 mm狭缝之外 |
| 54 | P1接地罩18：41颗孔上边y约−35、11颗前端z约−100、2颗侧壁x约−2 mm |
| 3 | P2接地罩20前端z约−97 mm，ID37/81/98位于长槽之外 |
| 2 | 返回IP的E14屏蔽板z约6.3 mm，ID47/62位于狭孔之外 |

上表是连续几何对应，不从占据PA数值推断电极身份；95颗终止instance2、2颗instance3。
未作Prism电压扫描或单因素结构对照，不能据此断言电极结构本身错误；
已证实的是当前继承OA的Prism工作点没有完成新源的设计注入，P2后位置、角度和yz能量均无到达样本。
原r05因自动诊断出生时钟核验失败而以failed封存，90项输出完整核验通过，全部真实轨迹保留。
97颗出生6D与源逐double一致；96条初始化采样时间为共同epoch，而实际FLY2保留各自出生偏移，
最大差0.0195661336293 us。该观测语义问题须显式保留原始值、依据冻结TOB派生诊断出生时刻，
不能改写原轨迹或以放宽物理容差处理，也不因纯后处理修复重复飞行。

恢复分析`20261016_202353__analysis__python__ion-processor-joint-n100-diagnostics`已沿公共恢复入口完成，
167项输出完整核验并封存，原始合并日志与r05逐字节一致；首10与r03的1369行轨迹／事件仍完全一致。
默认英文图为Prism相空间、自动时刻空间云和完整母群损失；保留97颗下游逐ID原始行及3颗上游损失。
终态发布曾触及Windows命令行长度，公共manifest写入器现通过临时JSON输出列表传递文件清单；
原发布失败摘要保留，仅重试发布，没有重新飞行或重绘科学结果。

203535的实际接口审计同时采样独立IP场与联合装配场。97颗出口平均K/q分别与各自phi相加后，
均值为4420.037337／4374.303354 V；两场delta phi均值−45.733983 V，去常数后的最大偏离0.060462 V，
电场向量差的最大范数284.244010 V/mm。因此两场接口差异含真实局部场差，不能只视为电势零点改变。
冻结独立IP的local y范围为−4…10 mm，出口local y=9.8距显式人工接地上脸仅0.2 mm（两网格）；
该脸注册为MR z=−0.2 mm。联合接口位于最高优先IP精细场的active内，距其实际zmin面0.5 mm。
质心source Ez=−276.770715、joint Ez=+7.459740 V/mm，近边界法向梯度差与上述审计一致，
但没有单因素边界重求对照，不把相容性当唯一因果证明。当前继续以冻结出口6D为声明的下游功能源；
不授予从捕获到MR的连续电场资格，也不通过修改已有速度补偿接口差异。
独立质心probe取97个出口位置、速度及绝对时间的均值，K(mean v)=4364.533956 eV/q，
与mean K=4364.822522相差0.288566 eV/q；联合phi=9.492287 V，probe H/q=4374.026243 V。
probe是闭合探索射线，不冒充原母群中的ID1，最终仍使用原97出口及全部100母群验证。

新工作点按速度矢量及K/q+实际phi守恒处理，Prism负责改变方向，轴向和慢向动能不分别守恒。
新IP初始Ey很小不改变分析器所需的慢分量。首轮保留既有MR有效慢作用设计目标Ws=5.374387143 V/q，
它的数值历史上与OA释放能量相等，但不是新IP源的能量门槛；cleanEy=5.169057531是指定参考面的设计Ky及角度容差映射。
新源采用实际总能量与同点phi、Ex解释快慢分量和角度，Prism负责方向分配，源6D保持。
继续原P预闭合→S／返回相位→P重闭合→完整轨迹→N100步骤，保留镜几何、y=360 mm慢转折和K=24.5设计。
有效慢势Psi不是实际静电phi；同步更新其快能参数时冻结新的工程参考版本，不继承旧资格。
只有真实回闭证据说明原工程目标不适用时才重新派生或重锚，不能预先将L=340 mm旧种子重标为L=360 mm新解。
当前P1约+342.968822 V为拓扑种子，P2暂保留−186.472536 V；新源闭合尚未完成。
P1/P2响应已按154142实际五层、镜区z=0.02 mm网格重新求解并封存，不复用不兼容的旧OA响应。
当前单Stripe设计的实际变量仍为P1/P2/S1，S2接地；这是原流程的控制量，不能据此另建三残差闭合。
P阶段闭合首次正镜位置及有效慢作用，S阶段沿原四观测／三控制约束模型处理返回位置和相位，随后P重闭合及完整验证。

真实构造质心N1 `20261016_234747__sim__simion__ip-prism-centroid-path`已完成49次快转折，
首次正镜y=−3.081580 mm，慢转折y=339.283900 mm，最终碰撞P2前罩；它不是原母群ID1或N100验收。
该轮同时确认碰撞PA预加载须按官方完整`path`识别已驻留实例，避免同进程重复打开；原始失败与修复后日志均保留。
事件实际场审计发现birth H/q=4374.026243 V、P1为4362.551815 V，差−11.474428 V，
而后续237事件H范围仅4362.522939…4362.564833 V。
[同点实际PA比较](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_001500__analysis__python__ip-patch-interface/results/patch_interface_audit/patch_interface_comparison.json)
的25项输出完整核验通过：z=−0.25 mm接口处IPfine约11.55 V、covered约0 V，与能量账本跳变相容。
这是实际场衔接差异，不能靠Prism闭合吸收；受影响的闭合暂缓。
后续`20261017_002400__analysis__python__ip-support-nodes`的522个真实节点及32项输出完整核验通过：
出生与接口支撑均为真空，covered仍有3580 V的E14金属及非零槽内电势，排除这两处落入接地金属和IP高压整体漏装。
下一受控数值域测试仅将fine solve下界−0.5→−20 mm、active下界−0.25→−10 mm，保留实际父场、全部电压、几何与源。
每次以自身birth的K/q+phi为能量基准；尚不声称扩域修复成立。
该比较只读查询，无Fly／Refine／GUI，不授予匹配或数值收敛资格；源6D及MR设计目标保持。
为新响应腾出容量，17组无活动或计划消费者的旧OA响应／中央视图／早期候选PA与surface已通过公共owner退役，
逐run收据累计释放99,342,635,580 B；保留原冻结重建输入和小证据。当前032031细镜、134039父／中央、
234000碰撞载体、OA与IP用户包、152536源场、154142联合场及全部唯一损失证据继续保留。
退役旧IOB所引用的场须按冻结输入重建，不能再把旧manifest当完整可加载资产。

