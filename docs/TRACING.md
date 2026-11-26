# 参考粒子 tracing

新公开链数值积分非相对论 Lorentz 方程，支持明确真空中静态均匀 E+B 和具名轴对齐平面。
四份作者配置在[参考配方](../recipes/reference/uniform_e.toml)及其同目录；参考单元不是完整仪器。
时变场、碰撞、自洽、非参考几何由能力预检拒绝。选择 max_step 时须避免一步多次穿面；切触未保证检测。

## 安装与运行

在源码目录构建普通发行；两份锁与 wheel 一起提供给使用者：

```powershell
.\.venv\Scripts\python.exe -m build --no-isolation
py -3.11 -m venv C:\msplatform-env
C:\msplatform-env\Scripts\python.exe -m pip install -r requirements-lock.txt
C:\msplatform-env\Scripts\python.exe -m pip install dist\mass_spectrometry_analysis-0.4.0-py3-none-any.whl
```

将唯一作者 TOML 复制到研究目录，切到源码树外后运行（替换部署路径）：

```powershell
C:\msplatform-env\Scripts\msplatform.exe --help
C:\msplatform-env\Scripts\msplatform.exe validate .\uniform_e.toml
C:\msplatform-env\Scripts\msplatform.exe run .\uniform_e.toml --artifact-root C:\msplatform-data\study
C:\msplatform-env\Scripts\msplatform.exe results inspect <run_id> --artifact-root C:\msplatform-data\study
```

`python -m msplatform` 使用相同入口。Python API 为 `msplatform.recipes.load_recipe`、
`msplatform.tracing.trace_particles`、`msplatform.workflows.reference_tracing.run_recipe/inspect_results`。
直接 tracer 消费已解析的 SI 科学数据；作者输入与身份由 load_recipe/validate_recipe 检查。
可用 `--source-revision <完整SHA>` 显式记录构建来源；未提供时标记来源 SHA 不可用，
不从研究目录猜测源码来源。该记录不决定物理缓存命中。

## 结果与复用

每个运行独立保留 resolved.json、provenance.json、execution.json、summary.json、run_manifest.json，
以及 initial_states.parquet、terminal_states.parquet、events.parquet 和 trajectories.h5。
frame 为显式实验坐标（参考 laboratory，x/y/z右手轴、原点由作者初态声明），时钟为实验相对秒。
粒子 ID 为正 int64，物种、质量、电荷态、派生电荷与权重各自保存。未保存的任意时刻完整回放不作承诺。
初态 parent_particle_id 为空且谱系标记为 unavailable_initial_snapshot，不把快照冒充真实出生记录；
本轮没有次级生成能力。事件序号按粒子递增，并保存平面轴法向穿越方向，重复穿面分别记录。
终态独立表达 physical_outcome 与 stop_reason；无法归属的 component/electrode/surface 是 null，
attribution_status/method 显式不可用；原生码、实体ID和诊断不丢弃。取消未启动粒子没有捏造的物理终点。
0 命中和时间截断可执行成功，统计分母保持完整母群；缺记录标记 incomplete，不补 lost。

相同科学输入复用场和完整独立粒子批；label 无关，场或粒子/数值输入改变只失效对应依赖。
缓存缺件重算完整受影响批；run 自含科学数据，所以合格缓存回收后仍可重读历史统计。
`provenance.field.reused` 和 `provenance.batches[].reused` 报告实际命中，不能只看路径存在。
缓存和存储限制见[ArtifactStore](ARTIFACT_STORE.md)，实际测试证据见[迁移记录](development/architecture-migration.md)。
