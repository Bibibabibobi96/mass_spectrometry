# 公共分析函数

本目录提供求解器无关的数值函数及已准备结果的图形导出，不读取项目配置或选择科学验收阈值。调用者负责母群、有效事件、
单位、输入身份及资格；方法依据见[验证方法](../../docs/science/VALIDATION_METHODS.md)，项目结果归PROJECT或INTEGRATION。

## 按问题定位

| 任务 | 模块与入口 | 输入和边界 |
|---|---|---|
| TOF直接峰宽、形状与bootstrap比较 | [peak_metrics.py](peak_metrics.py)：`compute_time_peak_metrics`、`compute_peak_metrics`、`compare_peak_shapes`、`bootstrap_resolution_difference` | TOF用μs、质量用Da；至少3个有限、正值且有方差的到达时间；设置由调用方分析合同提供 |
| 两份场样本完整配对、RMS差 | [field_comparison.py](field_comparison.py)：`merge_complete_samples`、`normalized_rms_difference_pct` | 键覆盖须一致且唯一；电场用V/m；近零参考的相对差可为null，不能当零误差 |
| 多变量及二变量总体矩 | [population_moments.py](population_moments.py)：`population_moments`、`population_pair_moments` | 多变量输入为有限二维数组，行是已选择观测、列是变量；可显式传入严格正有限相对权重；ddof=0，不转换单位或筛选粒子；二变量接口仍为无权，常量相关系数为null |
| 已选择束团的束宽、真角度发射度与零场预测 | [beam_focus_diagnostics.py](beam_focus_diagnostics.py)：`prepare_focus_diagnostics`、`prepare_time_focus_diagnostics`及prepared结果绘图 | 显式全母群ID→正相对权重；观察面及出口群由适配器确定；mm／μs、ddof=0；实际穿面与无场反事实分开 |
| 有界定向穿面证据 | [plane_crossings.py](plane_crossings.py)：`iter_bounded_plane_crossings` | 复用已有`PhaseSpaceState/PlaneSurface`；位置mm、速度m/s、共同仪器时间μs；返回原anchor、夹持区间、alpha及观察到的穿越次数，不生成第二份状态表 |
| 纵向多项式拟合与残差 | [longitudinal_fit.py](longitudinal_fit.py)：`fit_longitudinal_polynomial` | z用mm、vz用mm/μs；调用方确认有限配对和可辨识阶数；残差sigma为ddof=1，不代表冷却或独立噪声 |
| 按原粒子ID配对事件字段 | [particle_events.py](particle_events.py)：`group_particle_events`、`iter_particle_event_fields` | 保留母群、事件顺序及数量差异；不生成ID、丢弃未知粒子或选择相等容差 |
| 批量导出已准备图形 | [figure_export.py](figure_export.py)：`export_figures` | 调用者给定完整stem→figure、formats、dpi与facecolor；整批目的路径预检、独占新建，返回实际导出记录；不计算指标或创建图形 |
| 完整母群与寿命边界事实 | [particle_census.py](particle_census.py)：`lifetime_position`、`partition_cohort`、`subset_efficiency` | caller显式声明生效／终止时间、容差、分类标签和完整母群权重；保留原ID、分类数和明确分子分母；未知不推断存活，非出口终止不等于撞壁 |
| 从分辨率要求估算时间误差预算 | [tof_error_budget.py](tof_error_budget.py)：`calculate_tof_error_budget`及同名模块CLI | Python API时间用秒；CLI的`--flight-time-us`用μs；只做规划，高斯预算不能代替直接FWHM，见[方法与命令](../../docs/science/TOF_ERROR_BUDGET.md) |

母群选择、单位转换和指标判定必须在调用点显式完成；不同函数的总体矩、样本sigma和直接峰宽不能互换。
本层不提供运行器，也不从目录、软件成功退出或数值结果自动推断Candidate/Formal资格。

MP→IP接收和IP→MR测量源／分析用`partition_cohort`校验完整原ID的转交分区；分类只表示转交事实，
未知终态不被解释为物理损失。MR分析用`subset_efficiency`分别报告转交条件和原母群效率；旧来源
缺少完整母群权重时，全链加权值明确不可计算，转交群的已知权重仍可计算条件效率。
MR测量飞行将原生碰撞、超时、程序性拓扑拒绝和未知终态分别计数；终止回调的未知代码不作为物理损失。

`compare_peak_shapes`默认只比较分布，配对相关系数为null；提供keyword-only
`left_particle_ids`与`right_particle_ids`后才计算配对相关。`bootstrap_resolution_difference`
必须提供这两个参数。ID须为与各自TOF同长、唯一且顺序完全一致的整数一维数组；拒绝bool、类型强转、
排序、交集或重编号来凑成配对。调用方负责同源身份及真实ID来源，等长或两个独立run的同名编号不证明同源。

`compute_time_peak_metrics`只计算时间域KDE、直接FWHM、ddof=1样本sigma和时间等效比值，
不需要名义质量；`significant_time_kde_modes`来自时间密度。权重可省略或显式给出正有限等权，
共同常数只改变记录的权重和，不改变KDE；非等权、bool、字符串和复数权重拒绝，不静默转换或丢弃。
返回`metrics.analysis_metadata`记录方法`common_gaussian_kde_time_v2`、设置、单位、样本数、权重和、
有效数、可计算状态及未评定科学资格。TOF数组本身不能证明共同钟，默认time reference为unspecified；
调用者须绑定其已验证的出生／脉冲／epoch证据。

`compute_peak_metrics`继续使用`m0*(tof/mean(tof))²`，这是Da轴的名义质量相对映射，
不是独立绝对标定，也没有隐含电荷态。默认保留既有数值和结果字段；当前发布者显式用
`include_result_metadata=True`记录`nominal_mean_relative_square_v1`、参考均值及实际名义质量。
其旧`significant_kde_modes`仍来自质量域，不能与时间域峰数换名互用；冻结历史结果不改写。

`population_moments`返回具名`PopulationMoments`：观测行数、权重和、有效数、按输入列顺序的均值及中心协方差。
协方差分母为权重和；有效数为`(sum w)^2/sum(w^2)`，仅表示权重集中程度，不证明独立物理粒子数，
也不能转换为绝对电流。未给权重时每行权重为1；空群计数和权重和为0、均值与协方差为null，
单行或常量变量保留零方差。二变量接口和局部OA出口多变量统计共用该内核；调用者仍须保证原ID与观测选择。

`beam_focus_diagnostics`的schema 2分别记录`relative_weighted_recorded_beam_moments_v2`与
`relative_weighted_recorded_time_focus_v2`。每个case必须提供与完整`sources` ID集合相等的
`particle_weights`映射；公共层按已声明群与实际可用ID索引权重，不从出口重建母群。
均值、中心SD／协方差、位置－真角度回归残差、时间／能量相关及零场漂移共用总体矩内核，
返回实际观测数、权重和及有效数；相对权重不表示电流或物理束团电荷。
`rms_*`关于声明原点，`sigma_*`关于加权均值；角度始终为`atan2(vtrans,abs(vz))`，
漂移所用斜率`vtrans/abs(vz)`不替代真角度发射度。零vz、缺状态及不可辨识斜率仍返回null。

时间分位逐行记录方法：等权使用`numpy_quantile_linear_v1`，保持原`np.quantile(method="linear")`；
非等权使用`weighted_ecdf_left_inverse_v1`，即累计相对权重首次达到p的观测值，不作插值。
两者都是全尾部经验分位宽度，不能互换成高斯或FWHM。缺观测、全群覆盖及固定ID条件继续显式发布；
零场漂移不证明真实下游焦点。绘图只读取prepared结果。IP原生与局部OA明确提供全1，IP注入权重由
项目loader从manifest验证后的冻结canonical源读取；脉冲、负z、真实出口及同群政策仍归适配器。

`export_figures`只导出显式prepared figures：目的父目录须已存在，整批路径／格式／重复目标与已有文件
在首次保存前预检，每个文件独占创建。保存失败只删除本次创建文件并传播异常，不覆盖已有产物。
返回`path、format、savefig_dpi、size_inches、bytes、facecolor`实际记录；调用者把同一列表写入结果JSON，
图名、caption、科学样本、格式、DPI、颜色及figure关闭仍由调用者拥有。IP几何比较保持PNG／SVG、210 DPI，
局部OA保持PNG／SVG、190 DPI；两者仍显式白底，未统一科学样式或分辨率。

## 验证入口

穿面内核的`CrossingBracket`为schema 1；平面法向定义正向，两端法向速度均须严格为正，
位置须实际夹持且间隔不超过调用方给定上限与明确余量。`occurrence=1`、正整数k、`None`
分别选择首次、第k次及全部记录支持的穿越；同一原始端点只计一次。缺记录不推断物理损失，
未采样区间的转折或多次穿越不在证明范围。调用者核验共同钟、frame与原记录身份，
并耗尽流式生成器后才接受整体结果；可在每次yield时用当前原始行插值，保留原单位和运算顺序。
IP和局部OA各自保留样本／脉冲／寿命与真实出口选择，均直接调用此内核。
`test_plane_crossings.py`验证手算、双方向、斜面、端点去重、first/k/all、交错ID、时间／间隔边界和禁止外推；
项目及集成测试另验证实际接线、原始CSV／raw-log锚点和冻结副本缺依赖时失败。

[test_figure_export.py](test_figure_export.py)真实渲染PNG／SVG，检查格式、尺寸、实际字节数及批量碰撞／
失败清理；两个消费者的既有导出测试另验证实际调用、原文件名/DPI和JSON记录一致。

[test_beam_focus_diagnostics.py](test_beam_focus_diagnostics.py)维护已迁入的纯解析／绘图回归和非等权手算、
分位边界、权重比例、ID重排、缺观测及平移／横向旋转测试；IP的同名测试现只验证真实源加载与公共接线，
geometry与local-focus测试继续验证完整输出及原粒子证据，functional另验证冻结副本独立执行。

`test_population_moments.py`、`test_longitudinal_fit.py`、`test_particle_events.py`和`test_tof_error_budget.py`
在本目录验证纯函数边界；[test_peak_metrics.py](test_peak_metrics.py)验证峰分析设置、曲线输入域、
手算半高宽、主峰选择、截断方向和显式ID配对。KDE、质量／时间域及场比较的消费者行为回归继续由项目维护：
[oa-TOF峰形测试](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_peak_metrics.py)、
[场比较测试](../../projects/single_reflection_oa_tof_mass_analyzer/tests/analysis/test_field_comparison_contracts.py)；
MR及integration另测其输入接线和科学合同。修改公共函数后用[L1](../../docs/OPERATIONS.md#分层门禁)查看受影响消费者。
