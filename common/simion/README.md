# SIMION公共实现层

本目录保存不含器件身份、专用坐标系或运行模式假设的SIMION公共实现。`particle_source.py`接收已经由
上游适配器转换到工作台语义的 beam 或逐粒子状态并生成 FLY2/Lua 文本；多极杆的 ION11 和 canonical 字段映射
仍由 `common/multipole/simion_particle_source.py` 负责。

## 按任务导航

| 任务 | 入口 |
|---|---|
| 序列化几何、检查孔拓扑 | [几何与 Workbench](#几何与-workbench) |
| 缓存、物化完整 PA family | [PA 缓存与工作点](#pa-缓存与工作点) |
| 长 PA 输入与缓存写隔离 | 先读[跨项目边界](../../docs/SIMION_REFERENCE.md#长pa输入路径)，再读 [API 与证据](#长路径输入-api与证据) |
| 并发、资源画像及中断续算 | [调度与恢复](#调度与恢复) |
| 查旧 Fly 入口审计 | [只读历史入口](PRODUCTION_FLY_AUDIT.md) |

## 几何与 Workbench

[`gem_primitives.py`](gem_primitives.py)只序列化明确传入的有限坐标与尺寸，提供
`centered_box3D`和沿`z`轴的`cylinder`文本，不选择电极、器件尺寸、孔径、网格或坐标变换。
独立正交加速器和连接装配共用这一层；器件CSG、侧孔与两／三区电极组合由加速器项目拥有。

项目间连接的矩形开孔统一调用[`aperture.py`](aperture.py)：机械宽、高任一小于一个cell时失败关闭；
非整数cell倍数或孔边缘未落在网格节点时保留机械尺寸并输出机器可读离散警告；GEM减材固定使用
`exclude_shape_inside_or_on_v1`，不得用隐藏epsilon扩大机械孔。编译或缓存PA后，所有生产消费者还必须
通过[`aperture_topology_support.ps1`](aperture_topology_support.ps1)调用
[`verify_aperture_topology.lua`](verify_aperture_topology.lua)，确认法兰厚度方向至少有一条贯通非电极节点列，
并确认孔外四侧接地guard在法兰内部厚度节点仍存在（两端面连接相邻真空域，不作为侧壁判据）；FAIL禁止Fly。该入口面向仓库内所有未来SIMION项目连接，不绑定多极杆、
oaTOF、single-flight或具体电极编号。

`surface=fractional`只提高非对齐表面的场与边界表达精度，不保证连续几何精确，也不能替代真实PA拓扑审计
或网格敏感性验证。本层不选择PA/IOB和物理参数；商业进程仍由项目runner按统一预算与串行规则启动。

所有新建SIMION Workbench必须从[`assets/iob_instance_seeds/`](assets/iob_instance_seeds/README.md)
中与实际PA实例数一致的干净GUI种子派生。该公共目录提供1--10槽连续容器和唯一占位PA；派生器必须替换每一个槽，
不得创建空槽或保留占位实例。种子只用于生成运行目录或正式交付目录中的派生IOB，绝不原地修改。

## PA 缓存与工作点

[`pa_family_cache.py`](pa_family_cache.py)提供完整静电PA-family的内容寻址复用：调用方必须给出完整的
数值身份（resolved geometry、GEM、basis namespace、xyz网格、网格相位、surface、SIMION可执行文件身份、
Refine策略和构建器身份）以及精确文件清单。它只缓存并逐字节核验`.pa#`、`.pa0`和basis数组；新发布的
generation payload和manifest同时设为文件系统只读。同一身份命中时以原子复制物化到新的run-local目录，
并明确把私有副本恢复为可写；任一缺失、额外、哈希不同或损坏generation均失败关闭。IOB、Fast Adjust
工作点、程序和Fly2从不作为缓存几何真值：每个run必须重新装配、重新保存并在本次manifest中绑定。该层不理解
器件、坐标或电极含义，项目仍拥有其ID和几何合同。发布过程按cache key持有短生命周期目录锁；并发发布同一
key只允许一个写者，遗留锁失败关闭并需按artifact保留规则审计后处置，绝不由缓存代码猜测为可删除。
非Python消费者使用唯一命令行桥接：`python -m common.simion.pa_family_cache --action
probe|publish|materialize --cache-root <root> --identity <identity.json> --filenames <name,...>`；发布另给
`--source-directory`，物化另给`--destination-directory`。identity JSON和文件清单由器件适配层派生，
该CLI不接受或推断物理参数，命中／缺失的建场决定也仍属于调用方。

局部Dirichlet PA使用
[`build_dirichlet_patch_basis.lua`](build_dirichlet_patch_basis.lua)从一个或多个已解父basis复制六面边界响应。
局部活动实体必须与父basis使用同一激励归一化；构建器从父PA的非零实体节点读取并交叉核对该值，不假定
`1 V`或`10000 V`。[`measure_pa_basis_voltage.lua`](measure_pa_basis_voltage.lua)则用raw PA的电极ID把真实
几何实体与同样标为physical的Dirichlet边界节点区分开，供运行证据记录归一化。
[`compare_pa_fields_at_samples.lua`](compare_pa_fields_at_samples.lua)在调用方提供的项目坐标样点比较两个
已解PA的电势和三分量场，并允许两个PA分别选择严格`z`反射；旧的仅B侧反射调用仍兼容。它不选择局部域、
轨迹portal、实例优先级或接受阈值。
[`build_dirichlet_patch_operating_pa.lua`](build_dirichlet_patch_operating_pa.lua)从一个已解父工作点PA直接采样
六面Dirichlet边界，把调用方明确给出的局部电极电压写入同源raw局部几何并只Refine一个工作点。它用于局部
响应文件不能由SIMION原生Fast Adjust电极计数安全表达的情况；不推导电压、区域、原点、网格或Workbench
优先级，也不把父场与局部场相加。
[`voltageize_pa0.lua`](voltageize_pa0.lua)使用SIMION原生PA-family Fast Adjust，把调用方明确给出的
`ID=V`稀疏电压表另存为临时工作点PA0；它不Refine、不覆盖源family，也不拥有电极分组或电压选择。
这条公共路径适用于全局或局部PA family，可避免逐节点Lua叠加和重复建场；调用方仍须验证family identity、
几何网格、实例位置和跨局部域接口。若裁剪后的局部域不含某个实体、但仍依赖它的Dirichlet边界响应，
SIMION原生Fast Adjust会拒绝超出局部实体计数的响应；此时
[`adjust_operating_pa_from_basis.lua`](adjust_operating_pa_from_basis.lua)从已解基准工作点只叠加调用方列出的
非零电压增量响应，不Refine，也不假定响应归一化。零增量应直接复用基准PA0。

### Standalone 工作点与响应合成 API

[`export_fast_adjusted_standalone_pa.lua`](export_fast_adjusted_standalone_pa.lua)只在可写、一次性的 build staging
中使用。输入必须是原生 family controller `.pa0`、全量 `ID=V` 工作点表和一个尚不存在的 `.pa` 输出路径。
工具用 controller 的 `electrode_numbers` 拒绝漏项和未知 ID，调用原生 `pa:fast_adjust`，再把内存中的完整工作点
复制到全新 PA 对象。它不把 controller 另存为 `.pa0`，不 Refine，并把输出固定为 `refined=true`、
`refinable=false`。任何 `.pa-surf` 伴随文件、已有输出或覆盖输入都会在打开 family 前失败关闭。发布后的不可变
cache family 及其副本不得作为该工具输入。

[`compose_standalone_pa.lua`](compose_standalone_pa.lua)实现
`OUTPUT = BASE + sum(COEFFICIENT * RESPONSE)`。输入只接受 `surface=none` 的 standalone `.pa`；每项响应采用
`PATH.pa,COEFFICIENT`，路径可含逗号，因为最后一个逗号才是分隔符。工具先用官方 `pa:copy` 复制 base，随后验证
每个响应的尺寸、网格、对称性和 potential type。SIMION 2020 没有已记录的“另一 PA 数组整体相加”API，因此
实现按节点调用官方 `potential_add`；若当前 PA 对象不暴露该方法，才用 `point` 读写同一节点。两条路径都只改变
电势并保留 base 的电极标志，不 Refine，输出同样是 solved/nonrefinable 的全新 `.pa`。它不是运行时逐时间步叠场
接口，而是生成一个可复核、可缓存的固定工作点。

本机 SIMION 2020（8.2.0.11）的官方证据位于
`C:\Program Files\SIMION-2020\docs\simion.chm`：`lua_simion.pas.html`记录
`simion.pas:open`、`pa:copy`、`pa:point`／`potential_add`、`electrode_numbers`和`fast_adjust`；
`user_programming.html#efield-adjust`记录运行时场覆盖；
`multiple_pas.html#programmatically-controlling-pa-instance-priority`记录从 PA instance 查询场及模拟默认 Fast Adjust
行为；`faq.html#fadj-types`与`calculation_time.html`记录 Fast Adjust 类型和逐时间步用户程序的性能边界。
官方 API 支持上述基本操作，但“将若干 standalone 响应按项目系数合成为另一 standalone PA”、完整表门禁、
surface 拒绝与不可变缓存边界均是本仓库实现，不应表述为 SIMION 提供了原生 family replacement 命令。

默认回归只做 Python 静态合同检查，不启动 SIMION：

```powershell
.\.venv\Scripts\python.exe -m unittest common.simion.test_standalone_pa_composition_tools
```

文件内另有小型真实 solver 回归；只有持有公共主机租约并显式设置
`SIMION_SOLVER_TEST_AUTHORIZED=1`时才会运行，否则始终跳过。

## 长路径输入 API与证据

适用规则和关闭结论只由[长 PA 输入路径](../../docs/SIMION_REFERENCE.md#长pa输入路径)定义。
本节记录实现调用方式和历史证据；实现提交 `fe09cc9c`、Agent 路由提交 `d6a51112` 已发布。

### 调用与回归

[short_pa_path_support.ps1](short_pa_path_support.ps1) 提供：

| API | 输入与职责 |
|---|---|
| `New-ShortPaCopy -Source <PA> -Destination <short.pa>` | 建立目标不存在的短名独立普通副本；拒绝 `.paN` 响应成员；默认最多三次完整重复制，每次核对源复制前后与目标大小／SHA-256 |
| `Remove-ShortPaCopyDirectory -Path <directory>` | 仅清理系统临时目录下匹配前缀的目录，并再次核对已登记源 SHA-256；默认前缀为 `simion_pa_links_` |

短副本恢复为可写，但“改名”不能证明来源于 family 的响应已经失去 `.paN` 语义。已发布 cache 中的
family 成员即使完整物化到私有目录也不得再次交给供应商进程；`r66` 证明复制后的成员仍可能导致原 cache
兄弟文件延迟变化。原生 family 只在一次性 build staging 中构建，并由
[`export_standalone_pa.lua`](export_standalone_pa.lua)复制到全新 PA 对象、保存为受同一 manifest 覆盖的
standalone 响应。运行时只为这些真正 standalone 的响应建立短副本，在 SIMION 退出后核对源并清理。
已经冻结的旧调用方仍可使用
`New-ShortPaHardLink`／`Remove-ShortPaHardLinkDirectory`，但两个兼容名称也只执行独立副本语义。

`cache_generation.py materialize` 仍提供通用、逐字节核验的完整 family 复制，但不构成已发布 SIMION
family 的运行时安全证明。只有新 family 的构建 staging 可以执行原生 Refine/Fast Adjust；发布后运行器
不得打开 cache 或其副本中的 `.paN`。

从仓库根运行回归：

```powershell
.\.venv\Scripts\python.exe common/simion/test_short_pa_path_support.py
.\.venv\Scripts\python.exe common/simion/test_export_standalone_pa.py
```

第一项回归主动改写临时副本，检查长路径只读源的字节与属性未变；第二项以真实 SIMION 建立小型 family，
在独立进程验证新对象导出的 standalone PA 节点、场、电极标志、重开行为和延迟哈希稳定。两者都不替代
项目整机物理资格测试。

### 失败与真实复验记录

<details>
<summary>展开 hard-link 失败、9 月 15 日复验及 r49／r50 证据链</summary>

早期 hard link 在 SIMION 延迟写回后暴露源 `pa4` 哈希漂移，其缓存保护资格已撤销。中央 family 从
冻结 GEM 和 recipe 重建后恢复到原 generation SHA-256：
`5230B69194902E23A68F3EDF1CCB5BD11FCBC0FDCE1E56C3DBE9D323A2DF0B5F`。

- `20260915_080000__sim__simion__mrtof-transient-shortcopy-smoke-n1`：五组局域响应采用短普通副本，
  完成工作点 PA0 合成、八实例 IOB 与单中心离子飞行，报告 `full_drift_observed`。终态 manifest 和
  运行后完整 family probe 通过，临时副本已清理；一次性工作点未写公共 cache，源 generation 未 Refine。
  粒子未自然命中探测器，因此只证明输入隔离与执行链，不构成自然命中或分辨率证据。
- `20260916_050000__sim__simion__mrtof-return-grid-natural-return-n1-r49`：669,209,300-byte 分析器 PA
  暴露单次复制后立即校验不稳定。此失败促成默认最多三次完整重复制；每次仍要求源前后及目标
  大小／SHA-256完全一致，耗尽即失败关闭。
- `20260916_053000__sim__simion__mrtof-return-grid-natural-return-n1-r50`：使用上述实现完成完整分析器
  PA、五个局域 PA0、IOB 装配和真实 SIMION 飞行，并自然命中独立探测器。该结果不升级为统计、
  收敛或整机资格。
- `20260916_170000__sim__simion__mrtof-return-grid-jac11-r66`：完整复制已发布 family 后打开其 `.paN`，
  仍观察到原 negative-mirror cache 的 `.pa4` 延迟哈希漂移；campaign 失败关闭。该结果撤销“完整复制
  family 可作为已发布 cache 运行时隔离”的结论。
- `20260916_180000...r69` 至 `20260916_184000...r73`：五个局域 family 在初次构建 staging 中导出
  受同一 manifest 保护的 standalone 响应。`20260916_193000__sim__simion__mrtof-r55-standalone-flight-r76`
  仅打开 standalone 运行输入，真实飞行自然命中探测器，并通过飞行后完整 cache probe。

以上保留来源记录的日期和 run identity；本次文档整治未重新运行这些试验。

</details>

传统路径上限与目标进程选择有关，官方依据为 Microsoft
[Maximum Path Length Limitation](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation)
（2026-09-10 查阅）。本实现针对仍受传统路径行为影响的 SIMION 输入，不改变规范 artifact 路径。

## 完整 family 的物化原语

[`cache_generation.py`](cache_generation.py)统一提供不同 PA-family 缓存协议共有的直接文件清单、payload/
immutable generation 摘要，以及按 manifest 文件清单完整物化为可写 run-local 副本的原子复制原语。物化先拒绝
既有目标，再在一次流式复制中对实际读取并写入的同一字节计算 SHA-256、逐文件核对 manifest、flush/fsync，最后
原子发布整个目录；不为同一大型 family 重复执行源预哈希、staging 复哈希和发布后复哈希。目标副本不继承只读源
的时间戳或只读属性。它不定义 identity 字段、role、锁、缓存目录、容量治理或命中时的哈希频率。公共 PA-family
cache 与集成项目 v3 cache 共用该物化原语，同时分别保留自身的 identity、provider-run、断点恢复和 SIMION 写者
生命周期安全策略。对于刚完成求解、准备进入不可变缓存的 staging family，调用方使用
`--require-stable-inventory`要求连续两次完整字节清单一致；这覆盖 SIMION 可见进程退出后仍可能发生的延迟 PA
落盘。稳定性确认仅发生在一次性发布边界，普通缓存命中不会因此重复读取整个大型 family。
普通命中仍只读取每个 payload 一次；若某个大文件首次读取与 manifest 不一致，则只重读该文件，并且必须连续
两次恢复为 manifest 的长度与 SHA-256 才接受。三次机会内不能取得连续两次一致即保持 `corrupt`，错误详情记录
期望身份和每次观测值；这处理瞬时读取不稳定，不允许未知字节或持续损坏通过。

## 调度与恢复

### 调度与资源画像

[`resource_scheduler.py`](resource_scheduler.py)是独立粒子批次与相互独立完整case的唯一SIMION并发决策实现。
项目只提交总粒子数、独立性和网格、RF步数、trajectory quality、PA哈希等客观数值身份；CPU、内存、并发、
安全系数、观察时长和危险处置均由公共层固定，项目参数会被拒绝。粒子数只改变运行时间，不用来假定单进程
瞬时资源占用。资源允许的并发数决定同时活跃的进程数与同一数值身份的工作通道数；粒子数不构成
单进程资源上限。调度器在每个通道只安排完成其份额所需的批次，并使各通道的总粒子数尽可能相等，
避免没有物理或实测依据的单批粒子数上限及由此造成的额外分波。

资源身份还包含调用方派生的 `field_loading_policy_id`：相同 PA 文件和 IOB 拓扑若采用不同的动态调整
解集合，不能复用同一内存画像。该字段只区分实际加载行为，不改变 PA 缓存身份或资源预算公式。

完全相同的历史数值身份可直接复用单进程保守峰值并跳过观察。没有历史时，首个正式批次取
`ceil(N/min(N,10))`个粒子；它最多观察45秒但始终继续运行，若提前自然完成也直接保留结果。实测后按CPU
`floor((95%-后台占用)/max(10%,单进程实测))`和内存
`floor((当前可用内存-1 GiB)/单进程安全预算)`的较小值确定最终并发。Windows 设置页虽显示为
“GB”，但本公共合同按其二进制容量语义明确记为`GiB = 1024³ bytes`，避免歧义。首次正式观测与精确历史画像
都记录并使用`max(working set, private committed memory)`的峰值，再以其1.10倍作为单进程预算；旧的
`observed_peak_process_tree_working_set_bytes`仅为调用者兼容而保留，其数值同样已升级为该保守managed峰值。
每次错峰启动前还以仍在运行任务的新峰值重新计算一个进程的准入
余量，故后续内存增长会立即暂停扩容。观测时的可用内存已排除仍在运行的首批，因而内存/CPU计算的是可新增
槽位，调度器会再准确加上该首批；首批仍运行时占用一个槽位，剩余
粒子只分给其余槽位；首批结束后，该通道只补齐到与其余通道相同的总工作量。首批已完成时全部槽位
分配剩余粒子，绝不重跑首批。各进程相隔5秒启动；CPU高只暂停
新启动，不终止进程。即使可用内存不少于1 GiB，若仍不足`1 GiB + 下一worker的保守预算`，也只记录
`available_memory_below_dynamic_admission`并暂缓启动。低于0.5 GiB持续15秒才按“最晚启动优先”终止一个worker、
重新排队并降低并发；被终止批次置于队首，不能被平衡补偿批次插队。每次此类危险处置后，必须连续45秒满足
动态准入才恢复一个并发槽并重启队首工作；至多执行两次“终止—稳定观察—恢复”。若第二次恢复后再次发生持续
危险，调度器终止其余受管worker并以`memory_danger_recovery_attempts_exhausted`失败关闭，绝不无限回退或混同为
普通逐次降并发。

### 中断续算

跨运行中断续算由[`batch_continuation.py`](batch_continuation.py)提供统一的不可变协议，有两种互斥策略：
`build_batch_continuation_plan`验证失败/中断/checkpoint父run的manifest、冻结run-config、批区间、合同、母cohort输入和原始输出SHA-256，
再把全局有序前缀中已经完整终态的整批物化到新run，并从第一个未完成批开始重放；它不拼接中断批的粒子片段。
consumer可选择只保留受治理事件，或在仍严格校验释放、终态和完成哨兵的同时原样保留整份stdout及辅助TRACE；
`build_whole_unit_replay_plan`则只复用每个独立工作单元的全部manifest绑定终态产物，未完整的单元整体重放。
前者的consumer必须提供本机TRACE语法、可复用终态定义和新run输入投影；后者的consumer只提供独立单元键及
run相对的终态产物清单。两者都不解析项目物理或替代结果物化。该协议与运行中的45秒观测、内存准入/重排互补，
均为全仓库SIMION运行器可接入的公共能力。
失败发布的紧凑保留例外同时支持两种 run-local 完成日志：末行为精确 `status,Fly completed.` 的预脉冲
`simion__batch*.trace.log`，以及末行为原生 `status,Fly completed.*` 的全流程
`simion__batch*.stdout.log`。两者都必须由 retention action 和失败/checkpoint manifest 绑定；普通日志或
不完整批不能借此绕过容量策略。

### 结果收据与串行边界

成功运行只保留紧凑调度收据，不保留逐秒探测文件。 [`resource_profile.py`](resource_profile.py)发布首个正式
批次的独立峰值并用run manifest及输入收据SHA-256复核；并行聚合峰值不得按进程数拆分。PA/IOB构建及没有独立粒子/可合并结果
合同的SIMION任务保持串行；未知case资源身份每次先运行一个正式case，只有同一完整输入的已观测峰值才可参与
后续case wave。已完成case campaign可以把画像写入manifest覆盖的summary；后续运行只发现这种受完整性保护的
画像，不接受裸日志或未受manifest覆盖的JSON。调度器不会发现、批准或启动campaign，也不会在外层campaign之上创建嵌套并发。

### 调度的官方依据

Windows能力依据（2026-08-26查阅）：Microsoft `MEMORYSTATUSEX/GlobalMemoryStatusEx`文档说明
`ullAvailPhys`表示可立即复用的物理内存，用于1 GiB/0.5 GiB门限；.NET `System.Diagnostics.Process`文档支持读取
`WorkingSet64`和`TotalProcessorTime`；Microsoft `taskkill /T`文档支持只终止选中PID及其子进程。采用这些接口
是为了测量真实SIMION进程族，并在持续内存危险时只回收最新批次。

- [MEMORYSTATUSEX](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/ns-sysinfoapi-memorystatusex)
- [.NET Process](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.process?view=net-10.0)
- [taskkill](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill)
