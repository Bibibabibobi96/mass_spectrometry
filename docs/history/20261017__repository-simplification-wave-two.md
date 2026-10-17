# 全仓精简第二轮：重复验证、哈希与物化收口

DOC_STATUS: ARCHIVED_READ_ONLY

本页冻结2026-10-17本次全仓精简的最终结果，接续[第一轮记录](20261017__repository-simplification-wave-one.md)。
审查覆盖全部10个项目、integration和common；各项目覆盖与第一轮删除清单见前页。
累计基线为`a84776a6a2fdf6ec47e590db20d5b8c51d4132f1`，最终源码为`3ce3acea5227c2513f7b728b851ea9a8d0e2f509`。
当前规则和使用方法以最近的公共README、项目PROJECT和集成INTEGRATION为准。

## 实施结果

| 对象 | 之前 | 当前行为与保留边界 |
|---|---|---|
| 待弃临时载荷 | retention在删除前重新读完整文件算SHA | 不再新算无消费者的SHA；仍核对精确路径、run内归属、普通文件与大小，并写pending清单、逐文件进度和终态；冻结资产身份要求保留 |
| manifest重复记录 | 同一输入/输出路径逐记录重新读取 | writer和verifier分别在一次调用内复用解析路径、实际读取函数、大小和mtime_ns相同的内容身份；仍逐记录验证路径、bytes、SHA及保留角色；每次新调用重新读取 |
| IP终态manifest | 已冻结输入再次列入outputs | 排除精确已登记输入路径；未登记为输入的生成PA、运行结果与checkpoint仍列outputs，retention仍检查整个run |
| 集成runtime resolver | SHA、receipt关联和count通过后再启动Python扫CSV并往返临时JSON | 删除第二次count-csv；新增receipt selector与源合同selector大小写敏感一致性检查；state/receipt SHA、交叉绑定与count保留 |
| 集成adapter | 紧接resolver前重复检查source/design | 由同次resolver的完整检查承接；篡改输入仍在执行前拒绝 |
| 资源观察器 | 每次根据路径重读已解析budget JSON | 唯一入口接收`-Limits`对象；49处调用同步迁移，usage继续记录完整实际限额；16处Complete删除从未使用的budget参数 |
| 公共多极杆运行器 | 将预检派生预算永久搬入inputs并注册manifest | 已解析对象直接保留在内存；必要Python→PowerShell临时JSON在预检finally立即清理，成功和异常均覆盖；原始工程预算仍冻结 |
| 集成阶段预算 | 每阶段写派生budget JSON、算SHA、重复注册身份 | 限额直接由已解析对象传递；singleflight少1份，三阶段少3份派生文件；原始工程预算及其真实策略/身份仍保留 |
| MR静态场provider | composition、occupancy和每个新level各写预算副本 | 直接传内存限额；少1份composition及每occupancy/新level对应文件；跨Python/Lua使用的真正执行plan保留 |
| IP CLI/GUI预算 | 从冻结profile再写/复制resource_budget.json | 直接派生limits并传观察器；GUI输入从实际复制文件登记，不再出现悬空的旧budget输入；finalize确实消费的gui_execution_budget.json保留 |
| oaTOF ideal comparison | 额外写无消费者resolved_plan.json | 删除该写入；case/config/seed/code保留，真实工作点解仍由working_points.json保存 |
| oaTOF radial campaign | 私有candidate_diff.json并用其存在性阻止resume | 删除私有文件及无意义resume条件；真实baseline/resolved仍保留并验证；正式发布实际消费的Candidate/Formal diff保留 |
| 门禁测试 | 锁定CI注释、超时字面值、变量名与Git源码拼写 | 删除这些无故障判别价值的断言；非法目录、路由、篡改拒绝和诊断日志回放相关有效覆盖保留 |

本轮没有新增生产脚本、第二套CLI或持久审计框架。与第一轮累计删除16个脚本（生产12、测试4）；
本轮进一步减少生产代码72行，但为身份复用、限额类型、篡改拒绝和实际调用补足行为回归，测试代码增加291行，
本轮总代码增加219行。累计生产代码与总代码仍分别净减1,710和1,673行；不声称每轮所有指标都下降。
未删除artifacts、冻结历史或商业资产；第一轮删除源码基线逻辑大小81,445字节，可从Git恢复，未计量实际可用磁盘变化。

## 读写与流程对照

| 对照 | 结果及适用范围 |
|---|---|
| 同文件2个input加2个output的真实manifest fixture | 每次writer/完整verifier各自完整读取4→1；除生成时间外manifest记录一致；build/build/verify/verify仍分别重新读取 |
| 待删临时载荷fixture | 2份待弃载荷内容读取2→0；除删去未使用SHA外收据字段相同，保护检查与中断恢复保留 |
| IP历史manifest只读样本 | 159 inputs、640 outputs中158个路径重复，涉及2,173,360字节；隔离投影640→482 outputs。不是求解器重跑；不得再与通用memo叠加计算收益 |
| 集成resolver | 每次少1个Python进程、1次所选CSV扫描及1套临时JSON写/读/删；正常单飞调用两次、分段链五次，对应少2/5套 |
| 公共限额API | 活动PowerShell AST解析152份，49处Invoke（46处显式Limits、3处合法splat）及16处Complete均符合唯一签名；完整usage、warning、退出状态和非法采样间隔行为保留 |
| 第一轮源生成与四极杆 | cylinder/continuous volume重复生成2→1且CSV/receipt逐字节一致；四极杆默认bundle9文件逐字节一致，直接file_sha256调用30→16 |
| 第一轮MR/IP | 每个MR输入run少4次重复全文哈希；IP剖面去掉约112,500次运行时随机点自测及无人消费JSON，确定性几何回归保留 |

没有测量端到端时间加速，调用次数与文件数下降不能表述为真实求解性能提升。
复杂度下降体现为删掉路径型限额API、派生预算运输链、重复CSV子进程、无消费者文件与只检查实现拼写的门禁；
未计算统一圈复杂度指标，不虚构其下降百分比。

## 第一轮七项跟进的闭合

1. manifest重复内容读取：公共writer/verifier每次调用局部复用已实施；IP同时去掉重复输出记录。
2. run目录扫描：已逐消费者检查，保留独立发现能力。retention要发现未登记临时重载荷；writer有独立MR构建/journal及oaTOF虚拟文档消费者；
   verifier独立服务发布后的消费；capacity要计入新写manifest/receipt、未列小文件、链接和独立resume调用。
   仅加总manifest记录会漏算或误计外部输入，合并需要增加旁路状态运输，没有已证实的净收益。
3. 待删临时载荷新SHA：已移除并同步生命周期唯一权威，pending/进度/恢复能力保留。
4. runtime重复计数与前检：已删；selector/count/SHA交叉篡改矩阵及真实输入篡改拒绝覆盖保留。
5. 源码拼写断言：已删无价值部分；诊断日志回放护栏仍有实际用途，未批量移除。
6. peak_metrics两次最小二乘：保留。两个基底虽同列空间，NumPy的秩截断受尺度影响。
   NumPy2.4.6、101点、z中心约−18.4292mm且半宽5e−5mm的纯内存探针得到中心化/raw秩6/5，
   R²约1.000000/0.0084403；raw指标确有reference_analysis_core和冻结formal_validation消费者。
   合并会改变科学指标，不能按等价重构删除；本次未改数值或容差。
7. JSON运输与物化：公共多极杆、MR、IP、integration、oaTOF的已证实多余文件均已删除，真实消费者所需运输保留。
   host资源租约使用独立Python→PowerShell→新Python进程，临时运输在退出清理；MR plan/per-level供Python/Lua；
   oaTOF baseline/resolved供构建器、working_points保存实际解；raw engineering budget/profile是权威；
   GUI execution budget供后续finalize建立容量会话。没有仅因“已有机制”而保留。

## 验证与边界

最终44路径冻结源码的联合命令先验证生成绑定（UPDATED=0、check通过）与diff，再运行
`common/verify_changed.ps1`和`common/verify_repository_integration.ps1`。
两者同一会话连续执行，最终退出码0；终态分别为
`CHANGED_GATE=PASS PYTHON=3.11 CHANGED_PATHS=44 FULL_SCOPE=False`和
`REPOSITORY_INTEGRATION_GATE=PASS PYTHON=3.11`。完整L2结束于2026-10-17上海21:42前后。

| 最终验证 | 结果 |
|---|---|
| L1与全仓L2 | PASS；最终实现冻结后未再改源码/测试 |
| 公共合同／多极杆／SIMION | 644（skip 1）／413／262（skip 6） |
| integration／MR完整分析／oaTOF | 890（skip 3）／1,409（skip 10）／385（skip 1） |
| 加速器／四极／六极／八极 | 93／230／22／29 |
| IP／双锥／EI／Wehnelt | 166／30／22／52 |
| 调度／LiveLink资源／文档链接 | 72／31／15；主机适配器、registry、静态发布freshness亦通过 |
| 静态与文档 | Ruff、源码文本、开发标准、卫生、文档结构/链接通过；既有review信号不等于失败 |
| 身份/物化focused回归 | 独立新调用、同次变动、声明冲突、不同读取策略、虚拟/暂存路径、305输出长路径、receipt selector/count/SHA篡改、真实PS限额类型及清理行为均覆盖 |

表中数字是执行测试数，括号内是其中的显式跳过项；跳过项不构成已验证层级。
门禁输出中的预期非法参数、negative-fixture FAIL及synthetic flight标记不能解读成商业求解；
结论以各suite退出码、测试OK及顶层终态为准。

Agent 0负责公共层、整合、度量及串行Git；Agent 1负责oaTOF/加速器/MR与公共身份复用，
Agent 2负责多极杆及资源/数值独立复核，Agent 3负责IP/离子源/电子源及限额调用复核，
Agent 4负责integration与实际物化消费者复核；最终实现冻结后执行联合门禁。
中间回归曾发现遗漏的旧Complete参数、三个阶段Invoke缺少Limits、测试fixture旧解析对象以及新GUI测试subprocess缺少cwd；
均已修正，再由最终同一冻结源码的L1/L2覆盖。被主动取消的旧门禁不计为PASS。
未执行真实Refine、Fly、COMSOL Compute、GUI/CAD或Formal验收；纯Lua fixture与求解器无关分析不代表这些层级完成。

## CLOC与脚本数

固定提交对照命令：
`common/report_cloc_delta.ps1 -Base a84776a6a2fdf6ec47e590db20d5b8c51d4132f1 -Current 3ce3acea5227c2513f7b728b851ea9a8d0e2f509`。
结果`CLOC_DELTA=PASS`，CLOC 2.10，运行时工作树干净，unclassified=0。
分类器SHA256为`cbfb4c9eebbb38285800e4e358a13ef66c73404c4d399b8e4bd3687f71064285`，
语言定义SHA256为`985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6`。
基线选中文件身份为`4978c8a59f8144b5db059ff570574df348a9bbc30ada148bf22a6a537caa1d49`；
固定结果选中文件身份为`a4fdadabb87d43452f1ab1fdd1669f4bda09c88347534d9be9a7a1659decbb35`。
Markdown报告不进入代码计数，后续仅报告/索引提交不改变此源码对照。

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

| 脚本用途 | baseline | result | delta |
|---|---:|---:|---:|
| production | 737 | 725 | -12 |
| tests | 472 | 468 | -4 |
| total | 1209 | 1193 | -16 |

脚本数采用工具SCRIPT_FILES，包含生产模块及语言脚本，不把JSON/TOML/YAML配置算脚本。
下表每格为baseline → result（delta），分别记录files、blank、comment和code。

### total

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 511 → 511 (0) | 0 → 0 (0) | 0 → 0 (0) | 49741 → 49732 (-9) |
| Lua | 96 → 91 (-5) | 460 → 424 (-36) | 747 → 694 (-53) | 9976 → 9515 (-461) |
| MATLAB | 117 → 117 (0) | 991 → 991 (0) | 2264 → 2264 (0) | 14143 → 14134 (-9) |
| PowerShell | 155 → 152 (-3) | 1225 → 1211 (-14) | 1425 → 1425 (0) | 47938 → 47665 (-273) |
| Python | 831 → 823 (-8) | 23134 → 23002 (-132) | 15070 → 15197 (127) | 281217 → 280296 (-921) |
| SIMION GEM | 10 → 10 (0) | 35 → 35 (0) | 81 → 81 (0) | 246 → 246 (0) |
| TOML | 1 → 1 (0) | 4 → 4 (0) | 0 → 0 (0) | 24 → 24 (0) |
| YAML | 2 → 2 (0) | 4 → 4 (0) | 1 → 1 (0) | 120 → 120 (0) |
| SUM | 1723 → 1707 (-16) | 25853 → 25671 (-182) | 19588 → 19662 (74) | 403405 → 401732 (-1673) |

### production

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 507 → 507 (0) | 0 → 0 (0) | 0 → 0 (0) | 49631 → 49622 (-9) |
| Lua | 78 → 75 (-3) | 352 → 331 (-21) | 653 → 611 (-42) | 8106 → 7797 (-309) |
| MATLAB | 77 → 77 (0) | 542 → 542 (0) | 1743 → 1743 (0) | 10438 → 10429 (-9) |
| PowerShell | 146 → 144 (-2) | 1167 → 1157 (-10) | 1403 → 1403 (0) | 46501 → 46301 (-200) |
| Python | 426 → 419 (-7) | 13594 → 13446 (-148) | 8375 → 8339 (-36) | 158902 → 157719 (-1183) |
| SIMION GEM | 10 → 10 (0) | 35 → 35 (0) | 81 → 81 (0) | 246 → 246 (0) |
| TOML | 1 → 1 (0) | 4 → 4 (0) | 0 → 0 (0) | 24 → 24 (0) |
| YAML | 2 → 2 (0) | 4 → 4 (0) | 1 → 1 (0) | 120 → 120 (0) |
| SUM | 1247 → 1235 (-12) | 15698 → 15519 (-179) | 12256 → 12178 (-78) | 273968 → 272258 (-1710) |

### tests

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 4 → 4 (0) | 0 → 0 (0) | 0 → 0 (0) | 110 → 110 (0) |
| Lua | 18 → 16 (-2) | 108 → 93 (-15) | 94 → 83 (-11) | 1870 → 1718 (-152) |
| MATLAB | 40 → 40 (0) | 449 → 449 (0) | 521 → 521 (0) | 3705 → 3705 (0) |
| PowerShell | 9 → 8 (-1) | 58 → 54 (-4) | 22 → 22 (0) | 1437 → 1364 (-73) |
| Python | 405 → 404 (-1) | 9540 → 9556 (16) | 6695 → 6858 (163) | 122315 → 122577 (262) |
| SUM | 476 → 472 (-4) | 10155 → 10152 (-3) | 7332 → 7484 (152) | 129437 → 129474 (37) |

### unclassified

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| SUM | 0 → 0 (0) | 0 → 0 (0) | 0 → 0 (0) | 0 → 0 (0) |
