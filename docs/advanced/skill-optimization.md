# Skill Optimization

SuperQode can optimize markdown skills with GEPA's reflective optimizer,
AutoResearch, GEPA meta-harness, or the Omni recipe, and stage the result for
review. Use this when a skill is useful but still misses recurring cases in
your eval tasks.

For the broader optimization model across harnesses, skills, local routing, and
custom optimizers, see [Optimization Story](optimization.md).

## Install

GEPA is optional:

```bash
uv tool install "superqode[optimization]"
```

The base SuperQode install does not include optimization dependencies. The
stable `gepa` engine works with the packaged dependency. The agent engines and
Omni require a GEPA build containing `OptimizeAnythingConfig` and
`optimize_best_of`; until that API is in a tagged release, install GEPA from
its current `main` branch in the same environment:

```bash
uv tool install "superqode[optimization]" \
  --with "gepa @ git+https://github.com/gepa-ai/gepa.git"
```

AutoResearch and `gepa-meta-harness` invoke Claude Code and therefore require
the `claude` CLI. Their subprocesses are OS-sandboxed by default.

## Run

```bash
superqode skills optimize review \
  --engine omni \
  --harness harness.yaml \
  --tasks eval-tasks.yaml \
  --live \
  --max-metric-calls 20
```

From the TUI, use the same arguments after `:skills optimize`:

```text
:skills optimize review --engine omni --harness harness.yaml --tasks eval-tasks.yaml --live --max-metric-calls 20
```

`--live` is required because optimization needs real eval scores. The command
does not overwrite the live skill. Mark optimizer examples `split: held-in`
and reserve at least one `split: held-out` task for the sealed final gate. It
writes staged artifacts under:

```text
.superqode/skill-optimizations/<skill>-<timestamp>/
  baseline/SKILL.md
  staged/best_skill.md
  report.json
  report.md
  gepa-run/
  evals/
```

The report records the held-out baseline, candidate score, and regressions.
Review `staged/best_skill.md` before copying it over the live
`.agents/skills/.../SKILL.md`.

## Engines

| Engine | Behavior | Extra requirement |
|---|---|---|
| `gepa` | Reflective Pareto search; accepts the existing advanced GEPA controls | Reflection model |
| `autoresearch` | Claude Code agent repeatedly edits and evaluates the artifact | Claude CLI |
| `gepa-meta-harness` | Claude Code maintains a candidate frontier across iterations | Claude CLI |
| `omni` | Runs all three explorers in parallel, then continues from the winner | Claude CLI for two explorers |

Omni is a composition recipe, not a fourth upstream engine. With a budget of
20 evaluations, the default allocation is five evaluations for each explorer
and five for the continuation engine. Set `--explore-max-evals` to override
the per-explorer share and `--continuation-engine` to select the final phase.

## Review

The optimizer output is a proposal. Review the staged skill and compare it
against the baseline:

```bash
diff -u \
  .superqode/skill-optimizations/<run>/baseline/SKILL.md \
  .superqode/skill-optimizations/<run>/staged/best_skill.md
```

Run the bounded-edit check before adoption:

```bash
superqode skillopt check \
  --baseline .superqode/skill-optimizations/<run>/baseline/SKILL.md \
  --candidate .superqode/skill-optimizations/<run>/staged/best_skill.md
```

Then run a held-out eval pack or a task file that was not used for the
optimization run.

## Tuning

Most GEPA runs only need `--max-metric-calls`, `--reflection-lm`, and
`--max-edits`. Omni runs should also set `--max-token-cost`.
Use the advanced controls when you want to tune search cost or exploration:

| Option | Use |
|---|---|
| `--max-metric-calls` | Total evaluation budget |
| `--max-candidate-proposals` | Candidate proposal budget |
| `--max-reflection-cost` | Reflection LM cost cap |
| `--max-token-cost` | Total proposer cost cap; split across Omni's four stages |
| `--explore-max-evals` | Per-explorer Omni evaluation budget |
| `--continuation-engine` | Engine for the fresh continuation run |
| `--optimizer-model` | Claude model for agent engines |
| `--optimizer-effort` | Claude CLI effort for agent engines |
| `--agent-sandbox` | Keep Claude subprocesses inside GEPA's OS sandbox |
| `--minibatch-size` | Reflection minibatch size |
| `--max-workers` | Parallel candidate evaluation workers |
| `--candidate-selection` | `pareto`, `current_best`, `epsilon_greedy`, or `top_k_pareto` |
| `--frontier-type` | `instance`, `objective`, `hybrid`, or `cartesian` |
| `--acceptance` | `strict_improvement` or `improvement_or_equal` |
| `--cache-evaluation` | GEPA candidate/example evaluation cache |
| `--use-merge` | GEPA merge proposals across frontier candidates |
| `--max-merge-invocations` | Merge proposal limit |
| `--reflection-lm` | Model used by GEPA for reflection |

Start with a small budget first. Increase `--max-metric-calls` only after the
eval task file is stable and has a clear pass/fail signal.
