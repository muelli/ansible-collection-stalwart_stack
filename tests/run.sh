#!/bin/bash
# Offline checks, no target host needed. Run from anywhere:  tests/run.sh
set -u
cd "$(dirname "$0")/.." || exit 1
fail=0
step() { echo "== $1"; shift; "$@" || { echo "FAILED: $*"; fail=1; }; }

inv=$(mktemp); printf '[all]\nlocalhost ansible_connection=local\n[mailservers]\nlocalhost\n' > "$inv"
trap 'rm -f "$inv"' EXIT

step "syntax check" ansible-playbook -i "$inv" --syntax-check playbook.yml teardown.yml
step "derived Caddy sites" ansible-playbook -i localhost, -c local tests/user_instance_sites.yml
step "YAML and Jinja parse" python3 - <<'PY'
import glob, sys, yaml, jinja2
bad = 0
for f in glob.glob('roles/*/*/*.y*ml') + glob.glob('*.yml') + glob.glob('examples/*.yml') + glob.glob('tests/*.yml'):
    try: yaml.safe_load(open(f))
    except Exception as e: bad += 1; print(f, e)
env = jinja2.Environment()
for f in glob.glob('roles/*/templates/*.j2'):
    try: env.parse(open(f).read())
    except Exception as e: bad += 1; print(f, e)
sys.exit(1 if bad else 0)
PY
if command -v ansible-lint >/dev/null; then
  step "ansible-lint (errors only, style rules skipped)" ansible-lint --offline -p --skip-list var-naming,yaml roles playbook.yml teardown.yml tests
else
  echo "== ansible-lint not installed, skipped"
fi
exit $fail
