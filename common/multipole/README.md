# 多极杆公共参考实现

本目录只保存已经由至少两个平级项目实际调用并通过各自门禁的求解器无关能力。目前范围为一般
理想 $2n$ 极横向场、伪势与绝热性尺度、有限长度 L1 时间域传输、统一RF/DC双极性组电压合同、配对
多质量粒子表与质量响应分析，以及二维圆杆COMSOL场谐波筛选、由带符号谐波重建的L2有限长度传输和
带参数化开孔端板与有限外部区的三维COMSOL直接跟踪，以及由同一圆杆阵列合同生成的SIMION GEM、
粒子输入、RF/0 V配对跟踪和跨求解器功能比较。

当前调用方：

- `projects/rf_quadrupole_collision_cooling`
- `projects/rf_hexapole_ion_guide`
- `projects/rf_octupole_ion_guide`

`family_contract.json`只冻结三项目共同的坐标、`r0`和双极性组电压语义；
`resolve_family_operating_contract.py`把各项目baseline、mode和显式运行绑定标准化为每次run冻结的
`family_operating_contract.json`。项目 baseline/mode 仍是物理参数权威，公共代码不得内置项目专用
电压、尺寸、粒子源或资格阈值。配对质量扫描和质量响应是公共机制，四极杆Mathieu通带及当前PASS判据
仍留在四极杆项目。公共COMSOL有限三维求解器执行该合同的RF波形、幅值、频率、相位、差分DC和
公共偏置；`zero_rf_control`只关闭RF，保留DC与公共偏置。三维接口合同由
`resolve_finite_3d_contract.py`在求解前验证并单向派生端板、可为0 mm的连接器、释放面、检测面和真空域
轴向坐标。`round_rod_geometry.py`是四、六、八极杆杆心、杆径、角度、极性组和轴向范围的唯一公共
派生源；`interface_geometry.py`统一杆端间隙、开孔端板、可为0 mm的连接器、粒子入口面和出口观察面。
屏蔽截面可为项目参数，观察面也不等同于每台真实器件都安装实体探测器。COMSOL与SIMION只做求解器
格式转换。`simion_transport.lua`由四、六、八极杆实际调用，项目目录只保留工况与
附属结构适配。当前能力不选择机械正式几何，也不覆盖网格收敛、屏蔽优化、碰撞或空间电荷。理论与符号以
[`../../docs/multipoles/index.md`](../../docs/multipoles/index.md)为入口。

SIMION的通用beam/source-state文本序列化位于`common/simion/`；本目录只负责把多极杆canonical或
ION11坐标适配到该求解器无关序列化层。run目录建立、失败收尾、manifest及canonical粒子状态验证位于
`common/contracts/`，四、六、八极杆使用同一实现。
SIMION 2020有限三维运行器按`gem2pa → refine → PA句柄稳定等待 → 直接CLI fly`严格串行；不得在
`simion lua`任务内再次用`simion.command("fly")`重入同一PA操作。
