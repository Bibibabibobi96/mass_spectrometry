# RF多极杆离子光学项目状态

本文件是本项目当前事实、结构变体资格、有效结论和开放任务的唯一正文。运行方法见
[实现说明](IMPLEMENTATION.md)，理论与物理约定见[理论索引](theory/index.md)，
跨器件结果由[集成状态](../../../integrations/docs/INTEGRATION.md)维护。
本文汇合原四、六、八极杆项目仍有效的结论；身份迁移和代码合并本身不产生新的物理资格。

## 当前结论

四极接口开发 coarse 数值 profile 现显式设置 `minimum_element_size_mm=0.2`，经现有数值编译器与公共 mesh helper 传递；baseline 默认值保持。2026-10-31 mesh-only `20261031_084000__test__comsol__rf-interface-hmin-mesh` 外层68.162秒：实际全局 hmin 从6.69改为0.2 mm、custom开启，其余 auto9/hmax47.8/hcurve1/hgrad2/hnarrow0.1读回不变；网格非空、完整且无problems，原门禁通过。study/solution均为空，没有场或粒子求解。公共终态、容量、租约及alias清理完成，secondary_errors为空；该证据仅关闭粗网格准备断点，不证明完整传输、性能收益或科学资格。原080000/083000失败记录保持。

RF SIMION 继承 host grant 时仍核验原 token，但 completion 记录实际子任务退出结果（继承许可没有独立 release transaction）；许可事实未知时拒绝发布，重复收尾不再次释放。该接线修复不授予物理资格。

finite COMSOL 正常无碰撞 CLI 已接公共 PowerShell owner：原生前持久化 run 外小 Result、request 和实际容量会话，
收尾使用 COMSOL wrapper 真实 PID／起时／退出和 host release receipt。原命令 `-ResumeFinalization -RunId`
仅恢复原收尾，不重新解析科学输入或启动原生；明确路径及限制见[COMSOL说明](COMSOL.md#finite-原-cli-的收尾恢复)。
源／求场／分析主错误与收尾错误分别保留；未知 writer／release 不释放保护。旧 run 若缺原始冻结 owner 事实，
不会用当前默认值补造恢复资格。薄软件回归不等于真实求解、GUI 或科学资格；其他 COMSOL workflow 不由此自动获得恢复能力。
无碰撞[正常COMSOL入口](../workflows/no_collision_transport/run_comsol.ps1)可用
`-AnalyzeOnly -ParentManifestPath <原run_manifest.json> -EngineeringBudgetPath <分析自有预算> -PythonExe <正式解释器>`创建新analysis owner。
父run须有完整manifest绑定events、两组canonical state及冻结design/source/numerics/evidence；
通过原owner共享reader和SourceReferences保护原CSV，新run执行同一metrics／出口图／证据评价及公共收尾函数。
准入还绑定原native report、原public prepared entrypoint、comsol_task及其code_inventory。当前完整export记录
结合冻结producer控制顺序与两case／保存事实；旧同族producer无新增计时时，可由原task整体PASS／MODEL_SAVED
和原冻结导出顺序推导，不因缺计时自动拒绝。仅writer停止或CSV自洽不代表transport阶段已完成。
科学输入只取父冻结authority；分析源码按本次冻结，不因后处理修改而重求原场或粒子。
分析必须显式提供现`multipole_engineering_budget_contract`格式的自有预算，不借用父求解的2GiB承诺。
科学scope与父冻结授权／实际母群闭合；本次承诺取新预算transient，准入stat核对实际复制源码、小输入、清单
及新预算提供的结果／收尾余量，原MPH和CSV引用按零新增载荷计。host仅用现COMSOL/postprocess轻资源，不准入求场heavy。
正式分析显式绑定原particle_source，`source_binding=verified_ids`仅表示两case的原母群ID一致，
不表示native初态6D、权重或科学资格被独立验证；纯derive旧调用未给源时明确not_verified。
缺CSV／MPH-only返回`CSV_EXPORTS_INCOMPLETE_REEXTRACTION_REQUIRED`，不静默solve或读取MPH；
evaluator写出明确FAIL/checks时，保持CLI非零和status=failed，但执行完成、数据有效、科学FAIL分开报告；
失败阶段scientific_evaluation及具体未达checks保留，恢复动作是查看负结果／显式新研究，不盲修分析或重算。
显式`-AnalyzeOnly -ReextractFromModel`已接通同一分窗导出、原模型只读保护与公共原生路径／进程owner；
正常求解也消费同一科学template与导出实现，删除旧内联CSV转换。缺原映射的070000不推断身份；冷提取需要真实模型加载，不能称零商业调用。
`20261031_062508__analysis__comsol__rf-cold-v9`只读原071000的43,350,302 B已解MPH，公开命令75.878秒，
加载／提取阶段52.461秒，实际窗口提取4.176秒；观测进程树峰值3,148,632,064 B，无预算告警。
新增求解0、父模型保存false，7份事件／轨迹／canonical CSV与原输出逐字节相同；父manifest不变，
原MPH身份复用原记录及保护，仅stat而不重新哈希。科学结果仍UNQUALIFIED，不将8µs入口段改称完整传输或精度资格。
原CLI收尾恢复3.094秒返回REUSED；其CSV再由`20261031_062819__analysis__python__rf-cold-csv`重分析，
公开命令22.729秒，完成记录只有两Python进程，零模型加载／求解，冷提取父manifest保持不变。
这关闭了该已保存解格式的实际冷提取和后继CSV分析边界，不自动覆盖缺映射旧资产、所有故障现场或其他COMSOL workflow。
真实071000的N=100封存CSV由正常入口新建
`20261031_054000__analysis__python__rf-finite-v9`，公开命令21.016秒完成，实际分析0.806秒；
原母群ID核对通过，零出口图明确not_applicable，结果保持UNQUALIFIED，不授予完整传输或科学资格。
新增载荷预估30325367 B、自有承诺256 MiB，原MPH／CSV新增载荷0，实际completion的operations／resource_releases均为空。
原父manifest与准入记录一致；原CLI收尾恢复2.843秒返回REUSED，子manifest字节不变。
此前两次请求分别因retention不匹配和缺保留理由在创建run前拒绝，未新增原生调用。
随后`20261031_055828__analysis__python__rf-v9-observed`接通现有公共进程observer，公开命令29.598秒完成。
metrics／出口图两Python阶段分别记录实际PID、起时、退出、显式300秒／2GiB及可用内存预算和usage，
观测区间1.877／0.975秒，无告警；两个进程的完成事实与实际host release进入公共completion。
父manifest保持，商业工具调用0，科学结果仍UNQUALIFIED；正常求解后的分析保留原执行资源合同。
wall／RSS超预算沿既有软告警与物理危险政策处理，不以此强杀健康任务；短进程采样用量不冒充精确峰值测量。
原入口在分析前明确输出稳定Result路径；新增unknown-exit薄回归通过，未知进程不伪造完成或释放保护。

有限三维 COMSOL producer 读取所选数值合同的显式 `minimum_element_size_mm`：未声明时保持原网格控制，声明时须正有限且不大于 hmax，并限现选区 free-tetrahedral 路径。全局与工作区 Size 使用同一最小尺寸，typed raw 读回保持其他控制；mesh-only 根据冻结 strategy 验证真实完成、质量和分区事实，不把完整网格冒充场或粒子求解。

`plan_rf_exact_birth_releases` 同时由 finite 与 deterministic 两个原生 solver 消费。只合并完全相同出生时刻的粒子，以17位秒文本保存时钟，保留完整6D、ID映射、物种及已有权重；原生顺序读回按原 source 行映回。deterministic 两个正式 wrapper 冻结同一 helper，release gate 的 v2 breadcrumb/result 按实际分组核对每行源与原生属性，仍在粒子 Study 前停止。分组不允许新相位模型或丢失粒子。有限体积源起点仅接受原 preflight metadata 充分绑定的体积状态，平面源原条件保持。

有限轨迹记录增加原解末库存位置及最后有限状态事实。当前未读取真实原生损失原因，因此末态不可把缺失轨迹默认当作电极损失；时间窗结束与更早结束均保留 unknown，接受条件另轴报告。公共母群核算明确未知不等于损失，完整权重不足时不可计算。正常 finite 的零出口诊断返回 `not_applicable` 与原因，不制造空图；缺字段、非有限值或不闭合母群仍失败。软件完成不授予科学或 Formal 资格。

已记录正常 N=100 两臂（070000／071000）各求场一次、粒子求解两次，精确出生分组使 release 特征100→1，构造耗时30.9666232→0.4850743秒，公开墙钟157.4430824→102.8825954秒；这是所记录同范围源构造对照，不是通用速度承诺，也不包含尚未生产对照的 deferredUpdates。源初态6D由规范源派生，不能把ID对应或软件通过写成原生初态6D独立验证。当前纯 MATLAB/软件回归与这些原生来源证据分别报告，不提升全尺寸精度或传输资格。

有限三维 SIMION 运行器在每个批次的进程实际退出后核验原生 Fly 完成、摘要粒子数和局部终态 ID，
并原子保存批次完成 receipt；owner 排空后由终态 manifest 绑定实际保留的 receipt、状态、摘要与 stdout。
重规划首批使用对应批次的稳定文件名。receipt 发布错误延后到已启动同批自然收尾之后传播。
开启机械出口时绑定其状态；qualification 和 solver_review 还要求批次轨迹并在终态 manifest 绑定；
compact 指标与出口诊断只消费状态和摘要。
PA basis identity、Fly 物理投影和源状态也冻结进运行输入；逐批源生成器及其共享依赖由 code inventory 绑定。
finite 3D、interface readiness 与 mass-filter 的正式批次通过公共 `Invoke-SimionBatchPhase` 统一首批观察、重规划与派发；
项目 owner 继续负责 IOB 准备、批输入和结果合并。
`workflows/no_collision_transport/run_simion.ps1` 的 `-ContinuationPredecessorManifestPath` 显式指定同项目终态前驱；
新 run 验证冻结 Fly 输入和原批分区，并通过公共 whole-unit plan 引用被容量保护及只读锁保护的完整批次。
全复用跳过 PA、IOB 和原生飞行；缺失的完整批次重飞。旧 run 若缺少完整批次 receipt 或冻结身份则不能复用。
这是软件完成证据，不代表科学通过。
三条 SIMION 消费者共用 `runtime/simion_field_checkpoint_support.ps1` 的原 producer 场检查点：
正常入口默认 `solver_review`，显式 campaign 的 retention 声明仍优先。
`-NativeFieldRunPath` 可独立于粒子源/Fly 前驱指定原终态场 owner；静态 GEM（含 include）、网格、
fractional surface、实际 Refine 参数和 SIMION 身份一致时不重求场。
原 manifest 绑定 Refine 完成事实及完整 PA family；读取先投影小元数据，再沿既有容量和公共 PA 保护取得原载荷。
Refine 已完成而布局失败仍保留场；Program 或注册模板改变时仅重建必要 IOB。
布局准备须经现有原生 inspector 从永久 IOB 路径真实加载通过；只有 build 成功或旧 receipt 缺少 inspect 事实时，
场仍可复用，但必须重建并检查 IOB。旧 partial 前驱没有 manifest 绑定的已完成场检查点时明确失败关闭：
提供相同场身份的 `-NativeFieldRunPath`，或从保留场的新 producer 继续；已处置或未知旧场不能直接复用。
合法完整 Fly 的原 receipt 复用保持有效，全部 Fly 已复用不受该新增场检查点边界影响。
全部 Fly 已复用时不读取场、不构建 IOB。旧 `simion_pa_basis_policy` 的 ensure/publish 协议已删除；
当前 fractional 几何不支持 surface=none 的 standalone cache 导出，显式旧策略报错并指向原 producer 检查点，
不改变 surface 或静默忽略 `require_existing`。新增场身份仅核对实际原生输入的小文件，PA 验证复用公共受保护读取，
不创建第二账本或复制不可变 cache 原生 family。原字段/布局准备事实不授予数值或科学资格。
有限三维原 CLI 的 `-ResumeFinalization -RunId` 读取 run 外小 Result，沿公共 owner 只恢复收尾；
阶段与总耗时随结果输出。显式前驱新 run 可复用完整 Fly 后重做分析，父终态保持原身份。
finite、`interface_readiness/run_simion.ps1` 与 `mass_filter_reference/run_simion.ps1` 使用公共
`Initialize-RunArtifactPowerShellOwner`／`Complete-RunArtifactPowerShellOwner` 绑定已有
package、容量 session、冻结 PS 入口、原生退出和实际 host release；项目保留器件执行与 host 归属判断，
不再自行拼装同义 request、wait、completion 或收尾恢复器。公共路径映射保留原 producer 来源，
收尾失败继续使用同一小 Result，未知 writer／host release 不释放原保护。
后两条原 CLI 的 `-ResumeFinalization -RunId [-ArtifactRootPath ...] [-ResultPath ...]` 不要求源表或其他科学必填参数，
不进入场或 Fly 准备；默认小 Result 位于项目 `scratch/workflow_results/<run_id>/result.json`。
已完成原生批次的原 PID／启动时刻与实际 host release 统一经 `simion_execution.ps1` 传入公共 owner；
三入口只共享该实际事实桥，不复制发布或恢复控制。两正式 CLI 的 publication／seal 失败和 unknown writer
已用无求解器 fixture 验证原 CLI 恢复、负科学结果保留和重复恢复终态字节不变，未据此补授真实器件资格。
2026-10-30 的小型原生机制验收用 66.228 秒完成新建 9³ fractional 场、Refine=1、封存和 alias 清理，
再由 child 完成必要 IOB 重绑定、原生 inspect 与 N=1 探索粒子 Fly；恢复 Refine=0，PA 写入被 guard 拒绝，
父 manifest 字节不变且 child 封存。producer／consumer 为 `20261030_012708__test__simion__rf-field-` 前缀下
的 `producer-d34d8b1b`／`consumer-d34d8b1b`；[原生结果](../../../../artifacts/projects/rf_multipole_ion_optics/runs/20261030_012708__test__simion__rf-field-consumer-d34d8b1b/summary.json)
与原日志保留。此前 TOF=0 splat 在 toy Program 显式 `maxdt=0.01 us`
（约 0.0044 mm/step）的限步对照中消失，终态 TOF=0.1 us、正确实例起始 splat=0。
该 fixture 未改变生产默认数值，只证明本次场／IOB／受保护 Fly 机制；不授予全尺度数值、器件性能或 Formal 资格。

两个生产COMSOL solver已共用项目`visit_rf_particle_windows`／`extract_rf_particle_records`：原解先按原路径保存，
再沿原解时间库存分窗读取，保留必要穿面邻接、区域极值、首末态及既有轨迹采样，不由绘图触发新推进。
窗口大小是I/O批量而非时间降采样；实际physics identifier与原source ID由消费者显式传入。
完整6D、晚出生、跨窗重叠和未知内部缺口有14项纯MATLAB回归；实际冻结wrapper及分析闭包8项Python回归通过。
接口就绪仍保留完整母群MPH与GUI重算合同，质量过滤／finite原源构造循环尚未改为顺序分块，不能据此声称源构造提速。
当前COMSOL原CLI尚未接通仅后处理恢复；持久化事实不代表该能力。

实际公共提取器另经`20261030_212512__test__comsol__rf-window-read-n3`验证：冻结本次两个helper后，
只读重开保存模型，以cpt／cpt2／cpt3分别消费201个原时刻、7个窗口；保留70／46／24个科学样本，
每个样本对照原生位置／速度，最大位置差1.7764e-18 m、速度差0，原ID与时刻保持。
最大窗口MATLAB结构7357 B仅指该窗口，不包含加载模型或进程内存；进程树峰值2,685,837,312 B，
原生区间39.348秒，无新增求解，已完成正常封存与释放。这证明真实分窗API接线，不是N100规模性能结论。

下表原生功能结果来自冻结旧几何；当前schema 3裸杆与新壳体不继承这些资格。
当前具名runtime与活动campaign均未获新裸杆几何的商业执行授权；历史run ID须重新定义并明确授权，旧冻结证据不自动继承。

| 结构变体 | 已有功能证据 | 保持的限制 |
|---|---|---|
| [四极杆](#quad) | 三种typed电气模式COMSOL/SIMION N=100功能传输；质量过滤理论与有限几何响应 | 连续数值等价未闭合；历史严格接口相空间比较FAIL；质量分辨能力未资格 |
| [六极杆](#hex) | 三种typed电气模式COMSOL/SIMION N=100功能传输 | 连续数值资格延期且未豁免；RF微小排序不稳定，保留原P0基线 |
| [八极杆](#oct) | 三模式N=100功能传输；单端贯通模型100 Da和524 Da的SIMION真实机械出口功能 | 出口贯通不授予边缘场、数值或下游捕获资格；双端贯通仍须按独立证据范围判断 |

## 资格边界

机械出口母群统计现复用公共particle_census的完整ID分类；构字典前拒绝重复source ID，
两传输运行器同时冻结该依赖并计入容量。原机械平面、孔径、正向夹持与terminal覆盖校验保持，
有／无出口两组旧census结果精确相同；non_exit_terminal是非出口终态集合，不等同已证实实物损失。
此处仍是unit粒子计数，不授予相对权重或真实电流资格。

冻结旧几何的共同三模式baseline只闭合功能分类。四极与八极原N=100运行两求解器均100/100且handoff身份一致；
六极原记录也已闭合功能传输。连续相空间的空间／时间敏感性与跨求解器比较保持
`INCONCLUSIVE_NUMERICAL_CONVERGENCE_NOT_ESTABLISHED`；工程六指标PASS只允许声明范围内的下游推进。
四极与八极两种加速模式的SIMION相邻空间档已执行，COMSOL空间档触发原预登记资源帽，保持
`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不事后抬帽或改写历史终态。

- 正式统计binding须在运行前冻结bootstrap、接受尺度、effect resolution与预算；缺失这些设置的旧run
  保持`POSTHOC_DESCRIPTIVE`，不能通过补写配置升级资格。
- 项目descriptor的`candidate`生命周期及execution profile中的可申请证据级别，不等于某变体或功能已验收。
  机械、GUI/CAD与本项目Formal尚未闭合；质量过滤、接口、三模式和组装结果不能互相代替。
- 当前传输base未启用碰撞、空间电荷或磁场，也未建立制造支撑、公差与机械装配资格。
  碰撞理论已收录，但不代表碰撞运行能力已建立。
- 配置编译和纯回归只证明输入、投影及机制行为；没有真实求解、数值矩阵或GUI/CAD证据时不得宣称对应层级通过。

## 当前组件边界与几何

当前作者与resolved合同为schema 3。可装配多极杆默认只发布真实杆系（`bare`）；只有显式声明
`cylindrical_grounded_shell`才构造接地圆柱壳。默认不随独立运行或装配场景变化，也不从数值域猜测壳。
多极杆不承载入口／出口光学板、连接套筒或下游透镜；这些部件由其实际提供者通过装配配方接入。

壳只声明内半径、壁厚和两个物理轴向端面，外半径及长度派生。`endcaps`中入口和出口各自可选，
出现时仅声明孔径半径与厚度；没有端盖就不生成实体。端盖从壳端面向内延伸，仅填充孔外、壳内的环形
区域，与筒壁连续相接且共用唯一0 V电极，不产生重叠体积或独立偏压端盖。孔径等于壳内径不是无盖的另一种写法。
此前1 mm绝缘间隙草稿已退役，不作为壳体参数或全仓默认。
这些是schema 3作者JSON输入，可直接声明后经`compile_governed`编译；装配配方引用冻结resolved，
不再覆盖器件尺寸。当前优化catalog不开放壳、端盖或数值域半径的自动搜索；显式壳体具名设计仍为候选，未绑定授权runtime。

数值域和`observations`独立于物理壳。源、handoff和census不再由已移除的光学板派生；裸杆也需要明确的
外部场边界，默认PA边缘不是实物。壳尺寸必须对应实际设计，不把既有20 mm内半径推广为最优值或固定r0倍数。
可调孔板即使电压为0 V也仍是独立光学组件，不因瞬时同电位并入壳体。

四／六／八极分别为径向阶数n=2/3/4，共用同一几何机制。当前杆系电气模式保留
`no_acceleration_full_length`和`segmented_rod_axial_acceleration`；内置出口孔板加速模式及私有terminal
组合入口已退役，不能静默替换为另一科学实验。矩形专用参考仍服务原接口／质量过滤workflow，
不作为新可装配多极杆的隐含外壳或默认光学部件。

旧三模式、闭壳、单／双端贯通和出口孔板运行保持原输入、原owner与资格；它们是冻结旧几何证据，
不自动成为schema 3裸杆或新壳体的求场、飞行、数值、制造或Formal验证。本次先闭合几何，未开展跨求解器差异研究。

[壳体CAD检查](../../../../artifacts/projects/rf_multipole_ion_optics/runs/20261027_143100__test__cad__multipole-enclosure-r02/summary.json)
已完成bare、开放壳、前盖、后盖、双盖及缩放双盖六种构型：bare无壳实体，其余为唯一连续接地域；
各实体对正体积交叠和中心孔交集均为0。五份STEP冷导入均为1域，最大体积回导差约5.10e-11 mm³，
不作制造容差声明；独立manifest核验13项输出。该证据仅覆盖壳体，不授予求场、Fly、数值或Formal资格。
首轮在构建几何前因MATLAB目录helper遮蔽失败，保留执行失败证据，
不记为物理失败。当前壳体请求只把数值域上界延至82.9 mm以容纳既有最粗0.4 mm轴向格的出面观测余量，
实物端面仍为82.1 mm，源、handoff与census不动；其壳体尺寸与该CAD检查相同，输入全文身份不同，不混用hash。

[完整器件几何检查](../../../../artifacts/projects/rf_multipole_ion_optics/runs/20261027_144000__test__cad__multipole-full-geometry/summary.json)
进一步使用真实生产分段helper构造bare和双盖两种完整器件，各含32杆段；双盖的3个接地实体属于同一电极。
分别覆盖496／592对实体，原生实测bbox证明496／560对分离，其余32对经真实Boolean求交，正体积交叠均为0；
独立manifest核验8项输出。本run不重复STEP、求场或飞行。它与上述壳体连续性、通孔及STEP证据共同闭合
本轮几何干涉检查，不代表制造、数值、Fly或Formal资格，也不回写旧冻结几何的四处交叠结论。

当前census只接受实际回调状态夹住观测面的前向穿越（含terminate最后状态），不按近面阈值或从handoff
直线外推补造命中。[供应商CLI回调检查](../../../../artifacts/projects/rf_multipole_ion_optics/runs/20261027_133140__test__cad__multipole-enclosure/results/agent4_callback_acceptance.json)
覆盖4场景及重复run；无PA夹具只验证回调状态机，不建立真实PA边界backoff或Fly资格，未实际越面仍为未观测。

接口就绪 COMSOL 入口及有限三维 COMSOL／SIMION 运行器的失败发布若再次异常，仍传播原始错误及类型，
并在异常的`failure_closure_error`中保留发布失败原因；有限三维入口的host释放异常另记`host_release_error`。
没有原始失败时，host释放异常仍向外传播，不能变成成功。环境恢复／别名清理及原资源释放继续沿各自入口执行。
实际PowerShell catch／finally回归覆盖正常路径、主错与发布／释放再次失败，不调用商业求解器，
不改变这些workflow的科学输入、成功判据或现有资格。

## 机器权威

| 职责 | 入口 |
|---|---|
| 身份、结构变体与发现能力 | [project.json](../config/project.json) |
| 变体极数、电极数与物理设计校验 | [家族合同](../config/contracts/family_contract.json)、[项目设计Schema](../config/contracts/design_profiles.schema.json)、[设计解析器](../runtime/design_profile.py) |
| 具名设计与typed电气模式 | [design_profiles.json](../config/design_profiles.json)、[operating_modes.json](../config/operating_modes.json) |
| 完整runtime与粒子源绑定 | [runtime_profiles.json](../config/runtime_profiles.json)、[particle_source_profiles.json](../config/particle_source_profiles.json) |
| 三变体传输数值注册表 | [COMSOL](../config/comsol_solver_numerics.json)、[SIMION](../config/simion_solver_numerics.json) |
| 四极机械、变量、源及专用workflow合同 | [quadrupole/config](../variants/quadrupole/config/) |
| 六极机械、变量及工程合同 | [hexapole/config](../variants/hexapole/config/) |
| 八极机械、显式壳体、来源模型及工程合同 | [octupole/config](../variants/octupole/config/) |
| 可执行入口与绑定要求 | [execution_profiles.json](../config/execution_profiles.json) |
| 旧资格、原身份与冻结记录 | [历史索引](history/README.md) |

活动runtime编译完整输入后执行；不能用命令行自由覆盖几何、RF/DC、源或已绑定数值语义。
公共命令预览通过execution profile的`runtime_binding`调用本项目
[`resolve_execution_binding`](../runtime/runtime_profile.py)，具名runtime与campaign均复用既有解析器；
本项目提取实际结构及campaign的`authorized_run_id`，公共编译器负责身份、能力归属和受保护上下文校验。
纯回归覆盖三种结构、campaign身份、未知与跨结构拒绝及真实CLI预览；`authorized=False`仍可预览，
实际商业执行继续由`validate_pilot_budget`失败关闭，不改变上面的未授权结论。
专用workflow的允许输入与探索数值范围见软件说明及其机器合同。模型参数、阈值和正式证据都不从本文推导。
旧资格JSON保留原owner、profile名、SHA和run；它们不是可复制改名后执行的新资格合同。
新的运行合同若引用旧源数据，必须显式验证该来源身份，不能给历史数据补一个新owner。
活动设计由当前家族合同与设计解析器校验；历史owner与资格只从封存记录追溯，不允许新run回写到旧owner。

<a id="quad"></a>

## 四极杆

四极杆保留无碰撞传输、接口就绪、质量过滤和同求解器数值研究等科学workflow。
`quadrupole_official_transport`矩形参考服务旧接口／质量过滤的相应作用域，不是圆柱三模式实验端口；
`Mode`或粒子数不能切换科学声明。接口历史严格相空间比较FAIL，当前机械base仍待新资格。
RF+DC已有理论和有限几何功能响应，网格、跨求解器一致性及质量分辨能力未闭合。

冻结旧非typed出口孔板设计曾因`axial-drive potential profile does not accelerate selected charge sign`
被编译器拒绝。此负结果保留；内置孔板模式及其活动profile已退役，不能改物理符号或换成裸杆来制造通过。

质量过滤L0参考实现仍在[专属workflow](../workflows/mass_filter_reference/theory.py)，其源由
[official_particle_source.json](../variants/quadrupole/config/official_particle_source.json)声明，确定性采样由
[公共ion_release](../../../common/ion_release/README.md)提供。旧150 mm碰撞脚本不是活动合同。
旧矩形PA导出／比较三脚本已退役，不恢复硬编码0.2 mm基线的GEM文本替换链。

质量响应的L1、SIMION、COMSOL及响应比较共用`core/mass_response.py`准备结果，再复用公共
`half_height_width`计算`sampled_mass_response_linear_half_height_v1`。旧
`observed_half_maximum_band_Th`仍是全部半高样本的采样包络；新
`interpolated_main_peak_fwhm_Th`只取首个全局最大值两侧最近半高交点的线性插值，单位Th。
多个峰之间的空隙不会并入该主峰宽，等高plateau仍按同一定义处理。未夹住左／右／两侧交点时明确
记录缺侧；全零响应为`unavailable_no_positive_response`，峰位、采样带与插值宽都不可用。
输入质量点必须有限、严格递增且唯一，传输分数必须有限并在`[0,1]`内；原功能判据保持，
新诊断的`resolution_claim_allowed=false`，不能据稀疏采样插值建立质量分辨能力。

ION11第二列实际为`mass_amu`，不是任意电荷态的m/z。当前质量扫描只接受正单电荷：读取源、
生成两求解器扫描表及独立SIMION结果分析都校验有限正质量与精确`charge_state=+1`，不经整数截断，
不自动除电荷。L1源合同同样拒绝布尔或分数电荷。合法+1粒子的表字节和既有科学计算保持不变，
生成元数据注明该质量与Th数值相容范围；这不建立多电荷运行资格。

三个原生／比较PowerShell入口在运行前使用已有冻结包机制登记实际分析源码，分析从run-local包执行，
包含公共峰函数及项目传递依赖，禁止回到活动仓库导入。L1仍使用原积分器与科学配置；其CSV冻结后由
同一模块的纯分析分支在隔离包内生成JSON和图，两者消费同一份prepared结果，run config和manifest
登记CSV、源码、模块来源与Python依赖环境。比较表保持共同七质量点，图使用各来源的实际完整采样网格。
COMSOL／SIMION质量过滤运行器只声明冻结文件闭包，模块探针由此派生并保留包级检查。
隔离helper保留原错误文案，以`Exception.Data['exit_code']`传递分析进程非零退出；SIMION不再解析文案，
依赖探针、源码篡改和缺失仍直接失败。冻结包回归含真实隔离执行、物理PASS／FAIL和仅匹配文案的拒绝。
COMSOL的canonical state逐质量统计现也纳入同一`analysis_runtime`包，不再仅保存分析器`.txt`后调用
活动源码；长期回归使用七质量点、每点四个原ID的合成state，实际执行state metrics→响应→峰宽／功能
结果。冻结后改动临时活动源码不改变结果，删除冻结模块即失败；该fixture的插值宽为1.75 Th，
只验证分析接线，不代表真实COMSOL飞行或质量分辨能力。旧冻结run、receipt与已有资格不回写。

L1在冻结输入前通过公共`New-RunPackage`建立checkpoint三件套，并保留公共retention／capacity合同。
输入冻结、分析准备、计算或分析执行失败时由`Complete-FailedRun`记录阶段、原异常和部分冻结输入；请求源路径
与实际冻结输入分别登记，不复用原run ID。成功发布和物理FAIL保留原功能口径；收尾自身失败不吞原异常，
已发布终态不被异常收尾覆盖。完整`run()`回归保留配置的N=100／29质量点，以合成响应验证实际冻结分析、
PNG与三件套发布，未改变积分器、源采样或科学输入。

此前47项求解器无关回归覆盖手算曲线、平台／多峰、截断／全零、输入域、+1源边界与三个真实分析入口，
并验证冻结模块来源及篡改／缺失拒绝。原合同每质量N=100、29点的完整L1临时运行功能PASS：采样带
为99.5–103.0 Th，另报插值主峰宽4.1227490996398615 Th；11份分析源码快照与7个实际模块来源登记，
5项输出的manifest完整核验PASS，临时run已清理。该验证只关闭分析重放，不把原进程中的源生成／积分
称为隔离执行，也不代替原生SIMION／COMSOL重跑、网格收敛或质量分辨能力资格。

N=1000 COMSOL bridge曾在release构造阶段资源中断，向量化release候选未证明等价；两者都不是生产路径。
`analysis/sampling_analysis.py`暂保留具名N100／N1000历史同源统计CLI职责；当前仅发现私有统计测试
直接导入，不能据此认定存在活动生产调用。bridge预登记绑定旧`common/multipole/sampling_analysis.py`
路径及SHA，但该运行未到粒子求解、没有N1000结果，不证明当前源码与旧冻结副本相同或成功重放。
正确工作区保有两个SIMION N100／N1000及两个COMSOL N100的具名run，小输入／结果身份已核验；
各code_inventory不含sampling分析器，预登记的A3B210…旧源码仍无已验证副本。
待原冻结分析及输入可独立重放，或完成同输入等价替代后，连同私有测试
退役此CLI。保留不构成永久兼容承诺，也不授权恢复N1000研究。
相关数值、释放诊断及旧接口证据见
[四极历史](history/retired_projects/rf_quadrupole_ion_optics/docs/history/20260911__solver-sensitivity-and-retired-interface.md)。
当前适用操作保留在[COMSOL](COMSOL.md)与[SIMION](SIMION.md)说明中。
既有四极→oaTOF功能链不授予连续相空间、分辨率、机械或整机Formal资格。

<a id="hex"></a>

## 六极杆

六极杆保留理想场、圆杆场筛选与有限三维传输的模型层级。三模式功能证据不改变
`DEFERRED_NOT_WAIVED`／`INCONCLUSIVE`的连续量资格。相位匹配的RF幅值—频率筛选及N=1000复核
显示微小排序不稳定，继续保留P0 RF基线，不据此优选参数或扩展扫描；证据见
[RF复核](history/retired_projects/rf_hexapole_ion_optics/docs/history/20260803__hex-rf-drive-phase-matched-h15-n1000.md)。
源能量与加速方式的比较保持描述性，数值只见
[源能量记录](history/retired_projects/rf_hexapole_ion_optics/docs/history/20260803__multipole-four-mode-source-energy-h15-n100.md)。

旧oaTOF零长度直连、接地圆套筒与带孔法兰结论属于冻结旧几何。当前外部部件及直接位姿由装配配方声明，
零间隙仅在真实端面上的独立导体互不接触时允许；发生接触须显式修改几何或间隙，具体距离没有默认值。
旧逐臂profile、预登记和专用诊断测试的结论从
[退役campaign](history/retired_projects/rf_hexapole_ion_optics/docs/history/20260802__retired-comsol-qualification-campaigns.md)
追溯，新的研究只使用当前注册的runtime与窄变量campaign，不恢复一次性诊断树。

<a id="oct"></a>

## 八极杆

### 冻结机械出口证据

旧闭壳的内部handoff与最外端面不同。历史单端贯通运行
`20261022_210633__sim__simion__octupole-through-exit-n100`曾完成原100 Da母群越过82.1 mm外端面，
64项manifest输出通过；这些原ID、6D状态和时钟仍可作为明确来源的只读输入。
旧贯通作者与分支不再是当前运行接口，也不被改写为默认裸杆验证。

schema 3的同一提供者始终发布实际入口／出口：裸杆按杆端面及开放杆包络解释，有壳按壳端面与
实际端盖孔或开放内孔解释；释放、观测和机械端面分别命名。两端端盖只是同一壳体的可选构造。
原单／双端配置、粒子母群及资格从冻结记录追溯，不在当前代码保留兼容模型。

### 524 Da工况与来源模型比较

历史`octupole_through_exit_no_acceleration_524da_n100`绑定独立
[524 Da源](../variants/octupole/config/sources/planar_524da_2ev_n100.json)和具名数值profile，复用单端贯通设计。
旧100 Da源保留；相同位置、方向、ID和出生抽样下，质量改为524 Da、仍为+1及2 eV，速度按`sqrt(100/524)`
缩放。RF与机械不随质量调优；观察窗按相同轴向速度尺度扩展，不保证传输或收敛。
理想八极伪势深度在固定RF与几何下按`1/m`变化，因此同一明确物种不等于下游捕获保证。

旧owner的运行`20261023_084802__sim__simion__rf-octupole-ion-optics-through-exit-no-acceleration__resolved-l3`
完成新求场与N=100飞行，100个原始ID全部真实越过`82.1 mm`外端面、非出口数0，52项manifest输出校验通过。
该结果只关闭上游真实出口功能。旧100 Da→IP的74入HP／0捕获负结果保留；524 Da注入和MR交接由
[集成状态](../../../integrations/docs/INTEGRATION.md)维护，不以新上游配置关闭旧负结果。

平面冻结源与轴向体积快照的N=1000 SIMION两臂均全传输，出口位置与角分布不同；这是描述性来源模型比较，
详见[源模型记录](history/retired_projects/rf_octupole_ion_optics/docs/history/20260911__source-model-comparison.md)。
后续更改该比较仍须固定设计、下游端口、数值及完整粒子母队列，仅改变receipt绑定的source model。

## 已记录轨迹相位诊断

[`plot_transport_phase_diagnostics.py`](../analysis/plot_transport_phase_diagnostics.py)保留为既有描述性分析入口，
唯一模块命令见[README](../README.md#工作流入口)。它读取两份已记录轨迹，以相同原始ID比较；有限状态、
原记录顺序中的严格前向位置与递增时间、完整显示网格支持区间均须满足，重复或反向轨迹不排序去重，
缺支持区间直接失败，不补造终止后位置。原采样步长、平面选择、相位公式和差异阈值保持；零方差相关
发布null及状态，JSON禁止非有限数。

输出记录两份输入的实际字节/SHA、观测ID、单位、显示网格及各粒子支持区间。当前默认设计只决定诊断
平面与RF周期，不证明原CSV使用同一设计；母群、frame与clock证据未提供时均明确为unspecified，
相同ID不授予共同源、配对物理试验或科学资格。旧`plane_metrics`及`transverse_difference_onset`字段
继续供[接口评估](../workflows/interface_readiness/assess_integration.py)消费。

长期验证入口为[`test_interface_integration_gate.py`](../tests/analysis/test_interface_integration_gate.py)，
覆盖真实`--help`、CSV→JSON/PNG→接口评估CLI及无效窗口/轨迹拒绝；该层不运行求解器，不授予native或Formal资格。

## 部件与组装边界

本项目发布原生机械、端口、驱动及canonical handoff；连接器、位姿、公共电位、时钟和下游场域由
[组装规范](../../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md)与集成配方表达，不反写提供者base。
IP自身提供的裸八杆导引与本项目八极杆保持不同来源，不能只因杆数相同而互换模型、驱动或粒子母群。

提供者迁移的关闭条件是冻结输入下几何、驱动、端口、完整源／handoff与绝对时钟对照成立，
原消费者结论保持，新增接收端口和真实物理链另行验收。组装纯回归与重启恢复不授予器件数值或Formal资格。
跨器件执行与当前任务进度只查[集成状态](../../../integrations/docs/INTEGRATION.md)。

## 开放任务

1. 新出口相空间研究按[通用方法](theory/exit_phase_space_control.md)先固定真实下游接受尺度、唯一变量、
   损失约束、共同幸存者与相邻数值档，再选择具名campaign；本页不预选加速模式或最优参数。
2. 连续量、逐粒子等价与统计资格须先冻结误差预算和bootstrap设置；资源受限模式使用有依据的新预算
   或替代离散策略，不改旧run的预算或资格。
3. RF-only、RF+DC、轴向加速与各结构变体分别建立相称Candidate证据；机械、GUI/CAD与装配闭环后才讨论Formal。
4. 碰撞冷却须由当前机械base建立独立物理合同与workflow；气压、分子流等新增物理按需求增加，本文不预建能力。
5. 下游或整机性能研究由集成任务明确目标、指标和授权，功能贯通不自动扩展为优化或N=1000统计工作。

## 产物与历史

新运行的owner是`rf_multipole_ion_optics`，只写`artifacts/projects/rf_multipole_ion_optics/`。
旧三个项目的run、manifest和冻结资格继续使用原身份与原artifact解析位置，不提供猜测旧路径的fallback。
[历史索引](history/README.md)登记原owner、原路径、固定Git版本及迁移映射；冻结内容不改字节。
普通README／PROJECT编辑由Git保留版本，不因本次合并再复制一套全文快照或逐会话状态历史。

圆杆 L2 传输使用已认证 field-screen run 的冻结设计、合同与采样结果，要求与当前解析设计的真实杆阵列、坐标、r0 和极数一致，并仅采用杆半径比例严格匹配且通过场筛选检查的唯一候选；缺失或不匹配时拒绝，不以最优候选替代既定几何。场筛选为带接地外边界的二维场，传输使用其有限余弦谐波沿 z 均匀延拓，不代表三维真实求解或科学资格。当前 octupole 的既有扫参不含基准设计比例 0.5，需要匹配该设计的已认证场数据。
该近似使用 20 mm 接地边界，不等同于裸 enclosure 的完整场；传输截断为有限余弦谐波，不使用正弦谐波。
L1/L2 传输将身份输入冻结到本次 run；圆杆 L2 在冻结后核对场源 manifest 的记录并直接分析冻结样本，验证所有选定比例样本与真实杆阵列及完整合同采样网格一致。


### 接口正常链的冻结执行与收尾

`workflows/interface_readiness/run_comsol.ps1` 经公共运行 owner 执行；正常入口显式接收 `-LimitsPath`（公共 native Limits 的 JSON），并冻结该输入及由现主机 policy 派生的实际预算。机器 profile 的 `comsol_execution_limits_path` 为必填，缺失时不能编译为可执行计划。源码根、产物根、执行根由现公共路径上下文一次解析；持久配置保留清理执行 alias 后仍可消费的输入和包路径。

发布设计的新鲜度检查由 `New-RfPublishedDesignFreshnessPackage` 从所选项目纯解析器冻结并执行。接口 COMSOL/SIMION 和质量过滤 SIMION 消费实际检查后的 resolved 文件，不在检查后回退当前默认值。COMSOL 后的 metrics 与粒子状态合同同样从冻结 Python 包执行；GUI 读取本次冻结 config 指定的设计和接口，loader 只接受现 resolved schema 3。

原 CLI 的 `-ResumeFinalization -ResultPath <稳定小Result>` 仅继续公共 owner 收尾，不重新求场或飞行。该模式只允许恢复参数及 Python/RunId；科学参数不能被静默忽略。native/GUI 的实际 completion receipt 进入公共聚合，继承的同 token 去重，writer 未知仍保留保护。

确定性四极杆和有限三维 solver 使用同一项目终态分类器。全局时间窗结束且晚出生粒子尚未获得完整运输时长时记 `unknown`，无终止原因不等于 electrode loss；原接受面和几何拒绝事实不变。canonical 状态及 metrics 分开报告 accepted/lost/timeout/unknown，原母群分母、ID、出生/终态时钟及命中率保持不变。软件接线、原生求解、GUI验收与科学资格分别报告。

## 机器能力与解析输入

正常 wrapper、预算和 COMSOL prepare 共同消费本次 resolved runtime 与 input_definitions；授权及源身份仍在原边界校验。
能力查询与执行编译见[公共合同](../../../common/contracts/README.md#执行dry-run)；READY 仅描述声明条件。

## 显式研究请求的位置

普通只读 campaign 可由原 `runtime/run_simion_transport_campaign.ps1 -CampaignPath <绝对JSON路径>` 接收。
单文件名仍选 config/campaigns 具名案例；其他相对路径以仓库根为基准。JSON 内资源继续用原项目／仓库基准，
不按请求文件目录解释，也不允许引入外部代码。status、analysis preflight 与执行共用同一定位 API。
正常入口保留读保护，冻结本次解析；输出仍由原 managed run owner 决定，不能覆盖正在读取的请求。
标准案例、预注册、物理支持域与商业授权保持原合同；位置可读不等于获准运行。
