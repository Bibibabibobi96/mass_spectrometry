# Campaign只读审阅与执行授权门禁修复

<!-- DOC_STATUS: ARCHIVED_READ_ONLY -->

> 2026-09-04源码验证里程碑；当前状态见 [INTEGRATION.md](../INTEGRATION.md)。

## 修复与证据

此前完整集成门禁813项中3项失败，原因是exploration被误列活动注册，以及只读semantic diff过早进入执行授权检查。
移除误注册但保留探索文件与状态；仓库内非活动campaign可只读比较，仓库外派生输入与混合执行模式仍被拒绝。
执行和ValidateOnly仍遵循生命周期/显式探索准入，不恢复历史运行授权。

Agent 3的两个完整模块47项通过，专项2项通过、Ruff与PowerShell解析通过。
Agent 0重跑公开集成门禁：813项、170.222s，OK（3项跳过），Ruff通过；共享GATE租约正常释放。
绑定新鲜度与diff检查通过。本轮没有启动SIMION、refine、改变粒子或电压，没有删除产物，没有提交。
连续N=5000对照和圆形四臂仍未完成，源码回归不是handoff轨迹等价或Formal证据。

## CLOC快照

CLOC 2.10，统一入口 common/report_cloc_delta.ps1，时间2026-09-04T11:03:08Z。
基线842228787b86b526c7137b7a45ef5d35113a73f9 → WORKTREE（HEAD同基线）。
这是整个混合worktree快照，不是本轮独占增量；204 tracked dirty、120 untracked，unclassified为0。
每格为 files / blank / comment / code。

|分类/语言|baseline|result|delta|
|---|---|---|---|
|total JSON|455/0/0/42649|463/0/0/45353|8/0/0/2704|
|total Lua|54/319/323/5493|72/350/458/6631|18/31/135/1138|
|total MATLAB|106/963/2237/12507|107/939/2157/12407|1/-24/-80/-100|
|total PowerShell|106/816/756/29443|107/822/866/30033|1/6/110/590|
|total Python|539/12814/4730/149280|602/14142/5570/163100|63/1328/840/13820|
|total SIMION GEM|10/35/81/246|11/35/83/256|1/0/2/10|
|total TOML|1/4/0/24|1/4/0/24|0/0/0/0|
|total YAML|2/4/1/114|2/4/1/114|0/0/0/0|
|total SUM|1273/14955/8128/239756|1365/16296/9135/257918|92/1341/1007/18162|
|production JSON|451/0/0/42539|459/0/0/45243|8/0/0/2704|
|production Lua|46/226/302/4509|60/254/401/5270|14/28/99/761|
|production MATLAB|68/504/1685/8852|70/503/1640/8933|2/-1/-45/81|
|production PowerShell|98/767/750/28590|99/773/860/29177|1/6/110/587|
|production Python|293/7989/3769/87596|330/8881/4462/96278|37/892/693/8682|
|production SIMION GEM|10/35/81/246|11/35/83/256|1/0/2/10|
|production TOML|1/4/0/24|1/4/0/24|0/0/0/0|
|production YAML|2/4/1/114|2/4/1/114|0/0/0/0|
|production SUM|969/9529/6588/172470|1032/10454/7447/185295|63/925/859/12825|
|tests JSON|4/0/0/110|4/0/0/110|0/0/0/0|
|tests Lua|8/93/21/984|12/96/57/1361|4/3/36/377|
|tests MATLAB|38/459/552/3655|37/436/517/3474|-1/-23/-35/-181|
|tests PowerShell|8/49/6/853|8/49/6/856|0/0/0/3|
|tests Python|246/4825/961/61684|272/5261/1108/66822|26/436/147/5138|
|tests SUM|304/5426/1540/67286|333/5842/1688/72623|29/416/148/5337|

完整过滤口径：

```text
extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```
