# Wehnelt 电子枪项目

本项目的当前物理基线是**横置螺旋灯丝 Wehnelt 电子枪**，面向质谱 EI 离子源中优先提高电子
利用率、无需成像级轴对称束斑的应用。开始任务先读仓库根[`README.md`](../../README.md)，再读
当前权威状态[`docs/PROJECT.md`](docs/PROJECT.md)。需要追溯选型依据和旧实验时才读冻结背景
[`docs/history/PROJECT_HISTORY.md`](docs/history/PROJECT_HISTORY.md)。

机器身份、能力边界和当前`prototype`成熟度由[`config/project.json`](config/project.json)声明；
它用于项目发现，不改变PROJECT记录的正式资格。

物理输入只在[`config/baseline.json`](config/baseline.json)维护，数值与证据模式只在
[`config/numerical_modes.json`](config/numerical_modes.json)维护；解析器
[`analysis/resolve_contract.py`](analysis/resolve_contract.py)生成三阶段MATLAB唯一允许读取的
[`config/resolved_model.json`](config/resolved_model.json)。当前跟踪发布选择`build_only_smoke`，
只验证构建和GUI参数绑定，不是Candidate或Formal证据。项目Static门禁为`.\verify_project.ps1`；
仓库执行注册只使用[`config/execution_profiles.json`](config/execution_profiles.json)，未完成真实
N>=100复算前不注册`functional_reference`。

受治理商业构建入口为`.\run_build_only_smoke.ps1 -RunId <显式run_id>`。它只执行注册的
`build_only_smoke`，冻结resolved合同与实际MATLAB源码，调用一次仓库统一R2025b/COMSOL入口，并为
成功或失败结果写入可复核manifest；不得用手工LiveLink命令替代。

runner在run目录建立后立即写入`interrupted`预置summary和已复核manifest；只有捕获到明确异常才改写
为`failed`，完整通过报告判据后才改写为`success`。三种终态统一记录失败阶段、证据资格和几何/网格/
静电/CPT构建或求解布尔值。项目合同、resolver、Static gate、执行profile、实际调用的公共COMSOL入口
及manifest入口均冻结；商业wrapper的控制台与退出上下文写入`logs/commercial_wrapper.log`。失败收尾
递归枚举当时已经存在的冻结输入和输出，不能用空manifest掩盖中途失败。

`20260723_172817__test__comsol__wehnelt-build-only-smoke`和
`20260723_173100__test__comsol__wehnelt-build-only-smoke`是修复前的历史不合格诊断：前者把外部超时
记成了`failed`而非`interrupted`，后者未把中途复制的runner列入空inputs manifest；两目录保持原样，
不得作为当前runner治理正确性的证据。

## 基线源码流水线

按下列顺序运行，三份脚本均通过[`egun_paths.m`](egun_paths.m)定位产物：

1. `phase1_geometry_coil_transverse.m`：消费resolved合同，建立横置灯丝、Wehnelt 和阳极几何，保存几何中间模型。
2. `phase2_electrostatics_coil_transverse.m`：消费同一resolved合同，建立材料、选择集、静电场、网格、Study 和原生结果节点，保存静电中间模型。
3. `phase4_thermal_emission_coil_transverse.m`：消费同一resolved合同，建立热发射 CPT、瞬态 Study、粒子数据集和原生轨迹图，保存本次run的最终阶段模型。

编号保留为 phase1/2/4，是为了维持既有实验谱系；旧 phase3 是不适合效率评估的冷发射验证，
不属于正式流水线。

三阶段都必须显式接收resolved路径；缺失、过期或身份不匹配时失败关闭，不从MATLAB源码、环境变量
或旧MPH回退物理参数。人工只修改baseline或具名数值模式，再由解析器生成resolved；禁止手改resolved。

## 产物位置

- 当前没有通过现行门禁的formal资产；旧“formal”、中间模型和结果统一冻结在
  `artifacts/projects/wehnelt_electron_gun/archive/20260719_212436__migration-snapshot__repo__pre-v2-layout/legacy-layout/`。
- 新运行必须写入`runs/<run_id>/{comsol,results,logs}`并形成run config、summary和manifest。
- 历史模型和结果位于上述migration snapshot的
  `legacy-layout/{models,results}/comsol/archive/lineages/{solid_cathode,axial_coil}/`；这些路径只用于追溯。

## 历史脚本

`legacy/solid_cathode/`和`legacy/axial_coil/`只用于追溯旧结论，不得作为新工作的起点。
旧`phase5_wehnelt_sweep.m`实际使用轴向 Helix，因此其扫描结果不是横置基线参数结论；横置
Wehnelt 参数扫描需要以后重新建立和验证。

## 运行依赖

版本和启动方式只采用仓库根[`README.md`](../../README.md#工具链与执行入口)的统一工具链；当前
验证范围、正式资格和未闭合事项只写入PROJECT，本入口不保存容易漂移的复算数值。

新增跨项目API或调试经验按仓库根README路由到根`docs/`，项目特有当前事实写PROJECT，不创建
按阶段排列的活跃说明文件。
