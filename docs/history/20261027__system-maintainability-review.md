# 全仓文档与执行边界系统审查

DOC_STATUS: ARCHIVED_READ_ONLY

## 范围和身份

本次审查沿“质谱仪仿真组装厂”的统一规则，修复项目发现、执行配置、控制器、完成事实、
失败日志和文档职责的具体问题。以另一线程已提交的
`200113904859212cc8c7a065e7085dd9f1de6603`为独立基线；不重复计算其历史迁移或GUI加载器工作。
结果提交：6f207abbc2b410b453dbd7a556800a19fd2326d0。普通文字修订由Git保留，不附旧文档全本副本。

## 问题关闭

| 问题 | 修改后的权威与边界 |
|---|---|
| 公共结构变体被多极杆物理字段约束 | 公共descriptor只登记身份和能力归属，OA二区/三区与RF四/六/八极共用显式选择；歧义返回NEEDS_CLARIFICATION |
| 具名设计公共合同与项目物理混合 | v3公共设计登记验证来源身份、变量指针、范围、包络与能力；RF schema/resolver校验极数、拓扑和设计选项，不建设动态插件框架 |
| IP执行profile兼任私有预算 | 公开execution_profiles登记现有固定524 Da、+1 functional入口；预算移至runtime_profiles，旧冻结名称只允许显式历史GUI回放 |
| 旧状态和重复时间线遮挡当前答案 | INTEGRATION整理为当前结果、证据及限制；MR PROJECT只路由跨项目结论，保留旧plan身份缺口 |
| MR控制器双份科学决策和隐式上下文 | 纯Python控制器持有步长、候选与恢复状态；PowerShell显式Context负责执行；v5/6/7只通过具名导入生成新run的v8副本 |
| 失败门禁结束即删除日志 | 并行与串行fallback均保留失败日志、请求JSON、group_failure及精确清理命令，成功组才尝试清理 |
| SIMION完成判断散落 | native_completion维护TRACE和stdout各自严格合同；通用保留层经现有适配器调用，验证声明后才删除或写收据 |
| 软件文档职责和位置不清 | 根OPERATIONS保留用户操作，common入口说明公共实现；项目软件说明统一docs；COMSOL指南/API/排错职责分开；SolidWorks说明实际桥接API |

MR恢复审查修复了v5/v6阶段排序、Context隐式依赖和冻结handoff路径回绑三个行为问题。
保留既有prepared P/S、源/场/停止语义；公开运行入口数不增加。普通恢复默认v8，未知旧版本拒绝；
17个历史checkpoint（v5=4、v6=7、v7=6）只读验证，原文件字节不改写。
公共规划仍保留必要项目provider适配，不宣称全部科学编译已通用化。

集成完整回归另发现三个consumer漏登记新的native_completion依赖；已在既有清单补齐，
原测试扩至九个实际消费者，脱离活动源码执行bare-file与模块CLI，验证完成日志保留及缺adapter时失败关闭。

## 文档决策与规模

保留统一README、PROJECT和可维护历史索引。不因个别项目规模小而放宽规则，也不强制创建无内容的软件页面。
COMSOL_GUIDE、COMSOL_API、COMSOL_DEBUGGING分别承担使用、接口和故障定位，合并会扩大任务阅读量，因此保留。
SIMION_REFERENCE保留稳定名称；公共实现职责在common/simion/README说明。
MR的simion/README迁入docs/SIMION；oa-TOF检查单改名SIMION_DELIVERY_CHECKLIST，并更新真实打包消费者。
两者均一进一出；只新增common/README和common/analysis/README两个缺失入口。
三处冻结历史旧MR路径不改正文，由所属可维护索引解释新入口。

统计以UTF-8解码并规范化换行，排除所有docs/history冻结正文，保留8份history README。
基线116份、22068行、744549字符；结果118份、22050行、740817字符：净增2份、减少18行和3732字符。
冻结历史Markdown为184→185，新增项仅本篇；全部Markdown为300→303。
新增本篇冻结审计不增加维护文档数。
门禁/资源实现从OPERATIONS迁入common入口，独立逐行规范化比较无约束遗漏。
六项任务检索覆盖OA变体、RF长度、IP预算、COMSOL API/排错、SolidWorks和失败日志，均能由入口到唯一权威。

## 验证与边界

官方完整L2使用共享WORKTREE运行，33阶段中30 PASS、3 FAIL；共5315 tests、20 skipped、5条failure记录。
多极杆foundation不计入unittest数，三结构合同PASS；快速/前置13阶段全部PASS。
下表回归组共5157项；前置的scheduler 77、LiveLink resource 41、TOF预算16和文档链接24项共158，合计5315。
不把这一轮写成整体成功，也不把单个子例计为一种物理失败。

| L2回归组 | tests | skipped | 秒 | 原轮结果 |
|---|---:|---:|---:|---|
| longitudinal | 3 | 0 | 0.093 | PASS |
| population | 3 | 0 | 0.001 | PASS |
| events | 6 | 0 | 0 | PASS |
| common_contracts | 758 | 1 | 272.246 | FAIL 2 CRLF |
| simion | 326 | 6 | 82.824 | PASS |
| rf_domain | 473 | 0 | 342.385 | PASS |
| integration_common | 55 | 0 | 10.138 | PASS |
| assembly | 592 | 0 | 1833.704 | FAIL 1 dependency closure |
| solidworks | 2 | 0 | 0.006 | PASS |
| oa | 111 | 0 | 4.662 | PASS |
| mr_static | 1673 | 12 | 2053.788 | FAIL 2 fixture subcases |
| single_reflection | 453 | 1 | 268.367 | PASS |
| quadrupole | 231 | 0 | 157.475 | PASS |
| hexapole | 22 | 0 | 25.06 | PASS |
| octupole | 35 | 0 | 29.48 | PASS |
| ip | 312 | 0 | 140.765 | PASS |
| dual_cone | 30 | 0 | 6.853 | PASS |
| electron_gun | 50 | 0 | 29.862 | PASS |
| ei_source | 22 | 0 | 2.054 | PASS |

首轮受限环境检查已提前失败：一处新测试subprocess缺cwd已补齐；进程创建身份观测及自有fixture终止被环境拒绝，
随后在正常权限上下文复验通过。两个环境故障未记为模型或物理FAIL。
正常权限L2的三类失败及关闭证据：

| 原失败 | 根因与修复 | 后续验证 |
|---|---|---|
| common_contracts两项 | INTEGRATION新文本含CRLF；规范为LF | 同catalog、同参数及同源码的正式L1整组758/1 skip PASS，308.048秒 |
| assembly一项 | 三个冻结consumer漏登记native_completion | dependencies整模块10/94.679秒PASS；九consumer×两种CLI×adapter存在/缺失，共36次实际脱仓调用；正式三文件L1见下 |
| MR两个subtest | 测试抽取函数时未执行param，遗漏生产入口已有空默认值 | 只改fixture四行，从真实AST读默认并核对Context；111 runner+14纯状态共125/368.743秒PASS；独立复核确认生产源码未变 |

原全改动L1：84路径、23适用阶段，22 PASS/1 FAIL；3228 tests、8 skipped，唯一失败仍为上述依赖闭包。
MR的L1 Core42不能代替L2 Static1673；两者在本报告分开保存。
门禁的no_route_match/covered_by_common_contracts是路由决定，不混入unittest skipped数量。

修后三个实际变更路径按既有catalog执行一次正式L1：6阶段全部PASS，exit 0。
组装592 tests/1549.952秒、MR Core42 tests/172.135秒，共634项、0 skipped；阶段耗时分别1565.033和183.456秒。
卫生、文本字节、开发标准和Ruff亦PASS。成功组按公共机制报告GATE_DIAGNOSTICS=CLEANED，未保留独立成功日志文件；结果来自实际工具终态。
没有重跑整个L2或把MR Core冒充Static；完整受影响模块与不变生产源码的已有Static覆盖共同关闭夹具缺口。

源码身份是运行中的实际字节盘点，不是运行前冻结源码包：
01:51:55.897 UTC的1583项集合SHA256为`10340275a2680964c698d017cb028df154334af28163f620c73843a5bcc95882`；
03:11:05.582 UTC的最终集合为`7c297a981da3912e5aac698c041f048b2f74529712b6cc610ff7fc5b2ae08ce9`，
与修后三文件L1启动前一致。差异恰为运行依赖清单、依赖测试和MR runner测试三个文件，其他生产源码未漂移。
算法：Git tracked及非忽略untracked去重排序，排除Markdown与docs/history；逐项记录path、bytes及原始字节SHA256，
缺失项标missing；对sort_keys=True、separators=(',',':')的UTF-8 JSON数组计算集合SHA256。

最终文档L1通过DOCUMENTATION_ONLY快速路径：303份Markdown、活动链接／锚点0错误、161个历史归档、9个权威入口；卫生和文本字节检查亦PASS。
本篇首次检查因缺少只读归档标记失败，补齐标记后通过；不将这次格式修复算作源码或科学变化。


没有新增真实物理求解、参数优化或Formal资格。本轮纯代码/合同检查与另线程实际商业证据分开记录。
INTEGRATION保留235338整run发布失败、strict金属域500/1100、IP性能未过阈值、旧plan缺少绑定、
N2零探测及跨求解器未等价等限制。另线程CAD新证据只证明工程几何与STEP交换，
四处原始实体交叠仍存在；GUI按用户最新要求核对代码实现，不补写旧人工验收。

## CLOC

运行入口为`common/report_cloc_delta.ps1`，工具CLOC 2.10。
最终统计直接绑定固定提交`200113904859212cc8c7a065e7085dd9f1de6603 → 6f207abbc2b410b453dbd7a556800a19fd2326d0`。
与先前WORKTREE统计的全部行数、分类和脚本数一致；后续审计与索引只修改Markdown。
执行时仅将该进程LC_ALL、LC_CTYPE和LANG设为C，避免Windows Perl不支持C.UTF-8导致拒绝计数。
基线1532文件SHA256为`c42ae6db40ba6f0a34cba680994d8d94b5d8cbc0dd7b36063366dd6b492e4cb2`；
结果1540文件SHA256为`eeaa3ff83b6d4f6dd4e158899a06deb519f113419b8e0aa3d302128bcfecb0a6`。
分类器SHA256为`d3365e7f02e66a775ec8eb3b12fb7b7bfa1bf34b87009543768a8e36bb4db749`；
语言定义SHA256为`985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6`。
unclassified=0；下表每格顺序为基线、结果和delta。

| 类别 | 语言 | files 基线→结果 (Δ) | blank 基线→结果 (Δ) | comment 基线→结果 (Δ) | code 基线→结果 (Δ) |
|---|---|---|---|---|---|
| total | JSON | 324 → 329 (5) | 0 → 0 (0) | 0 → 0 (0) | 38498 → 38749 (251) |
| total | Lua | 95 → 95 (0) | 360 → 360 (0) | 711 → 711 (0) | 11053 → 11053 (0) |
| total | MATLAB | 123 → 123 (0) | 954 → 954 (0) | 1947 → 1947 (0) | 14462 → 14462 (0) |
| total | PowerShell | 142 → 142 (0) | 1019 → 1021 (2) | 984 → 957 (-27) | 38218 → 38175 (-43) |
| total | Python | 835 → 838 (3) | 23270 → 23362 (92) | 20226 → 20358 (132) | 271494 → 272450 (956) |
| total | SIMION GEM | 10 → 10 (0) | 26 → 26 (0) | 54 → 54 (0) | 214 → 214 (0) |
| total | TOML | 1 → 1 (0) | 4 → 4 (0) | 0 → 0 (0) | 24 → 24 (0) |
| total | YAML | 2 → 2 (0) | 4 → 4 (0) | 2 → 2 (0) | 140 → 140 (0) |
| total | SUM | 1532 → 1540 (8) | 25637 → 25731 (94) | 23924 → 24029 (105) | 374103 → 375267 (1164) |
| production | JSON | 323 → 328 (5) | 0 → 0 (0) | 0 → 0 (0) | 38364 → 38615 (251) |
| production | Lua | 78 → 78 (0) | 296 → 296 (0) | 614 → 614 (0) | 9372 → 9372 (0) |
| production | MATLAB | 76 → 76 (0) | 483 → 483 (0) | 1388 → 1388 (0) | 9827 → 9827 (0) |
| production | PowerShell | 134 → 134 (0) | 962 → 963 (1) | 951 → 924 (-27) | 36607 → 36525 (-82) |
| production | Python | 420 → 421 (1) | 13026 → 13066 (40) | 8812 → 8844 (32) | 144284 → 144576 (292) |
| production | SIMION GEM | 10 → 10 (0) | 26 → 26 (0) | 54 → 54 (0) | 214 → 214 (0) |
| production | TOML | 1 → 1 (0) | 4 → 4 (0) | 0 → 0 (0) | 24 → 24 (0) |
| production | YAML | 2 → 2 (0) | 4 → 4 (0) | 2 → 2 (0) | 140 → 140 (0) |
| production | SUM | 1044 → 1050 (6) | 14801 → 14842 (41) | 11821 → 11826 (5) | 238832 → 239293 (461) |
| tests | JSON | 1 → 1 (0) | 0 → 0 (0) | 0 → 0 (0) | 134 → 134 (0) |
| tests | Lua | 17 → 17 (0) | 64 → 64 (0) | 97 → 97 (0) | 1681 → 1681 (0) |
| tests | MATLAB | 47 → 47 (0) | 471 → 471 (0) | 559 → 559 (0) | 4635 → 4635 (0) |
| tests | PowerShell | 8 → 8 (0) | 57 → 58 (1) | 33 → 33 (0) | 1611 → 1650 (39) |
| tests | Python | 415 → 417 (2) | 10244 → 10296 (52) | 11414 → 11514 (100) | 127210 → 127874 (664) |
| tests | SUM | 488 → 490 (2) | 10836 → 10889 (53) | 12103 → 12203 (100) | 135271 → 135974 (703) |

生产code净增461，测试净增703，合计1164。脚本文件1205→1208，其中新生产纯Python模块1个、测试2个；
另外新增JSON配置/schema共5个。MR三个生产源码文件合计行数净增140，重复科学决策减少不等同于总行数下降。
本轮目标是明确职责、复用判定和可诊断性，不用拆文件、减少测试或删除必要约束制造减量。

完整过滤及分类口径：

```text
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```

## 交接

独立实现与审查由Agent 1–4承担，Agent 0统一集成；另一线程先完成其独立主题并交接Git写权。
四个主题提交为e9b9ed2c（发现／profile）、ca5d2132（MR控制器）、4b52ae18（公共诊断／冻结依赖）、
6f207abb（项目文档与当前事实）。本篇仅新增一份必要的系统审计，不复制旧全文或新增运行器。
原失败日志保留供同期架构终审独立消费，随后按公共精确清理入口处置；成功门禁、冻结测试和CLOC临时内容由各自入口清理。
既有冻结历史正文与封存181621迁移run保持不变。结果资格、现行规则与运行记录仍各有唯一所有者。
