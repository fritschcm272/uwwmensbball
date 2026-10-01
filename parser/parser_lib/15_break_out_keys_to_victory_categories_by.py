# 15_break_out_keys_to_victory_categories_by.py -- code for the notebook section "For each per-game "Keys to Victory" category (from the win/loss-splits cell above), break "
# Runs inside the notebook via run_section("15_break_out_keys_to_victory_categories_by"); its settings are in that notebook cell.

# For each per-game "Keys to Victory" category (from the win/loss-splits cell above), break out the SCOUTED
# OPPONENT's own production in that category by role -- Starter vs. Bench -- using the season stats merged onto
# player_profiles. This shows whether an emphasis like "own the glass" was really about containing the
# opponent's starting five or their bench unit.
for col, cat in STAT_COL_CATEGORY.items():
    CATEGORY_TO_STAT_COLS.setdefault(cat, []).append(col)


def parse_numeric_stat(val):
    s = str(val).strip()
    if s in ("", "-", "nan", "None"):
        return None
    if s.endswith("%"):
        return float(s.rstrip("%"))
    if "-" in s and not s.startswith("-"):
        try:
            return float(s.split("-")[0])  # compound "made-attempted" string -- use the made count
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None

role_breakdown_rows = []
for _, row in game_categories.iterrows():
    if row["category"] == "(no matched category)":
        continue
    stat_cols = [c for c in CATEGORY_TO_STAT_COLS.get(row["category"], []) if c in player_profiles.columns]
    if not stat_cols:
        continue
    opp_players = player_profiles[player_profiles["opponent"] == row["opponent"]]
    for role in ["Starter", "Bench"]:
        role_players = opp_players[opp_players["role"] == role]
        if role_players.empty:
            continue
        for col in stat_cols:
            vals = role_players[col].apply(parse_numeric_stat)
            if vals.notna().any():
                role_breakdown_rows.append({
                    "opponent": row["opponent"], "outcome": row["outcome"], "category": row["category"],
                    "role": role, "stat": col, "players_with_data": int(vals.notna().sum()),
                    "avg_per_player": round(vals.mean(), 2),
                    "role_total": round(vals.sum(), 2) if col in COUNT_STATS else None,
                })

role_breakdown = pd.DataFrame(
    role_breakdown_rows,
    columns=["opponent", "outcome", "category", "role", "stat", "players_with_data", "avg_per_player", "role_total"],
)
print("Opponent production by role (Starter vs Bench) for the stat(s) behind each matched Keys-to-Victory category:")
print(role_breakdown)

count_stat_rows = role_breakdown[role_breakdown["stat"].isin(COUNT_STATS)]
if not count_stat_rows.empty:
    pivot = count_stat_rows.pivot_table(
        index=["opponent", "category", "stat"], columns="role", values="role_total", aggfunc="first"
    ).reset_index()
    for r in ["Starter", "Bench"]:
        if r not in pivot.columns:
            pivot[r] = 0.0
    pivot["starter_share"] = (pivot["Starter"] / (pivot["Starter"] + pivot["Bench"]).replace(0, pd.NA)).round(3)
    print("\nStarter vs Bench totals for count-type stats, side-by-side (starter_share near 1 = concentrated among "
          "starters; near 0 = bench-driven):")
    print(pivot.sort_values(["opponent", "category", "stat"]))
else:
    print("No count-type stats available yet to compare Starter vs Bench totals for the matched categories.")
