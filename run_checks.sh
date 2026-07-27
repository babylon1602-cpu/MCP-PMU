#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${TRACE-0}" == "1" ]]; then
  set -x
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SMOKE_DATE="${SMOKE_DATE:-2026-07-26}"
SMOKE_REUNION="${SMOKE_REUNION:-1}"
SMOKE_COURSE="${SMOKE_COURSE:-1}"

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

fail() {
  echo "ERREUR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "commande introuvable: $1"
}

usage() {
  cat <<EOF
Usage: ./run_checks.sh [options]

Options:
  --skip-venv          N'installe pas le venv ; utilise l'environnement courant.
  --skip-install       N'installe pas les dépendances.
  --skip-pytest        Ne lance pas pytest.
  --skip-smoke         Ne lance pas le smoke test.
  --date YYYY-MM-DD    Date utilisée par le smoke test (défaut: ${SMOKE_DATE}).
  --reunion N          Réunion utilisée par le smoke test (défaut: ${SMOKE_REUNION}).
  --course N           Course utilisée par le smoke test (défaut: ${SMOKE_COURSE}).
  -h, --help           Affiche cette aide.

Variables d'environnement utiles:
  PYTHON_BIN     Interpréteur Python à utiliser (défaut: python3)
  TRACE=1        Active le mode debug bash
  SMOKE_DATE     Date par défaut du smoke test
  SMOKE_REUNION  Réunion par défaut
  SMOKE_COURSE   Course par défaut
EOF
}

SKIP_VENV=0
SKIP_INSTALL=0
SKIP_PYTEST=0
SKIP_SMOKE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-venv) SKIP_VENV=1; shift ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    --skip-pytest) SKIP_PYTEST=1; shift ;;
    --skip-smoke) SKIP_SMOKE=1; shift ;;
    --date) SMOKE_DATE="$2"; shift 2 ;;
    --reunion) SMOKE_REUNION="$2"; shift 2 ;;
    --course) SMOKE_COURSE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "option inconnue: $1" ;;
  esac
done

require_cmd "$PYTHON_BIN"
cd "$ROOT_DIR"

if [[ "$SKIP_VENV" -eq 0 ]]; then
  if [[ ! -d "$VENV_DIR" ]]; then
    log "Création du virtualenv dans $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  log "Virtualenv activé: $VENV_DIR"
else
  log "Virtualenv ignoré ; environnement Python courant utilisé"
fi

if [[ "$SKIP_INSTALL" -eq 0 ]]; then
  log "Installation des dépendances"
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
else
  log "Installation des dépendances ignorée"
fi

log "Compilation de contrôle"
python -m py_compile server.py smoke_test.py

if [[ "$SKIP_PYTEST" -eq 0 ]]; then
  log "Exécution des tests pytest"
  pytest -q
else
  log "Pytest ignoré"
fi

if [[ "$SKIP_SMOKE" -eq 0 ]]; then
  log "Exécution du smoke test"
  python smoke_test.py --date "$SMOKE_DATE" --reunion "$SMOKE_REUNION" --course "$SMOKE_COURSE"
else
  log "Smoke test ignoré"
fi

log "Tous les contrôles demandés sont terminés"
