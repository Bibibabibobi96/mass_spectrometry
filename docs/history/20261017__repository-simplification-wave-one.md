# 全仓精简第一轮：失活入口与重复工作

DOC_STATUS: ARCHIVED_READ_ONLY

本页冻结 2026-10-17 第一轮已验证的代码精简，不代表整个持续 goal 已完成。基线为
`a84776a6a2fdf6ec47e590db20d5b8c51d4132f1`，开始时工作区干净；结果为本主题提交前 WORKTREE，
源码内容身份见下表。当前实现以项目 PROJECT、integration INTEGRATION 和最近公共 README 为准。

## 覆盖与已实施结果

Agent 0 负责公共层、度量和整合；Agent 1 负责 oaTOF／加速器／MR，Agent 2 负责四／六／八极杆，
Agent 3 负责 IP／双锥／EI／Wehnelt，Agent 4 负责 integration。各 Agent 修改范围互斥，Git 写入由 Agent 0 串行完成。

| 范围 | 处置与保留依据 |
|---|---|
| oaTOF | 已检查入口、器件依赖和 Candidate/Formal 生命周期。器件理论已独立，正式 PA 的 scratch 隔离防止回写；本轮无可证实应删的项目代码 |
| 正交加速器 | 四份私有整文件哈希改为公共分块实现，删恒真路径判断；保留 flight、cache 与 MR handoff 的不同输入输出职责 |
| MR-TOF | 六份私有哈希改公共实现；步长比较复用已验证的四份输出身份；batch/trial 直接调用源合同，删转发层。coarse-raw producer 仍是 response bank 重建能力，保留 |
| 四极杆 | 删三脚本旧场诊断链；完整 bundle 校验承接生成与 binding 的重复校验，删重新解析与前缀扫描，复用输入身份；逐表 SHA 与字节比较共用一次读取 |
| 六／八极杆 | 项目已用公共薄入口；源、模式、数值与资格合同仍有消费者，未为减行合并科学边界 |
| IP | 删旧解析规定场与专用自测三脚本、九个无消费者参数及必填检查；MR 从旧冻结输入派生当前 seed 时去除同九字段，不改来源和 native 工作点 |
| IP 剖面导出 | 删除生产运行时的随机截面自测及无人消费的 section_validation.json；确定性测试覆盖切孔／减法；三图复用一次来源身份 |
| 双锥 | 删单消费者均匀气场 PowerShell 编译包装；直接调用既有 Python 编译器并保留失败停止；共用文件身份函数，删恒 PASS 判断 |
| EI／Wehnelt | 分别删除路径解析器四／五个无消费者字段；保留实际 COMSOL／CAD 运行上下文 |
| integration | 删四个无活动消费者 CLI；删通用死验证器、旧 CSV writer、manifest reader、缓存解除只读辅助函数；仅测试消费的全量内存 parser/StateRow 被删除，测试转向真实 streaming 路径 |
| 公共层 | 删五个孤立恢复／诊断／CAD CLI、四个无消费者函数／包装及始终拒绝的 --source CLI 参数；删只锁定规范文案的测试，保留行为测试 |
| 公共离子源 | cylinder receipt 校验与 continuous volume 物化复用同一次完整状态生成，删除无外部消费者的 rows 包装 |
| 其他公共边界 | common/paths 的 16 个组件消费者需要输出隔离；不同随机序列、时间／质量 KDE、bootstrap 有不同科学语义；主机调度、供应商入口和中立连接校验的有效边界保留 |

共删除 16 个脚本（生产 12、测试 4），其基线逻辑字节合计 81,445；均为 Git 管理源码，可从基线恢复；删除后活动文本对这 16 个文件名的引用为零。
未删除 artifacts、冻结历史或商业资产，未计量磁盘可用空间变化，不把源码逻辑大小称为实际释放容量。
本轮未新增生产脚本、审计框架或第二套执行入口；一次性检查以内联命令执行，遗留扫描进程已核对归属后结束。

## 行为与验证

| 对照或验证 | 结果与范围 |
|---|---|
| 四极杆默认 bundle HEAD／WORKTREE | 两工况、N100/N1000，共 9 文件逐字节一致；直接 file_sha256 调用 30→16，表 SHA 仍由已读字节计算 |
| 公共 cylinder／continuous volume | 同路径 N100 对照，CSV 与完整 receipt 字节一致；各物化／验证调用完整生成器均 1 次，原重复处为 2 次 |
| MR 步长比较 | 每输入 run 少 4 次重复全文哈希；已验证输出记录及 manifest 自身身份保留 |
| IP 截面 | 原运行时约 112,500 次随机点检查移至确定性行为回归；无消费者验证 JSON 不再物化 |
| focused 与项目回归 | 器件 93、MR 宽回归 176／最终子集 105／batch 步长 10／跨 IP 派生 21；四极杆 analysis 230／最终相关 66；六极 22、八极 29；IP 最终 Static 162、双锥 30、EI 22、Wehnelt 52；公共离子源 24；integration 最终相关 37，均通过 |
| 联合门禁 | L1 PASS；L2 全仓 PASS。MR 分析 1,409 项（skip 10）；integration 889 项（skip 3）；公共合同 639 项（skip 1）；公共 SIMION 262 项（skip 6）；公共多极杆 410 项；oaTOF 384 项（skip 1）。skip 是既有环境／显式授权边界，不代表这些层级已验证 |

初次集成回归暴露旧源码 SHA 绑定，按唯一 refresh_family_repository_bindings 编译器刷新一份派生配置后，
联合门禁重新覆盖。它是源码精简引起的合法身份更新，没有改输入物理值或放宽校验。
L1 运行期间只有项目文档收缩；最后的审计文档另走文档范围 L1。
未执行真实 Refine、Fly、COMSOL Compute、GUI/CAD 或 Formal 验收；纯 Lua fixture 不等同商业求解。
没有测量端到端加速，以上只报告实际删减和调用次数。

## CLOC 与脚本数

调用 `common/report_cloc_delta.ps1 -Base a84776a6 -Current WORKTREE`；CLOC 2.10，无 unclassified 文件。
分类器 SHA256 为 `cbfb4c9eebbb38285800e4e358a13ef66c73404c4d399b8e4bd3687f71064285`，
语言定义 SHA256 为 `985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6`。
基线选中文件身份 `4978c8a59f8144b5db059ff570574df348a9bbc30ada148bf22a6a537caa1d49`；
结果选中文件身份 `b039b1ff40938ac2bb6dad519d72a7560c1a83ee846217da2f183e920cbc4352`。

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

脚本数采用工具的 SCRIPT_FILES，包含生产模块和语言脚本，不把 JSON／TOML／YAML 配置算脚本。

### total

每格为 baseline → result（delta）。

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 511 → 511 (0) | 0 → 0 (0) | 0 → 0 (0) | 49741 → 49732 (-9) |
| Lua | 96 → 91 (-5) | 460 → 424 (-36) | 747 → 694 (-53) | 9976 → 9515 (-461) |
| MATLAB | 117 → 117 (0) | 991 → 991 (0) | 2264 → 2264 (0) | 14143 → 14134 (-9) |
| PowerShell | 155 → 152 (-3) | 1225 → 1213 (-12) | 1425 → 1425 (0) | 47938 → 47750 (-188) |
| Python | 831 → 823 (-8) | 23134 → 22976 (-158) | 15070 → 15028 (-42) | 281217 → 279992 (-1225) |
| SIMION GEM | 10 → 10 (0) | 35 → 35 (0) | 81 → 81 (0) | 246 → 246 (0) |
| TOML | 1 → 1 (0) | 4 → 4 (0) | 0 → 0 (0) | 24 → 24 (0) |
| YAML | 2 → 2 (0) | 4 → 4 (0) | 1 → 1 (0) | 120 → 120 (0) |
| SUM | 1723 → 1707 (-16) | 25853 → 25647 (-206) | 19588 → 19493 (-95) | 403405 → 401513 (-1892) |

### production

每格为 baseline → result（delta）。

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 507 → 507 (0) | 0 → 0 (0) | 0 → 0 (0) | 49631 → 49622 (-9) |
| Lua | 78 → 75 (-3) | 352 → 331 (-21) | 653 → 611 (-42) | 8106 → 7797 (-309) |
| MATLAB | 77 → 77 (0) | 542 → 542 (0) | 1743 → 1743 (0) | 10438 → 10429 (-9) |
| PowerShell | 146 → 144 (-2) | 1167 → 1159 (-8) | 1403 → 1403 (0) | 46501 → 46386 (-115) |
| Python | 426 → 419 (-7) | 13594 → 13446 (-148) | 8375 → 8337 (-38) | 158902 → 157706 (-1196) |
| SIMION GEM | 10 → 10 (0) | 35 → 35 (0) | 81 → 81 (0) | 246 → 246 (0) |
| TOML | 1 → 1 (0) | 4 → 4 (0) | 0 → 0 (0) | 24 → 24 (0) |
| YAML | 2 → 2 (0) | 4 → 4 (0) | 1 → 1 (0) | 120 → 120 (0) |
| SUM | 1247 → 1235 (-12) | 15698 → 15521 (-177) | 12256 → 12176 (-80) | 273968 → 272330 (-1638) |

### tests

每格为 baseline → result（delta）。

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 4 → 4 (0) | 0 → 0 (0) | 0 → 0 (0) | 110 → 110 (0) |
| Lua | 18 → 16 (-2) | 108 → 93 (-15) | 94 → 83 (-11) | 1870 → 1718 (-152) |
| MATLAB | 40 → 40 (0) | 449 → 449 (0) | 521 → 521 (0) | 3705 → 3705 (0) |
| PowerShell | 9 → 8 (-1) | 58 → 54 (-4) | 22 → 22 (0) | 1437 → 1364 (-73) |
| Python | 405 → 404 (-1) | 9540 → 9530 (-10) | 6695 → 6691 (-4) | 122315 → 122286 (-29) |
| SUM | 476 → 472 (-4) | 10155 → 10126 (-29) | 7332 → 7317 (-15) | 129437 → 129183 (-254) |


## 尚未闭合的后续项

以下是本轮结束时的下一步，不能据本页宣称全仓 goal 完成：

1. 同次 manifest 的 input/output 常重复列同一路径（如 IP batching）；writer/verifier 可分别在单次调用内复用
   相同解析路径与读取策略的内容读取，仍逐记录比对不同声明。不能跨发布／消费边界复用旧哈希。
2. retention→writer→verifier→capacity finalize 重复遍历同一 run；writer 独立拒绝未列重载荷仍是规范与测试合同，
   需收拢责任、同步规范后减少扫描，不直接删最后的完整 verifier 或容量准入。
3. retention 为待删临时 PA/TRJ 新算全文 SHA；开发标准与生命周期收据原 SHA 要求存在张力。
   应统一为继承已有身份，未封存可弃物用精确路径／类型／大小和保护检查，保留 pending、进度及恢复门禁。
4. 集成 runtime resolver 在已校验 state/receipt SHA、关联及 count 后再 count-csv，重复 Python 进程、CSV 扫描与
   临时 JSON。先补 receipt selector 与源合同 selector 一致性及篡改行为矩阵，再删重复计数；
   单飞链约省 2 套、分段链约省 5 套。adapter 紧接 resolver 的 source/design 前检也可合并。
5. 门禁测试中 CI 注释／超时数字／变量名、临时目录源码字符串断言可由现有行为 fixture 替代；并行日志回放
   尚有行为覆盖缺口，不批量删源码断言。
6. peak_metrics 的两个同列空间最小二乘可复用一次求解，但存在约 1.85e-13 的浮点差；
   需要明确容差和科学消费者回归。不同统计量不能因此合并。
7. oaTOF／MR／共享运行器剩余 JSON 运输和逐链物化仍需逐消费者审查；本轮引用筛查不等于完整流程证明。
