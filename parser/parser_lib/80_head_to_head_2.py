# 80_head_to_head_2.py -- code for the notebook section "Export the same tables as CSV files directly into the Streamlit app's source directory, so"
# Runs inside the notebook via run_section("80_head_to_head_2"); its settings are in that notebook cell.

# --- Export the same tables as CSV files directly into the Streamlit app's source directory, so the app can
# read them as static bundled data (pandas.read_csv) instead of querying a SQL warehouse / Unity Catalog at
# runtime. (The Databricks-only Delta-table export used inside the workspace is skipped in this portable
# version -- there's no Spark session outside Databricks, and this CSV export is the app's actual data source.)
os.makedirs(APP_DATA_DIR, exist_ok=True)

# opponent_schedules is derived straight from the combined "schedule" frame (which already loops over every
# team's MHTML in schedules_dir -- UWW's own plus any opponent's -- and tags each row with "team").
opponent_schedules = (
    schedule[schedule["team"] != "UW-Whitewater Warhawks"]
    .rename(columns={"team": "opponent", "date": "game_date", "opponent": "vs_opponent"})
    [["opponent", "game_date", "vs_opponent", "location", "outcome", "team_score", "opponent_score", "point_margin"]]
    .reset_index(drop=True)
)

# uww_pbp_events is trimmed to the columns the app actually renders -- the full ~25-column table is unnecessarily
# large to bundle as a static CSV inside the app package.
PBP_EVENTS_EXPORT_COLS = [
    "opponent", "game_date", "event_order", "period", "time_remaining",
    # time_remaining_seconds: the numeric form pbp_events already carries internally (from cell 88's
    # _clock_to_seconds), same as OPPONENT_PRIOR_PBP_EXPORT_COLS already exports for the opponent side.
    # Missing here meant rebound_pairs() had no way to verify our OWN play-by-play is oldest-first, the
    # exact gap that caused the opponent-side version of this same problem (see the play-calls cell).
    "time_remaining_seconds",
    "team", "player", "event_type", "raw_text", "shot_type", "uww_score", "opp_score", "uww_lineup",
    "video_description", "coach_note", "play_call",
    # Decoded play-call fields from uww_plays.csv (see the "Play calls" cell).
    "play_series", "play_situation", "play_actions", "primary_action", "play_location", "finish_spot", "play_title",
]
# shot_type/uww_lineup were previously only exported on the clutch-events slice (CLUTCH_EVENTS_EXPORT_COLS
# below) even though both are already computed on every row of the full pbp_events DataFrame, not just
# clutch-time ones -- added here so the app can answer questions that need which 5-man UWW lineup was on the
# floor for a given shot on ANY possession, not just crunch-time ones (e.g. "which lineup gets our best shot
# type most often").

# uww_clutch_events / uww_scoring_runs -- both already computed earlier in this notebook (the "Clutch-time
# event log" and "Scoring runs and largest lead/deficit" cells) but were previously never added to csv_tables,
# so they never reached the app despite the analysis already existing. clutch_events is a filtered slice of
# pbp_events (same shape), so it needs the same column trim plus shot_type/uww_lineup/opp_lineup so the app can
# show point values and which 5-man units were on the floor during clutch stretches.
clutch_events_export = clutch_events[[c for c in CLUTCH_EVENTS_EXPORT_COLS if c in clutch_events.columns]]

# opponent column = whoever the upcoming opponent ACTUALLY played in that game (not always Whitewater --
# these are their games BEFORE facing Whitewater), team column = which side that specific row's event
# belongs to (the upcoming opponent's own play, or their opponent-in-that-game's play). Filtering
# team != upcoming_opponent_short gives exactly "what other teams did against this opponent's defense" --
# previously computed inline for print/diagnostic output only (see the "opponent_events" split a few cells
# up) and never exported, so the app had no way to use it at all.
OPPONENT_PRIOR_PBP_EXPORT_COLS = [
    "opponent", "game_date", "event_order", "period", "time_remaining", "time_remaining_seconds",
    "team", "player", "event_type", "raw_text", "shot_type", "video_description",
    # Decoded play-call fields from opponent_plays.csv.
    "play_call", "play_series", "play_situation", "play_actions", "primary_action", "play_location", "finish_spot",
    "play_title",
    # The defense the offense faced on that clip, from the coaches' updated Title tagging (decode_defense_tag
    # in the play-calls cell). These were decoded and carried on the events but never made it into this export
    # list, so the opponent's prior-game pbp silently dropped every defense read -- the app had no way to see
    # defense-by-event for those games even though the data existed upstream.
    "defense_type", "defense_press", "defense_press_formation", "defense_coverage",
]
# NOTE: no per-event lineup columns here (unlike PBP_EVENTS_EXPORT_COLS' "uww_lineup" for UWW's own games) --
# self_lineup/their_lineup only exist on pbp_up, a local copy made a couple cells up for the season-lineup-box
# computation, never attached back onto pbp_events_upcoming itself. Nothing currently needs them at the
# per-event level for the opponent's prior games (uww_opp_lineup_season_box already covers the season-
# aggregate use case, and the minutes-played cell re-derives what it needs from stint_src directly).

csv_tables = {
    "uww_schedule": schedule,
    "uww_season_stats": stats,
    "uww_pbp_events": pbp_events[PBP_EVENTS_EXPORT_COLS],
    "uww_pbp_box_score": pbp_box_score,
    "uww_lineup_stints": lineup_stints,
    "uww_coaching_flags": coaching_flags_df,
    "uww_opponent_rosters": all_rosters,
    "uww_player_profiles": player_profiles,
    "uww_opponent_game_plans": all_game_plans,
    "uww_ktv_splits": splits,
    "uww_ktv_game_categories": game_categories,
    "uww_pbp_derived_keys": pbp_derived_keys,
    "uww_opponent_team_totals": team_totals,
    "uww_projected_box_score": projected_uww_box,
    "uww_opponent_projected_box_score": projected_opponent_box,
    "uww_player_comparisons": best_matches,
    "uww_opp_lineup_season_box": upcoming_lineup_season,
    "uww_opponent_schedules": opponent_schedules,
    "uww_clutch_events": clutch_events_export,
    "uww_scoring_runs": scoring_runs,
    "uww_coach_notes": coach_notes,
    "uww_live_rosters": live_rosters,
    "uww_head_to_head": head_to_head,
    "uww_head_to_head_box": head_to_head_box,
    # "do these games matter?" -- the verdict and each team's continuity since the meetings (79_head_to_head)
    "uww_head_to_head_continuity": globals().get("head_to_head_continuity", pd.DataFrame()),
    "uww_head_to_head_roster_change": head_to_head_roster_change,  # previous meetings with the upcoming opponent  # photo/number/position/height/class year only -- see the roster cell above
    # Every tagged clip from uww_plays.csv / opponent_plays.csv, decoded, plus the per-set summaries and the
    # shorthand glossary the brief and the app print.
    "uww_play_calls": play_calls,
    "uww_play_call_summary": play_call_summary,
    # NEW: one row per tagged screen coverage ("5tl" -> Down Screen / Top Lock / defender #5) and the
    # screen-coverage breakdown the brief's "HOW THEY GUARD SCREENS" section and the app both render.
    "uww_screen_coverage": screen_coverage,
    "uww_screen_coverage_summary": screen_coverage_summary,
    # NEW: the tag model's scores this run -- per field, accuracy on clips it didn't train on vs always guessing
    # the most common answer (every retrain is also appended to _tag_model/history.csv in INPUT_DIR).
    "uww_tag_model_report": tag_model_report,
    # NEW: one row per tracked player per clip (side, name, confidence, path on the floor) and the tracking
    # cell's per-game checks.
    "uww_player_tracks": player_tracks,
    "uww_tracking_report": tracking_report,
    # NEW: every tracking-insight table (matchups, help, screens, sets, inbounds, zone/press, coverage plan,
    # spacing, the app's search and replay lists) -- built in the tracking-insights cell.
    **_ti_tables,
    # NEW: court-mapped tables (shot chart, heat maps, screen locations, paint help, zone shapes, trap spots,
    # corners/paint spacing, play diagrams, mapping quality) -- court insights cell.
    **_cz_tables,
    # play-by-play event candidates (review mode): which track each rebound / steal / block / foul pointed at
    "uww_trk_event_candidates": globals().get("trk_event_candidates", pd.DataFrame()),
    # every player's BBall Index offensive role (and the numbers behind it)
    "uww_offensive_roles": globals().get("offensive_roles_table", pd.DataFrame()),
    # every player's BBall Index defensive role (and what it was credited from)
    "uww_defensive_roles": globals().get("defensive_roles_table", pd.DataFrame()),
    # the five on the floor, player by player: which track is him and how we know, or "not located"
    "uww_trk_lineup_slots": globals().get("trk_lineup_slots", pd.DataFrame()),
    "uww_lineup_grouping": lineup_grouping,  # lineup -> grouping label, shared by the brief and the app
    "uww_play_glossary": PLAY_GLOSSARY,
    "uww_plays_catalog": plays_catalog,
    "uww_opponent_prior_games_pbp": pbp_events_upcoming[[c for c in OPPONENT_PRIOR_PBP_EXPORT_COLS if c in pbp_events_upcoming.columns]],
    "uww_opponent_prior_games_box_score": pbp_box_score_upcoming,
    "uww_opponent_prior_games_lineup_stints": lineup_stints_upcoming,
}

# Tables that ACCUMULATE across runs instead of being overwritten. Everything else is a full rebuild of
# current state and must be replaced wholesale; these two are a record of what was predicted before a
# specific game, which is only useful if past rows survive. Rows are keyed by (opponent, game_date) and the
# newest run wins for a key that already exists -- so re-running the parser for the same upcoming game
# corrects that game's projection rather than duplicating it.

csv_export_status = []
for name, df in csv_tables.items():
    path = os.path.join(APP_DATA_DIR, f"{name}.csv")
    keys = APPEND_TABLES.get(name)
    if keys and os.path.exists(path) and all(k in df.columns for k in keys):
        prior = pd.read_csv(path)
        if all(k in prior.columns for k in keys):
            # Drop this run's (opponent, game_date) from the archive, then append the fresh rows.
            this_run = set(map(tuple, df[keys].astype(str).drop_duplicates().to_numpy()))
            prior_keys = list(map(tuple, prior[keys].astype(str).to_numpy()))
            prior = prior[[k not in this_run for k in prior_keys]]
            df = pd.concat([prior, df], ignore_index=True)
        else:
            print(f"  {name}: existing CSV predates the (opponent, game_date) stamp -- replacing it. "
                  f"Projections made before this run aren't recoverable.")
    df.to_csv(path, index=False)
    csv_export_status.append((name, len(df), os.path.getsize(path)))

_show(pd.DataFrame(csv_export_status, columns=["table", "rows", "csv_bytes"]))
