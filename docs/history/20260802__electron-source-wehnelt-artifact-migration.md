# 电子源与Wehnelt旧身份artifact迁移记录（2026-08-02）

DOC_STATUS: ARCHIVED_READ_ONLY

## 结果

`electron_impact_ion_source`与`wehnelt_electron_gun`两个行政改名前顶层artifact根已经通过仓库唯一
schema v2迁移入口，同卷原子迁入各自当前项目的具名archive。旧run manifest保持原字节、原项目身份
和原声明边界；描述符只保留`archived_verified`定位，不提供旧顶层路径回退。

|旧身份|当前项目|文件|字节|身份异常|目的archive|
|---|---|---:|---:|---:|---|
|`electron_impact_ion_source`|`apertured_tube_electron_impact_ion_source`|13|26,205,132|0|`20260801_130001__migration-snapshot__repo__electron-impact-ion-source`|
|`wehnelt_electron_gun`|`transverse_helical_filament_wehnelt_electron_gun`|409|2,097,411,860|0|`20260801_130004__migration-snapshot__repo__wehnelt-electron-gun`|

## 验证与边界

两棵源树都在apply前完成全文件集、字节数与SHA-256复核；原子移动后又在目的端逐文件复核，并发布
`identity_migration_manifest.json`和`archive_manifest.json`。旧顶层根已消失，当前活动项目根是唯一
顶层定位。迁移没有提升任何历史模型的Candidate或Formal资格。

规划器识别出电子源1个、Wehnelt 12个可重建二进制裁剪候选，共127,636,984字节；本次没有执行
`prune`，因此没有删除任何历史产物字节。若以后需要减容，必须从迁移后载荷重新生成独立裁剪计划、
取得明确授权并保留完成journal，不能把本记录视为删除许可。
