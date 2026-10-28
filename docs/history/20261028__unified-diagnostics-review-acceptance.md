# 统一诊断独立复审与工作区归位验收

DOC_STATUS: ARCHIVED_READ_ONLY

## 范围与身份

依据[独立评审最后一轮意见](https://chatgpt.com/share/6ae14c6d-863c-83ed-8396-95ff971bfdf4)，
对master基线`606a09589d4fdbd18e16c26793f335f54d01c76c`执行有界修复，结果代码提交为`fd0d7648d2b71a4c8cb3dbd07f6fc14e24bad0a1`。
本记录保存2026-10-28验收时点的修复、限制及迁移事实，不替代现行PROJECT或公共API说明。
首轮实施、此前CLOC和门禁过程由[606a0958中的原计划](https://github.com/Bibibabibobi96/mass_spectrometry/blob/606a09589d4fdbd18e16c26793f335f54d01c76c/docs/UNIFIED_DIAGNOSTICS_PLAN.md)保留。

用户确认以职责和依赖收敛为主，接受经审查的必要净增；只保留master、普通推送。
阶段计划在本轮关闭后退出活动文档层；必要证据压缩为本记录，由AUDITS索引，普通过程由Git保留。

## 问题处置

| 问题 | 验收时的实现与边界 |
|---|---|
| IP末端穿面晚于真实终态 | 按真实出口／终态限制样本使用区间，完整事件补最后锚点；原始记录仍验证且不改写。缺终态仅用双观测有界重建，缺坐标不虚构状态 |
| COMSOL分析执行活动源码 | canonical state metrics加入既有analysis_runtime，state→metrics→response完整链使用原隔离入口；修改临时活动源码无影响，缺冻结模块拒绝 |
| RF L1失败无标准三件套 | 冻结前调用公共New-RunPackage；冻结、准备、计算、分析失败由公共Complete-FailedRun收尾，保留原异常、阶段、部分输入及原ID；不覆盖已发布终态 |
| 单反射不可辨识标定仍computed | 复用原polyfit默认rank/rcond，校验实数、有限正输入、满秩及有限结果，不调容差；非法结果在发布前失败 |
| 辅助ION小数电荷被截断 | 原词法保留至Decimal整数校验；两个消费者复用原solver_diagnostics模块中的校验，不新增模块 |
| beam缺值掩盖非法值 | 检查全部已提供数值后再返回缺测；None不再掩盖NaN／Inf／复数 |
| MR历史中心诊断被旧峰方法误挡 | 非formal且非当前方法仅返回峰不可用并保留原合同，正式束团仍拒绝旧方法；合法v2输出保持，历史文件不改写 |
| MR测试依赖系统换行 | 默认fixture明确LF；真实LF／CRLF两臂验证原字节保持和冻结后篡改拒绝，不改变生产复制策略 |

当前事实分别归[IP PROJECT](../../projects/dual_pressure_rectilinear_ion_processor/docs/PROJECT.md)、
[RF PROJECT](../../projects/rf_multipole_ion_optics/docs/PROJECT.md)、
[单反射PROJECT](../../projects/single_reflection_oa_tof_mass_analyzer/docs/PROJECT.md)、
[MR PROJECT](../../projects/parallel_mirror_dual_stripe_mr_tof/docs/PROJECT.md)及[公共分析说明](../../common/analysis/README.md)。

## 四候选与历史输入复核

| 候选 | 已核实职责与结论 | 退出条件 |
|---|---|---|
| common terminal-plane | 独立终态CSV分析；真实双锥输入格式仍可复核，原生runner已退役。保留限定历史职责，不称为活动生产调用 | 历史冻结代码可独立重放，或同输入受管替代验证后连同私有测试退出 |
| RF sampling | 历史N100／N1000同源统计；仅有测试直接import，保留限定历史职责，不恢复中断研究 | 恢复并核验旧代码及依赖／路径映射，或同输入等价替代后退出 |
| MR fixed-grid voltage point | real-field period、fixed-grid handoff、voltage correction三条链消费其receipt，保留独立待验点准备者 | 三条消费链共同迁移或退役；准备receipt不授予工作点资格 |
| MR CAD pose | 唯一消费者是机械坐标回归，迁到tests/test_support，不保留生产wrapper | 长期验证参考；只改模块说明，去说明后的AST相同，变换未改 |

正确工作区内取得6个具名run，选定54项小输入／状态／metrics／三件套的字节数及SHA与原manifest一致。
不是全manifest验证，未读取或哈希巨型模型，也未重跑商业求解。
双锥两run具终态输入和metrics（58/100、0/100），但未绑定分析器源码；
RF四run的code_inventory不含sampling，预登记A3B210…旧源码只有声明，未找到已验证副本。
因此修正此前基于错误空产物目录的“未取得旧run包”理由，保留结论收窄为缺分析代码闭包／替代等价证据。

以下run路径为`C:/Users/Liao/mass_spectrometry/artifacts/projects/<owner>/runs/<run_id>`，原owner不改写：

| owner／run | run_manifest SHA-256 |
|---|---|
| dual_cone_tandem_quadrupole_ion_interface／20260914_162400__sim__simion__dual-cone-comsol-field-n100 | 8cb83752fabc050a1a2304a34224de040a6b6393a3c3fa2e424eb31e89a4bdf5 |
| dual_cone_tandem_quadrupole_ion_interface／20260914_104709__sim__simion__dual-cone-uniform-400pa-n100 | 23e451ad33b02d27a006f956d3cedbfde07d3fd089d16851afce84dde915197e |
| rf_quadrupole_ion_optics／20260731_010004__sim__simion__quad-noacc-followup-i-r020-z020-t080 | 9db01bb369a1dc321b3e25f17e0dfa4a9d35725aa082448de18bc00f2648fbbd |
| rf_quadrupole_ion_optics／20260731_040001__sim__simion__quad-n1000-sampling-i-r020-z020-t080__r01 | 9a40731646264074d0ae730a728e45ec8e3483024776f1498753894aba0a18c6 |
| rf_quadrupole_ion_optics／20260731_020001__sim__comsol__quad-noacc-followup-exit020-t160 | 992edc2ecb3b203967ec8e804848a7030d08a38b5c8786b5381e5532a3cde4d5 |
| rf_quadrupole_ion_optics／20260731_020002__sim__comsol__quad-noacc-followup-exit020-t320 | 35ce872da6aa421d862853cb7560442b31449a59b1591b31b7e91877c1411be7 |

## 工作区归位

用户指定工作区`C:/Users/Liao/mass_spectrometry`；外层README规定Git根为`simulation_repo`，
非Git产物根为`artifacts/projects`。聊天已移入应用中的Mass spectrometry项目。

此前错误在`C:/Users/Liao/Documents/ChatGPT/Mass spectrometry repository`副本执行。
正确仓库原来干净且停在0292d3bb，经普通fetch与ff-only快进首轮10提交到606a0958，
再逐字节迁入本轮23路径。旧副本本轮改动已撤除；唯一恢复stash
`e94b6cd818c2d77f90ed09ad53da49d6bd7fd164`已连对象保留在正确仓库，未作为生产代码应用或推送。

两个仓库的规范、锁定依赖一致，新工作区既有Python3.11和CLOC2.10直接复用。
错误位置未完成的L1／L2已中断，不记PASS。旧调度账本经公共status确认records为空后，
后续只使用`C:/Users/Liao/mass_spectrometry/artifacts/common/host_resources.sqlite3`；
不复制账本或覆盖既有科学资产。正确目录重新完成联合验收。

旧门禁两个临时组经公共清理入口删除34个日志／缓存文件、逻辑491,121字节；
中断的RF测试fixture另删除5,528字节。清理时C盘可用空间观测增加589,824字节，
并行门禁仍在写盘，此值不能独立归因于删除。内容均可由测试重建，未删除科学模型或唯一数据。
应用仍把旧managed worktree识别为当前聊天的primary checkout，归档工具拒绝移除；没有通用目录重绑工具。
该副本保持clean并保留其依赖的旧Git元数据，归位后全部实际读写、测试和Git操作均显式使用正确仓库目录。


## 本轮验证与适用范围

判据是评审所列失败路径关闭、合法输入保持、真实消费者与冻结依赖一致；不新增科学资格。
基线为606a0958，唯一改变是本页处置矩阵列出的实现／测试边界；RF使用明确的合成响应或canonical状态，
不把fixture结果当作商业求解器输出。

| 验证对象 | 本轮结果 |
|---|---|
| 公共beam＋IP五模块 | 108项通过，35.871秒；local-focus独立进程11项通过，9.013秒 |
| IP／beam合法输入对照 | IP 40组、8,240数值字段；beam 20组双API、19,945字段，均与基线精确一致 |
| 单反射拟合／电荷／CLI及冻结wrapper | 60项通过，41.199秒；6组合法拟合及6种合法ION编码的表值、dtype和完整结果保持 |
| MR LF／CRLF来源字节 | 38项通过，12.450秒；两臂真实handoff→materializer及冻结后换行篡改拒绝 |
| RF完整分析与run生命周期 | 15项通过，85.594秒；最后将source fixture状态明确为alive后单项再通过，12.534秒 |
| 四候选回归 | 12项通过，0.101秒；三个保留CLI的实际help入口成功 |
| RF补充计算故障场景 | 同一方法四阶段注入通过，17.668秒；四极Static 224项通过，231.109秒，0跳过 |
| MR受控历史诊断补修 | focused 48＋真实历史单项1共49项通过，1.069秒；36组合法v2完整结果与基线精确一致 |
| L1 | MR补修前的23路径完整门禁PASS；补修另有49项focused及后续MR／整机完整阶段覆盖 |
| L2最终MR／整机 | MR分析1693项，1681通过／12跳过，1818.682秒；纯Lua三脚本通过，另一个Python目录发现0项；整机605项通过，1737.629秒，0跳过 |
| L2分阶段闭合 | 36阶段通过；公共合同阶段完整复验778项、777通过／1跳过、0失败，293.799秒。全部37阶段有通过证据；完整命令退出码1保留，不称单次全命令PASS |
| 最终文档收尾 | 5个Markdown路径的文档L1通过；1624文件文本字节检查通过；文档链接0错误、111条既有历史review提示 |

各定向阶段均无跳过；表中按阶段计数，不跨轮累加为独立用例数。IP错误末段从10.85修正为10.71875 μs，
真实出口10.75 μs保持；COMSOL合成七质量×四原ID全链宽1.75 Th，L1合成N=100／29点宽4.5 Th。
这两种宽度用于检查接线，不能与首轮真实L1积分的4.1227490996398615 Th混为同一实验。

合并进程运行IP与local-focus时曾有119项中的1个函数对象身份断言失败：前一测试重载common模块，
后者仍持旧对象。按正式门禁的独立进程边界复验108＋11项通过，未修改无关测试。
正确工作区首次L2的MR分析1691项有1项错误、12项跳过：存在的历史受控中心输入冻结v1方法，
当前分析器错误地先校验无须执行的峰合同。606a0958同样复现；旧空产物目录曾使该项跳过。
修复后原单项物理断言保持且通过，三份原始材料的大小／SHA仍匹配原manifest。随后重新完整执行L2。
复现run为MR owner下`20261006_030113__sim__simion__mrtof-comsol-p1-plus1-center`，长期单项为
`test_static_workpoint_iteration.SelectedCenterObservationTest.test_real_common_center_reanalysis_preserves_exit_failure`；
读取`logs/native_two_prism_flight.log`、`results/two_prism_trial_materialization.json`及
`results/two_prism_trial_observation.json`，不重新Fly或改写它们。
初次CLOC因主机C.UTF-8 locale产生Perl诊断而明确失败；仅在计数进程中将locale设为C后成功，未忽略诊断。

第二次完整L2命令仍退出1：Agent 0在运行中先创建本文、后补AUDITS索引，公共合同内的真实文档门禁
读到了这个中间态。完成索引后暂停文件编辑，通过同一官方入口的`-InternalStage common_contracts`
完整复验该阶段，778项中0失败、1跳过；其余36阶段实跑通过。代码始终固定，未跳过测试或放宽门禁。
独立复核接受按阶段证据闭合；最终文档变更另验，不将该结果写成一次完整命令PASS。

Agent 1／2／3／4交付已分别经交叉只读复核，Agent 0整合。临时clone、run及容量fixture由各自
TemporaryDirectory清理；首次正确目录L2的失败日志经复核后由公共清理入口删除25文件、203,327字节，
C盘可用空间观测627,280,322,560→627,280,576,512字节。第二次L2及阶段复验日志经复核后同入口删除
26文件、210,228字节，可用空间观测627,762,216,960→627,762,475,008字节；磁盘变化受并行写入影响。
其他成功门禁组由原入口自动清理。未删除科学模型或唯一数据，临时验证可重建。
本轮未运行新的COMSOL／SIMION Fly、GUI／CAD或L3 Formal；几何、源、积分器、采集与时钟不变。

## 本轮CLOC与规模

官方入口`common/report_cloc_delta.ps1`，CLOC 2.10；`606a09589d4fdbd18e16c26793f335f54d01c76c → fd0d7648d2b71a4c8cb3dbd07f6fc14e24bad0a1`。
分类器SHA为`d3365e7f02e66a775ec8eb3b12fb7b7bfa1bf34b87009543768a8e36bb4db749`，
语言定义SHA为`985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6`；
计数输入身份由`383f31e7f3804828bbb95b7070c605c2610f394823aef6085f7c40981222da1a`
变为`2eb9ba02f1e90fef5430d4db55608a3786dbdf7f3b824c00938b893d9fa310c9`。

生产code净增19，tests净增493，total净增512；后者包含CAD参考从生产移入测试，不是493行全新测试。
生产脚本718→717，测试脚本488→489，总脚本1206不变；活动profile入口20和生产PS入口60均不变。
运行编排code +21、科学分析 −2，其余生产职责不变；没有新增CLI、运行协议或公共框架。

| 类别 | 语言 | files：基线→结果（delta） | blank | comment | code |
|---|---|---|---|---|---|
| total | JSON | 252→252 (0) | 0→0 (0) | 0→0 (0) | 34645→34645 (0) |
| total | Lua | 95→95 (0) | 361→361 (0) | 712→712 (0) | 11050→11050 (0) |
| total | MATLAB | 125→125 (0) | 960→960 (0) | 1964→1964 (0) | 14752→14752 (0) |
| total | PowerShell | 142→142 (0) | 1022→1022 (0) | 950→950 (0) | 38208→38213 (5) |
| total | Python | 834→834 (0) | 23410→23441 (31) | 20766→20841 (75) | 269464→269971 (507) |
| total | SIMION GEM | 10→10 (0) | 26→26 (0) | 54→54 (0) | 214→214 (0) |
| total | TOML | 1→1 (0) | 4→4 (0) | 0→0 (0) | 24→24 (0) |
| total | YAML | 2→2 (0) | 4→4 (0) | 2→2 (0) | 140→140 (0) |
| total | SUM | 1461→1461 (0) | 25787→25818 (31) | 24448→24523 (75) | 368497→369009 (512) |
| production | JSON | 251→251 (0) | 0→0 (0) | 0→0 (0) | 34511→34511 (0) |
| production | Lua | 77→77 (0) | 297→297 (0) | 611→611 (0) | 9295→9295 (0) |
| production | MATLAB | 77→77 (0) | 484→484 (0) | 1392→1392 (0) | 9799→9799 (0) |
| production | PowerShell | 134→134 (0) | 964→964 (0) | 917→917 (0) | 36558→36563 (5) |
| production | Python | 420→419 (-1) | 13074→13065 (-9) | 9045→9077 (32) | 143516→143530 (14) |
| production | SIMION GEM | 10→10 (0) | 26→26 (0) | 54→54 (0) | 214→214 (0) |
| production | TOML | 1→1 (0) | 4→4 (0) | 0→0 (0) | 24→24 (0) |
| production | YAML | 2→2 (0) | 4→4 (0) | 2→2 (0) | 140→140 (0) |
| production | SUM | 972→971 (-1) | 14853→14844 (-9) | 12021→12053 (32) | 234057→234076 (19) |
| tests | JSON | 1→1 (0) | 0→0 (0) | 0→0 (0) | 134→134 (0) |
| tests | Lua | 18→18 (0) | 64→64 (0) | 101→101 (0) | 1755→1755 (0) |
| tests | MATLAB | 48→48 (0) | 476→476 (0) | 572→572 (0) | 4953→4953 (0) |
| tests | PowerShell | 8→8 (0) | 58→58 (0) | 33→33 (0) | 1650→1650 (0) |
| tests | Python | 414→415 (1) | 10336→10376 (40) | 11721→11764 (43) | 125948→126441 (493) |
| tests | SUM | 489→490 (1) | 10934→10974 (40) | 12427→12470 (43) | 134440→134933 (493) |
| unclassified | SUM | 0→0 (0) | 0→0 (0) | 0→0 (0) | 0→0 (0) |

完整过滤口径（普通活动`archive`目录不因名称被排除）：

```text
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```

## 本轮提交与交付

| 提交 | 主题 |
|---|---|
| `52d95d8b` | IP真实生命区间与公共beam已提供值校验 |
| `083ec272` | 单反射标定可辨识性与电荷精确读取 |
| `53b323e3` | RF完整冻结分析及公共失败终态 |
| `fd0d7648` | MR历史诊断、fixture字节及测试参考归属 |

代码主题按累计最终树验证，不把联合门禁冒充每个中间提交独立运行的全门禁。
交付由master承载；末尾归档提交只修改Markdown，其自身`CLOC_DELTA=N/A (docs-only)`。
不新建分支或改写远程历史。活动计划删除，旧版本由固定Git提交保留；本记录仅保存必要验收证据。
