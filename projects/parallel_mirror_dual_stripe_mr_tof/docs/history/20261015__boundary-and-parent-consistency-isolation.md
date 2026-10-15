# 边界敏感性与父场组合一致性隔离里程碑

DOC_STATUS: ARCHIVED_READ_ONLY

归档类型：milestone。冻结截至2026-10-15直接父场对照完成时的有限诊断；不是整程收敛或COMSOL性能复现声明。
当前决策与未关闭动作只见[PROJECT](../PROJECT.md)，本页不作为后续自动执行计划。
归档前当前文档版本为Git `4d196924`；本页补入该版本之后完成的直接父场证据，不修改原run。

## 控制变量与边界来源

沿用当前冻结K=24.5、加速器y=−55 mm、会聚倾镜、完整C0装配、电压与源；无重新调压。
原生细镜五面输入来自中央及父场，FEM mesh4独立求整个C0。
[原25点检查][input]中，x=2 mm面原生中央场−FEM电势均差−0.488858 V、范围0.017444 V，
沿y差商2.623–7.294 V/m，并非纯常数偏移。差商不等于实际消费者受力。

[donor][donor]从同一mesh4导出0.25/0.25/0.10 mm薄体积V/valid，
覆盖[0,−65,90]至[2,360,324] mm，35838369节点，无未知节点，两PA共573414016字节。
所查25点及支撑全有效；x=2面最大电势表示差0.000988 V，四中心慢向差商最大差0.04253 V/m，
一处z差商仍差9.897 V/m，不能授全边界资格。载入8.406 s、查询207.236 s、写盘0.415 s；
总862.880 s含约594 s共享排队，无重新求场或飞行。

## 五面边界单因素飞行

[203103][flight]固定正镜完整求解域、0.04/0.20/0.02 mm网格、fractional、1e−5 V及五颗入口六维状态和时钟，
仅将五面边界换为上述donor；x=0仍对称，物理电极不覆盖，不裁剪PA。五颗均到同一出口，无碰撞或缺失。

| 相对mesh4的单镜出口最大绝对差 | 原native | FEM边界native |
|---|---:|---:|
| y/mm | 0.071484884 | 0.002356229 |
| vy/(mm/μs) | 0.009194909 | 0.000770351 |
| x/mm | 0.007175347 | 0.009011076 |
| vz/(mm/μs) | 0.000288182 | 0.000469998 |
| 相对中心TOF/ns | 0.037722466 | 0.038962600 |

公共中心TOF差从+0.299243降至+0.007180 ns，不算峰宽。慢向位置／速度差约缩小30／12倍，
但横向和相对计时未同步改善。总1207.641 s，gem2pa 94.229 s，边界／Refine脚本978.855 s；
其中原生Refine909.16 s、1030次迭代、Delta9.3e−6 V，实际五颗短段Fly1.74 s。
前一202936在商业计算前因48 GiB警告值误作硬预约失败；改回公共原生重阶段预算后以新身份成功，未改物理输入。

## 父场与中央场比较

[211107][parent]只加载现父PA一次，继承原中央／FEM25点值；全点有限，邻近支撑无物理节点。

| 慢向电势差商/V/m | 四中心范围 | x=2面20点电势均差/V |
|---|---:|---:|
| 父场−FEM | 1.407–6.020 | +1.334991 |
| 中央场−FEM | 2.623–7.294 | −0.488858 |
| 中央场−父场 | 1.216–1.274 | −1.823849 |

父层已有慢向跨源差，中央层又改变它；不能单凭同坐标比较唯一归因。
查询采用公共SIMION/postprocess轻阶段，总13.785 s，无求场、飞行或大PA复制。
旧210657错标flight的等待已取消并封存interrupted，未打开PA；新旧身份及输入分别保留。

## 当前电压下的直接父场复核

父场基解和P1/P2/S1/TE1四列响应几何相同，均为0.50/1.00/1.00 mm、fractional、1e−5 V；
响应归一化10000 V，当前完整组合G=1.002032603，不把G当误差界。
[212434][direct]从当前完整电压重新编译GEM，仅求父场，不建局域场或飞行。
原生Refine4150次、Delta1e−5 V、843.10 s；总886.708 s，gem2pa 19.680 s，查询1.890 s。

| 直接场−物化组合场，所查25点 | 最大绝对差 |
|---|---:|
| 电势/V | 1.6982×10⁻¹¹ |
| y向电势差商/(V/m) | 2.2737×10⁻⁹ |
| z向电势差商/(V/m) | 2.2737×10⁻⁸ |

直接场−FEM慢向差商仍为1.407–6.020 V/m：这些点上的组合附加差不能解释当前跨来源差。
该一致性不证明网格、停止误差或整程收敛；所有诊断均未计算五颗／25点的FWHM或R。

## 保留与清理

上述运行按公共manifest验证并登记；直接父PA、边界对照PA及必要来源保留，临时作者均已公共精确清理。
此前旧mesh1八PA退役释放5198465376字节，26份小证据及donor依赖helper保留；
旧平行镜K25.5的181800八PA/surface退役释放17492195912字节，43份小证据、重建计划和原响应来源保留。
旧mesh1/2/3的001600/150021/124839原MPH保留；历史IOB须重物化／重装配，不称完整GUI交付。
两份退役收据位于各原run的`solver_review_retirement_receipt.json`，不以运行终态本身授权删除。

[input]: ../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_191649__analysis__cross__native-mirror-boundary-input-check/summary.json
[donor]: ../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_194413__analysis__cross__fem4-boundary-donor-representation/summary.json
[flight]: ../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_203103__sim__simion__fem4-boundary-only-positive-mirror/summary.json
[parent]: ../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_211107__analysis__simion__parent-boundary-fixed25-query/summary.json
[direct]: ../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_212434__build__simion__direct-parent-fixed-grid/summary.json
