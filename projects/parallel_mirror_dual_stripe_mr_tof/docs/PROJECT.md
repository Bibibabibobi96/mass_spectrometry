# 开放路径平行镜双条带 MR-TOF 项目状态

返回[项目导航](../README.md)。本页只维护当前输入、资格、限制与未完成动作。
实施入口由项目导航进入；推导见[理论索引](theory/index.md)，机械来源见[CAD](CAD.md)。
完整旧过程已冻结在[mesh6 响应范围与场诊断里程碑](history/20261010__mesh6-response-range-and-field-diagnostics.md)。
以下数值是冻结合同的阅读摘要，不是可编辑的第二套参数权威。

## 当前决策

旧高放大响应组合的工程等价没有通过，原 staged S 搜索已经中断，不能继续沿其异常 P1 响应调压。
当前以[直接严格场][direct-field]及其[消费投影][direct-binding]作为临时复核参照，
不是真值、最终空间闭合点或正式场资格。该场的中心[真实 N=1][direct-n1]仍未闭合 S。

[既有参数更新诊断][saved-update]已失败：从上述成功保存模型更新现有
`mrtof_s1_v` 与 `par_dual_s.plistarr`，不重写 V0、不创建参数节点、不重建网格。
它沿既有表达式同时改变 S1/S2，是一条联动 S 方向，不是独立 S1 响应列。
实际264.6701119秒后触发 xmodel_assem.cpp:1896，无 LinIt、新场、查询或 MPH；
20项输出 manifest 验证通过，进程已结束。此负结果不授予响应或飞行资格。

停止同类大模型组装重试并保留复现证据。下一路线仅只读评估已有严格直接参照与
合格旧 S 增量的正确跨锚复用；兼容性及实际消费尚未证明，尚未实施或进行真实消费验证。
不自主启动电压扫描、N100、盲网格加密或新的优化器。

## 输入权威与物理定义

活动硬件只有名义平行伸长镜与两套独立形状、独立偏压 Stripe；Astral 收敛镜/单 Stripe 仅为理论对照。
COMSOL 求场，SIMION 消费标量场并追迹；两者使用同一冻结物理与 resolved 几何。
项目 x 是横向、y 是慢漂移、z 是快速反射方向。

| 内容 | 权威入口 | 边界 |
|---|---|---|
| 项目身份与能力 | [项目描述符](../config/project.json) | 能力登记不替代运行资格 |
| 候选几何 | [基础合同](../config/simion_candidate_two_zone.json)、[坐标合同](../config/cad_to_theory_frame.json) | 实际 run 的冻结合同优先于仓库默认值 |
| OA 组件 | [依赖合同](../config/accelerator_dependency.json)、[组件请求](../config/accelerator_component_request_n100.json) | receipt、位姿、电压与源按 run 绑定 |
| 当前数值/物理身份 | 下文来源 run 的 config、summary、manifest | 全电压、网格、源、时钟和 solver 分别保留 |
| 统计与比较 | [验证方法](../../../docs/VALIDATION_METHODS.md) | 只有同源、同口径、完整样本才可比较性能 |

当前 C0 分析域包含 OA、检测器、P1 接地罩延长及冻结屏蔽边界。
C0 是工程外域假设，不等于已完成实机腔体 CAD 资格；移动接地壳属于物理模型变化。
真空分区不是实体壁，碰撞几何和标量电场 PA 是不同消费者。
旧 native r15 和旧 mesh3 工作点不能冒称当前 C0/mesh6 同模型场。

## 真实源与束团证据

活动束团目标是释放慢向动能均匀全宽 0.1 eV（中心 ±0.05 eV），
圆柱 y 高 1 mm、半径 0.5 mm；[调试源发布][uniform-source]只证明源定义，不证明性能。
Gaussian σ(Ey)=0.1/0.2/0.3 eV 母序列已发布，现属历史，不是活动主目标。
σ 表示能量而不是速度；不裁尾、不重新抽样，不把窄源结果称为宽源性能。

当前受控中心由 common receipt 明确选定：位置 [0, −56.05182899425077, 32] mm、方向 +y、
释放 Ey=5.374387143093758 eV、质量 524 Th、电荷 +1、出生时刻 0。
ID6 是同中心其他量不变、x=−0.1 mm 的受控探针，不代表完整体积源或能量探针。
纯体积队列 ID1 不能默认为中心；母队列到 N1 仅在真实中心显式投影时允许队列文件身份不同。

时钟使用 common 出生时刻至事件的实际飞行时间；局部重放保留原入口状态与绝对时钟。
释放 Ey 与 OA 加速后 Ez、P2 局部 Ey 是不同量，不得互相替代。
当前 P2 参考面尚不能自动视为经验证的无场理论入口，源保持冻结不变。

## 临时直接参照工作点

完整 20 槽电压由[直接场来源][direct-field]冻结；“20 槽”不是 S1 加 20 V。
镜电压继承实际历史 TE1 状态，当前不再从旧裸镜周期反推更换释放源。
当前目标 K=24.5、慢转折目标 L=340 mm；全部精度见来源输入。

| 量 | 直接参照值 | 当前判断 |
|---|---:|---|
| P1 / P2 | +189.588174112441 / −190.10899285066873 V | 保持新 P 锚 |
| S1 / S2 | −28.00383247392914 / +55.33397459502199 V | 未闭合 |
| P 位置 / 角残差 | +0.092762917 mm / +0.002206944° | N1 通过原容差 |
| 首 slow / exact-K 位置残差 | +3.866470326 / −33.225087274 mm | 两项失败 |
| 终止 | 752.056583844 μs 复入 OA | 程序拓扑拒绝、非电极碰撞 |

该 N1 的运行 success 表示采集分析完成，不是 detector hit、完整返回或四项闭合。
旧 affine stage015 的 S 残差约 +24.435/+19.065 mm，不能替换直接参照的实际观察。
当前参数更新目标 S1/S2 为 −27.72379414918985/+55.11849067144983 V，P 与镜不变；
该联动方向未获得新解，不授予新的独立 Jacobian 或候选接受资格。

## 电场表示与数值资格

[mesh6 基场][mesh6-field]来自成功 mesh3 的 Copy+局部 Refine：
局部盒 x=[0,2.5]、y=[343,350.5]、z=[−103,103] mm，
四面体 22,038,908→22,770,107（+3.32%），31 个真空域、二阶电势 Q2。
这不是 OA/P1/P2 全段加密，也不证明整源轨迹覆盖或全场收敛。
当前成功求场保留历史 mesh 引用且活动 mesh6；删除旧 mesh 的副本曾在生成方程阶段失败。

已成功的严格直接路径使用 CG/AMG、loweramg on、实际 Study/Stationary 停止 1e−11。
不同保存场的全部实际 solver、参数化路径和 DOF 仍保留来源记录；
不能仅凭同 mesh 标签或参数化标签宣称同离散算子、内存比例或收敛。

| 标量消费者层级 | 间距 x/y/z（mm） | 接管边界 |
|---|---|---|
| base | 0.25 / 0.125 / 0.25 | 冻结全域与有效支撑 |
| first-slow-return-y | 0.25 / 0.03125 / 0.25 | x±2.25、y330..365、z±289.5 mm |

有序局窗 first-inclusive 路由，窗外回 base；所有候选的窗口、mask 和电压同步。
导体内缺值只按本次冻结电势补值，未知真空支撑不能补零；base 的 8870 未知节点与局窗 0 未知如实记录。
mask 必须符合实际消费者判定，浮点近 1 不等于 binary 1；已有投影只引用真实合法 mask，不伪写原记录。
adapter 的支撑 guard 是消费保护，不是官方原生梯度差分公式。
碰撞网格约 0.25 mm；电极标签不是电势值，近表面碰撞不授连续 CAD 精度。

## 响应组合的现行限制

已有 schema2 同锚 PS 响应编译、运行时仿射消费与公共固定点 composer。
组合必须核对完整电压、几何、材料、边界、mesh/Q2、网格、窗口与 mask；缺某轴响应不得改变该轴。
停止数值兼容仅排除声明的 Study/Stationary stol，实际每场配置和来源不被改写。
线性物理允许叠加不等于已计算响应具有工程精度；权重 G 只是放大量诊断，不是误差上界。

旧低 G 同点 N1 对照不能覆盖当前 G≈9.57 且含 P1/P2 的组合。
当前[83 点实际消费对照][consumer-pair]最大 affine−direct 为 1.78865 V、294.385 V/m。
[四角色分解][role-query]在所查正镜 fast7/45 点将差量定位到 P1 加权增量，
Ey 分别约 +294.247/+161.921 V/m；其余响应与负镜对应点近舍入，重构闭合约 1e−12 V。
这是少量坐标的贡献定位，不是全场误差界、P1 全部失效或唯一 FEM 根因。

旧 P1 171500 实际仅 ID16 增加 1%，同 geometry/mesh/grid，原停止 1e−9；
没有保存该 P1 原生 MPH，不能补造可重载解或直接原生核对。
严格 literal P1、单参数 P1、新固定锚 S1 三次复验均在 xmodel_assem.cpp row1896 组装失败，
无线性迭代或新解；不称 OOM、物理不收敛或永久供应商修复。
已有成功保存模型的参数更新路线亦在同类组装断言失败，当前停止这类大模型重试。

固定点物化与运行时组合已有历史算术/中心等价证据；不能改善响应本身的误差。
单 N1 物化准备可能抵消查询收益，固定多粒子点才评估摊销；不逐候选自动物化。
GUI 工作台重开、field callback 成功与 GUI 场查询对等分别验证，不能互相替代。

## 事件、闭合与接受规则

注入次序是 OA→P1(−z)→负镜预反射→P2(+z)→P2 后参考面→正镜预转折→Stripe。
返回必须自然通过 P2、正镜真实转向、沿−z到检测面；错误顺序、OA 重入及镜区外反号仍拒绝。
target-K 不切换电压；真实 collision、程序拒绝、目标相位、检测平面和有效命中分别记录。

原四残差是 P 位置/角度与首瞬时 slow/唯一 exact-K 位置，原容差不变。
合法 target 之前的阶段前缀可用于阶段诊断；之后失败不授完整返回或性能资格。
缺失/重复/乱序 target 或此前真实非法分支不生成有效阶段列，不以预测补观察。

首 slow 原始值保留；局部 signature 由邻接真实 fast 半周期与 z 方向派生。
已证相位不同的 S stencil 不作同根 Jacobian；旧缺日志记录明确 unknown，不冒称匹配。
邻接 vy 变号只作诊断，不硬拒同半周期的平滑根；不把全 slow 数量当匹配键。
瞬时零点不是唯一周期平均宏观转折；现有诊断量级不能解释全部约 24 mm 超程，亦不新定义理论目标。

既有 staged 入口先 P 后 S，每次 S 候选复核 P；接受新锚后清列重测，不运输跨根旧列。
候选预算、最小改善、回退与换档沿冻结合同有限执行；本次旧父已中断，不能原身份重启。
新锚 S Jacobian 必须实测；不混旧 mesh3 列、mesh6 列或旧 P 资格。

## 资格与历史性能

当前未取得四项空间闭合、正常完整返回的最终工作点、整程数值收敛或活动体积源性能。
同坐标 FEM 梯度、分量数组插值和标量数组求导是不同表示；原生 FEM 梯度不是真值。
小段同状态传播、少量坐标一致与 N7 受控响应均不能授全源 TOF/FWHM 误差预算。
mesh 与预条件器同时改变的耗时结果不作单因素提速归因。

| 已保留证据 | 可以说明 | 不能说明 |
|---|---|---|
| mesh3/mesh6 受控 N7 及同入口短段 | 具名轨迹、事件和状态的有限响应 | 全场收敛、FWHM 或正式收集率 |
| strict S2 复验及低 G 对照 | 原保存解停止误差与少量工程改善 | 当前异常 P1/高 G 范围已合格 |
| 当前直接 N1 与四角色查询 | 本工作点 P 通过、S 失败及少点 P1 贡献 | 新响应族、束团能力或唯一根因 |

历史窄源性能另见[前次里程碑](history/20261008__field-response-engineering-milestone.md)：
旧均匀 Ey 全宽 0.1 eV、K24.5/y−55 的 N100 为收集率 80%、KDE FWHM4.857 ns、R78695；
旧 Gaussian σ0.2 eV 为 78%、19.888 ns、R19217。
它们不是当前 C0/mesh6 能力，也不是 TE1 独立贡献；旧中断 Gaussian 十粒子不能补齐成 N100。
活动窄源 R≥100000、收集率≥80%仍是目标，不是已有结果。

## 开放动作与关闭条件

1. 只读评估严格直接参照与合格旧 S 增量的跨锚兼容：核对原物理、离散输入、
   目标 authority、增量来源及真实消费边界；不能更换身份标签把旧增量称为新锚响应。
2. 评估有证据且主 Agent 明确批准后，才决定最小实现及同目标实际消费/N1验证；
   当前不创建新场或运行，不预授跨锚可用性，不以自动重试、降 Q2 或改物理制造成功。
3. 只有输入与工程等价边界可接受后，才恢复原 staged P/S，实测新锚列并复核 P/完整返回。
   无闭合点不进入 TE1 后续或体积束团性能验收；不通过缩源、删尾、放宽容差制造通过。

容量由[公共策略](../../../common/contracts/artifact_capacity_policy.json)硬准入，资源时间/内存为 warning。
通过公共 run/lease/manifest/retention 管理，失败证据保留；不私改台账、复用失败 run_id 或覆盖已封存输入。
当前 provider、GUI、场源与待交接消费者必须保留，旧 IOB 的已退休 PA 依赖需要重装配。
源码静态门禁不代替商业真实运行、GUI/CAD 或 Formal；正式同步与资格仍待实际完成。

## 有效入口与追溯

生产试探使用[原 trial](../simion/run_two_prism_trial.ps1)，场编译使用
[static binding](../analysis/static_field_binding.py)及[provider](../analysis/corridor_field_provider.py)，
闭合使用[原 staged 父入口](../analysis/run_downstream_workpoint_iteration.ps1)。
运行参数必须来自具名冻结合同，不从本页复制局部常量成第二权威。
软件操作、理论与 CAD 继续由[项目导航](../README.md)进入，不另建横向文档网。

完整收缩前状态、旧 mesh3 锚、缺 P2 的历史语境、已结束诊断和失败过程见
[只读快照](history/20261010__mesh6-response-range-and-field-diagnostics.md)。
历史中的“当前/下一步”只按冻结时点解释；本页更新替换对应结论，不再追加启动与失败时间线。

[direct-field]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261010_071000__analysis__comsol__mrtof-stage015-direct-strict-field__r02/results/result.json
[direct-binding]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261010_075800__analysis__python__mrtof-stage015-direct-consumer-projection/run_manifest.json
[direct-n1]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261010_080700__sim__simion__mrtof-stage015-direct-n1/summary.json
[saved-update]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261010_085930__analysis__comsol__mrtof-saved-joint-parameter-update/run_config.json
[uniform-source]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261008_113647__analysis__python__mrtof-bounded-uniform-ey-debug-source/summary.json
[mesh6-field]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261009_133000__analysis__comsol__mrtof-mesh6-active-only-field__r02/results/result.json
[consumer-pair]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261010_080500__analysis__simion__mrtof-stage015-direct-affine-query__r02/summary.json
[role-query]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261010_081311__analysis__simion__mrtof-stage015-response-role-query/summary.json
