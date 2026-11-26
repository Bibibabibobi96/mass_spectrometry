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
`reference_tracing` 的 run 自含证据，因此其性能缓存用 provenance 引用。
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
