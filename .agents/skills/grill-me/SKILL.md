---
name: grill-me
description: Stress-test unresolved, high-impact repository plans before implementation. Invoke implicitly when a proposed scientific experiment or preregistration, acceptance criterion, expensive solver campaign, cross-project architecture/schema/identity change, artifact migration, qualification promotion, or destructive cleanup still contains user judgment that could materially change the result. Also use when the user explicitly asks to be grilled or to pressure-test a plan. Do not invoke for approved implementation, routine fixes, status/fact questions, discoverable repository facts, or low-risk documentation edits.
---

# Grill Me

Turn a consequential but under-specified proposal into an implementation-ready
decision set. This repository adaptation permits implicit Agent invocation while
keeping the upstream one-question-at-a-time review style.

## Workflow

1. Announce that this skill is pausing implementation to resolve a material
   decision.
2. Read the applicable `AGENTS.md`, root `README.md`, project `README.md`,
   `docs/PROJECT.md`, machine contracts, and existing evidence first. Never ask
   the user for a fact available there.
3. Restate the proposed outcome and identify the most load-bearing unresolved
   judgment. If the plan is already explicitly approved and adequately
   specified, exit the skill and continue execution.
4. Ask one focused question at a time. Include the recommended answer and its
   concrete trade-off so the user can accept, reject, or refine it.
5. Follow dependent branches before independent details. Prioritize decisions
   that affect physical meaning, comparison validity, evidence qualification,
   irreversible data changes, resource use, architecture authority, or future
   compatibility. Do not pursue theoretical edge cases that cannot change the
   current plan.
6. Do not implement, run expensive tools, change contracts, or write decision
   documents during the interview.
7. Stop when all material branches are decided, the user directs execution, or
   remaining items are explicitly deferred. Summarize:
   - settled decisions;
   - evidence and assumptions;
   - deferred or unresolved items;
   - implementation entry and completion gates;
   - actions not authorized.
8. After the user approves execution, route durable decisions to the repository's
   existing authority locations. Do not create a second plan or glossary unless
   the repository rules require one.

Adapted for this repository from Matt Pocock's MIT-licensed
[`grill-me`](https://github.com/mattpocock/skills/tree/main/skills/productivity/grill-me).
