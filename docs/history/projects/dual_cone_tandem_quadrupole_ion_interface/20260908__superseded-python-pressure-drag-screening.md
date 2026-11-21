<!-- DOC_STATUS: ARCHIVED_READ_ONLY -->

# 已退役的 Python 压力—阻尼轨迹筛选

本快照冻结项目建立时的低阶 Python 主轨迹路线。该路线使用规定压力、规定轴向气速、低场迁移率阻尼和
理想近轴四极场；它不求解可压缩气流、三维电场、扩散或离散碰撞。用户随后选择以 COMSOL 气流场作为
上游权威、由 SIMION 消费冻结气体场执行离子轨迹，因此 `pressure_drag_screening` 不再是活动 mode，
相关 Python 积分器和公开入口已退役。

退役源码与合同可由 Git 提交 `4de5c62b` 精确恢复。该提交中的输入和实现 SHA-256 也记录在下列原始
run manifest 中；旧 manifest 不改写，新 workflow 不得消费这些 run 作为气流场或轨迹资格证据。

- `20260908_162607__sim__python__dual-cone-screening`
- `20260908_163805__sim__python__dual-cone-common-reuse`

两次运行均只保留 `prototype_geometry_and_transport_trend_screening_only` 的原声明边界。其 success 状态
表示当时入口完成并通过自身合同，不表示传输率、出口能量、COMSOL、SIMION、Candidate 或 Formal
资格。对应 artifact 继续按原 manifest 身份保留；本次退役不授权删除或改写它们。
