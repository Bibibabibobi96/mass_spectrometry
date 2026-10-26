# COMSOL 官方离线资料

返回[参考资料索引](../README.md)。本页定位现有COMSOL原始资料，不维护项目结论或运行证据。任务分流返回
[COMSOL 阅读入口](../../tools/COMSOL_GUIDE.md)。查接口名称、合法值或物理定义时，只进入下表对应章节。

PDF 被 Git 忽略，干净 checkout 不携带手册；缺失时从已安装帮助或官方文档获取与目标版本相符的
资料。手册用于查证语义，不能替代当前环境的最小测试、项目证据或 GUI 验收。

| 问题 | 本机文件 | PDF 内声明版本 | 总页数 |
|---|---|---|---:|
| MATLAB 连接、加载、保存、`mph*` 函数与数据提取 | `LiveLinkForMATLABUsersGuide.pdf` | 6.3 | 400 |
| `model.*` 对象、feature 类型、属性、合法值与选择集 | `COMSOL_ProgrammingReferenceManual.pdf` | 6.3 | 1234 |
| Application Builder、Method、录制代码与应用对象 | `ApplicationProgrammingGuide.pdf` | 6.3 | 326 |
| 静电、磁场、线圈与 AC/DC 物理设置 | `ACDCModuleUsersGuide.pdf` | 6.4 | 540 |
| 释放、力、壁面、碰撞、空间电荷与轨迹语义 | `ParticleTracingModuleUsersGuide.pdf` | 6.4 | 414 |

## 来源与使用边界

2026-10-22使用已有 PDF 解析器只读核对了全部五份文件的封面、PDF 第2页的 Version、metadata Subject
和总页数；上表版本与这两处声明一致。本机三份6.3手册不能冒充6.4接口权威，新增或不确定的6.4调用
应查目标版本在线参考或已安装帮助。原始下载地址与供应商文件逐字节同一性尚未核对；没有下载、替换
或修改原 PDF。文件名不包含版本，替换文件后须重新核验，不能由安装版本推定手册版本。

2026-10-26目录整理时逐文件核对的本地副本身份如下；这些指纹用于确认同一副本，不表示已核对供应商下载原件。

| 文件 | bytes | SHA-256 |
|---|---:|---|
| `LiveLinkForMATLABUsersGuide.pdf` | 6986465 | `3acfd7bd693133554b3dbbec630e4ce498a5a9e5f349d95a21ab861475abb41b` |
| `COMSOL_ProgrammingReferenceManual.pdf` | 14004767 | `b24bb4f9af926f0c538fdacf4a1e1bb796d58b86b1ed173dd20b04cbba5af904` |
| `ApplicationProgrammingGuide.pdf` | 11720793 | `82a6df2bfe505dc315d729ad699e66fc06adb585c0c117c1589b1ec6c2d4d686` |
| `ACDCModuleUsersGuide.pdf` | 5136912 | `9fe503ff8d28d1c039085f47fb120f7a8f7bc739f13f8459a124308d0f2f6642` |
| `ParticleTracingModuleUsersGuide.pdf` | 4809371 | `e973f0d583a2553153f0ddcfc5e2266f4b1b89ea24b0eb20c0ca33636757d435` |

以下 COMSOL 官方在线定位已于2026-10-22核对，明确限定为6.4页面；它们不替代对本机离线 PDF 的版本核验：

| 要核对的语义 | 官方定位 | 使用边界 |
|---|---|---|
| Time 的控制来源、活动积分器属性与输出存储 | [Time，表6-74](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_solver.51.51.html) | 通用属性默认值不等于物理接口自动生成序列的实际设置 |
| 粒子数据集、表达式、指定 t 与返回字段 | [mphparticle，表6-34/6-35](https://doc.comsol.com/6.4/doc/com.comsol.help.llmatlab/llmatlab_ug_ref.9.51.html) | 官方函数语义不证明具体查询位置、速度或事件满足项目精度 |
| 壁面重赋值与原生事件记录 | [Wall](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.04.html)、[辅助变量](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_modeling.05.15.html) | 支持重置不保证任意积分器和查询时刻的终态回读正确，实证查 OA 项目 |
| 粒子数值评价与轨迹平面交点 | [Particle Evaluation，表7-106](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_results.52.119.html)、[IntersectionPoint3D](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_results.52.083.html) | 数量选择不是 ID；求交行数不等于唯一事件或完整目标身份 |
| 所选几何范围是否已建网 | [Mesh Status](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_mesh.49.031.html) | selection 范围须与物理域一致；完整建网不等于收敛 |
| 曲面碰撞与几何表示阶次 | [Geometry and Mesh Settings](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_modeling.05.10.html)、[组件 API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.23.html) | 边界网格表示与精确 CAD 曲面有差异；不以时间容差替代几何表示收敛 |
| 求解器日志能计量什么 | [The Log Window](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_solver.36.113.html)、[Advanced](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_solver.51.17.html) | 总阶段时间和 Res／Tfail 等计数不提供 CPT 各内部机制的独立秒数 |
| 启动参数 | [COMSOL Commands on Windows，表22-2](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_running.38.31.html) | `memoptassem` 的页面枚举与本机解析器存在差异，实际边界见公共启动器说明 |

新增或替换原始资料时记录官方来源、版本和定位信息；不要将手册全文或大段摘录复制到经验文档。
单项目经验写回项目；跨项目知识的提升条件按[仓库架构](../../REPOSITORY_ARCHITECTURE.md)执行，
不能因在官方手册中找到一个调用，就把该项目数值或排错经验升级为全仓结论。
