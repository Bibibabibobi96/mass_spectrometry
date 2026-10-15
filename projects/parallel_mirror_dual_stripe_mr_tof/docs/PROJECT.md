# 开放路径平行镜双条带 MR-TOF 项目状态

返回[项目导航](../README.md)。推导见[理论索引](theory/index.md)，机械交付见[CAD](CAD.md)。
本页只维护当前决策、有效证据和未完成动作；具名运行的冻结输入才是参数权威。
原有5225行混合工作区时间线完整保存在[本次只读里程碑](history/20261015__converging-field-and-performance-milestone.md)，不冒称已提交版本。

## 当前决策与完成边界

主线为对称会聚双镜＋五次项偏置Stripe＋保留实体的接地线性Stripe；K=24.5、加速器y=−55 mm。
原生SIMION自动闭合、响应组合和束团飞行已经可用；COMSOL进行同几何、同电压固定场复现，
尚无新场上的空间闭合或高斯束团性能，两条链资格分开。

原生细档高斯σEy=0.15／0.2 eV的N100分别为R≈101399／80929、98%／95%，均为有限工程结果。
COMSOL各次完整受控N13均0/13检测器命中，尚未获得收敛或性能复现资格。
本轮[固定场与求解状态里程碑](history/20261015__fixed-field-reproduction-and-solve-state.md)保存已完成比较、失败及恢复证据；
旧producer专项见[退役里程碑](history/20261015__producer-retirement-milestone.md)，两条链必要资产继续保留。
匹配求解控制后的两档FEM整程相对时间差已缩小，但仍改变空间返回；最新阶段见[匹配求场与轨迹对照](history/20261015__matched-solve-and-trajectory-comparison.md)。
同入口单镜对照已完成：出口相对中心时间两档最大差0.05853 ns，但慢向速度仍差0.003768 mm/μs，
说明本段计时接近不等于后续慢向返回稳定；尚不投入高斯N100。

## 输入权威与物理定义

当前电压来自[冻结闭合候选][native-anchor]，下表仅便于阅读；完整电压、几何和消费者按该运行输入重放。

| 部件／参数 | 当前值 |
|---|---|
| P1 / P2 | +191.69798504788915 / −186.47253641442782 V |
| 五次项Stripe（11/12） | −26.98736945139317 V |
| 线性Stripe（13/14） | 0 V；实体仍保留 |
| 两侧镜A–E | 0 / −5929.660769425788 / −2568.4173725265146 / +4162.7537535912525 / +6003.305171198471 V |
| 单镜倾角 | 0.025688744787259285°；两镜会聚角为其两倍 |
| 正镜旋转枢轴／负镜 | [0,0,102] mm／关于z=0镜像；正镜Rx=−θ、负镜Rx=+θ |
| K及目标事件 | 24.5；49个快速半周期，不是任意终止计数 |
| 当前TE1标量坐标 | −34.10982644173019；后续增量从当前坐标出发，不能重复施加绝对值 |

倾斜的是平面镜电极，不是将其改成曲面；正负镜与Stripe保持设计镜像，整机OA、Prism及检测器并非z镜像。
OA位置变换只施加一次；P1接地罩按原截面延长至OA出口前1 mm，不改变P1/P2尺寸及其绝缘间隙。
镜外侧E盖板保持E电位，不接地；不同电位实体不能接触。当前结构不是论文装置的完全复制。

C0为指定工程假设：完整内表面x∈[−162.5,162.5]、y∈[−242,558]、z∈[−425,425] mm。
半模型五个外面接地0 V，x=0为对称面而非接地壁；相关OA接地罩、理想网格、出口及检测器纳入装配。
C0不是已经确认的机械腔体；省略它的开放BEM与该边界模型不同，尚未证明对性能可忽略。

两区加速器使用线性场，理论出口z=0为初始时间聚焦设计面；实际束团仍需诊断，不因理论目标自动通过。
TE1控制局部释放z一阶时间响应，不自动校正Ey、横向偶响应、宽幅z或接受度；改镜后须自动重闭合P/S。
种子周期与实际镜周期区分记录，不在每次TE1中静默重定义几何或用旧轨迹Jacobian跨锚外推。

## 真实源与束团证据

源中心[0,−56.05182899425077,32] mm，沿+y释放；圆柱高度1 mm、半径0.5 mm；质量524 Da、电荷+1、共同出生时刻。
慢向动能均值5.374387143093758 eV。高斯σ是释放事件处动能标准差，不是速度sigma；
当前σ=0.2为主条件，0.15为对照，0.3为压力测试。位置与标准化能量取同一1000颗母样本的前100颗，
不重新居中有限样本均值、不裁尾、不缩源。角宽仍为零，空间电荷、真实出生时间宽和制造／探测器影响未覆盖。

纯体积N100与受控N13分别报告：N13含中心、z±0.1、Ey±0.05、x±0.1、y±0.5、x±0.5、z±0.5 mm参考。
受控ID1为名义中心；高斯ID1是体积样本，不能误称源中心。共同幸存者仅用于配对诊断，不能替代完整源性能。
σ0.15和0.2的母样本身份、相关性与实际有限样本均值分别见[源收据15][source15]和[源收据20][source20]。

以下均为同一候选电压、镜区z=0.02 mm场、4 ns/Q8、common KDE；损失全部保留。

| 高斯σEy/eV | 平均TOF/μs | KDE FWHM/ns | R | 命中／释放 |
|---|---:|---:|---:|---:|
| 0.15 | 764.216444815 | 3.768379855 | 101398.541848 | 98/100 |
| 0.20 | 764.216316535 | 4.721538636 | 80928.736944 | 95/100 |

原始结果分别为[细档σ15][fine15]和[细档σ20][fine20]。σ15损失49/98于P2接地件；σ20另损失7/21/56于P2接地件，
49于五次Stripe12、98于接地线性Stripe14；这些结果不等于所有尾部均有接受裕量。
镜区z=0.04→0.02 mm后，两组峰宽分别改变−0.005991/−0.005196 ns，命中及损失身份不变；
同粒子相对高斯ID1的检测器时间最大变化0.029653/0.029147 ns。平均公共TOF漂移约+0.094 ns，单列而不算作峰宽。

同源σ0.2历史平行镜78%／R19217与会聚候选95%／R79987有明显差别，但几何、电压、场表示和步长同时变化，
不能把全部改善独立归因于镜倾斜。[配对证据][parallel-pair]保留恢复20颗、新增损失3颗及共同命中75颗。
历史均匀Ey全宽0.1 eV、σ≈0.0289 eV的结果不是高斯σ0.1或0.2的性能资格，不跨采样／峰宽口径精细排名。

## 活动原生场与消费合同

正常入口仍为[原trial](../simion/run_two_prism_trial.ps1)、[原staged](../analysis/run_downstream_workpoint_iteration.ps1)、
[自动候选链](../analysis/run_native_candidate_chain.ps1)；场由`simion/run_native_static_field_provider.ps1`
和`analysis/static_field_binding.py`接入，不另建手工闭合器。
这些场接口及自动链仍有未发布的工作区改动；本页记录本机冻结证据，不表示干净Git检出已具备整套新实现。

| 场层 | 求解范围／布局（mm） | 各轴网格间距（mm） |
|---|---|---|
| C0父场 | 完整半外壳及相关装配 | 0.50 / 1.00 / 1.00 |
| 中央局域场 | [0,−100,−325]至[22.5,390,325] | 0.25 / 0.25 / 0.10 |
| 正负镜局域场 | x=0..2，y=−65..360，z=90..324及−324..−90 | 0.04 / 0.20 / 0.04（工作）或0.02（细档z） |

局域五面边界继承相同电压下父场；镜域先完整求解后裁剪存储x≤1.28 mm，实际启用x≤1 mm。
“完整域求解后裁剪”不等于在裁剪面重新Refine；多层优先级及碰撞载体按冻结binding，而非普通GUI云图推定。
新规则网格间距均为0.01 mm正整数倍，最小0.01 mm；历史非整数档冻结保留，不静默取整。

工作场[163135][native-field]复用父场与中央场、两镜Refine约553 s，建场/refine/裁剪约717 s；
含排队总时2031 s。细档[032031][fine-field]两镜Refine约1637 s，总2018 s，约13.14 GB，峰值内存约22.04 GiB。
它们是可用资产，不要求每个调压点重新求解；退役必须同时检查当前、下一消费者及GUI引用。

所有层显式Refine convergence=1e−5 V、fractional表面；默认0.005 V是指导值，不能恢复成项目硬约束。
同网格历史默认→严格产生重要响应变化；1e−5→1e−6在旧档检测器相对时间最大变化约0.025 ns，
仍不是当前所有轨迹的总误差界。实际Delta/迭代记录继续保留，不把停止参数直接等同于真实场误差。

正常最大步长4 ns、Q8；已测N13的4→2 ns相对检测器变化约0.00154 ns，时间210.6→384.7 s。
该历史证据支持当前工程默认，不自动授当前高斯尾部完整积分资格；最终候选仍检查返回状态和终止身份。

响应组合复用已有`analysis/static_field_binding.py`与`simion/scalar_field_adapter.lua`。
电势对电压线性、轨迹不线性；负权重允许，记录误差放大指标G但不将其当误差界。
当前S1 y360响应兼容163135；旧P1/P2/TE1响应仍含y350边界，不能绕过兼容检查接入新y360，
细档z0.02也不能直接套z0.04响应。只补实际闭合所需成员，不以响应库重建取代物理决策。

自动链先P再S；当前converging_clean_phase_energy使用首次正镜位置及清洁状态慢向能量，旧P2角度保留诊断。
P位置0.1 mm、能量0.0523430183 V/q、S两位置各0.1 mm；S1/P1/P2约束联合修正，接地S2不放开。
可信预测可取100%预测步；实测不符才有界回退，缺事件不造Jacobian，有明确有限停止条件。
当前中心四项通过，但P位置约+0.099999 mm贴近容差边缘，不等于稳健孔径裕量或跨网格闭合资格。

## 电场表示与数值资格

原生细档检测器峰宽及身份已经稳定到上述已测量级，但受控N13慢转折最大差仍约1.203 ns，
慢返回y=0约1.083 ns并有额外穿面记录。应按相同事件、方向和分支配对，不能宣布全轨迹数值收敛。
约0.2 ns是十万目标的总体初始工程预算，不是每环节独立预算，也不是探索性调焦统一硬门槛。
中心共同TOF平移、端点响应、两档差值均不能直接当FWHM或总误差上界。

COMSOL采用完整C0装配独立求场，不再沿用旧SIMION donor；实际消费仍为
COMSOL标量电势→规则PA→SIMION求导／插值／窗口选择→原飞行入口，不是直接FEM原生插值。
网格、求解停止、导出表示、窗口交接、积分及事件分别控制；不追求远离束路的尖角场处处相等。
两种场源共用trial、批次调度、事件诊断和发布；差别在场provider及binding，不另建COMSOL闭合器。
本轮135800消费四窗单工作点场，响应项为0，未验证当前COMSOL响应组合；新场空间闭合也尚未执行。
当前固定场导出／飞行已实跑；通用COMSOL改压provider仍使用旧sol1/std1及单窗来源合同，
不能宣称已适配当前mesh3/4多窗来源。相关活动源码尚有未发布依赖，干净检出复现资格未关闭。
外部场回调的普通GUI场查询不等价（`gui_field_queries_equivalent=false`）；保留IOB不代表云图显示实际消费场。

| 有效COMSOL对象 | 当前结果与用途 |
|---|---|
| [匹配mesh2][matched-mesh2] | 21076275四面体，Q2、CG＋AMG、rhob40000；32次CG、runAll819.263 s，总940.530 s |
| [mesh3重求][stopping-control] | 24023776四面体，匹配控制；38次CG、runAll880.423 s；同控制40点重求已可重复 |
| [mesh4局部最长边细分][mesh4-longest] | 30697694四面体，保持控制；44次CG，runAll1564.073 s；完整运行1880.077 s，峰值约41.83 GiB |
| [匹配mesh2四窗导出][matched-export] | success/full20、公共ready；总1608.874 s，查询合计1546.783 s；无新求场 |
| [匹配mesh2 N13][matched-n13] | success/full24；原调度器1 worker、飞行波次480.594 s；原源／电压／4 ns/Q8 |
| [配对分析][matched-pair] | 纯分析0.445 s，无新增商业计算；FEM间15项、细档native对照9项登记控制全部相等 |

实际导出沿[冻结四窗定义][mesh1-export]：base 0.25/0.25/0.10 mm，正负镜0.04/0.20/0.04 mm，
慢返回0.10 mm三轴；优先级正镜→负镜→慢返回→base。保留原生碰撞实例、单位、坐标及有效掩模。
基础窗5664个未知节点保持无效、另三窗全有效；须以实际轨迹支撑判断影响，不能补零或计作物理损失。
规则PA更细不自动等于FEM更准确；两来源共用追迹并不消除场表示差异。

此前mesh3同网格重求改变317.067 V/m且日志由Nonsymmetric变为Symmetric；
旧两档比较混有rhob及重求状态，不能全部归因网格。活动误差因子是i1.rhob，增大才更严格，
stol=1e−9或rhob40000均不是物理误差界。原mesh2的131251重求组装断言，无新场；
[150021][matched-mesh2]从成功模型重绑已有mesh2才求成，不是原失败输入重放。
新mesh2相对旧mesh2所查最大场差139.507 V/m，相对匹配mesh3为26.489 V/m；点差不是TOF。
mesh3同控制冷加载清解重求40点最大场差约1.75×10⁻⁷ V/m，支持该次可重复，不等于停止／FEM收敛。
完整失败、重求和分层查询过程见[本阶段冻结原文](history/20261015__matched-solve-and-trajectory-comparison.md)及其引用，不重复参数排列组合。

当前匹配FEM对照使用同一几何、电压、源、四窗及积分设置；两档均0/13检测器命中，
均10个物理碰撞＋3个拓扑拒绝、全部出现target49，但六颗粒子的碰撞部件改变；
相同计数不能称轨迹稳定。细档native参考为13/13命中，不能以命中更多选择真值。
无命中的FEM队列没有检测器FWHM／R，target49诊断不能冒充性能。

| 同target49受控响应 | Ey斜率（ns/eV） | x±0.1 mm偶响应（ns） | x±0.5 mm偶响应（ns） |
|---|---:|---:|---:|
| 匹配mesh2 | +16.44406 | −0.180612 | +1.958104 |
| mesh3重求 | +17.44775 | +0.079818 | +2.559779 |

| 配对对象／事件 | 最大相对中心TOF变化（ns） | 最大y变化（mm） |
|---|---:|---:|
| 匹配mesh2→mesh3，首次P2后 | 0 | 约2×10⁻¹⁰ |
| 匹配mesh2→mesh3，target49 | 0.601675 | 1.878743 |
| 细档native→匹配mesh2，target49 | 7.687358 | 14.634182 |

旧混控mesh2→mesh3在target49为2.055357 ns／3.928290 mm；匹配控制后差异缩小，
但仍不足以支持完整空间及时间资格。细档native为035610、镜网格0.04/0.20/0.02 mm、
物理y上界360 mm，不再使用旧y350参考代替；实际电压、源与碰撞定义一致。
表中是已观测配置响应，不是总误差界、额外峰宽或分辨率；源与返回状态差的放大尚须分段隔离。

进一步复用既有单镜重放：以匹配mesh2第12次正向中央穿面的同一组实际六维入口与原时钟，
分别驱动两档场，覆盖中心、Ey对及全幅x对共5颗；实际正镜转折后于首次负向z=0停止。
[mesh2单段][segment2]与[mesh3单段][segment3]入口逐项相同，全部完成同一出口，无新求场或物理PA物化，
总运行分别27.721／30.840 s。mesh3−mesh2中心公共时间差+0.073794 ns，
相对中心时间最大差0.058529 ns、y位置最大差0.027424 mm、vy最大差0.0037683 mm/μs。
这证明该单镜段自身可产生慢向状态差，不只是上游入口不同；不能把单段差乘49或据此宣布整程收敛。
重放mesh2与原整程相同出口时间最大差0.00409 ns，远小于本次场差；入口偏移与本段受力对出口位置
存在部分抵消，不能用两段差值直接线性分摊全程误差。
再将这两套镜出口状态放入同一mesh3场，传播13次快转折至global26/+z中央截面，
[第一组][amplification2]及[第二组][amplification3]均5颗完成，无碰撞或分支错配。
规定的140个非x0事件全部配对；x0微穿越计数98／95不同，不宣称全部事件拓扑一致。
保留原始时钟后，两组相对中心TOF最大差0.068332 ns，y差却从入口最大0.027424增至0.622397 mm；
中心y差−0.378149 mm，公共TOF差+0.024897 ns。确认慢向状态差可主要放大为空间返回差，
不能只凭小的单段时间差授予闭合／性能资格。两run总时223.399／71.183 s；前者含约126 s重任务排队。

补齐[匹配消费层40点查询][matched-layers]，总21.499 s，仅读现有PA与原生FEM小表，无COMSOL、飞行或新PA。
原生F3−F2最大场向量差26.489 V/m，实际C3−C2为26.511 V/m，deltaBridge最大1.445 V/m；
Ey分量对应12.445／12.354／0.344 V/m，C3与旧同场查询逐值一致。
已测正镜转折及邻域差异明显，入／出z=97 mm所查点的两档差小于10⁻⁸ V/m；不能外推成整个前段已收敛。
本批两档差主要已存在于FEM，不是导出新造；但共同绝对bridge仍达13.883 V/m，不能授予桥接整体资格。
40点含15旧mesh2事件点、15mesh3事件点及10邻域，不覆盖新mesh2全部路径，也不是连续力积分。
旧混控158 V/m结果不再代表当前比较；不强制对称、改压或以命中更多制造收敛。
COMSOL不升级；[厂商小材料][vendor]保留未发送，不另建整套追迹链。

mesh3→4仅对相同正镜槽壁—间隙—束路选择框进行一次最长边细分，新增单元27.78%，未改物理输入。
同40点最大场向量差由mesh2→3的26.489缩至6.655 V/m；Ey最大分量差由12.445缩至5.681 V/m，
本档最大电势差0.063412 V。最大场差点的实际h从0.19991降至0.14574 mm，支持该局部细化有效，
但细化策略不同且覆盖有限，不外推收敛阶或总误差界。最差单元质量下降至0.00004833，求解仍完成；
求解前后实际控制一致，已保存6.543 GB MPH，未冷重开、未导出、未飞行，不能据此授予轨迹／性能资格。

[当前native细档固定40点][native-fixed40]补查已完成，48.094 s，无新求场／导出／飞行；A=B查询实际复用PA，回归差为零。
N为035610的真实消费者而非COMSOL原生FEM：N−F3最大场向量差19.542 V/m，N−C3为15.946 V/m，
N−F3最大电势差0.44617 V。两种场源仍有可观测差别，且mesh4未一致向N靠拢；不能按接近历史命中选真值。
20个z=97 mm点虽对本次FEM局部细分不敏感，其N−F3仍可达19.542 V/m；这些位置未新增细化，
不能把相邻FEM档接近冒称该段已收敛。旧217点跨场源对照使用163135工作档与mesh1，不继承为当前证据。

## 剩余时间响应与设计线索

倾斜候选的局部Ey敏感性已明显下降，但尚未得到独立大样本下完整宽平台／十万资格。
当前两组高斯共同95颗的沿程ΔTOF/ΔEy约为：OA出口≈0、首次P2后1.61、target49 3.25、
回程P2入口3.50、P2出口−9.52、检测器−9.38 ns/eV。入口位置亦随Ey变化约−12.14 mm/eV。
P2短段位置扰动显示时间对入口y约1.077 ns/mm敏感，说明入口状态差经返回传输转换，
不是只看“时间差在P2出口增大”就认定误差产生于P2或P2网格。

工作场受控x±0.5 mm偶响应Cx≈2.362 ns、宽幅z响应及y端差仍存在；x奇项为零只支持左右对称，
不能排除偶像差或对称数值误差。正负镜段的不同状态、上游匹配和Stripe耦合需按同粒子同事件分析，
不能仅按单段最大差认定某一电极原因，也不能把各项端点差相加当完整FWHM。

S1单独−0.1 V对Ey响应改善很弱，却使空间相位偏约−0.915 mm，未成为新候选；不重复该小扫描。
下一有效方向应来自当前低压模型的镜倾角／Stripe／注入联合响应，兼顾空间返回、尾部和孔径裕量；
不恢复无工程资格的千伏Stripe，不按TE2名称预设解法，不以缩小σ替代主条件达标。
自动N100后处理复用已有分段及源状态分析，回归仅作定位线索；大幅因果判断仍需受控实际响应。

## 开放动作与关闭条件

已关闭的旧生产器、专属测试与入口清单归入[退役里程碑](history/20261015__producer-retirement-milestone.md)。
当前共享数学、活动配置及两条链的资产重建能力继续保留；已封存输入和小证据不随入口退役删除。
补充退役无活动引用的`tests/simion/test_accelerator_native_geometry.lua`及旧schema3的
`config/candidate_bunch_source_n1000.json`；现提供者与母样本生成不变，
相关5项回归通过；与下述结构诊断退役合并提交445116e8，未改变活动源或母样本。
另退役旧独立Stripe结构诊断发布器（2脚本）及其2项专属测试，活动入口／role引用为零；
共享曲线识别、制造宽度及理论种子保留，相关22项回归通过。历史冻结源码与结构诊断结果仍可查，
不再维护仅发布“电压待求”receipt的独立入口；不影响当前求场或自动闭合。
CLOC曾错误假定所有项目execution profile都有steps；已修复对合法项目专用格式的处理并推送c71dc95e，
官方统计已可运行，混合工作区增长不能归于本次整理。其他任务的CRLF与Refine合同问题已由其提交修复，
本次未夹带其文件。最新L1其余路由阶段通过，公共合同阶段曾因CP936/UTF-8测试输出失败；
编码回归已修复，该阶段独立重跑607项通过、1项跳过，原整轮失败记录保留，不概括为全量通过。

1. mesh4局部细化及固定40点检查已完成，出现局部场差收缩；初次启动仅容量准入失败，无科学求解。
   当前native细档与匹配FEM同坐标补查也已结束。174000正采用相同四窗定义导出mesh4，无新求场；成功封存后接同源受控轨迹，
   检验局部场差收缩是否传递为相对TOF／返回状态稳定；不混用旧场窗口，不调压，不自动加密或启动高斯N100。

本轮另沿公共机制退役083000旧导出、20261006_180500旧网格及094800已替代场的重载荷，
释放10594173854字节；小证据与重建输入保留，124839/150021当前模型及两条链、GUI、CAD依赖未删除。
公共退役wrapper自动容量收尾修复已提交a16dd4e0，通过真实小载荷删除／账本收尾、失败分支及编码回归；
checkpoint保留专用收尾，不把已删除但未完成账本收尾的资产视为可用空间。
具体范围见[本阶段快照](history/20261015__fixed-field-reproduction-and-solve-state.md)，不把已退役历史tip当作可直接恢复点。

当前STEP交付见[163154出版恢复][cad-delivery]：40个独立命名电极STEP、6个C0参考面及装配概览；
倾镜、精确曲线和去全部安装孔保持，真实连接同电位组件才合并，几何不连续者及正负镜不因同电压合并。
5 μm为交换验收精度，不是场／制造精度；未完成对方软件消费验收。新的英文Word尚待渲染和封存，
旧平行镜53件说明不能冒称与此包配套。CAD唯一活动入口为[run_resolved_cad_export](../analysis/run_resolved_cad_export.ps1)，
旧CAD入口退役范围见[退役里程碑](history/20261015__producer-retirement-milestone.md)，不改变当前交付链。

以下链接指向具名小证据，不复制全部manifest；资产保留期限以公共pin/lease与实际消费者为准。

[native-anchor]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_134039__sim__simion__converging-te1-trusted-fullstep-resume-stage-013/summary.json
[source15]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_224500__analysis__python__gaussian-ey-sigma0p15-volume-n100/results/bunch_source_receipt.json
[source20]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_144730__analysis__python__mrtof-gaussian-ey-sigma0p2-volume-n100/results/bunch_source_receipt.json
[fine15]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_040845__sim__simion__converging-y360-z002-gaussian-ey-sigma0p15-n100/summary.json
[fine20]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_044251__sim__simion__converging-y360-z002-gaussian-ey-sigma0p2-n100/summary.json
[parallel-pair]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_011744__analysis__python__parallel-tilted-gaussian-paired-reference/summary.json
[native-field]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_163135__build__simion__converging-mirror-y360-field/results/field_binding.json
[fine-field]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_032031__build__simion__converging-y360-mirror-z002-field/results/field_binding.json
[stopping-control]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_124839__analysis__comsol__mesh3-rhob-stopping-control/summary.json
[mesh1-export]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_010000__analysis__comsol__converging-beam-tube-export/run_config.json
[vendor]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_075800__analysis__repo__comsol-vendor-evidence/results/vendor_report.json
[cad-delivery]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_163154__build__cad__mrtof-tilted-step-publication-recovery/summary.json

[matched-mesh2]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_150021__analysis__comsol__mesh2-from-stable-source/run_config.json
[mesh4-longest]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_164500__analysis__comsol__positive-turn-mesh4-longest__r02/summary.json
[native-fixed40]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_173341__analysis__simion__fine-native-fixed40-field-layers/summary.json
[matched-export]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_152030__analysis__comsol__matched-mesh2-beam-tube-export/summary.json

[matched-n13]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_154824__sim__simion__matched-mesh2-fixed-u-controlled-n13/summary.json
[matched-pair]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_155820__analysis__python__matched-fem-controlled-n13-pairing/summary.json
[segment2]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_160855__sim__simion__matched-mesh2-same-entry-mirror/summary.json
[segment3]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_161302__sim__simion__matched-mesh3-same-entry-mirror/summary.json
[amplification2]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_162016__sim__simion__mesh2-entry-in-mesh3-return/summary.json
[amplification3]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_162423__sim__simion__mesh3-entry-in-mesh3-return/summary.json
[matched-layers]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_163502__analysis__cross__matched-consumer-field-layers/summary.json
