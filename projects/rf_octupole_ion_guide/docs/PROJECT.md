# RF八极杆离子导引项目状态

## 当前结论

自2026-07-23起，本项目粒子数只遵循仓库根README“通用验证口径”和
[`../../../common/contracts/particle_count_policy.json`](../../../common/contracts/particle_count_policy.json)，
不在项目内维护第二份档位定义。分段杆轴向加速和端面加速已经分别通过COMSOL与SIMION N=100功能
复验，四项来源run由[`family_contract.json`](../../../common/multipole/family_contract.json)冻结。
该PASS不授予网格收敛、跨求解器数值等价、机械或Formal资格。

Phase 4已用[`../config/design_profiles.json`](../config/design_profiles.json)冻结
`baseline_finite_3d`的request、变量目录、包络SHA-256及`full_length_grounded_shield + uniform`
拓扑。项目L3薄wrapper只接受`RuntimeProfileId`，由版本化profile绑定design profile、canonical粒子
CSV的SHA和各求解器数值profile；任意粒子路径和自由数值不再属于生产入口。公共runner保留为低层
投影机制。无evidence contract的运行固定为`UNQUALIFIED`。

Phase 2设计配置把当前`n=4`、8根电极身份、`r0=4 mm`、圆杆比`1/3`、有限杆范围、圆柱接地屏蔽及
真空域、圆孔接口、canonical驱动和uniform四段参考冻结为单一求解器无关请求。33个数值变量均以
请求JSON pointer、单位和双向边界声明；pole count保持项目身份，外壳model与连接器shape保持受支持
的锁定拓扑。注册execution profile仍是compile-only；薄wrapper运行公共runner时，无evidence合同只能
生成`UNQUALIFIED`结果。

项目已建立独立身份和理想有限长度L1传输合同。模型使用八根交替极性电极对应的理想八极场，直接积分
RF相位分辨的非线性横向运动，并以0 V对照判断RF是否产生功能性约束。它不是四极杆mode，也不使用
Mathieu稳定图。L1/L2/L3迁移前小样本数值只保留在
[`history/20260723__pre-n100-multipole-functional-evidence.md`](history/20260723__pre-n100-multipole-functional-evidence.md)，
不构成当前Candidate证据。

## 当前参数与边界

- 阶数`n=4`，电极数8，`r0=4 mm`，理想可用半径3.6 mm，有效长度79.6 mm。
- 单相位组相对共同偏置的RF零到峰值为139.81792 V，频率1.1 MHz。
- 坐标、`r0`和双极性组电压语义由`common/multipole/family_contract.json`统一；具体物理量只由项目
  design request编译，数值设置只由solver-numerics profile发布，并在每个run冻结。
- 固定N=100、100 amu、+1、2 eV功能源；最大源半径0.5 mm，最大入射发散5°。
- 入口和出口孔半径均为3.6 mm；入口、出口连接器长度当前均为0 mm（直连合同）；入口板范围`z=-1.0…-0.5 mm`，粒子从`z=-1.5 mm`释放；出口板范围
  `z=80.1…80.6 mm`，外部检测面为`z=81.1 mm`。绝对位置只由接口合同单向派生。
- 碰撞、空间电荷、磁场、支撑和机械公差均未启用。
- L2从`baseline_finite_3d` governed profile即时编译resolved，再使用二维COMSOL场的谐波展开；
  只发布逐候选metrics，不选择或回写L3几何。未做网格收敛，不允许机械设计、Candidate或Formal声明。
- L3使用20 mm内半径连续接地圆柱外壳、完整有限圆杆、两块开孔接地板和两段有限外部区，COMSOL
  和SIMION均有功能入口；尚未完成网格收敛、跨求解器数值等价或Candidate资格门禁。

## 权威入口

- [`../config/requests/baseline.json`](../config/requests/baseline.json)
- [`../config/design_variables.json`](../config/design_variables.json)
- [`../config/optimization_envelope.json`](../config/optimization_envelope.json)
- [`../config/execution_profiles.json`](../config/execution_profiles.json)
- [`../config/design_profiles.json`](../config/design_profiles.json)
- [`../config/resolved_design.json`](../config/resolved_design.json)
- [`../config/runtime_profiles.json`](../config/runtime_profiles.json)
- [`../config/particle_source_profiles.json`](../config/particle_source_profiles.json)
- [`../config/comsol_solver_numerics.json`](../config/comsol_solver_numerics.json)
- [`../config/simion_solver_numerics.json`](../config/simion_solver_numerics.json)
- [`../config/modes/transport_no_collision.json`](../config/modes/transport_no_collision.json)
- [`../analysis/run_transport.ps1`](../analysis/run_transport.ps1)
- [`../config/round_rod_field_screen.json`](../config/round_rod_field_screen.json)
- [`../analysis/run_round_rod_field_screen.ps1`](../analysis/run_round_rod_field_screen.ps1)
- [`../analysis/run_round_rod_transport.ps1`](../analysis/run_round_rod_transport.ps1)
- [`../analysis/run_finite_3d_transport.ps1`](../analysis/run_finite_3d_transport.ps1)
- [`../analysis/run_simion_finite_3d_transport.ps1`](../analysis/run_simion_finite_3d_transport.ps1)
- [`../verify_project.ps1`](../verify_project.ps1)

`config/baseline.json`和`config/finite_3d_transport.json`仅为历史L1/L3兼容快照，不得接收新参数或
供活动L3 solver直接消费。前者只因当前registry schema保留为旧格式项目身份检查，不构成solver权威。
六/八极杆共同使用的固定N=100 CSV只有一份，位于
`common/multipole/sources/hex_oct_baseline_fixed_100.csv`；两个项目分别以profile和SHA绑定它。

## 下一步

多极杆公共基础层已冻结为功能baseline；正长度连接器的公共实现由六极杆2 mm出口案例真实验证，
本项目保留0 mm baseline，不用重复同一共享求解器实验。当前离子导引和接口功能链已由COMSOL与
SIMION独立贯通。下一阶段不再增加模型层级；在需要把本设计
推进为Candidate时，再进行网格收敛和机械baseline。碰撞冷却与CAD仍为独立后续阶段。轴向加速若
继续推进，可通过`AxialAccelerationContractPath`建立项目具名explicit案例，再研究分段数量、各段
长度/间隙/电势、馈电和机械实现；当前默认uniform四段参数仍只是已通过双求解器N=100复验的功能
baseline，不是正式硬件选择。

本项目还保留三项明确退出任务：

1. `project.json.contracts.baseline`暂因根registry builder的旧`multipole`身份检查保留只读
   `config/baseline.json`。根schema/builder改由design profile/request或独立identity contract校验，
   且三RF项目registry门禁通过后，解除该兼容绑定并按删除授权处理旧文件。
2. SIMION vendor临时容器退出任务已于2026-07-27关闭。项目通过公共runner消费唯一共享的单PA非物理
   模板登记，prepare阶段校验成功run、人工GUI复核和IOB/CON SHA并冻结副本；不维护项目模板身份，
   不接受`TemplateIob`覆盖或vendor回退。该登记只关闭容器来源问题，不授予Candidate或Formal资格。
3. `config/finite_3d_transport.json`仍供旧family/L1测试读取。测试改为消费design request、resolved和
   solver-numerics profile且活动引用归零后，按删除授权退出该快照。公共机制边界见
   [`../../../common/multipole/README.md`](../../../common/multipole/README.md)。
4. SIMION 2026 `.wgem`因当前许可证年份不足，现以SIMION 2020 GEM+Workbench受控路径绕过，不视为
   根因修复且不阻断本阶段物理链。确有新版需求、许可证更新并完成官方示例状态机复验后才关闭。
   Git注册表只发布provider、run id和SHA，但来源manifest仍带本机绝对路径；还须将成功run迁移到
   不同工作区并重写/复核manifest，再验证IOB/CON/PA重开，三RF项目均通过后关闭跨机可移植性任务。
