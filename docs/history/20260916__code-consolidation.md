# 公共执行机制与代码整治验收

DOC_STATUS: ARCHIVED_READ_ONLY

本页冻结[代码深审](20260916__code-size-and-complexity-audit.md)后首轮可独立闭合的公共整治。
它记录本轮交付及明确保留项，不表示全仓所有复杂度问题已消失。当前规则仍见
[开发标准](../DEVELOPMENT_STANDARDS.md)，当前调用方式见相邻公共和项目文档。

## 处置结果

| 审计项 | 本轮决策与效果 |
|---|---|
| F1 集成编排 | fine/local/overlay refine 共用一个波次执行函数；保留各自输入、缓存身份与回调。四极杆两条工作流复用自适应批次机制 |
| F2 参数多份运输 | 删除 resolved_execution_plan.json 的重复生成及 adapter 的第二套解析；冻结 composition_plan 的 execution_steps 参数作为单一执行来源 |
| F3 源码形状测试 | 路径测试不再锁定16个消费者、变量名和实现位置；保留缺省上下文检查，增加实际 MATLAB 函数的隔离行为测试；波次测试覆盖诊断输出及失败状态 |
| F4 失活辅助链 | 删除没有消费者的 migrate_v3_campaign、write_current_policy_campaign；仍有消费者的时间网格辅助函数保留 |
| F5 生命周期重复 | 三类处置入口共享按记录核验并删除文件及原子JSON写入；保护租约从容量CLI下沉为模块，解除循环/私有CLI依赖；体积源使用公共SHA实现 |
| F6 PA缓存机制 | PA-family复用有序库存和校验复制；排序、copystat及缓存发布身份继续由原调用边界负责 |
| F7/F8 MR包装与诊断 | 未修改。另一MR任务要求冻结整个项目，包含旧accelerator runner；解冻后再实施去重与退役判断 |
| F9 profile重复 | 普通与体积源复用已有解析辅助函数；62个当前profile的解析字典与原实现完全一致 |
| F10 资源策略重复 | 执行器消费冻结计划中的时间和内存阈值，校验合法数值及阈值关系，取消硬编码等值拒绝；默认策略不变 |

发布入口补充核验执行收据中的 composition、connection、budget SHA，拒绝缺失或篡改身份；
集成冻结运行时同时登记新公共模块，并验证干净快照下的CLI导入。门禁测试显式严格UTF-8解码，
修复Windows默认CP936误读中文PowerShell输出；没有修改生产门禁策略。

## 有意保留及代价

- prepare 仍然较长。删除重复参数运输后，剩余科学分支与不同SHA来源没有强行压成通用框架；
  候选路径/SHA小助手的净收益不足，单纯移动大函数不能视为消除复杂度。
- ReleaseGate仍有独立诊断消费者，保留并写明退出条件；MATLAB越界插值与不同ION分割算法存在语义差异，
  不为减行强行合并。部分源码断言尚无日常行为门禁替代，因此保留。
- 保护租约下沉主要解决依赖方向，迁移本身没有减行收益。新增两个公共模块和一个MATLAB测试，
  脚本文件数增加3；本轮未实现“代码与脚本数同时下降”的全部目标。
- 删除前补充实际文件大小/SHA复核会增加读取I/O；没有测量清理性能，也没有声称提速。
  共享函数减少重复修复，但扩大单个缺陷的影响面，因此需要干净运行时、失败路径及跨项目验收。

## 回归事故与边界

早期公共原子JSON函数提炼漏接一个导入分支，导致另一任务的MR r10在终态发布时报NameError。
修复后补齐导入与回归，MR任务确认r11跨过同一发布路径完成；r10失败证据保留。
随后采用隔离验证后整合，并补齐冻结运行时依赖，避免只在宿主仓库中可导入的隐性依赖。

整合审查还修复了PowerShell原生命令诊断输出混入函数返回值的问题，并用实际打印诊断的mock覆盖；
恢复了无效profile路径原有ValueError行为。曾尝试的sys.path启动补丁违反仓库入口规则，已完全撤回；
布局CLI遵循既有仓库根 python -m 入口，未增加兼容白名单。

以上验收不包含本轮新的COMSOL/SIMION科学求解、GUI/CAD或Formal资格认定。
科学输入与现有结果未由本轮改动，MR独立任务的代码与结果不纳入本轮规模统计。

## 验证结果

对照为相同冻结输入下的旧实现与本轮实现；仅改变公共执行、数据运输和测试机制。
验收要求默认行为、身份链与失败关闭语义保持有效，非默认资源计划按冻结值执行。

| 验证层 | 结果与范围 |
|---|---|
| L1 | 71个显式变更路径，CHANGED_GATE=PASS；后续公共COMSOL说明更新由L2覆盖 |
| L2 | REPOSITORY_INTEGRATION_GATE=PASS；18组unittest共2691项，11项按测试条件跳过、2680项通过；另含PowerShell、注册表、生成配置、Ruff、文档与标准检查 |
| 关键L2覆盖 | 公共合同321、多极杆公共405、SIMION公共129、集成894、四极杆229、oa-TOF381项；这些是上一行的子集 |
| 解析一致性 | 六极12、八极25、四极25，共62个profile字典新旧完全一致 |
| MATLAB路径行为 | 12项通过，0失败/不完整；隔离fixture自动清理，无COMSOL调用 |
| 生产回归边界 | MR独立任务确认r11终态发布跨过本轮修复点；不是本轮新增科学求解或全链资格声明 |

L1/L2与focused测试有重叠，未将多轮结果相加冒充独立用例。
提交前仅清除了新模块末尾的多余空行，并再次通过Ruff及暂存差异检查，无逻辑修改。
任务自建临时副本和CLOC快照已清理；既有科学文件和其他Agent的文件未删除。

## 固定提交与实际规模

基线 `a26765a8baeee83ec022f65cff54ed0b200eace8` →
结果 `3d3fe0da81ee79474a44ee67a2e3c09abd523111`。
两个端点都固定为Git提交，不采用混有另一MR任务改动的WORKTREE。

| 主题 | 提交 | 文件数 |
|---|---|---:|
| 生命周期、缓存与集成 | `92c21dda` | 51 |
| profile、资源及四极波次 | `143c3fa5` | 16 |
| 路径行为测试与说明 | `f01a51b4` | 4 |
| 门禁UTF-8测试 | `3d3fe0da` | 1 |

CLOC code总量325654→325380，净减少274（约0.084%）；production减少246，tests减少28。
生产Python/PowerShell合计减少260，增加14行JSON依赖登记；测试Python减少101、MATLAB增加73。
这是一轮局部机制简化，不足以说明仓库已经“大幅瘦身”。新增脚本3个，未删除脚本文件；
脚本数1127→1130。科学分析及solver_models分类code均不变。

### 分类与语言明细

各单元格为“基线 → 结果（delta）”；files为CLOC纳入文件数，不等同于全部仓库文件数。

#### total

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 488 → 488 (0) | 0 → 0 (0) | 0 → 0 (0) | 48581 → 48595 (+14) |
| Lua | 98 → 98 (0) | 488 → 488 (0) | 657 → 657 (0) | 9208 → 9208 (0) |
| MATLAB | 110 → 111 (+1) | 967 → 976 (+9) | 2183 → 2184 (+1) | 12934 → 13007 (+73) |
| PowerShell | 151 → 151 (0) | 1106 → 1106 (0) | 1098 → 1097 (-1) | 40616 → 40494 (-122) |
| Python | 757 → 759 (+2) | 18493 → 18497 (+4) | 8361 → 8461 (+100) | 213921 → 213682 (-239) |
| SIMION GEM | 11 → 11 (0) | 35 → 35 (0) | 83 → 83 (0) | 256 → 256 (0) |
| TOML | 1 → 1 (0) | 4 → 4 (0) | 0 → 0 (0) | 24 → 24 (0) |
| YAML | 2 → 2 (0) | 4 → 4 (0) | 1 → 1 (0) | 114 → 114 (0) |
| SUM | 1618 → 1621 (+3) | 21097 → 21110 (+13) | 12383 → 12483 (+100) | 325654 → 325380 (-274) |

#### production

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 484 → 484 (0) | 0 → 0 (0) | 0 → 0 (0) | 48471 → 48485 (+14) |
| Lua | 84 → 84 (0) | 385 → 385 (0) | 588 → 588 (0) | 7527 → 7527 (0) |
| MATLAB | 72 → 72 (0) | 529 → 529 (0) | 1665 → 1665 (0) | 9436 → 9436 (0) |
| PowerShell | 143 → 143 (0) | 1054 → 1054 (0) | 1088 → 1087 (-1) | 39554 → 39432 (-122) |
| Python | 398 → 400 (+2) | 11437 → 11432 (-5) | 5955 → 5955 (0) | 125869 → 125731 (-138) |
| SIMION GEM | 11 → 11 (0) | 35 → 35 (0) | 83 → 83 (0) | 256 → 256 (0) |
| TOML | 1 → 1 (0) | 4 → 4 (0) | 0 → 0 (0) | 24 → 24 (0) |
| YAML | 2 → 2 (0) | 4 → 4 (0) | 1 → 1 (0) | 114 → 114 (0) |
| SUM | 1195 → 1197 (+2) | 13448 → 13443 (-5) | 9380 → 9379 (-1) | 231251 → 231005 (-246) |

#### tests

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 4 → 4 (0) | 0 → 0 (0) | 0 → 0 (0) | 110 → 110 (0) |
| Lua | 14 → 14 (0) | 103 → 103 (0) | 69 → 69 (0) | 1681 → 1681 (0) |
| MATLAB | 38 → 39 (+1) | 438 → 447 (+9) | 518 → 519 (+1) | 3498 → 3571 (+73) |
| PowerShell | 8 → 8 (0) | 52 → 52 (0) | 10 → 10 (0) | 1062 → 1062 (0) |
| Python | 359 → 359 (0) | 7056 → 7065 (+9) | 2406 → 2506 (+100) | 88052 → 87951 (-101) |
| SUM | 423 → 424 (+1) | 7649 → 7667 (+18) | 3003 → 3104 (+101) | 94403 → 94375 (-28) |

#### unclassified

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| SUM | 0 → 0 (0) | 0 → 0 (0) | 0 → 0 (0) | 0 → 0 (0) |

### 工具与完整过滤口径

使用仓库 `common/report_cloc_delta.ps1`、CLOC 2.10、skip-uniqueness；
MATLAB/Lua/GEM自定义语言映射及用途分类由同一入口执行。unclassified为0。
本报告及索引后续提交仅含文档，CLOC_DELTA=N/A (docs-only)。

- classifier SHA256: `db9ed262601aa58092558467e9652fcc82c3787383e283c356973142e535809a`
- language definition SHA256: `985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6`
- baseline input SHA256: `6aff8b862ae18e07efa03a0ab1f5762cb81cb6e64fe438852b5e819588241ff1`
- result input SHA256: `032cbcb26dcab4bfd5737200f62e51100ebed832baca3fad77d69a4cd403acf6`

```text
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;
excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;
excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;
language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;
production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);
tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|*Test.m|*.Tests.*;
unclassified=other_code_below_test_or_tests_path;
worktree_source=git_tracked_plus_nonignored_untracked
```

## 后续进入条件

MR的F7/F8在所属任务明确解冻整个项目后继续，先核对当时活动runner和诊断消费者，
再决定合并或退役。其余保留项只有出现等价行为覆盖或明确失去消费者后才删除；
不能把移动代码、缩短排版、丢弃科学差异计作整治收益。
