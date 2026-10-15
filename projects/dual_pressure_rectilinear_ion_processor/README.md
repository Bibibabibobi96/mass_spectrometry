# 双压力区矩形射频离子处理器

以简化实体电极和原生 SIMION 求场复现多极引导、捕获、碰撞冷却、聚集、整体抬升与正交引出。
本器件在现有仓库内独立维护，复用公共释放、RF、资源调度和运行证据合同；不继承其他器件的验收资格。

## 阅读与执行

- [项目状态](docs/PROJECT.md)：当前科学参数、坐标、证据边界和待完成动作。
- [SIMION 实施](docs/SIMION.md)：软件入口、官方依据和运行边界。
- 科学输入：[baseline](config/baseline.json)、[原生电压](config/native_operating_point.json)、[释放](config/source.json)、[验收](config/acceptance.json)。
- 来源与诊断：[尺寸来源](config/geometry_sources.json)、[全过程诊断](config/diagnostics.json)、[原生场诊断](config/field_diagnostics.json)。
- 执行输入：[numerics](config/numerics.json)、[execution profile](config/execution_profiles.json)、[项目身份](config/project.json)。
- 仓库规则：[根入口](../../README.md)。

生产入口为 `simion/run_functional.ps1`，准备与分析由 `analysis/functional.py` 负责。
当前 N=100 路线从冻结 GEM 重新 Refine 私有原生场，不再借用或 raw-clone 旧 PA 族来建立新证据。
GUI 包也应从同一冻结几何独立求场，保留完整母群，由用户打开、Fly 和确认；准备文件不等于 GUI 验收。
`verify_project.ps1` 的轻量测试不启动商业软件，不代表真实仿真通过。

## 所有权

`config/`拥有科学与数值权威，`analysis/`拥有准备及分析，`simion/`拥有求解器投影，`tests/`拥有静态回归。
旧解析规定场只作参考。COMSOL 后续消费同一科学配置；上游真实多极杆和 MRTOF 装配应由对应器件及独立 integration 维护。
本器件的抽象引导段不表示已消费真实上游端口。

运行产物进入仓库同级 `artifacts/projects/dual_pressure_rectilinear_ion_processor/runs/`；当前状态统一见 PROJECT。

## History 索引

- [旧原生运行、随机重放与源身份边界](docs/history/20261016__native-flight-and-source-identity.md)
