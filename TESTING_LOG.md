# Office testing log

No Claude Code access at the office — this file (and `debug-logs/`) is
the handoff channel.

**Easy path:** run `./scripts/collect-debug-log.sh` — it collects git
status, docker/compose versions, reachability checks against
github.com/ghcr.io/registry-1.docker.io/pypi.org/registry.npmjs.org,
`docker compose config`/`pull`/`ps`/`logs`, does a best-effort redaction
of anything that looks like a password/token/secret, shows you the
result, and asks before committing + pushing it to `debug-logs/`. Read
the output it shows you before confirming — the redaction is a safety
net, not a guarantee.

**Manual path (for anything the script doesn't cover):** paste raw
command output here directly (redirect to a file first so you get the
exact text, don't retype from memory), `git add TESTING_LOG.md && git
commit && git push` before leaving, and it'll be here to read at home.

**Before pasting: check the output for secrets** (`.env` values, PATs,
tokens, real hostnames/IPs if that matters) and redact if needed — this
file goes to a private GitHub repo, still don't want to be casual about
it.

Capture output like this so nothing gets lost/paraphrased:
```bash
docker compose pull 2>&1 | tee ghcr-pull-test.log
docker compose up   2>&1 | tee compose-up-test.log
```
Then paste the relevant part below (or the whole file if short).

---

## Template for each entry

```
### YYYY-MM-DD HH:MM — <what you were testing>

Command:
    <exact command>

Output:
    <paste>

Notes: <anything you noticed — worked / failed / partial>
```

---

<!-- newest entries at the top -->
