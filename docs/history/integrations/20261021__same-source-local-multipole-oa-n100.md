# 同源裸八极杆接二区／三区 OA 的 N=100 与默认加载闭合

DOC_STATUS: ARCHIVED_READ_ONLY

本记录冻结 2026-10-21 已闭合的局部功能链。活动入口和资格以后以
[INTEGRATION](../INTEGRATION.md)及[RUNNING](../RUNNING.md)为准。本轮没有操作 GUI，也没有启动
MRTOF 或反射器联合模拟；默认文件一致性通过新进程原生 Fly 核验。

## 对象、身份与交付入口

两方案复用既有 OA 提供者、方孔离散与拓扑核验、RF／脉冲 Program、PA 缓存和公共资源调度器。
科学输入由同一公开 `family_source_closure/execute.ps1 -FrontendRequest` 编译；局部实现不另立用户 CLI。
孔边不在网格上仍产生 warning，不自动吸附或修改机械几何。粒子与全部运行几何直接使用
`mrtof_global_cartesian`：导引 +y、引出 -z，观察变换为单位阵。

以下 run 均位于外层 `artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/`。
表中的短称仅用于本记录，不能替代冻结 request、profile 与场身份。

| 短称 | 提供者／profile | 成功原生 run |
|---|---|---|
| 二区 | `two_zone` / `closed_two_zone_compact_mr_axial_r3_gap1_4mm` | `20261021_134223__sim__simion__local-bare-guide-oa` |
| 三区 | `three_zone` / `explicit_functional_sectioned_square_4_15_15_bare_three_zone_v1` | `20261021_160146__sim__simion__local-bare-guide-oa` |

主交接为[完整报告](../../../../../artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20261021_165805__analysis__python__local-oa-design-comparison/results/scientific_report.md)，
内含两套直接加载 IOB、检查面相空间、共同时间空间图、损失表和原始日志链接。
分别加载上述原生 run 下的 `simion/extraction/gui_full_population/local.iob`，保留整个 run 及其
相邻 Program、FLY、PA；不要用另一方案或后来生成的 Program 覆盖冻结文件。

两个原生 manifest 分别为 success/full（483／471 项输出）；三区 manifest SHA-256 为
`33898D2D8ADEA10630D910E690AF565E79A074FB0769EDC3F095759203E3F334`。
独立对照 run `20261021_165805__analysis__python__local-oa-design-comparison` 为 success/full（31 项输出），
manifest SHA-256 为 `EBF05633B22E0D6C65C29F26A45C6701B974AEEEF5214D558761E0DEEBAE8073`。
对照分析前后 128 个源文件身份稳定，实际导入的绘图源码也已冻结；原始运行没有被重画结果覆盖。

## 冻结物理与数值条件

母群来自 IP 的 `20261020_104000__sim__simion__electrode-geometry-d-n100` 原始出生表，全部 100 个 ID、
质量、电荷、出生时钟及六维状态保留，没有选择 IP 出口幸存者或重采样。524 Da、+1，圆柱半径 1 mm、
全高 5 mm，正值纵向高斯能量参数 5±1 eV，横向 300 K。释放文件 SHA-256 为
`1ADE990A5B2409E5DE9F9A8A33334D186B3B9E6879CD9ADF058236E4AE0AFEB6`。

裸八极杆长 29 mm，内切半径 2 mm，圆杆半径 0.6 mm；3.7 MHz、每极 ±500 V cos 驱动、DC=0、
相位 0，导引真空 0 Pa。IP 原生源转换为 MR 坐标 `[-z,x,-y]+[0,-97,32] mm`；杆出口
`[0,-68,32] mm`，到 OA 孔壁的机械间隙 1 mm。侧孔 3×2.8 mm，中心 `[0,-66.5,32] mm`，
孔壁 y=-67…-66 mm。该孔径只代表本功能性工况，未证明最优接受度。

两者 repeller/grid1/exit 均在 z=34/30/0 mm，ON 电压分别为
4749.074377093093/3994.946318498907/0 V；OFF=0 V、导引 RF 连续。三区增加 z=15 mm 的中间面，
电压 1997.4731592494536 V。环电位由各方案实际位置上的线性压降生成。

| 几何或离散条件 | 二区 | 三区 |
|---|---:|---:|
| 加速区长（mm） | 4+30 | 4+15+15 |
| 屏蔽 x 外宽（mm） | 44 | 34 |
| 环厚（mm） | 1 | 0.5 |
| 开口（mm） | 25×26 | 26×26 |
| 环与中间面 | 15 个环 | 14 个环及中间面 |
| 侧孔边界语义 | inside_only | inside_or_on |
| 实际贯通孔节点／候选 | 783/899 | 899/899 |
| PA 网格节点数 | 443×331×388 | 343×331×383 |
| 单位响应模式 | 5 | 6 |

两者 x/z 网格 0.1 mm、y 网格 0.2 mm，官方 Refine，Q=8、最大步长 0.0005 µs、每 RF 周期 64 步
限制、最大年龄 200 µs、轨迹间隔 0.05 µs。采用理想零厚可穿越栅面，不能把结果解释为实际丝网透过率。
不同支撑、屏蔽和孔边界使本次不是“仅改变区数”的单变量对照，也没有网格或时间步收敛结论。

两次成功运行均命中完整校验的公共场缓存。三区缓存 key 为
`3CFD9E448429C40AA40EB5BB3FB32FE646D022775974F694A17E3FC61B341834`，generation 为
`4BAF18719269099AF0E359CEC9E0CC6C746A0CEDF58D6918F8B00B480EAC6335`；最终运行不再 Refine。

## N=100 与默认加载结果

discovery 自动选择脉冲时刻后，extraction 继续全部 100 个出生 ID。捕获框人数只用于时刻诊断，
没有删去框外离子。二区／三区脉冲时刻为 28.401608250996254／27.793500142888146 µs，框内 72／83。
公共自动调度保留 1.05 CPU 需求因子；二区自动上限 14，三区 discovery／extraction 上限 14／13。
三区首批实测 CPU 6.25%／6.888%，按 6.5625%／7.2324% 需求预算调度，而非固定单路。

统计平面是 z=0 首次沿 -z 穿越；σ 均为 ddof=0。角度定义为
θx=atan2(vx,|vz|)、θy=atan2(vy,|vz|)，均值与分散分别计算。

| 各自出口条件群 | 二区 | 三区 |
|---|---:|---:|
| 出口／母群 | 70/100 | 66/100 |
| native_stop_unresolved／超时 | 30/0 | 34/0 |
| σx／σy（mm） | 1.702776／3.734962 | 1.730299／3.538753 |
| θx／θy 均值（°） | 0.020533／1.583714 | 0.015271／1.456077 |
| σθx／σθy（°） | 0.239963／0.980397 | 0.274469／1.096548 |
| σt（ns） | 19.049654 | 18.007098 |
| 总能量均值±SD（eV） | 4303.804791±202.106750 | 4276.735007±216.163274 |

共同出口 62 个 ID 的配对表单独保存，不替代上述母群收集率：

| 共同 ID 条件群 | 二区 | 三区 |
|---|---:|---:|
| σx／σy（mm） | 1.779771／3.146998 | 1.689044／3.548489 |
| σθx／σθy（°） | 0.248476／0.467581 | 0.265887／1.122154 |
| σt（ns） | 15.014281 | 16.606567 |

三区各自出口群 σt 较小，但共同 ID 群 σt 增大，不能宣称三区聚焦更好。源／孔面按 +y 定义角分量，
与出口 -z 角分量也不能直接作改善百分比。grid1 首次过面包含脉冲前事件，检查面 σt 曲线不单独证明
时间聚焦；本轮没有给出 MRTOF 接受度或分辨率资格。

两套保存文件分别由新进程仅执行 `--nogui --noprompt fly local.iob`，无 Program／Q 覆盖。
100 个原始 ID 的 61,816／61,502 个 canonical 数值事件逐值一致，控制文件前后不变、差异字段 0。
这证明保存默认配置与调度飞行一致；GUI 人工验收由用户完成，本轮不代替该验收。

## 诊断完整性与已关闭缺陷

所有损失仍保留原生分类；`native_stop_unresolved` 尚未逐离子区分电极、束团接受度或数值成因。
独立对照保存 264 行损失证据（discovery 200、extraction 64），含原行、时间、位置、原日志来源及 SHA；
discovery 无引出脉冲的自然停止不能作为 extraction 损失率。136 行出口六维状态、18 行快照标记及
4 行域外查询与终态关联分别保留，不能将诊断空缺算成额外损失。

二区 6.25 µs 的 12 个旧样点比请求时刻早 47 ULP，旧 producer 相对 epsilon 判据与 consumer 真实
32 ULP 不同；原 Program、标记和回放证据保留。三区新 producer 已使用真实 32 ULP，2,345 个已发出
共享事件全部合格，但 ID16／ID36 在最后域内轨迹至真实 instance=0 终态之间有 6 次未采集快照。
这些区域没有补造位置或放宽容差。两类缺口的逐项时钟、原行和身份见独立报告。

本次自动空间图选择 4 个有记录的存活时刻及首个完整终态；仍保留全部时间／ID CSV。
通用规则最多显示 5 列，有完整终态时为它预留一列，没有完整终态时可显示 5 个存活时刻。
绘图按经过严格时钟验证的 requested_time 分组，不要求有效样点的实际浮点时刻逐位相等。
图区人数校验不变。独立对照从封存 CSV 重画两套空间图，原图未覆盖；未来运行自动使用新选择器。
二区检查面坐标修正的有效图来自 `20261021_141617__analysis__python__extraction-clock-review`，
交接报告直接链接此图，不使用原运行中错误传播轴的旧检查面图。

三区失败链保持各自身份，没有把中间运行发布为成功：

| 运行时间身份（均为 20261021） | 原因与关闭证据 |
|---|---|
| 142113 原生失败 | 域外 field_vc 导致批次异常；使用实际 wb_to_pa_coords 和 inside_vc 检查，查询标记不冒充接受轨迹或损失 |
| 150849 分析失败 | 全部 N=100 原生完成，但科学出口与即时数值停止的终态时钟不一致，另漏记 PA 外终态；严格分析拒绝而未放宽容差 |
| 153836 N1 / 154823 N2 | 原生探针确认即时 ion_splat 会回到上一接受端点；将数值停止置于已有 PA 余量中点，科学 z=0 状态三联插值不变。原 ID1 科学出口 9 字段逐值相同，真实终态延后 1.155360 ns；ID16 全局 terminate 原样记录自然终态 |
| 160146 完整 N=100 | 重过全部修复点，完整分析、默认全母群回放与 manifest 验证成功 |

原生机制采用 SIMION 2020 官方 `sim_segment_global=1`，域外 tstep／other_actions 不查询场，
terminate 保存实际 instance=0 终态。依据查阅于 2026-10-21 的本机官方
`C:/Program Files/SIMION-2020/docs/simion.chm`：`lua_simion.pas.html` 的 inside_vc／field_vc、
`lua_simion.wb.html` 的 wb_to_pa_coords、`workbench_program_extensions.html` 的全局分段扩展及
官方 dielectric/resistive 示例。CHM SHA-256 为
`02E2C122664FB93D11DE669B9900686601C9AB59FA992D66F10A5EE209810055`。
数值停止与插值诊断是基于官方 API 的项目实现，不称为官方推荐物理算法。

## 软件检查、保留和限制

精确主题门禁 `20261021_134524__gate__repo__exact-multipole-oa-topic` 保留原始失败：21 阶段中
15 PASS、6 FAIL。既有 MR refine-policy/allowlist 不匹配在基线同样失败；隔离 checkout 的缺少 .venv
和深路径 Lua MAX_PATH 另有归因记录。未把该 L1 改写为全绿，也未修改无关暂停中的 MR/IP 主题。
正常仓库路径的公共补验分别通过 SIMION 公共 275 项（6 skip）、OA Python 104 项及 Lua 26 项、
integration 997 项（3 skip）及 Ruff，实际源码身份稳定。

最终文档专用总门禁 `20261021_171423__gate__repo__local-oa-docs-final` 在 repository_hygiene 阶段因
仓库根残留空 `scratch` 目录失败，尚未进入文本字节和文档阶段。路径及空目录检查后，自动审批仍以
`blocked by policy` 拒绝删除；未改规则或换方式删除。后续独立文本字节与官方 `-StructureOnly` 文档
结构检查不能补回这项卫生失败，最终交接保留该限制。

后续场域／终态修复有 145752、153421、154633 三次各 3 项 focused 回归及 Ruff，原生 N1→N2→N100
闭合；显示修复 `20261021_164111__test__python__local-shared-display` 通过 6 项回归及 Ruff。
二区／三区默认加载对等、孔 guard 与全母群分析成功不等于数值收敛或实际电极接受度认证。

当前两套原生交付均保持 ready/pin，独立对照保持 ready/light_evidence。
旧 150849 三份重复 PA 通过公共 owner-selected retirement 删除，共 1,043,595,504 B；原 609 文件
全部保留，加收据后为 610 文件、904,324,606 B。审计
`20261021_170230__analysis__repo__retire-duplicate-oa-pa` 为 success/full（11 项），
manifest SHA-256 为 `52C4E1ECE177C6B97297105DD32F0403394E6A39BBED7945820D4DA0AA72D4F6`。
旧失败 manifest 未改写；N1/N2 的旧 IOB 需在新 managed run 中恢复同 SHA 依赖或重新装配才能重飞，
可从保留的 160146 工作 PA 或缓存、GEM、recipe 重建。当前两个交付 IOB 未被退役。

独立分析的一次性脚本在核验归档副本后删除。自动审批仅以 `blocked by policy` 拒绝删除两份 Temp
PowerShell 包装脚本（16,011 B 和 17,554 B），未重试或绕过，残留不影响数据或默认加载。
上述空 `simulation_repo/scratch` 同样保留，内容大小为 0 B。
