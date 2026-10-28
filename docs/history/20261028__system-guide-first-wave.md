# 独立系统指南第一波阶段验收

DOC_STATUS: ARCHIVED_READ_ONLY

依据[独立系统审查与修改指南（基线 3005980）](https://chatgpt.com/space/page_4e30e6be7c308191b188c3625d498db3)，记录本阶段已验证的实现、成本与范围；当前行为见[公共机制说明](../../common/README.md)和[容量合同](../../common/contracts/README.md)。

本报告验收的仅是：G1/G4 的测试选择与 effective 计划，G2 的显式消费者审计及 staged 字节检查，G3 的基础持久摘要，C1 的账本索引，C2 的计时与 owner 结果，C3 的同一 CLI 新鲜准入决定复用；另记录完整门禁暴露的 PID 创建身份归属修复。**不据此宣布 G1–G4 或 C1–C3 整组全部闭环。** G2/G4 的硬检查路径缩小仍未实施；G3 的更细 phase 计时／队列策略，以及 C3 的具名 reseal／pressure 维护均不在当前闭合范围。

**这是阶段检查点；用户扩大的全指南目标仍开放，不能把本报告、阶段提交或一次 L2 PASS 当作全目标完成。** 上述剩余项及 H1–H5、科学控制器职责、依赖拆分、其他 dead/duplicate 等仍由全量逐项矩阵继续审查和执行。

源码基线为 `3005980a9a0d3a62a67f36dff389a3110868faa7`。阶段提交依次为 G2 `b0d30608`、容量 `b0f1e9ac`、PID 归属 `bc8e859e`、门禁 `c9467c44f632fa60e943cc80bb4b6e2a0d9246b0`。完整 L1/L2 使用提交前冻结的同一源码；提交行为不构成额外测试。官方 exact-SHA CLOC 已 PASS，绑定最终阶段提交 `c9467c44f632fa60e943cc80bb4b6e2a0d9246b0`；本文采用该提交身份。

实现保持唯一 catalog、既有 owner、容量账本和资源租约。G1/G4 将被改测试接入真实命令，删除／fixture／未知路径扩大到正确 owner；G2 默认保留全量硬检查，消费者审计改为显式请求并复用 AST，pre-commit 检查 Git index 原字节；G3 保存阶段状态与子进程收据，失败、未选、中断不能冒充成功，摘要写失败不覆盖原错误。C1 在原锁内建立引用账本对象的索引；C2 分别记录 owner 结果和计时，嵌套阶段不得双计 total；C3 仅复用同一 CLI 新鲜 startup 决定，独立 apply 仍重新准入。

PID 修复保存同一 PID 的多个真实创建身份，并统一普通后代／work 后代判断；旧孤儿继续受保护，无关 PID 复用后代仍被拒绝。固定输入可复现旧实现失败，修复和独立回归通过；缺少原失败时完整快照，不能据此确定归因那次 L2 异常。

以下是软件与合同验收。没有据此宣称执行商用求解器、GUI/CAD 操作，或新增科学、Candidate、Formal 资格。RF 行为夹具记录物理前置调用，实际执行 unittest、PowerShell Parser 和租约接口；它不等同于重算物理。

**最终完整门禁。** 连续执行两轮门禁的根运行最终退出 `0`（运行器终态）；最后两份摘要均为 PASS、error=null。

| 门禁 | 软件阶段 | unittest 执行／通过／跳过 | 摘要区间 elapsed_seconds |
|---|---|---:|---:|
| L1 r4，实际 changed scope | 18 PASS / 24 NOT_APPLICABLE / 0 FAIL | 2,167／2,165／2 | 1941.079916 s |
| L2 r2，完整 repository integration | 37 PASS / 0 NOT_APPLICABLE / 0 FAIL | 5,431／5,411／20 | 2374.088572 s |

L1 的 24 个 NOT_APPLICABLE 是未选路由，不是 unittest skipped。Python 数量为每轮日志中 `Ran … tests` 的合计，包含 skip；不跨轮去重，不把 PowerShell 合同阶段计作 Python 用例。L1 MR 阶段虽然名称带 `_static`，实际命令是 `Level=Core`，只运行 42 项；RF 四极也是 Core 加被改模块，14 项。

摘要顶层区间从 `New-GateRunSummary` 内 Stopwatch 开始，到 `Complete-GateRunSummary` 完成；不含此前 PowerShell 启动和计划构建，所以**不能称为整个命令进程墙钟**。阶段区间包围本阶段操作；日志中的 `GATE_PROCESS=COMPLETE … ELAPSED_SECONDS` 另含子进程启动等成本；unittest 数字只计其测试体。阶段可并行，不求和或取最大值来补造整轮 wall。

L1 关键当前值：common 803／1 skip，测试体 1687.001 s、阶段 1692.297233 s；整机 605／0，1870.219 s、1888.815605 s；MR Core 42／0，227.807 s、245.702923 s。

L2 的 37 个实际阶段如下。横杠表示该阶段未报告 unittest 数量，不表示未执行或零条通过。

| L2 阶段（全部 PASS） | unittest 执行／skip | 测试体 s | 阶段 s |
|---|---:|---:|---:|
| `documentation` | — | — | 15.492081 |
| `repository_text_bytes` | — | — | 14.136007 |
| `development_standards` | — | — | 19.750686 |
| `ruff_all` | — | — | 6.036104 |
| `host_resource_scheduler_tests` | 80／0 | 59.694 | 64.447352 |
| `host_resource_adapter_tests` | — | — | 57.758532 |
| `livelink_resource_stages_tests` | 41／0 | 189.136 | 202.894502 |
| `longitudinal_fit_tests` | 3／0 | 0.112 | 11.736273 |
| `peak_metrics_tests` | 25／0 | 0.063 | 12.716712 |
| `figure_export_tests` | 5／0 | 0.229 | 9.001585 |
| `beam_focus_diagnostics_tests` | 20／0 | 3.993 | 8.843136 |
| `particle_census_tests` | 12／0 | 0.002 | 7.696254 |
| `plane_crossings_tests` | 23／0 | 0.039 | 11.167042 |
| `population_moments_tests` | 10／0 | 0.141 | 4.916074 |
| `particle_events_tests` | 6／0 | 0.000 | 4.589856 |
| `tof_error_budget_tests` | 16／0 | 2.210 | 6.907299 |
| `documentation_link_tests` | 24／0 | 10.615 | 15.218031 |
| `project_registry` | — | — | 6.448959 |
| `livelink_failure_classification` | — | — | 4.274129 |
| `livelink_environment` | — | — | 4.250311 |
| `rf_multipole_generated_publications` | — | — | 24.342318 |
| `common_contracts` | 803／1 | 1799.582 | 1807.852407 |
| `simion_common` | 326／6 | 98.539 | 112.152129 |
| `rf_multipole_domain_tests` | 396／0 | 366.541 | 382.955194 |
| `integration_common` | 55／0 | 12.610 | 17.691265 |
| `instrument_assembly_integration` | 605／0 | 1977.008 | 1987.650682 |
| `solidworks_common` | 2／0 | 0.006 | 7.816238 |
| `orthogonal_accelerator_static` | 111／0 | 6.395 | 16.772962 |
| `parallel_mirror_dual_stripe_mr_tof_static` | 1693／12 | 2101.692 | 2126.274337 |
| `single_reflection_oa_tof_mass_analyzer_static` | 484／1 | 340.002 | 356.377804 |
| `rf_multipole_quadrupole_static` | 224／0 | 325.790 | 340.552432 |
| `rf_multipole_hexapole_static` | 18／0 | 30.280 | 37.693806 |
| `rf_multipole_octupole_static` | 19／0 | 30.526 | 46.803843 |
| `dual_pressure_rectilinear_ion_processor_static` | 328／0 | 176.065 | 186.469245 |
| `dual_cone_tandem_quadrupole_ion_interface_static` | 30／0 | 8.289 | 16.481259 |
| `transverse_helical_filament_wehnelt_electron_gun_static` | 50／0 | 34.015 | 53.217130 |
| `apertured_tube_electron_impact_ion_source_static` | 22／0 | 2.866 | 16.015271 |

修复期间失败的 L1/L2 和较早 PASS 不拼接为最终 PASS。最终判据是上述全部修复后同一冻结源码的两次完整运行。G3 对可控错误／中断有结果记录；硬杀或断电可能留下 RUNNING／PENDING，仍应判作未完成。

**定向行为与修复过程。** G2 的实际 Git index／提交行为测试 27 项 PASS，10.455 s；容量回归 181 项中 180 PASS、1 个 Windows 权限条件 skip，25.770 s。PID 固定 `PYTHONHASHSEED=0` 的旧实现三方法产生五个失败断言（遗漏 PID 3 或 5 的存活后代）；候选完整 54 项 PASS，2.569 s，独立九项 PASS，0.525 s。此处不声称旧实现必然解释某次没有保留完整观测快照的 L2 异常。RF 新行为回归分别 26.573／34.832 s，通过真实命令和测试模块验证，不以源码命令字符串形状代替行为。

| 本阶段早期运行 | 摘要区间 s | 当时结果与后续修复 |
|---|---:|---|
| L1 r1 | 44.010032 | FAIL；动态闭包使回调找不到脚本函数，修复调用边界 |
| L1 r2 | 2030.035406 | FAIL；显式测试选择丢失发现根的导入语义，恢复并复核 PYTHONPATH |
| L1 r3 | 1957.088368 | 当时 16 阶段 PASS；早于 RF 行为测试和 PID 修复，不替代最终 r4 |
| L2 r1 | 2461.083093 | 35 PASS／2 FAIL；旧 RF discover 字符串断言失效，另有父租约继承失败；修复后重新完整执行 L1/L2 |

已启动且健康的子任务自然结束，没有用杀进程或拼接各轮成功来缩短验收。上述早期失败被保留为过程事实，最终完整 PASS 见前表。

**历史参照先列范围。** 本轮记录的主机为 i9-9900K、8 核 16 线程、51,457,728,512 bytes RAM；2026-08-02 记录为 i7-8700、6 核 12 线程、约 48 GB，且测试集合小得多。10-27、10-28 的测试集合、修复状态及并发背景也不相同。没有对这些历史完整门禁进行同输入重测。

| 历史原件／范围 | unittest 执行／skip | 测试体 s | 阶段或整体结果 |
|---|---:|---:|---|
| [20261028__unified-diagnostics-review-acceptance](20261028__unified-diagnostics-review-acceptance.md) MR Static | 1693／12 | 1818.682 | 所在完整 L2 退出 1 |
| 同记录整机 | 605／0 | 1737.629 | 所在完整 L2 退出 1 |
| 同记录 common 单阶段复验 | 778／1 | 293.799 | 单阶段 PASS，不改写完整 L2 退出码 |
| 同记录四极 Static 定向 | 224／0 | 231.109 | 定向 PASS |
| [20261027__system-maintainability-review](20261027__system-maintainability-review.md) 修后 L1 MR Core | 42／0 | 172.135 | 阶段 183.456 s，六阶段 L1 exit 0 |
| 同记录修后 L1 整机 | 592／0 | 1549.952 | 阶段 1565.033 s，同一 L1 exit 0 |
| 同记录原 L2 common／整机／MR | 758／1；592／0；1673／12 | 272.246；1833.704；2053.788 | 三阶段 FAIL，完整 L2 30 PASS／3 FAIL |
| [20260802__gate-system-audit](20260802__gate-system-audit.md) 最终 L2，并发 8 | common 177、整机 104 等 | 未记 | 整轮 wall 185.2 s，PASS |

历史未记录整轮 wall 的地方保持“未记录”。上表不能用于计算本任务完整门禁加速倍数；也不能把 common 时间增加全部归因为代码性能退化。

**同输入收益与新增成本。** G2 在最终门禁后暂停其他代理本机工作，使用 Python 3.11.0 独立进程、相同冻结当前语料，按旧/新、新/旧、旧/新三对顺序测量。旧检查器取自基线，当前检查器取冻结源码；导入后明确绑定同一 REPO_ROOT/SOURCE_ROOTS，并调用 `main(argv)`，所以是隔离 CLI 语义对照，不是两棵历史仓库的整体对照。

| G2 顺序 | 模式 | main s | process wall s | audit 次数 |
|---|---|---:|---:|---:|
| 1 | 旧默认 | 27.820101 | 28.022256 | 1 |
| 2 | 新默认 | 10.133508 | 10.299116 | 0 |
| 3 | 新默认 | 9.686765 | 9.822432 | 0 |
| 4 | 旧默认 | 26.349339 | 26.522883 | 1 |
| 5 | 旧默认 | 21.337024 | 21.478411 | 1 |
| 6 | 新默认 | 7.252139 | 7.358218 | 0 |
| 7 | 新显式审计 | 14.299374 | 14.444693 | 1 |

**这项收益来自默认路径退出可选消费者审计，不是同等默认功能下算法整体加速。** 硬检查范围保持不变，完整消费者审计由显式模式另行提供。默认 main 中位数 **26.349339 → 9.686765 s**，减少 16.662574 s（63.2372%，2.7201 倍）；process wall 中位数 **26.522883 → 9.822432 s**，减少 16.700451 s（62.9662%，2.7002 倍）。七轮全部 exit 0、`DEVELOPMENT_STANDARDS=PASS ERRORS=0 REVIEW_SIGNALS=479`。旧默认三次与新显式一次的 2,189 条全字段记录 SHA 完全一致：formal 675、test-only 1、uncertain 1,513；新默认未执行 audit，记录数／类别／摘要为 null，不填“零发现”。

main 计时包含 CLI 输出生成和审计结果收集，不含模块导入及返回后的摘要序列化；process wall 包含这些外层成本。三对未清 OS 缓存，只能作本机描述性测量；没有全机 CPU 遥测，不能排除 OS 或其他用户后台负载。显式审计仅一次，作为功能对照，不宣称稳定的审计加速。

G2 冻结语料为 1,446 文件、21,934,108 bytes，运行前后身份相同。语料 SHA：`660689fcb27ef802357e635af40f5191f1c6cd36c78224908e86fab58fb35fb6`；完整审计记录 SHA：`702038580bafddb2a63b344be4d523f1d6f63d56966855955f2c0c4a8fe67147`。旧／新 checker SHA 分别为 `e452fc581964ec87e4b0341a2c39150a6c2659a8381115f5516cd234260bd381`／`65a3c64d6ecf375d23be6fbbdb6f40f9374dc2133725206081f7bafa9b67108b`。

语料摘要方法：在 common/projects/integrations 下收集 `.py/.ps1/.lua/.m/.json`，os.walk 剪去确切目录名 history、legacy、.venv、__pycache__；每项为 `(相对POSIX路径, 原字节长度, sha256(raw).hexdigest())`，全表 `sort()`，对 `json.dumps(manifest,separators=(",",":")).encode()` 取 SHA-256。审计摘要对完整记录数组用 `json.dumps(records,sort_keys=True,separators=(",",":")).encode()`；两者默认 ensure_ascii=True、UTF-8、无 BOM／末尾换行；数组顺序不另改。

C1/C3 采用 TEMP 内真实已校准账本与文件、真实无争用文件锁，两版本使用同一 fixture。各场景各预热一次、7 对交替顺序，每次前 gc.collect；下列为中位数。

| 容量场景 | 原实现 ms | 当前 ms | 降幅 |
|---|---:|---:|---:|
| C1 40 run／200对象，操作墙钟 | 86.3027 | 9.3563 | 89.1587% |
| C1 40 run／200对象，持锁区间 | 85.5470 | 8.3738 | 90.2115% |
| C1 80 run／400对象，操作墙钟 | 334.7473 | 15.9229 | 95.2433% |
| C1 80 run／400对象，持锁区间 | 333.9100 | 14.9027 | 95.5369% |
| C1 160 run／800对象，操作墙钟 | 1318.4635 | 30.4239 | 97.6925% |
| C1 160 run／800对象，持锁区间 | 1317.5772 | 29.5302 | 97.7587% |
| C3 80 run／400对象，startup main | 18.5576 | 10.7795 | 41.9133% |

原始配对计时如下，单位 ms，每格为“旧→新”；七对实际执行顺序依次为旧/新、新/旧、旧/新、新/旧、旧/新、新/旧、旧/新。

| 场景／指标 | 第1对 | 第2对 | 第3对 | 第4对 | 第5对 | 第6对 | 第7对 |
|---|---:|---:|---:|---:|---:|---:|---:|
| C1 40 run／200对象，操作墙钟 | 84.1066→9.3563 | 85.1515→9.6496 | 92.5769→8.8654 | 86.3027→8.0095 | 84.1775→9.9457 | 87.1816→9.2223 | 86.4822→9.7267 |
| C1 40 run／200对象，持锁 | 83.3039→8.3139 | 84.1648→8.6389 | 91.7352→8.0679 | 85.5470→7.2402 | 83.4119→8.9947 | 86.4053→8.3738 | 85.6591→8.7895 |
| C1 80 run／400对象，操作墙钟 | 330.9841→15.0666 | 318.2573→15.9229 | 344.6097→18.1387 | 342.0192→15.1296 | 334.7473→16.5224 | 318.5695→14.7785 | 339.6137→18.5992 |
| C1 80 run／400对象，持锁 | 330.2167→14.2877 | 317.4107→14.9027 | 343.7664→17.2477 | 341.1279→14.3608 | 333.9100→15.6791 | 317.7698→14.0256 | 338.5910→17.7095 |
| C1 160 run／800对象，操作墙钟 | 1312.7394→29.4912 | 1318.4635→30.9518 | 1291.5929→30.4239 | 1315.0068→29.7724 | 1378.3194→30.1447 | 1321.5515→30.6920 | 1349.2710→30.8723 |
| C1 160 run／800对象，持锁 | 1311.8911→28.5762 | 1317.5772→29.8848 | 1290.5584→29.5302 | 1314.1626→28.8253 | 1377.1876→29.2438 | 1320.5663→29.7360 | 1347.9453→29.8688 |
| C3 80 run／400对象，操作墙钟 | 19.3482→10.3193 | 26.9513→12.5053 | 18.5576→9.8522 | 16.7907→10.9873 | 17.3269→10.7795 | 18.1971→10.8104 | 24.0428→10.6604 |

C1 为 ready-only、无可删除对象：完成／删除／阻断结果均为 0，真实账本前后 SHA 未变。80 run／400 对象的整账本访问 64,400→400，run 分类 32,400→400；计数单独执行，且从真实加载验证完成后开始，不含各 run 必要的局部遍历。持锁区间从真实加锁成功后到解锁前，不含获取／释放锁本身。没有测生产账本、真实退役或大 PA 删除性能。

C3 在预热 Python 进程内调用实际 CLI main，含参数解析、真实 ledger／lease 读取与 JSON 输出，不含解释器导入启动；不是冷启动基准。单独准入／拒绝探针对两版给出同一决定，准入、ledger、lease、disk 读取各由 2 次变 1 次；计时样本使用实际 disk_usage，正确性探针使用固定空闲量。独立 `apply(plan)` 的重新准入边界由行为回归保护，不能由本 fixture 推广成跨调用复用。

新增正式 L1 八臂故障注入的独立测量为 **1325.368 s**：四组 MR／RF 既有及新增测试，故意失败后修复通过。它证明被改测试真正执行且阻止错误通过，也增加维护成本；不把这 1325.368 s 直接当作每轮完整门禁的固定增量或从历史差值中相减。用户要求继续指南工作且不追加耗时改造，本阶段没有通过删测或改变重任务并发政策降低该成本。

**代码规模。** `common/report_cloc_delta.ps1`，CLOC 2.10、进程 locale=C；基线 → 最终阶段提交：

| 分类 | code 基线 | code 当前 | 净增 |
|---|---:|---:|---:|
| total | 369009 | 370495 | +1486 |
| production | 234076 | 234679 | +603 |
| tests | 134933 | 135816 | +883 |
| unclassified | 0 | 0 | 0 |

语言净增为 Python +943、PowerShell +450、JSON +75、YAML +18；科学分析与求解器模型 code 均不变。CLOC code 不等于物理行数，.gitattributes 与无扩展名 hook 不在该扩展名过滤中。最终 CLOC result 输入身份为 `f08d4da53c2d8b5bc0866f00611b0654db9f466c29fa1f622af2497fc2e73650`。功能分类／过滤及来源 SHA 以官方 exact-SHA 输出为准；不把新增行数当作质量或速度的替代指标。

WORKTREE 与 exact-commit CLOC 的计数相同，但输入原字节摘要不同（`96366b1d6eee877de87f7340239f0c5fe1574b5a9b1bdcbff579157f9a91e02b` 与上列 `f08d…`）。独立逐文件复算确定，`core.autocrlf=true` 下 git archive 导出的两个未声明 text/eol 的 `.fly2` 文件分别增加 19／31 个 CR：`projects/parallel_mirror_dual_stripe_mr_tof/simion/mrtof_candidate.fly2` 为 338→357 bytes，`projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/formal/oatof_ideal_grounded.fly2` 为 883→914 bytes；其余 1,460 文件完全相同。仅替换这两个归档载荷即精确得到 commit 输入摘要。HEAD blob 与当前工作树 1,462 项仍逐字节相同；差异来自归档导出视图，不表示验收期间执行源码改变。未为计数修改 .gitattributes，本文采用 exact-commit 结果身份。

|范围|语言|files|blank|comment|code|
|---|---|---:|---:|---:|---:|
|total|JSON|252 → 252 (+0)|0 → 0 (+0)|0 → 0 (+0)|34645 → 34720 (+75)|
|total|Lua|95 → 95 (+0)|361 → 361 (+0)|712 → 712 (+0)|11050 → 11050 (+0)|
|total|MATLAB|125 → 125 (+0)|960 → 960 (+0)|1964 → 1964 (+0)|14752 → 14752 (+0)|
|total|PowerShell|142 → 142 (+0)|1022 → 1030 (+8)|950 → 960 (+10)|38213 → 38663 (+450)|
|total|Python|834 → 835 (+1)|23441 → 23497 (+56)|20841 → 21040 (+199)|269971 → 270914 (+943)|
|total|SIMION GEM|10 → 10 (+0)|26 → 26 (+0)|54 → 54 (+0)|214 → 214 (+0)|
|total|TOML|1 → 1 (+0)|4 → 4 (+0)|0 → 0 (+0)|24 → 24 (+0)|
|total|YAML|2 → 2 (+0)|4 → 4 (+0)|2 → 2 (+0)|140 → 158 (+18)|
|total|SUM|1461 → 1462 (+1)|25818 → 25882 (+64)|24523 → 24732 (+209)|369009 → 370495 (+1486)|
|production|JSON|251 → 251 (+0)|0 → 0 (+0)|0 → 0 (+0)|34511 → 34586 (+75)|
|production|Lua|77 → 77 (+0)|297 → 297 (+0)|611 → 611 (+0)|9295 → 9295 (+0)|
|production|MATLAB|77 → 77 (+0)|484 → 484 (+0)|1392 → 1392 (+0)|9799 → 9799 (+0)|
|production|PowerShell|134 → 134 (+0)|964 → 972 (+8)|917 → 927 (+10)|36563 → 37013 (+450)|
|production|Python|419 → 419 (+0)|13065 → 13074 (+9)|9077 → 9087 (+10)|143530 → 143590 (+60)|
|production|SIMION GEM|10 → 10 (+0)|26 → 26 (+0)|54 → 54 (+0)|214 → 214 (+0)|
|production|TOML|1 → 1 (+0)|4 → 4 (+0)|0 → 0 (+0)|24 → 24 (+0)|
|production|YAML|2 → 2 (+0)|4 → 4 (+0)|2 → 2 (+0)|140 → 158 (+18)|
|production|SUM|971 → 971 (+0)|14844 → 14861 (+17)|12053 → 12073 (+20)|234076 → 234679 (+603)|
|tests|JSON|1 → 1 (+0)|0 → 0 (+0)|0 → 0 (+0)|134 → 134 (+0)|
|tests|Lua|18 → 18 (+0)|64 → 64 (+0)|101 → 101 (+0)|1755 → 1755 (+0)|
|tests|MATLAB|48 → 48 (+0)|476 → 476 (+0)|572 → 572 (+0)|4953 → 4953 (+0)|
|tests|PowerShell|8 → 8 (+0)|58 → 58 (+0)|33 → 33 (+0)|1650 → 1650 (+0)|
|tests|Python|415 → 416 (+1)|10376 → 10423 (+47)|11764 → 11953 (+189)|126441 → 127324 (+883)|
|tests|SUM|490 → 491 (+1)|10974 → 11021 (+47)|12470 → 12659 (+189)|134933 → 135816 (+883)|

官方入口的完整过滤口径与身份原行如下：

```text
BASELINE=3005980a9a0d3a62a67f36dff389a3110868faa7
RESULT=c9467c44f632fa60e943cc80bb4b6e2a0d9246b0
CLOC_VERSION=2.10
CLASSIFIER_SHA256=d3365e7f02e66a775ec8eb3b12fb7b7bfa1bf34b87009543768a8e36bb4db749
LANGUAGE_DEFINITION_SHA256=985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6
INPUT_IDENTITY SNAPSHOT=baseline FILES=1461 SHA256=2eb9ba02f1e90fef5430d4db55608a3786dbdf7f3b824c00938b893d9fa310c9
INPUT_IDENTITY SNAPSHOT=result FILES=1462 SHA256=f08d4da53c2d8b5bc0866f00611b0654db9f466c29fa1f622af2497fc2e73650
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```

**证据边界。** 本文保留最终阶段计数与计时、G2 七轮原值、C1/C3 七对原值及精确身份算法。以下选取最终 L2 的关键原始行，并保留原日志行号、摘要边界和原件 SHA；PID 和真实 dispatch 负例只用于对应软件合同，不授予物理资格。下列临时原件在全 goal 复核期间供追溯，随后纳入用户要求的任务清理；路径不是永久发布地址，也不以改名 TXT 的方式将临时 JSON 或脚本归档。旧 G2 数据和旧语料 overlay 不作为本阶段收益证据。

原日志 `l2_r2.log` SHA-256 为 `d763984b61040ce72890ee0ff53aa41966c0be97aa0ef922fb0c1b4786a3559a`，节选行号从 1 开始；中间未引用行不代表未执行：

```text
l2_r2.log:518: Ran 803 tests in 1799.582s
l2_r2.log:520: OK (skipped=1)
l2_r2.log:1625: Ran 605 tests in 1977.008s
l2_r2.log:1627: OK
l2_r2.log:1693: Ran 1693 tests in 2101.692s
l2_r2.log:1695: OK (skipped=12)
l2_r2.log:1797: Ran 224 tests in 325.790s
l2_r2.log:1799: OK
```

复核时记录的原件身份（主证据 TEMP 为 `C:/Users/Liao/AppData/Local/Temp/codex_guide_wave1_20261028_f773196bc812465eb95e29625b8210a6`；最终 G2 原件位于 `C:/Users/Liao/AppData/Local/Temp/codex_g2_final_benchmark_20261028`）：

- `l1_r4_summary.json`（34,636 bytes；SHA-256 `b7aede00f92dd67d2d870c82d269dcb6c38dca980c25a5f23d3874d37af8fd03`）
- `l2_r2_summary.json`（33,339 bytes；SHA-256 `db950b0003a8965ef12bc155f05f26268418e790e3932b768a8aa95b580f39bc`）
- `l1_final_test_results.txt`（8,848 bytes；SHA-256 `8e77af0fa9d914c594b89996301c55989c8bddbce678adf469558eec3d966bab`）
- `l2_final_test_results.txt`（14,093 bytes；SHA-256 `268cc25e6516c6e3bd57461fb7c115e2ff45793a416ca88ef4d1ac46b77bf63f`）
- `capacity_results.txt`（44,667 bytes；SHA-256 `1aff422e28a21068c67cc24f31095f9c08428689ac1fcee9d074c17b17d57c6f`）
- `capacity_benchmark_source.txt`（14,788 bytes；SHA-256 `7b9a71ffd1523c45d1b7d2273c194b7a141415daee1b35e557bc1d0fd1b2f01f`）
- `cloc_final_commit.txt`（14,196 bytes；SHA-256 `c58e9ba461ac76bd62daf473b37c736fa2a01199929f760479d559aa79a11446`）。
- 最终 G2 `measurement.json`（21,666 bytes；SHA-256 `cf9df4535544716a8b962d9f0fd5fc11502d562f4613d81eb46b39a8a33b5fd7`）。

**本轮清理被拒范围。** 自动审批拒绝的是同一个 PowerShell 调用：对已验证位于 `C:\Users\Liao\AppData\Local\Temp\codex_g2_final_benchmark_20261028` 内的下列路径执行 `Remove-Item -LiteralPath … -Recurse -Force`。工具仅返回 `blocked by policy`，没有更具体原因；调用未启动，因此以下内容仍在。之后仅只读核对，没有再试删除，也没有换工具绕过。

| 被拒路径（相对此 TEMP） | 文件数 | bytes |
|---|---:|---:|
| `corpus/**` | 1446 | 21934108 |
| `versions/baseline.py` | 1 | 18326 |
| `versions/current.py` | 1 | 22166 |
| `preparation.json` | 1 | 1334 |
| `run_1.json` | 1 | 598 |
| `run_2.json` | 1 | 311 |
| `run_3.json` | 1 | 310 |
| `run_4.json` | 1 | 598 |
| `run_5.json` | 1 | 599 |
| `run_6.json` | 1 | 310 |
| `run_7.json` | 1 | 599 |
| **新 G2 范围小计** | **1456** | **21979259** |

以上为文件逻辑字节之和，不代表实际可释放的磁盘分配量。此拒绝范围不包括最终 `measurement.json`、`runner.py`（1,662 bytes）或 `benchmark.py`（9,055 bytes），也不包括其他代理文件；用户要求任务结束清理中间文件仍待统一收尾。报告只说明已发生的阻塞，不把中间文件保留自动视作最终交付。

Agent 0 记录的另外四个此前被拒清理目录，已由本次只读枚举核对仍存在且无符号链接。均位于 `C:\Users\Liao\AppData\Local\Temp`：

| 目录名 | 文件数 | 逻辑 bytes |
|---|---:|---:|
| `capacity-benchmark-845b54bcd8c945459710f76d3c271d96` | 1418 | 618333 |
| `codex_g2_pre_import_odsoiwu0` | 4 | 51117 |
| `scheduler-multibirth-candidate-86012fa4455941449d665f2b7e9b4721` | 4 | 93622 |
| `codex_rf_gate_contract_candidate_8iayfqoc` | 3 | 56166 |
| 旧四目录小计 | 1429 | 819238 |
| **与新 G2 被拒范围合计** | **2885** | **22798497** |

以上只说明本轮已记录且仍可见的清理阻塞，不代表全任务所有临时文件的总量，也不证明能够释放相同数量的磁盘分配字节。全指南 goal 仍开放，临时原件保留至复核／统一清理；阶段提交和本记录不替代剩余工作的完成判据。
