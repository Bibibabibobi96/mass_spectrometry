# MR-TOF项目身份整合（2026-08-02）

DOC_STATUS: ARCHIVED_READ_ONLY

> DOC_STATUS: ARCHIVED_READ_ONLY
>
> Historical snapshot: statements are interpreted at the document date; current authority is the applicable active contract and current project/integration documentation.

## 决策

活动项目身份由`open_path_parallel_mirror_dual_stripe_mr_tof_mass_analyzer`收缩为
`parallel_mirror_dual_stripe_mr_tof`。短名称仍保留平行镜、双条带和MR-TOF三项硬件辨识信息，同时
降低Windows深层路径、SolidWorks外部引用、日志和命令行的长期负担。完整中文`display_name`不变。

本次采用一次性无兼容层迁移：项目目录、`project_id`、生成注册表、根README、Roadmap和项目current
文档只使用短名称。旧长名称从未拥有同名artifact根、新run或formal资产，因此不建立空旧根、alias、
wrapper或虚构legacy artifact映射；其源码演进由Git历史追溯。历史文档保持原文。

## artifact身份迁移

迁移前唯一外部证据根为`mr_tof`，只包含用户CAD种子archive和导航文件。公共身份迁移器生成闭世界
计划并验证121个文件、48,415,159字节，裁剪候选为0，manifest身份异常为0。随后将整棵旧根原子迁入：

`artifacts/projects/parallel_mirror_dual_stripe_mr_tof/archive/`
`20260801_130002__migration-snapshot__repo__mr-tof/legacy-project-root/`

目的地再次通过完整文件集合、字节和SHA-256复核，旧顶层根已消失。外层archive manifest使用当前短
项目身份，内层原始CAD manifest继续保留记录时的`mr_tof`身份、119项CAD清单和原声明边界，不改写
历史证据。项目描述符已切换为`archived_verified`，不保留旧路径回退。

机器清单SHA-256：

- `identity_migration_manifest.json`：
  `C1374504237C2EA5368CE47BC718CAFCF7670A15204FBD2FDE419B37C3A1CBD6`；
- `archive_manifest.json`：
  `34974E111977C3FFFA579D4CBAE9B6AE1643ACABFF8B45E49C8B49579B6FE1D9`；
- 当前`config/project.json`：
  `606268D75ECAD80634D13BF5AE16AE49D72D49CE1FCC4153FA32863B5BAA3291`。

## 验证与边界

- 项目注册表新鲜度：`PROJECT_REGISTRY=PASS PROJECTS=7`；
- artifact布局：`ARTIFACT_LAYOUT=PASS PROJECTS=9 RUNS=522 ARCHIVES=15`；
- 注册表、身份迁移和布局合同：32项测试通过；
- L2全仓静态集成：`REPOSITORY_INTEGRATION_GATE=PASS PYTHON=3.11`；
- 未启动SolidWorks或修改CAD；这次只迁移冻结字节和身份，不证明装配引用、坐标或设计拓扑已审计，
  不改变项目`prototype`状态，也不创建formal资产。
