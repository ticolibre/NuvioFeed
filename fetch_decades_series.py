#!/usr/bin/env python3
"""
Top-voted + best-rated series per decade (Nuvio / Stremio format).

  catalog/series/top-2020s-series.json  (2020-01-01 .. 2029-12-31)
  catalog/series/top-2010s-series.json  (2010-01-01 .. 2019-12-31)
  catalog/series/top-2000s-series.json  (2000-01-01 .. 2009-12-31)
  catalog/series/top-1990s-series.json  (1990-01-01 .. 1999-12-31)
  catalog/series/top-1980s-series.json  (1980-01-01 .. 1989-12-31)
  meta/series/<id>.json (only missing ones)
  manifest.json (adds the 5 catalogs, keeps the rest)

Same approach as fetch_decades.py (movies):
  discover sorted by vote_average.desc with a per-decade vote_count floor
  (older TV has fewer TMDB votes, so the floor is tiered to still fill 100),
  then local re-rank by weighted score = vote_avg * log10(vote_count+1).

Usage:
  TMDB_API_KEY=... python3 fetch_decades_series.py
"""

import json
import math
import os
import sys
import time
from pathlib import Path

import requests

API_KEY = os.environ.get("TMDB_API_KEY", "d548ef218d01483535878c27644b4ea9")
BASE = "https://api.themoviedb.org/3"
LANGUAGE = "es-MX"
REGION = "CR"
HERE = Path(__file__).parent

DECADES = {
    "top-2020s-series": {"label": "Top 2020s Series", "gte": "2020-01-01", "lte": "2029-12-31", "min_votes": 1000},
    "top-2010s-series": {"label": "Top 2010s Series", "gte": "2010-01-01", "lte": "2019-12-31", "min_votes": 1000},
    "top-2000s-series": {"label": "Top 2000s Series", "gte": "2000-01-01", "lte": "2009-12-31", "min_votes": 500},
    "top-1990s-series": {"label": "Top 90s Series", "gte": "1990-01-01", "lte": "1999-12-31", "min_votes": 200},
    "top-1980s-series": {"label": "Top 80s Series", "gte": "1980-01-01", "lte": "1989-12-31", "min_votes": 100},
}

LIMIT = 100
PAGES_NEEDED = 8  # over-fetch (vote_average sort), then re-rank by weighted score

POSTER = "https://image.tmdb.org/t/p/w500"
BACKDROP = "https://image.tmdb.org/t/p/w1280"
DELAY = 0.05
_session = requests.Session()


def tmdb(path, **params):
    params.setdefault("api_key", API_KEY)
    r = _session.get(f"{BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    time.sleep(DELAY)
    return r.json()


def discover_decade(gte, lte, min_votes):
    out = []
    for page in range(1, PAGES_NEEDED + 1):
        data = tmdb(
            "/discover/tv",
            **{
                "first_air_date.gte": gte,
                "first_air_date.lte": lte,
                "language": LANGUAGE,
                "sort_by": "vote_average.desc",
                "vote_count.gte": min_votes,
                "include_adult": "false",
                "page": page,
            },
        )
        results = data.get("results", [])
        if not results:
            break
        out.extend(results)
        print(f"    page {page} -> {len(results)} items (total {data.get('total_results')})")
        if page >= min(int(data.get("total_pages", 1)), PAGES_NEEDED):
            break
    seen = {}
    for m in out:
        if m.get("id") and m.get("id") not in seen:
            seen[m["id"]] = m
    ranked = sorted(
        seen.values(),
        key=lambda m: (float(m.get("vote_average") or 0) * math.log10(int(m.get("vote_count") or 0) + 1)),
        reverse=True,
    )
    return ranked[:LIMIT]


def enrich(show):
    mid = show.get("id")
    try:
        d = tmdb(f"/tv/{mid}", language=LANGUAGE, append_to_response="external_ids")
    except Exception as e:
        print(f"    warn details {mid}: {e}")
        d = {}
    overview = d.get("overview") or show.get("overview") or ""
    if not overview:
        try:
            en = tmdb(f"/tv/{mid}", language="en-US")
            overview = en.get("overview") or ""
        except Exception:
            pass
    imdb_id = (d.get("external_ids") or {}).get("imdb_id")
    genres = [g["name"] for g in (d.get("genres") or []) if g.get("name")]
    title = d.get("name") or show.get("name") or show.get("original_name") or ""
    release = d.get("first_air_date") or show.get("first_air_date") or ""
    year = release[:4] if release else ""
    poster_path = d.get("poster_path") or show.get("poster_path")
    backdrop_path = d.get("backdrop_path") or show.get("backdrop_path")
    meta_id = imdb_id if imdb_id else f"tmdb:{mid}"
    meta = {
        "id": meta_id,
        "type": "series",
        "name": title,
        "poster": f"{POSTER}{poster_path}" if poster_path else None,
        "posterShape": "poster",
        "background": f"{BACKDROP}{backdrop_path}" if backdrop_path else None,
        "description": overview or "",
        "releaseInfo": year,
        "genres": genres,
    }
    vote = d.get("vote_average", show.get("vote_average"))
    if vote:
        meta["app_extras"] = {"ratings": {"tmdb": {"rating": str(round(float(vote), 1))}}}
    return {k: v for k, v in meta.items() if v is not None}


def main():
    if not API_KEY:
        print("Missing TMDB API key", file=sys.stderr)
        sys.exit(1)
    catalogs = {}
    for key, cfg in DECADES.items():
        print(f"[{cfg['label']}] discover {cfg['gte']}..{cfg['lte']} (votes>={cfg['min_votes']}) ...")
        raw = discover_decade(cfg["gte"], cfg["lte"], cfg["min_votes"])
        print(f"[{cfg['label']}] {len(raw)} ranked, enriching ...")
        metas = [enrich(m) for m in raw]
        out_path = HERE / "catalog" / "series" / f"{key}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {"metas": metas, "cacheMaxAge": 86400, "staleRevalidate": 3600, "staleError": 86400},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        print(f"  wrote {out_path} ({len(metas)} metas)")
        catalogs[key] = (cfg, metas)

    meta_dir = HERE / "meta" / "series"
    meta_dir.mkdir(parents=True, exist_ok=True)
    new = 0
    for key, (cfg, metas) in catalogs.items():
        for meta in metas:
            safe = meta["id"].replace(":", "_")
            p = meta_dir / f"{safe}.json"
            if not p.exists():
                p.write_text(json.dumps({"meta": meta}, ensure_ascii=False, indent=2), encoding="utf-8")
                new += 1
    print(f"  wrote {new} new meta files")

    mp = HERE / "manifest.json"
    manifest = json.loads(mp.read_text(encoding="utf-8"))
    have = {c["id"] for c in manifest.get("catalogs", [])}
    for key, (cfg, metas) in catalogs.items():
        if key not in have:
            manifest["catalogs"].append(
                {"type": "series", "id": key, "name": cfg["label"],
                 "extra": [{"name": "skip", "isRequired": False}]}
            )
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  updated manifest.json")
    print("Done.")


if __name__ == "__main__":
    main()
