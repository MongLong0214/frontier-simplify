# Frontier-simplify benchmarks: Fable and Astra

Frontier-simplify targets Fable and Astra (`gpt-6-astra`). Model names in recorded results identify
what actually ran, not which models the skill is intended for. There is no Fable measurement yet.

Same prompt, same model, four arms (see [`prompts/_arms.md`](prompts/_arms.md)): nothing, two
one-line instructions, and the full skill. Built so the skill can lose.

## Astra spot check (2026-09-09)

`gpt-6-astra`, `xhigh`, Codex CLI 0.153.4, scenario `02-process`, **one run per arm**.
Both credential-only homes and all work directories were temporary; only the treatment home
contained the core skill. No personal ancestor instructions or sibling outputs were read.
Each linked directory preserves the exact `req.md`, `process.md` and `run.log`, including the
model banner. The treatment transcript shows the actual `frontier-simplify/SKILL.md` read.

| Arm | `process.md` lines | Skill read |
|---|---:|:---:|
| [Plain](results/02-process-off-astra-isolated-20260909/) | 246 | No |
| [Korean one-line instruction](results/02-process-oneline-astra-isolated-20260909/) | 81 | No |
| [English one-line instruction](results/02-process-oneline-en-astra-isolated-20260909/) | 152 | No |
| [Frontier-simplify](results/02-process-on-astra-isolated-20260909/) | 33 | Yes |

The 33-line output includes a development flow and verification of scoring, execution isolation,
result storage and fair comparison. These are observed contents, not proof of correctness.
This spot check reports line counts, **not new ceremony scores**, Fable effectiveness or safe
code-review convergence. Do not pool it with the historical five-scenario scores below.
An earlier control started inside the maintainer's checkout and read personal ancestor instructions;
it was stopped and excluded before this complete isolated four-arm run, not chosen by outcome.

To repeat with fresh output paths: `FRONTIERSIMPLIFY_TAG=my-astra-run ./run.sh 02-process`.

## Reproduce

```bash
./run.sh 01-prd        # PRD for one small feature — document inflation
./run.sh 02-process    # dev process for a 0-line solo project — process invention
./run.sh 03-loop       # a repo already trapped in its own gates — loop escape
./run.sh 04-guardrail  # process is legitimately required — the skill must NOT cut it
./run.sh 05-incident   # one bad merge — reactive rule inflation vs a regression test
```

`04-guardrail` and `05-incident` test the skill's failure modes, not the model's. A
ceremony-cutting skill that strips a PCI-DSS release checklist a 12-person payments team
explicitly asked for is broken, and `04-guardrail` exists to catch that. `05-incident` seeds a
small repo (see `seeds/`) and measures what the agent reaches for after one bad merge: a
regression test for the actual bug, or new standing rules bolted onto AGENTS.md.

`03-loop` is the discriminating one. It describes a repository whose verification machinery has
outgrown its product and whose gate has stopped passing anything, then asks for a plan. An
instruction to "make the smallest change" points straight at repairing the pin-reconciliation
script — the smallest change that keeps the loop running. Escaping requires naming the
machinery as the problem and deleting it, which is what stages 3 and 4 of the skill are for.

```bash
./routing.sh           # does the agent reach for the skill when it should, and only then?
```

`run.sh` measures what the skill does once loaded. `routing.sh` measures whether it gets loaded
at all — the axis ACES ([arXiv:2608.20614](https://arxiv.org/abs/2608.20614)) reports that no
document scan can observe. It runs eight probes: four the skill must fire on, and four it must
stay out of because its own *Never cut these* section puts them off limits (unit tests, fixing
an injection, accessibility, a data migration). Negative probes run twice — once with the skill alone
(`isolation`), once with four competing neighbour skills installed alongside it (`group`, the
realistic install); positive probes run in group mode. Activation is read off the transcript rather than judged: Codex opens a
skill by reading its `SKILL.md`, so the path lands in `run.log`. The two historical sweeps — before and after the
description fix the first sweep prompted — are in
[`results/SCORES.md`](results/SCORES.md#discovery-and-routing), with raw outputs under
`results/routing/` and `results/routing-v1-predesc/`.

Requires an authenticated `codex` CLI. The default is `gpt-6-astra` at `xhigh`. Override it with
`FRONTIERSIMPLIFY_MODEL` and `FRONTIERSIMPLIFY_EFFORT`. Choose `FRONTIERSIMPLIFY_TAG` for a new run;
existing outputs are never overwritten. The old `SOLSIMPLIFY_*` variables remain fallback aliases.
Outputs land in `results/<prompt>-<arm>-<tag>/` and `results/routing-<tag>/<probe>-<mode>/`.
Both helpers execute outside the checkout in temporary work directories so they do not inherit
the maintainer's ancestor instructions or see sibling results. Every arm gets the same scope instruction.

Control arms run against a throwaway `CODEX_HOME` containing only your credentials. Moving
an installed skill aside is **not** sufficient: a parked skill still reached the model in one
historical run, apparently through cached discovery — the output carried the then-current
`sol-simplify:` markers that a bare one-line prompt could never produce. The contamination is
silent, so `run.sh` greps every control arm for skill artifacts and prints a warning if any
appear. If you reproduce this benchmark by hand, check for that leak before believing a control.

## What is measured

**Ceremony count** is the headline, scored 0–10 against the fixed rubric in
[`RUBRIC.md`](RUBRIC.md) — one point per category invented without being asked, categories not
instances, requested items never scored, every point cited to a line in the committed output:

Line count is reported alongside, but it is a **crude proxy and can mislead**. A run that spends
its extra lines specifying four API endpoints is longer and *better*; a run that spends them on
a rollout plan is longer and worse. One observed pair: 116 lines vs 164 lines, both with a
ceremony count of zero — the longer one simply wrote the API contract out in full. Judge the
ceremony column, then read the outputs.

**Not measured, deliberately:** correctness. A shorter document is not automatically a better
one. Outputs are committed in `results/` so the reduction can be judged rather than taken on
faith.

## Known limitations of the committed results

Read these before quoting any number.

- **The initial historical runs were not environmentally symmetric.** Control arms ran in a throwaway
  `CODEX_HOME`; the skill arms ran in the author's real `~/.codex`, which also held other
  skills and settings. `run.sh` now builds *both* bases from credentials alone and adds only
  the skill to the treatment base. Those initial runs cannot fully attribute their effect to
  this skill alone. The separately tagged symmetric `02-process` spot checks use the corrected setup.
- **Single scorer, no blinding.** One person scored every run against the rubric, knowing
  which arm produced it. Re-scoring by someone else is the obvious next step; every score
  cites a line so disagreement can be specific.
- **Loop-commit counts are a subject-line heuristic.** `measure.sh` labels them *candidate*
  loop commits for that reason. Confirm with diffs before saying a commit shipped nothing.
- **Initial document runs lack transcripts.** Historical `05-incident` preserves a full work
  tree (source, tests, workflow, `run.log`). The initial document scenarios were run before `run.sh`
  captured `run.log`, so their transcripts are gone and cannot be reconstructed. Re-running
  any of them with the current `run.sh` writes `run.log` alongside the document.

## Honesty

- **n=1–3 per cell.** `01-prd` and `02-process` have three runs per arm and report medians;
  `03-loop` has one; `04-guardrail` and `05-incident` have one or two, and every run is listed
  rather than collapsed. Treat all of it as a demonstration of a reproducible effect, not as
  statistics — the sample is far too small for a confidence interval, and quoting one here
  would be exactly the invented precision this project scores against.
- **Do not pool models.** The historical five-scenario scores and routing sweeps used
  `gpt-5.6-sol` at `xhigh`. New Astra measurements are separate; Fable remains an intended use
  case without measured results. The failure mode may be weaker or absent on another model.
- **No per-repo savings claims.** The lean version of your project was never written, so there
  is no baseline to subtract from. The only real numbers are the ones in `results/`.
