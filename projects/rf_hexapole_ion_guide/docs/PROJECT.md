# RF六极杆离子导引项目状态

## 当前结论

自2026-07-23起，本项目粒子数只遵循仓库根README“通用验证口径”和
[`../../../common/contracts/particle_count_policy.json`](../../../common/contracts/particle_count_policy.json)，
不在项目内维护第二份档位定义。分段杆轴向加速和端面加速已经分别通过COMSOL与SIMION N=100功能
复验，四项来源run由[`family_contract.json`](../../../common/multipole/family_contract.json)冻结。
该PASS不授予网格收敛、跨求解器数值等价、机械或Formal资格。

项目已建立独立身份和理想有限长度L1传输合同。模型使用六根交替极性电极对应的理想六极场，直接积分
RF相位分辨的非线性横向运动，并以0 V对照判断RF是否产生功能性约束。它不是四极杆mode，也不使用
Mathieu稳定图。L1/L2/L3迁移前小样本及2 mm连接器数值只保留在
[`history/20260723__pre-n100-multipole-functional-evidence.md`](history/20260723__pre-n100-multipole-functional-evidence.md)，
不构成当前Candidate证据。

## 当前参数与边界

- 阶数`n=3`，电极数6，`r0=4 mm`，理想可用半径3.6 mm，有效长度79.6 mm。
- 单相位组相对共同偏置的RF零到峰值为139.81792 V，频率1.1 MHz。
- 坐标、`r0`和双极性组电压语义由`common/multipole/family_contract.json`统一；具体数值仍只由本项目
  baseline派生，并在每个run冻结标准化运行合同。
- 固定N=100、100 amu、+1、2 eV功能源；最大源半径0.5 mm，最大入射发散5°。
- 入口和出口孔半径均为3.6 mm；入口、出口连接器长度当前均为0 mm（直连合同）；入口板范围`z=-1.0…-0.5 mm`，粒子从`z=-1.5 mm`释放；出口板范围
  `z=80.1…80.6 mm`，外部检测面为`z=81.1 mm`。绝对位置只由接口合同单向派生。
- 碰撞、空间电荷、磁场、支撑和机械公差均未启用。
- L2使用二维COMSOL场的谐波展开并沿z均匀延伸；未做网格收敛，不允许机械设计、Candidate或Formal声明。
- L3使用20 mm内半径连续接地圆柱外壳、完整有限圆杆、两块开孔接地板和两段有限外部区，COMSOL
  和SIMION均有功能入口；尚未完成网格收敛、跨求解器数值等价或Candidate资格门禁。

## 权威入口

- [`../config/baseline.json`](../config/baseline.json)
- [`../config/modes/transport_no_collision.json`](../config/modes/transport_no_collision.json)
- [`../analysis/run_transport.ps1`](../analysis/run_transport.ps1)
- [`../config/round_rod_field_screen.json`](../config/round_rod_field_screen.json)
- [`../analysis/run_round_rod_field_screen.ps1`](../analysis/run_round_rod_field_screen.ps1)
- [`../analysis/run_round_rod_transport.ps1`](../analysis/run_round_rod_transport.ps1)
- [`../config/finite_3d_transport.json`](../config/finite_3d_transport.json)
- [`../analysis/run_finite_3d_transport.ps1`](../analysis/run_finite_3d_transport.ps1)
- [`../analysis/run_simion_finite_3d_transport.ps1`](../analysis/run_simion_finite_3d_transport.ps1)
- [`../verify_project.ps1`](../verify_project.ps1)

## 下一步

多极杆公共基础层已冻结为功能baseline，后续不再为本项目复制公共杆阵列、运行时或接口实现。当前
离子导引和接口功能链已由COMSOL与SIMION独立贯通。下一阶段不再增加模型层级；在需要把本设计
推进为Candidate时，再进行网格收敛和机械baseline。碰撞冷却与CAD仍为独立后续阶段。轴向加速若
继续推进，应研究分段数量、绝缘间隙、馈电和机械实现；当前4段参数只是已通过双求解器N=100复验的
功能baseline，不是正式硬件选择。
