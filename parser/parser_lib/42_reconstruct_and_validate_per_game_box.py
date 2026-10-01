# 42_reconstruct_and_validate_per_game_box.py -- code for the notebook section "Reconstruct a real single-game box score from the play-by-play, and sanity-check it agains"
# Runs inside the notebook via run_section("42_reconstruct_and_validate_per_game_box"); its settings are in that notebook cell.

player_events = pbp_events[
    pbp_events["player"].notna() & (~pbp_events["event_type"].isin(TEAM_LEVEL_EVENT_TYPES_BOX))
].copy()

player_events["points"] = player_events.apply(
    lambda row: int(row["shot_type"]) if row["event_type"] == "made_shot" else (1 if row["event_type"] == "free_throw_made" else 0),
    axis=1,
)
player_events["is_fgm"] = player_events["event_type"] == "made_shot"
player_events["is_fga"] = player_events["event_type"].isin(["made_shot", "missed_shot"])
player_events["is_3pm"] = player_events["is_fgm"] & (player_events["shot_type"] == "3")
player_events["is_3pa"] = player_events["is_fga"] & (player_events["shot_type"] == "3")
player_events["is_ftm"] = player_events["event_type"] == "free_throw_made"
player_events["is_fta"] = player_events["event_type"].isin(["free_throw_made", "free_throw_missed"])
player_events["is_oreb"] = player_events["event_type"] == "rebound_offensive"
player_events["is_dreb"] = player_events["event_type"] == "rebound_defensive"
player_events["is_ast"] = player_events["event_type"] == "assist"
player_events["is_stl"] = player_events["event_type"] == "steal"
player_events["is_blk"] = player_events["event_type"] == "block"
player_events["is_to"] = player_events["event_type"] == "turnover"
player_events["is_pf"] = player_events["event_type"] == "foul"

pbp_box_score = player_events.groupby(["opponent", "game_date", "team", "player"]).agg(
    PTS=("points", "sum"), FGM=("is_fgm", "sum"), FGA=("is_fga", "sum"),
    FG3M=("is_3pm", "sum"), FG3A=("is_3pa", "sum"), FTM=("is_ftm", "sum"), FTA=("is_fta", "sum"),
    OREB=("is_oreb", "sum"), DREB=("is_dreb", "sum"), AST=("is_ast", "sum"), STL=("is_stl", "sum"),
    BLK=("is_blk", "sum"), TO=("is_to", "sum"), PF=("is_pf", "sum"),
).reset_index()

# CONFIRMED GAP (fixed here): a bare team-level turnover (e.g. "Turnover (Offensive Foul)" with no player
# attached -- see classify_event's dedicated pattern for this) is correctly excluded from player_events above
# via the player.notna() filter, since there's no player to attribute it to. But that also means it never
# showed up ANYWHERE in the box score -- not on a player's line, and not accounted for at all -- so the box
# score's total turnover count silently undercounted the real game total by however many of these occurred.
# Surfaced here as a synthetic "TEAM" row per (opponent, game_date, team) instead, so these are visible rather
# than silently dropped.
_team_level_turnovers = pbp_events[pbp_events["player"].isna() & (pbp_events["event_type"] == "turnover")]
if not _team_level_turnovers.empty:
    _team_to_rows = _team_level_turnovers.groupby(["opponent", "game_date", "team"]).size().reset_index(name="TO")
    _team_to_rows["player"] = "TEAM"
    for _stat_col in ["PTS", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "DREB", "AST", "STL", "BLK", "PF"]:
        _team_to_rows[_stat_col] = 0
    pbp_box_score = pd.concat([pbp_box_score, _team_to_rows], ignore_index=True)
    print(f"Added {len(_team_to_rows)} synthetic TEAM row(s) for {int(_team_to_rows['TO'].sum())} bare (unattributed) team-level turnover(s) that would otherwise be missing from the box score entirely.")

pbp_box_score["REB"] = pbp_box_score["OREB"] + pbp_box_score["DREB"]
pbp_box_score["FG%"] = (100 * pbp_box_score["FGM"] / pbp_box_score["FGA"]).round(1)
pbp_box_score["3P%"] = (100 * pbp_box_score["FG3M"] / pbp_box_score["FG3A"]).round(1)
pbp_box_score["FT%"] = (100 * pbp_box_score["FTM"] / pbp_box_score["FTA"]).round(1)

starters_by_game = {}
for (opponent, game_date), group in pbp_events.groupby(GAME_KEYS, dropna=False):
    first_row = group.sort_values("event_order").iloc[0]
    starters_by_game[(opponent, game_date)] = {
        "UW-Whitewater": set(first_row["uww_lineup"].split(", ")) if pd.notna(first_row["uww_lineup"]) else set(),
        opponent: set(first_row["opp_lineup"].split(", ")) if pd.notna(first_row["opp_lineup"]) else set(),
    }
pbp_box_score["started"] = pbp_box_score.apply(
    lambda row: row["player"] in starters_by_game.get((row["opponent"], row["game_date"]), {}).get(row["team"], set()), axis=1
)

pbp_team_totals = pbp_box_score.groupby(["opponent", "game_date", "team"])["PTS"].sum().reset_index()
print("Validating PBP-reconstructed final scores against the schedule:\n")
# Matched on BOTH opponent and date. A name-only match returns the first meeting for every rematch,
# so a merged game would silently "validate" against the wrong row (or appear to be off by exactly
# the other meeting's score) instead of being reported.
_n_ok = _n_bad = 0
for (opponent, game_date) in pbp_events[GAME_KEYS].dropna(subset=["opponent"]).drop_duplicates().itertuples(index=False):
    cand = schedule[schedule["opponent"].str.contains(re.escape(opponent), case=False, na=False)].copy()
    cand = cand[cand["date"].apply(parse_schedule_date) == game_date] if game_date is not None else cand
    if cand.empty:
        print(f"  {opponent} {game_date}: no matching schedule row found -- can't validate.")
        continue
    sched_row = cand.iloc[0]
    sel = (pbp_team_totals["opponent"] == opponent) & (pbp_team_totals["game_date"] == game_date)
    uww_pts = pbp_team_totals[sel & (pbp_team_totals["team"] == "UW-Whitewater")]["PTS"]
    opp_pts = pbp_team_totals[sel & (pbp_team_totals["team"] == opponent)]["PTS"]
    uww_val = int(uww_pts.iloc[0]) if not uww_pts.empty else None
    opp_val = int(opp_pts.iloc[0]) if not opp_pts.empty else None
    ok = (uww_val, opp_val) == (sched_row["team_score"], sched_row["opponent_score"])
    _n_ok, _n_bad = _n_ok + ok, _n_bad + (not ok)
    status = "OK" if ok else "MISMATCH -- check parsing for this game"
    print(f"  {opponent} {game_date}: PBP {uww_val}-{opp_val} vs. schedule "
          f"{sched_row['team_score']}-{sched_row['opponent_score']} [{status}]")
    for team_label in ["UW-Whitewater", opponent]:
        starters_list = sorted(starters_by_game.get((opponent, game_date), {}).get(team_label, set()))
        print(f"    {team_label} starters: {', '.join(starters_list) if starters_list else '(not detected)'}")
print(f"\n{_n_ok} game(s) reconcile exactly, {_n_bad} do not.")
_dupes = pbp_box_score.groupby(["opponent", "game_date", "team", "player"]).size()
_dupes = _dupes[_dupes > 1]
if len(_dupes):
    print(f"WARNING: {len(_dupes)} duplicated (opponent, game_date, team, player) key(s) -- two files for one game?")

print(pbp_box_score.sort_values(["opponent", "PTS"], ascending=[True, False])[[
    "opponent", "game_date", "team", "player", "started", "PTS", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA",
    "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "FG%", "3P%", "FT%",
]])

# --- Cross-validate the PBP-reconstructed box score against the official per-game box-score snapshot ----------
box_files = sorted(glob.glob(f"{volume_dir}/*_box.mhtml"))
print(f"\nFound {len(box_files)} official box-score file(s) to cross-validate against:")
for f in box_files:
    print(" -", os.path.basename(f))

def parse_box_mhtml(path):
    html = load_mhtml_html(path)
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    score_df = pd.read_html(StringIO(str(tables[0])))[0]
    team_order = score_df.iloc[:, 2].tolist()
    frames = []
    for team_name, table in zip(team_order, tables[1:]):
        pdf = pd.read_html(StringIO(str(table)))[0]
        pdf["team"] = team_name
        frames.append(pdf)
    box_df = pd.concat(frames, ignore_index=True)
    box_df["started"] = box_df["PLAYER"].astype(str).str.endswith("*")
    box_df["player"] = box_df["PLAYER"].astype(str).str.rstrip("*").str.strip()
    box_df = box_df[~box_df["player"].str.contains("Team Total", case=False)]
    for pair_col, (m_col, a_col) in {"FGM-A": ("FGM", "FGA"), "3PM-A": ("FG3M", "FG3A"), "FTM-A": ("FTM", "FTA")}.items():
        split = box_df[pair_col].astype(str).replace("-", "0-0").str.split("-", n=1, expand=True)
        box_df[m_col] = pd.to_numeric(split[0], errors="coerce").fillna(0)
        box_df[a_col] = pd.to_numeric(split[1], errors="coerce").fillna(0)
    for c in ["PTS", "REB", "AST", "TO", "STL", "BLK", "PF"]:
        box_df[c] = pd.to_numeric(box_df[c], errors="coerce").fillna(0)
    return box_df[["team", "player", "started", "PTS", "REB", "AST", "TO", "STL", "BLK", "PF",
                   "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA"]]

box_stat_cols = ["PTS", "REB", "AST", "TO", "STL", "BLK", "PF", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA"]
print("\nValidating PBP-reconstructed per-player box score against the official box-score file, where available:\n")
for path in box_files:
    m = re.search(r"@ (.+)_box\.mhtml$", os.path.basename(path))
    opponent_short = m.group(1) if m else os.path.basename(path)
    official_box = parse_box_mhtml(path)
    pbp_slice = pbp_box_score[pbp_box_score["opponent"] == opponent_short]
    if pbp_slice.empty:
        print(f"{opponent_short}: no PBP-reconstructed box score found for this opponent -- skipping.\n")
        continue

    merged = official_box.merge(pbp_slice, on=["team", "player"], how="outer", suffixes=("_official", "_pbp"), indicator=True)
    only_official = merged[merged["_merge"] == "left_only"]
    only_pbp = merged[merged["_merge"] == "right_only"]
    both = merged[merged["_merge"] == "both"]

    n_stat_mismatch = 0
    n_started_mismatch = 0
    for _, r in both.iterrows():
        stat_mismatches = [c for c in box_stat_cols if r[f"{c}_official"] != r[f"{c}_pbp"]]
        started_mismatch = r["started_official"] != r["started_pbp"]
        if stat_mismatches or started_mismatch:
            detail = []
            if stat_mismatches:
                detail.append("; ".join(f"{c} official={r[f'{c}_official']} vs pbp={r[f'{c}_pbp']}" for c in stat_mismatches))
            if started_mismatch:
                detail.append(f"started official={r['started_official']} vs pbp={r['started_pbp']}")
            print(f"  MISMATCH {opponent_short} {r['team']} {r['player']}: {'; '.join(detail)}")
            n_stat_mismatch += bool(stat_mismatches)
            n_started_mismatch += bool(started_mismatch)
    for _, r in only_official.iterrows():
        print(f"  {opponent_short} {r['team']} {r['player']}: in official box score but missing from PBP reconstruction")
    for _, r in only_pbp.iterrows():
        print(f"  {opponent_short} {r['team']} {r['player']}: in PBP reconstruction but missing from official box score")

    status = (
        "OK" if not (n_stat_mismatch or n_started_mismatch or len(only_official) or len(only_pbp))
        else f"{n_stat_mismatch} stat mismatch(es), {n_started_mismatch} started mismatch(es), "
             f"{len(only_official)} missing-from-PBP, {len(only_pbp)} extra-in-PBP"
    )
    print(f"{opponent_short}: {len(both)} player(s) compared against the official box score -- [{status}]\n")
