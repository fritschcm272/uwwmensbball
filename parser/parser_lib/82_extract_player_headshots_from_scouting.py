# 82_extract_player_headshots_from_scouting.py -- code for the notebook section "Extract player headshot images from scouting reports (PDF or HTML) and save them to the St"
# Runs inside the notebook via run_section("82_extract_player_headshots_from_scouting"); its settings are in that notebook cell.

# --- Extract player headshot images from scouting reports (PDF or HTML) and save them to the Streamlit
# app's data/player_images/ directory.
# For PDFs: identify headshots by eliminating repeated header images, keeping portrait-oriented images on
#   roster pages, and matching to player names by vertical position order.
# For HTMLs: find <img> elements within playerGroup tiles and download from their URLs, matching to the
#   player name parsed from the same tile's player-info-line spans.
import re as _pi_re
import urllib.request
from urllib.parse import urlparse, quote, urlunparse
from collections import Counter as _PICounter


try:
    import fitz  # pymupdf -- only needed for PDF reports
except ModuleNotFoundError:
    fitz = None  # no PDFs to process if pymupdf isn't installed


_PI_OUTPUT_DIR = os.path.join(APP_DATA_DIR, "player_images")
os.makedirs(_PI_OUTPUT_DIR, exist_ok=True)


_PI_PLAYER_PATTERN = _pi_re.compile(r"#\d+\s*[\u2022\u00b7]\s*(.+?)\s*[\u2022\u00b7]\s*[GCFPG/]+\s*[\u2022\u00b7]")




# --- HTML headshot extraction: find <img> in each playerGroup tile, download from URL ---
def _extract_headshots_from_html(html_path, opponent_name, output_dir):
    """Extract player headshots from an HTML scout report by finding <img> elements in playerGroup tiles."""
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")
    printable = soup.find(class_="PrintableNode")
    if printable is None:
        return {}, {}, []


    extracted = {}
    skipped = {}
    _pending_downloads = []  # URLs that need authenticated download via Playwright


    # Diagnostic: count playerGroup tiles found
    _pg_tiles = [t for t in printable.find_all("div") if "Tile" in (t.get("class") or []) and "playerGroup" in (t.get("class") or [])]
    print(f"    [DIAG] Found {len(_pg_tiles)} playerGroup tiles in PrintableNode")
    if not _pg_tiles:
        # Try alternate: find any div with 'player' in class name
        _alt_tiles = [t for t in printable.find_all("div") if any("player" in c.lower() for c in (t.get("class") or []))]
        print(f"    [DIAG] Alternate: {len(_alt_tiles)} divs with 'player' in class")
        if _alt_tiles:
            print(f"    [DIAG] First alt classes: {_alt_tiles[0].get('class')}")
        # Also show all unique Tile classes
        _all_tiles = [t for t in printable.find_all("div") if "Tile" in (t.get("class") or [])]
        _tile_class_sets = set()
        for _t in _all_tiles[:20]:
            _tile_class_sets.add(tuple(sorted(_t.get("class", []))))
        print(f"    [DIAG] Unique Tile class combos (first 20): {list(_tile_class_sets)[:10]}")
    else:
        # Show first tile's structure in detail
        _first = _pg_tiles[0]
        _has_info = _first.find("span", class_="player-info-line")
        _has_img = _first.find("img")
        print(f"    [DIAG] First playerGroup: has player-info-line={_has_info is not None}, has img={_has_img is not None}")
        if _has_img:
            print(f"    [DIAG] First img src: {_has_img.get('src', '')[:100]}")
        if _has_info:
            _info_div = _has_info.find("div", class_=lambda c: c and "display-flex" in c)
            print(f"    [DIAG] info_div found: {_info_div is not None}")
            if _info_div is None:
                # Show what divs exist inside player-info-line
                _inner_divs = _has_info.find_all("div", limit=5)
                print(f"    [DIAG] Divs inside player-info-line: {[(d.get('class'), d.get_text()[:50]) for d in _inner_divs]}")
            else:
                _fspans = _info_div.find_all("span", recursive=False)
                _flds = [s.get_text(" ", strip=True) for s in _fspans]
                _itext = " \u2022 ".join(f for f in _flds if f)
                print(f"    [DIAG] info_text = {repr(_itext[:120])}")
                _nmatch = _PI_PLAYER_PATTERN.search(_itext)
                print(f"    [DIAG] regex match: {_nmatch is not None}")
                if _nmatch:
                    print(f"    [DIAG] captured name: {repr(_nmatch.group(1))}")
        else:
            _spans = _first.find_all("span", limit=5)
            print(f"    [DIAG] First tile spans: {[(s.get('class'), s.get_text()[:40]) for s in _spans]}")


    for tile in printable.find_all("div"):
        classes = tile.get("class", [])
        if "Tile" not in classes or "playerGroup" not in classes:
            continue


        # Extract player name from player-info-line
        info_span = tile.find("span", class_="player-info-line")
        if info_span is None:
            continue
        info_div = info_span.find("div", class_=lambda c: c and "display-flex" in c)
        if info_div is None:
            continue
        field_spans = info_div.find_all("span", recursive=False)
        fields = [s.get_text(" ", strip=True) for s in field_spans]
        info_text = " \u2022 ".join(f for f in fields if f)
        name_match = _PI_PLAYER_PATTERN.search(info_text)
        if not name_match:
            continue
        player_name = name_match.group(1).strip()
        safe_name = _pi_re.sub(r'[^\w\s\-]', '', player_name).strip()


        # Find the headshot <img> in this tile -- prefer the real HTTP headshot URL over
        # inline data: placeholders. FastScout headshot URLs typically contain "personnel",
        # "images/personnel/", "media-attachments", "headshot", "player", or "FSimages".
        img_tag = None
        for img in tile.find_all("img"):
            src = img.get("src", "")
            if not src or src.endswith(".svg") or "logo" in src.lower():
                continue
            # Never let a data: URI overwrite an already-found HTTP img
            if src.startswith("data:") and img_tag is not None:
                continue
            img_tag = img
            if "headshot" in src.lower() or "player" in src.lower() or "personnel" in src.lower() or "FSimages" in src or "media-attachments" in src:
                break  # best candidate found


        if img_tag is None:
            continue
        img_src = img_tag.get("src", "")


        filepath = os.path.join(output_dir, f"{safe_name}.png")
        if os.path.exists(filepath):
            skipped[safe_name] = opponent_name
            continue


        try:
            if img_src.startswith("data:"):
                import base64
                header, b64data = img_src.split(",", 1)
                img_bytes = base64.b64decode(b64data)
            else:
                # URL-encode path segments (spaces, parens, etc.) while keeping scheme/host intact
                _parsed = urlparse(img_src)
                _encoded_url = urlunparse(_parsed._replace(path=quote(_parsed.path, safe="/")))
                req = urllib.request.Request(_encoded_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    img_bytes = resp.read()


            if len(img_bytes) > 500:  # skip tiny placeholders
                with open(filepath, "wb") as out_f:
                    out_f.write(img_bytes)
                extracted[safe_name] = opponent_name
            elif img_src.startswith(("http://", "https://")):
                # CDN returned auth-wall placeholder -- collect for Playwright batch download
                # (only HTTP(S) URLs can be re-fetched with auth; data: URIs are genuinely empty)
                _pending_downloads.append((player_name, safe_name, img_src, filepath, opponent_name))
        except Exception as dl_err:
            print(f"    [WARN] Could not download headshot for {player_name}: {type(dl_err).__name__}: {dl_err}")


    # --- Collect pending downloads (do NOT attempt async here -- the caller batches them) ---
    if _pending_downloads:
        print(f"    [AUTH] {len(_pending_downloads)} headshot(s) need authenticated download (deferred to batch)")


    return extracted, skipped, _pending_downloads




# --- PDF headshot extraction (original PyMuPDF approach) ---
def _extract_headshots_from_pdf(pdf_path, opponent_name, output_dir):
    """Extract player headshots from a PDF scout report using PyMuPDF."""
    if fitz is None:
        print(f"    [SKIP] pymupdf not installed -- cannot process PDF: {os.path.basename(pdf_path)}")
        return {}, {}, {}


    doc = fitz.open(pdf_path)
    extracted = {}
    skipped = {}
    diag = {"file": os.path.basename(pdf_path), "format": "pdf", "pages": doc.page_count,
            "total_images": 0, "candidate_headshots": 0, "names_matched": 0}


    xref_count = _PICounter()
    for pn in range(doc.page_count):
        for img in doc[pn].get_images(full=True):
            xref_count[img[0]] += 1
    header_xrefs = {xref for xref, cnt in xref_count.items() if cnt >= 3}


    for pn in range(doc.page_count):
        page = doc[pn]
        images = page.get_images(full=True)
        diag["total_images"] += len(images)


        headshots = []
        for img in images:
            xref = img[0]
            if xref in header_xrefs:
                continue
            base = doc.extract_image(xref)
            w, h = base['width'], base['height']
            if h >= w * 0.8 and len(base['image']) > 5000:
                rects = page.get_image_rects(xref)
                if rects:
                    headshots.append({'y': rects[0].y0, 'image_data': base['image'], 'ext': base['ext']})


        if not headshots:
            continue
        diag["candidate_headshots"] += len(headshots)
        headshots.sort(key=lambda x: x['y'])


        text = page.get_text("text")
        names = _PI_PLAYER_PATTERN.findall(text)
        diag["names_matched"] += len(names)


        for i in range(min(len(headshots), len(names))):
            name = names[i].strip()
            safe = _pi_re.sub(r'[^\w\s\-]', '', name).strip()
            filename = f"{safe}.{headshots[i]['ext']}"
            filepath = os.path.join(output_dir, filename)
            if os.path.exists(filepath):
                skipped[safe] = opponent_name
            else:
                with open(filepath, 'wb') as out_f:
                    out_f.write(headshots[i]['image_data'])
                extracted[safe] = opponent_name


    doc.close()
    return extracted, skipped, diag




# --- Main loop: process all scout reports (HTML and PDF) ---
_pi_all_extracted = {}
_pi_skipped = {}
_pi_all_pending = []  # (player_name, safe_name, url, filepath, opponent_name) tuples deferred for batch auth download
_pi_diag = []


print(f"Processing {len(scout_report_files)} scout report(s) from scout_report_files...")
for _pi_path in sorted(scout_report_files):
    _pi_file = os.path.basename(_pi_path)
    _pi_opponent = opponent_from_scout_filename(_pi_path)


    if _pi_path.lower().endswith(".html"):
        _ext, _skip, _pending = _extract_headshots_from_html(_pi_path, _pi_opponent, _PI_OUTPUT_DIR)
        _pi_all_extracted.update(_ext)
        _pi_skipped.update(_skip)
        _pi_all_pending.extend(_pending)
        _pi_diag.append({"file": _pi_file, "format": "html", "extracted": len(_ext), "skipped": len(_skip)})
    else:
        _ext, _skip, _d = _extract_headshots_from_pdf(_pi_path, _pi_opponent, _PI_OUTPUT_DIR)
        _pi_all_extracted.update(_ext)
        _pi_skipped.update(_skip)
        if _d:
            _pi_diag.append(_d)


# --- Batch authenticated download of ALL pending headshots in a single Playwright session ---
# run_in_fastscout_session is SYNCHRONOUS (dispatches fn(page) on a dedicated worker thread using
# Playwright's sync API) -- no async/await/event-loop needed here.
if _pi_all_pending:
    print(f"\n[AUTH] Batch downloading {len(_pi_all_pending)} headshot(s) via authenticated Playwright session...")
    try:
        def _batch_download_headshots(page):
            downloaded = 0
            for _pname, _sname, _url, _fpath, _opp in _pi_all_pending:
                try:
                    _resp = page.request.get(_url)
                    if _resp.ok:
                        _body = _resp.body()
                        if len(_body) > 500:
                            with open(_fpath, "wb") as _f:
                                _f.write(_body)
                            _pi_all_extracted[_sname] = _opp
                            downloaded += 1
                        else:
                            print(f"  [SKIP] {_pname}: authenticated resp still only {len(_body)} bytes")
                    else:
                        print(f"  [SKIP] {_pname}: HTTP {_resp.status}")
                except Exception as _e:
                    print(f"  [WARN] {_pname}: {type(_e).__name__}: {_e}")
            return downloaded


        _pi_pw_downloaded = run_in_fastscout_session(_batch_download_headshots)
        if _pi_pw_downloaded:
            print(f"[OK] Downloaded {_pi_pw_downloaded}/{len(_pi_all_pending)} headshot(s) via authenticated session")
        else:
            print(f"[INFO] Playwright session connected but no images exceeded 500 bytes -- "
                  f"headshots may not be uploaded on FastScout for these teams.")
    except Exception as _sess_err:
        print(f"[INFO] Cannot authenticate for headshot download: {type(_sess_err).__name__}: {_sess_err}")
        print(f"[INFO] Set FASTSCOUT_USERNAME/FASTSCOUT_PASSWORD env vars and re-run to download headshots.")
else:
    print("\n[INFO] No headshots required authenticated download.")


print(f"\nExtracted {len(_pi_all_extracted)} new player headshot(s) to {_PI_OUTPUT_DIR}")
if _pi_skipped:
    print(f"Skipped {len(_pi_skipped)} already-on-disk headshot(s)")
for _pi_name, _pi_opp in sorted(_pi_all_extracted.items(), key=lambda x: x[1]):
    print(f"  [NEW] [{_pi_opp}] {_pi_name}")


if not _pi_all_extracted and not _pi_skipped:
    print("\n--- DIAGNOSTIC: 0 headshots found. Per-report breakdown: ---")
    if not _pi_diag:
        print("  scout_pdf_files was EMPTY -- no reports to process.")
    for _d in _pi_diag:
        if _d.get("format") == "html":
            print(f"  {_d['file']}: HTML format, {_d['extracted']} extracted, {_d['skipped']} skipped")
        else:
            print(f"  {_d['file']}: {_d.get('pages', '?')} pages, {_d.get('total_images', 0)} images, "
                  f"{_d.get('candidate_headshots', 0)} candidates, {_d.get('names_matched', 0)} names matched")

# --- before_scout: hide everything else the scouting report left behind in the app's data dir -----------
# Filtering the report out of scout_report_files stops NEW artifacts being produced from it, but two kinds
# of file written by an EARLIER run are still sitting in the app's data directory, and the app happily
# renders both: the player headshots extracted from the report, and the report PDF itself (which drives the
# "Download Scouting Report PDF" button). The report is gone and its by-products aren't -- that's the leak
# this closes, so before_scout="yes" looks the same as an opponent whose report simply hasn't been made yet.
#
# Moved into a "_hidden_before_scout" subfolder rather than deleted. The app reads only the top level of
# each directory, so a subfolder is invisible to it, and flipping before_scout back to "no" restores
# everything on the next run instead of needing a re-extract -- which for the HTML-sourced headshots means
# a re-authenticated Playwright download, not just a local re-parse.
import shutil

_BS_HIDDEN_SUBDIR = "_hidden_before_scout"


def _bs_hide(paths, live_dir):
    """Move `paths` out of `live_dir` into its hidden subfolder. Returns the basenames moved."""
    _moved = []
    for _path in paths:
        if not os.path.isfile(_path):
            continue
        _hidden_dir = os.path.join(live_dir, _BS_HIDDEN_SUBDIR)
        os.makedirs(_hidden_dir, exist_ok=True)
        shutil.move(_path, os.path.join(_hidden_dir, os.path.basename(_path)))
        _moved.append(os.path.basename(_path))
    return sorted(_moved)


def _bs_restore(live_dir):
    """Move everything back out of `live_dir`'s hidden subfolder -- not just the current opponent's, so a
    file hidden during one run doesn't stay hidden once you've moved on to the next game. A hidden file
    whose live copy already exists is left alone rather than overwriting a freshly produced one; it's a
    duplicate of the same artifact either way. Returns (restored_basenames, n_duplicates_left)."""
    _hidden_dir = os.path.join(live_dir, _BS_HIDDEN_SUBDIR)
    if not os.path.isdir(_hidden_dir):
        return [], 0
    _restored, _dupes = [], 0
    for _name in sorted(os.listdir(_hidden_dir)):
        _hidden_path = os.path.join(_hidden_dir, _name)
        if not os.path.isfile(_hidden_path):
            continue
        _dest = os.path.join(live_dir, _name)
        if os.path.exists(_dest):
            _dupes += 1
            continue
        shutil.move(_hidden_path, _dest)
        _restored.append(_name)
    return _restored, _dupes


def _pi_image_paths_for(base_dir, name):
    """Every filename this player's headshot could be under. The extractors write "<sanitized name>.<ext>"
    while the app looks up "<roster name>.<ext>" -- usually identical, but check both rather than assume."""
    _safe = _pi_re.sub(r"[^\w\s\-]", "", str(name)).strip()
    return [
        os.path.join(base_dir, f"{_n}.{_ext}")
        for _n in {str(name).strip(), _safe} if _n
        for _ext in ("png", "jpeg", "jpg")
    ]


# HEADSHOTS -- no longer hidden here. Report-extracted headshots used to be the only photo source for the
# upcoming opponent, so before_scout="yes" had to hide them to avoid leaking a report that's meant to not
# exist yet. That's no longer true: Personnel Details now gets its photos from the live /roster page scrape
# (see the "Roster pages" cell), which is independent of the scouting report and isn't gated by before_scout
# at all -- so there's nothing report-derived left to leak through a photo. Restoring files a PREVIOUS run
# already hid is kept below (harmless cleanup of stragglers); only the forward-hiding action is removed.

# REPORT PDF -- the app finds this with `f.lower().endswith(".pdf") and short_opponent.lower() in f.lower()`
# over data/scouting_reports/. Mirror that test exactly rather than inventing a looser one: the goal is to
# hide precisely what the app would otherwise offer for download, and a file the app can't find needs no
# hiding. Note this directory is hand-maintained -- the parser never writes to it -- so a PDF here survives
# every re-run on its own.
_BS_REPORTS_DIR = os.path.join(APP_DATA_DIR, "scouting_reports")


def _bs_report_pdfs_for(opponent_short):
    if not opponent_short or not os.path.isdir(_BS_REPORTS_DIR):
        return []
    _key = str(opponent_short).strip().lower()
    return [
        os.path.join(_BS_REPORTS_DIR, _f) for _f in sorted(os.listdir(_BS_REPORTS_DIR))
        if _f.lower().endswith(".pdf") and _key in _f.lower()
    ]


if _before_scout_enabled:
    _bs_reports_moved = _bs_hide(_bs_report_pdfs_for(upcoming_opponent_short), _BS_REPORTS_DIR)
    _bs_who = upcoming_opponent_short or "upcoming opponent"
    print(f"[before_scout=yes] Scouting report PDF: "
          + (f"hid {len(_bs_reports_moved)} file(s) from {_BS_REPORTS_DIR} -- {_bs_reports_moved}"
             if _bs_reports_moved else f"none on disk for {_bs_who} to hide."))
    # One-time cleanup: restore any headshots a PREVIOUS run hid, since new runs no longer hide them.
    _bs_restored, _bs_dupes = _bs_restore(_PI_OUTPUT_DIR)
    if _bs_restored or _bs_dupes:
        print(f"[before_scout=yes] Restored {len(_bs_restored)} headshot(s) hidden by an earlier version of "
              f"this cell to {_PI_OUTPUT_DIR}"
              + (f" ({_bs_dupes} left in place -- a live copy already exists)." if _bs_dupes else "."))
else:
    for _bs_dir, _bs_label in ((_PI_OUTPUT_DIR, "headshot"), (_BS_REPORTS_DIR, "scouting report PDF")):
        _bs_restored, _bs_dupes = _bs_restore(_bs_dir)
        if _bs_restored or _bs_dupes:
            print(f"\n[before_scout=no] Restored {len(_bs_restored)} previously hidden {_bs_label}(s) to "
                  f"{_bs_dir}"
                  + (f" ({_bs_dupes} left in place -- a live copy already exists)." if _bs_dupes else "."))


# --- Roster photos: what to do when the scouting report has none --------------------------------------
# CONFIRMED CHANGE (requested 11/19: "you could do a fall back of getting the roster pictures from the
# previous year ... I can also provide a second fall back of entering in their official website to get their
# player roster. There is additional information on there normally, so it's good information to have stored").
# Hope was the case that found this: all nine of their saved "headshots" were the SAME 5,637-byte grey
# silhouette -- their report carries no photos, so the extractor above saved the report's own no-photo avatar
# under every name. A fake photo is worse than none: it looks like the system worked.
# Three steps, in this order, and every photo records where it came from so the app and the brief can say so:
#   1. throw out the avatars (the same bytes under two or more names is never two headshots),
#   2. last season's archive (data_<season>/player_images beside data/),
#   3. the team's own athletics site, from inputs/opponent_sites.json -- which also gives the roster table
#      (hometown, high school, class, height, weight), worth keeping on its own.
import hashlib as _pi2_hashlib
import json as _pi2_json
import shutil as _pi2_shutil

_PI2_EXTS = ("png", "jpeg", "jpg")                      # the app and the brief try these, in this order
_PI2_SITES_JSON = os.path.join(INPUT_DIR, "opponent_sites.json")
_PI2_SOURCES_CSV = os.path.join(APP_DATA_DIR, "uww_player_image_sources.csv")
_PI2_WEB_CSV = os.path.join(APP_DATA_DIR, "uww_opponent_web_rosters.csv")
_PI2_PLACEHOLDER_DIR = os.path.join(_PI_OUTPUT_DIR, "_placeholders")
_pi2_sources = {}                                       # player -> {source, detail, opponent}


def _pi2_key(name):
    return _pi_re.sub(r"[^a-z]", "", str(name).lower())


def _pi2_path(name):
    """The saved photo for this player, whatever extension it has -- or None."""
    for _e in _PI2_EXTS:
        _p = os.path.join(_PI_OUTPUT_DIR, f"{name}.{_e}")
        if os.path.isfile(_p):
            return _p
    return None


# ---- 1. the report's own "no photo" avatar ----------------------------------------------------------
_pi2_by_hash = {}
for _f in sorted(os.listdir(_PI_OUTPUT_DIR)):
    _p = os.path.join(_PI_OUTPUT_DIR, _f)
    if not os.path.isfile(_p) or _f.rsplit(".", 1)[-1].lower() not in _PI2_EXTS:
        continue
    try:
        with open(_p, "rb") as _fh:
            _pi2_by_hash.setdefault(_pi2_hashlib.md5(_fh.read()).hexdigest(), []).append(_f)
    except OSError:
        continue
_pi2_avatars = {h: fs for h, fs in _pi2_by_hash.items() if len(fs) >= 2}
if _pi2_avatars:
    os.makedirs(_PI2_PLACEHOLDER_DIR, exist_ok=True)
    for _h, _fs in sorted(_pi2_avatars.items()):
        for _f in _fs:
            try:
                _pi2_shutil.move(os.path.join(_PI_OUTPUT_DIR, _f), os.path.join(_PI2_PLACEHOLDER_DIR, _f))
            except OSError:
                pass
        print(f"  [photos] the same image was saved for {len(_fs)} player(s) -- that is the report's "
              f"'no photo' avatar, not a headshot: {', '.join(sorted(os.path.splitext(x)[0] for x in _fs)[:6])}"
              + (" ..." if len(_fs) > 6 else ""), flush=True)


# ---- who still needs a photo ------------------------------------------------------------------------
_pi2_need = {}                                          # player name -> opponent
try:
    _pi2_ros = pd.read_csv(os.path.join(APP_DATA_DIR, "uww_opponent_rosters.csv"), dtype=str)
except Exception:
    _pi2_ros = pd.DataFrame()
if not _pi2_ros.empty and {"name", "opponent"} <= set(_pi2_ros.columns):
    for _, _r in _pi2_ros.iterrows():
        _nm = str(_r.get("name") or "").strip()
        if _nm and _pi2_path(_nm) is None:
            _pi2_need[_nm] = str(_r.get("opponent") or "").strip()


# ---- 2. last season's archive -----------------------------------------------------------------------
_pi2_archives = []
_pi2_parent = os.path.dirname(os.path.abspath(APP_DATA_DIR))
for _d in sorted(os.listdir(_pi2_parent) if os.path.isdir(_pi2_parent) else [], reverse=True):
    _pid = os.path.join(_pi2_parent, _d, "player_images")
    if _d.startswith("data_") and os.path.isdir(_pid):
        _pi2_archives.append((_d.replace("data_", ""), _pid))
_pi2_from_last = 0
for _nm in sorted(_pi2_need):
    for _season, _dir in _pi2_archives:
        _hit = next((os.path.join(_dir, f"{_nm}.{e}") for e in _PI2_EXTS
                     if os.path.isfile(os.path.join(_dir, f"{_nm}.{e}"))), None)
        if not _hit:
            continue
        try:
            _pi2_shutil.copy2(_hit, os.path.join(_PI_OUTPUT_DIR, os.path.basename(_hit)))
        except OSError:
            break
        _pi2_sources[_nm] = {"source": "last season", "detail": _season, "opponent": _pi2_need[_nm]}
        _pi2_from_last += 1
        break
if _pi2_from_last:
    print(f"  [photos] {_pi2_from_last} from last season's pictures "
          f"({', '.join(s for s, _ in _pi2_archives)}) -- shown with the season on the card", flush=True)
for _nm in list(_pi2_need):
    if _pi2_path(_nm) is not None:
        _pi2_need.pop(_nm, None)


# ---- 3. the team's own athletics site ---------------------------------------------------------------
# inputs/opponent_sites.json: {"Hope Flying Dutchmen": "https://athletics.hope.edu/sports/mens-basketball/roster"}
# The roster TABLE is read every time, photos or not: hometown, high school, class, height and weight are
# not in the scouting report and are worth having. A player who still has no photo gets one from his own
# profile page's og:image, which is where these sites keep the headshot.
import time as _pi2_time
from io import StringIO as _PI2_StringIO
from urllib.parse import urljoin as _pi2_urljoin

_PI2_FRESH_H = float(globals().get("OPPONENT_SITE_FRESH_HOURS", 12))


def _pi2_get(url, timeout=25):
    _req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (UWW scouting parser)"})
    with urllib.request.urlopen(_req, timeout=timeout) as _r:
        return _r.read()


def _pi2_cached(url, path):
    """The page, from disk when it was fetched recently -- a roster changes about once a season."""
    try:
        if os.path.isfile(path) and (_pi2_time.time() - os.path.getmtime(path)) < _PI2_FRESH_H * 3600:
            with open(path, "rb") as _fh:
                return _fh.read(), True
    except OSError:
        pass
    _body = _pi2_get(url)
    try:
        with open(path, "wb") as _fh:
            _fh.write(_body)
    except OSError:
        pass
    return _body, False


def _pi2_txt(v):
    """A cell as the page meant it. read_html types a numeric column, so jersey 13 arrives as 13.0 and would
    be written "13.0"; an empty cell arrives as NaN and would be written "nan"."""
    if v is None:
        return ""
    if isinstance(v, float):
        if v != v:
            return ""
        if float(v).is_integer():
            return str(int(v))
    _s = str(v).strip()
    return "" if _s.lower() in ("nan", "none") else _s


def _pi2_col(cols, *wants):
    for _c in cols:
        _l = str(_c).strip().lower()
        if any(_w in _l for _w in wants):
            return _c
    return None


_pi2_sites = {}
try:
    with open(_PI2_SITES_JSON, encoding="utf-8") as _fh:
        _pi2_sites = {str(k).strip(): str(v).strip() for k, v in (_pi2_json.load(_fh) or {}).items() if str(v).strip()}
except FileNotFoundError:
    pass
except Exception as _e:
    print(f"  [roster site] {os.path.basename(_PI2_SITES_JSON)} could not be read "
          f"({type(_e).__name__}: {_e}) -- skipped", flush=True)

_pi2_web_rows, _pi2_from_web = [], 0
for _opp, _url in sorted(_pi2_sites.items()):
    _safe = _pi_re.sub(r"[^A-Za-z0-9 ()-]+", " ", _opp).strip()
    _page = os.path.join(INPUT_DIR, f"{_safe} - Roster (web).html")
    _was_cached = False
    try:
        _html_b, _was_cached = _pi2_cached(_url, _page)
        _html = _html_b.decode("utf-8", "replace")
    except Exception as _e:
        print(f"  [roster site] {_opp}: {_url} could not be read ({type(_e).__name__}: {_e})", flush=True)
        continue
    try:
        _tables = pd.read_html(_PI2_StringIO(_html))
    except Exception:
        _tables = []
    _tbl = next((t for t in _tables if _pi2_col(t.columns, "name") is not None and len(t) >= 3), None)
    if _tbl is None:
        print(f"  [roster site] {_opp}: no roster table found -- the page is saved as "
              f"{os.path.basename(_page)} for a look", flush=True)
        continue
    _c_name = _pi2_col(_tbl.columns, "name")
    _c_no = _pi2_col(_tbl.columns, "#", "no.", "jersey")
    _c_pos = _pi2_col(_tbl.columns, "pos")
    _c_ht = _pi2_col(_tbl.columns, "ht", "height")
    _c_wt = _pi2_col(_tbl.columns, "wt", "weight")
    _c_cl = _pi2_col(_tbl.columns, "class", "year", " yr")
    _c_hm = _pi2_col(_tbl.columns, "hometown", "high school")
    _links = {}                                   # name -> profile page, where the headshot lives
    for _href, _txt in _pi_re.findall(r'href="([^"]*/roster/[^"]+?/\d+)"[^>]*>([^<]{3,60})<', _html):
        if _pi2_key(_txt):
            _links.setdefault(_pi2_key(_txt), _href)
    _rows_here = 0
    for _, _r in _tbl.iterrows():
        _nm = _pi_re.sub(r"\s+", " ", str(_r.get(_c_name) or "")).strip()
        if not _nm or _nm.lower() in ("nan", "name"):
            continue
        _hm = _pi2_txt(_r.get(_c_hm)) if _c_hm else ""
        _home, _hs = (_hm.split("/", 1) + [""])[:2]
        _cell = lambda c: (_pi2_txt(_r.get(c)) if c else "")              # noqa: E731
        _pi2_web_rows.append({
            "opponent": _opp, "jersey_number": _cell(_c_no), "name": _nm, "position": _cell(_c_pos),
            "height": _cell(_c_ht), "weight": _cell(_c_wt), "class_year": _cell(_c_cl),
            "hometown": _home.strip(), "high_school": _hs.strip(),
            "profile_url": _pi2_urljoin(_url, _links.get(_pi2_key(_nm), "")) if _links.get(_pi2_key(_nm)) else "",
            "source_url": _url, "fetched": pd.Timestamp.now().isoformat(timespec="seconds"),
        })
        _rows_here += 1
    _got_here = 0
    # CONFIRMED BUG (fixed 11/22; Corey: "The Hope player pictures are still not showing up in the briefs"). The first
    # version looked for the headshot in each player's PROFILE page og:image. Sidearm's og:image is the site's logo
    # (the saved page shows <meta name="og:image"> with no content at all), so every lookup quietly found nothing -- and
    # the bare `except: continue` hid that. The headshots are on the ROSTER page itself, as lazy-loaded
    # <img data-src="/images/2026/11/3/Miller_Brady.jpg?width=80" alt="Brady Miller - View Profile">. Read them from there,
    # at a larger width (the page's 80 px thumbnail is too small for a card), and say why when one can't be fetched.
    _imgs = {}
    for _tag in _pi_re.findall(r"<img\b[^>]*>", _html):
        _al = _pi_re.search(r'alt="([^"]*?)\s*-\s*View Profile"', _tag)
        _sr = _pi_re.search(r'data-src="([^"]+)"', _tag) or _pi_re.search(r'\bsrc="([^"]+)"', _tag)
        if _al and _sr and _pi2_key(_al.group(1)):
            _imgs.setdefault(_pi2_key(_al.group(1)), _sr.group(1).replace("&amp;", "&"))
    _fail_shown = 0
    for _key_, _src_ in _imgs.items():
        _nm = next((n for n in _pi2_need if _pi2_key(n) == _key_), None)
        if _nm is None:
            continue
        _base = _pi2_urljoin(_url, _src_.split("?")[0])
        _bytes = None
        for _u in (_base + "?width=400&quality=90", _pi2_urljoin(_url, _src_), _base):
            try:
                _bytes = _pi2_get(_u)
                break
            except Exception as _e:
                if _fail_shown < 3:
                    print(f"  [roster site] {_nm}: {_u} -- {type(_e).__name__}: {_e}", flush=True)
                    _fail_shown += 1
        if not _bytes or len(_bytes) < 2000:
            continue
        _ext = "png" if _bytes[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"
        try:
            with open(os.path.join(_PI_OUTPUT_DIR, f"{_nm}.{_ext}"), "wb") as _fh:
                _fh.write(_bytes)
        except OSError:
            continue
        _pi2_sources[_nm] = {"source": "team website", "detail": urlparse(_url).netloc, "opponent": _opp}
        _pi2_need.pop(_nm, None)
        _got_here += 1
    for _row in [r for r in _pi2_web_rows if r["opponent"] == _opp and r["profile_url"]]:
        if _row["name"] not in _pi2_need and not any(_pi2_key(_row["name"]) == _pi2_key(n) for n in _pi2_need):
            continue
        _nm = next((n for n in _pi2_need if _pi2_key(n) == _pi2_key(_row["name"])), _row["name"])
        try:
            _pbody = _pi2_get(_row["profile_url"]).decode("utf-8", "replace")
        except Exception:
            continue
        _m = (_pi_re.search(r'property="og:image"[^>]*content="([^"]+)"', _pbody)
              or _pi_re.search(r'content="([^"]+)"[^>]*property="og:image"', _pbody))
        if not _m:
            continue
        try:
            _bytes = _pi2_get(_pi2_urljoin(_row["profile_url"], _m.group(1)))
        except Exception:
            continue
        if len(_bytes) < 2000:                    # the site's own placeholder -- the same trap as the report's
            continue
        _ext = "png" if _bytes[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"
        try:
            with open(os.path.join(_PI_OUTPUT_DIR, f"{_nm}.{_ext}"), "wb") as _fh:
                _fh.write(_bytes)
        except OSError:
            continue
        _pi2_sources[_nm] = {"source": "team website", "detail": urlparse(_url).netloc, "opponent": _opp}
        _got_here += 1
    _pi2_from_web += _got_here
    print(f"  [roster site] {_opp}: {_rows_here} player(s) from {urlparse(_url).netloc}"
          + (" (saved page)" if _was_cached else "") + (f", {_got_here} photo(s)" if _got_here else ""), flush=True)

if _pi2_web_rows:
    pd.DataFrame(_pi2_web_rows).to_csv(_PI2_WEB_CSV, index=False)
    print(f"  [roster site] {len(_pi2_web_rows)} roster row(s) -> {os.path.basename(_PI2_WEB_CSV)} "
          f"(hometown, high school, class, height, weight)", flush=True)

# ---- where each photo came from, so the app and the brief can say so ---------------------------------
if not _pi2_ros.empty:
    for _nm in sorted({str(x).strip() for x in _pi2_ros.get("name", pd.Series(dtype=str)).dropna()}):
        if _nm and _nm not in _pi2_sources and _pi2_path(_nm) is not None:
            _pi2_sources[_nm] = {"source": "scouting report", "detail": "", "opponent": ""}
if _pi2_sources:
    pd.DataFrame([{"player": _k, "source": _v["source"], "detail": _v["detail"], "opponent": _v["opponent"]}
                  for _k, _v in sorted(_pi2_sources.items())]).to_csv(_PI2_SOURCES_CSV, index=False)
    _n_alt = sum(1 for _v in _pi2_sources.values() if _v["source"] != "scouting report")
    if _n_alt:
        print(f"  [photos] {_n_alt} picture(s) are not from this season's report -- the card says where "
              f"each came from ({os.path.basename(_PI2_SOURCES_CSV)})", flush=True)
