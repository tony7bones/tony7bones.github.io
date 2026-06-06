# Decision: split the repo into a "clean" branch and a "machine" branch

> Status: **DIRECTION CONFIRMED by a live spike (2026-06-06). Not yet
> implemented.** This records _what_ we decided and _why it's safe_. The actual
> reorganization is a separate, later job and has not started. Today's repo is
> unchanged.
>
> Safety snapshot before the spike: tag `safety/pre-dist-spike-ce5ae11`
> (on `origin`). To rewind to the exact state before any of this:
> `git reset --hard safety/pre-dist-spike-ce5ae11`.

## The problem, in plain words

Right now one folder (`repo/`) does two jobs at once:

- **Stuff written by hand** — the actual add-on source code.
- **Stuff the computer auto-generates** — zip files, `index.html` pages,
  checksum files. Machine clutter nobody edits.

They sit jumbled together, so the folder you work in is full of noise and you
can't tell "yours" from "the machine's." The goal is a clean place to work
where everything you see is meaningful.

## The decision

Split the two jobs across **two branches**:

| Branch                             | Holds                                                 | Who touches it          |
| ---------------------------------- | ----------------------------------------------------- | ----------------------- |
| **`main`** — your clean "drop box" | only hand-written source                              | **you**                 |
| **`dist`** — the "machine" branch  | all auto-generated clutter (zips, indexes, checksums) | **CI only — never you** |

The flow is one direction:

```
you edit  →  main (clean source)
                 │   CI compiles automatically
                 ▼
              dist (generated output)  ──▶  Kodi / the Fire Sticks read this
```

You work only in `main`. CI translates `main` into `dist`. Kodi reads `dist`.
The generated clutter never appears in the branch you look at.

## Why this is the right shape (not the heavier alternative)

An earlier plan ("Full Model B", see
[drop-folder-feasibility.md](drop-folder-feasibility.md)) tried to keep
everything on `main` by duplicating the whole tree into two folders. A second
review found that approach forced a tangle of problems: a self-contradictory
safety check, a real risk of leaking a secret file into the public site,
permanent doubling of large binary files in git history, and a "doubled diff"
on every change.

All of those problems come from one mistaken assumption: _that the generated
files have to live on the same branch you edit._ They don't. They only have to
exist **somewhere** that Kodi can reach. Moving them to a separate `dist`
branch makes every one of those problems disappear instead of having to be
managed forever.

## The risk we had to check first

Kodi (on the Fire Sticks) reaches into this repo over the internet to download
add-ons. It currently fetches from `main`. The open question was: **if the
generated files move to a different branch, can Kodi still find them?** If not,
every installed box breaks. That was the one thing that could have killed the
whole idea, so we tested it before committing to anything.

## The spike: what we tested and what we found (2026-06-06)

We made a throwaway copy of the repo on a `dist` branch and verified, three
independent ways, that the proxy add-on fetches from it cleanly. **Nothing on
the live site or the Fire Sticks was touched** — this was all off to the side.

1. **The code itself** — the proxy uses whatever branch name it's told, with no
   special treatment of `main`. (`lib/repository.py`: the fetch reference is
   literally the configured branch name.)
2. **The download mechanism** — files fetched from `dist` returned HTTP 200 and
   were **byte-for-byte identical** to the same files on `main`; a real add-on
   zip downloaded in full (427 KB); GitHub's content API also honored the
   `dist` reference.
3. **The proxy engine end-to-end** — running the proxy's _real_ code against a
   `dist`-pointed config, it assembled the add-on index and streamed a valid
   zip straight from `dist`. **PASS.**

**Conclusion:** pointing the proxy at a `dist` branch requires only changing the
branch name in its config — no engine changes, no change to the download URLs'
shape, and (critically) no change to the install URL
`https://tony7bones.github.io/`. The dual-branch model is viable and safe.

## Progress

1. **Set up CI to build `main` into `dist` automatically — ✅ DONE (Stage 1,
   QA-approved).** The publisher workflow `.github/workflows/publish-dist.yml`
   runs on every content change to `main` (and on demand) and keeps `dist`
   current. Operating guide: [../playbooks/dist-branch-publisher.md](../playbooks/dist-branch-publisher.md).
2. **Verify the proxy works off `dist` — ✅ largely DONE (Stage 2, QA-approved).**
   Two offline proofs against a throwaway `dist`-pointed config (the real
   `repository.json` is never touched):
   - **2a (engine):** flipping all 12 tony7bones entries to `dist` yields a
     **byte-identical `addons.xml`** + matching md5 vs `main`; all 8 `{ref}`-based
     zips download byte-identical; the proxy reads its own self-update version
     (2.0.0) from `dist`.
   - **2b (real HTTP server):** the proxy's actual serving stack
     (`httpserver`+`routes`+`repository`, same wiring as `service.py`) on a live
     localhost socket serves `/addons.xml` (12 addons), `/addons.xml.md5`, and
     streamed zips from `dist`, and 404s correctly.
   - **2c (live local Kodi) — still pending**: drive the real local Kodi proxy
     (`127.0.0.1:61234`) pointed at `dist` and prove a non-empty `GetDirectory` +
     rendered menu (per `../playbooks/local-kodi-verification.md`). This is the
     last verification gate before cutover. Note: 2a/2b prove equivalence _while
     `dist` mirrors `main`_; the Stage 1 publisher is what keeps them in sync.
3. Flip the proxy to read `dist` (a normal, versioned proxy release). — pending
   (Stage 3, the first live-affecting step)
4. Only then remove the generated clutter from `main` so it becomes the clean
   drop box. — pending (Stage 4)

Each stage is reversible, and the `safety/pre-dist-spike-ce5ae11` tag is the
backstop for the whole effort.
