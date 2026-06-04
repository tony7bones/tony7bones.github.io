# NEXT TASK — read this first

> **For the AI picking this up locally:** Do NOT explore freely or ask "what
> should I do?" first. Follow the steps below **in order**. There is exactly one
> task. Stop at the checkpoint and wait for the human.

## Step 1 — Get on the branch
```bash
git checkout hybrid-repo && git pull
```

## Step 2 — Read these two files completely, before doing anything else
- `docs/HYBRID-REPO-HANDOFF.md`  (the full handoff / context)
- `CLAUDE.md`                    (project rules — they override default behavior)

## Step 3 — Verify the baseline (paste the human the output of all three)
```bash
pytest _tools/ -q
ruff check _tools/
python3 _tools/generate_repo.py && git status --porcelain
```
**Expected:** `61 passed`, ruff clean, and `git status` **clean** (no changes).
If anything differs, **STOP** and tell the human.

## Step 4 — The task: live end-to-end test of the prototype
File under test: `_tools/external_addons.py` (the manifest-driven resolver).

1. Create `_tools/external-addons.json` with **ONE** real, public Kodi add-on that
   has GitHub releases. **Propose the add-on and show the JSON to the human before
   running anything.** (Schema: `_tools/external-addons.example.json`.)
2. Run the dry run and show the resolved output:
   ```bash
   python3 _tools/external_addons.py
   ```
3. If it resolves correctly, write the artifacts and show what appeared under `repo/`:
   ```bash
   python3 _tools/external_addons.py --write
   git status --porcelain
   ```
4. **Do NOT commit anything yet.** Show the human the diff and wait for approval.

### Alternative task (only if the human says so)
Instead of the live test, fix the two doc/impl mismatches described in §4 and §7 of
`docs/HYBRID-REPO-HANDOFF.md`:
- the canonical source URL mismatch (`tony7bones.github.io/repo` vs. `raw.githubusercontent.com`)
- the "CI never commits" claim that contradicts `.github/workflows/generate_repo.yml`

Show each change as a diff and wait for approval before committing.

## Rules (do not violate)
- The prototype is **OFF by default**. With no `_tools/external-addons.json`,
  `generate_repo.py` output is byte-identical. Do not break that invariant.
- §7 of the handoff doc lists "decisions still needed from the maintainer."
  **Do NOT act on those without asking the human.**
- Make **no** changes outside the one task above.
- Stop at every "show the human / wait for approval" checkpoint.
