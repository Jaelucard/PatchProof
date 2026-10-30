#!/bin/sh
set -eu

fail() {
    printf '%s\n' 'PatchProof gateway refused unsafe startup.' >&2
    exit 1
}

expected_uid=${PATCHPROOF_EXPECTED_UID-}
expected_gid=${PATCHPROOF_EXPECTED_GID-}
case "$expected_uid" in ''|0|0[0-9]*|*[!0-9]*) fail ;; esac
case "$expected_gid" in ''|0[0-9]*|*[!0-9]*) fail ;; esac
[ "${#expected_uid}" -le 10 ] && [ "${#expected_gid}" -le 10 ] || fail
[ "$(id -u)" = "$expected_uid" ] && [ "$(id -g)" = "$expected_gid" ] || fail

# Bind-file UID metadata can be virtualized by Docker Desktop. The host preparer
# validates ownership; this guard enforces the intended runtime identity and the
# exact credential-file shape before Caddy can parse or log any credential text.
AUTH_FILE=/run/secrets/judge-users
[ -f "$AUTH_FILE" ] && [ ! -L "$AUTH_FILE" ] || fail
file_mode=$(stat -c '%a' "$AUTH_FILE" 2>/dev/null) || fail
case "$file_mode" in 400|600) ;; *) fail ;; esac
file_size=$(stat -c '%s' "$AUTH_FILE" 2>/dev/null) || fail
case "$file_size" in ''|*[!0-9]*) fail ;; esac
[ "$file_size" -ge 1 ] && [ "$file_size" -le 256 ] || fail
awk '
    NR != 1 || NF != 2 { bad = 1; next }
    {
        if ($0 != $1 " " $2 || $1 !~ /^[A-Za-z0-9_-]+$/ || length($1) > 64) bad = 1
        if (tolower($1) == "import") bad = 1
        hash = $2
        version = substr(hash, 1, 4)
        cost = substr(hash, 5, 2)
        if (length(hash) != 60) bad = 1
        if (version != "$2a$" && version != "$2b$" && version != "$2y$") bad = 1
        if (cost != "12" && cost != "13" && cost != "14" && cost != "15" && cost != "16") bad = 1
        if (substr(hash, 7, 1) != "$") bad = 1
        body = substr(hash, 8)
        if (length(body) != 53 || body !~ /^[.\/A-Za-z0-9]+$/) bad = 1
    }
    END { if (NR != 1 || bad) exit 1 }
' "$AUTH_FILE" >/dev/null 2>&1 || fail

exec caddy "$@"
