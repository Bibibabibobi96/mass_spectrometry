# 旧 N1 family 活动源码退役

DOC_STATUS: ARCHIVED_READ_ONLY

旧运行器、活动合同、注册与专属测试已被直属装配工作流取代。该快照保留退役前当前文档中的科学结论、负结果、资格限制及证据定位；它们不因源码迁移获得新资格。原冻结run、PA、cache及既有history保持原身份，不受此源码退役影响。

新的活动入口见[统一集成入口](../../../README.md)。terminal catalog现归`instrument_assembly`；仍需维护的文本绑定由`integrations/runtime/refresh_repository_bindings.py`唯一编译，旧CLI无转发。

## 原始文档载荷

以下原始字节按生命周期扁平载荷方式保存；文内相对链接仍按原`docs/`位置解释，旧命令仅用于追溯。

- 原 `docs/INTEGRATION.md`：[原始文本](20261024__legacy-family-retirement/INTEGRATION.md.txt)；SHA-256 `F8DD2370A590A56293C910794371689581A98CAA34443988C1B9AFBD6CACCD9C`。
- 原 `docs/ARCHITECTURE.md`：[原始文本](20261024__legacy-family-retirement/ARCHITECTURE.md.txt)；SHA-256 `74B57C7C1DE97504342FDCA4F7B934AE3D56FAC1018EE4163A6E42653D3D3831`。
- 原 `docs/RUNNING.md`：[原始文本](20261024__legacy-family-retirement/RUNNING.md.txt)；SHA-256 `F5A39D5A750CA5664F1B06070849843DFB56B3FFA8DB7AEBDC6B9477255BE933`。

- 原 `config/explorations/paper1_c3_j3_s1_fixed_pulse_derivative_n100.json`：[C3/J3 固定脉冲科学合同](20261024__legacy-family-retirement/paper1_c3_j3_s1_fixed_pulse_derivative_n100.json)；来源为退役时仓库 tracked 合同，SHA-256 `FDC69D38411C0B68A9970BC892638F3CB33F2F816756A53F6F202402B8AEE313`。仅作历史科学约束，不恢复旧运行器。

- 原 `docs/HARD_LIMIT_AUDIT.md`：[2026-08-31 硬限制审计原始文本](20261024__legacy-family-retirement/HARD_LIMIT_AUDIT.md.txt)；SHA-256 `DB0E1BBBA676ACD2B2BCFC345F5F8994B48E78DF7D3658113682EDBF53F2905B`。原始字节保留，旧文档相对链接按当时位置解释。
