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
