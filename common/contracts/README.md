# 机器合同与设计请求

本目录保存跨项目的机器合同 Schema、语义校验器和可追溯规划工具。JSON Schema只判断字段、类型、
单位是否完整；Python语义层判断项目选择、能力成熟度、模式、指标、设计变量和约束是否成立。
二者不能互相取代。

## 项目发现

项目身份和能力的权威源是各项目`config/project.json`。根`config/project_registry.json`是生成索引，
禁止手改：

```powershell
.\.venv\Scripts\python.exe common\contracts\build_project_registry.py
.\.venv\Scripts\python.exe common\contracts\build_project_registry.py --check
```

## 从自然语言到计划

当前边界是“Agent理解自然语言，确定性工具验证合同”：Agent先把需求翻译成`design_request` JSON，
保留为`proposed`，由使用者批准后才能请求formal证据。校验结果固定为`READY`、
`NEEDS_CLARIFICATION`、`NEEDS_PROJECT_COMPLETION`、`NEEDS_NEW_PROJECT`或`UNSUPPORTED`，不会因为
项目目录存在就假定能力已经完成。

```powershell
.\.venv\Scripts\python.exe common\contracts\validate_design_request.py <request.json>
.\.venv\Scripts\python.exe common\contracts\plan_design_request.py <request.json> `
  --run-id 20260720_120000__analysis__repo__design-request `
  --output-dir <new-run-directory>
```

规划器只写`design_plan.json`和`run_config.json`，不启动商业求解器、不宣称满足指标，也不把
`formal_gate_passed`设为真。后续执行器必须继续使用项目门禁、summary和manifest闭合实际证据。
