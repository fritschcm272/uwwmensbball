# 63_season_wide_5_man_lineup_analysis_across.py -- code for the notebook section "Season-wide UWW 5-man lineup analysis, combining minutes/margin across ALL games played so"
# Runs inside the notebook via run_section("63_season_wide_5_man_lineup_analysis_across"); its settings are in that notebook cell.

# --- Season-wide UWW 5-man lineup analysis, combining minutes/margin across ALL games played so far -----------
season_uww_lineups = (
    lineup_stints.groupby("uww_lineup")
    .agg(
        games=("game_date", "nunique"),   # distinct GAMES, not distinct opponents -- a home-and-home is 2
        opponents=("opponent", lambda s: sorted(s.unique())),
        stints=("stint_num", "count"),
        total_minutes=("stint_minutes", "sum"),
        net_margin=("uww_margin_change", "sum"),
    )
    .reset_index()
)
season_uww_lineups["margin_per_min"] = (season_uww_lineups["net_margin"] / season_uww_lineups["total_minutes"]).round(2)
season_uww_lineups = season_uww_lineups.sort_values("total_minutes", ascending=False)

n_games_with_pbp = pbp_events.dropna(subset=["opponent"])[GAME_KEYS].drop_duplicates().shape[0]
print(f"Season-wide UWW 5-man lineups across {n_games_with_pbp} game(s) with play-by-play data "
      f"({season_uww_lineups.shape[0]} distinct lineups used):\n")
print("Most-used lineups overall (by total minutes on the floor):")
_show(season_uww_lineups, rows=10)

meaningful = season_uww_lineups[season_uww_lineups["total_minutes"] >= MEANINGFUL_MIN_MINUTES]
print(f"\nBest net-margin-per-minute UWW lineups season-wide (min {MEANINGFUL_MIN_MINUTES} minutes played):")
_show(meaningful.sort_values("margin_per_min", ascending=False), rows=10)
print(f"\nWorst net-margin-per-minute UWW lineups season-wide (min {MEANINGFUL_MIN_MINUTES} minutes played):")
_show(meaningful.sort_values("margin_per_min", ascending=True), rows=10)

recurring = season_uww_lineups[season_uww_lineups["games"] > 1].sort_values("games", ascending=False)
if recurring.empty:
    print("\nNo single 5-man lineup has repeated across multiple games yet -- each game so far has drawn from a "
          "distinct set of on-court combinations. This will populate as more games are added.")
else:
    print(f"\nLineups that have appeared in MORE than one game ({len(recurring)}):")
    print(recurring)

game_starting_lineups = (
    pbp_scoreable.sort_values(GAME_KEYS + ["event_order"])
    .groupby(GAME_KEYS, dropna=False)["uww_lineup"].first()
    .reset_index(name="starting_lineup")
)
print("\nUWW's starting (tip-off) lineup, by game:")
print(game_starting_lineups)
if game_starting_lineups["starting_lineup"].nunique() == 1:
    print("\nSame starting five has been used in EVERY game so far.")
else:
    print(f"\nStarting five has changed across games -- {game_starting_lineups['starting_lineup'].nunique()} "
          f"different starting combinations used over {n_games_with_pbp} game(s).")

lineups_per_game = lineup_stints.groupby(GAME_KEYS, dropna=False)["uww_lineup"].nunique().reset_index(name="distinct_lineups_used")
print("\nDistinct UWW 5-man combinations used, by game:")
print(lineups_per_game)
