# SIMION公共实现与验证

本目录保存不含器件身份、专用坐标系或运行模式假设的SIMION公共实现。`particle_source.py`接收已经由
上游适配器转换到工作台语义的 beam 或逐粒子状态并生成 FLY2/Lua 文本；多极杆的 ION11 和 canonical 字段映射
仍由 `projects/rf_multipole_ion_optics/runtime/simion_particle_source.py` 负责。
`render_source_states(..., significant_digits=17)`用于binary64往返精确投影；默认15位保持既有源文本不变。
本页维护仓库 API、调用约束与验证范围；软件表示和兼容边界见[SIMION 参考](../../docs/tools/SIMION_REFERENCE.md)，
主机许可与门禁接线见[公共机制](../README.md)。项目操作和科学资格由项目 README／PROJECT 路由。

## 按任务导航

| 任务 | 入口 |
|---|---|
| 将已冻结的粒子状态投影和序列化为 FLY2 | [粒子序列化](particle_source.py)：`project_direct_velocity`共用6D、时间及直接速度投影；坐标变换、原ID映射和科学能量仍由消费者拥有 |
| 序列化几何、检查孔拓扑 | [几何与 Workbench](#几何与-workbench) |
| 冻结工作台seed小配套、定义独立Laplace成员 | [共用工作台种子与独立场成员](#共用工作台种子与独立场成员) |
| 缓存 PA family、导出 standalone 工作点 | [PA 缓存与工作点](#pa-缓存与工作点) |
| 长 PA 输入与缓存写隔离 | 先读[跨项目边界](../../docs/tools/SIMION_REFERENCE.md#长pa输入路径)，再读 [API 与证据](#长路径输入-api与证据) |
| 科学事件／轨迹CSV与流式读取 | [科学事件CSV](#科学事件-csv)；帧、时钟和科学分类仍由实际项目拥有 |
| 读取原生 Fly 完成事实 | [原生完成事实](#原生完成事实) |
| HS1运行副本的重复Fly复位与参数审计 | [HS1生命周期](#hs1运行副本生命周期) |
| 共用电压边沿步长计算 | [电压边沿](#电压边沿) |
| 共用 RF/DC 公式与时间步约束 | [RF 驱动](#rf驱动) |
| 并发、资源画像及中断续算 | [调度与恢复](#调度与恢复) |
| 查旧 Fly 入口审计 | [只读历史入口](PRODUCTION_FLY_AUDIT.md) |

## 既有终态CSV诊断

[`analyze_terminal_plane.py`](analyze_terminal_plane.py)保留为独立的既有终态CSV分析工具：显式给出
完整source count、pass code和横向轴心，输出终态分类、传输子表与等权空间统计。它不重建轨迹或穿面，
也不从文件存在授予物理传输资格。直接Python消费者目前只有相邻测试；输入格式仍由双锥接口保留的
`gas_assisted_transport.lua`输出，但该项目的原生运行入口已经退役，不能称为活动生产链调用。

正确工作区保有双锥20260914两份N100运行的真实终态输入与metrics，其小记录身份已核验；
这些run未绑定分析器源码，尚不能独立重放run-local代码闭包，因此不按“仅测试import”删除该CLI。
保留范围只限这个既有CSV合同；退出条件是所属项目的历史输入／冻结分析可独立重放，或当前受管分析
完成同输入等价替代，随后一起移除CLI及专用测试。新器件不复制这套统计，仍从公共canonical诊断边界接入。

## 几何与 Workbench

[`gem_primitives.py`](gem_primitives.py)只序列化明确传入的有限坐标与尺寸；Python函数
`centered_box3d`、`cylinder_z`分别生成GEM的`centered_box3D`和沿`z`轴的`cylinder`文本，
不选择电极、器件尺寸、孔径、网格或坐标变换。
独立正交加速器和连接装配共用这一层；器件CSG、侧孔与两／三区电极组合由加速器项目拥有。

项目间连接的矩形开孔统一调用[`aperture.py`](aperture.py)：机械宽、高任一小于一个cell时失败关闭；
非整数cell倍数或孔边缘未落在网格节点时保留机械尺寸并输出机器可读离散警告；GEM减材固定使用
`exclude_shape_inside_or_on_v1`，不得用隐藏epsilon扩大机械孔。提供者已有的 `notin_inside` 电极边缘合同则
显式标为 `exclude_shape_inside_only_v1`，保留边缘节点，不冒称两种切口相同。编译或缓存PA后，所有生产消费者还必须
通过[`aperture_topology_support.ps1`](aperture_topology_support.ps1)调用
[`verify_aperture_topology.lua`](verify_aperture_topology.lua)，确认法兰厚度方向至少有一条贯通非电极节点列，
并确认孔外四侧接地guard在法兰内部厚度节点仍存在（两端面连接相邻真空域，不作为侧壁判据）；FAIL禁止Fly。
调用方显式声明真实世界坐标的法兰法向 `NormalAxis=x|y|z`、厚度范围及三维孔中心；宽、高分别沿剩余轴的
x/y/z顺序取值（法向y时为x/z）。验证器只置换PA节点索引，既不旋转PA，也不借其他轴字段代称坐标。
该入口面向仓库内所有未来SIMION项目连接，不绑定多极杆、
oaTOF、single-flight或具体电极编号。

`surface=fractional`只提高非对齐表面的场与边界表达精度，不保证连续几何精确，也不能替代真实PA拓扑审计
或网格敏感性验证。本层不选择PA/IOB和物理参数；商业进程仍由项目 runner 经公共主机调度和冻结预算准入，
独立粒子批次的并发再由本层调度器决定。

所有新建SIMION Workbench必须从[`assets/iob_instance_seeds/`](assets/iob_instance_seeds/README.md)
中与实际PA实例数一致的干净GUI种子派生。该公共目录提供1--10槽连续容器和唯一占位PA；派生器必须替换每一个槽，
不得创建空槽或保留占位实例。种子只用于生成运行目录或正式交付目录中的派生IOB，绝不原地修改。

## HS1运行副本生命周期

[`collision_hs1.adapt_hs1_for_repeat_fly`](collision_hs1.py)接收显式冻结的官方SIMION 2020
`examples/collision_hs1/collision_hs1.lua`文本，返回增加`reset_run_state`和只读`bound_parameters`的运行副本。
它是仓库的生命周期适配，不是供应商推荐的新碰撞算法；安装目录源码不修改。未知私有声明、参数绑定、
已适配来源或非唯一return均拒绝。碰撞公式、抽样、参数、PRNG及种子约定保持，调用方负责原始／适配源码身份。
IP与冷却前端共用此入口，并沿各自现有冻结机制携带公共模块；冷却消费者不再依赖IP functional工作流。
气体分布、调用时机和科学时序仍由消费者拥有，SDS不通过此HS1专用适配。

## 电压边沿

[`voltage_waveforms.lua`](voltage_waveforms.lua)提供三项纯数学操作，时间输入均为微秒：

- `cap_before_edge(time_us, current_dt_us, edge_us)`仅在边沿严格位于未来时缩短步长；到达或越过边沿后保持传入步长。
- `rectangular_gate(time_us, on_us, off_us)`返回`active, next_edge_us`，理想脉冲在`[on_us, off_us)`为ON；
  ON前返回下一开启边沿，ON期间返回关闭边沿，关闭后返回`false, nil`。
- `cubic_transition(start_value, end_value, u)`按原运算顺序计算
  `start_value + (end_value - start_value) * u * u * (3 - 2 * u)`；不自行截断`u`或改变原时序。

调用方负责验证时钟、边沿和归一化进度，选择器件阶段、触发及电极绑定；恒定电压仍是普通数值，
公共模块不调度事件或自动平滑理想跳变。IP的`native_drive.lua`显式接收模块，runtime与场探针注入同一冻结副本，
抬升进度及其截断仍由IP决定。MR联合场审计保留上游已绑定的驱动与波形源码；电压投影显式冻结并注入公共模块，
IP距离研究同时绑定并核对源驱动及波形身份。run、worker及保存工作台携带必要代码伴随文件，恢复消费冻结源码。
full／local脉冲hook及冷却前端的入口关闭／释放边沿也显式注入此公共模块；Program沿已有源清单冻结并内嵌它，
不从活动仓库动态加载。器件脉冲模式和时序仍归hook，现有RF kernel保持原权威。
[`test_voltage_waveforms.lua`](test_voltage_waveforms.lua)是无PA／Workbench的纯Lua边沿、矩形门及三次过渡回归；
职责标准见[电压驱动与同步](../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md#电压波形器件驱动与同步)。

## RF驱动

[`rf_drive.lua`](rf_drive.lua)是共享的纯RF/DC数学kernel，不拥有Workbench、segment callback、PA实例或时钟。
调用方显式传入唯一instrument time，kernel验证并计算sine/cosine、相位、RF幅值与scale、两组DC、
逐电极common-mode与scale，并从每周期步数给出timestep cap。`new_differential`用于已包含静态场的载体，
`new`用于完整逐电极驱动；几何、电极含义、源时钟和数值选择仍归消费者。

生产调用先将kernel冻结为run-local输入；Program加载该副本，在初始化时编译驱动，飞行热路径不重解析配置。
不同项目及integration不得另存同义RF公式。多极杆的调用时钟和验证边界见
[实现说明](../../projects/rf_multipole_ion_optics/docs/IMPLEMENTATION.md#求解器投影)。

## 原生完成事实

[`native_completion.py`](native_completion.py)只解析仓库已实测的 SIMION 2020 原始行
`status,Fly completed. <splats> splats[, <seconds> seconds]`：它提供 splat 数和可选耗时，
不把这项项目实现表述为供应商稳定 stdout ABI。裸前缀、截断或旧格式不是完成事实；调用方选择自己的
单日志唯一或多日志显式求和策略，且不相加 elapsed。项目仍负责粒子 ID、时钟、阈值和科学终态。

同一模块为失败收尾提供`recoverable_batch_log_kind`、`has_recoverable_batch_completion`和
`recoverable_batch_logs`：仅识别run的`logs/simion__batch*.trace.log`或`.stdout.log`。
恢复完成判据检查最后一个非空行；TRACE使用仓库生产者的精确裸sentinel `status,Fly completed.`，
原生stdout必须符合上面的数字语法，不能把TRACE约定用于原生日志。日志原字节与路径保持不变。
这只决定声明日志能否保留以供恢复，不能替代完整母群、源、时钟或科学验收。
通用收尾、收据及终态保护由[保留API](../contracts/README.md#运行终态保留)处理，不在PowerShell复制供应商文本解析。

## PA 缓存与工作点

[`pa_family_cache.py`](pa_family_cache.py)提供完整静电PA-family的内容寻址复用：调用方必须给出完整的
数值身份与精确文件清单。family可以只有一份工作PA，沿同一事务、owner和generation协议发布；
独立求解单元的划分与审计证据边界见[统一复用规则](../../docs/DEVELOPMENT_STANDARDS.md#昂贵阶段复用与中断恢复)。
身份包含resolved geometry、GEM、xyz网格、网格相位、surface、SIMION可执行文件
和构建器身份；响应基另声明basis namespace与Refine策略，实际工作场则声明完整工作点电压／收敛表和边界策略；
仅实际包含RF工作场时声明RF参考幅值，无RF工作场身份省略该字段。两种身份各有精确字段集合，
不混用或补假响应基；具体电极与物理含义仍由提供者／工作流校验。
同一缓存机制核验声明的原生或standalone PA及必要小证据；新发布的
generation payload和manifest同时设为文件系统只读。schema v2默认按每组等长payload发布流式XOR冗余；单文件
组的XOR即完整副本，因此不可重建或高成本PA具备单成员恢复能力。调用方只有在payload可由完整内容身份确定性
重建时，才可显式采用`none_reconstructible`策略：仍逐文件SHA-256、只读封装和原子发布，但不复制等体积XOR。
同一身份命中时可原子复制到新的run-local目录，
但完整 family 物化只服务字节审计、迁移或受控 build 边界，不授权供应商进程再次打开其中的 `.paN`；
SIMION 运行必须消费构建 staging 导出的 standalone `.pa`。任一缺失、额外、哈希不同或损坏 generation
均失败关闭。IOB、Fast Adjust
工作点、程序和Fly2从不作为缓存几何真值：新工作台由本次冻结输入派生并在manifest中绑定；恢复运行可以通过
[公共续算计划](#中断续算)绑定并只读复用前驱的完整批次及其已保存IOB，不为已完成批次重复装配、保存或Fly。
该层不理解器件、坐标或电极含义，项目仍拥有其ID和几何合同。发布过程按cache key持有短生命周期目录锁；并发发布同一
key只允许一个写者，并同时建立容量门禁可见的TTL保护租约；遗留锁失败关闭并需按artifact保留规则审计后处置，
绝不由缓存代码猜测为可删除。v1迁移或v2单成员恢复均发布到新的successor generation，manifest将前一代SHA-256
冻结为`predecessor_generation_sha256`，完整验证新payload和parity后最后切换pointer；旧generation不原位修改，
也不因失去current身份就自动删除。生产消费者使用`ensure`：current generation单成员损坏时自动发布
successor并原子推进pointer；显式冻结的旧generation在物化或subset验证时也可生成直接successor，但若
current已指向别代则绝不回退pointer，返回值必须把predecessor与repair receipt写入本次运行证据。
普通 current 命中先走封存 metadata 快路（manifest、精确文件名、大小、只读状态和 parity 结构）；发现长度、可写位、
指针或结构异常时才回退到逐字节验证与修复，不把正常命中变成整套 PA 重读。
完整 family 校验与 standalone response 选择共用 `cache_generation.verify_immutable_payload_record`：正常只读一次；
异常读取沿既有连续匹配／Windows 持久快照核验收敛，持续字节不匹配仍拒绝，且不修改发布源。
原生family只走确定的`<root>/.transactions/<cache-key>/transaction.json`事务；common同时拥有同目录内的
`payload`和scratch。状态只有`building / prepared / published / retired`，错误只写`last_error`而不增加状态。
位于仓库`artifacts/`下的 PA family 禁止调用旧的`publish_pa_family_cache`直发 helper：它只保留给非受管的
临时／fixture cache；受管资产必须由`advance_pa_family_cache_transaction`取得唯一 owner、写入登记、验证证据
和发布／ledger handoff，避免出现可见却无人能恢复或退役的 generation。
历史校准若只能从 pointer／manifest 证明字节身份、却找不到该 owner transaction，则把该 key 登记为带 owner
和期限的`writing`恢复对象，而非 ready published cache；它不能消费或退休，直到真实 owner 恢复事务或通过授权
disposition 收尾，校准不会伪造 transaction。
对于确已被不同已验证 generation 替代的已 pin PA，唯一 owner 可调用
`release_pa_family_cache_retirement_pin`，以替代 generation 的受管证据及其 SHA-256 绑定一次 retirement
intent；该操作只解除 transaction pin 并同步 ledger，随后仍须通过通常的 exact-generation retirement
disposition 删除。它不提供通用 unpin，也不接受不可核验的路径或摘要。
builder把每个成员先写到返回的确定性scratch，再以原子改名落入`payload`；common看到完整精确清单后建立连续稳定的
持久化视图并封存，返回`verify`。调用方提交绑定cache key与inventory的SIMION验证证据后，common在同一事务内
完成parity、generation原子发布、pointer和容量ledger交接。中断后重复`advance-transaction`从同一状态收敛，
不重新Refine。生产`artifacts/`缺少可信容量ledger时在修改payload前失败关闭；首次事务还必须给出显式
owner和`--producer-run-config`。common只对这个小型、冻结的运行配置记录路径和一次性SHA-256，随后续作和
缓存命中不再读取它，更不会为此读取PA；因此每个新PA在产生重载荷前已有来源、责任人和恢复入口。fixture可在其外独立运行。
发布向key范围迁入recovery或payload前，沿既有容量入口登记同generation的`published_cache/writing`范围。
发布异常分别保留journal、重记transaction和已登记writing key的实际驻留字节；次级记账错误附在原异常上，
不遮盖原错。generation及pointer完成后才转ready并沿原交接归属；相同current pointer重放不再改写。
原生构建或审计在两次advance之间失败时，owner确认原生写者已返回后，在释放容量承诺前调用
同一`advance-transaction --record-stage-only`（Python参数`record_stage_only=True`）。它只接受已存在、
同owner与producer的building事务，在原锁内通过文件大小重记该事务及其payload／working容量；
不创建事务、读PA或重算哈希，不封存或推进发布，保留原状态与科学失败。单反射owner若连该记账也
失败，在原失败summary说明待收尾，保留现有公共保护租约与承诺，延后stopped-payload seal，不洗成发布成功。

尚未发布的`building / prepared`事务可在同一`advance-transaction`显式传`--producer-handoff <json>`
（Python参数`producer_handoff`），交给新的受管producer继续构建或验证，不提供求解器checkpoint续算。
请求为schema 1，含新run的`inputs/`下三份冻结record：`transaction_record`、`predecessor_manifest`、
`stopped_receipt`，以及当前`capacity_lease_id/capacity_lease_owner`。三份record核验冻结字节和SHA-256，
按JSON对象解析，不以文件大小限制合法manifest。stopped receipt必须来自公共
`seal-stopped-payload`，与前驱manifest的run／状态及当前ready、pinned owner账本一致；前驱run必须已声明
`solver_review`或`qualification`保留合同，`compact`不能事后借交接保留重载荷。owner负责在封存前
实际确认writer及后代退出。已停止的`checkpoint`保持原科学状态，不改写为成功或失败。
停止receipt以`run_config`记录封存时实际配置；handoff核对它与原transaction producer属于同一run路径，
并验证当前配置字节。原producer SHA保留为开始构建时的来源记录；正常生命周期补齐依赖或收尾元数据
不要求整个配置SHA永远不变。场identity和文件清单仍须完全一致。初始化checkpoint manifest保留原身份，
停止时配置身份随冻结receipt保留，不改历史文件。
调用同时以`--owner`和`--producer-run-config`声明新责任人；新run必须已登记，当前workflow租约须保护
该run及cache，其他活跃key／事务／前驱路径保护仍拒绝。cache identity和文件清单保持完全相同。
原owner／producer与冻结前驱记录保存在同一事务的`producer_handoff`审计记录，新owner／producer一次
原子写入并登记容量；该次调用只交接，不封存或发布。缺成员返回`build`，成员齐全或已封存则返回`verify`，
保留原inventory；`prepared`还须核验并保留原验证证据。完整文件存在不代表科学验证通过。
已有同generation的writing key范围随这次已验证交接同步责任人；同步中断沿已提交journal续作，
不接管外来owner或改写既有ready范围。
新owner随后普通advance才进入封存／验证／发布：未验证资产须提交绑定inventory的原生审计；已有有效
`prepared`证据可直接完成原发布步骤。中断后重放同一交接或普通advance收敛，不增加状态机。
build-scratch在验证证据持久保存后才按原机制清理，使接续验证仍可使用原native basis；交接不读取或复制
scratch，也不把它视为完整成员。已发布事务拒绝新交接，部分单元仍由调用方按原构建边界重做。
已有member／retained-inventory／publication-metadata恢复journal的事务仍由各自既有恢复合同处理；
普通producer handoff拒绝覆盖这些journal绑定的owner，不改写原恢复授权。

尚未验证的封存成员与其轻量receipt身份不一致时，owner可在同一个`advance-transaction`调用中传入
`--member-recovery <json>`（Python参数`member_recovery`）。请求固定为schema v1、role
`simion_pa_family_member_recovery`，绑定`cache_key`、`owner`、旧`inventory_sha256`、`receipt`
文件记录和非空`members`；每个成员提供`sealed`、`expected`两个`name/bytes/sha256`记录及
`receipt_record_path`数组（JSON对象键或非负数组下标）。owner核对旧清单、receipt字节身份和实际引用，
仅接受同名但身份不同的成员；不为该检查重读PA。只有`building`且没有verification或generation身份
可以恢复，不能同时提交验证证据。事务内`member_recovery` journal原子记录请求和旧清单并清空活动inventory，
随后只移除请求成员及被其失效的receipt，其余成员不动。中断后的普通advance重放该journal，完成后的相同
请求不再删除已经重建的成员。此可选journal是既有冻结building事务的原子扩展，不新增生命周期状态；
之后仍走正常缺失成员构建、重新生成receipt、封存、验证及发布，禁止项目直接改台账或整包重算。
若这些保留成员的随后封存库存出现瞬态读取差异，可在同一入口传
`--retained-inventory-recovery <json>`（Python 参数 `retained_inventory_recovery`）。请求只含
`schema_version: 1`、`cache_key`、`owner`、当前 `inventory_sha256` 与明确的非空 `names`，不接受调用者提供
替代哈希。owner 仅在 `building`、无验证／发布身份、原成员恢复已完成且清单完整时处理；名字必须是原
`member_recovery.files` 中未删除／重建、但与当前库存不同的保留成员。锁内逐个以只读 `/J` 私有快照核对
原库存身份，全部成功才原子更新选中记录、库存摘要与恢复证据；PA 和 receipt 字节、其余库存均不改变。
任一快照失败均不部分更新。完成后的相同请求幂等返回正常 `verify` 阶段，不再复制或扫描 PA；随后仍须提交
绑定新库存摘要的正常 SIMION 验证证据。此功能只修复已证明的库存读取差异，不接受损坏字节或跳过物理验证。
生产`artifacts/`事务若使用`--published-pin-reason`，该pin与发布在ledger同一原子handoff中生效，不存在发布后
再pin的窗口；这类长期资产不进入自动退休。唯一owner可在同一`advance-transaction`传入`--published-pin-generation-sha256 <exact-generation>`和
非空`--published-pin-reason`，为已有的未pin published generation补长期保护。动作核对原owner、
当前精确generation及ready ledger身份，不读PA，不改payload或科学身份；相同请求会补齐中断的ledger写入。
持久保存IOB等消费者可在`validate_pa_family_cache_generation(..., require_publication_pin=True)`边界
核验transaction与ledger的generation、owner和pin一致；普通运行期复用仍只需其现有精确租约与只读保护。
未pin的generation也只能由固定PA manager入口
`approve_pa_family_cache_retirement(cache_root, cache_key, generation)`退休：它在PA key锁内核对唯一transaction、
current generation和sealed manifest，并复用manifest中的成员SHA/bytes生成完整文件清单，不重读大型PA。容量ledger
在decision lock内核对manager、无pin和无租约后，先回调PA owner原子写`retired` transaction，再发布绑定generation
及完整清单的唯一disposition。实际删除器只消费该disposition；批准或删除中断后沿同一记录幂等恢复，不重新Refine。
物理删除完成前probe不再返回HIT；完成后同一identity自动开启新的`building`周期。
发布后校验拒绝某一generation时，rollback也在同一key锁内先进入`writing`：恢复predecessor后以其SHA-256、
key root实际字节和`ready/last_used_epoch`同步ledger。若首代被拒而没有predecessor，key root只剩回滚收据，
则不虚构published identity或零字节retired状态，而把该可删除证据根登记为`rebuildable_payload/ready`；回滚中断
则以实际残留字节保留`published_cache/writing`和错误收据，供显式恢复。
非Python消费者只使用三个命令行action：`probe`、`advance-transaction`和`materialize`。
已发布的 `none_reconstructible` generation 若只有一个封存哈希错误，可由原 owner 显式调用
`advance-transaction --publication-metadata-correction <json>`。请求字段为 `schema_version: 1`、
`cache_key`、`owner`、`generation_sha256`、`inventory_sha256`、`member_name`、`sealed_sha256`、
`retained_sha256`；当前工作流可另传 `capacity_lease_id/capacity_lease_owner`，两者仅为本次授权上下文，
不参与纠错身份。成员必须仍在已完成 member recovery 的原始保留清单中、从未删除重建；原清单 SHA 必须
等于当前 Windows unbuffered SHA，且修正后所有保留成员均与原清单一致。除该成员外不重新读取 PA 字节。
owner 在扫描前核对原 pointer 和其他活跃消费者，并核验旧真实格式验证报告及 verifier 的哈希。
该入口不修改原 verification、不重跑 SIMION，不把 published 伪装为 building；pending journal 优先于
普通 advance/probe，阻止重新发布错误身份。同 key-root 内撤回 pointer、同卷 rename 原只读载荷至 owner staging，
将原 manifest 原样移存 `metadata-correction/original_manifest.json`，写入 successor manifest 后 rename 发布。
PA 全程不写、不复制、不 hardlink，旧 generation 路径失效；这是有证据的错误发布撤回例外，绝非允许原位修改发布资产。
独立 `metadata-correction/receipt.json` 明确 `no_solver_rerun: true`、原验证报告、原/新 inventory 与持久字节证明，
CLI 返回 `publication_metadata_correction_receipt` 供运行器冻结。原生 `.paN` 即使移到 staging 仍禁止 SIMION 打开。
每个 rename/pointer 边界可从同一 journal 续作；容量始终沿同一 key-root owner 对象 `writing→ready` 登记实际逻辑字节，
保留原 pin，仅增加轻量证据，不走 stage handoff 或预留另一整包。完整纠错证据也纳入既有 owner retirement 清单。
需要随 PA family 生成 standalone response receipt 时，同一 `advance-transaction` 可传
`--response-receipt <json>`（Python 参数 `response_receipt`）。规范只含
`schema_version: 2`、`receipt_name`（已声明的直接 JSON 成员）、`exporter_path`、
`source_location`（`payload`或`build_scratch`）和
`exports: [{response_id, source_name, standalone_name}, ...]`，不接受外部 PA 哈希。
owner先登记规范，等待声明成员齐全，在原锁内取得实际来源与保留响应的字节身份；schema 2 receipt中的
source是构建来源记录，不要求导出用的原生PA永久留在generation。standalone响应仍须属于发布manifest，
并按其库存核验。若source同样被保留，其名称／大小／SHA须与manifest记录相等，选择器不因此读取源PA。
writer复用该次inventory，计算小receipt身份并持久化事务库存；科学verification已通过并持久化为prepared后，
才清理同owner的scratch，保证尚未完成验证的交接仍保留实际构建来源。
相同规范或普通 advance 均可重放已登记事务；已经封存时只核对元数据，不再次扫描 PA。
prepared发布在目录移动前失败时，重放复用逐值相同的既有只读manifest；不同内容、间接路径或非文件
明确拒绝，不为重放解除只读或覆盖原manifest。该规则同时覆盖xor与无冗余发布策略。
规范变化、已有未归属 receipt 或失败的写入均不能发布；未封存的中断写入由 owner 按原规范重建。
新提交的recipe及新写receipt均为schema 2。reader另严格支持已有schema 1：recipe保留原四字段和版本，
其source与standalone都必须是声明的payload成员；receipt的原生source必须逐值匹配manifest，默认读取还核验源字节。
这对应原v1作者的payload语义，不推测缺失来源。v2来源可只作provenance的规则不变；未知版本、布尔版本或额外字段拒绝。
已封存v1事务及generation只读不改写，原publication pin／owner／inventory证明仍必需；未封存v1事务由原owner普通advance继续，
新生成receipt为v2，原recipe身份保留。缺generation或未完成库存不会因版本可读而升级为ready／published。
前端仅保留独立响应与必要小记录；仍有真实原生消费者的OA／MR继续保留其声明的raw载荷，不按扩展名统一删除。

[`native_fast_adjust_runtime_support.ps1`](native_fast_adjust_runtime_support.ps1)和
[`assemble_native_fast_adjust_family.lua`](assemble_native_fast_adjust_family.lua)把已发布 raw `.pa#` 与上述
standalone 响应重组为一套受管、只读的私有原生 Fast Adjust family。控制器只执行一次`solutions={0}`；响应
逐个从 standalone `.pa` 复制到全新`.paN`对象，不再次Refine，也不打开已发布generation中的原生`.paN`。
首次构造核对generation身份及小型response receipt字节；PA载荷沿现有短副本记录核对，不额外扫描整库。
同一helper的显式`Transaction`参数集也接受公共loader验证的受管未发布库存：调用方必须给出实际
transaction路径、库存SHA、当前producer与活动容量session；真实lease须覆盖该run和cache key。
它沿相同guarded copy逐个构造私有响应，不伪造generation。可选逐响应验证回调只在该响应的私有
standalone副本仍受护时执行；全部响应验证完成后，调用方才向原公共事务提交verification并发布。
是否已完成重场构建由项目的原manifest与实际构建记录证明，helper的roundtrip不能替代Refine完成证据。
`InvokeNativeOperation` 保留 Python 受管进程完成合同，也接受直接 PowerShell owner 的
`powershell_process_completion`：实际 PID、启动时刻和退出码须与原生 observation 一致，且进程退出、
stdout／stderr 排空均已确认。OA→MR 经提供者透传该回调；未知完成保留原输入保护，不虚构 Python worker。
同一场身份的后续K、电压、粒子源、TE1和GUI只复用producer-owned checkpoint，不按trial重复重组。
该边界已由 OA provider `20261003_152000__sim__simion__mrtof-oa-private-runtime-provider-r04` 与 MRTOF
safe-exit `20261003_153100__sim__simion__mrtof-oa-private-runtime-safe-exit-n100` 真实贯通：后者复用既有
checkpoint、无 PA Refine 或全族复制，100/100 粒子到达声明的加速器几何出口。该证据只验证运行时复用与
出口传输，不授予下游整机分辨率资格。
未传入此选项且未登记规范的既有事务行为不变；单独 receipt writer 继续支持独立构建调用。
`advance-transaction`返回`build / verify / complete`之一，以及确定的transaction、build与scratch路径；验证完成时
追加`--verification-evidence <json>`，昂贵长期资产再追加`--published-pin-reason <reason>`。`materialize`使用
`--destination-directory`。受管`artifacts/` generation 的`materialize`还必须给出活动 TTL lease 的 id 和
owner；common在复制前只读事务、sealed manifest、ledger 和 lease 元数据，核对 manager、published generation
及 cache-key 覆盖，任一 retired／缺绑定／过期状态即失败。它不建立隐式长租约，也不为健康命中重读 PA payload；
工作流必须让该 lease 覆盖从命中到消费完成的删除竞争。Python层保留验证、修复和迁移原语；它们不再形成另一套
原生family发布CLI或恢复状态机。

当运行只消费同一 generation 中已经独立导出的 standalone 成员时，Python 调用方可使用
`validate_pa_family_cache_subset(...)`：它仍验证 generation manifest、cache key、身份元数据和 generation
record 摘要，但只打开调用方明确列出的文件并逐字节核验，避免为了读取 standalone 子集而重新打开未使用的
原生 `.paN` 兄弟文件。返回值明确标记 `complete_native_generation_qualified=false`；该接口只证明所列子集可安全
消费，不能替代完整 generation probe，也不能据此宣布整个原生 family 健康。

局部Dirichlet PA使用
[`build_dirichlet_patch_basis.lua`](build_dirichlet_patch_basis.lua)从一个或多个已解父basis复制六面边界响应。
父basis参数既可写成单一路径，也可写成 `PATH,COEFFICIENT|...` 的线性组合；系数由调用方已经冻结的
工作电压提供，构建器只做同一点电势叠加，不推导电压或增加响应身份。
构建器第五参数选择边界模式，第六参数可传有限正数的 Refine convergence（V）；省略时仍使用
安装版本默认值。调用方负责从唯一数值配置派生、冻结并记录该值；公共实现不选择项目精度。
第七参数可在已给convergence时传 `0`／`1`，显式转发官方 `pa:refine` 的 `skipped_point`；
省略则不传该选项，保留安装默认。回归中的模拟PA只验证参数转发和默认行为，不证明原生求场收敛或提速。
写入五面／六面后只调用一次官方 Refine，不改变电极电压、镜像面或源 PA。
局部活动实体必须与父basis使用同一激励归一化；构建器从父PA的非零实体节点读取并交叉核对该值，不假定
`1 V`或`10000 V`。[`measure_pa_basis_voltage.lua`](measure_pa_basis_voltage.lua)则用raw PA的电极ID把真实
几何实体与同样标为physical的Dirichlet边界节点区分开，供运行证据记录归一化。
[`compare_pa_fields_at_samples.lua`](compare_pa_fields_at_samples.lua)在调用方提供的项目坐标样点比较两个
已解PA的电势和三分量场，并允许两个PA分别选择严格`z`反射；旧的仅B侧反射调用仍兼容。它不选择局部域、
轨迹portal、实例优先级或接受阈值。
[`field_comparison.py`](field_comparison.py)统一读取该比较CSV、拒绝缺列与非有限残差，并计算RMS和最大残差；
样点分组、物理区域、身份绑定及接受阈值仍由消费项目定义。
[`build_dirichlet_patch_operating_pa.lua`](build_dirichlet_patch_operating_pa.lua)从一个已解父工作点 standalone
`.pa` 或一次性 `.pa0` 直接采样
六面Dirichlet边界，把调用方明确给出的局部电极电压写入同源raw局部几何并只Refine一个工作点。它用于局部
响应文件不能由SIMION原生Fast Adjust电极计数安全表达的情况；不推导电压、区域、原点、网格或Workbench
优先级，也不把父场与局部场相加。
第七参数可显式指定有限正数的 Refine convergence（V）；省略时保留官方安装默认值，日志分别记录
实际声明值或 `installed_default`。这是求场停止条件，不是局部场误差上限；比较前需确认安装默认值，
不能仅凭指定了某个数值便称其更严格。
第三参数也可显式为 `zero_dirichlet`，用于没有父场的完整计算域；此时不打开父PA，六面边界取0 V。
求解后仅恢复raw PA#中原本非物理的外边界标志，保留求得电势和真实金属，避免将数值边界当作碰撞电极。
这是项目对官方 `point`／`refine` API的边界组装，不是新的场求解算法；2026-10-22核对的SIMION 2020
本机依据为 `examples/field_emission/refinelib.lua`、`fe_geom.lua` 与 `examples/misc/pa_move_electrode.lua`。
计算域大小、零远边界适用性、透明理想网格和实际飞行验证仍由调用项目负责。
[`voltageize_pa0.lua`](voltageize_pa0.lua)使用SIMION原生PA-family Fast Adjust，把调用方明确给出的
`ID=V`稀疏电压表另存为临时工作点PA0；它不Refine、不覆盖源family，也不拥有电极分组或电压选择。
该入口只适用于新建、可写、一次性的 build staging family，禁止对已发布 cache 或其物化副本执行。
它可避免构建期逐节点Lua叠加和重复建场；调用方仍须验证family identity、
几何网格、实例位置和跨局部域接口。

### Standalone 工作点与响应合成 API

以下公共入口仅负责 PA 表示、工作点导出与缓存，不选择项目电压，也不授予物理工作点资格。

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

适用规则和关闭结论只由[长 PA 输入路径](../../docs/tools/SIMION_REFERENCE.md#长pa输入路径)定义。
本节记录实现调用方式和历史证据；实现提交 `fe09cc9c`、Agent 路由提交 `d6a51112` 已发布。

### 调用与回归

[short_pa_path_support.ps1](short_pa_path_support.ps1) 提供：

| API | 输入与职责 |
|---|---|
| `New-ShortPaCopy -Source <PA> -Destination <short.pa> -ExpectedBytes <n> -ExpectedSha256 <sha>` | 持有禁止写入/删除/替换源文件的句柄并建立目标不存在的独立普通副本；拒绝 `.paN` 响应成员。Windows 大 PA 使用 `robocopy /J`，以私有目标的长度／SHA-256直接核对 manifest，不再用可能滞后的缓冲源视图否决正确落盘字节；较小文件仍核对同一受护源流和目标 |
| `Protect-ImmutablePaSource ...` / `Unprotect-*` | 为确需直接只读消费的 immutable 源建立进程期 `FileShare.Read` 保护；大 PA 首次直接无缓冲读取并核对 manifest，不建立额外 PA 探针，同一进程后续复用同一保护。只有已经确认不在 Fast Adjust 后执行 `wb:save()` 等写操作的加载／飞行路径，才可把受护源直接交给 SIMION；存在明确写入路径时仍使用一次性私有副本。 |
| `Remove-ShortPaCopyDirectory -Path <directory>` | 仅清理系统临时目录下匹配前缀的已登记独立副本并释放源句柄；默认前缀为 `simion_pa_links_` |

PA登记与释放共用`GetFullPath`规范化键；已有输入先按PowerShell当前位置解析，8.3短名和展开名不另建记录。
`New-ShortPaCopy -GuardDestinationReadOnly`在首次目标身份校验时取得并持续持有同一read handle；
大目标使用既有无缓冲读取。`Publish-ShortPaCopyDestination -KeepDestinationGuard`将该实际句柄转入
现immutable owner，随后Protect不再读同一载荷；曾可写、后来才加guard的目标不能据此复用身份。
独立`Confirm-ShortPaCopyIdentity`与默认response selector仍完整核验。源guard的已验证身份只在持续
有效且身份一致时复用；两个owner用重叠独立read handles，不相互Dispose。
selector的`verify_payload=False`仅供随后有guard的物化选择；小response receipt自身SHA、manifest、
响应命名／ID／次序及大小仍核验，不能作为PA已验收证明。
这复用[既有.NET路径语义](https://learn.microsoft.com/en-us/dotnet/api/system.io.path.getfullpath?view=net-10.0)（2026-10-26核对），不改变长PA运输、复制或哈希协议。

`Get-ImmutablePaSourceVerificationSha256` 的大文件路径在源保护句柄持续持有期间，从运行源码根通过
`python -m common.contracts.file_identity --unbuffered <path>` 调用公共
`file_sha256_unbuffered`。这消除了每次验证额外的整件 `/J` 探针复制与临时 PA 空间；真正需要的运行副本
仍走原有 `/J` 复制及目标校验。无缓冲读取失败直接失败关闭，不回退普通缓冲读取；小文件行为不变。
无缓冲身份校验优先使用既有 `SIMULATION_PYTHON_EXE`，未设置时使用运行源码根的 `.venv`；显式路径无效时失败，不回退。

短副本恢复为可写，但“改名”不能证明来源于 family 的响应已经失去 `.paN` 语义。已发布 cache 中的
family 成员即使完整物化到私有目录也不得再次交给供应商进程；`r66` 证明复制后的成员仍可能导致原 cache
兄弟文件延迟变化。原生 family 只在一次性 build staging 中构建，并由
[`export_standalone_pa.lua`](export_standalone_pa.lua)复制到全新 PA 对象、保存为受同一 manifest 覆盖的
standalone 响应。运行时只为这些真正 standalone 的响应建立短副本，在 SIMION 退出后核对源并清理。
无活动调用者的旧 hard-link 命名转发接口已删除；已冻结运行继续使用自己的源码快照。

`cache_generation.py materialize` 仍提供通用、逐字节核验的完整 family 复制，但不构成已发布 SIMION
family 的运行时安全证明。只有新 family 的构建 staging 可以执行原生 Refine/Fast Adjust；发布后运行器
不得打开 cache 或其副本中的 `.paN`。

从仓库根运行回归：

```powershell
.\.venv\Scripts\python.exe -m unittest common.simion.test_short_pa_path_support
.\.venv\Scripts\python.exe -m unittest common.simion.test_export_standalone_pa
```

第一项回归主动改写临时副本，检查长路径只读源的字节与属性未变；第二项以真实 SIMION 建立小型 family，
在独立进程验证新对象导出的 standalone PA 节点、场、电极标志、重开行为和延迟哈希稳定，并执行
`family build → 两响应新对象导出 → 短路径复制 → compose → 关闭 → 延迟复核`，要求原生 family 与已发布
standalone 响应的全部 SHA-256 均不改变。该链已在公共租约
`common-standalone-response-writeback-regression` 下用 SIMION 2020 实跑通过。两者都不替代
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
- `20260916_231000__build__simion__mrtof-local-r55-detached-r85`：把全局分析器、五局域替代、加速器和
  探测器固化为唯一八 PA 运行集合。`20260916_235000__sim__simion__mrtof-r55-detached-flight-r87` 只把该集合
  投影为短路径副本，真实飞行与终态 manifest 均通过，TOF 与 r76 完全一致；这证明工作台重打包没有改变
  当前中心轨迹，但不提升其工作点或性能资格。

以上保留来源记录的日期和 run identity；本次文档整治未重新运行这些试验。

</details>

传统路径上限与目标进程选择有关，官方依据为 Microsoft
[Maximum Path Length Limitation](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation)
（2026-09-10 查阅）。本实现针对仍受传统路径行为影响的 SIMION 输入，不改变规范 artifact 路径。

## 完整 family 的物化原语

`inventory_named_files`和`copy_verified_file`供可写build staging发布；`snapshot_immutable_file`专供已发布
cache消费。二者禁止混用：前者可在发布前flush仍可写的生产者文件，后者永远只读源，并在Windows大PA上仅以
`robocopy /J`生成的私有快照对manifest验明持久字节，即使源意外丢失只读属性也绝不以`r+b`打开。

[`cache_generation.py`](cache_generation.py)统一提供不同 PA-family 缓存协议共有的直接文件清单、payload/
immutable generation 摘要，以及按 manifest 文件清单完整物化为可写 run-local 副本的原子复制原语。物化先拒绝
既有目标，再对私有持久快照计算 SHA-256、逐文件核对 manifest、flush/fsync，最后
原子发布整个目录；不为同一大型 family 重复执行源预哈希、staging 复哈希和发布后复哈希。目标副本不继承只读源
的时间戳或只读属性。它不定义 identity 字段、role、锁、缓存目录、容量治理或命中时的哈希频率。公共 PA-family
cache 与集成项目 v3 cache 共用该物化原语，同时分别保留自身的 identity、provider-run、断点恢复和 SIMION 写者
生命周期安全策略。刚完成求解的 transaction payload 只能在所有生产者退出后封存：事务锁内先 flush 每个
可写成员，再生成一次完整字节清单并立刻置为只读。该清单是随后收据绑定、generation identity 与发布的唯一
payload 权威；不得再复制完整 family 或重复扫描来“确认”同一个已封存边界。普通命中只检查 sealed manifest、
精确名称/大小和只读状态，不重读整个大型 family；发现异常时才走完整审计或恢复。已发布源绝不以 ReadWrite
打开、flush 或原位“修复”。

Windows上的独立大PA投影由[`short_pa_path_support.ps1`](short_pa_path_support.ps1)在`8 MiB`及以上使用
`robocopy /J`非缓冲复制，再核对目标SHA-256；较小文件仍使用受写穿透保护的流式复制。本机已复现普通
缓存式复制在同长度约3 GB PA中产生单字节差异，而同一来源经`/J`得到冻结SHA，因此不得把重复普通复制
或增加哈希次数当作恢复办法。临时staging只在目标目录内创建，成功后同卷重命名，异常路径删除该具名前缀目录。

PA-family 首次发布不再重复库存刚复制的 staging：`copy_verified_file` 返回已落盘目标的清单，发布器直接用它
生成 manifest、封存并原子重命名。小文件仍比较源／目标；Windows 大文件先 flush 仍可写的 build staging，随后
以 `/J` 目标快照为发布字节权威。缓存消费者则必须把该返回身份与既有 manifest 比较，不能自行接受未知字节。
同次发布再按等长组生成`immutable_pa_xor_parity`，主manifest绑定每份parity manifest和payload的SHA-256。
恢复时所有大输入先以只读`/J`快照确认持久视图；仅恰好一个payload损坏且parity完整时才允许重建。多成员损坏、
parity损坏、pointer并发漂移或新generation任一验证失败均保持旧pointer并失败关闭。

## 调度与恢复

### 调度与资源画像

主机只允许一个重任务，轻任务仍可按公共预算同时运行，规则见
[主机资源调度](../../docs/OPERATIONS.md#主机资源调度)。公共执行器先核验父重任务许可，内部worker不重复
申请主机许可；以下规划与实时启动检查共同决定可运行的worker数，不把重任务许可解释为资源已全部空闲。

[`resource_scheduler.py`](resource_scheduler.py)是独立粒子批次与相互独立完整case的唯一SIMION并发决策实现。
项目只提交总粒子数、独立性和网格、RF步数、trajectory quality、PA哈希等客观数值身份；CPU、内存、并发、
安全系数、观察时长和危险处置均由公共层固定，项目参数会被拒绝。粒子数只改变运行时间，不用来假定单进程
瞬时资源占用。资源允许的并发数决定同时活跃的进程数与同一数值身份的工作通道数；粒子数不构成
单进程资源上限。调度器在每个通道只安排完成其份额所需的批次，并使各通道的总粒子数尽可能相等，
避免没有物理或实测依据的单批粒子数上限及由此造成的额外分波。

资源身份还包含调用方派生的 `field_loading_policy_id`：相同 PA 文件和 IOB 拓扑若采用不同的动态调整
解集合，不能复用同一内存画像。该字段只区分实际加载行为，不改变 PA 缓存身份或资源预算公式。

完全相同的历史数值身份可直接复用单进程保守峰值并跳过观察。没有历史时，首个正式批次取
`ceil(N/min(N,10))`个粒子；它最多观察45秒但始终继续运行，若提前自然完成也直接保留结果。内存使用
整个窗口的进程树峰值；CPU 使用最后最多10秒的中位持续占用，并另记窗口峰值，避免 PA 加载或
Fast Adjust 的短时多核峰值把随后长时间单核飞行误判为单路。若批次在观察窗口内自然完成，则 CPU 仍保守使用峰值。实测后按CPU
`floor(95%/(max(100%/逻辑处理器数,单进程实测)×1.05))`和内存
`floor(当前可用内存/单进程实测峰值)`的较小值确定最终并发，最低一个槽位。Windows 设置页虽显示为
48 GB，实际可用物理总量仍按系统 API 的字节值记录。已知画像和首批观测均使用
`max(working set, private committed memory)`的峰值，系数固定为1，不另加百分比或1 GiB启动余量。
原历史画像无需改写，按其实际峰值重新编译当前公开策略。
观测时的可用内存已排除仍在运行的首批，因此内存计算的是可新增槽位，再计入活动首批；CPU容量按整机计算。
一个满载逻辑CPU的归一化占用作为下限，与实测值取较大者，再按用户要求乘1.05作为有效CPU需求，
是相对增加5%，不是增加5个百分点。中央Python策略只在编译plan时计算一次；plan分别保留原始实测、
下限约束后的占用、有效`per_process_cpu_budget_percent`和系数，调度日志显示有效预算及1.05系数。
画像仍发布原始实测，runtime重排不重复放大；独立粒子、完整工作项和case选择使用同一CPU需求。
历史后台占用不固化为通道上限，每次启动以实时总CPU加冻结的有效单进程预算检查中央95%准入。
旧冻结plan没有有效预算字段时，实时启动器保持其原始占用规则，不追改正在运行的证据。
SIMION公开策略由`limits.memory_policy=warn_single_worker`标明：预计内存不足时输出
`MEMORY_PRESSURE_WARNING`与`admission.status=memory_warning`，若当前无活动worker仍允许启动一路。
已有worker时，加一路仍须当前空闲内存容纳其最新实测峰值，并继续遵守CPU准入、槽位上限和启动间隔，
避免同时启动多个大场消费者。预计不足、普通压力或瞬时低内存不终止健康进程；
正式首批观测及批次执行均保留已有的持续critical危险保护，不由`warn_single_worker`关闭。
确认危险后的受管终止、有限恢复及失败收尾沿用原公共机制；阈值、持续时间与次数由同一公共策略提供，项目不得复制。
Windows分配失败、真实进程非零退出仍保留失败证据并失败闭合。usage receipt记录实际策略、警告和危险处置事件。
无此SIMION策略标记的调用继续采用其原准入保留量；其他求解器不变。

### 中断续算

跨项目的复用与中断恢复规则以[开发标准：昂贵阶段复用与中断恢复](../../docs/DEVELOPMENT_STANDARDS.md#昂贵阶段复用与中断恢复)
为唯一正文；这里仅说明现有公共 API 的职责和接入边界。

[`batch_continuation.py`](batch_continuation.py)的`build_whole_unit_replay_plan`
复用每个独立工作单元的完整终态产物，生成新的 run 输入，
不恢复正在运行的 SIMION 进程、不拼接未完成批的粒子片段，也不推断项目的物理终态。
前驱也可为已发布的`success`，用于重做分析或发布而不重新Fly；`running`／live仍拒绝。
`WholeUnitReplayUnit`必须显式传入`is_complete`；消费者用原生完成判据产生该布尔事实。
为false的单元直接安排整单元重跑，不读取或哈希其部分日志；为true的单元仍须通过已有manifest绑定及字节校验。
whole-unit plan schema 2直接绑定当前显式前驱manifest输入／输出中的实际文件，输出canonical绝对路径；
恢复run再次中断时，下一次仍可复用其已绑定的更早产物，不扫描祖先、不复制日志或新建恢复权威。
已自然退出的首个正式批若在重规划前后失败，owner可将原 provisional 计划、首批输入和小退出事实绑定到原run终态。
`resource_scheduler.plan_recovered_formal_followup`先核对已完成区间；有真实资源观测时沿用既有自适应规划。
缺少完整观测时保留已完成首批，按不大于原首批的区间冻结缺失批，并先观察第一个缺失批；
`--recovered-missing-plan`使用该批的真实峰值、CPU与主机内存观测校准原分区，按实际CPU／内存容量接续其他缺失批，
不重新发射已完成首批，也不虚构资源峰值。小退出事实按既有终态manifest验证；未绑定的硬中断事实不授权复用。
已有完整固定分区的续跑使用`prepare_fixed_partition_dispatch(plan, batch_plan, replay_indices, profiles=...)`
或`--prepare-fixed-recovery-plan PATH --fixed-batch-plan PATH --profiles PATH --replay-batch-index INDEX`：
profiles可省略；现有identity匹配的画像须覆盖实际最大缺批，不以普通新计划的bootstrap或批量否定原分区，
也不丢弃已有覆盖充分的观测计划。覆盖不足时在真实最大缺批上采集正式资源观测，再以`--recovered-missing-plan`校准。
观测批索引随计划保留；画像不足时仅先启动最大缺批的正式观测，覆盖画像或观测校准充分后，
按既有CPU、内存和互斥准入决定并发，不再无条件固定单通道。IP、prepared-joint、OA→MR及RF入口消费这组公共API；
RF finite每个case按实际缺批重新检查覆盖，仍在运行的观测worker计入资源预算。
原完整批、粒子ID与区间不改变；bootstrap批量不代表原缺失完整批的容量上限。
项目 adapter 只需提供其冻结的科学输入投影、独立单位及实际终态判据；项目 runner 负责把生成的 plan 接到新的执行与结果物化。公共层不把这些物理语义、粒子
分类或项目结果布局变成第二套通用合同。

PA family 的可恢复发布／复用由[`pa_family_cache.py`](pa_family_cache.py)的事务和 generation API 承担；
运行期 Fast Adjust 私有 family 由[`native_fast_adjust_runtime_support.ps1`](native_fast_adjust_runtime_support.ps1)
从已发布 generation 重建。两者均不保存或恢复供应商进程的内存状态。当前公共层尚未提供把任意
项目 runner 自动接入 continuation 的 CLI：各项目保留上述窄 adapter，避免公共层猜测日志语法或完成语义。

`Invoke-SimionBatchPhase`统一协调首批观察、owner物化回调、剩余批次派发及全复用零启动；
前端、prepared joint和OA→MR使用此入口。`Invoke-SimionFormalObservation`负责启动正式首批、检查观测结果并调用owner的重规划回调；
成功时返回同一进程记录供后续wave接管，回调失败时先排空该进程；启动后观察异常也传递实际记录，
无法确认身份或停止时保留未知状态。前端、prepared joint、OA→MR、RF有限三维及IP功能入口已接入；
批次物化和科学完成判据仍由owner负责。

首批正式观测启动后，准备或调度重规划失败时，`Invoke-ObservedPreparationFailureDrain`将已启动记录交还
公共进程执行器等待收尾，再执行可选的控制验证并抛出原异常；收尾或验证次错附于原异常的Data并以警告报告。
前端、prepared joint和OA→MR经统一批次协调器共用此失败路径；RF和IP的迁移应以各自实际接线为准。
批次wave中的后续准备或checkpoint失败停止派发新任务，公共进程owner继续等待已启动的健康worker，
为其调用原checkpoint回调，并保留原始异常和收尾次错；未确认停写时调用方不得发布终态或释放保护。
前端按固定分区保存经现有 manifest 绑定的自然退出码、stdout 和控制文件；default replay
同样按完整批次复用。旧 pulse 若没有逐 worker 退出事实则按未知处理，不能仅凭日志推定完成。

### 直接进程观察

`process_observation.run_observed_process`只采样直接启动的外部根进程，并默认把墙钟阈值作为一次性
`OBSERVED_PROCESS_WARNING`：健康SIMION自然完成，观测器不因耗时、峰值或日志静默终止它。若调用方已有
独立、明确的放弃决定，才可同时提供`hard_deadline_seconds`与
`hard_deadline_action="terminate_process_tree"`；Windows通过`taskkill /T`处置该根进程及其子进程。
这不是资源调度、健康诊断或普通运行预算的替代入口。

采样、告警回调或等待间隔抛出异常（含`KeyboardInterrupt`）时，观察器保持日志句柄打开，沿
[Python 3.11 `Popen.wait()`](https://docs.python.org/3.11/library/subprocess.html#subprocess.Popen.wait)
等待本次直接启动的根进程自然退出，再抛出原异常；等待期间再次收到`KeyboardInterrupt`仍继续等待。
已启动进程的异常附`observed_process_exit_confirmed`与`observed_process_returncode`，分别表示根进程退出
是否得到确认及其原生退出码。等待本身失败时前者为false、后者为null，note明确标记
`OBSERVED_PROCESS_EXIT_UNCONFIRMED`；日志关闭的第二个错误也保留在note，不替换原错误。
根进程退出不证明脱离它的后代已停止；调用者仍须满足已有进程owner的后代完成判据，未知状态不得封存或清理输出。
相邻测试使用短小Python子进程验证持续写入、非零退出、观察异常与清理异常，不构成真实SIMION验收。

`particle_batching.merge_rebased_particle_csvs`按列名`particle_id`恢复ID，保留原列顺序和批次／事件行顺序。
消费者可直接合并原CSV，不需为ID列重排物化中间表；项目母群、终态和碰撞校验仍由原消费者负责。

### 结果收据与串行边界

成功运行只保留紧凑调度收据，不保留逐秒探测文件。 [`resource_profile.py`](resource_profile.py)发布已完成运行中
实测的单worker内存峰值及该worker的实际工作单元数，并用run manifest及输入收据SHA-256复核。
后续worker峰值高于首批时使用其对应计数；未测得同一worker的CPU时不混用首批CPU。
进程名、PID及创建身份保存在resource usage中；并行聚合峰值不得按进程数拆分。PA/IOB构建及没有独立粒子/可合并结果
合同的SIMION任务保持串行；未知case资源身份每次先运行一个正式case，只有同一完整输入的已观测峰值才可参与
后续case wave。已完成case campaign可以把画像写入manifest覆盖的summary；后续运行只发现这种受完整性保护的
画像，不接受裸日志或未受manifest覆盖的JSON。调度器不会发现、批准或启动campaign，也不会在外层campaign之上创建嵌套并发。

### 调度的官方依据

Windows能力依据（2026-08-26查阅）：Microsoft `MEMORYSTATUSEX/GlobalMemoryStatusEx`文档说明
`ullAvailPhys`表示可立即复用的物理内存，用于实测并发容量和持续危险观测；.NET `System.Diagnostics.Process`文档支持读取
`WorkingSet64`和`TotalProcessorTime`；Microsoft `taskkill /T`文档支持只终止选中PID及其子进程。采用这些接口
是为了测量真实SIMION进程族，并记录真实内存压力及进程失败。

- [MEMORYSTATUSEX](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/ns-sysinfoapi-memorystatusex)
- [.NET Process](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.process?view=net-10.0)
- [taskkill](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill)

## 共用工作台种子与独立场成员

`workbench_seed.freeze_workbench_seed(run, repo)`只冻结官方一实例seed与必需placeholder的小配套对；
同run再次消费核对已有副本，不能复制或替代科学PA family。local context与cooled的实际复用context共同调用，
原local私有seed复制实现已删除。源资源的用途见[官方种子](assets/iob_instance_seeds/README.md)。
独立Laplace身份继续由integration的`single_reflection_flight.field_plan.laplace_member_identity`提供；
单反射domain与cooled七成员共用该投影，缓存事务仍归本目录，物理operator／边界条件由原owner校验。

## 科学事件 CSV

`scientific_event_csv.lua`按调用者给出的列和有效数字写入CSV，检查列、行完整性及write／flush／close失败；
`scientific_event_io.iter_csv_rows`流式校验表头、行宽和CSV语法。`expected_record`或`identity_result`
请求身份时，在同一次完整读取中计算原字节身份；未读至EOF不产生已验证身份。普通读取不新增哈希。
帧、单位、绝对时钟、方向、母群与实际损失仍由项目解释，IO不定义新科学schema。

MR和IP正常生产者携带冻结写入器，实际分析调用同一读取器；MR进程日志只保留运行／完成信息，
事件和请求的轨迹分别记录，保留原12／17位精度。IP保留原15位及既有诊断采样政策。
声明CSV后缺失或损坏直接失败；无声明的已封存历史日志只由显式读取适配处理，不回退掩盖CSV错误。
科学有效性和原生验收见各项目PROJECT；共享IO软件通过不授予新的飞行或物理资格。

本run的新PA在其owner确认所有writer停止并完成必要flush后，
`Protect-ImmutablePaSource -Source <PA>`可在同一持续只读handle下建立一次身份；
传预期身份时bytes与SHA必须成对，单项或不匹配拒绝。IP正式dispatch消费这份活guard记录，
模板生成与收尾不重复读取相同受护PA；guard中断必须重新验证。
外部发布资产仍用原manifest预期身份，未知writer不得进入新身份建立边界，身份不代表科学适用性。
IP的prepare也调用现`workbench_seed.freeze_workbench_seed`冻结官方seed和placeholder配套，
不另复制科学场；其冻结Python闭包同时保留实际Lua资源和已选作者配置。
