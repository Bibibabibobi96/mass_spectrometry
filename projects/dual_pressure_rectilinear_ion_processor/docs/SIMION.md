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
本轮选择`solver_review`，理由为保留原生电极场与工作台供GUI审查。r05仍冻结旧1 GiB预算；
后续profile将新增容量及瞬时目录warning预算提高为6 GiB，采样间隔30 s。
依据是r04中止时原生保留轨迹临时文件已达411,840,000 bytes，N=100保留轨迹的峰值不能按轻量CSV估算。
6 GiB是保守容量预留，不是已测完整N=100占用；该选择不代表GUI验收完成。
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


## GUI重放与批处理区别

`simion/prepare_gui_replay.ps1`从明确、已验证的baseline创建独立`solver_review`准备run，
通过`analysis/gui_replay.py`复制冻结的source、HS1、RF、drive和config，完整clone基准18文件PA族（PA#、PA0..15及pa-surf）至新run，记录源与副本身份；不共享可写PA。
默认`processor.lua`精确复制基准run已冻结的runtime字节，不消费当前工作树runtime；
默认一次Fly的runtime SHA相同，只有显式RepeatFlyCount=2才追加验证编排并记录差异。GUI事件和采样只写新run。
新wrapper每次Fly清理状态并复位HS1随机源、锁定grouped=0和image control=0。
GUI builder把新run的simion绝对目录直接嵌入脚本；全部load_particles和IOB保存路径均由该绝对目录构成，
不依赖CLI相对脚本名或wb:load公共seed后改变的进程CWD。
原批处理wrapper和冻结配置保持原身份；旧配置缺新采样字段时仍可原样重放，不强行升级wrapper。

builder不再调用Fast Adjust；wb:save可能改写被引用PA，因此工作台仅引用独立完整clone。
构建前后复核源PA族全部SHA，任何变动均使一致性证据无效。实际Fly由同一动态Fast Adjust回调控制。准备阶段不执行商业求解，创建checkpoint也不表示GUI完成。
当前真实IOB构建已完成；留下独立GUI准备run供用户打开与Fly。用户要求GUI由用户确认，本轮不自行运行GUI或追加repeat。
用户手动Fly并确认后才可发布GUI视觉验收；只有真实手动确认才记录`gui_visual_review=true`。
headless比较完整raw事件、canonical状态及全部已记录采样；它不覆盖每个积分步，也不冒充手动视觉验收。
准备入口可选`-RepeatFlyCount 2`，仅用于同一会话连续两次`run()`的状态生命周期验证，
逐次保存事件和采样，再分别与冻结基准比较；默认1次保持用户每次Fly仅运行一轮。
新几何数值配置以普通1 μs、引出区0.005 μs记录实际积分状态，仅增加记录密度，不用采样窗口裁剪积分步。
真正脉冲边界仍按RF淬灭后半周期调度并显式落点。旧r05/r06继续使用各自冻结采样，不补造旧轨迹。
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

r10已通过实际vendor姿态检查：ex→(0,1,0)、ey→(0,0,−1)、ez→(−1,0,0)，
PA原点→(4,−1,13.8) mm，单GU=0.1 mm。r10已完成新世界坐标真实native Fly，N=10为`exploration_pass`：
捕获10/10、引出9/10、捕获均能0.03840967267 eV，引出前9粒子均在LP，慢轴σy=0.331102781675 mm，
平均出口3927.990922904 eV；不授予N=100正式baseline或Candidate资格。
ID1在t=4178.520896 μs、world=(1.3965569,169.0133388,9.8188436) mm终止为`solver_stop`，
具体电极unknown。
r07真实N=10为捕获10/10、引出8/10、平均引出能量3927.873 eV、全体慢轴σ=15.234 mm，未达聚集目标。
旧r07 GUI重复Fly污染源PA0，旧一致性结论无效；从SHA验证PA#重Refine后PA0恢复精确SHA：
`8E68A310E56AEB5603E72973526E8DC9B3F8E40CCF5CFFAAB31DD1BC19ED5A99`。
恢复场身份与姿态通过均不能替代新Fly结果。

原生场另输出`native_field_samples_project.csv`，保存转换后的项目位置/电场向量；
原生局部场CSV保留，电势为旋转不变量。六个全过程图角色和元数据区分全母群、条件LP子群及unknown，
全母群展宽不能以LP局部展宽替代。

当前GUI准备checkpoint：`20261015_181000__test__simion__ion-processor-gui-ready__r10`。
18文件原生PA族完整clone，source/runtime精确复制r10，真实IOB姿态构建已通过；尚未Fly。
GUI操作与确认由用户完成，当前仅准备文件，不自动追加GUI或重复Fly测试；旧r07无效repeat结论不复用。
坐标方向兼容MRTOF仍不表示其全局port已装配注册。
