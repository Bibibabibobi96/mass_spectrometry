# 正交脉冲加速器

本项目独立维护二区／三区正交脉冲加速器；两者是同一硬件设计概念下的结构变体，不是运行mode。
它不属于单反射oa-TOF，也不采用MR-TOF的全局坐标。当前迁移状态、验证边界和未完成工作只查
[`docs/PROJECT.md`](docs/PROJECT.md)。

## 阅读与入口

1. 仓库规则：根[`README.md`](../../README.md)。
2. 当前事实：[`docs/PROJECT.md`](docs/PROJECT.md)。
3. 理论：[`docs/theory/README.md`](docs/theory/README.md)。
4. 项目身份：[`config/project.json`](config/project.json)；器件API语义：
   [`config/component_contract.json`](config/component_contract.json)。

独立二区计算入口是`python -m projects.orthogonal_accelerator.analysis.accelerator_time_focus`，
接受显式输入合同，`--self-test`只验证解析参考。轻量验证入口为`verify_project.ps1`，不启动商业求解器。
该门禁还使用显式`-LuaExe`或本机 SIMION 2020 所附 Lua 检查构建参数合同；没有Lua时明确跳过该项。
各API的参数和坐标约定以源码及理论为准；不提供隐藏的仪器电压、尺寸或焦面默认值。

原生PA专项回归使用`tests/simion/test_two_zone_native_geometry.lua`：只读检查冻结参数生成的
环通孔、屏蔽间隙与Fast Adjust电压，须在独立SIMION租约及受管run中执行，不属于轻量门禁。

封闭二区候选的组件级聚焦 campaign 固定在
[`config/two_zone_component_focus_campaign.json`](config/two_zone_component_focus_campaign.json)：它声明
1 mm 半径、1 mm 高圆柱的 N=100 要求、九路电压、负 z 焦面和数值/验收阈值。其结果验收入口为
`python -m projects.orthogonal_accelerator.analysis.component_focus_analysis`；该入口只消费仓库公共
ion-release receipt/CSV 及原生 SIMION 日志，不生成本地源，也不调用仪器项目。提供者自动入口`simion/run_component_focus_workflow.ps1`接受消费者的窄组件请求与仓库 common ion-release spec，冻结其 resolved campaign/plan，调用既有 PA runner 一次（cache hit 或唯一原生构建）和既有 N=100 flight runner 一次，并生成统一父 receipt。它不复制 PA、不导出第二套 response-bank，也不在构建后手工插入粒子释放；release 在编译时冻结，且其速度/能量只影响 flight，不进入 PA cache identity。低层`run_component_focus_pa.ps1`与`run_component_focus_flight.ps1`仍是该自动入口复用的单用途子运行器。

## 所有权

`analysis/`拥有器件理论和几何派生，`simion/`、`comsol/`拥有器件实现，`tests/`拥有独立回归。
共享运行、IOB基础机制、坐标与证据工具继续使用根`common/`。不保留另一份`common/accelerator/`领域实现。
离子释放、粒子状态和 FLY2 序列化是共享层职责；本项目只声明源包络与组件验收，不得复制释放器。

仪器项目通过明确接口复用本项目：自身保留系统布局、完整粒子链、联合聚焦与整机验收；
integration保存连接及冻结依赖，不保存第二份加速器模型。旧OA整机适配器只做参数映射或兼容导入。
新器件独立运行产物归`artifacts/projects/orthogonal_accelerator/`；既有OA/MR历史证据不迁移、不改身份。


## History索引

<details>
<summary>展开只读历史记录</summary>

- [20260903__legacy-accelerator-diagnostic](docs/history/20260903__legacy-accelerator-diagnostic.md)

- [加速器迁移与原生检查](docs/history/20260911__component-migration-evidence.md)

</details>
