# 78_rebuild_player_comparisons_with_pbp_3.py -- code for the notebook section "CONFIRMED BUG (fixed): this cell used urllib.request without importing it -- harmless whil"
# Runs inside the notebook via run_section("78_rebuild_player_comparisons_with_pbp_3"); its settings are in that notebook cell.

# CONFIRMED BUG (fixed): this cell used urllib.request without importing it -- harmless while every roster photo
# was already on disk, but it would stop the notebook the first time a new photo had to be downloaded.
import urllib.request

# --- UW-Whitewater player headshots from the team's own roster page ----------------------------------------
# The app shows a photo on each UWW player card, looked up by filename in data/uww_player_pictures/. Those
# were being placed there by hand. This reads the saved roster page (a browser "Save as Webpage, Single
# File" export of uwwsports.com's roster) that lives in INPUT_DIR alongside every other snapshot, and fills
# that folder automatically.
#
# Two sources per player, in order:
#   1. the full-size image on the athletics site (the page only links an 80px thumbnail, so the query
#      string is dropped to ask for the original), and
#   2. the thumbnail bytes EMBEDDED in the .mhtml itself -- which is why this still works with no network
#      at all, just at 80px.


_ROSTER_PIC_DIR = os.path.join(APP_DATA_DIR, "uww_player_pictures")
os.makedirs(_ROSTER_PIC_DIR, exist_ok=True)

_roster_paths = sorted(
    p for p in glob.glob(f"{INPUT_DIR}/*.mhtml") + glob.glob(f"{INPUT_DIR}/*.html")
    if re.search(r"roster", os.path.basename(p), re.IGNORECASE)
)
print(f"Found {len(_roster_paths)} roster snapshot(s):")
for _p in _roster_paths:
    print(" -", os.path.basename(_p))


def _mhtml_embedded_parts(path):
    """{Content-Location -> raw bytes} for every image part inside an MHTML archive. The archive keeps the
    images the browser had already loaded, so a lazy-loaded photo further down the page may be absent --
    hence the download attempt first."""
    if not path.lower().endswith(".mhtml"):
        return {}
    import email as _email
    from email import policy as _policy

    with open(path, "rb") as fh:
        msg = _email.message_from_bytes(fh.read(), policy=_policy.default)
    out = {}
    for part in msg.walk():
        if part.get_content_type().startswith("image/"):
            loc = part.get("Content-Location", "")
            if loc:
                out[loc] = (part.get_payload(decode=True) or b"", part.get_content_subtype())
    return out


def _roster_file_stem(name):
    """"Tyshawn Teague-Johnson" -> "uww_Tyshawn_Teague-Johnson", matching what the app's picture lookup
    expects (it strips the "uww_" prefix and splits the rest on underscores)."""
    cleaned = re.sub(r"[^A-Za-z0-9 '\-\.]", "", str(name)).strip()
    cleaned = re.sub(r"\s+", "_", cleaned).replace("'", "").replace(".", "")
    return f"uww_{cleaned}"


_roster_saved, _roster_skipped, _roster_failed = [], [], []
for _rpath in _roster_paths:
    try:
        _rhtml = load_html_snapshot(_rpath)
    except Exception as _rerr:
        print(f"  Could not read {os.path.basename(_rpath)}: {type(_rerr).__name__}: {_rerr}")
        continue
    if not _rhtml:
        continue
    _embedded = _mhtml_embedded_parts(_rpath)

    # Every roster tile renders <img alt="<Name> - View Profile">; that alt is the most reliable place the
    # player's name appears next to their photo (the surrounding markup changes with the site's template).
    _soup = BeautifulSoup(_rhtml, "html.parser")
    _players = []
    for _img in _soup.find_all("img"):
        _alt = str(_img.get("alt", ""))
        _m = re.match(r"^(.*?)\s*-\s*View Profile\s*$", _alt, re.IGNORECASE)
        if not _m:
            continue
        _name = _m.group(1).strip()
        _url = _img.get("data-src") or _img.get("src") or ""
        if _name and _url:
            _players.append((_name, _url))
    print(f"  {os.path.basename(_rpath)}: {len(_players)} player photo(s) referenced")

    for _name, _url in _players:
        _abs = _url if _url.startswith("http") else urljoin("https://uwwsports.com/", _url)
        _stem = _roster_file_stem(_name)
        _existing = glob.glob(os.path.join(_ROSTER_PIC_DIR, _stem + ".*"))
        if _existing and not UWW_ROSTER_FORCE_REFRESH:
            _roster_skipped.append(_name)
            continue

        _data, _ext = None, "jpg"
        # 1. full size from the site -- the page links "?width=80", so ask for the unresized original
        _full = _abs.split("?")[0]
        try:
            _req = urllib.request.Request(_full, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(_req, timeout=15) as _resp:
                _data = _resp.read()
                _ctype = _resp.headers.get("Content-Type", "")
                _ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(_ctype.split(";")[0], "jpg")
        except Exception as _derr:
            # 2. the thumbnail the archive already carries -- no network needed
            _hit = _embedded.get(_abs) or _embedded.get(_url)
            if _hit and _hit[0]:
                _data, _ext = _hit[0], _hit[1] or "webp"
                print(f"    {_name}: download failed ({type(_derr).__name__}) -- using the 80px copy embedded in the archive")
        if not _data:
            _roster_failed.append(_name)
            continue
        _dest = os.path.join(_ROSTER_PIC_DIR, f"{_stem}.{_ext}")
        try:
            with open(_dest, "wb") as _fh:
                _fh.write(_data)
            _roster_saved.append((_name, os.path.basename(_dest), len(_data)))
        except Exception as _werr:
            print(f"    {_name}: could not write {os.path.basename(_dest)} ({type(_werr).__name__})")
            _roster_failed.append(_name)

print(f"\nHeadshots: {len(_roster_saved)} saved, {len(_roster_skipped)} already on disk, {len(_roster_failed)} failed."
      f"  ->  {_ROSTER_PIC_DIR}")
for _n, _f, _b in _roster_saved:
    print(f"  {_n:<28} {_f:<40} {_b/1024:.0f} KB")
if _roster_failed:
    print("  Failed (no download and nothing embedded for them): " + ", ".join(_roster_failed))
if not _roster_paths:
    print("  No roster snapshot found. Save the team roster page as a single-file .mhtml into INPUT_DIR "
          "with 'Roster' in the filename, then re-run this cell.")
