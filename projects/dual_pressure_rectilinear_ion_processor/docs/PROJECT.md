# 双压力区矩形射频离子处理器项目状态

本页维护独立器件的输入、有效结论、资格和开放动作。操作见[项目入口](../README.md)与
[SIMION说明](SIMION.md)；完整局部实验、接口迁移及实现修复见
[文档收口里程碑](history/20261026__assembly-documentation-consolidation.md)。

## 当前状态与封存边界

本项目拥有HP／LP拓扑、RF驱动、气体与碰撞、捕获／转运／聚集／抬升／正交引出时序及独立验收。
可复用裸导引、冷却组件和完整IP是不同输出边界；裸导引不包含HP／LP、气体浴或完整IP资格。
真实上游接入、器件间位姿和下游联合飞行归[统一集成](../../../integrations/README.md)。

| 对象 | 当前结论与限制 |
|---|---|
| 独立简化器件 | 原生实体、GEM→Refine、RF/DC／脉冲和HS1碰撞功能贯通 |
| 封存独立GUI | 2026-10-16用户确认加载及飞行无问题；原包保留 |
| 真实上游注入 | 已接收冻结出口状态；不同物种有独立负结果与功能证据，见下文 |
| COMSOL、空间电荷、厂家CAD、气体截面标定 | 未完成 |
| 全程网格／时间步收敛、统计显著性、实机性能 | 未取得资格 |

HP／LP压力和温度是当前碰撞气体浴的规定输入，不表示已经求解整机压力分布或分子流。
HS1截面仍为未标定示例值。原解析规定电场已退役，活动生产只使用原生电极场及具名电压合同。

### 原批分区恢复

`simion/run_functional.ps1 -ContinuationPredecessorManifestPath <原manifest> -RunId <新run>`
保持前驱完整批次分区和原ID；已完成（包括已归档）的单元由manifest引用，缺失完整单元重做。
公共scheduler按实际最大缺失单元选择同身份画像；画像不足时先执行该原单元观测，保留其实际进程，
再按实测CPU、内存和现有互斥策略派发剩余单元，不再强制单路恢复。未知writer仍保守处理，
健康worker自然结束；该恢复不是原生积分checkpoint，不改变前驱终态。

`accelerator_interface/execute.ps1 -FullJoint`的MP→IP分支可独立传
`-IonProcessorContinuationPredecessorManifestPath <IP原manifest>`，同时提供新IP RunId及原已发布
MP→IP准备RunId、未变请求和接收配置。复用前核验原准备包、源和冻结接收几何；IP入口继续核验
冻结源、设计、驱动及数值。恢复后的新IP源生成新接口设计，不能直接套用绑定旧源的接口设计；
下游完整批恢复仍使用独立的`-ContinuationPredecessorManifestPath`。失败报告提供实际阶段、owner路径
及原始错误。软件恢复与并行回归不授予新的物理或科学资格。

## 当前输入权威

| 内容 | 唯一入口 |
|---|---|
| 几何、气体、RF、时序 | [baseline](../config/baseline.json) |
| 电极电压 | [native_operating_point](../config/native_operating_point.json) |
| 完整出生源 | [source](../config/source.json) |
| 数值与验收 | [numerics](../config/numerics.json)、[acceptance](../config/acceptance.json) |
| 来源及假设 | [geometry_sources](../config/geometry_sources.json)、[source_parameter_sources](../config/source_parameter_sources.json) |
| 坐标与诊断 | [coordinate_transform](../config/coordinate_transform.json)、[diagnostics](../config/diagnostics.json) |
| 公共执行能力与内部预算 | [execution_profiles](../config/execution_profiles.json)、[runtime_profiles](../config/runtime_profiles.json)，两者职责分开 |

来源文件解释尺寸与假设，不是第二份可调真值。声明式候选由同一入口消费完整外部配置，缺失字段失败关闭；
任何改动生成新run，不缩放旧出口速度或改写封存结果充当新工况。

本地到器件world帧为`world=(-local_z,local_x,9.8-local_y)` mm：world x横向、+y慢漂移、-z引出，
速度只旋转，时间不变。该帧方向兼容MR，不自动等于MR装配坐标。z=0是有界观察面，
不是实体端口、接地／无场面或已经验证的第一时间焦点。

封存参考的识别性摘要：HP／LP／guide长100／80／30 mm、r0=2 mm；N100、524 u、+1圆柱源，
纵向5±1 eV截断Gaussian、横向300 K；RF为3.7 MHz、1000 Vpp，气体300 K、28 u，HP／LP为1／0.2 Pa。
精确源采样、时序、原生电极和派生尺寸只认该run冻结输入；这些摘要不能重建模型。
300 K是文献启发的入口横向假设，非厂家实测温度；不重居中或缩放有限母样本。

## 有效结果与默认诊断

功能参考为`20261016_121423__sim__simion__ion-processor-thermal-n100-auto`，用户确认包为
`20261016_122844__test__simion__ion-processor-thermal-user-workbench/simion/processor.iob`。
两者身份与科学边界见[功能里程碑](history/20261016__thermal-source-gui-accepted.md)。

| 指标 | 封存参考 |
|---|---:|
| 原始母群／终态 | 100／100 |
| HP捕获／引出 | 97／97，六项原功能检查通过 |
| 上游损失 | ID24、64、80；0 timeout |
| 同97粒子出生／捕获总能量均值 | 4.989944／0.042768 eV |
| 引出总能量均值／人口sigma | 3892.109885／35.327658 eV |
| z=0束斑人口sigma(x,y) | 0.084756／0.345205 mm |
| z=0到达时间人口sigma | 3.179094 ns |

三个损失保留原生solver_stop与全部采样；亚网格几何余量不能证明精确撞壁。
97/100与其他源的95/100或100/100不能单凭一次差异称为优化。GUI场采样一致不是全场收敛，
也不要求随机碰撞轨迹逐点重现。加载包及唯一轨迹继续保留，文档收口不改变公共保留合同。

## 统一组装迁移任务

提供者从同一native projection发布真实guide入口、E14出口屏蔽端面、截面、壁厚及具名电极集合。
一组可含多个solid，不按CSG分块或PA编号重新定义物理电极。裸导引与冷却组件分别发布自己的真实几何，
不构造假孔、整面静态电位或新时钟。完整接口不替代真实几何与场的消费核验。

`component_exit.py`只读封存运行，发布公共canonical粒子状态、原ID、物种、实测6D、绝对时间和全母群census；
新MP→IP准备结果的母群终态携带每ID相对权重，IP出口census同时保留未转交粒子的权重；历史记录缺少
母群权重时保留未知，不能把缺失权重当单位权重计算全链效率。转交分类复用公共`particle_census`。
零出口发布`zero_exit`和完整母群census，不构造空粒子状态；下游应停止匹配和飞行并保留负结果。
上游零出口导致的IP空接收run也输出同一零出口结论，不宣称IP已飞行；未转交ID不作为物理损失，
注入源的原始`species_id`与权重随出口保留。新的准备run在终态manifest发布前不可作为有效交接。
IP源与批次源的6D及直接速度序列化投影使用公共`particle_source`，原坐标变换与原ID映射不变。
已发布的MP→IP准备结果通过公共manifest引用核验准备run终态、原始输入包和上游manifest，
IP冻结输入保留该引用；旧式未发布的准备包仍使用原生产者校验路径，不弱化原生完成与科学结果检查。
不重建速度、不执行求解。实例路由由冻结配方指定，测试粒子权重不表示实际电流。
单位、父母群、边界事件与唯一时钟由接收方独立验收；实际端面与数值z=0观察面分别保留。

### 真实上游状态注入

公共functional入口的`-InjectedSource`接受冻结状态包，默认独立源行为不变。
上游状态不重采样，出生与到达绝对时刻、原ID及物种保留；碰撞随机源绑定原ID，批次序号不改母群身份。
到达前表示尚未进入IP，不表示未出生；零出口不启动下游Fly。

注入状态的正相对权重从冻结injected_states.csv按原ID保留，经release适配到出口canonical；
不归一化、不以缺字段默认1，独立原生生成源仍采用原等权1合同。权重是统计元数据，不改
SIMION输入速度、能量、采样或物理力，不代表实际束团电荷。2026-10-27的32项admission／
component-exit回归覆盖原生等权、注入等权3.5与非等权0.125／8、ID重排、缺ID／缺权重拒绝；
出口其余字段和母群census不变。这是纯状态交接修复，无需以新飞行验证轨道；既有封存产物不重写，
历史非单位注入权重导出需按冻结输入重新导出后才可用于相应加权统计。

| 冻结接入工况 | 有效结论 | 资格边界 |
|---|---|---|
| 100 Da／+1，20261022_213053 | 接收100个真实机械出口ID，74进入HP，0捕获／提取，六项验收均未通过 | 完整failed负结果；具体失稳机制未知 |
| 524 Da／+1，后继真实接入 | 81／100提取，后继MR状态／时钟与100母群闭合 | 原捕获／提取门限仍failed，功能交接不等于性能通过 |

原始输入、终态分类、完整manifest与后续链证据只查
[真实状态交接](../../../integrations/docs/INTEGRATION.md#真实多极杆ip状态交接)。
完整负工况可交接其实际出口并携带原failed结果；未完成原生、无效状态或零出口不能进入下游实飞。

## 局部诊断的有效结论

以下都是已完成的具名N100研究，源、几何、场、网格、数值与时钟分别由各自冻结study和原run绑定。
它们不替换封存独立基线，不自动启动整机联合、优化或GUI。详细矩阵及证据链接保存在
[收口前原文](history/20261026__assembly-documentation-consolidation.md)。

| 科学问题 | 可保留结论 | 不支持的解释 |
|---|---|---|
| LP长度×抬升电压2×2 | 高电压的x角展宽响应较大，缩短LP未消除；固定共同95个ID比较 | 单次N100总体显著性、原因百分比 |
| 提取孔与LP压力 | 屏蔽孔0.8→1.0 mm减弱一部分x场致展宽；LP0.2→0.1 Pa保留HS1尾部 | 将全部末端角宽当冷却温度，或删尾部改善指标 |
| RF零交叉关断 | x角宽增加、y角宽降低；开关遵循具名零交叉序列 | 两轴同时改善、实测电源波形或严格微观配对因果 |
| E10／E11局部调压 | 角宽、束宽、发射度、能散与损失有取舍 | 无代价准直或最优电压 |
| 直角／成形提取与连续辅助轮廓 | 相空间取向、束腰与时间宽度改变；D对C的x角改善伴随y角和时宽恶化 | 厂家等形CAD或已选最佳轮廓 |
| D基准调压／Outer覆盖对称 | 三组分别96／97／34引出；对称覆盖形成不利入口势垒 | 仅凭外观对称保证性能 |
| 出口后时间焦点与假想小孔 | 保留t–vz相关可估计零场RMS焦点；小孔以传输损失换条件宽度 | 真实Prism焦点、粒子冷却或MR分辨率 |

完整D对照见[独立里程碑](history/20261020__d-auxiliary-voltage-and-symmetric-coverage.md)。
轮廓尺寸中未知坡角、唇厚、圆角和抽气窗仍是作者假设；LP61.5 mm裁短不等于对称光学优化。
连续辅助片的弦近似几何误差不是场或轨迹误差界。

### 未解决的数值与损失边界

- C37触发r0人工径向接受边界，不是已证明撞金属；D99进入末端漏场并离开数值观察面，端域长度未收敛。
- 多个solver_stop终点距连续实体仅亚网格余量，不能确定实机接触位置或原因。
- 受力预算支持开关节点约定可能造成残差，但缺内部节点直接记录，不能称已证明求解器错误。
- 真实碰撞历程可在干预前分叉，不能把局部对照当逐轨迹纯因果实验。
- RMS最小、中央68%／90%宽度和直接峰宽是不同指标，不能按高斯任意互换或用去趋势宽度冒充真实焦面峰宽。

## 执行与复用

生产入口、原生场复用、分批和GUI副本见[SIMION实施](SIMION.md#执行与验收边界)。
默认诊断保留全部母群、损失、分时空间云、相空间、冷却能量及引出后结果；同时刻云和逐粒子穿面集合分开。
原生Fly完成事实、科学终态与性能验收分别校验。配置、源和实际代码依赖由运行冻结，
新飞行不继承来源场的粒子结果或GUI资格。


空间穿面诊断已由 `spatial_crossings.py` 适配公共 `plane_crossings` 的版本1
`bounded_linear_directed_plane_crossing` 内核。IP仍选择脉冲后的首次负z穿面，保留原行号、
完整母群及终止原因；脉冲前记录按原顺序先过滤，z=0仅取实测出口。内核状态视图按冻结
epoch加原生elapsed时间一次，诊断表继续在原mm／mm-us及原生 `t_us` 上插值，不往返换算速度。
当前独立运行epoch=0；frame和epoch必须来自已声明配置，不提供缺字段默认值。

样本只流式读取一次，适配器每ID保存当前夹持原状态；公共receipt产生后立即插值，不缓存完整转换轨迹。
已知出口／终态限定重建区间：原生Lua先写积分步末采样再插值终止事件，因此晚于终态的原始采样仍保留，
分析以完整实测终态替代末端锚点；仅有终止时刻时，保留同刻实际样本可支持的前段，不能虚构终态坐标。
正z穿面不包含终止瞬间，z=0继续单独发布真实出口；缺终态仍允许两个实测样本支持的有界穿面，
不能据此外推存活。所有脉冲后原始采样仍核验有限性及每ID时序，过滤晚样本不掩盖非法记录。
出口自身允许的z=0记录容差不授权平面区间外推：出口仍高于请求正z平面时，该平面保持unknown。
未知穿面不解释为损失；完整母群原ID和相对权重不受生命周期截段影响。
functional在源码冻结闭包前导入新内核，断仓回归验证冻结副本实际计算及缺模块时拒绝回退。

2026-10-27迁移验证：extraction／geometry／functional共78项求解器无关测试通过。
对基线 `b5efb9d9c1963b5fc62a4c44c34549c08a9a6878` 的100组合成输入（5,200条记录、1,740行输出）
逐字段数值相同、输入未修改；专项出口越界用例从 `alpha=1.0000000000090001` 改为unknown。
这些是分析与冻结链回归，不是新原生飞行或科学性能资格。

同日将寿命边界、完整母群分类和显式分母效率接入公共particle_census版本1；IP保留原精确记录、
分阶段gap和显示插值，出生／入域包含而终止排除。缺terminal或缺采样不能推断存活；既有lost／
loss_count／diagnostic_losses.csv语义明确为非出口终止，包含timeout及未判明停止，不直接证明撞壁，
图显示改为non-exit terminal。局部OA与RF机械出口也使用同一母群内核，各自物理判定仍由原适配器负责。

注入IP从冻结canonical表读取完整入域ID权重；新增census权重和、实测extraction_exit条件效率保留
原相对权重。全链计数分母来自冻结上游母群；没有完整上游权重权威时，全链加权效率为null并说明原因。
本节快照sigma／冷却矩仍明确标为等权，不因census加权而改变；新增公共beam结果采用下述独立方法身份。

验证为54项公共／三消费者focused回归，以及IP与RF两runner实际冻结/删模块拒绝回退探针各1项；
后者不启动商业求解器。基线b5efb9d对照的600行IP状态、30行局部OA census及两组RF结果，
全部原有字段精确相同；新增权重手算覆盖计数2/3与相对权重65/93。RF重复母ID由静默折叠改为拒绝。

新run冻结`inputs/runtime_profiles.json`中的内部资源与保留预算；公开`execution_profiles.json`只供执行规划。
历史GUI重放通过显式`allow_legacy`读取原冻结`inputs/execution_profiles.json`的旧预算格式，
不改历史字节；两份预算并存或把新公开执行合同当预算均拒绝。普通新运行不走历史兼容入口。

## 公共束流与图形诊断

原`analysis/beam_focus_diagnostics.py`已迁到[公共束流模块](../../../common/analysis/beam_focus_diagnostics.py)，
项目位置退役且不保留转发包装。IP几何分析与局部OA直接复用schema 2的束宽、真角度发射度、
时间／能量相关与零场反事实预测；观察面、脉冲、实际出口、固定粒子群和缺测政策仍由适配器确定。
注入全母群相对权重仅从manifest-bound `injected_states.csv`经canonical loader一次读取，ID必须与source事件完整匹配；
原生源按其既有合同明确全1。公共均值、中心协方差、角度残差与漂移矩复用总体矩，原点RMS与中心sigma分列。
等权分位使用具名linear算法；非等权分位为weighted ECDF左逆，不在观测间插值；相对权重不表示电流。

受控几何比较把完整原ID到相对权重映射与源6D／时间共同视为源不变量，包含未提取母粒子；
权重比例变化或全体共同缩放均拒绝，不通过归一化掩盖输入变化。公共beam的单个群体统计仍保留
相对权重比例不变性；sources、exits、共同群、状态及权重键在比较或聚合前均要求正整数ID，拒绝bool／float且不重编号。
该输入guard修复保持原方法身份；84项相关分析／渲染测试通过，另40组等权输入的47,054个旧数值字段
与基线b5efb9d9精确相同，包含unknown观测且输入未修改。

迁移验证五模块75项通过，40组合成case的52,808个既有数值字段与旧实现精确相同；
新增带权手算、ID顺序、比例不变与完整CSV身份回归另测。快照／冷却专用旧等权矩没有被暗改为新beam方法。
真实冻结副本已运行带权beam计算，删除冻结公共模块后失败且不回退活动仓库。

几何图与局部OA复用[公共图形导出](../../../common/analysis/figure_export.py)，保留原名称、PNG／SVG、
IP的210 DPI及白底。manifest记录实际导出的尺寸／格式／DPI／字节，路径整批预检；失败只清理本批创建文件。
六模块合计80项通过，包含真实PNG／SVG渲染；冻结副本实际导出与缺模块拒绝也通过。
冻结回归以同一参数化执行循环保留五类实际计算／导出、冻结源码来源及逐模块删除后拒绝回读仓库的检查。
这些结果不构成新Fly、场、数值收敛或科学性能资格。

## 开放动作与关闭条件

1. 按[统一集成状态](../../../integrations/docs/INTEGRATION.md)完成实际请求、端口、电极与驱动消费对照；
   独立IP、裸导引及冷却组件分别验收，不能用接口纯回归代替真实装配。
2. 若恢复碰撞／损失调查，先做固定状态短程步长／开关验证、C37真实边界继续飞行及D99端域对照，
   保留全部原生状态；未经新授权不恢复已暂停的整机优化。
3. 真实上游捕获或匹配改动须冻结物种、母群、到达时钟、唯一变量与接受标准；旧100 Da负结果和524 Da门限失败保留。
4. 声明定量性能前补齐截面标定、网格／全程步长、随机重复及实机几何依据；COMSOL与空间电荷作为独立能力建设。
5. 新GUI包用独立可写运行目录准备，用户验收与文件默认重放分别记录，不覆盖已确认包。

独立产物归`artifacts/projects/dual_pressure_rectilinear_ion_processor/`；跨组件装配及联合证据归集成owner。

IP功能入口的正式首批观测及重规划由公共SIMION机制执行；IP继续负责批次物化和物理判据。

IP批次请求可在提供已验证场身份及冻结程序后计算，计算过程不创建IOB或场；正常准备入口继续使用同一身份投影。
`run_functional.ps1 -ContinuationPredecessorManifestPath`目前支持完整母群已归并的显式终态前驱：
验证原生批完成、母群、科学输入与程序身份后直接引用原CSV重分析，不启动PA、IOB或Fly，也不改父run。
多代重分析先验证前驱与数据源的 manifest 绑定，在容量会话中保护来源链，再引用原始完整母群；出口也沿该绑定读取原生证据。
正式批次完成回调持久记录每个原生进程的实际退出码与批次身份；旧结果缺少该证据时不能仅凭结束日志推断单批成功。
未归并的终态前驱按原批次计划恢复：完整单元须有原进程退出码、日志、输入和输出的 manifest 绑定；
未知或不完整单元整批重飞，不能安全容纳原批的当前资源预算会直接拒绝，不改变分区。原始 worker 数据由受保护的前驱提供；
已归档 worker 的四个 CSV 在新 run 解包供现有 merger 读取，种子、HS1 和日志仍引用原始证据。
合并后按既有文件移除合同删除临时解包；多次部分失败沿每代绑定追溯原完成单元，不重新启动已复用批。
全批复用只执行合并和分析，不启动 SIMION；混合恢复引用前驱场并持有防写锁，使用新 run 发布结果，不修改父 run。
外部 PA 家族由原 owner 的 manifest 保持唯一字节权威；新 run 只绑定小来源 manifest 与现有
`native_field_consumption.json`，后者保留精确 family records 和几何／网格／Refine投影。
准备的元数据绑定本身不授权原生消费：正式 `NativeFieldRun` 和混合恢复均在首个原生调用前逐成员执行一次
公共 immutable-source 字节校验并持有防写／删除句柄，持续到新 run 发布与完整验证结束。
消费侧同时持有原终态发布的既有 byte-lock，拒绝 pending journal；来源 manifest、run config 和PA不能
在此窗口被替换。后续投影与子manifest不再重复读取原owner的大PA，不新增跳过校验参数。
部分恢复按冻结场的来源判断外部家族，沿用上述保护；不会因未传`NativeFieldRun`而把已接续场误当新建家族写打开。
显式场与部分恢复同时指定时，只在实际adopt前获取一次最终来源保护，不重复获取同一终态发布锁；全批复用不进入该adopt分支。
summary与stdout报告失败阶段、原因、恢复动作、稳定结果路径和阶段／总耗时；summary计时截止结果观察，
stdout的最终owner总耗时另含发布及资源释放。未知写者保留保护并要求先确认其完成，不能直接重试。
正常IP收尾使用公共PowerShell owner：冻结request、实际进程／host完成事实和小Result后，由公共机制执行
保留、终态发布与容量封存。Result默认持久放在`scratch/workflow_results/<run_id>/result.json`；
原入口`run_functional.ps1 -RunId <id> -ResumeFinalization [-ResultPath <原Result>]`只重放收尾，
不准备源／场／IOB、不重飞、不修改父run。发布前失败与已发布终态后的seal失败均保留原事实；重复恢复
不重写已发布summary/manifest。未知writer仍拒绝收尾，原始科学异常与收尾次错分别保留。
`component_exit.load_component_source`验证封存的IP来源与结果；科学门限失败、诊断失败与写入状态未知分别记录，
未知写入者不发布终态或显式释放受保护资源。
原生准备命令与IOB模板构建同样以公共观察器的实际退出事实决定停写；退出未知时保留PA句柄、资源和容量保护，原始异常不被收尾覆盖。

## 机器能力与解析输入

profile 区分软件检查与实际科学动作；现有 ConfigurationDirectory 接口继续消费声明配置，不增加新 runner。
能力查询与执行编译见[公共合同](../../../common/contracts/README.md#执行dry-run)；READY 仅描述声明条件。

## 结构化记录与默认诊断

`runtime.lua`以公共`scientific_event_csv.lua`写events／samples，原15位精度、采样与轨迹请求政策不变；
`functional.prepare`在输出前检查并把同一写入器冻结到运行及可执行源码闭包，缺资源拒绝。
`diagnostics`默认流式读取，保留完整母群、原ID、6D和绝对时钟；帧／权重继续沿既有权威解释。
格式损坏失败，不用少行输入制造通过。新公共化不改变碰撞种子、驱动、积分或接受规则。

canonical状态保留原reason：接受为transmitted、明确逃逸／电极损失为lost；协议timeout为timeout，
未解析的solver_stop／unknown为unknown，不再全部写lost。母群、capture／extraction及原门限不变。
原non-exit terminal诊断不证明碰撞原因，未知电极保持unknown。
软件CSV／冻结／诊断回归不等于新增求场、飞行或科学资格，既有协议timeout及损失解释须按原范围报告。

### 运行根与冻结原生路径

正式`run_functional.ps1`在启动时解析并冻结公共四根，持久身份使用`artifact_run_dir`；
实际Python与SIMION准备／批次调用沿同一Package的`Get-RunNativeExecutionContext`选择执行表示，
同步运输cwd、argv、环境及Lua内的种子／场／IOB引用。主机库保持原身份，恢复读取原Result的run位置。
`functional.prepare`冻结实际动态资源、所选配置和官方seed/placeholder；新解释器可仅凭该源码闭包
重新准备同一GEM与源，不从今日活动默认配置补输入。公共持续只读guard的一次身份记录直接交dispatch，
原分区／原ID恢复、未知writer保守处理和科学接受条件不变。
本改动的软件夹具不等于新场Refine或功能Fly资格；外部PA仍由原owner及既有私有副本／保护边界处理。

2026-10-31 小型真实路径验收 run `20261031_141654__sim__simion__ip-path-probexxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`：
实际冻结 IP prepare 和原项目 build_workbench，经公共 IOB owner 完成新建11³／0.1mm未求解零场、保存、重开，
删除旧 execution alias 后以新 alias 冷重开同一 IOB，四个原生进程均实际退出0。
PA 在 builder 前取得持续防写 guard；保护前可写、保护中拒写，文件属性前后均 Archive，未设置 ReadOnly。
外层公开调用43.5748秒，纯准备2.5341秒，原生边界6.1688秒，公共路径准备0.76335秒／运输0字节；
终态、容量、资源释放及两个 alias 清理完成。小 Result 位于该主题 scratch 的
`agent2/native_ip_proposal/complete_owner_draft/root_native_result.json`。
该11³ PA仅验证 IOB／pose／路径与保存机制，0 Refine、0 Fly，不代表完整IP场、N=100功能或科学资格。


### 已有CLI恢复的解释器运输

IP原CLI沿公共workspace路径约定优先消费SIMULATION_PYTHON_EXE，未显式提供时保留仓库.venv默认。选定后准入及后续Python消费者使用同一解释器；无效显式路径仍由公共路径检查拒绝，不静默回退。GitHub system Python环境无需伪造仓库.venv即可按原CLI恢复publication／seal收尾，unknown writer仍保留保护；生产容量底线与科学输入不变。

历史CI604的accelerator五个subfail及5dd的IP publication／seal两个subfail均保留原FAIL。当前HEAD隔离源码不含.venv，由既有外部解释器执行：IP原方法三个场景通过33.398秒；accelerator四个方法最终分别通过dispatch2.933／实际provider8.664／请求归一化3.960／terminal4.495秒（首轮两项fixture上下文补齐前失败记录保留）。另以当前JointWorkflow命名和已迁project恢复测试作消费者投影，三个accelerator方法通过10.974／5.059／4.840秒；原未改dirty dispatch另验3.172秒，确认已修而跳过live重复补丁。迁IP fixture补回原HEAD已有惰性native_path_preparation后，publication／seal／unknown三个场景通过37.516秒，保留初次三FAIL及全部原保护／错误断言。

上述为定向软件方法及真实PowerShell／Python进程，公共GATE自然释放、零商业调用；两种隔离投影都使用HEAD公共机制，不依赖dirty common支持。不是最终全范围CI、SIMION物理或科学资格，也不把不同scope的b771成功当作覆盖。
