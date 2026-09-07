# Post-pulse 脉宽 N=1 阶段复验

<!-- DOC_STATUS: ARCHIVED_READ_ONLY -->

> 只读历史记录：2026-09-04 阶段快照，不覆盖当前 INTEGRATION.md，不代表物理链或 Formal 验收完成。

## 对象与结论

同一冻结 ID 46、方形 300 mm 加速器、1×1 mm 入口、102.4 mm gap，同一 PA cache。
只改变脉宽策略；均从相同 pre-pulse 状态及 instrument time 81.11363636363636 us 启动。

|真实 run（integration runs 根下）|脉宽 us|出口能量 eV|探测器|
|---|---:|---:|---:|
|20260904_105816__sim__simion__rf-oatof-single-flight-gap102p4__n1|1|525.855970|0/1|
|20260904_111538__sim__simion__rf-oatof-single-flight-gap102p4__n1|6.6887563539020105|1998.853677|0/1|

全部冻结 restart 行独立 z/vz/mass/charge 经现有三区公式计算到设计 focus 平面的最长时间，不拟合
z–vz、不使用 detector 结果，作者宽度为不缩短的下限。理想出口时间5.998658317204204 us、
理想出口总能量1998.853533 eV；真实出口时间5.9638752821 us。脉宽修正恢复出口能量，但非全链通过。

新 run 的 zmax=278.142127396 mm，出口 z=278.070813196589 mm，main PA 下游边界
z=278.270813196589 mm：粒子在主 PA 内、出口后约0.0713 mm折返，尚未进入飞行管。
最终撞 main repeller，分类 non_detector_splat_instance_3。原因未关闭，N=5000未启动。
SIMION自然完成28.934 s，波次总耗时29.988 s，无refine；终态容量检查PASS，496.66 GiB，无删除；
共享租约已释放。之前的准备尝试20260904_111446因局部变量覆盖adapter mapping失败，未启动求解器；
已使用独立变量名修正，后继真实运行越过该点。

## 只读 PA 抽查

按本机SIMION 2020 `lib/python/SIMION/PA.py`的load/point格式稀疏seek少数节点，不加载整个PA或修改cache。
依据：[官方Field I/O](https://simion.com/info/field_io.html)（2026-09-04查阅，其SL/file-format能力适用于2020）。
官方Python读取器会全量分配，本次仅复用其32/56字节头、节点偏移及电极标记解码规则；不是新的生产解析器。

main cache d4b86d5cf1fbc5ea1702720dff55b3526ecb5cd670d75381f15cbc321926df91，generation
435b2b4f0c39381e20496738f47398268264cc69d8c98cdefc96ba6ef3975f42：在接近出口轨迹的ix=203、iy=220，
出口后pa44/45/46的解电势近0，pa47约10000 V但运行V_exit=0。最外层原pa#、pa_标记非电极，
pa44–49因Dirichlet写入标记电极。提示检查controller/basis电极掩码一致性，但未通过原生fast-adjust
点查询证实它是反弹原因；不能据此擅自清除或重建PA。

## 验证与责任

Agent 0负责实现、集成与真实复验，Agent 1负责独立物理/合同审查及解析测试。
17项后继/布局测试、6项独立解析测试通过，Ruff及diff检查通过。真实运行通过准备、商业执行、发布、
终态容量阶段，但物理出口异常未关闭。未做GUI/CAD、完整八案例或Formal验证。既有全仓L2文档门禁
仍有无关历史banner失败，未宣称全仓通过。无提交或推送，连续故障链留在worktree。

## CLOC 快照

842228787b86b526c7137b7a45ef5d35113a73f9 → WORKTREE；CLOC 2.10，2026-09-04T03:16:14Z。
范围是全部dirty worktree，不是本次独占增量。四元组为files/blank/comment/code，unclassified均为0。

|类别/语言|基线|结果|delta|
|---|---|---|---|
|total JSON|455/0/0/42649|461/0/0/44760|6/0/0/2111|
|total Lua|54/319/323/5493|71/348/446/6559|17/29/123/1066|
|total MATLAB|106/963/2237/12507|107/939/2157/12407|1/-24/-80/-100|
|total PowerShell|106/816/756/29443|107/822/857/29979|1/6/101/536|
|total Python|539/12814/4730/149280|598/13931/5454/159302|59/1117/724/10022|
|total GEM|10/35/81/246|11/35/83/256|1/0/2/10|
|total TOML|1/4/0/24|1/4/0/24|0/0/0/0|
|total YAML|2/4/1/114|2/4/1/114|0/0/0/0|
|total SUM|1273/14955/8128/239756|1358/16083/8998/253401|85/1128/870/13645|
|production JSON|451/0/0/42539|457/0/0/44650|6/0/0/2111|
|production Lua|46/226/302/4509|59/253/394/5218|13/27/92/709|
|production MATLAB|68/504/1685/8852|70/503/1640/8933|2/-1/-45/81|
|production PowerShell|98/767/750/28590|99/773/851/29123|1/6/101/533|
|production Python|293/7989/3769/87596|330/8788/4363/94409|37/799/594/6813|
|production GEM|10/35/81/246|11/35/83/256|1/0/2/10|
|production TOML|1/4/0/24|1/4/0/24|0/0/0/0|
|production YAML|2/4/1/114|2/4/1/114|0/0/0/0|
|production SUM|969/9529/6588/172470|1029/10360/7332/182727|60/831/744/10257|
|tests JSON|4/0/0/110|4/0/0/110|0/0/0/0|
|tests Lua|8/93/21/984|12/95/52/1341|4/2/31/357|
|tests MATLAB|38/459/552/3655|37/436/517/3474|-1/-23/-35/-181|
|tests PowerShell|8/49/6/853|8/49/6/856|0/0/0/3|
|tests Python|246/4825/961/61684|268/5143/1091/64893|22/318/130/3209|
|tests SUM|304/5426/1540/67286|329/5723/1666/70674|25/297/126/3388|

完整过滤口径（common/report_cloc_delta.ps1）：

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
