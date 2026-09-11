# RF八极杆离子光学

本项目是RF多极杆家族的八极杆设计线。当前参数、资格、有效结论和开放任务只以
[`docs/PROJECT.md`](docs/PROJECT.md)为准；本页只负责导航。

## 阅读顺序

1. 仓库根[`README.md`](../../README.md)。
2. 本项目[`docs/PROJECT.md`](docs/PROJECT.md)。
3. 共享实现与术语：[`common/multipole/README.md`](../../common/multipole/README.md)。
4. 理论背景：
   [共同理论](../../docs/multipoles/foundations.md)和
   [高阶多极杆](../../docs/multipoles/higher_multipoles.md)。
5. 跨器件单流程：
   [RF多极杆→oaTOF integration](../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/README.md)。

## 机器权威

项目身份见 [project.json](config/project.json)；机械、电气、源、数值和资格合同统一由
[PROJECT](docs/PROJECT.md)导航。共享编译与运行方法见
[公共多极杆入口](../../common/multipole/README.md)，跨器件连接见
[RF 多极杆→oaTOF integration](../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/README.md)。

## 执行

- COMSOL：[`analysis/run_finite_3d_transport.ps1`](analysis/run_finite_3d_transport.ps1)
- SIMION：[`analysis/run_simion_finite_3d_transport.ps1`](analysis/run_simion_finite_3d_transport.ps1)
- 静态门禁：[`verify_project.ps1`](verify_project.ps1)

入口接受具名 runtime profile，或一个已预登记的 multipole campaign 加 experiment ID；后者仍解析为同一份
冻结 runtime contract，不能用作任意参数覆盖。产物只写
`artifacts/projects/rf_octupole_ion_optics/`；历史证据只按项目descriptor的
`archived_verified`位置读取。


## History索引

<details>
<summary>展开只读历史记录</summary>

- [20260723__pre-n100-multipole-functional-evidence](docs/history/20260723__pre-n100-multipole-functional-evidence.md)

- [源模型描述性比较](docs/history/20260911__source-model-comparison.md)

</details>
