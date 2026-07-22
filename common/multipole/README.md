# 多极杆公共参考实现

本目录只保存已经由至少两个平级项目实际调用并通过各自门禁的求解器无关能力。目前范围为一般
理想 $2n$ 极横向场、伪势与绝热性尺度、有限长度 L1 时间域传输、统一RF/DC双极性组电压合同、配对
多质量粒子表与质量响应分析，以及二维圆杆COMSOL场谐波筛选、由带符号谐波重建的L2有限长度传输和
带参数化开孔端板与有限外部区的三维COMSOL直接跟踪。

当前调用方：

- `projects/rf_quadrupole_collision_cooling`
- `projects/rf_hexapole_ion_guide`
- `projects/rf_octupole_ion_guide`

`family_contract.json`只冻结三项目共同的坐标、`r0`和双极性组电压语义；
`resolve_family_operating_contract.py`把各项目baseline、mode和显式运行绑定标准化为每次run冻结的
`family_operating_contract.json`。项目 baseline/mode 仍是物理参数权威，公共代码不得内置项目专用
电压、尺寸、粒子源或资格阈值。配对质量扫描和质量响应是公共机制，四极杆Mathieu通带及当前PASS判据
仍留在四极杆项目。三维接口合同由
`resolve_finite_3d_contract.py`在求解前验证并单向派生端板、释放面、检测面和真空域轴向坐标。当前能力
不选择机械正式几何，也不覆盖网格收敛、屏蔽优化、碰撞、空间电荷或通用求解器适配。理论与符号以
[`../../docs/multipoles/index.md`](../../docs/multipoles/index.md)为入口。
