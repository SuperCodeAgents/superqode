"""SkillOpt-style optimization workspaces for SuperQode skills."""

from __future__ import annotations

import asyncio
import difflib
import json
import shlex
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from superqode.harness.eval import load_eval_tasks
from superqode.harness.loader import harness_spec_to_dict, load_harness_spec
from superqode.skills import Skill, SkillsLoader

SKILL_OPTIMIZER_ENGINES = ("gepa", "autoresearch", "gepa-meta-harness", "omni")
OMNI_EXPLORATION_ENGINES = ("gepa", "autoresearch", "meta_harness")


@dataclass(frozen=True)
class SkillOptExport:
    """Files created for a SkillOpt-style skill optimization workspace."""

    project_dir: Path
    baseline_dir: Path
    skill_path: Path
    baseline_skill_path: Path
    tasks_path: Path
    instructions_path: Path
    harness_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_dir": str(self.project_dir),
            "baseline_dir": str(self.baseline_dir),
            "skill_path": str(self.skill_path),
            "baseline_skill_path": str(self.baseline_skill_path),
            "tasks_path": str(self.tasks_path),
            "instructions_path": str(self.instructions_path),
            "harness_path": str(self.harness_path) if self.harness_path else None,
        }


@dataclass(frozen=True)
class SkillOptimizationResult:
    """Result of a staged skill optimization run."""

    engine: str
    skill_name: str
    output_dir: Path
    baseline_skill_path: Path
    staged_skill_path: Path
    report_json_path: Path
    report_md_path: Path
    baseline_score: float | None
    best_score: float | None
    total_metric_calls: int | None
    check: dict[str, Any]
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "skill_name": self.skill_name,
            "output_dir": str(self.output_dir),
            "baseline_skill_path": str(self.baseline_skill_path),
            "staged_skill_path": str(self.staged_skill_path),
            "report_json_path": str(self.report_json_path),
            "report_md_path": str(self.report_md_path),
            "baseline_score": self.baseline_score,
            "best_score": self.best_score,
            "total_metric_calls": self.total_metric_calls,
            "check": self.check,
            "metadata": self.metadata or {},
        }


def export_skillopt_project(
    *,
    skill: str,
    tasks_path: str | Path,
    project_dir: str | Path,
    root: str | Path = ".",
    harness_path: str | Path | None = None,
    max_edits: int = 4,
    live_eval: bool = False,
    force: bool = False,
) -> SkillOptExport:
    """Create a SkillOpt-style optimization workspace for one markdown skill."""

    root_path = Path(root).expanduser().resolve()
    source_skill = _resolve_skill(skill, root_path)
    source_tasks = Path(tasks_path).expanduser().resolve()
    load_eval_tasks(source_tasks)

    project = Path(project_dir).expanduser().resolve()
    if project.exists() and any(project.iterdir()) and not force:
        raise FileExistsError(f"{project} already exists and is not empty; pass --force")

    if project.exists() and force:
        shutil.rmtree(project)

    baseline = project / "baseline"
    skill_rel = _skill_relative_path(source_skill, root_path)
    skill_target = baseline / skill_rel
    skill_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_skill.path or source_skill.source_path, skill_target)

    tasks_target = baseline / "eval-tasks.yaml"
    shutil.copyfile(source_tasks, tasks_target)

    harness_target: Path | None = None
    if harness_path:
        source_harness = Path(harness_path).expanduser().resolve()
        harness_target = baseline / "harness.yaml"
        shutil.copyfile(source_harness, harness_target)

    snapshot = baseline / ".skillopt" / "baseline_skill.md"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(skill_target, snapshot)

    instructions = baseline / "AGENTS.md"
    instructions.write_text(
        _optimizer_instructions(
            skill_name=source_skill.name,
            skill_rel=skill_rel,
            max_edits=max_edits,
            has_harness=bool(harness_target),
        ),
        encoding="utf-8",
    )
    (baseline / "README.md").write_text(
        _readme(skill_name=source_skill.name, skill_rel=skill_rel, max_edits=max_edits),
        encoding="utf-8",
    )

    (project / "tasks.json").write_text(
        json.dumps(
            _optimization_tasks(
                skill_rel=skill_rel,
                max_edits=max_edits,
                has_harness=bool(harness_target),
                live_eval=live_eval,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (project / "skillopt.json").write_text(
        json.dumps(
            {
                "objective": (
                    f"Improve the SuperQode skill `{source_skill.name}` using "
                    "bounded text edits and accept only changes that preserve or "
                    "improve held-out eval performance."
                ),
                "baseline_dir": "baseline",
                "tasks_file": "tasks.json",
                "skill_path": str(skill_rel),
                "max_edits": int(max_edits),
                "gate": (
                    "Run live harness eval on eval-tasks.yaml before adopting the edited skill."
                    if live_eval
                    else "Dry eval checks the contract; run live harness eval before adoption."
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return SkillOptExport(
        project_dir=project,
        baseline_dir=baseline,
        skill_path=skill_target,
        baseline_skill_path=snapshot,
        tasks_path=project / "tasks.json",
        instructions_path=instructions,
        harness_path=harness_target,
    )


def optimize_skill_with_gepa(
    *,
    skill: str,
    harness_path: str | Path,
    tasks_path: str | Path,
    output_dir: str | Path,
    root: str | Path = ".",
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    runtime: str | None = None,
    working_dir: str | Path = ".",
    sandbox_backend: str = "local",
    reflection_lm: str = "openai/gpt-5.1",
    max_metric_calls: int = 20,
    max_candidate_proposals: int | None = None,
    max_reflection_cost: float | None = None,
    reflection_minibatch_size: int | None = None,
    max_workers: int = 1,
    seed: int = 0,
    max_edits: int = 8,
    candidate_selection_strategy: str = "pareto",
    frontier_type: str = "hybrid",
    acceptance_criterion: str = "strict_improvement",
    cache_evaluation: bool = False,
    use_merge: bool = False,
    max_merge_invocations: int = 5,
    engine: str = "gepa",
    continuation_engine: str = "gepa",
    optimizer_model: str = "claude-sonnet-4-6",
    optimizer_effort: str | None = None,
    max_token_cost: float | None = None,
    explore_max_evals: int | None = None,
    agent_sandbox: bool = True,
    live: bool = False,
    force: bool = False,
    optimizer: Callable[..., Any] | None = None,
    allow_dry_run: bool = False,
) -> SkillOptimizationResult:
    """Optimize one SuperQode skill and stage the best candidate.

    ``gepa`` keeps the stable legacy integration. The agent engines and
    ``omni`` require GEPA's engine-pluggable optimize_anything API.
    """

    if not live and not allow_dry_run:
        raise ValueError("GEPA skill optimization requires --live so eval tasks produce scores.")
    if engine not in SKILL_OPTIMIZER_ENGINES:
        raise ValueError(f"Unsupported skill optimizer engine: {engine}")
    if continuation_engine not in {"gepa", "autoresearch", "gepa-meta-harness"}:
        raise ValueError(f"Unsupported Omni continuation engine: {continuation_engine}")

    root_path = Path(root).expanduser().resolve()
    source_skill = _resolve_skill(skill, root_path)
    source_skill_path = source_skill.path or source_skill.source_path
    source_text = source_skill_path.read_text(encoding="utf-8")

    task_file = load_eval_tasks(tasks_path)
    tasks = list(task_file["tasks"])
    if not tasks:
        raise ValueError("GEPA optimization requires at least one eval task")
    train_tasks, val_tasks, test_tasks = _optimization_splits(tasks)

    harness_source = Path(harness_path).expanduser().resolve()
    # Validate early; candidate evals will write temporary derived specs.
    load_harness_spec(harness_source)

    out = Path(output_dir).expanduser().resolve()
    if out.exists() and any(out.iterdir()) and not force:
        raise FileExistsError(f"{out} already exists and is not empty; pass --force")
    if out.exists() and force:
        shutil.rmtree(out)
    baseline_dir = out / "baseline"
    staged_dir = out / "staged"
    eval_dir = out / "evals"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    staged_dir.mkdir(parents=True, exist_ok=True)
    eval_dir.mkdir(parents=True, exist_ok=True)

    baseline_skill_path = baseline_dir / "SKILL.md"
    baseline_skill_path.write_text(source_text, encoding="utf-8")

    evaluator = _GEPASkillEvaluator(
        source_harness_path=harness_source,
        tasks=tasks,
        eval_dir=eval_dir,
        provider=provider,
        model=model,
        runtime=runtime,
        working_dir=Path(working_dir).expanduser().resolve(),
        sandbox_backend=sandbox_backend,
        live=live,
        skill_name=source_skill.name,
        baseline_text=source_text,
        max_edits=max_edits,
    )

    if optimizer is None and engine == "gepa":
        try:
            from gepa.optimize_anything import (  # type: ignore[import-not-found]
                EngineConfig,
                GEPAConfig,
                MergeConfig,
                ReflectionConfig,
                optimize_anything,
            )
        except ImportError as exc:
            raise RuntimeError(
                "GEPA is not installed. Install it with `uv tool install 'superqode[optimization]'` "
                "or `pip install gepa`."
            ) from exc

        config = GEPAConfig(
            engine=EngineConfig(
                run_dir=str(out / "gepa-run"),
                max_metric_calls=int(max_metric_calls),
                max_candidate_proposals=max_candidate_proposals,
                max_reflection_cost=max_reflection_cost,
                max_workers=max(1, int(max_workers)),
                parallel=max_workers > 1,
                seed=int(seed),
                display_progress_bar=False,
                candidate_selection_strategy=candidate_selection_strategy,
                frontier_type=frontier_type,
                acceptance_criterion=acceptance_criterion,
                cache_evaluation=cache_evaluation,
            ),
            reflection=ReflectionConfig(
                reflection_lm=reflection_lm,
                reflection_minibatch_size=reflection_minibatch_size,
                module_selector="all",
            ),
            merge=MergeConfig(max_merge_invocations=max_merge_invocations) if use_merge else None,
            refiner=None,
        )
        optimizer = optimize_anything
    elif optimizer is not None:
        config = None
    else:
        config = None

    objective = (
        f"Optimize the SuperQode skill `{source_skill.name}` so it improves harness "
        "evaluation quality without changing the skill identity or adding unsafe behavior."
    )
    background = (
        "The candidate is a complete markdown SKILL.md file. Preserve YAML frontmatter, "
        "keep instructions concise, and prefer concrete reusable developer workflow rules. "
        "The evaluator stages each candidate into a temporary SuperQode harness and returns "
        "task-level pass/fail feedback plus failure reasons as Actionable Side Information."
    )

    kwargs: dict[str, Any] = {
        "seed_candidate": {"skill": source_text} if engine == "gepa" else source_text,
        "evaluator": evaluator.evaluate,
        "dataset": train_tasks,
        "valset": val_tasks,
        "objective": objective,
        "background": background,
    }
    if test_tasks and engine != "gepa":
        kwargs["test_set"] = test_tasks
    if config is not None:
        kwargs["config"] = config
    if optimizer is not None:
        result = optimizer(**kwargs)
    else:
        result = _run_modern_optimizer(
            engine=engine,
            continuation_engine=continuation_engine,
            seed_candidate=source_text,
            evaluator=evaluator.evaluate,
            dataset=train_tasks,
            valset=val_tasks,
            test_set=test_tasks,
            objective=objective,
            background=background,
            output_dir=out,
            max_evals=int(max_metric_calls),
            explore_max_evals=explore_max_evals,
            max_token_cost=max_token_cost if max_token_cost is not None else max_reflection_cost,
            reflection_lm=reflection_lm,
            optimizer_model=optimizer_model,
            optimizer_effort=optimizer_effort,
            agent_sandbox=agent_sandbox,
            max_workers=max_workers,
            seed=seed,
            max_candidate_proposals=max_candidate_proposals,
            candidate_selection_strategy=candidate_selection_strategy,
            frontier_type=frontier_type,
            acceptance_criterion=acceptance_criterion,
            cache_evaluation=cache_evaluation,
            use_merge=use_merge,
            max_merge_invocations=max_merge_invocations,
            reflection_minibatch_size=reflection_minibatch_size,
        )

    best_candidate = _best_skill_text(result)
    staged_skill_path = staged_dir / "best_skill.md"
    staged_skill_path.write_text(best_candidate, encoding="utf-8")
    check = check_skill_candidate(
        baseline_path=baseline_skill_path,
        candidate_path=staged_skill_path,
        max_edits=max_edits,
    )

    baseline_score, best_score = _optimization_scores(result)
    result_metadata = _result_metadata(result)
    if live and test_tasks:
        heldout_gate = _run_skill_heldout_gate(
            evaluator=evaluator,
            baseline_text=source_text,
            candidate_text=best_candidate,
            tasks=test_tasks,
        )
        result_metadata["heldout_gate"] = heldout_gate
        baseline_score = heldout_gate["baseline_score"]
        best_score = heldout_gate["candidate_score"]
        if not heldout_gate["accepted"]:
            errors = list(check.get("errors") or [])
            errors.append("candidate failed the sealed held-out non-regression gate")
            check = {**check, "ok": False, "errors": errors}
    total_metric_calls = getattr(result, "total_metric_calls", None)
    if total_metric_calls is None:
        total_metric_calls = result_metadata.get(
            "omni_total_evals",
            getattr(result, "total_evals", None),
        )
    report_json_path = out / "report.json"
    report_md_path = out / "report.md"
    opt_result = SkillOptimizationResult(
        engine=engine,
        skill_name=source_skill.name,
        output_dir=out,
        baseline_skill_path=baseline_skill_path,
        staged_skill_path=staged_skill_path,
        report_json_path=report_json_path,
        report_md_path=report_md_path,
        baseline_score=baseline_score,
        best_score=best_score,
        total_metric_calls=int(total_metric_calls) if total_metric_calls is not None else None,
        check=check,
        metadata=result_metadata,
    )
    report_json_path.write_text(json.dumps(opt_result.to_dict(), indent=2) + "\n", encoding="utf-8")
    report_md_path.write_text(render_skill_optimization_report(opt_result) + "\n", encoding="utf-8")
    return opt_result


class _GEPASkillEvaluator:
    def __init__(
        self,
        *,
        source_harness_path: Path,
        tasks: list[dict[str, Any]],
        eval_dir: Path,
        provider: str,
        model: str,
        runtime: str | None,
        working_dir: Path,
        sandbox_backend: str,
        live: bool,
        skill_name: str,
        baseline_text: str,
        max_edits: int,
    ) -> None:
        self.source_harness_path = source_harness_path
        self.tasks = tasks
        self.eval_dir = eval_dir
        self.provider = provider
        self.model = model
        self.runtime = runtime
        self.working_dir = working_dir
        self.sandbox_backend = sandbox_backend
        self.live = live
        self.skill_name = skill_name
        self.baseline_text = baseline_text
        self.max_edits = max_edits
        self._lock = threading.Lock()
        self._counter = 0
        self._baseline_scores: dict[str, float] = {}

    def evaluate(
        self, candidate: str | dict[str, str], example: dict[str, Any]
    ) -> tuple[float, dict[str, Any]]:
        skill_text = (
            str(candidate.get("skill", "")) if isinstance(candidate, dict) else str(candidate)
        )
        with self._lock:
            self._counter += 1
            eval_id = self._counter
        task = self._task_by_id(str(example.get("id") or ""))
        run_dir = self.eval_dir / f"eval-{eval_id:04d}-{_safe_name(str(task.get('id') or 'task'))}"
        run_dir.mkdir(parents=True, exist_ok=True)
        candidate_check = _check_skill_text(
            baseline_text=self.baseline_text,
            candidate_text=skill_text,
            max_edits=self.max_edits,
        )
        if not candidate_check["ok"]:
            return 0.0, {
                "Input": {"Task": task},
                "Feedback": {
                    "Status": "invalid_candidate",
                    "Errors": candidate_check["errors"],
                    "Candidate check": candidate_check,
                },
                "scores": {
                    "harness_score": 0.0,
                    "valid_candidate": 0.0,
                    "non_regression": 0.0,
                },
            }
        spec_path = run_dir / "harness.yaml"
        task_path = run_dir / "eval-tasks.yaml"
        _write_candidate_harness(
            source_harness_path=self.source_harness_path,
            output_path=spec_path,
            skill_name=self.skill_name,
            skill_text=skill_text,
        )
        task_path.write_text(
            yaml.safe_dump(
                {"tasks": [task], "metadata": {"source": "gepa-skill-optimization"}},
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        try:
            from superqode.harness.eval import run_harness_eval

            payload = asyncio.run(
                run_harness_eval(
                    spec_paths=[spec_path],
                    tasks_path=task_path,
                    provider=self.provider,
                    model=self.model,
                    runtime=self.runtime,
                    working_dir=self.working_dir,
                    sandbox_backend=self.sandbox_backend,
                    live=self.live,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return 0.0, {
                "Input": {"Task": task},
                "Feedback": {"Status": "exception", "Error": str(exc)},
                "scores": {"harness_score": 0.0},
            }

        variant = payload.get("variants", [{}])[0]
        task_result = (variant.get("tasks") or [{}])[0]
        score = float(task_result.get("score") or 0.0)
        task_id = str(task.get("id") or "")
        if skill_text == self.baseline_text:
            with self._lock:
                self._baseline_scores[task_id] = score
        baseline_score = self._baseline_scores.get(task_id)
        non_regression = 0.0 if baseline_score == 1.0 and score < baseline_score else 1.0
        usage = task_result.get("usage") or {}
        cost = usage.get("cost_usd")
        duration = float(task_result.get("duration_seconds") or 0.0)
        cost_efficiency = 1.0 / (1.0 + max(0.0, float(cost or 0.0)))
        latency_efficiency = 1.0 / (1.0 + max(0.0, duration))
        return score, {
            "Input": {
                "Task ID": task.get("id"),
                "Prompt": str(task.get("prompt") or "")[:1000],
                "Expect Contains": task.get("expect_contains"),
            },
            "Generated Outputs": {
                "Status": task_result.get("status"),
                "Reason": task_result.get("reason"),
                "Content chars": task_result.get("content_chars"),
            },
            "Feedback": {
                "Harness status": payload.get("status"),
                "Task status": task_result.get("status"),
                "Failure digest": task_result.get("failure_digest") or {},
                "Score": score,
                "Baseline score": baseline_score,
                "Non-regression": bool(non_regression),
                "Candidate check": candidate_check,
                "Usage": usage,
                "Duration seconds": duration,
            },
            "scores": {
                "harness_score": score,
                "valid_candidate": 1.0,
                "non_regression": non_regression,
                "cost_efficiency": cost_efficiency,
                "latency_efficiency": latency_efficiency,
            },
        }

    def _task_by_id(self, task_id: str) -> dict[str, Any]:
        for task in self.tasks:
            if str(task.get("id") or "") == task_id:
                return task
        return dict(self.tasks[0])


def check_skill_candidate(
    *,
    baseline_path: str | Path,
    candidate_path: str | Path,
    max_edits: int = 4,
    max_bytes: int = 50_000,
) -> dict[str, Any]:
    """Validate a candidate skill for bounded SkillOpt-style edits."""

    baseline = Path(baseline_path).expanduser()
    candidate = Path(candidate_path).expanduser()
    errors: list[str] = []
    if not baseline.is_file():
        errors.append(f"baseline skill not found: {baseline}")
    if not candidate.is_file():
        errors.append(f"candidate skill not found: {candidate}")
    if errors:
        return {"ok": False, "errors": errors}

    return _check_skill_text(
        baseline_text=baseline.read_text(encoding="utf-8"),
        candidate_text=candidate.read_text(encoding="utf-8"),
        max_edits=max_edits,
        max_bytes=max_bytes,
    )


def _check_skill_text(
    *,
    baseline_text: str,
    candidate_text: str,
    max_edits: int,
    max_bytes: int = 50_000,
) -> dict[str, Any]:
    errors: list[str] = []
    if not candidate_text.strip():
        errors.append("candidate skill is empty")
    if len(candidate_text.encode("utf-8")) > max_bytes:
        errors.append(f"candidate skill exceeds {max_bytes} bytes")

    baseline_meta = _frontmatter(baseline_text)
    candidate_meta = _frontmatter(candidate_text)
    if baseline_meta.get("name") and candidate_meta.get("name") != baseline_meta.get("name"):
        errors.append("candidate changed the skill frontmatter name")

    edit_count = _diff_hunks(baseline_text, candidate_text)
    if edit_count > int(max_edits):
        errors.append(f"candidate uses {edit_count} diff hunks; max_edits is {max_edits}")

    return {
        "ok": not errors,
        "errors": errors,
        "edit_hunks": edit_count,
        "max_edits": int(max_edits),
        "candidate_bytes": len(candidate_text.encode("utf-8")),
        "candidate_name": candidate_meta.get("name") or "",
    }


def render_skillopt_export(payload: SkillOptExport | dict[str, Any]) -> str:
    data = payload.to_dict() if isinstance(payload, SkillOptExport) else payload
    lines = [
        f"SkillOpt workspace: {data['project_dir']}",
        f"Baseline: {data['baseline_dir']}",
        f"Skill: {data['skill_path']}",
        f"Tasks: {data['tasks_path']}",
        f"Instructions: {data['instructions_path']}",
    ]
    if data.get("harness_path"):
        lines.append(f"Harness: {data['harness_path']}")
    lines.append("")
    lines.append("Next: run an optimizer against this workspace, then gate with harness eval.")
    return "\n".join(lines)


def render_skillopt_check(payload: dict[str, Any]) -> str:
    status = "passed" if payload.get("ok") else "failed"
    lines = [
        f"SkillOpt check: {status}",
        f"Edit hunks: {payload.get('edit_hunks', 0)}/{payload.get('max_edits', 0)}",
    ]
    for error in payload.get("errors", []):
        lines.append(f"- {error}")
    return "\n".join(lines)


def render_skill_optimization_result(payload: SkillOptimizationResult | dict[str, Any]) -> str:
    data = payload.to_dict() if isinstance(payload, SkillOptimizationResult) else payload
    lines = [
        f"Skill optimization: {data['engine']}",
        f"Skill: {data['skill_name']}",
        f"Output: {data['output_dir']}",
        f"Staged skill: {data['staged_skill_path']}",
    ]
    if data.get("baseline_score") is not None or data.get("best_score") is not None:
        lines.append(f"Score: {data.get('baseline_score')} -> {data.get('best_score')}")
    if data.get("total_metric_calls") is not None:
        lines.append(f"Metric calls: {data['total_metric_calls']}")
    check = data.get("check") or {}
    lines.append(f"Bounded edit check: {'passed' if check.get('ok') else 'failed'}")
    if check.get("errors"):
        lines.extend(f"- {error}" for error in check["errors"])
    lines.append(f"Report: {data['report_md_path']}")
    return "\n".join(lines)


def render_skill_optimization_report(result: SkillOptimizationResult) -> str:
    data = result.to_dict()
    return "\n".join(
        [
            f"# SuperQode Skill Optimization: {result.skill_name}",
            "",
            f"- Engine: {result.engine}",
            f"- Baseline score: {result.baseline_score}",
            f"- Best score: {result.best_score}",
            f"- Metric calls: {result.total_metric_calls}",
            f"- Baseline skill: `{result.baseline_skill_path}`",
            f"- Staged skill: `{result.staged_skill_path}`",
            f"- Bounded edit check: {'passed' if result.check.get('ok') else 'failed'}",
            "",
            "The staged skill is a proposal. Review it and run held-out evals before copying it over the live skill.",
            "",
            "## Check",
            "",
            "```json",
            json.dumps(data["check"], indent=2),
            "```",
        ]
    )


def _resolve_skill(value: str, root: Path) -> Skill:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_file():
        loader = SkillsLoader(root)
        parsed = loader._parse_skill(candidate)  # noqa: SLF001 - central parser for skill files
        if not parsed:
            raise ValueError(f"Could not parse skill file: {candidate}")
        return _attach_source_path(parsed, candidate)

    loader = SkillsLoader(root)
    skill = loader.get(value)
    if not skill or not skill.path:
        raise ValueError(f"Skill not found by name or path: {value}")
    return _attach_source_path(skill, skill.path)


def _attach_source_path(skill: Skill, path: Path) -> Skill:
    object.__setattr__(skill, "source_path", path)
    return skill


def _skill_relative_path(skill: Skill, root: Path) -> Path:
    path = skill.path or skill.source_path
    try:
        return path.resolve().relative_to(root)
    except ValueError:
        return Path(".agents") / "skills" / _slug(skill.name) / "SKILL.md"


def _slug(value: str) -> str:
    chars = [ch.lower() if ch.isalnum() else "-" for ch in value.strip()]
    return "-".join(part for part in "".join(chars).split("-") if part) or "skill"


def _frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    try:
        data = yaml.safe_load(text[4:end]) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _diff_hunks(left: str, right: str) -> int:
    left_lines = left.splitlines()
    right_lines = right.splitlines()
    matcher = difflib.SequenceMatcher(a=left_lines, b=right_lines)
    return sum(1 for tag, *_ in matcher.get_opcodes() if tag != "equal")


def _optimization_tasks(
    *,
    skill_rel: Path,
    max_edits: int,
    has_harness: bool,
    live_eval: bool,
) -> list[dict[str, Any]]:
    skill_arg = shlex.quote(str(skill_rel))
    tasks: list[dict[str, Any]] = [
        {
            "id": "skill-file-present",
            "type": "file_phrase",
            "path": str(skill_rel),
            "weight": 1.0,
            "required_phrases": ["---", "#"],
        },
        {
            "id": "bounded-skill-edit",
            "type": "command",
            "weight": 2.0,
            "command": (
                "superqode skillopt check "
                f"--baseline .skillopt/baseline_skill.md --candidate {skill_arg} "
                f"--max-edits {int(max_edits)} --json"
            ),
            "expect_exit_code": 0,
        },
    ]
    if has_harness:
        live_flag = " --live" if live_eval else ""
        tasks.append(
            {
                "id": "held-out-eval-contract",
                "type": "command",
                "weight": 3.0,
                "command": (
                    "superqode harness eval --spec harness.yaml "
                    f"--tasks eval-tasks.yaml --json{live_flag}"
                ),
                "expect_exit_code": 0,
            }
        )
    return tasks


def _optimizer_instructions(
    *,
    skill_name: str,
    skill_rel: Path,
    max_edits: int,
    has_harness: bool,
) -> str:
    eval_line = (
        "- Run `superqode harness eval --spec harness.yaml --tasks eval-tasks.yaml --json` "
        "and keep the candidate only when held-out score improves without regressions."
        if has_harness
        else "- No harness was exported; produce only a staged skill edit and require downstream eval before adoption."
    )
    return f"""# SkillOpt-Style Skill Optimization

You are optimizing the SuperQode skill `{skill_name}`.

Edit only `{skill_rel}`. Treat the markdown skill as trainable text state for a
frozen agent. Use the eval tasks as rollout evidence, propose bounded
add/delete/replace edits, and preserve behavior that already works.

Rules:
- Keep the frontmatter `name` unchanged.
- Use no more than {int(max_edits)} coherent diff hunks.
- Prefer concrete operating rules over broad rewrites.
- Do not edit `.skillopt/baseline_skill.md`.
{eval_line}
- Before finishing, run `superqode skillopt check --baseline .skillopt/baseline_skill.md --candidate {skill_rel} --max-edits {int(max_edits)}`.
"""


def _readme(*, skill_name: str, skill_rel: Path, max_edits: int) -> str:
    return f"""# SuperQode SkillOpt Workspace: {skill_name}

This workspace adapts the SkillOpt loop to a SuperQode markdown skill:

1. Roll out or inspect failures from `eval-tasks.yaml`.
2. Reflect on recurring failures and successes.
3. Edit `{skill_rel}` with a bounded text budget.
4. Gate the candidate with SuperQode evals before adoption.

The bounded edit check is:

```bash
superqode skillopt check --baseline .skillopt/baseline_skill.md --candidate {skill_rel} --max-edits {int(max_edits)}
```
"""


def _best_skill_text(result: Any) -> str:
    best = getattr(result, "best_candidate", result)
    if isinstance(best, dict):
        return str(best.get("skill") or next(iter(best.values()), ""))
    return str(best)


def _gepa_scores(result: Any) -> tuple[float | None, float | None]:
    scores = getattr(result, "val_aggregate_scores", None)
    if not scores:
        return None, None
    baseline = float(scores[0]) if scores else None
    best_idx = int(getattr(result, "best_idx", 0) or 0)
    best = float(scores[best_idx]) if 0 <= best_idx < len(scores) else None
    return baseline, best


def _optimization_scores(result: Any) -> tuple[float | None, float | None]:
    """Normalize legacy GEPA and engine-pluggable Result score fields."""
    legacy = _gepa_scores(result)
    if legacy != (None, None):
        return legacy
    metadata = getattr(result, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    baseline_test = metadata.get(
        "omni_original_baseline_test_score",
        metadata.get("baseline_test_score"),
    )
    optimized_test = metadata.get("test_score")
    if baseline_test is not None and optimized_test is not None:
        return float(baseline_test), float(optimized_test)
    best_score = getattr(result, "best_score", None)
    return None, float(best_score) if best_score is not None else None


def _optimization_splits(
    tasks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Create deterministic optimizer-visible and sealed task splits."""
    held_in = [task for task in tasks if str(task.get("split") or "held-in") != "held-out"]
    held_out = [task for task in tasks if str(task.get("split") or "held-in") == "held-out"]
    if not held_in:
        raise ValueError("Optimization requires at least one held-in eval task")
    if len(held_in) < 3:
        return list(held_in), list(held_in), held_out
    val_size = max(1, len(held_in) // 5)
    return held_in[:-val_size], held_in[-val_size:], held_out


def _run_modern_optimizer(
    *,
    engine: str,
    continuation_engine: str,
    seed_candidate: str,
    evaluator: Callable[..., Any],
    dataset: list[dict[str, Any]],
    valset: list[dict[str, Any]],
    test_set: list[dict[str, Any]],
    objective: str,
    background: str,
    output_dir: Path,
    max_evals: int,
    explore_max_evals: int | None,
    max_token_cost: float | None,
    reflection_lm: str,
    optimizer_model: str,
    optimizer_effort: str | None,
    agent_sandbox: bool,
    max_workers: int,
    seed: int,
    max_candidate_proposals: int | None,
    candidate_selection_strategy: str,
    frontier_type: str,
    acceptance_criterion: str,
    cache_evaluation: bool,
    use_merge: bool,
    max_merge_invocations: int,
    reflection_minibatch_size: int | None,
) -> Any:
    try:
        from gepa.optimize_anything import (
            OptimizeAnythingConfig,
            optimize_anything,
            optimize_best_of,
        )
    except ImportError as exc:
        raise RuntimeError(
            "This optimizer requires GEPA's engine-pluggable optimize_anything API. "
            "Install a GEPA release containing `OptimizeAnythingConfig` and "
            f"`optimize_best_of` (the Omni API). Import failed: {exc}"
        ) from exc

    common = {
        "evaluator": evaluator,
        "dataset": dataset,
        "valset": valset,
        "objective": objective,
        "background": background,
    }
    if test_set:
        common["test_set"] = test_set

    def make_config(
        engine_name: str,
        *,
        eval_budget: int,
        token_budget: float | None,
        phase: str,
    ):
        public_name = engine_name
        oa_engine = "meta_harness" if engine_name == "gepa-meta-harness" else engine_name
        engine_config: dict[str, Any]
        if oa_engine == "gepa":
            engine_config = {
                "engine": {
                    "max_candidate_proposals": max_candidate_proposals,
                    "max_workers": max(1, int(max_workers)),
                    "parallel": max_workers > 1,
                    "seed": int(seed),
                    "display_progress_bar": False,
                    "candidate_selection_strategy": candidate_selection_strategy,
                    "frontier_type": frontier_type,
                    "acceptance_criterion": acceptance_criterion,
                    "cache_evaluation": cache_evaluation,
                },
                "reflection": {
                    "reflection_lm": reflection_lm,
                    "reflection_minibatch_size": reflection_minibatch_size,
                    "module_selector": "all",
                },
                "merge": ({"max_merge_invocations": max_merge_invocations} if use_merge else None),
                "refiner": None,
            }
        else:
            engine_config = {"model": optimizer_model}
            if optimizer_effort:
                engine_config["effort"] = optimizer_effort
        phase_dir = output_dir / "oa" / phase / public_name
        return OptimizeAnythingConfig(
            engine=oa_engine,
            name=f"superqode-skill-{phase}-{public_name}",
            max_evals=eval_budget,
            max_token_cost=token_budget,
            max_concurrency=max(1, int(max_workers)),
            output_dir=phase_dir,
            run_dir=str(phase_dir / "engine"),
            sandbox=agent_sandbox,
            engine_config=engine_config,
        )

    if engine != "omni":
        return optimize_anything(
            seed_candidate,
            **common,
            config=make_config(
                engine,
                eval_budget=max_evals,
                token_budget=max_token_cost,
                phase="single",
            ),
        )

    if max_evals < 4:
        raise ValueError("Omni requires --max-metric-calls of at least 4")
    explore_evals = explore_max_evals or max(1, max_evals // 4)
    continuation_evals = max_evals - (3 * explore_evals)
    if continuation_evals < 1:
        raise ValueError(
            "Omni exploration budgets leave no continuation budget; lower "
            "--explore-max-evals or raise --max-metric-calls"
        )
    explore_token_cost = max_token_cost / 4 if max_token_cost is not None else None
    continuation_token_cost = (
        max_token_cost - (3 * explore_token_cost)
        if max_token_cost is not None and explore_token_cost is not None
        else None
    )
    explore_configs = [
        make_config(
            "gepa-meta-harness" if item == "meta_harness" else item,
            eval_budget=explore_evals,
            token_budget=explore_token_cost,
            phase="explore",
        )
        for item in OMNI_EXPLORATION_ENGINES
    ]
    explore = optimize_best_of(
        seed_candidate,
        **common,
        configs=explore_configs,
        max_workers=len(explore_configs),
    )
    continuation = optimize_anything(
        explore.best_candidate,
        **common,
        config=make_config(
            continuation_engine,
            eval_budget=continuation_evals,
            token_budget=continuation_token_cost,
            phase="continue",
        ),
    )
    explore_results = (getattr(explore, "metadata", {}) or {}).get("all_results", [])
    continuation_metadata = getattr(continuation, "metadata", {}) or {}
    continuation.metadata = continuation_metadata
    explore_rows = [
        {
            "engine": (getattr(item, "metadata", {}) or {}).get("engine"),
            "best_score": getattr(item, "best_score", None),
            "total_evals": getattr(item, "total_evals", None),
            "total_cost": (getattr(item, "metadata", {}) or {}).get("total_cost"),
        }
        for item in explore_results
    ]
    continuation_row = {
        "engine": continuation_metadata.get("engine") or continuation_engine,
        "best_score": getattr(continuation, "best_score", None),
        "total_evals": getattr(continuation, "total_evals", None),
        "total_cost": continuation_metadata.get("total_cost"),
    }
    all_rows = [*explore_rows, continuation_row]
    continuation.metadata["omni"] = True
    continuation.metadata["omni_continuation_engine"] = continuation_engine
    continuation.metadata["omni_explore"] = explore_rows
    continuation.metadata["omni_continuation"] = continuation_row
    continuation.metadata["omni_total_evals"] = sum(
        int(row["total_evals"]) for row in all_rows if row.get("total_evals") is not None
    )
    continuation.metadata["omni_total_cost"] = sum(
        float(row["total_cost"]) for row in all_rows if row.get("total_cost") is not None
    )
    explore_metadata = getattr(explore, "metadata", {}) or {}
    if explore_metadata.get("baseline_test_score") is not None:
        continuation.metadata["omni_original_baseline_test_score"] = explore_metadata[
            "baseline_test_score"
        ]
    return continuation


def _result_metadata(result: Any) -> dict[str, Any]:
    metadata = getattr(result, "metadata", None)
    if not isinstance(metadata, dict):
        return {}
    keys = (
        "engine",
        "omni",
        "omni_continuation_engine",
        "omni_explore",
        "omni_continuation",
        "omni_total_evals",
        "omni_total_cost",
        "budget",
        "total_cost",
        "wall_time",
        "output_dir",
        "baseline_test_score",
        "test_score",
        "omni_original_baseline_test_score",
    )
    return {key: metadata[key] for key in keys if key in metadata}


def _run_skill_heldout_gate(
    *,
    evaluator: _GEPASkillEvaluator,
    baseline_text: str,
    candidate_text: str,
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_scores: dict[str, float] = {}
    candidate_scores: dict[str, float] = {}
    regressions: list[str] = []
    for task in tasks:
        task_id = str(task.get("id") or "")
        baseline_score, _ = evaluator.evaluate(baseline_text, task)
        candidate_score, _ = evaluator.evaluate(candidate_text, task)
        baseline_scores[task_id] = baseline_score
        candidate_scores[task_id] = candidate_score
        if baseline_score > candidate_score:
            regressions.append(task_id)
    baseline_avg = sum(baseline_scores.values()) / len(baseline_scores)
    candidate_avg = sum(candidate_scores.values()) / len(candidate_scores)
    return {
        "accepted": not regressions and candidate_avg >= baseline_avg,
        "baseline_score": baseline_avg,
        "candidate_score": candidate_avg,
        "baseline_scores": baseline_scores,
        "candidate_scores": candidate_scores,
        "regressions": regressions,
    }


def _write_candidate_harness(
    *,
    source_harness_path: Path,
    output_path: Path,
    skill_name: str,
    skill_text: str,
) -> None:
    from dataclasses import replace

    spec = load_harness_spec(source_harness_path)
    injection = (
        f"\n\n## Candidate Skill Under GEPA Optimization: {skill_name}\n\n{skill_text.strip()}\n"
    )
    if spec.agents:
        first = spec.agents[0]
        agents = (
            replace(
                first,
                system_prompt=((first.system_prompt or "").rstrip() + injection).strip(),
            ),
            *spec.agents[1:],
        )
        spec = replace(spec, agents=agents)
    else:
        from superqode.harness.spec import AgentSpec

        spec = replace(
            spec,
            agents=(
                AgentSpec(
                    id="candidate",
                    role="candidate",
                    system_prompt=injection.strip(),
                ),
            ),
        )
    output_path.write_text(
        yaml.safe_dump(harness_spec_to_dict(spec), sort_keys=False), encoding="utf-8"
    )


def _safe_name(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    return "-".join(part for part in cleaned.split("-") if part)[:80] or "task"
