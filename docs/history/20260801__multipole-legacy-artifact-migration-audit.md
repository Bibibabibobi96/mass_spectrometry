# 多极杆旧项目身份 artifact 迁移审计

> 本文是 2026-08-01 的只读迁移前审计。它不修改项目当前资格，不授权从旧运行晋升结论，也不表示
> 旧顶层目录或重型文件已经移动、删除。

## 目标与边界

2026-07-28 行政改名后，四、六、八极杆分别保留一棵由项目描述符登记的只读 legacy artifact 根。
这些根避免了旧 manifest 的 recorded project identity 被错误改写，但也使每个设计线同时存在旧、现
两个顶层目录。路线图要求把旧根无损封装进当前项目的 `archive/`，再独立执行 manifest 级减容。

唯一迁移映射为：

|旧顶层根|当前项目根|归档载荷|
|---|---|---|
|`rf_quadrupole_collision_cooling`|`rf_quadrupole_ion_optics`|`archive/<migration_id>/legacy-project-root/`|
|`rf_hexapole_ion_guide`|`rf_hexapole_ion_optics`|`archive/<migration_id>/legacy-project-root/`|
|`rf_octupole_ion_guide`|`rf_octupole_ion_optics`|`archive/<migration_id>/legacy-project-root/`|

迁移保持旧根内部相对布局和全部旧 manifest 原字节。读取旧绝对路径时，只允许使用迁移 manifest
冻结的 exact-root-prefix 重定位；不得猜测文件名、搜索相邻目录或改写 recorded project identity。

## 冻结盘点

公共 planner 对真实旧树完成逐文件字节数和 SHA-256 冻结，计划保存在工作区独立审计目录，不在 Git
或 artifacts 中制造第二份结果权威。

|旧根|runs|文件|总字节|活动引用run|仅history引用run|仓库文本未引用run|
|---|---:|---:|---:|---:|---:|---:|
|四极杆旧身份|265|13,325|33,494,631,276|8|56|201|
|六极杆旧身份|78|5,129|20,524,793,218|5|7|66|
|八极杆旧身份|35|1,836|4,521,495,575|4|6|25|
|合计|378|20,290|58,540,920,069|17|69|292|

三项目当前 `formal_assets.status=none`，旧身份run没有被当前 formal asset manifest引用。378个run均有
`run_config.json`、`summary.json`和`run_manifest.json`；绝大多数是保留合同生效前的schema v1，不能
事后伪称已预注册`compact/qualification/solver_review`。其manifest记录的project仍为对应旧身份。

收紧裁剪边界后重新生成计划，并另做第二遍全文件集、字节、SHA及recorded identity复核。首次复核时
六极杆旧树一份`finite_3d_transport.mph`的SHA与刚生成的计划不同，工具按合同拒绝通过；待文件稳定后
重新冻结六极杆全树并再次完整复核，三份当前计划才全部通过。该事件说明执行真实迁移前仍必须即时
重验，不能把较早的计划当作永久快照。

随后六极杆apply前复核又发现另一份3,378,869,955字节MPH的当前SHA与其不可变run manifest记录值
不同。schema v2 planner因此增加manifest input/output身份交叉审计：迁移计划冻结当前观察字节，同时
把recorded/observed差异列为`identity_anomalies`并强制保留。仓库不保留schema v1兼容入口，所有计划
必须重新由唯一v2 planner生成。

|项目|run / 文件|manifest SHA-256|当前冻结 SHA-256|异常|处置|
|---|---|---|---|---|---|
|四极杆|`20260722_213000__sim__cross__rf-oatof-s1-physical-5ev__n100`引用的`20260722_210000__sim__comsol__rf-oatof-s1-physical-port-5ev__n100/run_manifest.json`|`19CB07DA6764B90FCF98BF847E403814C3117C8B41FDF81927008EED2F2B5C1F`、9,486字节|`5817AAB2B25E05EAE49E25548C3D20EEE1224F04F180E0A799B60B5104C98A04`、10,615字节|跨run冻结引用与当前文件不一致|`manifest_identity_anomaly`，强制保留|

六极杆目的端复核时上述MPH已连续三遍稳定读回旧manifest记录的原始SHA，且无活动COMSOL求解进程；
因此先对完整目的端重新冻结，再按标准v2路径回滚、重新plan并迁回，最终异常数为0。该过程没有改写旧
manifest，也没有把一次性upgrade/repair入口留在生产代码。四极杆当前异常数为1，异常文件强制保留。

## 保留与减容结论

必须保留run三件套、冻结输入、canonical states/events、metrics、数值结果、报告、图、必要日志和旧
archive。活动或history引用的run不能整run删除。`formal/`、`archive/`、所有`runs/*/inputs/`及名称
明确含input、frozen或snapshot语义的冻结容器始终保留；旧根顶层和非`runs/`区域的二进制也默认
保留。只有run内部非冻结输入区域的可重建COMSOL/SIMION/CAD原生二进制，以及旧根顶层scratch，
可在无损迁移、目标SHA复核以及迁移reader回归后单独裁剪；每项必须在pruning manifest记录原路径、
归档路径、字节数、原SHA和原因。

|旧根|裁剪候选文件|候选字节|迁移后保留字节|
|---|---:|---:|---:|
|四极杆旧身份|1,055|31,437,689,483|2,056,941,793|
|六极杆旧身份|268|20,291,483,243|233,309,975|
|八极杆旧身份|75|4,482,568,733|38,926,842|
|合计|1,398|56,211,741,459|2,329,178,610|

三行均来自唯一schema v2 planner。v2终态manifest已经选择保留的输出优先于历史后缀分类；`.iob`及
CAD文件不再被笼统视为可重建solver binary。六、八极杆已按收紧后的计划无损迁入但尚未裁剪；四极杆
源树已重新冻结，但Windows仍拒绝原子目录移动，因此其候选不是可立即执行的裁剪授权。

除顶层scratch外，候选必须同时位于`runs/<run_id>/`且不在任何输入、冻结或snapshot容器中；允许后缀
严格限于`.mph`、`.iob`、SolidWorks/STEP文件和SIMION `.pa/.pa#/.paN/.pa-surf`。CSV、完整轨迹、
日志、旧archive、formal、冻结输入和其他数值证据本轮不因体积自行删除；若以后需要进一步减容，
必须重新做独立证据审计，不能扩大本次路径或后缀规则。

## 事务顺序与恢复

1. 从项目描述符验证唯一legacy mapping，冻结完整源文件集、字节数、SHA、run引用类别和裁剪候选。
2. 移动前再次复核全树；只允许同卷原子目录移动到当前项目的具名migration snapshot。
3. 在目标位置逐文件复核SHA和旧manifest recorded project identity，再发布archive及migration manifest。
4. 切换描述符、公共reader和结构门禁到归档定位，运行相关静态、L1/L2和artifact结构回归。
5. 只有旧顶层路径零活动消费者后，才移除已经为空的旧顶层入口。
6. 另行执行裁剪；裁剪前可按相同manifest反向移动完整回滚，裁剪后只可由冻结输入与Git历史重建已删
   原生二进制，保留的数值证据仍可直接读取。

公共实现为`common/contracts/artifact_identity_migration.py`。迁移计划、归档包装和裁剪日志分别由
`artifact_identity_migration.schema.json`、`artifact_identity_archive_manifest.schema.json`和
`artifact_identity_pruning_journal.schema.json`定义。项目描述符是旧身份定位的唯一权威：迁移前使用
`source_pending_relocation`，迁移并复核后切换为`archived_verified`；归档态不允许回退搜索旧顶层根。

裁剪采用同卷`.prune-quarantine`和持久状态日志。隔离阶段中断可续跑或完整回滚；进入删除阶段后只可
续跑，不能伪称字节级可逆；日志先完成而归档包装尚未发布的崩溃窗口可幂等修复。相关fixture覆盖
迁移、目的端SHA复核、旧manifest身份保持、隔离中断、删除中断、发布中断、回滚和结构门禁。

截至本文更新时，六、八极杆已无损迁入当前项目具名archive且descriptor为`archived_verified`，尚未
裁剪；四极杆源树和v2计划完整，目标archive不存在，descriptor保持`source_pending_relocation`。
四极杆在沙箱和用户账户下执行同卷`os.replace`均遇到WinError 5，Restart Manager未找到明确持有者；
重启或解除过滤驱动/不可见目录句柄后可直接重试标准apply。现阶段没有删除任何历史产物字节。
