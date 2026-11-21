# 出口场导出回归

DOC_STATUS: ARCHIVED_READ_ONLY

只读历史快照；记录 2026-09-04 的阶段检查，不代表物理链已完成。

## 范围与结果

Agent 0 修改后继 campaign 发布入口以选择已有 field-export 模式，保持默认粒子飞行；
修复 PA+ 六 mode 导出混入 physical rod IDs 的错误，并在理论 CSV 之外记录出口边界电势。
Agent 1 只读复核本机 SIMION2020 `simion.chm` 的 instance potential/field API：带电压表的
查询受支持，旧 `_wc` 名称仍兼容；不能将先前 nil 归因为 Fly 回调限制。
不修改 PA 缓存、几何、电压、源或 refine 精度。37 项 focused unittest 与相关 Python Ruff 通过。
这些测试不证明异常反弹已修复，也不构成 N=5000、GUI/CAD 或 Formal 验收。

真实诊断 run `20260904_114100__sim__simion__rf-oatof-single-flight-gap102p4__n1`
经公共入口和共享租约执行，复用 PA，无 refine。`logs/total_axis_field.stdout.log` 记录全部
3001 个理论区间点，出口 z=278.070813197 mm 为 0 V，下一格 z=278.170813197 mm
为 7314.94475291373 V。最外层节点 potential 未定义导致原生脚本退出失败，终态与失败证据
照实发布；终态容量 496.67 GiB、未删除 cache、租约释放。中心轴跳变直接证明存在异常势垒，
但尚未完成去除合成边界 electrode flags 的因果对照，不能宣称根因修复。
后续导出只查询严格位于 PA 内的节点，不再把最外层 API 开区间边界当作物理失败；该小改动仅静态回归。

## CLOC

`842228787b86b526c7137b7a45ef5d35113a73f9 → WORKTREE`，CLOC 2.10，
2026-09-04T03:44:19Z。这是共享工作树整体变化，包含其他主题，不能归因于本次修复。
每格为 baseline → result（delta），列依次为 files、blank、comment、code。

|分类/语言|files|blank|comment|code|
|---|---|---|---|---|
|total/JSON|455→461 (+6)|0→0 (0)|0→0 (0)|42649→44760 (+2111)|
|total/Lua|54→71 (+17)|319→348 (+29)|323→446 (+123)|5493→6559 (+1066)|
|total/MATLAB|106→107 (+1)|963→939 (-24)|2237→2157 (-80)|12507→12407 (-100)|
|total/PowerShell|106→107 (+1)|816→822 (+6)|756→857 (+101)|29443→29979 (+536)|
|total/Python|539→598 (+59)|12814→13931 (+1117)|4730→5463 (+733)|149280→159330 (+10050)|
|total/GEM|10→11 (+1)|35→35 (0)|81→83 (+2)|246→256 (+10)|
|total/TOML|1→1 (0)|4→4 (0)|0→0 (0)|24→24 (0)|
|total/YAML|2→2 (0)|4→4 (0)|1→1 (0)|114→114 (0)|
|total/SUM|1273→1358 (+85)|14955→16083 (+1128)|8128→9007 (+879)|239756→253429 (+13673)|
|production/JSON|451→457 (+6)|0→0 (0)|0→0 (0)|42539→44650 (+2111)|
|production/Lua|46→59 (+13)|226→253 (+27)|302→394 (+92)|4509→5218 (+709)|
|production/MATLAB|68→70 (+2)|504→503 (-1)|1685→1640 (-45)|8852→8933 (+81)|
|production/PowerShell|98→99 (+1)|767→773 (+6)|750→851 (+101)|28590→29123 (+533)|
|production/Python|293→330 (+37)|7989→8788 (+799)|3769→4372 (+603)|87596→94419 (+6823)|
|production/GEM|10→11 (+1)|35→35 (0)|81→83 (+2)|246→256 (+10)|
|production/TOML|1→1 (0)|4→4 (0)|0→0 (0)|24→24 (0)|
|production/YAML|2→2 (0)|4→4 (0)|1→1 (0)|114→114 (0)|
|production/SUM|969→1029 (+60)|9529→10360 (+831)|6588→7341 (+753)|172470→182737 (+10267)|
|tests/JSON|4→4 (0)|0→0 (0)|0→0 (0)|110→110 (0)|
|tests/Lua|8→12 (+4)|93→95 (+2)|21→52 (+31)|984→1341 (+357)|
|tests/MATLAB|38→37 (-1)|459→436 (-23)|552→517 (-35)|3655→3474 (-181)|
|tests/PowerShell|8→8 (0)|49→49 (0)|6→6 (0)|853→856 (+3)|
|tests/Python|246→268 (+22)|4825→5143 (+318)|961→1091 (+130)|61684→64911 (+3227)|
|tests/SUM|304→329 (+25)|5426→5723 (+297)|1540→1666 (+126)|67286→70692 (+3406)|

完整过滤口径：extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd；
excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs；
excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/project/(archive|scratch)/**；
language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM；
production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named)；
tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|*Test.m|*.Tests.*；
unclassified=other_code_below_test_or_tests_path（本次 0）；worktree_source=git_tracked_plus_nonignored_untracked。
