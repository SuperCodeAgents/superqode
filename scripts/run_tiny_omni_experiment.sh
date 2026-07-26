#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CALL_DIR="$(pwd)"
DEFAULT_TASKS="${ROOT_DIR}/examples/evals/omni-tiny.yaml"
OMNI_TASKS="${ROOT_DIR}/examples/evals/omni-release.yaml"
GEPA_COMMIT="${OMNI_GEPA_COMMIT:-f919db0a622e2e9f9204779b81fe00cc1b2d808f}"
GEPA_REQUIREMENT="gepa @ git+https://github.com/gepa-ai/gepa.git@${GEPA_COMMIT}"

MODE="smoke"
SPEC_PATH=""
TASKS_PATH=""
LOCAL_MODEL="${OMNI_LOCAL_MODEL:-qwen3.5:9b}"
WORKING_DIR="${CALL_DIR}"
OUTPUT_DIR=""
ASSUME_YES=0

usage() {
  cat <<'EOF'
Run a tightly bounded GEPA experiment with local rollouts and Claude subscription auth.

Usage:
  scripts/run_tiny_omni_experiment.sh --spec PATH [options]

Options:
  --spec PATH          HarnessSpec to optimize (required; never overwritten)
  --mode MODE          smoke (default) or release-quality omni
  --model MODEL        Installed Ollama model (default: qwen3.5:9b)
  --tasks PATH         Override the mode-specific eval tasks
  --working-dir PATH   Repository used by harness rollouts (default: current directory)
  --output PATH        Staging directory (default: unique .superqode directory)
  --yes                Skip the final interactive confirmation
  -h, --help           Show this help

Examples:
  scripts/run_tiny_omni_experiment.sh \
    --spec examples/harnesses/omni-tiny-local.yaml

  scripts/run_tiny_omni_experiment.sh \
    --spec examples/harnesses/omni-tiny-local.yaml \
    --mode omni

The script unsets ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN for the child
process so Claude Code uses your signed-in subscription. It does not modify the
source harness and it does not pull models automatically.
EOF
}

fail() {
  echo "Error: $*" >&2
  exit 2
}

absolute_from_call_dir() {
  local value="$1"
  if [[ "${value}" = /* ]]; then
    printf '%s\n' "${value}"
  else
    printf '%s\n' "${CALL_DIR}/${value}"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --spec)
      [[ $# -ge 2 ]] || fail "--spec requires a path"
      SPEC_PATH="$2"
      shift 2
      ;;
    --mode)
      [[ $# -ge 2 ]] || fail "--mode requires smoke or omni"
      MODE="$2"
      shift 2
      ;;
    --model)
      [[ $# -ge 2 ]] || fail "--model requires an Ollama model"
      LOCAL_MODEL="$2"
      shift 2
      ;;
    --tasks)
      [[ $# -ge 2 ]] || fail "--tasks requires a path"
      TASKS_PATH="$2"
      shift 2
      ;;
    --working-dir)
      [[ $# -ge 2 ]] || fail "--working-dir requires a path"
      WORKING_DIR="$2"
      shift 2
      ;;
    --output)
      [[ $# -ge 2 ]] || fail "--output requires a path"
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --yes)
      ASSUME_YES=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ -n "${SPEC_PATH}" ]] || fail "--spec is required"
[[ "${MODE}" = "smoke" || "${MODE}" = "omni" ]] || fail "--mode must be smoke or omni"

SPEC_PATH="$(absolute_from_call_dir "${SPEC_PATH}")"
if [[ -z "${TASKS_PATH}" ]]; then
  if [[ "${MODE}" = "omni" ]]; then
    TASKS_PATH="${OMNI_TASKS}"
  else
    TASKS_PATH="${DEFAULT_TASKS}"
  fi
else
  TASKS_PATH="$(absolute_from_call_dir "${TASKS_PATH}")"
fi
WORKING_DIR="$(absolute_from_call_dir "${WORKING_DIR}")"
[[ -f "${SPEC_PATH}" ]] || fail "HarnessSpec not found: ${SPEC_PATH}"
[[ -f "${TASKS_PATH}" ]] || fail "task file not found: ${TASKS_PATH}"
[[ -d "${WORKING_DIR}" ]] || fail "working directory not found: ${WORKING_DIR}"

command -v claude >/dev/null 2>&1 || fail "Claude Code is not installed"
command -v ollama >/dev/null 2>&1 || fail "Ollama is not installed"
command -v uv >/dev/null 2>&1 || fail "uv is not installed"

CLAUDE_STATUS="$(claude auth status 2>/dev/null || true)"
if ! grep -q '"loggedIn": true' <<<"${CLAUDE_STATUS}"; then
  fail "Claude Code is signed out. Run 'claude', complete /login, then rerun this script"
fi

if ! OLLAMA_MODELS="$(ollama list 2>/dev/null)"; then
  fail "Ollama is not responding. Start it with 'ollama serve'"
fi
if ! awk 'NR > 1 {print $1}' <<<"${OLLAMA_MODELS}" | grep -Fxq "${LOCAL_MODEL}"; then
  fail "Ollama model '${LOCAL_MODEL}' is not installed. Run: ollama pull ${LOCAL_MODEL}"
fi

if [[ -n "${ANTHROPIC_API_KEY:-}" || -n "${ANTHROPIC_AUTH_TOKEN:-}" ]]; then
  echo "Note: Anthropic API environment credentials are set; they will be unset for this run."
fi

if [[ -z "${OUTPUT_DIR}" ]]; then
  OUTPUT_DIR="${ROOT_DIR}/.superqode/harness-optimizations/${MODE}-$(date +%Y%m%d-%H%M%S)"
else
  OUTPUT_DIR="$(absolute_from_call_dir "${OUTPUT_DIR}")"
fi

COMMON_ARGS=(
  harness optimize-omni
  --spec "${SPEC_PATH}"
  --tasks "${TASKS_PATH}"
  --provider ollama
  --model "${LOCAL_MODEL}"
  --optimizer-model haiku
  --working-dir "${WORKING_DIR}"
  --output "${OUTPUT_DIR}"
  --live
)

if [[ "${MODE}" = "smoke" ]]; then
  EXPERIMENT_ARGS=(
    --engine autoresearch
    --max-evals 1
    --max-token-cost 0.10
  )
  BUDGET_DESCRIPTION="1 optimizer evaluation; Claude cap: USD 0.10 equivalent"
else
  EXPERIMENT_ARGS=(
    --engine omni
    --continuation-engine gepa
    --reflection-lm "ollama/${LOCAL_MODEL}"
    --max-evals 24
    --explore-max-evals 6
    --max-token-cost 2.00
    --max-workers 1
  )
  BUDGET_DESCRIPTION="24 optimizer evaluations; total proposer cap: USD 2.00 equivalent"
fi

COMMAND=(
  env
  -u ANTHROPIC_API_KEY
  -u ANTHROPIC_AUTH_TOKEN
  uv run
  --with "${GEPA_REQUIREMENT}"
  python
  -m superqode.main
  "${COMMON_ARGS[@]}"
  "${EXPERIMENT_ARGS[@]}"
)

echo "Tiny GEPA experiment is ready."
echo "  Mode:       ${MODE}"
echo "  Harness:    ${SPEC_PATH}"
echo "  Tasks:      ${TASKS_PATH}"
echo "  Local model:${LOCAL_MODEL}"
echo "  GEPA commit:${GEPA_COMMIT}"
echo "  Output:     ${OUTPUT_DIR}"
echo "  Budget:     ${BUDGET_DESCRIPTION}"
echo
printf 'Command:'
printf ' %q' "${COMMAND[@]}"
printf '\n\n'

if [[ "${ASSUME_YES}" -ne 1 ]]; then
  printf 'Run the experiment now? [y/N] '
  if ! read -r REPLY || [[ ! "${REPLY}" =~ ^[Yy]$ ]]; then
    echo "Cancelled before any model call."
    exit 0
  fi
fi

cd "${ROOT_DIR}"
"${COMMAND[@]}"

echo
echo "Experiment finished. Review staged artifacts in:"
echo "  ${OUTPUT_DIR}"
