# RF八极杆离子导引项目状态

## 当前结论

项目已建立独立身份和理想有限长度L1传输合同。模型使用八根交替极性电极对应的理想八极场，直接积分
RF相位分辨的非线性横向运动，并以0 V对照判断RF是否产生功能性约束。它不是四极杆mode，也不使用
Mathieu稳定图。权威运行`20260722_174051__sim__python__rf-octupole-ion-guide-l1__n25`中，RF开启时
25/25到达出口，0 V对照仅1/25到达；该结果满足当前L1功能门禁。

二维COMSOL圆杆场筛选`20260722_180355__sim__comsol__rf-octupole-ion-guide-round-rod-screen__l2`
选择`r_rod/r0=0.36`：杆半径1.44 mm、中心半径5.44 mm、相邻表面间隙1.2836 mm；边界归一化
`A12/A4=0.0038734`、`A20/A4=0.0031532`。两个采样环得到的高阶系数一致。使用带符号谐波重建场的
`20260722_181611__sim__python__rf-octupole-ion-guide-round-rod__l2-n25`为RF 25/25、0 V 1/25，出口
RMS半径0.5560 mm。它证明二维真实圆杆横向场的功能贯通，不证明有限三维端部或机械资格。

有限三维直接COMSOL运行`20260722_183912__sim__comsol__rf-octupole-ion-guide-finite-3d__l3-n25`
在相同N=25源下得到RF 25/25、0 V 1/25；RF出口RMS半径0.622266 mm，杆区最大半径1.040429 mm。
相对L2，端部场使束斑和最大径向运动有所增加，但没有破坏当前功能门禁。模型和原生轨迹均已保存。

## 当前参数与边界

- 阶数`n=4`，电极数8，`r0=4 mm`，理想可用半径3.6 mm，有效长度79.6 mm。
- 单相位组相对共同偏置的RF零到峰值为139.81792 V，频率1.1 MHz。
- 固定N=25、100 amu、+1、2 eV源；最大源半径0.5 mm，最大入射发散5°。
- 碰撞、空间电荷、磁场、开孔端盖、外部接口、支撑和机械公差均未启用。
- L2使用二维COMSOL场的谐波展开并沿z均匀延伸；未做网格收敛，不允许机械设计、Candidate或Formal声明。
- L3使用20 mm内半径封闭接地圆柱腔和完整有限圆杆，COMSOL直接求解端部场与轨迹；它尚未满足
  `foundations.md`对完整接口、独立比较和Candidate资格的全部要求。

## 权威入口

- [`../config/baseline.json`](../config/baseline.json)
- [`../config/modes/transport_no_collision.json`](../config/modes/transport_no_collision.json)
- [`../analysis/run_transport.ps1`](../analysis/run_transport.ps1)
- [`../config/round_rod_field_screen.json`](../config/round_rod_field_screen.json)
- [`../analysis/run_round_rod_field_screen.ps1`](../analysis/run_round_rod_field_screen.ps1)
- [`../analysis/run_round_rod_transport.ps1`](../analysis/run_round_rod_transport.ps1)
- [`../config/finite_3d_transport.json`](../config/finite_3d_transport.json)
- [`../analysis/run_finite_3d_transport.ps1`](../analysis/run_finite_3d_transport.ps1)
- [`../verify_project.ps1`](../verify_project.ps1)

## 下一步

下一阶段把封闭端面改成参数化开孔接口，验证外部注入和输出；随后再决定是否需要SIMION独立比较、
网格收敛和机械baseline。碰撞冷却与CAD仍为独立后续阶段。
