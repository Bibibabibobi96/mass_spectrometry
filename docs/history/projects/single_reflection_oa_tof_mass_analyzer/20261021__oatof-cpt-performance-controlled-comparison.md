# OA-TOF N100 原生离子追踪受控对照

DOC_STATUS: ARCHIVED_READ_ONLY

完成日期：2026-10-21。本记录冻结本轮已完成的受控对照、精度负结果与小验证。
证据来自所链接的冻结 run；后续修复与正式采用条件由项目当前状态页管理。

本阶段承接[网格、收敛与原生追踪调研][prior-guide]，用现有 OA-TOF 的冻结电场和同一组 100 个粒子，
定位 COMSOL 原生追踪的可控成本。原调研保持只读。本文不重复通用网格指南，也不改变当前 Formal 资产。

本轮定位到两类可操作成本，并确认了一个独立的事件提取缺陷；**尚无通过本轮预设 1 ps 精度门槛的求解器提速配置**。
原基线 B0 与密集输出 DP5 的 A8/B8/D 中，`std2_run` 占不含附加探针的 MATLAB 主体约 **77–89%**，
即 Study 编译、变量准备、积分及求解期间存储是主要已计时阶段；二分输出参考 R2 为 74.30%，稀疏输出 S 为 92.43%。
这些比例不等于纯 ODE 或电场查询占比。

保存模型实际运行 **Newtonian + Generalized-α + Strict**，而活动构造器只把闲置的 `tstepsbdf` 设为 `free`。
163970 个输出时刻因而也约束活动积分步，其中反射窗占全部输出间隔约 91.16%。DP5/Free 虽显著减少接受步数，
本轮 `Tfail/(Step+Tfail)` 仍约 **58–60%**；这是拒步计数比，不能解释为场查询耗时占比或某个根因的贡献。

最清楚的局部提速证据来自**同一解的合并 API 读取**：A8/A1 分别为原三次读取的 **2.44/2.55 倍速度**，
所检查的原始数值逐值零差；尚未生产化或兑现为端到端收益。稀疏输出 S 使读取明显变快，但 D−S 最大 TOF 差
**296.411113808 ps**、Ion 8/19 的 Event 不一致，三类状态误差也全部超过原 128 ULP 余量，不能称为无损。
GA 与 DP5 的加严检查分别仍差 **655.698830499 ps** 和 **12.207852208 ps**；D、S 和单核诊断均未获接受资格。
纯数组 MATLAB 实测进一步确认：仅把冻结平台的两个零改为 1e-12 mm，就能使现有提取器改变 Event 并移动 TOF 约 100 ps。
这需要先修复并回归，但不能据此抹掉已有轨迹差或重建未保留的原始粒子路径。

## 固定对象与证据身份

以下路径以工作区为起点；所有运行均在
`artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/<run_id>/`，不在源码树保存计算载荷。
表内共同身份适用于后文所有对照；任何改变均须成为新的冻结 run，不能沿用旧简称。

| 身份维度 | 本轮固定值与证据 |
|---|---|
| 几何、边界、电压、材料与场 | 当前 Formal MPH；只消费已有 `sol1`，不重新构建几何、网格或电场 |
| 主资产 | `formal/comsol/single_reflection_oa_tof_mass_analyzer__model.mph`；986349231 B；SHA-256 见下文 |
| 网格 | 336867 个四面体、58968 个顶点；每臂求解前后读取网格计数与同坐标场指纹 |
| 粒子 cohort | 保存的 `sol2` 初始位置和速度中固定 100 个粒子，ID 1–100；ION 表核对位置与顺序 |
| 质量与电荷 | 名义 524 Da、+1；保留 MPH 原表达式 `mp=8.701230e-25[kg]`、`Z=1`，不重算常数 |
| 力模型 | 保存的真实 FEM 静电场；已有回读确认理想场混合权重为零；本轮不增加相互作用或其他物理 |
| 初态输入 | 用保存初态生成 17 位有效数字的释放表；求解后再次读取 t=0 的位置、速度与全部 ID |
| 时间与检测 | 同一脉冲相对 TOF、检测面、有效半径、返回方向和事件提取实现；同一 0–72.8534 μs 飞行区间 |
| 指标合同 | 每个 run 冻结相同 `analysis_contract.json`；canonical KDE/FWHM/R 仅作 N100 诊断 |
| 软件与执行 | COMSOL 6.4、MATLAB R2025b；公共启动入口；单个受管实例串行运行 |
| 资格 | `controlled_cpt_performance`；`formal_qualification=false`；不晋升、不保存新 Formal MPH |

基线 [manifest][b-manifest] 冻结的主要 SHA-256：

- MPH：`9F4C3DCE51791B41B4A7649500F74C29366BAC431111E79AF6CE5399ECA72A4D`。
- N100 ION：`3BD65B6CD43C5C122708D98BBD0BC0D9BD599D9FBBF17C5BB76B469613ECF26D`。
- 分析合同：`9AC9DF480DC0D57499E39F26FE358C437C0D30F103417BB4A02E3B1730A36BDD`。

场指纹包括三处固定坐标的 `V/Ex/Ey/Ez` 和网格计数；基线求解前后完全一致。它是运行过程核查，
不是对完整场数组逐字节哈希。完整输入身份来自 MPH 哈希，保持场的执行机制来自 `es=off`、`cpt=on`、
`sol2/v1.notsolmethod=sol`、`notsol=sol1` 以及不运行静电 Study 的约束。

## 已执行配置登记

完整身份由上述共同表、各 run 的 `inputs/settings.json`、配置前后原生回读和 manifest 共同定义。
`baseline-r04`、`reference`、`reference-r02` 是已存在的原始 `arm`，不以“快配置”等显示名替代它们。

| arm | Formulation / 活动算法 / 活动步策略 | rtol / 输出 | 其他设置 | 状态与用途 |
|---|---|---|---|---|
| `baseline-r04` | Newtonian / implicit genalpha / strict | 1e-5 / 原 163970 点 | reacf=true；storeudot=true；自动初始/最大步 | success；原成本基线，1 ps 校准失败；[summary][b-summary] |
| `reference` | Newtonian / implicit genalpha / strict | 1e-7 / 原输出时间表各间隔二分，327939 点 | reacf=true；storeudot=true；自动初始/最大步；readback_probe=true | interrupted；不能作为精度参考；[summary][r1-summary] |
| `reference-r02` | Newtonian / implicit genalpha / strict | 1e-7 / 同一二分输出时间表 | reacf=true；storeudot=true；自动初始/最大步；readback_probe=false | success；加严比较点，尚非已收敛真值；[summary][r2-summary] |

基线和参考的 GA 参数继承保存模型：`rhoinf=0.75`、位置 Field 自动缩放、全局 scaled 绝对容差因子
0.1。原生节点里残留的 `maxstepgenalpha=0.1`、`initialstepgenalpha=0.001` 不能读作实际生效步长：
其启用状态分别为 `maxstepconstraintgenalpha=auto` 和 `initialstepgenalphaactive=false`。

reference-r02 的最终 run 身份为 `20261021_124653__benchmark__comsol__oatof-cpt-reference-r02`。
它关闭额外 API 读回探针，并将启动器预算预设为 1800 s；完整事件与状态导出成功。
后文 B0 专指 `baseline-r04`，R2 专指 `reference-r02`，二者身份分别以上表和冻结 run 为准。

## 校准失败与参考检查转向

比较 run `20261021_130702__analysis__python__oatof-cpt-comparison` 已成功封存。
其 [summary][cal-summary] 的 `status=success` 表示分析执行和证据发布完成；
`calibration_pass=false` 才是数值判定，不能把两者混为一谈。差值方向统一为 B0−R2。

| B0−R2 指标 | 已冻结结果 |
|---|---:|
| TOF 平均差 / RMS 差 / 最大绝对差 | 0.221993691778 / 0.286316328596 / 0.655698830499 ns |
| 去均值 TOF RMS 差 | 0.180819912707 ns |
| 检测面二维落点 RMS / 最大模长差 | 0.001366654414 / 0.005063288560 mm |
| 400 状态位置 RMS / 最大模长差 | 0.019502940393 / 0.077079580033 mm |
| 400 状态速度 RMS / 最大模长差 | 1.181152282260 / 3.325986703688 m/s |
| 1 ps TOF 校准 | FAIL |

原始数值及全部配对数据见 [comparison.json][cal-result]。B0 与 R2 都保留 100 IDs、全部命中和 400 条有限状态；
初态、粒子属性、场指纹及分析合同一致。上游消费投影核验通过，但它只核验比较实际消费的记录，不声称全文复核所有未消费载荷。
Agent 1 独立读取该分析 run 冻结的 CSV，按 ID/TimeS 配对重算，未调用原比较实现，得到相同 TOF 统计；
最差 ID=77，B0/R2 分别为 71.3535631985982/71.3529074997677 μs。
5 μs 已有最大位置差 0.01276539 mm、速度差 3.14721 m/s，50 μs 最大位置差增至 0.07707958 mm，主要沿 z。
50→70 μs 的速度差变化不超过 9.82e-11 m/s，位置差变化与 20 μs×速度差的线性传播残差不超过 1.57e-9 mm；
70 μs 状态按各自 vz 外推至各自 TOF 均落在 z≈0（最大绝对偏离 8.60e-12 mm）。这些核查说明至少已有轨迹数值差，
不能把全部偏差当作终点提取或单位伪差，也未排除个别提取影响；四个采样时刻不足以分离加速区细步与早段漂移的贡献。
两个 GA 点同时改变 rtol 和 Strict 输出间隔，故不能把偏差单独归因于某一项；两点均无 Tfail/NLfail 也不证明轨迹精度。
原 `acceptance.json` 虽列出状态差上限，但 `calibration_tof_pass=false`，这些上限**不得用于接受任何候选**。

原拟 GA Free、GA 反力输出、DP5 三臂提速计划已暂停。以下 DP5 配置共同保持原 163970 输出点、
初始步 `1e-10 s`、最大步 `5e-8 s`、q/v 自动父缩放、全局 scaled atol 因子 0.1、reacf=false、storeudot=true。

| 当前参考检查 | Formulation / 活动算法 / 步策略 | rtol | processor_count | 状态 |
|---|---|---:|---|---|
| `dp5-reference-a-r02`（A8；前文 A） | NewtonianFirstOrder / explicit RK DP5 / free | 1e-10 | 0；原生日志实际 8 核 | success；未 qualified；[summary][dp5a-summary] |
| `dp5-one-core`（A1） | 同上 | 1e-10 | 1 | 科学阶段完成，外层已封存 interrupted；[summary][dp5a1-summary] |
| `dp5-tight-eight-core`（B8） | 同上 | 1e-11 | 0；原生日志实际 8 核 | success；A8/B8 校准失败；[summary][dp5b8-summary] |

A8 身份为 `20261021_131110__benchmark__comsol__oatof-cpt-dp5-reference-a-r02`，A1 为
`20261021_132944__benchmark__comsol__oatof-cpt-dp5-one-core`。A1 的 std2_run 比 A8 长 29.36%，
因此停止单核加严计划，改用 `20261021_134737__benchmark__comsol__oatof-cpt-dp5-tight-eight-core`（B8）与 A8 校准。
A8/B8 积分数值只改变 rtol；额外后处理探针选择不同，不能称为完整执行配置完全相同，也不能混比总墙钟。
DP5 与 B0 还改变 formulation、算法和速度自由度；必要的限步/输出细化检查及 1 ps 门槛继续保留。

### A8/B8 加严检查与跨核诊断

`20261021_140450__analysis__python__oatof-cpt-comparison` 的 [summary][dp5-cal-summary] 为 success，
但 `calibration_pass=false`；其 [comparison.json][dp5-cal-result] 与 [acceptance.json][dp5-cal-acceptance]
明确记录 `calibration_tof_pass=false`、`qualification=false`。该文件中的状态差上限仍不能用于接受候选。

| A8−B8 指标 | 已冻结结果 |
|---|---:|
| TOF 平均差 / RMS 差 / 最大绝对差 | 0.435562077712 / 4.333573764014 / 12.207852208235 ps |
| 去均值 TOF RMS 差 | 4.311629302782 ps |
| 检测面二维落点 RMS / 最大模长差 | 5.145570979165e-5 / 1.124915244292e-4 mm |
| 400 状态位置 RMS / 最大模长差 | 1.169567223829e-4 / 5.992259271310e-4 mm |
| 400 状态速度 RMS / 最大模长差 | 0.005747066393 / 0.017119739024 m/s |
| 1 ps TOF 校准 | FAIL；不改变原门槛 |

Agent 2 独立按各 run manifest 核对事件/状态 CSV 的字节数与 SHA，再按 ID 读取并重算 TOF 差，
未调用比较器实现，复现上述最大值与 RMS。最差 ID=66，A8/B8 分别为
71.3514628347314/71.3514750425836 μs；三臂 A8、A1、B8 均有 100 个唯一 ID、100 命中和 400 条有限状态。
这不把 B8 提升为已收敛真值，也不证明只需继续收紧 rtol 就能满足要求。

同次独立读取还得到 **A1−A8** 的 TOF 平均差 −0.401420403904 ps、RMS 5.918353697126 ps、
最大绝对差 **14.786504692665 ps**；最差 ID=95，A1/A8 分别为
71.3528712761148/71.3528564896101 μs。A1 的原始事件由 [interrupted manifest][dp5a1-manifest]
绑定，只作跨核数值敏感性诊断，不能绕过比较器的 success 要求进入校准或 accepted 链。
单次跨核差既不是可随意忽略的序列化余量，也不足以定位线程归约、场插值或积分误差各自的贡献。

## 精度先于速度

“同一个 rtol”不等于“同一轨迹精度”，尤其在二阶位置方程改为一阶位置/速度方程后。
以下是始终保留的比较要求；首轮 GA 校准失败已经阻止候选接受，后续须重新取得合格的基线—参考对。

1. 所有臂必须完成 100 个唯一 ID 的释放、检测事件和状态核查；不删除异常粒子，不仅比较命中子集。
   初态、粒子属性、场指纹、分析合同、逐粒子 `Status/Event` 必须一致。
2. 基线对加严参考的最大绝对 TOF 差必须不超过 **0.001 ns = 1 ps**；未过此校准门槛，不能接受候选。
3. 候选对参考也须满足最大绝对 TOF 差 ≤1 ps。该阈值不随候选表现改变。
4. 在 **5、30、50、70 μs** 共同时间取全部粒子，形成 **400 条位置/速度状态**；必须完整、有限、ID/时间配对一致。
5. 对检测面二维落点、共同时间三维位置和三维速度，分别计算误差向量模长的 RMS 与最大值。
   候选—参考的两个统计量都不得大于**已通过校准的新基线**—参考对应量加上浮点序列化余量。

余量按每个量类统一计算：`128 × spacing(max(1,max(abs(reference)))) × sqrt(d)`；
落点 `d=2`，位置/速度 `d=3`，使用各自输出单位 mm 或 m/s。128 ULP 仅吸收 CSV 浮点往返误差，
不构成可任意放宽的物理精度预算。初态另按各坐标分量检查 128 eps(scale)。

参考解、校准结果、冻结 `acceptance.json`、完整逐粒子差值和比较 summary 应由独立分析 run 留证。
GA 与 A8/B8 两轮校准及负结果已见上文；本轮没有取得合格基线—参考对，因此没有有效的候选接受合同或 accepted 配置。
该方法只证明同一冻结 N100 cohort 相对于加严参考的经验一致性；不证明物理绝对误差、网格收敛，
也不把 N100 的 FWHM/R 外推成 N1000 或真实仪器分辨率。

## 已完成求解与计时口径

`20261021_121557__benchmark__comsol__oatof-cpt-baseline-r04` 完成，数据来自其
[summary][b-summary]、[native log][b-log]，不是从屏幕进度或总日志行数估算。

| 指标 | baseline-r04（B0） | reference-r02（R2） |
|---|---:|---:|
| 原生 `Solution time` | 346 s | 820 s |
| `std2_run` 墙钟 | 355.0733416 s | 830.0958326 s |
| 新解初态读取 | 21.8095307 s | 69.0129443 s |
| 检测事件提取 / 400 状态提取 | 12.3058726 / 21.6248936 s | 38.2413760 / 65.1403048 s |
| MATLAB 诊断主体总计 / 启动器墙钟 | 458.3188167 / 547.0891077 s | 1117.1512797 / 1158.4752213 s |
| 末行 Step / Res / Jac / Sol | 163990 / 180998 / 32 / 180998 | 327959 / 425800 / 32 / 425800 |
| Order / Tfail / NLfail | 2 / 0 / 0 | 2 / 0 / 0 |
| 托管进程采样峰值 / 系统最低可用内存 | 5164531712 / 33687027712 B | 6208684032 / 31858237440 B |
| 检测事件、命中 / 有限共同时间状态 | 100、100 / 400 | 100、100 / 400 |

R2 数据见 [summary][r2-summary] 和 [native log][r2-log]。B0 原生日志另报告 physical/virtual memory
2.35/2.42 GB；其新初态最大位置差为 7.105427357601002e-15 mm，速度差为 0 m/s。

| DP5 指标 | A8（8 核） | A1（1 核；外层中断） | B8（8 核） |
|---|---:|---:|---:|
| 原生 `Solution time` / `std2_run` | 410 / 416.1941971 s | 530 / 538.3795557 s | 796 / 803.9148314 s |
| DOF / 输出点 / Step / Res / Tfail | 600 / 163970 / 14888 / 245322 / 20158 | 600 / 163970 / 14871 / 248031 / 20562 | 600 / 163970 / 25537 / 446705 / 38278 |
| 初态 / 检测 / 状态读取 | 18.3912826 / 10.9521551 / 18.8462783 s | 22.5657902 / 12.6437987 / 21.6605346 s | 20.1736340 / 12.2408839 / 21.3704295 s |
| 主体不含附加探针 | 501.5220745 s | 635.8511161 s（不能当作 wrapper wall） | 899.3536573 s |
| 主体含探针 / 启动器墙钟 | 542.3529339 / 581.3144741 s | 不用于完整执行比较 / 不可用 | 900.4776166 / 967.7925588 s |
| 托管峰值 / 系统最低可用内存 | 5459161088 / 32254001152 B | 均不可用，资源采样未发布且不可恢复 | 5143797760 / 28351635456 B |
| 命中 / 有限状态 / 求解前后场指纹 | 100 / 400 / 一致 | 100 / 400 / 一致 | 100 / 400 / 一致 |

A 的 [native log][dp5a-log] 显示接受步明显少于原输出点，但拒步较多；本次计数满足
`Res=7×(Step+Tfail)=245322`。这是该次原生计数关系，不是场查询次数或普遍性能比例。
本次 std2_run 比 B0 长、比 R2 短；三者精度尚未取得共同资格，不能据此宣布同精度提速。
[132210 比较 run][a-comparison] 得到 A−R2 最大 TOF 差 0.420228768505 ns、RMS 0.235157853485 ns；
A−B0 对应为 0.432974252192 ns、0.168970751163 ns。旧校准仍为 false，A 的 accepted=false，状态子项通过不能恢复资格。

B8 的 [native log][dp5b8-log] 明确使用 8 核，末行 `Res=7×(Step+Tfail)=446705`；
其 `std2_run` 为 A8 的约 1.932 倍，但 A8/B8 仍未通过 1 ps 校准。拒步多是已观测求解器行为，
尚未逐步配对粒子穿越单元的时刻、局部误差估计与拒步原因，不能从计数直接得出拒步的唯一根因。

`std2_run` 包含 Study 编译、变量准备、积分和求解期间输出存储，不能标成纯 ODE 内核时间。
启动器墙钟还包括冷启动、调度、进程与许可证生命周期；提取、读回、CSV 导出和运行证据处理另列。
比较速度应先用同口径 `std2_run`，再给端到端时间；不能混用 native `Solution time` 与另一臂总墙钟。
`Res` 是原生残差计数，不是有限元场查询次数；没有 profiler 证据时不拆分“场插值占比”和框架占比。

## 同一解的后处理 API 探针

A8、A1 各自导出完成后，在各自同一解上按 `solnum=1`、重复 `t=0`、六表达式合并查询的固定暖序只读测试：

| 查询 | A8 耗时 | A1 耗时 | 原始数值核查 |
|---|---:|---:|---|
| `solnum=1` 初态 | 2.5542544 s | 3.0058465 s | 各自位置、速度逐值一致 |
| 重复 `t=0` 初态 | 18.4548185 s | 21.5362778 s | 各自位置、速度逐值一致 |
| 2006 个联合时刻、6 个位置/速度表达式 | 19.7750519 s | 22.2932098 s | 各自初态、400状态6通道、检测窗口200100值×3通道逐值一致 |
| 原初态＋检测＋状态三阶段 | 48.1897160 s | 56.8701235 s | 原输出和分阶段计时保持不变 |

证据为各自 native summary 的 `readback_probe`。各自合并查询 finite/nonfinite mask 相同，最大逐值差均为零；
三阶段耗时除以合并查询耗时，分别为 **2.4369 和 2.5510**。这是读取阶段的实测比值。
这只证明**各自同一解、固定暖序、各一次测量**的 API 收益；不是跨线程逐值等价，也没有随机化顺序、冷态复测或生产替换。
探针本身额外增加成本；不能扣除局部收益后声称端到端时间已经兑现，A1 的外层中断边界尤其不能省略。

## B8 冻结电场的内部面采样

B8 在全部正式导出后执行只读场探针，额外用时 **1.1198475 s**；[native summary][dp5b8-native]
记录 `field_probe.status=completed`、`geometry_and_data_checks_passed=true`。
该成功状态只表示几何定位和有限数据完整，不是电场精度或轨迹精度 PASS。

探针从 ROI `x=[−52,−44]、y=[−3,3]、z=[−20,0] mm` 内、靠近其中心的四面体种子中确定
12 个内部共享面；实际均属真空 domain 21，面中心仅覆盖约 x=−48.57…−47.23、y=−0.81…1.16、
z=−10.81…−8.66 mm 的局部小区域。每面必须有恰好两个同域四面体 owner，并排除全部 `tri` 几何面，
包括可能同域的内部边界。三档面法向偏移以及两个 owner 质心共 96 个查询点，逐点核对 mm 坐标回读、
域和原生 `meshelement` 所属；不把连通表列号预先假定为原生单元 ID。

使用 `dset1/sol1`、`edim=domain`、`recover=off`、`ext=0` 查询 raw `es.Ex/Ey/Ez/V`，未重求电场、
未改变粒子受力设置，也未运行 PPR 对照。[36 行、38 列 CSV][dp5b8-field-csv] 保存两侧坐标、单元身份、
E/V 和差值；全部有限，CSV 逐列往返差为零。Agent 1 和 Agent 2 分别独立读取复核，得到：

| 法向单侧偏移 ε（mm） | 12 面 `‖E+−E−‖` 范围（V/m） | 最大切向差（V/m） | 最大绝对电位差（V） |
|---:|---:|---:|---:|
| 1e-3 | 1.7226408–73.7542757 | 0.22203653 | 0.197332834 |
| 1e-4 | 1.7742631–73.8263456 | 0.02220365 | 0.019733284 |
| 1e-5 | 1.7795842–73.8335567 | 0.00222037 | 0.001973328 |

ε 每缩小十倍，电位差和切向场差约缩小十倍，而总场差保持非零且接近法向。
这为**所采样 12 个面附近的 raw 电场跨单元法向变化**提供局部证据，与连续分片电位的梯度可跨面跳变相容。
它不量化全场离散误差，不证明这些面就是实际粒子轨迹的拒步位置，也没有建立该变化对总耗时或 TOF 偏差的因果贡献。
不能从本次 `recover=off` 查询反推受力配置；后续D已另行回读同一冻结模型的 `ef1.UsePPR='0'`。
本轮没有 PPR 提速或改善精度的实测结论，不能据此推荐未经验证地改变场表示。

## 本机资源控制与未完成运行

本轮在 i9-9900K（8 核/16 线程）、约 47.9 GiB 已安装内存的本机串行执行。
每臂只启动一个受管商业求解实例，沿公共资源调度入口取得重许可；默认 processor_count=0，
allocator 与 assembly scalability 均为 auto。A8 实际 8 核，A1 明确请求并使用 1 核；其 native 阶段反而更慢。
[官方多线程说明][official-threads]记录 Windows 默认物理核策略；[性能调优][official-tuning]和
[硬件建议][official-hardware]说明小模型可能因多核成本而变慢；本次 A1 结果不支持本机该配置减少到单核会提速。

冻结预算为：基线和 reference 启动器墙钟 1200 s，reference-r02、A8、A1、B8、D 与 S 为 1800 s；
托管内存 28 GiB，最低系统可用内存 6 GiB，
3 s 采样，新增磁盘预约 50 MiB。托管内存按已确认 PID/出生身份的进程逐个取 `max(working set, private)`
再求和；它与 COMSOL 内部峰值定义不同。磁盘预约是容量合同，不是求解器硬盘上限。
最终只保留 compact 证据、100 条检测事件、400 条状态和必要日志；不保存新的 MPH 或完整轨迹载荷。

首个参考 `20261021_122558__benchmark__comsol__oatof-cpt-reference` 的原生积分已经结束，
`std2_run=823.846973 s`，但在提取阶段超过总墙钟预算；启动器记录 `interrupted`、
`wall_seconds=1200.792334`、`interruption_reason=wall budget exceeded`。
这是端到端未完成的诊断证据，**不能用于精度校准、完整速度排序或宣称求解器数值失败**。
重试使用新 run ID，不能续写原参考使其看似成功。

早期 baseline 启动/配置尝试也不进入性能矩阵：首轮 formulation 属性键错误；r02 未进入 Study 求解；
r03 遇主机重启。完整的原配置成本基线为 r04，精度校准仍失败。长向量反复写入/读取会产生配置与桥接成本，因此正式比较
分别计时；不把这种工具开销误算成积分慢。运行失败或中断记录应保留其原始状态与原因。

DP5 首次尝试 `20261021_130857__benchmark__comsol__oatof-cpt-dp5-reference-a` 在配置 guard 失败：
原生 Field 的 `solvefor` 返回 Boolean true/false，脚本误按字符串 on/off 比较。该次没有进入求解，
不能解释成 DP5 的数值或物理失败；[失败 summary][dp5-failed] 保留实际类型和错误栈。
修复按原生 Boolean 值校验后，以新 run ID 重试；没有改变物理、容差或验收门槛。
`20261021_132123__analysis__python__oatof-cpt-comparison` 因 NumPy Boolean 的 JSON 序列化失败而封存；
仅补 `bool(...)` 包装后，`20261021_132210__analysis__python__oatof-cpt-comparison` 完成。该修复不重跑求解或改变判据。

A1 的原生科学阶段 completed，公共入口已输出 PASS 且原生进程退出，但外层 watchdog 未正常结束。
主 Agent 按精确进程身份仅终止 PID 3980，按 interrupted 处置；外层 wall、peak、minimum available 均不可用，
不能用主体时间、监控间隙或其他 run 的采样补造。A1 可支持上述阶段诊断，不能进入要求 success 的正式比较器接受链。
A1 的 [reconciliation evidence][dp5a1-reconciliation] 保留双层状态与不可恢复指标；仅删除两份与冻结
输入 SHA 一致、可重建的临时 `.m`，共 53032 B，原始 summary/CSV/log 保持。终态 manifest 已独立完整验证，
公共容量租约已释放；这不改变 interrupted 的资格边界。
A1 的附加场探针在 MATLAB 空结构体赋值处失败（`MATLAB:heterogeneousStrucAssignment`），未完成场检查。
该实现问题修正后，B8 真实重试成功，局部场结果和限制见前文场采样小节；不回写 A1 的原失败证据。
纯数组探针首次使用不受命名合同支持的 `matlab` scope，在创建 run 前被拒绝；未启动 MATLAB，
只读核查无运行目录、容量租约或账本残留。改用已支持的 `comsol` scope 后以新 ID 完成，不影响科学对照。

## 为什么原输出会有 163970 点

当前数值作者合同 [formal_solver_numerics.json][numerics] 定义敏感区域 0.2 ns、无场漂移 50 ns，
加速器/反射器/检测窗余量分别 0.5/2/0.5 μs，并要求全部细网格与全局 t=0 相位对齐。
[configure_oatof_segmented_output.m][output-builder] 根据几何、质量和电压预测关键时刻，向外取整细窗端点，
最后添加 1 μs 尾段。这是参数化输出及事件解析设计，不是全飞程统一 0.2 ns 的物理定律。

保存模型原生 `tlist` 的 0.2 ns 窗为 0–1.7388、21.3516–51.2452、70.8532–71.8534 μs，
分别含 8694、149468、5001 个间隔；50 ns 漂移段分别含 392、392、20 个间隔，另有 12.8 ns 和 8 ns 连接间隔。
163969 个间隔加初始点形成 163970 个输出点；0.2 ns 间隔约占 99.51%，其中反射窗约占全部间隔 91.16%。
原生回读证据为既有 [oatof_readback_summary.json][saved-readback]。当前 GA/Strict 要求到达这些输出时刻，
因此保存需求与积分步数耦合；基线末行 Step=163990 与此机制一致，因果收益仍需仅改活动步策略的对照确认。

2026-07 的[数值验证记录][old-numerical]报告过全局相位对齐、漂移段粗化和 N100 速度收益；活动构造器
注释也保留了过早粗化、反射窗缩窄导致结果变差的历史。那些记录并未确认当时活动算法真正处于 Free，
不能据此宣称“Free 不能解耦输出”或“0.2 ns 是本模型的普遍积分精度下限”。检测事件提取仍需足够时间分辨率。

## 手动缩放与输出密度的单变量对照

本轮后两项诊断不将校准失败的 B8 称为已收敛真值。D 对 B8 测量手动缩放设置的代价与偏差；
S 对 D 只检验输出保存密度对同一数值配置的影响。这两个问题不要求预先宣布某个轨迹为真值，
但也不能产生新的高精度接受资格。原 A8/B8 校准及候选接受逻辑保持不变。

D 的原始 arm 为 `dp5-scale30000`，run 为 `20261021_141035__benchmark__comsol__oatof-cpt-dp5-scale30000`。
相比 B8，唯一数值配置修改是速度 Field 的 `scalemethod=manual, scaleval=30000`；
DP5/free、rtol=1e-11、scaled atol 因子0.1、初始步1e-10 s、最大步5e-8 s、8核、原163970输出点、
反力关闭和导数存储均相同。30000 m/s 来自先前四个状态时刻的最大速度模长约27707.93 m/s，
不是全轨迹最大值或通用推荐值。[D summary][scale-summary]

**自动位置尺度发生了联动。** D 的配置回读仍是父级auto、q继承parent且闲置scaleval=1，v手动30000；
但在原生日志最终 `Analysis of Variables` 后，q和v的实际尺度都报告为30000，A8/B8对应均为1。
因此本轮只能称为“手动速度尺度设置触发了实际q/v共同缩放”，不能称为仅改变速度误差权重。
官方说明自动尺度初始取决于Jacobian/质量矩阵并将实际值写入日志，但没有公开此模型的具体跨Field计算公式。
若要隔离速度权重，需要另建q手动固定的新臂，不能事后改写D的身份。[Dependent Variables][official-scaling]

在本轮rtol与atol因子下，scaled绝对容差仍为无量纲1e-12；速度实际尺度从1变为30000，
使物理单位速度的等效绝对容差项从1e-12变为3e-8 m/s，这不是全局轨迹误差保证。
相同rtol因而不保证相同物理误差控制。位置尺度的联动也必须纳入解释，不能把这一设置作为无损提速开关。
D额外只读回收了实际 `ElectricForce/ef1` 属性：`UsePPR='0'`、`E_src=userdef`；
冻结MPH的 `dmodel.xml` 中12个 `ideal_{accel,drift,stage1,stage2}_{ex,ey,ez}` 表达式均为0，
所以所示条件表达式退回 `es.Ex/Ey/Ez`。没有开启PPR或更换物理场。

| 已完成指标 | D：原输出密度 | S：稀疏输出 |
|---|---:|---:|
| 输出点数 / 原生 DOF | 163970 / 600 | 3641 / 600 |
| native Solution time / std2_run | 668 / 675.005559 s | 620 / 625.0637135 s |
| Step / Res / Tfail | 21715 / 373576 / 31653 | 21650 / 371203 / 31379 |
| 初态 / 检测 / 状态读取 | 23.1126461 / 13.9464853 / 20.7865482 s | 0.3875624 / 0.8434098 / 0.1992051 s |
| 三次读取合计 | 57.8456796 s | 1.4301773 s |
| 不含附加探针的主体 / 启动器墙钟 | 770.3989613 / 917.2066436 s | 676.2512180 / 904.8020871 s |
| 受管峰值 / 系统最低可用内存 | 5219069952 / 30631071744 B | 5233983488 / 31350226944 B |
| 命中 / 有限共同时间状态 / 场指纹 | 100 / 400 / 一致 | 100 / 400 / 一致 |

D 的 std2_run 相对 B8 减少16.03%。D启动器包含公共调度等待重许可的时间，不能把wrapper差值等同计算提速。
每种配置只做单次运行；未随机化顺序或估计重复测量波动。精度判定见后续冻结比较，不能由耗时下降推定。

独立读取发现D仍100/100命中，但Ion 8、19由B8的 `frozen_on_detector` 变为 `crossing`，
两个D的TOF都恰为查询表中央时刻71.3533881412611 μs。D−B8全100粒子的最大TOF差约296.3243 ps，
已违反原Event一致和1 ps要求，因此D拒绝接受。分析器只增加“保留不一致事件并明确判失败”的诊断分支，
不删除粒子、不把两种Event视为等价、不改变基线／参考严格校验或任何误差门槛。
原始坐标时间序列未保留，不能把全部TOF差归因于ODE误差，也不能断言这两个粒子走了某个具体插值索引。

现有事件提取函数的源码揭示了已由下文纯数组实测确认的边界：穿越判断使用 `z(i-1)>=0 && z(i)<=0` 且优先执行，
精确零平台会走crossing并取首零采样时刻；极小正平台则走冻结分支并从先前接近段外推。
全零平台也会被相等坐标分支赋予第二个查询时刻。纯数组实测登记在后续段落；此问题与轨迹积分分开处理，
不能用它抹掉此前A8/B8均为冻结事件时已经发生的12.21 ps参考差。

S 的 run 为 `20261021_142636__benchmark__comsol__oatof-cpt-dp5-scale30000-sparse`，
[summary][sparse-summary] 与 [native log][sparse-log] 均已封存。S 预先限定为原输出时间表的子集：每100点保留1点，另保留首尾、完整检测查询窗（预测TOF±200 ns）内的
全部原始点，以及该窗边界和5/30/50/70 μs状态查询两侧各两个原始邻点。保留导数存储、首末时间、
初始步和最大步，避免将保存密度与积分控制同时更改。官方对Free输出解耦的说明，以及时间查询使用邻近
输出值和导数的插值机制，支持这一设计；实际等价性仍须逐粒子核查。[步长控制][official-timesteps]、
[时间插值][official-time-interpolation]、[减少保存数据][official-data-storage]

在S运行前，配对诊断已固定：100事件和400状态身份一致；TOF差≤1 ps；对落点、位置和速度分别报告
完全同值，以及仅允许原128 ULP序列化余量的RMS/最大差检查。该余量不叠加失败校准的状态误差，
也不改变任何候选的accepted字段。原生日志比较只取有Step编号的积分行，排除out行；显示的步序列一致
只能说明记录一致，不证明未保存的内部全精度轨迹逐位一致。

S 相对 D 的 std2_run 减少 **7.40%**，三次读取合计的单次耗时比为 **40.45**，主体减少 **12.22%**。
但是两次运行的原生积分日志从 **第 15 个 Step** 已出现可见差异：D 的时间/步长为
`1.2513e-8/1.0262e-9 s`，S 为 `1.2512e-8/1.0257e-9 s`，当时 Res/Tfail 同为 252/21。
因此耗时差不能隔离成纯保存或桥接成本；不能从单次各一臂排除运行重复性影响，也不能声称 Free 下输出改变必然无损。
配置回读、输入身份与场指纹支持“本次登记只改变输出子集”，并不等于已经证明全部数值差的因果来源。

最终分析 `20261021_144817__analysis__python__oatof-cpt-comparison` 的 [summary][final-summary]、
[comparison.json][final-comparison] 和 [manifest][final-manifest] 已以 success 封存，包含 22 个输出。
success 表示分析执行成功；`calibration_pass=false`，D/S 的 `accepted` 均为 false。
下表始终使用全部 100 个粒子和 400 条有限状态，不删除 Ion 8/19。

| 比较方向 | TOF RMS / 最大绝对差（ps） | Event 一致 | 数值资格 |
|---|---:|---|---|
| D−B8 | 35.416884141 / 296.324296301 | 否；8、19 不同 | accepted=false；校准失败且 Event/TOF 均失败 |
| S−B8 | 0.676573237 / 1.644832295 | 是；全部为 frozen_on_detector | accepted=false；校准失败且 TOF 超过 1 ps |
| D−S | 35.406359380 / 296.411113808 | 否；D 的 8、19 为 crossing，S 为 frozen_on_detector | 仅机制诊断；精确同值与 128 ULP 两种诊断均失败 |

| D−S 误差类 | 向量 RMS / 最大模长差 | 独立 128 ULP 余量 | 两项判断 |
|---|---:|---:|---|
| 检测落点（mm） | 1.951327405e-5 / 4.767324044e-5 | 1.286219742e-12 | 均 FAIL |
| 400 状态位置（mm） | 2.078738767e-5 / 8.682435030e-5 | 2.520465652e-11 | 均 FAIL |
| 400 状态速度（m/s） | 8.619782519e-4 / 2.549407850e-3 | 8.065490087e-10 | 均 FAIL |

D/S 对 B8 的状态子项虽小于失败校准所列的量，仍不能恢复资格；D−S 诊断完全没有叠加该校准误差。
即便暂不考虑 Event，D/S 的状态数据也不能视为仅有 CSV 往返误差。新分析通道保留 Event 差异只是为了报告全量负结果，
默认基线/参考严格核验、候选 Event 门、1 ps 门及既有 accepted 逻辑均保持。

## 原生 MATLAB 纯数组提取验证

`20261021_144857__test__comsol__oatof-extractor-probe` 经公共入口以 1 核执行，冻结并调用未修改的原提取函数，
不加载 MPH、不求解场或轨迹。[原生 JSON][extractor-native] 的 `test_executed=true`、`observed_defect=true`；
[manifest][extractor-manifest] 以 success 封存并完整验证 7 个输出，`physical_qualification=false`。

已知轨迹为 `z=max(0.55275−0.0275×t_ns,0) mm`，接近速度大小 27500 m/s，真实到达为 **20.1 ns**。
采样时间为 `[0,2,20,20.2,20.4] ns`，准确采样位置为 `[0.55275,0.49775,0.00275,0,0] mm`。

| 纯数组输入 | 原函数实际 Event / TOF | 相对已知真值 |
|---|---|---|
| 精确零冻结平台 | crossing / 20.2 ns | 晚 99.999999999997584 ps |
| 仅最后两个 z 改为 1e-12 mm | frozen_on_detector / 20.100000000000024 ns | 差约 2.32e-11 ps；与上一输出差 99.99999999997442 ps |
| `[0,2,20] ns` 上全零静止平台 | crossing / 2 ns | 没有向下穿越，不能由这些数据确定首次到达 |

现有 **6 个单测全部通过**，说明旧测试没有覆盖这里暴露的分支缺陷；不是问题不存在的证据。
精确零平台的采样不提供冻结发生于两个采样点之间的准确时刻，提取器却把首零点作为 crossing；
微小正平台改走先前接近段外推，导致不连续的输出判定。全零输入则揭示相等坐标不应自动成为新穿越。
修复应先定义“穿越”“已在检测面”“冻结到达”及无法确定事件的语义，再加这些最小回归，不能只放宽误差或强制统一标签。
本探针没有 D 的原始 `pd` 坐标序列，不能重建 Ion 8/19 的实际分支索引，不能把 D/S 的所有差异归于提取器，
更不能取消此前 A8/B8 在相同冻结 Event 下的 **12.20785 ps** 校准失败。

## 官方支持的方法与本项目适配

查阅日期为 2026-10-21，以下均为 COMSOL 6.4 官方原文或本机同版本官方示例。

| 官方依据 | 本轮采用方式与边界 |
|---|---|
| [Choosing a Formulation][official-formulation] | 默认二阶 Newtonian 配 GA；一阶 Newtonian 配 DP5。显式法对某些非刚性问题可能更快，强烈突变加速度时隐式法更稳健；不能预先保证 OA 提速 |
| [Time API，表 6-74][official-time] | GA 用 `tstepsgenalpha`，DP5 用 `tstepsdopri5`；`tout=tlist` 管保存时刻，Free/Strict 管实际步选择；Strict 可另插入小步 |
| [Time-Dependent Solver，Output][official-solver] | RK 不支持反力输出；保留 `storeudot=true`，并验证速度实际可读；导数存储影响后处理精度 |
| [Variables API，表 6-80/81][official-variables] | formulation 改变后 `updateVariables()`；核查新增速度 Field、缩放、求解/存储开关与冻结场来源 |
| [官方 trapped_protons 示例][official-example] | 已静态核对实际枚举 `NewtonianFirstOrder` 与显式 DP5 配置；只作为 API 支持证据，不借用其物理数值 |
| [mphparticle][official-particle] | 显式限定 dataset、表达式和查询时间；不导出完整轨迹后再截取；少输出是否能减少所有内部读回成本须实测 |

DP5 的最小活动配置是 `odesolvertype=explicit`、`timemethodexp=rk`、`rkmethod=dopri5`。
只设 `rkmethod` 不会把仍为 implicit 的模型切换为显式。限步须写 `maxstepconstraintdopri5/maxstepdopri5`，
初始步须写 `initialstepdopri5active/initialstepdopri5`；GA 或 BDF 的残留键不能代表 DP5 的活动配置。

上述 A8/A1/B8 保留 q 的自动父缩放，新增 v 也明确继承 auto；全局 scaled 绝对容差因子 0.1，
q/v 的 `atolmethod=global`。这里声明的是自动缩放策略，没有声称固定的速度绝对误差值。
`out` 控制是否保存 Field，`usestoresel=all` 只控制保存范围；保存 XML 中缺少 `out` 不证明官方 API 没有该项。
可暴露时读回 `out=on`，否则明确记录，并以求解后 t=0 与 400 状态中的实际 q/v 数据核验。

反力输出在隐式求解中可增加请求输出时刻的残差装配，故值得独立测试；实际收益须看受控对照。
Free 允许积分器依据误差控制选步，但不会自动删除 163970 次输出的插值/存储工作。
不能只把 `tout` 改成 `tsteps` 就宣称积分变快；也不能用输出点数代替内部步数。[Time API][official-time]

### 原始梯度与 PPR 的机制边界

[形函数文档][official-shape]说明标准 Lagrange 元的分片多项式值连续；据此不能保证一阶梯度跨单元连续。
本轮 B8 已取得上述合法内部面两侧的完整 raw 数据。该局部观测与这一机制相容；若进一步根据形函数阶次推导
误差阶，仍须确认 V 的实际离散类型，不能把网格的几何阶次当成电位插值阶次。
[Electric Force][official-electric-force] 的 PPR 选项用邻近单元信息恢复受力电场，改变实际追踪所消费的场表示。
[绘图 Quality][official-plot-quality] 的 Smoothing 是同坐标值平均，Recover 是导数恢复；边界附近恢复甚至可能更差。
文档的 2–5 倍成本指结果评估，不能移作 CPT 耗时倍率。[mphinterp][official-interp] 的 `recover=off/pprint/ppr`
仅改变查询的恢复策略，不会回写已求出的轨迹；PPR 受力候选须独立冻结并通过既定逐粒子门槛。
已经观察到的局部 raw 场变化仍不能单独证明刚性、唯一拒步原因或 PPR 必然提速；后续解释和候选继续受既定精度门约束。

## 本轮结论与适用边界

| 问题 | 已取得的结论 |
|---|---|
| 原模型为什么接受步数很大 | 作者合同 `solver_steps=free` 未被消费，活动实现硬编码闲置 BDF 键；保存模型 GA/Strict 使密集输出约束活动积分步。只切换活动 GA 步策略的收益未测，不能给出独立速度倍率 |
| 求解和读取哪一段值得优先处理 | 密集输出下 Study 阶段占主要主体时间，读取也有可测成本；同解合并读取已有 2.44/2.55 倍暖序收益且检查值零差 |
| DP5 与手动缩放能否直接采用 | 不能。A8/B8 仍差 12.20785 ps；D 触发实际 q/v 共同缩放且 Event/TOF 失败；同 rtol 不代表同物理绝对容差 |
| 减少线程是否更快且等价 | A1 的 std2_run 比 A8 慢 29.36%，独立跨核最大 TOF 差 14.78650 ps；外层 interrupted，只能作诊断 |
| Free 下稀疏输出是否无损 | 本次未通过。D/S 的 Event、TOF、三类 128 ULP 检查均失败；积分日志第 15 步已有差异，无法把时间变化隔离为纯保存成本 |
| 提取器是否存在可复现问题 | 存在。未改原函数的 MATLAB 三数组实测暴露零平台分支敏感性和全零伪穿越；旧 6 测试未覆盖，生产尚未修复 |
| raw 电场是否具有局部跨面变化 | B8 合法内部面的数据支持局部法向梯度跳变；不是全场误差、唯一拒步原因或 PPR 提速证据 |
| 是否取得合格参考与同精度提速 | 没有。GA 和 DP5 校准均失败，D/S accepted=false；端到端合格收益和重复性区间均未建立 |

本轮已封存的受管峰值约 **5.14–6.21 GB**，系统最低可用内存约 **28.35–33.69 GB**（十进制），
没有显示这组 N100 冻结场追踪受到内存容量压力。A1 缺失的资源采样不纳入该范围。
这不能外推到重新剖分更细网格、重求静电场、空间电荷或更大粒子数；也不能由剩余内存多推断继续加核会更快。
本轮没有重求电场、做网格收敛或新增大型模型验证。

本阶段尚无同物理、同误差门槛的 SIMION 配对计时。即使 COMSOL 某臂提速，也只能回答本模型的
原生配置瓶颈与改进幅度，不能据此宣称 COMSOL 已追平 SIMION，或将差异完全归因于某一种软件架构。

## 未来正式采用的唯一配置链

下一轮按以下次序推进，避免在尚未可靠的提取与参考上继续比较快慢：

1. **先关闭活动键和提取语义问题。** 让作者合同真正驱动活动算法对应的步策略，并读回核验；
   为精确零、微小正平台、全零平台和真实受控轨迹建立提取回归。保留原始小规模检测窗数据以便复核，
   不把不同 Event 静默合并，也不放宽 1 ps 门槛。
2. **再取得合格参考。** 固定受力场和同一 cohort，先验证提取后的参考一致性，再分别检查 rtol、最大步及所需输出支持。
   加入相同配置重复运行，区分重复性与配置因素；只有校准通过后才冻结新的状态误差接受合同。
3. **将同解合并读取沿现有入口生产化。** 复用已验证的显式表达式、联合时刻及数据拆分，保留 ID、有限性和逐值核验，
   在相同输出上复测冷/暖序与端到端时间；当前局部 2.44/2.55 倍不能直接写成整条工作流的提速。
4. **数值旋钮逐项过门。** GA Free、反力输出、DP5、手动 q/v 尺度、输出稀疏化或受力 PPR 都是独立候选，
   各自冻结活动配置及实际尺度，保留同物理与逐粒子误差门后再比较时间和资源。当前失败结果不支持默认开启任何一项。

生产落地应沿已有单向链完成：`config/formal_solver_numerics.json`
→ `analysis/geometry_contract.py` 的 `comsol_runtime` → `resolved_geometry.json`
→ `load_oatof_contract.m` → `run_oatof_model.m` → `oatof_configure_particle_model.m`。
`configure_oatof_segmented_output.m` 继续负责输出时刻构造；不得另建一套生产配置或手工维护 GUI 数值。

目前作者合同的 `solver_steps=free` 没有被活动构造器消费；`geometry_contract.py` 只传递 numerics，
构造器、`run_fixed_particle_retrace.m` 和 `verify_oatof_comsol_sync.m` 分别硬编码写入/检查闲置的 `tstepsbdf=free`。
这不是“合同已被消费但写错键”。正式修复需在数值合同显式表达
formulation、活动积分器、相应步策略、容差/缩放与输出存储，再由既有构造边界写入并读回**活动键**。
重追迹与 GUI 对等验证须复用这一设置和判据；只再修改闲置 BDF 键不能关闭本问题。

N100 对照通过只允许形成项目性能建议。正式采用仍需完成合同/构造器门禁、目标样本的适用验证、
MPH 保存后重新打开及 GUI Compute 核验，并按项目既有发布事务更新资产身份。
几何和场不变不免除数值设置的 GUI 对等检查；本次没有重求电场、网格收敛、CAD 或新 Formal 发布。

[prior-guide]: ../../../../docs/history/20261021__comsol-mesh-and-particle-performance-research.md
[b-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_121557__benchmark__comsol__oatof-cpt-baseline-r04/summary.json
[b-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_121557__benchmark__comsol__oatof-cpt-baseline-r04/run_manifest.json
[b-log]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_121557__benchmark__comsol__oatof-cpt-baseline-r04/logs/cpt_native.log
[r1-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_122558__benchmark__comsol__oatof-cpt-reference/summary.json
[r2-settings]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_124653__benchmark__comsol__oatof-cpt-reference-r02/inputs/settings.json
[r2-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_124653__benchmark__comsol__oatof-cpt-reference-r02/summary.json
[r2-log]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_124653__benchmark__comsol__oatof-cpt-reference-r02/logs/cpt_native.log
[cal-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_130702__analysis__python__oatof-cpt-comparison/summary.json
[cal-result]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_130702__analysis__python__oatof-cpt-comparison/results/comparison.json
[dp5-failed]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_130857__benchmark__comsol__oatof-cpt-dp5-reference-a/summary.json
[dp5a-settings]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_131110__benchmark__comsol__oatof-cpt-dp5-reference-a-r02/inputs/settings.json
[dp5a-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_131110__benchmark__comsol__oatof-cpt-dp5-reference-a-r02/summary.json
[dp5a-log]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_131110__benchmark__comsol__oatof-cpt-dp5-reference-a-r02/logs/cpt_native.log
[a-comparison]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_132210__analysis__python__oatof-cpt-comparison/results/comparison.json
[dp5a1-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_132944__benchmark__comsol__oatof-cpt-dp5-one-core/summary.json
[dp5a1-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_132944__benchmark__comsol__oatof-cpt-dp5-one-core/run_manifest.json
[dp5a1-reconciliation]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_132944__benchmark__comsol__oatof-cpt-dp5-one-core/reconciliation_evidence.json
[dp5a1-native]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_132944__benchmark__comsol__oatof-cpt-dp5-one-core/results/bench_summary.json
[dp5b8-settings]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_134737__benchmark__comsol__oatof-cpt-dp5-tight-eight-core/inputs/settings.json
[dp5b8-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_134737__benchmark__comsol__oatof-cpt-dp5-tight-eight-core/summary.json
[dp5b8-native]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_134737__benchmark__comsol__oatof-cpt-dp5-tight-eight-core/results/bench_summary.json
[dp5b8-log]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_134737__benchmark__comsol__oatof-cpt-dp5-tight-eight-core/logs/cpt_native.log
[dp5b8-field-csv]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_134737__benchmark__comsol__oatof-cpt-dp5-tight-eight-core/results/internal_tet_field_probe.csv
[dp5-cal-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_140450__analysis__python__oatof-cpt-comparison/summary.json
[dp5-cal-result]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_140450__analysis__python__oatof-cpt-comparison/results/comparison.json
[dp5-cal-acceptance]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_140450__analysis__python__oatof-cpt-comparison/results/acceptance.json
[numerics]: ../../config/formal_solver_numerics.json
[output-builder]: ../../comsol/configure_oatof_segmented_output.m
[saved-readback]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_102831__test__comsol__field-and-cpt-followup__r02/results/oatof_readback_summary.json
[old-numerical]: NUMERICAL_VALIDATION_20260716_18.md
[official-formulation]: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_modeling.05.09.html
[official-time]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_solver.51.51.html
[official-solver]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_solver.36.139.html
[official-variables]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_solver.51.57.html
[official-example]: https://doc.comsol.com/6.4/doc/com.comsol.help.models.particle.trapped_protons/trapped_protons.html
[official-particle]: https://doc.comsol.com/6.4/doc/com.comsol.help.llmatlab/llmatlab_ug_ref.9.51.html
[official-threads]: https://www.comsol.com/support/knowledgebase/1096
[official-tuning]: https://www.comsol.com/support/knowledgebase/1324
[official-hardware]: https://www.comsol.com/support/knowledgebase/866
[official-shape]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_xmesh.35.4.html
[official-electric-force]: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_acdc.07.22.html
[official-plot-quality]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_results.37.024.html
[official-interp]: https://doc.comsol.com/6.4/doc/com.comsol.help.llmatlab/llmatlab_ug_ref.9.37.html
[scale-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_141035__benchmark__comsol__oatof-cpt-dp5-scale30000/summary.json
[sparse-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_142636__benchmark__comsol__oatof-cpt-dp5-scale30000-sparse/summary.json
[sparse-log]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_142636__benchmark__comsol__oatof-cpt-dp5-scale30000-sparse/logs/cpt_native.log
[final-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_144817__analysis__python__oatof-cpt-comparison/summary.json
[final-comparison]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_144817__analysis__python__oatof-cpt-comparison/results/comparison.json
[final-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_144817__analysis__python__oatof-cpt-comparison/run_manifest.json
[extractor-native]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_144857__test__comsol__oatof-extractor-probe/results/extractor_probe_summary.json
[extractor-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_144857__test__comsol__oatof-extractor-probe/run_manifest.json
[official-scaling]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_solver.36.130.html
[official-timesteps]: https://www.comsol.com/support/knowledgebase/1254
[official-time-interpolation]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_solver.36.017.html
[official-data-storage]: https://www.comsol.com/support/learning-center/article/reducing-the-amount-of-solution-data-stored-in-a-model-66461
