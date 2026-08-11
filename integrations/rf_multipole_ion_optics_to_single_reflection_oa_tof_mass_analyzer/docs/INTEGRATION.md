# RF多极杆离子光学到单次反射oaTOF集成

本文件是四、六、八极杆到单次反射oaTOF连接的当前状态权威。项目自身资格分别由各项目
`docs/PROJECT.md`维护；完整运行表、失败链和被取代方案只查日期化history。

## 当前身份

- integration ID：`rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer`。
- 唯一公开执行入口：
  [`workflows/family_source_closure/execute.ps1`](../workflows/family_source_closure/execute.ps1)。
- 调用者只选择campaign和`ExperimentId`；源项目、求解器、工况、母样本、resolved design和数值设置
  必须从冻结的source run派生，不能在CLI重复声明。
- 四、六、八极杆分别选择模式中性的direct-mating connection profile；连接器、位姿、公共电位、
  时钟和场责任区由resolved connection决定。
- 当前结果均为功能或诊断证据，不授予连续相空间、数值收敛、优化、Candidate或整机Formal资格。

## 机器权威

| 职责 | 入口 |
|---|---|
| 连接拓扑与端口 | [`connection_profiles.json`](../config/connection_profiles.json) |
| 声明式实验 | [`experiment_campaign.json`](../config/experiment_campaign.json) |
| 执行适配 | [`execution_adapter_profiles.json`](../config/execution_adapter_profiles.json) |
| 单流程布局 | [`single_flight_layout_profiles.json`](../config/single_flight_layout_profiles.json) |
| runtime bindings | [`config/*_runtime_binding.json`](../config/) |
| 依赖与实现身份 | [`family_runtime_dependencies.json`](../config/family_runtime_dependencies.json)、[`family_runtime_implementation.json`](../config/family_runtime_implementation.json) |
| oaTOF可调变量 | [oaTOF `design_variables.json`](../../../projects/single_reflection_oa_tof_mass_analyzer/config/design_variables.json) |
| oaTOF优化包络 | [oaTOF `optimization_envelope.json`](../../../projects/single_reflection_oa_tof_mass_analyzer/config/optimization_envelope.json) |

repository-text SHA由`runtime/refresh_family_repository_bindings.py`单向刷新；campaign source SHA由
`workflows/family_source_closure/refresh_campaign_source_bindings.py`冻结。已发布终态manifest的
campaign不得改写。

单次Fly的前端网格、oaTOF数值profile和可选空间窗口只由
[`simion_single_flight.json`](../config/simion_single_flight.json)定义；campaign只引用profile ID，不复制
网格或窗口参数。`continuous_injection_full_population`表示从多极杆入口释放声明母样本的全部粒子，
不得先按脉冲可提取性或检测结果筛选；`pulse_eligible_conditional`只用于具备选择receipt的条件诊断。
空间窗口是在声明checkpoint上的detector-blind分组统计，不修改轨迹，也不是因果反事实。

## 两种执行策略

campaign的`execution_strategy`显式选择下列一种策略：

| 策略 | 物理流程 | 适用边界 |
|---|---|---|
| `staged_three_stage` | COMSOL接口运输 → COMSOL脉冲捕获 → SIMION分析器 | 既有分阶段campaign；未声明策略时的兼容默认 |
| `simion_single_flight` | 同一次SIMION Fly连续完成多极杆、连接器、脉冲加速、无场漂移、反射和检测 | 当前八极杆整体前端及参数化布局候选 |

`simion_single_flight`中的`multipole_handoff`、`pre_pulse_state`和
`local_accelerator_exit`只是同一轨迹的checkpoint，不是导出、重新释放、时间清零或第二次Fly。
任何文档或分析把它们解释为三段重启，均与当前流程冲突。

## 单流程PA与屏蔽

当前单流程仍使用四个Workbench实例：

| 槽位 | PA角色 | 说明 |
|---:|---|---|
| 1 | flight tube | 接地无场管 |
| 2 | reflectron | 双级反射器 |
| 3 | combined frontend | 多极杆、整体屏蔽、连接器和oaTOF加速器组成一个PA |
| 4 | detector | GUI可见数值终止层 |

多极杆和加速器不是两个相互重启的PA。圆形多极杆罩、接地圆套筒、带孔法兰和加速器罩形成连续
`0 V`屏蔽；任一profile声明非零屏蔽都会在GEM/Program生成前失败关闭。

combined frontend当前电极映射为：

| 电极号 | 角色 |
|---:|---|
| 1–8 | 八极杆杆组 |
| 9 | 连续接地屏蔽罩与连接器 |
| 10–17 | oaTOF加速器功能电极 |
| 18 | 入口参考套筒 |
| 19 | 入口板 |

每个run生成的`single_flight_frontend_contract.json`是编号和几何的机器权威；本文只提供识别性摘要。
加速器电极不能再按“10–17且没有18/19”解释。

## 参数合同与自动重构

单流程布局profile的`design_overrides`只能引用oaTOF变量目录中登记的变量：

- `continuous`变量在目录安全范围和适用优化包络内可直接给值；
- `integer`变量是离散设计量，必须为合法整数并触发相应拓扑重建；
- 理论派生字段不得直接覆盖，由时间聚焦和加速器—反射器耦合编译器重算；
- 拓扑变化必须使用专用编译路径，不能伪装成连续标量；
- 网格、trajectory quality和时间步属于数值合同，不反写物理设计。
- `single_flight_pulse_offset_rf_periods`是实验行自由变量，默认`0`、范围`[-0.5,0.5]`；它在状态驱动
  基准时刻上加偏移并记录质心误差，不重建PA，也不能直接覆盖派生的绝对脉冲时刻。

当前单流程编译顺序为：

`layout profile + design overrides → candidate baseline → theory closure → resolved geometry → PA rebuild plan`

理论闭合自动更新所影响的加速器、无场区、反射器、检测器对称位置、能量包络和电压。运行时只在
run-local目录重建`frontend_pa`、`flight_tube_pa`或`reflectron_pa`中实际变化的PA，并把resolved
值绑定到Lua；不修改oaTOF Formal资产，也不允许SIMION实现反向改写参数。

范围校验只证明可编译，不证明候选可行或更优。每个候选仍须重新完成PA贯通、孔外接地guard、
电极映射、真实Fly和数值敏感性检查。

## 当前连续单流程结论

当前1.5 mm入口参考套筒、10 eV目标注入的N=1000八极杆连续基准为
`1000→968→950→948→948`，总检测传输94.8%；`pre_pulse_state`能量为
`10.01783±0.05134 eV`。handoff正交加速方向角度σ为`1.81390°`，脉冲前σz为
`0.54583 mm`，因此已闭合的是高传输和目标能量，不是角度或z方向展宽。

首个参数化候选把理论源z全宽从1.0 mm改为2.2 mm。编译器自动扩大能量包络并重算反射器二级长度和
背板电压，run-local只重建受影响PA。真实八极杆输入未改变，传输仍为948/1000，分辨率变化−0.30%，
没有性能收益；该结果只证明参数合同与自动重构链工作。完整数值、run索引和声明边界见
[2026-08-10候选记录](../../../docs/history/20260810__oatof-source-z22-auto-rebuild.md)。

绝对RF时钟稳态源的5×200诊断为1000→1000→1000→996。初次聚合把oaTOF基础Program输出的原生
`ion_time_of_flight`误标成绝对探测时刻，得到的`R=49.54`及基于该时刻的x条件筛选结论均已失效；
逐粒子补回`source_release`仪器时刻后，同一真实轨迹为直接FWHM `1.97584 ns`、`R=19417.37`。
修正后能散与单独角度的线性解释量均约1%或更低，位置三分量为6.63%；完整`xyz-vxyz`相空间为
22.67%。随后以同一996粒子共同队列完成N=1000、每臂5批并行的SIMION受控重放
`20260810_221000__sim__simion__rf-oatof-resolution-screen__n1000`。保持当前中心、只把z宽度匹配到
理想源形状时，FWHM降低28.93%、R提高40.70%至27223.97；单能化变化−0.07%，收窄x或x-y使R
分别降低3.83%和3.97%，去除z-vz协方差使R降低42.11%，完全压缩z-vz线性残差只提高4.51%且变为
双峰。延迟1/8或1/4 RF周期同时降低R和传输。这个结论只在固定combined frontend场内成立：z宽度是
源相空间中最强单变量，但已有z-vz相关性总体有利，不能直接消除。

同一996粒子的Formal场桥接曾显示：Formal形状源和Formal反射器在0.20 mm combined frontend中只有
`R=12014.18`，切换冻结Formal accelerator PA后为`R=115493.38`。新的整体PA各向异性序列已经解释
这项9.61倍差异：保持同一冻结源和Formal反射器，`x=y=0.20,z=0.10 mm`得到`R=123454.40`，但配对
TOF去均值RMS仍为`0.3065 ns`；`x=y=0.20,z=0.05 mm`得到`R=118503.71`，相对Formal PA的配对
RMS降到`0.00590 ns`，TOF σ为`0.1082/0.1098 ns`。因此先前主要是正交加速方向离散不足，不是
加速器理论几何本身失效；0.05 mm是收敛诊断点，不自动成为生产默认。

全局各向异性网格也会细化多极杆横截面的z方向。完整稳态束在z=0.10/0.05 mm时分别为
`977/1000,R=23901.04`和`980/1000,R=17614.85`；共同粒子的脉冲前状态相对0.20 mm基准已有
`z RMS=0.178 mm`、`vz RMS=0.0416 mm/us`变化，所以这些完整结果是多极杆场与加速器场的混合
敏感性，不能单独归因给加速器。0.05 mm下重放冻结真实源仍只有`R=17364.33`；主瓶颈随之转移为
真实`z-vz`相空间与理论时间聚焦不匹配。

半径100 mm、2 mm薄环、8/15环的新oaTOF候选接入受治理八极杆稳态源后，旧N=1000单次Fly为
`R=23834.40`；它与理想源`R=107739.80`使用了不同反射器轴向网格，只能作跨工况诊断。新的全量
连续注入campaign固定反射器轴向0.10 mm、径向1.0 mm，并从多极杆入口释放全部2000粒子，不再先取
脉冲可提取子集。真实过程为`2000→1919→1873→1706→1617`，脉冲瞬间1623粒子位于stage1接受区，
其中1617命中；因此整体效率为80.85%，而条件效率99.63%。单峰`R=23390.46`。1623粒子条件运行只
复现可提取队列的峰形，不能替代该整机分母。机器入口为
[`octupole_oatof_r100_t2_rings8_15_z010_n2000_campaign.json`](../config/diagnostics/octupole_oatof_r100_t2_rings8_15_z010_n2000_campaign.json)，
代表证据为`20260811_170000__sim__simion__rf-oatof-single-flight-gap0__n2000__r02`。

同一2000母样本的前1000行随后作为标准配对子样本，仍从多极杆入口自然释放，得到
`1000→957→938→852→806`、脉冲可提取811、单峰`R=22562.21`。同一PA和同一0.10/1.0 mm oaTOF
网格上的冻结状态重放为`R=22713.50`，相对连续基准的配对TOF RMS仅0.0198 ns。把同一806粒子改成
当前1×1×1 mm³位置分布、保持观测能散但令速度沿多极杆轴且脉冲前`vz=0`后，806/806仍命中，却变为
双峰`R=14183.86`，比重放下降37.55%。因此严格同网格结果不支持“独立均匀位置+零z角度就是本布局
理想源”；真实束在`pre_pulse_state`的`z-vz`相关系数0.886，现阶段总体参与而不是单纯破坏时间聚焦。
这里的`vz`是加速脉冲前由多极杆、连接区和边缘场带入的正交加速方向速度，不是提取后的速度。后续源
优化必须匹配`z-vz`相空间椭圆、脉冲时刻与实际加速场，不能只压窄z或把vz置零。证据为
`20260811_190000__sim__simion__same-grid-source-attribution__n806__r02`；该结果是受控反事实诊断，不是
Formal或数值收敛结论。

0.05 mm场上的N=1000理想条件矩阵显示：只压缩z宽度为`R=23578.6`，只压缩z-vz线性残差为
`R=20004.2`，单能化和横向位置变化均小于3%，直接去相关反而降低18%。把z σ从0.490 mm压到
0.288 mm、保留观测线性斜率并把vz σ降到65.3 m/s时，996/996、单峰`R=49804.49`；这是发射度/
匹配目标，不是可直接指定的正式源。脉冲提前1/8 RF周期只把完整束提高到`R=17855.37`，且vz σ
不变，故停止脉冲相位盲扫。以上仍为`CONTROLLED_COUNTERFACTUAL_DIAGNOSTIC_ONLY`。

加速器自由量现可由实验行的`single_flight_design_overrides`声明；省略时继承layout/base resolved
默认值，聚焦面、平移、反射器和罩体等派生量仍禁止直接指定。N=1000单飞在PA准备完成后自动拆成
5批并合并全局粒子编号；默认PA最多5批并行，细网格由数值profile限制同时批数。两组4.0 mm
`d1`三维诊断进一步排除了实体容纳不足：长焦点漂移的
1700 V行虽有991/1000命中，但成为双峰且R降至8999.75；保持160 V/mm和0.344 mm紧凑焦点漂移的
1600 V行有995/1000命中、单峰R=19176.67，仍比3.0 mm基准低1.24%。因此当前2.2 mm稳态束已基本
位于stage1实体范围内，不能以增大d1替代三维时间接受优化。候选PA必须复制formal资产后在run-local
重建；不得用可写硬链接跨越formal边界。

旧0.20/0.15/0.125 mm各向同性序列和分段均匀理想场不是有效oracle；它们未沿0.05 mm Formal PA的
关键z方向收敛。旧运行表只在
[网格及理想场记录](../../../docs/history/20260810__oatof-frontend-grid-and-ideal-field.md)保留，不再用于
否定网格影响。

为避免全局各向异性网格同时改变多极杆横向场，单次Fly现支持边界耦合的局部加速器PA：完整多极杆、
连接器和加速器继续由0.20 mm各向同性粗PA覆盖，局部PA通过20个逐电极基函数复制六面Dirichlet边界，
并在出口人工边界前用重叠保护区回退粗PA。方法合同只在
[跨项目连接架构](../../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md#simion粗全局pa与局部细pa耦合)维护。
N=100同网格对照保持`100→75→66→56→56`，探测TOF配对RMS为0.0160 ns、最大差0.0825 ns，证明
PA分解和保护区未造成可观测的系统偏移。随后只把局部加速器z网格改为0.05 mm，census仍完全相同，
相对同网格对照的探测TOF平均变化−1.806 ns、去均值配对RMS为2.058 ns；该差异不再混入多极杆网格
变化。冷构建真实墙钟535.8 s，缓存3.53 GiB，Fly加载峰值工作集约7.73 GiB；N=100结果只授予功能
和隔离归因，不构成分辨率或收敛声明。机器入口为
[`octupole_accelerator_overlay_identity_n100_campaign.json`](../config/diagnostics/octupole_accelerator_overlay_identity_n100_campaign.json)与
[`octupole_accelerator_overlay_z005_n100_campaign.json`](../config/diagnostics/octupole_accelerator_overlay_z005_n100_campaign.json)。

目标能量只能在连续链`pre_pulse_state`、且粒子位于repeller与grid1之间时验证。
`terminal`或`multipole_handoff`能量只作接口诊断。

## 证据路由

- 当前10 eV、1.5 mm套筒N=1000基准：
  [history](../../../docs/history/20260805__octupole-terminal-15mm-sleeve-single-flight-n1000.md)
- 入口套筒与加速器内目标能量修正：
  [history](../../../docs/history/20260805__octupole-15mm-sleeve-accelerator-energy.md)
- 早期10 eV布局诊断：
  [history](../../../docs/history/20260805__octupole-10ev-single-flight.md)
- 开孔离散、孔径选择和受控反事实等旧完整过程：以对应run manifest及根
  [history目录](../../../docs/history/)为准；current文档不复制多轮运行表。

## 开放任务

1. 保持多极杆+加速器整体物理装配和单次Fly；局部PA已闭合同网格身份和N=100的0.05 mm功能链，
   进入任何性能或生产判断前仍须按粒子数合同完成N=1000配对统计，并确认局部场结果与冻结Formal
   加速器oracle的一致性。不得把N=100功能结果直接当成生产候选。
2. 若需要跨求解器结论，另行授权同几何、同源、同绝对时钟和同checkpoint的COMSOL连续前端。
3. 保持d1=3.0 mm基准，先以冻结真实束构造保持/扫描`z-vz`相空间椭圆的源匹配反事实，再筛选
   repeller/grid1场比并用完整连续注入母样本确认；不得把`vz=0`或独立1 mm立方源预设为理想答案。
   理论编译器必须自动重算聚焦面和反射器，不直接指定派生量。通过标准为N=1000、传输≥95%、单峰且
   `R≥30000`，不能以删除尾部粒子换取窄峰。
4. 新的2 mm、3 mm或其他源宽必须各自形成受治理layout profile并重建受影响PA；不能从2.2 mm
   无收益结果直接外推。

## 静态门禁

[`verify_integration.ps1`](../verify_integration.ps1)只验证连接、端口、profile、source/design冻结、
repository identity和失败关闭逻辑，不运行COMSOL、SIMION、MATLAB或CAD，也不替代物理资格。
