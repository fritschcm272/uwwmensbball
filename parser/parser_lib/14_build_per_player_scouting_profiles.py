# 14_build_per_player_scouting_profiles.py -- code for the notebook section "Build a comparable "player profile" for every scouted player: normalized position group, h"
# Runs inside the notebook via run_section("14_build_per_player_scouting_profiles"); its settings are in that notebook cell.

# Build a comparable "player profile" for every scouted player: normalized position group, height in inches,
# and a set of playing-style tags mined from their free-text scouting notes (player_notes + keys_to_defending).
def parse_height_inches(h):
    m = re.match(r"(\d+)'(\d+)\"?", str(h))
    return int(m.group(1)) * 12 + int(m.group(2)) if m else None

def normalize_position(pos):
    pos = str(pos).upper()
    if "G" in pos and "F" in pos:
        return "Wing"
    if "G" in pos:
        return "Guard"
    if "F" in pos or "C" in pos:
        return "Forward/Post"
    return "Unknown"

NOTES_TAG_KEYWORDS = {
    "catch_and_shoot": ["c&s", "c & s", "catch & shoot", "catch and shoot", "quick release", "spot-up", "spot up"],
    "pull_up_shooter": ["pull up", "pull-up", "mid range", "mid-range", "go to=mid", "step back"],
    "three_point_shooter": ["3's", "3pt", "three", "sniper", "shooter", "shoot"],
    "slasher_driver": ["driver", "drive", "gets to rim", "attacks the rim", "rhd", "lhd", "finish", "attack"],
    "post_scorer": ["post game", "back to the basket", "ls/rh", "post", "power post"],
    "rebounder": ["rebound", "board"],
    "playmaker": ["playmaker", "assist", "creator", "create", "distributor", "main creator", "ball mover", "ball move"],
    "physical_finisher": ["physical", "strong", "bully", "through his defender"],
    "high_usage": ["main creator", "go to"],
    "cutter": ["back cut", "curl"],
}

KEYS_TAG_KEYWORDS = {
    "deny_catch_and_shoot": [
        "c&s", "c & s", "closeout", "close out", "chase", "high hand", "early hand", "arrive on the catch",
        "stunt", "pick and pop", "pick & pop",
    ],
    "anticipate_move": ["anticipate", "antcipate", "antipipate"],
    "keep_in_front": ["keep in front", "keep him in front", "contest", "active hands", "vision off ball",
                       "stay in front", "step up", "spin back"],
    "help_defense": ["help", "gap", "wedge", "talk switches"],
    "box_out_priority": ["box out", "boxout", "keep off glass", "off the glass"],
    "post_defense": ["nls", "no ls/rh", "no rs/lh", "post defense", "front the post", "limit post touches", "post touches"],
    "physical_discipline": ["be physical", "stay down", "do not foul", "no fouls", "no foul", "wall up"],
    "pressure_disrupt": ["pressure", "presure", "disrupt", "speed up"],
    "transition_defense": ["locate in transition", "transition"],
    "deny_cuts": ["back cut"],
    "screen_navigation": ["fight over screens", "over screens", "under screens", "pops after screens"],
}

def tag_player(text, keywords):
    text = text.lower()
    text = re.sub(r"\bnon[- ]shooter\b", "", text)
    return {tag for tag, kws in keywords.items() if any(kw in text for kw in kws)}

player_profiles = all_rosters.copy()
player_profiles["height_inches"] = player_profiles["height"].apply(parse_height_inches)
player_profiles["position_group"] = player_profiles["position"].apply(normalize_position)
player_profiles["notes_tags"] = player_profiles["player_notes"].apply(lambda t: tag_player(t, NOTES_TAG_KEYWORDS))
player_profiles["keys_tags"] = player_profiles["keys_to_defending"].apply(lambda t: tag_player(t, KEYS_TAG_KEYWORDS))
player_profiles["notes_tags_display"] = player_profiles["notes_tags"].apply(lambda s: ", ".join(sorted(s)) if s else "")
player_profiles["keys_tags_display"] = player_profiles["keys_tags"].apply(lambda s: ", ".join(sorted(s)) if s else "")

# The season box score is the "table" element immediately following the "...BOXSCORE" section header. It covers
# the WHOLE roster (including deep bench players never mentioned in the scouting notes) plus a team-total row.
def extract_pdf_season_stats(elements_df, opponent):
    rows = elements_df.to_dict("records")
    box_idx = next(
        (i for i, r in enumerate(rows) if r["element_type"] == "section_header" and "BOXSCORE" in r["element_content"].upper()),
        None,
    )
    if box_idx is None or rows[box_idx + 1]["element_type"] != "table":
        print(f"No season boxscore table found for '{opponent}'.")
        return pd.DataFrame()

    stats_df = read_boxscore_table(rows[box_idx + 1]["element_content"])
    stats_df = stats_df.rename(columns={"#": "jersey_number", "PLAYER": "name"})
    # pdfplumber's table extraction sometimes truncates a multi-word name cell down to its first word (e.g. this
    # PDF's own "Team Total" row comes through as just "Team") -- so filtering on the exact string "Team Total"
    # alone can silently let that aggregate row through into player_profiles (and downstream FG%/3P% consumers
    # like player_comparison.py's parse_pct(), which then chokes on a "made-attempted" string like "617-1511").
    # Its jersey number is reliably "-" regardless of the name-cell truncation, so filter on that instead.
    stats_df = stats_df[stats_df["jersey_number"].astype(str).str.strip() != "-"]
    stats_df = stats_df[stats_df["name"] != "Opponent"]
    stats_df["jersey_number"] = "#" + stats_df["jersey_number"].astype(str)
    stats_df.insert(0, "opponent", opponent)
    return stats_df

pdf_season_stats = pd.concat(
    [extract_pdf_season_stats(df, opponent) for opponent, df in scout_reports.items()],
    ignore_index=True,
) if scout_reports else pd.DataFrame()

missing = pdf_season_stats.merge(
    player_profiles[["opponent", "jersey_number"]], on=["opponent", "jersey_number"], how="left", indicator=True
)
box_only = missing[missing["_merge"] == "left_only"][["opponent", "jersey_number", "name"]].drop_duplicates()

if not box_only.empty:
    box_only = box_only.copy()
    box_only["game_date"] = box_only["opponent"].apply(game_date_for)
    box_only["position"] = None
    box_only["height"] = None
    box_only["weight"] = None
    box_only["class_year"] = None
    box_only["role"] = "Bench"
    box_only["player_notes"] = ""
    box_only["keys_to_defending"] = ""
    box_only["height_inches"] = None
    box_only["position_group"] = "Unknown"
    box_only["notes_tags"] = [set() for _ in range(len(box_only))]
    box_only["keys_tags"] = [set() for _ in range(len(box_only))]
    box_only["notes_tags_display"] = ""
    box_only["keys_tags_display"] = ""
    box_only["has_scouting_report"] = False
    print(f"Adding {len(box_only)} box-score-only player(s) with no scouting writeup (defaulted to role=Bench):")
    _show(box_only[["opponent", "jersey_number", "name"]])
    player_profiles = pd.concat([player_profiles, box_only[player_profiles.columns.tolist()]], ignore_index=True)
else:
    print("No box-score-only players found -- every player in the season boxscore already has a roster/notes entry.")

# CONFIRMED CHANGE (requested): this used to left-join real season stats from the PDF's boxscore table
# onto player_profiles. Root cause of a real, reported leak: these scout report PDFs are explicitly
# labeled "Last Season" and contain the PRIOR YEAR's per-player numbers -- e.g. Ripon's real stats had
# nothing to do with any game they've played this year, and no reference_date fix can make a stale,
# undated PDF summary trustworthy. Stopped using ANY team or player statistics sourced from the scouting
# report, parser-wide: stat_cols is added here as all-null instead of merged in from pdf_season_stats, so
# player_profiles has the columns every downstream consumer expects, but they start empty. The ONLY
# legitimate source for these numbers from here on is the PBP-derived override further down this
# notebook (see "Override the upcoming opponent's player_profiles stats"), which uses real, current-
# season game data instead. pdf_season_stats itself is left in place above (still parsed, unused for
# stats) since box_only -- the "player has box-score data but no separate notes/tags writeup" backfill a
# few lines up -- still needs it to know which players exist at all.
stat_cols = ["MIN", "FG%", "3PM-A", "3P%", "FTM-A", "FT%", "REB", "AST", "TO", "STL", "BLK", "PTS"]
for _col in stat_cols:
    player_profiles[_col] = None

print("Scouting-report player statistics are disabled by design (PDF reports are last-season data) -- "
      "player_profiles stat columns start blank and are only filled in by the PBP-derived override "
      "further down this notebook, from real current-season games.")

print(player_profiles[[
    "opponent", "jersey_number", "name", "role", "notes_tags_display", "keys_tags_display", "PTS", "REB", "AST", "FG%", "3P%",
]])
