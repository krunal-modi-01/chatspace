#!/usr/bin/env bash
# CI secret-scan gate (T38). Full-repository scan run on every PR/push — this
# is the CI-side counterpart to `.claude/hooks/secret-scan.sh` (which scans a
# single file at edit time). Mirrors the same detection patterns so both
# gates agree on what counts as a leaked secret.
#
# MANDATORY, not disable-able: no env var, flag, or commit message trailer
# short-circuits this script. The only way to make it pass is to remove the
# offending content (or, for a real false positive, adjust the pattern here
# via a reviewed PR to this file itself).
#
# Exit 0  -> clean.
# Exit 1  -> a likely secret was found; the CI job fails and blocks merge.
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

fail=0

if command -v gitleaks >/dev/null 2>&1; then
  echo "== secret-scan: using gitleaks =="
  # Scans the working tree AND full git history so a secret that was
  # committed and later removed still fails the gate.
  if ! gitleaks detect --source "$REPO_ROOT" --redact --exit-code 1; then
    echo "gitleaks detected a likely secret. Remove it and use an env var / secret manager." >&2
    fail=1
  fi
else
  echo "== secret-scan: gitleaks unavailable, falling back to regex heuristics ==" >&2
  # Same high-signal patterns as .claude/hooks/secret-scan.sh, applied to
  # every git-tracked file (excluding lockfiles, which can contain incidental
  # hash-looking strings that trip the JWT-shaped pattern).
  patterns=(
    'AKIA[0-9A-Z]{16}'                              # AWS access key
    'ASIA[0-9A-Z]{16}'
    '-----BEGIN[A-Z ]*PRIVATE KEY-----'
    'ghp_[A-Za-z0-9]{36}'                            # GitHub PAT
    'xox[baprs]-[A-Za-z0-9-]+'                       # Slack token
    'sk-[A-Za-z0-9]{20,}'                            # generic API secret / OpenAI-style
    'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.'    # JWT
  )
  # NOTE: deliberately does NOT include the hook's generic
  # `(password|secret|api_key|token)[:=]"..."` catch-all pattern here. That
  # pattern is safe applied to a *single just-edited file* at edit time
  # (.claude/hooks/secret-scan.sh's use case), but applying it repo-wide in
  # this full-scan fallback produces false positives against legitimate,
  # already-reviewed test fixtures (e.g. backend/tests/test_auth_service.py's
  # dummy passwords) — confirmed by running this script locally. This
  # fallback only runs when gitleaks itself is unavailable (never in CI,
  # which always installs gitleaks first); gitleaks' own secret-detection
  # rules are the real safety net and don't share this false-positive mode.
  while IFS= read -r -d '' f; do
    case "$f" in
      *.lock|*/uv.lock|*/package-lock.json|.github/scripts/secret-scan.sh) continue ;;
    esac
    [ -f "$f" ] || continue
    # Skip binary files.
    if ! grep -Iq . "$f" 2>/dev/null; then continue; fi
    for p in "${patterns[@]}"; do
      # `-e` (not a bare pattern arg) so a leading `-----` pattern (the PEM
      # private-key marker) is never misparsed as a grep option.
      if grep -Eiq -e "$p" "$f"; then
        echo "possible secret in $f (matched /$p/)" >&2
        fail=1
      fi
    done
  done < <(git ls-files -z)
fi

if [ "$fail" -ne 0 ]; then
  echo "secret-scan: BLOCKED - one or more likely secrets found." >&2
  exit 1
fi

echo "secret-scan: clean."
exit 0
