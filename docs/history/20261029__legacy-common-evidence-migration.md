# 旧 common 证据归位与精确处置

DOC_STATUS: ARCHIVED_READ_ONLY

本记录冻结 2026-10-29 的历史证据迁移。它独立于仍在执行的全指南审查，不给原科学运行增加成功、
Candidate 或 Formal 资格。布局修复只承认现有公共执行别名合同与具名当前主机数据库，不开放任意
common 目录、SQLite 备份或非 JSON 处置日志。

## 原始证据与恢复位置

工作区 artifact 根为 `artifacts/`；表中原路径均相对此根。23 份提交验证日志来自
`common/scratch/20261022_commit_workspace/`，原 owner 为 `repository_commit_validation`；
另 1 份原 owner 为 `instrument_assembly` 的退役控制台日志来自处置收据目录。
载荷保持原字节，仅在文件名后加 `.txt`，不作为活动 CLI、源码或当前规则。

| 原路径 | 原字节载荷 | bytes | SHA-256 |
|---|---|---:|---|
| `common/scratch/20261022_commit_workspace/cleanup.json` | [cleanup.json.txt](20261029__legacy-common-evidence-migration/cleanup.json.txt) | 687 | `6BBF7993A30380A274C09182B199FB61A5A562F490D4BD6BD32A274654A79389` |
| `common/scratch/20261022_commit_workspace/cloc-final.log` | [cloc-final.log.txt](20261029__legacy-common-evidence-migration/cloc-final.log.txt) | 14154 | `59BDD4E8D942220BC885BE254F40742DF9A373FC69B8D0D12B18FB31AD8B934D` |
| `common/scratch/20261022_commit_workspace/cloc-release.log` | [cloc-release.log.txt](20261029__legacy-common-evidence-migration/cloc-release.log.txt) | 14188 | `91FD43E60BAE993DE9F565D29AD9CD3B5B59431667D9E2E88F551A33E5912F16` |
| `common/scratch/20261022_commit_workspace/cloc.log` | [cloc.log.txt](20261029__legacy-common-evidence-migration/cloc.log.txt) | 14284 | `AE76A395C2127E07914C2FF1A6622BDB60A9B2CA2BE10C1AA21D1AC345A1DF82` |
| `common/scratch/20261022_commit_workspace/commits.txt` | [commits.txt.txt](20261029__legacy-common-evidence-migration/commits.txt.txt) | 582 | `C2A99CA561D8E252139C09D0332A0AB5BD99B2AF7C1246A7C0888796551DF35C` |
| `common/scratch/20261022_commit_workspace/documentation_migration_navigation.log` | [documentation_migration_navigation.log.txt](20261029__legacy-common-evidence-migration/documentation_migration_navigation.log.txt) | 3559 | `7E33D168E8D4AFF127A7DC1BA1B89B19174C75E11E5DDB3F3F846378FFD58A3D` |
| `common/scratch/20261022_commit_workspace/focused-failure-probe.log` | [focused-failure-probe.log.txt](20261029__legacy-common-evidence-migration/focused-failure-probe.log.txt) | 483 | `FEAFB63BAD266C6B77E3E4B8765DBF8E3C7AED7CBE644F012D1CE8EFAFB6DF48` |
| `common/scratch/20261022_commit_workspace/l1-current.log` | [l1-current.log.txt](20261029__legacy-common-evidence-migration/l1-current.log.txt) | 24326 | `BD8D637D0F72FD96087DA95870D5DA0F386156B2DA4A5EDAA5AFA02E48524745` |
| `common/scratch/20261022_commit_workspace/l1-isolated.log` | [l1-isolated.log.txt](20261029__legacy-common-evidence-migration/l1-isolated.log.txt) | 47793 | `3EF4ACAC327E932142CCA1E81325F7A70B5509AE8A0686DC83C71522F9445050` |
| `common/scratch/20261022_commit_workspace/l1-quad-fixture.log` | [l1-quad-fixture.log.txt](20261029__legacy-common-evidence-migration/l1-quad-fixture.log.txt) | 10395 | `B88E3A87210A45D24B1FBE996440221F9E49DB9108EEE084E9C5836CC7245CDB` |
| `common/scratch/20261022_commit_workspace/l1-serial.log` | [l1-serial.log.txt](20261029__legacy-common-evidence-migration/l1-serial.log.txt) | 32229 | `26D7CF25A60919D86E1A3EBC297BD8C944C0E84E77ED87A2578F8672FFE0932F` |
| `common/scratch/20261022_commit_workspace/l1.log` | [l1.log.txt](20261029__legacy-common-evidence-migration/l1.log.txt) | 26911 | `A360241F9C15039BA20CB69A0EE5546628A3DCF8C89DC908F442E9BAF471AE7D` |
| `common/scratch/20261022_commit_workspace/l2-serial.log` | [l2-serial.log.txt](20261029__legacy-common-evidence-migration/l2-serial.log.txt) | 61413 | `A0F0253E8CFC5BAF4F2F37D651DF6AAFAE2A593C18F8A207DDF1DD81887B3B26` |
| `common/scratch/20261022_commit_workspace/l2.log` | [l2.log.txt](20261029__legacy-common-evidence-migration/l2.log.txt) | 974 | `A097D42C522EAA080AB5C90677BC9D8A1B26B1DA560CAF8B0FADDB0EEB26A667` |
| `common/scratch/20261022_commit_workspace/mr-adapters-recheck.log` | [mr-adapters-recheck.log.txt](20261029__legacy-common-evidence-migration/mr-adapters-recheck.log.txt) | 103 | `5908C79981B1361A56B0A2D7BEDB0E9BD7FC9A2EFDFB1968BE756DD713E25FAB` |
| `common/scratch/20261022_commit_workspace/mr-core-recheck.log` | [mr-core-recheck.log.txt](20261029__legacy-common-evidence-migration/mr-core-recheck.log.txt) | 1878 | `F31B78EC80D8F4D7E8FB181DD75BDCD7BCAFD05754E940766C94A80A4AB42C2A` |
| `common/scratch/20261022_commit_workspace/mr-focused-failure-probe.log` | [mr-focused-failure-probe.log.txt](20261029__legacy-common-evidence-migration/mr-focused-failure-probe.log.txt) | 21747 | `9CFDC178AE0BF42F79CDED108CE5DA4E2BF7468544FB8D07C1F17C686BC73D3B` |
| `common/scratch/20261022_commit_workspace/mr-runner-module-recheck.log` | [mr-runner-module-recheck.log.txt](20261029__legacy-common-evidence-migration/mr-runner-module-recheck.log.txt) | 230 | `FD59FCAF9AF227A2F53DD19809B404D67116065BC7F468FF52BD80165900989C` |
| `common/scratch/20261022_commit_workspace/quad-static-recheck.log` | [quad-static-recheck.log.txt](20261029__legacy-common-evidence-migration/quad-static-recheck.log.txt) | 1617 | `FB7A52228664F801F2E9212C4DE753ACEC8F8452666FDECBB22F9CF3FD879385` |
| `common/scratch/20261022_commit_workspace/release_report.md` | [release_report.md.txt](20261029__legacy-common-evidence-migration/release_report.md.txt) | 7957 | `6A46D841AF9843B1F3801E68D07C9658AEEBCEDD0854E13E0374080B63119D86` |
| `common/scratch/20261022_commit_workspace/remaining-worktree.txt` | [remaining-worktree.txt.txt](20261029__legacy-common-evidence-migration/remaining-worktree.txt.txt) | 19383 | `CB4F6033E9C0E96118D62467440CB750AFA6A7EA1A98322AE1FE3C25A4CFE11F` |
| `common/scratch/20261022_commit_workspace/status-freeze.txt` | [status-freeze.txt.txt](20261029__legacy-common-evidence-migration/status-freeze.txt.txt) | 19959 | `EF581C8C4F439CA2DF254E13C70F240762937CF7B53363ABBF6A259789386698` |
| `common/scratch/20261022_commit_workspace/worktree-development-standards.log` | [worktree-development-standards.log.txt](20261029__legacy-common-evidence-migration/worktree-development-standards.log.txt) | 56 | `65AE4E7A500DF9074C931D4C994C5C747B67958CE2C8CA87764B7F4E7BCEA868` |
| `common/capacity_disposal_receipts/20261024__151103-frontend-copy-retirement.log` | [20261024__151103-frontend-copy-retirement.log.txt](20261029__legacy-common-evidence-migration/20261024__151103-frontend-copy-retirement.log.txt) | 290978 | `430055C3745C8D097BE6016009BFCD057E150A5FD4BED594BCECCC62D79C00D7` |

2026-10-22 原报告对应 `52d2b2b8f162b8f478ddc0be2c8dd06c8e8084a2` →
`986d0c86fc1b40697c4a2c829511cf21b5bf6368`，6 个提交、18 个源码/文档文件。
完整串行 L1 通过；首次完整 L2 的 MR Static 和四极杆 Static 失败。后续 MR 两个原失败项、
111 项完整模块及 Core 复验、四极杆 230 项 Static 复验通过，**没有完整 L2 单轮零退出的证据**。
这些旧日志的资格边界不由本次归档改写；完整原文见表中 `release_report.md.txt`。

2026-10-24 日志的嵌入 JSON 与原运行
`projects/instrument_assembly/runs/20261024_151103__sim__simion__full-single-reflection-oatof-n100/solver_review_retirement_receipt.json`
逐对象相等；该原收据 285213 bytes，SHA-256
`B39583D26162EFB3186ED0454847E1E74D0076D21FB404B7F135290CF906F0D0`。
日志记录 6 个 frontend PA 副本的历史退役、13935180792 bytes 删除与当时的 reseal pending，
不是本次重新删除这些 PA。既存
`common/capacity_disposal_receipts/20261024__151103-frontend-copy-reseal.json`
记录其后 ready 封存。原 run 收据和这份 reseal JSON 未改；新迁移收据绑定两者原始文件身份。

## 52 份 task_inputs 的逐项依据

本次完整核对 52 文件，共 245965 bytes。42 文件（196718 bytes）已有 manifest 绑定且实际原字节
相同的副本；10 文件（49247 bytes）没有同字节副本，保存到新受管 MR run。
核对读取 7634 个 manifest、22906 个 manifest/config/summary 文档及 99 个匹配的小型冻结副本；
未读或哈希 PA 载荷。两个旧 JSON 无法解析，另按原始文本核对，均未引用旧 task_inputs 根：

- `20260917_003000__sim__simion__mrtof-bare-mirror-period-y280-r61/run_config.json`
- `20260929_085427__sim__simion__mrtof-condition-n1-workpoint-iter-05/summary.json`

当前源码/配置、上述运行元数据、匹配副本、进程命令行及新鲜 lease/ledger 检查未发现需要旧原路径的
活动消费者。不凭 3 个样本外推 52 个文件，也不因副本所属运行失败就删除其必要证据。
完整逐项原路径、原 owner、bytes、SHA、目的路径和保留 manifest SHA 见新 run 的
`inputs/evidence_migration_plan.json`；42 个已有副本只引用，不重新复制。

新 run 为
`projects/parallel_mirror_dual_stripe_mr_tof/runs/20261029_001647__analysis__python__mrtof-legacy-common-evidence`，
mode `legacy_common_evidence_preservation`，compact、ready/light_evidence，驻留 140085 bytes。
它保存 10 个唯一 author 输入、16384-byte 旧 host 数据库、784-byte 原删除收据和迁移清单。
原数据库 owner 仍为 `common.host_resources`，sequence 984，关联 MR run
`20260924_224500__sim__simion__mrtof-baseline-screen-n100-static`；它只作历史证据，不是当前控制面。
原删除收据保留旧 schema/owner/字节，未伪装成新容量处置收据。

新 run 的 `success` 仅表示证据保存完成；native_execution_count=0，不代表任何科学成功。
它使用公共 package、单一容量 session、retention、manifest/finalize、释放入口。
manifest SHA-256 为 `C465637ACC58D4ADF76648DE7DAA43E317D403A0659577180A1EEFAA241DCC7B`；
迁移 plan SHA-256 为 `6339E8833F3F817A423E6033A4015B53CCB6C6DD29159471797DE75A28A45EFD`。
这些 artifacts 不随 Git 分发；需要复原时由原 owner 提供上述身份的 run，
按 plan 的恢复映射核验副本，不能凭路径缺失重造原数据。

## 处置、账面库存与验证边界

第一批 77 文件共 588041 bytes：52 个 author、23 个旧任务日志、旧 host 备份与旧删除收据。
复制及核验期间持源文件只读/允许删除的 Windows handle，拒绝写入；公共 decision lock 内重读 ledger
和 active lease，按精确记录调用 `remove_recorded_files`，不递归扩删。
随后仅移除已空的明确目录。全部 77 个目的副本在删除后重新核对 bytes/SHA。

第一批公开收据
`common/capacity_disposal_receipts/20261029_001647__legacy-common-evidence-migration.json`
为 22930 bytes，SHA-256
`6D69F078DC99335E2D73D8F0DD5E59DF9EFF0E0281A8E9DC6EA7F84F0C2EE67A`。
执行脚本在上述步骤完成后，因向 host release 误传 `Outcome=completed` 而 exit 1；
未将整脚本记为 PASS。源 handle 已释放，原 host owner 已退出，随后公共
`Get-HostResourceStatus` 返回空 records，正常回收已证实；独立后验确认归档、删除和容量终态成立。
一次性 TEMP 作者 66043 bytes 后由主 Agent 经正常审批精确删除；SHA 为
`E2FEAB6CCF8D2D8920E28D107EBC7E74560853055875EAD732F046CA1BF86D4F`。
此前本 Agent 的清理被自动审批以 `blocked by policy` 拒绝后未换工具重试。

第 78 个历史退役日志先在“未登记范围”前置检查被拒，未删除。核实它属于已登记的
`common/capacity_disposal_receipts` 整目录后，沿原 `common.capacity_lifecycle` owner 精确迁移；
短 decision lock 内复查 class/status/pin/disposition/保护和源身份，完成单文件处置，
锁外调用自行加锁的公共 `record_capacity_object`。没有嵌套非重入锁或直接写 ledger。
新收据 `20261029__frontend-copy-retirement-log-migration.json` 2819 bytes，SHA-256
`E33F158F7F2B234CFE5FFB87C61B64C4CE7A6EA1C41619CFFFDD997557AF9FD5`，
保留原 ledger row 及旧 v2 字段由正常 ready 登记移除的依据。
当时治理根实际库存 56792708 bytes，旧登记仅 4681187 bytes；迁移后登记 56504549 bytes，
按全部直接文件 metadata 重算并核对 resident，不能把既有约 52 MB 漂移解释为删除收益。

最后一个已批准目标为 0-byte `common/capacity_disposal_receipts/residual_sweep_plan_latest.json`，
SHA-256 为 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`。
既有测试 `test_lease_registration_ignores_empty_historical_plan_placeholder` 已明确它是历史空计划；
无内容需要另存载荷。精确处置的新收据
`20261029__empty-historical-plan-placeholder-disposal.json` 为 1589 bytes，SHA-256
`9335090F72505B6E64AF03779BE560FA4C035859A1E635661920774CC637707C`，
保存原创建/修改时间、授权、原 ledger row 与公共操作依据。该次命令 exit 0，host 正常 released。
原前 78 文件的收据不改；治理目录最终 5710 个直接 JSON、56506138 bytes，与重新登记及 resident
一致。没有以坏 JSON 为由泛化扫描删除。

总计移除 79 个旧原路径文件、879019 bytes；其中 196718 bytes 为已有严格副本的重复内容，
682301 bytes 原始必要内容分别保留在新 run 与 24 个只读历史载荷中。
新 run、历史原字节载荷及 3 个处置收据共 783309 bytes，不含本 Markdown；
这些必要元数据成本不能省略。另由主 Agent 精确清理一次性 TEMP 作者 66043 bytes。
初次复制前卷可用空间 625776816128 bytes，最终布局复核时 625732829184 bytes，差值
-43986944 bytes；其间有并发系统与其他任务写入，不能把该观测当作本次独占物理释放量。
完整读取扫描未单独计时，不报告其 wall-time 或吞吐收益。

本次实际 `verify_artifacts_root(..., verify_hashes=False)` 已越过 common 直接成员、ledger、
execution_aliases、当前 host DB 与全部直接 JSON 记录；随后失败于独立旧目录
`common/simion/orthogonal_accelerator_pa_family_cache/`，其直接成员为 `.locks` 与 `.transactions`。
该目录不在本次获批处置范围，未改白名单、未删除或移入本历史，也没有宣称 root/common 全 PASS。
失败发生在当前 PA family cache 检验之前；本次记录关闭的是上述明确历史证据迁移子主题，
不是整个 H4 或全指南目标。

本轮没有商业工具、求解、PA 删除或 PA payload 哈希，没有修改旧 run/manifest。
布局回归为 35 项 PASS、0 skip；新增 junction fixture 补 cwd 后该项再次 PASS。
没有重复完整 L1/L2；上述历史测试和本轮 layout 验证范围分别成立。
历史正文与原字节载荷本身为 docs-only，CLOC_DELTA=N/A；layout 源码变化由全指南主题的公共 CLOC 统一统计。
