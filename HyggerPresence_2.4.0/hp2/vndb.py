"""Hygger Presence 2.4.0 - VNDB Kana API v2 + user list integration."""
from datetime import date
import re
import time

import requests

API_BASE = "https://api.vndb.org/kana"
USER_AGENT = "HyggerPresence/2.4.0 (+https://github.com/hyther1111/HyggerPresence)"
COVER_PATTERN = re.compile(r"https://t\.vndb\.org/cv/[A-Za-z0-9_/]+\.jpg")
_VOTEGRAPH_RE = re.compile(r'<table class="votegraph".*?<tfoot>(.*?)</tfoot>', re.S)
_POP_RANK_RE = re.compile(r"(\d+)\s+votes?\s*\(rank\s+(\d+)\)", re.I)
_AVG_RANK_RE = re.compile(r"average\s*\([^)]*?rank\s+(\d+)\)", re.I)
_VNDB_HTML_BLOCKED_UNTIL = 0.0
_VNDB_HTML_COOLDOWN = 90.0

VN_FIELDS = (
    "id,title,alttitle,titles.title,titles.lang,image.url,"
    "released,developers.name,average,rating,votecount,"
    "length_minutes,length_votes"
)
ULIST_VN_FIELDS = (
    "id,vote,started,finished,notes,labels.id,labels.label,"
    "releases.id,releases.title,releases.released,releases.list_status,"
    "vn.title,vn.alttitle,vn.titles.title,vn.titles.lang,"
    "vn.image.url,vn.released,vn.developers.name,"
    "vn.average,vn.rating,vn.votecount,vn.length_minutes,vn.length_votes"
)


def _headers(token=None, json_body=False):
    headers = {"User-Agent": USER_AGENT}
    if json_body:
        headers["Content-Type"] = "application/json"
    clean = str(token or "").strip()
    if clean:
        headers["Authorization"] = f"token {clean}"
    return headers


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
    response = requests.get(
        f"https://vndb.org/{vndb_id}/cv",
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return parse_cover_urls(response.text)


def parse_vndb_id(url_or_id):
    m = re.search(r"(?:vndb\.org/)?(v\d+)", str(url_or_id or "").strip(), re.I)
    return m.group(1).lower() if m else None


def _fmt_rating(value):
    if value is None or value == "N/A":
        return "N/A"
    try:
        num = float(value)
    except Exception:
        return str(value)
    if num > 10:
        num /= 10.0
    return f"{num:.2f}"


def _extract_vn_info(vn, vndb_id=None):
    """Normalize a VNDB Kana `/vn` object into Hygger Presence's dict shape."""
    vid = (vn.get("id") or vndb_id or "").lower()
    original = None
    for t in vn.get("titles") or []:
        if t.get("lang") == "ja":
            original = t.get("title")
            break
    main_title = original or vn.get("alttitle") or vn.get("title") or vid
    romanized = vn.get("title") or vn.get("alttitle") or main_title

    developers = vn.get("developers") or []
    developer = " & ".join(d["name"] for d in developers if d.get("name")) or "Unknown"

    released = vn.get("released") or ""
    year = released[:4] if len(released) >= 4 else "????"

    average = vn.get("average")
    bayes = vn.get("rating")
    if isinstance(average, dict) or isinstance(bayes, dict):
        blob = average if isinstance(average, dict) else bayes
        rating_average = blob.get("average") or blob.get("rating")
        rating_weighted = blob.get("bayesian") or blob.get("weighted")
    else:
        rating_average = average if average is not None else bayes
        rating_weighted = bayes if average is not None else None
    if rating_weighted is None:
        rating_weighted = rating_average

    votecount = vn.get("votecount")
    votes_text = str(int(votecount)) if isinstance(votecount, (int, float)) and votecount > 0 else "N/A"
    length_minutes = vn.get("length_minutes")
    length_votes = vn.get("length_votes")

    return {
        "id": vid,
        "title": main_title,
        "original": main_title,
        "romanized": romanized,
        "image": (vn.get("image") or {}).get("url") or "",
        "developer": developer,
        "year": year,
        "rating_average": _fmt_rating(rating_average),
        "rating_weighted": _fmt_rating(rating_weighted),
        "vndb_votes": votes_text,
        "length_minutes": int(length_minutes) if isinstance(length_minutes, (int, float)) and length_minutes > 0 else 0,
        "length_votes": int(length_votes) if isinstance(length_votes, (int, float)) and length_votes > 0 else 0,
    }


def fetch_vndb_ranks(vndb_id, timeout=5, session=None, skip_if_blocked=True):
    """Fetch VNDB rating rank and popularity rank from the VN's page votegraph."""
    global _VNDB_HTML_BLOCKED_UNTIL
    result = {"vndb_rank": "N/A", "vndb_popularity": "N/A"}
    vid = parse_vndb_id(vndb_id)
    if not vid:
        return result
    if skip_if_blocked and time.monotonic() < _VNDB_HTML_BLOCKED_UNTIL:
        return result
    http = session or requests
    try:
        r = http.get(
            f"https://vndb.org/{vid}",
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )
        if r.status_code in (403, 429, 503):
            _VNDB_HTML_BLOCKED_UNTIL = time.monotonic() + _VNDB_HTML_COOLDOWN
            return result
        r.raise_for_status()
        _VNDB_HTML_BLOCKED_UNTIL = 0.0
        match = _VOTEGRAPH_RE.search(r.text or "")
        if not match:
            return result
        tfoot = match.group(1)
        pop = _POP_RANK_RE.search(tfoot)
        if pop:
            result["vndb_popularity"] = f"#{pop.group(2)}"
            result["vndb_votes"] = pop.group(1)
        avg = _AVG_RANK_RE.search(tfoot)
        if avg:
            result["vndb_rank"] = f"#{avg.group(1)}"
    except Exception:
        pass
    return result


def fetch_vndb_batch(vndb_ids, token=None, timeout=15, session=None):
    """Fetch metadata for many VNDB IDs in bulk chunks of up to 50."""
    clean_ids = []
    seen = set()
    for raw in vndb_ids or ():
        vid = parse_vndb_id(raw)
        if vid and vid not in seen:
            seen.add(vid)
            clean_ids.append(vid)
    out = {}
    if not clean_ids:
        return out
    http = session or requests
    for idx in range(0, len(clean_ids), 50):
        chunk = clean_ids[idx:idx + 50]
        flt = ["id", "=", chunk[0]] if len(chunk) == 1 else ["or"] + [["id", "=", v] for v in chunk]
        try:
            r = http.post(
                f"{API_BASE}/vn",
                json={"filters": flt, "fields": VN_FIELDS, "results": len(chunk)},
                headers=_headers(token, json_body=True),
                timeout=timeout,
            )
            r.raise_for_status()
            for vn in (r.json().get("results") or []):
                info = _extract_vn_info(vn)
                if info.get("id"):
                    out[info["id"]] = info
        except Exception as e:
            print("VNDB batch error:", e)
    return out


def fetch_vndb(vndb_id, token=None, include_ranks=True, session=None, skip_ranks_if_blocked=True):
    vid = parse_vndb_id(vndb_id)
    if not vid:
        return None
    http = session or requests
    try:
        payload = {"filters": ["id", "=", vid], "fields": VN_FIELDS}
        r = http.post(
            f"{API_BASE}/vn",
            json=payload,
            headers=_headers(token, json_body=True),
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("results"):
            return None
        info = _extract_vn_info(data["results"][0], vid)
        if include_ranks:
            ranks = fetch_vndb_ranks(
                vid, session=http, skip_if_blocked=skip_ranks_if_blocked
            )
            info["vndb_rank"] = ranks.get("vndb_rank", "N/A")
            info["vndb_popularity"] = ranks.get("vndb_popularity", "N/A")
            if ranks.get("vndb_votes"):
                info["vndb_votes"] = ranks["vndb_votes"]
        return info
    except Exception as e:
        print("VNDB error:", e)
        return None


def search_vndb(query, token=None, limit=15, timeout=12):
    """Search VNDB by title (or direct ID/URL) and return normalized VN dicts."""
    text = str(query or "").strip()
    if not text:
        return []
    direct = parse_vndb_id(text)
    if direct and text.lower() in (direct, f"https://vndb.org/{direct}", f"http://vndb.org/{direct}"):
        one = fetch_vndb(direct, token=token, include_ranks=False)
        return [one] if one else []
    try:
        payload = {
            "filters": ["search", "=", text],
            "fields": VN_FIELDS,
            "sort": "searchrank",
            "results": max(1, min(25, int(limit))),
        }
        r = requests.post(
            f"{API_BASE}/vn",
            json=payload,
            headers=_headers(token, json_body=True),
            timeout=timeout,
        )
        r.raise_for_status()
        results = r.json().get("results") or []
        return [_extract_vn_info(vn) for vn in results]
    except Exception as e:
        print("VNDB search error:", e)
        return []


_AUTH_CACHE = {}
_LABELS_CACHE = {}
_READONLY_LABELS = {"no label", "voted", "blacklisted"}


def _is_assignable_label(lb):
    lid = lb.get("id")
    name = str(lb.get("label") or "").strip().lower()
    if lid is None or int(lid) <= 0:
        return False
    if name in _READONLY_LABELS:
        return False
    return True


def verify_token(token, timeout=10, use_cache=False):
    """Validate a VNDB API token via GET /kana/authinfo."""
    clean = str(token or "").strip()
    if not clean:
        return {"ok": False, "error": "Token is empty."}
    if use_cache and clean in _AUTH_CACHE:
        return dict(_AUTH_CACHE[clean])
    try:
        r = requests.get(
            f"{API_BASE}/authinfo",
            headers=_headers(clean),
            timeout=timeout,
        )
        if r.status_code == 401:
            _AUTH_CACHE.pop(clean, None)
            return {"ok": False, "error": "Invalid or revoked VNDB token (401)."}
        r.raise_for_status()
        data = r.json()
        res = {
            "ok": True,
            "id": data.get("id") or "",
            "username": data.get("username") or "",
            "permissions": list(data.get("permissions") or []),
        }
        _AUTH_CACHE[clean] = dict(res)
        return res
    except Exception as e:
        return {"ok": False, "error": str(e)}


def fetch_ulist_labels(user_id="", token="", timeout=10, use_cache=False):
    """Fetch assignable VNDB list labels for the user (excludes Voted / No label)."""
    clean = str(token or "").strip()
    cache_key = (clean, str(user_id or ""))
    if use_cache and cache_key in _LABELS_CACHE:
        return list(_LABELS_CACHE[cache_key])
    params = {"user": user_id} if user_id else {}
    r = requests.get(
        f"{API_BASE}/ulist_labels",
        params=params,
        headers=_headers(clean),
        timeout=timeout,
    )
    r.raise_for_status()
    raw = r.json().get("labels") or []
    filtered = [lb for lb in raw if _is_assignable_label(lb)]
    if clean:
        _LABELS_CACHE[cache_key] = list(filtered)
    return filtered


def _fmt_user_vote(vote):
    if vote is None:
        return ""
    try:
        return f"{float(vote) / 10.0:.1f}"
    except Exception:
        return ""


def fetch_user_list(token, label_ids=None, timeout=15, cancel_event=None):
    """Fetch all visual novels on the authenticated user's VNDB list.

    Returns (entries, auth_info, error_message).
    """
    auth = verify_token(token, timeout=timeout)
    if not auth.get("ok"):
        return [], auth, auth.get("error") or "Invalid VNDB token."
    perms = auth.get("permissions") or []
    if "listread" not in perms:
        return [], auth, "This token does not have 'listread' permission."

    wanted_labels = {int(x) for x in (label_ids or []) if str(x).isdigit()}
    entries = []
    page = 1
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                return entries, auth, "cancelled"
            payload = {
                "user": auth["id"],
                "fields": ULIST_VN_FIELDS,
                "results": 100,
                "page": page,
            }
            if len(wanted_labels) == 1:
                payload["filters"] = ["label", "=", next(iter(wanted_labels))]
            r = requests.post(
                f"{API_BASE}/ulist",
                json=payload,
                headers=_headers(token, json_body=True),
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json()
            for row in data.get("results") or []:
                labels = row.get("labels") or []
                l_ids = [int(lb["id"]) for lb in labels if _is_assignable_label(lb)]
                l_names = [lb["label"] for lb in labels if _is_assignable_label(lb) and lb.get("id") != 7]
                if wanted_labels and not (wanted_labels & set(l_ids)):
                    continue
                vn = dict(row.get("vn") or {})
                vn["id"] = row.get("id")
                info = _extract_vn_info(vn, row.get("id"))
                info["vndb_labels"] = l_names
                info["vndb_label_ids"] = l_ids
                info["vndb_vote"] = _fmt_user_vote(row.get("vote"))
                info["vndb_started"] = row.get("started") or ""
                info["vndb_finished"] = row.get("finished") or ""
                info["vndb_notes"] = row.get("notes") or ""
                entries.append(info)
            if not data.get("more"):
                break
            page += 1
            if page > 50:
                break
        return entries, auth, ""
    except Exception as e:
        return [], auth, str(e)


def fetch_vn_releases(vndb_id, timeout=12, session=None):
    """Fetch all known releases for `vndb_id` from VNDB Kana API."""
    vid = parse_vndb_id(vndb_id)
    if not vid:
        return []
    http = session or requests
    releases = []
    page = 1
    try:
        while page <= 5:
            r = http.post(
                f"{API_BASE}/release",
                json={
                    "filters": ["vn", "=", ["id", "=", vid]],
                    "fields": "id,title,alttitle,released,languages.lang,platforms,official,patch",
                    "sort": "released",
                    "results": 100,
                    "page": page,
                },
                headers=_headers(json_body=True),
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json()
            releases.extend(data.get("results") or [])
            if not data.get("more"):
                break
            page += 1
    except Exception:
        pass
    return releases


def fetch_user_entry(vndb_id, token, timeout=12):
    """Fetch one VN's list entry, user labels, and VNDB releases concurrently."""
    from concurrent.futures import ThreadPoolExecutor

    vid = parse_vndb_id(vndb_id)
    clean = str(token or "").strip()
    if not vid:
        return None, [], [], "Invalid VNDB ID."
    if not clean:
        return None, [], [], "No VNDB API token configured."
    auth = verify_token(clean, timeout=timeout, use_cache=True)
    if not auth.get("ok"):
        return None, [], [], auth.get("error") or "Invalid VNDB token."
    perms = auth.get("permissions") or []
    if "listread" not in perms:
        return None, [], [], "Token missing 'listread' permission."

    def _get_entry():
        r = requests.post(
            f"{API_BASE}/ulist",
            json={
                "user": auth["id"],
                "filters": ["id", "=", vid],
                "fields": (
                    "id,vote,started,finished,notes,labels.id,labels.label,"
                    "releases.id,releases.title,releases.released,releases.list_status,"
                    "releases.languages.lang,releases.platforms"
                ),
                "results": 1,
            },
            headers=_headers(clean, json_body=True),
            timeout=timeout,
        )
        r.raise_for_status()
        return (r.json().get("results") or [None])[0]

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_labels = pool.submit(fetch_ulist_labels, auth["id"], clean, timeout, True)
            f_entry = pool.submit(_get_entry)
            f_releases = pool.submit(fetch_vn_releases, vid, timeout)
            labels = f_labels.result()
            entry = f_entry.result()
            all_releases = f_releases.result()
        return entry, labels, all_releases, ""
    except Exception as exc:
        return None, [], [], str(exc)


def update_user_entry(vndb_id, token, label_ids=None, vote=None,
                      started=None, finished=None, notes=None, timeout=12):
    """Create or update a VN entry on the user's VNDB list (requires listwrite).

    `vote` may be None (clear), a 1.0..10.0 score, or a 10..100 raw VNDB integer.
    """
    vid = parse_vndb_id(vndb_id)
    clean = str(token or "").strip()
    if not vid or not clean:
        return False, "Missing VNDB ID or token."
    patch = {}
    if label_ids is not None:
        patch["labels"] = [int(x) for x in label_ids]
    if vote is None or str(vote).strip() in ("", "-", "None"):
        patch["vote"] = None
    else:
        val = float(vote)
        iv = int(round(val if val > 10 else val * 10))
        patch["vote"] = max(10, min(100, iv))
    patch["started"] = str(started).strip() or None if started is not None else None
    patch["finished"] = str(finished).strip() or None if finished is not None else None
    patch["notes"] = (str(notes)[:2000] if str(notes or "").strip() else None)
    try:
        r = requests.patch(
            f"{API_BASE}/ulist/{vid}",
            json=patch,
            headers=_headers(clean, json_body=True),
            timeout=timeout,
        )
        if not r.ok:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def delete_user_entry(vndb_id, token, timeout=12):
    """Remove a VN (and its releases) from the user's VNDB list."""
    vid = parse_vndb_id(vndb_id)
    clean = str(token or "").strip()
    if not vid or not clean:
        return False, "Missing VNDB ID or token."
    try:
        r = requests.delete(
            f"{API_BASE}/ulist/{vid}",
            headers=_headers(clean),
            timeout=timeout,
        )
        if not r.ok:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def update_release_status(release_id, token, status=2, timeout=12):
    """Add or update a release's list status (`PATCH /rlist/<id>`). status=4 deletes."""
    rid = str(release_id or "").strip().lower()
    if not re.match(r"^r\d+$", rid):
        return False, "Invalid release ID."
    clean = str(token or "").strip()
    if not clean:
        return False, "Missing VNDB token."
    try:
        if status is None or int(status) < 0:
            r = requests.delete(
                f"{API_BASE}/rlist/{rid}",
                headers=_headers(clean),
                timeout=timeout,
            )
        else:
            r = requests.patch(
                f"{API_BASE}/rlist/{rid}",
                json={"status": int(status)},
                headers=_headers(clean, json_body=True),
                timeout=timeout,
            )
        if not r.ok:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def mark_playing(vndb_id, token, timeout=10):
    """Ensure `vndb_id` is marked as 'Playing' (id=1) on the user's VNDB list.

    Leaves games already marked 'Playing' (1) or 'Finished' (2) untouched so
    replaying a finished VN never overwrites its status.
    """
    vid = parse_vndb_id(vndb_id)
    clean = str(token or "").strip()
    if not vid or not clean:
        return False
    try:
        auth = verify_token(clean, timeout=timeout)
        if not auth.get("ok") or "listwrite" not in (auth.get("permissions") or []):
            return False
        check = requests.post(
            f"{API_BASE}/ulist",
            json={
                "user": auth["id"],
                "filters": ["id", "=", vid],
                "fields": "id,started,labels.id",
                "results": 1,
            },
            headers=_headers(clean, json_body=True),
            timeout=timeout,
        )
        check.raise_for_status()
        existing = (check.json().get("results") or [None])[0]
        if existing:
            ids = {lb.get("id") for lb in existing.get("labels") or []}
            if 1 in ids or 2 in ids:
                return False
        patch = {
            "labels_set": [1],
            "labels_unset": [3, 4, 5],
        }
        if not (existing and existing.get("started")):
            patch["started"] = date.today().isoformat()
        res = requests.patch(
            f"{API_BASE}/ulist/{vid}",
            json=patch,
            headers=_headers(clean, json_body=True),
            timeout=timeout,
        )
        res.raise_for_status()
        return True
    except Exception:
        return False
