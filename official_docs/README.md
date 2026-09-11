# COMSOL 官方离线资料

本目录是本机官方 PDF 原始资料的位置；PDF 被 Git 忽略，干净 checkout 不携带这些手册。表中给出本机文件名，缺失时从已安装 COMSOL 帮助或官方文档获取与目标版本相符的资料。日常任务先查[API 参考](../docs/COMSOL_API.md)、
[排错指南](../docs/COMSOL_DEBUGGING.md)或项目入口；查接口名称、合法值或物理模型时按下表定位。
手册用于查证语义，不能替代当前环境的最小测试、项目证据或 GUI 验收。

| 问题 | 手册 |
|---|---|
| MATLAB 连接、加载、保存、`mph*` 函数与数据提取 | LiveLink for MATLAB：`LiveLinkForMATLABUsersGuide.pdf` |
| `model.*` 对象、feature 类型、属性、合法值与选择集 | Programming Reference：`COMSOL_ProgrammingReferenceManual.pdf` |
| Application Builder、Method、录制代码与应用对象 | Application Programming Guide：`ApplicationProgrammingGuide.pdf` |
| 静电、磁场、线圈与 AC/DC 物理设置 | AC/DC Module：`ACDCModuleUsersGuide.pdf` |
| 释放、力、壁面、碰撞、空间电荷与轨迹语义 | Particle Tracing Module：`ParticleTracingModuleUsersGuide.pdf` |

## 来源与使用边界

文件名不包含版本。本索引已核对文件存在，但未逐份核验 PDF 标题页、版本、页数或原始下载地址；
引用时从手册本身记录版本与章节/页码，不能由当前安装的 COMSOL 版本推定全部离线手册同版。

新增或替换原始资料时记录官方来源、版本和定位信息；不要将手册全文或大段摘录复制到经验文档。
单项目经验写回项目；跨项目知识的提升条件按[仓库架构](../docs/REPOSITORY_ARCHITECTURE.md)执行，
不能因在官方手册中找到一个调用，就把该项目数值或排错经验升级为全仓结论。
