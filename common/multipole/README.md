# 多极杆公共参考实现

本目录是RF多极杆家族的共享实现边界。主要职责为：

- 求解器无关的理想 $2n$ 极场、伪势、绝热性、L1/L2传输、RF/DC双极性组电压和配对多质量合同；
- 由同一圆杆阵列与轴向接口合同生成COMSOL和SIMION输入；
- 公共传输、canonical粒子状态和求解器间的功能比较。

项目参数、项目PASS阈值、专用耦合物理和Formal资格不属于本目录。

当前调用方：

- `projects/rf_quadrupole_collision_cooling`
- `projects/rf_hexapole_ion_guide`
- `projects/rf_octupole_ion_guide`

粒子数不在本目录另设默认值，只消费根README指定的仓库级
[`../contracts/particle_count_policy.json`](../contracts/particle_count_policy.json)。低于N=100的旧运行只在
各项目history中保留，不构成当前功能、Candidate或Formal证据。

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

## 连接器术语与责任边界

**Multipole passive connector**是多极杆公共能力：它由统一轴向接口合同表达0 mm共面直连或
正长度被动接地连接段，支持`rectangular_bore`与`cylindrical_bore`截面。它还统一处理孔径、轴向范围、
观察面及刚体坐标变换的通用语义；各项目只从baseline与mode单向派生具体尺寸、截面和位姿。

**RF→oaTOF专属耦合链**不是第二套连接器几何内核。它在公共passive connector上适配RF出口与oaTOF入口参数，
并另外负责oa屏蔽开孔、局部联合场、全局时钟下的脉冲捕获/提取以及下游分析器续算。这些是
`rf_quadrupole_collision_cooling`项目的耦合参数和验收链，不反向复制公共连接器实现。

公共层还提供`axial_acceleration.py`与`create_multipole_segmented_round_rods.m`。轴向加速合同
schema v2支持两种分段策略：`uniform`按段数、统一间隙和首末公共模电势派生等长段与线性电势阶梯；
`explicit`逐段给出长度、段后间隙和公共模电势，并强制所有段和间隙精确守恒杆长。两种策略都保持
每段两组杆接受相反RF、共享同一轴向DC公共模电势，功能对照保持相同分段几何和RF，仅把轴向静电场
缩放为0；不得在粒子状态或handoff处重写速度。

公共COMSOL与SIMION有限三维runner及四、六、八极杆薄wrapper统一接受
`AxialAccelerationContractPath`。未显式给出路径时仍读取各项目
`config/modes/axial_acceleration_reference.json`，因此三项目现有默认保持`uniform`四段参考；
`explicit`必须由调用方传入具名合同，不会隐式改变默认工况。四极杆已用一份非等长、非等间隙、
非线性电势的显式合同完成两求解器N=100功能复验，详细运行证据只记在四极杆PROJECT；六、八极杆
目前只完成wrapper兼容和静态合同覆盖，没有新增显式分段真实求解器结论。

分段杆默认`uniform`轴向加速与端面加速已经由四、六、八极杆分别完成COMSOL和SIMION N=100功能
复验，共12项证据由`family_contract.json`的`functional_validation`冻结。该PASS及四极杆新增的
`explicit`功能证据只关闭公共加速实现和状态链的相应功能风险；参数优化、网格收敛、跨求解器数值
等价和机械馈电仍不在当前闭合范围。

SIMION的通用beam/source-state文本序列化位于`common/simion/`；本目录只负责把多极杆canonical或
ION11坐标适配到该求解器无关序列化层。run目录建立、失败收尾、manifest及canonical粒子状态验证位于
`common/contracts/`，四、六、八极杆使用同一实现。
SIMION 2020有限三维运行器按`gem2pa → refine → PA句柄稳定等待 → 直接CLI fly`严格串行；不得在
`simion lua`任务内再次用`simion.command("fly")`重入同一PA操作。

## 冻结状态

公共基础层现为`frozen_functional_baseline`，机器范围和变更条件只由`family_contract.json`定义，
`python -m common.multipole.verify_family_foundation`一次校验四、六、八极杆身份、运行合同、公共生产入口
及连接器变量，并已接入仓库轻量门禁。冻结表示后续项目直接复用，不表示接口、网格、机械几何或
Formal资格已经完成；修改公共基础层仍允许，但必须通过家族门禁，并对受影响适配器执行真实求解器回归。

生产路径审计未发现第二套杆阵列、RF/DC运行时、有限三维接口或canonical状态实现。保留在
项目侧的是四极杆Mathieu/oaTOF耦合与方形外壳、六/八极杆薄入口和项目验收阈值；这些语义不能上移。
四极杆已关闭的网格与联合场诊断脚本可能保留专用分区或几何印模，不属于冻结生产入口；若重新启用，
必须先改为消费公共杆阵列，不能据其局部写法恢复第二参数源。

迁移前小样本的连接器、传输和加速数值不在公共README重复保存，只从各项目README进入日期化history。
