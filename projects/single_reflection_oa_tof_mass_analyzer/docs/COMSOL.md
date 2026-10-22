# 单次反射正交加速飞行时间质量分析器：COMSOL实施与验证

本文只记录COMSOL入口、模型树和独立验收。当前项目资格、跨求解器结论与开放任务只见
[`PROJECT.md`](PROJECT.md)。先按下表读取本次需要的章节；完成记录从项目 README 的 History 索引追溯。

| 本次任务 | 章节 |
|---|---|
| 构建或复现 | [入口](#活动入口)、[输入合同](#模型与合同)、[实现边界](#当前实现边界) |
| 网格／积分精度和成本比较 | [数值配置顺序](#精度与数值配置的使用顺序) |
| 检测事件及稀疏输出 | [读取步骤](#原生事件读取的操作顺序)、[辅助记录候选](#原生辅助变量记录候选) |
| 发布或修改正式资产 | [GUI 与验收](#gui与验收)、PROJECT 中的当前资格 |

## 活动入口

- 具名生产入口：`../comsol/run_oatof_model.m`
- 模型树内部实现：`../comsol/oatof_build_model_core.m`，不作为位置参数公开入口
- MATLAB单元：`../tests/comsol/test_support/run_oatof_matlab_unit_tests.m`
- Formal写入合同：`../tests/comsol/test_support/run_oatof_formal_write_contract_tests.m`
- N=100候选功能：`../tests/comsol/run_n100_candidate_functional.ps1`
- 几何同步：`../workflows/formal_reference/verify_geometry_contract.ps1`

版本与启动采用[仓库操作指南](../../../docs/OPERATIONS.md)，连接复用、重试和失败分类见
[公共 COMSOL 入口](../../../common/comsol/README.md)。项目任务不自行
`mphstart`。普通构建不得写Formal路径；只有获批promotion事务中角色与目标精确匹配时才允许。

## 模型与合同

生产入口只消费`../config/resolved_geometry.json`或上层显式冻结的Candidate resolved；
`../config/formal_solver_numerics.json`是网格、分段时间输出和solver设置的唯一权威。Candidate
`ContractPath`必须贯穿顶层入口、底层构建器和时间窗口，不能由理论默认值覆盖。

模型树按加速器、反射器、检测器、漂移区、栅网、网格、粒子物理和结果节点分责。影响结果的参数、
选择集、材料、网格、物理、Study/Solver、数据集和图必须持久化到MPH并可由Desktop查看与Compute。

## 当前实现边界

- 当前批准几何为闭合加速器屏蔽，没有RF注入侧孔；`interfacePort`只用于隔离候选，不属于Formal。
- 加速器局部尺寸与参考档读取数值合同；这两个字段本身不证明空间收敛。局部网格必须检查实际
  选择、操作顺序、阶次和单元／DOF，不进行无目标反射器全域加密。
- 粒子曲面边界还需独立验证组件几何表示阶次（`comp.sorder()`），不以电势阶次、单元数或 `rtol`
  代替；源应位于离散后的有效域。曲面表示可同时影响源是否释放、撞壁时刻与位置。解析小模型的
  通过档不能直接作为仪器默认；当前证据与适用范围由 PROJECT 统一维护。
- 分段时间输出必须以全局细时间格对齐；求解器只存合同规定的窗口与状态。
- `solver_steps` 与 `times_to_store` 从 resolved 数值合同消费。构造和重追踪共用
  `oatof_cpt_solver_policy`，按活动 GA/BDF/DP5 选择对应步策略键并回读；同步核验走同一边界的只读模式。
  项目当前只支持 `times_to_store=tlist`，不继承未声明的内部步抽样设置。存量 MPH 的旧设置须独立核验，
  源码修复本身不更新其资产身份或资格。
- 固定粒子释放按mm读取，逐粒子到达事件统一由项目提取器处理。COMSOL/MATLAB只导出带终态分类的原始事件CSV及Python分析请求；FWHM、R、均值/标准差、KDE、bootstrap和源映射拟合只由`analysis/analyze_comsol_detector_events.py`经`reference_analysis`发布。
- 检测器提取区分三维静止尾段和近面运动：空间容差仅判断平台是否靠近检测面，静止判断只容许浮点表示余量。
  零及微小正负冻结平台从平台前下降段回推；无有效接近段，或外推早于所用接近段终点、晚于首个确认平台点时不给有效到达。
  冻结附近查询坐标可能仍有插值过渡，最后变化查询点不能作为真实到达时间的下界；这种回推仍须通过独立数值收敛门槛。
  真正穿越须有局部正负侧证据；全零静止、触面后返回和跨缺口数据不冒充到达。输出保留所用原始采样行号供复核。
- 可组合理想场替换只用于原因隔离，不形成Formal性能声明。

## 精度与数值配置的使用顺序

先从 [PROJECT](PROJECT.md) 确认用途：重现已有 Formal 时消费其冻结身份；新的精度／性能研究则
冻结新的输入与判据，不覆盖正式 MPH。网格与输出的实际值从数值合同读取，不将下表诊断配置写成默认值。

| 选择 | 现有证据能支持什么 | 还必须检查什么 |
|---|---|---|
| 生产网格与参考网格 | 合同区分日常加速器局部尺寸与参考尺寸 | 这两个字段不是新实验自动通过空间收敛的证明；作用选择集、阶次、场与功能指标需对应 |
| 原生 CPT 时间设置 | 同一 FEM/N100 的 DP5、活动 `free`、`rtol=1e-13`、最大内部步长 50 ns 已建立参考与重复 | 输出表按冻结窗口读取；50 ns 不是检测事件误差，1 ps 也不是应设置的积分步长；该配置未推广为 Formal |
| 结果读取 | 合并读取须保持原有采样状态、事件和字段 | 局部倍率不能代替完整流程成本；实际证据与限制查 PROJECT |
| 降低计算成本 | 在同一功能预算下比较相邻网格／时间配置及完整资源成本 | 保留参考重复不确定性和全部状态门；时间差小不能覆盖位置 RMS 失败 |

### 从真实观测到规划预算的实例

以下命令只演示怎样消费既有 N100 参考观测；输入来源见[冻结比较表][precision-comparison]。
允许 R 下降 1% 和固定外标偏差 1 ppm 是规划假设，不是本项目批准的功能要求。

```powershell
python -m common.analysis.tof_error_budget --flight-time-us 71.35279859675002 --reference-resolution 37054.74023592537 --max-resolution-loss-pct 1 --mass-bias-ppm 1 --format markdown
```

该样本的直接 FWHM 与高斯代理明显不同，且有多个 KDE 模态，不能用高斯 sigma 预算作验收。
按[时间预算指南](../../../docs/TOF_ERROR_BUDGET.md)先留出其他未计入误差，再由完整配对事件重算
canonical 峰形／FWHM、共同漂移、全部粒子和状态指标；通过声明预算后才比较成本。

[precision-comparison]: ../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195714__analysis__python__oatof-cpt-comparison/results/comparison.json

## 原生事件读取的操作顺序

1. 求解前冻结状态存储、Wall 的物理选择集、Freeze／Disappear 行为和目标探测器定义；旧解未存的状态不能事后恢复。
2. 先核对数据集、粒子 ID 与单位，分开记录请求的输出时刻和实际保存的解时刻，不能只看导出行数。
3. 原生 `cpt.st` 用于核对边界停止时刻；仍须确认停止于目标检测器而非其他壁面。Freeze 保留的非零撞壁速度不能用作否定条件。Counter 的 `rL` 是所选区域入选逻辑，不能无条件当作最后停止边界编号。
4. 若读取固定 t 的 XYZ，再使用已有提取器检查连续数据、合法接近段和平台／穿越；无法支持事件时保留拒绝原因，不能扩大近面容差补命中。
5. 比较原生时刻、坐标估计、目标事件集合和独立参考。两种方法一致只说明这一事件／读取链，不能替代场与积分收敛。

当前读取限制：DP5 稀疏输出的固定 t 坐标可停留在检测面前，Counter 也可漏计，即使原生
停止时刻和事件位置正确。改用 st／末次解读取、求解后创建 Counter 或 StoreExtra，均不能
视作通用修复。输出表会影响保存状态和 Counter 归属，但内部公式尚未识别；不要用加密输出、
放宽空间容差或把全部停止当目标命中来绕过这一缺口。

[官方状态](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.02.html)
与 [Freeze 定义](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.38.html)
限定停止数据的含义。现有重追迹诊断可在求解前启用状态存储；默认关闭，未存状态不能事后恢复。
当前候选范围和保留的负结果查 [PROJECT 的兼容边界](PROJECT.md#已知兼容边界)。

### 原生辅助变量记录候选

[Wall 重赋值](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.04.html)
和[辅助变量](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_modeling.05.15.html)是官方支持路径。
在 CPT 下创建五个 `AuxiliaryField`，采用 `R='0'`、`Integrate='WithRespectToTime'`、
`DependentVariableQuantity='dimensionless'`，释放初值均为零；仅目标 Wall 启用重赋值：

| 节点／字段 | 目标壁面新值 |
|---|---|
| aux1／impact_hit | `1` |
| aux2／impact_time_s | `t/1[s]` |
| aux3／impact_x_mm | `qx/1[mm]` |
| aux4／impact_y_mm | `qy/1[mm]` |
| aux5／impact_z_mm | `qz/1[mm]` |

例如 `release.set('aux0_aux1','0')` 初始化第一字段，
`wall.set('caux_aux1',true)`、`wall.set('daux_aux1','1')` 在该壁面记录标记；
其余字段依同样命名规则设置。另一壁面须独立核对选择集及未启用的重赋值项。
终态一次 `mphparticle` 合并读取 pidx、五字段、`cpt.st` 和 `cpt.fs`，先恢复初始粒子身份，
再按 impact_hit 分类；其他壁面的停止时间不能冒充目标到达。

此方法只作为 GA／Newtonian 稀疏终态候选，未接入生产提取器或 Formal。DP5／NewtonianFirstOrder
组合不能沿用其终态读取假设；精确 st 查询有效也不保证晚期查询有效。两组合同时改变积分器和方程
形式，不能将差异单独归因于其中一项；停止后标记略偏离 1 时不得随意取整补命中。

迁移时保留全部粒子身份，并独立检查目标／其他壁面、重复穿越、输出敏感性与实际精度。固定字段
单时刻返回量为 O(N)，不证明求解 CPU 或完整流程随 N 线性增长。已通过的小模型范围、失败路径与
完整成本统一查 [PROJECT](PROJECT.md#已知兼容边界) 及其原生事件证据；本节只维护构造和读取步骤。

## GUI与验收

适用的候选或Formal模型必须：

1. 保存后由COMSOL Desktop重开；
2. 核对resolved参数、几何、选择集、网格及GUI可见物理节点；
3. 核对`std1/std2`与`sol1/sol2`附着，禁止GUI Compute生成新solver显示旧解；
4. 由Study Compute等价复算静电和粒子研究；
5. 复核固定粒子表、唯一terminal事件分类、输出列和manifest；terminal是事件终态，不是探测面别名；
6. 几何改变时同步SolidWorks，并由PROJECT更新资格。

当前 MPH 身份、验证结果与 GUI evidence 只查 [PROJECT](PROJECT.md) 和
[`formal_validation.json`](../config/formal_validation.json)；当前源码路径不自动重验历史资产。

## 兼容限制

COMSOL 6.4的极小粒子数不稳定由同源N=100承载前缀绕行；除PROJECT列出的重启条件外不再扫描。
已关闭的场替换扫掠、局部网格、分段时间性能、极小N调查和生产入口故障链全部从同日history快照
及来源manifest追溯。
