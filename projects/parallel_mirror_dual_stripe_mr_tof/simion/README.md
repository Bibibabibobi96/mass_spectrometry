# MR-TOF Candidate SIMION 路径

`../analysis/simion_candidate_reference.py`由
`../config/simion_candidate_two_zone.json`生成候选 GEM 拓扑。它使用项目坐标：`z`是反射方向、`y`是漂移方向、`x`是横向聚焦方向，`z=0`是中央注入参考面。

本机官方依据为 SIMION 2020 的`examples/geometry/parallel_plate_capacitor_2d.gem`（零宽、节点对齐的理想栅）及`examples/field_dump/field_dump.lua`与`fielddumplib.lua`（Workbench 场导出），查阅日期为2026-09-02。当前 GEM 只冻结五电极镜和四个物理 Stripe 的候选拓扑；加速器、棱镜、接地屏蔽、PA边界、ideal-grid 行和 IOB 必须等待 SolidWorks CAD 审计和数值合同后生成。不得把该文本当作 Formal 资产或运行已验证模型。
