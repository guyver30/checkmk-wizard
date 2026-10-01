#!/usr/bin/env bash
# Harness for deploy/reset-site.sh. Runs a COPY of the script in a temp dir with
# stub `podman`, `curl` and `sleep` on PATH, so nothing real is touched.
# Usage: bash test-reset-site.sh   (exit 0 = all cases pass)

set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
script_src="$repo/deploy/reset-site.sh"
work_root="$(mktemp -d "${TMPDIR:-/tmp}/reset-site-test.XXXXXX")"
trap 'rm -rf "$work_root"' EXIT

fails=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1 -- $2"; fails=$((fails + 1)); }

# Per-case state
D="" LOG="" OUT="" RC=0

# new_case NAME [ENV_CONTENT]
new_case() {
    D="$work_root/$1"
    mkdir -p "$D/deploy" "$D/bin"
    cp "$script_src" "$D/deploy/reset-site.sh"
    printf 'services:\n  checkmk:\n    image: checkmk/check-mk-raw:2.4.0-latest\n' > "$D/deploy/compose.yaml"
    printf '%s' "${2:-CMK_SITE_ID=dmc
OTHER=keep
}" > "$D/deploy/.env"
    LOG="$D/log"
    : > "$LOG"
    cat > "$D/bin/podman" <<'SHIM'
#!/usr/bin/env bash
echo "podman $* | $(grep '^CMK_SITE_ID' .env 2>/dev/null | tr '\n' ' ')" >> "$LOG"
case "$*" in
    "compose config -q") [ -z "${STUB_CONFIG_FAIL:-}" ] || exit 1 ;;
    "volume exists "*) [ -z "${STUB_NO_VOLUME:-}" ] || exit 1 ;;
    "container inspect"*) echo "${STUB_RUNNING:-true}" ;;
    "exec checkmk ls"*|"run "*) printf 'lost+found\n%s\n' "${STUB_SITES:-dmc}" ;;
    "compose exec checkmk omd config"*) echo off ;;
esac
exit 0
SHIM
    cat > "$D/bin/curl" <<'SHIM'
#!/usr/bin/env bash
echo "curl $*" >> "$LOG"
printf 302
SHIM
    printf '#!/usr/bin/env bash\nexit 0\n' > "$D/bin/sleep"
    chmod +x "$D/bin/podman" "$D/bin/curl" "$D/bin/sleep"
}

# run_case INPUT ARGS...  (INPUT is a printf format string)
run_case() {
    local input="$1"; shift
    # shellcheck disable=SC2059  # input is a printf format on purpose (escapes)
    OUT="$(printf "$input" | PATH="$D/bin:$PATH" LOG="$LOG" bash "$D/deploy/reset-site.sh" "$@" 2>&1)"
    RC=$?
}

env_of() { cat "$D/deploy/.env"; }
log_has() { grep -q -- "$1" "$LOG"; }
line_no() { grep -n -- "$1" "$LOG" | head -1 | cut -d: -f1; }

assert_no_changes() {
    local name="$1" orig="$2"
    if [ "$RC" -ne 1 ]; then fail "$name" "exit $RC, expected 1"; return; fi
    if ! grep -q "Aborted." <<<"$OUT"; then fail "$name" "no 'Aborted.' in output"; return; fi
    if log_has "compose down" || log_has "volume rm" || log_has "compose up"; then
        fail "$name" "destructive call logged"; return
    fi
    if [ "$(env_of)" != "$orig" ]; then fail "$name" ".env changed"; return; fi
    pass "$name"
}

orig_env='CMK_SITE_ID=dmc
OTHER=keep'

# --- abort paths -----------------------------------------------------------
new_case esc_confirm
run_case '\033'
assert_no_changes "Esc at confirm prompt" "$orig_env"

new_case esc_newname
run_case 'dmc\n\033'
assert_no_changes "Esc at new-name prompt" "$orig_env"

new_case wrong_confirm
run_case 'xyz\n'
assert_no_changes "wrong confirmation" "$orig_env"

new_case eof
run_case ''
assert_no_changes "EOF on stdin" "$orig_env"

# --- keep name ---------------------------------------------------------------
new_case keep
run_case 'dmc\n\n'
n=keep_name
if [ "$RC" -ne 0 ]; then fail $n "exit $RC: $OUT"
else
    d="$(line_no 'compose down')"; v="$(line_no 'volume rm')"; u="$(line_no 'compose up')"
    if [ -z "$d" ] || [ -z "$v" ] || [ -z "$u" ] || ! [ "$d" -lt "$v" ] || ! [ "$v" -lt "$u" ]; then
        fail $n "bad order down=$d rm=$v up=$u"
    elif [ "$(env_of)" != "$orig_env" ]; then fail $n ".env changed: $(env_of)"
    elif ! log_has '/dmc/check_mk/'; then fail $n "curl not on /dmc/"
    else pass $n; fi
fi

# --- rename ----------------------------------------------------------------
new_case rename
run_case 'dmc\nnewsite\n'
n=rename
if [ "$RC" -ne 0 ]; then fail $n "exit $RC: $OUT"
elif [ "$(grep -c '^CMK_SITE_ID=newsite$' "$D/deploy/.env")" -ne 1 ] || [ "$(grep -c '^CMK_SITE_ID' "$D/deploy/.env")" -ne 1 ]; then
    fail $n ".env: $(env_of)"
elif ! log_has '/newsite/check_mk/' || ! log_has 'omd config newsite show'; then fail $n "later calls not using new name"
elif ! grep -q 'volume rm .*| CMK_SITE_ID=dmc' "$LOG"; then fail $n ".env written before volume rm"
elif ! grep -q 'compose up -d | CMK_SITE_ID=newsite' "$LOG"; then fail $n ".env not written before compose up"
else pass $n; fi

new_case invalid_then_valid
run_case 'dmc\n1bad\ngood\n'
n=invalid_then_valid
if [ "$RC" -ne 0 ]; then fail $n "exit $RC: $OUT"
elif ! grep -q 'Invalid: start with a letter' <<<"$OUT"; then fail $n "no re-ask message"
elif ! grep -q '^CMK_SITE_ID=good$' "$D/deploy/.env"; then fail $n ".env: $(env_of)"
else pass $n; fi

new_case backspace
run_case 'dmc\nnewx\177site\n'
n=backspace_editing
if [ "$RC" -ne 0 ]; then fail $n "exit $RC: $OUT"
elif ! grep -q '^CMK_SITE_ID=newsite$' "$D/deploy/.env"; then fail $n ".env: $(env_of)"
else pass $n; fi

new_case commented '# CMK_SITE_ID=dmc
OTHER=keep
'
run_case 'dmc\nabc\n'
n=uncomment_line
if [ "$RC" -ne 0 ]; then fail $n "exit $RC: $OUT"
elif ! grep -q '^CMK_SITE_ID=abc$' "$D/deploy/.env" || grep -q '^# CMK_SITE_ID' "$D/deploy/.env"; then fail $n ".env: $(env_of)"
else pass $n; fi

# --- volume differs from .env ---------------------------------------------
new_case mismatch_abort
STUB_SITES=other run_case 'dmc\n'
n=mismatch_wrong_confirm_aborts
if [ "$RC" -ne 1 ] || ! grep -q 'WARNING: they differ' <<<"$OUT"; then fail $n "rc=$RC out=$OUT"
elif log_has "compose down"; then fail $n "went on"
else pass $n; fi

new_case mismatch_ok
STUB_SITES=other run_case 'other\n\n'
n=mismatch_default_is_volume_site
if [ "$RC" -ne 0 ]; then fail $n "exit $RC: $OUT"
elif ! grep -q '^CMK_SITE_ID=other$' "$D/deploy/.env"; then fail $n ".env: $(env_of)"
else pass $n; fi

# --- non-interactive ---------------------------------------------------------
new_case yes
STUB_SITES=other run_case '' --yes
n=yes_keeps_detected_name
if [ "$RC" -ne 0 ]; then fail $n "exit $RC: $OUT"
elif ! grep -q '^CMK_SITE_ID=other$' "$D/deploy/.env"; then fail $n ".env: $(env_of)"
else pass $n; fi

new_case yes_site
run_case '' --yes --site foo
n=yes_site_renames
if [ "$RC" -ne 0 ]; then fail $n "exit $RC: $OUT"
elif ! grep -q '^CMK_SITE_ID=foo$' "$D/deploy/.env"; then fail $n ".env: $(env_of)"
else pass $n; fi

new_case bad_site
run_case '' --site 9bad --yes
n=site_invalid_exit_2
if [ "$RC" -ne 2 ]; then fail $n "exit $RC"
elif [ -s "$LOG" ]; then fail $n "podman called: $(cat "$LOG")"
else pass $n; fi

# --- pre-flight / missing volume ---------------------------------------------
new_case preflight
STUB_CONFIG_FAIL=1 run_case 'dmc\n'
n=preflight_config_fail
if [ "$RC" -eq 0 ]; then fail $n "exit 0"
elif ! grep -q 'init-env.sh' <<<"$OUT"; then fail $n "no init-env.sh hint"
elif grep -q 'confirm' <<<"$OUT"; then fail $n "prompt shown"
elif [ "$(wc -l < "$LOG")" -ne 1 ]; then fail $n "extra podman calls: $(cat "$LOG")"
else pass $n; fi

new_case novolume
STUB_NO_VOLUME=1 run_case 'dmc\n\n'
n=volume_missing_proceeds
if [ "$RC" -ne 0 ]; then fail $n "exit $RC: $OUT"
elif ! grep -q 'no site to delete' <<<"$OUT"; then fail $n "no notice"
elif ! log_has "compose up"; then fail $n "did not bring stack up"
else pass $n; fi

echo
if [ "$fails" -ne 0 ]; then echo "$fails case(s) failed"; exit 1; fi
echo "All cases passed"
