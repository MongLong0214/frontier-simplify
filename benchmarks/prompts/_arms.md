# Control arms

The benchmark runs four arms per prompt so the skill has to earn its length:

| arm | what is injected |
|---|---|
| `off` | nothing |
| `oneline` | `불필요한 절차·문서·게이트를 만들지 마라. 요청한 것만 만들어라.` |
| `oneline-en` | `Make the smallest change that fully solves the task. Do not add abstractions, fallbacks, defensive guards, refactors, or features unless they are strictly required.` |
| `on` | the full `skills/frontier-simplify/SKILL.md` |

`oneline-en` is the widely-shared one-line fix for Codex over-engineering. If a single
sentence matches a 100-line skill, the benchmark should say so — that is the point of
including it.
