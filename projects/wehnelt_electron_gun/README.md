# Wehnelt 电子枪项目

本项目的当前物理基线是**横置螺旋灯丝 Wehnelt 电子枪**，面向质谱 EI 离子源中优先提高电子
利用率、无需成像级轴对称束斑的应用。开始任务先读仓库根[`README.md`](../../README.md)，再读
当前权威状态[`docs/PROJECT.md`](docs/PROJECT.md)。需要追溯选型依据和旧实验时才读冻结背景
[`docs/history/PROJECT_HISTORY.md`](docs/history/PROJECT_HISTORY.md)。

机器身份、能力边界和当前`prototype`成熟度由[`config/project.json`](config/project.json)声明；
它用于项目发现，不改变PROJECT记录的正式资格。

## 基线源码流水线

按下列顺序运行，三份脚本均通过[`egun_paths.m`](egun_paths.m)定位产物：

1. `phase1_geometry_coil_transverse.m`：建立横置灯丝、Wehnelt 和阳极几何，保存几何中间模型。
2. `phase2_electrostatics_coil_transverse.m`：建立材料、选择集、静电场、网格、Study 和原生结果节点，保存静电中间模型。
3. `phase4_thermal_emission_coil_transverse.m`：建立 2700 K 热发射 CPT、瞬态 Study、粒子数据集和原生轨迹图，保存最终正式模型。

编号保留为 phase1/2/4，是为了维持既有实验谱系；旧 phase3 是不适合效率评估的冷发射验证，
不属于正式流水线。

## 产物位置

- 当前没有通过现行门禁的formal资产；旧“formal”、中间模型和结果统一冻结在
  `artifacts/projects/wehnelt_electron_gun/archive/20260719_212436__migration-snapshot__repo__pre-v2-layout/legacy-layout/`。
- 新运行必须写入`runs/<run_id>/{comsol,results,logs}`并形成run config、summary和manifest。
- 历史模型和结果：对应`archive/lineages/solid_cathode/`、`archive/lineages/axial_coil/`

## 历史脚本

`legacy/solid_cathode/`和`legacy/axial_coil/`只用于追溯旧结论，不得作为新工作的起点。
旧`phase5_wehnelt_sweep.m`实际使用轴向 Helix，因此其扫描结果不是横置基线参数结论；横置
Wehnelt 参数扫描需要以后重新建立和验证。

## 运行依赖

版本和启动方式只采用仓库根[`README.md`](../../README.md#工具链与执行入口)的统一工具链；当前
验证范围、正式资格和未闭合事项只写入PROJECT，本入口不保存容易漂移的复算数值。

新增跨项目API或调试经验按仓库根README路由到根`docs/`，项目特有当前事实写PROJECT，不创建
按阶段排列的活跃说明文件。
