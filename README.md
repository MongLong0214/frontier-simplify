<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg?v=4">
    <img src="assets/logo.svg?v=4" width="480" alt="Frontier-simplify — skills for Fable and Astra">
  </picture>
</p>

<p align="center">
  <em>It built the gate. Then the gate stopped letting it work.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-111111?style=flat-square" alt="MIT license">
  <img src="https://img.shields.io/badge/install-one%20file-111111?style=flat-square" alt="One file">
  <img src="https://img.shields.io/badge/works%20with-Codex%20%C2%B7%20Claude%20Code%20%C2%B7%20Cursor-111111?style=flat-square" alt="Works with">
  <img src="https://img.shields.io/badge/measured%20on-gpt--6--astra-111111?style=flat-square" alt="Measured on gpt-6-astra">
</p>

<p align="center">
  <strong>Built for Fable and Astra: less invented process, fewer repeated reviews.</strong><br>
  <sub>One markdown file. Nothing to configure, nothing to run.<br>
  <b>Astra spot check: 246 lines without the skill, 33 with it.</b><br>
  One process-design scenario, one run per arm. Length is not a quality score. Fable is not benchmarked.<br>
  <a href="benchmarks/">see how that was measured</a></sub>
</p>

<p align="center">
  <sub><strong>English</strong> &middot; <a href="README.ko.md">한국어</a></sub>
</p>

---

# Frontier-simplify for Fable and Astra

Built for frontier coding agents including **Fable** and **Astra (`gpt-6-astra`)**. Coding agents
do not only over-engineer code. They build **bureaucracy around their own work** — gates,
registries, traceability matrices, validators for the validators — and then spend the project
maintaining it. Frontier-simplify cuts that invented process and bounds automatic review attempts.
The skills are model-independent; targeting Fable and Astra does not claim measured results for both.

The core `frontier-simplify` skill is one Markdown file; no plugin or hook is required.
The optional review skill adds an explicitly invoked local runner, described below.

## Install

Pick whichever fits your agent. Then just work — the agent loads the skill on its own when a task calls for it. Nothing to invoke.

**Codex** — as a plugin, versioned and updatable:

```bash
codex plugin marketplace add MongLong0214/frontier-simplify
codex plugin add frontier-simplify@frontier-simplify
```

**Claude Code:**

```
/plugin marketplace add MongLong0214/frontier-simplify
/plugin install frontier-simplify@frontier-simplify
```

**Or just copy the file** — into its own folder under `~/.codex/skills/`, `~/.claude/skills/`, or any tool's rules directory (Cursor, Windsurf, Cline, Copilot). It is plain markdown with standard frontmatter. Keep the folder: a loose `SKILL.md` sitting directly in `skills/` still loads, but it will shadow a plugin install and quietly serve the older copy.

```bash
mkdir -p ~/.codex/skills/frontier-simplify
curl -sL https://raw.githubusercontent.com/MongLong0214/frontier-simplify/main/skills/frontier-simplify/SKILL.md \
  -o ~/.codex/skills/frontier-simplify/SKILL.md
```

To uninstall, delete the file.

### Upgrading from sol-simplify

Version 2.0.0 renames the repository, marketplace, plugin and three skill directories to
`frontier-simplify`, `frontier-simplify-audit` and `frontier-simplify-review`. Remove the old plugin
or standalone skill copies through the same installation method, then install using the commands
above; do not leave both identities active. Update saved script paths and reinstall a local review
hook or poller from the renamed checkout if you use one. Existing review history stays in place:
the old `~/.sol-simplify-review` root is automatically reused so the PR budget cannot reset.
Historical benchmark transcripts and the original review-design/reassessment documents keep their
original names and model identities; they are evidence, not current installation instructions.

## What it does

Asked to design a development process for a project with **no code yet and one maintainer**:

The example below is the historical `gpt-5.6-sol` measurement, not an Astra or Fable result.

**Without** — 437 lines, 35 sections: risk-based quality gates, six test tiers, a CI operating model, a release-candidate checklist, a defect taxonomy, project health metrics, and a section on maintaining the document itself.

**With frontier-simplify** — 58 lines, 6 sections. And it says why:

> No ceremonial self-approval PRs when working alone.
>
> No new documents or global rules because of a single mistake.
>
> When a check fails for reasons unrelated to product behavior, fix or delete the check
> instead of building an exception procedure around it.

The skill was never mentioned in the prompt. Codex found it and applied it on its own.

Process it decides to keep, it marks with a removal condition — so it can be audited later instead of becoming permanent:

```
frontier-simplify: <why this exists>, remove when <condition>
```

## What it never cuts

Correctness. Tests that exercise real behavior. Input validation at trust boundaries. Error handling that prevents data loss. Security. Accessibility. Data migrations. Anything you explicitly asked for.

Restraint applies to process the agent invented, never to the product's real obligations. On the scenario where a payments team facing a PCI-DSS audit explicitly asks for a checklist, approval flow, rollback procedure, and audit records, the skill kept all four — every run, mapped to real PCI DSS v4.0.1 controls.

## Audit a repo that already has the disease

A second skill diagnoses an existing repository instead of preventing a new one. Install it the same way, then say *"audit this repo for ceremony"*.

```bash
mkdir -p ~/.codex/skills/frontier-simplify-audit
curl -sL https://raw.githubusercontent.com/MongLong0214/frontier-simplify/main/skills/frontier-simplify-audit/SKILL.md \
  -o ~/.codex/skills/frontier-simplify-audit/SKILL.md
```

It measures the machinery-to-product ratio, finds maintenance commits that shipped nothing, ranks what to delete, and reports only — it changes no files.

## Stop repeating the same code review

The optional **frontier-simplify-review** skill preserves concrete findings and checks repairs against
them. Its runner is for one maintainer on a trusted local host, not a merge gate or hosted service.
Use a separate installation of this repository, outside the checkout being reviewed:

```sh
export REVIEW_CODEX_MODEL=gpt-6-astra  # Astra when using the Codex executor
skills/frontier-simplify-review/scripts/review-pr.sh "$CONSUMER_REPO" "$PR_NUMBER" auto codex
skills/frontier-simplify-review/scripts/review-pr.sh "$CONSUMER_REPO" "$PR_NUMBER" status codex
```

- Identical inputs reuse the latest attempt. Code, target, supplied context, lessons, response,
  model settings or protocol changes invalidate that reuse. Unchanged failures do not auto-retry.
- Repairs use the original findings and latest review. Rewritten history or a changed base gets
  a fresh scope review within the **same three-attempt PR budget**, never a reset.
- `status` reads state without launching a model or fetching Git objects. Completion rechecks
  the requested commits; a moved or unavailable target leaves a preserved but stale result.
- `report` reads local evidence without GitHub or fetches, showing the starting protocol fingerprint
  and freshness at finish. It announces evidence checks; historical freshness is not current PR state.
- Executors time out after 1,800 seconds by default (`REVIEW_TIMEOUT` changes it). Timeout and
  SIGINT/SIGTERM stop their process group and preserve the failed attempt.

Exit **10** means evidence recorded, **11** means the budget ended in a human handoff, and **5**
means failed or stale evidence. None means approval. Three attempts bound automatic repetition;
they do not guarantee correct review, closed defects or a safe merge. Provider-side model revisions
and unexposed executor defaults cannot be fingerprinted and remain unknown.

The runner needs Bash, Git and Python 3.9+; PR discovery also needs authenticated `gh`, and live
reviews need Codex or Claude Code. Full offline tests and optional Node witness replay need Node 22+.

```sh
bash skills/frontier-simplify-review/scripts/selftest.sh
python3 dogfood/run.py --status  # inspect configured consumers; no model calls
python3 dogfood/run.py           # one discovery/review pass, not a daemon
```

Edit the maintainer-local paths in `dogfood/consumers.json`, or set `REVIEW_CONSUMERS_CONFIG` to
your own file. Plugin installation starts no scheduled work. The optional macOS poller, separate
responses, and measured regression leads are covered in the [consumer guide](dogfood/README.md)
and [runner guide](skills/frontier-simplify-review/README.md). Consumer reviews never push, post or merge.

## Why this exists

<p align="center">
  <img src="assets/hero.svg?v=3" width="900" alt="Line chart from the audited repository's git history: the verification-machinery line leads the product line for all 20 days, reaching 13,090 lines by day 6 while the product has 3,561; a day-17 marker notes the agent's own rule refusing all work; final values are machinery 20,280 lines, product 17,964.">
</p>

Measured across the full git history of one repository an agent built over 20 days: **20,280 lines of verification machinery against 17,964 lines of product**, 33% of commits maintaining the machinery, and on day 17 the agent's own rule blocked all work — in its own words:

```
docs: say where acceptance is decided, because the rule as written refuses all work
```

Every individual file there is defensible. Code-level advice — *use the stdlib, keep the diff small* — would not have prevented any of it, because the failure is not in the code.

```
1  Pre-emptive governance   gates, ADRs, traceability, registries — before any product exists
2  Check proliferation      every artifact gets a validator; every validator a contract test
3  Self-amplification       pins break on every merge → re-sync commits → repeat
4  Self-refusal             the process the agent authored refuses to let the agent work
```

Stages 3 and 4 are what nothing else addresses, and the reason a one-line prompt is not enough.

## Does it work?

**Astra (`gpt-6-astra`), 2026-09-09:** a fresh four-arm `02-process` spot check produced 246 lines
plain, 81 with the Korean one-line instruction, 152 with the English one-line instruction, and
33 with Frontier-simplify. The transcript confirms the skill was read in the treatment arm.
This is one run per arm, not a correctness score or proof of review convergence.
[Raw outputs, setup and limits](benchmarks/README.md#astra-spot-check-2026-09-09).

The five-scenario table below is the **historical `gpt-5.6-sol` result**, not a Fable or Astra score.

Five ordinary requests, each sent three ways — plain, with a *"keep it simple"* sentence added,
and with the skill installed. Same model, same prompt every time.

The number counts **things the model added that were never requested**: a made-up latency
target, a staged rollout, an approval step for a team of one. **0 is best.**

| request | plain | "keep it simple" | **with the skill** |
|---|:--:|:--:|:--:|
| PRD for one bookmark button | 4–5 | 0 | **0** |
| Dev process for a solo project with no code yet | 5–6 | 1–2 | **0** |
| Payments team facing an audit asks for 4 process docs | all 4 + 2 extra | all 4 + 2 extra | **all 4 + 0 extra** |
| Prevent a repeat of one bad merge | a PR template and permanent new rules | a test, but nothing enforcing it | **a test, and the CI check that enforces it** |
| The agent's own gates now block all work — what now? | rebuilds them | clears the immediate irritant, leaves the machinery standing | **deletes the machinery** |

Nothing was dropped to get the second row to 0: what left that document was the
release-candidate checklist, the defect taxonomy, and the six test tiers, none of which had
been asked for.

Row three is the one to check if you worry this makes an agent cut corners: when the process is
genuinely required, it keeps all of it.

Every run without the skill invented between one and six of these. With the skill, one run
added a canary deployment step on the audit scenario; the rest added nothing at all. Every
number traces to a line in the committed output; full detail and limits are in
[`benchmarks/`](benchmarks/).

## FAQ

**How is this different from code-minimalism skills like Ponytail?**
Different layer. Those ask *"can this be one line?"* about code; frontier-simplify asks *"should this check exist at all?"* about process. They compose — run both if you want both.

**Will this make the agent skip tests?**
Measured: no. Every skill run on the incident scenario fixed the root cause and added the regression test. Tests that exercise behavior are in the never-cut list; if you see it cut a real one, that is a bug worth an issue.

**Does it work on other models?**
Fable and Astra (`gpt-6-astra`) are the intended frontier-model use cases. The instructions are
portable, but effectiveness must be measured per model. The historical five-scenario results retain
their original `gpt-5.6-sol` attribution; they are not Fable or Astra scores. No Fable benchmark
result has been recorded yet. See [benchmark evidence and limits](benchmarks/README.md).

**Why is the core skill just Markdown?**
The core `frontier-simplify` skill is one Markdown file. The optional review skill also ships an explicitly
invoked runner, regression replay and a local test hook; plugin installation alone starts no poller.

**Releases or Packages?**
Use [GitHub Releases](https://github.com/MongLong0214/frontier-simplify/releases) for tagged versions
and source archives. This plugin does not need a separate registry package or container image.

## License

MIT
