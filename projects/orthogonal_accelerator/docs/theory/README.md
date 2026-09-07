# 正交加速器理论入口

本目录维护正交脉冲加速器这一硬件设计概念的局部理论。二区和三区是同项目内的结构变体，
不是同一硬件的电压 mode；参数、几何和验证身份仍须按变体区分。当前能力和资格只查
[`PROJECT.md`](../PROJECT.md)，机器精确输入只查项目 `config/`。

## 阅读顺序

1. [`oaaccelerator_time_focus.md`](oaaccelerator_time_focus.md)：二区静止释放、场与能量、第一时间焦距、
   等场退化、紧凑边界和单位。
2. [`affine_phase_space_time_focus.md`](affine_phase_space_time_focus.md)：有符号初始速度、局部位置—速度
   相关、实际能量、焦距、导数及随机残差。
3. [`three_zone_accelerator_ideal_theory.md`](three_zone_accelerator_ideal_theory.md)：三区精确时间、局部
   一至四阶导数、二区退化、完整源可达性与装配接口。

## 部件与整机边界

独立加速器输出局部电极与源坐标、出口、第一时间焦距、实际能量和时间导数；它不决定调用方的
全局原点、棱镜、反射器电压、多圈返回或检测时间。第一时间焦面不是必然的空间束腰，也不是最终质量焦面。

单次反射 oa-TOF 的源到 detector 框架、加速器—反射器联合一至三阶闭合、有限束宽分辨率与
T0—T5实验仍由其[理论入口](../../../single_reflection_oa_tof_mass_analyzer/docs/theory/README.md)导航。
MR-TOF 的坐标、中央交接面及多次反射由其
[理论入口](../../../parallel_mirror_dual_stripe_mr_tof/docs/theory/index.md)导航。

## 迁移与证据边界

双区正文从单次反射 oa-TOF 的同名文档迁入；affine 和三区正文按“局部加速器／下游整机”拆分，
没有复制一套并行公式。旧双区路径只留迁移导航，旧 affine/三区路径继续承载整机连接内容。
原 oa-TOF 的历史文档、run、Formal CAD/PA/IOB 和验证身份保持只读，不自动归属新项目。

这些推导属于经典基础或解析 oracle；单纯迁移不会产生新颖性、三维场、传输、分辨率或 Formal 资格。
二区和三区的完整源、场网格、时间步、独立求解器和工程验证必须分别执行。
