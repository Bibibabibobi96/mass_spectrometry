# Ion Processor束团接受度与碰撞网格诊断里程碑

DOC_STATUS: ARCHIVED_READ_ONLY

本页冻结2026-10-18已完成的损失定位、两条数值对照、原生装配与IP/OA相空间比较。
后续决策以[PROJECT](../PROJECT.md)为准；此前中心P→S／相位→P闭合归
[联合母群里程碑](20261017__ion-processor-closure-and-joint-population.md)。

## 范围与冻结输入

独立IP源为152536运行的100母群、97实测出口，上游损失24／64／80保留。
源半径1mm、全高5mm；轴向入口5±1eV高斯及横向300K高斯；下游复用已实现的出口六维状态与仪器时钟，
不重新随机采样碰撞、不缩源、不裁尾。下游电场保持原闭合055场，S2接地；几何、电压及四项中心判据不改。
本轮未改变Prism电压，未重开优化、N1000或联合连续HP捕获到MR的模拟，未操作GUI。

三臂实际原生飞行均处理完整97颗交接粒子，未把首10颗当N100。公共调度器自动执行10＋87，
CPU容量9、内存容量1；无手工单worker上限，安全余量保持0及warning政策。

| 数值臂 | 实际运行 | 唯一数值变化 | 检测／下游损失 |
|---|---|---|---:|
| 原4ns | `20261017_181502__sim__simion__ip-closed-mrtof-joint-n100` | 原粗占据、Q8 | 19／78 |
| 2ns控制 | `20261018_124327__sim__simion__ip-joint-step-n100__r02` | 只将最大步长4→2ns | 19／78 |
| 2ns细碰撞 | `20261018_132248__sim__simion__ip-collision-overlay-n100` | 同2ns，追加同CSG占据patch | 19／78 |

5份源companion逐字节相同。原4ns的旧派生trajectory CSV存在读视图差异，不消费；
122404从已验证原native日志重建后匹配原记录SHA，保存全部逐离子损失及诊断。
初次123425在Fly前因旧183222包重序列化field descriptor导致严格身份拒绝，未作为物理结果。
正式finalizer改为精确字节冻结descriptor及显式ContractPath；124208原生四实例组装通过后才运行2ns控制。

## 损失位置与数值资格

33颗早期损失全部完成实际负镜预反射，`turns=0`不表示未反射。
124609在z=−110mm的双向括号插值中，出镜|x|>2mm集合恰好等于这33颗；
随后约0.075μs接触4mm内屏蔽槽。源vx与出镜x相关系数−0.998844；
σx从源0.060895mm增至出镜1.928858mm。该镜已有横向聚焦，表现为角度压缩及位置展宽，
不能解释为缺少全部x聚焦，也不能用中心四项闭合代替整束接受度。
103点细镜接口原生查询最大|ΔV|=3.934mV，仅为所查接口证据，非全场收敛。

4→2ns保持所有检测／损失ID、分类、部件与事件次数；19检测者最大终末时差0.0487ns，
但ID54同Stripe接触点相差3.557mm。步长对照不授所有接触位置或全部六维状态收敛。

ID11原终点在连续CSG真空中，实际占据查询约1；同CSG局部0.05mm对照为0。
局部网格查询本身不是Fly验收，且共同整数节点标志不变，不能表述为全部粗节点已被纠正。
实际修正采用electric_、持久NOTREFINABLE的完整分析器CSG占据patch，仅gem2pa，
不Refine、不FastAdjust、不覆盖原PA、不把占据值用作物理电势。
范围[0,−6,−100]至[3,2,−38]mm，pitch0.05mm、61×161×1241，原场回调保持。
它沿既有槽口延伸，避免仅包围旧终点造成新的补丁边界假接触。

132106原生五实例IOB保存重载通过原3项及新增14项优先级探针、98点场审计；
patch持久不可Refine属性和保存重载后的实际属性均通过。原四实例和OA默认选择保留。
132248真实N100完成并full manifest核验177 outputs，81份原始损失JSONL及自动英文图保留。

ID11继续飞行0.620160μs后，于t8249.30579892μs、
(0.00807544050227,−2.0000000014,−71.1316642281)mm接触Stripe1／电极12／instance5，
动能4377.057543eV；并非此前内部推测的P2端墙。
中间新增慢转折位于y=−2.39374368623mm、z=−87.0944236129mm；原target49相位y=+4.36965298097mm保持。
假接触已消除，但仍有实际几何接受度损失，未提升检测率。

另27个交接离子终点数值改变；ID13同Stripe的终点z变化20.334422mm，ID72的接触从粗网格偏置位置移到P2实体y=−3mm面。
因此不能说仅影响ID11或所有旧分类都证明原触点精确。新部件分类为内屏蔽37、Stripe1 17、P2屏蔽11、
Stripe2 3、ground foil3、IP部件3、过早detector接触2；另79／95为非碰撞返回拓扑拒绝。
此前两者target49的y约+16.51／+17.57mm，返回P2前的支路偏离，不能误记为真实碰撞或总动能不足。

相对2ns控制，细碰撞组的原生前置转折97、P2参考61、首次正镜及phase origin58逐字段保持；主慢转折51状态完全相同。
target49仅ID46有约4.209e−6mm位置变化；返回／检测ID集合保持。
检测器投影与native terminal分别统计，不把投影面六维状态补造出来。

## IP与OA的13阶段相空间

最终比较用最新132248的IP实飞，OA为040845的σEy0.15eV及044251的σEy0.20eV配置。
原生事件可覆盖13阶段；OA未记录密轨迹，不新插值任意截面或同时刻云。
原Lua的出口事件已有linear_bracket定位，沿用其原始记录，不冒充无插值的精确积分落点。
每个站点保存全部母ID、缺失原因、全到达群及最终检测子群，不能用后者替换分母。
角定义atan2(vx或vy,|vz|)；快转折角为N/A，主慢转折原事件无速度，不补造速度／能量。
主慢转折沿既有drift_phase_origin之后首次记录选择，不固定n=1；部分IP早期入射已有一次速度零交叉。
RMS相空间面积为描述性中心二阶矩，不称归一化发射度或已定义的接受椭圆。

| 全到达群指标 | IP细碰撞／2ns | OA σEy0.15eV | OA σEy0.20eV |
|---|---:|---:|---:|
| 出口σx／mm | 0.060895 | 0.246597 | 0.246597 |
| 出口σθx／° | 0.271991 | 0.0000312 | 0.0000312 |
| P2参考到达数 | 61 | 100 | 100 |
| P2参考σx／mm | 0.952154 | 0.127243 | 0.127197 |
| P2参考σθy／° | 0.126771 | 0.029035 | 0.037392 |
| P2参考σEy／eV | 0.681418 | 0.142631 | 0.190175 |
| target49到达数 | 41 | 100 | 100 |
| target49 σy／mm | 11.745743 | 1.380179 | 1.907217 |
| 检测／100母群 | 19 | 98 | 95 |

出口σEz为IP44.654eV、OA46.826eV；平均能量接近不表示角宽及返回相位已匹配。
IP的P2位置—角度相关系数约+0.92885，target49 y—局部动能偏差约−0.92783，
只作为描述性相关，不据此分配损失原因百分比。
K=Ex+Ey+Ez是动能，不含qΦ；转折Ez=0及沿程σK变化均不能证明冷却。

OA初始角宽为0、共同出生时刻，源尺寸及Prism电压也与IP不同；OA为4ns、IP为2ns。
因此比较是完整工程配置参考，不能判定硬件本征优劣。0.1mm／0.01°为中心闭合判据，
不是整束σ限制；整束发射度、角宽、能散和最低检测率要求未定义，不虚构PASS。
当前样本的主要设计方向为横向相空间及慢轴返回匹配，不能以缩源或裁尾代替。

## 证据、恢复与验证

- [最新13站报告及四图](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261018_135731__analysis__python__ip-oa-station-phase-space__r04/results/report.md)：3900粒子站点行、1638统计、624关系，9项独立校验；full manifest25 outputs。
- [三臂逐ID报告](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261018_135814__analysis__python__ip-joint-loss-causal-comparison/results/report.md)：300终态、200终点配对、2600阶段配对及243份原损失JSONL的SHA引用；full manifest27 outputs。
- [数值／定位边界说明](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261018_135814__analysis__python__ip-joint-loss-causal-comparison/results/verification_note.md)：实际loader使用、detector投影与native terminal差别。
- [可加载联合IOB](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261018_132106__analysis__python__ip-collision-overlay-workbench/results/joint_workbench/runtime/joint.iob)：对应132248负结果；用户自行GUI Fly，Agent未操作GUI。
- [完整CLOC与工程日志](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261018_135814__analysis__python__ip-joint-loss-causal-comparison/results/verification)：不作为物理资格证据。

首次相空间分析因metadata字段路径错误失败，r02因file_record实参类型错误失败；各actual exit1、原脚本与科学输出均独立failed封存。
r03通过后，新实飞完成才另建r04替换IP臂；r04分析脚本与r03逐字相同，无容差放宽、结果覆盖或新模拟。

两个历史PA的缓冲／无缓冲视图分叉由原owner同字节恢复，保留原坏对象和独立正确快照；
原manifest／retirement及当前场重新验证通过。容量账本只恢复唯一退役0字节记录的path键名，未重算容量或改写物理输入。
上述公共机制经common回归及两次真实97颗飞行越过，不把治理恢复当物理PASS。
重复snapshot_2沿公共owner退役释放2,146,584,928B；未被IOB／飞行消费的窄盒125028 PA及surface另退役释放12,703,044B，
其GEM、输入、manifest、日志及重建证据保留并完成公共容量重封；当前宽盒PA、源场及全部唯一损失证据保留。

L1r06实际exit0，16执行阶段通过。原L2r03保留exit1：29阶段通过，MR完整1430测试中两处过时fixture失败；
分别补齐真实恢复子进程所需binding及普通／overlay AST分支选择，未放松production验证。
修复后完整MR Static重跑exit0，1430测试／10跳过、三个纯Lua回归及PowerShell AST通过；
SIMION Python discover实际0测试，不报作额外测试覆盖。组合证据不是原L2重写为PASS。

CLOC2.10，以7f028866eef0b881577cf26c04d85a7917647c9d→WORKTREE计：
total code401521→403788（+2267），production271893→273073（+1180），tests129628→130715（+1087）。
完整报告逐语言列files／blank／comment／code、基线／结果／delta及过滤口径，unclassified为0。
此次N100属于功能／诊断样本，不授整束匹配、时间聚焦或Formal资格。
