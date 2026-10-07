# 39_reconstruct_on_court_5_man_lineup_for_both.py -- code for the notebook section "On-court 5-man lineups for both teams, at every point in the play-by-play ----------------"
# Runs inside the notebook via run_section("39_reconstruct_on_court_5_man_lineup_for_both"); its settings are in that notebook cell.

# --- On-court 5-man lineups for both teams, at every point in the play-by-play -----------------------------
# Reconstructed purely from substitution events ("Subs In"/"Subs Out") plus a starting lineup inferred from each
# player's FIRST event of the game: if a player's first action is anything other than "Subs In", they were
# already on the floor at tip-off (a starter); if their first action IS "Subs In", they came off the bench.
# Dead-ball substitutions almost always swap multiple players for a team at the EXACT same game-clock time, so
# subs are applied as an atomic batch per (opponent, team, period, time_remaining_seconds) -- applying them one
# row at a time would otherwise show a transient 4-man lineup between an "out" row and its matching "in" row.
# Excludes every TEAM-level event whose "player" field is actually a team name, not a roster player.
real_player_events = pbp_events[
    pbp_events["player"].notna() & (~pbp_events["event_type"].isin(TEAM_LEVEL_EVENT_TYPES))
].sort_values("event_order")

def starting_lineup(team_events):
    first_seen = team_events.groupby("player").first()
    return set(first_seen[first_seen["event_type"] != "sub_in"].index)

uww_lineup_col = pd.Series(index=pbp_events.index, dtype=object)
opp_lineup_col = pd.Series(index=pbp_events.index, dtype=object)

for (opponent, game_date), opp_rows in pbp_events.groupby(GAME_KEYS, dropna=False):
    opp_real = real_player_events[
        (real_player_events["opponent"] == opponent) & (real_player_events["game_date"] == game_date)
    ]

    # Period start anchors are shared by BOTH teams: the true boundary for a period is the earliest real event
    # across EITHER team tagged with that period, not just one team's own subset.
    period_starts = opp_real.dropna(subset=["period"]).groupby("period")["event_order"].min().sort_values()
    periods_in_order = period_starts.index.tolist()

    for team_label, target_col in [("UW-Whitewater", uww_lineup_col), (opponent, opp_lineup_col)]:
        team_events = opp_real[opp_real["team"] == team_label]

        # Re-infer the starting five FRESH at the start of EVERY period (H1, H2, OT...), not just tip-off.
        changes = []
        for period in periods_in_order:
            period_events = team_events[team_events["period"] == period].sort_values("event_order")
            starters = starting_lineup(period_events)
            if len(starters) != 5:
                print(f"WARNING: {opponent} {game_date}/{team_label}/{period} starting-lineup detection found {len(starters)} "
                      f"players (expected 5): {sorted(starters)}")

            # Apply substitutions one at a time in chronological order, but only RECORD a new change-point once
            # the running set settles back at exactly 5.
            current = set(starters)
            changes.append((period_starts[period] - 1, frozenset(current)))
            sub_events = period_events[period_events["event_type"].isin(["sub_in", "sub_out"])].sort_values("event_order")
            for _, row in sub_events.iterrows():
                if row["event_type"] == "sub_in":
                    current.add(row["player"])
                else:
                    current.discard(row["player"])
                if len(current) == 5:
                    changes.append((row["event_order"], frozenset(current)))
            if len(current) != 5:
                print(f"WARNING: {opponent} {game_date}/{team_label}/{period} never settled back to a 5-man lineup by the "
                      f"last substitution (ended with {len(current)}): {sorted(current)}")

        changes_df = pd.DataFrame(changes, columns=["event_order", "lineup"]).sort_values("event_order")
        target_rows = opp_rows.sort_values("event_order")
        merged = pd.merge_asof(target_rows[["event_order"]], changes_df, on="event_order", direction="backward")
        lineup_strings = merged["lineup"].apply(lambda s: ", ".join(sorted(s)) if isinstance(s, frozenset) else None)
        lineup_strings.index = target_rows.index
        target_col.loc[target_rows.index] = lineup_strings

pbp_events["uww_lineup"] = uww_lineup_col
pbp_events["opp_lineup"] = opp_lineup_col

# ---- Swapped lineup columns, fixed at the source --------------------------------------------------------
# One game (vs Aurora) came out with uww_lineup and opp_lineup the wrong way round, and every consumer
# (the Keys to Victory cell, the app) was excluding that OPPONENT outright to compensate. That discarded
# every game against them -- including, now that Aurora is the upcoming opponent, the most relevant one.
# Corrected here, once, before any stint or lineup table is built from these columns: in each game,
# whichever column actually contains OUR players (by name, from our own events) is our lineup. The score
# columns are UWW-first regardless, so only the two lineup strings are swapped.
_uww_names = set(pbp_events.loc[pbp_events["team"] == "UW-Whitewater", "player"].dropna().astype(str).str.strip())

def _ours_share(lineups):
    names = [n.strip() for s in lineups.dropna().astype(str) for n in s.split(",") if n.strip()]
    return (sum(n in _uww_names for n in names) / len(names)) if names else 0.0

_swapped_games = []
for _gk, _g in pbp_events.groupby(GAME_KEYS, dropna=False):
    if _ours_share(_g["opp_lineup"]) > _ours_share(_g["uww_lineup"]):
        pbp_events.loc[_g.index, ["uww_lineup", "opp_lineup"]] = pbp_events.loc[_g.index, ["opp_lineup", "uww_lineup"]].values
        _swapped_games.append(_gk)
print(f"Lineup column check: {len(_swapped_games)} game(s) had our lineup in the opponent's column and were "
      f"corrected{': ' + str(_swapped_games) if _swapped_games else '.'}")

_show(pbp_events[["opponent", "period", "time_remaining", "team", "event_type", "raw_text", "uww_lineup", "opp_lineup"]], rows=30)

print("\nLineup size check (every non-null value should be exactly 5 players):")
print(" uww_lineup sizes:", pbp_events["uww_lineup"].dropna().apply(lambda s: len(s.split(", "))).value_counts().to_dict())
print(" opp_lineup sizes:", pbp_events["opp_lineup"].dropna().apply(lambda s: len(s.split(", "))).value_counts().to_dict())
