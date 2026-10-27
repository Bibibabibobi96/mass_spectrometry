# SIMION 最小实现与边界

本文维护 SIMION 的活动入口、表示与验收；当前资格见 [PROJECT](PROJECT.md)。
所有命令从仓库根执行，尖括号内容须替换为显式冻结输入或符合命名合同的新 run ID。

本项目的离子轨迹推进权威是 SIMION。Python 只编译 GEM、校验输入、序列化粒子源和整理证据，不能
积分离子运动。

## 当前执行阻断

当前数值合同和 GEM 固定使用 fractional 表面增强。公共 standalone PA 导出暂不支持保留 `.pa-surf`；不能改为无表面增强，也不能把已发布原生 `.paN` 交给 SIMION。因此原生 C0、共享 Fly 及两种气体来源的运行 wrapper 已整体退役，SIMION transport 执行 profile 已撤下，不保留旧名或阻断 stub。COMSOL 气流、canonical 场校验和纯输入准备继续可用。公共能力验证完成后，再沿统一 PA 事务和资源调度机制建立运行入口。恢复条件及历史资格见 [PROJECT](PROJECT.md#当前资格)。

## 可执行的纯准备

无碰撞 C0 输入准备（不执行供应商）：

```powershell
projects\dual_cone_tandem_quadrupole_ion_interface\workflows\gas_assisted_transport\prepare.ps1 `
  -Mode c0_gem_smoke `
  -OutputDir ..\artifacts\projects\dual_cone_tandem_quadrupole_ion_interface\scratch\<task_id>
```

它生成原 fractional GEM、输入副本和准备 receipt，不创建 PA 或传输率证据。

COMSOL 气体场升级路径的输入准备：

```powershell
projects\dual_cone_tandem_quadrupole_ion_interface\workflows\gas_assisted_transport\prepare.ps1 `
  -Mode gas_assisted_transport -GasFieldManifest <comsol-export-manifest.json> `
  -OutputDir ..\artifacts\projects\dual_cone_tandem_quadrupole_ion_interface\runs\<run_id>
```

在 COMSOL 场 manifest 缺失、字段/坐标域不符、Lua 场文件缺失或 SHA-256 漂移时，入口在调用
SIMION 前失败。当前 `gas_field_interface.json` 的 `current_artifact` 是 `null`，表示尚无全局 current 场；
每次运行仍可显式消费已校验的 COMSOL 场 manifest 或规定均匀场，且须冻结来源。

准备阶段从 SIMION 安装目录的 `examples\collision_sds` 冻结并哈希
`collision_sds.lua`、`mbmr.dat`、`textfilelib.lua`、`arraylib.lua` 和 `m_defs.dat`。这些 SIMION 官方、
受许可约束的文件只进入运行目录，不复制进 Git。RF 电压计算冻结并复用
[`common/simion/rf_drive.lua`](../../../common/simion/rf_drive.lua)；粒子文件由 `common/simion/particle_source.py` 序列化。

当前源圆柱半径为 `1.5 mm`，位于半径 `5 mm` 的上游储气腔内。源可以宽于第一锥 `1 mm` 孔半径；
运行器保留这些离子，并让锥孔电极几何和一致的 COMSOL 流体支持边界代理决定其能否进入下游。

当前两段 RF 均为 `570 kHz` 正弦波，电极组 1/2 分别为 `+300 sin(omega t)` 与
`-300 sin(omega t)` V；因此每组对地峰值为 `300 V`，对置组之间为 `1200 Vpp`。`570 kHz` 是用户
给定 `550–590 kHz` 范围的标称中点，不代表频率扫描已经完成。

## 几何范围

单体 PA 使用电极 `1/2` 表示两锥，`3` 表示末端孔板，`11/12` 表示椭圆杆两相，`21/22` 表示圆杆两相。设备坐标到
Workbench 的平移记录在 `simion_solver_numerics.json`。杆几何由
`common.multipole.simion_geometry.render_grouped_rod_array_gem` 生成，项目不复制圆杆或椭圆杆公式。

当前 C0 GEM 把椭圆杆入口暂时截为 `z=4.6 mm` 平面。真实“沿第二锥面切削”仍需项目级、经拓扑
测试的 CSG mask；在它完成前，C0 只证明 GEM/PA 电极命名和粗几何可编译，不证明入口边缘场。

低压圆柱壳因壁厚和端部结构未知而未虚构为导体；泵口、两段间透镜和出口透镜同样未建模。

## 气体场接口

COMSOL CSV 先由 `analysis/export_simion_gas_runtime.py`（或 `build_gas_runtime.ps1`）在独立校验通过后编译。导出 manifest 必须严格满足 `config/gas_field_interface.json`，并指向一个带 SHA-256 的自包含 Lua
只读场适配器。适配器在设备局部坐标中提供：

- `pressure_pa(x_mm,y_mm,z_mm)`：绝对压力 Pa；
- `temperature_k(x_mm,y_mm,z_mm)`：K；
- `velocity_m_s(x_mm,y_mm,z_mm)`：三分量 m/s。

禁止外推；整个 `z=-5..120 mm, r=0..23.5 mm` 域必须覆盖。圆四极杆在 `z=108.00 mm` 结束，孔板位于 `z=110.22..110.72 mm`，板后保留 `9.28 mm` 观察段；为防止 SDS 在终止步越过气体场，离子终止采样面设在 `z=119.75 mm`。后续飞行 Program 必须通过官方
`collision_sds.lua` 注入这些函数，并通过共享 RF kernel 驱动电极；不得用 Python 阻尼积分器替代。
规则网格的切割单元继续按有效流体角点归一化插值；若一步推进完全离开流体支持但尚未由粗 PA 表面
终止，Program 将其记录为边界代理损失码 `3` 并停止该离子；均匀场的声明域边缘也就是规定气体包络边缘，越出时采用同一损失码。该码与锥壁或包络边界位置一致，但受 `0.1 mm`
流场网格、`0.5 mm` PA 网格和未确认锥口圆角限制，不能单独解释为精确实机撞壁率。真正越出治理坐标域
以外的其他气场执行错误仍是运行错误，不能按损失吞掉。

原型粒子数和当前资格见 [PROJECT](PROJECT.md#当前资格)，束斑统计与原记录的限制见
[原型历史记录](history/20260911__empty-enclosure-gas-transport-prototype.md)。

[返回项目状态](PROJECT.md)
