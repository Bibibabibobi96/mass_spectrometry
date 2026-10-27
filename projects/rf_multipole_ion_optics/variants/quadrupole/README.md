# RF四极杆设计变体

本目录保存RF多极杆项目的四极杆专属设计与科学输入，结构为径向阶数`n=2`、四根电极。
研究范围是RF-only传输、RF+DC质量过滤与接口就绪；当前杆系typed模式与矩形专用参考分别消费自己的合同。
当前结果、资格和开放动作只见
[PROJECT的四极杆状态](../../docs/PROJECT.md#quad)，不在本入口复制第二份状态表。

## 阅读与选择

按[项目README](../../README.md#固定阅读顺序)完成启动阅读后，从[design注册表](../../config/design_profiles.json)
选择`quadrupole_`前缀设计；普通传输的完整绑定见[runtime注册表](../../config/runtime_profiles.json)。
物理解释见[共同理论](../../docs/theory/foundations.md)与[四极理论](../../docs/theory/quadrupole.md)；
运行入口统一见[项目工作流](../../README.md#工作流入口)。

## 专属输入

[机械base](config/requests/baseline.json)、[变量](config/design_variables.json)、[包络](config/optimization_envelope.json)、[质量过滤源](config/official_particle_source.json)。

当前可装配提供者默认裸杆；显式接地壳及连续接地端盖采用项目共同几何合同，外部光学单独装配。
专属接口／质量过滤数值与三变体typed传输数值分属不同合同；选择矩形参考时不能把其几何当作圆柱装配提供者。
软件实现边界见[COMSOL](../../docs/COMSOL.md)与[SIMION](../../docs/SIMION.md)。
结构变体ID为`quadrupole`；电气模式和装配外壳选择另有明确字段，不隐式切换模型。

## 来源与产物

原项目ID为`rf_quadrupole_ion_optics`，旧资格与run由[历史索引](../../docs/history/README.md)追溯。
新运行owner与产物规则见[项目目录与产物](../../README.md#目录与产物)。
