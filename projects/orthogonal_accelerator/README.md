# 正交脉冲加速器

本项目独立维护二区／三区正交脉冲加速器；两者是同一硬件设计概念下的结构变体，不是运行mode。
器件接口声明各自局部坐标；消费者可把实际几何、PA、IOB和释放一次装配到MR-TOF全局坐标，
局部多极杆接入工作流即使用 +y 传输、-z 引出，不依靠显示坐标旋转。当前迁移状态、验证边界和未完成工作只查
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

组件聚焦合同见[封闭二区 campaign](config/two_zone_component_focus_campaign.json)，自动入口为
[`simion/run_component_focus_workflow.ps1`](simion/run_component_focus_workflow.ps1)；
[`analysis/component_focus_analysis.py`](analysis/component_focus_analysis.py)只消费公共释放凭据和原生日志。
具体工作流、输入冻结与验收边界见[组件工作流与验收](docs/PROJECT.md#组件工作流与验收)。

## 所有权

`analysis/`拥有器件理论和几何派生，`simion/`、`comsol/`拥有器件实现，`tests/`拥有独立回归。
共享运行、IOB基础机制、坐标与证据工具继续使用根`common/`。不保留另一份`common/accelerator/`领域实现。
离子释放、粒子状态和 FLY2 序列化是共享层职责；本项目只声明源包络与组件验收，不得复制释放器。

仪器项目通过明确接口复用本项目，保留系统布局约束、联合聚焦与整机科学验收；
[统一集成](../../integrations/README.md)拥有组件实例装配、跨组件执行及冻结依赖，不保存第二份加速器模型。
旧OA整机适配器只做参数映射或兼容导入。
新器件独立运行产物归`artifacts/projects/orthogonal_accelerator/`；既有OA/MR历史证据不迁移、不改身份。

## History索引

[历史索引](docs/history/README.md)集中列出已冻结实验、迁移和旧方案；需要追溯证据时按需进入。
