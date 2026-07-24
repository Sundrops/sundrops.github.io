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


def fetch_full_authors(api_key: str, citation_id: str) -> str | None:
    """Fetch the complete (untruncated) author list for one article."""
    import requests

    try:
        params = {
            "engine": "google_scholar_author",
            "author_id": USER_ID,
            "view_op": "view_citation",
            "citation_id": citation_id,
            "api_key": api_key,
        }
        resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("error"):
            print(f"    [detail] error for {citation_id}: {payload['error']}")
            return None
        return (payload.get("citation") or {}).get("authors")
    except Exception as e:
        print(f"    [detail] failed for {citation_id}: {e}")
        return None


def fetch_via_serpapi(api_key: str, author_cache: dict | None = None) -> dict | None:
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
        reused = 0
        for p in data["papers"]:
            if p["authors"].rstrip().endswith("...") and p["_citation_id"]:
                cached = author_cache.get(p["title"])
                if cached and not cached.rstrip().endswith("..."):
                    p["authors"] = cached
                    reused += 1
        if reused:
            print(f"  [SerpAPI] Reused {reused} cached author list(s)")

        # Fetch complete author lists only for entries still truncated.
        truncated = [p for p in data["papers"]
                     if p["authors"].rstrip().endswith("...") and p["_citation_id"]]
        if truncated:
            print(f"  [SerpAPI] Fetching full authors for "
                  f"{len(truncated)} truncated article(s)...")
            for p in truncated:
                full = fetch_full_authors(api_key, p["_citation_id"])
                if full:
                    p["authors"] = full

        for p in data["papers"]:
            p.pop("_citation_id", None)

        for p in data["papers"]:
            p["field"] = classify_field(p.get("title", ""))
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
        data["papers"].sort(key=lambda p: (p.get("year") or 0, p.get("citations", 0)), reverse=True)
        return data

    except Exception as e:
        print(f"  [scholarly] failed: {e}")
        return None


def main():
    print("[Scholar Sync] Fetching data...")

    existing = json.loads(DATA_PATH.read_text()) if DATA_PATH.exists() else None

    # Build a title -> complete-author cache from existing data so we skip
    # re-fetching detail pages for papers whose full authors we already have.
    author_cache = {}
    if existing:
        for p in existing.get("papers", []):
            authors = (p.get("authors") or "").rstrip()
            if authors and not authors.endswith("..."):
                author_cache[p.get("title", "")] = authors

    api_key = os.environ.get("SERPAPI_KEY", "").strip()
    data = None

    if api_key:
        data = fetch_via_serpapi(api_key, author_cache)
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
