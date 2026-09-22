# 公共离子释放

此目录拥有与项目、几何和求解器无关的离子释放采样、canonical CSV 和 receipt 身份。`release.py` 是 canonical
状态物化的唯一公共入口，使用闭合的 `(geometry.shape, sampling.strategy)` 注册表分派；连续轴向体积源保留其
既有的闭合 `(source_region_model, method)` key。未知几何、策略或连续源 key 均失败关闭，不使用插件发现或项目回调。需要保留既有求解器表序列的 sampler 在本目录显式具名，返回 solver-neutral 的
latent 或 phase-space 值，不绕过 canonical materialization 合同。

需要保留动能和方向、再由项目适配至特定求解器的调用方使用
`generate_center_first_halton_cylinder_phase_space`。它复用同一 centre-first Halton 圆柱采样核，不写文件、不选择
场或 FLY2 表示；MR-TOF 的确定性束团以此生成后仅投影为既有项目状态表。项目提供冻结的
局部 Cartesian `frame_id`、位置、物种和相空间请求；项目适配器负责把该状态映射到 SIMION、COMSOL 或其他
求解器，公共层不选择释放面、场、器件坐标变换或物理验收阈值。

`cylinder` 由 [`cylinder.py`](cylinder.py) 实现两种完整圆柱体积策略：

- `center_first_halton_cylinder_v1`：首粒子精确位于中心，后续粒子覆盖完整圆柱、能量和角度区间。只改变
  `particle_count` 时，较小表是同一母队列的精确前缀，适合 N=100/N=1000。
- `seeded_independent_gaussian_cylinder_v1`：均匀空间圆柱与独立 Gaussian 三维速度；沿请求轴应用正速度截断。
  它表达某一时刻的源体积快照，不宣称已经经过下游场。

[`mt19937_disk_cone_rf_phase.py`](mt19937_disk_cone_rf_phase.py) 注册 `disk` 的
`mt19937_uniform_disk_filled_cone_rf_phase_v1` 策略。它保留 RF 多极杆家族源的五次 MT19937 抽样顺序和 CSV
字节序列；公共层物化和验证 receipt，项目只选择冻结请求。

同一模块还注册 `mt19937_uniform_disk_sqrt_cone_rf_phase_v1`。它是 ideal transport 的历史 L1 对照：严格保留
圆盘半径、位置方位、`sqrt(u)` 圆锥半角、速度方位、RF 周期内出生时间的五次取样顺序；它不能替换
filled-cone 策略，因为两者的角度统计语义不同。

[`dotnet_gaussian_box_ion11.py`](dotnet_gaussian_box_ion11.py) 保留 OA-TOF 历史 ION11
盒状 Gaussian 源的固定 `.NET Random` 序列兼容实现。它同样是公共采样器；项目只传入源参数，
不再保有生成算法。

[`numpy_box_cone.py`](numpy_box_cone.py) 提供矩形横向位置、均匀能量、filled-cone
方向与 RF 相位的确定性 NumPy 释放。它返回不含项目坐标映射的相空间；L1 四极杆
质量过滤器只将其投影为 SI 积分状态。

[`continuous_axial_volume.py`](continuous_axial_volume.py) 拥有注册的
`ion_source_volume_cylinder_v1` 连续前端源。它保留活动源请求字段和 seeded 随机抽样顺序，因此同一
请求仍产生相同 canonical CSV；消费者通过 `materialize_release_from_file` 调用注册表，不再导入多极杆
项目内 sampler。

每次物化都写入仓库 canonical 列序：

```text
particle_id,birth_time_s,x_mm,y_mm,z_mm,vx_m_s,vy_m_s,vz_m_s,mass_amu,charge_state
```

receipt 绑定完整版本化请求、canonical 状态、顺序粒子 ID、CSV 字节数和 SHA-256。`validate_materialized_release`
重新生成表并拒绝任一身份或内容差异。该层不运行求解器，也不构造 FLY2；SIMION 使用者可在通过验证后调用
[`common/simion/particle_source.py`](../simion/particle_source.py) 的纯渲染器。

新增 plane、sphere 或其他 shape 时，必须新增自己的完整 schema/几何边界验证与确定性 sampler，再在
`release.py` 注册明确的 `(shape, strategy)`；不得通过宽松的可选字段把不同几何混入 cylinder 合同。
