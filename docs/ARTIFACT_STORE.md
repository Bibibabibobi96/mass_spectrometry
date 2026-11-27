# ArtifactStore 实施说明

生命周期唯一规则见[新参考链合同](LIFECYCLE.md#新参考链-artifactstore)。
`msplatform.storage.ArtifactStore` 的受管根必须在所有 Git 工作树外，且为空或属于本 Store；
不会导入或调用旧 GC，不接管既有研究数据。当前本地同步 SQLite，不是分布式服务。

## API 与实际消费者

`new_work()` 创建当前实例私有写区；`put_asset_claimed(kind,key,work)` 在发布 ready 的同一事务取得保护；
`claim_key(key)` 校验全部文件并在消费期间持权，损坏/缺件/并发回收为 MISS。
`claim(asset_id)` 适用于已知精确身份；`pin` 与必要 run 引用阻止回收。
`publish_run(work, required_assets=(), provenance_assets=())` 固定月桶和独立 JSON manifest；
`inspect_run` 复核 SQL/JSON 及载荷；`discard_work` 只清当前实例创建的精确私有写区。
新 run 在 `begin_run` 登记时固定 UTC `runs/YYYY/MM/<run_id>`，跨月发布或恢复仍使用该登记路径；
单步 `publish_run` 在其创建运行身份时固定月桶。资产采用
`assets/<kind>/<sha256(key)前两位>/<asset_id>`，写区为 `work/<task_id>`，元数据保存在
`catalog.sqlite`。历史 Store 的登记路径由数据库作为权威，读取、恢复和回收不重排旧文件；
manifest 当前的 `created_utc` 记录发布时刻，不能据此反推已经登记的创建月桶。
`reference_tracing` 的 run 自含证据，因此其性能缓存用 provenance 引用。
`inplace_asset(kind, key)` 为需要稳定绝对路径的未来原生 owner 提供原位写入基础：先登记
publishing 与持有 claim，返回最终路径，调用者证明所有 writer 和 native binding 已停止后
才能 `seal()`；失败时可明确记录失败原因，未完成的原位资产不可命中缓存或被 GC。
控制进程失联后的 `recover_managed_native_store_stage` 仅接受已完成的原 terminal、writer 和
绑定证据，成功与失败按原 completion 恢复；未知状态保持 publishing，不以父退出或 TTL 猜测。
原生 `run_managed_stage` 的显式 `managed_native_store` scope 可调用该接口，并复用既有
进程绑定与逐文件 guard；公共 native 工作流尚需逐消费者接入，不能据此声称全部 PA/MPH 已转移。
`begin_run/mark_running/finish_run/run_status` 提供运行前身份和独立的执行/发布状态；
未准入的 queued 输入和原因可查询，当前没有后台自动派发器。
调用 `mark_running` 前须进入 `with store.run_writer(run_id):`，持锁覆盖计算、异常收尾及发布；
`run_status` 的 `work_path` 可定位尚未发布的冻结输入和部分证据。

`reserve(peak_bytes)` 与 `reservation_written(token, remaining_bytes)` 表达未落盘增长，
高低水位由部署提供；参考链以每样本64字节、发布双副本及每粒子1MiB容器开销保守估算，
可用 run 的 `--reserve-bytes` 提高峰值预算。不是实测峰值上界，扩大样本前应核对部署预算。
`--high-water-bytes/--low-water-bytes/--safety-bytes` 是存储策略，不是科学参数。
`collect(target_bytes)` 回收明确合格 cache 并报告实际释放及失败。

## 恢复和未实现边界

发布中断保留 publishing 状态和原 work/destination；管理员确认所有 writer 已停止并独占操作后
调用 `recover_publications()` 重放同一状态机。删除中断由后续 collect 重放 delete_pending；
OS 锁随 GC 进程退出释放。句柄/权限失败留下失败原因，不宣称已释放。
claim 和预留持有独立 token 的现有 OS 文件锁；`recover_controls()` 仅在取得原 token 锁后释放
精确控制记录，活进程持有的保护保持。未知旧控制记录保守留存，无 TTL。
`recover_interrupted_runs()` 先恢复失联控制，再逐个尝试取得原 writer token 的 OS 锁；
只将尚未进入发布的失联 running 标为 failed，并记录 `writer interrupted before publication`。
原 run ID、私有 work 和已有字节保留；不生成终态数据或成功缓存。活 writer、publishing、ready
均不受影响；重复恢复不再修改。没有 writer token 的历史 running 不猜测退出状态，须人工调查。
当前参考求解没有原生子进程；后续独立/native 消费者须各自持权，不能只凭父进程退出释放后代使用。
后台自动调度及完整索引重建/其余旧 owner 接管属剩余 M03/C。数据库控制状态不能当缓存删除。
这里的恢复是资产发布/完整批重算，未实现求解器内部 checkpoint。
