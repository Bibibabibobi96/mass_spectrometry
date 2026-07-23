# RF六极杆离子导引项目状态

## 当前结论

自2026-07-23起，本项目粒子数只遵循仓库根README“通用验证口径”和
[`../../../common/contracts/particle_count_policy.json`](../../../common/contracts/particle_count_policy.json)，
不在项目内维护第二份档位定义。baseline已迁移到新的默认功能档；下文N=25运行只保留为迁移前历史
证据，不再构成当前功能或Candidate闭合，L1/L2/L3及两类加速均等待新标准复验。

项目已建立独立身份和理想有限长度L1传输合同。模型使用六根交替极性电极对应的理想六极场，直接积分
RF相位分辨的非线性横向运动，并以0 V对照判断RF是否产生功能性约束。它不是四极杆mode，也不使用
Mathieu稳定图。迁移前历史公共合同回归`20260722_210400__sim__python__rf-hexapole-family-contract__l1-n25`中，RF开启时
25/25到达出口，0 V对照仅1/25到达；该结果只记录当时的L1功能门禁结果。

迁移前历史二维COMSOL圆杆场筛选`20260722_180121__sim__comsol__rf-hexapole-ion-guide-round-rod-screen__l2`
选择`r_rod/r0=0.55`：杆半径2.2 mm、中心半径6.2 mm、相邻表面间隙1.8 mm；边界归一化
`A9/A3=0.0023644`、`A15/A3=0.0028776`。两个采样环得到的高阶系数一致。使用带符号谐波重建场的
`20260722_181607__sim__python__rf-hexapole-ion-guide-round-rod__l2-n25`为RF 25/25、0 V 1/25，出口
RMS半径0.4206 mm。它证明二维真实圆杆横向场的功能贯通，不证明有限三维端部或机械资格。

迁移前历史带接口有限三维COMSOL完整电压合同回归`20260723_052000__sim__comsol__rf-hexapole-family-contract__complete-drive-n25`
从入口端板外侧释放相同N=25粒子。入口孔两组均通过25/25；RF组穿过完整杆区、出口孔并到达外部
检测面25/25，零RF对照仅1/25到达。RF检测面RMS半径0.528788 mm，杆区最大半径0.902589 mm。
结果显式记录波形、RF/DC、公共偏置、频率和相位；当前baseline的DC与公共偏置均为0 V。
模型已保存参数化开孔端板、封闭外壳、有限外部区和原生轨迹节点；该N=25结论只是历史功能证据。

迁移前历史公共正长度连接器回归`20260723_054900__sim__comsol__rf-hexapole-connector__exit2-n25`仅把出口接地管
从0改为2 mm，检测面相应从81.1移到83.1 mm；RF仍为25/25、零RF仍为1/25，RF出口RMS半径
0.523226 mm。它只记录当时的正长度连接器可执行，不证明2 mm优于直连，也不改变
当前0 mm baseline或资格状态。

迁移前历史公共分段杆轴向加速运行
`20260723_073100__sim__comsol__rf-hexapole-axial-acceleration__n25__r02`使用4段、0.4 mm段间隙和
`0→-3 V`公共模阶梯；RF与源保持不变。加速组和同几何零轴向压降对照均为25/25，平均末端能量分别
为5.0103和1.9823 eV，实测增益3.0280 eV，通过5 eV理论目标的功能判据。它不是分段优化、网格收敛、
SIMION独立验证或机械资格。

迁移前历史共享圆杆几何与SIMION核心回归`20260722_233001__sim__simion__rf-hexapole-family-contract__shared-runtime-n25__r08`
同样得到RF 25/25、0 V 1/25。SIMION出口RMS半径0.467682 mm，COMSOL为0.524896 mm；最大杆区半径
分别为0.740731 mm和0.820490 mm。传输计数完全一致，束斑差只作诊断，不构成网格收敛或数值等价声明。
该SIMION入口与四极杆、八极杆共同使用根级run生命周期、源序列化和canonical粒子状态校验；粒子质量
由本项目baseline显式传入，不存在公共层100 amu默认值。SIMION构建与飞行使用严格串行的直接CLI，
避免refine后的PA锁与Lua嵌套命令重入。

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
  直接求解端部/孔口场与轨迹；尚未完成网格收敛、独立求解器比较或Candidate资格门禁。

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
继续推进，先补SIMION适配，再研究分段数量、绝缘间隙、馈电和机械实现；当前4段参数只作为COMSOL
功能baseline。
