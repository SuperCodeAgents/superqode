# Skills Commands

`superqode skills` manages and optimizes project skills. A skill is a markdown
artifact that teaches the harness a repeatable workflow, review style, tool
sequence, or project convention.

```bash
superqode skills COMMAND [ARGS]...
```

## optimize

Optimize a markdown skill with GEPA. The live skill is never overwritten;
SuperQode writes staged artifacts and a review report.

```bash
superqode skills optimize review \
  --engine omni \
  --harness harness.yaml \
  --tasks eval-tasks.yaml \
  --live
```

`--engine gepa` keeps the stable reflective optimizer. The engine-pluggable
API also supports `autoresearch`, `gepa-meta-harness`, and `omni`. Omni runs
GEPA, AutoResearch, and GEPA's meta-harness engine in parallel, selects the
best result, and gives that candidate a fresh continuation run.

Important options:

| Option | Purpose |
| --- | --- |
| `--engine TEXT` | `gepa`, `autoresearch`, `gepa-meta-harness`, or `omni` |
| `--continuation-engine TEXT` | Fresh engine used after Omni exploration |
| `--harness PATH` | Harness used to evaluate candidates |
| `--tasks PATH` | Eval task file |
| `--output PATH` | Directory for staged artifacts |
| `--provider TEXT` | Provider for eval runs |
| `--model TEXT` | Model for eval runs |
| `--runtime TEXT` | Runtime or backend override |
| `--sandbox TEXT` | Sandbox profile, default `local` |
| `--reflection-lm TEXT` | Model used by GEPA for reflection |
| `--max-metric-calls INTEGER` | Evaluation budget |
| `--explore-max-evals INTEGER` | Per-engine exploration budget for Omni |
| `--max-token-cost FLOAT` | Optimizer-model USD cap, partitioned across Omni stages |
| `--optimizer-model TEXT` | Claude model for AutoResearch and meta-harness |
| `--agent-sandbox / --no-agent-sandbox` | Sandbox agent-engine subprocesses |
| `--max-edits INTEGER` | Bounded edit limit |
| `--live` | Execute eval tasks against the configured model |
| `--json` | Emit JSON |

Tasks marked `split: held-out` are sealed from optimization and used for the
final non-regression gate.

For workflow guidance, see [Skill Optimization](../advanced/skill-optimization.md).
