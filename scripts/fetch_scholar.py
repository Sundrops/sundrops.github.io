#!/usr/bin/env python3
"""
Fetch Google Scholar data.

Source priority:
  1. SerpAPI (reliable, works from GitHub Actions IPs) -- requires SERPAPI_KEY.
  2. scholarly library (free, but often blocked from CI IPs) -- fallback.
Falls back to the existing data.json if every method fails, so the page
never breaks.

Run daily via GitHub Actions.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data.json"
USER_ID = "oqN1dA8AAAAJ"
SERPAPI_ENDPOINT = "https://serpapi.com/search"

# Research field taxonomy. Papers are classified into one of these buckets.
FIELDS = ["VLA", "Robot Learning", "World Model", "Vision"]

# Explicit title-keyword -> field overrides (checked first, in order).
# Keys are lowercase substrings matched against the paper title.
FIELD_OVERRIDES = [
    ("agibot world", "Robot Learning"),
    ("grpo-ma", "Robot Learning"),
    ("univla", "VLA"),
]

# Keyword heuristics per field (checked in order; first match wins).
FIELD_KEYWORDS = [
    ("VLA", ["vla", "vision-language-action", "vision-text-action",
             "vlm reasoning", "system-2 thinking"]),
    ("World Model", ["world model", "world simulator", "world foundation",
                     "enerverse", "genie envisioner", "world models",
                     "envisioning"]),
    ("Robot Learning", ["robot", "manipulation", "imitation", "policy",
                        "demonstration", "goal-conditioned", "agentic",
                        "generalization", "data composition", "data collection"]),
    ("Vision", ["segmentation", "parsing", "scene graph", "detection",
                "face recognition", "relation detection", "surveillance",
                "distillation", "tracklet"]),
]


def classify_field(title: str) -> str:
    """Assign a research field to a paper based on its title."""
    t = (title or "").lower()
    for key, field in FIELD_OVERRIDES:
        if key in t:
            return field
    for field, keywords in FIELD_KEYWORDS:
        if any(k in t for k in keywords):
            return field
    return "Robot Learning"  # default for recent embodied-AI work


# ---------------------------------------------------------------------------
# Manual per-paper resource links (project page / GitHub / HuggingFace / PDF).
#
# HOW TO ADD A LINK:
#   1. Pick a short, unique lowercase substring of the paper title as the key.
#   2. Add a list of {"type", "url"} entries. `type` controls the icon/label:
#      "code" (GitHub), "hf" (HuggingFace), "page" (project site),
#      "pdf" / "arxiv" (paper), or any custom label string.
#
# These are merged into data.json on every run and survive re-fetches, so you
# only edit this one place.
# ---------------------------------------------------------------------------
PAPER_LINKS = {
    "acot-vla": [
        {"type": "code", "url": "https://github.com/AgibotTech/ACoT-VLA"},
    ],
    "roboclaw": [
        {"type": "page", "url": "https://roboclaw-agibot.github.io/"},
        {"type": "code", "url": "https://github.com/RoboClaw-Robotics/RoboClaw"},
    ],
    "libra-vla": [
        {"type": "page", "url": "https://libra-vla.github.io/"},
    ],
    "ge-sim": [
        {"type": "page", "url": "https://ge-sim-v2.github.io/"},
        {"type": "code", "url": "https://github.com/AgibotTech/GE-Sim-V2"},
        {"type": "hf", "url": "https://huggingface.co/agibot-world/Genie-Envisioner-Sim-v2.0"},
    ],
    "agibot world colosseo": [
        {"type": "page", "url": "https://agibot-world.com"},
        {"type": "code", "url": "https://github.com/OpenDriveLab/AgiBot-World"},
        {"type": "hf", "url": "https://huggingface.co/agibot-world"},
    ],
    "univla": [
        {"type": "code", "url": "https://github.com/OpenDriveLab/UniVLA"},
        {"type": "hf", "url": "https://huggingface.co/qwbu/univla-7b"},
    ],
    "genie envisioner": [
        {"type": "page", "url": "https://genie-envisioner.github.io/"},
        {"type": "code", "url": "https://github.com/AgibotTech/Genie-Envisioner"},
        {"type": "hf", "url": "https://huggingface.co/agibot-world/Genie-Envisioner"},
    ],
    "hume": [
        {"type": "page", "url": "https://hume-vla.github.io/"},
        {"type": "code", "url": "https://github.com/hume-vla/hume"},
        {"type": "hf", "url": "https://huggingface.co/Hume-vla/Hume-System2"},
    ],
    # NOTE: keep "enerverse-ac" BEFORE "enerverse" — get_links() returns the
    # first substring match, and "enerverse" is contained in "enerverse-ac".
    "enerverse-ac": [
        {"type": "page", "url": "https://annaj2178.github.io/EnerverseAC.github.io"},
        {"type": "code", "url": "https://github.com/AgibotTech/EnerVerse-AC"},
        {"type": "hf", "url": "https://huggingface.co/agibot-world/EnerVerse-AC"},
    ],
    "enerverse:": [
        {"type": "page", "url": "https://sites.google.com/view/enerverse"},
    ],
    "eo-1": [
        {"type": "page", "url": "https://eo-robotics.ai/eo-1"},
        {"type": "code", "url": "https://github.com/EO-Robotics/EO1"},
        {"type": "hf", "url": "https://huggingface.co/IPEC-COMMUNITY/EO-1-3B"},
    ],
    "ewmbench": [
        {"type": "code", "url": "https://github.com/AgibotTech/EWMBench"},
        {"type": "hf", "url": "https://huggingface.co/agibot-world/EWMBench-model"},
    ],
    "is diversity all you need": [
        {"type": "code", "url": "https://github.com/OpenDriveLab/AgiBot-World"},
    ],
    "grpo-ma": [
        {"type": "code", "url": "https://github.com/whcpumpkin/GRPO-MA"},
    ],
    "genie centurion": [
        {"type": "page", "url": "https://genie-centurion.github.io/"},
    ],
    "adversarial data collection": [
        {"type": "page", "url": "https://sites.google.com/view/adc-robot"},
    ],
    "act2goal": [
        {"type": "page", "url": "https://act2goal.github.io/"},
    ],
    "real2edit2real": [
        {"type": "page", "url": "https://real2edit2real.github.io/"},
        {"type": "code", "url": "https://github.com/Real2Edit2Real/Real2Edit2Real"},
    ],
    "unified embodied vlm": [
        {"type": "page", "url": "https://geniereasoner.github.io/GenieReasoner/"},
    ],
    "imagine2act": [
        {"type": "page", "url": "https://sites.google.com/view/imagine2act"},
        {"type": "code", "url": "https://github.com/LiangHeng121/Imagine2Act"},
    ],
}


def get_links(title: str) -> list:
    """Return manually-curated resource links for a paper title."""
    t = (title or "").lower()
    for key, links in PAPER_LINKS.items():
        if key in t:
            return links
    return []


def _new_data() -> dict:
    return {
        "stats": {"total_citations": 0, "h_index": 0, "i10_index": 0},
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "user_id": USER_ID,
        "papers": [],
    }


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def fetch_full_authors(api_key: str, citation_id: str) -> tuple[str | None, str | None]:
    """Fetch (complete author list, venue) for one article from its detail page.

    The detail page's `journal` field reflects manual Scholar edits (e.g. an
    arXiv preprint later published at a conference) sooner than the list view,
    so we use it to refresh the venue too.
    """
    import requests

    try:
        params = {
            "engine": "google_scholar_author",
            "author_id": USER_ID,
            "view_op": "view_citation",
            "citation_id": citation_id,
            "api_key": api_key,
        }
        resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("error"):
            print(f"    [detail] error for {citation_id}: {payload['error']}")
            return None, None
        citation = payload.get("citation") or {}
        return citation.get("authors"), citation.get("journal")
    except Exception as e:
        print(f"    [detail] failed for {citation_id}: {e}")
        return None, None


def fetch_via_serpapi(api_key: str, author_cache: dict | None = None,
                      full_refresh: bool = False) -> dict | None:
    """Fetch author profile + all articles through SerpAPI (paginated).

    author_cache maps a paper title -> a previously fetched complete author
    string (no trailing "..."). Cached titles skip the per-article detail
    request, saving SerpAPI quota.
    """
    import requests

    author_cache = author_cache or {}
    print("  [SerpAPI] Fetching author profile...")
    data = _new_data()
    start = 0
    page_size = 100  # SerpAPI max num for scholar author articles

    try:
        while True:
            params = {
                "engine": "google_scholar_author",
                "author_id": USER_ID,
                "api_key": api_key,
                "num": page_size,
                "start": start,
                "sort": "cited_by",
            }
            resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=60)
            resp.raise_for_status()
            payload = resp.json()

            if payload.get("error"):
                print(f"  [SerpAPI] API error: {payload['error']}")
                return None

            # cited_by.table is stable across pages; read it once.
            if start == 0:
                table = (payload.get("cited_by") or {}).get("table", [])
                metrics = {}
                for row in table:
                    for key, val in row.items():
                        metrics[key] = val
                data["stats"] = {
                    "total_citations": _to_int(
                        (metrics.get("citations") or {}).get("all")
                    ),
                    "h_index": _to_int((metrics.get("h_index") or {}).get("all")),
                    "i10_index": _to_int(
                        (metrics.get("i10_index") or {}).get("all")
                    ),
                }

            articles = payload.get("articles") or []
            for art in articles:
                data["papers"].append({
                    "title": art.get("title", ""),
                    "authors": art.get("authors", ""),
                    "venue": art.get("publication", ""),
                    "citations": _to_int((art.get("cited_by") or {}).get("value")),
                    "year": _to_int(art.get("year")) or None,
                    "url": art.get("link", ""),
                    "_citation_id": art.get("citation_id", ""),
                })

            # Stop when a page returns fewer than requested (last page).
            if len(articles) < page_size:
                break
            start += page_size

        # Reuse previously fetched complete author lists (cache) so we don't
        # re-hit the detail endpoint for papers we already resolved.
        if not full_refresh:
            reused = 0
            for p in data["papers"]:
                if p["authors"].rstrip().endswith("...") and p["_citation_id"]:
                    cached = author_cache.get(p["title"])
                    if cached and not cached.rstrip().endswith("..."):
                        p["authors"] = cached
                        reused += 1
            if reused:
                print(f"  [SerpAPI] Reused {reused} cached author list(s)")

        # Which papers need a detail request:
        #  - full refresh: every paper (re-pull authors/venue after edits)
        #  - normal:       only those still truncated ("...")
        if full_refresh:
            to_fetch = [p for p in data["papers"] if p["_citation_id"]]
        else:
            to_fetch = [p for p in data["papers"]
                        if p["authors"].rstrip().endswith("...") and p["_citation_id"]]
        if to_fetch:
            print(f"  [SerpAPI] Fetching detail pages for "
                  f"{len(to_fetch)} article(s)...")
            consecutive_fail = 0
            for p in to_fetch:
                full_authors, journal = fetch_full_authors(api_key, p["_citation_id"])
                if full_authors:
                    p["authors"] = full_authors
                    # On a full refresh, trust the detail page's venue since it
                    # picks up manual Scholar edits before the list view does.
                    if full_refresh and journal:
                        p["venue"] = journal
                    consecutive_fail = 0
                else:
                    consecutive_fail += 1
                    # Bail out early if the detail endpoint keeps failing
                    # (e.g. invalid key / quota exhausted) instead of spinning
                    # through every remaining article.
                    if consecutive_fail >= 3:
                        print("    [detail] 3 consecutive failures; "
                              "skipping remaining detail fetches")
                        break

        for p in data["papers"]:
            p.pop("_citation_id", None)

        for p in data["papers"]:
            p["field"] = classify_field(p.get("title", ""))
            p["links"] = get_links(p.get("title", ""))
        data["papers"].sort(key=lambda p: (p.get("year") or 0, p.get("citations", 0)), reverse=True)
        print(f"  [SerpAPI] Got {len(data['papers'])} articles, "
              f"{data['stats']['total_citations']} citations")
        return data

    except Exception as e:
        print(f"  [SerpAPI] failed: {e}")
        return None


def fetch_via_scholarly() -> dict | None:
    """Use scholarly library with optional free proxy rotation (fallback)."""
    try:
        from scholarly import scholarly, ProxyGenerator

        print("  [scholarly] Initializing...")
        try:
            pg = ProxyGenerator()
            if pg.FreeProxies():
                scholarly.use_proxy(pg)
                print("  [scholarly] Using free proxy rotation")
            else:
                print("  [scholarly] No proxies, using direct connection")
        except Exception as proxy_err:
            print(f"  [scholarly] Proxy setup failed ({proxy_err}); direct")

        print(f"  [scholarly] Fetching author {USER_ID}...")
        author = scholarly.search_author_id(USER_ID)
        author = scholarly.fill(author, sections=["basics", "indices", "pubs"])

        data = _new_data()
        data["stats"] = {
            "total_citations": _to_int(author.get("citedby")),
            "h_index": _to_int(author.get("hindex")),
            "i10_index": _to_int(author.get("i10index")),
        }

        for pub in author.get("publications", []):
            bib = pub.get("bib", {})
            data["papers"].append({
                "title": bib.get("title", ""),
                "authors": bib.get("author", ""),
                "venue": bib.get("venue", ""),
                "citations": _to_int(pub.get("num_citations")),
                "year": _to_int(bib.get("pub_year")) or None,
                "url": "",
            })

        for p in data["papers"]:
            p["field"] = classify_field(p.get("title", ""))
            p["links"] = get_links(p.get("title", ""))
        data["papers"].sort(key=lambda p: (p.get("year") or 0, p.get("citations", 0)), reverse=True)
        return data

    except Exception as e:
        print(f"  [scholarly] failed: {e}")
        return None


def main():
    print("[Scholar Sync] Fetching data...")

    # Full refresh: ignore the author cache and re-fetch every detail page.
    # Use for the quarterly deep sync (merged papers, updated authors/venues).
    full_refresh = (
        "--full" in sys.argv
        or os.environ.get("FULL_REFRESH", "").strip().lower() in ("1", "true", "yes")
    )

    existing = json.loads(DATA_PATH.read_text()) if DATA_PATH.exists() else None

    # Build a title -> complete-author cache from existing data so we skip
    # re-fetching detail pages for papers whose full authors we already have.
    author_cache = {}
    if full_refresh:
        print("  FULL_REFRESH: ignoring author cache, re-fetching all details")
    elif existing:
        for p in existing.get("papers", []):
            authors = (p.get("authors") or "").rstrip()
            if authors and not authors.endswith("..."):
                author_cache[p.get("title", "")] = authors

    api_key = os.environ.get("SERPAPI_KEY", "").strip()
    data = None

    if api_key:
        data = fetch_via_serpapi(api_key, author_cache, full_refresh)
    else:
        print("  No SERPAPI_KEY set; skipping SerpAPI.")

    if not data or data["stats"]["total_citations"] <= 0:
        print("  Falling back to scholarly...")
        data = fetch_via_scholarly()

    # Nothing usable at all -> keep existing or fail.
    if not data or data["stats"]["total_citations"] <= 0:
        if existing:
            print(f"  Fetch failed; keeping existing data.json "
                  f"({len(existing.get('papers', []))} papers)")
            return
        print("  ERROR: No data available and no existing data.json")
        sys.exit(1)

    # We have valid stats. If the publication list came back empty but we have
    # an older list, preserve those papers so the page stays populated.
    if not data["papers"] and existing and existing.get("papers"):
        print(f"  Stats updated; publication list empty, "
              f"preserving {len(existing['papers'])} existing papers")
        data["papers"] = existing["papers"]
    else:
        print(f"  Success: {len(data['papers'])} papers")

    DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
