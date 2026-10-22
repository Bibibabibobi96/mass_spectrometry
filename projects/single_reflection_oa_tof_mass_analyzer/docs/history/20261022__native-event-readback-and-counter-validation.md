# 原生事件回读、额外碰壁数据与 Counter 的小模型验证

DOC_STATUS: ARCHIVED_READ_ONLY

完成日期：2026-10-22。源码基线为 `2f04afadd64b55854c040bf2836486d3183a220e`，执行环境为
COMSOL 6.4 / MATLAB R2025b。本记录冻结五次独立 N100 小模型，不加载 OA 整机 MPH、不求静电场，
不改变 Formal、生产配置或既有 acceptance。它补充[上一阶段记录](20261021__oatof-cpt-fixed-policy-reference-and-full-flow.md)，不改写旧负结果。

## 已关闭的问题

1. **普通时刻库存不包含额外碰壁时刻，不等于 StoreExtra 没有作用。** 本例开关两臂的
   `mphsolinfo(...).solvals`、`sol1.getPVals()` 和不传 `t` 的 `mphparticle` 都只返回同一组 16 时刻；
   但开启后在已知碰壁时刻查询 XYZ，结果回到浮点余量。不能从库存条数推断额外数据是否参与查询。
2. **实际读出的停止时间可用于本例的位置查询。** 开启状态与额外碰壁存储后，用晚期 `cpt.st`
   向量作为 `mphparticle` 的 `t`，按粒子身份配对，其平面位置最大误差约 `6.78e-18 mm`。
   查询不再依赖解析答案；解析式仅用于独立核验停止时间。此结论仍限于恒速、单个终止平面。
3. **Counter 的创建时机不能解释稀疏结果。** 求解后添加并 `updateSolution()` 与求解前创建，
   目标 `rL` 都只包含 58/100，非命中对照均 0/100，故两案整体 FAILED。不能把原生停止时间正确
   或 update API 成功当作边界身份完整。
4. **仅改变输出表即可改变本例的 Counter 与坐标提取结果。** 相同前置 Counter、活动 free、
   源、网格和时间积分设置下，输出从 2 ns 改为 0.2 ns 后，Counter 为 100/0，坐标提取为
   100 个有效事件／命中并通过原解析 1 ps 门。稀疏负结果保留；0.2 ns 不是所有模型的安全默认值。

这里没有识别 Counter 的内部算法或漏计根因，也没有证明两种输出表的全部内部积分时序相同。
操作上的结论已经明确：当前稀疏读取链不具备本例完整检测资格，不能用 Counter 直接补齐被拒事件。

## 模型、唯一变量与判据

五案均为 2×2×1 mm 真空盒、72 个四面体；100 粒子沿 −z 以 27500 m/s 常速飞向 z=0 Freeze。
源与上一阶段 `195033` 案完全相同：解析到达时间约为 `(20.1+0.003*(ID−1)) ns`，实际 oracle 从
冻结 release 的二进制数值计算 `z_initial/abs(vz)`，不以十进制显示值替代输入。
结束 30 ns，晚期回读 28/30 ns。无碰撞、无空间电荷、无静电场求解。

固定 DP5 / NewtonianFirstOrder、活动 `free`、`tout=tlist`、rtol=1e-12、初始内部步 0.1 ns、最大内部步
2 ns，状态存储开启；Study.run 前后均实际回读。时间接受门为解析停止时间差不超过 1 ps；
位置门仍为原近面容差 1 μm，不因失败放宽。Counter 额外要求目标包含全部 100 ID、负对照包含 0 ID。

| 冻结案 | StoreExtra | 输出间隔 | Counter 创建 | 原生时间门 | 固定输出坐标提取 | 目标／负对照 rL | run 状态 |
|---|---|---:|---|---|---|---|---|
| [A：084937][a] | false | 2 ns | 无 | PASS | 0/100，FAIL | 不适用 | success；只通过回读诊断 |
| [B：085153][b] | true | 2 ns | 无 | PASS | 0/100，FAIL | 不适用 | success；只通过回读诊断 |
| [C：085508][c] | true | 2 ns | 求解后 | PASS | 0/100，FAIL | 58/0，FAIL | failed |
| [D：085813][d] | true | 2 ns | 求解前 | PASS | 0/100，FAIL | 58/0，FAIL | failed |
| [E：085959][e] | true | 0.2 ns | 求解前 | PASS | 100/100，PASS | 100/0，PASS | success；本例通过 |

A/B 的 `passed_scope` 明确仅为读取完成、活动设置和原生解析时间门；`coordinate_extractor_pass=false`
单独保留，不能将这两个 success 称为检测器通过。C/D 正常完成真实 Compute 和导出，但因冻结判据失败
以 failed 封存，没有重试覆盖或删除未入选粒子。

## 原始数据支持的细节

五案原生停止时间最大解析差均为 `3.308722450212111e-24 s`。A/B 的默认时刻、两种 getter 与请求表
均为 16 点；晚期固定 t 坐标留在面前约 0.00275…0.0109175 mm，全部 fs=2，冻结后 vz 仍为 −27500 m/s。
A 在解析时刻查询的最大 |z| 仍为 0.0109175 mm，B 则约 `2.68e-17 mm`。因此在解析时刻查询是
有效的机制探针，但不能作为未知模型的实际事件算法。

C/D/E 另用实际读出的停止时间查询；`native_stop_matched_positions.csv` 与完整查询数组的逐 ID
对角一致，最大 |z| 约 `6.78e-18 mm`。此诊断一次查询全部 N 个时刻和全部 N 粒子，形成 N×N 数组，
只用于有界 N100 验证，不是已优化的生产读取器；扩大 N 前须控制批量与数据量。

C/D 的 Counter=0 恰为 ID59…100；其源位置、到达时间和晚期位置偏差也随 ID 变化，不能从该相关性
断言内部原因或反推通用容差。E 的时刻库存为 151 点，晚期 |z| 约 `6.78e-18 mm`，原坐标提取器的
最大解析时间差 `5.260868695837256e-22 s`。D/E 的原生日志最终均 Step=17、Res=119、Tfail=0；
这只是打印的末计数相同，不证明所有内部步与失败尝试时序逐值相同。

Counter 使用同一 `rel1`、`std1/time1`，目标/负对照分别为边界 3/4，所有属性和选择均回读。
C 中先求解一次，再添加 Counter 并调用 `sol1.updateSolution()`；D/E 先创建 Counter、只求解一次，
之后执行同样的 update/readback。前后 XYZ/st/fs 与时刻 CSV 可独立比对，均逐位不变。
末次 `getU()` 向量逐位不变由探针实时 `isequal` 记录；未成对保留完整 U，不能声称独立离线重算了该项。

## 官方支持路径

查阅日期均为 2026-10-22，目标版本 6.4：

- [mphparticle](https://doc.comsol.com/6.4/doc/com.comsol.help.llmatlab/llmatlab_ug_ref.9.51.html)：默认读取保存时刻，或以 `t` 请求查询；没有保证全部绘图专用额外数据成为全局时刻库存。
- [状态与额外碰壁数据](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.02.html)、[Wall](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.04.html)：区分停止状态、输出与 Freeze 保留撞壁速度的语义。
- [Particle Counters](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_modeling.05.20.html)：`rL` 是选中区域的逐粒子入选逻辑，不是最后停止边界编号；只生成变量，可更新已有解。
- [Solution API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.58.html)：采用支持的 `updateSolution()`，没有为计数另造追踪或擅自重算。

本机官方示例 `applications/Particle_Tracing_Module/Charged_Particle_Tracing/sensitive_high_resolution_ion_microprobe.mph`
只读检查，未加载／求解：其模型版本 6.4.0.257，SHA-256 为
`54C825A504BA8C093BB8BB2DE203389D2212D7AE2F41E004D2247E55702FE0C0`。
它明确提供 `ParticleCounter` 类型及 ParticleSelection/ReleaseFeature/StudyStep 字段；本次采用该路径。
官方模型出处与 API 检索记录冻结在 C/D/E 的 `inputs/official_counter_api_evidence.json.txt`。
官方支持与本例实测负结果并列保存，不将文档存在当作任意读取链已合格。

## 资源、身份与复现

每案串行、2 线程、600 s 外部执行预算、8 GiB 受管进程族上限；均未超限。A/B 预留 16 MiB、C/D/E
预留 32 MiB artifact 新写入预算，无 MPH 保存。以下时间是公共 launcher 启动至返回的受管执行区间，
不含 run 准备与最终封存；**不是完整流程提速试验，不作速度比或稳定性能声明**。

| 案 | Compute / s | 受管执行区间 / s | 进程族采样峰值 / B | 样本数 |
|---|---:|---:|---:|---:|
| A | 2.078741 | 108.0741776 | 2817552384 | 85 |
| B | 0.8629795 | 51.7970948 | 3073613824 | 40 |
| C | 0.9857393 | 56.0416553 | 2921353216 | 41 |
| D | 0.9647021 | 51.4808408 | 3026341888 | 39 |
| E | 0.8888845 | 51.8675069 | 3281444864 | 38 |

峰值为公共 launcher 后代逐 PID `max(working_set, private)` 求和，名义 1 s 采样间隔包含采样开销；
不含外层 runner，不是唯一物理页或连续峰值。原始 JSONL 已保留，独立复核重算峰值与摘要一致。
五份 manifest 共 216 条身份记录均独立复核字节数/SHA；源 CSV 与 release 文本各案相同，
也与上一阶段 195033 源完全相同。A/B 仅 StoreExtra 不同；C/D 仅 Counter 创建时机不同；D/E 仅输出表不同。

复现步骤：

1. 按仓库入口读取规则、项目状态及公共工具链要求；先核对来源 manifest，不执行已删除的 scratch 路径。
2. 从所选案 `run_config.json` 的 `parameters.source_identities` 恢复三份一次性脚本及辅助 JSON，
   使用每项原 source 的文件名与冻结 `.txt` 字节，不能把 C/D/E 的 helper 混用。
   两个科学 helper 也须从同案 inputs 恢复到独立 SourceRepoRoot 下原项目/comsol相对位置。
3. 核对当前公共 launcher 与冻结输入 SHA；不一致时登记新的复现实验及依赖差异，不称原样复现。
   商业执行仍必须走当前受管公共入口，不绕过容量或主机门禁。
   一次性 PS 内部冻结了原主仓库部署路径；原样运行要求该路径及其 `.venv`／公共入口仍存在。
   `SourceRepoRoot` 只选择两个科学 helper 的来源，不重定向主仓库或 artifacts。换机器／路径时须显式修改
   恢复副本的 `MainRepoRoot` 并登记新源码身份和部署差异，不能声称执行字节未变。
4. 在任务内声明的 scratch 执行对应 `diagnostic_*_regression.ps1 -SourceRepoRoot <已恢复根> -ProcessorCount 2 -WallSeconds 600`。
   A/B 用同一 native-event 脚本，B 追加 `-StoreExtraWallSteps`；C/D/E 用各自命名脚本，其 StoreExtra 已冻结为 true。
5. 运行器自动产生新 run ID，冻结输入，清理运行时源码并封存。C/D 的预期是科学 FAIL，不能以返回成功作为复现要求。
   分别检查原生时间门、坐标提取、Counter、原始 CSV、资源及 manifest；后续续算仍使用新身份。

首次尝试在求解前因五个历史 MR checkpoint 复核逾期被容量门禁阻断，未建立科学运行。确认无 writer、
无消费者／重叠租约且全为轻量证据后，沿公共 `seal-checkpoint` 关闭其 writing 状态；119 个原文件
的哈希不变，科学状态仍 checkpoint，释放 0 B，续算须新 run。回执冻结在各案
`inputs/diagnostic_capacity_recovery.json.txt`，不可将该回执当作新的批量恢复命令。

各案运行时临时代码已按自身 cleanup 回执清除；最终另核对并删除 scratch 中 14 个可精确恢复的文件，
合计 244683 B，及空 scratch 目录。所有必要字节仍由各案 inputs/manifest 保存；没有新增长期源码或配置。

## 保留的未闭合问题

本例没有授予曲面、多壁面、再次穿越、Disappear、碰撞、RF/脉冲或整机检测资格；Counter 的内部
漏计机制仍未识别。本轮已完成有界的接口与输出敏感性结论，不继续无新判据扫描。
生产采用仍须先绑定功能预算，验证目标事件与样本、空间／时间收敛、保存重开及 GUI Compute。
未复算大型模型，也没有新的整机加速或 Formal 声明。

[a]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_084937__test__comsol__oatof-event-readback/run_manifest.json
[b]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_085153__test__comsol__oatof-event-readback/run_manifest.json
[c]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_085508__test__comsol__oatof-counter-readback/run_manifest.json
[d]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_085813__test__comsol__oatof-counter-precompute-readback/run_manifest.json
[e]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_085959__test__comsol__oatof-counter-dense-readback/run_manifest.json
