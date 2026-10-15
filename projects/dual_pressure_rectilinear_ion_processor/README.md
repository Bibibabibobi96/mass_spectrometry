# 双压力区矩形射频离子处理器

本项目以简化实体电极建模和原生SIMION求场复现多极杆引导、捕获、碰撞冷却、轴向聚集、整体电位抬升与正交引出。
它是现有仓库内的独立器件项目，复用公共释放、RF波形、SIMION与run治理机制。

## 阅读与输入

1. 仓库规则：[根入口](../../README.md)。
2. 当前范围、资格和开放任务：[项目状态](docs/PROJECT.md)。
3. SIMION实施、官方来源与执行边界：[SIMION说明](docs/SIMION.md)。
4. 科学输入：[baseline](config/baseline.json)、[原生电压](config/native_operating_point.json)、[释放](config/source.json)、[验收目标](config/acceptance.json)。
5. 执行绑定与载荷保留：[execution profile](config/execution_profiles.json)。
6. 尺寸出处：[geometry sources](config/geometry_sources.json)；全过程诊断：[diagnostics](config/diagnostics.json)。
7. 数值输入：[numerics](config/numerics.json)；项目身份：[descriptor](config/project.json)。

唯一生产workflow是原生实体电极求场；旧解析workflow尚未运行，只保留参考对照。
生产入口为`simion/run_functional.ps1`，求解器无关准备为`analysis/functional.py`；
`verify_project.ps1`运行本项目轻量unittest，不启动商业软件。当前实施与结果由项目状态维护，
不由文件存在推断通过。
当前来源映射区分报告尺寸、模型解释和假设；修订几何采用0.1 mm网格与60段辅助形状近似。
旧几何r06 N=10探索结果由项目状态维护，不作为当前几何验证。正式默认N=100，探索不授予正式功能或GUI资格。
该器件不继承多极杆、静电正交加速器或oaTOF项目的资格。

## 所有权

`config/`拥有科学与数值权威，`analysis/`拥有求解器无关编译及分析，`simion/`拥有SIMION投影，
`tests/`拥有静态回归。COMSOL后续消费同一科学配置，不另建第二套物理参数。
上游实际多极杆模型继续归原项目；正式跨部件连接、端口与联合证据应归独立integration。
本轮前置多极杆为本器件功能workflow中的抽象引导段，不表示已消费原多极杆出口证据。

新增代码与配置按正式功能维护；运行产物仅进入仓库同级
`artifacts/projects/dual_pressure_rectilinear_ion_processor/runs/<run_id>/`。

## 坐标与当前证据

原生PA、native projection及source.json保持局部母集；公共刚体合同将局部状态映射为
`world=(-local_z, local_x, 9.8-local_y)` mm，速度仅旋转。项目世界x为横向、+y为慢漂移、−z为引出，
frame为`ion_processor.xyz.reflection_z.drift_y.transverse_x.local.v2`。
方向与MRTOF兼容，但装配port的Y尚未注册，不能称MRTOF全局坐标。
r10的真实vendor pose basis及0.1 mm网格映射已通过；真实native Fly已完整结束，N=10为`exploration_pass`：
捕获10/10、引出9/10、捕获均能0.03840967267 eV，引出前9粒子均在LP，慢轴σy=0.331102781675 mm，
平均引出能量3927.990922904 eV。这是新世界坐标探索证据，不是N=100正式baseline或Candidate。

r07保留N=10负结果：捕获10/10、引出8/10、引出子群平均3927.873 eV、全母群引出前慢轴σ=15.234 mm，未达聚集目标。
旧r07 GUI重复Fly曾改写源PA0，旧一致性证据无效。源PA0已从SHA验证的PA#重新Refine并精确恢复；
当前GUI准备完整clone 18个PA族文件，构建前后复核源SHA，不共享可写PA。

全过程诊断包含六个图角色：`trajectory_geometry`、`timed_clouds`、`extraction_local_clouds`、
`stage_phase_space`、`cooling_stage_energy`和`population_evolution`，各含PNG/SVG及来源metadata。
原生场另输出`native_field_samples_project.csv`，把位置和场向量转换至项目坐标；原生局部查询CSV继续保留。

GUI准备checkpoint为`20261015_181000__test__simion__ion-processor-gui-ready__r10`：
完整clone 18文件PA族，source/runtime与r10精确一致，真实IOB姿态构建已通过；尚未Fly。
GUI由用户打开、Fly并确认。当前仅准备文件，不自行追加GUI或重复Fly验收，旧r07无效repeat证据不复用。
