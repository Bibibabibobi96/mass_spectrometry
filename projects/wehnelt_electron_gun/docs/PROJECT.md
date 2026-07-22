# Wehnelt电子枪当前项目状态

本文件是项目当前状态的唯一权威。选型依据和旧实验时间线只查
[`history/PROJECT_HISTORY.md`](history/PROJECT_HISTORY.md)，不得用其中的历史“当前”
覆盖本文件。

## 当前基线

当前物理基线为5匝横置螺旋钨丝、2700 K热发射的Wehnelt电子枪。正式源码链为
`phase1_geometry_coil_transverse.m`、`phase2_electrostatics_coil_transverse.m`和
`phase4_thermal_emission_coil_transverse.m`；实心阴极和轴向线圈源码只属于`legacy/`。

基线参数为线圈半径0.3 mm、钨丝半径0.05 mm、节距0.2 mm，阴极/Wehnelt/阳极电势分别为
0/-0.5/70 V，Wehnelt与阳极孔径半径分别为1.0/1.5 mm。横置方案服务于EI离子源的电子利用率，
不声明成像级轴对称束斑。

## 资产与验证状态

当前没有通过现行门禁的formal资产。旧模型和结果冻结在
`archive/20260719_212436__migration-snapshot__repo__pre-v2-layout/legacy-layout/`。R2025b曾重算静电中间模型并
确认横置Helix、静电Study和原生场结果节点；最终CPT模型尚未在R2025b下重开和GUI Compute复算。
因此历史34.18%收集效率仍是待复验结果，不能作为当前已闭合性能门禁。

## 已知程序问题

- 三阶段源码已移除COMSOL安装路径和`mphstart`，只能由仓库统一R2025b连接入口运行；尚未做三阶段
  不求解构建冒烟和最终CPT复验，因此不改变当前资产资格。
- 参数仍直接写在MATLAB源码中，没有baseline/resolved机器契约和运行模式分层。
- 当前正式MPH早于现行run config/summary/manifest合同；资产身份与结果尚未形成完整哈希链。
- 横置Wehnelt参数扫描尚未建立；旧phase5实际属于轴向灯丝，只能支持非单调性的历史假设。

## 下一步

1. 通过统一R2025b入口完成三阶段不求解构建冒烟和节点审计，再用小样本复算最终CPT。
2. 为几何、电压、温度、粒子与数值设置建立机器契约，保持GUI节点可检查。
3. 复验收集效率、损失分类和正式结果图，补齐run config、summary、manifest及资产SHA。
4. 只有下游设计需要时才建立横置谱系参数扫描；不得复用轴向phase5的具体最优值。

## 产物边界

项目产物根为`artifacts/projects/wehnelt_electron_gun/`。现有formal路径表示资产职责，不自动等于
现行门禁已通过；旧谱系保留在archive，临时验证进入runs或scratch，不写入Git。
