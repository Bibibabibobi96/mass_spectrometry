# PA+ 边界标记修复与同源复验

DOC_STATUS: ARCHIVED_READ_ONLY

只读历史快照；2026-09-04 阶段证据，不构成 N=5000、GUI/CAD 或 Formal 资格。

## 根因与修复范围

原始几何的非电极外边界被 Dirichlet basis 构建器设成电极，以固定求解边界；这些合成标记在
refine 后仍留在 PA+ mode 内，而原控制器没有相同标记。原生组合场查询确认出口后出现虚假势垒。
运行器在普通复制 cache family 后，以原 pa# 为几何权威，清除六个不重叠边界面上的合成标记；
真实电极保持不变。使用 SIMION2020 官方 electrode setter，不写电势、不 refine、不修改 cache。
post-pulse 处理实际六 mode，完整带场链处理其合同 mode；零场 pre-pulse 跳过。

官方依据：SIMION2020 安装目录 examples/magnetic_potential/current_sphere_3dp.lua 的
pa:electrode(x,y,z,e)，及 lib/cpp/simion/pa.h 的 electrode setter（保留 decoded potential）；
2026-09-04 由 Agent 0/1 核验。它是基于官方接口的项目修复，不称为官方推荐算法。

首次接入 run 20260904_114814 在主域修复完成后，因第二域重复冻结同名 Lua 而失败；
现已改为本 run 只冻结一次脚本，并增加回归。失败 run 保留来源与日志，未覆盖。

## 受控对照

|项目|修复前|修复后|
|---|---|---|
|独立场 run|20260904_114100|20260904_115108|
|完整 run 后缀|__sim__simion__rf-oatof-single-flight-gap102p4__n1|相同|
|出口轴线电势|0 V|0 V|
|出口后 0.1 mm 电势|7314.94475291373 V|−7.93414551394942e−68 V|
|3001 点内部轴线 CSV|参考|文件逐字节相同，potential/Ex/Ey/Ez 最大差均 0|
|导出终态|最外节点查询未定义而失败|成功；仅采严格位于 PA 内部的节点|

主域每 mode 清除 4,024,915 个标记，六 mode 共耗时40.252 s；入口局部域每 mode 清除25,385个，
六 mode 共0.674 s。两份 restoration receipt 均 PASS。辅助资源记录仍写 running，不能据此
判断真实进程状态；耗时只取其计时字段，成功依据 solver 退出、receipt、导出及终态manifest。
这一对照证明已采样内部轴线保持不变，不外推为全空间字节相同。

## 同源 N=1 飞行

run：20260904_115435__sim__simion__rf-oatof-single-flight-gap102p4__n1。
保持 ID46、源六维状态、质量电荷、几何、电压、网格和6.6887563539020105 us脉宽不变。
该粒子由 frozen compact handoff 重启，未换成命中样本。

|事件|instrument time/us|结果|
|---|---:|---|
|加速器出口|87.0775116457|1998.853677458549 eV，正常穿越|
|加速器焦面|87.7678746687|正常前向穿越|
|反射器入口|92.2771936071|z=600 mm|
|反射器折返点|97.8324421795|z=751.243098525 mm|
|反射器返回出口|103.387689917|x=73.4541、y=73.4397 mm；vy=+2.35885 mm/us|
|最终损失|113.917410182|飞行管端壁，x=118.6052、y=98.2777、z=−51.9292 mm|

探测器命中0/1；出口虚假反弹解除，但该粒子横向漂移后错过探测器。不能称为探测器命中贯通，
更不能计算单粒子分辨率或据此推断5000母群效率。实际批飞行30.91 s，波次31.967 s；
资源总计31.968 s、峰值17,339,772,928 bytes。所有PA复用、无refine。终态容量496.68 GiB，
未删除cache，主机租约释放。下一步保留该负结果，检查完整方形母群与已有handoff，不能挑选共同命中群。

## 回归与提交

86项 boundary mask、domain-split runner、Program、派生后继/pulse duration测试联合通过。
新增mask文件的Ruff及git diff --check通过。Agent 1独立核验场CSV与修改范围。
未进行本轮全仓L2、GUI/CAD或N=5000；未提交，整个物理链与统计目标仍未完成。
本轮文档门禁已运行，仓库卫生通过；唯一失败是另一项目既有
projects/orthogonal_accelerator/docs/history/20260903__legacy-accelerator-diagnostic.md
缺少归档标记。没有修改该无关文件；本轮新增history均已加DOC_STATUS标记并登记索引。

## CLOC

BASELINE=842228787b86b526c7137b7a45ef5d35113a73f9 → WORKTREE，CLOC 2.10；
CREATED_UTC=2026-09-04T03:56:09.3194318+00:00。共享工作树整体快照，不能归因于本次修复。
每格为 baseline→result（delta）。

|分类/语言|files|blank|comment|code|
|---|---|---|---|---|
|total/JSON|455→461 (+6)|0→0 (0)|0→0 (0)|42649→44760 (+2111)|
|total/Lua|54→72 (+18)|319→348 (+29)|323→450 (+127)|5493→6606 (+1113)|
|total/MATLAB|106→107 (+1)|963→939 (-24)|2237→2157 (-80)|12507→12407 (-100)|
|total/PowerShell|106→107 (+1)|816→822 (+6)|756→860 (+104)|29443→30008 (+565)|
|total/Python|539→599 (+60)|12814→13946 (+1132)|4730→5464 (+734)|149280→159416 (+10136)|
|total/SIMION GEM|10→11 (+1)|35→35 (0)|81→83 (+2)|246→256 (+10)|
|total/TOML|1→1 (0)|4→4 (0)|0→0 (0)|24→24 (0)|
|total/YAML|2→2 (0)|4→4 (0)|1→1 (0)|114→114 (0)|
|total/SUM|1273→1360 (+87)|14955→16098 (+1143)|8128→9015 (+887)|239756→253591 (+13835)|
|production/JSON|451→457 (+6)|0→0 (0)|0→0 (0)|42539→44650 (+2111)|
|production/Lua|46→60 (+14)|226→253 (+27)|302→398 (+96)|4509→5265 (+756)|
|production/MATLAB|68→70 (+2)|504→503 (-1)|1685→1640 (-45)|8852→8933 (+81)|
|production/PowerShell|98→99 (+1)|767→773 (+6)|750→854 (+104)|28590→29152 (+562)|
|production/Python|293→330 (+37)|7989→8788 (+799)|3769→4372 (+603)|87596→94419 (+6823)|
|production/SIMION GEM|10→11 (+1)|35→35 (0)|81→83 (+2)|246→256 (+10)|
|production/TOML|1→1 (0)|4→4 (0)|0→0 (0)|24→24 (0)|
|production/YAML|2→2 (0)|4→4 (0)|1→1 (0)|114→114 (0)|
|production/SUM|969→1030 (+61)|9529→10360 (+831)|6588→7348 (+760)|172470→182813 (+10343)|
|tests/JSON|4→4 (0)|0→0 (0)|0→0 (0)|110→110 (0)|
|tests/Lua|8→12 (+4)|93→95 (+2)|21→52 (+31)|984→1341 (+357)|
|tests/MATLAB|38→37 (-1)|459→436 (-23)|552→517 (-35)|3655→3474 (-181)|
|tests/PowerShell|8→8 (0)|49→49 (0)|6→6 (0)|853→856 (+3)|
|tests/Python|246→269 (+23)|4825→5158 (+333)|961→1092 (+131)|61684→64997 (+3313)|
|tests/SUM|304→330 (+26)|5426→5738 (+312)|1540→1667 (+127)|67286→70778 (+3492)|

完整过滤口径：
```text
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```
