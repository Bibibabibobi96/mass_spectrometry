# OA-TOF 提取器与活动步策略修复后的精度、完整流程验证

DOC_STATUS: ARCHIVED_READ_ONLY

完成日期：2026-10-21。本记录补充[上一阶段 N100 对照][prior]，保留全部成功与负结果，不改变 Formal 资产或资格。
本轮运行的科学源码来自隔离目录 `C:/tmp/oatof-cpt-fix-20261021`；公共执行与证据管理仍使用主仓库入口。
旧 A（`20261021_154058__benchmark__comsol__oatof-cpt-fixed-dp5-rtol11-dense-a`）已以执行 success 封存，
但 94/100 事件被首次修复的错误下界拒绝，未通过科学门；其后冻结窗口复提取通过，仍不等于 1 ps 校准通过。
新 A2（`20261021_160603__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol11-dense-a`）与 B 已 success 封存，均为 100 命中、400 条完整有限状态；
但首轮 A2/B 校准最大 TOF 差为 1.064140590756324 ps，超过原 1 ps 门，失败结果保留。
C（rtol=1e-13）已 success 封存，B/C 最大差 0.11737509453269013 ps，原 1 ps 校准通过；最终实现回归为 57 个 MATLAB 测试通过。
C 经容量恢复才完成治理闭合，不能作为公平性能臂；同配置重复 C（173757，以下记 C2）已 success 封存。
C2 相对 C 最大 TOF 差 0.0172856005065114 ps，原八项检查全部通过、accepted=true；这支持本 N100 协议的一次重复性观察。
C2 的耗时另受调度干扰，不作公平提速结论。新 B12 separate-flow（181158）已执行 success，但两项位置 RMS 超出原状态门，accepted=false。
B12 数值矩阵到此停止；C13 separate-flow（183755）和 merged-flow（190832）均已 success 封存并通过原八项门。
此次配对的完整流程从 1780.9614266 s 降至 1730.6504611 s，减少 50.3109655 s（2.824933%）；
主链 API 从 59.4112699 s 降至 21.5029653 s，约 2.762934 倍。单次配对只记录本次观测，不能证明稳定整体提速或把求解波动归因于读取。
两组四个小模型已真实完成（194330/195033）：原生停止时间均通过解析 1 ps 门，但 DP5 的 2 ns 输出臂采样外推无事件，两组整体 run 均保持 FAIL。
195033 启用官方 StoreExtra 选项后，本固定 t 查询路径仍未恢复事件；未另行枚举全部额外解时刻，不能据此宣称该选项全局无效。
本轮科学运行与证据冻结已完成，不继续加严或放宽门。[汇总比较][final-comparison]保留所有接受与拒绝结果；
[最终 manifest][final-manifest]的 187 条记录（144 inputs、42 outputs 与 run_config）已独立逐项核验 SHA 和字节数。

## 1. 本次修复了什么

| 边界 | 修复前的问题 | 隔离源码的当前行为 |
|---|---|---|
| 步策略合同 | `solver_steps` 未实际驱动活动算法，构造/重追踪/验证硬编码 BDF 键 | 共同调用 `oatof_cpt_solver_policy`，按实际算法选择唯一活动键 |
| 原生键 | GA 或 DP5 可能仍使用自己的 Strict/Free 设置 | GA→`tstepsgenalpha`；BDF→`tstepsbdf`；DP5→`tstepsdopri5` |
| 合同消费 | 读到闲置 BDF=free 可能形成假阳性 | `apply` 写入并回读，`verify` 只回读；未知算法、非法步策略/存储合同在写入前拒绝 |
| 精确零平台 | 首零采样点可能被误当作真实 crossing 时刻 | 先识别终端静止 XYZ 平台，再从平台前的合法接近段外推 |
| 全零/触面返回 | 相等坐标或单个零点可能成为伪穿越 | 无接近段不捏造到达；触面后返回不算向下穿越；真实穿越需后续进入面下侧 |
| 近面运动 | 在物理距离容差内缓慢运动可能被误判冻结 | 平台静止用坐标尺度的 128 ULP；近面物理距离容差不再充当静止容差 |
| 外推有效性 | 平台到达缺少可审计区间 | 外推必须不早于所选接近段末端 approach_end、不晚于首个平台样本；保持 8 ULP 的时间表示误差 |
| 不完整轨迹 | 可能跨缺失样本寻找事件 | 有效轨迹内部存在非有限坐标时拒绝，不跨缺口插值 |

生产构造器、固定粒子重追踪和 GUI 同步验证复用同一个 policy 边界。
`geometry_contract.py` 在解析阶段验证 `solver_steps∈{free,intermediate,strict}`、`times_to_store=tlist`。
此修复不自动改变积分算法、rtol、输出表或场；这些仍由各臂冻结配置明确声明。
诊断 harness 在 `Study Compute` 前后调用相同 policy 验证，并回读 rtol、存储和限步活动键。

提取器输入时间单位是 s，位置单位是 mm；速度读取使用显式 `cpt.v*/1[m/s]`。
检测 CSV 的 `TofUs` 是 μs；比较器先乘 1000 得 ns，1 ps 门对应 `0.001 ns`。
终端静止的 128 ULP、外推端点的 8 ULP、比较器原有 128 ULP 序列化余量用途不同，不能互换。
新增 `segment_start_index`、`segment_end_index`、`plateau_start_index` 均为原输入窗口的 1-based 行号；不适用为 NaN。
拒绝外推时仍保留尝试使用的区间索引。新增索引放入独立 `arrivals_audit.csv`，不改变生产事件 CSV 合同。

COMSOL 原生 `cpt.st` 表示粒子停止于边界的时间，不是上述采样外推的别名；[官方状态数据说明][status-doc]还说明状态存储默认关闭，
部分量不能只凭轨迹事后恢复。[Freeze 说明][freeze-doc]明确冻结后保留碰壁时的位置和速度，因此非零末速度不表示粒子仍在运动。
仓库已有 [run_fixed_particle_retrace][stop-time-code] 的状态存储与停止时间读取路径；使用时仍须区分目标探测面和其他停止边界。
未保存该量的旧解不能免费补出原生到达时间；另行开启存储、重追踪及验证属于新受控运行，不回写本轮提取器校准。

## 2. 已完成的实现验证及其边界

初轮回归 `20261021_152519__test__comsol__oatof-cpt-fix-regression` 的 [summary][reg-summary]、[原生结果][reg-native]、
[manifest][reg-manifest] 和[源码清理回执][reg-cleanup]保留；最终修复回归是 `20261021_160415__test__comsol__oatof-cpt-fix-regression`。

| 验证 | 已观察结果 | 不能据此声称 |
|---|---|---|
| 初轮 MATLAB R2025b 单测 | 54 个测试全部通过，无失败/未完成；包含提取、场理想化解析和 policy 测试 | 后续真实窗口仍暴露下界缺陷，不能代表最终修复覆盖 |
| 最终 MATLAB R2025b 回归 | [160415 原生结果][reg2-native]：57 个测试全通过，原 100 粒子检测窗复提取通过 | 仅证明实现及该原窗行为，真实求解精度另由 B/C 校准 |
| COMSOL 6.4 小 API 检查 | GA、BDF、DP5 三种 Time 节点均完成 apply、保存、重开、verify | 空模型未运行 solver，不能证明实际 Study Compute 不会重建设置 |
| 本轮 L1 终端运行 | 已观察到 388 tests、skip=1，终端报告成功 | 当时没有保存独立 stdout，不为它编造日志链接 |
| 已捕获 L1 证据 | [180918 冻结日志][cal3-l1]：`CHANGED_GATE=PASS`，Python 3.11、24 个变更路径、非全仓范围 | 不等同全仓门禁；后续代码/文档收口仍须相应最终检查 |
| 最终 CPT 源码 L1 | `diagnostic_final_l1_gate.log`：16 个变更路径、`CHANGED_GATE=PASS`；OA Static 阶段 179.089 s，388 tests、skip=1 | [冻结日志][final-l1]；源码相关范围通过不回写完整 L2 为 PASS |
| 后续 L1/L2 相关门 | TOF 预算计算器 16 tests；OA 静态门 388 tests、skip=1，通过 | 不代表完整 L2 通过 |
| 完整 L2 | 已执行完成，三阶段失败，overall FAIL；详见下表 | 后续单阶段修复/重跑不能回写原 L2 为 PASS |
| 真实小模型及官方选项对照 | 194330/195033 各四案均完成 Study.run；原生停止时间均通过解析 1 ps 门，DP5/2 ns 采样外推均失败，两组整体 FAIL | 仅恒速平面 Freeze 和固定 t 回读；不代表 OA 场或官方选项全局结论 |

完整 L2 的三个失败阶段与边界如下。`diagnostic_l2_gate_r02.log`、环境重跑日志和两份基线审查回执已生成，
均已作为[最终证据 inputs][final-inputs]冻结，保留原失败状态。

| 失败阶段 | 已确认边界 | 当前状态 |
|---|---|---|
| common_contracts 的 MR refine policy 检查 | 指定测试及 MR Lua 调用在审查的前后提交中为相同 blob；既有分类器对该行的拒绝可复现 | 此特定失败为既有基线问题，仍为 FAIL；不据此判定 MR 物理合同是否合格 |
| simion_common | 隔离目录缺少 `.venv`；经 junction 复用已有受支持环境后重跑 | 269 tests、skip=6，重跑 PASS；原 L2 失败记录保留 |
| rf_quadrupole_ion_optics_static | 隔离路径 `C:/tmp/artifacts` 缺少已校准容量 ledger，fixture 在注册写入范围时失败；所审八份调用链源码与基线同 blob | 230 tests 中一项失败；尚未进入该用例的科学验证，属于前置环境/fixture 边界，未冒充科学 PASS |

两份基线审查仅支持各自核对的调用/文件范围，不能把其他失败统称为已有问题，也不授予本次完整 L2 通过。
最终 CLOC 已按独立主题准备：时间预算工具 `1cf9→7d91`，CPT 修复 `7d91→WORKTREE`；
精确基线、工具口径及分类计数见[计算器 CLOC][final-budget-cloc]与[CPT CLOC][final-cpt-cloc]。后者为 7d91c83b 到本轮源码 WORKTREE；不使用本文行数代替源码统计。

回归原生结果明确 `existing_model_loaded=false`、`field_or_trajectory_solved=false`、`physical_qualification=false`。
三个小 MPH 已按回执删除；`model_path` 是当时的运行位置，不是仍可执行或打开的交付资产。
54 个测试涵盖零/正/负平台、容差边界、全零静止、缺少接近段、真实穿越、触面返回、横向运动、无效时间和缺失样本。
policy 测试还覆盖闲置 BDF 假阳性、未知算法/存储策略及 setter 未实际生效。
这些测试确认已定义的边界行为，不重建上一阶段 D 的 Ion 8/19 原始路径，也不取消旧 A8/B8 的 12.20785 ps 失败。

### 真实窗口暴露的第二个下界缺陷与修复

旧 A 的 [summary][a-summary] 和 [原生结果][a-native] 均为执行 success，但只有 6 个 detector_hit；
另 94 个为 `freeze_extrapolation_outside_interval`。完整 100 粒子数据被保留，未删除被拒粒子。
`success` 只表示求解、导出和封存完成；这组事件不满足全部命中的科学门，不能进入接受链。
首次修复把 `t(plateau_index-1)` 当作到达下界；真实窗口显示冻结附近的查询插值过渡点可能晚于接近直线的到达估计，
所以“最后仍变化的查询时刻”不是原生事件时间下界。这里的外推仍是估计，不是读取 COMSOL 原生事件时刻。
[修复后的冻结源码][reg2-detector] 仅把该下界改为 `t(approach_index)`（approach_end），保持首个平台上界、8 ULP 和其余规则。

第二次回归 `20261021_160415__test__comsol__oatof-cpt-fix-regression` 已 success 封存，manifest 有 7 个输出。
[原生回归结果][reg2-native] 记录 57 个 MATLAB 测试全部通过、三种小 API 保存重开再次通过；没有重算场或轨迹。
它消费旧 A 的 [冻结检测窗副本][reg2-window]（200100 行、100 粒子、每粒子 2001 时刻），原窗复提取得到 100 个有限平面事件，
Event 全为 `frozen_on_detector`；只验证平面事件，此回归使用默认无限有效半径，不能冒充正式有限探测面命中验收。
[manifest][reg2-manifest] 绑定窗口与新源码；窗口 SHA 为 `87B2B5991418617E97AA8BCB09B4609A92D10E7A2C60CB0979160CEEB3D4BBA8`。
这关闭了该原窗的误拒绝回归，不证明 1 ps 收敛；旧 A 的事件 CSV、summary 和科学失败边界保持原样。
后续用新源码、关闭附加探针重新产生 rtol11/12 对照，旧 A 排除在公平性能排序之外。

### 四个真实小模型：原生停止时间通过，稀疏采样外推出现负结果

首次尝试 `20261021_193815__test__comsol__oatof-native-event-regression` 的 [summary][tiny-first-summary] 为 failed、`test_executed=false`，
在释放文件回读守卫处停止，尚未运行 Study；`readmatrix(...,'Delimiter','tab')` 没有按预期得到六列。
新运行 `20261021_194330__test__comsol__oatof-native-event-regression` 先保留该诊断，再显式使用实际制表符 `sprintf('\t')`、`NumHeaderLines=0`，
[原生记录][tiny-native]显示自动方式为 100×1、显式方式为 100×6；显式回读与原源逐位相同，六列最大差均为零。
这修复的是一次性试验的输入解析，不修改生产提取器、粒子源、时间门或空间容差。193815 的失败不改写为求解失败或成功。

小模型为 100 粒子恒速直线运动、平面 z=0 Freeze，不加载 OA MPH、不求静电场；释放时刻均为零，速度为 −27500 m/s，
解析到达时间从 20.1 ns 逐粒增加 0.003 ns，仿真止于 30 ns，晚期在 28/30 ns 回读。
DP5/GA 各用 0.2 ns 和 2 ns 输出表（151/16 点）；固定 rtol=1e-12、初始步 1e-10 s、最大步 2e-9 s、
活动步策略 Free、tout=tlist，并开启原生粒子状态存储。四案 Study.run 前后均保持 `control=time1`、实际活动键及所有登记设置，未强制 control=user。
因此本次真正测试了 Study Compute 下的活动 policy 保持；不把早先三个空模型属性 roundtrip 当作同一证据。

| 案例 | Study.run（s） | 原生日志末 Step | 原生停止时间最大解析误差（s） | 采样外推结果 |
|---|---:|---:|---:|---|
| [DP5 / 0.2 ns][tiny-dp5-dense] | 0.9313588 | 17 | 3.308722450212111e-24 | 100 hit；最大误差 5.260868695837256e-22 s；通过 |
| [DP5 / 2 ns][tiny-dp5-sparse] | 0.3403269 | 17 | 3.308722450212111e-24 | 100 no_detector_event；估计全 NaN；失败 |
| [GA / 0.2 ns][tiny-ga-dense] | 0.5576729 | 19 | 1.9852334701272664e-23 | 100 hit；最大误差 5.426304818347862e-22 s；通过 |
| [GA / 2 ns][tiny-ga-sparse] | 0.2874964 | 19 | 1.9852334701272664e-23 | 100 hit；最大误差 1.6212740006039342e-22 s；通过 |

这些接近浮点表示量级的误差只针对恒速解析构造，不表示真实仪器具有相应绝对精度。每种方法两输出表的原生 st 最大差均为零；
两种密度的末 Step 相同也不证明全部内部步序列逐项一致。小案耗时不得用于判断 OA 模型 GA/DP5 的性能排名。
194330 的[顶层 summary][tiny-summary]为 failed、`test_executed=true`，`execution_wall_seconds=108.0498397`；
各 case 的执行 status=success 与总体 passed=false 并存，因为四案完成后汇总断言保留 DP5 稀疏臂的负结果。
该 wall 字段不是前述大模型完整流程 Stopwatch；日志 Solution time 取整为 0 s，不代替表中的实际 Study.run 计时。
[manifest][tiny-manifest]保留 29 个输出；[清理回执][tiny-cleanup]只删除可由冻结输入恢复的执行副本，原始数据完整保留。

四案在 28/30 ns 的 xyz、速度和 st 均逐位恒定，速度仍为朝向平面的撞壁速度，最终状态均为 frozen；
这支持本构造中的原生停止时间和 [Freeze 保留碰壁速度][freeze-doc]语义，但最终状态不是逐时刻状态历史。
DP5/2 ns 的[晚期原始回读][tiny-sparse-late]有 200 行：z 从 0.0027500000000000254 至 0.010917500000000096 mm，
全部超过原 0.001 mm 近面容差；[事件误差表][tiny-sparse-errors]的 100 个 EstimatedStopS 均为 NaN。
同一臂原生 st 最大解析误差仍仅 3.308722450212111e-24 s，因而不能把无外推事件误报为原生时间门失败。
同时不能把稀疏输出回读的 qz 直接视为真实 impact 坐标，也不能扩大空间容差来制造 hit；
当前证据没有分离输出存储、查询插值及边界处理各层的贡献，不武断指定唯一根因。

已验证的结论是：本四案支持启用原生状态后的停止时间对照；“采样外推对输出密度不敏感”的假设在 DP5/2 ns 案不成立。
原生状态数据的定义和存储前提仍按[官方说明][status-doc]，不能对未保存 st 的旧解免费事后补出事件，
也不据小模型自动迁移 OA 事件定义、替换旧数据或授予新 Formal 资格。原四案负结果按实际范围保留，随后仅追加下述官方存储选项对照，未调整容差。

### 官方 StoreExtra 开关对照：固定 t 查询路径的负结果保持

[官方 COMSOL 6.4 说明][status-doc]将 Store extra time steps for wall interactions 用于在指定输出时刻之外增加靠近碰壁的解时刻，改善碰壁轨迹显示；
文档没有承诺任意固定 t 的 mphparticle 回读坐标就是原生 impact 坐标。
`20261021_195033__test__comsol__oatof-native-event-regression` 的[冻结配置][extra-settings]显式设置 `store_extra_wall_steps=true`；
194330 配置没有这个新增字段，其旧脚本直接设 false，四案 before/after 也均为 false。
195033 的[原生记录][extra-native]确认四案 before/after `store_extra=true`，control=time1、Free、rtol、限步和原输出表均保持；
除 run 路径和该开关外，源、物理条件、1 ps 时间门与 0.001 mm 空间容差不变。

四次 Study.run 分别耗时 0.9749372、0.4540187、0.5373949、0.3729122 s；原生停止时间四案仍全部通过解析门。
DP5/0.2 ns 与 GA 两密度的采样外推仍通过；DP5/2 ns 的 100 个事件仍为 no_detector_event、EstimatedStopS 全 NaN，
[该臂原始结果][extra-sparse]的晚期平面最大距离仍为 0.010917500000000096 mm，原生时间最大解析误差仍为 3.308722450212111e-24 s。
[顶层 summary][extra-summary]为 failed、test_executed=true，execution_wall_seconds=136.3421756；[manifest][extra-manifest]保留 29 个输出。
本次仍向 mphparticle 显式传入同一组 t 和 lateTimes，没有另外枚举、查询全部 extra solution times。
因此结论严格限于“启用后未修复本固定时刻回读/外推路线”，不能判定额外时刻不存在或官方选项在所有路线无效。
两组负结果均保留，不再运行或放宽门；[原生事件复核][final-native-review]与[StoreExtra 复核][final-extra-review]已冻结。

## 3. N100 预注册矩阵与不可变门槛

所有数值比较继续使用原 Formal MPH 已保存的 `sol1`；不重建几何、网格或静电场。
保存的 `sol2` 初态前 100 个粒子作为释放源，核对 N100 ION 与冻结 N1000 母表的精确前缀及 ID 顺序。
几何/边界/电压/质量/电荷、`es=off`、`cpt=on`、`notsol=sol1`、原输出表和受力表达式保持。
每臂求解前后核对场指纹及网格计数；这些采样不是全场数组逐字节哈希，MPH 哈希负责完整输入身份。
新比较器要求提取器、exporter、policy 三份冻结源码的 SHA 一致，并核验 manifest、settings 和原生绑定记录。
旧 run 缺少新 policy 源码身份或使用旧提取语义，不能混入本次参考校准。

| 次序 | 配置/目的 | 进入后续的条件 |
|---|---|---|
| 旧 A：诊断排除 | 首次修复仍误拒 94/100；含 AB/BA 附加探针 | 留作缺陷与 API 诊断，不与新臂作公平性能比较 |
| A2：fixed2 已封存 | 新提取器；DP5/Free，rtol=1e-11，原 163970 输出点，q/v=parent auto；无附加探针；预算 3600 s | 全部数据守卫通过；A2/B 校准失败 |
| B：已封存 | 同源、同场、同输出、同限步、8 核和 separate 读取，rtol=1e-12；预算 3600 s | A2/B 失败；随后 B/C 原 1 ps 校准通过 |
| C：已封存 | 同一数值与读取配置，仅 rtol=1e-13；受管预算预设 5400 s | B/C 最大差 0.11737509453269013 ps；保留容量恢复边界 |
| C2 同配置重复：已封存 | 173757；与 C 相同科学配置，预算 5400 s | 对 C 最大差 0.0172856005065114 ps；八项检查通过，耗时受调度干扰 |
| B12 separate-flow：已封存 | 181158；rtol=1e-12、8 核、separate、密集输出、探针关闭；预算 5400 s | TOF 通过，但两项位置 RMS 超旧门，accepted=false；不再扩展 B12 矩阵 |
| C13 separate-flow：已封存 | 183755；rtol=1e-13，其余科学配置及新 child 测量方式匹配；预算 5400 s | 相对 C 最大 TOF 差 0.019553695551621786 ps，八项门通过 |
| C13 merged-flow：已封存 | 190832；与 C13 separate 匹配，仅改变主读取策略 | 相对 C 最大 TOF 差 0.01553569006773614 ps，八项门通过；性能仅单次配对观察 |

当前已完成 C2 重复、未接受的 B12 和 C13 separate/merged 完整流程对照，不追加更严 rtol 或展开 manual scale、稀疏输出等数值扫描。
本轮校准、重复与 matched pair 通过不抹去 A2/B 或 B12 的失败，也不扩大为生产最优或 Formal 结论。

旧 A 的[冻结 settings][a-settings]：NewtonianFirstOrder/explicit RK DP5；8 核；reacf=false；storeudot=true；
初始步 1e-10 s、最大步 5e-8 s；全局 scaled atol 因子 0.1；q/v Field 继承 auto；Stride=1、Refine=1。
旧 A 主读取为 separate，附加探针顺序 AB、BA；[A2 settings][fixed2-settings] 保持数值参数，但 ReadbackProbe=false；各臂均 FieldProbe=false。
[B settings][b-settings] 和 [C settings][c-settings] 分别将 rtol 加严至 1e-12、1e-13，其余上述科学配置保持。
[重复 C settings][repeat-settings] 和 [run_config][repeat-config] 冻结相同 rtol、8 核、separate、原输出及关闭附加探针；外层资源观察方式另行记录。
q/v 请求值 0 表示继承父级 auto，不表示物理尺度为零，也不能把闲置 scaleval=1 当成运行时实际尺度。
后续若采用 q=1、v=30000 的 manual 配置，须同时固定两字段，并从原生日志核对最终实际尺度。
manual scale 会改变物理绝对容差权重，不能以相同 rtol 宣称相同精度。

完整精度门保持如下，不随候选结果或观察到的噪声改变：

1. 同 100 个唯一 ID，全部 hit/status/event 一致；不删除不利粒子；初态、场和分析合同一致。
2. 基线—加严参考最大逐粒子 TOF 差 ≤1 ps；校准失败时所有候选 `accepted=false`。
3. 候选—参考最大逐粒子 TOF 差 ≤1 ps。
4. 5、30、50、70 μs 四个共同时间、全部 ID，共 400 条位置/速度状态完整且有限。
5. 落点二维位置、共同时间三维位置、速度的向量 RMS 和最大模长，均不大于合格基线—参考对应量加原序列化余量。
6. 余量仍为 `128*spacing(max(1,maxabs(reference)))*sqrt(d)`，d=2 或 3；单位分别为 mm 或 m/s。

`acceptance.json` 无论新建或复用，都从本次 B/R 重算并核对路径、三类误差键、有限数值和全部阈值。
Event 不一致的候选只可保留全部粒子作诊断，不能通过 accepted；基线/参考 Event 不一致直接拒绝校准。
重复运行同样保留全部差值。两次结果只提供有限的重复性观察，不构成稳定的置信区间。

## 4. 完整流程时间和峰内存：必须同时报告

首要时间指标是外层 Stopwatch 包围一次 `diagnostic_launch.ps1` 调用得到的 `complete_flow_seconds`。
开始点在 launcher 子进程启动、其脚本准备和输入身份哈希之前；结束点在 terminal manifest 独立验证、容量租约释放调用及该子进程返回之后。
调用返回本身不证明调度账本已移除所有租约；C2 的 observer 边界和后续独立回收核对见第 5 节。
因此包含准备/复制/哈希、容量预检、启动/排队、加载、配置、积分、读取、导出、探针、retention 和封存。
不包含测量 wrapper 自身在 Stopwatch 启动前的源码快照/observer 就绪等待、返回后的 observer 退出及测量汇总，
也不包含随后独立 analysis、人工复核或把该条测量追加写入 JSONL 的时间。
各臂按相同定义计时；探针、等待许可或异常终止不能事后从完整流程时间里静默扣掉。

活动记录 `complete_flow_measurements.jsonl` 每条包含：
`run_id`、`arm`、`started_at_utc`、`ended_at_utc`、`complete_flow_seconds`、`exit_code`、
`peak_managed_memory_bytes`、`method`、`arguments`。
分析前停止追加，通过 `diagnostic_analysis.ps1 -ExecutionTimingsPath ...` 冻结到 analysis inputs。
冻结副本与来源 SHA 进入 manifest 和外部输入身份表；活动 scratch 记录本身不是最终引用终点。

峰内存来自该 run `summary.json.peak_managed_memory_bytes`，是已核 PID/出生身份的托管进程采样峰值：
逐进程取 `max(working_set, private)` 后求和，采样间隔 3 s；不能当作 COMSOL 内部峰值、总系统内存或全机器瞬时精确峰值。
采样范围是受管执行阶段，不补造准备/封存阶段未采样的峰值；缺失就填不可用，不借其他臂替代。
同时列出最低系统可用内存；预算为托管 28 GiB、系统可用至少 6 GiB、磁盘预约 64 MiB。
旧 A、A2、B 的受管墙钟预算为 3600 s；[C run_config][c-config]、[C2 run_config][repeat-config]、B12 及 C13 separate-flow 均预设 5400 s。
这是逐臂预声明的受管阶段预算，并非外层完整 Stopwatch 的硬上限；本轮不按运行结果事后改预算定义。
B（字节）为原始报告值；换算 GiB 使用 2^30，GB 使用 10^9，表头必须写清楚。

C2 及后续完整流程臂另记录 `peak_complete_flow_process_family_bytes`，覆盖准备至封存的外层 wrapper、observer 及其受管子进程。
它也是 3 s 采样的逐 PID `max(working_set, private)` 之和峰值，包含共享页重复计数的可能；不是唯一物理页峰值、连续时间峰值或全机器内存。
该值与 solver 受管阶段峰值分别报告，不把覆盖范围扩大造成的差异称为求解器内存增长。

| 辅助计时 | 解释 | 不允许的等同 |
|---|---|---|
| native Solution time | 原生日志报告的求解时间 | 不等同整个工作流 |
| `std2_run` | Study 编译/变量准备/积分/求解存储 | 不等同纯 ODE 或场查询时间 |
| MATLAB 主体总计 | 含本体加载、配置、读取/导出及登记的附加探针 | 不等同外层完整流程 |
| 原 `wall_seconds` | 启动器内部已有边界 | 不改名为本次 complete_flow_seconds |
| 主链 API 总时间 | 明确 separate 三读或 merged 一读的真实主导出链 | 不含所有生产流程成本 |
| AB/BA 探针 | 同一解上四次暖 API 策略测量 | 不等同端到端提速，也不是冷启动重复 |

读取策略 A 为原 t=0、检测 XYZ、400 状态六表达式三次 API 查询；策略 B 为六表达式联合时刻的一次查询（与运行臂名称分开）。
顺序 AB、BA 至少得到 A/B 各两次；记录每次耗时、形状、有限掩码和逐值差。
主链 `ReadbackMode=merged` 才真正使用联合查询拆分初态/检测/状态；仅开探针没有替换主链。
即使 API 逐值零差，也须看匹配配置的完整流程秒数和内存；不能把 API 比值直接称为生产整体提速。

## 5. 已封存结果与证据边界

旧 A、A2、B、C、C2、B12、C13 separate/merged、六次分析、小模型输入预检失败及两组四案试验均已封存；各失败及适用范围分别保留。

| arm/run | 终态 | 最大 TOF 差/比较对象 | 状态门 | 同配置重复 | accepted |
|---|---|---|---|---|---|
| 旧 A：154058 | 执行 success；科学失败 | 不进入新校准 | 6 hit / 94 误拒 | 不作性能重复基线 | 不具资格 |
| A2：160603 fixed2-dp5-rtol11-dense-a | 执行 success，已封存 | 相对 B：1.064140590756324 ps | 100 hit / 400 states 完整有限 | 本轮不重复 A2 | 校准失败，不具资格 |
| B：162540 fixed2-dp5-rtol12-dense-b | 执行 success，已封存 | 相对 C：0.11737509453269013 ps | 100 hit / 400 states 完整有限 | 新 B12 未接受 | B/C 校准通过；非 Formal |
| C：165235 fixed2-dp5-rtol13-dense-c | 执行 success；容量恢复后闭合 | B/C 同上 | 100 hit / 400 states 完整有限 | C2 已通过 | 作为加严参考；非性能资格 |
| C2：173757 fixed2-dp5-rtol13-dense-c-repeat | 执行 success，已封存 | 相对 C：0.0172856005065114 ps | 100 hit / 400 states；八项检查全通过 | 同配置一次重复通过 | true；非 Formal/性能资格 |
| B12：181158 fixed2-dp5-rtol12-separate-flow | 执行 success，已封存 | 相对 C：0.10911809056324273 ps | 100 hit / 400 states；两项位置 RMS 失败 | 新测量方式；原门不放宽 | false |
| C13：183755 fixed2-dp5-rtol13-separate-flow | 执行 success，已封存 | 相对 C：0.019553695551621786 ps | 100 hit / 400 states；八项门全通过 | 新测量方式 | true；非 Formal |
| C13 merged：190832 fixed2-dp5-rtol13-merged-flow | 执行 success，已封存 | 相对 C：0.01553569006773614 ps | 100 hit / 400 states；八项门全通过 | 匹配 separate 的读取对照 | true；非 Formal |

| arm/run | complete flow（s） | 托管峰值（B/GiB） | 最低可用（B/GiB） | std2（s） | 主链 API（s） | 探针/队列说明 |
|---|---:|---:|---:|---:|---:|---|
| 旧 A（仅诊断） | 1183.8395816 | 5546184704 / 5.165287 | 27161169920 / 25.295811 | 864.3604399 | 52.3080928 | AB/BA 阶段额外 148.8344701 s |
| A2（160603） | 1155.4755105 | 5201625088 / 4.844391 | 23161905152 / 21.571205 | 789.5157003 | 55.2207359 | separate；探针关闭；排队至少 153 s |
| B（162540） | 1528.405753 | 5174067200 / 4.818726 | 25773150208 / 24.003117 | 1241.7513417 | 53.3782316 | separate；附加读取/场探针关闭 |
| C（165235，仅精度/诊断） | 尝试 2118.3234821；含恢复总墙钟 2326.3753785 | 4921032704 / 4.583069 | 26012332032 / 24.225872 | 1700.4590173 | 54.1753861 | 容量恢复；不可作公平性能臂 |
| C2（173757，仅精度/诊断） | 1864.9123134 | 5304004608 / 4.939739 | 26392555520 / 24.579983 | 1684.084681 | 56.289243 | 调度干扰；耗时不作公平提速 |
| B12 separate-flow（181158，仅诊断） | 1337.1858447 | 5234556928 / 4.875061 | 26482388992 / 24.663647 | 1172.7485816 | 50.1143433 | external child；科学门失败，不作同精度提速臂 |
| C13 separate-flow（183755） | 1780.9614266 | 5358891008 / 4.990856 | 24622858240 / 22.931824 | 1607.0291436 | 59.4112699 | 全精度门通过；matched pair 的 separate 臂 |
| C13 merged-flow（190832） | 1730.6504611 | 5055033344 / 4.707867 | 25373167616 / 23.630604 | 1563.7496378 | 21.5029653 | 全精度门通过；仅单次配对性能观察 |

前三臂完整秒数已冻结于[首轮 analysis 的外层计时记录][cal-flow]；旧 A 原启动器 wall 为 1154.0610302 s，B 为 1498.6981598 s，均不能替代完整秒数。
B 的资源和分阶段时间见 [summary][b-summary] 及[原生结果][b-native]；100 命中和全部状态有限不代表 TOF 已收敛。
AB/BA 四次 API 耗时依次 51.1729655、20.2988744、20.4230098、56.8569001 s；全部检查 `bitwise_equal=true`、最大逐值差为 0。
这支持同解读取等价性，不修复旧事件表，也不提供科学接受资格；少做 148.8344701 s 的探针不能计为算法提速。

首轮比较 `20261021_165143__analysis__python__oatof-cpt-comparison` 已 success 封存，[manifest][cal-manifest] 的 11 个输出、39 条文件记录（含 run_config）已独立核验。
[comparison][cal-comparison] 给出 A2−B 最大差 1.064140590756324 ps（[逐粒子表][cal-deltas] 中 Ion 38），RMS 为 0.393028290024431 ps。
[acceptance][cal-acceptance] 的 `calibration_tof_pass=false`、`qualification=false`；该轮没有候选，不能把候选空表写成任何配置 accepted。
阈值仍是 1 ps，不把超出约 0.06414 ps 当作舍入余量；场/源/事件和状态守卫通过也不能抵消这项失败。
第二轮 `20261021_173121__analysis__python__oatof-cpt-comparison` 已 success 封存，[manifest][cal2-manifest] 有 11 个输出、40 条文件记录（含 run_config）。
[B/C comparison][cal2-comparison] 的最大 TOF 差为 0.11737509453269013 ps（Ion 91）、RMS 为 0.04038627799424106 ps，
[acceptance][cal2-acceptance] 明确 `calibration_tof_pass=true`，而 `qualification=false`；候选列表仍为空。
全部 100 ID/命中/事件及 400 有限状态守卫通过；落点、共同时间位置、速度的最大向量差分别为
2.1619189461432425e-6 mm、5.600893734366938e-6 mm、1.9945988738857365e-4 m/s，用于登记后续状态误差限。
这建立了本固定场、固定源、固定提取语义的经验参考校准，不是物理绝对误差、网格收敛或 Formal 资格。

第三轮 `20261021_180918__analysis__python__oatof-cpt-comparison` 已 success 封存，[manifest][cal3-manifest] 有 15 个输出、60 条文件记录。
[comparison][cal3-comparison] 复用并重算同一 B/C acceptance，C2−C 最大 TOF 差为 0.0172856005065114 ps（[逐粒子表][cal3-deltas] 中 Ion 86），
RMS 为 0.005879437644181207 ps；Event、TOF、三类状态的 RMS/max 共八项检查全为 true，`accepted=true`。
落点、共同时间位置、速度的最大向量差分别为 2.789895731122507e-7 mm、6.865589928335501e-7 mm、2.342850189855885e-5 m/s，
全部小于冻结 B/C 状态门。它记录一次同配置重复通过，不能把两次样本扩展为置信区间或绝对误差上界。

第四轮 `20261021_183517__analysis__python__oatof-cpt-comparison` 已 success 封存，[manifest][cal4-manifest] 保留 22 个输出。
[comparison][cal4-comparison] 中 B12 separate-flow 相对 C 的最大 TOF 差为 0.10911809056324273 ps（[逐粒子表][cal4-deltas] 中 Ion 1），
RMS 为 0.04099127195315618 ps，Event 和 TOF 门通过；但下列两项超过原 B/C 状态门，其余六项检查通过，整体 `accepted=false`。

| 位置向量 RMS（mm） | B12−C 实测 | 原冻结限值 | 超限比例 |
|---|---:|---:|---:|
| 探测面 XY | 8.532524061592899e-7 | 8.060561512470987e-7 | 5.85520684% |
| 四个共同时间 XYZ | 1.2251206556844013e-6 | 1.216619934882962e-6 | 0.69871622% |

限值已经包括预登记的 128 ULP 序列化余量，不再加一层百分比容忍，不删除最差粒子，也不只凭 TOF 通过替代整体状态门。
B12 的数值矩阵在此停止；其执行耗时可作诊断记录，但不得成为“相同精度已提速”的证据。

这里有一个数值判定陷阱：本轮状态门来自单次 B−C 差加 128 ULP，是预注册的数值一致性门，
没有从孔径/落点裕量、能量、传输率或分辨率等功能预算反推。C2−C 本身非零，表明相同冻结设置的两个重复结果存在非零数值差，尚未分解其链路来源；
128 ULP 只覆盖规定的序列化余量，不包含这种重复不确定性，两次样本也不足以建立可靠置信区间。
因此位置 RMS 微小超限不等价于工程功能不合格，但缺少功能预算也不能据此声称工程合格；本轮 B12 仍保持 FAIL。
未来实验应在看候选结果之前声明位置/速度等功能预算、统计口径、参考重复不确定性的估计与合成方法，
并以相应重复和功能指标验证。不能事后把参考差、固定百分比或新误差预算加到本轮门限上，将失败改成通过。

[summary][b12-summary] 和[原生结果][b12-native] 给出 std2=1172.7485816 s，[原生日志][b12-log]报告 Solution time=1165 s，
主体（optional probe 前）=1267.081753 s，主链三次 API=19.6771031+11.3760154+19.0612248=50.1143433 s。
[冻结外层计时][cal4-flow] 的完整流程为 1337.1858447 s，受管阶段峰值 5234556928 B，
全流程进程族采样峰值 5774585856 B（5.378002 GiB）；独立复核确认 402 条采样覆盖计时区间。
两个内存指标仍使用第 4 节定义，不是唯一物理页或连续峰值；[B12 独立复核回执][final-b12-review]已冻结。

第五轮 `20261021_190745__analysis__python__oatof-cpt-comparison` 已 success 封存，[manifest][cal5-manifest] 有 15 个输出。
[comparison][cal5-comparison] 中 C13 separate-flow 相对原 C 最大 TOF 差为 0.019553695551621786 ps（[逐粒子表][cal5-deltas] 中 Ion 60），
RMS 为 0.006374769880352634 ps，八项检查全部为 true，`accepted=true`；100 ID/事件与 400 有限状态完整。
落点、共同时间位置、速度的 RMS/max 分别为 1.2449862240999935e-7/3.399309044508701e-7 mm、
1.7705857251529224e-7/8.338176182316622e-7 mm、8.352012542422203e-6/2.563002506636566e-5 m/s，均满足原 B/C 门。
[summary][c13-summary] 与[原生结果][c13-native]给出 std2=1607.0291436 s、主体（optional probe 前）=1707.7822526 s，
[原生日志][c13-log]的 Solution time 为 1600 s，主链 API 共 59.4112699 s；内部 wall=1749.8502608 s。
[190745 冻结完整流程记录][cal5-flow]确认外层 Stopwatch=1780.9614266 s、exit_code=0，
受管阶段峰值 5358891008 B，全流程进程族采样峰值 5882204160 B（5.478230 GiB）。
同一记录绑定测量源码、observer 与资源采样文件的 SHA；其实际字节现均已进入[最终复现 inputs][final-inputs]。
separate 的独立采样复核发现：两个非峰值样本中有五个只出现一次的短寿命 PID 未记录出生时间，
峰值样本全部 16 个 PID 的出生身份完整。530 条采样覆盖完整计时区间，但不能表述为“所有样本的所有进程身份均完整”；
此边界与[独立复核回执][final-separate-review]已随最终证据冻结；采样峰值不能代替连续时间真实峰值。

### 相同科学配置的 separate/merged 配对结果

第六轮 `20261021_193737__analysis__python__oatof-cpt-comparison` 已 success 封存，[manifest][cal6-manifest] 有 22 个输出。
[comparison][cal6-comparison] 中两个候选相对同一 C 参考的八项门均通过、`accepted=true`，源/场、100 ID/命中/事件和 400 有限状态守卫保持。
merged−C 最大 TOF 差 0.01553569006773614 ps（[逐粒子表][cal6-merged-deltas]中 Ion 42）、RMS 0.006102763005975413 ps。
两臂相互比较的最大 TOF 差为 0.017385403339176264 ps（[配对表][cal6-pair-deltas]中 Ion 81），RMS 0.006871193309166193 ps；
100 个 Event 完全一致，但采样位置/速度、探测面 XY 及 TOF 均非 exact；状态差也超过纯 128 ULP 余量，
所以 `same_sampled_outputs_within_serialization_and_1ps=false`。这是 `diagnostic_only` 的更严格机制检查，
不是原 accepted 门；该 false 不表示 1 ps 时间门失败，也不改变两臂各自相对 C 的 accepted=true。
这两次各自重新求解的结果通过原参考门，不应冒充同一个解上的 bitwise 读取等价性；后者由旧 A 的同解 AB/BA 探针支持。

[merged summary][merged-summary]、[原生结果][merged-native]和[原生日志][merged-log]给出 std2=1563.7496378 s、Solution time=1557 s、
主体（optional probe 前）=1629.2325606 s、主链单次 API=21.5029653 s；内部 wall=1697.3250225 s。
[193737 冻结完整流程计时][cal6-flow]保留两臂 Stopwatch 和两种峰内存。以下减少量均为 separate−merged，百分比的分母均为 separate：

merged 的独立 review 确认 511 条采样覆盖完整流程，所有样本记录的 PID 出生身份完整；两臂的采样侧车及各四份源码快照 SHA 核对通过。
这与 separate 的两条非峰值样本缺项边界分别记录，不由一臂推定另一臂身份完整。

| 指标 | 本次减少量 | 相对减少 |
|---|---:|---:|
| 完整流程 | 50.3109655 s | 2.824933% |
| std2 | 43.2795058 s | 2.693138% |
| 主链 API | 37.9083046 s | 63.806589% |
| MATLAB 主体（probe 前） | 78.5496920 s | 4.599514% |
| 受管阶段采样峰值 | 303857664 B | 5.670159% |
| 全流程进程族采样峰值 | 259022848 B | 4.403500% |

主链读取的耗时比为 2.762933812668153；它与同解 AB/BA 逐值零差的已有证据共同支持合并读取减少 API 开销的方向。
但 std2 在读取之前完成，本次 43.2795058 s 的求解阶段差不能归因于后续读取合并；其余启动/封存开销也在两次运行间变化。
完整流程仅观测到 1.029070552737739 的时间比，不能由 API 比例推出整个生产流程约 2.76 倍提速。
这是一对满足原精度门的完整诊断运行，没有重复配对/随机交替的性能分布，因此不声称稳定整体提速或稳定内存下降；
若未来要声明稳定收益，应另预登记匹配重复，并保留完整流程、原生求解、读取、资源与异常的全部口径。
当前可采用的结论是：本 N100 固定场案例合并读取已在真实主导出链工作、保住本轮精度门，并观察到明显 API 时间减少；
整体收益较小且夹杂求解及编排波动。sampler 原始数据、各臂四份测量/资源源码快照及[分离臂复核][final-separate-review]、[合并臂复核][final-merged-review]均已冻结到[最终 inputs][final-inputs]。

### C 的容量恢复与重复臂的计时边界

[C summary][c-summary]、[原生结果][c-native] 均为 success，求解、100 命中、400 状态及导出先已完成。
保留的完整原生日志和必要检测窗使载荷合计 26,364,032 B，比 25 MiB light-evidence 额度多 149,632 B；
这不是 28 GiB 内存预算或 64 MiB 瞬时磁盘预约超限，也不是科学求解失败。
公共 `seal-stopped-payload` 按原字节保留该运行，将其登记为 `ready/pinned` 的 `rebuildable_payload`，
不删检测窗、不裁日志、不重算轨迹；[已冻结恢复回执][c-recovery] 给出 29 个文件、owner、保留理由和 `new_run_required` 续跑边界。

[第二轮冻结外层计时][cal2-flow] 原样保留首次异常记录：attempt Stopwatch 为 2118.3234821 s，但 run_id 为空、JSON exit_code=0 无效，
实际外层工具退出码为 1。追加恢复记录以原开始 UTC 至公共恢复核验结束计得 2326.3753785 s，含诊断/恢复间隔，
不是普通成功臂的同口径 Stopwatch；C 内部 `wall_seconds=2091.7172544` 也不得替代它。
4921032704 B 仍只是原受管子进程采样峰值，没有覆盖整个恢复流程的内存采样；不补造全流程峰值。
因此 C 可进入精度校准，不能进入公平耗时排序或用作提速比值分母。

C2 的 [summary][repeat-summary]、[原生结果][repeat-native] 记录科学求解和导出完成；内部 wall=1827.1910306 s，MATLAB 主体总计=1785.8478105 s。
[冻结完整流程记录][cal3-flow] 的 Stopwatch 为 1864.9123134 s、exit_code=0；公共容量 fallback 正常返回，
[封存回执][cal3-capacity] 保留 26,317,766 B、30 个文件为 ready/pinned，不改变科学数据。
受管阶段峰值 5304004608 B 与全流程进程族采样峰值 7320924160 B（6.818142 GiB）分列；后者包含 outer 和 observer，不能称为唯一物理内存峰值。

[已冻结 observer 审查][cal3-observer] 确认旧同进程编排使两项轻 GATE 租约延迟释放，合计预留 4 核/4 GiB；
这是资源准入/排队干扰，并未把两个租约重复计入逐 PID 内存采样。科学配置未变，C2 可用于精度/重复性，耗时不作公平提速。
Agent 1 的[终态独立复核][cal4-repeat-review]已确认八项门、552 条采样及旧两项 GATE 全部回收，该回执现已冻结于 183517 inputs。
新的测量 wrapper（SHA-256 `D0B18F6B11E9DC47154578D1ABF9D8567043DB447C3D27738F60A8BAF0423435`）
改为单独外部 child 执行 launcher，使 observer 与 launcher 为同级子进程；[参数/退出码/许可自测][cal4-selftest]已通过，但这不是求解或性能证据。
测量源码已进入最终 analysis 的[冻结输入][final-inputs]；B12 使用此方式完成，科学门失败。准备阶段 GATE 的工具 stdout 未持久化，
因此不声称冻结 run 自身具有那两项 released 日志；独立复核的进程关系、公用 COMSOL release 和终态账本观察分开记录。

### 原生日志中的积分活动集中区间

[计数结果][native-distribution] 和[生成源码][native-distribution-source] 已冻结于 180918 inputs。
以下按日志打印时间选择不晚于 2 μs 的最后一条 accepted-step 行，使用该行累积计数占全程计数的比例：

| 臂 | 截止选中时间（μs） | Step / 全程（占比） | Res / 全程（占比） | Tfail / 全程（占比） |
|---|---:|---:|---:|---:|
| B（rtol12） | 1.9586 | 30266 / 39374（76.87%） | 549780 / 680008（80.85%） | 48274 / 57770（83.56%） |
| C（rtol13） | 1.9941 | 43827 / 56480（77.60%） | 742133 / 929544（79.84%） | 62192 / 76312（81.50%） |

因此约前 2 μs 集中了约 77% 的 Step、80% 的 Res、81–84% 的 Tfail，值得优先对照该段力和积分行为。
这里的时间切点是诊断划分，不是已识别的物理界面或加速区边界；日志时间有舍入，跨界失败尝试按其后 accepted 行归入分段。
脚本排除输出专用 `-` 行，核对 Step 连续、累积量单调、分段合计和 `Res=7*(Step+Tfail)`；该恒等式不证明七次等成本场查询。
这些是原生计数分布，不是 CPU 时间、墙钟或场查询比例，也不能单独证明电场跨单元跳变导致拒步。

## 6. 可复现步骤：从冻结输入恢复，不运行历史临时路径

1. 阅读主仓库 AGENTS→README→项目 README/PROJECT 及生命周期规则；确认本机公共工具链可用。
2. 从目标 success run 的 manifest 校验将消费的输入/输出身份；不要修改旧 run，也不要在旧结果目录续跑。
3. 在 `artifacts/projects/single_reflection_oa_tof_mass_analyzer/scratch/<新的时间戳任务目录>/` 建立临时受管目录。
   该层级必须保留：一次性 PS 脚本按此布局定位主仓库公共入口，不能随意搬到另一层级直接执行。
4. 仅从新阶段冻结的 `inputs/*.txt` 按 SHA 恢复 `diagnostic_launch.ps1`、`diagnostic_run.m`、`diagnostic_task.m`；
   本次 C13 对照的这三份脚本来自 [183755 inputs][c13-inputs]；用原字节复制，只去掉末尾 `.txt`，不可重新编码或拼接旧版本。
   当前回归入口从 [160415 inputs][reg2-inputs] 恢复，先以其冻结原窗复核 57 测试和 100 平面事件；C13 配对分析入口和 compare 从 [193737 inputs][cal6-inputs] 恢复。
   如复核第 2 节的负结果，从 [194330 inputs][tiny-inputs]恢复三份 `diagnostic_native_event_*` 执行文件及两份科学函数，
   原样保留 settings 的方法/输出表/容差与实际制表符读取；预期记录是四案完成、DP5/2 ns 外推失败，不能以总体 PASS 作为复现条件。
   官方 StoreExtra=true 对照改用 [195033 inputs][extra-inputs]中的完整对应版本和冻结开关，不将两版一次性脚本混用。
   该回归 PS 明确只接受原已审隔离目录；路径失效时应重新建立受管重现实验，不能静默绕过路径绑定。
   A2/B、B/C、C2、B12、C13 separate 和 matched pair 分析均已封存；不以旧 144817 比较器替代新源码身份门。
   测量 wrapper/observer 也须从最终 analysis 的冻结 `.txt` 恢复为 `diagnostic_measure.ps1`、`diagnostic_memory_monitor.ps1`；
   仅有 JSONL 中记载的旧 scratch 路径或 SHA 不足以恢复文件，未冻结字节前不得声称完整测量复现包已齐备。
5. `SourceRepoRoot` 指向已核验的隔离源码树；需要历史重建时，按冻结源文件建立临时最小目录结构并核对 SHA。
   该参数提供项目 `comsol/` 下三份科学函数、`config/analysis_contract.json` 和 `common/analysis/peak_metrics.py`。
   科学函数来自各臂 inputs，peak_metrics 来自相应封存 analysis inputs；不能按已经删除的 `runtime_path` 执行。
6. 主仓库 `common/contracts/run_artifact_support.ps1`、公共 COMSOL launcher 和主仓库 Python 环境继续作为稳定入口。
   执行顺序为测量 wrapper→独立 `diagnostic_launch.ps1` 子进程→NewRunPackage/容量与执行租约→
   `common/comsol/run_comsol_r2025b.ps1`→冻结 `diagnostic_task.m`/`diagnostic_run.m` 和科学函数。
   不另开手动 COMSOL 实例；当前一臂终态、封存与许可释放核对完成后，再串行开始下一臂。
7. 已完成顺序为原窗回归→无探针 rtol11（A2）→匹配 rtol12（B）→A2/B 失败→rtol13（C）→B/C 原门通过→C2 同配置重复通过。
   B12 separate-flow 两项状态 RMS 失败后停止该矩阵，保持原门；C13 separate/merged 均已封存并通过完整精度门。
   单次性能配对的观察边界如第 5 节；小模型已按第 2 节保留总体 FAIL，不追加其他数值扫描或为失败改门限。
   每次生成新 run，冻结 .txt、参数、科学源 SHA，并实际消费 run-local 副本；不以旧 A 复提取结果伪装为新的完整求解 run。
8. 最终分析冻结各臂消费记录、三份科学源码、peak_metrics、完整流程 JSONL、实际测量 wrapper/observer 与终态复核回执、最终 L1 日志；完成独立 manifest 验证。
   科学运行配置一致不代表测量编排版本一致；新旧 observer 方式必须显式区分，不混成公平性能样本。

原数据身份（恢复时逐项核对，不重新生成粒子源）：

| 输入 | SHA-256 |
|---|---|
| Formal MPH | `9F4C3DCE51791B41B4A7649500F74C29366BAC431111E79AF6CE5399ECA72A4D` |
| N100 ION | `3BD65B6CD43C5C122708D98BBD0BC0D9BD599D9FBBF17C5BB76B469613ECF26D` |
| N1000 母 ION | `D300469758FED94E2771C1C9CA36AFF38128F42163523F3611D65990D5587179` |

模型路径为该项目 artifacts 的 `formal/comsol/single_reflection_oa_tof_mass_analyzer__model.mph`；
ION 位于 `formal/simion/oatof_comsol_524amu_gaussian_N100.ion` 与 `..._N1000.ion`。
新臂科学源 SHA 及消费路径可由 [settings][fixed2-settings] 和各 `.txt` 输入核查；不以 SourceRepoRoot 路径相同替代字节身份。

脚本字节核对值如下；仍须同时核对各 run manifest，而不是把本表当作输入身份的替代权威。

| 从冻结输入恢复的文件 | SHA-256 |
|---|---|
| diagnostic_launch.ps1 | `BDB0990C358DDB1603BDE6D221B0D5A8AF4BA839F6C3E2C41F2A3D2493828F29` |
| diagnostic_run.m | `388C2BDFDE7D7A18E0986DD3A521E12B17A71C99F4A09C5E6382499565E78E45` |
| diagnostic_task.m | `8F4C5FFE08E9085B8948B2BE40949364564080CF6E7969C649893F8A3BDB4B2E` |
| diagnostic_analysis.ps1 | `857BE27D84C63AC3D9590F2F9F6B8638E548B66DA5027C12E6A7BD9F22B07032` |
| diagnostic_compare.py | `F1BBAE77A33EAD34F6872F8C22B65D61F3A9A75D11146286CAD34A65B188CCB7` |

完整流程复现按以下参数调用已恢复的测量 wrapper；这是复现示例，不是追加运行授权。
`$scratch`、`$sourceRepo` 和三个 run 变量须替换为已核验的本机路径，`$newArm` 必须是新名称。
该测量版本固定 8 核、Free、初始步 1e-10 s、最大步 5e-8 s，主 launcher 默认 Refine=Stride=1、storeudot=true，本 DP5 分支固定 reacf=false，
关闭附加读取/场探针；运行前须与冻结 settings 核对。`$acceptancePath` 指向同一 B/C 的冻结 acceptance。

```powershell
& "$scratch/diagnostic_measure.ps1" -SourceRepoRoot $sourceRepo -Arm $newArm `
  -Integrator dp5 -Rtol 1e-13 -QScale 0 -VelocityScale 0 `
  -ReadbackMode separate -WallSeconds 5400 -AcceptancePath $acceptancePath
& "$scratch/diagnostic_analysis.ps1" -SourceRepoRoot $sourceRepo `
  -Baseline $baselineRun -Reference $referenceRun -Candidate $candidateRuns `
  -AcceptancePath $acceptancePath -ExecutionTimingsPath "$scratch/complete_flow_measurements.jsonl"
```

匹配读取对照仅把 `ReadbackMode` 改为 `merged` 并使用新 arm/run ID；其余科学配置不变。
先等待运行成功封存，再调用独立 analysis，不在前一臂活动时抢占商业软件或修改它的冻结脚本。
wrapper 在独立 launcher 子进程启动前开 Stopwatch、返回后停止；observer 先报告 ready，再按名义 3 s 间隔采样，
并在停止信号后保留末次采样。实际采样周期包含采样开销，原始 UTC/进程出生身份用于核对覆盖，不能当作严格等间隔连续记录。
逐样本对唯一受管 PID 求和 `max(working_set, private)`，最后取样本最大值；准备/封存覆盖与 solver 阶段分别报告。
保存完整流程 JSONL、原始资源采样、测量与公共资源辅助源码的冻结快照及 SHA，随最终 analysis 一并登记；
校验准备、公共 COMSOL 阶段与结束后的租约状态，不能用“调用了 release”代替实际回收证据。

$baselineRun/$referenceRun 必须指向本阶段同一科学实现的完整 success run；先分析校准，再决定候选。
已有 acceptance 仅可通过 `-AcceptancePath` 重用同一 B/R 的合同；当前合格基线/参考为 B/C，比较器会重算，不能复用 A2/B 失败阈值或手工提高阈值。
源、原生变量/场绑定、实际活动键及 rtol 仍由各臂冻结 settings、原生 summary 与三份科学源码身份核对；C 的容量恢复没有改变这些科学字节。
本轮 TOF 仍由修复提取器从保留检测窗估计，未改为 `cpt.st` 原生停止时间；不得把两种事件定义混入校准。
必要小证据包括源/新初态、2001×100 检测 XYZ 窗、400 状态、事件表、索引审计、参数/日志和清理回执。
检测窗名为 `detector_window_particle_states.csv`，是必需的局部重提取证据，不是全飞程轨迹。
源、新初态、状态及原始检测窗使用 17 位 CSV 并检查回读；事件表仍由冻结生产 exporter 写出，不宣称所有 CSV 都逐位往返。

## 7. 生产采用、正式资格与清理边界

N100 相对加严参考通过只支持本模型、本源、本场、本输出配置下的经验一致性。
它不等于物理绝对误差≤1 ps、网格收敛、N1000 分辨率验证或公平 SIMION 配对结果。
本阶段即使获得提速，仍须完成生产合同/构造器门禁、目标样本验证、实际 MPH 保存重开和 GUI Compute 对等检查。
三次空模型属性重开不能替代正式资产上述检查；当前 Formal MPH 不在本阶段被覆盖或晋升。
完整原始负结果与失败状态继续保留，不能因新提取器修复而回写旧 CSV。

终态前精确删除与 inputs `.txt` SHA 相符的 run-local `.m/.py`，记录字节数、SHA 和恢复来源；保留必要小数据。
公共 retention 后写 terminal manifest 并独立验证，释放容量租约；异常时也保留真实失败/中断状态。
一次性源码恢复副本为最终 inputs 的 retained_source__*.txt；原执行版本仍以各 run 的 inputs 为准。完整流程 JSONL、资源侧车及日志均按原字节冻结，不依赖活动 scratch。
最终引用应落到不可变 run inputs/results，而不是活动 scratch、本机临时源码树或已删除 runtime 路径。


[prior]: 20261021__oatof-cpt-performance-controlled-comparison.md
[reg-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_152519__test__comsol__oatof-cpt-fix-regression/summary.json
[reg-native]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_152519__test__comsol__oatof-cpt-fix-regression/results/regression_summary.json
[reg-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_152519__test__comsol__oatof-cpt-fix-regression/run_manifest.json
[reg-cleanup]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_152519__test__comsol__oatof-cpt-fix-regression/temporary_source_cleanup.json
[reg-inputs]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_152519__test__comsol__oatof-cpt-fix-regression/inputs
[a-settings]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_154058__benchmark__comsol__oatof-cpt-fixed-dp5-rtol11-dense-a/inputs/settings.json
[a-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_154058__benchmark__comsol__oatof-cpt-fixed-dp5-rtol11-dense-a/summary.json
[a-native]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_154058__benchmark__comsol__oatof-cpt-fixed-dp5-rtol11-dense-a/results/bench_summary.json
[reg2-native]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_160415__test__comsol__oatof-cpt-fix-regression/results/regression_summary.json
[reg2-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_160415__test__comsol__oatof-cpt-fix-regression/run_manifest.json
[reg2-window]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_160415__test__comsol__oatof-cpt-fix-regression/inputs/detector_window_particle_states.csv
[reg2-detector]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_160415__test__comsol__oatof-cpt-fix-regression/inputs/oatof_extract_detector_arrivals.m.txt
[reg2-inputs]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_160415__test__comsol__oatof-cpt-fix-regression/inputs
[tiny-first-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_193815__test__comsol__oatof-native-event-regression/summary.json
[tiny-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_194330__test__comsol__oatof-native-event-regression/summary.json
[tiny-native]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_194330__test__comsol__oatof-native-event-regression/results/native_event_summary.json
[tiny-inputs]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_194330__test__comsol__oatof-native-event-regression/inputs
[tiny-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_194330__test__comsol__oatof-native-event-regression/run_manifest.json
[tiny-cleanup]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_194330__test__comsol__oatof-native-event-regression/temporary_source_cleanup.json
[tiny-dp5-dense]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_194330__test__comsol__oatof-native-event-regression/results/dopri5_output_0.2_ns.json
[tiny-dp5-sparse]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_194330__test__comsol__oatof-native-event-regression/results/dopri5_output_2_ns.json
[tiny-ga-dense]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_194330__test__comsol__oatof-native-event-regression/results/genalpha_output_0.2_ns.json
[tiny-ga-sparse]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_194330__test__comsol__oatof-native-event-regression/results/genalpha_output_2_ns.json
[tiny-sparse-late]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_194330__test__comsol__oatof-native-event-regression/results/dopri5_output_2_ns_late_states.csv
[tiny-sparse-errors]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_194330__test__comsol__oatof-native-event-regression/results/dopri5_output_2_ns_arrival_errors.csv
[extra-settings]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195033__test__comsol__oatof-native-event-regression/inputs/settings.json
[extra-native]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195033__test__comsol__oatof-native-event-regression/results/native_event_summary.json
[extra-sparse]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195033__test__comsol__oatof-native-event-regression/results/dopri5_output_2_ns.json
[extra-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195033__test__comsol__oatof-native-event-regression/summary.json
[extra-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195033__test__comsol__oatof-native-event-regression/run_manifest.json
[extra-inputs]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195033__test__comsol__oatof-native-event-regression/inputs
[fixed2-settings]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_160603__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol11-dense-a/inputs/settings.json
[b-settings]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_162540__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol12-dense-b/inputs/settings.json
[b-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_162540__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol12-dense-b/summary.json
[b-native]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_162540__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol12-dense-b/results/bench_summary.json
[c-settings]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_165235__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-dense-c/inputs/settings.json
[c-config]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_165235__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-dense-c/run_config.json
[c-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_165235__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-dense-c/summary.json
[c-native]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_165235__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-dense-c/results/bench_summary.json
[c-recovery]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_173121__analysis__python__oatof-cpt-comparison/inputs/diagnostic_c_capacity_recovery.json
[repeat-settings]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_173757__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-dense-c-repeat/inputs/settings.json
[repeat-config]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_173757__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-dense-c-repeat/run_config.json
[repeat-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_173757__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-dense-c-repeat/summary.json
[repeat-native]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_173757__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-dense-c-repeat/results/bench_summary.json
[b12-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_181158__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol12-separate-flow/summary.json
[b12-native]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_181158__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol12-separate-flow/results/bench_summary.json
[b12-log]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_181158__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol12-separate-flow/logs/cpt_native.log
[c13-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_183755__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-separate-flow/summary.json
[c13-native]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_183755__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-separate-flow/results/bench_summary.json
[c13-log]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_183755__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-separate-flow/logs/cpt_native.log
[c13-inputs]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_183755__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-separate-flow/inputs
[merged-summary]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_190832__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-merged-flow/summary.json
[merged-native]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_190832__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-merged-flow/results/bench_summary.json
[merged-log]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_190832__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-merged-flow/logs/cpt_native.log
[cal-flow]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_165143__analysis__python__oatof-cpt-comparison/inputs/complete_flow_measurements.jsonl
[cal-comparison]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_165143__analysis__python__oatof-cpt-comparison/results/comparison.json
[cal-acceptance]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_165143__analysis__python__oatof-cpt-comparison/results/acceptance.json
[cal-deltas]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_165143__analysis__python__oatof-cpt-comparison/results/baseline_vs_reference_event_deltas.csv
[cal-inputs]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_165143__analysis__python__oatof-cpt-comparison/inputs
[cal-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_165143__analysis__python__oatof-cpt-comparison/run_manifest.json
[cal2-flow]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_173121__analysis__python__oatof-cpt-comparison/inputs/complete_flow_measurements.jsonl
[cal2-comparison]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_173121__analysis__python__oatof-cpt-comparison/results/comparison.json
[cal2-acceptance]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_173121__analysis__python__oatof-cpt-comparison/results/acceptance.json
[cal2-inputs]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_173121__analysis__python__oatof-cpt-comparison/inputs
[cal2-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_173121__analysis__python__oatof-cpt-comparison/run_manifest.json
[cal3-comparison]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_180918__analysis__python__oatof-cpt-comparison/results/comparison.json
[cal3-deltas]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_180918__analysis__python__oatof-cpt-comparison/results/candidate1_vs_reference_event_deltas.csv
[cal3-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_180918__analysis__python__oatof-cpt-comparison/run_manifest.json
[cal3-inputs]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_180918__analysis__python__oatof-cpt-comparison/inputs
[cal3-flow]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_180918__analysis__python__oatof-cpt-comparison/inputs/complete_flow_measurements.jsonl
[cal3-capacity]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_180918__analysis__python__oatof-cpt-comparison/inputs/capacity_recovery_20261021_173757__benchmark__comsol__oatof-cpt-fixed2-dp5-rtol13-dense-c-repeat.json
[cal3-observer]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_180918__analysis__python__oatof-cpt-comparison/inputs/diagnostic_repeat_observer_lease_review.json
[cal3-l1]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_180918__analysis__python__oatof-cpt-comparison/inputs/diagnostic_l1_gate.log
[cal4-comparison]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_183517__analysis__python__oatof-cpt-comparison/results/comparison.json
[cal4-deltas]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_183517__analysis__python__oatof-cpt-comparison/results/candidate2_vs_reference_event_deltas.csv
[cal4-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_183517__analysis__python__oatof-cpt-comparison/run_manifest.json
[cal4-flow]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_183517__analysis__python__oatof-cpt-comparison/inputs/complete_flow_measurements.jsonl
[cal4-inputs]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_183517__analysis__python__oatof-cpt-comparison/inputs
[cal4-repeat-review]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_183517__analysis__python__oatof-cpt-comparison/inputs/diagnostic_repeat_final_review.json
[cal4-selftest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_183517__analysis__python__oatof-cpt-comparison/inputs/diagnostic_measure_child_selftest.report.json
[cal5-comparison]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_190745__analysis__python__oatof-cpt-comparison/results/comparison.json
[cal5-deltas]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_190745__analysis__python__oatof-cpt-comparison/results/candidate1_vs_reference_event_deltas.csv
[cal5-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_190745__analysis__python__oatof-cpt-comparison/run_manifest.json
[cal5-flow]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_190745__analysis__python__oatof-cpt-comparison/inputs/complete_flow_measurements.jsonl
[cal5-inputs]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_190745__analysis__python__oatof-cpt-comparison/inputs
[cal6-comparison]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_193737__analysis__python__oatof-cpt-comparison/results/comparison.json
[cal6-merged-deltas]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_193737__analysis__python__oatof-cpt-comparison/results/candidate2_vs_reference_event_deltas.csv
[cal6-pair-deltas]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_193737__analysis__python__oatof-cpt-comparison/results/candidate1_vs_candidate2_event_deltas.csv
[cal6-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_193737__analysis__python__oatof-cpt-comparison/run_manifest.json
[cal6-flow]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_193737__analysis__python__oatof-cpt-comparison/inputs/complete_flow_measurements.jsonl
[cal6-inputs]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_193737__analysis__python__oatof-cpt-comparison/inputs
[native-distribution]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_180918__analysis__python__oatof-cpt-comparison/inputs/diagnostic_native_step_distribution.json
[native-distribution-source]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_180918__analysis__python__oatof-cpt-comparison/inputs/diagnostic_native_step_distribution.py
[status-doc]: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.02.html
[freeze-doc]: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.38.html
[stop-time-code]: ../../comsol/run_fixed_particle_retrace.m
[final-inputs]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195714__analysis__python__oatof-cpt-comparison/inputs
[final-comparison]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195714__analysis__python__oatof-cpt-comparison/results/comparison.json
[final-manifest]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195714__analysis__python__oatof-cpt-comparison/run_manifest.json
[final-l1]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195714__analysis__python__oatof-cpt-comparison/inputs/diagnostic_final_l1_gate.log
[final-l2]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195714__analysis__python__oatof-cpt-comparison/inputs/diagnostic_l2_gate_r02.log
[final-budget-cloc]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195714__analysis__python__oatof-cpt-comparison/inputs/diagnostic_budget_cloc_committed.log
[final-cpt-cloc]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195714__analysis__python__oatof-cpt-comparison/inputs/diagnostic_cpt_cloc_worktree.log
[final-native-review]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195714__analysis__python__oatof-cpt-comparison/inputs/diagnostic_native_event_final_review.json
[final-extra-review]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195714__analysis__python__oatof-cpt-comparison/inputs/diagnostic_native_extra_steps_review.json
[final-b12-review]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195714__analysis__python__oatof-cpt-comparison/inputs/diagnostic_b12_separate_final_review.json
[final-separate-review]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195714__analysis__python__oatof-cpt-comparison/inputs/diagnostic_c13_separate_final_review.json
[final-merged-review]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_195714__analysis__python__oatof-cpt-comparison/inputs/diagnostic_c13_merged_final_review.json
