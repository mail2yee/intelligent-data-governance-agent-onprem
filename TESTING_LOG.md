# Office testing log

No Claude Code access at the office — this file is the handoff channel.
Paste raw command output here (redirect to a file first so you get the
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
