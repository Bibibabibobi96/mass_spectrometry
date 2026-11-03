# Phase 02：提供者／后端解耦与公共命名语义闭合

DOC_STATUS: ARCHIVED_READ_ONLY

证据快照：2026-11-04。固定B7的两端完整软件与限定原生证据已独立审计；本记录归档P2迁移里程碑，当前状态继续查路线图与集成状态。

## 对象与边界

按2026-11-03全局V6／P2修订2继续既有任务，命名复核起点为
`2de6385c1989ac9eb5f988adbb86fd4043e387c4`，最终被测代码固定为
`b7e3044710e003af8183d897d9fd0753e1e151ff`。本记录只关闭P2声明的迁移与验证范围，
不改变P1冻结证据、旧run、R01–R20总要求或P3–P5责任，不授予Formal资格。
任务分支为`task/phase01-installed-scientific-core`；未合入master。
原V6 `04_PHASE_02_GOAL.md` SHA256为
`44a38c134355499b7ab6b7dd46dc1e84200a1ae7563bbbbd53d96fd7aa1ceeeb`；
十八项完成条件、B01–B40及R01–R20阶段责任均按原文审计，不把已做范围另定义为目标。
当前科学链边界只由[集成状态](../../integrations/docs/INTEGRATION.md#当前边界)维护，
RF和OA自身能力分别查[RF提供者](../../projects/rf_multipole_ion_optics/docs/PROJECT.md)与
[OA提供者](../../projects/orthogonal_accelerator/docs/PROJECT.md)，本记录保留本次固定验收事实。

## 实现与命名迁移

- RF/OA真实提供者拥有唯一中立拓扑，科学组键为`(instance_id, electrode_group_id)`；
  RF极性组、物理成员与后端槽位分别表达。分段物理合法性不再由SIMION容量决定。
- 新component3／plan5／binding2及单反射request10采用新字段；已用component1/2、plan3/4等
  旧版本按原义读取，新writer不双写旧同义字段。未知版本、混版、覆盖或来源不符明确拒绝。
- OA二区／三区统一repeller、intermediate_grid_1、可选intermediate_grid_2、exit_grid。
  旧component/theory的grid2和旧sectioned geometry的grid2分别映射，不做全局字符串替换。
- 真实RF→OA准备、场、Program、绑定与冻结消费者已切换；保留完整父装配、局部切边、
  实例姿态和碰撞检查，未请求源／场时不暗采样或求解。映射与basis变化按身份使缓存失效。
- 本链中立状态和particle_census实迁；RF完整事件协议归`rf_event_table_validation`，
  ION11解码与位置Rr+t／速度Rv的六维frame变换职责分开，原ID、母群、权重和仪器钟不变。
- 三区时间尺度明确为`time_scale_s_sqrt_v_per_mm`，公开提取坐标说明frame／原点／方向，
  不改变原公式与数值。新使用的峰结果强制既有方法、FWHM、时间参考、质量轴／标定和样本metadata，
  数学委托唯一实现，未知时钟或未标定不伪造合格，旧输出保持原义。
- 公共CLI明确charge／format／RNG；import `msplatform`、发行`mass-spectrometry-analysis`保留，
  更新范围说明，未来发行名决策及剩余活动桥退出最迟P4。其余峰／状态消费者具名留P3/P4。

## 最终完整软件验收

| 对象 | scope／并发 | 结果 | 父测试 | subtest | 公开墙钟 |
|---|---|---|---|---|---|
| 本机B7 | Repository／8 | 50 PASS、12 NOT_APPLICABLE | 6473：6452成功、21跳过 | 7012成功 | 2029.1888673秒 |
| 远端B7，run41666241674 | Repository／4 | 50 PASS、12 NOT_APPLICABLE | 6473：6251成功、222跳过 | 6745成功、9跳过 | 3422.0074453秒 |

本机摘要内部2027.616126秒；公开墙钟由外层单调时钟覆盖命令启动到实际退出。
本机Python3.11.0／PowerShell7.6.9／Ruff0.15.22／pywin32 312，pip check通过。
开发venv的核心来源为src，不能将其称为普通安装证据；本轮独立临时venv执行的普通
wheel/sdist、重建wheel与树外消费者测试实际成功163.208489秒，实际冷冻结方法成功23.427070秒。
这些测试检查site-packages／snapshot origins、schema资源与本地ref、Unicode／空格和冷-I执行，
缺失backend／component3资源负例失败关闭，不借作者树或当前安装补洞。

本机运行前后HEAD、clean工作树、index、pyproject与依赖锁一致。
index SHA256 `56CB1256C213BCDFD671A5AD5E40C34605912690B831F10F229DCB6C979CB292`；
lock SHA256 `020CBECFB401F7A202BFDFCC8D48B1A9AD5860C808C6CFC46A2DF36B9167B721`。
原始outcome中的source_sha=null保持；由固定checkout、全过程冻结、前后身份和逐文件SHA绑定，
不伪造import时哈希。父测试定位键无重复，未记录fixture／loader错误或test_evidence_error。
NOT_APPLICABLE、测试skip与未执行分别报告。远端完整工件ZIP的SHA256为
`431e09afe7aeaff5cfc59d266f2bd98a2440eddd4e57e1666eab0fccd67425d5`，与GitHub公布digest一致；
artifact13249973306、run41666241674均绑定同一B7任务分支。远端Python3.11.9／Windows26100、4逻辑核，
内部墙钟3419.723599秒；不同主机与本机结果不构成受控并发性能对照。
两端6473个父定位键及对应测试源码SHA全部相同：6250项双方成功，202项本机成功而远端跳过，
20项双方跳过，1项本机跳过而远端成功（symlink能力）；双方跳过的3项原理由不同。
远端独占Dirichlet阶段被选且软件阶段PASS，但原六方法均因官方SIMION Lua CLI不可用而skip，
不得称远端原生六项实际通过。原生数值证据来自本机同源实际执行。
远端skip还包括plain Lua、外部历史载荷、8.3路径、CLOC和SLreader等条件，不能全归商业软件缺失。
远端普通wheel/sdist与冷冻结方法均实际success；完整逐键差异与原理由由双端对账工件保留。

本机独立审计核492份实际测试源码SHA、38次调用与76份start/completed收据，
所有被选阶段及其依赖顺序正确；22组短method名碰撞按源码分开，不误作重复删除。
相较0466341a新增8个父方法（RF3、parallel support4、Changed路由1），无方法删除。
四份变更测试源码涉及共同178个父方法；两项Dirichlet由旧error转为新success是改源后的结果，
不标作同源偶发重跑恢复，也不把新测试计数冒充纯改名增加的覆盖。
本机21项skip分为：宿主不可建symlink1、需公共原生许可与显式授权6、Windows SIMION N1显式opt-in探索1、
已退役历史中心PA1、未显式SIMION_EXE2、已退役外部A父载荷2、未选择native SIMION6、
native-97事后检查opt-in1、未配置三区T5 receipt1。每项保留原test_key和原reason。

## R0、真实原生与资格限制

历史partial／owner／prepared-joint／RF超时保留原FAIL与UNKNOWN根因；修复受控夹具现场保全、
原错误与secondary诊断区分、自有进程归属及确认退出，未推广为生产求解器强杀。
R0的有界UNKNOWN裁决关闭已核验的取证、进程归属、失败保全与测试身份子包，
不声明全部历史故障原因已证明或生产求解器已根治。
没有用延长原期限、删除科学断言、默认降并发或一次重跑抹掉旧失败。
默认异步I/O的原生卡顿另保留现场；官方排错开关false在显式微型fixture中读回验证，
不是全局生产策略，也不能由有限对照推断唯一历史根因。
原各轮精确FAIL／后继修复及差异仍可从
[B7固定路线图](https://github.com/Bibibabibobi96/mass_spectrometry/blob/b7e3044710e003af8183d897d9fd0753e1e151ff/docs/ROADMAP.md#科学核心与平台边界迁移)
追溯，不修改原报告或用后继PASS抵消旧FAIL。

本机完整Repository中的原Dirichlet六方法全部实际成功，另五非法输入subtest成功，0skip；
suite13.182秒，stage19.857414秒，公共pa_refine资源已释放。原六方法科学AST与120秒保持，
直接GEM／Refine与最终数值断言仍执行。辅助诊断的原句柄确认直接子进程退出，但没有额外
未记录的invocation绑定或任意未知后代全树证明。细节见独立原生审计。

真实三区N100映射A/B仅反序RF的8个native标签，原源、几何、驱动与钟不变；
各14批实际Fly和14批显式保存回放，原15项功能合同通过，100个ID终态闭合、36探测／64其他，
35个ID有完整六事件顺序。37组85231次所记录数值比较严格无差异。
原N100八桶场观测合同仍INCONCLUSIVE，其中两个pulse结束窗口没有合格记录，不能插值或补写PASS。

独立非粒子场run `20261103_231500__analysis__simion__phase02-field-io-false`完成原三间隙点、
结束前／恰好结束／结束后三个相邻binary64时刻及A/B两种映射的18次实际wb:efield查询。
六段科学代码原字节保持，不伪造粒子ID或历史；pulse状态true／false／false，A/B对应语义和数值严格相同。
从冻结驱动、参考电压与实际时刻独立计算phase／coefficient，并按原成员顺序从实际basis重组gradient，
均精确一致；单位／坐标换算最大1ULP差如实保留。
四次构建／GUI操作退出0，52项保护和资源释放，公开528.113933秒，未新增Fly／Refine。
计划文件有两个同路径同哈希输入标签，场输出各唯一；表示局限未影响本次消费，不宣称所有manifest路径唯一。
原A/B保存工作台另经GUI检查并自然退出，未保存原文件。有限证据不证明全空间PA精度、
所有粒子历史、数值收敛、独立PDE重解或Formal资格，原NOT_QUALIFIED保持。

## 成本、退役与后续责任

原15分钟全软件目标未达；本机8路与远端4路不同主机，不计算受控加速比。
同map FieldDesignOnly无新增Refine／Fly／native，功能复用通过，但338.988秒超过原300秒envelope，
性能负结果保持。两端阶段等待／执行／清理分量均由原摘要保留，末端等待与慢分片分别报告。

本机最慢分片`instrument_assembly_integration__tests_04`墙钟1121.825788秒，其中执行1117.223866秒、
准入等待2.606646秒、清理1.866310秒；其派发前排队29.153068秒。
单反射tests_01墙钟951.865905秒，派发前排队824.250396秒；最后结束的是`rf_multipole_domain_tests`。
各阶段重叠，累计准入等待122.570335秒不是串行关键路径，也不从它反推CPU竞争原因。
远端同名最慢集成分片805.697130秒，其中执行800.845628秒、准入等待2.148585秒、
清理2.534310秒；派发前排队824.279412秒。远端最后结束的同样是RF domain，
累计准入等待118.118745秒，不能与本机差值组成受控性能因果结论。

本批替代算法与无消费者桥退出；仍有活动消费者的有限单向桥具名、有条件且最迟P4退出，
历史版本读取与冻结实现保留，不以静态搜索零命中直接删除公共API。
一次性作者退役按各精确收据记录，归档成本与删除逻辑字节分列：

| 对象 | 移除文件／逻辑字节 | 新增恢复载荷字节 | 保留／恢复 |
|---|---:|---:|---|
| 早期point诊断作者 | 29／431221 | ZIP83747 | 23份ZIP、6份既有冻结run精确副本 |
| header／INERT作者 | 5／43076 | ZIP3389 | 3份ZIP、2份既有封存输入 |
| membership作者 | 3／69478 | 0 | 既有冻结run精确输入 |
| GUI holder作者 | 1／6084 | 0 | 两次GUI检查已有精确副本 |
| 非粒子作者 | 18／433325 | 344242 | 必要归档加既有冻结输入，净载荷减少89083字节 |
| save控制作者 | 6／59611 | 59611 | 精确只读归档，净载荷0 |
| WCT作者 | 1／6776 | 6776 | 精确只读归档，净载荷0 |

原run、PA、IOB、失败与输出保留，精确哈希和恢复位置均有退役收据；额外小JSON／报告成本未计入表内。
不把逻辑字节当实测物理磁盘释放。旧rev4的8份PA共308274072逻辑字节仍保留：
公共处置因缺封存heavy身份失败关闭，没有私改pin／账本或删除，旧处置FAIL仍在。

R01–R20整体仍OPEN。P3负责真实handoff／钟／恢复，P4负责推广、剩余桥退出和原反馈预算，
P5负责新器件／后端压力与整体要求闭合。新代码完整验收与最终docs-only后继分别绑定，
不能把文档后继当作重新执行了全仓测试。

## CLOC与证据

实读 `cloc-phase02-2de-to-b7e30447.log`：CLOC_DELTA=PASS，2de6385c1989ac9eb5f988adbb86fd4043e387c4 → b7e3044710e003af8183d897d9fd0753e1e151ff，CLOC2.10、clean；logSHA256 `80bbed1d24d6174a5bfff91e867b34fa45731e3fb5bd43a0df2c7a87469ea55c`。独立校验每语言delta=结果−基线、语言合计及production+tests=total全部成立；unclassified全0。

总代码421835→428568（+6733）；production256094→259637（+3543）；tests165741→168931（+3190）。总文件1644→1665（+21），生产+13、测试+8。此为整个指定P2基线跨度，不混046→b7较窄delta。

分类：活动execution_profile入口及run_/verify_ PS为production，即使在tests树内；fixture/test_support/test命名为tests；普通tests/support不自动算测试。artifacts/generated/vendor/run、任意docs/history、根scratch等明确排除；once-off原生author及归档不冒production计数。完整过滤如下（原文）：

```text
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```

逐语言完整三类表（files/blank/comment/code的baseline→result(delta)）：

### total

|Language|Files|Blank|Comment|Code|
|---|---:|---:|---:|---:|
|JSON|258→264 (+6)|0→0 (+0)|0→0 (+0)|35673→38132 (+2459)|
|Lua|100→100 (+0)|369→369 (+0)|749→749 (+0)|11425→11425 (+0)|
|MATLAB|160→160 (+0)|1016→1016 (+0)|1983→1983 (+0)|17783→17783 (+0)|
|PowerShell|146→146 (+0)|1120→1121 (+1)|1404→1405 (+1)|47445→47503 (+58)|
|Python|967→982 (+15)|26306→26661 (+355)|32179→32873 (+694)|308805→313021 (+4216)|
|SIMION GEM|10→10 (+0)|26→26 (+0)|54→54 (+0)|214→214 (+0)|
|TOML|1→1 (+0)|8→8 (+0)|2→2 (+0)|37→37 (+0)|
|YAML|2→2 (+0)|8→8 (+0)|15→15 (+0)|453→453 (+0)|
|SUM|1644→1665 (+21)|28853→29209 (+356)|36386→37081 (+695)|421835→428568 (+6733)|

### production

|Language|Files|Blank|Comment|Code|
|---|---:|---:|---:|---:|
|JSON|255→261 (+6)|0→0 (+0)|0→0 (+0)|35251→37710 (+2459)|
|Lua|81→81 (+0)|299→299 (+0)|639→639 (+0)|9524→9524 (+0)|
|MATLAB|96→96 (+0)|496→496 (+0)|1399→1399 (+0)|10812→10812 (+0)|
|PowerShell|138→138 (+0)|1061→1062 (+1)|1371→1372 (+1)|45756→45814 (+58)|
|Python|464→471 (+7)|13847→13973 (+126)|9851→10108 (+257)|154047→155073 (+1026)|
|SIMION GEM|10→10 (+0)|26→26 (+0)|54→54 (+0)|214→214 (+0)|
|TOML|1→1 (+0)|8→8 (+0)|2→2 (+0)|37→37 (+0)|
|YAML|2→2 (+0)|8→8 (+0)|15→15 (+0)|453→453 (+0)|
|SUM|1047→1060 (+13)|15745→15872 (+127)|13331→13589 (+258)|256094→259637 (+3543)|

### tests

|Language|Files|Blank|Comment|Code|
|---|---:|---:|---:|---:|
|JSON|3→3 (+0)|0→0 (+0)|0→0 (+0)|422→422 (+0)|
|Lua|19→19 (+0)|70→70 (+0)|110→110 (+0)|1901→1901 (+0)|
|MATLAB|64→64 (+0)|520→520 (+0)|584→584 (+0)|6971→6971 (+0)|
|PowerShell|8→8 (+0)|59→59 (+0)|33→33 (+0)|1689→1689 (+0)|
|Python|503→511 (+8)|12459→12688 (+229)|22328→22765 (+437)|154758→157948 (+3190)|
|SUM|597→605 (+8)|13108→13337 (+229)|23055→23492 (+437)|165741→168931 (+3190)|

不据新增代码宣称净复杂度下降。

工作区任务证据目录`.tools/phase02-v6-20261103/`保存：最终本机summary／execution／source-before/after、
local-b7-terminal-audit、安装冻结与native6独立审计、native-readiness非粒子结果与owner审计／限定接受、
作者退役收据、cloc-phase02-2de-to-b7e30447.log。远端run41666241674的原ZIP和解压工件保存在
`remote-b7-41666241674/`，其`independent-review`与`same-b7-reconciliation`记录完整核对。
原18Goal／40B逐项证据对应保存在`final-goal-completion-audit.md/json`；R01–R20总要求及后续阶段责任完整保留。
本文、路线图、集成状态与审计索引构成纯文档后继，源码验收仍固定于B7；文档检查收据随最终提交说明绑定。
