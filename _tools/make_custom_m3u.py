#!/usr/bin/env python3
"""Filter and relabel groups from a source M3U into a custom M3U."""

import re
from pathlib import Path

GROUP_MAP = {
    "USA ENTERTAINMENT": "US Entertainment",
    "USA NEWS/WEATHER": "US News/Weather",
    "PPV EVENTS": "PPV Events",
}

ORDER = ["USA ENTERTAINMENT", "USA NEWS/WEATHER", "PPV EVENTS"]

SORT_ALPHA = {"USA ENTERTAINMENT", "USA NEWS/WEATHER"}

# Words that must stay ALL CAPS
ABBREVS = {
    "A&E",
    "ABC",
    "AM",
    "AMC",
    "CBS",
    "AMG",
    "AWE",
    "AXS",
    "BBC",
    "BET",
    "CMT",
    "CNBC",
    "CNN",
    "CW",
    "DIY",
    "E",
    "ENG",
    "ET",
    "FE",
    "FOX",
    "FX",
    "FXM",
    "FXX",
    "FYI",
    "GAC",
    "GEO",
    "HGTV",
    "HLN",
    "HSN",
    "IFC",
    "INSP",
    "ION",
    "KLCS",
    "MMA",
    "MSNBC",
    "MSNOW",
    "MTV",
    "NAT",
    "NASA",
    "NBC",
    "NECN",
    "OWN",
    "PBS",
    "PM",
    "PPV",
    "QVC",
    "RFD",
    "RSBN",
    "RT",
    "RWS",
    "SYFY",
    "TBD",
    "TBS",
    "TCM",
    "TLC",
    "TMZ",
    "TNT",
    "TV",
    "UFC",
    "UP",
    "USA",
    "VH1",
    "VS",
    "WGN",
    "WPWR",
    "WWE",
    "WWOR",
}

# Small words that stay lowercase (unless they open a segment)
LOWERCASE = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "with",
    "from",
    "by",
    "of",
}

SEPARATORS = {"|", "-", "–"}


def _title_token(token, is_first):
    """Return token in the correct case."""
    if not token:
        return token

    core = re.sub(r"^[()\s*]+|[()\s*!]+$", "", token)

    # Tokens containing digits stay as-is (times, codes, channel numbers)
    if re.search(r"\d", core):
        return token

    # Separator tokens stay as-is
    if core in SEPARATORS:
        return token

    # Check abbreviation (strip non-alpha/ampersand for the lookup)
    alpha = re.sub(r"[^A-Za-z&]", "", core).upper()
    if alpha in ABBREVS:
        return token  # already uppercase

    # Lowercase filler words (not at segment start)
    if not is_first and core.lower() in LOWERCASE:
        return token.lower()

    # Default: title-case (capitalise first alpha char, lowercase the rest)
    result = []
    capped = False
    for ch in token:
        if ch.isalpha() and not capped:
            result.append(ch.upper())
            capped = True
        elif capped:
            result.append(ch.lower())
        else:
            result.append(ch)
    return "".join(result)


def to_title(name):
    """Convert an ALL CAPS channel name to Title Case, preserving abbreviations."""
    tokens = name.split(" ")
    result = []
    after_sep = True  # treat start as segment-opening position
    for tok in tokens:
        core = re.sub(r"^[()\s*]+|[()\s*!]+$", "", tok)
        is_sep = core in SEPARATORS
        result.append(_title_token(tok, after_sep))
        after_sep = is_sep or not tok.strip()
    return " ".join(result)


def parse_m3u(path):
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    channels = []
    i = 1  # skip #EXTM3U header
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            url = lines[i + 1].strip() if i + 1 < len(lines) else ""
            channels.append((line, url))
            i += 2
        else:
            i += 1
    return channels


def get_group(extinf):
    m = re.search(r'group-title="([^"]*)"', extinf)
    return m.group(1) if m else ""


def sort_key(extinf):
    m = re.search(r'tvg-name="([^"]*)"', extinf)
    name = m.group(1) if m else ""
    return re.sub(r"^[^|]*\|\s*", "", name).strip()


def process(extinf, new_group):
    # Strip "USA | " prefix
    extinf = re.sub(r'tvg-name="USA \| ', 'tvg-name="', extinf)
    extinf = re.sub(r",USA \| ", ",", extinf)

    # Relabel group
    extinf = re.sub(r'group-title="[^"]*"', f'group-title="{new_group}"', extinf)

    # Title-case tvg-name
    extinf = re.sub(
        r'tvg-name="([^"]*)"',
        lambda m: f'tvg-name="{to_title(m.group(1))}"',
        extinf,
    )

    # Title-case display name (text after the final attribute closing quote + comma)
    last_quote = extinf.rfind('"')
    comma = extinf.index(",", last_quote)
    display = to_title(extinf[comma + 1 :])
    extinf = extinf[: comma + 1] + display

    return extinf


def main():
    src = Path(__file__).parent.parent / "network24_plus.m3u"
    out = Path(__file__).parent.parent / "network24_custom.m3u"

    channels = parse_m3u(src)

    buckets = {g: [] for g in ORDER}
    for extinf, url in channels:
        g = get_group(extinf)
        if g in buckets:
            buckets[g].append((extinf, url))

    with out.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for source_group in ORDER:
            new_group = GROUP_MAP[source_group]
            entries = buckets[source_group]
            if source_group in SORT_ALPHA:
                entries = sorted(entries, key=lambda e: sort_key(e[0]))
            count = len(entries)
            f.write("#\n")
            f.write("# ============================================================\n")
            f.write(f"#  {new_group.upper()}  ({count} channels)\n")
            f.write("# ============================================================\n")
            f.write("#\n")
            for extinf, url in entries:
                f.write(process(extinf, new_group) + "\n")
                f.write(url + "\n")

    total = sum(len(v) for v in buckets.values())
    print(f"Written {total} channels to {out}")
    for g in ORDER:
        print(f"  {GROUP_MAP[g]}: {len(buckets[g])} channels")


if __name__ == "__main__":
    main()
