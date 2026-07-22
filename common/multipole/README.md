# 多极杆公共参考实现

本目录只保存已经由至少两个平级项目实际调用并通过各自门禁的求解器无关能力。目前范围为一般
理想 $2n$ 极横向场、伪势与绝热性尺度、有限长度 L1 时间域传输，以及二维圆杆COMSOL场谐波筛选和
由带符号谐波重建的L2有限长度传输，以及封闭接地圆柱腔内的有限三维COMSOL直接跟踪。

当前调用方：

- `projects/rf_hexapole_ion_guide`
- `projects/rf_octupole_ion_guide`

项目 baseline 是参数权威；公共代码不得内置项目专用电压、尺寸或粒子源。当前公共L2能力不选择机械
正式几何，也不覆盖开孔接口、网格收敛、屏蔽优化、碰撞、空间电荷或通用求解器适配。理论与符号以
[`../../docs/multipoles/index.md`](../../docs/multipoles/index.md)为入口。
