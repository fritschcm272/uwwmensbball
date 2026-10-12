# 81_extract_and_save_team_logos_from_pbp_mhtml.py -- code for the notebook section "Extract team logos embedded in the PBP/schedule MHTML files and save them into the Streaml"
# Runs inside the notebook via run_section("81_extract_and_save_team_logos_from_pbp_mhtml"); its settings are in that notebook cell.

# --- Extract team logos embedded in the PBP/schedule MHTML files and save them into the Streamlit app's
# data/logo/ directory. Each MHTML archive (Chrome "Save as Webpage, Single File") bundles referenced images
# as binary MIME parts. Team logos appear under two URL patterns:
#   1. https://download.fastmodeltechnologies.com/FSimages/logos/NCAAB-III/<Team>.png
#   2. https://stats-assets.fastmodelsports.com/images/teams/<Team>  (alternate, e.g. Simpson)
# The filename becomes "<Team>.png" -- matching the short_opponent names used elsewhere in the app.
from urllib.parse import unquote as _logo_unquote

_LOGO_DIR = os.path.join(APP_DATA_DIR, "logo")
os.makedirs(_LOGO_DIR, exist_ok=True)

_LOGO_URL_PATTERN_1 = "https://download.fastmodeltechnologies.com/FSimages/logos/NCAAB-III/"
_LOGO_URL_PATTERN_2 = "https://stats-assets.fastmodelsports.com/images/teams/"

_logo_mhtml_files = sorted(glob.glob(f"{volume_dir}/*.mhtml"))

_logos_saved = {}
for _mf in _logo_mhtml_files:
    with open(_mf, "rb") as _f:
        _raw = _f.read()
    _msg = email.message_from_bytes(_raw, policy=policy.default)
    for _part in _msg.walk():
        _loc = _part.get("Content-Location", "")
        _ct = _part.get_content_type()
        if not _ct.startswith("image/"):
            continue
        _team_name = None
        if _LOGO_URL_PATTERN_1 in _loc:
            _team_name = _logo_unquote(_loc.replace(_LOGO_URL_PATTERN_1, "").replace(".png", ""))
        elif _LOGO_URL_PATTERN_2 in _loc:
            _team_name = _logo_unquote(_loc.split("/")[-1])
        if _team_name and _team_name not in _logos_saved:
            _payload = _part.get_payload(decode=True)
            if _payload and len(_payload) > 100:
                _filepath = os.path.join(_LOGO_DIR, f"{_team_name}.png")
                with open(_filepath, "wb") as _out:
                    _out.write(_payload)
                _logos_saved[_team_name] = len(_payload)

print(f"Saved {len(_logos_saved)} team logos to {_LOGO_DIR}:")
for _name in sorted(_logos_saved):
    print(f"  - {_name} ({_logos_saved[_name]:,} bytes)")


# ---- The upcoming opponent's logo, when no saved page had it --------------------------------------------------------
# CONFIRMED BUG (fixed; "Missing the MSOE logo"): logos only came from the saved UWW play-by-play / schedule pages, so an
# opponent UWW never played that season (the MSOE scrimmage, EXTRA_GAMES) had no crest in the app or the brief. When the
# upcoming opponent has no logo on file, it's fetched from FastScout: first the public logo address by their name, then
# (if that misses) the logo shown on their FastScout team page. Saved as "<their short name>.png". LOGO_FETCH_UPCOMING = False
# turns this off.
def _logo_have(*names):
    stems = sorted((os.path.splitext(f)[0] for f in os.listdir(_LOGO_DIR) if f.lower().endswith(".png")), key=len, reverse=True)
    for n in names:
        n = str(n or "").strip()
        if not n:
            continue
        if n in stems or any(n.startswith(s) and len(s) >= 3 for s in stems) or any(s.startswith(n) and len(n) >= 3 for s in stems):
            return True
    return False


def _logo_is_image(b):
    return bool(b) and len(b) > 100 and (b[:8] == b"\x89PNG\r\n\x1a\n" or b[:3] == b"\xff\xd8\xff" or b[:4] in (b"RIFF", b"GIF8"))


def _logo_fetch_public(names):
    import urllib.request
    from urllib.parse import quote
    for n in names:
        for base in (_LOGO_URL_PATTERN_1, _LOGO_URL_PATTERN_2):
            url = base + quote(n) + (".png" if base == _LOGO_URL_PATTERN_1 else "")
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10) as r:
                    b = r.read()
                if _logo_is_image(b):
                    return b, url
            except Exception:
                continue
    return None, None


def _logo_fetch_from_team_page(team_url, words):
    def _job(page):
        page.goto(team_url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        imgs = page.evaluate("""() => Array.from(document.images).map(i => ({src: i.currentSrc || i.src || '', alt: i.alt || '',
                                    w: i.naturalWidth || 0}))""")
        cands = [i for i in imgs if re.search(r"/logos/|/images/teams/|logo", i["src"], re.I) and i["w"] >= 20]
        cands = [i for i in cands if not re.search(r"whitewater|fastmodel[^/]*/(?:img|assets)/|hudl", i["src"] + " " + i["alt"], re.I)]
        cands.sort(key=lambda i: -sum(w in (i["src"] + " " + i["alt"]).lower() for w in words))
        for i in cands:
            src = i["src"]
            try:
                if src.startswith("data:image"):
                    import base64
                    b = base64.b64decode(src.split(",", 1)[1])
                else:
                    b = page.request.get(src, timeout=20000).body()
                if _logo_is_image(b):
                    return b, src
            except Exception:
                continue
        return None, None
    return run_in_fastscout_session(_job)


if globals().get("LOGO_FETCH_UPCOMING", True) and globals().get("upcoming_opponent"):
    _lo_short = str(globals().get("upcoming_opponent_short") or upcoming_opponent).strip()
    _lo_full = str(upcoming_opponent).strip()
    if _logo_have(_lo_short, _lo_full):
        pass
    else:
        _lo_words = [w for w in re.split(r"[^a-z0-9]+", _lo_full.lower()) if len(w) > 2]
        _lo_names = list(dict.fromkeys(n for n in (_lo_short, _lo_full, " ".join(_lo_full.split()[:-1]),
                                                    _lo_full.split()[0] if _lo_full.split() else "") if n))
        _lo_bytes, _lo_src = _logo_fetch_public(_lo_names)
        if _lo_bytes is None:
            _lo_url = None
            for _sn in ("uww_team_schedule", "schedule"):
                _s = globals().get(_sn)
                if isinstance(_s, pd.DataFrame) and "Upcoming" in _s.columns and "opponent_url" in _s.columns:
                    _u = _s.loc[_s["Upcoming"] == "Yes", "opponent_url"].dropna()
                    if len(_u):
                        _lo_url = str(_u.iloc[0])
                        break
            if _lo_url:
                try:
                    _lo_bytes, _lo_src = _logo_fetch_from_team_page(_lo_url, _lo_words)
                except Exception as _le:
                    print(f"  [logo] couldn't open {_lo_full}'s FastScout page ({type(_le).__name__}: {_le})")
        if _lo_bytes is not None:
            _lo_path = os.path.join(_LOGO_DIR, re.sub(r'[\\/:*?"<>|]+', "_", _lo_short) + ".png")
            with open(_lo_path, "wb") as _out:
                _out.write(_lo_bytes)
            print(f"  Upcoming opponent's logo wasn't on file -- saved {os.path.basename(_lo_path)} from {_lo_src}")
        else:
            print(f"  !! No logo found for the upcoming opponent ({_lo_full}). Save their logo as "
                  f"{os.path.join(_LOGO_DIR, _lo_short + '.png')} by hand to show it in the app and brief.")
