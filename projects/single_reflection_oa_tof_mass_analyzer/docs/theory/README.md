# oa-TOF 理论入口

本目录的 Markdown 与配套 Python 是当前可执行理论权威；项目参数、状态和正式结果仍以
`../../config/`、`../PROJECT.md`和仓库外运行证据为准。

按问题读取：

- 双区正交加速器一阶空间聚焦：`oaaccelerator_time_focus.md`；
- 多极杆实测线性 `z-v_z` 相空间扩展：`z_vz_linear_phase_space_coupling.md`；
- 二级反射镜局部一、二阶能量聚焦：`dual_stage_reflectron.md`；
- 从释放到探测面的整机纵向耦合：`oatof_oaaccelerator_coupling.md`。

三个层级不能互相替代。特别是，局部反射镜闭式解不包含加速器在一阶焦面处仍存在的二阶时间
曲率，不能直接作为整机二阶聚焦结论。局部闭式解只用于退化检查和初值，不能覆盖耦合模型或
项目当前机器参数。

## 分辨率时钟边界

分辨率公式、飞行时间零点及absolute instrument clock的声明边界只查
[`PROJECT.md`](../PROJECT.md)的分辨率段；本目录不建立第二份权威。

旧 DOCX 保留为 superseded 历史输入，不再作为活跃公式权威：

- [`三栅加速器总长度符号推导.docx`](../history/20260721__superseded-theory-docx/三栅加速器总长度符号推导.docx)；
- [`单次反射TOF二级反射镜等时聚焦推导.docx`](../history/20260721__superseded-theory-docx/单次反射TOF二级反射镜等时聚焦推导.docx)。

原始重写投稿包及 SHA 已冻结在 `../history/20260720__oatof-theory-refactor-review/`；审查清单见
`../history/20260720__oatof-theory-refactor-review.md`。归档不参与活跃程序导入。
