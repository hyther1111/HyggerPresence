"""Hygger Presence 1.0.4 - VNDB API."""
import re

import requests


COVER_PATTERN = re.compile(r"https://t\.vndb\.org/cv/[A-Za-z0-9_/]+\.jpg")


def parse_cover_urls(html):
    """All cover image URLs on a VNDB /v<id>/cv page, de-duplicated, order kept."""
    seen, urls = set(), []
    for url in COVER_PATTERN.findall(html or ""):
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def cover_urls(vndb_id, timeout=12):
    """Covers of a VN by scraping its cover page (the API only exposes one)."""
    response = requests.get("https://vndb.org/%s/cv" % vndb_id, timeout=timeout,
                            headers={"User-Agent": "HyggerPresence/2.0"})
    response.raise_for_status()
    return parse_cover_urls(response.text)


def parse_vndb_id(url_or_id):
    m = re.search(r"(?:vndb\.org/)?(v\d+)", str(url_or_id).strip(), re.I)
    return m.group(1).lower() if m else None


def fetch_vndb(vndb_id):
    try:
        payload = {
            "filters": ["id", "=", vndb_id],
            "fields": (
                "title,alttitle,titles.title,titles.lang,image.url,"
                "released,developers.name,rating"
            ),
        }
        r = requests.post(
            "https://api.vndb.org/kana/vn",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("results"):
            return None
        vn = data["results"][0]

        original = None
        for t in vn.get("titles", []):
            if t.get("lang") == "ja":
                original = t.get("title")
                break
        main_title = original or vn.get("alttitle") or vn.get("title") or vndb_id
        romanized = vn.get("title") or vn.get("alttitle") or main_title

        developers = vn.get("developers") or []
        developer = " & ".join(d["name"] for d in developers) if developers else "Unknown"

        released = vn.get("released") or ""
        year = released[:4] if len(released) >= 4 else "????"

        rating = vn.get("rating")
        # The v2 API hands out a plain number on VNDB's 0-100 scale (87.5 is
        # the 8.75 the site shows). Older payloads nested a dict; both shapes
        # are accepted and both end up on the 0-10 scale the templates use.
        if isinstance(rating, dict):
            rating_average = rating.get("average") or rating.get("rating")
            rating_weighted = rating.get("bayesian") or rating.get("weighted")
        else:
            rating_average = rating
            # v2 has no Bayesian rating of its own, so leave the stored one be
            rating_weighted = None

        def _fmt_rating(v):
            if v is None or v == "N/A":
                return "N/A"
            try:
                value = float(v)
            except Exception:
                return str(v)
            if value > 10:            # 0-100 scale -> 0-10
                value /= 10.0
            return f"{value:.2f}"

        return {
            "id": vndb_id,
            "title": main_title,
            "original": main_title,
            "romanized": romanized,
            "image": (vn.get("image") or {}).get("url"),
            "developer": developer,
            "year": year,
            "rating_average": _fmt_rating(rating_average),
            "rating_weighted": _fmt_rating(rating_weighted),
        }
    except Exception as e:
        print("VNDB error:", e)
        return None
