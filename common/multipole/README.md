# 多极杆公共参考实现

本目录只保存已经由至少两个平级项目实际调用并通过各自门禁的求解器无关能力。目前范围为一般
理想 $2n$ 极横向场、伪势与绝热性尺度，以及忽略端部边缘场的有限长度 L1 时间域传输参考。

当前调用方：

- `projects/rf_hexapole_ion_guide`
- `projects/rf_octupole_ion_guide`

项目 baseline 是参数权威；公共代码不得内置项目专用电压、尺寸或粒子源。真实圆杆几何、寄生多极、
网格、屏蔽、有限三维端部、碰撞、空间电荷及求解器适配仍不属于公共层。理论与符号以
[`../../docs/multipoles/index.md`](../../docs/multipoles/index.md)为入口。
