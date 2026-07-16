"""BELIEF TRIPWIRE: a disproven claim about tvOS storage may not re-enter the docs.

WHY THIS EXISTS
---------------
The 2026-07-14 data loss (an EZ Maintenance++ restore destroyed the owner's customized
Apple TV menu) was not, at root, a coding mistake. It was a FALSE SENTENCE in our own
documentation:

    "Kodi mirrors its settings into NSUserDefaults and rewrites the on-disk userdata
     files from that mirror on launch."

That is false. `MigrateUserdataXMLToNSUserDefaults` (PreflightHandler.mm:81-93) returns
early forever once `UserdataMigrated` is set, and nothing ever copies a key back to disk.
A key SHADOWS the disk file; it does not restore it.

But if you believe it, "vector the file into NSUserDefaults, then delete the disk copy"
looks completely safe - there is a mirror to fall back on. So we wrote exactly that, and
it deleted the only copy of the owner's menu. Six of our docs carried the false claim,
plus the auto-loading agent memory, so every session started by loading the bug.

We then hand-corrected all six. On 2026-07-14 an adversarial review found the false claim
STILL PRESENT in the body of three of them - in one case seventeen lines below its own
correction banner. Hand-correcting a belief does not remove it.

Hence this test. A wrong idea that can silently return is not fixed.

THE RULE
--------
A line asserting the disproven model must be explicitly marked as false (it may be QUOTED,
in order to correct it - that is what the banners do). An unmarked assertion fails CI.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

SEARCH_DIRS = ("docs", ".claude")

# The disproven claim, in the shapes it has actually appeared in our tree.
FALSE_CLAIMS = (
    re.compile(
        r"rewrites?\s+(the\s+)?on-disk[^.\n]{0,40}from\s+(that|the)\s+mirror", re.I
    ),
    re.compile(r"rewrites?\s+`?userdata/[\w.]+`?\s+from\s+(that|the)\s+mirror", re.I),
    re.compile(r"rewrites?\s+the\s+on-disk\s+`?userdata`?\s+files", re.I),
    re.compile(
        r"re-?materiali[sz]e[sd]?\s+the\s+disk\s+(file|copy)\s+from\s+the\s+(key|mirror)",
        re.I,
    ),
    re.compile(
        r"kodi\s+(will\s+)?restore[sd]?\s+the\s+(disk|posix)\s+(file|copy)\s+from\s+nsuserdefaults",
        re.I,
    ),
)

# A line is allowed to CONTAIN the claim if it also marks it as false. This is what lets a
# correction quote the thing it is correcting.
DISAVOWED = re.compile(
    r"\bFALSE\b|\bis\s+not\s+true\b|\bWRONG\b|\bdisproven\b|\bmyth\b|\bNOT\b\s+rewrite|"
    r"\bdoes\s+not\s+rewrite\b|\bnever\s+rewrites\b|\bcame\s+from\s+the\s+Kodi\s+Wiki\b",
    re.I,
)


def _md_files():
    out = []
    for d in SEARCH_DIRS:
        out.extend(sorted((ROOT / d).rglob("*.md")))
    return out


def test_the_disproven_tvos_mirror_claim_is_not_asserted_anywhere():
    """No doc may assert that Kodi rewrites userdata from NSUserDefaults.

    It doesn't. Believing it is what made deleting the disk copy look safe, and that
    deleted the owner's menu. Quote it to correct it, never to state it.
    """
    offenders = []
    for path in _md_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, 1):
            if not any(rx.search(line) for rx in FALSE_CLAIMS):
                continue
            # A correction QUOTES the claim, and its disavowal ("is FALSE") may land on a
            # neighbouring line because prose wraps. Judge the surrounding window, not the
            # single line - otherwise the tripwire flags the very corrections it wants.
            window = "\n".join(lines[max(0, i - 3) : i + 2])
            if DISAVOWED.search(window):
                continue
            offenders.append(
                "  %s:%d\n    %s" % (path.relative_to(ROOT), i, line.strip()[:150])
            )
    assert not offenders, (
        "These lines assert the DISPROVEN tvOS storage model - that Kodi rewrites the\n"
        "on-disk userdata files from its NSUserDefaults mirror. It does NOT: a key\n"
        "SHADOWS the disk file and nothing ever copies it back "
        "(PreflightHandler.mm:81-93,\nTVOSFile.cpp:70-122). Believing this is what made "
        "'vector it, then delete the disk\ncopy' look safe, and it destroyed the owner's "
        "menu on 2026-07-14.\n\n" + "\n".join(offenders) + "\n\n"
        "If you are QUOTING the claim in order to correct it, mark it as false on the\n"
        "same line (the word FALSE is enough)."
    )


def test_the_tripwire_actually_detects_the_claim():
    """Guard the guard: prove the regexes still match the sentence that caused the bug.

    If this ever fails, the tripwire has rotted and is protecting nothing.
    """
    historical = [
        "Kodi mirrors its settings into the app's NSUserDefaults (a binary plist) and "
        "rewrites the on-disk userdata files from that mirror on launch.",
        "so Kodi stores userdata/*.xml in the app's NSUserDefaults and rewrites the "
        "on-disk files from that mirror on launch",
        "and **rewrites `userdata/guisettings.xml` from that mirror on launch**",
    ]
    for sentence in historical:
        assert any(rx.search(sentence) for rx in FALSE_CLAIMS), (
            "The tripwire no longer detects the sentence that caused the 2026-07-14 data "
            "loss:\n  %s" % sentence
        )
        assert not DISAVOWED.search(sentence), (
            "This historical sentence is being treated as already-disavowed, so the "
            "tripwire would let it through:\n  %s" % sentence
        )
