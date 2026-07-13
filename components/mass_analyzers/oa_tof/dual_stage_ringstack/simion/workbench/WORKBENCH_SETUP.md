# oa-TOF Workbench：首轮单离子验证配置

## 已验证的无 GUI 调用

```bat
"C:\Program Files\SIMION-2020\simion.exe" --nogui fly --trajectory-quality 8 --particles oatof_single_100amu.ion --recording oatof_events.rec --recording-enable 1 --recording-output ..\05_results\single_ion.csv oatof_ideal.iob
```

SIMION 2020 已确认该命令存在；其 IOB 是二进制 Workbench 布局文件，必须由 Workbench 保存生成，禁止用文本编辑器伪造或修改。

## 已锁定的统一坐标

完整表见`../05_results/coordinate_mapping.csv`。全局飞行轴是`+z`：释放中心`(0,0,1.5) mm`，加速器出口`z=19.83 mm`，反射镜入口`z=619.83 mm`，级间栅网`z=739.83 mm`，背板前表面`z=826.6628 mm`。探测器中心为`(-48.8,0,19.83) mm`。

`oatof_single_100amu.ion`是首轮唯一粒子：100 amu、+1、初始位置`(0,0,1.5) mm`、沿`+x`的5 eV初速。这与COMSOL的`rel1`设置一致；它不是N=1000统计用的5±1 eV高斯分布。

## 应加入的 PA 实例

| PA | 模型坐标系 | 作用 | 首轮设置 |
|---|---|---|---|
| `../01_accelerator/oatof_accelerator_3d.pa0` | 本地 z 轴为飞行轴；原点是 COMSOL repeller 参考面 | 正交抽取 | 使用已保存的 2240/1760/线性环电压 |
| `../02_reflectron/oatof_reflectron_ideal_10_5.pa0` | 2D cylindrical，本地 x 是反射深度 | 轴对称双级反射镜 | 使用已保存的 10/5 环电压 |

不要在 Workbench 中再次覆盖 PA0 电压。第一轮保持 `ideal_grid`；只有场和单离子轨迹通过 COMSOL 对照后，才加入真实丝网局部修正。

## 验证顺序与接受量

1. 在源区发射一颗 `m/z=100` 的正离子；初始条件与 COMSOL 统计的基线一致。
2. 记录入口栅网、级间栅网、最大反射深度和探测面事件。
3. 与 COMSOL 正式 10/5 环基线比较：总到达时间 `31.44793 us`，最大二级穿透 `51.07 mm`。
4. 仅当单粒子轨迹、轴线 `V(z)` 和 `Ez(z)` 均一致时，再依次运行 N=100、N=1000。

## 坐标纪律

- 全局飞行轴和局部加速器轴均定义为 `+z`；不得把此前 SolidWorks 的装配坐标直接套入 SIMION。
- 反射镜 PA 的局部轴向`x`须旋转/映射为全局`+z`；入口栅网定义为反射镜深度零点，并放在`z=619.83 mm`。
- 探测面位于加速器出口侧横向偏移后的 COMSOL 基准位置；设置后先以一颗无初速离子检查其是否穿过。
- 任何坐标变换均在 `05_results/coordinate_mapping.csv` 记录后才可批量飞行。
