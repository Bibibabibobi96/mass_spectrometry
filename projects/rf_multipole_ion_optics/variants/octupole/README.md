# RF八极杆设计变体

本目录保存RF多极杆项目的八极杆专属设计与科学输入，结构为径向阶数`n=4`、八根电极。
研究范围是有限三维无碰撞传输、机械出口和来源模型比较。当前可装配提供者默认裸杆，接地壳须显式声明。
当前结果、资格和开放动作只见
[PROJECT的八极杆状态](../../docs/PROJECT.md#oct)，不在本入口复制第二份状态表。

## 阅读与选择

按[项目README](../../README.md#固定阅读顺序)完成启动阅读后，从[design注册表](../../config/design_profiles.json)
选择`octupole_`前缀设计；普通传输的完整绑定见[runtime注册表](../../config/runtime_profiles.json)。
物理解释见[共同理论](../../docs/theory/foundations.md)与[高阶多极杆理论](../../docs/theory/higher_multipoles.md)；
运行入口统一见[项目工作流](../../README.md#工作流入口)。

## 专属输入

[机械base](config/requests/mechanical_base.json)、[显式接地壳请求](config/requests/grounded_shell.json)、[变量](config/design_variables.json)、[包络](config/optimization_envelope.json)、[完整N=100源](config/sources/family_complete_mother_n100.json)、[524 Da源](config/sources/planar_524da_2ev_n100.json)。

当前壳体与可选带孔端盖采用共同几何机制，端盖与壳连续连接并共用0 V；独立孔板／透镜由外部提供者拥有。
旧闭壳、单／双端贯通结论只属于冻结旧几何，不继承为当前裸杆或显式壳体资格。
100 Da完整母群与524 Da源分别声明；旧嵌套母样本的前缀身份保持。
内部handoff与真实最外端盖出口各自使用其事件证据，不能仅凭全传输数字互换。
结构变体ID为`octupole`；电气模式和装配外壳选择另有明确字段，不隐式切换模型。

## 来源与产物

原项目ID为`rf_octupole_ion_optics`，旧资格与run由[历史索引](../../docs/history/README.md)追溯。
新运行owner与产物规则见[项目目录与产物](../../README.md#目录与产物)。
