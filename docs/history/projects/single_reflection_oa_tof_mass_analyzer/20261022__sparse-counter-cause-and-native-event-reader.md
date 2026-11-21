# 稀疏 Counter 因果对照与原生事件读取候选

DOC_STATUS: ARCHIVED_READ_ONLY

完成日期：2026-10-22；源码基线 `68047deb6f45732902f0b97fc8c9db6a413ba9f5`。
环境为 COMSOL 6.4 Build 293、MATLAB R2025b。本记录接续[五案验证](20261022__native-event-readback-and-counter-validation.md)，
保留全部失败；不加载整机 MPH、不求静电场、不改变生产源码、数值合同或 Formal。

## 已关闭的操作问题

1. **稀疏 Counter 问题已定位到输出保存及边界归属链。** 同一已存解上改用真实停止时刻、
   末次解索引或全局 Nsel／alpha 均不能修复 58/100。原生停止时间、事件位置和匹配的边界环境查询
   却全部正确。保留原 16 时刻，仅插入 20.5 ns，即恢复 Counter 100/0 与晚期平面位置。
   保存的末次 U 也随之变化，不能只归因于导出或 Counter 表达式；内部分类公式未识别。
2. **得到不加密输出的原生终态读取候选。** Wall 重赋值五个 AuxiliaryField，GA／Newtonian
   组合在原稀疏输出下通过全目标 N100、两真实壁面 50/50 和同配置重复。终态一次读取保留所有 ID，
   区分目标事件与其他壁面停止。它是本小模型的候选方法，尚未接入整机生产提取器。
3. **重复性通过。** 两次 50/50 运行的源、初始状态和终态 CSV 字节 SHA 相同，全部终态通道逐位差为零；
   时间／位置门仍为 1 ps／1 μm。两次保存重开后 13 通道×100 粒子逐位一致。
4. **成本边界明确。** 两次 50/50 的完整诊断流程为 87.2440／86.1791 s，外层采样峰值为
   3.207／3.252 GiB。三坐标读取局部约快 2.51／2.87 倍，不是整机总提速；固定字段返回量 O(N)
   也不是已测得 CPU 随 N 线性增长。

## 模型、源身份与判据

固定源 SHA-256 为 `70892128AF5CB5FB8647228E3718EAB12B4FCB72B9ED2BCC28578E3A6DCD4976`，
来自 `085813` 的 `analytic_release.txt`，全部新运行冻结此输入。Cause 探针重新生成的文件还逐字节核验相同。
显式无表头、tab、17 位数字读回 100×6；自动格式探测曾只读成 100×1，不用它构造 oracle。

原盒为 2×2×1 mm、72 tet；100 粒子 XY 为 ±0.2 mm 的 10×10 网格，vz=−27500 m/s。
各粒子解析到达时间从实际冻结的 z／速度计算，约为 `(20.1+0.003*(源行−1)) ns`。
质量 524 Da、单正电荷、零电场，无碰撞或空间电荷。z=0 为 Freeze；结束 30 ns。
双壁面对照把盒沿 x=0 分成两块并保留内部面，实际 82 tet；源无 x=0 粒子且 vx=0，物理飞行不变。
负 x 目标面为边界 3，正 x 其他 Freeze 面为边界 8，各接收 50 颗。未重新抽样或删粒子。

固定 rtol=1e−12、初始内部步 0.1 ns、最大内部步 2 ns、活动 free、tout=tlist，状态及 StoreExtra 开启。
稀疏表为 0:2:30 ns；单插点臂保留 COMSOL 解析的原 16 个 binary64 时刻，再增加 20.5 ns。
DP5 配 NewtonianFirstOrder；GA 配 Newtonian。比较改变的是此数值组合，不能将差异单独归因于某一项。

每次先以初始六维状态与 pidx 恢复 source 行；全部 100 个 st、fs 必须通过。
目标辅助标记精确为 1、辅助时刻与解析／原生 st 差不超过 1 ps、XYZ 差不超过 1 μm；
其他壁面的五个辅助字段必须全零，不能把其他停止当检测到达。Counter 与候选读取分别判定。
极小解析误差是此常速夹具的浮点结果，不是仪器绝对时间精度。

## 逐案结果与保留的失败

| run 短号 | 唯一主要控制／诊断 | 结论 | run 终态 |
|---|---|---|---|
| [092603][cause] | 同一 DP5 稀疏解，多种只读查询 | st／事件 XYZ／匹配边界正确；rL 持续 58/0；all-solnum 返回结构处理失败 | failed |
| [093224][aux-first] | 五辅助变量终态记录首测 | 晚期五字段全零；不能作为事件读取 | failed |
| [093740][insert] | 仅插入 20.5 ns，另保留完整返回结构 | Counter 100/0、晚期位置通过，原生事件不变 | success |
| [094534][aux-query] | 原稀疏表，actual st／偏移查询 | exact-st 辅助记录全部正确，晚期仍零；at 组合被拒 | failed |
| [095221][intersection] | 官方平面求交，标量表达式 | none=0；specifiedtimes=100 行／96 ID；proportional=16 ID | failed |
| [100144][all-extra] | 增加接口实际列出的 all 额外数据模式 | 200 行／100 ID，每颗两条完全相同主记录；目标通道无法配齐 | failed |
| [100419][ga] | GA／Newtonian，原稀疏表 | 100 个目标辅助事件通过，Counter 100/0 | success |
| [101249][split] | 同源 GA，目标／其他壁面 50/50 | 目标 50、非目标五字段全零、全部 st/fs 正确，Counter 50/50 | success |
| [101442][repeat] | 同配置完整重建及求解重复 | source／initial／terminal CSV 字节相同；全部终态通道逐位零差 | success |

`092603` 的失败来自调用方读取 `pd.t`，不等于 COMSOL 未返回数据。后案表明
`solnum='all'` 与再加 `times='on'` 都成功返回 8×17×100 表达式值，但没有 t；数值 `solnum=1:17`
返回逐值相同表达式并带 t／solnum。旧 failed 不回写，新版将 API、原始返回和规范化阶段分别记录。

`093224` 首版 benchmark 误把候选的全零 Aux XYZ 当参考：终态自比较通过无科学意义，
原生 XYZ 相对它差 0.2 mm 也不是原生绝对误差。`094534` 起改用冻结源的独立 oracle，并增加路径间一致门。
两案早期 persistence 的 failed 包含 MATLAB 内即时删除未确认；数值往返实际一致。
后续分别记录数值持久性和清理责任，实际 MPH 删除以退出后的 compact 收据为准，旧字段保持原样。

### Counter 的因果证据

`092603` 的 default、late t、solnum=end、actual-st 均为目标 58／其他 0；全局 Nsel=58、alpha=0.58。
actual-st 对角配对的全部 100 个 XYZ 最大 |z|=6.776263578034403e−18 mm，
`bndenv(cpt.pcnt_det.Ob)` 全为 1、边界号全为 3；不能把 N×N 非匹配位置的 NaN 当丢粒子。
原生 st 最大解析差 3.308722450212111e−24 s。两次运行的 native-st 匹配 XYZ／st／fs 逐项相同。

单插时刻后，42 个 rL 从 0 变 1，晚期坐标回面。跨运行 U900 有 112 项不同，最大逐项差
1.09175e−5；没有冻结 DOF 映射，不给这些槽位另命名。各运行自身只读前后 U900 均逐位不变。
两份原生日志末 Step17／Res119／Tfail0 相同，但中间日志节流不同，不能称全部内部步序相同。
20.5 ns 是本到达窗的诊断控制，不是通用安全输出间隔或替代事件验收的规则。

### 辅助记录与其他读取方法

五字段均为零初值、R=0 的官方 AuxiliaryField；目标 Wall 通过 caux_aux1…5／daux_aux1…5
重置为命中标记、t 和 XYZ。具体设置见[项目操作说明](../COMSOL.md#原生辅助变量记录候选)。

| DP5 稀疏查询 | 原始 hit 范围 | 辅助时间最大解析差 | 辅助 XYZ 最大差 |
|---|---|---|---|
| actual st | 全部 1 | 3.309e−24 s | 6.776e−18 mm |
| st+1 ULP | 0.9999999999999979…0.9999999999999982 | 4.301e−23 s | 4.163e−16 mm |
| st+1 fs | 0.9999993761696816…0.9999994736842104 | 1.272e−14 s | 1.248e−7 mm |
| late／solnum=end | 五字段全部 0 | 无有效事件 | 无有效事件 |

后两种偏移的“严格等于 1 的数量为零”不表示原始值为零；不能取整来制造二元标记。
这证明重赋值实际发生，未证明晚期读取可靠，也没有官方依据说 Freeze 禁止重赋值。
GA／Newtonian 的目标辅助时刻最大解析差为 1.9852334701272664e−23 s，XYZ 为
2.7755575615628914e−17 mm；两壁面与重复均保持，并未增加输出点。

其他快速关闭的接口问题：

- evaluate=1 返回 ID76，evaluate=59 返回 59 个非连续 ID，向量 [59 1] 被拒；它是数量抽取，不能当任意 ID 选择器。
- `at(cpt.st,qx)` 被拒为 nonscalar／out-of-range；官方标量 at 不能直接推广为逐粒子时间一次查询。
- 原生 Particle 数值节点 expr 只接受单字符串，不能照搬 mphparticle 的多表达式 cell 合同。
- IntersectionPoint3D 的 all 在 DP5 案返回 200 条主记录，每颗两条的 ID／t／st／XYZ 逐位相同且 t=st，
  与独立 native-st 查询一致；但目标表达式仅返回 116 个标量，pidx 前后各 200，无法逐 ID 配对。
  不把 116 个 1 推断为全部目标通过，也不按 ID 随意去重。原始一对一门仍 false；本轮不采用它作最终事件读取。

## 完整流程、内存与局部读取成本

全部计算通过公共 R2025b 入口串行，COMSOL 2 核、8 GiB、600 s；最大模型 82 tet。
外层 Stopwatch 覆盖准备、容量、排队、启动、Compute、读取、封存和资源释放。
外层 3 s 名义采样包含 wrapper／observer／inner；内层 1 s 名义采样为 launcher 后代。
均为按 PID 求和的 max(working set, private) 离散观测，不是连续物理内存峰值，采样调用还产生额外间隔。
排队未独立精确计时，包含在完整流程；不以完整流程减 Compute 冒充排队。

| run | Compute s | 完整流程 s | 内层峰 GiB | 外层峰 GiB |
|---|---:|---:|---:|---:|
| 092603 | 2.421621 | 343.002 | 4.830 | 3.233 |
| 093224 | 1.025426 | 205.269 | 3.119 | 3.605 |
| 093740 | 0.822908 | 73.931 | 2.789 | 3.285 |
| 094534 | 1.641370 | 241.796 | 3.102 | 3.606 |
| 095221 | 1.034093 | 84.112 | 2.898 | 3.451 |
| 100144 | 0.994739 | 81.817 | 3.015 | 3.505 |
| 100419 | 1.045233 | 92.192 | 3.326 | 3.817 |
| 101249 | 0.929821 | 87.244 | 2.750 | 3.207 |
| 101442 | 0.952426 | 86.179 | 2.771 | 3.252 |

首次较密内层采样观测到 4.830 GiB，高于其外层较疏采样；两者并不矛盾，不能丢弃较高观测。
不同诊断查询量、准备和排队不同，不能用表中不同行的耗时比宣称整体加速。

同一个 GA 已存解，每条路径先 warmup 一次，再做七对交替顺序读取，全部对独立 oracle 与配对门：

| 工况 | N×N 三坐标中位 s | 终态 Aux 三坐标中位 s | 局部比值 |
|---|---:|---:|---:|
| 全目标 100419 | 0.2765742 | 0.0913416 | 3.028× |
| 50/50 101249 | 0.3003442 | 0.1196577 | 2.510× |
| 同配置重复 101442 | 0.2824362 | 0.0982575 | 2.874× |

两者各一次 MATLAB 读取调用，返回 30100／301 个 numeric doubles（240800／2408 B）；
100 倍返回量缩减不是 100 倍耗时缩减。这里只测三位置字段；split 的参考位置按预声明 source mask
将非目标行映射为无事件的零值，全部 100 行保留。此计时不包含完整目标识别、求解和封存；
完整终态读取还包含 pidx、hit、时间、状态及诊断字段，不能冒用三坐标计时。
Aux 增加了五个粒子依赖变量，GA 案末 U 为 1100 项；未测得新方法的整机净收益或大 N CPU 标度。

## 复现、官方依据与保留

各案 inputs 保存对应版本的 `.m.txt`、`.ps1.txt`、task、科学 helper、原 release、官方证据 JSON 与启动入口。
[完整流程发布包][flow]保存全部 11 次测量及来源快照，其中 9 次真实小模型、2 次启动前容量拒绝。
发布器重新核对采样 SHA、区间覆盖和内存峰值；它的 success 不等于各科学 run 成功。

复现最终 50/50：先核对 [101442 inputs][repeat-inputs] 和发布包 manifest，再将
`diagnostic_aux_event_regression.m.txt/.ps1.txt`、`diagnostic_aux_event_task.m.txt`、
`diagnostic_intersection_readback.m.txt` 恢复为同名去掉末尾 .txt 的文件；
将官方证据恢复为原 source leaf `diagnostic_native_aux_api_evidence.json`、`diagnostic_intersection_api_evidence.json`。
测量包的 `full_flow_20261022_101439_722__native-ga-split-repeat__diagnostic_counter_cause_measure.ps1.txt`
及同前缀的 `diagnostic_memory_monitor.ps1.txt` 分别恢复为 `diagnostic_counter_cause_measure.ps1`
和 `diagnostic_memory_monitor.ps1`，不保留 full_flow 前缀。使用任务专属 scratch 目录，恢复后核对 SHA。
原公共科学 helper 和 085813 release 必须存在，runner 会再次冻结及核验；不复用旧 run_id。
此冻结 PS 的 MainRepoRoot 固定为 `C:/Users/Liao/mass_spectrometry/simulation_repo`；SourceRepoRoot
只指定科学 helper 来源，不重定向公共启动器、依赖或 artifacts。下列命令限定于本机此布局，不是任意目录的可移植入口。

```powershell
pwsh -NoProfile -File <恢复目录>/diagnostic_counter_cause_measure.ps1 -InnerScript <恢复目录>/diagnostic_aux_event_regression.ps1 -SourceRepoRoot C:/Users/Liao/mass_spectrometry/simulation_repo -Arm native-ga-split-reproduction -ProcessorCount 2 -WallSeconds 600 -MemoryLimitBytes 8589934592 -UseGenAlpha -SplitDetector
```

单平面去掉 SplitDetector；DP5 对照另去掉 UseGenAlpha。复现 Counter 单插点使用 [093740 inputs][insert-inputs]
对应 cause 三源，将官方 Counter 证据恢复为 `diagnostic_counter_api_evidence.json`，测量器传 InsertArrivalOutput。
所有脚本均为冻结的一次性诊断，
不是新增公共 CLI；当前 source 科学 helper 若与冻结身份不同，不把其输出冒充本记录复现。

官方支持与本机资料身份记录在各案 `official_auxiliary_api_evidence.json.txt`、
`official_intersection_api_evidence.json.txt`，包括 [Wall](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.04.html)、
[Auxiliary variables](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_modeling.05.15.html)、
[Counter](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_modeling.05.20.html)、
[Particle Evaluation](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_results.52.119.html)
和 [IntersectionPoint3D](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_results.52.083.html)。
在线 Intersection API 页首类型名误拼由安装官方模型 `alvarez_lens.mph` 的实际类型消歧，未猜 API。

两次容量拒绝均未创建科学 run 或启动 Compute，原始数字以明确标记的工具观察转录保留。
预留先由文本量估算调整，再由实际约 5.9 MB compact run、约 1.8 MB 临时 MPH 支持最终 16 MiB 预算；
未改变全局门禁、账本目标、源或精度。另一轮只读 maintenance 规划未删除任何对象。
七个临时 MPH 由公共 compact 收据删除，共 12388725 B。104 个 scratch 文件逐项 SHA 匹配受管 inputs 后
删除，共 1923038 B，空目录亦删除，必要代码与负结果均可恢复。清理窗口卷可用空间增加 2093056 B，
该数含分配粒度及其他并行写入影响，不等同于逻辑释放量。

## 仍未授予的资格

已明确拒用 DP5 稀疏晚期辅助表、数量抽样冒充 ID、逐粒子 at 及未闭合身份的平面交点表。
Counter／DP5 保存链和 Intersection 目标通道长度的内部实现仍需供应商解释；本轮已有可操作使用限制，
不靠猜内部公式继续无界扫描。未验证曲面、再次穿越、Disappear、碰撞、RF／脉冲、大 N 标度、
仪器场与积分收敛、正式 MPH 的 GUI Compute 或整机整体提速；生产接入须另建受控验收，不自动替换现有提取器。

[cause]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_092603__test__comsol__oatof-counter-cause/run_manifest.json
[aux-first]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_093224__test__comsol__oatof-auxiliary-planar-event/run_manifest.json
[insert]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_093740__test__comsol__oatof-counter-cause-arrival-output/run_manifest.json
[aux-query]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_094534__test__comsol__oatof-auxiliary-planar-event/run_manifest.json
[intersection]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_095221__test__comsol__oatof-auxiliary-planar-event/run_manifest.json
[all-extra]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_100144__test__comsol__oatof-auxiliary-planar-event/run_manifest.json
[ga]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_100419__test__comsol__oatof-auxiliary-planar-event-ga/run_manifest.json
[split]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_101249__test__comsol__oatof-auxiliary-planar-event-ga-split/run_manifest.json
[repeat]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_101442__test__comsol__oatof-auxiliary-planar-event-ga-split/run_manifest.json
[flow]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_101718__analysis__python__oatof-counter-cause-flow/run_manifest.json
[repeat-inputs]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_101442__test__comsol__oatof-auxiliary-planar-event-ga-split/inputs
[insert-inputs]: ../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261022_093740__test__comsol__oatof-counter-cause-arrival-output/inputs
