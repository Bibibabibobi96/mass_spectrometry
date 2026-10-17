# 开放路径平行镜双条带 MR-TOF 项目状态

返回[项目导航](../README.md)。推导见[理论索引](theory/index.md)，机械交付见[CAD](CAD.md)。
本页只维护当前决策、有效证据和未完成动作；具名运行的冻结输入才是参数权威。
已完成矩阵、恢复与退役记录归[边界输入隔离里程碑](history/20261015__boundary-input-isolation.md)；更早过程由项目README导航。

分析模块统一使用公共分块文件身份函数，保留各自既有摘要大小写。
单中心步长比较复用同次已验证 manifest 输出记录，不再为 summary、trial、observation 和原始飞行日志
各重复全文哈希；batch/trial 的源区间解析直接调用源合同模块，删除兼容转发函数。
IP 替换装配从历史冻结源派生当前 seed 时，只剔除九个退役解析场字段；保留原生电压/几何参数，
不反写来源证据。coarse-raw producer 仍用于 native response bank 的粗父几何重建；PA family 的
独立私有运行表示用于防止发布资产被 SIMION 回写。

## 当前决策与完成边界

加速器接口可选`orthogonal_accelerator`或`dual_pressure_rectilinear_ion_processor`，默认OA保留；入口见[操作说明](../simion/README.md#加速器选择与接口准备)。
IP独立器件GUI已由用户验收；下游采用冻结出口六维状态交接，不是同一Fly内连续积分HP捕获／冷却到MR。
实测源来自152536独立N100：100母群、97出口，上游损失ID24/64/80；原ID、时钟及速度保持，不以缩放源补匹配。
能量只报告差异、不判定达标；默认自动输出各时刻空间位置、Prism相空间及全部损失原始证据。

172646已按原P→S／返回相位→P及完整返回通过，S2接地；原OA实际慢转折目标340mm，运行名称y360不是参数权威。
第17候选／055实飞通过完整工作点；
S1=−26.988823505V、P1=369.183763535V、P2=−212.537230795V。
P位置／action残差为+0.083549981mm／+0.008216214eV/q；慢转折／返回相位残差为−0.020811814／+0.008540326mm，
四项最大归一化残差0.835499809，S阶段为0.208118140。原判据及源保持，累计17候选／55计划、54次实飞。
同场181502联合N100完整处理97颗交接粒子：检测19、下游损失78、超时0；母群检测率19%，已交接群19.587629%。
78颗中76为原生接触终止、79／95为非碰撞的返回拓扑拒绝；81份逐离子证据含上游24/64/80，全部保留。
P2固定z33mm平面仅61颗到达，角度2.016884±0.126776°，Ey=5.434391±0.681463、Ez=4364.497923±38.142882eV/q，
均为到达子群总体标准差，不代表97颗整束。质心闭合通过，整束匹配和时间聚焦资格仍未取得。
默认生成7个实际事件／寿命决定时刻的空间图、Prism能量分配图和母群损失图。
本轮闭合、负结果、自动调度、发布与退役见[联合母群里程碑](history/20261017__ion-processor-closure-and-joint-population.md)；
此前软件恢复、输入运输和治理异常见[恢复里程碑](history/20261017__ion-processor-original-controller-recovery.md)。
最新L2实际退出0，MR静态1408项（10项跳过）；源码门禁不替代束团性能资格。

[005908冻结目标](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_005908__analysis__python__ip-centroid-target-authoring/results/target_authoring/target_authority.json)
能量参考保留Ws=5.374387143eV/q、K=24.5；clean参考Ez=4359.320021、Ey=5.213248eV/q。
慢转折目标以[171041修订权威](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_171041__analysis__python__ip-original-mr-target-authoring/results/target_authority.json)的340mm为准。
0.01°映射0.0524898eV/q只用于质心P控制，不是N100能量验收阈值；有效慢势与实际静电势分开记账。
003000扩域场的同点及实际轨迹接口审计支持原约11.47V跳变已消除，不授予全轨迹离散收敛资格。

当前可加载IP包为[183222 joint.iob](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_183222__analysis__python__ip-closed-joint-workbench/results/joint_workbench/runtime/joint.iob)，
使用最终055场；四实例／三优先级、保存重载、98点接口场审计通过，97颗FLY2与N100源逐字节相同。
20个分析器电压及15个IP电压、时钟与积分参数一致；用户可直接加载飞行，Agent未操作GUI。
包用于复现上述19%母群检测结果，不授予全束匹配资格。下一物理问题是有限束团的接受度／损失位置分析，未自动启动优化或新扫描。

主线为对称会聚双镜＋五次项偏置Stripe＋保留实体的接地线性Stripe；K=24.5、加速器y=−55 mm。
原生SIMION自动闭合、响应组合和束团飞行已经可用；COMSOL进行同几何、同电压固定场复现，
尚无新场上的空间闭合或高斯束团性能，两条链资格分开。

原生细档高斯σEy=0.15／0.2 eV的N100分别为R≈101399／80929、98%／95%，均为有限工程结果。
COMSOL各次完整受控N13均0/13检测器命中，尚未获得收敛或性能复现资格。
匹配控制及局部细化后，相对计时差缩小，空间返回仍敏感；跨来源慢向场差部分已存在于原始场及继承边界。
五面边界单因素对照已显著缩小已测单镜的慢向位置／速度差，时间及横向差未同步缩小。
同网格直接父场与组合场的25点一致性已通过，但慢向跨源差仍在；下一决策是受控区分停止因素、
继承边界与内部离散，不继续盲目加密或投入高斯N100。

## 输入权威与物理定义

下表为保留OA分支的[冻结闭合候选][native-anchor]；IP分支使用本页当前决策中的独立闭合电压。
完整电压、几何和消费者按各自冻结运行输入重放。

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

## OA真实源与束团证据

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

静态场 provider 的资源限额直接由已编译 plan 传给同进程公共观察器，不再另写 composition、各 occupancy
或各 field level 的 `*_resource_budget.json`；完整 plan 和 usage 内的 limits 仍冻结，预算和数值不变。

正常入口仍为[原trial](../simion/run_two_prism_trial.ps1)、[原staged](../analysis/run_downstream_workpoint_iteration.ps1)、
[自动候选链](../analysis/run_native_candidate_chain.ps1)；场由`simion/run_native_static_field_provider.ps1`
和`analysis/static_field_binding.py`接入，不另建手工闭合器。
固定场binding、外场消费、原trial接线、标准诊断及staged／候选自动链源码统一纳管。
运行仍须提供对应冻结资产；源码发布不授予其他输入的闭合、束团性能或Formal资格。
分块PA组合器及专属测试已作为项目模块纳管并推送ed745b07；算法字节未变、无公共兼容入口。
Prism路径身份统一使用`two_prism_topology_signature`；已删除无人调用的私有兼容转发，不改变转折分支判定。
相关导入／冻结路径已同步，28项组合器focused测试及MR Core/L1通过。
固定场消费另运行七模块300项回归：298通过、2项因旧A父PA已退役而跳过，约108.8 s；
活动launcher合同、Lua穿面事件及Python静态检查通过。三路独立审查未发现普通消费路径发布阻断。
真实证据仍以细档native高斯N100和mesh4受控N13为准；纯测试不授响应、物化或COMSOL改压重建资格。

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
032031细档仍为当前可用资产。163135旧粗档已在IP新场准备期间沿公共owner机制退役PA／surface，
其冻结输入、轨迹和网格比较指标保留；历史IOB须重建场后才能重放。
同轮还退役043210旧平行前驱及073134早期会聚前驱场，三组释放41,611,748,008 B。
当前134039中央场、032031细镜、7515开头的OA响应缓存及用户GUI包全部保留。
退役同时检查当前、下一消费者及GUI引用，不按文件年龄删除。

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

批次恢复按实际场模式绑定小输入：静态native／COMSOL使用场binding及adapter，不再要求无关的Fast Adjust bank／bundle。
[真实中断资产计划验收][static-recovery]已复用完整首批2颗、识别剩余11颗需重放，14项冻结输入匹配，
没有加载PA或重新飞行。两种静态模式的正常复用与binding变更拒绝回归已覆盖；
该证据只关闭恢复规划缺口，不代表11颗续飞、GUI重装配或完整自动链已经验收。

## 电场表示与数值资格

原生细档的已测高斯峰宽及损失身份接近，但N13慢转折最大差仍约1.203 ns、慢返回y=0约1.083 ns，
不能宣布全轨迹收敛。约0.2 ns是十万目标的总体初始工程预算，不是探索硬门槛、单环节预算或严格误差界。
共同TOF平移、端点响应和相邻档差均不能直接当作FWHM；事件必须按身份、方向和返回分支配对。

COMSOL现在是完整C0装配独立求场，不再继承SIMION donor；实际消费为标量电势→规则PA→
SIMION求导、插值和窗口选择→原trial。两来源复用调度、碰撞和诊断，不另建追迹／闭合系统。
普通GUI场查询不等于外场回调，保留IOB不授云图对等资格。网格、求解停止、导出、积分及事件误差分别管理。

### 有效场与固定输入对照

当前[mesh4][mesh4-longest]为30697694四面体、Q2、CG＋AMG、rhob40000、sol4/dset1；
runAll约1564 s、完整运行1880 s、峰值约41.83 GiB。参数不是误差界；mesh3同控制冷重求的40点可重复，
不等于停止误差关闭。旧混控制或组装失败档不能串成收敛序列，完整过程归[里程碑](history/20261015__boundary-input-isolation.md)。
COMSOL不升级；厂商材料保留未发送，不继续无新假设的大模型重试。

[mesh4四窗导出][mesh4-export]约1971 s／5.199 GB：
base间距0.25/0.25/0.10 mm，正负镜0.04/0.20/0.04 mm，慢返回三轴0.10 mm；
优先级正镜→负镜→慢返回→base。基础窗5664未知节点保留无效，另三窗全有效；
必须按真实轨迹支撑检查，不能补零或将未知查询计作物理碰撞。

同源[mesh4 N13][mesh4-n13]全部出现target49，0/13检测器命中，10碰撞＋3拓扑拒绝；
中心target49 y残差+10.694 mm。没有检测器峰宽／R，不运行高斯N100来补造性能。
[配对][mesh4-pair]的FEM间15项、跨源9项控制一致，当前结果为：
单镜原始出口见[mesh3][segment3]、[mesh4][segment4]及[native][segment-native]，不与整程终点混用。

| 固定输入比较 | 最大相对中心ΔTOF/ns | 最大Δy/mm | 解释 |
|---|---:|---:|---|
| mesh2→3，target49 | 0.601675 | 1.878743 | 匹配求场控制，尚改变返回 |
| mesh3→4，target49 | 0.211393 | 1.006036 | 差异缩小，ID9碰撞部件改变 |
| native细档→mesh4，target49 | 7.342627 | 15.095070 | 跨来源未一致，不按命中多选真值 |
| mesh3→4，同入口单正镜五颗 | 0.028632 | 0.013904 | 同出口，最大Δvy=0.0018746 mm/μs |
| mesh4→native，同入口单正镜五颗 | 0.037722 | 0.071485 | 同出口，最大Δvy=0.0091949 mm/μs |

单镜入口六维状态与原时钟完全继承，五颗覆盖中心、Ey及全幅x对。小单段计时差伴随慢向状态差，
不能乘49或授整程资格；[同场放大试验][amplification3]已见入口y差0.027424扩大至0.622397 mm。
target49的Ey斜率在mesh3／mesh4／native为17.44775／17.69162／2.46446 ns/eV；
全幅Cx为2.559779／2.556643／2.324758 ns，均不是检测器性能。

### 当前已隔离的差异与下一决策

[40点消费分层][mesh4-consumer]显示，所查正镜转折点的消费场−原始FEM慢向分量最大差0.08308 V/m，
native−消费仍约7.58514 V/m；主要跨源慢向差已存在于原始场，不支持盲细导出。
但z=97 mm所查点的桥接向量差仍约13.883 V/m，不能授整条桥接资格。
局部镜坐标Ry=Ey−tanθ·Ez仅用于诊断，不是纯Stripe场，也不能扣除后修轨迹。

冻结几何与完整电压逐字段一致，未发现漏OA、C0不同或二次旋转；原生细镜五面却继承中央及父场，
而FEM求整个C0。当前倾镜／电压没有独立父边界资格，旧平行镜证据不能继承。
[25点边界输入][boundary-input]中x=2 mm面原生−FEM电势均值−0.488858 V、变化范围0.017444 V，
沿y差商对应2.623–7.294 V/m；这不是纯常数偏置，也尚未证明它解释了束内差异。

[边界单因素飞行][boundary-flight]固定完整正镜域、0.04/0.20/0.02 mm、几何、电压、fractional、1e−5 V及五颗同入口，
只将五面输入换成[mesh4 donor][boundary-donor]；x=0仍对称，物理电极不覆盖。三组均5/5到同一出口，无碰撞或缺失。
相对FEM的最大y差由0.071485降至0.002356 mm、vy差由0.009195降至0.000770 mm/μs，约缩小30／12倍。
相对中心TOF差却由0.037722变为0.038963 ns，横向亦未同步改善；这证明边界影响此段慢向空间状态，非整程收敛。
donor的25点表示及原始完整矩阵、耗时／故障与处置记录已归[本里程碑](history/20261015__boundary-and-parent-consistency-isolation.md)。

父层固定25点矩阵已结束，完整结果与耗时归[父场隔离里程碑](history/20261015__parent-axis-field-isolation.md)。
当前0.50/1.00/1.00 mm父层已含慢向跨源差；中央层又改变该差，不能解释为同一常数电势偏移。
同U直接父场与组合场最大电势差1.70e−11 V；1e−5→1e−6停止增量也仅8.42e−11 V，
均不足解释所查跨源慢向差，不因此授整个场或其他响应库资格。

| 四中心实际API慢向电场增量 | 范围，V/m |
|---|---:|
| 父层仅z：1.00→0.50 mm | +3.485–3.517 |
| 父层仅y：1.00→0.50 mm | +0.0341–0.0467 |

已测z敏感性不是仅由电势差商定义造成；但z向梯度的两种查询模板仍有2.09–3.80 V/m差别。
平均电势更接近FEM不代表梯度更准确；没有一种场被指定为真值。
API为25点无局窗父层诊断投影，没有联动局域重建或飞行，不能推导峰宽、R或全轨迹收敛。

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

1. 边界单因素、父场组合／停止、y／z拆轴及实际API查询已完成；所查父层慢向变化主要对z敏感。
   已获批的中央单阶段对照000829正在执行：仅以z=0.50 mm父场替换边界，完整中央网格及物理输入不变，
   容量承诺9,817,256,922 B已准入；预计80–95分钟，完成后只查原25点，不自动建正镜或飞行。
   新父身份绑定实际222113封存PA及网格，不消费其中旧parent_level投影；旧中央为物化、新中央为直接解，比较仅作传递诊断。
   不绕过中央层冒充原传递链；仍需检验实际轨迹影响，
   不按更接近FEM选择真值。余下横向／计时差仍待解释。
   不将FEM donor伪装成原生祖先，不以单镜改善替代整程或束团资格，不逐场调压冒充数值收敛。
2. 冻结场消费与自动闭合源码／配置统一纳管；各模式资格仍按具名运行分别验证。
   通用COMSOL改压provider已有多窗编译与发布校验，但求解readback仍绑定sol1/std1，
   不授当前mesh4的sol4重建或改压资格；普通冻结场重放不执行该求场作者。
3. 代表射线支持后才做冻结高斯N100复现，统一KDE、全部损失、峰形及不确定性；
   数值比较固定电压，调焦后的性能比较另做。未支持时交付已量化差异与下一设计决策，不宣称十万达标。

两条链的当前场、响应库、GUI和CAD继续保护；已结束无人消费的载荷只沿公共owner退役。
旧mesh1／mesh2／mesh3四窗PA及旧平行镜181800物化场已公共退役，原MPH、小证据及必要重建来源保留；
历史IOB需重新物化／重装配，当前会聚场、GUI／CAD不受影响。处置字节与收据见[处置记录](history/20261015__boundary-and-parent-consistency-isolation.md#保留与清理)，
更早退役代码和运行恢复见[原里程碑](history/20261015__boundary-input-isolation.md)，
不靠运行终态自动判删除，也不将清理或门禁通过当物理资格。
203103边界因果试验的完整镜PA／surface也已公共退役，释放10,151,390,124 B；27份冻结输入、五射线结果及donor保留。
其收尾CLI退出码−1073741819，但账本已提交ready/light_evidence且两文件已删除；不重复删除或为取PASS重跑发布，保留该退出异常边界。

当前[STEP交付][cad-delivery]为40个独立电极STEP、6个C0参考面及装配概览；保留倾镜、精确曲线、去全部安装孔。
仅真实连接同电位组件合并。5 μm为交换精度，不是场／制造精度；尚未完成对方软件消费验收。
给Pulsar Physics的[英文交接包][pulsar-handoff]已精简为2页，包含倾镜STEP、完整电压、离子初态及真实逐步轨迹叠加STEP边线图；
不展示分辨率目标或内部收敛过程。配套英文邮件保留会议五问并补充RF／脉冲、空间电荷、质谱应用与数据导出，由用户自行发送。
代表离子采用040845源ID1同输入[重放][pulsar-trajectory]，213706条原始回调记录、350条旧事件逐字段完全一致；
检测时刻仍为764.217930877 μs。原生terminal同状态回调的微小时钟回退原样保留，不排序或改值；不授予新束团性能资格。
记录功能39项focused及真实N1通过；改动仍依赖工作区时钟／ID适配，未单独发布。
旧四实例源码断言已按OA／IP分支合同修正；2026-10-16真实联合包闭环后22路径L1通过，
包括MR Core42项及普通Lua回归、IP Static161项。该源码门禁不授予新装配联合飞行或GUI资格。
旧平行镜53件说明不作配套；唯一活动CAD入口为
[run_resolved_cad_export](../analysis/run_resolved_cad_export.ps1)。

以下链接指向具名小证据，不复制全部manifest；资产保留期限以公共pin/lease与实际消费者为准。

[native-anchor]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_134039__sim__simion__converging-te1-trusted-fullstep-resume-stage-013/summary.json
[source15]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_224500__analysis__python__gaussian-ey-sigma0p15-volume-n100/results/bunch_source_receipt.json
[source20]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_144730__analysis__python__mrtof-gaussian-ey-sigma0p2-volume-n100/results/bunch_source_receipt.json
[fine15]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_040845__sim__simion__converging-y360-z002-gaussian-ey-sigma0p15-n100/summary.json
[fine20]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_044251__sim__simion__converging-y360-z002-gaussian-ey-sigma0p2-n100/summary.json
[parallel-pair]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_011744__analysis__python__parallel-tilted-gaussian-paired-reference/summary.json
[native-field]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_163135__build__simion__converging-mirror-y360-field/results/field_binding.json
[fine-field]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_032031__build__simion__converging-y360-mirror-z002-field/results/field_binding.json
[cad-delivery]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_163154__build__cad__mrtof-tilted-step-publication-recovery/summary.json
[pulsar-handoff]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261016_140921__build__python__pulsar-trajectory-handoff/summary.json
[pulsar-trajectory]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261016_142700__sim__simion__pulsar-representative-id1__r02/summary.json
[mesh4-longest]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_164500__analysis__comsol__positive-turn-mesh4-longest__r02/summary.json
[mesh4-export]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_174000__analysis__comsol__mesh4-coherent-beam-tube-export/summary.json
[mesh4-n13]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_181000__sim__simion__mesh4-fixed-u-controlled-n13/summary.json
[mesh4-pair]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_182403__analysis__python__mesh4-controlled-n13-pairing/summary.json
[mesh4-consumer]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_185431__analysis__simion__mesh4-fixed40-consumer-field-layers/summary.json
[boundary-donor]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_194413__analysis__cross__fem4-boundary-donor-representation/summary.json
[boundary-flight]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_203103__sim__simion__fem4-boundary-only-positive-mirror/summary.json
[boundary-input]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_191649__analysis__cross__native-mirror-boundary-input-check/summary.json
[static-recovery]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_193228__analysis__python__native-static-batch-continuation-acceptance/summary.json
[segment3]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_161302__sim__simion__matched-mesh3-same-entry-mirror/summary.json
[segment4]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_183100__sim__simion__mesh4-same-entry-positive-mirror/summary.json
[segment-native]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_183200__sim__simion__fine-native-same-entry-positive-mirror/summary.json
[amplification3]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_162423__sim__simion__mesh3-entry-in-mesh3-return/summary.json

固定镜到 Stripe 的 `load_fixed_grid_mirror_point` 只核验实际消费的 run_config 与四份镜电压、
周期及原生 L1/probe 证据，保留其角色、互相身份绑定和全部物理门槛。下游合同身份不同时，仍核验
原 run 邻接冻结 source contract 的 SHA 及允许的物理差异；同身份分支不新增历史文件要求。
无关轴场比较、日志、资源／容量收据的缺失或损坏不阻止这项消费，不代表原完整 run 通过重新验收。
