# RF→oaTOF staged grid2 restart功能迁移（2026-08-15）

## 结论

`local_accelerator_exit`历史checkpoint现在可以通过既有single-flight执行链，以SIMION官方支持的
individual-particle FLY2位置/速度释放和Program回调进入分析器；没有建立第二套assembler、时钟或运行
入口。活动restart只接受精确28列`canonical_component_particle_state_v1`，不接受旧11列TRACE。

本轮先完成静态、合同和`ValidateOnly`功能迁移，随后r07 governed child完成一次真实SIMION飞行、analyzer
与逐事件diagnostic parity；frontend为既有官方PA cache hit，未运行refine或PA构建。r07 parent publication
因staged source identity旧比较路径失败，所以整个r07及其child只能标记`DIAGNOSTIC_ONLY`，不产生正式物理
等价或分辨率结论。随后唯一`FUNCTIONAL_MIGRATION_ONLY` successor r08完成真实SIMION与parent publication，
验证了canonical source/connection lineage分离；其summary仍明确为`FUNCTIONAL_SCREEN_ONLY`、
`paired_analysis_status=NOT_RUN`及`formal_gate_passed=false`，因此旧runner暂不删除。

## 单权威链

- campaign冻结restart事件`local_accelerator_exit`、坐标系`oatof_global`、时钟
  `canonical_instrument_time_us/instrument_clock_epoch_v1`、`position_projection_applied=false`和显式起始
  instance。无overlay必须为instance 3，有overlay必须为instance 5，双向约束均失败关闭，禁止按位置猜测。
- resolved population唯一冻结staged源表、N、有序canonical ID SHA和禁止postselection。34个ID保持源文件
  顺序且允许非连续；其紧凑JSON整数数组SHA为
  `F3394E32FD237968FC29D9EA564B7AC986966008B09BEFD8AD6D8EF20FC8ED30`。
- FLY2每行使用官方`standard_beam`的直接`position=vector(...)`与`velocity=vector(...)`。单独冻结的
  row map把连续SIMION solver row映射到canonical ID；source release、TRACE、analyzer event和detector
  均消费该映射，不允许用行号猜ID。
- staged入口跳过RF frontend、pulse和accelerator运行时电压写入，但继续执行analyzer静态PA初始化；下游
  电场保持base后region override，探测器规范时钟为canonical restart time加solver local elapsed。
- staged链禁止pulse schedule/time进入schema、prepare、adapter、runner、run config和SIMION CLI；analyzer
  即使收到runner等价的geometry输入也只做`downstream_only_from_local_accelerator_exit`分析，跳过pulse
  eligibility与injection validation。eligible集合直接使用`expected_particle_ids`，支持非连续canonical ID。
- runner对全部restart FLY2统一只抽取`standard_beam`粒子行后再核对N和批切片，FLY2的`particles`、
  `coordinates`与闭合行不计作粒子。真实runner函数级N=34回归确认输入和batch slice均恰为34个粒子行。
- canonical staged table及producer manifest是唯一population/source identity。旧upstream source只保留为
  `connection_lineage_only`，不得充当第二source authority。campaign SHA与实验行SHA均在
  `SolverAuthorized`分支和runner调用之前复核。

## 历史桥与限制

历史N=34 oracle绑定：

- producer run：`20260804_094500__sim__cross__oct-simion-grid2-common-oatof__n34`
- canonical 28列状态SHA：
  `66F88F513F8FA20AB55C35A15A41CC9DA7E8FC62FAB19781BA7E1CEAD6350019`
- upstream 11列TRACE SHA：
  `0DCC58D734BB24544BE79DF2B6EA1F95B0DADFC514128EA4B09B22EF4BC427EC`
- legacy template SHA：
  `562A9C07FDB95CDC15A8B91255161F478A5AC8F30E0743360E777E9C590A80D8`
- 独立bridge characterization receipt SHA：
  `A63E0AFA7737F5378ECF089A908660BEA147A652CF0BF447E8233CBE80F2A4A6`

兼容层只复用既有`materialize_simion_grid2_state`。prepare冻结上述三项输入，重新物化出的canonical文件
必须命中既有SHA，receipt也必须命中独立characterization。TRACE能量先与质量和速度派生动能按
`rtol=5e-8, atol=5e-9 eV`核验，再由质量和速度重算输出能量。receipt同时永久记录：位置与时间来自grid2
穿越线性插值；速度来自当前solver step，并非穿越时刻插值；`ax/ay`为非权威legacy字段。因此该桥不能
冒充精确crossing-state物理权威。

## 未发布诊断successor

campaign为`staged_grid2_restart_legacy_n34_successor`，唯一实验为
`staged_grid2_restart_legacy_n34_functional`，预留run ID
`20260815_120000__sim__cross__staged-grid2-restart-legacy__n34`。它只绑定冻结旧oracle并验证新执行准备链；
没有写入Formal、Candidate或实验性能注册表。

首次`SolverAuthorized`只经公开`family_source_closure/execute.ps1`入口启动；parent
`20260815_120000__sim__cross__staged-grid2-restart-legacy__n34`在SIMION启动前失败关闭，未创建child，
未出现SIMION进程。不可变机器收据为该parent的`run_manifest.json`与`summary.json`：status=`failed`，
reason=`Runtime implementation role or integration-local path differs: simion_rf_drive_kernel`，
failure_stage=`governed_child_execution_or_publication`，formal gate=false。执行时冻结campaign SHA为
`9D894E244413EFD521B30188E3661C2C9E32A0A785AF88ABEDED4C3E7349FEFB`，row SHA为
`45E499FE5209DB91C025ED40C2B02AF155AAA242412CAACDF009CA1095D2939E`。失败目录、inputs、manifest和
summary保持原样，不补造execution receipt。

根因是runtime implementation registry已经正式注册两个外部provider：repository-common RF drive
kernel及oaTOF项目analyzer component，但resolver旧代码无差别要求所有role位于integration目录。
修复保持integration-local为默认，只允许这两个精确role→规范path映射，文件仍逐项核验冻结SHA；错误
common路径、未知外部role和用Formal路径替代Candidate组件均失败关闭。旧campaign只把顶层状态归档为
`archived_invalid`，完整experiment row不变；公开入口在freshness、prepare及创建run目录之前拒绝所有
非`authorized`状态的`SolverAuthorized`。独立replacement campaign
`staged_grid2_restart_legacy_n34_successor_r01`冻结相同科学输入，parent为
`20260815_120000__sim__cross__staged-grid2-restart-legacy__n34__r01`，预期child由公开入口唯一派生为
`20260815_120000__sim__simion__rf-oatof-single-flight-gap0__n34__r01`。

r01同样只经公开入口运行，并在4.8 s内、SIMION启动前再次失败关闭；未创建child且SIMION进程数为0。
不可变summary reason为`Runtime resolved source contract fields differ from the closed runtime contract.`，
冻结campaign SHA为`8E3BC52FB35EB787A352CAF3F3E299ED902009C2AE33D8E7F2706054765D801C`，row SHA为
`DC125298A938F81DBAF526C81537C10F3DE48A6971156CAC6AA861F5960A7BD5`。根因是schema/prepare已正式
发布staged顶层`authority_scope=connection_lineage_only`，runtime closed-field列表尚未同步。修复后
resolver仅在字段存在时把它纳入exact fields并要求该唯一值；runner结合resolved population做双向核验：
staged必须存在，所有非staged必须不存在。始终运行的synthetic测试覆盖2个正例和3个负例；另一个可选
测试读取r01真实prepared合同并完整调用`Resolve-RfOatofRuntimeBinding`，本轮artifact存在且实际PASS。
r01仅顶层归档，完整row不变；replacement r02冻结相同科学输入，parent/child分别为
`20260815_120000__sim__cross__staged-grid2-restart-legacy__n34__r02`和
`20260815_120000__sim__simion__rf-oatof-single-flight-gap0__n34__r02`。

r02随后在官方frontend PA缓存决策处暴露授权范围缺口：当精确cache key MISS时，旧行既没有授权构建，
也没有声明必须复用。实际parent目录存在但没有manifest/summary；single-flight child已创建，frontend
GEM2PA/refine相关日志各3份，child manifest与summary均保持初始化`interrupted`，manifest/summary SHA为
`0371AB11D7F0727FB3161F231AC9BBDF05A3EE0CCA4076949CB00EB7E774BF71`/
`5CE2346FD1850FC0AB7845A9B0317F00DAAE2E0D10DC5DA2EA4D081DB253FE5D`，Fly batch日志为0。该事实不是物理或
数值FAIL。r02现以`archived_invalid`冻结，执行时冻结的repository-text SHA为
`4144B88CD450481FA66A8848057F13B7AD5D28F282D36C392C1725B00DBA686B`，完整row canonical SHA为
`CCCF2D2E43C3A2B505B692E78130493D2236D0A91720B16353D6F9A040F6F4D1`。第五轮复核发现顶层claim曾误写
`No SIMION child run`；随后只把它纠正为真实的`child exists/interrupted + frontend GEM2PA/refine logs +
no Fly`，当前归档campaign文件SHA为
`963821D3F7EDB997A21B16E27C515C69BAD3B5AEA7C3A8A97D078F2A30B60088`。该勘误未修改科学实验行、既有
artifact或原manifest/SHA。

replacement r03使用schema-v4，把PA缓存策略提升为campaign实验行的单一权威：
`single_flight_pa_cache_policy=build_and_publish_if_missing`。prepare冻结策略与显式来源，adapter逐项核对
campaign/plan/budget，runner再次核对budget；任何SolverAuthorized旧行或缺字段行均失败关闭。r03的
campaign/experiment/parent身份分别为`staged_grid2_restart_legacy_n34_successor_r03`、
`staged_grid2_restart_legacy_n34_functional_r03`、
`20260815_120000__sim__cross__staged-grid2-restart-legacy__n34__r03`，repository-text SHA为
`648CC676C8BB1249985AE1EAF0C33EBE430C6D32792CD3FB50599CE04F16FEB5`，row canonical SHA为
`7F94ED8BA3D0262EEEF1002858043BBD10AE41EDA6C5796495B66E23C8A7D453`。去除新身份与显式PA策略字段后，
r02/r03实验行逐项相等；因此没有夹带源、场、几何、网格、时钟、N或分析参数变化。

PA策略覆盖现有四个实际family：frontend、accelerator overlay、flight tube、reflectron。成功终态记录
`formal`、`not_applicable`、`cache_hit`或`built_and_published`；在任何预算解析、cache gate或builder前，
最小权威run config先记录四family的`pending_cache_decision`，随后把实际失败或构建授权写成
`cache_miss_required_existing`或`cache_miss_build_authorized`。`require_existing`使用manifest/文件合同只读验证，损坏
entry不删除；任一MISS以role+key失败，且overlay interface与aperture topology的SIMION验证均排在四family
门禁之后。overlay key依赖已验证frontend PA0 SHA，因此frontend MISS会先以frontend identity失败，不伪造
下游identity。`build_and_publish_if_missing`保留官方Test→GEM2PA/refine→Publish链，不引入第二runner或fallback。

独立动态负门禁campaign为`staged_grid2_restart_legacy_n34_pa_cache_miss_gate`，repo归档SHA为
`FD2D4B36B2A3C9965EA8C742BC0418E5AFBCD969FED5F8BE5C82A4F03F335256`，row SHA为
`05A7691CAF469F47334DC043AC7BA297F43EF3AF293A4D09D5E1F6B83FC02B60`，claim固定为
`DYNAMIC_GATE_NEGATIVE_TEST_ONLY`。首次parent
`20260815_125000__sim__cross__staged-grid2-pa-cache-miss-gate__n34`在cache前暴露schema-v4继承遗漏：
prepare仍有一处只对`schema_version==3`生成layout参数，adapter因缺少`architecture_generation_id`失败。
该run在4.2 s内终止，SIMION进程前后均为0且没有child；manifest/summary SHA分别为
`3B3C043342A3CA08B43C96C75468DC6AFA08728526C30E0EF295653D9527384E`/
`BA2C945ECEF6437E4F61528C1167161DA186AC5FDB563C5EFD24EDC74498D97A`。系统审计把campaign-v3继承语义
两处统一为`>=3`；runtime-binding自身schema恰为v3，仍保持精确`==3`，没有混淆独立合同。

不可复用首次run ID后，`__r01`经官方source refresher、公开ValidateOnly和相同冻结科学输入重试。
parent/child分别为`20260815_125000__sim__cross__staged-grid2-pa-cache-miss-gate__n34__r01`与
`20260815_125000__sim__simion__rf-oatof-single-flight-gap0__n34__r01`。运行前后SIMION进程均为0；精确
frontend role/key为`simion_single_flight_frontend_pa_cache`/
`c612cb42a6912682889732fc0875108f113d0b91ee671481083aaa5a082a3ab2`，cache目录运行后仍不存在，
GEM2PA builder、refine与Fly batch日志数量均为0。parent为failed且reason精确包含上述role+key；旧child
暴露pre-snapshot生命周期缺陷：manifest仍为`interrupted`，summary已覆盖为`failed`，manifest记录的
summary SHA仍为旧值`5CE2346F...FE5D`，与实际summary SHA不一致。parent manifest/summary SHA为
`3F19221F89E752192B6C870F3C987CDC0BDCBB1C20E05811A92FE0B7B1341AE8`/
`68CEE7B2398740DA0B3D125622015CC6F2548DC82B59FAC2E86E0753ABF7EAC5`，child manifest/summary SHA为
`D112D5A0FFEB48DCC1E372FCD0467A0970A3197508148412001290E8EBD2D5A9`/
`E1F36E6DD8B420CFF915E70793808D7367B94C7981B2D65575CA33E0715ADB9F`。旧artifact原样保留，不能作为
生命周期闭合正证据。

标准failed-run终结器随后扩展受限附加summary字段，runner无论snapshot是否完成均统一经该终结器恢复
inputs、写最终summary、应用retention并重写verified manifest；附加字段不得覆盖status/reason等保留字段。
全新`__r02`动态门禁再次命中相同role/key，运行前后SIMION进程均为0，cache目录仍不存在，GEM2PA、
refine、Fly日志均为0。parent与child manifest、child summary均为`failed`；child manifest唯一summary
output的SHA/bytes为`FD3D2D07535180BC26E214BBAEE80C713D16CDEAA4DC7B12DE24AC13AFA0B135`/`472`，
与最终summary完全一致。parent manifest/summary SHA为
`0039BF970A3E5A90AD532EF0F061300A560B9D11CC3B52A852235A407B094E12`/
`68CEE7B2398740DA0B3D125622015CC6F2548DC82B59FAC2E86E0753ABF7EAC5`，child manifest/summary SHA为
`29F37AA3FE2BED71D3BBF8E894F266024C03F1745726DB0C33A2997FAFF0FB7F`/
`FD3D2D07535180BC26E214BBAEE80C713D16CDEAA4DC7B12DE24AC13AFA0B135`。最终negative campaign以
`archived_invalid`冻结，repo/row SHA为`80DAD6A24D12E9C1A2B02765BFF9FBA1DB020E355257B8069020F52D844EC090`/
`6812A50DD354BC8AEC327788D5EF2BE908D9621073B10D189D52A434EE19F493`。这些负门禁只证明失败关闭，
不构成SIMION物理运行或r03科学执行。

第五轮复核还发现上述negative `__r02`的最终child run config仍来自旧初始化器，只含
`lifecycle_stage=run_package_initialized`，没有policy、provenance或四family dispositions；原manifest已绑定
该旧文件，因此保持逐字节不改，`__r02`不能作为run config与summary双记录的正证据。运行器随后改为在
进入`try`和预算解析前先写`pa_cache_policy_pending_budget_validation`最小run config，并在每个family的
MISS/hit/build/publish决定前更新同一权威对象；failed lifecycle继续由公共`Complete-FailedRun`终结。

独立negative campaign `staged_grid2_restart_legacy_n34_pa_cache_miss_gate_r03`使用parent
`20260815_130000__sim__cross__staged-grid2-pa-cache-miss-gate__n34__r03`和child
`20260815_130000__sim__simion__rf-oatof-single-flight-gap0__n34__r03`。执行前official source binding与
`ValidateOnly`均PASS，parent/child无碰撞、SIMION进程为0、目标cache不存在。公开入口的
`SolverAuthorized`在8.3 s内按预期以frontend role和精确key
`c612cb42a6912682889732fc0875108f113d0b91ee671481083aaa5a082a3ab2`失败；前后SIMION进程均为0，
目标cache仍不存在，builder/refine/verifier/Fly日志均为0。parent/child manifest与summary均为`failed`；
child run config与summary的policy=`require_existing`、provenance=`explicit_campaign_row`及四family
dispositions逐项相同：frontend=`cache_miss_required_existing`、overlay=`not_applicable`、flight tube与
reflectron=`formal`。child manifest绑定run config SHA/bytes
`6D82B72F01AEF525675004206E93BD75F35EEE10F165F0D4AFB7ACDD0AD0D078`/`6137`及summary SHA/bytes
`A2E1D699F635FA88293679E29BD02FDDB18570EC3B98CA9D4DC64E06F6E66ACA`/`1109`，均与最终文件相同；parent
summary绑定`E697A5D7B79E82E383BCC50F2D25750D3B1E39D0B7FCDBDF6FD9D680A0D6F585`/`695`。parent/child
manifest SHA分别为`CCCC870018A8C6F1E6F700685EB0C40F40AE4282B0EDB2AD3A8B30C366D70A98`和
`FDC020C3B9624373FE8D030CF7606B0734077247879E9A369B561234D7D98261`。执行冻结campaign SHA为
`9CFA60F722F995168ED32E8FE2536185B54D261D87C920A1021F80DA3C5F85CE`，row SHA为
`7F8DE2C97941D9640AF069D6E8BEB320917E6F4889DB1A586C5C53BEE971A0E4`；终态归档claim/status后的当前
campaign文件SHA为`10383FF84699700FFAEDD831614BABDFF5E0230AF51F155622734039F9059267`。这些证据只关闭缓存策略
失败链，不是科学r03执行。

科学successor r03随后经唯一公开入口执行。官方frontend GEM2PA/refine完成，并以精确key
`c612cb42a6912682889732fc0875108f113d0b91ee671481083aaa5a082a3ab2`原子发布schema-v2缓存；refine
wall time约189 s。source materialization与Program build均PASS，但在Fly之前，运行器错误地从仅含
`stage_budget`/`frozen_budget`的阶段预算wrapper读取`source_identity`，触发StrictMode失败。因此parent
`20260815_120000__sim__cross__staged-grid2-restart-legacy__n34__r03`与child
`20260815_120000__sim__simion__rf-oatof-single-flight-gap0__n34__r03`均为failed，Fly日志为0，不能产生或
支持任何物理结论。parent manifest、child manifest、child summary与child run config SHA分别为
`69126A7E5A93177A6687C65910CC067DE330F786285FEAC3164A1538682EB925`、
`1E25DCD7B7B07DBC900DAF1DC4BE53B927752A4380156314545630E32DFBBA17`、
`2A6F196CC07B2C19197CAF76FD1A1B0F346D0BCA2566B6A830CCE6E4CA64334C`与
`7D4E0A5AA1CCC2036DEAF82AD216752A63D9B8C0B6EFEAF5B1D23FF274D57981`。r03现以
`archived_invalid`冻结，其campaign/run身份永久禁止复用；当前repository-text campaign SHA为
`CAA9AB871584C43A77D124116E89103999A0591384FFD9CF1301323B5AFFB13E`。

修复先由公共初始化器把resolved budget冻结到run-local `frozen_budget`，随后只从该冻结副本读取
policy与`source_identity`，并由`Set-RfStagedRunConfigurationIdentity`集中构造run config身份；同一block
审计确认阶段预算wrapper剩余读取仅为其实际拥有的`stage_budget`与`frozen_budget`。源码回归要求
Initialize之后的赋值精确调用`Read-RfFrozenResolvedBudgetDocument -StageBudgetReceipt $budget`，禁止直接
`Get-Content $ResolvedEngineeringBudget`或其他外部budget读取。真实r03 resolved budget/run config回归把
已发布schema-v4 BUILD预算复制为run-local frozen副本，同时把外部副本的policy与source authority篡改，
再验证读取结果仍来自frozen，并覆盖cache-hit身份构造；因此冻结后只有一个预算权威。边界参数与frozen
值相等校验后，runner把有效policy/provenance重新绑定为frozen document值；同一值随即覆盖pre-cache
run config并以`pa_cache_policy_frozen_post_budget_validation`立即落盘，严格早于configuration、geometry、
source及首个cache gate。之后所有缓存决策、run config与summary只消费这组已重绑定值。
验证canonical `source_identity`、connection lineage和旧`upstream_source_identity`移除。独立r04使用新的
campaign/experiment/parent身份`staged_grid2_restart_legacy_n34_successor_r04`、
`staged_grid2_restart_legacy_n34_functional_r04`、
`20260815_120000__sim__cross__staged-grid2-restart-legacy__n34__r04`；除experiment/run身份外，r03/r04
实验行逐项、逐字节规范化相等，且均保持`build_and_publish_if_missing`。r04仅允许复用r03已经正式发布的
精确缓存并完成冻结N=34功能parity，不允许优化、Candidate或Formal声明。

r04经第六轮独立审查明确批准后通过唯一公开入口执行。frontend精确命中key
`c612cb42a6912682889732fc0875108f113d0b91ee671481083aaa5a082a3ab2`，disposition=`cache_hit`；overlay为
`not_applicable`，flight tube/reflectron为`formal`，GEM2PA/refine日志均为0。source与Program build PASS，
但SIMION在创建首个离子时以非零状态退出：batch stderr为空，stdout精确报告generated Program line 915
把userdata类型的`simion.wb.instances`传给`ipairs`，随后`Fly'm failed`；0 splats，SIMION终态进程为0。
因此parent/child均failed且无物理结果。parent manifest/summary SHA为
`DC1D580A842F780092F8D1732EAB45A5255B46F6BBBBB9F22D8ABBE10C522F19`/
`96A8A69D6A2247F0E5F509743D7A65D8CBE3196C9DA2D9BD540BDD561BA64C38`，child manifest/summary/run config
SHA为`59383A50F35440754A9682A6B9798281C07CC1E5E2937B975135898E0BC3F3A0`/
`6809463940D077EE2B636DD010052B5CBD3993EE76FB626891486B372DB86676`/
`F582707E33A5E5C336B683888183C1613515E6244CB12FD204172468CD714A2B`。batch stdout/stderr SHA为
`DA93226E55D28FA75C49B7DFBD4D0E92033D3BA1ADFB30C11F3B8D1D5B050FBC`/
`E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`。r04以`archived_invalid`永久冻结。

SIMION 2020官方examples把`simion.wb.instances`作为userdata array proxy，通过长度与整数下标枚举；本机
`examples/contour/contourlib81.lua:387-389`、`examples/collision_sds/collision_sds.lua:354-356`均使用
`for i=1,#simion.wb.instances do`。唯一Program builder已改为这一官方写法；production全域审计没有其他
SIMION userdata `pairs`/`ipairs`误用。真实IOB smoke进一步暴露`pa:load(frontend.pa0)`后SIMION会把slot 3
payload filename更新为`frontend.pa0`。合同据此拆为两张由同一Python compiler派生、互不混用的表：
`formal_iob_config`在load前按nonoverlay 4-slot或overlay 5-slot exact验证IOB初始payload；
`analyzer_config`在load后按四个runtime role exact验证实际payload。禁止regex放宽、伪造filename或把
overlay slot 5混入analyzer四角色。官方CLI characterization覆盖normal/overlay正测及错误count/slot3/
slot5/override basename负测；定点32/32 PASS。复用仓库既有真实IOB+单行ion CLI模式的非科学smoke使用
当前component、r04其余冻结输入和真实c612 override，SIMION exit 0、1 splat、无userdata/role错误，终态
进程为0；该smoke只授予initialize-run实现资格，不产生分辨率或物理结论。

第七轮审查发现正式overlay builder在load前实际把slot 3写为`accelerator.pa0`，而早期mock曾错误预置
`frontend.pa0`。现已以production caller/builder为权威修正：4-slot与5-slot load前slot 3都必须exact
`accelerator.pa0`，5-slot的slot 5必须exact `accelerator_overlay.pa0`；只有Program执行官方
`pa:load`后，analyzer四角色的slot 3才必须exact `frontend.pa0`。slot 5运行期检查也改用exact basename，
不再使用尾部regex。新增可复用只读probe
`tests/test_single_flight_overlay_iob_contract.lua`。按正式runner流程把SIMION-distributed IOB与5个GEM复制到
run-local临时目录，再调用production `build_single_flight_overlay_iob.lua`，得到
`SINGLE_FLIGHT_OVERLAY_IOB=PASS INSTANCES=5`；生成IOB SHA/bytes为
`679E144A82E05610ABF27CC9296B61CEA6DFFADEE427158A35102726FB05C154`/`21427`，preload probe明确
`SLOT3=accelerator.pa0 SLOT5=accelerator_overlay.pa0`。随后官方Fly自动加载同basename当前Program及真实
c612 frontend override，SIMION exit 0、1 splat、1.96 s，正常输出source release与pulse事件且无
role/payload错误；当前Program SHA/bytes为
`B54AE66BEAD06C57D83F3EDB977BD7DAB26C649905CED27D52D3E27FA9377AC8`/`63356`，单离子Fly2为
`1781694FDFAA0FA4F2261B14A77E8FFBD45EB504866CCD2A9B9E091A2F97A974`/`227`。这些是实现合同smoke，
不授予物理parity或分辨率结论；probe后仅删除经repo-root与basename双校验的临时目录，未保留大型文件。

独立r05身份为`staged_grid2_restart_legacy_n34_successor_r05`、
`staged_grid2_restart_legacy_n34_functional_r05`、
`20260815_120000__sim__cross__staged-grid2-restart-legacy__n34__r05`。除experiment/run身份外，r04/r05
实验行规范化完全相等，继续使用BUILD policy并预期精确cache hit；r05必须重新通过official refresh、
ValidateOnly、全门禁与独立审查后才可SolverAuthorized。

r05随后完成真实SIMION N=34运行：34/34 `source_release`、34/34
`local_accelerator_exit`、34/34 `detector_crossing`均存在，SIMION报告`Fly completed. 34 splats, 5.20
seconds`。分析器在source-release一致性门禁失败；这不是轨迹失败。canonical CSV→FLY2文本逐值序列化精确，
particle ID、row map、position和instrument clock也逐行精确；最大速度分量往返误差为
`2.0893199689453468e-4 m/s`，最大speed绝对误差为`2.0919225e-4 m/s`，由实际速度与canonical mass公共
函数派生的最大能量误差为`1.3395621181189199e-5 eV`，方向误差约`5e-16 rad`。因此r05只证明旧的
手填绝对阈值没有覆盖SIMION官方FLY2 loader内部表示往返，不能支持分辨率、物理parity或任何高阶像差结论。
parent/child均以`Single-flight log analysis failed`闭合；parent manifest/summary SHA为
`0927B5A2F08B26097086F99412B68EC9FD168B7C152FC4F99341B0A9BF2BB55E`/
`481B660ACF425C94ACE619CC65769C290595643B9C3A9E35F2B5196C18478ED7`，child manifest/summary SHA为
`D42DD1B1190F351C1D9DC2A30E2BD44EC396D3675604E4647FF730261DB3BB7A`/
`7FC3D646B262CA9715EF574DE2593E46B7DE2790CE73576B381BFAB65C1A77A8`。r05 campaign现为
`archived_invalid`，其campaign/experiment/run身份永久禁止复用。

独立tests-side loader characterization只使用SIMION官方CLI、官方einzel IOB载体、无电极点
`(3,0,0)`、`segment.initialize`记录及官方examples使用的`ion_splat=1`，没有传播电场也没有写回速度。
A臂为production现用的`standard_beam velocity=vector(...)`；B臂为官方
`ke+direction=vector(...)`并以SIMION `speed_to_ke`构造能量。289个预登记合成阈值点覆盖zero、9层
source-speed上界和32个方向；另有34个r05 exact-vector witness，只用于外部见证，不参与预算推导。
A/B各独立重复两次，误差包络实质相同，B没有准确度收益；因此保留A作为唯一production renderer，B不接入
生产路径。selection receipt为
`config/diagnostics/staged_grid2_n34_simion_fly2_loader_ab_characterization.json`，raw-byte SHA为
`08E4C988D0D64C5B6D4EC50F64B74D3C439D06AFABCDAF07E57D66A74126E0E5`；A-only authorization
receipt为`config/diagnostics/staged_grid2_n34_simion_fly2_loader_authorization_budget.json`，raw-byte SHA为
`3C55554E41C9D016C3A2DEC8CB11DC1FFC1436FC843805D0E8987CDE32CDF1FE`。预算只由289个合成点推导：
速度raw relative envelope=`3.226754015005981e-9`，预登记4倍安全因子后向外一位有效数字取
`2e-8`；派生能量raw relative envelope=`6.453508085431755e-9`，同法取`3e-8`。两者absolute floor均为0，
zero speed/energy必须exact；ID/row-map/position/clock也必须exact；SIMION native `ion_ke`只作diagnostic。
34/34 r05 witness在该预算内PASS，但没有改变预算。receipt身份按raw bytes冻结；CRLF改为LF即使JSON语义
相同也必须SHA漂移并fail，不能误用repository-text规范化。

当时唯一活动身份为schema-v5 campaign `staged_grid2_restart_legacy_n34_successor_r06`、experiment
`staged_grid2_restart_legacy_n34_functional_r06`、parent run
`20260815_130000__sim__cross__staged-grid2-restart-legacy__n34__r06`。r06与r05科学输入及官方PA policy相同，
只增加上述A-only loader receipt与resolved-population v2验证合同。v2在solver边界强制
`validation canonical source SHA == campaign staged source SHA == resolved population source-table SHA`；
任一不等即在SIMION前失败。外层公开入口同时强制staged `SolverAuthorized`必须是campaign v5并显式声明
loader budget；历史v4只能ValidateOnly/归档审阅，不能创建child。schema还双向约束
`v5+staged -> budget required`及`budget present -> v5+staged`。r06 source binding、ValidateOnly和PrepareOnly
均PASS；审阅产物中的resolved population为v2且精确冻结`2e-8`/`3e-8`相对界、zero exact和
`native ion_ke=diagnostic_only`。

r06经审查批准后从唯一公开入口执行。parent/child均无碰撞，运行前SIMION进程为0；预算、canonical source及
frontend cache身份精确，frontend disposition=`cache_hit`；官方SIMION PA topology verifier执行并PASS，
没有GEM2PA/refine。Program build前的source
materialization为34/34 PASS，但builder仍只接受旧的四个flat正absolute tolerance字段，拒绝resolved
population v2的nested relative/zero-exact结构，因此在cache-hit SIMION aperture-topology verification之后、
Fly之前且任何离子轨迹之前的Program build失败；GEM2PA/refine/Fly日志均为0，没有离子物理飞行，终态
SIMION进程为0。公开输出中的`FAMILY_SOURCE_CLOSURE_PUBLICATION=PASS`是终端
stdout/stderr缓冲顺序中的中间publication
收据，不是终态授权；最终parent/child manifest和summary均为`failed`，reason均为
`Single-flight Program build failed.`。parent manifest/summary SHA为
`83265B5763DFB5CC503F3636D6C83EBF710D1FFACB40417D0F4EF4E65BAD88EC`/
`A9CA831B324FB06414E9CDD6CD6496E4CB26BF2A2CB0DA3B52FAEA31B1AD363B`，child manifest/summary/run config
SHA为`487225E9490BBCEB14C91A147119748C1E2FCAA8DA5FB66CBC290518AF9ECDDC`/
`57898944D6E372DB0131E4240D86B307681CC1C292E9F1DD116E8469A2C4CE9D`/
`E42298A30CBD816249F944CF68BB8CEC278351C1B3C0D13C141BC852FC183A32`。r06已归档为
`archived_invalid`，不能复用且不产生物理结论。

最小修复只删除builder旧四字段门禁，改为核对resolved population v2 validation的身份、budget引用、SHA、
exact policy、有限正relative bound、zero exact/absolute floor 0、派生能量authority及native diagnostic角色；
没有硬编码`2e-8`/`3e-8`，没有把容差复制到Program，也没有新增validator模块或第二权威。旧flat fixture明确
负测拒绝。当时用于下一次执行的活动身份为`staged_grid2_restart_legacy_n34_successor_r07`/
`staged_grid2_restart_legacy_n34_functional_r07`/
`20260815_133000__sim__cross__staged-grid2-restart-legacy__n34__r07`；科学输入、budget、source与PA policy均与
r06相同，只允许在全门禁和独立审查后执行FUNCTIONAL_MIGRATION_ONLY。

r07经审查批准后由唯一公开入口执行。frontend继续精确cache hit，未运行GEM2PA/refine；Program、Fly、
新analyzer及六面板均PASS，34/34离子在source release、local accelerator exit、accelerator focus、reflectron
entrance/midgrid/turning/exit和detector均有完整census。loader gate为PASS：最大速度absolute差
`0.00020893199689453468 m/s`、relative差`3.381632399772421e-9`；最大派生能量absolute差
`1.3395621181189199e-5 eV`、relative差`6.771689415789017e-9`，均低于冻结授权预算。仪器时钟峰仅作
diagnostic：mean TOF=`70.75874898122942 us`、direct FWHM=`2.4310030995167153 ns`、time-equivalent
R=`14553.405751579727`、direct mass FWHM=`0.006871219017099861 Da`、mass R=
`14553.458382149933`、significant KDE modes=2；`instrument_clock_peak_is_resolution_claim=false`，因此这些
数值不是正式分辨率结论。

r07 child成功后，parent publication在旧publisher分支失败：single-flight固定读取child中不存在的
`upstream_source_identity`，报`family first stage and parent source identities differ`。实际parent
execution receipt、engineering budget与child `source_identity`已全量一致，均为唯一canonical staged-grid2
源；原multipole source只存在于三者一致的`connection_lineage_only`记录中。parent manifest/summary SHA为
`A2765754DDA4DC05E9DDB9F20517D23ED3F649C1B2AB3333348D069DD9A28400`/
`DF70F0C05D9D6D65147288C058C8BF557EC65CB70C09CAFD03A227946D69D3D5`，终态failed；child
manifest/run config/summary/checkpoints SHA为
`AB69C13D5161FA003FA6354C3F9BC4DF1BDB1000B293D82083937FC31729245D`/
`9E644602BA766684DFEB072FDA829DD8E288A0379EC4AD32407A85AC842BF350`/
`C82746BA28873B742A2F8BE8C37DC55B33EEA5DAC3740360427E85F4C9B22649`/
`B03054EE879978C3B22C1804CBCF41CBB402362CDEEBBE18609F8C920F90263B`。由于parent合同失败，r07整体及
child只能标记`DIAGNOSTIC_ONLY`，身份禁止复用。

r07 child与r05相同冻结输入的SIMION raw log各包含374条`TRACE:`事件；排除只含run-local PA路径和wall
time的status行后，374条事件逐字符完全相同，canonical UTF-8 LF trace SHA同为
`1D83DBB56414CCEF8E92AE7B70AAD02DF1A809D2A2E30B7B2CB5602EA1924087`。这证明本次builder/analyzer迁移没有
改变逐粒子轨迹事件，但仍受r07 parent失败限制，只能作为diagnostic parity证据。

publisher最小修复不增加第二source：staged判定只取resolved population的
`source_release_mode=staged_grid2_restart`；child与receipt全量比较canonical `source_identity`；resolved source
contract、receipt与child的`connection_lineage_only`及其identity必须一致，且staged child禁止
`upstream_source_identity`。staged parent只写`source_identity`与`connection_lineage`；nonstaged保持既有
upstream分支。新增测试覆盖staged成功、canonical/lineage互换拒绝、lineage漂移拒绝与nonstaged回归。
新活动身份为`staged_grid2_restart_legacy_n34_successor_r08`/
`staged_grid2_restart_legacy_n34_functional_r08`/
`20260815_140000__sim__cross__staged-grid2-restart-legacy__n34__r08`；science、canonical source、budget与官方PA
policy均与r07相同，只允许在全门禁与独立审查通过后执行。

r08在全部预执行门禁与独立审查通过后，由唯一公开`execute.ps1 -SolverAuthorized`入口执行一次，总wall time
41.9 s，前后SIMION进程均为0。frontend cache key仍为
`c612cb42a6912682889732fc0875108f113d0b91ee671481083aaa5a082a3ab2`且disposition=`cache_hit`；
accelerator overlay为`not_applicable`，flight tube与reflectron均为`formal`。run-local没有GEM2PA/refine命名文件，
accelerator/reflectron refiner输入均为null，因此本次GEM2PA/refine=0。官方SIMION Fly、Program、analyzer、
aperture-topology verifier和六面板均PASS，stderr为空；34/34离子通过source release、local accelerator exit、
accelerator focus、reflectron entrance/midgrid/turning/exit并到达detector。

r08 loader gate为PASS且与r07数值相同：ID/position/clock exact，最大速度absolute差
`0.00020893199689453468 m/s`、relative差`3.381632399772421e-9`；最大派生能量absolute差
`1.3395621181189199e-5 eV`、relative差`6.771689415789017e-9`；native `ion_ke`仅diagnostic。r08
checkpoints SHA=`B03054EE879978C3B22C1804CBCF41CBB402362CDEEBBE18609F8C920F90263B`，与r07完全相同。
r05、r07、r08的SIMION raw log各有374条`TRACE:`事件，逐字符完全相同，canonical trace SHA均为
`1D83DBB56414CCEF8E92AE7B70AAD02DF1A809D2A2E30B7B2CB5602EA1924087`。

r08 parent publication现为success，parent manifest/run config/summary/execution receipt SHA分别为
`4506AFC8A9F033CDE60D052B315EFC9C912EB36ED64980FCE4A8ED3041E315E3`/
`B0392DB7F3820EE59AB40E0DB94AD5239BBE9DDA1AB1AF3F9B56E8653CF93290`/
`8B45F6850B39E444AA1D2FB292A39B21FCD6BC1CCF8A18F067BE8A9B91658BA3`/
`7775188FB40A1C78D2B3044ACDC5CC37B14FCA02C45C4A49AF79168A15351B20`；child
manifest/run config/summary SHA分别为
`A2303130309E6556D92444839346F9834E098C7402BC9CE4ACDD6A0D8ED4B251`/
`1209441029994A8D57D3738C6961A0D4830A1C6F806D03F2B0D08CB333279CF8`/
`379161EECC7A37FD2DB011C8B50D2867E6BBD652D416C75D395E5DA9A6D77FA0`。parent与child均只写canonical
`source_identity`和`connection_lineage_only`；两者均没有`upstream_source_identity`或第二source。parent census
及child census全量一致，parent明确`claim_status=FUNCTIONAL_SCREEN_ONLY`、`paired_analysis_status=NOT_RUN`、
`formal_gate_passed=false`。

r08仪器时钟峰与r07完全相同，仅作为diagnostic：mean TOF=`70.75874898122942 us`、direct FWHM=
`2.4310030995167153 ns`、time-equivalent R=`14553.405751579727`、direct mass FWHM=
`0.006871219017099861 Da`、mass R=`14553.458382149933`、significant KDE modes=2；
`instrument_clock_peak_is_resolution_claim=false`，不能登记为正式分辨率结果。

## 验证收据

- Python compile与PowerShell AST：PASS。
- PA策略、runtime、staged source、program、analyzer、transport、population与workflow expanded focused：
  原功能迁移集102/102 PASS；loader v2、raw-byte、三方SHA、v4外层早拒绝加入后，r07执行前focused
  110/110 PASS。publisher修复后publication/source-binding/workflow三模块expanded focused为48/48 PASS，
  其中publication专项16/16 PASS并覆盖四个新staged/nonstaged分支；公共run artifact lifecycle专项也PASS；
  策略专项覆盖损坏cache只读保留、官方
  Test→GEM2PA/refine→Publish顺序、四family门禁先于SIMION verifier、schema-v4 policy要求、legacy
  policy仅限`ValidateOnly`、campaign→plan/budget动态篡改拒绝、cache gate前initial run config顺序以及
  failed run config/summary/manifest终态一致性。
- r08最终integration full：406/406 PASS；integration gate同时通过Ruff与406/406测试。
- 两份既有schema-v3 successor 29行及活动replacement 1行，全部经唯一公开入口
  `execute.ps1 -ValidateOnly`：30/30 PASS；旧失败campaign不再属于active matrix。
- repository-text publication closure与唯一活动r08 campaign source bindings经官方refresher/check PASS；loader
  authorization receipt单独保持raw-byte SHA权威。
  archived negative repo文件只规范任务创建时多出的末尾空行，其字节与official canonical compiler输出相等，
  published artifact及其SHA未改；由于failed target manifest没有execution receipt，官方`--check`按设计拒绝
  为该归档文件恢复published identity freshness，因此它不进入活动campaign freshness matrix。
- `pwsh -NoProfile -File common/verify_changed.ps1` L1：PASS；清除误置于repo内的2个PrepareOnly临时文件后，
  r08 publisher修复与campaign/history加入后的最终changed paths为57；其中common contracts 179/179、
  integration 406/406及所有路由到的项目静态门禁
  均PASS；documentation独立门禁也PASS。
- CLOC命令为`pwsh -NoProfile -File common/report_cloc_delta.ps1 -Base HEAD -Current WORKTREE`；CLOC 2.10
  （base `5ca7b47a4d4dfbf366d5853b46c09f115f686135`→WORKTREE）PASS：total code
  `175640→207498`（+31858），production `127474→157343`（+29869），tests
  `48136→49502`（+1366），unclassified `30→653`（+623，tests-side SIMION loader characterization脚本）。
  双口径审计不改文件格式，只从production结果中扣除两份机器逐点receipt：A/B receipt
  `config/diagnostics/staged_grid2_n34_simion_fly2_loader_ab_characterization.json`为623508 bytes/15669 lines，
  authorization receipt `config/diagnostics/staged_grid2_n34_simion_fly2_loader_authorization_budget.json`为
  311736 bytes/7828 lines，合计935244 bytes/23497 lines；扣除后handwritten production为
  `127474→133846`（+6372），handwritten tests为`48136→49502`（+1366）。因此官方全repo CLOC原值保留，
  同时明确production大增主要来自机器JSON，不冒充手写执行逻辑。该命令统一使用仓库base解析、
  artifact/generated/vendor/run/history排除器和production/test分类器；3个既有SIMION probe分类warning不变。

以上证据中的真实SIMION主体先由r07 governed child给出diagnostic parity，再由r08以相同canonical N=34输入
复现完全相同的374条逐粒子事件并成功完成parent publication。由此，staged-grid2功能迁移和single-source
identity separation已通过；但r08仍是`FUNCTIONAL_SCREEN_ONLY`且paired analysis未运行，所以不得宣称正式
物理等价或分辨率资格。下一步只做既有结果审计、受控paired analysis和旧路径删除决策，不自动删除旧路径。

## 后续迁移降本硬验收

r08只完成functional migration与diagnostic parity，不等同于完整迁移完成。后续必须以固定base
`5ca7b47a4d4dfbf366d5853b46c09f115f686135`、迁移过程峰值和最终状态形成同口径三点表，至少量化：
production LOC、脚本/公共入口数、重复实现数、活动gate/runtime数、campaign数、旧runner/teleport/23-arm
入口数以及test/production比。只有最终状态相对base和峰值证明目标复杂度与重复实现下降，才允许宣称
“迁移完成”；否则只能报告功能迁移或parity阶段完成。

## C5.1/C5.2：第二runner与legacy Program测试副本收口

r08成功发布和独立终审完成后，C5只做活动入口收口，不再运行Fly、refine或改写PA。旧
`resolution_attribution`公开CLI、合成counterfactual Python实现、23-arm旧profile及其测试被永久删除；
legacy single-flight Program测试support、characterization测试和48行fixture同步删除。7个旧文件合计
删除4075个物理行。仍有科学用途的能力没有复制旧变换代码：23个旧arm ID按原顺序冻结在
`config/family_source_closure_legacy_attribution_migration.json`，只有可由现有family合同精确表达者绑定
现有authority或`config/simion_single_flight.json`中的具名10 eV profile；无精确successor的合成变换均
标记`retired_synthetic_transform`。detector-blind pre-pulse checkpoint改用新的capability ID，避免把旧
figure输出语义静默改成CSV。正式oaTOF的`Assert-NotContains teleport`负门禁保持不变。

相同Git base `5ca7b47a4d4dfbf366d5853b46c09f115f686135`下，integration目录脚本口径固定为
`.py/.ps1/.lua`，production排除`tests/`，公开入口固定为`workflows/<name>/execute.ps1`：

|量|HEAD|C5后WORKTREE|变化|
|---|---:|---:|---:|
|integration全部文件|264|275|+11|
|全部脚本|130|128|-2|
|production脚本|77|75|-2|
|test脚本|53|53|0|
|公开workflow入口|2|1|-1|

文件总数增加来自本轮完整functional migration的合同、诊断登记和测试，不代表执行入口增加；唯一公开
入口现为`workflows/family_source_closure/execute.ps1`。C5开始时冻结的统一CLOC为total 207498、
production 157343、tests 49502、unclassified 653；C5后同口径为203462、154865、47944、653，即
total -4036、production -2478、tests -1558、unclassified 0。该差值证明删除没有通过把旧production
搬入tests来制造净减。

C5完整无飞行验收如下：

- integration full：Ruff PASS，366/366 PASS；旧40个第二runner/legacy测试删除后不再计入历史406项。
- 两份schema-v3活动successor 29行和r08 replacement 1行均经唯一公开入口串行`-ValidateOnly`：
  30/30 PASS，118.319 s。
- `common/verify_changed.ps1`：PASS，68个changed path；common contracts 179/179、integration 366/366、
  oaTOF 206/206及所有路由项目静态门禁均PASS，总耗时124.7 s。
- documentation、family repository bindings、r08 campaign source bindings、Ruff与`git diff --check`：PASS。
- C5独立复审P0/P1/P2均为0；独立solver-free 13/13 PASS。没有运行Fly、refine、粒子模拟或PA写入。

C5.1/C5.2由此完成的是代码和入口收口，不改变r08的`FUNCTIONAL_SCREEN_ONLY`资格边界，也不产生新的
分辨率结论。后续停止在此，等待C5.3是否执行的单独决策。

## C5.3：pulse直接合同与唯一SIMION输入publisher

C5.3没有重跑SIMION、Fly、GEM2PA/refine或改写PA，也没有改变四个pulse对照的源、布局、grid、场、
tqual、时间步、反射器或统计参数。已发布的旧
`config/pulse_resolution_optimization_campaign.json`保持HEAD原字节，Git blob SHA为
`4a5f167f21e16a5c1c0cc658015ac588280427bf`；它只保留历史发布路径，不再是活动执行矩阵。新的schema-v5
successor为`config/pulse_resolution_direct_campaign.json`，使用新campaign/run identity，并把四个可执行
比较直接登记为`experiment_id → source_profile_id → field_profile_id → authority_status`，不再由旧arm ID
选择执行。旧arm到successor/retired的追溯只保留在C5.1/C5.2 disposition合同和history中。

四行共同冻结同一N=1000母源、同一前100行及同一instrument clock：source state SHA为
`F8F77CFA0A3A21D06BC779FAAC2CB2F066AC38BBC986E3A6A60F28A1E58AE409`；历史N=100 prefix SHA为
`A8721EAB49AC15904DE6D1B135C0B16D98022E68B46710313575F356F1F984CF`；ordered particle-ID SHA为
`F9E2DBDE0AE4640704FB66EE02C101CF84ABE35137363D62647622606DF61279`，IDs为1至100。历史prefix receipt
的selection seed保持null；schema-v5 execution population中的0只表示确定性首100行算法，不引入随机选择
或第二权威。pulse执行值由合同显式固定为`31.81366987147908 us`，并逐字节绑定历史resolved schedule
SHA `AC9B99A3769C72A0980387D599EF6BC0DDA74DBB388069C27368EC28E19837D1`与baseline receipt SHA
`97495F4B0A49D4FF3CA8ECE3EBBDF949AFFAEA3D32E14CF26B707C4573133D4E`。prepare只读取这两份冻结证据，
核对source身份、577个transmitted handoff、464个finite-wall survivor、pulse/base/offset/width、prefix SHA、
IDs、seed与receipt clock后发布本次resolved schedule；此successor不会用N=100或源状态重新计算pulse。

四个direct比较依次使用`accelerator_real_pa`、`accelerator_ideal_stage1_real_stage2`、
`accelerator_ideal_stage1_stage2_real_reflectron`和`full_domain_piecewise_ideal_field`。第4项只继承
field semantics，不主张与历史all-ideal实现具有implementation或numerical equivalence；N=100仍只授权
screening，不产生Candidate、Formal或分辨率资格。

baseline登记已迁入`analysis/register_pulse_resolution_result.py`，runner按experiment/field直接生成唯一结果
与promotion receipt；旧`register_n100_baseline.py`和活动arm桥均退出。canonical state到ION11/row-map的
渲染、逐行身份、clock、物理状态及速度往返校验合并进唯一
`analysis/publish_family_source_bundle.py`；永久删除293行旧`write_oatof_simion_input.py`及201行同名测试，
测试迁入publisher边界。活动非history的旧register、旧writer、旧arm执行字段与`PulseResolutionArmId`
引用均为0。

C5.3 solver-free验收：writer专项30/30 PASS；主focused 118/118 PASS；独立终审P0/P1/P2均为0且独立
25/25 PASS；integration full经一次既有Stage-B validator作用域遗漏修正后366/366 PASS。四份活动campaign
共34行（24+5+1+4）全部通过唯一公开入口`execute.ps1 -ValidateOnly`，新direct campaign官方source-binding
compiler/check PASS，旧campaign原字节不变。以上检查均未启动SIMION，因此只证明合同迁移、输入身份与
编排闭合，不产生新的模拟结果。

C5.3最终门禁：完整活动34行ValidateOnly为34/34 PASS，耗时126.7 s；integration full为366/366 PASS；
`common/verify_changed.ps1`为PASS，81个changed path，wall time 123 s，common contracts 179/179、
integration 366/366、oaTOF 206/206及其余路由项目静态门禁均PASS；documentation、family repository
bindings、direct campaign source bindings、Ruff与`git diff --check`均PASS。CLOC 2.10按同一命令、base
`5ca7b47a4d4dfbf366d5853b46c09f115f686135`与过滤口径得到base→最终WORKTREE：total
`175640→204046`（+28406）、production `127474→155535`（+28061）、tests `48136→47858`（-278）、
unclassified `30→653`（+623，仍为同一SIMION loader characterization脚本）。以C5.1/C5.2结束时冻结值
作为C5.3阶段基线，则total `203462→204046`（+584）、production `154865→155535`（+670）、tests
`47944→47858`（-86）、unclassified `653→653`（0）。integration脚本数从128降至126，production从75
降至74，tests从53降至52，公开workflow保持1；因此新direct合同和固定证据校验增加了少量生产合同代码，
同时唯一publisher与旧writer删除继续减少脚本和重复入口。

### C5.3 post-gate独立审计：冻结cohort纠正与重新NO-GO

上述GO随后被更深一层的字段—消费者审计推翻。先前`ValidateOnly`只证明输入身份和编排能够解析，
没有进入`analyze_single_flight.py`的完整population一致性检查；当时四行把
`eligible_population_count`静态写成100，但冻结历史checkpoint实际并非100个pulse-eligible粒子。
因此前述“独立终审P0/P1/P2均为0”和“新direct campaign可执行”只保留为审计发生前的过程记录，
不得继续作为当前GO依据。

新冻结cohort权威来自
`20260812_210000__sim__simion__rf-oatof-single-flight-gap0__n100/results/single_flight_particle_checkpoints.csv`
（SHA-256 `D46986FC918605D9EB2AD1BA059BB76F9E6AFA24156C30C20A5880375F6B9044`）。按数值particle ID升序、
UTF-8 compact JSON整数数组计算：source-release为IDs 1..100，SHA
`F9E2DBDE0AE4640704FB66EE02C101CF84ABE35137363D62647622606DF61279`；pre-pulse为66个，SHA
`0A4B33799A1C310F3F23E1260B52EF05E9517A7CEA20C2117A9E3607BDCD611D`；其中pulse-eligible为50个，
SHA `19D70E6F7633B0E783B52BC56B5A35CBA4E83C0051CE290853917A96992AA8E2`；outside-transverse-bore为
16个，SHA `B1317E6AF8C4B33CEE6C795E10F8DC0FF508BA3898762E4FAD45BC6A2D7FADC2`。50个eligible全部到达
detector；detector总数56还包含6个outside粒子。该事件计数与旧baseline receipt的100→75→66→56
census闭合，receipt peak的50粒子与eligible集合闭合。新合同不再手写这些count；prepare必须从冻结
CSV派生集合长度并逐集合验证ordered-ID SHA，禁止按detector survivor重新选择cohort。

为阻止旧baseline结果被三条候选误当成新合同授权，活动schema-v5拆为两个campaign：
`pulse_resolution_direct_campaign.json`只含单行、`authorized`的baseline登记；
`pulse_resolution_direct_candidate_campaign.json`只含三行candidate，状态为`PENDING_PREREGISTRATION`，
等待新direct-v5 baseline result及其精确eligible-cohort receipt。candidate不再引用旧97495F baseline
receipt或旧baseline checkpoints；只保留一个pending baseline authority ID。两份campaign都使用同一
campaign级cohort authority，并只保留行内`single_flight_population.analysis_randomness`作为bootstrap
权威；已删除原顶层bootstrap副本。固定pulse authority继续绑定历史resolved schedule、exact pulse和
source-state identity，但不再回读旧baseline receipt，也不复制其prefix/count/seed摘录。

本段实施本身不运行SIMION、Fly、refine或PA写入。当前状态重新为**NO-GO**：只有新的单行baseline
真实运行生成结果并由冻结cohort门禁闭合后，三条pending candidate才可另行授权；此前不得沿用本节
上方旧34/34 ValidateOnly结果启动candidate或声称新的分辨率证据。

### C5.3 post-gate修复闭合：baseline-only授权前置条件GO

重新NO-GO后只修复独立审计已经确认的生产缺口，没有新增Schema、CLI、字段族或第二套验证架构，也没有
运行SIMION。最终活动合同保持两份：`pulse_resolution_direct_campaign.json`是单行、`authorized`的
`pulse_resolution_baseline`；`pulse_resolution_direct_candidate_campaign.json`是三行
`PENDING_PREREGISTRATION`模板。后者没有baseline evidence或preregistration，任何执行请求均在prepare
失败关闭。旧`pulse_resolution_optimization_campaign.json`保持HEAD blob
`4a5f167f21e16a5c1c0cc658015ac588280427bf`及内容SHA-256
`2A8FA4FEF8FF1FD53A2991862EDACA36CE23FF3E0812D5CD8A8907697E61E524`；现有legacy disposition以原路径、
HEAD blob和内容SHA把它登记为`non_executable_historical_evidence`，唯一公开入口在source-binding检查和
任何output前对三种模式给出专用拒绝，测试同时证明没有新scratch、run或PrepareOnly目录。

四层cohort不再由静态count或common survivor解释。prepare实读冻结checkpoint并派生100个
source-release、66个pre-pulse、50个pulse-eligible和16个outside-transverse-bore粒子，逐层核对有序ID
digest并验证`66 = 50 ⊔ 16`。analyzer要求当前run精确复现冻结eligible IDs；任一冻结eligible未到detector
即失败，不按结果重选共同survivor。baseline registrar发布自包含receipt：冻结实验行及其canonical SHA、
campaign ID/SHA、四层authority/census、行内analysis randomness、source/prefix、clock及完整
`paired_checkpoint_rows`，最后计算receipt self-SHA。未来candidate只允许消费prepare复制到plan-local
`inputs/pulse_resolution_baseline_evidence.json`的哈希冻结receipt；runner已删除旧
`PulseResolutionBaselineCheckpoints*`参数和跨campaign checkpoint回读。

为避免prepare阶段只做浅层身份检查，registrar中的无副作用
`validate_frozen_baseline_evidence`成为单一验证实现，prepare在任何mkdir/write之前直接复用它，核文件SHA、
self-SHA、`solver_execution_performed is true`、embedded rows以及重算的`100/66/50/16`和四个digest；
registrar在候选后验登记时复用同一函数。动态负测分别篡改self-SHA、删除一条真实eligible
`pre_pulse_state`并重算self-SHA，两种篡改都经`PrepareOnly`和`SolverAuthorized`真实公开入口在零output、
零SIMION条件下拒绝。旧checkpoint参数的陈旧runtime静态测试也改为新plan-local receipt链的正/负断言。

完整收口曾暴露一个独立的活动消费者缺口：`phase_space_transfer_model`白名单使用了不存在的direct-v5
campaign ID，full integration首轮在374项中出现1 failure和3 errors。最小修复仅加入真实拆分身份
`pulse_resolution_direct_baseline_v5`与`pulse_resolution_direct_candidates_v5`并返回实际campaign ID；
pending candidate仍只允许solver-free纯分析投影，把其`execution_state`改为`executable`会失败关闭。专项
40/40 PASS后，同一full integration复跑为Ruff PASS、374/374 PASS，wall time `65.396 s`；最新L1在
84个changed paths上PASS，wall time `125.001 s`，其中common contracts 179项、integration 374项、
oaTOF 206项及所有适用路由项目门禁均通过。

其余最终门禁：单行baseline `ValidateOnly` PASS（`4.442 s`）；pending candidate `ValidateOnly`按预期
失败关闭（`3.125 s`，未进入solver）；development standards、runtime bindings、baseline和candidate
source bindings、全仓Ruff及`git diff --check`均PASS。上述门禁均未运行SIMION或使用
`SolverAuthorized`。因此当前授权边界从重新NO-GO收敛为：**唯一公开入口下，direct-v5单行baseline已经
满足启动`SolverAuthorized`的solver-free前置条件，可以在独立运行身份和现有资源门禁下单独授权；三行
pending candidate仍是NO-GO，必须等待本次新baseline solver receipt被哈希冻结并完成预注册后另行审查。**

最终统一CLOC由`common/report_cloc_delta.ps1 -Base 5ca7b47 -Current WORKTREE`使用CLOC 2.10生成，
result输入快照SHA-256为`2EF655EAC0C912A8E08B63E78B06E770EE2A9131E4ADC79233CA38CF9227CC03`；过滤口径
排除`.git/.venv/.tmp/artifacts/generated/vendor/third_party/run/runs`、任意`docs/history`、仓库根
`scratch`，并按活动entrypoint、测试命名与tests下未分类警告拆分。三个比较基线必须分开解释：

|口径|total|production|tests|unclassified|
|---|---:|---:|---:|---:|
|HEAD `5ca7b47`|175640|127474|48136|30|
|C5代码量峰值|207498|157343|49502|653|
|C5.3开始前|203462|154865|47944|653|
|最终WORKTREE|205008|156105|48250|653|
|HEAD→最终|+29368|+28631|+114|+623|
|C5峰值→最终|-2490|-1238|-1252|0|
|C5.3前→最终|+1546|+1240|+306|0|

最终653行unclassified仍全部来自既有三份SIMION probe和本轮623行loader characterization；没有把它们
静默归入production或tests。integration沿用既有`.py/.ps1/.lua`脚本口径：HEAD/C5开始为
`130 = 77 production + 53 tests`，C5.3开始前为`128 = 75 + 53`，最终为
`127 = 74 production + 52 tests + 1 unclassified`；唯一公开科学workflow由HEAD的2个降为并保持1个
`workflows/family_source_closure/execute.ps1`。最终74个production脚本共27242 CLOC，其中Python
56个/19843行、PowerShell 13个/6952行、Lua 5个/447行；phase-space窄修相对修复前只增加1行production
CLOC，没有增加脚本或入口。

已归档wall time只作为负载不同的观测：C5.1/C5.2的30行ValidateOnly为
`118.319 s`，旧C5.3的34行为`126.7 s`；L1分别为`124.7 s/68 paths`、`123 s/81 paths`，本轮为
`125.001 s/84 paths`。因行数和changed-path范围不同，不作性能提升或退化结论。本轮可直接比较的同一
full integration在修复前`67.117 s`失败、修复后`65.396 s`通过；这只说明缺口闭合，不作为性能基准。

### C5.4 首次baseline失败、canonical修复与r01 successor

首次获授权的`pulse_resolution_direct_baseline_v5`运行
`20260815_160000__sim__cross__pulse-direct-real-rr__n100`在SIMION启动前失败：prepare与composition已通过，
adapter在PowerShell StrictMode下读取不存在的旧字段
`single_flight_accelerator_field_profile_id`，因此PA cache/build/refine/Fly均未开始。失败run保持terminal
`failed`，manifest SHA-256为
`477A8BA8822256AC585F9DB64F443D51B3C525660904D95738896D928C8BF994`，不得复用该run ID。

修复只把adapter的场profile读取改为冻结plan已有的canonical
`resolved_region_field_profile_id`，没有恢复旧字段或增加第二权威。此前`ValidateOnly`只验证plan后即退出，
不会调用adapter，因此新增严格冻结plan回归明确覆盖canonical正例、旧字段缺失负例及该层级边界。旧campaign
`pulse_resolution_direct_campaign.json`保持内容SHA-256
`E4AC9275B4970721088797AD67DAC979D84D4BDF7FCE52003DD554DAA78AD47B`不变，并与失败run证据一起登记为
`non_executable_historical_evidence`。

新的唯一活动baseline为`pulse_resolution_direct_baseline_v5_r01`，文件
`pulse_resolution_direct_baseline_successor_campaign.json`，run ID为
`20260815_160000__sim__cross__pulse-direct-real-rr__n100__r01`。除campaign ID与run ID外，它与失败campaign
的规范科学JSON完全相同；回归测试删除这两个identity字段后要求深比较为零差异。本节只记录solver-free
修复与继任关系，不包含新的SIMION、分辨率或资格结果。

### C5.5 r01 cache-miss失败与r02构建策略继任

唯一获授权的r01 baseline在约10秒内于frontend PA cache门禁失败关闭。父run
`20260815_160000__sim__cross__pulse-direct-real-rr__n100__r01`与子run
`20260815_160000__sim__simion__rf-oatof-single-flight-gap0__n100__r01`均为`failed`、
`formal_eligible=false`；父/子manifest SHA-256分别为
`6860D9D13AC0A65EA6D9476277EA9F5F4289FD359792D8861364518B4F1804A5`与
`F4364A48EE94D9B9D4A9102C834B6E1A3CE5B6B8C0F4C42D78693C074B8BAFE9`。失败原因是显式
`require_existing`要求的frontend key
`01C205C64FC144710678BF823E3ED3852C28EA2992C6C14064CA2A53F4515309`不存在；SIMION、build、
refine与Fly均未启动。`100/66/50/16`只在prepare冻结输入中闭合，不是本run的求解观测；正式baseline
result、receipt及promotion均未生成。

只读cache审计按schema-v2 identity精确重算该key。它与既有`c612...`的schema、role、project、SIMION
版本/可执行文件身份及gem2pa/refine参数完全相同，唯一差异为原始frontend GEM SHA。两份GEM的几何/
电极正文相同，只是`upstream_resolved_sha256` provenance注释不同；当前cache合同哈希完整GEM字节，故
不得复制、重索引或把`c612...`冒充为新key。其余frontend/formal cache具有不同布局，accelerator-overlay
cache又属于不同role和输入结构；结论是该精确组合从未构建，而非role或索引错误。

r01 campaign保持SHA-256
`D9F66C43A702DC52FF113A5C5A87E97CF391D6183A9B0915A053FF4993728904`并登记为
`non_executable_historical_evidence`。活动successor为
`pulse_resolution_direct_baseline_successor_r02_campaign.json`，campaign ID
`pulse_resolution_direct_baseline_v5_r02`，run ID
`20260815_160000__sim__cross__pulse-direct-real-rr__n100__r02`。相对r01只改变两个identity字段及
`single_flight_pa_cache_policy: require_existing -> build_and_publish_if_missing`；删除这三个执行/身份差异
后规范JSON深比较为零。该策略复用唯一官方runner已有的原子构建发布路径，不增加第二实现。本节当前只
登记solver-free继任，尚未授权或执行r02 SolverAuthorized。

### C5.6 loader characterization receipt compact-v2 迁移

本轮只迁移Git内逐点诊断证据的存储形态，不改变任何科学阈值、生产消费者字段、SIMION输入或历史
campaign。迁移前两份schema-v1 JSON分别为：

|旧Git receipt|bytes|lines|冻结SHA-256|
|---|---:|---:|---|
|`staged_grid2_n34_simion_fly2_loader_ab_characterization.json`|623508|15669|`08E4C988D0D64C5B6D4EC50F64B74D3C439D06AFABCDAF07E57D66A74126E0E5`|
|`staged_grid2_n34_simion_fly2_loader_authorization_budget.json`|311736|7828|`3C55554E41C9D016C3A2DEC8CB11DC1FFC1436FC843805D0E8987CDE32CDF1FE`|

确定性迁移run为
`20260815_223500__migration__repo__staged-grid2-loader-receipt-compact-v2`。其受管ZIP
`results/staged_grid2_n34_simion_fly2_loader_raw_receipts.zip`为53068 bytes，SHA-256为
`86DB4FB500C2C9EF1FDD32541CACD9A0D054D190D572B6CF5EAFE12C9C59C559`；固定member顺序、1980-01-01
时间戳、Unix 0644权限和DEFLATE level 9。ZIP内两份member逐字节恢复上述旧JSON，member bytes和SHA-256
均被冻结，并由测试验证可从旧raw确定性重建当前compact summary。

Git中的两份receipt现为既有schema的version 2 compact summary：characterization为8822 bytes/181行，
SHA-256为`3154AD9FF08660C3636FFBBD80A16BCE38956E55DB04EBD3592A2C24BAEAD74C`；authorization
budget为4985 bytes/96行，SHA-256为
`B8BEB73EB1F6B1650A6AB4FA5E50784169CDB7FCCE0A3BB044A765ED10E72B32`。前者删除四个逐点数组，后者
删除两个逐点数组；所有production消费者字段保留，两份summary共享同一个`raw_evidence`描述符。
`prepare.py`最小兼容schema v1/v2；v2只校验受管容器path/bytes/SHA和冻结member描述，不在运行时解压。

r06/r07/r08及其run artifact保持immutable；r08子run仍保存旧authorization budget的exact-byte副本。
本迁移未执行SIMION、未生成新科学结果，也不改变既有NO-GO/GO结论。项目级artifact layout的既存失败只来自
此前不完整且待外部删除的`20260815_120000__sim__cross__staged-grid2-restart-legacy__n34__r02`，不得在本迁移中
伪造补齐；compact-v2迁移run自身`run_config.json`、`summary.json`、`run_manifest.json`三件套完整。
