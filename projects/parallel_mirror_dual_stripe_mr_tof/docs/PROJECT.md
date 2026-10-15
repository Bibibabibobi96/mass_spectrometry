# 开放路径平行镜双条带 MR-TOF 项目状态

返回[项目导航](../README.md)。推导见[理论索引](theory/index.md)，机械交付见[CAD](CAD.md)。
本页只维护当前决策、有效证据和未完成动作；具名运行的冻结输入才是参数权威。
原有5225行混合工作区时间线完整保存在[本次只读里程碑](history/20261015__converging-field-and-performance-milestone.md)，不冒称已提交版本。

## 当前决策与完成边界

主线为对称会聚双镜＋五次项偏置Stripe＋保留实体的接地线性Stripe；K=24.5、加速器y=−55 mm。
原生SIMION自动闭合、响应组合和束团飞行已经可用。COMSOL当前进行同几何、同电压的固定场复现，
尚未取得新场上的空间闭合或高斯束团性能；不能把两条链的资格混为一谈。

原生细档高斯σEy=0.15 eV的N100为R≈101399、98%；σ=0.2 eV为R≈80929、95%。
这是有限工程结果，不是正式十万资格：前者名义峰宽距目标仅约0.053 ns，尚无独立大样本统计资格。
COMSOL mesh2已成功求场、导出及同源受控N13；两档均无检测器命中。固定输入配对已显示目标49处
相对中心时间最大变化约1.950 ns、y位置约3.717 mm，尚不支持性能复现或场已收敛。

近期先完成COMSOL mesh1/mesh2同消费配置的N13配对，分开评估FEM和导出表示影响，
再决定是否恢复当前候选上的Ey／横向像差优化。整理文档、移除无消费者旧入口与公共退役并行进行，
不占据物理主线，不新建第二套完整追迹或闭合框架。

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

| 当前COMSOL对象 | 实际结果与资格 |
|---|---|
| mesh1：[001600／恢复004119][mesh1] | Q2，CG＋AMG；16071408四面体、22659432 DOF，24次CG；原生求场约382 s |
| mesh2：[074200状态隔离][mesh2] | 复制后局部Longest-edge Refine；21076275四面体、29650232 DOF；27次CG、约525 s；求场成功 |
| 同输入固定217点 | mesh2−mesh1最大ΔV≈0.042604 V、向量ΔE≈10.6858 V/m；主要在快速镜转折，其他所查分组接近 |
| 当前导出：[083000][mesh2-export] | 四窗计算完成，success/full20、公共ready及实际binding通过；查询1070.913/107.410/108.066/145.079 s；无重新求场 |

两档完整几何、电压、Q2、活动CG/AMG及数值控制保持，mesh2求解前仅在内存移除旧dataset/solution/study，
不更改源MPH。旧保存求解状态下Compile3%访问异常，本次越过并成功，支持状态依赖的软件线索，
不证明所有组装故障已关闭或“坏网格／内存不足”是根因。cold回读217点与保存前一致。
活动CG／loweramg的stol=1e−9、误差检查与手动缩放同冻结控制；不是有MUMPS节点就称使用MUMPS，
也不能将该停止设置解释成电场已达1e−9物理误差。
本次有值的对照可以诊断当前离散影响，但有限停止误差仍在；217点差值不能预测束团FWHM或完整路径误差。

导出严格沿[010000][mesh1-export]网格：base 0.25/0.25/0.10 mm、正负镜0.04/0.20/0.04、慢返回0.10 mm三轴；
优先级正镜→负镜→慢返回→base。保持原单位、坐标、有效掩模及原生碰撞实例；未知查询不得补零或当真实损失。
mesh1的部分无效节点在远x面及OA邻域，已查217点支撑无缺失，但不证明完整源连续覆盖。

mesh1同电压受控[013155 N13][comsol-n13]为0/13检测器命中：10个物理碰撞、3个程序拓扑拒绝，全部出现target49；
没有NUMERICAL_COVERAGE_FAILURE；无检测器峰宽/R。与原生N13沿程相对时间最大差达到约7.549 ns、
目标处y差约14.407 mm。[014440配对][comsol-native-pair]包含FEM及消费表示影响，不能唯一归因或选哪方为真值。
新[mesh2 N13][mesh2-n13]为093500__r02，success/full24；原dispatch、4 ns/Q8、受控ID1–13，全部出现target49。
检测器0/13，12个物理碰撞、1个拓扑拒绝；没有检测器FWHM/R。物理碰撞为五次Stripe11一颗、
接地线性Stripe13/14七颗、中央接地体15四颗。与mesh1的10个物理碰撞、3个拓扑拒绝不同，不能因两档均无命中宣布稳定。
准备时两项运输漏项已更正：使用同字节OA原权威收据，显式传入原S1/S2值；093500仅preFly失败，无新轨迹。
旧失败证据保留，不把接续成功描述成性能复现；不因新场失焦而调压掩盖本轮固定输入比较。

[两档FEM沿程配对][fem-pair]的15项冻结控制相等，保留13颗、4460个共同事件及12个旧独有／3个新独有事件。
首次P2后相对中心时间最大变化0.003659 ns、y位置0.009166 mm；target49扩大至1.950478 ns／3.717233 mm。
快速转折最大y变化4.563822 mm。变化主要在进入长程分析器后累积，不能据此唯一归因于Stripe或某镜。
慢转折／慢返回的缺失和追加穿面仍需分支核对；不同碰撞终点的时间差不当作同截面TOF误差，
日志中的detector_plane诊断穿面也不等于实际检测器命中。该分析约0.305 s，无新增商业运行。

COMSOL不升级；[小文件厂商材料][vendor]已准备，含原始控制/崩溃/成功证据，不含大MPH，也未联系或上传厂商。
同场原生CPT短段历史对照不重复；目前没有依据另建COMSOL整机追迹主线。

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

1. 完成两档配对的慢转折／返回分支核对，依据逐周期增长确定下一项有限场表示或离散对照。
   不重复已完成飞行；无新假设不重复大模型求解，不在零命中场上直接投入高斯N100。
2. 根据mesh1/mesh2配对区分共同TOF、粒子相对时间、空间返回与终止身份；只针对改变设计决策的束路补充精度检查。
   不等待所有旧失闭合轨迹一致，也不因中心命中选“真值”；若结果仍改变性能判断，报告有限可信范围。
3. 原生工作流保留可重放能力；必要响应兼容成员完成后自动有界P/S恢复，冻结候选再检查代表离散稳健性。
   有超出数值／统计变化的改善后运行同源N100；稳定候选再N1000及独立采样，不机械重开K23.5或全工况扫描。
4. 容量硬准入及重载荷自动退役沿公共机制，保留两条链当前/后续消费者、GUI、冻结输入和小证据；
   CPU／内存／时间为warning，必要人工中断由实际进展决定。不手工减账、不反复哈希或物化大场拖慢接续。
5. [重放命名更正][replay]保留窄源及高斯参考入口；实际run_config、source receipt和field binding共同冻结。
   GUI重开能力不代表回调场云图对等；已退役GUI注明需重装配，不能把小IOB称作可直接消费完整场。

当前STEP交付见[163154出版恢复][cad-delivery]：40个独立命名电极STEP、6个C0参考面及装配概览；
倾镜、精确曲线和去全部安装孔保持，真实连接同电位组件才合并，几何不连续者及正负镜不因同电压合并。
5 μm为交换验收精度，不是场／制造精度；未完成对方软件消费验收。新的英文Word尚待渲染和封存，
旧平行镜53件说明不能冒称与此包配套。CAD唯一活动入口为[run_resolved_cad_export](../analysis/run_resolved_cad_export.ps1)，
旧无入链机械审计CLI退役可从Git恢复，原CAD及历史JSON/STL证据未删除。

以下链接指向具名小证据，不复制全部manifest；资产保留期限以公共pin/lease与实际消费者为准。

[native-anchor]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_134039__sim__simion__converging-te1-trusted-fullstep-resume-stage-013/summary.json
[source15]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_224500__analysis__python__gaussian-ey-sigma0p15-volume-n100/results/bunch_source_receipt.json
[source20]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_144730__analysis__python__mrtof-gaussian-ey-sigma0p2-volume-n100/results/bunch_source_receipt.json
[fine15]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_040845__sim__simion__converging-y360-z002-gaussian-ey-sigma0p15-n100/summary.json
[fine20]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_044251__sim__simion__converging-y360-z002-gaussian-ey-sigma0p2-n100/summary.json
[parallel-pair]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_011744__analysis__python__parallel-tilted-gaussian-paired-reference/summary.json
[native-field]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_163135__build__simion__converging-mirror-y360-field/results/field_binding.json
[fine-field]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_032031__build__simion__converging-y360-mirror-z002-field/results/field_binding.json
[mesh1]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_004119__analysis__comsol__converging-field-publication-recovery/inputs/model_reference.json
[mesh2]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_074200__analysis__comsol__converging-mesh2-state-isolation/summary.json
[mesh2-export]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_083000__analysis__comsol__converging-mesh2-beam-tube-export/run_config.json
[mesh1-export]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_010000__analysis__comsol__converging-beam-tube-export/run_config.json
[comsol-n13]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_013155__sim__simion__converging-comsol-fixed-u-controlled-n13/summary.json
[mesh2-n13]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_093500__sim__simion__converging-mesh2-fixed-u-controlled-n13__r02/summary.json
[fem-pair]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_090634__analysis__python__converging-fem-mesh1-mesh2-n13-pairing/summary.json
[comsol-native-pair]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_014440__analysis__python__comsol-native-controlled-n13-pairing/summary.json
[vendor]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_075800__analysis__repo__comsol-vendor-evidence/results/vendor_report.json
[replay]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_234530__analysis__python__converging-reference-replay-naming-correction/results/REPLAY_CORRECTION.md
[cad-delivery]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_163154__build__cad__mrtof-tilted-step-publication-recovery/summary.json
