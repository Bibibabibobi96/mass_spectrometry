# oa-TOF SIMION 实施与验证

本文件只记录SIMION实现、GUI操作和独立验证。统一几何、粒子、FWHM定义、正式状态和下一步
由[`PROJECT.md`](PROJECT.md)定义。历史过程由项目 README 路由，日常任务不从本文件跳转读取。
发送给同事的独立参数交接单见[`SIMION_REPRODUCTION_PARAMETERS.md`](SIMION_REPRODUCTION_PARAMETERS.md)。

## 当前入口与状态

- 正式文本入口：`../simion/workbench/formal/oatof_ideal_grounded.lua/.fly2`。
- 正式GUI/交付目录：`artifacts/projects/oa_tof/formal/simion/`；IOB、CON、
  同名Program/Fly2、四套完整PA家族和固定ION均集中于此。
- 迁移前的收敛参考、构建源和待审计历史已冻结在本项目archive的`legacy-layout/models/simion/`；
  正式IOB不引用archive中的PA。
- 当前标准：524 amu、+1、`5±0.4 eV`；GUI检查档N=100、正式统计档N=1000。
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

### 2026-07-23 源码构建与N=100跟踪回归

长期入口为`tests/simion/run_n100_source_build_and_track.ps1`。它先冻结baseline、resolved合同、
Program/Fly2和四个构建器源码，再从源码建立独立SIMION交付并执行N=100跟踪。运行
`20260723_143116__test__simion__oatof-source-build-track__n100`确认：

- reflectron、flight-tube和detector三个构建器都拒绝缺少必需参数的调用；
- 构建后的SHA清单覆盖53个交付文件，临时`*.source.gem`和`*.processed.gem`残留为0；
- N=100为100/100 detector crossing及100/100 hit，平均TOF为`71.353597 us`；
- 失败注入时根配置、摘要和manifest三件套仍完整收口并通过manifest复核。

该入口只证明源码可构建、运行合同和失败收尾可工作；它不修改Formal，也不声明网格收敛或新的正式
性能。

任意设计候选先由`analysis/prepare_candidate_consumers.py`从同一
`candidate_resolved_geometry.json`生成隔离的`oatof_resolved.lua`、Program和Fly2；正式文本保持不变。
零改动回归要求三份生成文本与正式版本逐字一致。该步骤尚未Refine PA、建立IOB或Fly，因此只标记
`text_generated_pa_iob_not_built`，不能作为SIMION候选运行通过的证据。

`build_formal_delivery.ps1`的默认行为仍从正式合同构建run内候选交付；当显式提供`ContractPath`时，
必须同时提供`CandidateBaselinePath`和`CandidateTextDir`，构建器禁止调用正式文本同步，而是从隔离
候选输入建立PA/IOB。两种模式都只允许输出到`runs/`，晋升继续是独立门禁。
集成runner额外传入`DeferRunFinalization`：构建器只在`simion/`写阶段摘要，不得提前覆盖run根
`summary.json/run_manifest.json`；根三件套由跨软件生命周期后端在所有阶段结束后唯一收口。

稳定实现入口以`config/simion_stable_entry.json`冻结：0.05mm是正式可移植交付，0.025mm仅作轴向
网格收敛参考。该清单记录外部资产路径、大小和SHA-256，不重复维护物理参数；物理
参数仍以`config/baseline.json`为唯一来源。每次移动、重建或打包SIMION资产后运行：

```powershell
.\projects\oa_tof\tests\simion\verify_stable_entry.ps1
```

脚本验证当前正式包SHA256清单覆盖53个包内文件，再实际加载IOB并检查4实例、静态优先级与
T.Qual=8。任一项改变都必须重新验证并有意识地更新清单，禁止只替换PA或手工改IOB后
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
该样本的粒子传递。该数值属于耦合baseline晋升前回归，不是当前性能机器记录；当前正式比较只认
`config/formal_validation.json`中的2026-07-20同源N=1000结果。

2026-07-20耦合纵向baseline的正式包通过SHA、四实例和quality=8真实加载门禁。同源N=1000为
1000/1000命中，平均TOF`71.3535844772 us`，统一直接KDE质量FWHM为`0.010715355226 Da`、
`R=48901.79`。新理论预测均值`71.3533528284 us`，模拟减预测为`+0.2316 ns`，绝对RMSE
`0.6186 ns`；逐粒子相关较弱，不能把亚纳秒残差解释成解析式已经复现SIMION离散场细节。当前IOB、
Program、交付manifest和结果SHA均由`config/simion_stable_entry.json`及
`config/formal_validation.json`冻结。

2026-07-18旧Formal IOB、PA和同名Program的N=1000重算同样1000/1000命中，平均TOF
`71.9910151844 us`，质量FWHM`0.0117728715881 Da`、`R=44509.11`；现仅作为老baseline比较证据，
旧资产位于2026-07-20晋升前Formal归档。

正式场诊断表明，SIMION释放区轴向Ez平均比COMSOL高`0.8396%`，而反射器内部相对RMS差仅
`0.000528%`。代表轨迹显示该小差异在出射漂移中累计、在反射器中反向补偿，最终只留下数ns
TOF差。SIMION加速器离轴Ex/Ey比COMSOL平滑且较弱；在COMSOL完成加速器域网格收敛前，禁止
仅凭该差异修改SIMION正式PA几何或电压。场采样入口位于`tests/simion/export_axis_field_profiles.lua`
和`export_accelerator_vector_field_samples.lua`。

### 可组合Ez替换诊断

本节只记录SIMION实现与独立验证；通用方法见根
[`VALIDATION_METHODS.md`](../../../docs/VALIDATION_METHODS.md#受控理想化场替换与原因隔离)，跨求解器
能力与统一结论见[`PROJECT.md`](PROJECT.md#场方向归因实例)。

正式Program源码保留旧`ideal_accel_enable/ideal_refl_stage1_enable/ideal_refl_stage2_enable`整区域
兼容开关，并新增`ideal_accel_ez_enable`、`ideal_drift_ez_enable`、
`ideal_refl_stage1_ez_enable`和`ideal_refl_stage2_ez_enable`。新开关只覆盖对应全局轴向场在PA局部
坐标中的导数，不清零其他局部分量；多个区域可以同时启用。诊断运行复制正式自包含包到独立运行
目录并替换同名Program，不修改正式资产或`simion_stable_entry.json`。

长期入口为`tests/simion/run_field_idealization_sweep.ps1`，公共案例配置为
`config/diagnostics/field_idealization_feasibility.json`。选择器沿用`ideal:<region>.ez[+...]`；若请求
Ex/Ey，入口明确拒绝，因为当前flight-tube/reflectron采用旋转二维圆柱PA，不能独立表示全局横向
分量。N=100的real、all.ez、accel.ez和accel.ez+stage2.ez四例均100/100到达并通过17项输出manifest；
首轮相对WorkingDirectory导致的`chdir error`发生在Program加载前，已作为编排失败单独归档，修复为
启动前解析绝对输出路径。该测试只证明工具和区域组合可行，不要求与COMSOL干预数值精确一致。

入口现先按`simion_stable_entry.json`验证正式包完整SHA、IOB四实例和quality=8，再建立或复用诊断
包。`-RuntimePackage`只在其IOB、原正式manifest/SHA和诊断Program哈希全部匹配时允许复用，避免每次
重复复制约1.3 GB PA家族；复用包仍不改变正式artifact。两案例N=100小测试使用既有已验证诊断包，
real与accel+stage2 Ez均100/100到达并通过13项输出manifest。选择器长期测试确认当前PA不支持的Ex/Ey
请求会在创建运行目录和启动SIMION前被拒绝。

### 2026-07-17 严格聚焦几何提升

候选构建器按`d1=3.0 mm,d2=16.8 mm`生成独立PA家族，并通过四实例IOB、同名Program、解析焦点、
同源粒子和CAD同步门禁后提升为正式几何。后续源码构建链重建和检测终止升级均通过N=1000数值
等价门禁；当前正式目录已由`simion_stable_entry.json`冻结，早期scratch/candidate不再是运行依赖。

### 透明栅网跳转距离诊断与正式状态

`ideal_grid_epsilon_mm`是理想零厚度栅网的数值跨面距离，不是机械间隙。扫描证明减小该值不会
改变PA场，却能减少人为跳过的栅网邻域场积分。Program现增加
`accelerator_grid_epsilon_mm`和`reflectron_grid_epsilon_mm`两个分组覆盖量。2026-07-17扫描阶段曾以
`0.005 mm`为旧正式对照；随后严格聚焦几何转正时，加速器、反射器分组值及fallback已统一提升为
`0.0001 mm`。当前机器契约、正式Program和同事复现参数表三者一致，旧`0.005 mm`不再是正式默认值。

历史N=100析因显示反射器entgrid/midgrid贡献占主导；N=1000候选仍1000/1000命中，纯SIMION进程
`35.37 s`，旧`0.005 mm`同环境为`38.44 s`，没有明显时间代价。最终转正依据不是单一R更接近，
而是同源N=1000配对TOF/落点改善、GUI重开、正式包重建和CAD同步门禁全部通过。当前正式资产的
直接重算结果由`config/formal_validation.json`冻结；详细扫描过程保留在数值验证history。

固定距离跨越仍会保留对数值电极层和网格相位的实现依赖，但这不影响当前100%传输、N=100/N=1000
合同或既有正式结论。自动识别并越过实际数值电极层只在PROJECT所列条件触发后作为精度增强重启，
不得继续扫描固定距离追平某个R、峰宽或单一跨求解器指标。

## GUI对等原则

本节2026-07-15/16的数值表只保留Program、Data Recording和积分档位的实现证据，属于耦合baseline
晋升前样本，不得覆盖文首及`config/formal_validation.json`的当前正式性能。

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

`trajectory_log_enable`只控制审计输出，不关闭Program，也不改变检测器终止或飞行物理。

## GUI轨迹质量与运行时门禁

正式Program以`adjustable trajectory_quality=8`在加载IOB和每次Fly初始化时写入轨迹质量。
Data Recording文件本身不保存T.Qual，单独的GUI工作簿不能证明正式积分档位。运行时门禁必须实际
加载IOB并读取本次Program报告：

```powershell
.\projects\oa_tof\tests\simion\verify_iob_runtime_contract.ps1 `
  -IobPath <待验收.iob> -ExpectedTrajectoryQuality 8 -ExpectedInstances 4
```

只检查Lua文本或IOB存在不算通过。门禁使用每次唯一的临时报告路径，避免误读上一次残留结果。
已关闭的低质量宽峰、同名Excel覆盖和Program On/Off配对调查从项目README的history清单追溯，
不得把其中任一GUI工作簿作为当前性能基线。

## 实施流程

### 阶段 A：确认安装与可写工作区

安装版本和程序入口只按仓库根[`README.md`](../../../README.md#工具链与执行入口)执行。源码留在项目
`simion/`，生成的PA/IOB只能进入本次artifact run或正式交付目录，不写回安装目录或Git源码树。
`../simion/examples_reference/simion_fast_adjust_demo.gem`仅用于确认GEM处理、Refine、Fast Adjust和
PA0保存链；`simion_nonideal_grid_demo.gem`只用于观察真实细丝grid的网格尺度，二者都不能放大后
冒充oa-TOF正式几何。

### 阶段 B：理想栅网反射镜 PA#

当前几何源为`../simion/reflectron/oatof_reflectron_ideal_10_5.gem`，参数化构建器为
`../simion/reflectron/build_reflectron_variant.lua`；正式交付中的2D cylindrical PA由该链生成，
不是源码目录中的第二份参数权威。

几何包含：接地圆柱屏蔽壳、入口栅网、10个一级环、级间栅网、5个二级环、背板。每个环单独为一个Fast Adjust电极；准确位置/电压见：

- `../config/baseline.json`
- `../config/reflectron_ring_table.csv`
- `../config/simion_stable_entry.json`（正式二进制身份，不重复定义物理参数）

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

加速器当前几何源为`../simion/accelerator/oatof_accelerator_3d.gem`，参数化构建器为
`../simion/accelerator/build_accelerator_variant.lua`，使用3D Cartesian PA。正式几何为孔半宽5mm、环单边宽5mm、
带电电极到接地屏蔽内壁每侧5mm、repeller后表面到后盖前表面5mm、屏蔽壁4mm；
PA物理范围为`38×38×30 mm³`（z=`-10..20mm`）。常态快速网格为
`xy=0.25mm、z=0.05mm`（`153×153×601`）；跨求解器闭合/收敛参考为
`xy=0.25mm、z=0.025mm`（`153×153×1201`）。GEM物理几何只有一份；数值网格参数不得
借诊断变体修改电极尺寸、厚度、轴向位置或绝缘间隙。

包含repeller、grid1、grid2、5个加速器环和接地屏蔽罩。grid1/grid2同样是一网格点厚的透明等势面。

基准电压：repeller=2240 V，grid1=1760 V，grid2=0 V；加速器环电压依据当前COMSOL脚本的线性规则。

当前电极编号与 fast-adjust：1=repeller，2=grid1，3..7=五个加速器环，8=grid2，9=grounded shield；对应电位为2240、1760、1466.666667、1173.333333、880、586.666667、293.333333、0、0 V。物理值仍只从baseline/resolved链派生。

`oatof_accelerator_3d.gem`的9号接地屏蔽默认仍是完整外方框减内方框并另加后封闭；新增的
`interface_port_enable`默认为0。S1隔离候选可由参数化构建器显式传入端口开关、横向宽度、轴向高度和
一级间隙内的局部中心；当前只冻结轴向高度`0.9 mm`，横向宽度仍等待轴心—离轴场均匀性与其他硬约束
取交集。这只提供与COMSOL同语义的负x侧孔能力；横向值未解析时不得启用，也不能只在IOB中把粒子放进
屏蔽内部，或在联合RF/静电场、重新Refine/Fast Adjust、孔边缘场和GUI实例验证前替换Formal PA。
SIMION只消费PROJECT与接口合同冻结的闭合Formal场参考和联合开孔初始扫描点，不在本文复制数值；
不得把该单求解器参考当作跨求解器已验证孔宽。SIMION必须在相同开孔合同下重建PA，并与COMSOL按
同一三个AND场指标和粒子分辨率门禁比较。

网格闭合使用上述参数化构建器。构建器必须先打印尺寸和完整PA家族容量估算，
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
平均静电场强度。扫描时的旧正式`0.005 mm`缓冲在半格相位会使粒子于grid1数值层splat，禁止把它
解释为真实栅网损失；当前正式`0.0001 mm`减少固定跳转误差，但没有证明跨相位自适应。以后若要求
亚ns逐粒子闭合，必须先实现按实际数值电极层自适应的透明跨越并同时验证
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

同名正式Fly2必须在GUI中显示524 amu、+1、N=1000、1×1×1 mm³释放体和`5±0.4 eV`
能量分布。需要与COMSOL严格比较时使用固定归档ION文件，并在结果中注明ION路径。

当前两端统一使用N=100检查档和N=1000正式统计档；命令行统计运行同步传入
`--default-num-particles 1000`。N=100优先复用同源N=1000轨迹的确定性前缀，N=40和N=300退出
新日常运行，N=5000仅用于明确的性能或统计收敛专项。

2026-07-19按新合同重建正式交付候选，并以固定N=1000逐粒子对照更新前正式包；场、TOF、落点和
峰形等价门禁PASS。提升时PA、IOB、Program和ION均字节不变，只更新Fly2、派生合同、交接文档及
SHA/manifest；`config/simion_stable_entry.json`已冻结新的正式身份。

每次重建后的第一轮GUI冒烟只飞固定单粒子，记录：

1. 到达entgrid时刻；
2. 最大反射深度；
3. 返回探测面时刻；
4. 横向位置和速度。

当前正式统计只引用`../config/formal_validation.json`冻结的同源N=1000结果；早期N=100和100 amu
数值只属于晋升前证据，不得用于当前耦合baseline验收。

### 阶段 E：真实丝网局部单元

真实丝网局部单元尚未实现，因此当前不预建`03_grid_cell/`空目录。只有需求冻结真实丝径、节距、
材料和两侧电压后，才在隔离候选中建立高分辨率3D网孔单元，输出透过率、撞丝概率和横向kick查表。

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
跳过该COMSOL物种，不完整时保全旧失败报告并只重跑该物种，最终仍重新生成并复核manifest。仅修改
分析或绘图时必须用`-ReanalyzeOnly`：它验证已有COMSOL/SIMION CSV和命中汇总，完全不启动两端
求解器，只重建分析与manifest。

2026-07-19以同一500 Da ION前缀完成N=100/300/1000/5000时间标定，每档独立Fly三次且日志分析不计入
墙钟。四档中位数分别为`4.056/10.077/31.297/151.444 s`，十二个样本的工程拟合为
`T=1.088+0.030113*N s`，`R^2=0.999920`。SIMION近似线性且绝对成本较低，N=5000仍约151 s，
所以该N=5000结果保留为性能专项证据；日常选择仍只使用统一N=100/1000两档。

五质量各N=1000候选随后以一次5000粒子混合Fly完成，`diagnostic_max_tof_us=176`，总计5000/5000
到达，最大落点半径`13.4690 mm`，未触发timeout。分析图不再用10–2000 Da公共横轴画五根尖线，
而是在五个局部质量偏差面板中用公共分箱叠加两端峰形，第六面板显示质心TOF差随m/z变化。
同一已保存CSV的纯后处理进一步给出五个质量的标准化KDE重叠
`0.81183/0.77942/0.73584/0.71477/0.71268`和KS距离`0.116/0.128/0.168/0.199/0.218`。
这些非参数指标用于表达带肩/尾峰形差异，不用单高斯拟合替代；复算没有重新Fly。
