# oa-TOF SIMION 实施与验证

本文件只记录SIMION实现、GUI操作和独立验证。统一几何、粒子、FWHM定义、正式状态和下一步
由[`PROJECT.md`](PROJECT.md)定义。历史过程由项目 README 路由，日常任务不从本文件跳转读取。
发送给同事的独立参数交接单见[`SIMION_REPRODUCTION_PARAMETERS.md`](SIMION_REPRODUCTION_PARAMETERS.md)。

## 当前入口与状态

- 正式文本入口：`../simion/workbench/formal/oatof_ideal_grounded.lua/.fly2`。
- 正式GUI/交付目录：`artifacts/projects/oa_tof/models/simion/formal/oatof_524amu/`；IOB、CON、
  同名Program/Fly2、四套完整PA家族和固定ION均集中于此。
- `models/simion/workspace/`仅保留收敛参考、构建源和待审计历史；正式IOB不再引用其中PA。
- 当前标准：524 amu、+1、`5±0.4 eV`；GUI常规统计N=5000。
- 正式轨迹积分档位是`trajectory quality=8`；同名Program在IOB加载和每次Fly前自动写入，
  GUI Fly和命令行必须一致，低档只允许显式诊断。
- 正式日常网格：加速器`xy=0.25mm,z=0.05mm`；收敛参考`z=0.025mm`。
- 检测器PA是GUI可见数值终止层，不是机械检测器实体；当前正式Workbench槽位/PA instance为4，
  GUI优先级为4，是最高优先级终止层。
- Program和Data Recording必须同时开启；关闭Program窗口不等于禁用Program。
- `trajectory_log_enable`默认必须为0，使GUI Data Recording不被逐粒子TRACE淹没；只有命令行
  审计/峰形分析时才显式设为1。
- 当前日常IOB、正式COMSOL MPH和SolidWorks装配体已经通过共享几何门禁；SIMION网格收敛参考仍
  保持候选角色，不得误写成第二套正式几何。

稳定实现入口以`config/simion_stable_entry.json`冻结：0.05mm是正式可移植交付，0.025mm仅作轴向
网格收敛参考。该清单记录外部资产路径、大小和SHA-256，不重复维护物理参数；物理
参数仍以`config/baseline.json`为唯一来源。每次移动、重建或打包SIMION资产后运行：

```powershell
.\projects\oa_tof\tests\simion\verify_stable_entry.ps1
```

脚本分别验证正式包和自包含收敛参考的SHA256清单各覆盖54个文件，再实际加载两个IOB并检查
4实例、静态优先级与T.Qual=8。任一项改变都必须重新验证并有意识地更新清单，禁止只替换PA或手工改IOB后
继续称为稳定入口。

`simion/workbench/build_formal_delivery.ps1`已从统一baseline/resolved契约和四份版本化GEM独立生成
全部PA家族，在输出目录的私有布局副本上重建四实例IOB，并部署同名Program/Fly2、N=100/N=1000
固定ION、复现说明、运行manifest和`SHA256SUMS.csv`。构建过程不读取
`workspace/diagnostics`中的PA；正式IOB布局只作为四实例GUI容器模板，打开前先复制到新PA同目录，
因此模板的旧PA路径不会参与新模型。`.con`GUI视图配置显式随新basename部署。

2026-07-17源码重建v3经固定N=1000转正门禁：两边均1000/1000命中，关键非零场矢量最大相对差
`7.92e-8`，新包减旧包的平均TOF为`-0.001014 ns`，逐粒子TOF RMS/最大绝对差为
`0.001874/0.008660 ns`，落点RMS/最大距离为`0.0000240/0.0001011 mm`，标准化KDE重叠
`0.9998405`。源码重建包已提升到正式目录，旧正式包整体归档；转正门禁入口为
`tests/simion/test_formal_delivery_source_build_equivalence.ps1`。

2026-07-16在正式几何同步后，用同一524 amu固定N=100 ION表重跑quality=8真实PA场，100/100
命中，平均TOF为`71.9901350726 us`。统一Python直接质量FWHM为`0.019673808666 Da`，
`R=26634.3954`；与同步前固定N=100结果只存在数值尾差，证明补齐10 mm封闭屏蔽罩没有实质改变
该样本的粒子传递。正式跨求解器比较和峰结构解释见`PROJECT.md`，机器记录见
`config/formal_validation.json`。

2026-07-18以当前正式IOB、PA、同名Program和正式N=1000 ION表直接重算，1000/1000命中，平均TOF
`71.9910151844 us`，统一直接KDE质量FWHM为`0.0117728715881 Da`、`R=44509.11`。该CSV、运行摘要、
当前IOB和交付manifest的SHA均由新版`config/formal_validation.json`冻结。

正式场诊断表明，SIMION释放区轴向Ez平均比COMSOL高`0.8396%`，而反射器内部相对RMS差仅
`0.000528%`。代表轨迹显示该小差异在出射漂移中累计、在反射器中反向补偿，最终只留下数ns
TOF差。SIMION加速器离轴Ex/Ey比COMSOL平滑且较弱；在COMSOL完成加速器域网格收敛前，禁止
仅凭该差异修改SIMION正式PA几何或电压。场采样入口位于`tests/simion/export_axis_field_profiles.lua`
和`export_accelerator_vector_field_samples.lua`。

### 2026-07-17 严格聚焦几何提升

候选构建器按`d1=3.0 mm,d2=16.8 mm`生成独立PA家族，并通过四实例IOB、同名Program、解析焦点、
同源粒子和CAD同步门禁后提升为正式几何。后续源码构建链重建和检测终止升级均通过N=1000数值
等价门禁；当前正式目录已由`simion_stable_entry.json`冻结，早期scratch/candidate不再是运行依赖。

### 2026-07-17 透明栅网跳转距离分组诊断

`ideal_grid_epsilon_mm`是理想零厚度栅网的数值跨面距离，不是机械间隙。扫描证明减小该值不会
改变PA场，却能减少人为跳过的栅网邻域场积分。Program现增加
`accelerator_grid_epsilon_mm`和`reflectron_grid_epsilon_mm`两个可选覆盖量；默认`-1`时继续使用
正式`ideal_grid_epsilon_mm=0.005`，故现有正式包行为不变。

N=100析因显示反射器entgrid/midgrid贡献占主导；正式几何副本只把反射器覆盖改为`0.0001 mm`
后，N=1000仍1000/1000命中，纯SIMION进程`35.37 s`，原`0.005 mm`同环境为`38.44 s`，没有
明显时间代价。逐粒子TOF闭合明显改善，但KDE峰形重叠下降，因此该覆盖仍是候选，不更新正式IOB、
Program默认值或`simion_stable_entry.json`。先前10分钟运行是直接改IOB basename造成的加载卡死，
日志保持0字节且未开始Fly；用正式四实例构建器重建后立即恢复正常，不能计入小跳转耗时。

## GUI对等原则

正式IOB必须让用户直接看到并修改reflectron、accelerator、flight-tube和detector四个PA实例、
Fast Adjust电压、实例坐标、Fly2粒子和同名Program。命令行只允许改变线程、无GUI模式和输出
路径，不能覆盖GUI不可见的物理参数。检测器必须显示有效面和口径，禁止只用Lua虚拟平面终止。

四个电场PA在本IOB模板中的Workbench槽位和GUI优先级编号一致，必须从低到高为：
`1 flight_tube`、`2 reflectron`、`3 accelerator`、`4 detector`。SIMION在重叠点只使用GUI
优先级最大的电场PA，因此无场管/接地屏蔽是最低优先级回退场，不能遮蔽加速器、反射器或
检测器终止面。正式Program不再用
`segment.instance_adjust()`补救错误排序，使GUI场查看、Program On/Off和命令行共享同一静态物理。
通用规则与官方依据见根级[`SIMION_REFERENCE.md`](../../../docs/SIMION_REFERENCE.md)。构建器、
`resolved_geometry.json`和运行时门禁共同拒绝顺序漂移。

2026-07-18静态正式验证确认上述顺序本身正确：Program不参与PA选择时，源区、漂移区、反射区和
检测器分别选择实例3、1、2、4。原0.05 mm薄终止层在N=100中只有9粒子被捕获，另91粒子跨层
后撞近端端盖；修复保持有效前表面`z=0`不动，只把吸收层向后加厚到0.1 mm，并在返回离子进入
检测面上游100 mm后，仅把真正跨面的一个时间步截到层内0.02 mm。N=100和N=1000均为100%实例4
物理命中；N=1000相对旧参考场差为0，平均TOF差`-0.000406 ns`，逐粒子TOF RMS/最大差为
`0.004733/0.018742 ns`，落点RMS/最大差为`2.35e-6/9.35e-6 mm`。原生splat仍插值到
`|z|<1e-8 mm`，不是在捕获深度记录。N=1000关闭/开启控制耗时`28.46/29.33 s`，开销约3.0%。

原生Data Recording复核至少记录Ion Number、TOF、X/Y/Z和Event；只有一列TOF不能证明所有
记录都来自当前契约指定的检测器槽位。

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

### 2026-07-16 GUI Program On/Off配对审计闭合

桌面同名工作簿再次更新为5000行、左右两组并排记录。冻结副本位于
`artifacts/projects/oa_tof/runs/simion_gui_recording/2026-07-16_program_on_off/raw/`，文件
462631字节，SHA-256为
`132640A666B5C861D3DA9B0834B2C300DD2C61478331206B1079A2017692A988`。Program On列为
`program on/event/TOF/PA instance/x/y/z`，Program Off列被Excel读为
`program off/event.1/TOF.1/PA instance.1/x.1/y.1/z.1`。两组Event均为用户所选ion splat事件的
数值码4，PA实例均为4，z均为19.83 mm。On组5000个连续离子的严格Recording审计全部通过，
最大检测器局部半径15.343 mm，小于40 mm。

本次来源是日常候选`oatof_accz0050_refz0250.iob`（SHA-256
`BD39757D2A8DC3BFF8DD052A8BBAFF570498E3A520C9A38D0EF7F91C86BDC203`）。稳定入口运行门禁再次
实际加载四个PA实例并得到`TRAJECTORY_QUALITY=8/STATUS=PASS`。XLSX本身仍不保存T.Qual；这里的
quality证据来自同名Program加载契约和用户记录的Program On状态，不得从TOF列反推。

统一Python直接FWHM结果为：

| 组别 | 平均TOF (us) | 标准差 (ns) | 直接TOF FWHM (ns) | 直接质量FWHM (Da) | R |
|---|---:|---:|---:|---:|---:|
| Program On（正式） | 71.99028682 | 0.806483 | 1.526591 | 0.02222238 | 23579.83 |
| Program Off（仅诊断） | 71.98789634 | 0.697827 | 0.723979 | 0.01053960 | 49717.24 |

该XLSX中的TOF实际只保留到`0.0001 us=0.1 ns`，不是Excel单元格显示格式造成的隐藏截断。因此
它适合闭合GUI和比较同精度的On/Off组，但直接FWHM仍会受0.1 ns量化影响；正式跨求解器数值比较
优先使用保留更多有效位的命令行TRACE/CSV，不用本表替换高精度基线。

同名Fly2固定执行`seed(20260713)`，所以两组是同一初始粒子的配对A/B，不是随机重抽样。Off-On
平均TOF为`-2.39048 ns`，逐粒子标准化TOF相关仅`0.05164`；标准化峰形KDE重叠`0.90727`、KS距离
`0.1122`（p约`8.1e-28`）。关闭Program后，初始粒子到TOF的排序几乎被重排，差异不是5000粒子
统计波动。

R的两倍差距不能按“整体展宽两倍”解释。On组非高斯右肩略高于50%峰高，直接FWHM跨过整个
肩部；Off组肩部略低于50%，FWHM只覆盖主峰。标准差只相差约15%，而半高阈值把峰肩的小变化
放大成R约111%的变化。比较图和机器结果位于同一run目录的`comparison/`。

Program代码逐项排查后的主因是透明栅网跨越。正式粒子每次飞行经过grid1一次、grid2一次、
entgrid往返两次、midgrid往返两次，共6次；既有TRACE逐粒子均记录为`1/1/2/2`。每次跨越把粒子
从栅网前`0.005 mm`移到后`0.005 mm`并补偿飞行时间，按约25--30 mm/us轴向速度估算，6次约
2--2.4 ns，与实测均值差`2.39048 ns`同量级。跨界位置重置还改变PA边界处的场积分和TOF映射，
从而移动右肩。默认`ideal_accel/stage1/stage2=0`，故`efield_adjust`不生效；
`detector_tstep_enable=0`，故时间步窗口不生效；约72 us未触发90 us超时；`segment.terminate()`只在
局部变量中算检测面修正，不改Data Recording的splat值。Fast Adjust和几何联动仍是正式可复现
所必需，但若在同一已初始化会话中由On切到Off，现有PA电势和实例位置可能被继承，XLSX不能证明
它们的状态。因此Off组只能用于说明禁用Program会破坏数值契约，不能作为更高R的替代基线。

结论：GUI人工复现链已闭合，正式结果只认Program On组；以后并排XLSX必须显式映射`.1`列，
Program Off门禁必须失败。

## 实施流程

### 阶段 A：确认安装与可写工作区

程序：`C:\Program Files\SIMION-2020\simion.exe`。

工作文件必须保存在本目录，不能保存在Program Files。先在SIMION中打开
`examples_reference/simion_fast_adjust_demo.gem`，另存为
`01_accelerator/smoke_fast_adjust.pa#`，并完成：GEM处理、Refine、Fast Adjust和保存PA0。
这一步通过的标准是：生成`smoke_fast_adjust.pa0/.pa1/.pa2/.pa3`，且可改变某个电极电压而不重新Refine。

随后只读打开`examples_reference/simion_nonideal_grid_demo.gem`，观察真实细丝grid的网格尺度；不要把该示例直接放大到oa-TOF全孔径。

### 阶段 B：理想栅网反射镜 PA#

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

### 阶段 C：加速器 PA#

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

2026-07-17进一步把`dz=0.05 mm`固定，只扫描几何相对网格的四个轴向相位，并用实例反向位移保持
全局机械坐标不变。`build_accelerator_variant.lua`因此增加仅用于候选诊断的前/后域余量与
`grid_phase_z`参数；默认均为0，正式PA不变。前后各扩展`0.2 mm`的裁边控制与正式裁边逐粒子等价，
而四相位在统一`0.03/0.04 mm`透明栅网跳转缓冲下分别产生`1.62898/1.65565 ns`平均TOF跨度。
两者只差`1.64%`，证明ns级相位敏感性稳健；但直接FWHM跨度为`32.89%/19.35%`，尚未对跳转缓冲
收敛。轴线场相对RMS最大仅`0.001718%`，所以主要问题是粒子跨越一网格点电极层的离散映射，不是
平均静电场强度。正式`0.005 mm`缓冲在半格相位会使粒子于grid1数值层splat，禁止把它解释为真实
栅网损失。以后若要求亚ns逐粒子闭合，必须先实现按实际数值电极层自适应的透明跨越并同时验证
相位/缓冲收敛；不得把电极尺寸改成网格整数倍，也不得用本次诊断PA替换正式交付。

### 阶段 D：Workbench 与初始验证

正式IOB必须有四个GUI可见PA实例：reflectron、accelerator、flight-tube和detector。
IOB目录还必须包含同 basename 的完整`.lua`和`.fly2`；`.fly2`至少要有可编辑的
`standard_beam`，不得只保存空`particles { coordinates=0 }`，否则GUI的Define Particles
会报`attempt to index a nil value`。`build_formal_iob.lua`在保存IOB前预读正式Fly2，保存后
自动恢复到输出basename，防止SIMION生成的最小Fly2覆盖GUI粒子定义。
加速器轴放在`x=-48.8 mm`，反射镜轴放在`x=0`；接地detector示意PA的中心位于
`x=+48.8 mm`，有效半径40 mm，迎离子面位于`z=L_accel`。它不是机械探测器形状；数值
吸收层厚度、前后余量和各向异性网格由独立参数控制，不能回写为COMSOL或SolidWorks实体
厚度。禁止只用不可见Lua测试面代替GUI示意PA；Lua只在检测器槽位电极splat后的
`segment.terminate`中记录、审计命中。当前推荐`xy=0.5 mm、z=0.01 mm、吸收层0.1 mm`。

原生Data Recording复现时必须保持Program开启，因为电压fast-adjust、四个理想栅网跳转和
检测器单步事件定位属于模型本身。`tstep_adjust`正式默认开启，但不是邻域统一细步进：只在
检测面上游100 mm内预测跨面，且仅把真正跨越`z=0`的单步终点放入0.02 mm捕获深度。原生
电极splat后再直线插值回精确有效面；该逻辑不改变PA优先级、上游轨道或场。

这里的“关闭Program窗口”和“禁用Program”必须区分：关闭设置对话框不会停用程序，可以继续
打开Data Recording；取消Program复选框或选择Disable Program会停用fast-adjust、理想栅网
跨越、几何联动、命中分类和超时保护，结果不再属于本基线。Program与Data Recording必须
同时启用。GUI原生复核建议至少同时记录Ion Number、TOF、X/Y/Z和Event；只有TOF一列时不能
证明全部记录均来自当前契约指定的检测器槽位终止层。

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

524 amu SIMION正式N=100、quality=8平均到达时间为`71.9901350726 us`；同步后的COMSOL正式
N=100平均值为`71.9868802959 us`。31.44793 us和二级最大穿透51.07mm只属于100 amu历史COMSOL
模型，不得用于524 amu验收。

### 阶段 E：真实丝网局部单元

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

## 混合质荷比候选

`simion/workbench/analyze_ideal_field_log.ps1`在逐粒子CSV中保留ION表的`MassAmu`和`ChargeState`，
支持一次Fly后按物种拆分，不再只能分析单一524 amu粒子。宽质量候选入口
`tests/cross_solver/run_mass_spectrum_candidate.ps1`把五份共享初始条件的ION表合并为一个混合粒子表，
正式Program、四PA优先级和quality=8均保持不变。只有COMSOL五个分批结果也成功并通过统一分析、
manifest复核后，这次SIMION混合Fly才构成完整跨求解器候选；不得单独提升或覆盖524 amu正式包。

首次混合Fly仍沿用524 Da正式Program的`diagnostic_max_tof_us=90`，因此10/100/500 Da共120粒子
全部到达，而1000/2000 Da共80粒子在90 us被主动timeout；这不是传输损失。宽质量入口现按
`90*sqrt(max_mass/524)`向上取整生成运行时GUI adjustable，本次为176 us。复用五份已通过COMSOL
报告后重跑SIMION，200/200均穿过检测面并位于40 mm有效半径内，最大落点半径`8.0922 mm`；旧
90 us失败日志保留为`simion_mixed_timeout90.failed.log`。入口支持`-Resume`；逐物种CSV和报告完整时
跳过该COMSOL物种，不完整时保全旧失败报告并只重跑该物种，最终仍重新生成并复核manifest。

2026-07-19以同一500 Da ION前缀完成N=100/300/1000/5000时间标定，每档独立Fly三次且日志分析不计入
墙钟。四档中位数分别为`4.056/10.077/31.297/151.444 s`，十二个样本的工程拟合为
`T=1.088+0.030113*N s`，`R^2=0.999920`。SIMION近似线性且绝对成本较低，N=5000仍约151 s，
所以跨求解器批次不应为了节省SIMION时间降低粒子数；粒子数选择由COMSOL成本和统计目标决定。

五质量各N=1000候选随后以一次5000粒子混合Fly完成，`diagnostic_max_tof_us=176`，总计5000/5000
到达，最大落点半径`13.4690 mm`，未触发timeout。分析图不再用10–2000 Da公共横轴画五根尖线，
而是在五个局部质量偏差面板中用公共分箱叠加两端峰形，第六面板显示质心TOF差随m/z变化。
