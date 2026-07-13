# Wehnelt 电子枪组件

`phase1`到`phase4`构成按几何、静电、粒子追踪和热发射逐级加载/保存的 COMSOL 流水线，
`phase5`执行 Wehnelt 参数扫描。运行前先读
[`项目_螺旋灯丝Wehnelt电子枪.md`](项目_螺旋灯丝Wehnelt电子枪.md)。

脚本通过[`egun_paths.m`](egun_paths.m)定位工作区产物：当前可继续计算的模型链位于
`artifacts/components/electron_sources/wehnelt_electron_gun/models/comsol/workspace/`，
结果位于同一组件的`results/comsol/`。因为权威正式模型尚未审定，`workspace/`中的文件
不得直接标记为`formal/`。
