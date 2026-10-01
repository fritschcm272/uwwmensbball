# 37_load_coach_tagged_recap_csvs.py -- code for the notebook section "Playbook catalog: the team's own play index (Hudl "Plays" page, saved as MHTML) ----------"
# Runs inside the notebook via run_section("37_load_coach_tagged_recap_csvs"); its settings are in that notebook cell.

# --- Playbook catalog: the team's own play index (Hudl "Plays" page, saved as MHTML) -------------------
# Every other source names a play differently -- the season play log writes 'Panther-4 "P4"', a coach's
# clip note might say "P-4", "P4" or "PANTHER 4" -- so without a canonical list they count as separate
# plays everywhere downstream. This catalog is that list: the play's real name, the SERIES it belongs to,
# the shorthand the staff actually types, and a set of normalized match keys the app resolves against.
import io



def _play_norm(text):
    """Match key: uppercase, letters and digits only -- "P-4"/"P 4"/"p4" all collapse to "P4"."""
    return re.sub(r"[^A-Z0-9]", "", str(text).upper())


plays_catalog_paths = sorted(
    p for p in glob.glob(f"{INPUT_DIR}/*.mhtml") + glob.glob(f"{INPUT_DIR}/*.html")
    if re.search(r"plays\.(mhtml|html)$", os.path.basename(p), re.IGNORECASE)
)
print(f"Found {len(plays_catalog_paths)} playbook catalog file(s):")
for p in plays_catalog_paths:
    print(" -", os.path.basename(p))

_pc_frames = []
for path in plays_catalog_paths:
    try:
        _pc_html = load_html_snapshot(path)
    except Exception as e:
        print(f"  Could not read {os.path.basename(path)}: {type(e).__name__}: {e}")
        continue
    if not _pc_html:
        continue
    try:
        _pc_tables = pd.read_html(io.StringIO(_pc_html))
    except ValueError:
        print(f"  {os.path.basename(path)}: no HTML tables found -- skipping.")
        continue
    # The page renders one filter row and one data table; take whichever table actually holds play rows
    # (a real season value like "2025-26" and a play name) rather than trusting table order.
    for _t in _pc_tables:
        if _t.shape[1] < 6:
            continue
        _sub = _t.iloc[:, 2:6].copy()
        _sub.columns = ["season", "team", "series", "play_name"]
        _sub = _sub[
            _sub["season"].astype(str).str.match(r"^\d{4}-\d{2}$", na=False)
            & _sub["play_name"].notna()
            & (_sub["team"].astype(str).str.upper().str.strip() != "ALL")
        ]
        if not _sub.empty:
            _pc_frames.append(_sub)

if _pc_frames:
    plays_catalog = pd.concat(_pc_frames, ignore_index=True)
    plays_catalog = plays_catalog.drop_duplicates(subset=["season", "team", "play_name"]).reset_index(drop=True)
    for _c in ("season", "team", "series", "play_name"):
        plays_catalog[_c] = plays_catalog[_c].astype(str).str.strip()
    # Shorthand the staff types lives in quotes inside the play name: 'Panther-4 "P4"' -> alias "P4",
    # base name "Panther-4". A play whose whole name is quoted (the ELOB set '"20"') has no base name --
    # its family falls back to the SERIES rather than being left blank.
    plays_catalog["aliases"] = plays_catalog["play_name"].apply(
        lambda n: "|".join(re.findall(r'"([^"]+)"', str(n)))
    )
    plays_catalog["base_name"] = plays_catalog["play_name"].apply(
        lambda n: re.sub(r'"[^"]*"', "", str(n)).strip()
    )
    plays_catalog["play_family"] = plays_catalog.apply(
        lambda r: (re.match(r"[A-Za-z]+", r["base_name"]).group(0) if re.match(r"[A-Za-z]+", r["base_name"]) else r["series"]),
        axis=1,
    )
    plays_catalog["match_keys"] = plays_catalog.apply(
        lambda r: "|".join(sorted({
            k for k in (
                [_play_norm(r["play_name"]), _play_norm(r["base_name"])]
                + [_play_norm(a) for a in str(r["aliases"]).split("|") if a]
            ) if k
        })),
        axis=1,
    )
    plays_catalog = plays_catalog[PLAYS_CATALOG_COLS]
    print(f"\nParsed {len(plays_catalog)} play(s) across {plays_catalog['series'].nunique()} series "
          f"and {plays_catalog['play_family'].nunique()} family/families.")
    print(plays_catalog[["series", "play_family", "play_name", "aliases"]].to_string(index=False))
else:
    plays_catalog = pd.DataFrame(columns=PLAYS_CATALOG_COLS)
    print("No playbook catalog parsed -- play calls will be used exactly as they appear in the source data.")
