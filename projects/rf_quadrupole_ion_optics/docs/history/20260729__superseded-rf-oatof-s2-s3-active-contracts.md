# RF→OA 旧 S2/S3 活动合同归档

<!-- DOC_STATUS: ARCHIVED_READ_ONLY -->

## 归档结论

本清单及同名载荷目录冻结 RF→OA 语义阶段迁移前的 S2/S3 配置和两个项目私有
resolver。活动实现已由显式 connection profile、公共 resolved connection 以及
`pre_pulse_interface_transport`、`pulse_capture`、`analyzer_transport` 三阶段取代。

这些载荷只用于追溯既有 N=100 功能证据和零物理变化迁移来源，不再属于活动配置、
Static 门禁、execution profile 或运行时依赖。不得从本目录直接执行或把其中字段恢复为
第二套连接拓扑权威。

## 载荷清单

载荷在迁移时保持字节不变，原路径以双下划线扁平化。

| 原仓库路径 | 扁平载荷 | SHA-256 |
|---|---|---|
|`projects/rf_quadrupole_ion_optics/analysis/resolve_s2_connector_case.py`|[`analysis__resolve_s2_connector_case.py`](20260729__superseded-rf-oatof-s2-s3-active-contracts/analysis__resolve_s2_connector_case.py)|`23DE6E2E7C8B6D4794DB45AC6EBBEE054D89D6E353A3E50F9A741384348B8515`|
|`projects/rf_quadrupole_ion_optics/analysis/resolve_spatial_registration.py`|[`analysis__resolve_spatial_registration.py`](20260729__superseded-rf-oatof-s2-s3-active-contracts/analysis__resolve_spatial_registration.py)|`07052E09EA0928095E01ACB9286DA9BF9D59FB713A2C05CBAB79419A116E3148`|
|`projects/rf_quadrupole_ion_optics/config/resolved_rf_to_oatof_s2_spatial_registration.json`|[`config__resolved_rf_to_oatof_s2_spatial_registration.json`](20260729__superseded-rf-oatof-s2-s3-active-contracts/config__resolved_rf_to_oatof_s2_spatial_registration.json)|`360E05130038C003085838E87F0A32AF62B1F2A819FE28EA5021454EE46DBDBD`|
|`projects/rf_quadrupole_ion_optics/config/rf_to_oatof_s2_dependencies.json`|[`config__rf_to_oatof_s2_dependencies.json`](20260729__superseded-rf-oatof-s2-s3-active-contracts/config__rf_to_oatof_s2_dependencies.json)|`8502B6CAAEF18E8B4F58B6FFCB2D28117EA858CBE72C154AB47AC6859F52DB45`|
|`projects/rf_quadrupole_ion_optics/config/rf_to_oatof_s2_passive_connector.json`|[`config__rf_to_oatof_s2_passive_connector.json`](20260729__superseded-rf-oatof-s2-s3-active-contracts/config__rf_to_oatof_s2_passive_connector.json)|`76F9C93E0877254D4BD36099CC15EC879827EF2ADED35DF7E7EE292BB3332ACE`|
|`projects/rf_quadrupole_ion_optics/config/rf_to_oatof_s3_pulse_capture.json`|[`config__rf_to_oatof_s3_pulse_capture.json`](20260729__superseded-rf-oatof-s2-s3-active-contracts/config__rf_to_oatof_s3_pulse_capture.json)|`F13246CC22BFCBFA2A511CEA4291C7BCAC55F954E105C0941D2E84D56073D80A`|

统一校验入口为
[`SHA256SUMS.txt`](20260729__superseded-rf-oatof-s2-s3-active-contracts/SHA256SUMS.txt)。

## 复现边界

载荷不是自包含可执行包。若必须重放，应从 Git 历史恢复原路径，并按当时冻结的
artifact manifest、COMSOL/SIMION 版本和旧阶段合同隔离执行。历史结果不得覆盖当前
connection profile、resolved connection 或三阶段语义工作流的结论。
