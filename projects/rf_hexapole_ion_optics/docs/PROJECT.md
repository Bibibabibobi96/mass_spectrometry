# RF六极杆离子光学项目状态

## 当前结论

本项目当前只承认由 `mechanical_base + operating_modes + design_profiles` 编译的三种模式：
`no_acceleration_full_length`、`segmented_rod_axial_acceleration`和
`exit_aperture_plate_acceleration`。三者机械相同，仅由typed registry改变杆段和出口孔板电位。
项目入口只接受具名runtime profile；粒子源和求解器数值均由profile绑定，不能从命令行自由覆盖。

三模式N=100 baseline均已在COMSOL与SIMION闭合功能传输。无加速空间/时间敏感性、两种加速模式
空间臂及后续工程比较不支持连续数值收敛或跨求解器等价；当前状态仍为
`DEFERRED_NOT_WAIVED`/`INCONCLUSIVE`。家族工程六指标可用于下游推进，但不得升级为数值、
机械、Candidate或Formal资格。

2026-08-03完成分段加速模式的相位匹配RF幅值—频率H15筛选及N=1000复核。七个实际评价点的空间
RMS差不超过0.011 mm、角RMS差不超过0.109°，全部属于工程等效；N=100中的微小排序不稳定，不能
用于参数优选。维持P0 RF基线并停止扩大RF扫描。详见
[N=1000日期化报告](history/20260803__hex-rf-drive-phase-matched-h15-n1000.md)。

同日补齐无加速5 eV初始源并复用既有三模式N=100 H15证据：六极杆分段加速相对无加速5 eV同时
降低空间RMS`0.0519 mm`、角RMS`0.7844°`和能量展宽`0.0076 eV`；末端加速则以0.96给出最高
handoff透射，空间RMS与分段加速仅差`0.0012 mm`。完整12臂对照见
[`20260803 四模式源能量记录`](history/20260803__multipole-four-mode-source-energy-h15-n100.md)。

## 当前参数与边界

- 六根电极，径向阶数`n=3`，`r0=4 mm`，圆杆半径比0.5，有效杆长79.6 mm。
- RF单相位组相对共同偏置的零到峰值139.81792 V，频率1.1 MHz。
- N=100与N=1000源来自同一母样本；N=100是N=1000的精确前缀。
- COMSOL baseline/空间/时间档为`0.5 mm,80`、`0.35 mm,80`、
  `0.35 mm,160 steps/RF period`。
- SIMION baseline/空间/时间档为`0.4 mm,40`、`0.3 mm,40`、
  `0.3 mm,80 steps/RF period`。
- 入口、出口孔半径3.6 mm；当前是零长度直连合同。碰撞、空间电荷、磁场、支撑和机械公差未启用。
- 坐标、物理面和事件角色只按公共多极杆README解释。

## 权威入口

- [机械base](../config/requests/mechanical_base.json)
- [typed模式](../config/operating_modes.json)
- [设计变量](../config/design_variables.json)与[优化包络](../config/optimization_envelope.json)
- [设计profile](../config/design_profiles.json)
- [运行profile](../config/runtime_profiles.json)
- [粒子源profile](../config/particle_source_profiles.json)
- [COMSOL数值profile](../config/comsol_solver_numerics.json)
- [SIMION数值profile](../config/simion_solver_numerics.json)
- [N=100共同预登记](../config/qualification/n100_convergence_preregistration.json)
- [无加速资格记录](../config/qualification/n100_no_acceleration_qualification.json)
- [分段加速资格记录](../config/qualification/n100_segmented_rod_axial_acceleration_qualification.json)
- [出口孔板加速资格记录](../config/qualification/n100_exit_aperture_plate_acceleration_qualification.json)
- [dispersion接受合同](../config/qualification/dispersion_acceptance.json)
- [工程预算](../config/qualification/engineering_budget.json)

旧项目身份的artifact只按`project.json`的`archived_verified`位置只读解析，不提供旧顶层路径
fallback。已关闭的逐臂profile、预登记和专用测试不再位于活动配置；它们的工程结论见
[退役campaign摘要](history/20260802__retired-comsol-qualification-campaigns.md)，原始机器记录可从Git历史恢复。

## 下一步

屏蔽罩及包含外壳的端部组合电极已固定为0 V，设计变量不再开放屏蔽电位；后续连接oaTOF时由campaign
显式选择公共接地圆套筒+带孔法兰profile。

1. 按[通用出口相空间方法](../../../docs/multipoles/exit_phase_space_control.md)建立具名筛选campaign；
   当前P0 RF基线在新合同批准前不变。关闭条件是冻结真实下游接受尺度、唯一变量、损失约束、共同
   幸存者分析和相邻数值档。
2. 使用当前12个runtime profile和声明式campaign入口完成真正需要的N=100/N=1000实验，不恢复一次性
   solver/mesh诊断profile。
3. 以家族六指标判断下游可接受性，同时显式保留数值收敛未豁免状态。
4. 需要新的网格或求解器研究时，新建有窄变量轴、资源帽和终止条件的campaign；不得复制旧JSON后改SHA。
5. 只有新证据通过当前资格合同后，才讨论Candidate/Formal提升。
