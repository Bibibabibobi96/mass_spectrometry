# 公共分析函数

本目录提供求解器无关的数值函数，不读取项目配置或选择科学验收阈值。调用者负责母群、有效事件、
单位、输入身份及资格；方法依据见[验证方法](../../docs/science/VALIDATION_METHODS.md)，项目结果归PROJECT或INTEGRATION。

## 按问题定位

| 任务 | 模块与入口 | 输入和边界 |
|---|---|---|
| TOF直接峰宽、形状与bootstrap比较 | [peak_metrics.py](peak_metrics.py)：`compute_peak_metrics`、`compare_peak_shapes`、`bootstrap_resolution_difference` | TOF用μs、质量用Da；至少3个有限、正值且有方差的到达时间；设置由调用方分析合同提供 |
| 两份场样本完整配对、RMS差 | [field_comparison.py](field_comparison.py)：`merge_complete_samples`、`normalized_rms_difference_pct` | 键覆盖须一致且唯一；电场用V/m；近零参考的相对差可为null，不能当零误差 |
| 两个量的总体矩 | [population_moments.py](population_moments.py)：`population_pair_moments` | 同长有限一维数组；ddof=0，无权重或单位转换；常量相关系数为null |
| 纵向多项式拟合与残差 | [longitudinal_fit.py](longitudinal_fit.py)：`fit_longitudinal_polynomial` | z用mm、vz用mm/μs；调用方确认有限配对和可辨识阶数；残差sigma为ddof=1，不代表冷却或独立噪声 |
| 按原粒子ID配对事件字段 | [particle_events.py](particle_events.py)：`group_particle_events`、`iter_particle_event_fields` | 保留母群、事件顺序及数量差异；不生成ID、丢弃未知粒子或选择相等容差 |
| 从分辨率要求估算时间误差预算 | [tof_error_budget.py](tof_error_budget.py)：`calculate_tof_error_budget`及同名模块CLI | Python API时间用秒；CLI的`--flight-time-us`用μs；只做规划，高斯预算不能代替直接FWHM，见[方法与命令](../../docs/science/TOF_ERROR_BUDGET.md) |

母群选择、单位转换和指标判定必须在调用点显式完成；不同函数的总体矩、样本sigma和直接峰宽不能互换。
本层不提供运行器，也不从目录、软件成功退出或数值结果自动推断Candidate/Formal资格。

## 验证入口

`test_population_moments.py`、`test_longitudinal_fit.py`、`test_particle_events.py`和`test_tof_error_budget.py`
在本目录验证纯函数边界。峰形与场比较的行为回归仍由实际消费者维护：
[oa-TOF峰形测试](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_peak_metrics.py)、
[场比较测试](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_field_comparison_contracts.py)；
MR及integration另测其输入接线和科学合同。修改公共函数后用[L1](../../docs/OPERATIONS.md#分层门禁)查看受影响消费者。
