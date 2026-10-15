#!/usr/bin/env python3
"""
Top-voted + best-rated movies per decade (Nuvio / Stremio format).

  catalog/movie/top-2020s.json  (2020-01-01 .. 2029-12-31)
  catalog/movie/top-2010s.json  (2010-01-01 .. 2019-12-31)
  catalog/movie/top-2000s.json  (2000-01-01 .. 2009-12-31)
  meta/movie/<id>.json (only missing ones)
  manifest.json (adds the 3 catalogs, keeps the rest)

Ranking = combination of votes + rating:
  discover sorted by vote_average.desc with vote_count.gte=MIN_VOTES,
  then local re-rank by weighted score = vote_avg * log10(vote_count+1),
  top 200 kept in that order.

Usage:
  TMDB_API_KEY=... python3 fetch_decades.py
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
    "top-2020s": {"label": "Top 2020s: Most Voted", "gte": "2020-01-01", "lte": "2029-12-31"},
    "top-2010s": {"label": "Top 2010s: Most Voted", "gte": "2010-01-01", "lte": "2019-12-31"},
    "top-2000s": {"label": "Top 2000s: Most Voted", "gte": "2000-01-01", "lte": "2009-12-31"},
    "top-1990s": {"label": "Top 90s: Most Voted", "gte": "1990-01-01", "lte": "1999-12-31"},
    "top-1980s": {"label": "Top 80s: Most Voted", "gte": "1980-01-01", "lte": "1989-12-31"},
}

LIMIT = 200
MIN_VOTES = 1000
PAGES_NEEDED = 15  # over-fetch (vote_average sort), then re-rank by weighted score

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


def discover_decade(gte, lte):
    out = []
    for page in range(1, PAGES_NEEDED + 1):
        data = tmdb(
            "/discover/movie",
            **{
                "primary_release_date.gte": gte,
                "primary_release_date.lte": lte,
                "language": LANGUAGE,
                "region": REGION,
                "sort_by": "vote_average.desc",
                "vote_count.gte": MIN_VOTES,
                "include_adult": "false",
                "include_video": "false",
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
    # de-dupe, re-rank by weighted score (rating * log popularity of votes)
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


def enrich(movie):
    mid = movie.get("id")
    try:
        d = tmdb(f"/movie/{mid}", language=LANGUAGE, append_to_response="external_ids")
    except Exception as e:
        print(f"    warn details {mid}: {e}")
        d = {}
    overview = d.get("overview") or movie.get("overview") or ""
    if not overview:
        try:
            en = tmdb(f"/movie/{mid}", language="en-US")
            overview = en.get("overview") or ""
        except Exception:
            pass
    imdb_id = (d.get("external_ids") or {}).get("imdb_id")
    genres = [g["name"] for g in (d.get("genres") or []) if g.get("name")]
    title = d.get("title") or movie.get("title") or movie.get("original_title") or ""
    release = d.get("release_date") or movie.get("release_date") or ""
    year = release[:4] if release else ""
    poster_path = d.get("poster_path") or movie.get("poster_path")
    backdrop_path = d.get("backdrop_path") or movie.get("backdrop_path")
    meta_id = imdb_id if imdb_id else f"tmdb:{mid}"
    meta = {
        "id": meta_id,
        "type": "movie",
        "name": title,
        "poster": f"{POSTER}{poster_path}" if poster_path else None,
        "posterShape": "poster",
        "background": f"{BACKDROP}{backdrop_path}" if backdrop_path else None,
        "description": overview or "",
        "releaseInfo": year,
        "genres": genres,
    }
    vote = d.get("vote_average", movie.get("vote_average"))
    if vote:
        meta["app_extras"] = {"ratings": {"tmdb": {"rating": str(round(float(vote), 1))}}}
    return {k: v for k, v in meta.items() if v is not None}


def main():
    if not API_KEY:
        print("Missing TMDB API key", file=sys.stderr)
        sys.exit(1)
    catalogs = {}
    for key, cfg in DECADES.items():
        print(f"[{cfg['label']}] discover {cfg['gte']}..{cfg['lte']} ...")
        raw = discover_decade(cfg["gte"], cfg["lte"])
        print(f"[{cfg['label']}] {len(raw)} ranked, enriching ...")
        metas = [enrich(m) for m in raw]
        out_path = HERE / "catalog" / "movie" / f"{key}.json"
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

    meta_dir = HERE / "meta" / "movie"
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
                {"type": "movie", "id": key, "name": cfg["label"],
                 "extra": [{"name": "skip", "isRequired": False}]}
            )
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  updated manifest.json")
    print("Done.")


if __name__ == "__main__":
    main()
