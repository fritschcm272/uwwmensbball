# 40_classify_each_on_court_opponent_lineup.py -- code for the notebook section "Classify each on-court OPPONENT 5-man unit using its players' scouting-report data -------"
# Runs inside the notebook via run_section("40_classify_each_on_court_opponent_lineup"); its settings are in that notebook cell.

# --- Classify each on-court OPPONENT 5-man unit using its players' scouting-report data -----------------------
# One new field, opp_lineup_summary, describing the specific opponent lineup on the floor: role composition
# (Starter/Bench), position composition, and each player's most common notes_tags/keys_tags. There's no
# equivalent field for uww_lineup -- UW-Whitewater is "us", not a scouted opponent, so player_profiles has no
# scouting-report rows for our own roster to classify it with.
def summarize_lineup(opponent, lineup_str):
    if pd.isna(lineup_str):
        return None
    names = lineup_str.split(", ")
    rows = player_profiles[(player_profiles["opponent"] == opponent) & (player_profiles["name"].isin(names))]
    if rows.empty:
        return f"No scouting data found for: {', '.join(names)}"
    unmatched = [n for n in names if n not in set(rows["name"])]

    role_summary = " / ".join(f"{count} {role}" for role, count in rows["role"].value_counts().items())
    pos_summary = ", ".join(f"{count} {pos}" for pos, count in rows["position_group"].value_counts().items())

    notes_tag_counts = Counter(tag for tags in rows["notes_tags"] for tag in tags)
    keys_tag_counts = Counter(tag for tags in rows["keys_tags"] for tag in tags)
    top_notes = ", ".join(f"{tag} x{n}" for tag, n in notes_tag_counts.most_common(3))
    top_keys = ", ".join(f"{tag} x{n}" for tag, n in keys_tag_counts.most_common(3))

    parts = [
        role_summary,
        f"Pos: {pos_summary}",
        f"Style: {top_notes}" if top_notes else "Style: (no tagged traits)",
        f"Defend: {top_keys}" if top_keys else "Defend: (no tagged traits)",
    ]
    if unmatched:
        parts.append(f"No scouting match: {', '.join(unmatched)}")
    return " | ".join(parts)

unique_opp_lineups = pbp_events[["opponent", "opp_lineup"]].drop_duplicates().dropna().copy()
unique_opp_lineups["opp_lineup_summary"] = unique_opp_lineups.apply(
    lambda r: summarize_lineup(r["opponent"], r["opp_lineup"]), axis=1
)
# Drop any stale opp_lineup_summary from a previous run before merging, so re-running this cell overwrites
# cleanly instead of colliding into opp_lineup_summary_x/_y.
pbp_events = pbp_events.drop(columns=["opp_lineup_summary"], errors="ignore").merge(unique_opp_lineups, on=["opponent", "opp_lineup"], how="left")

print(
    pbp_events[["opponent", "opp_lineup", "opp_lineup_summary"]]
    .drop_duplicates(subset=["opponent", "opp_lineup"])
    .sort_values("opponent")
)
