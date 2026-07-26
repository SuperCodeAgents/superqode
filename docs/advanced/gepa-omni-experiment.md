# GEPA Omni Integration Experiment

This page records the controlled release experiment for SuperQode's GEPA Omni
integration. It is reproducible evidence for the integration and a source for
future release notes and blog posts. It is not a statistical model benchmark.

## Outcome

The full Omni pipeline completed successfully on July 26, 2026:

- all three exploration engines ran with six real evaluations each
- GEPA continuation ran with six more evaluations
- MetaHarness found the winning exploration candidate
- the continuation retained a perfect optimizer-visible score
- the sealed held-out score improved from `0.0` to `1.0`
- both held-out cases passed
- candidate policy audit reported no violations or warnings
- the live HarnessSpec was not modified
- Claude usage was authenticated through a Pro subscription, not an API key

## Experiment design

The experiment optimized `examples/harnesses/omni-tiny-local.yaml` against
`examples/evals/omni-release.yaml`.

The candidate was a complete HarnessSpec. Its optimization policy allowed
changes to `agents`, `model_policy`, and `workflow`, while protecting execution
policy, checks, approvals, and sandbox configuration.

The evaluation contract contained:

- three optimizer-visible release-decision cases
- two distinct sealed held-out cases
- both positive and negative release decisions
- exact output-format requirements
- unresolved-check, security-review, migration, and rollback conditions

## Models and authentication

| Role | Model or engine | Authentication |
| --- | --- | --- |
| Harness rollouts | Ollama `qwen3.5:9b` | Local |
| GEPA reflection | `ollama/qwen3.5:9b` | Local |
| AutoResearch proposer | Claude Haiku | Claude subscription OAuth |
| MetaHarness proposer | Claude Haiku | Claude subscription OAuth |
| Continuation | GEPA with local reflection | Local |

Before the run, `claude auth status` reported `authMethod: claude.ai` and a Pro
subscription. `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` were absent, and
the runner also removed both variables from the child environment.

## Reproducibility

| Component | Version |
| --- | --- |
| GEPA | `0.1.4` at commit `f919db0a622e2e9f9204779b81fe00cc1b2d808f` |
| Claude Code | `2.1.220` |
| Ollama | `0.30.3` |
| Local model | `qwen3.5:9b`, Q4_K_M |
| SuperQode base commit | `8bcd8704758ac72c0e584e2859751c94be6b0f5a` |

The experiment ran against the Omni integration working tree based on the
listed SuperQode commit. The release should record the final integration commit
after these changes are committed.

Run the same bounded experiment:

```bash
scripts/run_tiny_omni_experiment.sh \
  --spec examples/harnesses/omni-tiny-local.yaml \
  --mode omni
```

The runner pins GEPA, selects the release task file, uses subscription
authentication, and applies these bounds:

```text
Total optimizer evaluations: 24
Per exploration engine:       6
Continuation:                 6
Total proposer ceiling:       $2.00 API-price-equivalent
Candidate workers per engine: 1
```

## Explorer results

| Phase | Best score | Evaluations | Proposer cost equivalent |
| --- | ---: | ---: | ---: |
| GEPA exploration | 0.0 | 6 | $0.000000 |
| AutoResearch exploration | 0.0 | 6 | $0.180230 |
| MetaHarness exploration | 1.0 | 6 | $0.268777 |
| GEPA continuation | 1.0 | 6 | $0.000000 |
| **Total** | **1.0** | **24** | **$0.449007** |

The proposer cost is the API-price-equivalent accounting returned by Claude
Code and GEPA. It represents subscription allowance consumption for this run,
not API-key billing.

The 24 optimizer evaluations used 10,820 local-model tokens. The final
baseline-versus-candidate held-out comparison used another 2,013 local tokens,
for 12,833 recorded local tokens in total. Wall-clock time was approximately
11 minutes 22 seconds.

## Candidate and held-out result

The baseline prompt asked for a concise release decision but did not define a
stable output contract or an explicit blocker policy. The winning candidate
changed one field: the `release-decider` agent's system prompt.

The candidate added:

```text
DECISION: yes
REASON: [brief explanation]

OR

DECISION: no
REASON: [brief explanation]
```

It also made the decision policy explicit: answer yes only when all
requirements are met and no blocker remains; answer no when required checks
fail or concerns are unresolved.

| Held-out variant | Score | Passed | Failed | Local tokens |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 0.0 | 0 | 2 | 923 |
| Candidate | 1.0 | 2 | 0 | 1,090 |

The candidate generalized to both sealed cases: a ready dependency update with
a tested rollback plan, and a database change blocked by missing migration and
rollback plans.

## Safety result

The final candidate audit recorded:

```text
Changed fields:    1
Changed surfaces:  agents
Policy violations: 0
Warnings:          0
Regressions:       0
Held-out gate:     passed
```

The optimizer did not modify execution permissions, checks, approval policy,
sandbox configuration, model routing, or workflow. SuperQode staged the
candidate separately and left the source HarnessSpec unchanged.

## What this proves

This controlled experiment demonstrates that:

- subscription-authenticated Claude Code can drive GEPA's agent engines without
  an Anthropic API key
- Ollama can provide both harness rollouts and GEPA reflection
- Omni can compare three optimization strategies and continue from the winner
- SuperQode can audit complete HarnessSpec candidates before evaluation
- a separate held-out gate can reject regressions before human adoption
- proposer and evaluation budgets remain bounded and observable

## Limitations

- This was one controlled run over five small binary-scored tasks.
- The intentionally under-specified baseline made improvement straightforward.
- The result demonstrates integration behavior, not general superiority over
  manual prompt engineering or another optimizer.
- Dollar values are API-price-equivalent usage, not an Anthropic API invoice.
- GEPA's budget-exhaustion stop currently emits verbose tracebacks even when a
  phase ends normally at its configured limit.
- LiteLLM emitted optional Bedrock/SageMaker import and asynchronous logging
  cleanup warnings; neither affected the local Ollama path or final result.

Use representative project tasks, multiple seeds, and repeated held-out runs
before making production-quality or comparative performance claims.
