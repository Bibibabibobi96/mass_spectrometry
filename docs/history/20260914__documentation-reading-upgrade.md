# 2026-09-14 文档阅读路径升级与验收

DOC_STATUS: ARCHIVED_READ_ONLY

本记录冻结本轮升级范围和验证结果；当前维护规则见[仓库架构](../REPOSITORY_ARCHITECTURE.md#按任务读取与局部检索)，
日常入口见[README](../../README.md)。不保存第二套执行规范或项目资格。

## 范围与决策

代码与文档主题：`d53e0a777630aae85a1163e24a1eba36a3abc29a → 748d3fac91892abb01967e3192c2d09b6d57f84d`，
19个文件，225行新增、117行删除。工作树含其他Agent的科学实现与文档，不将其差异计入本主题。

- 开发标准保留原有规则正文及锚点，新增通用必读与条件专题路由；AGENTS和根README同步，不再强制每个小修复通读全部专题。
- 公共工具可直接进入对应规范与邻近测试，不要求不存在的PROJECT或新建占位文档。
- OA的12份活动文档共1638→1599行；理论按局部公式、整机耦合、条件控制等任务导航，实验要求归研究计划，当前阶段状态归证据矩阵。
- 补齐最低矩阵Source/Statistics；overlap审查空表改为明确待填写模板。未改数学公式、物理阈值、阶段门槛或冻结历史。
- 新增表格缺列、多列和空值审查信号；inventory增加字符数。该检查不推断语义冲突、不证明科学资格，也不将所有空值判为违规。
- integration两份混合文档的旧family指引与无时间基点工作树状态已在工作树收口；保留原工作流提交归属，不夹带其既有改动。
- MR PROJECT、SIMION及公共SIMION说明由原Agent唯一写入；独立审查推动旧装配表区分构建控制器与standalone飞行输入，Fast Adjust就地限定新staging，旧r172指令改为历史语气。科学运行与提交归其主题。

没有为按需阅读拆出新的活动说明文件；本次只新增这份历史验收记录，旧历史字节保持不动。

## 检索与渲染验收

独立Agent从入口模拟任务，第二轮检查以下答案及限制：

| 任务 | 结果 |
|---|---|
| 公共Markdown parser小修复 | 无PROJECT路由成立；开发标准通用章节加格式演进，范围扩大时再触发专题 |
| OA局部反射镜聚焦 | 可直接查组件定义、导数和适用域；整机声明须追加耦合，不要求先通读两篇统一框架 |
| 论文源与统计最低矩阵 | Source/Statistics可直接定位完整条件与WP1/WP6，不用空格猜测 |
| C3/C4进入资格 | 可找到C3独立参考缺口与C4阻塞条件；不将局部PASS升级为投稿或结构优越 |

公共parser任务实际准备路线为根启动231行、开发标准节选224行、操作节选62行，共517行；
不包含实际源码、测试及执行/提交时补读。开发标准原规则要求通读411行，当前该任务读取224行，
减少187行（45.5%）。这不是所有任务的统一阅读预算，也不表示整个文档体系缩短45.5%。
局部反射镜任务仍需较长定义与推导；项目README/PROJECT的固定启动成本仍存在，不能承诺零遗漏。

已用本地HTML渲染检查开发标准任务表、理论导航和论文最低矩阵，检查列完整、换行和可读性。
本地渲染器不等同GitHub，未宣称全仓数学渲染复验。三份临时HTML、临时目录、HTTP进程和浏览器标签已清理。

## 验证边界

| 检查 | 结果 |
|---|---|
| 文档解析回归 | 15项PASS，含5项新增表格检查 |
| 实验权威链规范合同 | 1项PASS |
| OA纵向理论与文档回归 | 7项PASS |
| Ruff、开发标准、差异格式 | PASS |
| StructureOnly | PASS；243份Markdown，本地链接错误0，表格审查信号0（新增本记录前） |
| L1改动范围门禁 | 23路径范围；卫生、文本、文档、开发标准、Ruff及15项文档回归PASS；OA/集成静态回归失败，见下文 |
| L2仓库集成 | 首次卫生阻断；第二次文档/其余fast阶段PASS，文本CR阻断完整回归；文本修复后最终复跑等待科学运行租约，未完成 |
| 商业求解器、GUI/CAD、Formal | 本文档任务未执行、不新增资格 |

初次卫生阻断对象是旧`artifacts/scratch/corrupt_pa_family_quarantine`，已由MR Agent保留全部字节迁入
合法项目scratch；后续受管文本检查发现集成既有JSON含CR，原OA工作流已保持内容不变规范为UTF-8 LF。
两项检查重跑均PASS。文档Agent没有删除他人故障证据、改变科学输入或放宽门禁。

L1随后执行的OA Static共366项，1 error、1 skip：粒子参数拒绝测试的Windows子进程stderr
不能按UTF-8解码，后续断言取得None。集成共883项，4 failures、1 error、3 skips：活动派生发布
不新鲜、run实现SHA绑定不同，以及运行器改动后的字符串/形状断言。失败落在并行工作流的实现、
依赖合同及既有测试，未通过更改科学配置或放宽断言来处理；已通知原工作流。顶层L1为FAIL，不能
被子脚本中较早打印的PASS覆盖。

最终L2复跑在公共租约等待超过210秒；持有者为MR Agent的8条真实中央差分campaign，原Agent确认
预计15–25分钟。文档Agent取消自己尚未取得租约的排队进程，没有中断科学运行。完整L2未通过，
也未将局部检查或既有文档结果当成其替代；后续相关科学门禁由原工作流在终态后执行。

## CLOC

通过仓库统一`common/report_cloc_delta.ps1`比较上述两个提交，CLOC 2.10；只比较提交快照，
不把并行工作树的代码计入。total代码286524→286612（+88），production +46，tests +42。
各表格元组依次为 **files / blank / comment / code**；delta是结果减基线，未分类文件为0。

| 分类 / language | 基线 | 结果 | delta |
|---|---|---|---|
| total / JSON | 480/0/0/47675 | 480/0/0/47675 | 0/0/0/0 |
| total / Lua | 89/415/575/8121 | 89/415/575/8121 | 0/0/0/0 |
| total / MATLAB | 110/964/2179/12888 | 110/964/2179/12888 | 0/0/0/0 |
| total / PowerShell | 133/962/928/34084 | 133/962/928/34084 | 0/0/0/0 |
| total / Python | 673/15924/6589/183362 | 673/15932/6594/183450 | 0/8/5/88 |
| total / SIMION GEM | 11/35/83/256 | 11/35/83/256 | 0/0/0/0 |
| total / TOML | 1/4/0/24 | 1/4/0/24 | 0/0/0/0 |
| total / YAML | 2/4/1/114 | 2/4/1/114 | 0/0/0/0 |
| total / SUM | 1499/18308/10355/286524 | 1499/18316/10360/286612 | 0/8/5/88 |
| production / JSON | 476/0/0/47565 | 476/0/0/47565 | 0/0/0/0 |
| production / Lua | 76/319/513/6659 | 76/319/513/6659 | 0/0/0/0 |
| production / MATLAB | 72/526/1661/9390 | 72/526/1661/9390 | 0/0/0/0 |
| production / PowerShell | 125/911/922/33144 | 125/911/922/33144 | 0/0/0/0 |
| production / Python | 367/10060/5223/109465 | 367/10063/5228/109511 | 0/3/5/46 |
| production / SIMION GEM | 11/35/83/256 | 11/35/83/256 | 0/0/0/0 |
| production / TOML | 1/4/0/24 | 1/4/0/24 | 0/0/0/0 |
| production / YAML | 2/4/1/114 | 2/4/1/114 | 0/0/0/0 |
| production / SUM | 1130/11859/8403/206617 | 1130/11862/8408/206663 | 0/3/5/46 |
| tests / JSON | 4/0/0/110 | 4/0/0/110 | 0/0/0/0 |
| tests / Lua | 13/96/62/1462 | 13/96/62/1462 | 0/0/0/0 |
| tests / MATLAB | 38/438/518/3498 | 38/438/518/3498 | 0/0/0/0 |
| tests / PowerShell | 8/51/6/940 | 8/51/6/940 | 0/0/0/0 |
| tests / Python | 306/5864/1366/73897 | 306/5869/1366/73939 | 0/5/0/42 |
| tests / SUM | 369/6449/1952/79907 | 369/6454/1952/79949 | 0/5/0/42 |
| unclassified / SUM | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 |

完整过滤口径及采样身份：

```text
CLOC_VERSION=2.10
CLASSIFIER_SHA256=db9ed262601aa58092558467e9652fcc82c3787383e283c356973142e535809a
LANGUAGE_DEFINITION_SHA256=985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6
INPUT_IDENTITY SNAPSHOT=baseline FILES=1499 SHA256=57f7b6932603f3052776ca84cd5e189952faebc91e48bfa8c6e99198fe01914a
INPUT_IDENTITY SNAPSHOT=result FILES=1499 SHA256=88207fa3f9e3525e4fbacc20fc4c0801078089fa7cceee7cf37d8137c95771fd
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```
