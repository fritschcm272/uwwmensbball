# 09_extract_each_opponent_roster.py -- code for the notebook section "Player identity lines in the PDF's parsed text look like "#<jersey> \u2022 <name> \u2022 <"
# Runs inside the notebook via run_section("09_extract_each_opponent_roster"); its settings are in that notebook cell.

# Player identity lines in the PDF's parsed text look like "#<jersey> \u2022 <name> \u2022 <pos> \u2022 <height> \u2022 <weight> \u2022
# <class>", each followed by a "Player Notes:" section_header + text and a "Keys to Defending" section_header +
# text. Starter/bench split (and roster size) varies by opponent, so it's derived from the "BENCH" section
# header's position when the PDF actually prints one. Some PDFs (e.g. Eureka) never print a "BENCH" header at
# all even though later players still have Player Notes/Keys to Defending filled in (Damuzha Moore, Jacob
# Gonzalez) -- for those, fall back to roster order: the 1st-5th players listed are Starters, 6th onward Bench.

import json
from datetime import date

# The schedule's "date" strings (e.g. "Fri, Nov 14") carry NO year at all -- a men's basketball season spans
# two calendar years, so the year has to be inferred from the season boundary rather than read off the string.
# CONFIRMED CHANGE (requested): this used to hardcode a single "2025-26 season" assumption in its own
# SEASON_START_YEAR, separate from (and inconsistent in RETURN TYPE with) the other parse_schedule_date
# defined earlier in this notebook -- that one returns a datetime, this one returns a plain date, and
# every call site further down this notebook was written against THIS one's date-returning behavior
# (e.g. comparing against reference_date.date()). Kept as its own function rather than consolidated into
# the earlier one specifically to preserve that return type -- the fix here is the same as the other
# one's: accept an explicit season_start_year instead of a single hardcoded constant, so a caller can
# pass uww_season_start_year (computed once, right after UWW's own schedule is parsed, from the real
# season read off the page itself -- see extract_season_start_year) instead of silently assuming one
# season for every date resolved here.
def parse_schedule_date(date_str, season_start_year=None):
    """'Fri, Nov 14' -> date(2025, 11, 14) (or whatever year season_start_year resolves to)."""
    if pd.isna(date_str):
        return None
    parsed = datetime.strptime(str(date_str).strip(), "%a, %b %d")
    _syear = season_start_year if season_start_year is not None else _DEFAULT_SEASON_START_YEAR
    year = _syear if parsed.month >= 8 else _syear + 1
    return date(year, parsed.month, parsed.day)

# A few entries (e.g. Eureka's Damuzha Moore, Jacob Gonzalez) don't render "Player Notes"/"Keys to Defending" as
# separate labeled sections at all -- both labels AND both fields' text come through as ONE run-on text element,
# because the PDF's two side-by-side columns got merged with their lines interleaved by the text extractor.
# Splitting that reliably with regex isn't feasible (the interleaving order isn't consistent), so an LLM call
# separates the blob back into the two original fields based on their content -- notes describe playing style,
# keys are short defensive coaching instructions. (Portable: uses a plain OpenAI-compatible client instead of
# Databricks' ai_query() SQL function -- see USE_LLM / OPENAI_API_KEY / AI_MODEL / OPENAI_BASE_URL.)
def split_combined_notes_keys(blob):
    if not USE_LLM:
        return "", ""
    prompt = (
        "The following text is a run-on merge of two DIFFERENT scouting-report fields for one basketball "
        "player, with their lines interleaved: 'Player Notes' (describes how the player plays -- shooting, "
        "driving, position role, etc.) and 'Keys to Defending' (short defensive coaching instructions on how "
        "to guard him -- e.g. 'keep in front', 'box out', 'be a helper', 'anticipate drive', 'get off into "
        "gaps'). Split the text below back into its two original fields, preserving the original wording "
        "exactly (do not paraphrase, do not add words), and drop the literal labels 'Player Notes:' / "
        "'Keys to Defending' themselves from the output. Respond with ONLY a JSON object of the exact shape "
        '{"player_notes": "...", "keys_to_defending": "..."}, no other text.'
        f"\n\nTEXT: {blob}"
    )
    try:
        from openai import OpenAI

        client = OpenAI(base_url=os.environ.get("OPENAI_BASE_URL") or None)
        response = client.chat.completions.create(
            model=os.environ.get("AI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content)
    except Exception as llm_error:
        print(f"  LLM split failed for a combined notes/keys blob: {type(llm_error).__name__}: {llm_error} -- leaving both fields blank.")
        return "", ""
    return parsed.get("player_notes", "").strip(), parsed.get("keys_to_defending", "").strip()

# Reuse the schedule as the source of truth for each game's date (same fuzzy opponent-name match used later to
# resolve each scouted opponent's game number), rather than re-parsing it out of the PDF filename. Returns a
# real datetime.date (via parse_schedule_date) rather than the schedule's raw display string, since every
# "game_date" column built from this function (player_profiles, pbp_events, and everything grouped from pbp_events
# -- pbp_box_score, lineup_box_score) is meant for date arithmetic/sorting, not just display.
# CONFIRMED BUG (fixed here): this called parse_schedule_date() with no season_start_year override,
# silently falling back to _DEFAULT_SEASON_START_YEAR (2025) regardless of which season the MATCHED row
# actually belongs to. schedule already carries a real per-row "season" column (see
# extract_season_start_year() / build_team_schedule_from_html()), so the fix reads the season directly
# off the matched row itself, rather than assuming one season for every caller of this function --
# game_date_for() feeds player_profiles/pbp_events/pbp_box_score/lineup_box_score's own "game_date"
# columns (per this function's own docstring above), so a wrong year here would have propagated well
# beyond just a filename.
def game_date_for(opponent_short):
    matches = schedule[schedule["opponent"].str.contains(re.escape(opponent_short), case=False)]
    if matches.empty:
        return None
    _gdf_row = matches.iloc[0]
    _gdf_season_start_year = None
    if "season" in schedule.columns and pd.notna(_gdf_row.get("season")):
        try:
            _gdf_season_start_year = int(str(_gdf_row["season"]).split("-")[0])
        except (ValueError, TypeError):
            _gdf_season_start_year = None
    return parse_schedule_date(_gdf_row["date"], _gdf_season_start_year)

def extract_roster_from_pdf(elements_df, opponent):
    elements = elements_df.to_dict("records")
    n = len(elements)
    bench_idx = next(
        (e["element_index"] for e in elements if e["element_type"] == "section_header" and e["element_content"].strip() == "BENCH"),
        None,
    )
    game_date = game_date_for(opponent)

    rows = []
    player_seq = 0
    i = 0
    while i < n:
        el = elements[i]
        if el["element_type"] == "text":
            m = PLAYER_LINE_RE.match(el["element_content"].strip())
            if m:
                jersey, name, pos, height, weight, cls = m.groups()
                player_seq += 1
                notes, keys, combined_blob = [], [], None
                j = i + 1
                while j < n:
                    nel = elements[j]
                    if nel["element_type"] == "text" and PLAYER_LINE_RE.match(nel["element_content"].strip()):
                        break
                    if nel["element_type"] == "section_header" and nel["element_content"].strip() in ("STARTERS", "BENCH"):
                        break
                    if nel["element_type"] == "text":
                        content = nel["element_content"].strip()
                        prev = elements[j - 1]
                        if prev["element_type"] == "section_header" and prev["element_content"].startswith("Player Notes"):
                            notes.append(content)
                        elif prev["element_type"] == "section_header" and prev["element_content"].startswith("Keys to Defending"):
                            keys.append(content)
                        elif "player notes" in content.lower() and "keys to defending" in content.lower():
                            combined_blob = content
                    j += 1
                if not notes and not keys and combined_blob:
                    notes_text, keys_text = split_combined_notes_keys(combined_blob)
                else:
                    notes_text, keys_text = " ".join(notes), " ".join(keys)
                if bench_idx is not None:
                    role = "Starter" if el["element_index"] < bench_idx else "Bench"
                else:
                    role = "Starter" if player_seq <= STARTERS_BY_ORDER_CUTOFF else "Bench"
                rows.append({
                    "opponent": opponent,
                    "game_date": game_date,
                    "jersey_number": f"#{jersey}",
                    "name": name.strip(),
                    "position": pos,
                    "height": height,
                    "weight": (weight.strip() or None),
                    "class_year": cls,
                    "role": role,
                    "player_notes": notes_text,
                    "keys_to_defending": keys_text,
                    # Every row here came from parsing an actual scouting-report player entry (jersey/name/pos
                    # line + its Player Notes / Keys to Defending text) -- as opposed to a player later recovered
                    # ONLY from the season boxscore table (see player_profiles), who was never individually
                    # scouted. Carried forward through player_profiles so downstream cells that judge free-text
                    # scouting language (e.g. the LLM comparison) can restrict themselves to real scouted players.
                    "has_scouting_report": True,
                })
                i = j
                continue
        i += 1
    return pd.DataFrame(rows)

roster_cols = ["opponent", "game_date", "jersey_number", "name", "position", "height", "weight", "class_year", "role", "player_notes", "keys_to_defending", "has_scouting_report"]
all_rosters = pd.concat(
    [extract_roster_from_pdf(df, opponent) for opponent, df in scout_reports.items()],
    ignore_index=True,
) if scout_reports else pd.DataFrame(columns=roster_cols)
print(all_rosters)
