# SIMION功能复现实施

当前科学状态与资格见[PROJECT](PROJECT.md)。

## 按任务查阅

| 任务 | 入口 |
|---|---|
| 选择生产入口、输入和证据层级 | [执行与验收边界](#执行与验收边界) |
| 修改实体几何或理解厂商支持范围 | [表示与官方支持路径](#表示与官方支持路径) |
| 复用原生场、分批飞行或传入候选配置 | [自动分批与单工作台重放](#自动分批与单工作台重放) |
| 准备独立用户工作台 | [GUI准备](#gui准备与批处理区别) |
| 核查碰撞副本、随机状态及参数绑定 | [HS1生命周期](#hs1运行副本生命周期适配)、[参数审计](#hs1参数绑定与原生内部值审计) |
| 解释坐标、原生诊断或引出受力 | [世界坐标](#项目世界坐标与当前验收状态)、[几何与诊断](#当前几何时序与诊断)、[受力审计](#被动引出受力与碰撞审计) |

## 表示与官方支持路径

2026-10-20补充：成形提取件及连续辅助片用原生GEM `half_space(x,y,z,nx,ny,nz)`交集表示凸体，
顶点为唯一CSG几何输入，SciPy ConvexHull只在准备/绘图时派生支持平面，不在逐离子回调重建。
采用[官方GEM说明](https://simion.com/info/gem_geometry_file.html#half-space)的法向外侧约定，
该功能标记从8.2EA-20170324提供；本机8.2.0.11已对四组候选完成真实GEM／Refine与N100飞行。在线文档标注2026，
不据此使用新版本独有接口。原有Fast Adjust、HS1、RF和飞行积分入口不变。
`analysis/electrode_contours.py`编译显式`baseline.electrode_contours`，
`analysis/convex_geometry.py`提供凸体边界与截面，默认几何图按真实多边形减孔绘制，不以AABB替代金属。
几何改变必须重新求解全部15个响应，不能复用旧几何PA。
跨组诊断通过现有functional入口`compare-geometry-study --run <analysis-run>`消费冻结三组或四组合同，
不启动求解器；物理判据失败但具有完整真实终态的组仍保留并参与比较。
受力诊断用E5/E14真实CSG的轴向包络定义分区；成形斜面不能再按单个box读取，也不能把包络平面当金属碰撞面。
历史已封存运行若缺该派生诊断，比较入口核验原始step/impulse记录后在新的分析run中补齐，
原manifest状态及原始飞行均保持，后续新运行仍沿默认自动输出。`export_force_budget`的显式
`output_directory`仅转移派生产物owner，不改变源、积分或统计定义。

目标版本为本机SIMION 2020。唯一生产workflow为简化实体电极几何→GEM/PA→原生Laplace单位响应求解→
按实际RF、DC与脉冲电压组合电场→官方HS1碰撞与同一次连续Fly。实体电极、透镜、辅助DC阶梯和引出狭缝
来自同一baseline。原生电压只消费`config/native_operating_point.json`，RF/时序沿既有baseline冻结。
动态场复用官方Fast Adjust及单位响应线性叠加支持机制，不用理想解析梯度覆盖生产电极场。

前一解析场workflow未形成运行证据，已删除无生产消费者的解析场及其专用测试；旧curvature/offset仅在历史解释中保留。
不得将历史解析场输出或普通GUI静态电势显示混为原生动态场证据。旧0.2 mm场族的15组原生响应Refine完成（15.47 s），当前0.1 mm场族已求解；旧场不自动继承资格，当前恢复与结果边界见PROJECT。
RF波形复用`common/multipole/simion_rf_drive.lua`，所有阶段使用唯一绝对instrument time。
LP浮动屏蔽件电极14平时与LP common-mode同步，引出脉冲时消费原生电压配置中的相对偏置；
当前跟随Pull的−900 V修正及条件对照见PROJECT。HP屏蔽件电极15与HP common-mode同步；
屏蔽件与接地外边界的关系由原生几何统一派生，避免4 kV抬升把离子云暴露于未经声明的近地泄漏场。
屏蔽件是简化功能几何，不是实际商业CAD。
单位响应的尺寸、原点、电极映射、网格、Refine误差与源码身份必须冻结；几何壁碰撞和状态事件由实际积分记录。

公共离子初态和receipt来自`common/ion_release/release.py`，FLY2序列化复用
`common/simion/particle_source.py`。单槽IOB从公共干净种子派生，运行包装复用公共容量生命周期与主机租约。
源、场、时钟、数值、程序和HS1输入必须冻结至run-local并进入manifest。

## 官方资料查证

查阅日期：2026-10-15。在线补充文档目前标注SIMION 2026，实际调用以本机2020示例和接口为准。

| 资料 | 支持与采用范围 |
|---|---|
| [Collision Model HS1](https://simion.com/info/collision_model_hs1.html) | 官方硬球、弹性、Maxwell气体模型，包含冷却与反向加热；不含碎裂、反应或气体反馈 |
| [GEM Geometry File](https://simion.com/info/gem_geometry_file.html) | 官方CSG实体电极与GEM→PA路线；在线页面为2026，采用本机2020支持语法 |
| [simion.pas API](https://simion.com/info/lua_simion.pas.html) | 官方PA创建、Refine与fast_adjust接口，8.1及以后支持；作为原生单位响应路线依据 |
| [Refine](https://simion.com/info/refine.html) | 官方原生电势求解与Fast Adjust响应机制；不据在线新版本特性推断本机均支持 |
| [Fast Adjust FAQ](https://mail.simion.com/info/faq.html) | 官方说明动态电极场可在RF/脉冲飞行中按响应叠加；回调不会自动更新完整PA0显示 |
| [User Programming](https://simion.com/info/user_programming.html#efield-adjust) | 官方用户程序入口；该网页当前正文未提供完整efield_adjust细节，不能单凭页面锚点证明调用语义 |
| `C:/Program Files/SIMION-2020/examples/collision_hs1/README.html` | 已读取，明确示例空PA、低压适用性及test2可按空间变化压力/温度/气流 |
| `C:/Program Files/SIMION-2020/examples/collision_hs1/collision_hs1.lua` | 已读取头部和参数：自动MFP=-1、每MFP默认20步、seed约定、截面示例；正式执行前冻结实际消费完整源码身份 |
| [装置论文DOI](https://pubs.acs.org/doi/10.1021/jasms.3c00311) | 公开装置结构依据；该次查阅在线打开失败，不把访问失败写成论文不存在 |

HS1示例的2.27e-18 m²用于He与约200 amu离子示例，不是N2与524 amu的测量。
`seed=42`定义实际PRNG seed；本机HS1的`_random_seed=n`使用n−1，因此应向该参数传43并记录映射。
数值合同声明自动平均自由程及每MFP步数；碰撞步长与RF步长同时约束实际积分。

本项目采用基于官方求场接口和官方碰撞算法的实体电极模型，不是供应商验证过的Astral装置模型。

## 被动引出受力与碰撞审计

新准备的resolved输入声明`extraction_force_audit`并冻结
[`extraction_force_audit.lua`](../simion/extraction_force_audit.lua)；它在实际primary quench后，
围绕既有HS1调用记录同时间、同位置的pre/post速度。相邻步的上一post-HS1至当前pre-HS1速度差
是实际数值传播增量，当前post减pre是实际碰撞跳变。记录不改粒子状态、积分步长或随机流；
初始化只查询全部15个单位响应，使首正式批资源观测包含这些原生场的实际载入。
历史GUI复验仍按其冻结resolved合同选择依赖，不向未声明审计的旧包注入新模块。

2026-10-19重新核对的官方支持路径如下；在线资料标注2026，生产适用性同时依据本机2020示例
及本项目已有原生场查询，不推断新版本独有能力在2020可用。

| 资料 | 支持的范围与限制 |
|---|---|
| [Field I/O](https://simion.com/info/field_io.html)、[simion.pas](https://simion.com/info/lua_simion.pas.html) | 官方`field_vc`、`potential_vc`读取原生PA响应；显式电压表和单位响应线性叠加沿已有查询路径使用 |
| [Calculation Time](https://simion.com/info/calculation_time.html)、[加速度变量说明](https://simion.com/info/asms_short_course.html) | 调整回调每步可能调用多次，`ion_ax_mm`等是加速度；未提供可直接据回调次数推导积分权重的合同 |
| `C:/Program Files/SIMION-2020/examples/field_dump/fielddumplib.lua`、`examples/drag/drag.lua`、`examples/collision_sds/README.html` | 本机官方场导出、加速度变量与回调用法；不把供应商示例称为逐电极冲量分析算法 |

项目分析采用实际段端点的三次Hermite路径，对官方单位响应场作5节点复合Simpson求积，并保留
3节点粗结果之差。这是基于官方场查询API的项目后处理算法，**不是官方推荐算法或SIMION实际积分权重的精确重放**。
primary/side quench及pulse边界显式分段；段末恰逢电压不连续时，仅电压求值使用相邻binary64左极限，
不修改粒子时间或位置。每点同时直接查询总电压场并核对单位响应重构；CSV保留加权场时间积分、
未加权单位响应积分及最大重构差。q/m、单位换算和速度／能量预算由Python公共物理权威计算，Lua不维护第二份常数。

两份原始表为`simion/extraction_steps.csv`和`simion/extraction_impulses.csv`，公共分批合并只重映射
首列粒子ID，校验严格header和worker所属ID，并保存原始逐批压缩证据。
第一行是实际首审计回调的零时长anchor，保留该时刻碰撞跳变；actual末步可能晚于线性插值的z=0出口事件，
完整原始步预算与出口面统计分别说明作用域，不强行配成同一状态。
电场分量和、实际速度变化、碰撞跳变及细粗求积差共同进入闭合检查；未分配残差保留，不按比例塞给电极或碰撞。
方差预算保留起始状态、各电极、碰撞和残差间的协方差，不能将各分量方差直接相加或称为原因百分比。

Pull与LP shield的狭缝是实体cutout，狭缝几何本身不是独立单位响应电极。
`native_geometry.shield_extraction_slit_width_mm`单独控制E14屏蔽开口，默认仍等于原0.8 mm；
`geometry.extraction_slit_width_mm`继续控制文献种子的E5 Pull开口。
独立屏蔽宽度属于功能模型补全与受控修正假设，来源由[geometry_sources](../config/geometry_sources.json)分类，
不能称为厂家尺寸；任何改变仍需新GEM、Refine和真实飞行验证。

## 执行与验收边界

生产入口为`simion/run_functional.ps1`，准备与分析由`analysis/functional.py`承担；
`verify_project.ps1`执行轻量unittest。从仓库根使用项目入口，先验证输入和计划，再启动真实SIMION。
不得通过旧oaTOF或多极杆入口偷偷覆盖科学参数。终态发布run_config、summary和manifest，
保留canonical粒子事件、必要日志与轻量图。

项目专用[执行合同](../config/execution_profiles.json)的`native_functional`绑定
`native_electrode_functional`、唯一runner及五份相对输入路径，不复制物理标量。该合同使用项目专用role，
由项目编译器校验；不冒充公共通用execution profile格式。
保留原生电极场与工作台供GUI审查的运行使用`solver_review`；实际保留合同随运行冻结。
N100和独立GUI准备的字节承诺分别消费本次冻结profile的`committed_new_bytes`与
`gui_preparation_committed_new_bytes`，实际承诺与准入结果写入run；不将旧尺寸场族的体积当作新几何的实际占用。
CLI保留完整事件与既定采样CSV及合并副本，
但不再保留供应商稠密TRJ临时文件；不改变积分、采样间隔或粒子母群。实际目录占用仍每30 s监测。
`retain_batch_trajectories`冻结进各worker配置并进入资源身份；master完整100粒子工作台不带该batch开关，
用户Fly时仍显示并保留原生轨迹。官方依据（2026-10-16核查，SIMION 2020）：
`examples/child_particles/child80.lua`明确image control 0为YES/YES、3为NO/NO，
`examples/multiprocess_zmq/tune_series.lua`展示关闭磁盘轨迹；本项目CSV记录独立于此开关。
该预留是运行前估计，不代表GUI验收或实际峰值。
GUI预留只覆盖准备；用户手动Fly的稠密轨迹增长另计。两种预留均来自冻结profile，中央容量策略不变。
原生场查询的主机内存声明单独消费同一profile的`native_field_query_memory_bytes`：
历史同尺寸查询实测峰值3,154,186,240 bytes，因此本轮声明4 GiB；历史资源观测不授予其物理结果资格。
它不改变主机中央准入策略或飞行worker并发，后者继续按首正式批实测重规划。

新运行不再消费已封存的旧raw PA族：从冻结GEM在本次私有run执行gem2pa和Refine，保留fractional `.pa-surf`。
所有IOB保存结束后，保护完整原生族，worker只作内存Fast Adjust；飞行后逐成员核对身份并保存回执。
此路线不把已发布缓存复制改名为新构建，不使用surface=none导出来丢弃fractional几何。
运行器必须复用公共`New-RunPackage`、capacity session、host lease和`Invoke-ResourceBudgetedProcess`。
不增加项目私有memory硬限，内存准入仍由公共主机policy负责。

`solver_timeout_s=1800`冻结为本轮求解预算记录；现有公共resource runner未据此主动硬终止，
也未实现该字段的专门warning，运行后保留实际耗时，不把该字段写成已执行的超时控制。项目不另写第二套超时wrapper。工具调用的10 s等等待窗口仅返回进度，
不会用作杀死实际求解进程的hard timeout。

判据和当前资格由项目状态页维护。只运行纯Lua或单元测试不构成真实Fly证据；真实Fly也不构成电极场、
数值收敛或GUI/CAD资格。COMSOL后续需要独立投影和同源状态比较。

当前原生网格0.1 mm、辅助几何60阶梯，Refine阈值0.001 V；这是新场身份，不代表已完成数值收敛。
Refine停止值从本次运行冻结的`inputs/numerics.json`读取；公共精度门禁只许可该路径的精确传递调用，
不许可硬编码阈值或其他路径复制。此次登记不改变已有原生场和GUI包的科学输入。
HP入口按论文2 mm钢孔解释为圆孔直径；LP outer以中心4 mm、端部3.7 mm内表面间隙放置有限板，
厚度向外增长。解释与未报告尺寸见`config/geometry_sources.json`，不将平板宽厚或屏蔽尺寸称厂家CAD。
最终GUI重开及场对等必须单独验收，单位响应计算完成也不能自动授予GUI交付资格。


## GUI准备与批处理区别

唯一入口仍为`simion/prepare_gui_replay.ps1`，从明确、完整核验的baseline创建独立`solver_review`准备run。
`analysis/gui_replay.py`精确复制baseline冻结的GEM、source、HS1、RF、drive、builder和runtime；
不复制、哈希或向供应商重新打开baseline原生PA族。具名轻量消费投影仅核验实际所需的配置JSON、GEM、
冻结程序/源、summary、events、samples及canonical状态；原manifest中的PA记录仅作历史来源，不声称重新核验。
如baseline已由公共owner-retirement退役，先调用公共`verify_retirement`核验完整收尾及保留库存，再核验所需记录，
并绑定receipt身份。未退役来源也只消费该明确子集；新族成员由冻结projection电极ID派生，不要求旧PA仍在位。
新summary区分canonical `status=success/failed`与物理`functional_status`；历史格式只按其原资格解释。

该入口通过公共容量和SIMION租约串行执行GEM→Refine→官方IOB builder→只读原生场查询，
保留`.pa-surf`及完整新私有族、Refine日志、实际vendor姿态检查和IOB身份，最后发布checkpoint。
不调用Fly，不操作GUI；Load/Fly及视觉确认由用户进行。它不使用仅支持surface=none的standalone导出，
也不把旧raw family复制改名冒充新构建。新私有PA0允许用户工作台保存，编号响应与fractional surface身份单独记录。

默认runtime逐字节来自baseline，不消费工作树runtime；只有显式RepeatFlyCount=2才追加可追溯编排，
准备动作本身始终不执行Fly。配置仅重定位私有场和seed路径，物理参数、源6D与绝对RF时钟保持冻结。
工作台使用新run的绝对路径保存IOB与载入FLY2，避免`wb:load`改变CWD后误写来源目录。
builder不做Fast Adjust；运行时由冻结动态回调驱动电压。

冻结profile中的GUI承诺仅覆盖私有求场、日志和IOB准备，不包含用户Fly后可能增长数GiB的TRJ轨迹。
checkpoint只表示准备完成，不表示GUI视觉通过、轨迹等价或功能验收。重新Refine和随机碰撞条件下不预设逐轨迹相同；
后续比较只能报告实测差异。只有用户真实手动确认，才可记录`gui_visual_review=true`。

若baseline声明原生场诊断，准备结束默认生成`results/native_field_preparation_comparison.json`，
对照双方manifest／文件身份绑定的`native_field_samples.csv`和`native_potential_audit.csv`。
报告各列最大差、行数和既有序列化比较口径；数值差仅记录，采样位置／时间／标签或证据身份不一致则失败关闭。
未声明诊断时明确记录`not_declared_by_baseline`，不补造场相等结论。此报告不执行Fly、不授予GUI或轨迹一致性资格。

当前wrapper还在每次Fly开始用官方`simion.experimental.plot_line_segment`画出出口线框
（由局部HP末端至LP末端、测量面及PA横向范围派生，再转换世界坐标，颜色12）。这是数值面的GUI图形标记，
不是金属电极或模拟轨迹；不改变场、粒子或随机状态。本机依据为`simion.chm`的
`lua_simion.experimental.html#simion.experimental.plot_line_segment`；实际可见性仍待手动GUI确认。


## HS1运行副本生命周期适配

项目准备入口调用[公共HS1生命周期适配](../../../common/simion/README.md#hs1运行副本生命周期)，
同时冻结官方安装源与适配运行副本身份。reset与只读参数审计的机制由公共实现维护，
碰撞采样及弹性碰撞方程不因生命周期适配改变。项目runtime顶层只import一次，在Fly回调中调用reset，
不在回调内重新import；SIMION曾拒绝后一用法。

早期r04进入Fly后被外部中止，仅支持不完整探索观察，见[原生运行历史](history/20261016__native-flight-and-source-identity.md)。
该记录不代表当前功能或GUI状态；后继封存参考与用户确认只查[PROJECT](PROJECT.md#有效结果与默认诊断)。
新工作台的重复Fly仍按其冻结数值身份分别验收，不能由历史确认自动推定逐轨迹等价。

## 当前几何、时序与诊断

HP输运偏置当前为2 V，主push/pull和LP侧电极均为±900 V，末端透镜相对电压50 V属于项目种子。
`schedule.extraction_start_us=5500`定义RF淬灭起点，`rf_quench_delay_cycles=0.5`在3.7 MHz下
派生实际脉冲时刻5500.135135… μs；quench_start+0.1 μs处于淬灭等待，不能标作pulse+0.1 μs。
local y=9.8 mm测量面（world z=0）与local y=10 mm接地边界相差0.2 mm，当前0.1 mm网格为两格；它是数值观察面。

`analysis/diagnostics.py:export_diagnostics`从冻结的`inputs/diagnostics.json`、事件、samples及canonical状态
输出6组PNG/SVG、figure metadata和CSV：全ID轨迹与几何、全程分时云图、LP条件引出局部云图、
阶段相空间、冷却阶段能量细节、全程能量/慢轴位置/人数/展宽演化。
几何只读native projection，标注电极编号和功能；全母群alive/extracted/lost/notborn/unknown闭合，
终止后最后位置不进入alive云，未记录电极ID写unknown。
当前`radial_escape`是|local y|或|local z|超出boundary_radius_mm=2 mm操作接受域时的程序终止，
不称原生金属碰撞；`solver_stop`也不能编造电极ID。r07冻结此规则，后续真实碰撞追踪属于另一次显式口径改变。显示插值限定相邻实际记录，普通bracket≤1.05 μs、
引出区≤0.025 μs，并保存实际bracket和最大gap；不从稀疏旧run伪造密集轨迹。
N=10全部散点/ECDF，不加KDE/拟合或统计资格；N=100仍是功能范围。

原生场诊断由冻结的场查询计划、实际PA、电压时序与采样CSV建立电势/电场切线和阶段审计，
不以解析场替代原生响应。旧r05审计和r06探索只约束各自冻结几何；当前新几何必须独立求场与诊断。
旧r06已取得`exploration_pass`，具体旧几何数值与不适用当前验证的边界由PROJECT维护，不复制为新结论。

原生证据按solver_review保留；HS1副本与身份处理见[生命周期适配](#hs1运行副本生命周期适配)。
正式N=100、数值收敛、同IOB headless重放、两次Fly生命周期与手动GUI可见轨迹分别验收。

## 项目世界坐标与当前验收状态

PA/GEM、native projection、source.json及source_states母集均保持局部几何。
公共`rigid_transform`合同定义world=(-local z, local x, 9.8-local y) mm，速度和场向量仅旋转；
项目frame为`ion_processor.xyz.reflection_z.drift_y.transverse_x.local.v2`。
世界横向x、慢漂移+y、引出−z，与MRTOF方向兼容；器件frame不自动等于MR装配frame。
实际机械端口与接口状态见[PROJECT](PROJECT.md#统一组装迁移任务)，实例位姿由冻结配方绑定。
FLY2与工作台姿态使用同一合同；runtime将SIMION世界状态逆转到局部进行HS1压力分区、原生接受域与事件判定，
输出事件和samples再转世界。canonical快轴z，半径及散角按世界z计算；原生接受参数另行注明，压缩使用慢轴y。
旧无合同冻结运行保留原坐标解释，不通过重命名旧CSV伪造新证据。

历史r07/r10运行、源身份与旧碰撞绑定边界见[历史记录](history/20261016__native-flight-and-source-identity.md)。旧N=10结果不作为当前N=100已验证N2结果。当前真实统计与功能判据统一见[项目状态](PROJECT.md)。

原生场另输出`native_field_samples_project.csv`，保存转换后的项目位置/电场向量；
原生局部场CSV保留，电势为旋转不变量。默认全过程图角色和元数据区分全母群、条件LP子群及unknown，
全母群展宽不能以LP局部展宽替代。

早期准备包`20261016_015429__test__simion__ion-processor-n100-user-workbench`从同一冻结GEM独立Refine，
保留完整18文件场族；57,106个对应采样点的电势和三分量电场值与CLI相同，该准备步骤未执行GUI Fly。
此场采样对照不替代后继热源包的用户确认。当前封存参考与确认包见[PROJECT](PROJECT.md#有效结果与默认诊断)，
新包仍按上述GUI准备与用户验收边界处理；旧clone包不作为当前入口。

## 冻结代码资源与下游数值离域记录

准备阶段除Python源码外，同时冻结公共`particle_count_policy.py`通过`POLICY_PATH`读取的相邻JSON至
`inputs/code/common/contracts/particle_count_policy.json`，并绑定为run输入。回归测试使用独立Python进程在run目录、
仅以冻结closure为PYTHONPATH校验N=100，避免当前进程的import缓存掩盖缺资源问题。

下游数值观察面由冻结native projection派生：末端透镜最后实体x上界与PA最大x的中点。
当前local x=(210.5+212)/2=211.25 mm（world y=211.25 mm），位于透镜后且PA域内；
它分类为`numerical_observation_not_metal`，不增加电极、不修改GEM或既有场身份。
新`downstream_domain_exit`仅为本项目终态原因；分析要求终态恰在该派生面且局部vx>0，不能称金属撞击。
历史运行缺失的terminal不由分析补造；新guard须经后续真实运行产生记录，r11原99终态仍保留其不完整性。


## HS1参数绑定与原生内部值审计

SIMION的`adjustable`具有独立作用域；不能用普通Lua全局赋值推断导入HS1内部参数已经改变。
安装2020版HS1 README的Gas Mixtures示例在回调内显式使用`adjustable`赋值；
[官方作用域说明](https://simion.com/info/lua_scope.html)给出其局部作用域语义。
原生零步探针`20261015_203456__test__simion__hs1-adjustable-scope-zero-step`直接从HS1词法域读取：
普通赋值后为mass=4、T=273，显式声明后为mass=28、T=300；这证明赋值机制，不能直接给历史run的内部值定值。
探针两个微Fly均完成，但包装器误判CSV重复顶层行数，终态仍保持failed；
纯分析证据`20261015_205106__analysis__python__hs1-scope-native-readback`完整核验源记录并发布success。

正式runtime在每次reset后显式赋值9个HS1 adjustables；适配副本增加只读`bound_parameters()`，
不改安装源、碰撞公式或采样。初始化前后均从HS1自身作用域读取并对冻结输入逐键断言，
写`simion/hs1_bound_parameters.csv`；不一致时在积分前停止。主程序的`seed(n.seed)`随后独立执行。
纯Lua stub只测试生命周期、审计和失败关闭，删除`adjustable`关键字的语法适配不能证明供应商绑定语义。
旧普通赋值历史run没有该内部值证据，其气体模型不能视为已验证N2；当前数值结果和资格见项目状态。

## 自动分批与单工作台重放

同几何纯调压使用 `run_functional.ps1 -ConfigurationDirectory <完整配置目录> -NativeFieldRun <已封存来源run>`。
原生 Refine 已建立15个可调电极的单位响应；`runtime.lua`的`segment.fast_adjust`每次按冻结
`native_drive.voltages`写入全部`adj_elect`，包含RF、抬升、脉冲和E10／E11相对偏置。
电势按单位响应线性叠加，轨迹、碰撞与束团状态仍需每组重新计算。
既有prepare核对原生几何投影、网格／Refine精度、GEM身份、Refine完成日志及18个PA族成员的
路径／字节／SHA；不一致失败关闭。成功后引用只读来源，runner跳过GEM／Refine，飞行前后保护并核验原生场族。
改变实体、网格或求场设置则重新建场；GUI独立工作台的准备与手动验收继续使用其原合同。

`run_functional.ps1 -ConfigurationDirectory <directory>`支持MR匹配候选的完整科学／数值配置目录；
未指定时仍消费本项目`config/`。显式目录要求自身包含坐标合同，冻结全部实际消费配置及可选的
`component_matching_derivation.json`，不回退到封存基线拼接缺项。准备、资源调度、求场与自动诊断复用原入口。
候选目录仅是求解输入，不表示已经求场或完成出口匹配。

外层主机`flight`租约只管理整项重任务的准入；粒子worker并发由公共
`common.simion.resource_scheduler`、`common.simion.particle_batching`及
`Invoke-ResourceBudgetedProcesses`决定。未知资源身份先保留首正式批，观测峰值后重规划；
不在项目固定并发路数或以PA磁盘大小代替进程峰值。
观测后的准备或调度错误会停止新worker启动，但不会中止仍健康的首正式worker；运行器等待其自然终态，
保留其原生日志和输出后才将本次运行发布为失败。
worker控制文件和输出各自隔离，根`simion`目录始终保留完整母群的master工作台，供后续GUI准备复制。

SIMION官方程序流程图规定先创建全部离子并调用各自`initialize`，随后才逐离子积分。
不能仅凭`initialize`的赋种记录推断每粒子实际积分随机流；后续创建与求解器调用可能影响消费顺序。
依据：[官方程序流程图](https://simion.com/docs/fig-prg-flow.pdf)。
`numerics.collision_rng_policy=per_global_particle_seed_v1`明确规定在每粒子首次实际积分回调中重置HS1私有状态与步长，
重赋/读取参数并初始化，最后调用`seed(base_seed+global_particle_id-1)`。
worker全局ID为公共batch offset加本地ion_number；赋种参数由global ID派生，不依赖批数和启动顺序。此映射不单独证明SIMION实际碰撞随机流相同。
种子范围1…2147483646是项目保守整数合同，不宣称厂商RNG极限；不同整数种子也不等于已证明统计独立子流。
每Fly保存`collision_rng_seeds.csv`，合并后必须覆盖完整母群并符合种子公式。
新政策与旧串行跨粒子共享随机流属于不同数值身份，不能逐ID要求新结果匹配r17。

批次CSV由公共merger恢复global ID；events表先透明重排列使particle_id为首列，公共合并后恢复event首列。
这只改变列序，不改行内科学状态。真正的分区等价需用原生SIMION同一小母群、不同batch划分、非零offset
比较完整events、samples及种子记录；纯Lua stub不能替代该验证。手动GUI验收仍由用户完成。

多worker产生的大量输出通过公共Python清单API直接传Path列表，避免重复绝对
路径参数超过Windows命令行长度；文件选择和公共身份/保留检查保持一致。

随机碰撞允许不同随机实现产生不同单离子轨迹。原生分区对照未通过仅表示精确重放未验证，
不自动判定碰撞物理或公共并发失败，也不阻塞完整N100统计评价。GUI手动Fly比较捕获/引出率、
损失位置和空间/能量分布；单次N100不能证明统计等价，不承诺逐离子重合。


### Automatic English diagnostic panels

The registered geometry comparison also exports recorded envelope minima, projected angle covariance/residuals, and explicitly counterfactual zero-field waists. Spatial crossings may use the last positive-z sample and the measured extraction_exit event as a bounded terminal bracket under the existing maximum time gap. Such rows have method `bounded_sample_to_exit_event_crossing` and no invented upper sample line. Missing support remains unknown; increasing the plane density does not establish solver convergence.

The 2026-10-20 switch audit found a roughly −62 m/s z impulse consistent with a post-switch end-node contribution of weight 1/6, while the passive quadrature intentionally takes the left limit at that boundary. Internal field-call nodes were not recorded, so this is an inference requiring a fixed-state short-step control. SIMION's [official flowchart](https://simion.com/info/_images/fig-prg-flow.pdf) and [FAQ](https://simion.com/info/faq.html) document multiple fast_adjust calls per integration step and step-end other_actions. These callback semantics are used for installed SIMION 2020 8.2.0.11; current online documentation does not certify this particular inferred node sequence. Source-bound raw steps, neighboring steps and all 15 electrode responses are retained in the mechanism evidence run linked from PROJECT.

The existing `functional.analyze` → `export_diagnostics` path exports the English structure/section atlas (including E9), timed section clouds, extraction section clouds, three population/energy/phase-space panels, and the combined post-extraction packet/axis-energy figure. Both producer modules are imported before `prepare` captures the Python source closure; each fresh run freezes the implementation it uses. No separate manual plotting command is required.

The post-extraction common time is selected from recorded crossings and sampling support, with bounded interpolation and no extrapolation. Missing extracted ions or insufficient common-time support produce explicit availability metadata, header-only tables where appropriate, and explanatory panels; these diagnostic states do not upgrade the measured physical `functional_status`. Source paths, timings, cohort counts and electrode dimensions come from the run's frozen inputs and recorded data. Existing evidence is never overwritten; historical sealed runs retain their frozen diagnostic implementation.
