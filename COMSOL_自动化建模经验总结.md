# COMSOL 6.4 自动化建模经验总结（已拆分，本文件仅作重定向）

> 本文件原来是单体大文档（1300+行），已按内容性质拆分成4份独立文档，便于以后不同项目
> 分别调用查看、分别喂给AI。**请勿再往这个文件里追加内容**，按下表去对应的新文件里加。

**先读 [`README.md`](README.md)**——它解释了每份新文档的
用途、边界、以及"新发现该写进哪一份"的判断规则。

| 内容 | 新文件 |
|---|---|
| 通用COMSOL/MATLAB API调用速查、已验证部件库 | [`COMSOL_MATLAB_API手册.md`](COMSOL_MATLAB_API手册.md) |
| 通用调试方法论（分辨率排查流程、崩溃恢复、几何/选择集通用陷阱） | [`COMSOL_调试方法论.md`](COMSOL_调试方法论.md) |
| oa-TOF正交加速+双级环栈反射镜分析器的当前参数与项目专属教训 | [`components/mass_analyzers/oa_tof/dual_stage_ringstack/docs/项目_oaTOF双级环栈反射镜.md`](components/mass_analyzers/oa_tof/dual_stage_ringstack/docs/项目_oaTOF双级环栈反射镜.md) |
| 螺旋灯丝+Wehnelt电子枪项目的物理结论 | [`components/electron_sources/wehnelt_electron_gun/项目_螺旋灯丝Wehnelt电子枪.md`](components/electron_sources/wehnelt_electron_gun/项目_螺旋灯丝Wehnelt电子枪.md) |

> 脚本按部件放在`components/`下；跨部件复用代码和验证基线放`common/`。oa-TOF、
> RF四极杆碰撞冷却、离子源和电子枪互不混装，规则见`README.md`。

原始未拆分版本（含完整的逐帧调试叙事，供交叉核对细节用）存档于
[`COMSOL_自动化建模经验总结_旧版存档.md`](COMSOL_自动化建模经验总结_旧版存档.md)。
