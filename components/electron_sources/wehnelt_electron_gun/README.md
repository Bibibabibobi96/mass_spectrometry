# Wehnelt 电子枪组件

本组件的正式基线是**横置螺旋灯丝 Wehnelt 电子枪**，面向质谱 EI 离子源中优先提高电子
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

- 正式模型：`artifacts/components/electron_sources/wehnelt_electron_gun/models/comsol/formal/ElectronGun_CoilT_Thermal_CPT.mph`
- 可重建的中间模型：同组件的`models/comsol/workspace/`
- 正式结果图：同组件的`results/comsol/formal/`
- 历史模型和结果：对应`archive/lineages/solid_cathode/`、`archive/lineages/axial_coil/`

## 历史脚本

`legacy/solid_cathode/`和`legacy/axial_coil/`只用于追溯旧结论，不得作为新工作的起点。
旧`phase5_wehnelt_sweep.m`实际使用轴向 Helix，因此其扫描结果不是横置基线参数结论；横置
Wehnelt 参数扫描需要以后重新建立和验证。

## 运行依赖与当前验证限制

脚本依赖 MATLAB、COMSOL 6.4 LiveLink 以及本机`D:\COMSOL 6.4\...\mli`路径。2026-07-13
整理时，MATLAB R2022b 在执行最小`-batch`命令前发生 MCOS 启动崩溃，因此本次只依据此前
已完成的横置/轴向同条件对照选择基线，没有重新求解或完成 GUI Compute 复验。修复 MATLAB
运行时后，第一次电子枪工作应先打开正式 MPH，核对 GUI 节点并重新执行两个 Study。
