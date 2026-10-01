# 17_classify_each_raw_play_by_play_text_string.py -- code for the notebook section "The 4-column layout is "Time | UW-Whitewater | Score | <Opponent>" -- almost every row has"
# Runs inside the notebook via run_section("17_classify_each_raw_play_by_play_text_string"); its settings are in that notebook cell.

# The 4-column layout is "Time | UW-Whitewater | Score | <Opponent>" -- almost every row has exactly ONE of the
# two team-text columns filled in (one atomic event per row), alongside the running score. A few event strings
# are TEAM-level with no player name at all (a shot-clock/backcourt turnover, or a held-ball jump ball).
EVENT_PATTERNS = [
    ("jump_ball_won", re.compile(r"^(?P<player>.+?) Wins Jump Ball$")),
    ("jump_ball_lost", re.compile(r"^(?P<player>.+?) Loses Jump Ball$")),
    # A held ball can be logged with any parenthetical reason ("(Held Ball)", "(Block Tie Up)", ...).
    # TEAM_LEVEL_EXACT only ever listed "(Held Ball)", so every other variant fell through to the
    # unclassified fallback and became its own fake player -- "Jump Ball (Block Tie Up)" reached the box
    # score with more total minutes than any real player on the roster. No player group on purpose.
    ("jump_ball_held", re.compile(r"^Jump Ball \(.+\)$")),
    ("made_shot", re.compile(r"^(?P<player>.+?) Makes (?P<shot_type>\d)PT(?: (?P<shot_desc>.+))?$")),
    ("missed_shot", re.compile(r"^(?P<player>.+?) Misses (?P<shot_type>\d)PT(?: (?P<shot_desc>.+))?$")),
    ("rebound_offensive", re.compile(r"^(?P<player>.+?) Offensive Rebound$")),
    ("rebound_defensive", re.compile(r"^(?P<player>.+?) Defensive Rebound$")),
    ("team_deadball_rebound_offensive", re.compile(r"^(?P<player>.+?) Offensive Deadball Rebound$")),
    ("team_deadball_rebound_defensive", re.compile(r"^(?P<player>.+?) Defensive Deadball Rebound$")),
    ("assist", re.compile(r"^(?P<player>.+?) Assists$")),
    ("steal", re.compile(r"^(?P<player>.+?) Steals$")),
    ("block", re.compile(r"^(?P<player>.+?) Blocks$")),
    # The parenthetical turnover-type suffix (e.g. "(Bad Pass)") is present for some individual turnovers but
    # MISSING entirely for others (e.g. "Corey Thompson Turnover") -- making the suffix optional handles both.
    ("turnover", re.compile(r"^(?P<player>.+?) Turnover(?: \((?P<turnover_type>.+)\))?$")),
    # A bare TEAM-level turnover with a parenthetical type but NO player attached (e.g. "Turnover (Offensive
    # Foul)") previously fell all the way through to the "unclassified" catch-all below, whose fallback sets
    # player = the ENTIRE raw text -- so the literal string "Turnover (Offensive Foul)" ended up as its own
    # "player" row in the reconstructed box score (confirmed: exactly this string, in exactly this shape,
    # showed up in a real game's box score). TEAM_LEVEL_EXACT only covered the bare "Turnover" case with no
    # parenthetical at all -- this regex generalizes to ANY bare "Turnover (TYPE)" variant instead of needing
    # every possible type enumerated individually. No `(?P<player>...)` group here on purpose: leaving
    # "player" out of this match's groupdict() means the merged pbp_events row gets player=NaN naturally
    # (pandas fills a missing dict key with NaN when building the DataFrame), which is exactly what makes the
    # box-score builder's `pbp_events["player"].notna()` filter correctly exclude it.
    ("turnover", re.compile(r"^Turnover(?: \((?P<turnover_type>.+)\))?$")),
    # foul_type was required to be "<something> Foul", so a bare "<Player> Commits Foul" -- a real,
    # common line with no foul type recorded -- never matched, and the fallback turned the WHOLE string
    # into a player name ("Damyen Jackson Commits Foul" appeared as a person, with minutes). Making the
    # descriptor optional classifies those correctly AND credits the foul to the right player, rather
    # than just discarding them.
    ("foul", re.compile(r"^(?P<player>.+?) Commits (?P<foul_type>.*?Foul)$")),
    ("free_throw_made", re.compile(r"^(?P<player>.+?) Makes Free Throw \((?P<ft_num>\d+) of (?P<ft_total>\d+)\)$")),
    ("free_throw_missed", re.compile(r"^(?P<player>.+?) Misses Free Throw \((?P<ft_num>\d+) of (?P<ft_total>\d+)\)$")),
    ("sub_in", re.compile(r"^(?P<player>.+?) Subs In$")),
    ("sub_out", re.compile(r"^(?P<player>.+?) Subs Out$")),
    # A timeout is called by a TEAM or an official ("Official TV Timeout"), never by a roster player, so
    # the caller is deliberately not captured as `player` -- it stays in raw_text. Keeping it meant
    # "Official TV" and every team name showed up wherever player names are enumerated.
    ("timeout", re.compile(r"^.+? Timeout$")),
    ("ejected", re.compile(r"^(?P<player>.+?) Ejected$")),
]
TEAM_LEVEL_EXACT = {
    "Turnover": {"event_type": "turnover", "player": None, "turnover_type": "Team"},
    # A few games log a bare team rebound with NO player prefix at all -- classified into the same
    # team_deadball_rebound_* buckets as the other team-level rebound format.
    "Offensive Rebound": {"event_type": "team_deadball_rebound_offensive", "player": None},
    "Defensive Rebound": {"event_type": "team_deadball_rebound_defensive", "player": None},
    "Jump Ball (Held Ball)": {"event_type": "jump_ball_held", "player": None},
    # A foul logged with neither a player nor a type.
    "Commits Foul": {"event_type": "foul", "player": None},
}


def classify_event(text):
    text = text.strip()
    if text in TEAM_LEVEL_EXACT:
        return dict(TEAM_LEVEL_EXACT[text])
    for event_type, pattern in EVENT_PATTERNS:
        m = pattern.match(text)
        if m:
            return {"event_type": event_type, **m.groupdict()}
    # CONFIRMED BUG (fixed here): this used to return `player=text`, so any line the patterns above don't
    # recognise became a PLAYER named after the raw event string -- with its own box-score row, its own
    # minutes from the lineup reconstruction, and a place in the leaderboards. Keep the text in raw_text
    # (build_pbp_events already stores it) and leave `player` empty, so an unrecognised line is counted and
    # reported but can never masquerade as a person. Add a pattern above for anything that shows up here.
    return {"event_type": "unclassified", "player": None}
