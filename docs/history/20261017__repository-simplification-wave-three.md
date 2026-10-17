# 全仓精简第三轮：验证净收益与发布工作复用

DOC_STATUS: ARCHIVED_READ_ONLY

本页冻结2026-10-17第三轮深度精简；本轮基线为`e22b6d83ca8beb2805f6434fa57e78c8fdd8e9fe`，
结果源码为`083867d5592ae17f22d59a846bc0ca627d116c68`。前两轮结果见[第一轮](20261017__repository-simplification-wave-one.md)与
[第二轮](20261017__repository-simplification-wave-two.md)，不重复计入本轮收益。
本轮重新评估剩余检查、哈希与物化是否改变实际决策、检测何种错误、以及是否值得读写/维护成本；
“有消费者”本身不构成保留依据。

## 覆盖与实施

Agent 0负责公共发布/合同、整合和度量；Agent 1负责OA/加速器/MR，Agent 2负责四/六/八极与公共多极杆，
Agent 3负责IP/双锥/EI/Wehnelt，Agent 4负责integration与公共连接。修改范围互斥，Git由Agent 0串行执行。
Agent 1独立复核公共发布，Agent 3复核OA/MR，Agent 4复核多极杆；最终源码冻结后运行联合门禁。

| 范围 | 已实施精简及实际收益 |
|---|---|
| 公共manifest发布 | producer停写后writer与紧接的verifier使用同一file_record/SHA实现，第二次全文重读不是独立算法保障（同次仍按实际路径/读取策略复用身份）。删除公共PS发布器的第二Python进程、重复载荷哈希和目录扫描；缺失输出拒绝前移至writer CLI，写后精确读回manifest字节而非再次读取全部载荷。独立消费者默认仍fresh完整验证 |
| 公共输出列表运输 | 大量路径由UTF-8 stdin传递，消除每次manifest的临时JSON创建/写入/读回/删除；仍支持JSON文件输入、重复--output、空数组和超40k字符含中文路径 |
| 公共死包装/重复实现 | 删除仅由测试调用的Initialize-RunRecord，fixture转现有New-RunPackage；删除无调用的Copy-FrozenDependency；writer/verifier共用同一延迟保留策略入口 |
| OA输入计划 | 删除candidate_consumption_plan.json结构、读写及重写逻辑。三份真实SIMION文本身份进入既有config.inputs/input_sha256，无新增账本；每Candidate少一文件、两次写/两次读，完整prepare/start合计少两次resolved SHA；radial每case少一份文件 |
| OA路径查询 | 已登记路径解析不再重复验证整个闭包；保留未登记/重复登记/schema/role/逃逸检查。真实75文件闭包取3路径，228次SHA+3次rglob→0，返回路径一致；freeze/start/stage/final实际边界仍验证 |
| MR固定镜消费 | fixed-grid loader只核验run_config及point/period/native/probe四份物理证据，保留条件source合同校验。真实r130样本50次SHA、1,412,007B→7次、232,939B；返回对象完全相等，少43次与1,179,068B。无关附件漂移不再阻断该明确消费范围，不宣称整个上游run重新完整或取得资格 |
| 四/六/八极源投影 | CSV字节一次读取，同时用于SHA、解析和完整物理校验；SIMION消费已校验rows，移除重复plane判断。N100预检+全投影+两50粒子batch，11次源读取→4次；planar/volume各完整/subset+offset共4组FLY2/Lua与基线逐字节相同 |
| 多极杆runtime解析 | 同次source摘要2→1，campaign摘要4→1；无跨调用cache或参数覆盖 |
| 家族生产门禁 | 删除129行wrapper/support源码拼写/次数检查（diff文本量，不作CLOC）；每次少读取6份wrapper和3次support。真实PowerShell行为回归验证三项目×两solver、默认身份、参数传递、各调用恰一次、非法stage/数值/solver在runner前拒绝与TEMP清理；有效RF冻结覆盖迁入已有家族测试，删除一个测试脚本 |
| IP组件出口 | 复用刚核验的9份manifest输入记录，release receipt按精确路径/bytes/SHA与已验证身份比对；每次少11次全文读取，冲突与同大小篡改仍拒绝 |
| IP绘图 | 删除无决策作用的native_pa0_sha256字段及PA全文读取：图只消费采样CSV/resolved，额外PA哈希不能证明CSV由它产生。保留实际绘图输入provenance；post绘图删除5次after-hash，行为回归证明源内容/文件集合保持。默认整合直接使用返回stats，少一次刚写统计JSON读回；研究者JSON保留 |
| Wehnelt | 删除以固定英文句子、键集合等阻断的重复mode检查及实现形状测试。真实build-only、禁止求解和资格边界继续由resolved/numerical modes与MATLAB实际提前返回保证 |
| integration分域 | 删除无决策消费者的domain_split_runtime_contract.json及write-only required_pa_roles；真实gap/extents/thickness、PA/IOB选择及分域失败判据保留 |
| integration人口运输 | 保留唯一人口投影校验进程，改stdout直接返回；不再物化resolved_single_flight_population.json、重复读回/输入登记/下游marker检查。冻结raw resolved_population_contract仍拥有实际人口语义 |
| 公共连接schema | registry递归schema已完整覆盖所有profiles，删除3处重复profile校验；22-profile标准链每次少24次重复遍历，两个独立public入口及port/authority语义仍核验 |
| integration发布 | Python直接调用现有build_run_manifest/write_json_atomic，删除success/failure两段Python→Python CLI argv/超时/进程壳，每次终态少一个Python启动；原ContractError失败和输出语义保留 |
| 加速器/双锥/EI | 逐入口审查剩余校验、哈希与文件。没有为删行撤掉不同信任/写入边界的数值、单位、源/发布代和私有可写PA保护；收益与成本见下节 |

没有新增生产脚本、旁路验证开关、持久缓存、第二账本或审计框架。
本轮脚本总数1,193→1,192（生产725不变，测试468→467）；生产代码净减365行，总代码净减211行，
测试代码净增154行。没有把测试增长隐藏进生产统计，也不把第一/二轮成果算作本轮删除。
删除的测试脚本基线逻辑大小4,798字节，其有效覆盖已迁入已有测试边界。
本轮不清理任何已有PA/MPH/图或历史run，不改写前两轮历史。唯一删除的Git源码可由基线恢复；
源码逻辑大小与实际磁盘释放量不同，本轮未计量磁盘可用空间变化。
一次性探针以内联命令/内存模块进行；长期行为回归扩展已有测试，没有遗留一次性脚本。

## 对照复现入口

- MR历史样本为工作区artifact根下
  `projects/parallel_mirror_dual_stripe_mr_tof/runs/20260917_223000__sim__simion__mrtof-measured-chord-root-fixed-grid-r130/run_manifest.json`；
  只读补取的小manifest SHA256为`2BD9ECC925813636AACF400A7F7B8CE915229E3963256D821628437ABAD87007`。
  下游合同为`projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json`，
  SHA256为`8DED9B0D2067699B08C769DAA8E7A6EE41E906C487128EBF028FC05C36067103`。
  原探针对相同两输入执行基线旧loader与当前loader，计binary身份读取open及每次文件大小，
  包含downstream/条件source两次读取，不含JSON文本解析，也不是计时基准；两返回对象相等。
  SHA是之后只读补取，原探针未同时记录，不伪称当时冻结了该补充身份。
- OA 75文件closure是TemporaryDirectory中调用真实freeze函数的源码fixture，不对应物理run；
  取3个登记路径对照旧/新helper，退出时自动清理。
- 多极杆4组字节对照使用`common/multipole/test_particle_source_preflight.py::ParticleSourcePreflightTest`：
  planar由setUp/write_source(count=100)确定性生成；volume沿原nonplanar-source-exception spec，
  count=20/seed=7，调用公共release materializer。两者各完整投影及ID3..12/offset2；
  旧preflight/renderer从基线Git blob仅在内存加载。
- M3剩余机会量化使用
  `projects/rf_quadrupole_ion_optics/tests/analysis/test_same_solver_numerical_convergence.py`：
  make_run(solver=SIMION, steps=40, handoff_ids=1..100, particles=100)，原generate_bundle/default seed，
  角色直接取该模块PORTABLE_INPUT_ROLES的13项。Path写入被内存覆盖拦截，无磁盘MEMORY_ONLY_M3目录。

## 保留项的净收益与成本

| 保留边界 | 防止的具体错误与决策收益 | 成本及为何不改为更弱替代 |
|---|---|---|
| 独立消费输入/结果内容SHA | 发布以后同长度内容被改、错误文件被替换时拒绝，避免把另一组源/场/粒子证据用于物理结论；回归含真实字节篡改与路径替换 | 仅在独立消费所需记录上读取内容；同次重复身份复用，MR已收窄无关附件。大小/mtime无法检测同长度替换，不能替代该边界 |
| 发布后小manifest精确读回 | 拒绝截断JSON、重复键和schema_version 1→true等有效JSON但字节/类型改变；公共PS在失败时保留旧manifest | 读清单大小字节，而非载荷大小；直接bytes比较避免Python字典true==1等宽松相等。已删除第二次全文SHA与verifier进程 |
| OA每stage闭包与输入身份 | stage间可隔着长求解/外部执行，防止下一阶段使用改变的冻结代码、解释器或合同，确保同一Candidate可追溯；三生成文本任一篡改拒绝 | 实际stage边界一次完整核验仍有成本；路径查询无需这一重复成本，已删228次/3路径示例。不能跨stage长执行沿用旧验证结论 |
| canonical源物理验证 | 及时拒绝非法质量/电荷、能量、NaN、重复ID、错误plane/volume/clock，避免昂贵运行得到错误粒子输入 | 单个字节快照同时哈希/CSV/校验，返回rows给投影，不再第二次解析或逐层重复plane判断 |
| v2保留合同与容量inventory | 发现manifest遗漏的重载荷、防止compact误留PA/轨迹；容量还须计算新清单/收据、未列小文件与链接，避免错误准入耗尽磁盘 | 保留必要目录元数据发现；共享PS发布已删即时verifier的第二遍。加总manifest会漏算新文件或误算外部输入，不能代替实际占用 |
| summary/manifest原子journal | 进程在两个终态文件中间崩溃时拒绝混合终态并可重放，避免中断被误认为完整成功 | 只处理小JSON，不读取重载荷；真实故障注入回归保留。直接顺序覆盖两文件不能等价恢复 |
| 原生PA只读源到私有可写副本 | Fast Adjust/GUI/求解器需要写副本；直接引用或共享可写源会破坏缓存代际与其他run输入，错误场可能静默进入飞行 | 内容验证与复制确有I/O成本，但处于真实写入/所有权边界，不是纯运输JSON。禁止用文件存在/大小代替已冻结代际身份 |
| EI/MATLAB独立入口单位/角色/mode | 用户可直接从MATLAB/resolved启动而未经过Python gate；缺单位/非法域/错误模式会得到错误几何或求解 | 廉价小合同解析保护独立入口，不是同次调用层层重复的文本assert；无需新增公共验证框架 |
| MR真实plan与OA baseline/resolved/working points | 不同进程或Python/Lua消费冻结的单一派生权威，防止各语言重新推导不同值；working points保存case指标无法还原的实际电压解 | 小合同承担跨进程/语言实际交接；本轮只删重复消费计划、派生人口/预算运输，不另造来源与重建规则 |

两处已识别的剩余机会也按成本说明，不能把它们称为永久必要：

- 四极same-solver closure的公共预检与evaluator私验仍有重复SHA。当前N100选择13输入的内存fixture，
  第二遍两个closure可省34次SHA、178,034字节；该fixture不复制PA本体，仅存库存，也未模拟搬迁配置字节变化。
  公共边界额外保护schema/journal/v2 retention与未列重载荷，私验额外保护config身份一致和portable source identity；
  直接删除任一整层会漏掉真实检查。当前没有公共完整验证函数API，用CLI替换需冻结最多7依赖文件共59,673字节及隔离回归，
  会增加该小fixture的复制/身份成本。更好的后续是抽出已有完整验证的函数并同时删除私验重复体；本轮未为约178KB样例
  再扩一套验证接口/临时receipt，不把重复SHA本身说成科学保障，也不声称该路径已精简完毕。
- Wehnelt保留275字节mode描述及run副本：它没有科学决策收益，但冻结Static gate内registry发现仍要求同目录文件存在。
  仅删副本会使真实隔离gate失败。完整删除需要把仓库发现检查移出run-local冻结gate；本轮省去大段文案阻断后，
  不为这275字节副本引入skip标志或一套额外门禁分层状态。其成本是一次微小复制、复制边界3次SHA及正常manifest身份，
  不是求解保护；应随后续发现/运行gate职责收口删除，不能将“有消费者”当作永久保留理由。

双锥CSV验证后再次解析亦是低收益候选：两次分别执行源/事件/数值拒绝与投影，若共享已解析rows可去重，
但应在现有验证返回边界统一实现；本轮未为单项目小CSV额外增加开关/缓存或复制校验器。EI的独立MATLAB输入检查则
有真实信任边界，未将它与上述重复解析混为一类。

## 验证、适用边界与中间发现

最终源码/测试固定为53条变更，绑定编译器生成1份implementation配置并通过check。
`common/verify_changed.ps1`终态为`CHANGED_GATE=PASS PYTHON=3.11 CHANGED_PATHS=53 FULL_SCOPE=False`。
随后同一会话执行完整L2，最终结果见下表。

| 验证 | 结果 |
|---|---|
| L1／全仓L2 | PASS；同一冻结源码，无测试后生产修改 |
| 公共合同／多极杆／SIMION | 646（skip 1）／413／262（skip 6） |
| integration／MR／OA | 891（skip 3）／1,412（skip 10）／386（skip 1） |
| 加速器／四极／六极／八极 | 93／230／22／29 |
| IP／双锥／EI／Wehnelt | 169／30／22／49 |
| 关键focused | 公共manifest/终态29项及实际PS helper；OA69、MR14；源/runtime36及家族19；IP出口/Wehnelt54、绘图33；分域68、人口/公共连接53、真实父发布4 |
| 对照 | OA路径228SHA/3扫描→0；MR相同物理对象与实际读取字节；源4组FLY2/Lua字节相同；UTF8/GBK父环境launcher调用通过 |

测试数包含其中显式skip，skip不等于已验证对应层级。最终进程退出码0，终态为`REPOSITORY_INTEGRATION_GATE=PASS PYTHON=3.11`，上海2026-10-17 22:39前后完成。
中间L1先发现新家族行为夹具三处subprocess缺cwd，修复后19项通过；随后并行环境发现PowerShell错误输出
继承GBK导致UTF8解码失败，已在子进程显式固定UTF8，且GBK父环境下19项复验通过。两次失败均是新增fixture
的执行环境问题，没有改物理输入、放宽科学断言或关闭错误；最终联合结果只计最后同一冻结版本。
文档/索引另走文档范围L1。

没有测量端到端求解加速；本页只报告调用、实际读取字节、物化与代码/脚本变化。
没有运行真实Refine/Fly、COMSOL Compute、GUI/CAD或Formal验收，纯Lua与模拟入口夹具不等同商业求解。
本轮未改变物理参数、粒子数、数值精度、统计定义或资格阈值。

## CLOC

固定对照：
`common/report_cloc_delta.ps1 -Base e22b6d83ca8beb2805f6434fa57e78c8fdd8e9fe -Current 083867d5592ae17f22d59a846bc0ca627d116c68`。
`CLOC_DELTA=PASS`，CLOC 2.10，固定结果测量时工作树干净，unclassified=0。
分类器SHA256：`cbfb4c9eebbb38285800e4e358a13ef66c73404c4d399b8e4bd3687f71064285`；
语言定义SHA256：`985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6`。
基线选中文件身份`a4fdadabb87d43452f1ab1fdd1669f4bda09c88347534d9be9a7a1659decbb35`；
结果选中文件身份`de8ea13abb1bfaed14f018fcb83103f954ec2dafd5a71766e5c5299dad9f2b01`。
后续纯Markdown报告/索引提交不改变本源码计数。

完整过滤口径（与工具输出一致）：

```text
extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd
excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs
excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**
language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM
production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named)
tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|*Test.m|*.Tests.*
unclassified=other_code_below_test_or_tests_path
worktree_source=git_tracked_plus_nonignored_untracked
```

| script category | baseline | result | delta |
|---|---:|---:|---:|
| production | 725 | 725 | 0 |
| tests | 468 | 467 | -1 |
| total | 1193 | 1192 | -1 |

脚本数采用SCRIPT_FILES，包含模块与语言脚本，JSON/TOML/YAML配置不算脚本。
以下每格为baseline → result（delta），语言分类与文件/空白/注释/代码均保留。

### total

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 511 → 511 (0) | 0 → 0 (0) | 0 → 0 (0) | 49732 → 49732 (0) |
| Lua | 91 → 91 (0) | 424 → 424 (0) | 694 → 694 (0) | 9515 → 9515 (0) |
| MATLAB | 117 → 117 (0) | 991 → 991 (0) | 2264 → 2264 (0) | 14134 → 14134 (0) |
| PowerShell | 152 → 152 (0) | 1211 → 1210 (-1) | 1425 → 1420 (-5) | 47665 → 47531 (-134) |
| Python | 823 → 822 (-1) | 23002 → 23002 (0) | 15197 → 15206 (9) | 280296 → 280219 (-77) |
| SIMION GEM | 10 → 10 (0) | 35 → 35 (0) | 81 → 81 (0) | 246 → 246 (0) |
| TOML | 1 → 1 (0) | 4 → 4 (0) | 0 → 0 (0) | 24 → 24 (0) |
| YAML | 2 → 2 (0) | 4 → 4 (0) | 1 → 1 (0) | 120 → 120 (0) |
| SUM | 1707 → 1706 (-1) | 25671 → 25670 (-1) | 19662 → 19666 (4) | 401732 → 401521 (-211) |

### production

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 507 → 507 (0) | 0 → 0 (0) | 0 → 0 (0) | 49622 → 49622 (0) |
| Lua | 75 → 75 (0) | 331 → 331 (0) | 611 → 611 (0) | 7797 → 7797 (0) |
| MATLAB | 77 → 77 (0) | 542 → 542 (0) | 1743 → 1743 (0) | 10429 → 10429 (0) |
| PowerShell | 144 → 144 (0) | 1157 → 1155 (-2) | 1403 → 1398 (-5) | 46301 → 46175 (-126) |
| Python | 419 → 419 (0) | 13446 → 13440 (-6) | 8339 → 8340 (1) | 157719 → 157480 (-239) |
| SIMION GEM | 10 → 10 (0) | 35 → 35 (0) | 81 → 81 (0) | 246 → 246 (0) |
| TOML | 1 → 1 (0) | 4 → 4 (0) | 0 → 0 (0) | 24 → 24 (0) |
| YAML | 2 → 2 (0) | 4 → 4 (0) | 1 → 1 (0) | 120 → 120 (0) |
| SUM | 1235 → 1235 (0) | 15519 → 15511 (-8) | 12178 → 12174 (-4) | 272258 → 271893 (-365) |

### tests

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 4 → 4 (0) | 0 → 0 (0) | 0 → 0 (0) | 110 → 110 (0) |
| Lua | 16 → 16 (0) | 93 → 93 (0) | 83 → 83 (0) | 1718 → 1718 (0) |
| MATLAB | 40 → 40 (0) | 449 → 449 (0) | 521 → 521 (0) | 3705 → 3705 (0) |
| PowerShell | 8 → 8 (0) | 54 → 55 (1) | 22 → 22 (0) | 1364 → 1356 (-8) |
| Python | 404 → 403 (-1) | 9556 → 9562 (6) | 6858 → 6866 (8) | 122577 → 122739 (162) |
| SUM | 472 → 471 (-1) | 10152 → 10159 (7) | 7484 → 7492 (8) | 129474 → 129628 (154) |

### unclassified

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| SUM | 0 → 0 (0) | 0 → 0 (0) | 0 → 0 (0) | 0 → 0 (0) |
