# 单次反射正交加速飞行时间质量分析器：COMSOL实施与验证

本文只记录COMSOL入口、模型树和独立验收。当前项目资格、跨求解器结论与开放任务只见
[`PROJECT.md`](PROJECT.md)；2026-07-28以前的实现时间线和诊断数值冻结在
[`history/20260728__pre-document-consolidation-comsol.md`](history/20260728__pre-document-consolidation-comsol.md)。

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
- 正式数值合同以加速器`hmax=1 mm`为日常值、`0.5 mm`为收敛参考；反射器无需无目标全域加密。
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
  既有重追迹诊断可在求解前启用状态存储并读取 `cpt.st`；当前默认关闭，事后开启不能恢复未存状态。
  [官方状态与边界定义](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.02.html)
  及 [Freeze 语义](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.38.html)
  说明停止时间与冻结后保留的撞壁速度；不能用非零速度否定冻结，也不能把数值停止时间直接当作精确真值。
  已测常速平面小模型中，DP5 的稀疏输出可使 `mphparticle` 回读的冻结位置留在面前，即使原生停止时间准确。
  此时提取器拒绝事件是有效的失败关闭，不能扩大空间容差或把查询平台点当作精确碰壁位置；
  原生停止时间仍须结合目标边界身份和独立收敛验证，不能直接替换整机检测器判定。
- 可组合理想场替换只用于原因隔离，不形成Formal性能声明。

## 精度与数值配置的使用顺序

先从 [PROJECT](PROJECT.md) 确认用途：重现已有 Formal 时消费其冻结身份；新的精度／性能研究则
冻结新的输入与判据，不覆盖正式 MPH。网格与输出的实际值从数值合同读取，不将下表诊断配置写成默认值。

| 选择 | 现有证据能支持什么 | 还必须检查什么 |
|---|---|---|
| 生产网格与参考网格 | 合同区分日常加速器局部尺寸与参考尺寸 | 这两个字段不是新实验自动通过空间收敛的证明；作用选择集、阶次、场与功能指标需对应 |
| 原生 CPT 时间设置 | 同一 FEM/N100 的 DP5、活动 `free`、`rtol=1e-13`、最大内部步长 50 ns 已建立参考与重复 | 输出表按冻结窗口读取；50 ns 不是检测事件误差，1 ps 也不是应设置的积分步长；该配置未推广为 Formal |
| 结果读取 | 匹配参考精度的合并读取已在真实主链执行 | 不能省略原有采样状态、事件与字段；单次完整流程收益不作为稳定性能保证 |
| 降低计算成本 | 在同一功能预算下比较相邻网格／时间配置及完整资源成本 | 先声明预算和参考重复不确定性；旧 B12 的位置 RMS 失败不能因时间差小而改为通过 |

### 从真实观测到规划预算的实例

2026-10-21 N100 参考的 [冻结比较表][precision-comparison] 给出有效平均 T=71.35279859675 us、
直接时间 FWHM=962.802574549 ps、时间等效 R=37054.7402359。这是诊断样本描述，不是新标准分辨率资格。
若仅为规划演示，假定允许 R 比此参考下降 1%、固定外标质量偏差 1 ppm，可使用唯一计算器：

```powershell
python -m common.analysis.tof_error_budget --flight-time-us 71.35279859675002 --reference-resolution 37054.74023592537 --max-resolution-loss-pct 1 --mass-bias-ppm 1 --format markdown
```

输出的最低 R=36684.1928336、最大峰宽=972.527853079 ps，剩余峰宽裕量约 9.72528 ps；
共同时间偏移的固定外标限约 35.6764 ps。1% 和 1 ppm 是显式假设，不是本项目已批准需求，
且剩余裕量必须先留给尚未计入的物理／测量误差，不能全部分给数值求解。

尤其不能直接把计算器的高斯 sigma 列当作本样本的验收阈值：同一参考的高斯代理峰宽约
1429.2216 ps，直接峰宽比该代理小约 32.63%（以代理为分母），且有两个显著 KDE 模态。实际候选须由完整配对事件重算
canonical 峰形／FWHM，并分别检查共同漂移、全部粒子和状态指标。通用公式及条件只查
[时间预算指南](../../../docs/TOF_ERROR_BUDGET.md)。达到已声明功能预算后，才在通过的配置中选成本较低者。

[precision-comparison]: ../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195714__analysis__python__oatof-cpt-comparison/results/comparison.json

## 原生事件读取的操作顺序

1. 求解前冻结状态存储、Wall 的物理选择集、Freeze／Disappear 行为和目标探测器定义；旧解未存的状态不能事后恢复。
2. 先核对数据集、粒子 ID 与单位，分开记录请求的输出时刻和实际保存的解时刻，不能只看导出行数。
3. 原生 `cpt.st` 用于核对边界停止时刻；仍须确认停止于目标检测器而非其他壁面。Freeze 保留的非零撞壁速度不能用作否定条件。Counter 的 `rL` 是所选区域入选逻辑，不能无条件当作最后停止边界编号。
4. 若读取固定 t 的 XYZ，再使用已有提取器检查连续数据、合法接近段和平台／穿越；无法支持事件时保留拒绝原因，不能扩大近面容差补命中。
5. 比较原生时刻、坐标估计、目标事件集合和独立参考。两种方法一致只说明这一事件／读取链，不能替代场与积分收敛。

已知恒速平面小模型的[后续验证](history/20261022__native-event-readback-and-counter-validation.md)区分了
三条路径：普通时刻库存、固定 t 坐标、实际停止时刻的位置查询。开启 StoreExtra 后，后者已在 N100
解析例中通过；前两者未自动增加碰壁时刻或修复稀疏平台。稀疏 Counter 不论求解前后创建均漏计，
仅改变输出表的密档通过；因此 Counter 也要独立验证输出敏感性，不能直接用来补齐拒绝事件。
该诊断的 N×N 时刻／粒子查询仅用于小样本，不是可无条件扩大粒子数的高效生产实现。

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
