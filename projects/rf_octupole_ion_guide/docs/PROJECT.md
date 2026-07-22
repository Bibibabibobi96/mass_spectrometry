# RF八极杆离子导引项目状态

## 当前结论

项目已建立独立身份和理想有限长度L1传输合同。模型使用八根交替极性电极对应的理想八极场，直接积分
RF相位分辨的非线性横向运动，并以0 V对照判断RF是否产生功能性约束。它不是四极杆mode，也不使用
Mathieu稳定图。权威运行`20260722_174051__sim__python__rf-octupole-ion-guide-l1__n25`中，RF开启时
25/25到达出口，0 V对照仅1/25到达；该结果满足当前L1功能门禁。

## 当前参数与边界

- 阶数`n=4`，电极数8，`r0=4 mm`，理想可用半径3.6 mm，有效长度79.6 mm。
- 单相位组相对共同偏置的RF零到峰值为139.81792 V，频率1.1 MHz。
- 固定N=25、100 amu、+1、2 eV源；最大源半径0.5 mm，最大入射发散5°。
- 碰撞、空间电荷、磁场、真实圆杆、外壳、支撑、端部边缘场和接口均未启用。
- 当前结果只允许L1趋势和代码/合同复用结论，不允许真实传输率、机械设计、Candidate或Formal声明。

## 权威入口

- [`../config/baseline.json`](../config/baseline.json)
- [`../config/modes/transport_no_collision.json`](../config/modes/transport_no_collision.json)
- [`../analysis/run_transport.ps1`](../analysis/run_transport.ps1)
- [`../verify_project.ps1`](../verify_project.ps1)

## 下一步

下一阶段建立参数化真实圆杆二维场并拟合寄生多极，再进入有限三维端部和粒子跟踪。几何选择不得由
理想场结果直接指定；碰撞冷却、COMSOL、SIMION和CAD均为独立后续阶段。
