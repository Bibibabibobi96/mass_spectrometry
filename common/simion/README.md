# SIMION公共实现层

本目录保存不含器件身份、专用坐标系或运行模式假设的SIMION公共实现。`particle_source.py`接收已经由
上游适配器转换到工作台语义的 beam 或逐粒子状态并生成 FLY2/Lua 文本；多极杆的 ION11 和 canonical 字段映射
仍由 `common/multipole/simion_particle_source.py` 负责。

## 按任务导航

| 任务 | 入口 |
|---|---|
| 序列化几何、检查孔拓扑 | [几何与 Workbench](#几何与-workbench) |
| 缓存 PA family、导出 standalone 工作点 | [PA 缓存与工作点](#pa-缓存与工作点) |
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
generation payload和manifest同时设为文件系统只读。schema v2默认按每组等长payload发布流式XOR冗余；单文件
组的XOR即完整副本，因此不可重建或高成本PA具备单成员恢复能力。调用方只有在payload可由完整内容身份确定性
重建时，才可显式采用`none_reconstructible`策略：仍逐文件SHA-256、只读封装和原子发布，但不复制等体积XOR。
同一身份命中时可原子复制到新的run-local目录，
但完整 family 物化只服务字节审计、迁移或受控 build 边界，不授权供应商进程再次打开其中的 `.paN`；
SIMION 运行必须消费构建 staging 导出的 standalone `.pa`。任一缺失、额外、哈希不同或损坏 generation
均失败关闭。IOB、Fast Adjust
工作点、程序和Fly2从不作为缓存几何真值：每个run必须重新装配、重新保存并在本次manifest中绑定。该层不理解
器件、坐标或电极含义，项目仍拥有其ID和几何合同。发布过程按cache key持有短生命周期目录锁；并发发布同一
key只允许一个写者，并同时建立容量门禁可见的TTL保护租约；遗留锁失败关闭并需按artifact保留规则审计后处置，
绝不由缓存代码猜测为可删除。v1迁移或v2单成员恢复均发布到新的successor generation，manifest将前一代SHA-256
冻结为`predecessor_generation_sha256`，完整验证新payload和parity后最后切换pointer；旧generation不原位修改，
也不因失去current身份就自动删除。生产消费者使用`ensure`：current generation单成员损坏时自动发布
successor并原子推进pointer；显式冻结的旧generation在物化或subset验证时也可生成直接successor，但若
current已指向别代则绝不回退pointer，返回值必须把predecessor与repair receipt写入本次运行证据。
普通 current 命中先走封存 metadata 快路（manifest、精确文件名、大小、只读状态和 parity 结构）；发现长度、可写位、
指针或结构异常时才回退到逐字节验证与修复，不把正常命中变成整套 PA 重读。
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
不重新Refine。生产`artifacts/`缺少可信容量ledger时在修改payload前失败关闭；fixture可在其外独立运行。
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
再pin的窗口；这类长期资产不进入自动退休。未pin的generation也只能由固定PA manager入口
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
`schema_version: 1`、`receipt_name`（已声明的直接 JSON 成员）、`exporter_path` 和
`exports: [{response_id, source_name, standalone_name}, ...]`，不接受外部 PA 哈希。
owner 先登记该规范，等待所有数据成员齐全，再在锁内逐成员 flush、扫描一次并置为只读；receipt
writer 只复用本次内存 inventory，最后仅计算小 receipt 的哈希并联合封存。源映射必须属于该 family。
相同规范或普通 advance 均可重放已登记事务；已经封存时只核对元数据，不再次扫描 PA。
规范变化、已有未归属 receipt 或失败的写入均不能发布；未封存的中断写入由 owner 按原规范重建。
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

[`native_fast_adjust_operating_pa_cache.py`](native_fast_adjust_operating_pa_cache.py)把这条一次性 staging 导出路径
接入内容寻址缓存，但不执行求解器。身份绑定 source family role／cache key、controller basename、完整且有序的
solution ID 集合、每个 standalone 输出对全部 ID 的有限电压表、上述 exporter 的 SHA-256 和 SIMION 2020 PA
格式；缺一项即失败关闭。调用方在原生 family 唯一一次 Refine 后、删除 staging 前取得确定性导出计划并运行
exporter，再只发布 direct `.pa` 输出。底层复用 `pa_family_cache.py` 的原子发布、只读 generation 与可写私有物化；
原生 `.pa0`／`.paN` 永不进入 operating cache，也不因 operating cache 命中而被供应商进程重新打开。现有
[`operating_pa_cache.py`](operating_pa_cache.py) schema v2 继续专用于 standalone 基准／响应线性合成，两种身份不兼容、
不会互相命中。

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
| `New-ShortPaCopy -Source <PA> -Destination <short.pa> -ExpectedBytes <n> -ExpectedSha256 <sha>` | 持有禁止写入/删除/替换源文件的句柄并建立目标不存在的独立普通副本；拒绝 `.paN` 响应成员。Windows 大 PA 使用 `robocopy /J`，以私有目标的长度／SHA-256直接核对 manifest，不再用可能滞后的缓冲源视图否决正确落盘字节；较小文件仍核对同一受护源流和目标 |
| `Protect-ImmutablePaSource ...` / `Unprotect-*` | 为确需直接只读检查的 immutable 源建立进程期 `FileShare.Read` 保护；大 PA 直接无缓冲读取并核对 manifest，不建立额外 PA 探针。它不是把公共 cache 路径交给 SIMION 的许可 |
| `Remove-ShortPaCopyDirectory -Path <directory>` | 仅清理系统临时目录下匹配前缀的已登记独立副本并释放源句柄；默认前缀为 `simion_pa_links_` |

`Get-ImmutablePaSourceVerificationSha256` 的大文件路径在源保护句柄持续持有期间，从仓库根通过
`.venv` 的 `python -m common.contracts.file_identity --unbuffered <path>` 调用公共
`file_sha256_unbuffered`。这消除了每次验证额外的整件 `/J` 探针复制与临时 PA 空间；真正需要的运行副本
仍走原有 `/J` 复制及目标校验。无缓冲读取失败直接失败关闭，不回退普通缓冲读取；小文件行为不变。

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
`ceil(N/min(N,10))`个粒子；它最多观察45秒但始终继续运行，若提前自然完成也直接保留结果。实测后按CPU
`floor((95%-后台占用)/max(10%,单进程实测))`和内存
`floor((当前可用内存-1 GiB)/单进程安全预算)`的较小值确定最终并发。Windows 设置页虽显示为
“GB”，但本公共合同按其二进制容量语义明确记为`GiB = 1024³ bytes`，避免歧义。首次正式观测与精确历史画像
都记录并使用`max(working set, private committed memory)`的峰值，再以其1.10倍作为单进程预算；旧的
`observed_peak_process_tree_working_set_bytes`仅为调用者兼容而保留，其数值同样已升级为该保守managed峰值。
每次错峰启动前还以仍在运行任务的新峰值重新计算一个进程的准入
余量，故后续内存增长会立即暂停扩容。观测时的可用内存已排除仍在运行的首批，因而内存计算的是可新增
内存槽位，调度器会再加上该首批；CPU容量已按整机计算，不能再增加一个槽位。首批仍运行时占用一个槽位，剩余
粒子只分给其余槽位；首批结束后，该通道只补齐到与其余通道相同的总工作量。首批已完成时全部槽位
分配剩余粒子，绝不重跑首批。各进程相隔5秒启动；CPU高只暂停
新启动，不终止进程。即使可用内存不少于1 GiB，若仍不足`1 GiB + 下一worker的保守预算`，也只记录
`available_memory_below_dynamic_admission`并暂缓启动。低于0.5 GiB持续15秒才按“最晚启动优先”终止一个worker、
重新排队并降低并发；被终止批次置于队首，不能被平衡补偿批次插队。每次此类危险处置后，必须连续45秒满足
动态准入才恢复一个并发槽并重启队首工作；至多执行两次“终止—稳定观察—恢复”。若第二次恢复后再次发生持续
危险，调度器终止其余受管worker并以`memory_danger_recovery_attempts_exhausted`失败关闭，绝不无限回退或混同为
普通逐次降并发。

已知资源画像暂时无法装入当前空闲内存时，计划保留完整待运行批次，`admission`报告`wait_for_memory`与
当前新增容量0；执行器继续按实时余量等待，不强行启动，也不丢弃粒子。单worker同样保留1.10倍安全预算。
只有单worker安全预算超过总物理内存扣除系统保留量的包络时，规划直接报告无法满足。

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
