"""Hygger Presence 2.4.0 - multi-platform VN ratings and rankings.

Fetches ratings and rankings from:
  * VNDB        (rating, weighted rating, rating rank, popularity rank)
  * Bangumi     (bgm.tv score, rank, vote count)
  * ErogameScape (median, average, rank, vote count - falls back to N/A if
                  region-blocked / unreachable)
"""
from html import unescape
import re
import time
import unicodedata
from urllib.parse import quote

import requests

BANGUMI_API = "https://api.bgm.tv/v0"
BANGUMI_UA = "hyther1111/HyggerPresence (https://github.com/hyther1111/HyggerPresence)"
EGS_SQL_URL = "https://erogamescape.dyndns.org/~ap2/ero/toukei_kaiseki/sql_for_erogamer_form.php"
EGS_UA = "HyggerPresence/2.4.0 (+https://github.com/hyther1111/HyggerPresence)"

_EGS_BLOCKED_UNTIL = 0.0
_EGS_COOLDOWN = 120.0

_BGM_ID_RE = re.compile(r"(?:(?:bgm\.tv|bangumi\.tv)/subject/)?(\d+)", re.I)
_EGS_ID_RE = re.compile(r"(?:game\.php\?game=)?(\d+)", re.I)
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _norm(text):
    """Normalize a title for fuzzy comparison across platforms."""
    s = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.sub(r"[\s\-_~〜・:：!！?？'\"「」『』()（）\[\]【】.,。、]+", "", s)


def parse_bangumi_id(value):
    text = str(value or "").strip()
    if not text:
        return ""
    m = _BGM_ID_RE.search(text)
    if m and (text.isdigit() or "subject/" in text.lower()):
        return m.group(1)
    return ""


def parse_egs_id(value):
    text = str(value or "").strip()
    if not text:
        return ""
    m = _EGS_ID_RE.search(text)
    if m and (text.isdigit() or "game=" in text.lower()):
        return m.group(1)
    return ""


def _fmt_bgm_subject(subject):
    rating = subject.get("rating") or {}
    score = rating.get("score")
    # v0 subjects put rank inside rating; legacy search puts rank at top level.
    rank = rating.get("rank")
    if rank is None:
        rank = subject.get("rank")
    total = rating.get("total")
    score_text = f"{float(score):.1f}" if isinstance(score, (int, float)) and score > 0 else "N/A"
    rank_text = f"#{int(rank)}" if isinstance(rank, int) and rank > 0 else "N/A"
    votes_text = str(int(total)) if isinstance(total, int) and total > 0 else "N/A"
    return {
        "bangumi_id": str(subject.get("id") or ""),
        "bangumi_rating": score_text,
        "bangumi_rank": rank_text,
        "bangumi_votes": votes_text,
    }


def _score_bgm_candidate(item, queries, year):
    names = [_norm(item.get("name")), _norm(item.get("name_cn"))]
    names = [n for n in names if n]
    title_score = 0
    for q in queries:
        nq = _norm(q)
        if not nq:
            continue
        if nq in names:
            title_score = max(title_score, 100)
            break
        if any(nq in n or n in nq for n in names):
            title_score = max(title_score, 35)
    # Require an actual title match so release year + vote count never pick an unrelated subject.
    if title_score <= 0:
        return 0
    score = title_score
    item_date = str(item.get("date") or item.get("air_date") or "")
    if year and year.isdigit() and item_date.startswith(year):
        score += 25
    total = ((item.get("rating") or {}).get("total")) or 0
    score += min(20, int(total) // 50)
    return score


def _bgm_search_queries(titles):
    """Build ordered search keywords including punctuation-trimmed fallbacks."""
    raw = []
    for t in titles or ():
        clean = str(t or "").strip()
        if clean and clean not in raw:
            raw.append(clean)
    queries = list(raw)
    for clean in raw:
        # Bangumi's GET search endpoint drops/fails on !/?// in path segments.
        trimmed = re.split(r"\s+-\s+|\s*[!！?？/／]+", clean)[0].strip()
        if trimmed and len(trimmed) >= 2 and trimmed not in queries:
            queries.append(trimmed)
    return queries


def _legacy_bgm_search(query, timeout=6, session=None):
    http = session or requests
    r = http.get(
        f"https://api.bgm.tv/search/subject/{quote(query, safe='')}?type=4&responseGroup=large",
        headers={"User-Agent": BANGUMI_UA},
        timeout=timeout,
    )
    if not r.ok:
        return []
    return (r.json() or {}).get("list") or []


def fetch_bangumi(titles, year="", bangumi_id="", timeout=6, session=None):
    """Fetch Bangumi score, rank and vote count for a visual novel."""
    empty = {
        "bangumi_rating": "N/A",
        "bangumi_rank": "N/A",
        "bangumi_votes": "N/A",
    }
    headers = {"User-Agent": BANGUMI_UA, "Content-Type": "application/json"}
    http = session or requests
    bid = parse_bangumi_id(bangumi_id)
    queries = _bgm_search_queries(titles)
    try:
        if bid:
            r = http.get(
                f"{BANGUMI_API}/subjects/{bid}",
                headers={"User-Agent": BANGUMI_UA},
                timeout=timeout,
            )
            if r.ok:
                return _fmt_bgm_subject(r.json())
            # Unauthenticated /v0/subjects/{id} returns 404 for NSFW subjects;
            # resolve the explicit ID via legacy search when titles are known.
            if r.status_code == 404 and queries:
                for query in queries[:3]:
                    for item in _legacy_bgm_search(query, timeout=timeout, session=http):
                        if str(item.get("id") or "") == str(bid):
                            return _fmt_bgm_subject(item)
            return empty

        if not queries:
            return empty

        best_item = None
        best_score = -1
        # Legacy search includes NSFW subjects (eroge) that /v0/search/subjects hides when unauthenticated.
        for query in queries[:3]:
            for item in _legacy_bgm_search(query, timeout=timeout, session=http):
                s = _score_bgm_candidate(item, queries, str(year or ""))
                if s > best_score:
                    best_score = s
                    best_item = item
            if best_score >= 100:
                break

        if best_item is None or best_score < 35:
            for query in queries[:2]:
                r = http.post(
                    f"{BANGUMI_API}/search/subjects?limit=8",
                    json={"keyword": query, "filter": {"type": [4]}},
                    headers=headers,
                    timeout=timeout,
                )
                if not r.ok:
                    continue
                for item in (r.json().get("data") or []):
                    s = _score_bgm_candidate(item, queries, str(year or ""))
                    if s > best_score:
                        best_score = s
                        best_item = item
                if best_score >= 100:
                    break

        if best_item is None or best_score < 20:
            return empty
        return _fmt_bgm_subject(best_item)
    except Exception:
        return empty


def _parse_egs_table(html):
    """Extract rows of cells from ErogameScape's SQL result HTML table."""
    rows = []
    for tr in _TR_RE.findall(html or ""):
        cells = [_TAG_RE.sub("", unescape(td)).strip() for td in _TD_RE.findall(tr)]
        if cells:
            rows.append(cells)
    return rows


def fetch_erogamescape(titles, year="", egs_id="", timeout=4, skip_if_blocked=True, session=None):
    """Fetch ErogameScape median, average and rank (returns N/A if blocked)."""
    global _EGS_BLOCKED_UNTIL
    empty = {
        "egs_median": "N/A",
        "egs_average": "N/A",
        "egs_rank": "N/A",
        "egs_votes": "N/A",
    }
    now = time.monotonic()
    if skip_if_blocked and now < _EGS_BLOCKED_UNTIL:
        return empty

    http = session or requests
    eid = parse_egs_id(egs_id)
    queries = []
    for t in titles or ():
        clean = str(t or "").strip()
        if clean and clean not in queries:
            queries.append(clean)
    if not eid and not queries:
        return empty

    try:
        if eid:
            where = f"g.id = {int(eid)}"
        else:
            escaped = queries[0].replace("'", "''")
            where = f"g.gamename ILIKE '%{escaped}%'"
        sql = (
            "SELECT g.id, g.gamename, g.sellday, g.median, g.average2, g.count2, "
            "(SELECT COUNT(*) + 1 FROM gamelist x "
            " WHERE x.median IS NOT NULL AND (x.median > g.median "
            "   OR (x.median = g.median AND COALESCE(x.average2,0) > COALESCE(g.average2,0)))) AS rank "
            "FROM gamelist g "
            f"WHERE {where} AND g.median IS NOT NULL "
            "ORDER BY g.count2 DESC NULLS LAST LIMIT 8"
        )
        r = http.post(
            EGS_SQL_URL,
            data={"sql": sql},
            headers={"User-Agent": EGS_UA},
            timeout=timeout,
        )
        if r.status_code in (403, 429, 503):
            _EGS_BLOCKED_UNTIL = time.monotonic() + _EGS_COOLDOWN
            return empty
        r.raise_for_status()
        _EGS_BLOCKED_UNTIL = 0.0
        table = _parse_egs_table(r.text)
        # First row is header (id, gamename, sellday, median, average2, count2, rank)
        data_rows = [row for row in table[1:] if len(row) >= 7 and row[0].isdigit()]
        if not data_rows:
            return empty

        chosen = data_rows[0]
        if not eid:
            best_score = -1
            for row in data_rows:
                nr = _norm(row[1])
                s = 0
                for q in queries:
                    nq = _norm(q)
                    if nq and nr == nq:
                        s += 100
                    elif nq and (nq in nr or nr in nq):
                        s += 30
                if year and str(row[2]).startswith(str(year)):
                    s += 25
                try:
                    s += min(20, int(row[5]) // 50)
                except Exception:
                    pass
                if s > best_score:
                    best_score = s
                    chosen = row

        median_v, avg_v, count_v, rank_v = chosen[3], chosen[4], chosen[5], chosen[6]
        return {
            "egs_id": str(chosen[0]),
            "egs_median": str(median_v) if median_v not in ("", "null", "NULL") else "N/A",
            "egs_average": str(avg_v) if avg_v not in ("", "null", "NULL") else "N/A",
            "egs_votes": str(count_v) if count_v not in ("", "null", "NULL") else "N/A",
            "egs_rank": f"#{rank_v}" if str(rank_v).isdigit() else "N/A",
        }
    except (requests.ConnectTimeout, requests.ReadTimeout, requests.ConnectionError):
        _EGS_BLOCKED_UNTIL = time.monotonic() + _EGS_COOLDOWN
        return empty
    except Exception:
        return empty


def fetch_all_ratings(
    game,
    token="",
    fetch_vndb_rank=True,
    fetch_bangumi_flag=True,
    fetch_egs_flag=True,
    skip_egs_if_blocked=True,
    prefetched_vn=None,
    session=None,
):
    """Fetch VNDB + Bangumi + ErogameScape ratings/rankings for one game."""
    from .vndb import fetch_vndb, fetch_vndb_ranks, parse_vndb_id

    http = session or requests.Session()
    close_session = session is None
    try:
        info = {}
        vid = parse_vndb_id((game or {}).get("vndb_id") or "")
        if vid:
            if prefetched_vn is not None:
                info.update(prefetched_vn)
                if fetch_vndb_rank:
                    ranks = fetch_vndb_ranks(vid, session=http, skip_if_blocked=True)
                    info["vndb_rank"] = ranks.get("vndb_rank", "N/A")
                    info["vndb_popularity"] = ranks.get("vndb_popularity", "N/A")
                    if ranks.get("vndb_votes"):
                        info["vndb_votes"] = ranks["vndb_votes"]
            else:
                vn = fetch_vndb(
                    vid,
                    token=token,
                    include_ranks=bool(fetch_vndb_rank),
                    session=http,
                    skip_ranks_if_blocked=skip_egs_if_blocked,
                )
                if vn:
                    info.update(vn)

        titles = []
        for source in (info, game or {}):
            for key in ("original", "title", "romanized"):
                val = str(source.get(key) or "").strip()
                if val and val not in titles:
                    titles.append(val)
        year = str(info.get("year") or (game or {}).get("year") or "").strip()

        if fetch_bangumi_flag:
            bgm = fetch_bangumi(
                titles,
                year=year,
                bangumi_id=(game or {}).get("bangumi_id") or "",
                session=http,
            )
            info.update(bgm)

        if fetch_egs_flag:
            egs = fetch_erogamescape(
                titles,
                year=year,
                egs_id=(game or {}).get("egs_id") or "",
                skip_if_blocked=skip_egs_if_blocked,
                session=http,
            )
            info.update(egs)

        return info
    finally:
        if close_session:
            http.close()


def fetch_bulk_ratings(
    games,
    token="",
    fetch_vndb_rank=True,
    fetch_bangumi_flag=True,
    fetch_egs_flag=True,
    cancel_event=None,
    progress_cb=None,
    max_workers=6,
):
    """Bulk-fetch metadata & platform ratings rapidly using batched VNDB + worker pool."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    from .vndb import fetch_vndb_batch, parse_vndb_id

    items = list(games or [])
    results = []
    failed = 0
    if not items:
        return results, failed, ""

    # Step 1: batch all VNDB Kana API lookups (50 per HTTP call) + probe EGS once first
    # so subsequent threads hit _EGS_BLOCKED_UNTIL instantly if region-blocked.
    session = requests.Session()
    tls = threading.local()

    def thread_session():
        s = getattr(tls, "session", None)
        if s is None:
            s = requests.Session()
            tls.session = s
        return s

    try:
        vids = [parse_vndb_id(g.get("vndb_id") or "") for g in items]
        vn_map = fetch_vndb_batch([v for v in vids if v], token=token, session=session)
        if cancel_event is not None and cancel_event.is_set():
            return results, failed, "cancelled"

        total = len(items)
        done_count = 0

        def work_one(game):
            if cancel_event is not None and cancel_event.is_set():
                return game, None, None
            vid = parse_vndb_id(game.get("vndb_id") or "")
            pre = vn_map.get(vid) if vid else None
            try:
                info = fetch_all_ratings(
                    game,
                    token=token,
                    fetch_vndb_rank=fetch_vndb_rank,
                    fetch_bangumi_flag=fetch_bangumi_flag,
                    fetch_egs_flag=fetch_egs_flag,
                    skip_egs_if_blocked=True,
                    prefetched_vn=pre,
                    session=thread_session(),
                )
                return game, info, None
            except Exception as exc:
                return game, None, str(exc)

        first_error = ""
        workers = max(1, min(int(max_workers or 6), len(items)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(work_one, g) for g in items]
            for fut in as_completed(futures):
                game, info, err = fut.result()
                if cancel_event is not None and cancel_event.is_set():
                    for pending in futures:
                        pending.cancel()
                    break
                if err and not first_error:
                    first_error = err
                if info:
                    results.append((game, info))
                else:
                    failed += 1
                done_count += 1
                if progress_cb is not None:
                    progress_cb(done_count, total)
        return results, failed, first_error
    finally:
        session.close()
