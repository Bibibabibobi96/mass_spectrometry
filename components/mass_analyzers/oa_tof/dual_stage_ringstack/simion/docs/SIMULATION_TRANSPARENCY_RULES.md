# 仿真可见性与可修改性原则（强制）

适用于 oa-TOF 的 SIMION 工作及后续任何仿真软件。

## 基本原则

完成后的正式模型必须能由用户直接在目标软件 GUI 中打开、查看、修改并重新运行。GUI 所见必须与自动化运行时的物理设置完全一致；不得依赖未保存的内存状态、仅命令行生效的覆盖参数或不可见的临时文件。

## SIMION 正式交付要求

1. 正式 Workbench 使用有物理含义的 PA 文件名和实例标签：`accelerator`、`flight_tube_ground`、`reflectron`；不得保留示例模板名（如`bend_x`、`bend_y`）。
2. 每个正式 PA 的`PA#`、`PA0`和必要的电极解`PA1...`都位于项目工作区，并能从 GUI 的 PAs 面板查看与 Fast Adjust 修改。
3. 所有电极电压保存于正式 PA0/PA 解及 GUI 可见的 Fast Adjust 表；不得把`--restore-potentials 0`、临时 Lua 赋值或未保存的内存电位作为正式状态。
4. Workbench 的实例位置、旋转、比例、优先级、ION/FLY2、REC、轨迹质量和用户程序都必须保存在正式 IOB 或其同名关联文件中。
5. 用户程序必须使用与 IOB 同名的`.lua`，其物理参数一律写为`adjustable`变量；每个变量有单位、默认值和用途说明，可在 GUI Variables 面板修改。
6. 任何命令行运行只允许读取这些已保存的正式文件；命令行参数不得改变物理模型。允许的例外仅是计算资源控制（线程数、无GUI）和输出路径。
7. 结果表必须标注所用 IOB、PA、Lua、ION/FLY2 的版本/路径及全部 adjustable 值。

## 当前状态处理

现有`template_bender/`、`template_bngrid/`及其 IOB 仅用于 API 调试，不能视为正式模型，也不能作为 GUI 交付物。后续将从这些调试产物中重建命名清晰的正式 Workbench；在完成前，不报告其飞行时间或分辨率为 oa-TOF 正式结果。
