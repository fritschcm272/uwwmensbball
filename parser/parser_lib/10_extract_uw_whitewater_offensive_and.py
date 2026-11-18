# 10_extract_uw_whitewater_offensive_and.py -- code for the notebook section "PDF elements already separate section_header from text cleanly (no banner/page-chrome nois"
# Runs inside the notebook via run_section("10_extract_uw_whitewater_offensive_and"); its settings are in that notebook cell.

headers_in_order = [
    "TEAM STRENGTHS", "KEYS TO VICTORY",
    "Overall Defensive Scheme", "Attacking their man defense", "Ball Screen & DHO Defense",
    "Ball Screen Actions & Reads", "Speciality Defensive Notes", "Potential Adjustments",
    "Defending Their Action", "Overall OFFENSIVE SCHEME", "Ball Screen Actions & Personnel",
    "Ball Screen Coverage(s)", "Potential Adjustments", "ELOB & SLOB",
]
section_group = {
    "TEAM STRENGTHS": "Game Plan Overview", "KEYS TO VICTORY": "Game Plan Overview",
    "Overall Defensive Scheme": "Offensive Game Plan (vs. Opponent Defense)",
    "Attacking their man defense": "Offensive Game Plan (vs. Opponent Defense)",
    "Ball Screen & DHO Defense": "Offensive Game Plan (vs. Opponent Defense)",
    "Ball Screen Actions & Reads": "Offensive Game Plan (vs. Opponent Defense)",
    "Speciality Defensive Notes": "Offensive Game Plan (vs. Opponent Defense)",
    "Defending Their Action": "Defensive Game Plan (vs. Opponent Offense)",
    "Overall OFFENSIVE SCHEME": "Defensive Game Plan (vs. Opponent Offense)",
    "Ball Screen Actions & Personnel": "Defensive Game Plan (vs. Opponent Offense)",
    "Ball Screen Coverage(s)": "Defensive Game Plan (vs. Opponent Offense)",
    "ELOB & SLOB": "Defensive Game Plan (vs. Opponent Offense)",
}
# PDF elements already separate section_header from text cleanly (no banner/page-chrome noise mixed in, unlike
# flattened MHTML text) -- reconstruct the game plan by bucketing consecutive "text" elements under the most
# recent matching "section_header", stopping once the roster ("STARTERS") begins.
def extract_game_plan_from_pdf(elements_df, opponent):
    buckets, order = {}, []
    current_label = None
    adj_seen = 0
    for el in elements_df.to_dict("records"):
        if el["element_type"] == "section_header":
            content = el["element_content"].strip()
            if content == "STARTERS":
                break
            if content in headers_in_order:
                if content == "Potential Adjustments":
                    adj_seen += 1
                    label = f"Potential Adjustments ({'Defense' if adj_seen == 1 else 'Offense'})"
                    category = "Offensive Game Plan (vs. Opponent Defense)" if adj_seen == 1 else "Defensive Game Plan (vs. Opponent Offense)"
                else:
                    label, category = content, section_group[content]
                current_label = label
                buckets[label] = []
                order.append((category, label))
            else:
                current_label = None  # banner/divider header (e.g. "RIPON DEFENSE") we don't care about
        elif el["element_type"] == "text" and current_label is not None:
            txt = el["element_content"].strip()
            if txt:
                buckets[current_label].append(txt)
    return pd.DataFrame([
        {"opponent": opponent, "category": category, "topic": label, "notes": " | ".join(buckets[label])}
        for category, label in order
    ])

game_plan_cols = ["opponent", "category", "topic", "notes"]
all_game_plans = pd.concat(
    [extract_game_plan_from_pdf(df, opponent) for opponent, df in scout_reports.items()],
    ignore_index=True,
) if scout_reports else pd.DataFrame(columns=game_plan_cols)
# CONFIRMED CHANGE (requested: bring in Carroll's 2026-27 report). all_game_plans_history = each opponent's plan from the
# report of the game we already played (section 11 / 12 pair those keys with that game's result). all_game_plans -- what
# the app, the keys to victory and the brief read (uww_opponent_game_plans) -- uses the UPCOMING game's report instead
# for an opponent that has one. report_date says which report each row came from.
_rd = globals().get("scout_report_dates") or {}
all_game_plans["report_date"] = all_game_plans["opponent"].map(lambda o: _rd.get(o))
all_game_plans_history = all_game_plans.copy()
_gp_up = globals().get("scout_reports_upcoming") or {}
if _gp_up:
    _rdu = globals().get("scout_report_dates_upcoming") or {}
    _new_plans = [extract_game_plan_from_pdf(df, o).assign(report_date=_rdu.get(o)) for o, df in _gp_up.items()]
    all_game_plans = pd.concat([all_game_plans[~all_game_plans["opponent"].isin(list(_gp_up))]] + _new_plans,
                               ignore_index=True)
    print("Game plans from the UPCOMING game's report: " + "; ".join(
        f"{o} ({_rdu.get(o)}, {len(p)} topic(s))" for o, p in zip(_gp_up, _new_plans)), flush=True)
# CONFIRMED CHANGE (requested 11/17, with FastScout listing Elmhurst twice -- this game and a 2025-26 one):
# section 08 flags an upcoming opponent whose only report was written for a DIFFERENT game. Its keys, strengths
# and schemes are that game's, so they are not this game's plan: the rows come out of all_game_plans (what the
# app, the keys to victory and the brief read). all_game_plans_history keeps them -- paired with the game they
# were actually written for, which is what sections 11 / 12 need.
_gp_stale = globals().get("scout_report_stale") or {}
if _gp_stale and globals().get("SCOUT_REPORT_MUST_MATCH_GAME", True):
    _drop = all_game_plans["opponent"].isin(list(_gp_stale))
    if _drop.any():
        for _o, (_fn, _was, _want) in _gp_stale.items():
            print(f"!! {_o}: dropping {int((all_game_plans['opponent'] == _o).sum())} game-plan topic(s) -- they come "
                  f"from '{_fn}', written for {_was}, and the upcoming game is {_want}. The brief will have no "
                  f"staff keys for {_o} until this game's report is downloaded from FastScout.", flush=True)
        all_game_plans = all_game_plans[~_drop].reset_index(drop=True)
pd.set_option("display.max_colwidth", 150)
print(all_game_plans)
