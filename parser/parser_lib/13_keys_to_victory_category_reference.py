# 13_keys_to_victory_category_reference.py -- code for the notebook section "Keys-to-Victory category reference -------------------------------------------------------"
# Runs inside the notebook via run_section("13_keys_to_victory_category_reference"); its settings are in that notebook cell.

# --- Keys-to-Victory category reference -----------------------------------------------------------------------
# Documents WHY each category exists: which Keys-to-Victory phrases trigger it, which stat column(s) it's graded
# on, and the reasoning -- including cases where a phrase is deliberately left unmapped because no stat in a
# season box score can measure it. Update this table any time KEYS_TO_VICTORY_STAT_MAP / STAT_COL_CATEGORY change.
# Last updated: expanded keywords after reviewing all 6 opponents' KTV + Team Strengths notes for unmapped phrases.
KTV_CATEGORY_REFERENCE = [
    {
        "category": "Ball Security / Turnovers", "stat_cols": "TO",
        "example_phrases": "ball security, turnover, protect/take care of the ball, limit turnovers, careless",
        "why_chosen": "Directly named -- \"ball security\"/\"turnovers\" have a 1:1 stat column (TO), no proxy needed.",
    },
    {
        "category": "Rebounding", "stat_cols": "REB, ORB, DRB",
        "example_phrases": "own the paint, bully/dominate the glass, rebound, board, second chance, crash (the glass)",
        "why_chosen": "\"Glass\"/\"board\"/\"crash\"/\"own the paint\" possession language in this scouting vocabulary is "
                      "always about winning the rebounding battle, not shot-making -- REB/ORB/DRB are the direct stats.",
    },
    {
        "category": "Three-Point Shooting", "stat_cols": "3PM-A, 3P%",
        "example_phrases": "three, 3 pt, 3pt, perimeter shooting, spacing, shooting ability, shooting team, "
                           "will shoot, sniper",
        "why_chosen": "Direct stat match for perimeter shot volume/efficiency. Expanded with \"3 pt\"/\"shooting "
                      "ability\"/\"shooting team\" from Elmhurst notes (\"High level 3 pt shooting team\") and "
                      "\"will shoot\" from Eureka (\"All 5 Will Shoot\").",
    },
    {
        "category": "Free Throws", "stat_cols": "FTM-A, FT%",
        "example_phrases": "free throw, ft line, getting to ft",
        "why_chosen": "Direct stat match. Added \"ft line\" / \"getting to ft\" from Aurora (\"getting to FT line\").",
    },
    {
        "category": "Fouls / Discipline", "stat_cols": "PF",
        "example_phrases": "foul, wall up, drawing fouls",
        "why_chosen": "Direct stat match for foul-discipline emphasis. Added \"wall up\" (Aurora) and \"drawing "
                      "fouls\" (Aurora \"Great at drawing fouls\").",
    },
    {
        "category": "Ball Movement / Assists", "stat_cols": "AST",
        "example_phrases": "assist, ball movement, share the ball, playmaking, playmaker, create",
        "why_chosen": "Direct stat match for offensive ball-sharing emphasis. Added \"playmaking\"/\"playmaker\"/ "
                      "\"create\" from Simpson/Ripon notes (\"2 playmaking guards\", \"Multiple guys that can create\").",
    },
    {
        "category": "Paint Protection / Blocks", "stat_cols": "BLK",
        "example_phrases": "block, protect the rim, paint protection",
        "why_chosen": "Direct stat match for interior shot-blocking emphasis.",
    },
    {
        "category": "Perimeter Defense / Ball Pressure", "stat_cols": "STL",
        "example_phrases": "steal, press capable, full court press, force turnovers, force to's, guard your yard, "
                           "keep the ball in front, guard 1 on 1, early gap, help side, active hands, pressure, "
                           "physical & aggressive on ball, on ball defensively",
        "why_chosen": "Renamed from \"Ball Pressure / Steals\" once Aurora/Eureka/Elmhurst introduced CONTAINMENT "
                      "phrasing (\"guard your yard\", \"keep the ball in front\", \"guard 1 on 1\") alongside the "
                      "original steal-gambling phrasing (\"press\", \"force turnovers\"). Both are point-of-attack, "
                      "on-ball defensive emphases. STL is the only stat in the season box score that reflects "
                      "defensive activity at all. Added \"pressure\" (data-driven keys), \"physical & aggressive on "
                      "ball\" / \"on ball defensively\" (Elmhurst \"Physical & Aggressive on ball defensively\"), "
                      "and \"force to's\" (Ripon). NOTE: \"press\" changed to \"press capable\"/\"full court press\" to "
                      "avoid false-positive substring matches (e.g. \"pressure\" contains \"press\").",
    },
    {
        "category": "Scoring Inside", "stat_cols": "FG2M, FG2A, FG2%",
        "example_phrases": "dominate the paint, attack the paint, live in the paint, attack the basket, "
                           "scoring at the rim, get to rim, attack the rim, get to the rim",
        "why_chosen": "Interior-scoring emphasis -- uses derived 2PT FG stats (FGM-FG3M, FGA-FG3A) as a "
                      "direct measure of inside scoring rather than overall FG efficiency. Does NOT include "
                      "free throws. Added from Aurora/Simpson/Ripon/Elmhurst/St. Thomas phrasing.",
    },
    {
        "category": "Field Goal Efficiency", "stat_cols": "FGM-A, FG%",
        "example_phrases": "limit their scoring",
        "why_chosen": "Overall shooting efficiency emphasis -- used when the scouting note is about limiting "
                      "opponent scoring broadly rather than specifically inside or from 3PT range.",
    },
    {
        "category": "(intentionally unmapped)", "stat_cols": "-",
        "example_phrases": "communication screening action / communicate screens & actions (Ripon, Elmhurst), "
                           "take away personnel tendencies (Simpson), heavy ball screen usage (Ripon), "
                           "will be their 4th game (Eureka)",
        "why_chosen": "No corresponding stat exists in a season box score for screen-navigation communication, "
                      "opponent-personnel-specific keys, scheme-specific ball screen usage, or schedule context. "
                      "These stay qualitative-only in the game-plan notes and don't produce a category row.",
    },
]

pd.set_option("display.max_colwidth", 300)
_show(pd.DataFrame(KTV_CATEGORY_REFERENCE))
