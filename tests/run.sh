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
for f in glob.glob('roles/*/*/*.y*ml') + glob.glob('*.yml') + glob.glob('playbooks/*.yml') + glob.glob('meta/*.yml') + glob.glob('examples/*.yml') + glob.glob('tests/*.yml'):
    try: yaml.safe_load(open(f))
    except Exception as e: bad += 1; print(f, e)
env = jinja2.Environment()
for f in glob.glob('roles/*/templates/*.j2'):
    try: env.parse(open(f).read())
    except Exception as e: bad += 1; print(f, e)
sys.exit(1 if bad else 0)
PY
collection_build() {
  local d; d=$(mktemp -d)
  ansible-galaxy collection build --force --output-path "$d" . >/dev/null || return 1
  local tgz; tgz=$(ls "$d"/*.tar.gz)
  # Nothing local or secret may ship, and the root playbooks must match the shipped ones.
  if tar tzf "$tgz" | grep -E '(^|/)(\.vault_pass|secrets\.yml|hosts\.ini|inventory|group_vars|.*\.bak|.*\.vault)(/|$)'; then
    echo "forbidden files in the tarball"; return 1
  fi
  ansible-galaxy collection install "$tgz" -p "$d/inst" >/dev/null || return 1
  ANSIBLE_COLLECTIONS_PATH="$d/inst" ansible-playbook -i "$inv" --syntax-check \
    muelli.stalwart_stack.site muelli.stalwart_stack.teardown >/dev/null || return 1
  for p in playbook:site teardown:teardown; do
    diff <(sed 's/muelli\.stalwart_stack\.//' playbooks/${p#*:}.yml) ${p%%:*}.yml >/dev/null \
      || { echo "${p%%:*}.yml and playbooks/${p#*:}.yml differ"; return 1; }
  done
  rm -rf "$d"
}
step "collection build, install and FQCN playbooks" collection_build
if command -v ansible-lint >/dev/null; then
  step "ansible-lint (errors only, style rules skipped)" ansible-lint --offline -p --skip-list var-naming,yaml roles playbook.yml teardown.yml playbooks tests
else
  echo "== ansible-lint not installed, skipped"
fi
exit $fail
