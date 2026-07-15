# Wehnelt 电子枪项目

本项目的正式基线是**横置螺旋灯丝 Wehnelt 电子枪**，面向质谱 EI 离子源中优先提高电子
利用率、无需成像级轴对称束斑的应用。运行前先读
[`项目_螺旋灯丝Wehnelt电子枪.md`](项目_螺旋灯丝Wehnelt电子枪.md)。

## 正式流水线

按下列顺序运行，三份脚本均通过[`egun_paths.m`](egun_paths.m)定位产物：

1. `phase1_geometry_coil_transverse.m`：建立横置灯丝、Wehnelt 和阳极几何，保存几何中间模型。
2. `phase2_electrostatics_coil_transverse.m`：建立材料、选择集、静电场、网格、Study 和原生结果节点，保存静电中间模型。
3. `phase4_thermal_emission_coil_transverse.m`：建立 2700 K 热发射 CPT、瞬态 Study、粒子数据集和原生轨迹图，保存最终正式模型。

编号保留为 phase1/2/4，是为了维持既有实验谱系；旧 phase3 是不适合效率评估的冷发射验证，
不属于正式流水线。

## 产物位置

- 正式模型：`artifacts/projects/wehnelt_electron_gun/models/comsol/formal/ElectronGun_CoilT_Thermal_CPT.mph`
- 可重建的中间模型：同项目的`models/comsol/workspace/`
- 正式结果图：同项目的`results/comsol/formal/`
- 历史模型和结果：对应`archive/lineages/solid_cathode/`、`archive/lineages/axial_coil/`

## 历史脚本

`legacy/solid_cathode/`和`legacy/axial_coil/`只用于追溯旧结论，不得作为新工作的起点。
旧`phase5_wehnelt_sweep.m`实际使用轴向 Helix，因此其扫描结果不是横置基线参数结论；横置
Wehnelt 参数扫描需要以后重新建立和验证。

## 运行依赖与当前验证限制

脚本依赖 MATLAB R2025b 和 COMSOL 6.4 LiveLink。R2022b 的MCOS初始化故障只保留为历史背景，
不再是可用环境；改用R2025b后，
COMSOL官方MATLAB启动器已完成自动链路测试：成功加载`ElectronGun_CoilT_ES.mph`，确认
Helix `axis=x`、`es`物理场、`std1` Study及`pg_V`/`pg_E`原生结果节点存在，并通过
`model.study('std1').run`重算静电场。z=8 mm轴上复核值为`V=40.0917301067 V`、
`|E|=5300.60566114 V/m`。最终`ElectronGun_CoilT_Thermal_CPT.mph`及其CPT Study尚未在
R2025b下复算，因此34.18%收集效率仍沿用此前归档结果。

当前项目专属知识仍集中在本 README 和上述项目文档；不要把它拆成多个按阶段排列的说明文件。
新增跨项目 API 或调试经验时按仓库根 README 写入根 `docs/`，不是追加到本项目历史。

## 工具链基线

本项目的正式及候选MATLAB/COMSOL任务只使用MATLAB **R2025b**；未来引入STEP、零件或装配时只使用
**SolidWorks 2022**。不再支持MATLAB R2022或SolidWorks 2013。
