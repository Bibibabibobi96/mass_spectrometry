# oa-TOF SIMION 实施与验证

本文件只记录SIMION实现、GUI操作和独立验证。统一几何、粒子、FWHM定义、正式状态和下一步
由[`PROJECT.md`](PROJECT.md)定义。历史过程由项目 README 路由，日常任务不从本文件跳转读取。

## 当前入口与状态

- 正式文本入口：`../simion/workbench/formal/oatof_ideal_grounded.lua/.fly2`。
- 当前 GUI 候选 IOB：工作区
  `artifacts/projects/oa_tof/models/simion/workspace/diagnostics/accelerator_compact_scan/workbenches/grid_xy025_z0050_refaxial0250/oatof_accz0050_refz0250.iob`。
- `models/simion/workspace/` 暂时保留，因为 IOB 使用相对 PA 路径；只有重建并验证四个实例后才能扁平化。
- 当前标准：524 amu、+1、`5±0.4 eV`；GUI常规统计N=5000。
- 正式轨迹积分档位是`trajectory quality=8`；同名Program在IOB加载和每次Fly前自动写入，
  GUI Fly和命令行必须一致，低档只允许显式诊断。
- 日常候选网格：加速器`xy=0.25mm,z=0.05mm`；收敛参考`z=0.025mm`。
- 检测器第4实例是GUI可见数值终止层，不是机械检测器实体。
- Program和Data Recording必须同时开启；关闭Program窗口不等于禁用Program。
- `trajectory_log_enable`默认必须为0，使GUI Data Recording不被逐粒子TRACE淹没；只有命令行
  审计/峰形分析时才显式设为1。
- 当前候选尚待COMSOL 524 amu闭合，不能单独提升为正式项目模型。

稳定实现入口以`config/simion_stable_entry.json`冻结：0.05mm是日常候选，0.025mm仅作轴向
网格收敛参考。该清单只记录外部工作区资产的路径、大小和SHA-256，不重复维护物理参数；物理
参数仍以`config/baseline.json`为唯一来源。每次移动、重建或打包SIMION资产后运行：

```powershell
.\projects\oa_tof\tests\simion\verify_stable_entry.ps1
```

脚本先逐项验证IOB、CON、Program、Fly2和四个PA的大小/哈希，再实际加载每个IOB并检查4实例与
T.Qual=8。任一项改变都必须重新验证并有意识地更新清单，禁止只替换PA或手工改IOB后继续称为稳定入口。

## GUI对等原则

正式IOB必须让用户直接看到并修改reflectron、accelerator、flight-tube和detector四个PA实例、
Fast Adjust电压、实例坐标、Fly2粒子和同名Program。命令行只允许改变线程、无GUI模式和输出
路径，不能覆盖GUI不可见的物理参数。检测器必须显示有效面和口径，禁止只用Lua虚拟平面终止。

原生Data Recording复核至少记录Ion Number、TOF、X/Y/Z和Event；只有一列TOF不能证明所有
记录都来自第4实例终止层。

GUI记录时把Data Recording输出保存到独立CSV/文本文件，不从SIMION控制台复制。Program保持
启用，加载后确认Fly对话框自动显示`trajectory quality=8`，Adjustables中的
`trajectory_log_enable=0`；
这样检测器终止、几何联动和Fast Adjust仍然
工作，但控制台不再输出每个离子的`detector_splat_raw/detector_crossing/detector_hit_entity`。

2026-07-15已将0.05 mm日常候选和0.025 mm收敛候选同步为上述默认值。单粒子实测：不传覆盖
参数时TRACE为0行，显式`trajectory_log_enable=1`时为11行，且两种模式均正常完成飞行。因此
该开关只控制审计输出，不关闭Program，也不改变检测器终止或飞行物理。

### 2026-07-15 GUI Data Recording积分精度审计

桌面同名工作簿`simion_524amu_intensity_time_spectrum.xlsx`的更新版含5000个连续离子，所有记录
均来自PA实例4且`z=19.83mm`，因此记录数量、检测器实例和检测面均正确。MATLAB直接FWHM分析
得到平均TOF `72.00529112us`、TOF标准差`7.24070347ns`、直接TOF FWHM
`22.05991476ns`，对应直接质量FWHM `0.32107740amu`、`R=1632.01`。

用完全相同的`oatof_accz0050_refz0250.iob/.fly2`做命令行对照后确认差异来自轨迹积分档位：

| 运行 | N | 平均TOF (us) | 标准差 (ns) | 直接TOF FWHM (ns) | 直接质量R |
|---|---:|---:|---:|---:|---:|
| GUI工作簿 | 5000 | 72.005291 | 7.240703 | 22.059915 | 1632.01 |
| 命令行quality=3 | 5000 | 72.004126 | 7.053347 | 19.925180 | 1806.97 |
| 正式命令行quality=8 | 5000 | 71.990291 | 0.815089 | 1.408880 | 25549.58 |

quality=3与GUI结果高度一致，而quality=8使均值恢复到正式基线并将直接FWHM缩小约一个数量级。
因此本次GUI宽峰不是检测器厚度、Program输出、Excel直方图、N或偶然统计误差造成，而是Fly
对话框仍使用低轨迹质量。该GUI工作簿只保留为错误复现，不得作为正式质量谱。重新记录前必须
在Fly对话框确认`trajectory quality=8`。Data Recording文件不会保存该设置，分析器只能验证
N、检测器实例和检测面，并会把轨迹质量标成`QUALITY_UNVERIFIED`。

为防止再次依赖人工记忆，正式文本Program增加`adjustable trajectory_quality=8`：
`segment.load()`在每次加载IOB时把Particles页T.Qual改为8，`segment.initialize_run()`在每次
Fly前再次写入。只改Particles页的T.Qual会在飞行前被正式Program恢复；需要低精度诊断时必须
显式修改Program Adjustables中的`trajectory_quality`，并在结果名中标出quality，不能覆盖基线。

`build_formal_iob.lua`现在会在保存四实例IOB后同时部署同basename的完整`.lua`和`.fly2`，
并在构建前拒绝缺少quality=8加载契约的Program。运行时门禁为：

```powershell
.\projects\oa_tof\tests\simion\verify_iob_runtime_contract.ps1 `
  -IobPath <待验收.iob> -ExpectedTrajectoryQuality 8 -ExpectedInstances 4
```

门禁必须实际加载IOB并收到Program的`segment.load`报告；只检查Lua文本或IOB文件存在不算通过。
独立SIMION Lua进程不能直接读取Workbench Program环境中的`sim_trajectory_quality`，会得到nil；
门禁因此使用每次唯一的临时报告路径，由Program加载段写值，避免误读上一次残留的PASS报告。
Data Recording本身不保存T.Qual，因此以后遇到“GUI导出结构正确但TOF峰突然宽一个数量级”时，
按以下顺序快速定位：先核对N、PA instance和检测面，再查看平均TOF与标准差是否接近本次
quality=3指纹（约`72.004us/7.05ns`），最后用同一IOB分别做quality=3/8小样本或固定粒子对照。
若低档复现而quality=8恢复约`71.9903us/0.815ns`，直接判定为轨迹积分档位问题，不再重复排查
检测器厚度、Program控制台输出、Excel直方图或偶然统计误差。

### 2026-07-16同名Excel覆盖与统一分析复核

桌面同名文件后来已被覆盖，当前`simion_524amu_intensity_time_spectrum.xlsx`不再是上节所述
含Ion Number、PA instance和X/Y/Z的版本。当前列只有`TOF`及人工`mean/max/min/delta T/std/R1/R2`，
共有5000条TOF；因此只能复核单峰谱，不能证明记录来自第4实例、检测面一致、quality=8或与另一
求解器逐粒子配对。本次文件为56059字节，SHA-256为
`57EEC5E6EC6275C8DC79C3F9A2EC4E4D336DB772FD9E753127F718643DCC4FC4`。以后文档不得仅用可覆盖
文件名指代数据，至少绑定列结构、行数和SHA-256。

Python 3.11/Pandas统一入口成功读取当前工作簿，并明确把顺序粒子ID标记为人工生成。统一算法得到
平均TOF`71.99026824 us`、标准差`0.81232215 ns`、直接TOF FWHM`1.29084535 ns`、直接质量
FWHM`0.0187909682 Da`和`R=27885.74`；时间域等价R为`27884.93`，相差约0.0029%。Excel内的
`R1=19456.83`和`R2=35452.67`均不符合本项目`R=m/FWHM_m`定义，不得引用。

该工作簿与冻结的正式命令行N=5000数据平均TOF只差`-0.0226 ns`，但统一直接FWHM对应的R高
约14.3%。两者不是同一固定粒子表，非高斯右肩又使直接FWHM对样本敏感，所以不能据平均时间相近
认定逐粒子或峰宽闭合。当前工作簿只保留为未配对GUI人工复核；正式跨求解器比较仍必须导出真实
Ion Number，并记录PA instance、X/Y/Z和Event。

2026-07-15已用新构建器重建0.05mm日常候选和0.025mm收敛候选；两者重新加载均为4实例、
`TRAJECTORY_QUALITY=8`。0.05mm候选四实例仍是`849×356×1`反射器、`153×153×601`
加速器、`601×355×1`无场管和`165×165×31`检测器，坐标及网格未变。其IOB二进制SHA-256
重建前后均为`BD39757D2A8DC3BFF8DD052A8BBAFF570498E3A520C9A38D0EF7F91C86BDC203`；quality契约
位于构建器自动部署的同名Program中，这是预期行为。进一步用命令行故意请求quality=3，Program
在飞行前仍报告`trajectory_quality=8`，单离子于`31.4489337341us`命中检测面，证明旧会话或
外部T.Qual值不会污染正式运行。单粒子ION测试不要传`--default-num-particles 1`，SIMION会报
容量参数越界；省略该容量参数即可。

## 实施流程

## 阶段 A：确认安装与可写工作区

程序：`C:\Program Files\SIMION-2020\simion.exe`。

工作文件必须保存在本目录，不能保存在Program Files。先在SIMION中打开
`examples_reference/simion_fast_adjust_demo.gem`，另存为
`01_accelerator/smoke_fast_adjust.pa#`，并完成：GEM处理、Refine、Fast Adjust和保存PA0。
这一步通过的标准是：生成`smoke_fast_adjust.pa0/.pa1/.pa2/.pa3`，且可改变某个电极电压而不重新Refine。

随后只读打开`examples_reference/simion_nonideal_grid_demo.gem`，观察真实细丝grid的网格尺度；不要把该示例直接放大到oa-TOF全孔径。

## 阶段 B：理想栅网反射镜 PA#

已建立`02_reflectron/oatof_reflectron_ideal_10_5.pa#`，使用2D cylindrical PA，标尺`1 mm/gu`。这是与COMSOL轴对称理想栅网反射镜场比较的正式第一基线；在它通过轴线场和转向深度比较前，不扩展成全尺寸3D阵列。

几何包含：接地圆柱屏蔽壳、入口栅网、10个一级环、级间栅网、5个二级环、背板。每个环单独为一个Fast Adjust电极；准确位置/电压见：

- `00_reference/oatof_final_10_5_baseline.json`
- `00_reference/reflectron_ring_table_10_5.csv`

栅网规则：`entgrid`和`midgrid`是与有效截面等大的、一网格点厚的电极面。它们是理想透明等势面，**不是**带大孔的实体板。这样才与COMSOL内部边界基线一致。

建议编号：

| electrode | SIMION fast-adjust号 |
|---|---:|
| entgrid | 1 |
| stage1 ring 1..10 | 2..11 |
| midgrid | 12 |
| stage2 ring 1..5 | 13..17 |
| backplate | 18 |

地屏蔽罩保持普通0 V电极，不需要单独Fast Adjust。

## 阶段 C：加速器 PA#

加速器使用3D Cartesian PA。正式固化前的稳定候选为孔半宽5mm、环单边宽5mm、
带电电极到接地屏蔽内壁每侧5mm、repeller后表面到后盖前表面5mm、屏蔽壁4mm；
PA物理范围为`38×38×30 mm³`（z=`-10..20mm`）。常态快速网格为
`xy=0.25mm、z=0.05mm`（`153×153×601`）；跨求解器闭合/收敛参考为
`xy=0.25mm、z=0.025mm`（`153×153×1201`）。GEM物理几何只有一份；数值网格参数不得
借诊断变体修改电极尺寸、厚度、轴向位置或绝缘间隙。

包含repeller、grid1、grid2、5个加速器环和接地屏蔽罩。grid1/grid2同样是一网格点厚的透明等势面。

基准电压：repeller=2240 V，grid1=1760 V，grid2=0 V；加速器环电压依据当前COMSOL脚本的线性规则。

当前电极编号与 fast-adjust：1=repeller，2=grid1，3..7=五个加速器环，8=grid2，9=grounded shield；对应电位为2240、1760、1466.666667、1173.333333、880、586.666667、293.333333、0、0 V。唯一参数化重建入口为`build_accelerator_variant.lua`。

网格闭合使用`build_accelerator_variant.lua`。构建器必须先打印尺寸和完整PA家族容量估算，
并设置可接受的GiB硬上限。各向同性/分区对照已证明横向0.25mm足够，误差主要来自z向。
`z=0.05mm`相对`z=0.025mm`的FWHM仍宽约23.6%（反向表述为0.025比0.05低19.1%），
故0.05mm只作常态快速网格，0.025mm作收敛参考；当前不再继续加密。正式或稳定结论必须把选定PA保存
进独立四实例IOB，使GUI可直接看到实际网格和实例坐标；运行时PA覆盖只允许短期诊断，不能
作为正式交付。已fast-adjust的PA0飞行时设置`accelerator_fast_adjust_enable=0`，避免重复
组合9个基阵。

## 阶段 D：Workbench 与初始验证

正式IOB必须有四个GUI可见PA实例：reflectron、accelerator、flight-tube和detector。
IOB目录还必须包含同 basename 的完整`.lua`和`.fly2`；`.fly2`至少要有可编辑的
`standard_beam`，不得只保存空`particles { coordinates=0 }`，否则GUI的Define Particles
会报`attempt to index a nil value`。`build_formal_iob.lua`在保存IOB前预读正式Fly2，保存后
自动恢复到输出basename，防止SIMION生成的最小Fly2覆盖GUI粒子定义。
加速器轴放在`x=-48.8 mm`，反射镜轴放在`x=0`；接地detector示意PA的中心位于
`x=+48.8 mm`，有效半径40 mm，迎离子面位于`z=L_accel`。它不是机械探测器形状；数值
吸收层厚度、前后余量和各向异性网格由独立参数控制，不能回写为COMSOL或SolidWorks实体
厚度。禁止只用不可见Lua测试面代替GUI示意PA；Lua只在第4实例电极splat后的
`segment.terminate`中记录、审计命中。当前推荐`xy=0.5 mm、z=0.01 mm、吸收层0.05 mm`。

原生Data Recording复现时必须保持Program开启，因为电压fast-adjust和四个理想栅网跳转
属于模型本身。细z检测器PA已使`TOF at ion's splat`与`z=19.83 mm`参考面逐粒子闭合；
检测器邻域`tstep_adjust`仅为可选诊断，正式默认关闭。

这里的“关闭Program窗口”和“禁用Program”必须区分：关闭设置对话框不会停用程序，可以继续
打开Data Recording；取消Program复选框或选择Disable Program会停用fast-adjust、理想栅网
跨越、几何联动、命中分类和超时保护，结果不再属于本基线。Program与Data Recording必须
同时启用。GUI原生复核建议至少同时记录Ion Number、TOF、X/Y/Z和Event；只有TOF一列时不能
证明全部记录均来自第4实例检测器终止层。

同名正式Fly2必须在GUI中显示524 amu、+1、N=5000、1×1×1 mm³释放体和`5±0.4 eV`
能量分布。需要与COMSOL严格比较时使用固定归档ION文件，并在结果中注明ION路径。

SIMION常规统计自2026-07-15起使用N=5000；命令行必须同步传入
`--default-num-particles 5000`，否则SIMION默认1000容量会拒绝读取完整ION表。COMSOL快速闭合
可保留较小N，不因SIMION提速而强制同步增加计算量。

第一轮只飞固定单粒子，记录：

1. 到达entgrid时刻；
2. 最大反射深度；
3. 返回探测面时刻；
4. 横向位置和速度。

524 amu SIMION 0.05mm日常网格当前到达时间约71.99023 us；正式COMSOL 524 amu基准尚待
重算。31.44793 us和二级最大穿透51.07mm只属于100 amu历史COMSOL模型，不得用于524 amu验收。

## 阶段 E：真实丝网局部单元

仅在理想栅网版本通过后，建立`03_grid_cell/`中的高分辨率3D网孔单元。输入真实丝径、节距、材料和两侧电压；输出透过率、撞丝概率、横向kick查表。

主Workbench不显式铺满细丝。用Lua在粒子通过栅网平面时按局部表施加损失/偏转，或采用SIMION的非理想grid单元重复/跳转技术。

优先顺序：先`entgrid`、再`midgrid`、最后才评估grid1/grid2。

## 结果纪律

- 每次曲线含多条线必须有legend。
- 图标题写明PA标尺、栅网模式、粒子数和Fast Adjust电压集。
- 理想栅网与真实丝网结果不得混在同一基线表。
- 首次比较必须保留COMSOL与SIMION的轴线`V(z)`、`Ez(z)`和单粒子轨迹PNG。
- 加密测试必须先做同网格裁边控制，再做单离子、N=100、N=1000；否则不能把裁边效应、
  统计波动和网格收敛混为同一结论。
