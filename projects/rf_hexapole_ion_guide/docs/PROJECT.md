# RF六极杆离子导引项目状态

## 当前结论

项目已建立独立身份和理想有限长度L1传输合同。模型使用六根交替极性电极对应的理想六极场，直接积分
RF相位分辨的非线性横向运动，并以0 V对照判断RF是否产生功能性约束。它不是四极杆mode，也不使用
Mathieu稳定图。权威运行`20260722_174048__sim__python__rf-hexapole-ion-guide-l1__n25`中，RF开启时
25/25到达出口，0 V对照仅1/25到达；该结果满足当前L1功能门禁。

二维COMSOL圆杆场筛选`20260722_180121__sim__comsol__rf-hexapole-ion-guide-round-rod-screen__l2`
选择`r_rod/r0=0.55`：杆半径2.2 mm、中心半径6.2 mm、相邻表面间隙1.8 mm；边界归一化
`A9/A3=0.0023644`、`A15/A3=0.0028776`。两个采样环得到的高阶系数一致。使用带符号谐波重建场的
`20260722_181607__sim__python__rf-hexapole-ion-guide-round-rod__l2-n25`为RF 25/25、0 V 1/25，出口
RMS半径0.4206 mm。它证明二维真实圆杆横向场的功能贯通，不证明有限三维端部或机械资格。

## 当前参数与边界

- 阶数`n=3`，电极数6，`r0=4 mm`，理想可用半径3.6 mm，有效长度79.6 mm。
- 单相位组相对共同偏置的RF零到峰值为139.81792 V，频率1.1 MHz。
- 固定N=25、100 amu、+1、2 eV源；最大源半径0.5 mm，最大入射发散5°。
- 碰撞、空间电荷、磁场、有限三维圆杆、外壳、支撑、端部边缘场和接口均未启用。
- L2使用二维COMSOL场的谐波展开并沿z均匀延伸；未做网格收敛，不允许机械设计、Candidate或Formal声明。

## 权威入口

- [`../config/baseline.json`](../config/baseline.json)
- [`../config/modes/transport_no_collision.json`](../config/modes/transport_no_collision.json)
- [`../analysis/run_transport.ps1`](../analysis/run_transport.ps1)
- [`../config/round_rod_field_screen.json`](../config/round_rod_field_screen.json)
- [`../analysis/run_round_rod_field_screen.ps1`](../analysis/run_round_rod_field_screen.ps1)
- [`../analysis/run_round_rod_transport.ps1`](../analysis/run_round_rod_transport.ps1)
- [`../verify_project.ps1`](../verify_project.ps1)

## 下一步

下一阶段建立有限三维圆杆、入口/出口边缘场和直接求解器粒子跟踪；当前二维候选在此之前不写入机械
baseline。碰撞冷却、SIMION和CAD均为独立后续阶段。
