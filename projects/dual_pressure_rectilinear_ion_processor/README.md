# 双压力区矩形射频离子处理器

以简化实体电极和原生 SIMION 求场复现多极引导、捕获、碰撞冷却、聚集、整体抬升与正交引出。
本器件在现有仓库内独立维护，复用公共释放、RF、资源调度和运行证据合同；不继承其他器件的验收资格。

## 阅读与执行

- [项目状态](docs/PROJECT.md)：当前科学参数、坐标、证据边界和待完成动作。
- [SIMION 实施](docs/SIMION.md)：软件入口、官方依据和运行边界。
- 科学输入：[baseline](config/baseline.json)、[原生电压](config/native_operating_point.json)、[释放](config/source.json)、[验收](config/acceptance.json)。
- 来源与诊断：[尺寸来源](config/geometry_sources.json)、[全过程诊断](config/diagnostics.json)、[原生场诊断](config/field_diagnostics.json)。
- 执行输入：[numerics](config/numerics.json)、[公共执行登记](config/execution_profiles.json)、[内部运行预算](config/runtime_profiles.json)、[项目身份](config/project.json)。
- 仓库规则：[根入口](../../README.md)。

生产入口为[`simion/run_functional.ps1`](simion/run_functional.ps1)，准备与分析由
[`analysis/functional.py`](analysis/functional.py)承担。按任务查[执行与验收边界](docs/SIMION.md#执行与验收边界)、
[原生场复用与分批](docs/SIMION.md#自动分批与单工作台重放)或[GUI准备](docs/SIMION.md#gui准备与批处理区别)。
[`verify_project.ps1`](verify_project.ps1)只执行轻量测试；真实功能及用户确认结论由PROJECT维护。
该门禁通过公共计时runner即时报告失败及逐测试耗时，保持原完整测试发现范围。

公共规划的`native_functional`只支持固定524 Da／+1功能源及capture/extraction fraction指标，证据请求限`plan`。
它通过现有静态门禁和`run_functional.ps1`执行，不接受设计变量、真实上游状态或私有预算的隐式绑定；
完整配置边界见[公共执行登记](config/execution_profiles.json)，科学资格仍按PROJECT判断。

## 所有权

`config/`拥有科学与数值权威，`analysis/`拥有准备及分析，`simion/`拥有求解器投影，`tests/`拥有静态回归。
旧解析规定场已退出活动源码，历史只读记录保留其解释。COMSOL后续消费同一科学配置；
上游器件提供真实几何／出口，跨组件装配和状态交接由[统一集成](../../integrations/README.md)维护。
本器件的抽象引导段不表示已消费真实上游端口。

运行产物进入仓库同级 `artifacts/projects/dual_pressure_rectilinear_ion_processor/runs/`；当前状态统一见 PROJECT。

## History 索引

[历史索引](docs/history/README.md)集中列出已冻结实验、迁移和旧方案；需要追溯证据时按需进入。
