# Handoff对照诊断覆盖修复

<!-- DOC_STATUS: ARCHIVED_READ_ONLY -->

> 只读源码验证里程碑；当前状态见 [INTEGRATION.md](../INTEGRATION.md)。

## 范围与验证

修复比较器的稀疏母群ID检查及跨IOB原生槽号比较，Program build receipt从实际生成布局发布角色图。
两侧canonical checkpoint表提供完整检测ID集合和逐粒到达时间/落点差；不重新从solver-local时间推导epoch。
PASS仅涵盖脉冲状态及离散结局，轨迹数值等价因缺少轨迹误差预算明确未评估。没有共同检测峰形筛选。
缺少角色图的旧receipt不能猜测、回写或获得新资格。未运行新求解器，未改变电压、PA或冻结粒子状态。

主Agent重跑handoff比较器及Program测试：45项通过（1.091s）；实现Agent四文件Ruff通过。
绑定编译器只刷新一份派生implementation文件；文档门禁通过。实际连续N=5000对照仍未完成，
本里程碑不是handoff误差、轨迹收敛或Formal证据。无临时代码，无删除，无提交。

## CLOC快照

统一入口`common/report_cloc_delta.ps1`，CLOC 2.10，2026-09-04T10:49:39Z。
基线`842228787b86b526c7137b7a45ef5d35113a73f9` → `WORKTREE`（HEAD同基线）。
这是整个混合worktree的快照，不是本次修复独占增量；204个tracked dirty、119个untracked，unclassified为0。
每格四元组依次为 **files / blank / comment / code**。

|分类/语言|baseline|result|delta|
|---|---|---|---|
|total JSON|455/0/0/42649|463/0/0/45356|8/0/0/2707|
|total Lua|54/319/323/5493|72/350/458/6631|18/31/135/1138|
|total MATLAB|106/963/2237/12507|107/939/2157/12407|1/-24/-80/-100|
|total PowerShell|106/816/756/29443|107/822/866/30036|1/6/110/593|
|total Python|539/12814/4730/149280|602/14142/5570/163066|63/1328/840/13786|
|total SIMION GEM|10/35/81/246|11/35/83/256|1/0/2/10|
|total TOML|1/4/0/24|1/4/0/24|0/0/0/0|
|total YAML|2/4/1/114|2/4/1/114|0/0/0/0|
|total SUM|1273/14955/8128/239756|1365/16296/9135/257890|92/1341/1007/18134|
|production JSON|451/0/0/42539|459/0/0/45246|8/0/0/2707|
|production Lua|46/226/302/4509|60/254/401/5270|14/28/99/761|
|production MATLAB|68/504/1685/8852|70/503/1640/8933|2/-1/-45/81|
|production PowerShell|98/767/750/28590|99/773/860/29180|1/6/110/590|
|production Python|293/7989/3769/87596|330/8881/4462/96278|37/892/693/8682|
|production SIMION GEM|10/35/81/246|11/35/83/256|1/0/2/10|
|production TOML|1/4/0/24|1/4/0/24|0/0/0/0|
|production YAML|2/4/1/114|2/4/1/114|0/0/0/0|
|production SUM|969/9529/6588/172470|1032/10454/7447/185301|63/925/859/12831|
|tests JSON|4/0/0/110|4/0/0/110|0/0/0/0|
|tests Lua|8/93/21/984|12/96/57/1361|4/3/36/377|
|tests MATLAB|38/459/552/3655|37/436/517/3474|-1/-23/-35/-181|
|tests PowerShell|8/49/6/853|8/49/6/856|0/0/0/3|
|tests Python|246/4825/961/61684|272/5261/1108/66788|26/436/147/5104|
|tests SUM|304/5426/1540/67286|333/5842/1688/72589|29/416/148/5303|

完整过滤口径（统一入口原样）：

```text
extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```
