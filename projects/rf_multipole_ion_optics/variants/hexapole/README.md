# RF六极杆设计变体

本目录保存RF多极杆项目的六极杆专属设计与科学输入，结构为径向阶数`n=3`、六根电极。
研究范围是理想场、圆杆场筛选与有限三维无碰撞传输；RF参数筛选结论保持原证据范围。当前结果、资格和开放动作只见
[PROJECT的六极杆状态](../../docs/PROJECT.md#hex)，不在本入口复制第二份状态表。

## 阅读与选择

按[项目README](../../README.md#固定阅读顺序)完成启动阅读后，从[design注册表](../../config/design_profiles.json)
选择`hexapole_`前缀设计；普通传输的完整绑定见[runtime注册表](../../config/runtime_profiles.json)。
物理解释见[共同理论](../../docs/theory/foundations.md)与[高阶多极杆理论](../../docs/theory/higher_multipoles.md)；
运行入口统一见[项目工作流](../../README.md#工作流入口)。

## 专属输入

[机械base](config/requests/mechanical_base.json)、[变量](config/design_variables.json)、[包络](config/optimization_envelope.json)、[圆杆场筛选](config/round_rod_field_screen.json)。

这里保留机械、圆杆近似与工程比较输入。P0 RF基线在新的具名科学合同建立前保持不变；
共享运行器或N=1000比较不构成自动选择新工作点的依据。
结构变体ID为`hexapole`；电气模式和装配外壳选择另有明确字段，不隐式切换模型。

## 来源与产物

原项目ID为`rf_hexapole_ion_optics`，旧资格与run由[历史索引](../../docs/history/README.md)追溯。
新运行owner与产物规则见[项目目录与产物](../../README.md#目录与产物)。
