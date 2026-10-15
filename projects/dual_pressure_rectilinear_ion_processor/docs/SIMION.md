# SIMION功能复现实施

当前科学状态与资格见[PROJECT](PROJECT.md)。

## 表示与官方支持路径

目标版本为本机SIMION 2020。唯一生产workflow为简化实体电极几何→GEM/PA→原生Laplace单位响应求解→
按实际RF、DC与脉冲电压组合电场→官方HS1碰撞与同一次连续Fly。实体电极、透镜、辅助DC阶梯和引出狭缝
来自同一baseline。原生电压只消费`config/native_operating_point.json`，RF/时序沿既有baseline冻结。
动态场复用官方Fast Adjust及单位响应线性叠加支持机制，不用理想解析梯度覆盖生产电极场。

前一解析场workflow尚未运行。`efield_adjust`中的解析规定场和旧curvature/offset仅供受控参考；
不得将其输出或普通GUI静态电势显示混为原生动态场证据。旧0.2 mm场族的15组原生响应Refine完成（15.47 s），当前0.1 mm场族已求解；旧场不自动继承资格，当前恢复与结果边界见PROJECT。
RF波形复用`common/multipole/simion_rf_drive.lua`，所有阶段使用唯一绝对instrument time。
LP浮动屏蔽件电极14与LP common-mode同步，HP屏蔽件电极15与HP common-mode同步；
屏蔽件与接地外边界的关系由原生几何统一派生，避免4 kV抬升把离子云暴露于未经声明的近地泄漏场。
屏蔽件是简化功能几何，不是实际商业CAD。
单位响应的尺寸、原点、电极映射、网格、Refine误差与源码身份必须冻结；几何壁碰撞和状态事件由实际积分记录。

公共离子初态和receipt来自`common/ion_release/release.py`，FLY2序列化复用
`common/simion/particle_source.py`。单槽IOB从公共干净种子派生，运行包装复用公共容量生命周期与主机租约。
源、场、时钟、数值、程序和HS1输入必须冻结至run-local并进入manifest。

## 官方资料查证

查阅日期：2026-10-15。在线补充文档目前标注SIMION 2026，实际调用以本机2020示例和接口为准。

| 资料 | 支持与本轮采用范围 |
|---|---|
| [Collision Model HS1](https://simion.com/info/collision_model_hs1.html) | 官方硬球、弹性、Maxwell气体模型，包含冷却与反向加热；不含碎裂、反应或气体反馈 |
| [GEM Geometry File](https://simion.com/info/gem_geometry_file.html) | 官方CSG实体电极与GEM→PA路线；在线页面为2026，采用本机2020支持语法 |
| [simion.pas API](https://simion.com/info/lua_simion.pas.html) | 官方PA创建、Refine与fast_adjust接口，8.1及以后支持；作为原生单位响应路线依据 |
| [Refine](https://simion.com/info/refine.html) | 官方原生电势求解与Fast Adjust响应机制；不据在线新版本特性推断本机均支持 |
| [Fast Adjust FAQ](https://mail.simion.com/info/faq.html) | 官方说明动态电极场可在RF/脉冲飞行中按响应叠加；回调不会自动更新完整PA0显示 |
| [User Programming](https://simion.com/info/user_programming.html#efield-adjust) | 官方用户程序入口；该网页当前正文未提供完整efield_adjust细节，不能单凭页面锚点证明调用语义 |
| `C:/Program Files/SIMION-2020/examples/collision_hs1/README.html` | 已读取，明确示例空PA、低压适用性及test2可按空间变化压力/温度/气流 |
| `C:/Program Files/SIMION-2020/examples/collision_hs1/collision_hs1.lua` | 已读取头部和参数：自动MFP=-1、每MFP默认20步、seed约定、截面示例；正式执行前冻结实际消费完整源码身份 |
| [装置论文DOI](https://pubs.acs.org/doi/10.1021/jasms.3c00311) | 公开装置结构依据；本轮在线打开失败，不把访问失败写成论文不存在 |

HS1示例的2.27e-18 m²用于He与约200 amu离子示例，不是N2与524 amu的测量。
`seed=42`定义实际PRNG seed；本机HS1的`_random_seed=n`使用n−1，因此应向该参数传43并记录映射。
数值合同声明自动平均自由程及每MFP步数；碰撞步长与RF步长同时约束实际积分。

本轮是基于官方求场接口和官方碰撞算法的项目实体电极模型，不是供应商验证过的Astral装置模型。

## 执行与验收边界

生产入口为`simion/run_functional.ps1`，准备与分析由`analysis/functional.py`承担；
`verify_project.ps1`执行轻量unittest。从仓库根使用项目入口，先验证输入和计划，再启动真实SIMION。
不得通过旧oaTOF或多极杆入口偷偷覆盖科学参数。终态发布run_config、summary和manifest，
保留canonical粒子事件、必要日志与轻量图。

项目专用[执行合同](../config/execution_profiles.json)的`native_functional`绑定
`native_electrode_functional`、唯一runner及五份相对输入路径，不复制物理标量。该合同使用项目专用role，
由项目编译器校验；不冒充公共通用execution profile格式。
本轮选择`solver_review`，理由为保留原生电极场与工作台供GUI审查。
当前执行profile预留4 GiB：新建私有18文件场族约3.3 GB，CLI保留完整事件与既定采样CSV及合并副本，
但不再保留供应商稠密TRJ临时文件；不改变积分、采样间隔或粒子母群。实际目录占用仍每30 s监测。
`retain_batch_trajectories`冻结进各worker配置并进入资源身份；master完整100粒子工作台不带该batch开关，
用户Fly时仍显示并保留原生轨迹。官方依据（2026-10-16核查，SIMION 2020）：
`examples/child_particles/child80.lua`明确image control 0为YES/YES、3为NO/NO，
`examples/multiprocess_zmq/tune_series.lua`展示关闭磁盘轨迹；本项目CSV记录独立于此开关。
该预留是运行前估计，不代表GUI验收或实际峰值。
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

4 GiB承诺仅覆盖私有求场、日志和IOB准备，不包含用户Fly后可能增长数GiB的TRJ轨迹。
checkpoint只表示准备完成，不表示GUI视觉通过、轨迹等价或功能验收。重新Refine和随机碰撞条件下不预设逐轨迹相同；
后续比较只能报告实测差异。只有用户真实手动确认，才可记录`gui_visual_review=true`。

当前wrapper还在每次Fly开始用官方`simion.experimental.plot_line_segment`画出出口线框
（由局部HP末端至LP末端、测量面及PA横向范围派生，再转换世界坐标，颜色12）。这是数值面的GUI图形标记，
不是金属电极或模拟轨迹；不改变场、粒子或随机状态。本机依据为`simion.chm`的
`lua_simion.experimental.html#simion.experimental.plot_line_segment`；实际可见性仍待手动GUI确认。


## HS1运行副本生命周期适配

安装目录的原始HS1保持不变，run同时保存其来源身份及适配运行副本的SHA。
适配只为运行副本增加`reset_run_state`生命周期入口，清理HS1私有初始化标志、碰撞步长与累计状态，
使同一GUI工作台重复Fly能够重新初始化随机源。碰撞采样、速度分布和弹性碰撞方程正文不变。
程序顶层只import HS1一次，Fly回调调用reset钩子，不在回调中重新import。
此项是基于官方模块的项目生命周期适配，不声称官方原模块直接提供该钩子。

回调内重新import已被SIMION拒绝，当前采用上述reset钩子。r04已真实进入Fly后被外部中止，
仅保留不完整探索观察；重复Fly等价性仍须实际headless重放与手动GUI核验，当前不声明功能或GUI通过。


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

原生证据按solver_review保留。HS1运行副本reset adapter只修改生命周期：安装源不改、碰撞正文不改、
顶层一次import、reset_run_state清理私有状态；原源/适配副本SHA进入run。
正式N=100、数值收敛、同IOB headless重放、两次Fly生命周期与手动GUI可见轨迹分别验收。

## 项目世界坐标与当前验收状态

PA/GEM、native projection、source.json及source_states母集均保持局部几何。
公共`rigid_transform`合同定义world=(-local z, local x, 9.8-local y) mm，速度和场向量仅旋转；
项目frame为`ion_processor.xyz.reflection_z.drift_y.transverse_x.local.v2`。
世界横向x、慢漂移+y、引出−z，与MRTOF方向兼容，但装配port Y未注册，不能称MRTOF全局frame。
FLY2与工作台姿态使用同一合同；runtime将SIMION世界状态逆转到局部进行HS1压力分区、原生接受域与事件判定，
输出事件和samples再转世界。canonical快轴z，半径及散角按世界z计算；原生接受参数另行注明，压缩使用慢轴y。
旧无合同冻结运行保留原坐标解释，不通过重命名旧CSV伪造新证据。

历史r07/r10运行、源身份与旧碰撞绑定边界见[历史记录](history/20261016__native-flight-and-source-identity.md)。旧N=10结果不作为当前N=100已验证N2结果。当前真实统计与功能判据统一见[项目状态](PROJECT.md#当前n100运行)。

原生场另输出`native_field_samples_project.csv`，保存转换后的项目位置/电场向量；
原生局部场CSV保留，电势为旋转不变量。六个全过程图角色和元数据区分全母群、条件LP子群及unknown，
全母群展宽不能以LP局部展宽替代。

当前用户工作台为 `20261016_015429__test__simion__ion-processor-n100-user-workbench`，从同一冻结GEM独立Refine并保留完整18文件场族。57,106个对应采样点的电势和三分量电场值与CLI相同；未执行GUI Fly。GUI操作和Programs状态确认由用户完成；旧clone包不作为当前入口。

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

外层主机`flight`租约只管理整项重任务的准入；粒子worker并发由公共
`common.simion.resource_scheduler`、`common.simion.particle_batching`及
`Invoke-ResourceBudgetedProcesses`决定。未知资源身份先保留首正式批，观测峰值后重规划；
不在项目固定并发路数或以PA磁盘大小代替进程峰值。
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
