# 30_compare_pbp_derived_opponent_tendencies_to.py -- code for the notebook section "Compare our PBP-derived findings to UWW's own scouting keys for the upcoming opponent ----"
# Runs inside the notebook via run_section("30_compare_pbp_derived_opponent_tendencies_to"); its settings are in that notebook cell.

# --- Compare our PBP-derived findings to UWW's own scouting keys for the upcoming opponent ---------------------
_safe_display = lambda df: print(df) if not df.empty else print("  (no data)")

elmhurst_plan = all_game_plans[
    (all_game_plans["opponent"] == upcoming_opponent_short) & (all_game_plans["topic"].isin(["TEAM STRENGTHS", "KEYS TO VICTORY"]))
]
print(f"UWW's own scouting notes for {upcoming_opponent_short} [SOURCE: SCOUTING REPORT]:")
for _, r in elmhurst_plan.iterrows():
    print(f"  {r['topic']}: {r['notes']}")

# Rebounding split, for the "DOMINATE THE PAINT" key -- covers both individual and team-level rebound events.
rebounds = elmhurst_events[elmhurst_events["event_type"].str.contains("rebound", na=False)]
reb_split = rebounds["event_type"].apply(lambda x: "offensive" if "offensive" in x else "defensive").value_counts().reset_index()
reb_split.columns = ["rebound_type", "count"]

# Blocks recorded AGAINST them by their opponents -- another paint-imposition signal.
blocks_against = opponent_events[opponent_events["event_type"] == "block"]

paint_attempts = shot_profile.loc[shot_profile["shot_desc"].str.contains("Layup", na=False), "attempts"].sum()
three_pt = shot_profile[shot_profile["shot_type"] == "3"]
three_pt_attempts, three_pt_makes = three_pt["attempts"].sum(), three_pt["makes"].sum()
measured_3p_pct = round(three_pt_makes / three_pt_attempts * 100, 1) if three_pt_attempts else None

print("\n--- Comparing PBP evidence to the stated Keys to Victory [SOURCE: SCOUTING REPORT] ---\n")

print("KEY 1 [SCOUTING REPORT] -- COMMUNICATE SCREENS & ACTIONS:")
print("  Not directly measurable from play-by-play event types (no screen-action tagging) -- this is a")
print("  communication/technique key tied to their offensive scheme (per the scout's own Offensive Scheme notes),")
print("  not something the event log alone can confirm or refute.\n")

print("KEY 2 [SCOUTING REPORT] -- DOMINATE THE PAINT:")
print(f"  Their own rebounding split across their {prev_games.shape[0]} games: {reb_split.to_dict('records')}")
print(f"  Their layup-area attempts (Layup + Driving Layup): {paint_attempts} of {shot_profile['attempts'].sum()} total FGA")
print(f"  Blocks recorded against them by opponents: {len(blocks_against)}")
print("  Compare against their own Defensive Scheme notes and layup-area conversion rate to judge whether this key")
print("  is supported by the evidence.\n")

print("KEY 3 [SCOUTING REPORT] -- GUARD 1 ON 1:")
print(f"  Measured 3PT jump-shot rate: {three_pt_attempts} attempts at {measured_3p_pct}%.")
print(f"  Scoring balance (top 5 scorers): {top_scorers.head(5).to_dict('records')}")
print("  Compare against the scout's own TEAM STRENGTHS note on shooting/scoring balance to judge whether")
print("  over-helping creates open catch-and-shoot looks that straight man coverage would limit.")

# --- New Keys to Victory, derived directly from PBP data/tendencies rather than the written scouting report --
# CONFIRMED BUG (fixed here): DATA-KEY 1's recommendation was a hardcoded sentence -- "load up P&R roll coverage
# and transition defense" -- printed no matter WHICH actions came out on top. On Aurora it sat under
# "ISO: 60.0% on 20; Cut: 55.0% on 20", neither of which is a P&R roll or transition, so the evidence and the
# instruction on the same key contradicted each other. Each recommendation is now built from the actions the
# data actually picked, via _PT_DEFENSIVE_CALL below.
#
# CONFIRMED BUG (fixed here): DATA-KEY 3 ranked turnover triggers by RAW COUNT. Spot-Up is also their most-used
# action (79 shots), so it tops the turnover list by volume alone -- which then contradicted DATA-KEY 2 telling
# us to let them keep running it. Now ranked by turnover RATE per use of the action (TO / (shots + TO)), with a
# volume floor, so "trigger" means an action that is actually loose rather than one that is merely common.
#
# CONFIRMED BUG (fixed here): "No Play Type" -- the tagger's own placeholder for an untagged clip -- was being
# ranked as if it were an action ("No Play Type: 7 of 52 turnovers"). A coach can't scheme against it.
# Placeholder labels are dropped from every ranking below.
#
# CONFIRMED BUG (fixed here): "Both well above their overall clip" was asserted without checking. An action
# now has to beat (or trail) the overall FG% by _PT_MIN_GAP points to be called out at all.
print("\n\n--- New Keys to Victory, derived from PBP data/tendencies [SOURCE: PBP-DERIVED] ---\n")

_PT_PLACEHOLDERS = {"", "nan", "none", "no play type", "unknown", "n/a", "not tagged"}
_PT_MIN_ATTEMPTS = 15   # shots on an action before its FG% is worth a key
_PT_MIN_USES_FOR_TO = 20  # shots + turnovers on an action before its turnover RATE is worth a key
_PT_MIN_GAP = 5.0       # FG% points above/below their overall clip before an action is "well" above/below

# What to actually DO against each action. Keyed on lower-cased substrings of the tagger's play-type labels,
# checked in order, so "P&R Roll Man" hits the roll-man entry before the generic "p&r" one.
_PT_DEFENSIVE_CALL = [
    ("roll man", "tag the roll man early from the weak side and don't give up the pocket pass"),
    ("ball handler", "pick one ball-screen coverage and stay in it -- keep the handler out of the middle"),
    ("p&r", "pick one ball-screen coverage and stay in it -- keep the handler out of the middle"),
    ("iso", "keep a gap, show help at the level of the ball and make him score over a crowd"),
    ("isolation", "keep a gap, show help at the level of the ball and make him score over a crowd"),
    ("cut", "jump to the ball on every pass and see man and ball -- no back-cuts behind ball-watchers"),
    ("transition", "sprint back, stop the ball first and match up second"),
    ("post", "front or three-quarter the post and send a timed dig from the passer"),
    ("off screen", "lock and trail off the screen and switch nothing we haven't called"),
    ("hand off", "get into the handoff and force it away from the middle"),
    ("handoff", "get into the handoff and force it away from the middle"),
    ("spot", "close out short and under control -- contest without flying by"),
    ("put back", "hit a body on every shot before going to the ball"),
    ("offensive rebound", "hit a body on every shot before going to the ball"),
]


def _pt_is_placeholder(label):
    return str(label).strip().lower() in _PT_PLACEHOLDERS


def _pt_call(label):
    low = str(label).lower()
    for needle, call in _PT_DEFENSIVE_CALL:
        if needle in low:
            return call
    return f"make {label} a named item in the defensive walkthrough"


overall_fg_pct = round(shots["made"].mean() * 100, 1)
_pt_named = play_type_tendency[~play_type_tendency["play_type"].apply(_pt_is_placeholder)]
high_volume_types = _pt_named[_pt_named["attempts"] >= _PT_MIN_ATTEMPTS]

most_efficient = (high_volume_types[high_volume_types["fg_pct"] >= overall_fg_pct + _PT_MIN_GAP]
                  .sort_values("fg_pct", ascending=False).head(2))
least_efficient = (high_volume_types[high_volume_types["fg_pct"] <= overall_fg_pct - _PT_MIN_GAP]
                   .sort_values("fg_pct").head(2))

# Turnover RATE per use of each action. A use is a shot or a turnover on that action.
_to_named = turnovers[~turnovers["play_type"].apply(_pt_is_placeholder)]
_to_counts = _to_named.groupby("play_type").size().rename("turnovers")
turnover_rates = (play_type_tendency.set_index("play_type")[["attempts"]]
                  .join(_to_counts, how="outer").fillna(0))
turnover_rates = turnover_rates[~turnover_rates.index.to_series().apply(_pt_is_placeholder)]
turnover_rates["uses"] = turnover_rates["attempts"] + turnover_rates["turnovers"]
turnover_rates["to_rate"] = (100 * turnover_rates["turnovers"]
                             / turnover_rates["uses"].replace(0, float("nan"))).round(1)
_team_uses = float(turnover_rates["uses"].sum()) or 1.0
team_to_rate = round(100 * float(turnover_rates["turnovers"].sum()) / _team_uses, 1)
top_turnover_triggers = (turnover_rates[(turnover_rates["uses"] >= _PT_MIN_USES_FOR_TO)
                                        & (turnover_rates["to_rate"] > team_to_rate)]
                         .sort_values("to_rate", ascending=False).head(2))


def _pt_list(frame):
    return "; ".join(f"{r['play_type']}: {r['fg_pct']}% on {int(r['attempts'])} attempts"
                     for _, r in frame.iterrows())


def _pt_calls(frame):
    return " ".join(f"{r['play_type']}: {_pt_call(r['play_type'])}." for _, r in frame.iterrows())


_derived = []
if not most_efficient.empty:
    _derived.append({
        "title": "Take away their most efficient high-volume actions",
        "supporting_stats": _pt_list(most_efficient),
        "recommendation": (f"Each is {_PT_MIN_GAP:.0f}+ points above their {overall_fg_pct}% overall clip on "
                           f"{_PT_MIN_ATTEMPTS}+ attempts. " + _pt_calls(most_efficient)),
    })
if not least_efficient.empty:
    _derived.append({
        "title": "Funnel them into their worst high-volume looks",
        "supporting_stats": _pt_list(least_efficient),
        "recommendation": (f"Each is {_PT_MIN_GAP:.0f}+ points below their {overall_fg_pct}% overall clip -- "
                           "don't help off these actions; make them keep taking them."),
    })
if not top_turnover_triggers.empty:
    _derived.append({
        "title": "Pressure the actions they turn it over on",
        "supporting_stats": "; ".join(
            f"{pt}: {int(r['turnovers'])} TO in {int(r['uses'])} uses ({r['to_rate']}% vs {team_to_rate}% "
            f"across all actions)" for pt, r in top_turnover_triggers.iterrows()),
        "recommendation": ("Loosest actions per use, not the most common ones -- load ball pressure and "
                           "gap help onto these specifically rather than pressing everything."),
    })

for _i, _k in enumerate(_derived, start=1):
    print(f"DATA-KEY {_i} [PBP-DERIVED] -- {_k['title'].upper()}:")
    print(f"  {_k['supporting_stats']}")
    print(f"  {_k['recommendation']}\n")
if not _derived:
    print("  No action cleared the volume and gap floors -- no PBP-derived keys this week.")

# One row per key, tagged with an explicit `source` so downstream consumers can tell these from the written
# report's keys. Keyed by `opponent` so future opponents' keys can append to the same table.
pbp_derived_keys = pd.DataFrame(
    [{"opponent": upcoming_opponent_short, "key_number": _i, "source": "PBP-DERIVED", **_k}
     for _i, _k in enumerate(_derived, start=1)],
    columns=["opponent", "key_number", "title", "source", "supporting_stats", "recommendation"],
)
print("\nStructured PBP-derived keys, ready for CSV export:")
_safe_display(pbp_derived_keys)
