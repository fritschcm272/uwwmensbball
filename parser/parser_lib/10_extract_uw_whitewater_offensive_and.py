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
pd.set_option("display.max_colwidth", 150)
print(all_game_plans)
