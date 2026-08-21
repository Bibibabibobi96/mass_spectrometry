# 2026-08-02 文档内容、权威与格式审计

DOC_STATUS: ARCHIVED_READ_ONLY

## 范围与判据

本次审计覆盖仓库门禁识别的114份Markdown，其中61份为排除任意`docs/history/`后的活动文档。判据为：

- 根README、项目README、PROJECT、软件文档、理论文档和history各自只承担根README规定的职责；
- 当前项目状态只在项目`docs/PROJECT.md`，机器精确值只在版本化配置，日期化结果只在history；
- 活动文档不引用已退役源码或已删除配置，不把已完成任务继续列为开放项；
- 同一公式、系数表或规范正文不在两个活动文档并列维护；
- Markdown链接、标题结构、history载荷、编码和仓库边界通过统一文档门禁。

## 发现与处置

1. `docs/ROADMAP.md`仍把已经完成的旧项目artifact迁移列为当前开放任务，并保留四极杆
   `source_pending_relocation`旧状态。七个项目描述符实际均为`archived_verified`，因此删除该已完成
   任务；完成证据继续只由`docs/AUDITS.md`索引的日期化审计承担。
2. `common/multipole/README.md`复制两批SIMION campaign数值，并声明旧多极杆证据仍处迁移前状态。
   公共README现只保留共享方法、资格合同和状态路由；具体结果回归根history及各项目PROJECT，旧证据
   只从项目描述符的`archived_verified`位置解析。
3. 四、六、八极杆、oaTOF和Wehnelt项目README包含会随运行变化的完成状态、资源终态或数值结果。
   这些入口现只保留稳定边界和导航，当前事实统一路由到各自PROJECT。
4. MR-TOF的TE1/TE2镜电压公式和系数表同时存在于镜设计与注入校准文档。镜设计文档保留唯一正文，
   注入校准文档改为链接并仅说明流程用途。
5. 活动文档未发现对本轮删除的artifact migration、旧轴向配对、旧无加速分析wrapper或六极杆closed
   qualification JSON的引用。

## 核验结果

- `common/verify_documentation.ps1`：PASS，完成态数量以同主题最终门禁输出为准；3个根权威入口。
- 七个项目README均路由根README和项目PROJECT；COMSOL/SIMION/CAD文档均返回PROJECT且无横向网状链接。
- 七个项目`config/project.json`的legacy artifact状态均为`archived_verified`。
- 活动文档中长度不小于120字符的跨文件完全重复段落由2组降为0组。
- 退役源码和六极杆closed配置的活动Markdown引用为0。

## 保留边界

- history按原声明保留旧名称、旧状态和旧数值；它们不是当前权威，不因本次审计改写。
- 项目README仍可保存稳定几何摘要、机器入口和不可变项目硬规则，但不得继续累积运行结果。
- 理论文档可在各自适用域维护推导；跨主题使用同一系数表时必须链接其唯一理论来源。
- 本次只审计和整理文档，没有启动COMSOL、SIMION、MATLAB或CAD运行。
