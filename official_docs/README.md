# COMSOL 官方离线资料

本目录是本机官方 PDF 原始资料的位置；PDF 被 Git 忽略，干净 checkout 不携带这些手册。表中给出本机文件名，缺失时从已安装 COMSOL 帮助或官方文档获取与目标版本相符的资料。日常任务先查[API 参考](../docs/COMSOL_API.md)、
[排错指南](../docs/COMSOL_DEBUGGING.md)或项目入口；查接口名称、合法值或物理模型时按下表定位。
手册用于查证语义，不能替代当前环境的最小测试、项目证据或 GUI 验收。
关键调用的已登记证据见[API 验证索引](../docs/COMSOL_API.md#关键能力的证据索引)，共享测试设计与运行
证据的区别见[公共测试说明](../common/comsol/README.md#源码覆盖与运行证据)。

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

以下 COMSOL 官方在线定位已于2026-10-22核对，明确限定为6.4页面；它们不替代对本机离线 PDF 的版本核验：

| 要核对的语义 | 官方定位 | 使用边界 |
|---|---|---|
| Time 的控制来源、活动积分器属性与输出存储 | [Time，表6-74](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_solver.51.51.html) | 通用属性默认值不等于物理接口自动生成序列的实际设置 |
| 粒子数据集、表达式、指定 t 与返回字段 | [mphparticle，表6-34/6-35](https://doc.comsol.com/6.4/doc/com.comsol.help.llmatlab/llmatlab_ug_ref.9.51.html) | 官方函数语义不证明具体查询位置、速度或事件满足项目精度 |
| 所选几何范围是否已建网 | [Mesh Status](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_mesh.49.031.html) | selection 范围须与物理域一致；完整建网不等于收敛 |
| 启动参数 | [COMSOL Commands on Windows，表22-2](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_running.38.31.html) | `memoptassem` 的页面枚举与本机解析器存在差异，实际边界见公共启动器说明 |

新增或替换原始资料时记录官方来源、版本和定位信息；不要将手册全文或大段摘录复制到经验文档。
单项目经验写回项目；跨项目知识的提升条件按[仓库架构](../docs/REPOSITORY_ARCHITECTURE.md)执行，
不能因在官方手册中找到一个调用，就把该项目数值或排错经验升级为全仓结论。
