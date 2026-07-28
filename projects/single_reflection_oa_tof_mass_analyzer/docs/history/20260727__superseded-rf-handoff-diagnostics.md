# oa-TOF 已替代 RF handoff 投影诊断源码归档

<!-- DOC_STATUS: ARCHIVED_READ_ONLY -->

## 归档结论

本清单及同名载荷目录冻结早期 RF→oa-TOF 刚体投影、RF 网格配对投影和投影入口共享时钟脉冲的
源码闭包。它们只证明当时声明范围内的投影功能，不包含真实侧孔、被动连接器或局部联合场，不能覆盖
当前 RF 项目的 S2/S3 物理链、阶段资格或 oa-TOF Formal 阻断条件。

当前替代入口是 RF 四极杆项目的
`tests/cross_solver/run_s3_cumulative_chain.ps1`。该入口先在 COMSOL 中通过真实侧孔和连接器，再从
canonical 局部出口状态续算下游 SIMION；当前状态和资格只以 RF 项目 `docs/PROJECT.md` 为准。
本次迁移不移动、修改或重新评价任何历史 run、Formal 资产或结果。

归档前的活动性审计确认：

- oa-TOF `config/execution_profiles.json`和`config/project.json`没有注册这三个旧 mode；
- `verify_project.ps1`没有显式调用旧 runner；它原先仅通过`test_*.py`通配发现本载荷内随包迁移的
  历史回归测试；
- Candidate `analysis/candidate_source_closure.py`的显式 allowlist 不含本载荷任何路径；
- 批次外仍存在的名称引用只指向历史结果文件或本归档，不构成源码消费。

因此这批文件不再属于活动 capability、execution profile、Static 门禁职责或 Candidate 冻结源码闭包。

## 载荷清单

载荷文件保持归档前字节不变，仅把原仓库路径用双下划线扁平化。原始版本可在提交
`d4f85aff641b731a4209ac7dcc0cf19fbf82bb6a`中追溯。

| 原仓库路径 | 扁平载荷 | SHA-256 |
|---|---|---|
|`projects/oa_tof/analysis/analyze_rf_handoff_projection.py`|[`analysis__analyze_rf_handoff_projection.py`](20260727__superseded-rf-handoff-diagnostics/analysis__analyze_rf_handoff_projection.py)|`609D246E10523AFB1288602EE5B572450B351EE1556F6C4DF860F877F2C7A78E`|
|`projects/oa_tof/analysis/analyze_rf_handoff_pulse.py`|[`analysis__analyze_rf_handoff_pulse.py`](20260727__superseded-rf-handoff-diagnostics/analysis__analyze_rf_handoff_pulse.py)|`00D9B98F1B65B494E71BB9A61F4C3CED9078C81115B9F67F3BAAB7D98AFA1AF3`|
|`projects/oa_tof/analysis/prepare_rf_handoff_projection.py`|[`analysis__prepare_rf_handoff_projection.py`](20260727__superseded-rf-handoff-diagnostics/analysis__prepare_rf_handoff_projection.py)|`E520C0218D54BFF77B1526EFDA69373DFE64A2764990C7E1B37E0370B45C5804`|
|`projects/oa_tof/config/modes/rf_handoff_projection.json`|[`config__modes__rf_handoff_projection.json`](20260727__superseded-rf-handoff-diagnostics/config__modes__rf_handoff_projection.json)|`754B16B973A6D08484A230026A8124B099E1E22C683A3F9580D08E9EBEA59634`|
|`projects/oa_tof/config/modes/rf_handoff_pulse.json`|[`config__modes__rf_handoff_pulse.json`](20260727__superseded-rf-handoff-diagnostics/config__modes__rf_handoff_pulse.json)|`ED0AEC0536F5285F6CF359A84D00836C6FD4CC67E0DBA788A798396499511B4A`|
|`projects/oa_tof/config/modes/rf_hybrid_mesh_projection.json`|[`config__modes__rf_hybrid_mesh_projection.json`](20260727__superseded-rf-handoff-diagnostics/config__modes__rf_hybrid_mesh_projection.json)|`FE95358002046B340B30D9F5E1CE55BB5A1F279F0F6DBE7A6221EAFA509D8040`|
|`projects/oa_tof/diagnostics/legacy_rf_projection/verify_inputs.ps1`|[`diagnostics__legacy_rf_projection__verify_inputs.ps1`](20260727__superseded-rf-handoff-diagnostics/diagnostics__legacy_rf_projection__verify_inputs.ps1)|`30BB967A806A48A61E12966D86B31DF0A6E9742178A9982644A417EEFADE8266`|
|`projects/oa_tof/tests/analysis/test_rf_handoff_projection.py`|[`tests__analysis__test_rf_handoff_projection.py`](20260727__superseded-rf-handoff-diagnostics/tests__analysis__test_rf_handoff_projection.py)|`10F15B3BED802A3E0A023B41967628EE51A0BBC3B9B9A2213B82C2DD5A5D1A7A`|
|`projects/oa_tof/tests/cross_solver/run_rf_handoff_projection.ps1`|[`tests__cross_solver__run_rf_handoff_projection.ps1`](20260727__superseded-rf-handoff-diagnostics/tests__cross_solver__run_rf_handoff_projection.ps1)|`4CB118814361EDFD707AD65F9277D73E97F55354A807E1B149BE5AF2C48313C1`|
|`projects/oa_tof/tests/cross_solver/run_rf_handoff_pulse.ps1`|[`tests__cross_solver__run_rf_handoff_pulse.ps1`](20260727__superseded-rf-handoff-diagnostics/tests__cross_solver__run_rf_handoff_pulse.ps1)|`D5E4725533D1E22058A2C5F3AB8DA2DA5E900E964EE81CA0672B947AE5A7A389`|

统一校验入口为
[`SHA256SUMS.txt`](20260727__superseded-rf-handoff-diagnostics/SHA256SUMS.txt)。

## 历史 run 身份

本批次配置冻结或消费的主要历史证据仍保留在 Git 外 artifacts：

| 角色 | 身份 | 审计状态 |
|---|---|---|
|旧 COMSOL/SIMION RF 接口源|`20260719_212436__migration-snapshot__repo__pre-v2-layout` archive 中的两份状态及原 run manifest|archive manifest存在；mode按文件大小和SHA复核|
|RF低成本网格源|`20260722_030000__sim__comsol__rf-hybrid-n100__hend0p5__r02`|success manifest|
|RF参考网格源|`20260722_031000__sim__comsol__rf-hybrid-n100__hend0p25`|success manifest|
|早期刚体投影|`20260720_164843__sim__cross__rf-handoff-projection__n100`|oa-TOF success manifest|
|网格配对投影|`20260722_050000__sim__cross__rf-hybrid-mesh-projection__n100__r03`|oa-TOF success manifest；RF合同记录的当前历史投影结果|
|共享时钟有限脉冲|`20260722_083000__sim__simion__rf-entry-finite-pulse__n100__r13`|RF合同记录的最终历史脉冲结果|

同目录中更早的投影和脉冲尝试仍按各自 manifest 保留，但不替代上表中的历史结论。活动替代证据是
RF项目`20260724_205559__sim__cross__rf-oatof-s3-end-to-end-gap1__n100`累积链；它不属于本载荷，也不因
本次源码归档而复制。

## 复现边界

本载荷是原始源码快照，不是可从当前位置直接执行的自包含包。历史脚本依赖归档时仓库中的
`rf_handoff_adapter.py`、`build_handoff_pulse_program.py`、`solver_diagnostics.py`、COMSOL固定粒子重放、
SIMION Formal分析入口、公共run/manifest机制，以及RF项目的handoff builder与合同；还依赖上表中的
Git外状态、manifest和oa-TOF Formal资产。扁平化后相对导入和路径推导故意不再可执行。

若必须重放，应从上述Git提交恢复原目录结构，逐项复核本清单SHA和外部manifest身份，并在隔离run中按
当时软件边界执行。不得直接修改本载荷、把历史代码重新加入Static或execution profile，也不得把重放
结果解释为当前S2/S3或Formal证据。
