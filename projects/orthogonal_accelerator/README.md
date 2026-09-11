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

## 所有权

`analysis/`拥有器件理论和几何派生，`simion/`、`comsol/`拥有器件实现，`tests/`拥有独立回归。
共享运行、IOB基础机制、坐标与证据工具继续使用根`common/`。不保留另一份`common/accelerator/`领域实现。

仪器项目通过明确接口复用本项目：自身保留系统布局、完整粒子链、联合聚焦与整机验收；
integration保存连接及冻结依赖，不保存第二份加速器模型。旧OA整机适配器只做参数映射或兼容导入。
新器件独立运行产物归`artifacts/projects/orthogonal_accelerator/`；既有OA/MR历史证据不迁移、不改身份。


## History索引

<details>
<summary>展开只读历史记录</summary>

- [20260903__legacy-accelerator-diagnostic](docs/history/20260903__legacy-accelerator-diagnostic.md)

- [加速器迁移与原生检查](docs/history/20260911__component-migration-evidence.md)

</details>
