# 冻结母群 handoff 复用与 N50 读入复验

DOC_STATUS: ARCHIVED_READ_ONLY

2026-09-04 阶段证据。未完成八孔径当前对照，不构成效率、分辨率或 Formal 结论。

## 来源审计

9月1日方形四孔径 producer（203653、205305、205755、210247）共有同字节5000母粒子，
SHA=88C5BD19E33D1F88F032BAEEAE869930E4CB10AA227B2A45A52C3519114B6941。
它们使用固定窗口、stride40，不能与9月2日h100自然全程、stride1的最优pulse混为孔径控制变量。

本次采用20260902_071500__analysis__python__ideal-accept-square-h100-pulse-eligible-restart__n50：
其实际producer是20260902_032202__sim__simion__rf-oatof-single-flight-gap102p4__n5000。
全5000自然geometry_collision、pulse disabled；1.1MHz每周期40格、stride1、clock origin0。
detector-blind sample3618选择82.20454545454545 us的全部50粒子，不是共同命中筛选。
上游来源与当前N1的碰撞域x_min存在10mm差异，未证明等价，因此本次仅为该历史母群的条件post-pulse。

## 发布与执行

既有publisher新增互斥materialization-manifest/compact-receipt，复用同一derive实现，不复制状态、
不重飞上游。输入记录保留真实证据角色，保持5000母群分母、50个冻结状态及其源ID映射。
当前脉宽由全部状态派生6.970278629109567 us，不沿用旧1us。

派生run：20260904_120400__analysis__python__rf-oatof-h100-frozen-handoff-successor__n50。
公开ValidateOnly通过；真实run：
20260904_120605__sim__simion__rf-oatof-single-flight-gap102p4__n50。
共享调度器单路完成50粒子，原生exit0，批飞行145.414s、波次147.532s，无refine。
后处理source-release验证失败，整次run按failed发布，未报告探测效率或分辨率。
容量496.69GiB，未删除cache，租约释放。

## 精确失败项

Agent1独立比较全部50个actual source_release与冻结初态；位置/时间最大误差均0。
速度最大误差7.804810593370348e-7 m/s，小于1e-6门限。
唯一能量超限为ion27／source2679：5.48406831057946e-9 eV，大于冻结5e-9门限；
第二大4.422087585e-9，未超限。冻结energy与冻结velocity公共重算完全一致：
18.454227171189157 eV；actual速度重算18.45422716570509 eV。
差异来自读入后的微小速度变化，不是ID、时钟、位置或输入能量自一致性错误。
没有放宽门限或篡改原始结果。下一步检查官方初始化速度赋值路径，保持严格冻结初态后再复验。

## 验证

Agent2新增publisher互斥与转发测试2项，加既有derive测试共3项通过；
相关Python Ruff通过。商业飞行完成，但分析门禁失败；不宣称本次成功物理结果。
未进行N5000八案例、全流程对照、GUI/CAD或全仓L2。源码未提交。

## CLOC

BASELINE=842228787b86b526c7137b7a45ef5d35113a73f9 → WORKTREE，CLOC 2.10；
CREATED_UTC=2026-09-04T04:06:34.6327339+00:00。共享工作树整体统计，不等于本次修复增量。

|分类/语言|files|blank|comment|code|
|---|---|---|---|---|
|total/JSON|455→461 (+6)|0→0 (0)|0→0 (0)|42649→44760 (+2111)|
|total/Lua|54→72 (+18)|319→348 (+29)|323→450 (+127)|5493→6606 (+1113)|
|total/MATLAB|106→107 (+1)|963→939 (-24)|2237→2157 (-80)|12507→12407 (-100)|
|total/PowerShell|106→107 (+1)|816→822 (+6)|756→860 (+104)|29443→30008 (+565)|
|total/Python|539→600 (+61)|12814→13954 (+1140)|4730→5464 (+734)|149280→159513 (+10233)|
|total/SIMION GEM|10→11 (+1)|35→35 (0)|81→83 (+2)|246→256 (+10)|
|total/TOML|1→1 (0)|4→4 (0)|0→0 (0)|24→24 (0)|
|total/YAML|2→2 (0)|4→4 (0)|1→1 (0)|114→114 (0)|
|total/SUM|1273→1361 (+88)|14955→16106 (+1151)|8128→9015 (+887)|239756→253688 (+13932)|
|production/JSON|451→457 (+6)|0→0 (0)|0→0 (0)|42539→44650 (+2111)|
|production/Lua|46→60 (+14)|226→253 (+27)|302→398 (+96)|4509→5265 (+756)|
|production/MATLAB|68→70 (+2)|504→503 (-1)|1685→1640 (-45)|8852→8933 (+81)|
|production/PowerShell|98→99 (+1)|767→773 (+6)|750→854 (+104)|28590→29152 (+562)|
|production/Python|293→330 (+37)|7989→8788 (+799)|3769→4372 (+603)|87596→94427 (+6831)|
|production/SIMION GEM|10→11 (+1)|35→35 (0)|81→83 (+2)|246→256 (+10)|
|production/TOML|1→1 (0)|4→4 (0)|0→0 (0)|24→24 (0)|
|production/YAML|2→2 (0)|4→4 (0)|1→1 (0)|114→114 (0)|
|production/SUM|969→1030 (+61)|9529→10360 (+831)|6588→7348 (+760)|172470→182821 (+10351)|
|tests/JSON|4→4 (0)|0→0 (0)|0→0 (0)|110→110 (0)|
|tests/Lua|8→12 (+4)|93→95 (+2)|21→52 (+31)|984→1341 (+357)|
|tests/MATLAB|38→37 (-1)|459→436 (-23)|552→517 (-35)|3655→3474 (-181)|
|tests/PowerShell|8→8 (0)|49→49 (0)|6→6 (0)|853→856 (+3)|
|tests/Python|246→270 (+24)|4825→5166 (+341)|961→1092 (+131)|61684→65086 (+3402)|
|tests/SUM|304→331 (+27)|5426→5746 (+320)|1540→1667 (+127)|67286→70867 (+3581)|

完整过滤口径：
```text
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```
