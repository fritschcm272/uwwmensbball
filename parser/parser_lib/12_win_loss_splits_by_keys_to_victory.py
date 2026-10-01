# 12_win_loss_splits_by_keys_to_victory.py -- code for the notebook section "Win/loss splits by "Keys to Victory" category WITH SIDE ATTRIBUTION (UWW vs OPP)."
# Runs inside the notebook via run_section("12_win_loss_splits_by_keys_to_victory"); its settings are in that notebook cell.

# Win/loss splits by "Keys to Victory" category WITH SIDE ATTRIBUTION (UWW vs OPP).
# Each matched phrase now carries a "side" from PHRASE_SIDE: UWW = what Whitewater proactively does (offense/
# hustle), OPP = what Whitewater does to CONTAIN the opponent (defense/discipline). This answers the coaching
# question: "When we emphasize attacking the rim ourselves (UWW) vs limiting THEIR rim attacks (OPP), which
# approach correlates with winning?"
# The stat-category grouping is unchanged (rebounding columns still roll up to "Rebounding"), but now each
# game-category row also carries its side, so splits can be cut both ways.
STAT_COL_CATEGORY = {
    "TO": "Ball Security / Turnovers", "STL": "Perimeter Defense / Ball Pressure",
    "REB": "Rebounding", "ORB": "Rebounding", "DRB": "Rebounding",
    "3PM-A": "Three-Point Shooting", "3P%": "Three-Point Shooting",
    "FTM-A": "Free Throws", "FT%": "Free Throws",
    "PF": "Fouls / Discipline",
    "AST": "Ball Movement / Assists",
    "BLK": "Paint Protection / Blocks",
    "FG2M": "Scoring Inside", "FG2A": "Scoring Inside", "FG2%": "Scoring Inside",
    "FGM-A": "Field Goal Efficiency", "FG%": "Field Goal Efficiency",
}

SIDE_DISPLAY_LABELS = {
    ("Ball Security / Turnovers", "UWW"): "UWW: Protect the Ball",
    ("Ball Security / Turnovers", "OPP"): "OPP: Force Turnovers",
    ("Rebounding", "UWW"): "UWW: Crash the Boards",
    ("Rebounding", "OPP"): "OPP: Limit Their Rebounding",
    ("Three-Point Shooting", "UWW"): "UWW: Hit Our Threes",
    ("Three-Point Shooting", "OPP"): "OPP: Contest Their Shooting",
    ("Free Throws", "UWW"): "UWW: Get to the FT Line",
    ("Free Throws", "OPP"): "OPP: Keep Them Off the Line",
    ("Fouls / Discipline", "UWW"): "UWW: Stay Disciplined",
    ("Fouls / Discipline", "OPP"): "OPP: They Draw Fouls",
    ("Ball Movement / Assists", "UWW"): "UWW: Share the Ball",
    ("Ball Movement / Assists", "OPP"): "OPP: Disrupt Their Ball Movement",
    ("Perimeter Defense / Ball Pressure", "UWW"): "UWW: Create Pressure",
    ("Perimeter Defense / Ball Pressure", "OPP"): "OPP: On-Ball Defense",
    ("Paint Protection / Blocks", "UWW"): "UWW: Protect Our Rim",
    ("Paint Protection / Blocks", "OPP"): "OPP: Limit Their Interior",
    ("Scoring Inside", "UWW"): "UWW: Attack the Paint",
    ("Scoring Inside", "OPP"): "OPP: Limit Their Inside Scoring",
    ("Field Goal Efficiency", "UWW"): "UWW: Efficient Shooting",
    ("Field Goal Efficiency", "OPP"): "OPP: Limit Their FG Efficiency",
}

def categories_for_note(note_text):
    """Return list of (category, side) tuples matched from note text."""
    text = str(note_text).lower()
    seen = set()
    results = []
    for phrase, stat_cols in KEYS_TO_VICTORY_STAT_MAP.items():
        if phrase in text:
            side = PHRASE_SIDE.get(phrase, "UWW")  # default to UWW if not explicitly listed
            for c in stat_cols:
                cat = STAT_COL_CATEGORY.get(c)
                if cat and (cat, side) not in seen:
                    seen.add((cat, side))
                    results.append((cat, side))
    return sorted(results)

def stat_cols_for_note(note_text):
    """Legacy helper: just the stat columns (no side), used by downstream How We Stack Up."""
    text = str(note_text).lower()
    cols = []
    for phrase, stat_cols in KEYS_TO_VICTORY_STAT_MAP.items():
        if phrase in text:
            for c in stat_cols:
                if c not in cols:
                    cols.append(c)
    return cols

game_category_rows = []
for _, row in scouted_game_comparison.iterrows():
    keys_to_victory = all_game_plans.loc[
        (all_game_plans["opponent"] == row["opponent"]) & (all_game_plans["topic"] == "KEYS TO VICTORY"), "notes"
    ]
    if keys_to_victory.empty:
        continue
    cat_sides = categories_for_note(keys_to_victory.iloc[0])
    if not cat_sides:
        game_category_rows.append({"opponent": row["opponent"], "outcome": row["outcome"], "category": "(no matched category)", "side": ""})
    for cat, side in cat_sides:
        game_category_rows.append({"opponent": row["opponent"], "outcome": row["outcome"], "category": cat, "side": side})

game_categories = pd.DataFrame(game_category_rows)
print("Per-game 'Keys to Victory' categories detected WITH SIDE ATTRIBUTION:")
print("  UWW = what Whitewater does proactively (attack, score, rebound, share)")
print("  OPP = what Whitewater does to contain the opponent (guard, force TOs, limit, pressure)")
print(game_categories)

if not game_categories.empty:
    # Granular splits: by category + side
    game_categories["display_label"] = game_categories.apply(
        lambda r: SIDE_DISPLAY_LABELS.get((r["category"], r["side"]), f"{r['side']}: {r['category']}"), axis=1
    )
    splits = (
        game_categories.groupby(["category", "side", "display_label"])["outcome"]
        .agg(games="count", wins=lambda s: (s == "W").sum(), losses=lambda s: (s == "L").sum())
        .reset_index()
        .sort_values(["category", "side"], ascending=[True, True])
    )
    splits["win_pct"] = (splits["wins"] / splits["games"]).round(3)
    print("\nWin/loss splits by category + side (UWW vs OPP emphasis):")
    print(splits[["display_label", "side", "category", "games", "wins", "losses", "win_pct"]])
else:
    print("No 'Keys to Victory' notes with a matched category yet.")
