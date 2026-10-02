# 47_play_calls.py -- code for the notebook section "Play calls: uww_plays.csv (every tagged clip, all games), decoded and joined onto the play"
# Runs inside the notebook via run_section("47_play_calls"); its settings are in that notebook cell.

# --- Play calls: uww_plays.csv (every tagged clip, all games), decoded and joined onto the play-by-play ------
# CONFIRMED CHANGE (requested): play-call data now comes from exactly two files in INPUT_DIR --
#   uww_plays.csv        UW-Whitewater's own tagged offensive possessions, every game this season
#   opponent_plays.csv   the UPCOMING opponent's tagged offensive possessions from their prior games
# Both are the video-tagging tool's clip export (one row per possession: Title, Result, Date, Pd., Clock,
# Player, Team, Synergy String, ...). The play call lives in "Title", typed as shorthand with where on the
# floor it was run ("OK State- DHO RS- Pat Miller", "41- BS LS- Reject", "Blob-Box-Curl"), so every title is
# DECODED below into situation / set / actions / location, and the raw title is always kept beside it.
#
# JOIN. Each clip is matched to one play-by-play event of the team on offense, scored in this order:
#   1. same game date + period, and the clip's Synergy String equals the event's video_description
#      (the _video.mhtml export carries the identical string, so this is an exact fingerprint)
#   2. same player, clock within _PL_CLOCK_TOL seconds, and an event type the clip's Result allows
#   3. clock within 3 seconds and a compatible event type, when the player name is spelled differently
# One event takes at most one clip. Unmatched clips are NOT dropped: they stay in uww_play_calls.csv with
# matched_event=False, so the play-call breakdowns still count them -- only their pbp-derived points are
# replaced by the points the Result tag implies.
#
# POINTS. A matched clip scores what the play-by-play says the offense scored at that clock stamp (made
# shots plus free throws, so and-ones and trips to the line count). An unmatched clip falls back to its
# Result tag, and a foul with no play-by-play behind it is left unknown rather than guessed.
#
# This supersedes the old "*_plays_*.csv" season log path in the recap cell above (that glob is removed).

_PL_UWW_FILE = os.path.join(INPUT_DIR, "uww_plays.csv")
_PL_OPP_FILE = os.path.join(INPUT_DIR, "opponent_plays.csv")
_PL_CLOCK_TOL = 12          # seconds; clip clocks are typed at the moment of the result, give or take a stoppage
_PL_UWW = "UW-Whitewater"
_PL_EVENT_COLS = ["play_call", "play_series", "play_situation", "play_actions", "primary_action",
                  "play_location", "finish_spot", "play_title", "play_decode_quality",
                  "defense_type", "defense_press", "defense_press_formation", "defense_coverage",
                  "possession_side", "defense_faced", "defense_played", "coverage_faced", "coverage_played"]
_pl_problems = []

# --- Play-title decoder ------------------------------------------------------------------------------------
# The "Title" column is the tagger's shorthand, typed live and inconsistently:
#   "OK State- DHO RS- Sci Sc- STS -RE"   "Blob-Box-Curl"   "5 out- pass 5 -flair"   "41- BS LS- Reject"
# Structure, when there is one: [situation] - [formation / named set] - [action] - [action] ... - [spot]
# Hyphens are the separator, EXCEPT inside formations ("4-1", "2-1-1") and "Hi-Lo", which are protected first.
# Every clip keeps its raw title next to the decode, and decode_quality says how much to trust it.

_PD_SITUATIONS = [
    (r"\bblob\b", "BLOB"), (r"\bslob\b", "SLOB"),
    # "timepit" is the tagger's own typo/shorthand for "timeout" -- functionally the same situation as ATO
    # (a play run after a stoppage), so it's folded into the same pattern rather than given its own category.
    (r"\bato\b|\btime\s*out\b|\btimepit\b", "ATO"), (r"\bopener\b", "Opener"),
    # NEW (from the coaches' latest tagging): "tran" is by far the most common untagged word in the new
    # opponent_plays.csv (42 clips) -- without this, every one of them silently fell back to the "Half
    # court" default, which is a real miscategorization, not just an unrecognized word.
    (r"\btran(?:s(?:ition)?)?\b", "Transition"),
]
# Named sets / formations. kind "formation" is an alignment ("5 Out", "4-1"); kind "set" is a named play
# ("Panther", "OK State") and outranks a formation when naming the call.
_PD_SETS = [
    (r"\b5\s*out\b", "5 Out", "formation"),
    (r"\b4~1\b|\b41\b", "4-1", "formation"),
    (r"\b3~2\b|\b32\b", "3-2", "formation"),
    (r"\b2~3\b|\b23\b", "2-3", "formation"),
    (r"\b2~1~1\b", "2-1-1", "formation"),
    (r"\b33\b", "33", "formation"),
    (r"\bhilo\b", "Hi-Lo", "formation"),
    (r"\bhorns\b", "Horns", "formation"),
    (r"\bdiamond\b", "Diamond", "formation"),
    (r"\bbox\b", "Box", "formation"),
    (r"\bline\b|\blline\b|\bl\b", "Line", "formation"),
    (r"\bstairs\b", "Stairs", "set"),
    (r"\bokstate\b", "OK State", "set"),
    (r"\bpan(?:th|ht)er\b", "Panther", "set"),  # "panhter" is a letter-transposed typo, matched the same way
    (r"\bp4\b", "P4", "set"),                   # one of our own plays (uww_plays.csv)
    (r"\bchaos\b|\bchoas\b", "Chaos", "set"),   # "choas" is a letter-transposed typo of "chaos"
    (r"\bcheetah\b", "Cheetah", "set"),
    (r"\bflop\b", "Flop", "set"),
    (r"\bhighway\b", "Highway", "set"),
    (r"\bpistol\b", "Pistol", "set"),
    (r"\bmonty\b", "Monty", "set"),
    # NEW (data-driven from opponent_plays.csv / uww_plays.csv's latest tagging -- these are the highest-
    # frequency unrecognized words in the new files, in order of how often they showed up):
    (r"\bflow\b", "Flow", "formation"),           # 46 clips -- reads as a base half-court offense, like "5 Out"
    (r"\bchin\b", "Chin", "formation"),            # 34 clips (incl. "chin,")
    (r"\btwins?\b", "Twins", "formation"),         # 7 clips
    (r"\bsnap\b", "Snap", "set"),                  # 7 clips
    (r"\bblack\b", "Black", "set"),                # 5 clips -- a color-coded call
    (r"\bbulldog\b", "Bulldog", "set"),            # 3 clips
    (r"\bpinch\b", "Pinch", "set"),                # ~7 clips across variants ("pinch set", "pinch-over-zoom")
    (r"\bblocker[\s-]*mover\b", "Blocker-Mover", "set"),  # 6 clips
]
# Actions. rank 1 = a named/signature action that identifies the play; 2 = a screen or handoff action;
# 3 = connective movement (pass, swing, follow) that describes HOW the ball got there, not what the play is.
_PD_ACTIONS = [
    (r"\bpat\s*miller\b", "Pat Miller", 1), (r"\bgren(?:ade|dae)\b", "Grenade", 1),
    (r"\bhammer\b", "Hammer", 1), (r"\bzoom\b", "Zoom", 1), (r"\bt?twirl\b", "Twirl", 1),
    (r"\bbreddy\b", "Breddy", 1), (r"\bricky\b|\bric\b", "Ricky", 1), (r"\bivo\b", "IVO", 1),
    (r"\bspain\b", "Spain", 1), (r"\bmotion\b", "Motion", 1), (r"\blob\b", "Lob", 1), (r"\brip\b", "Rip", 1),
    (r"\bxai?vi?er\s*screen\b", "Xavier Screen", 1), (r"\bshoulder\s*screen\b", "Shoulder Screen", 1),
    (r"\bguards?\s*cross\b", "Guards Cross", 1),  # NEW -- 20 clips in opponent_plays.csv
    (r"\bucla\b", "UCLA", 1),                     # NEW -- "UCLA screen"/"UCLA cut", 3 clips
    (r"\bbig\s*on\s*big\b", "Big-on-Big", 1), (r"\bexh?ac?h?n?g?e?\b|\bexchange\b", "Exchange", 2),
    (r"\bdho\b|\bdh\b|\bhandoff\b|\bhand\s*off\b", "DHO", 2),
    (r"\bbs\s*scree?n?\b|\bball\s*screens?\b|\bbs\b", "Ball Screen", 2),
    (r"\bdown\s*screens?\b|\bds\b", "Down Screen", 2), (r"\bup\s*screen\b", "Up Screen", 2),
    (r"\bstagger\b", "Stagger", 2), (r"\bsts\b", "Screen the Screener", 2),
    # "double" is used for either a double screen or a stagger screen depending on the tagger -- kept as one
    # label rather than guessing which, since the coaches themselves described it as ambiguous.
    (r"\bdouble\b", "Double/Stagger Screen", 2),
    # "ored"/"oreb" mark an offensive rebound on the clip -- a result note, not what generated the shot, so
    # it's rank 3 (won't outrank a real action like Ball Screen or DHO as the primary_action).
    (r"\boreb\b|\bored\b", "Offensive Rebound", 3),
    (r"\bsci(?:ssors)?\b(?:\s*sc\b)?", "Scissors", 2), (r"\b\d\s*screen\s*\d\b", "Screen", 2),
    (r"\bfla(?:i|)re?\b|\bflairs?\b|\bflares?\b", "Flare", 2), (r"\bcurl\b", "Curl", 2),
    (r"\bdd\b", "Double Drag", 2), (r"\breject\b|\brj\b", "Reject", 2), (r"\bslip\b", "Slip", 2),
    (r"\bpop\b", "Pop", 2), (r"\bget\b", "Get", 2), (r"\bgive\b", "Give", 2),
    (r"\biso\b", "ISO", 2), (r"\bpost\b|\bpt\b", "Post Touch", 2), (r"\bclear\b", "Clear", 3),
    (r"\bbc\s*cut\b", "Backcut", 2), (r"\bcut\b", "Cut", 3), (r"\bflash\b", "Flash", 3),
    (r"\bfollow\b", "Follow", 3), (r"\bswing\b", "Swing", 3), (r"\bpass\b", "Pass", 3),
    (r"\bdribble\b|\bpush\s*thru\b", "Dribble Entry", 3), (r"\bstand\b", "Stand", 3),
]
_PD_LOCATIONS = [
    (r"\blw\b", "Left Wing"), (r"\brw\b", "Right Wing"), (r"\blc\b", "Left Corner"), (r"\brc\b", "Right Corner"),
    (r"\bls\b|\bleft\s*side\b|\bleft\b", "Left Side"), (r"\brs\b|\bright\s*side\b|\bright\b", "Right Side"),
    (r"\blb\b", "Left Block"), (r"\brb\b", "Right Block"), (r"\ble\b", "Left Elbow"), (r"\bre\b", "Right Elbow"),
    (r"\btop(?:\s*key)?\b", "Top"), (r"\bother\s*side\b", "Opposite Side"), (r"\bwing\b", "Wing"),
]
_PD_REVIEW = r"\brewatch\b|\btbd\b|\bmess\s*up\b|\?"
_PD_IGNORE = r"\bset\b|\bhalf\b|\bplay\b|\bgl\b|\bout\b|\baround\b"

# --- Defense-tag decoder (NEW: coaches' updated Title logic) ------------------------------------------------
# Titles now also carry the DEFENSE this team's offense faced on the clip -- e.g.
#   "5 OUT- PASS- DS- CURL: M2M SOFT HEDGE"   "UWW M2M D- BLOB"   "FLOW: M2M PRESS- SWITCH"
#   "5 OUT: M2M-SWITCH"   "OVER-CHEETAH: M2M D- DROP"   "Flow: M2M: Deny"
# In uww_plays.csv that's the OPPONENT's defense while UWW ran the play; in opponent_plays.csv it's the
# defense the upcoming opponent faced in their own prior game. Extracted as its own set of fields and
# blanked out of the working text before the offense decoder below runs, so "m2m", "press", "switch" etc.
# never show up as unrecognized leftover text (which used to knock otherwise-clean titles down to Partial).
_PD_PRESS_FORMATIONS = [
    (r"\b1\s*-\s*2\s*-\s*1\s*-\s*1\b", "1-2-1-1 Press"),
    (r"\b1\s*-\s*2\s*-\s*2\b", "1-2-2 Press"),
    # Fixed-width look-around so a stray "2-1-2?" (an unrelated, already-flagged-for-review guess) doesn't
    # get misread as a "1-2" press just because "1-2" appears as a substring of a longer digit run.
    (r"(?<!\d-)\b1\s*-\s*2\b(?!-\d)", "1-2 Press"),
]
# Checked in order: a named coverage before the bare word it's built from ("soft hedge" before "hedge").
_PD_COVERAGE = [
    (r"\bsoft\s*hedge\b", "Soft Hedge"), (r"\bhedge\b", "Hedge"), (r"\bswitch\b", "Switch"),
    (r"\bice\b", "Ice"), (r"\bdrop\b", "Drop"), (r"\bdeny\b", "Deny"), (r"\bjam\b", "Jam"),
    # NEW, data-driven from the latest tagging:
    (r"\bshow\b", "Show"),      # 13 clips, usually "show and get back/recover" -- a real coverage, not hedge
    (r"\bunder\b", "Under"),    # 6 clips -- go under the screen
    (r"\bfight\b", "Fight"),    # 6 clips -- fight over the screen, distinct from a switch or a hedge
    (r"\btoken\b", "Token"),    # 11 clips (incl. "token,")
    (r"\bblitz\b", "Blitz"),    # 2 clips -- aggressive double-team on the ball screen
]
_PD_PRESS_WORD = r"\bpress\b|\bpres\b|\bprss\b|\bpresss\b"
# Pure marker noise that only ever rides along with a defense tag ("UWW M2M D", "5 OUT- M2M D") -- the
# team-name prefix and a bare trailing "D" (for "Defense") add nothing once defense_type is captured.
# "uwsp"/"uswp" (79 clips combined, incl. the "uwsp," variant): NOT a third party -- this is UW-Stevens
# Point's OWN marker for themselves, the same role "uww" plays in our own file (the upcoming opponent as of
# Jan 7 is Stevens Point, and this is how their tagger writes their own team name next to the defense they
# were in). It names who was on defense, which the Team/opponent columns already carry, so it adds nothing
# once defense_type is captured. A future scouted team's own tagging will very likely use its own
# abbreviation the same way -- add it here when it shows up as unrecognized leftover text.
_PD_DEFENSE_NOISE = r"\buww\b|\buwsp\b|\buswp\b|\bd\b"


def decode_defense_tag(title):
    """Pull the opponent-defense fields out of a raw Title: defense_type (Man-to-Man / N-N Zone / Zone),
    defense_press (bool), defense_press_formation (named press alignment, if stated), and defense_coverage
    (ball-screen/on-ball call: Switch, Hedge, Soft Hedge, Ice, Drop, Deny, Jam -- pipe-joined if more than
    one is tagged). Returns (fields dict, remaining text with every matched token blanked to a space) so the
    caller can run the ordinary offense decode on what's left."""
    t = " " + re.sub(r"\s+", " ", str(title or "")).lower().strip() + " "
    out = {"defense_type": None, "defense_press": False, "defense_press_formation": None, "defense_coverage": ""}

    # Zone subtype ("2-3 zone", "3-2 zone", "1-3-1 zone") before the bare word, else Man-to-Man.
    zm = re.search(r"\b(\d)\s*-\s*(\d)(?:\s*-\s*(\d))?\s*zone\b", t)
    if zm:
        out["defense_type"] = "-".join(g for g in zm.groups() if g) + " Zone"
        t = t[:zm.start()] + " " * (zm.end() - zm.start()) + t[zm.end():]
    elif re.search(r"\bzone\b", t):
        out["defense_type"] = "Zone"
        t = re.sub(r"\bzone\b", " ", t)
    # "mwm" and a bare "m2" are typos/truncations of "m2m" seen repeatedly in the latest tagging (4 and 6
    # clips) -- same meaning, just fat-fingered.
    if re.search(r"\bm2m\b|\bmwm\b|\bm2\b", t):
        out["defense_type"] = out["defense_type"] or "Man-to-Man"
        t = re.sub(r"\bm2m\b|\bmwm\b|\bm2\b", " ", t)

    for pat, name in _PD_PRESS_FORMATIONS:
        pm = re.search(pat, t)
        if pm:
            out["defense_press"], out["defense_press_formation"] = True, name
            t = t[:pm.start()] + " " * (pm.end() - pm.start()) + t[pm.end():]
            break
    if re.search(_PD_PRESS_WORD, t):
        out["defense_press"] = True
        t = re.sub(_PD_PRESS_WORD, " ", t)

    coverage = []
    for pat, name in _PD_COVERAGE:
        if re.search(pat, t):
            coverage.append(name)
            t = re.sub(pat, " ", t)
    out["defense_coverage"] = " | ".join(dict.fromkeys(coverage))

    if out["defense_type"] or out["defense_press"] or coverage:
        t = re.sub(_PD_DEFENSE_NOISE, " ", t)
    # The colon/semicolon (and an occasional "+" joining two coverages, e.g. "Drop+Press") are the new
    # tagging convention's own delimiter between offense and defense -- strip them here rather than let
    # them fall through to the offense decoder as unrecognized punctuation (which used to knock an
    # otherwise-clean title down to "Partial" on every single title that used the new format).
    t = re.sub(r"[:;+]", " ", t)
    return out, re.sub(r"\s+", " ", t).strip()


def _pd_prep(title):
    t = " " + str(title or "").lower().strip() + " "
    # Only real alignments are protected -- "33- 5 BS" is a set name, a separator, then the five man.
    t = re.sub(r"(?<!\d)([1-3])\s*-\s*([1-3])\s*-\s*([1-3])(?!\d)", r"\1~\2~\3", t)
    t = re.sub(r"(?<!\d)(4\s*-\s*1|3\s*-\s*2|2\s*-\s*3|1\s*-\s*4)(?!\d)",
               lambda m: re.sub(r"\s*-\s*", "~", m.group(1)), t)
    t = re.sub(r"\bhi\s*-?\s*lo(?:w)?\b", "hilo", t)
    t = re.sub(r"\bok\s*st(?:ate)?\b", "okstate", t)
    t = re.sub(r"\b5\s*out\b", "5 out", t)
    t = re.sub(r"\bbig\s+sci\b", "sci", t)
    return t


def _decode_play_title_legacy(title, known_players=()):
    """Decode one Title into structured fields. Never raises; an undecodable title comes back with
    decode_quality "No call" or "Needs review" and its raw text intact."""
    raw = re.sub(r"\s+", " ", str(title or "")).strip()
    out = {"play_title": raw, "play_call": None, "play_series": None, "play_situation": "Half court",
           "play_formation": None, "play_set": None, "play_actions": "", "primary_action": None,
           "play_location": None, "finish_spot": None, "featured_player": None, "decode_quality": "Clean",
           "decode_note": "", "defense_type": None, "defense_press": False, "defense_press_formation": None,
           "defense_coverage": ""}
    if not raw:
        out.update(decode_quality="No call", decode_note="blank title")
        return out
    low = raw.lower()
    # A title that is only a player's name is the tagger marking who, not what.
    players = {str(p).lower(): str(p) for p in known_players if str(p).strip()}
    if low.strip(" -") in players:
        out.update(decode_quality="No call", featured_player=players[low.strip(" -")],
                   decode_note="title is a player name, not a play")
        return out
    review = bool(re.search(_PD_REVIEW, low))
    # Defense fields come out of the RAW title first (order-independent of where they sit -- before or
    # after a colon, or the whole title), and every matched token is blanked before the offense decoder
    # below ever sees the text, so "m2m", "press", "switch" etc. never land in play_actions or notes.
    defense_fields, defense_stripped = decode_defense_tag(raw)
    out.update(defense_fields)
    prepped = _pd_prep(defense_stripped)
    segments = [s.strip() for s in prepped.split("-") if s.strip()]

    situations, formations, sets, actions, locations, notes = [], [], [], [], [], []
    for seg in segments:
        rest = " " + seg + " "
        found = []  # (position, kind, value, extra)
        for pat, name in _PD_SITUATIONS:
            for m in re.finditer(pat, rest):
                found.append((m.start(), "situation", name, None)); rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
        for pat, name, kind in _PD_SETS:
            for m in re.finditer(pat, rest):
                found.append((m.start(), kind, name, None)); rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
        for pat, name, rank in _PD_ACTIONS:
            for m in re.finditer(pat, rest):
                found.append((m.start(), "action", name, rank)); rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
        for pat, name in _PD_LOCATIONS:
            for m in re.finditer(pat, rest):
                found.append((m.start(), "location", name, None)); rest = rest[:m.start()] + " " * (m.end() - m.start()) + rest[m.end():]
        # A trailing "3" after a spot is the finish ("LW 3" = left-wing three).
        three = re.search(r"\b3\b", rest)
        if three:
            found.append((three.start(), "three", "3", None)); rest = rest[:three.start()] + " " + rest[three.end():]
        rest = re.sub(_PD_REVIEW + "|" + _PD_IGNORE, " ", rest)
        # The five/four man referenced inside an action ("pass 5", "5 BS", "DHO 4") -- kept as context only.
        rest = re.sub(r"\b[1-5]\b", " ", rest)
        leftover = rest.strip()
        if leftover:
            # Anything left is either a player's name ("Madson", "PT BROCK") or shorthand we don't know.
            hit = next((players[p] for p in players
                        if any(w and re.search(r"\b" + re.escape(w) + r"\b", leftover) for w in p.split())), None)
            if hit:
                out["featured_player"] = out["featured_player"] or hit
            else:
                notes.append(leftover)
        seg_kinds = {f[1] for f in found}
        is_last = seg is segments[-1]
        if is_last and seg_kinds and seg_kinds <= {"location", "three"} and not leftover:
            spots = [f[2] for f in sorted(found, key=lambda f: f[0]) if f[1] == "location"]
            if spots:
                out["finish_spot"] = spots[-1]
        for _, kind, value, extra in sorted(found, key=lambda f: f[0]):
            if kind == "situation":
                situations.append(value)
            elif kind == "formation":
                formations.append(value)
            elif kind == "set":
                sets.append(value)
            elif kind == "action":
                actions.append((value, extra))
            elif kind == "location":
                locations.append(value)
            elif kind == "three" and locations:
                out["finish_spot"] = f"{locations[-1]} 3"
            elif kind == "three":
                out["finish_spot"] = "3"

    dedupe = lambda xs: list(dict.fromkeys(xs))  # noqa: E731
    situations, formations, sets = dedupe(situations), dedupe(formations), dedupe(sets)
    oob = next((s for s in situations if s in ("BLOB", "SLOB")), None)
    if oob:
        out["play_situation"] = oob + (" (ATO)" if "ATO" in situations else "")
    elif "ATO" in situations:
        out["play_situation"] = "ATO"
    elif "Opener" in situations:
        out["play_situation"] = "Opening set"
    elif "Transition" in situations:
        out["play_situation"] = "Transition"
    # "Line" and "Box" only mean a formation under an inbounds play; elsewhere "L" is noise.
    if not oob:
        formations = [f for f in formations if f not in ("Line", "Box")]
    out["play_formation"] = formations[0] if formations else None
    out["play_set"] = sets[0] if sets else None
    out["play_actions"] = " | ".join(dedupe(a for a, _ in actions))
    ranked = sorted(((r, i, a) for i, (a, r) in enumerate(actions)), key=lambda x: (x[0], x[1]))
    out["primary_action"] = ranked[0][2] if ranked and ranked[0][0] <= 2 else (ranked[0][2] if ranked else None)
    out["play_location"] = locations[0] if locations else None

    # Name the call: [OOB] + (named set, else formation) + primary action when it adds something.
    base = out["play_set"] or out["play_formation"]
    parts = []
    if oob:
        parts.append(oob)
    if base:
        parts.append(base)
    if out["primary_action"] and out["primary_action"] != base and (not base or ranked[0][0] <= 2):
        # A named set carries its own identity ("Panther"); only add an action to it when it's a signature one.
        if not (out["play_set"] and ranked[0][0] > 1):
            parts.append(out["primary_action"])
    out["play_call"] = " ".join(parts) if parts else None
    out["play_series"] = (oob if oob else None) or out["play_set"] or out["play_formation"] or (
        "Motion / no set" if actions else None)

    if out["play_call"] is None:
        if situations:
            out["play_call"] = f"{out['play_situation']} (unspecified)"
            out["play_series"] = out["play_situation"].replace(" (ATO)", "")
            out["decode_quality"] = "Partial"
        else:
            out["decode_quality"] = "No call"
    if notes:
        out["decode_note"] = "unrecognized: " + ", ".join(notes)
        if out["decode_quality"] == "Clean":
            out["decode_quality"] = "Partial"
    if review:
        out["decode_quality"] = "Needs review"
        out["decode_note"] = ("tagger flagged it (rewatch/TBD/?/mess up)" + ("; " + out["decode_note"] if out["decode_note"] else ""))
    return out


# --- Structured tag decoder (NEW: coaches' structured Title format, Sept 2026) ------------------------------
# CONFIRMED CHANGE (requested): coaches now tag every clip in ONE fixed shape instead of free shorthand:
#     <Offensive formation>-<Play call>(<offensive detail>, <detail>, ...): [<Press>] <Defensive formation> (<defensive detail>, ...)
#     e.g.  "5 out-Motion(pass 5,ds,reject,bs): m2m (5tl,12drop)"
# Every piece now has a fixed SLOT, so it is read by position rather than guessed by keyword:
#   * text before the FIRST ":" is offense, after it is defense (legacy titles used ":" and "-" loosely --
#     that looseness is exactly why the old keyword decoder kept landing things in the wrong column)
#   * offense: the last "-" before "(" splits formation from play call; the parentheses hold the ordered
#     offensive details. No play call -> "Motion" (staff default). No formation -> left blank, not guessed.
#   * defense: optional press word/formation, then the defensive formation, then parentheses holding
#     "<defender jersey #><coverage code>" details ("5tl" = defender #5 top-locked the down screen,
#     "12drop" = defender #12 dropped on the ball screen). Press goes before a dash: ": 122 - m2m" = 1-2-2
#     press back to man. No press -> "None" (staff default). Defense-only possessions are just ": m2m" / "m2m".
#   * each defensive detail is paired to the offensive SCREEN it answers (down-screen codes to ds, ball-screen
#     codes to bs, then by order) and exported as coverage_detail, so "how do they guard the down screen" is
#     one filter instead of a text search.
# Detection: a title is read this way only if it has "(" ... ")" AND a ":" -- every legacy title in
# uww_plays.csv fails that test (the one legacy title with parens, "FLOW (ZOOM) - M2M D", has no colon), so
# the old keyword decoder still handles last season's clips unchanged and nothing already exported moves.
# Anything the structured reader doesn't recognize is NOT dropped: it's listed in decode_note as a tag error
# and the clip is marked Partial, so the app's existing "clips needing attention" table becomes the coaches'
# tag-fix list.

# Coverage codes that answer a DOWN SCREEN / off-ball screen vs a BALL SCREEN. Codes in both (switch) pair by
# order. Confidence "Inferred" = my reading of the shorthand; confirm with staff and flip to "Standard".
# CONFIRMED CHANGE (coach answers, parser_check_WOS_at_WWW_1-3-26.xlsx): over and top lock are used on BALL screens too
# (so they pair with either kind); stay = the ball handler REJECTS the screen and the defender stays with him;
# switch2nd = stayed on the first screen, switched the second; show&GB = show (soft or hard hedge) then get back to the
# screener. rj and token are PRESSES, never coverages (handled by the press reader).
_PT_OFFBALL_COVERAGE = {
    "trail": ("Trail", "Standard"), "chase": ("Trail", "Standard"), "cheat": ("Cheat", "Standard"),
    "thru": ("Through", "Standard"), "through": ("Through", "Standard"),
    "bump": ("Bump", "Standard"), "front": ("Front", "Standard"),
}
_PT_BALL_COVERAGE = {
    "drop": ("Drop", "Standard"), "hedge": ("Hedge", "Standard"), "softhedge": ("Soft Hedge", "Standard"),
    "sh": ("Soft Hedge", "Inferred"), "show": ("Show", "Standard"), "ice": ("Ice", "Standard"),
    "blue": ("Ice", "Inferred"), "blitz": ("Blitz", "Standard"), "trap": ("Blitz", "Standard"),
    "under": ("Under", "Standard"), "fight": ("Fight", "Standard"),
    "jam": ("Jam", "Inferred"), "weak": ("Weak", "Inferred"),
    "stay": ("Stay (reject)", "Standard"), "switch2nd": ("Stay, then Switch 2nd", "Standard"),
    "show&gb": ("Show & Get Back", "Standard"), "showgb": ("Show & Get Back", "Standard"),
    "show&getback": ("Show & Get Back", "Standard"),
}
_PT_EITHER_COVERAGE = {"switch": ("Switch", "Standard"), "sw": ("Switch", "Inferred"), "siwtch": ("Switch", "Standard"),
                       "swtich": ("Switch", "Standard"), "over": ("Over", "Standard"),
                       "tl": ("Top Lock", "Standard"), "toplock": ("Top Lock", "Standard"), "lock": ("Top Lock", "Inferred"),
                       "deny": ("Deny", "Standard"),
                       "none": ("No coverage / lost", "Inferred"), "late": ("Late", "Inferred")}
# Offensive actions that are SCREENS a defender can "cover" -- only these get paired to a defensive detail.
_PT_OFFBALL_SCREENS = {"Down Screen", "Up Screen", "Flare", "Stagger", "Double/Stagger Screen",
                       "Screen the Screener", "UCLA", "Screen", "Pin Down", "Back Screen", "Cross Screen", "Swing Screen"}
_PT_BALL_SCREENS = {"Ball Screen", "DHO", "Double Drag", "Get", "High Ball Screen", "Ricky (rescreen)", "Zoom",
                    "Double Ball Screen"}
# New structured-tag vocabulary not in the legacy _PD_ACTIONS list (checked first, exact token match).
_PT_EXTRA_ACTIONS = {"pd": ("Pin Down", 2), "pin down": ("Pin Down", 2), "bks": ("Back Screen", 2),
                     "back screen": ("Back Screen", 2), "cs": ("Cross Screen", 2), "cross screen": ("Cross Screen", 2),
                     "roll": ("Roll", 3), "short roll": ("Short Roll", 3), "ghost": ("Ghost", 2),
                     "drive": ("Drive", 3), "kick": ("Kick Out", 3), "shot": ("Shot", 3),
                     # coach definitions (parser_check_WOS_at_WWW_1-3-26.xlsx)
                     "hi bs": ("High Ball Screen", 1), "high bs": ("High Ball Screen", 1), "hibs": ("High Ball Screen", 1),
                     "high ball screen": ("High Ball Screen", 1), "double bs": ("Double Ball Screen", 1),
                     "swing": ("Swing (pass across)", 3), "swing screen": ("Swing Screen", 2),
                     "ricky": ("Ricky (rescreen)", 1), "zoom": ("Zoom", 1),
                     "doubleclear": ("Double Clear", 3), "double clear": ("Double Clear", 3),
                     "slip": ("Slip", 3), "dd": ("Dribble Drive", 3), "dribble drive": ("Dribble Drive", 3),
                     "cornercut": ("Corner Cut", 3), "cutcorner": ("Corner Cut", 3), "cut corner": ("Corner Cut", 3), "corner cut": ("Corner Cut", 3),
                     "flash": ("Flash", 3), "pop": ("Pop", 3), "iso": ("Iso", 3),
                     "doublecut": ("Double Cut", 3), "double cut": ("Double Cut", 3),
                     "p-wing": ("Pass to Wing", 3), "pass wing": ("Pass to Wing", 3),
                     "pass corner": ("Pass to Corner", 3), "reject": ("Reject", 3), "cut": ("Cut", 3), "pass": ("Pass", 3)}
# Named plays typed INSIDE the offense parentheses ("5 out(Over)" = the 5-out set called Over).
_PT_PLAYS_IN_DETAILS = {"over": "Over"}
# Press type inside press( ): coaches -- presses are man presses and always fall back into man.
_PT_PRESS_CODES = {"rj": "Run & Jump", "r&j": "Run & Jump", "runandjump": "Run & Jump", "12": "1-2-2 Press",
                   "122": "1-2-2 Press", "1-2-2": "1-2-2 Press", "token": "Token Press", "m2m": "Full-court M2M Press",
                   "man": "Full-court M2M Press", "221": "2-2-1 Press", "1211": "1-2-1-1 Press"}
# Press slot (before " - " in the defense half, per staff: "1-2-2 press back to man" is coded ": 122 - m2m").
# Bare digit strings are press alignments here: "122" -> 1-2-2 Press, "1211" -> 1-2-1-1, "221" -> 2-2-1.
_PT_PRESS_DIGITS = r"^\s*([1-4])-?([1-4])-?([1-4])?-?([1-4])?\s*(?:press)?\s*$"
# Offensive plays that are CALLS, not formations, even when typed alone ("Flow(ds,bs): m2m ()").
_PT_PLAY_CALL_NAMES = {"flow": "Flow", "motion": "Motion"}
_PT_PRESS_TYPES = [(r"\br\s*\+\s*j\b|\brun\s*(?:and|&|\+)\s*jump\b", "Run & Jump"),
                   (r"\b1\s*-\s*2\s*-\s*1\s*-\s*1\b", "1-2-1-1 Press"), (r"\b1\s*-\s*2\s*-\s*2\b", "1-2-2 Press"),
                   (r"\b2\s*-\s*2\s*-\s*1\b", "2-2-1 Press"), (r"\b1\s*-\s*2\b", "1-2 Press"),
                   (r"\bm2m\s*press\b|\bfull\s*court\b", "Full-court M2M Press"), (_PD_PRESS_WORD, "Press")]
_PT_DEF_FORMATIONS = [(r"\bm2m\b|\bman\b|\bmwm\b", "Man-to-Man"), (r"\b(\d)\s*-\s*(\d)(?:\s*-\s*(\d))?\s*zone\b", None),
                      (r"\b(\d)\s*-\s*(\d)(?:\s*-\s*(\d))?\b", None), (r"\bbox\s*(?:and|&|\+)\s*1\b|\bbox\s*1\b", "Box-and-1"),
                      (r"\btriangle\s*(?:and|&|\+)\s*2\b", "Triangle-and-2"), (r"\bmatch\s*up\b|\bmatchup\b", "Match-up Zone"),
                      (r"\bzone\b", "Zone")]


def _pt_normalize(title):
    """Forgive the coding slips the coaches named (parser_check_WOS_at_WWW_1-3-26.xlsx) before decoding:
    '::press(rj)' / ':;press(rj)' -> ':press(rj)'; '5out(ds)::m2m' -> one colon; '2NDH-' dropped (the half is known);
    'blob(line)-m2m' -> 'blob(line):m2m'; 'm2m D' -> 'm2m'; 'm2m(rj)' -> 'press(rj)' (rj is always the press);
    'double bs:(under)' -> 'double bs:m2m(under)'."""
    t = str(title or "")
    t = t.replace(";", ":")
    t = re.sub(r"^\s*:+\s*", ":", t)
    t = re.sub(r":\s*:+", ":", t)
    t = re.sub(r"^\s*2ndh\s*-\s*", "", t, flags=re.I)
    if ":" not in t:
        t = re.sub(r"\)\s*-\s*(?=(?:m2m|man|press|zone)\b)", "):", t, flags=re.I)
    t = re.sub(r"\b(m2m)\s+d\b", r"\1", t, flags=re.I)
    t = re.sub(r"\bpres{1,3}\s*\(", "press(", t, flags=re.I)       # 'presss(rj)', 'pres(rj)'
    t = re.sub(r"\bprss\s*\(", "press(", t, flags=re.I)
    t = re.sub(r"\bm2m\s*\(\s*(rj)\s*\)", r"press(\1)", t, flags=re.I)
    t = re.sub(r":\s*\(", ":m2m(", t)
    return t


def _pt_tokens(txt):
    """Details inside ( ) -> tokens. Commas are the standard; the coaches often used dashes the same way
    ('over-swing-ricky', 'over-switch'), so both separate -- except inside a digit alignment ('1-2-2') and 'p-wing'."""
    t = re.sub(r"\bp-wing\b", "p~wing", str(txt or ""), flags=re.I)
    t = re.sub(r"(?<=\d)-(?=\d)", "~", t)
    return [x.replace("~", "-").strip() for x in re.split(r"[,\-]", t) if x.strip()]


def _pt_player_detail(tok):
    """'denymadz' / 'deny 15' / 'double madz' -> 'Denied madz' / 'Double-teamed #15' (a player, not a screen)."""
    m = re.match(r"^(deny|double)\s*(?:team(?:ed)?)?\s*#?\s*(.*)$", tok.strip(), re.I)
    who = m.group(2).strip() if m else tok
    who = f"#{who}" if re.fullmatch(r"\d{1,2}", who) else who
    return ("Denied " if m and m.group(1).lower() == "deny" else "Double-teamed ") + who


def is_structured_title(title):
    """Clearly the new shape: parentheses AND a colon (offense : defense)."""
    t = str(title or "")
    return ":" in t and "(" in t and ")" in t


def _pt_parse_defense(def_txt):
    """Defense half of a structured tag -> (fields, detail text, errors).
    Shape: [<press> -] <defensive formation> [(<details>)]   e.g. "122 - m2m (5tl)", "m2m (12drop)", "- 23"."""
    errors = []
    # CONFIRMED CHANGE (coach answers): 'press(<type>)' -- what's in the parentheses is the PRESS TYPE (rj = Run & Jump,
    # 12 = 1-2-2, token, m2m = man press) and a press always falls back into man; a SECOND parenthesis is the ball-screen
    # coverage ('press(rj)(switch)', 'press(12)((switch))'), a third can deny / double a player ('(denymadz)').
    press_code = None
    m = re.search(r"\bpress\s*\(([^()]*)\)", def_txt, re.I)
    if m:
        press_code = m.group(1).strip().lower()
        def_txt = def_txt[:m.start()] + " press " + def_txt[m.end():]
    def_txt = re.sub(r"\(\s*\(", "(", def_txt)
    def_txt = re.sub(r"\)\s*\)", ")", def_txt)
    groups = re.findall(r"\(([^()]*)\)", def_txt)
    if len(groups) > 1:
        def_txt = re.sub(r"\([^()]*\)", " ", def_txt) + " (" + ", ".join(groups) + ")"
    dhead, ddetails, ok = _pt_split_paren(def_txt)
    if not ok:
        errors.append("defense parentheses unbalanced")
    d = re.sub(_PD_DEFENSE_NOISE, " ", " " + dhead.lower() + " ")
    # Protect digit alignments ("2-3 zone", "1-2-2") before splitting press from defense on the dash.
    # Only a TIGHT dash is part of an alignment ("2-3", "1-2-2"); a spaced dash is the press separator, so
    # "1211 - 23" is press 1-2-1-1 back to a 2-3 zone.
    prot = re.sub(r"(?<=\d)-(?=\d)", "~", d)
    segs = [x.replace("~", "-").strip() for x in prot.split("-")]
    if len(segs) >= 2:
        press_txt, form_txt = segs[0], " ".join(x for x in segs[1:] if x)
    else:
        press_txt, form_txt = "", segs[0]
    press = None
    if press_txt:
        m = re.match(_PT_PRESS_DIGITS, press_txt)
        if m:
            press = "-".join(g for g in m.groups() if g) + " Press"
        else:
            press = next((name for pat, name in _PT_PRESS_TYPES if re.search(pat, press_txt)), None)
            if press is None:
                errors.append(f"unknown press '{press_txt}'")
                press = press_txt.upper()
    else:
        # No " - " slot: a press word can still ride inside ("m2m press", "r+j m2m").
        for pat, name in _PT_PRESS_TYPES:
            m = re.search(pat, form_txt)
            if m:
                press = name
                form_txt = (form_txt[:m.start()] + " " + form_txt[m.end():]).strip()
                break
    form_txt = re.sub(_PD_PRESS_WORD, " ", form_txt).strip()
    dform = None
    m = re.fullmatch(r"([1-4])-?([1-4])(?:-?([1-4]))?\s*(?:zone)?", form_txt)
    if m:  # "23" / "2-3" / "2-3 zone" / "131"
        dform = "-".join(g for g in m.groups() if g) + " Zone"
        form_txt = ""
    else:
        for pat, name in _PT_DEF_FORMATIONS:
            m = re.search(pat, form_txt)
            if m:
                dform = name or ("-".join(g for g in m.groups() if g) + " Zone")
                form_txt = (form_txt[:m.start()] + " " + form_txt[m.end():]).strip()
                break
    if form_txt:
        errors.append(f"unrecognized defense text '{form_txt}'")
    if dform is None and not press_code and press is None:
        errors.append("no defensive formation")
    if press_code:
        code_ = re.sub(r"[\s_]", "", press_code)
        if code_ in _PT_PRESS_CODES:
            press = _PT_PRESS_CODES[code_]
        else:
            errors.append(f"unknown press type '{press_code}'")
            press = press or "Press"
    if dform is None and press is not None:
        dform = "Man-to-Man"                        # coaches: presses fall back into man
        errors = [e for e in errors if e != "no defensive formation"]
    fields = {"defense_type": dform, "defense_formation": dform, "defense_press": press is not None,
              "defense_press_formation": press if press not in (None, "Press") else None}
    return fields, ddetails, errors


def _pt_action(token):
    """One offensive detail token -> (canonical action, rank, position number or None)."""
    tok = re.sub(r"\s+", " ", token.lower()).strip()
    pos = None
    m = re.search(r"\b([1-5])\b", tok)
    if m:  # "pass 5" / "5 bs" -- a POSITION (1-5), not a jersey number, on the offense side
        pos = int(m.group(1))
        tok = (tok[:m.start()] + tok[m.end():]).strip()
    if tok in _PT_EXTRA_ACTIONS:
        return (*_PT_EXTRA_ACTIONS[tok], pos)
    for pat, name, rank in _PD_ACTIONS:
        if re.fullmatch(r"\s*(?:" + pat + r")\s*", tok):
            return name, rank, pos
    return None, None, pos


def _pt_coverage(code):
    """'tl' -> ('Top Lock', 'offball', conf); unknown -> (None, None, None)."""
    c = re.sub(r"[\s\-_]", "", code.lower())
    for table, fam in ((_PT_OFFBALL_COVERAGE, "offball"), (_PT_BALL_COVERAGE, "ball"), (_PT_EITHER_COVERAGE, "either")):
        if c in table:
            return table[c][0], fam, table[c][1]
    return None, None, None


def _pt_split_paren(text):
    """'5 out-Motion(pass 5,ds)' -> ('5 out-Motion', 'pass 5,ds', ok). ok=False on unbalanced parens."""
    if text.count("(") != text.count(")") or text.count("(") > 1:
        ok = False
    else:
        ok = True
    m = re.search(r"\(([^()]*)\)", text)
    if not m:
        return text.strip(), "", ok
    return (text[:m.start()] + " " + text[m.end():]).strip(), m.group(1), ok


def decode_structured_title(title, known_players=()):
    """Decode a title written in the structured format. Same output keys as the legacy decoder plus
    tag_format / play_details / defense_formation / defense_details / coverage_detail."""
    raw = re.sub(r"\s+", " ", str(title or "")).strip()
    out = {"play_title": raw, "play_call": None, "play_series": None, "play_situation": "Half court",
           "play_formation": None, "play_set": None, "play_actions": "", "primary_action": None,
           "play_location": None, "finish_spot": None, "featured_player": None, "decode_quality": "Clean",
           "decode_note": "", "defense_type": None, "defense_press": False, "defense_press_formation": None,
           "defense_coverage": "", "tag_format": "Structured", "play_details": "", "defense_formation": None,
           "defense_details": "", "coverage_detail": ""}
    errors = []
    if ":" in raw:
        off_txt, def_txt = raw.split(":", 1)
    else:  # defense-only tag ("m2m", "122 - m2m (5tl)") -- a possession tagged from the defense's side
        off_txt, def_txt = "", raw
    if not off_txt.strip():
        dfields, ddetails, derr = _pt_parse_defense(def_txt)
        out.update(dfields)
        out.update(tag_format="Structured (defense only)", play_situation="Half court", play_set=None,
                   decode_quality="No call", decode_note="defense-only tag")
        if derr:
            out["decode_note"] += "; tag errors: " + "; ".join(derr)
        dd = [t for t in _pt_tokens(ddetails) if not re.match(r"^(deny|double)", t.strip().lower())]
        _pl_d = [_pt_player_detail(t) for t in _pt_tokens(ddetails) if re.match(r"^(deny|double)", t.strip().lower())]
        codes = [re.fullmatch(r"#?\s*(\d{1,2})?\s*([a-z+&0-9 ]+?)", t.lower()) for t in dd]
        names = [(_pt_coverage(m.group(2))[0] or m.group(2), m.group(1)) if m else (t, None) for t, m in zip(dd, codes)]
        _fams = {n: fam for (n, _j), m in zip(names, codes) if m for _x, fam, _c in [_pt_coverage(m.group(2))]}
        out["defense_details"] = " | ".join([f"#{j} {n}" if j else n for n, j in names] + _pl_d)
        # No offensive details to pair with, so the screen is named by the coverage code's family.
        _fam_label = {"offball": "Off-ball screen", "ball": "Ball Screen"}
        out["coverage_detail"] = " | ".join(
            f"{_fam_label.get(_fams.get(n) or '', 'Screen')}: {n}{f' (def #{j})' if j else ''}" for n, j in names)
        out["defense_coverage"] = " | ".join(dict.fromkeys(n for n, _ in names))
        return out

    # ---- Offense: formation - play call (details) ----
    head, details, ok = _pt_split_paren(off_txt)
    if not ok:
        errors.append("offense parentheses unbalanced")
    head = head.strip(" -")
    # Split formation / play call on the LAST dash that isn't inside a digit alignment ("4-1", "1-2-2").
    protected = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "~", head)
    parts = [p.replace("~", "-").strip() for p in protected.rsplit("-", 1)] if "-" in protected else [head]
    if len(parts) == 2:
        formation_txt, call_txt = parts
    else:
        # One word: a known formation ("5 out(...)") means default Motion; anything else is the call.
        one = parts[0]
        is_form = one.strip().lower() not in _PT_PLAY_CALL_NAMES and any(k == "formation" and re.search(p, _pd_prep(one)) for p, _, k in _PD_SETS)
        formation_txt, call_txt = (one, "") if is_form else ("", one)

    # Situation words can sit in either slot ("Blob-Line(...)", "Tran-Motion(...)").
    situations = []

    def _pull_situations(txt):
        for pat, name in _PD_SITUATIONS:
            if re.search(pat, txt.lower()):
                situations.append(name)
                txt = re.sub(pat, " ", txt, flags=re.I)
        return txt.strip(" -")

    formation_txt, call_txt = _pull_situations(formation_txt), _pull_situations(call_txt)
    # "Blob-Line(...)": once the situation word is pulled out, a lone formation left in the CALL slot is the
    # formation, and the call falls back to the Motion default.
    if not formation_txt and call_txt and call_txt.strip().lower() not in _PT_PLAY_CALL_NAMES and any(
            k == "formation" and re.fullmatch(r"\s*(?:" + p + r")\s*", _pd_prep(call_txt)) for p, _, k in _PD_SETS):
        formation_txt, call_txt = call_txt, ""
    formation = None
    if formation_txt:
        prepped = _pd_prep(formation_txt)
        hit = next(((name, pat) for pat, name, kind in _PD_SETS if re.search(pat, prepped)), None)
        formation = hit[0] if hit else formation_txt.strip().title()
        if hit and re.sub(hit[1], " ", prepped).strip(" -"):
            errors.append(f"extra text in formation '{formation_txt.strip()}' (one formation, then '-', then the call)")
        if not hit:
            errors.append(f"new formation '{formation_txt.strip()}' (add to _PD_SETS if real)")
    call = call_txt.strip()
    if call.lower() in _PT_PLAY_CALL_NAMES:
        call, call_is_action = _PT_PLAY_CALL_NAMES[call.lower()], False
    elif call:
        prepped = _pd_prep(call)
        hit = next((name for pat, name, kind in _PD_SETS if re.fullmatch(r"\s*(?:" + pat + r")\s*", prepped)), None)
        act = _pt_action(call)[0]
        call = hit or act or call.title()
        call_is_action = hit is None and act is not None
    else:
        call = "Motion"  # staff default when no play call is tagged
        call_is_action = False
    actions, detail_labels = [], []
    spots = []
    moved_cov = []                                  # coverage words typed on the offense side ('bs(stay)')
    oob_now = any(x in ("BLOB", "SLOB") for x in situations)
    toks = _pt_tokens(details)
    # BLOB / SLOB: the first word in ( ) is the inbounds formation ('blob(line)', 'blob(box, sts)') -- coaches
    if oob_now and toks and not formation and any(
            k == "formation" and re.fullmatch(r"\s*(?:" + p + r")\s*", _pd_prep(toks[0])) for p, _, k in _PD_SETS):
        formation = next(name for p, name, k in _PD_SETS if k == "formation" and re.fullmatch(r"\s*(?:" + p + r")\s*",
                                                                                               _pd_prep(toks[0])))
        toks = toks[1:]
    for tok in toks:
        # a named play typed inside the parentheses ('5 out(Over)') is the play call
        if tok.lower() in _PT_PLAYS_IN_DETAILS and call == "Motion":
            call = _PT_PLAYS_IN_DETAILS[tok.lower()]
            detail_labels.append(f"play: {call}")
            continue
        # a coverage word on the offense side belongs to the defense ('bs(stay):m2m(over)')
        if _pt_action(tok)[0] is None and _pt_coverage(tok)[0] is not None:
            moved_cov.append(tok)
            continue
        # Optional floor spots ("LW", "RS", "LW 3") may ride in the details; they go to location/finish.
        loc = next((lname for lpat, lname in _PD_LOCATIONS
                    if re.fullmatch(r"\s*(?:" + lpat + r")(?:\s*3)?\s*", tok.lower())), None)
        if loc:
            spots.append(loc + (" 3" if re.search(r"\b3\s*$", tok) else ""))
            detail_labels.append(spots[-1])
            continue
        name, rank, pos = _pt_action(tok)
        if name is None:
            errors.append(f"unknown offensive detail '{tok}'")
            detail_labels.append(tok)
            continue
        actions.append((name, rank, pos))
        detail_labels.append(name + (f" -> {pos}" if pos else ""))
    if spots:
        out["play_location"] = spots[0].replace(" 3", "")
        out["finish_spot"] = spots[-1] if len(spots) > 1 or spots[-1].endswith(" 3") else None
    out["play_formation"] = formation
    out["play_set"] = call
    out["play_details"] = " | ".join(detail_labels)
    out["play_actions"] = " | ".join(dict.fromkeys(a for a, _, _ in actions))
    ranked = sorted(((r, i, a) for i, (a, r, _) in enumerate(actions)), key=lambda x: (x[0], x[1]))
    out["primary_action"] = ranked[0][2] if ranked else None

    # ---- Defense: [press -] formation (details) ----
    dfields, ddetails, derr = _pt_parse_defense(def_txt)
    errors += derr
    out.update(dfields)

    # ---- Defensive details: "<jersey><code>", paired to the offensive screen they answer ----
    if call_is_action and call in (_PT_OFFBALL_SCREENS | _PT_BALL_SCREENS) and not any(a == call for a, _, _ in actions):
        actions.append((call, 1, None))             # the call itself is the screen ('bs:m2m(tl)')
    offball = [i for i, (a, _, _) in enumerate(actions) if a in _PT_OFFBALL_SCREENS]
    ball = [i for i, (a, _, _) in enumerate(actions) if a in _PT_BALL_SCREENS]
    used, cov_names, cov_detail, ddl = set(), [], [], []
    reminders = []
    for tok in moved_cov + _pt_tokens(ddetails):
        if re.match(r"^(deny|double)", tok.strip().lower()):
            ddl.append(_pt_player_detail(tok))
            continue
        m = re.fullmatch(r"#?\s*(\d{1,2})?\s*([a-z+&0-9 ]+?)", tok.lower())
        if not m:
            errors.append(f"unreadable defensive detail '{tok}'")
            continue
        jersey, code = m.group(1), m.group(2).strip()
        name, fam, _conf = _pt_coverage(code)
        if name is None:
            errors.append(f"unknown coverage code '{code}'")
            name = code
        pool = offball if fam == "offball" else ball if fam == "ball" else offball + ball
        target = next((i for i in sorted(pool) if i not in used), None)
        if target is None:
            target = next((i for i in offball + ball if i not in used), None)
        if target is not None:
            used.add(target)
            screen = actions[target][0]
        else:
            screen = "Ball Screen" if fam == "ball" else "Off-ball screen" if fam == "offball" else "Screen"
            reminders.append(f"'{tok}': no screen tagged on offense to pair it with")
        if not jersey:
            # coaches: missing numbers were forgotten, not meant -- the tag still reads; the note says what to add
            reminders.append(f"add the defender's jersey number to '{tok}'")
        cov_names.append(name)
        # Jersey is the DEFENDER's number (staff-confirmed): "5tl" = defender #5 top-locked the down screen.
        cov_detail.append(f"{screen}: {name}{f' (def #{jersey})' if jersey else ''}")
        ddl.append(f"#{jersey} {name}" if jersey else name)
    out["defense_details"] = " | ".join(ddl)
    out["coverage_detail"] = " | ".join(cov_detail)
    out["defense_coverage"] = " | ".join(dict.fromkeys(cov_names))

    # ---- Situation / call naming, same conventions as the legacy decoder so summaries line up ----
    situations = list(dict.fromkeys(situations))
    oob = next((s for s in situations if s in ("BLOB", "SLOB")), None)
    if oob:
        out["play_situation"] = oob + (" (ATO)" if "ATO" in situations else "")
    elif "ATO" in situations:
        out["play_situation"] = "ATO"
    elif "Transition" in situations:
        out["play_situation"] = "Transition"
    # Motion and action-named calls ("Horns-BS") read with their formation ("5 Out Motion", "Horns Ball
    # Screen"); a named set ("Panther") carries its own identity, same as the legacy naming.
    base = f"{formation} {call}" if formation and (call == "Motion" or call_is_action) else call
    out["play_call"] = f"{oob} {base}" if oob else base
    out["play_series"] = oob or call
    if errors:
        out["decode_quality"] = "Partial"
        out["decode_note"] = "tag errors: " + "; ".join(errors)
    if reminders:
        out["decode_note"] = (out["decode_note"] + "; " if out["decode_note"] else "") + "reminders: " + "; ".join(reminders)
    if re.search(_PD_REVIEW, raw.lower()):
        out["decode_quality"] = "Needs review"
        out["decode_note"] = "tagger flagged it" + ("; " + out["decode_note"] if out["decode_note"] else "")
    return out


def _pt_is_defense_only(title):
    """A no-colon title that is ENTIRELY a defense tag ("m2m", "122 - m2m", "23 (12drop)")."""
    t = str(title or "").strip()
    if not t or ":" in t:
        return False
    fields, _d, errs = _pt_parse_defense(t)
    return not errs and fields["defense_type"] is not None


def decode_play_title(title, known_players=()):
    """Router. Every title is re-decoded from its raw text on every run (nothing cached), so a change to the
    tagging standard only needs a change here.
      1. parentheses + colon                -> structured decoder
      2. no colon, and the whole title is a defense tag ("m2m", "122 - m2m") -> structured, defense only
      3. colon + formation dash, no parentheses ("5 out-Motion: m2m") -> structured IF it reads with zero tag errors, else
         the legacy keyword decoder (legacy titles like "UWW M2M: BLOB" misuse the colon)
      4. everything else                    -> legacy keyword decoder
    Both decoders return the same keys so _pl_decode_all builds consistent columns."""
    out = None
    raw_title = title
    title = _pt_normalize(title) if str(title or "").strip() else title
    try:
        if is_structured_title(title) or _pt_is_defense_only(title):
            out = decode_structured_title(title, known_players)
        elif ":" in str(title or "") and "-" in str(title).split(":", 1)[0]:
            trial = decode_structured_title(title, known_players)
            if "tag errors" not in trial["decode_note"]:
                out = trial
    except Exception as exc:  # never let one bad tag stop the parser -- surface it instead
        out = _decode_play_title_legacy(title, known_players)
        out.update(tag_format="Structured (failed)", decode_quality="Needs review", play_details="",
                   defense_formation=out.get("defense_type"), defense_details="", coverage_detail="",
                   decode_note=f"structured decode failed: {exc}")
    if out is None:
        out = _decode_play_title_legacy(title, known_players)
        out.update(tag_format="Legacy" if str(title or "").strip() else None, play_details=out.get("play_actions", ""),
                   defense_formation=out.get("defense_type"), defense_details="", coverage_detail="")
    # Situation stated in the tag wins; otherwise _pl_infer_situation fills it from Synergy / play-by-play.
    out["situation_source"] = "Tag" if out["play_situation"] != "Half court" else None
    out["play_title"] = re.sub(r"\s+", " ", str(raw_title or "")).strip() or out.get("play_title")
    # Situation-only titles ('tran', 'tran:m2m', 'oreb') -- coaches: fine as is, a possession with no play call
    off_part = str(title or "").split(":", 1)[0].strip().lower()
    sit_only = {"tran": "Transition", "transition": "Transition", "oreb": "Offensive rebound",
                "o-reb": "Offensive rebound", "putback": "Offensive rebound"}
    if off_part in sit_only:
        out.update(play_situation=sit_only[off_part], situation_source="Tag", play_set=None, play_call=None,
                   play_series=None, decode_quality="No call",
                   decode_note=(out.get("decode_note") or "situation only (no play call)"))
    return out


# Plain-English meaning for every shorthand the decoder knows, and how sure that reading is. Exported so the
# brief and the app can print it -- a coach should be able to see exactly how "RIC" became "Ricky".
PLAY_GLOSSARY = pd.DataFrame([
    ("BLOB / SLOB", "Baseline / sideline out-of-bounds play", "Standard"),
    ("ATO", "After-timeout play", "Standard"),
    ("Opener", "First set of a half", "Inferred"),
    ("5 Out / 4-1 (41) / 3-2 (32) / 2-3 (23)", "Floor alignment: perimeter-post split", "Standard"),
    ("33", "Named set (alignment not stated)", "Inferred"),
    ("HiLo / Hi-Low", "High-low post alignment", "Standard"),
    ("Horns", "Two bigs at the elbows", "Standard"),
    ("Box / Line / Stairs / 2-1-1", "Inbounds alignments", "Standard"),
    ("OK State, Panther, Cheetah, Flop, Highway, Pistol, Monty", "Named sets from the staff's playbook", "Standard"),
    ("DHO / DH / handoff", "Dribble handoff", "Standard"),
    ("BS", "Ball screen", "Standard"),
    ("DS", "Down screen", "Standard"),
    ("STS", "Screen the screener", "Standard"),
    ("Sci / Sci Sc", "Scissors cut off the post", "Inferred"),
    ("Flair / Flare", "Flare screen", "Standard"),
    ("RJ / Reject", "Ball handler rejects the screen", "Standard"),
    ("DD", "Double drag ball screen", "Inferred"),
    ("IVO", "Iverson cut", "Inferred"),
    ("RIC / Ricky", "Named action (ricochet screen) -- confirm with staff", "Inferred"),
    ("Zoom / Twirl / Grenade / Hammer / Pat Miller / Breddy / Rip / Spain", "Named actions", "Standard"),
    ("PT", "Post touch -- confirm with staff", "Inferred"),
    ("BC Cut", "Backdoor cut", "Inferred"),
    ("LW RW LC RC LS RS LB RB LE RE Top", "Left/right wing, corner, side, block, elbow; top of the key", "Standard"),
    ("LW 3 / top key 3", "Where the three-point shot came from", "Standard"),
    ("Rewatch / TBD / ? / mess up", "Tagger flagged the clip for review -- excluded from set rankings", "Standard"),
    # Defense faced (new tagging logic, after the colon: "... : M2M SOFT HEDGE")
    ("M2M", "Man-to-man defense", "Standard"),
    ("2-3 / 3-2 / 1-3-1 Zone / Zone", "Zone defense, with subtype when stated", "Standard"),
    ("Press / 1-2-1-1 / 1-2-2 / 1-2", "Full-court press, with formation when named", "Standard"),
    ("Switch / Hedge / Soft Hedge / Ice / Drop", "Ball-screen coverage call", "Standard"),
    ("Deny / Jam", "On-ball or off-ball denial call", "Inferred"),
    ("Show / Under / Fight / Blitz", "More ball-screen coverage calls -- show and recover, go under, fight "
     "over the top, or trap it", "Standard"),
    ("Token", "A named ball-screen coverage call -- confirm the read with staff", "Inferred"),
    # New situation and set names, from the coaches' latest tagging convention:
    ("Tran / Transition", "Live-ball offense before the defense is set, as its own situation (not folded "
     "into Half court)", "Standard"),
    ("Flow / Chin / Twins / Snap / Black / Bulldog / Pinch / Blocker-Mover", "Named sets or formations",
     "Standard"),
    ("Guards Cross / UCLA", "Named actions -- two guards exchange; a screen off a UCLA cut", "Standard"),
    # Structured tag format (Sept 2026): "5 out-Motion(pass 5,ds,reject,bs): m2m (5tl,12drop)"
    ("Formation-Call(details): [Press] Defense (details)", "Structured tag: formation, play call (Motion if "
     "blank), ordered offensive details; press (None if blank), defensive formation, coverage details", "Standard"),
    ("pass 5 / 5 bs", "Number inside the OFFENSE parentheses = position (1-5), not jersey", "Standard"),
    ("tl", "Top lock on an off-ball screen", "Standard"),
    ("trail / chase / cheat / over / through / bump", "Off-ball (down/flare/pin) screen coverages", "Standard"),
    ("drop / hedge / show / ice / blitz / under / fight / switch", "Ball-screen coverages", "Standard"),
    ("R+J", "Run-and-jump press", "Standard"),
    ("122 - m2m", "Press slot before the dash: 1-2-2 press, falling back to man-to-man (1211, 221, 12 likewise)",
     "Standard"),
    ("5tl", "DEFENDER #5 top-locked the screen (the number is the defender's jersey)", "Standard"),
    ("m2m (alone)", "Defense-only tag on a possession where only the defense is being charted", "Standard"),
    # coach definitions (parser_check_WOS_at_WWW_1-3-26.xlsx, Questions for coaches)
    ("HI BS", "High (center) ball screen", "Standard"),
    ("Over (offense)", "5-out play call: go over the 5 man after the pass to him", "Standard"),
    ("Swing", "Pass across the middle of the court", "Standard"),
    ("Swing Screen", "Screen set on the low block", "Standard"),
    ("Ricky", "A screen followed by an immediate rescreen", "Standard"),
    ("Doubleclear / Doublecut", "Two players clear / cut out to open an iso", "Standard"),
    ("Slip", "Screener slips to the basket before/without setting the screen", "Standard"),
    ("Ghost", "Run up like a screen, then run through it without setting it", "Standard"),
    ("Stagger", "Two players set down screens in a row for one player", "Standard"),
    ("Zoom", "Dribble handoff with a screen from a player in between", "Standard"),
    ("DD", "Dribble drive", "Standard"),
    ("Flash / Pop / Iso", "Flash to the ball / screener pops out for 3 / one player on his own", "Standard"),
    ("P-wing / Pass corner", "Pass to the wing / pass to the corner", "Standard"),
    ("Line / Box (inbounds)", "Line: two in the corners, two on the blocks. Box: one on each elbow and each block", "Standard"),
    ("Over (coverage)", "On-ball defender goes over the screen and stays with his man", "Standard"),
    ("Under (coverage)", "Defender goes under the screen and stays on his man", "Standard"),
    ("Switch", "The two defenders trade men on the screen", "Standard"),
    ("Stay", "Ball handler rejects the screen; the defender stays with him", "Standard"),
    ("Show & GB", "Show (soft or hard hedge), then get back to the screener", "Standard"),
    ("Switch2nd", "Stayed on the first screen, switched the second", "Standard"),
    ("TL", "Top lock", "Standard"),
    ("RJ / press(rj)", "Run-and-jump press (falls back into man)", "Standard"),
    ("press(12)", "1-2-2 press (falls back into man)", "Standard"),
    ("Token", "Token press: pressure without going for steals", "Standard"),
    ("deny / double + player", "Denied a player the ball / double-teamed him (e.g. denymadz, deny15)", "Standard"),
], columns=["shorthand", "meaning", "confidence"
])


def _pl_norm(text):
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _pl_result_points(result):
    """Points a Result tag implies, or None when it doesn't say (a drawn foul, 'No Violation')."""
    t = re.sub(r"\s+", " ", str(result or "")).strip().lower()
    if t == "make 3 pts":
        return 3
    if t == "make 2 pts":
        return 2
    m = re.match(r"^(\d) pts$", t)
    if m:
        return int(m.group(1))
    if t.startswith("miss") or t in ("turnover", "shot clock violation", "kicked ball"):
        return 0
    return None


def _pl_compatible(result, event_type):
    t = str(result or "").lower()
    if t.startswith("make"):
        return event_type == "made_shot"
    if t.startswith("miss"):
        return event_type == "missed_shot"
    if "turnover" in t or "violation" in t:
        return event_type == "turnover"
    if "foul" in t or re.match(r"^\d pts$", t):
        return event_type in ("free_throw_made", "free_throw_missed", "made_shot", "foul")
    return False


def _pl_load(path, label):
    if not os.path.exists(path):
        _pl_problems.append(f"{os.path.basename(path)} not found in INPUT_DIR -- {label} play calls skipped")
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except Exception as e:
        _pl_problems.append(f"{os.path.basename(path)}: could not read ({e})")
        return pd.DataFrame()
    need = {"Title", "Result", "Date", "Pd.", "Clock", "Player", "Team"}
    if need - set(df.columns):
        _pl_problems.append(f"{os.path.basename(path)}: missing column(s) {sorted(need - set(df.columns))}")
        return pd.DataFrame()
    df = df[df["Player"].notna() & df["Title"].notna()].copy()
    df["game_date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
    _future = df["game_date"].notna() & (df["game_date"] >= reference_date.date())
    if int(_future.sum()):
        print(f"  {os.path.basename(path)}: dropped {int(_future.sum())} clip(s) dated on/after {reference_date_str}.")
    df = df[~_future]
    df["period"] = df["Pd."].apply(_recap_period_label)
    df["time_remaining_seconds"] = df["Clock"].apply(_clock_to_seconds)
    df["player"] = df["Player"].astype(str).str.strip()
    df["result"] = df["Result"].astype(str).str.strip()
    df["game_code"] = df.get("Game", pd.Series(index=df.index, dtype=object))
    ss = df.get("Synergy String", pd.Series(index=df.index, dtype=object))
    df["synergy_string"] = ss
    # First step after "<jersey> <name> > " -- how the possession ENDED in Synergy's terms (Spot-Up, P&R Ball
    # Handler, ...). Different from the play call, which is what was drawn up.
    df["synergy_play_type"] = ss.astype(str).str.extract(r"^\s*\d*\s*[^>]+>\s*([^>]+?)\s*(?:>|$)")[0]
    df["clip_number"] = df.get("#")
    return df.reset_index(drop=True)


def _pl_team_label(csv_team, labels):
    """Map a clip's Team ("Aurora University") onto the play-by-play's label ("Aurora Spartans") by word
    overlap. None when nothing overlaps -- a guess here would attribute a possession to the wrong team."""
    words = {w for w in re.findall(r"[a-z]+", str(csv_team).lower()) if len(w) > 2 and w not in ("university", "college", "the")}
    if "whitewater" in words:
        return _PL_UWW if _PL_UWW in labels else None
    best, score = None, 0
    for lab in labels:
        lw = {w for w in re.findall(r"[a-z]+", str(lab).lower()) if len(w) > 2}
        s = len(words & lw)
        if s > score:
            best, score = lab, s
    return best


def _pl_match(clips, events, offense_label_for):
    """Attach event_index / matched_by / pbp points to each clip. `offense_label_for(clip_row, game_labels)`
    returns the play-by-play team label for the clip's offense."""
    clips = clips.copy()
    clips["event_index"] = pd.NA
    clips["matched_by"] = None
    clips["points"] = None
    clips["points_source"] = None
    if clips.empty:
        return clips
    # CONFIRMED BUG (fixed here): the offense team was only resolved for clips whose game had play-by-play, so
    # a game with no _pbp file dropped every clip out of the team's scouting (offense_team was blank). Resolve
    # it from every label we know about, play-by-play or not.
    _all_labels = set(events["team"].dropna().unique()) if not events.empty else set()
    _all_labels |= {_PL_UWW} | ({upcoming_opponent_short} if upcoming_opponent_short else set())
    clips["team"] = [offense_label_for(c, _all_labels) for _, c in clips.iterrows()]
    ev = (events[events["team"].notna() & events["player"].notna()].copy() if not events.empty
          else pd.DataFrame(columns=list(events.columns) + ["team", "player"]))
    ev["_desc"] = ev["video_description"].apply(_pl_norm) if "video_description" in ev.columns else ""
    by_game = {g: grp for g, grp in ev.groupby("game_date")} if not ev.empty else {}
    used = set()
    for i, c in clips.iterrows():
        grp = by_game.get(c["game_date"])
        if grp is None:
            continue
        team = offense_label_for(c, set(grp["team"].dropna().unique())) or c["team"]
        clips.at[i, "team"] = team
        if team is None:
            continue
        cand = grp[(grp["team"] == team) & (grp["period"] == c["period"])]
        cand = cand[~cand.index.isin(used)]
        if cand.empty:
            continue
        sig = _pl_norm(c.get("synergy_string"))
        secs = c["time_remaining_seconds"]
        best, how = None, None
        if sig:
            hit = cand[cand["_desc"] == sig]
            if not hit.empty:
                if secs is not None and pd.notna(secs):
                    hit = hit.assign(_dt=(hit["time_remaining_seconds"] - secs).abs()).sort_values("_dt")
                best, how = hit.index[0], "synergy string"
        if best is None and secs is not None and pd.notna(secs):
            cand = cand.assign(_dt=(cand["time_remaining_seconds"] - secs).abs(),
                               _ok=cand["event_type"].apply(lambda e: _pl_compatible(c["result"], e)))
            same = cand[(cand["player"].str.lower() == c["player"].lower()) & (cand["_dt"] <= _PL_CLOCK_TOL)]
            same = same.sort_values(["_ok", "_dt"], ascending=[False, True])
            if not same.empty:
                best, how = same.index[0], "player + clock"
            else:
                near = cand[cand["_ok"] & (cand["_dt"] <= 3)].sort_values("_dt")
                if not near.empty:
                    best, how = near.index[0], "clock + result"
        if best is not None:
            used.add(best)
            clips.at[i, "event_index"] = best
            clips.at[i, "matched_by"] = how
    # Points from the play-by-play: everything the offense scored at the matched event's clock stamp.
    scoring = ev[ev["event_type"].isin(["made_shot", "free_throw_made"])].copy() if not ev.empty else pd.DataFrame()
    pts_at = {}
    if not scoring.empty:
        scoring["_pts"] = scoring.apply(
            lambda r: 1 if r["event_type"] == "free_throw_made"
            else int(pd.to_numeric(pd.Series([r.get("shot_type")]), errors="coerce").fillna(2).iloc[0]), axis=1)
        pts_at = scoring.groupby(["game_date", "team", "period", "time_remaining_seconds"])["_pts"].sum().to_dict()
    # the matched event's event_order -- a stable link from a clip to its play-by-play row (the app's play-by-play
    # opens each play's possession replay with it; requested)
    clips["pbp_event_order"] = pd.NA
    for i, c in clips.iterrows():
        if pd.notna(c["event_index"]):
            e = ev.loc[c["event_index"]]
            clips.at[i, "pbp_event_order"] = e.get("event_order")
            clips.at[i, "points"] = int(pts_at.get((e["game_date"], e["team"], e["period"], e["time_remaining_seconds"]), 0))
            clips.at[i, "points_source"] = "play-by-play"
        else:
            p = _pl_result_points(c["result"])
            if p is not None:
                clips.at[i, "points"] = p
                clips.at[i, "points_source"] = "result tag"
    return clips


def _pl_lineup_for(clips, events, lineup_col):
    """The 5-man unit on the floor at the matched pbp event, pulled onto each clip -- not decoded from the
    clip itself, so this runs after _pl_match assigns event_index, using whichever per-event lineup column
    that side's events carry (see the "On-court 5-man lineups" cells: uww_lineup for our own games,
    self_lineup for the opponent's prior games). None for an unmatched clip; there's no pbp moment to read
    a lineup from, and guessing one from context wouldn't be honest about what's actually known."""
    out = pd.Series([None] * len(clips), index=clips.index, dtype=object)
    if lineup_col not in events.columns:
        return out
    matched = clips["event_index"].notna()
    if matched.any():
        out.loc[matched] = clips.loc[matched, "event_index"].map(events[lineup_col])
    return out


def _pl_decode_all(clips, roster_names):
    if clips.empty:
        return clips
    decoded = pd.DataFrame([decode_play_title(t, roster_names) for t in clips["Title"]], index=clips.index)
    return pd.concat([clips, decoded], axis=1)


def _pl_attach(events, clips):
    """Write the decoded fields onto matched events. An existing play_call (from a coach recap) is kept
    where this file has nothing for that event."""
    events = events.copy()
    for col in _PL_EVENT_COLS:
        if col not in events.columns:
            events[col] = None
    matched = clips[clips["event_index"].notna()]
    for _, c in matched.iterrows():
        idx = c["event_index"]
        for col in _PL_EVENT_COLS:
            src = "decode_quality" if col == "play_decode_quality" else col
            val = c.get(src)
            if val is not None and not (isinstance(val, float) and pd.isna(val)) and val != "":
                events.at[idx, col] = val
    return events


# ---- Shot clock, estimated from the game clock (no shot-clock column exists in the play-by-play) --------
# CONFIRMED CHANGE (requested): estimated from when each possession started and when it ended, using NCAA
# men's basketball rules (Division III plays the same shot clock as D1/D2): 30 seconds on any change of
# possession -- a make, a turnover, a defensive rebound, the last free throw of a trip, the start of a
# period -- and a 20-second reset when the SAME team keeps the ball off its own offensive rebound (the
# 2019-20 NCAA rule change). There is no shot-clock column to read, so this reconstructs the clock's state
# at every event by walking each game/period in order and tracking whose possession it is and when that
# possession began; the game-clock reading at the moment a possession starts stands in for the shot-clock
# reset, and the moment of the matched event (usually the shot or turnover) gives the reading it ended at.
# This is an ESTIMATE, not a read of an actual shot-clock display -- see decode_note-style caveats below on
# where it can be off, and _SC_QUALITY_NOTE, exported alongside the numbers.
_SC_END_TEAM_EVENTS = {"made_shot", "turnover"}       # possession moves to the other team immediately
_SC_MISS_EVENTS = {"missed_shot", "free_throw_missed"}  # possession is undecided until the rebound
_SC_OFF_REBOUND = {"rebound_offensive", "team_deadball_rebound_offensive"}   # same team keeps it -- reset to 20
_SC_DEF_REBOUND = {"rebound_defensive", "team_deadball_rebound_defensive"}   # ball changes hands -- reset to 30
_SC_FT_MADE = {"free_throw_made"}                      # treated as ending the trip -- see the caveat below
_SC_QUALITY_NOTE = (
    "Estimated from the game clock using NCAA men's shot-clock rules (30 sec on a change of possession, "
    "20 sec after an offensive rebound), not read from an actual shot-clock display. A possession is timed from "
    "the moment the previous one ended (made basket, turnover, defensive rebound or last free throw) -- the "
    "inbound itself is a second or two later. Substitutions, timeouts and fouls don't restart it; every free "
    "throw of a trip carries the time used when the foul happened. 0 seconds is real on putbacks and on free "
    "throws in the same second as a change of possession."
)


def estimate_shot_clock(events):
    """Returns (shot_clock_used, shot_clock_max) as two Series aligned to `events`' index -- seconds run off
    the shot clock when each event happened, and the reset ceiling (30 or 20) that applied to the
    possession it happened during. None where the game clock or event type is missing.

    CONFIRMED BUG (fixed; the coach-review workbook showed 101 of 154 matched clips at 0 seconds used). Two causes:
      1. The play-by-play never records the moment a possession BEGINS, and a new possession was started at its own
         first recorded event (usually the shot / turnover / foul being measured) -> 0 seconds. A possession now
         starts when the previous one ENDED: the made basket, turnover, defensive rebound or LAST free throw.
      2. Any event by the other team -- a substitution, timeout, a defensive foul -- was taken as a possession change
         and restarted the clock. Only events that show who HAS the ball (shots, free throws, turnovers, rebounds,
         assists) decide possession now; subs, timeouts, fouls, steals and blocks never restart it."""
    used = pd.Series([None] * len(events), index=events.index, dtype=object)
    cmax = pd.Series([None] * len(events), index=events.index, dtype=object)
    if events.empty or "team" not in events.columns:
        return used, cmax
    ev = events[events["time_remaining_seconds"].notna() & events["event_type"].notna()].sort_values("event_order")
    if ev.empty:
        return used, cmax
    offense_events = {"made_shot", "missed_shot", "free_throw_made", "free_throw_missed", "turnover"}
    for _keys, grp in ev.groupby(GAME_KEYS + ["period"], dropna=False):
        poss_team, poss_start, poss_max = None, None, 30
        last_end = None                              # clock when the last possession ended (the next one starts here)
        last_shot = (None, None)                     # (clock, seconds used) of the last made shot -- for its assist
        trip = (None, None)                          # (clock, seconds used) when a free-throw trip began (the foul)
        for idx, row in grp.sort_values("event_order").iterrows():
            et, clock, team = row["event_type"], float(row["time_remaining_seconds"]), row.get("team")
            if et == "period_marker":
                poss_team, poss_start, poss_max, last_end = None, None, 30, clock
                continue
            if last_end is None:
                last_end = clock                     # first event of the period we can see
            in_trip = trip[0] == clock and (et in _SC_FT_MADE or et in _SC_MISS_EVENTS and et.startswith("free_throw")
                                            or et.startswith("team_deadball"))
            if in_trip:
                # between free throws of one trip: the dead-ball "rebound" is bookkeeping, not a new shot clock
                used.at[idx] = trip[1]
                cmax.at[idx] = poss_max if poss_start is not None else 30
                last_ft_ = et in _SC_FT_MADE and (pd.isna(row.get("ft_num")) or pd.isna(row.get("ft_total"))
                                                  or row.get("ft_num") == row.get("ft_total"))
                if last_ft_:
                    poss_team, poss_start, poss_max, last_end = None, None, 30, clock
                continue
            if et in _SC_DEF_REBOUND and isinstance(team, str):
                poss_team, poss_start, poss_max = team, clock, 30
            elif et in _SC_OFF_REBOUND and isinstance(team, str):
                poss_team, poss_start, poss_max = team, clock, 20
            elif et in offense_events and isinstance(team, str) and team != poss_team:
                # this team has the ball: its possession began when the previous one ended
                poss_team, poss_start, poss_max = team, last_end, 30
            elapsed = None
            if et == "assist" and last_shot[0] == clock:
                elapsed = last_shot[1]               # the pass that set up the basket: same moment as the basket
            elif poss_start is not None:
                elapsed = min(max(poss_start - clock, 0.0), poss_max)
            elif last_end is not None:
                # nobody has recorded the ball yet (a foul, steal, timeout before the offense's first event):
                # the clock has been running since the last possession ended
                elapsed = min(max(last_end - clock, 0.0), 30.0)
            used.at[idx] = elapsed
            cmax.at[idx] = poss_max if poss_start is not None else (30 if elapsed is not None else None)
            if et == "made_shot":
                last_shot = (clock, elapsed)
            if et.startswith("free_throw") and trip[0] != clock:
                trip = (clock, elapsed)              # first free throw of the trip: the time used at the foul
            last_ft = et in _SC_FT_MADE and (pd.isna(row.get("ft_num")) or pd.isna(row.get("ft_total"))
                                              or row.get("ft_num") == row.get("ft_total"))
            if et in _SC_END_TEAM_EVENTS or last_ft:
                poss_team, poss_start, poss_max, last_end = None, None, 30, clock
            elif et in _SC_DEF_REBOUND:
                last_end = clock
            # missed shots / missed free throws: the possession stays open until the rebound
    return used, cmax


for _sc_df_name in ("pbp_events", "pbp_events_upcoming"):
    _sc_df = globals()[_sc_df_name]
    if not _sc_df.empty:
        _sc_used, _sc_max = estimate_shot_clock(_sc_df)
        _sc_df["shot_clock_used"] = _sc_used
        _sc_df["shot_clock_max"] = _sc_max
        globals()[_sc_df_name] = _sc_df

# ---- Personnel grouping TYPE (two bigs / base five / small-ball), not the literal 5-man unit -------------
# CONFIRMED CHANGE (requested): the literal on-court lineup is already broken out, player by player, in
# Top Lineups -- Personnel Grouping Tendencies should instead pool tendencies across every lineup that
# shares a personnel PROFILE (how many traditional bigs are on the floor), the way a coach actually talks
# about it ("their two-big lineup runs more post touches"), not repeat the same five names again.
#
# "Big" here means one of a team's two highest-rebounding players by tagged rebounds in the play-by-play --
# a self-contained stand-in for position/height that needs nothing beyond the play-by-play already built.
# It's an approximation (a high-rebounding wing could get swept in, and a team's true second big could be
# a close third) -- good enough to separate a traditional frontcourt from a small-ball group, not a
# roster-accurate positional breakdown.
_PG_TYPE_LABELS = ("Two-big lineup", "Base five (one big)", "Small / shooting five (no true big)")
_PG_REBOUND_EVENTS = ["rebound_offensive", "rebound_defensive", "team_deadball_rebound_offensive",
                      "team_deadball_rebound_defensive"]


def _pg_rebound_leaders(events, team_label, top_n=2):
    if events.empty or "team" not in events.columns or not team_label:
        return set()
    reb = events[(events["team"] == team_label) & events["event_type"].isin(_PG_REBOUND_EVENTS)
                & events["player"].notna()]
    if reb.empty:
        return set()
    return set(reb["player"].value_counts().head(top_n).index)


def _pg_grouping_type(lineup_str, bigs_set):
    if not lineup_str or not bigs_set or not isinstance(lineup_str, str):
        return None
    members = [p.strip() for p in lineup_str.split(",") if p.strip()]
    if not members:
        return None
    n_big = sum(1 for m in members if m in bigs_set)
    return _PG_TYPE_LABELS[0] if n_big >= 2 else _PG_TYPE_LABELS[1] if n_big == 1 else _PG_TYPE_LABELS[2]


_pg_uww_bigs = _pg_rebound_leaders(pbp_events, _PL_UWW)
_pg_opp_bigs = _pg_rebound_leaders(pbp_events_upcoming, upcoming_opponent_short)

# ---- Granular grouping labels from real roster positions (requested) ---------------------------------
# "Two bigs / one big / no big" is coarse -- it can't tell a three-guard look from a four-guard one. The
# roster-page scrape now supplies each player's listed position, so a lineup can be described the way a coach
# says it out loud: "3G-1W-1B". Guard/Wing/Big is the grouping that survives FastScout's position strings
# ("G", "G/F", "F/C", "W"); the first letter decides, with F treated as a wing only when paired with a guard.
# Falls back to the rebound-based two-big/one-big/no-big label for a team with no roster positions on file,
# so nothing depends on the scrape having run.
_PG_POS_GROUP = {"G": "G", "W": "W", "F": "W", "C": "B"}


def _pg_position_map():
    ros = globals().get("live_rosters")
    out = {}
    if ros is None or getattr(ros, "empty", True) or "position" not in ros.columns:
        return out
    for _, r in ros.iterrows():
        pos = str(r.get("position") or "").strip().upper()
        if not pos:
            continue
        first, parts = pos[0], [p for p in re.split(r"[/-]", pos) if p]
        group = _PG_POS_GROUP.get(first, "W")
        if first == "F":
            group = "B" if any(p.startswith("C") for p in parts) else "W"
        out[_ros_norm_name(r.get("name")) if "_ros_norm_name" in globals()
            else re.sub(r"\s+", " ", str(r.get("name"))).strip().lower()] = group
    return out


_pg_positions = _pg_position_map()


def _pg_shape_label(lineup_str):
    """"3G-1W-1B" when every player's position is known, else None."""
    if not lineup_str or not isinstance(lineup_str, str) or not _pg_positions:
        return None
    members = [p.strip() for p in lineup_str.split(",") if p.strip()]
    groups = [_pg_positions.get(re.sub(r"\s+", " ", m).strip().lower()) for m in members]
    if not members or any(g is None for g in groups):
        return None
    counts = {g: groups.count(g) for g in ("G", "W", "B")}
    return "-".join(f"{counts[g]}{g}" for g in ("G", "W", "B") if counts[g])


def _pg_grouping_label(lineup_str, bigs_set):
    return _pg_shape_label(lineup_str) or _pg_grouping_type(lineup_str, bigs_set)

# ---- Game situation (leading/trailing big, or clutch), reusing the SAME clutch definition already used
# elsewhere in this pipeline (see the "Clutch-time event log" cell: last 5 minutes of the 2nd half or any
# overtime, score within 8) rather than inventing a second one. Both pbp_events and pbp_events_upcoming carry
# "uww_score"/"opp_score" columns holding the score of whoever's game this is (the team_label / self_team
# passed into build_pbp_events) vs the other team -- so the identical formula applies to either dataframe
# unchanged; for pbp_events_upcoming these are the SCOUTED opponent's own score and their opponent's score
# that game, not literally UWW's.
_GS_CLUTCH_MARGIN = 8
_GS_CLUTCH_SECONDS = 300
_GS_BLOWOUT_MARGIN = 10


def _gs_situation(row):
    if pd.isna(row.get("uww_score")) or pd.isna(row.get("opp_score")):
        return None
    margin = row["uww_score"] - row["opp_score"]
    if (row.get("period") != "H1" and pd.notna(row.get("time_remaining_seconds"))
            and row["time_remaining_seconds"] <= _GS_CLUTCH_SECONDS and abs(margin) <= _GS_CLUTCH_MARGIN):
        return f"Clutch (last 5 min, margin \u2264 {_GS_CLUTCH_MARGIN})"
    if margin >= _GS_BLOWOUT_MARGIN:
        return f"Leading by {_GS_BLOWOUT_MARGIN}+"
    if margin <= -_GS_BLOWOUT_MARGIN:
        return f"Trailing by {_GS_BLOWOUT_MARGIN}+"
    return None  # a comfortable middle -- not one of the situations this breakdown is built to flag


for _gs_df_name in ("pbp_events", "pbp_events_upcoming"):
    _gs_df = globals()[_gs_df_name]
    if not _gs_df.empty and {"uww_score", "opp_score", "period", "time_remaining_seconds"}.issubset(_gs_df.columns):
        _gs_df["game_situation"] = _gs_df.apply(_gs_situation, axis=1)
        globals()[_gs_df_name] = _gs_df

# ---- Offensive vs DEFENSIVE possessions ----------------------------------------------------------------
# Until now every clip in these files was an OFFENSIVE possession, so "defense_type" unambiguously meant
# "the defense this team faced". Once defensive possessions are tagged too, that same field means the
# OPPOSITE thing on half the rows -- the defense this team PLAYED -- and nothing downstream would notice:
# "Aurora scored 1.15 PPP against man" would quietly average together with "Aurora's opponents scored 1.15
# against Aurora's man". Both numbers look plausible. That is exactly the two-things-one-name drift that
# has bitten this project before, so the ambiguity is resolved HERE, once, and the ambiguous field is split
# into two explicitly-named ones that can never be confused downstream.
def _pl_possession_side(df, own_team):
    """Offense when the clip's own team has the ball, Defense when it doesn't. Falls back to Offense with a
    loud problem note when the team can't be read, because silently guessing is what this function exists
    to prevent."""
    if df.empty:
        return df
    df = df.copy()
    if "team" not in df.columns:
        df["possession_side"] = "Offense"
        _pl_problems.append(f"{own_team} plays file has no readable Team column -- every clip assumed to be "
                            f"an OFFENSIVE possession. If defensive possessions are tagged in it, every "
                            f"defense-split table is wrong. Fix the export's Team column.")
        return df
    _own = df["team"].astype(str) == str(own_team)
    _unknown = df["team"].isna() | (df["team"].astype(str).str.strip() == "")
    df["possession_side"] = _own.map({True: "Offense", False: "Defense"})
    df.loc[_unknown, "possession_side"] = "Offense"
    if int(_unknown.sum()):
        _pl_problems.append(f"{own_team} plays file: {int(_unknown.sum())} clip(s) have no Team value -- "
                            f"assumed OFFENSIVE possessions. Check them before trusting defense splits.")
    # The split. defense_faced is what the tagged team's OFFENSE saw; defense_played is what that team's
    # own DEFENSE was in. Exactly one of the two is populated on any given clip.
    _is_off = df["possession_side"] == "Offense"
    for _src, _faced, _played in (("defense_type", "defense_faced", "defense_played"),
                                  ("defense_coverage", "coverage_faced", "coverage_played"),
                                  ("defense_press", "press_faced", "press_played"),
                                  ("defense_press_formation", "press_formation_faced", "press_formation_played")):
        if _src not in df.columns:
            continue
        df[_faced] = df[_src].where(_is_off)
        df[_played] = df[_src].where(~_is_off)
    return df


# ---- Situation, from what's already known about the play (staff: coaches won't tag BLOB/SLOB/ATO/Tran) ----
# CONFIRMED CHANGE (requested): a situation typed in the tag always wins (situation_source "Tag"). Otherwise:
#   * ATO        -- the last non-substitution play-by-play event before the matched event in the same game and
#                   period is a timeout, and the play ended within one shot clock (30 s) of it
#   * Transition -- Synergy classified the possession as Transition
# BLOB vs SLOB cannot be told apart from the play-by-play or the Synergy string (neither records where the
# inbound happened), so those still need the tag -- they are never guessed.
_SIT_SKIP_EVENTS = {"sub_in", "sub_out", "unclassified"}


def _pl_infer_situation(clips, events):
    if clips.empty:
        return clips
    clips = clips.copy()
    if "situation_source" not in clips.columns:
        clips["situation_source"] = None
    keys = [k for k in GAME_KEYS + ["period"] if not events.empty and k in events.columns]
    ordered = (events[events["event_type"].notna()].sort_values("event_order")
               if not events.empty and "event_order" in events.columns else pd.DataFrame())
    groups = {k: g for k, g in ordered.groupby(keys, dropna=False)} if keys and not ordered.empty else {}
    for i, c in clips.iterrows():
        if c.get("situation_source") == "Tag":
            continue
        idx = c.get("event_index")
        if idx is not None and not pd.isna(idx) and idx in events.index and groups:
            ev = events.loc[idx]
            key = tuple(ev[k] for k in keys) if len(keys) > 1 else ev[keys[0]]
            grp = groups.get(key)
            if grp is not None and idx in grp.index:
                prior = grp.loc[:idx].iloc[:-1]
                prior = prior[~prior["event_type"].isin(_SIT_SKIP_EVENTS)]
                if not prior.empty and prior.iloc[-1]["event_type"] == "timeout":
                    t0, t1 = prior.iloc[-1]["time_remaining_seconds"], ev["time_remaining_seconds"]
                    if pd.notna(t0) and pd.notna(t1) and 0 <= t0 - t1 <= 30:
                        clips.at[i, "play_situation"] = "ATO"
                        clips.at[i, "situation_source"] = "Play-by-play (timeout)"
                        continue
        if str(c.get("synergy_play_type") or "").strip().lower() == "transition":
            clips.at[i, "play_situation"] = "Transition"
            clips.at[i, "situation_source"] = "Synergy"
            continue
        clips.at[i, "situation_source"] = "Default (Half court)"
    return clips


# ---- Defender names for the jersey numbers in the defensive details ------------------------------------
# Staff-confirmed: "5tl" = the DEFENDER wearing #5 top-locked the screen. The number belongs to defense_team.
# Jersey -> name comes from (1) live_rosters (roster pages), then (2) the Synergy strings in both play files,
# which always start "<jersey> <name> >" for the player who finished the play. A number that can't be matched
# is left as "#5" -- never guessed.
def _pl_jersey_book():
    book = {}
    ros = globals().get("live_rosters")
    if isinstance(ros, pd.DataFrame) and not ros.empty and {"team", "jersey_number", "name"} <= set(ros.columns):
        for _, r in ros.iterrows():
            j = re.sub(r"\D", "", str(r["jersey_number"]))
            if j:
                book.setdefault(str(r["team"]), {})[j] = str(r["name"]).strip()
    for raw in (globals().get("_pl_uww_raw"), globals().get("_pl_opp_raw")):
        if not isinstance(raw, pd.DataFrame) or raw.empty or "Team" not in raw.columns:
            continue
        for team, ss in zip(raw["Team"], raw.get("synergy_string", pd.Series(dtype=object))):
            m = re.match(r"^\s*(\d{1,2})\s+([^>]+?)\s*>", str(ss or ""))
            if m and str(team).strip():
                book.setdefault(str(team).strip(), {}).setdefault(m.group(1), m.group(2).strip())
    return book


def _trk_numbers_for_game(game_date, game_code, report=None):
    """name (lower case) -> jersey number FOR ONE GAME, most trusted first:
         1. that same game's Synergy descriptions ("15 Collin Madson > ...")
         2. the current roster pages (live_rosters)
         3. any other source (every Synergy description ever seen) -- majority, only if nothing better
    CONFIRMED BUG (fixed; found by the coach: Collin Madson labelled #0, he wears #15). Every Synergy description from
    every game was pooled and the LAST one won -- one entry listed Madson as #0. A conflict is added to `report`."""
    out = {}
    pcs = globals().get("play_calls")
    if isinstance(pcs, pd.DataFrame) and "synergy_string" in pcs.columns:
        same = pcs[(pcs["game_date"].astype(str) == str(game_date)) & (pcs["game_code"].astype(str) == str(game_code))]
        for ss in same["synergy_string"].dropna().astype(str):
            for j_, n_ in re.findall(r"(?:^|>)\s*(\d{1,2})\s+([A-Za-z][^>]*?)\s*(?=>|$)", ss):
                out.setdefault(n_.strip().lower(), j_)
    ros = globals().get("live_rosters")
    if isinstance(ros, pd.DataFrame) and not ros.empty and {"jersey_number", "name"} <= set(ros.columns):
        for _, r in ros.iterrows():
            j_ = re.sub(r"\D", "", str(r["jersey_number"]))
            if j_:
                out.setdefault(str(r["name"]).strip().lower(), j_)
    votes = {}
    for team_book in _pl_jersey_book().values():
        for j_, n_ in team_book.items():
            votes.setdefault(str(n_).strip().lower(), {}).setdefault(j_, 0)
            votes[str(n_).strip().lower()][j_] += 1
    for n_, v in votes.items():
        if n_ not in out:
            out[n_] = max(v, key=v.get)
        elif report is not None and any(j_ != out[n_] for j_ in v):
            report.append(f"{n_.title()}: #{out[n_]} in this game / current roster, "
                          + ", ".join(f"#{j_}" for j_ in v if j_ != out[n_]) + " elsewhere")
    return out


def _review_doc(path):
    """The saved review in a .json file (a dict with a 'checks' and/or 'answers' list), or None for anything else.
    CONFIRMED CHANGE (requested: "accept any .json files in those folders" -- e.g. a review renamed oct-1st.json). Inside
    the review folders (play_review, track_validation, title_review) a review is recognized by what's in it, not by its
    name; any other .json there is ignored. (Downloads still only looks at the browser's own names.)"""
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return None
    if isinstance(d, dict) and (isinstance(d.get("checks"), list) or isinstance(d.get("answers"), list)):
        return d
    return None


def _review_files(folder):
    """Every review .json anywhere under a folder (recognized by its contents)."""
    return sorted({os.path.abspath(f) for f in glob.glob(os.path.join(folder, "**", "*.json"), recursive=True)
                   if _review_doc(f) is not None})


def _play_review_file_saves():
    """File every saved Play review (play_review_*.json) into the RUN FOLDER it came from:
    INPUT_DIR/play_review/<game>/run_<date_time>/. CONFIRMED CHANGE (requested: a new review run for a game only when
    every earlier run folder has its saved .json). The file says its game and run; copies come from Downloads /
    OneDrive's Downloads, and files left at the top of play_review by earlier versions are moved in. A file whose run
    folder no longer exists stays at the top of play_review (it's still read)."""
    import shutil
    prdir = os.path.join(INPUT_DIR, "play_review")
    os.makedirs(prdir, exist_ok=True)
    home = os.path.expanduser("~")

    def run_dir_for(f):
        game = run = None
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
            game, run = d.get("game"), d.get("run")
        except Exception:
            pass
        slug = re.sub(r"[^A-Za-z0-9]+", "_", str(game)).strip("_") if game else None
        if not (slug and run):
            m = re.match(r"play_review_(.+?)_(\d{8}_\d{4,6})", os.path.basename(f))
            if m:
                slug, run = slug or m.group(1), run or m.group(2)
        if slug and run:
            d_ = os.path.join(prdir, slug, f"run_{run}")
            if os.path.isdir(d_):
                return d_
        return None

    # reviews saved from the Streamlit app are committed to the repo's data/play_review_saves (APP_DATA_DIR) and
    # arrive with a git pull -- filed the same way (any name; recognized by contents)
    _app_saves = os.path.join(globals().get("APP_DATA_DIR") or globals().get("OUTPUT_DIR") or ".", "play_review_saves")
    for f in (glob.glob(os.path.join(home, "Downloads", "play_review_*.json"))
              + glob.glob(os.path.join(home, "OneDrive", "Downloads", "play_review_*.json"))
              + [f for f in glob.glob(os.path.join(_app_saves, "*.json")) if _review_doc(f) is not None]):
        dst = os.path.join(run_dir_for(f) or prdir, os.path.basename(f))
        if not os.path.exists(dst) or os.path.getmtime(f) > os.path.getmtime(dst):
            shutil.copy2(f, dst)
    for f in [f for f in glob.glob(os.path.join(prdir, "*.json")) if _review_doc(f) is not None]:   # left at the top
        d_ = run_dir_for(f)
        if d_:
            dst = os.path.join(d_, os.path.basename(f))
            if not os.path.exists(dst) or os.path.getmtime(f) > os.path.getmtime(dst):
                shutil.move(f, dst)
            else:
                os.remove(f)
    return prdir


def coach_checks_all():
    """Every coach check from the validation pages, merged -> (checks, files).
    Reads every track_validation_*.json in INPUT_DIR/track_validation and all its game folders (copying in any found in
    Downloads, OneDrive's Downloads or INPUT_DIR first). Files are merged in the order they were SAVED: if the same box
    (same frame, same spot) was checked more than once, the latest check wins. Each check carries its "game".
    CONFIRMED CHANGE (coach: three checks files in one game folder -- are they all used?). Player tracking, the jersey
    reader test and the recognizer's training set all use this ONE merge now (the reader test used to keep the FIRST
    file's answer for a re-checked box, and the recognizer saved a crop from every file)."""
    import shutil
    vdir = os.path.join(INPUT_DIR, "track_validation")
    os.makedirs(vdir, exist_ok=True)
    home = os.path.expanduser("~")
    for f in (glob.glob(os.path.join(home, "Downloads", "track_validation_*.json"))
              + glob.glob(os.path.join(home, "OneDrive", "Downloads", "track_validation_*.json"))
              + glob.glob(os.path.join(INPUT_DIR, "track_validation_*.json"))):
        dst = os.path.join(vdir, os.path.basename(f))
        if not os.path.exists(dst) or os.path.getmtime(f) > os.path.getmtime(dst):
            shutil.copy2(f, dst)
    # the combined Play review (play_review_*.json) holds player checks too -- filed into their run folders
    prdir = _play_review_file_saves()
    files = sorted(set(_review_files(vdir)) | set(_review_files(prdir)))     # any review .json, whatever its name
    docs = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
            docs.append((str(d.get("saved", "")), os.path.getmtime(f), d))
        except Exception:
            continue
    merged = {}
    for _saved, _mt, d in sorted(docs, key=lambda x: (x[0], x[1])):
        for c in d.get("checks", []):
            key = (c.get("frame_file"), round(float(c.get("px", 0))), round(float(c.get("py", 0))))
            merged[key] = dict(c, game=d.get("game"))
    return list(merged.values()), files


def title_review_answers():
    """Answers from the Auto-Title review pages (title_review_*.json) -> {(clip_key, field): value}.
    'right' = the automatic answer shown was right; 'wrong' + a typed answer = that answer. Every file under
    INPUT_DIR/title_review (and any in Downloads / OneDrive's Downloads, copied in) is merged in the order saved --
    the latest answer for a clip's field wins. Used by the Tag model (as labels for untagged clips) and the review."""
    import shutil
    rdir = os.path.join(INPUT_DIR, "title_review")
    os.makedirs(rdir, exist_ok=True)
    home = os.path.expanduser("~")
    for f in (glob.glob(os.path.join(home, "Downloads", "title_review_*.json"))
              + glob.glob(os.path.join(home, "OneDrive", "Downloads", "title_review_*.json"))):
        dst = os.path.join(rdir, os.path.basename(f))
        if not os.path.exists(dst) or os.path.getmtime(f) > os.path.getmtime(dst):
            shutil.copy2(f, dst)
    prdir = _play_review_file_saves()
    docs = []
    for f in _review_files(rdir) + _review_files(prdir):                      # any review .json, whatever its name
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
            docs.append((str(d.get("saved", "")), os.path.getmtime(f), d))
        except Exception:
            continue
    out, marks = {}, {}
    for _s, _m, d in sorted(docs, key=lambda x: (x[0], x[1])):
        for a in d.get("answers", []):
            key = (a.get("clip_key"), a.get("field"))
            marks[key] = a
            if a.get("verdict") == "right" and a.get("auto") not in (None, ""):
                out[key] = a["auto"]
            elif a.get("verdict") == "wrong" and str(a.get("correct") or "").strip():
                out[key] = str(a["correct"]).strip()
            else:
                out.pop(key, None)
    globals()["_title_review_marks"] = marks          # every mark (incl. "can't tell"), for the accuracy report
    return out


def _pl_name_defenders(clips):
    if clips.empty or "defense_team" not in clips.columns:
        return clips
    clips = clips.copy()
    book = _pl_jersey_book()
    labels = set(book)

    def _lookup(team):
        if team is None or (isinstance(team, float) and pd.isna(team)):
            return {}
        # Roster pages, Synergy exports and the play-by-play name teams differently ("Wisconsin-(Whitewater)
        # Warhawks" vs "UW-Whitewater"), so merge every book entry that maps to this team either way.
        merged = {}
        for key in labels:
            if key == team or _pl_team_label(key, {team}) == team or _pl_team_label(team, {key}) == key:
                for j, n in book[key].items():
                    merged.setdefault(j, n)
        return merged

    def _named(row):
        cd = str(row.get("coverage_detail") or "")
        if "def #" not in cd:
            return None
        names = _lookup(row.get("defense_team"))
        return re.sub(r"def #(\d{1,2})", lambda m: f"def #{m.group(1)} {names[m.group(1)]}" if m.group(1) in names
                      else m.group(0), cd)
    clips["coverage_defenders"] = clips.apply(_named, axis=1)
    return clips


# ---- One plays file (requested): uww_plays.csv holds EVERY tagged clip -------------------------------------
# CONFIRMED CHANGE (requested): the staff keeps ONE export, uww_plays.csv, with UWW's games AND the opponents'
# games together. Which file a clip was in used to decide how it was treated (UWW side vs upcoming-opponent
# side). Now each clip's GAME decides, from its own Team values and dates:
#   UWW       the game is in UWW's play-by-play (pbp_events), or UW-Whitewater is one of its teams
#   Opponent  otherwise, the game is in the upcoming opponent's play-by-play (pbp_events_upcoming), or the
#             upcoming opponent is one of its teams -- their prior games, scouted as before
#   Other     a game between two other teams (e.g. last week's opponent vs someone else). Not part of this
#             week's scouting tables, but its coach tags still train the tag model.
# A meeting between UWW and the upcoming opponent counts as a UWW game (it's in UWW's play-by-play). The
# head-to-head sections read clips by date from either side, so they're unaffected.
# If an old opponent_plays.csv is still in INPUT_DIR it's merged in, and any clip that's in both files is kept
# once (UWW file first).
def _pl_txt(series):
    """Text for building keys: missing -> "" (pandas 3's astype(str) keeps NaN, which breaks key joins)."""
    return series.map(lambda v: "" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v))


def _pl_load_all():
    frames = []
    for path, label in ((_PL_UWW_FILE, "UW-Whitewater"), (_PL_OPP_FILE, "opponent")):
        if os.path.exists(path):
            df = _pl_load(path, label)
            if not df.empty:
                df["_file"] = os.path.basename(path)
                frames.append(df)
    if not frames:
        _pl_problems.append(f"{os.path.basename(_PL_UWW_FILE)} not found in INPUT_DIR -- play calls skipped")
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if len(frames) > 1:
        # Same clip in both files: same game, half, clock, player, Synergy description and result. The n-th
        # repeat within a file is kept distinct, so two real free throws with identical text aren't merged.
        key = ["game_code", "game_date", "period", "Clock", "player", "synergy_string", "result"]
        k = pd.concat([_pl_txt(df[c]) for c in key], axis=1).agg("|".join, axis=1)
        df["_occ"] = df.groupby([df["_file"], k]).cumcount()
        dup = (k + "#" + df["_occ"].astype(str)).duplicated(keep="first")
        print(f"  opponent_plays.csv is still in INPUT_DIR -- merged with uww_plays.csv ({int(dup.sum())} clip(s) "
              f"were in both and kept once). Once everything is in uww_plays.csv, delete opponent_plays.csv.")
        df = df[~dup].drop(columns="_occ").reset_index(drop=True)
    return df


def _pl_route(df):
    """'UWW' / 'Opponent' / 'Other' for every clip, decided per game (Game code + date)."""
    if df.empty:
        return pd.Series(dtype=object)
    uww_dates = set(pbp_events["game_date"].dropna()) if not pbp_events.empty else set()
    opp_dates = set(pbp_events_upcoming["game_date"].dropna()) if not pbp_events_upcoming.empty else set()
    gkey = _pl_txt(df["game_code"]) + "|" + _pl_txt(df["game_date"])
    route = pd.Series(index=df.index, dtype=object)
    for _, idx in df.groupby(gkey).groups.items():
        teams = set(df.loc[idx, "Team"].dropna().astype(str))
        d = df.loc[idx[0], "game_date"]
        has_uww = any(_pl_team_label(t, {_PL_UWW}) for t in teams)
        has_opp = bool(upcoming_opponent_short) and any(_pl_team_label(t, {upcoming_opponent_short}) for t in teams)
        if has_uww and d in uww_dates:
            r = "UWW"
        elif has_opp and d in opp_dates:
            r = "Opponent"
        elif has_uww:
            r = "UWW"
        elif has_opp:
            r = "Opponent"
        else:
            r = "Other"
        route.loc[idx] = r
    return route


_pl_all_raw = _pl_load_all()
_pl_all_raw["_route"] = _pl_route(_pl_all_raw) if not _pl_all_raw.empty else None
_pl_split = {r: (_pl_all_raw[_pl_all_raw["_route"] == r].drop(columns="_route").reset_index(drop=True)
                 if not _pl_all_raw.empty else pd.DataFrame()) for r in ("UWW", "Opponent", "Other")}
if not _pl_all_raw.empty:
    _games = {r: (_pl_txt(g["game_code"]) + _pl_txt(g["game_date"])).nunique() for r, g in _pl_all_raw.groupby("_route")}
    print("  Play clips by game type: " + ", ".join(
        f"{r} {len(_pl_split[r])} clip(s) in {int(_games.get(r, 0))} game(s)" for r in ("UWW", "Opponent", "Other")))

# ---- UW-Whitewater ------------------------------------------------------------------------------------
_pl_uww_raw = _pl_split["UWW"]
_pl_roster = set(pbp_events["player"].dropna().astype(str)) if not pbp_events.empty else set()
_pl_uww = _pl_decode_all(_pl_uww_raw, _pl_roster | set(_pl_uww_raw.get("player", [])))
if not _pl_uww.empty:
    _pl_uww = _pl_match(_pl_uww, pbp_events, lambda c, labels: _pl_team_label(c["Team"], labels) or _PL_UWW)
    _pl_uww["side"] = "UWW"
    _pl_uww = _pl_possession_side(_pl_uww, _PL_UWW)
    # UWW's opponent in that game, from the play-by-play itself.
    _pl_date_opp = (pbp_events.dropna(subset=["game_date"]).groupby("game_date")["opponent"].first().to_dict()
                    if not pbp_events.empty else {})
    _pl_uww["opponent"] = _pl_uww["game_date"].map(_pl_date_opp)
    # Who actually had the ball -- no longer "always us". On a defensive possession the opponent is the
    # offense and we are the defense.
    _pl_uww_off = _pl_uww["possession_side"] == "Offense"
    _pl_uww["offense_team"] = _pl_uww["opponent"].where(~_pl_uww_off, _PL_UWW)
    _pl_uww["defense_team"] = _pl_uww["opponent"].where(_pl_uww_off, _PL_UWW)
    _pl_uww["on_court_lineup"] = _pl_lineup_for(_pl_uww, pbp_events, "uww_lineup")
    # Both fives, by who had the ball (requested) -- the tag model uses them to learn matchups and to limit
    # "who screened" / "who guarded the screen" to the players actually on the floor.
    _pl_uww_their5 = _pl_lineup_for(_pl_uww, pbp_events, "opp_lineup")
    _pl_uww["offense_lineup"] = _pl_uww["on_court_lineup"].where(_pl_uww_off, _pl_uww_their5)
    _pl_uww["defense_lineup"] = _pl_uww_their5.where(_pl_uww_off, _pl_uww["on_court_lineup"])
    _pl_uww["personnel_grouping_type"] = _pl_uww["on_court_lineup"].apply(lambda lu: _pg_grouping_label(lu, _pg_uww_bigs))
    _pl_uww["game_situation"] = _pl_lineup_for(_pl_uww, pbp_events, "game_situation")
    _pl_uww["shot_clock_used"] = _pl_lineup_for(_pl_uww, pbp_events, "shot_clock_used")
    _pl_uww["shot_clock_max"] = _pl_lineup_for(_pl_uww, pbp_events, "shot_clock_max")
    _pl_uww = _pl_infer_situation(_pl_uww, pbp_events)
    _pl_uww = _pl_name_defenders(_pl_uww)
    pbp_events = _pl_attach(pbp_events, _pl_uww)

# ---- Upcoming opponent --------------------------------------------------------------------------------
_pl_opp_raw = _pl_split["Opponent"]
_pl_opp_roster = (set(pbp_events_upcoming["player"].dropna().astype(str))
                  if not pbp_events_upcoming.empty else set())
_pl_opp = _pl_decode_all(_pl_opp_raw, _pl_opp_roster | set(_pl_opp_raw.get("player", [])))
if not _pl_opp.empty:
    # The file is supposed to be THIS week's opponent. If none of its Team values overlap the upcoming
    # opponent's name, it is last week's file -- say so rather than scouting the wrong team.
    _pl_teams = _pl_opp["Team"].dropna().unique()
    if upcoming_opponent_short and not any(_pl_team_label(t, {upcoming_opponent_short}) for t in _pl_teams):
        _pl_problems.append(f"Upcoming-opponent clips are for {list(_pl_teams)}, not {upcoming_opponent_short} -- "
                            f"check the Team column. Opponent play calls skipped.")
        _pl_opp = pd.DataFrame()
if not _pl_opp.empty:
    _pl_opp = _pl_match(_pl_opp, pbp_events_upcoming,
                        lambda c, labels: _pl_team_label(c["Team"], labels))
    _pl_opp["side"] = "Opponent"
    _pl_opp = _pl_possession_side(_pl_opp, upcoming_opponent_short)
    _pl_opp_off = _pl_opp["possession_side"] == "Offense"
    # In pbp_events_upcoming, `opponent` is the THIRD PARTY they played that game.
    _pl_up_opp = (pbp_events_upcoming.dropna(subset=["game_date"]).groupby("game_date")["opponent"].first().to_dict()
                  if not pbp_events_upcoming.empty else {})
    _pl_opp["opponent"] = _pl_opp["game_date"].map(_pl_up_opp)
    _pl_opp["offense_team"] = _pl_opp["team"].where(_pl_opp_off, _pl_opp["opponent"])
    _pl_opp["defense_team"] = _pl_opp["opponent"].where(_pl_opp_off, upcoming_opponent_short)
    _pl_other = _pl_opp["team"].notna() & (_pl_opp["team"] != upcoming_opponent_short)
    if int(_pl_other.sum()):
        print(f"  Upcoming-opponent games: {int(_pl_other.sum())} clip(s) are the OTHER team's offense -- kept, "
              f"but excluded from {upcoming_opponent_short}'s play-call scouting.")
    _pl_opp["on_court_lineup"] = _pl_lineup_for(_pl_opp, pbp_events_upcoming, "self_lineup")
    _pl_opp_their5 = _pl_lineup_for(_pl_opp, pbp_events_upcoming, "their_lineup")
    _pl_opp["offense_lineup"] = _pl_opp["on_court_lineup"].where(_pl_opp_off, _pl_opp_their5)
    _pl_opp["defense_lineup"] = _pl_opp_their5.where(_pl_opp_off, _pl_opp["on_court_lineup"])
    _pl_opp["personnel_grouping_type"] = _pl_opp["on_court_lineup"].apply(lambda lu: _pg_grouping_label(lu, _pg_opp_bigs))
    _pl_opp["game_situation"] = _pl_lineup_for(_pl_opp, pbp_events_upcoming, "game_situation")
    _pl_opp["shot_clock_used"] = _pl_lineup_for(_pl_opp, pbp_events_upcoming, "shot_clock_used")
    _pl_opp["shot_clock_max"] = _pl_lineup_for(_pl_opp, pbp_events_upcoming, "shot_clock_max")
    _pl_opp = _pl_infer_situation(_pl_opp, pbp_events_upcoming)
    _pl_opp = _pl_name_defenders(_pl_opp)
    pbp_events_upcoming = _pl_attach(pbp_events_upcoming, _pl_opp)

# ---- Other teams' games (training data for the tag model only) ------------------------------------------
_pl_other_raw = _pl_split["Other"]
_pl_other = _pl_decode_all(_pl_other_raw, set(_pl_other_raw.get("player", []))) if not _pl_other_raw.empty else pd.DataFrame()
if not _pl_other.empty:
    # No play-by-play for these games: points come from the Result tag, situation from Synergy.
    _pl_other = _pl_match(_pl_other, pd.DataFrame(columns=["team", "player", "game_date", "event_type"]),
                          lambda c, labels: (str(c["Team"]).strip() if pd.notna(c["Team"]) else None) or None)
    _pl_other["side"] = "Other"
    _pl_other["possession_side"] = "Offense"   # from the point of view of the team with the ball
    _pl_other["team"] = _pl_txt(_pl_other["Team"]).str.strip()
    _pl_other["offense_team"] = _pl_other["team"]
    _pl_game_teams = (_pl_other.groupby(["game_code", "game_date"])["team"].apply(lambda t: sorted(set(t)))
                      .to_dict())
    _pl_other["defense_team"] = _pl_other.apply(
        lambda r: next(iter(set(_pl_game_teams.get((r["game_code"], r["game_date"]), [])) - {r["team"]}), None)
        if len(set(_pl_game_teams.get((r["game_code"], r["game_date"]), [])) - {r["team"]}) == 1 else None, axis=1)
    _pl_other["opponent"] = _pl_other["defense_team"]
    _pl_other = _pl_infer_situation(_pl_other, pd.DataFrame())

for _df_name in ("pbp_events", "pbp_events_upcoming"):
    _df = globals()[_df_name]
    for _col in _PL_EVENT_COLS:
        if _col not in _df.columns:
            _df[_col] = None

# ---- Captured frames, joined onto each clip ---------------------------------------------------------------
# CONFIRMED CHANGE (requested): the frame-capture cell records where each clip's 5 frames are
# (uww_clip_frames.csv); the tag model below the play-calls cell learns from them. The clip page and the
# export describe the same clip with the SAME Synergy description and player, but can date a game a day apart
# (the Oshkosh game is "Jan 2, 2026" on the clip page, 1/3/2026 in the export), so the join is description +
# player, the nearest date within a day, then the n-th occurrence in clip order (repeated descriptions such
# as free throws stay one-to-one).
_PL_FRAME_COLS = ["frame_files", "track_files", "track_times", "video_start_s"]


def _pl_attach_frames(clips):
    clips = clips.copy()
    cf = globals().get("clip_frames")
    for c in _PL_FRAME_COLS:
        clips[c] = None
    if clips.empty or not isinstance(cf, pd.DataFrame) or cf.empty or "frame_files" not in cf.columns:
        return clips
    norm = lambda s: s.astype(str).str.replace(r"\s+", " ", regex=True).str.strip().str.lower()
    for _c in ("track_files", "track_times", "video_start_s"):
        if _c not in cf.columns:
            cf = cf.assign(**{_c: None})
    v = cf[cf["frame_files"].notna()].copy()
    if v.empty:
        return clips
    v["_key"] = norm(v["description"]) + "|" + norm(v["player"])
    v["_date"] = pd.to_datetime(v["clip_date"], errors="coerce").dt.date
    v["_pos"] = pd.to_numeric(v["position"], errors="coerce")
    v = v.sort_values(["_key", "_date", "_pos"]).drop_duplicates(["_key", "_date", "_pos"], keep="last")
    v["_occ"] = v.groupby(["_key", "_date"]).cumcount()
    dates_by_key = v.groupby("_key")["_date"].apply(lambda d: sorted(set(x for x in d if x is not None)))
    c = clips.copy()
    c["_key"] = norm(c["synergy_string"]) + "|" + norm(c["player"])
    c["_ord"] = pd.to_numeric(c.get("clip_number"), errors="coerce")

    def _near(row):
        cands = dates_by_key.get(row["_key"], [])
        gd = row["game_date"]
        if gd is None or pd.isna(gd):
            return None
        gd = pd.Timestamp(gd).date()
        best = min(cands, key=lambda d: abs((d - gd).days), default=None)
        return best if best is not None and abs((best - gd).days) <= 1 else None
    c["_vdate"] = c.apply(_near, axis=1)
    c = c.sort_values(["_key", "_vdate", "_ord"])
    c["_occ"] = c.groupby(["_key", "_vdate"], dropna=False).cumcount()
    m = c.reset_index().merge(v[["_key", "_date", "_occ"] + _PL_FRAME_COLS],
                              left_on=["_key", "_vdate", "_occ"], right_on=["_key", "_date", "_occ"],
                              how="left", suffixes=("_drop", ""))
    m = m.set_index("index")
    for col in _PL_FRAME_COLS:
        clips[col] = m[col].reindex(clips.index)
    return clips


# ---- One table of every clip -------------------------------------------------------------------------
PLAY_CALL_COLS = [
    "side", "scouted_opponent", "offense_team", "defense_team", "opponent", "game_date", "game_code", "period",
    "time_remaining_seconds", "player", "result", "points", "points_source", "matched_event", "matched_by",
    "play_title", "play_call", "play_series", "play_situation", "play_formation", "play_set", "play_actions",
    "primary_action", "play_location", "finish_spot", "featured_player", "decode_quality", "decode_note",
    "synergy_play_type", "synergy_string", "on_court_lineup", "personnel_grouping_type", "game_situation",
    "shot_clock_used", "shot_clock_max", "shot_clock_situation",
    # NEW: the defense this offense faced on the clip, from the coaches' updated Title tagging (see
    # decode_defense_tag). "defense_team" above is WHICH team was on defense; these are WHAT they played.
    "defense_type", "defense_press", "defense_press_formation", "defense_coverage",
    # Offense vs Defense possession, and the unambiguous split of the four fields above (see
    # _pl_possession_side). Prefer defense_faced / defense_played over the raw defense_type downstream:
    # the raw field means opposite things on offensive and defensive possessions.
    "possession_side", "defense_faced", "defense_played", "coverage_faced", "coverage_played",
    "press_faced", "press_played", "press_formation_faced", "press_formation_played",
    # NEW (structured tags): which format the Title was read with, the ordered offensive details, and each
    # defensive coverage paired to the screen it answered ("Down Screen (#5): Top Lock | Ball Screen (#12): Drop").
    "tag_format", "play_details", "defense_formation", "defense_details", "coverage_detail",
    # NEW: where play_situation came from (Tag / Play-by-play (timeout) / Synergy / Default) and the coverage
    # detail with defender names filled in from the jersey numbers.
    "situation_source", "coverage_defenders",
    # NEW: the matched play-by-play event's event_order (links a clip to its play-by-play row)
    "pbp_event_order",
    # NEW: where this clip's captured frames are (frame-capture cell) and its place in the export -- the tag
    # model cell after this one adds its predictions (pred_*) and the Suggested Title.
    "frame_files", "clip_number",
    # NEW: both teams' five on the floor, by who had the ball (from the play-by-play lineups).
    "offense_lineup", "defense_lineup",
    # NEW: this clip's dense tracking frames (frame-capture cell), read by the player-tracking cell, and each
    # frame's time in the full-game video (links possessions to each other).
    "track_files", "track_times", "video_start_s",
]
_pl_frames = []
for _f in (_pl_uww, _pl_opp, _pl_other):
    if _f is None or _f.empty:
        continue
    _f = _pl_attach_frames(_f)
    _f["scouted_opponent"] = upcoming_opponent_short
    _f["matched_event"] = _f["event_index"].notna()
    # Bucketed for the "Shot clock tendencies" breakdown. Boundaries are seconds USED (not remaining),
    # scaled to the standard 30-second clock -- an offensive-rebound putback (20-second max) can only ever
    # land in Early or Organized, which is correct: it genuinely can't have used more than 20 seconds.
    _sc_used = pd.to_numeric(_f.get("shot_clock_used"), errors="coerce")
    _f["shot_clock_situation"] = pd.cut(
        _sc_used, bins=[-0.01, 9, 19, 100],
        labels=["Early clock (0-9 sec used)", "Organized offense (10-19 sec used)", "Late clock (20+ sec used)"],
    ).astype(object).where(_sc_used.notna(), None)
    _pl_frames.append(_f.reindex(columns=PLAY_CALL_COLS))
play_calls = pd.concat(_pl_frames, ignore_index=True) if _pl_frames else pd.DataFrame(columns=PLAY_CALL_COLS)
# Other teams' games are kept apart: the scouting tables, brief and app only ever see UWW and upcoming-
# opponent clips (play_calls), exactly as before. The tag model trains on both.
if isinstance(globals().get("clip_frames"), pd.DataFrame) and not clip_frames.empty:
    print(f"  Frames matched to {int(play_calls['frame_files'].notna().sum())} of {len(play_calls)} clip(s) "
          f"({len(clip_frames)} captured).")
    # CONFIRMED CHANGE (coach: "frames for three games but only one gets a Play review"). Frames only become play
    # calls (and then tracking and reviews) when the game's clips are in the tagged export (uww_plays.csv) -- say, page
    # by page, what was captured and what matched, and which tagged games have no frames yet.
    _used_ff = set(play_calls["frame_files"].dropna().astype(str))
    for (_lab, _url), _cfp in clip_frames.groupby([clip_frames.get("source_label", pd.Series("", index=clip_frames.index)),
                                                   clip_frames.get("source_url", pd.Series("", index=clip_frames.index))],
                                                  dropna=False):
        _n_m = int(_cfp["frame_files"].dropna().astype(str).isin(_used_ff).sum())
        _note = ("" if _n_m else " -- NONE match a tagged clip: this game isn't in uww_plays.csv (export its clips from "
                                 "Synergy into it to track and review them)")
        print(f"    captured page {str(_lab)[:45]!r}: {len(_cfp)} clip(s), {_n_m} matched to tagged clips{_note}")
    for (_gd, _gc), _g in play_calls.groupby(["game_date", "game_code"], dropna=False):
        if _g["frame_files"].isna().all():
            print(f"    tagged game {_gd} {_gc}: {len(_g)} clip(s), NO frames -- capture it (Frame capture, "
                  f"VISION_ONLY_GAME = that game)")


class FramesNotReady(Exception):
    """Raised to STOP the notebook when captured frames and the tagged plays (uww_plays.csv) don't line up."""


# CONFIRMED CHANGE (requested: stop the notebook when (1) a game has frames captured but isn't in uww_plays.csv, or
# (2) plays in uww_plays.csv don't have frames captured yet). A small allowance per game for clips the capture
# occasionally misses; FRAMES_STOP_IGNORE_GAMES for games you've decided not to capture / tag; a test capture
# (VISION_TEST_CLIPS) only gets a note. Raised at the top level (no try/except around it), so it halts "Run All".
if isinstance(globals().get("clip_frames"), pd.DataFrame) and not clip_frames.empty and globals().get("FRAMES_STOP_FOR_GAPS", True):
    _ign = [str(x).lower() for x in globals().get("FRAMES_STOP_IGNORE_GAMES", [])]
    _ignored = lambda *labels: any(i and any(i in str(l).lower() for l in labels) for i in _ign)
    _allow = int(globals().get("FRAMES_MISSING_PLAYS_ALLOWED", 2))
    _gaps_capt, _gaps_tag, _gaps_part = [], [], []
    _used_ff = set(play_calls["frame_files"].dropna().astype(str))
    for (_lab, _url), _cfp in clip_frames.groupby([clip_frames.get("source_label", pd.Series("", index=clip_frames.index)),
                                                   clip_frames.get("source_url", pd.Series("", index=clip_frames.index))],
                                                  dropna=False):
        if not _cfp["frame_files"].dropna().astype(str).isin(_used_ff).any() and not _ignored(_lab, _url):
            _gaps_capt.append(f"    - {_lab}: {len(_cfp)} clip(s) captured, none in uww_plays.csv")
    for (_gd, _gc), _g in play_calls.groupby(["game_date", "game_code"], dropna=False):
        if _ignored(f"{_gd} {_gc}", _gc, _gd):
            continue
        _miss = _g[_g["frame_files"].isna()]
        if len(_miss) == len(_g):
            _gaps_tag.append(f"    - {_gd} {_gc}: {len(_g)} tagged play(s), NO frames")
        elif len(_miss) > _allow:
            _ex = "; ".join(f"#{int(r['clip_number']) if pd.notna(r.get('clip_number')) else '?'} "
                            f"{str(r.get('synergy_string') or '')[:45]}" for _, r in _miss.head(5).iterrows())
            _gaps_part.append(f"    - {_gd} {_gc}: {len(_miss)} of {len(_g)} tagged plays have no frames (e.g. {_ex})")
    if _gaps_capt or _gaps_tag or _gaps_part:
        _test = bool(globals().get("VISION_TEST_CLIPS"))
        print("  " + "=" * 100)
        print(("  NOTE (test capture -- not stopping): " if _test else "  STOPPED: ")
              + "the captured frames and uww_plays.csv don't line up yet.")
        if _gaps_capt:
            print("  Games with frames captured that are NOT in uww_plays.csv -- export their tagged clips from Synergy into "
                  "uww_plays.csv:")
            print("\n".join(_gaps_capt))
        if _gaps_tag:
            print("  Tagged games with NO frames -- run Frame capture for each (VISION_ONLY_GAME = that game):")
            print("\n".join(_gaps_tag))
        if _gaps_part:
            print(f"  Tagged games missing frames for more than {_allow} play(s) -- rerun Frame capture for that game "
                  "(only the missing clips are captured):")
            print("\n".join(_gaps_part))
        print("  Then rerun from the Frame capture cell (or this cell, if only uww_plays.csv changed).")
        print("  To go on without a game, add it to FRAMES_STOP_IGNORE_GAMES (e.g. \"WEC@WSP\"); to turn this check off, "
              "FRAMES_STOP_FOR_GAPS = False.")
        print("  " + "=" * 100, flush=True)
        if not _test:
            raise FramesNotReady("captured frames and uww_plays.csv don't line up -- see the list printed above")

play_calls_other = play_calls[play_calls["side"] == "Other"].reset_index(drop=True)
play_calls = play_calls[play_calls["side"] != "Other"].reset_index(drop=True)

# ---- Summaries: one row per (side, level, name) --------------------------------------------------------
# Built here so the brief and the app read the same numbers. A clip flagged Rewatch/TBD or with no call is
# counted in the totals but never ranked as a set.
_PL_LEVELS = [("play_call", "Play call"), ("play_series", "Series"), ("primary_action", "Primary action"),
              ("play_situation", "Situation"), ("play_location", "Location"), ("synergy_play_type", "Finish type"),
              # Which 5-man unit was on the floor, from the play-by-play's own lineup reconstruction (see
              # "On-court 5-man lineups" / the upcoming-opponent lineup cell) -- not decoded from the clip,
              # pulled from the matched pbp event, so this level only has rows for MATCHED clips.
              ("on_court_lineup", "Personnel grouping"),
              # Grouped by personnel TYPE (two bigs / base five / small-ball) rather than the literal five
              # names -- see _pg_grouping_type above. This is what Personnel Grouping Tendencies reads.
              ("personnel_grouping_type", "Personnel grouping type"),
              # Leading/trailing by 10+, or clutch (same clutch definition as the "Clutch-time event log"
              # cell elsewhere in this notebook: last 5 min of the 2nd half or OT, margin <= 8) -- only
              # populated for matched clips, and only for one of these three situations; a comfortable
              # middle possession gets no game_situation value and isn't part of this breakdown.
              ("game_situation", "Game situation"),
              # Estimated shot-clock bucket (see estimate_shot_clock above) -- also only populated for
              # matched clips, since the estimate needs an actual pbp moment to read the game clock from.
              ("shot_clock_situation", "Shot clock"),
              # NEW: the defense faced, decoded straight from the Title (see decode_defense_tag) -- unlike
              # the levels above this doesn't need a matched pbp event, so a clip tagged only "M2M" with no
              # named play still counts here even though it has no "Play call" row. Fills the real data
              # behind what used to be the DEFENSE TYPE BY SITUATION / BALL SCREEN COVERAGE sample tables.
              # Faced vs played, kept separate (see _pl_possession_side) -- "Defense faced" is what this
              # team's OFFENSE saw, "Defense played" is what its own defense was in. The raw defense_type
              # level is deliberately NOT summarized any more: on a mixed offense/defense file it would
              # average the two together into a number that means nothing.
              ("defense_faced", "Defense faced"), ("coverage_faced", "Ball screen coverage faced"),
              ("defense_played", "Defense played"), ("coverage_played", "Ball screen coverage played")]


def _pl_summarize(df, side):
    rows = []
    if df.empty:
        return rows
    df = df.copy()
    df["_pts"] = pd.to_numeric(df["points"], errors="coerce")
    res = df["result"].astype(str).str.lower()
    df["_fga"] = res.str.startswith(("make", "miss")) & res.str.contains("2|3", regex=True)
    df["_fgm"] = res.str.startswith("make") & res.str.contains("2|3", regex=True)
    df["_3pa"] = res.str.contains("3 pts")
    df["_3pm"] = res.str.startswith("make 3")
    df["_to"] = res.str.contains("turnover|violation|kicked", regex=True)
    df["_fd"] = res.str.contains("foul")
    df = df[df["decode_quality"] != "Needs review"]
    total_known = df["_pts"].notna().sum()
    team_ppp = (df["_pts"].sum() / total_known) if total_known else None
    for col, level in _PL_LEVELS:
        g = df[df[col].notna() & (df[col].astype(str).str.strip() != "")]
        for name, grp in g.groupby(col):
            known = grp["_pts"].notna().sum()
            ppp = grp["_pts"].sum() / known if known else None
            fga = int(grp["_fga"].sum())
            top = grp["player"].value_counts()
            rows.append({
                "side": side, "scouted_opponent": upcoming_opponent_short, "level": level, "name": name,
                "uses": len(grp), "games": grp["game_date"].nunique(), "poss_with_points": int(known),
                "points": float(grp["_pts"].sum()), "ppp": round(ppp, 2) if ppp is not None else None,
                "team_ppp": round(team_ppp, 2) if team_ppp is not None else None,
                "fgm": int(grp["_fgm"].sum()), "fga": fga,
                "fg_pct": round(100 * grp["_fgm"].sum() / fga, 1) if fga else None,
                "fg3m": int(grp["_3pm"].sum()), "fg3a": int(grp["_3pa"].sum()),
                "turnovers": int(grp["_to"].sum()), "fouls_drawn": int(grp["_fd"].sum()),
                "top_player": top.index[0] if len(top) else None,
                "top_player_uses": int(top.iloc[0]) if len(top) else 0,
                # Which series this set belongs to (mode) -- lets the brief nest sets under their series
                # without re-deriving the mapping from the clips.
                "series": (grp["play_series"].dropna().value_counts().index[0]
                           if col != "play_series" and grp["play_series"].notna().any() else
                           (name if col == "play_series" else None)),
                "top_action": (grp["primary_action"].dropna().value_counts().index[0]
                               if col != "primary_action" and grp["primary_action"].notna().any() else None),
                "top_location": (grp["play_location"].dropna().value_counts().index[0]
                                 if col != "play_location" and grp["play_location"].notna().any() else None),
                # How many times that spot came up -- the brief shows "Right Side (x4)" rather than implying
                # every use of the set started there.
                "top_location_uses": (int(grp["play_location"].dropna().value_counts().iloc[0])
                                      if col != "play_location" and grp["play_location"].notna().any() else 0),
                "situation": (grp["play_situation"].value_counts().index[0] if col != "play_situation" else name),
                # Same mode-attachment pattern as "situation" above, for the three other splits (requested):
                # lets a "Play call" or "Series" row also be grouped under whichever personnel/shot-clock/
                # game-situation bucket it most often ran in, so those splits can nest sets the same way
                # Half court / BLOB / SLOB / ATO already do, instead of a flat one-row-per-bucket summary.
                "personnel_grouping_mode": (
                    grp["personnel_grouping_type"].dropna().value_counts().index[0]
                    if col != "personnel_grouping_type" and "personnel_grouping_type" in grp.columns
                    and grp["personnel_grouping_type"].notna().any()
                    else (name if col == "personnel_grouping_type" else None)),
                "shot_clock_mode": (
                    grp["shot_clock_situation"].dropna().value_counts().index[0]
                    if col != "shot_clock_situation" and "shot_clock_situation" in grp.columns
                    and grp["shot_clock_situation"].notna().any()
                    else (name if col == "shot_clock_situation" else None)),
                "game_situation_mode": (
                    grp["game_situation"].dropna().value_counts().index[0]
                    if col != "game_situation" and "game_situation" in grp.columns
                    and grp["game_situation"].notna().any()
                    else (name if col == "game_situation" else None)),
                # Same pattern once more, for the defense the offense faced (requested) -- lets "Best against
                # each defense" on HOW WE RUN OFFENSE use the exact same tier-h + series/set pivot as every
                # other split on that card, instead of a bespoke summary table.
                # defense_FACED, not the raw ambiguous defense_type -- this rides on "Best against each
                # defense" in HOW WE RUN OFFENSE, which is about what our offense saw.
                "defense_type_mode": (
                    grp["defense_faced"].dropna().value_counts().index[0]
                    if col != "defense_faced" and "defense_faced" in grp.columns
                    and grp["defense_faced"].notna().any()
                    else (name if col == "defense_faced" else None)),
                "example_titles": " | ".join(grp["play_title"].astype(str).value_counts().index[:3]),
                "game_codes": " ".join(sorted(grp["game_code"].dropna().astype(str).unique())),
            })
    return rows


_pl_sum_rows = []
if not play_calls.empty:
    # Summarized SEPARATELY for offensive and defensive possessions, and every row is stamped with which
    # it came from.
    #
    # CONFIRMED BUG (fixed here): once defensive possessions started appearing in uww_plays.csv,
    # side == "UWW" stopped meaning "our offense" -- it means "a clip from our file", which now includes
    # possessions where the opponent had the ball. Summarizing them together put opposing players in our
    # own offensive tables: a SLOB credited to CJ Brown, a Ripon player, showed up under our sets. The
    # play_call / series levels are only meaningful for the side that had the ball, so they are built per
    # possession_side, and consumers filter on it.
    def _pl_sum_side(df, side_label):
        rows = []
        if df.empty:
            return rows
        _ps = df.get("possession_side")
        for _poss in ("Offense", "Defense"):
            _part = df[_ps.astype(str) == _poss] if _ps is not None else (df if _poss == "Offense" else df.iloc[0:0])
            if _part.empty:
                continue
            for _r in _pl_summarize(_part, side_label):
                _r["possession_side"] = _poss
                rows.append(_r)
        return rows

    _pl_sum_rows += _pl_sum_side(play_calls[play_calls["side"] == "UWW"], "UWW")
    # For the opponent, an OFFENSIVE possession is one where they had the ball; their defensive clips keep
    # their own team label, so filter on possession_side rather than on offense_team alone.
    _opp_clips = play_calls[play_calls["side"] == "Opponent"]
    if "possession_side" in _opp_clips.columns:
        _opp_clips = _opp_clips[((_opp_clips["possession_side"].astype(str) == "Offense")
                                 & (_opp_clips["offense_team"] == upcoming_opponent_short))
                                | (_opp_clips["possession_side"].astype(str) == "Defense")]
    else:
        _opp_clips = _opp_clips[_opp_clips["offense_team"] == upcoming_opponent_short]
    _pl_sum_rows += _pl_sum_side(_opp_clips, "Opponent")
play_call_summary = pd.DataFrame(_pl_sum_rows)
if not play_call_summary.empty and "possession_side" in play_call_summary.columns:
    print(f"  play_call_summary: {int((play_call_summary['possession_side'] == 'Offense').sum())} offensive "
          f"row(s), {int((play_call_summary['possession_side'] == 'Defense').sum())} defensive.")

# ---- Screen coverage: how each defense guards each screen, and who --------------------------------------
# CONFIRMED CHANGE (requested): a scouting-report section built from the structured tags' defensive details.
# One row per (clip, coverage) pair in uww_screen_coverage.csv, then uww_screen_coverage_summary.csv with two
# levels the brief and the app both render (the app only renders -- nothing is computed there):
#   "Screen x coverage"            share of each coverage within each screen type ("Down Screen: Top Lock 60%")
#   "Defender x screen x coverage" the same, per defender jersey/name
# perspective says WHOSE defense it is, so the four combinations can never be mixed up:
#   Opponent defense           upcoming opponent defending (opponent_plays.csv, their defensive possessions)
#   Defenses opponent faced    whoever the upcoming opponent played, defending THEM
#   UWW defense                our defense (uww_plays.csv, our defensive possessions)
#   Defenses UWW faced         opponents defending us
# PPP on a coverage row is the points on the POSSESSIONS where that coverage was used -- it's what happened
# after, not proof the coverage caused it. Every row carries its count; thin rows are flagged, never hidden.
_SCV_PERSPECTIVE = {("Opponent", "Defense"): "Opponent defense", ("Opponent", "Offense"): "Defenses opponent faced",
                    ("UWW", "Defense"): "UWW defense", ("UWW", "Offense"): "Defenses UWW faced"}
_SCV_PIECE = re.compile(r"^\s*(?P<screen>[^:]+?)\s*:\s*(?P<cov>.+?)\s*"
                        r"(?:\(def #(?P<j>\d{1,2})(?:\s+(?P<name>[^)]+))?\))?\s*$")


def _scv_pairs(clips):
    rows = []
    if clips.empty or "coverage_detail" not in clips.columns:
        return pd.DataFrame(columns=SCREEN_COVERAGE_COLS)
    for _, c in clips.iterrows():
        src = c.get("coverage_defenders") if isinstance(c.get("coverage_defenders"), str) else c.get("coverage_detail")
        if not isinstance(src, str) or not src.strip():
            continue
        for piece in src.split(" | "):
            m = _SCV_PIECE.match(piece)
            if not m:
                continue
            screen = m.group("screen").strip()
            rows.append({
                **{k: c.get(k) for k in ("side", "scouted_opponent", "possession_side", "offense_team", "defense_team",
                                         "game_date", "game_code", "period", "player", "play_call", "play_title",
                                         "result", "points", "decode_quality")},
                "perspective": _SCV_PERSPECTIVE.get((c.get("side"), c.get("possession_side")), "Unknown"),
                "screen_type": screen,
                "screen_family": "Ball screen" if screen in _PT_BALL_SCREENS else "Off-ball screen",
                "coverage": m.group("cov").strip(),
                "defender_jersey": m.group("j"),
                "defender_name": (m.group("name") or "").strip() or None,
            })
    return pd.DataFrame(rows, columns=SCREEN_COVERAGE_COLS)


def _scv_summarize(pairs):
    out = []
    if pairs.empty:
        return pd.DataFrame()
    p = pairs[pairs["decode_quality"] != "Needs review"].copy()
    p["_pts"] = pd.to_numeric(p["points"], errors="coerce")
    res = p["result"].astype(str).str.lower()
    p["_fga"] = res.str.startswith(("make", "miss")) & res.str.contains("2|3", regex=True)
    p["_fgm"] = res.str.startswith("make") & res.str.contains("2|3", regex=True)
    p["_to"] = res.str.contains("turnover|violation|kicked", regex=True)
    p["defender"] = p.apply(lambda r: (f"#{r['defender_jersey']} {r['defender_name']}" if r["defender_name"]
                                       else f"#{r['defender_jersey']}") if r["defender_jersey"] else "(no jersey)",
                            axis=1)

    def _stats(g):
        known = int(g["_pts"].notna().sum())
        fga = int(g["_fga"].sum())
        return {"uses": len(g), "games": g["game_date"].nunique(), "poss_with_points": known,
                "ppp": round(g["_pts"].sum() / known, 2) if known else None,
                "fg_pct": round(100 * g["_fgm"].sum() / fga, 1) if fga else None, "fga": fga,
                "turnovers": int(g["_to"].sum()),
                "example_titles": " | ".join(g["play_title"].astype(str).value_counts().index[:2])}

    base = ["side", "scouted_opponent", "perspective", "screen_family", "screen_type"]
    for keys, g in p.groupby(base, dropna=False):
        total = len(g)
        for cov, gc in g.groupby("coverage"):
            top = gc["defender"].value_counts()
            out.append({**dict(zip(base, keys)), "level": "Screen x coverage", "defender": None, "coverage": cov,
                        "screens_of_type": total, "share_pct": round(100 * len(gc) / total),
                        "thin_sample": total < SCREEN_COVERAGE_RULES["thin_screens"],
                        "top_defender": top.index[0] if len(top) else None, **_stats(gc)})
    for keys, g in p.groupby(base + ["defender"], dropna=False):
        total = len(g)
        for cov, gc in g.groupby("coverage"):
            out.append({**dict(zip(base + ["defender"], keys)), "level": "Defender x screen x coverage",
                        "coverage": cov, "screens_of_type": total, "share_pct": round(100 * len(gc) / total),
                        "thin_sample": total < SCREEN_COVERAGE_RULES["thin_screens"], "top_defender": None,
                        **_stats(gc)})
    return pd.DataFrame(out).sort_values(["perspective", "level", "screen_family", "screen_type", "uses"],
                                         ascending=[True, True, True, True, False]).reset_index(drop=True)


screen_coverage = _scv_pairs(play_calls)
screen_coverage_summary = _scv_summarize(screen_coverage)
if screen_coverage.empty:
    print("  screen_coverage: no clips with defensive coverage details yet (needs the structured tags, "
          "e.g. \"...: m2m (5tl,12drop)\").")
else:
    print(f"  screen_coverage: {len(screen_coverage)} tagged screen coverage(s) -- "
          + ", ".join(f"{k}: {v}" for k, v in screen_coverage["perspective"].value_counts().items()))


# One lineup -> grouping map, exported so the game-plan cell aggregates MINUTES on exactly this rule rather
# than classifying lineups a second time (which is how minutes and tagged clips once landed on different
# groupings). Every five-man unit either side has on film, whether or not any clip matched it.
_lg_rows = []
for _lg_df, _lg_side, _lg_team, _lg_bigs, _lg_col in (
        (pbp_events, "UWW", _PL_UWW, _pg_uww_bigs, "uww_lineup"),
        (globals().get("upcoming_lineup_season"), "Opponent", upcoming_opponent_short, _pg_opp_bigs, "lineup")):
    if _lg_df is None or getattr(_lg_df, "empty", True) or _lg_col not in getattr(_lg_df, "columns", []):
        continue
    for _lu in _lg_df[_lg_col].dropna().astype(str).unique():
        _lg_rows.append({"side": _lg_side, "team": _lg_team, "lineup": _lu,
                         "grouping": _pg_grouping_label(_lu, _lg_bigs),
                         "shape": _pg_shape_label(_lu), "scouted_opponent": upcoming_opponent_short})
lineup_grouping = pd.DataFrame(_lg_rows, columns=["side", "team", "lineup", "grouping", "shape",
                                                  "scouted_opponent"])

# ---- Feed UWW's clips into coach_notes, which the app's existing play-call analytics already read -------
if _pl_uww is not None and not _pl_uww.empty:
    _pl_cn = _pl_uww[_pl_uww["play_call"].notna()].copy()
    _pl_cn["coach_note"] = None
    _pl_cn["clip_side"] = "Offense"
    _pl_cn["team"] = _PL_UWW
    _cn_extra = ["game_date", "points", "play_series", "play_title", "play_actions", "play_location", "play_situation"]
    for _c in _cn_extra:
        if _c not in coach_notes.columns:
            coach_notes[_c] = None
    _pl_cn = _pl_cn[[c for c in coach_notes.columns if c in _pl_cn.columns]]
    # The old season play log is retired, so any previous play_call-only rows are superseded by this file.
    _old_log_rows = coach_notes["play_call"].notna() & coach_notes["coach_note"].isna()
    coach_notes = pd.concat([coach_notes[~_old_log_rows], _pl_cn], ignore_index=True)

# ---- Report ---------------------------------------------------------------------------------------------
for _label, _f in (("UWW games", _pl_uww), ("upcoming-opponent games", _pl_opp)):
    if _f is None or _f.empty:
        continue
    _q = _f["decode_quality"].value_counts().to_dict()
    _m = int(_f["event_index"].notna().sum())
    print(f"{_label}: {len(_f)} clip(s) across {_f['game_date'].nunique()} game(s); decoded {_q}; "
          f"matched to play-by-play {_m}/{len(_f)} "
          f"({_f['matched_by'].value_counts().to_dict()}).")
    _unm = _f[_f["event_index"].isna()]
    if not _unm.empty:
        print("  First unmatched clips (date, period, clock, player, result):")
        print(_unm[["game_date", "period", "Clock", "player", "result"]].head(6).to_string(index=False))
    _top = _f[_f["decode_quality"] != "Needs review"]["play_call"].value_counts().head(6)
    print(f"  Most-called: {_top.to_dict()}")
    _sc_cov = _f["shot_clock_used"].notna().sum()
    if _sc_cov:
        print(f"  Shot clock estimated for {_sc_cov}/{len(_f)} clip(s) (needs a matched pbp event).")
    _def_cov = _f["defense_type"].notna().sum()
    if _def_cov:
        print(f"  Defense tagged on {_def_cov}/{len(_f)} clip(s): "
              f"{_f['defense_type'].value_counts().to_dict()}; "
              f"press on {int(_f['defense_press'].sum())}, coverage called on "
              f"{int((_f['defense_coverage'].astype(str).str.len() > 0).sum())}.")
        # WHICH SIDE those tags landed on decides what every defense table downstream can say. A file
        # where every tag sits on an offensive possession can describe what this team FACED but can say
        # nothing about the defense they PLAY -- which is the difference between opp_defense filling in
        # and staying sample.
        if "possession_side" in _f.columns:
            _off_n = int((_f["possession_side"] == "Offense").sum())
            _def_n = int((_f["possession_side"] == "Defense").sum())
            _faced = int(_f["defense_faced"].notna().sum()) if "defense_faced" in _f.columns else 0
            _played = int(_f["defense_played"].notna().sum()) if "defense_played" in _f.columns else 0
            print(f"    Possessions: {_off_n} offensive, {_def_n} defensive "
                  f"-> {_faced} defense-faced tag(s), {_played} defense-played tag(s).")
            if _played == 0 and _faced:
                print("    NOTE: no defensive possessions in this file, so nothing here can describe the "
                      "defense this team PLAYS -- only what its offense faced. If you tagged their "
                      "defense, check whether the Team column names the team being scouted rather than "
                      "the team with the ball.")
if _pl_problems:
    print("Play-call problems:")
    for _p in _pl_problems:
        print(f"  - {_p}")



# --- Self-check: do the clips' video positions agree with the game clock? --------------------------------------------
# CONFIRMED CHANGE (after the capture bug: clip 1's frames showed clip 2). Within a half, a clip that starts LATER in the
# full-game video must have the same or LESS time on the game clock. A clip that breaks that order was captured at the
# wrong spot of the video; it is listed here so it can't go unnoticed again. (It catches clips grabbed at a badly wrong
# spot; it could NOT catch the original bug, which shifted every clip by one play and so kept them in order.)
def _clip_order_check(pc):
    need = {"video_start_s", "time_remaining_seconds", "period", "game_date"}
    if pc.empty or not need <= set(pc.columns):
        return pd.DataFrame()
    d = pc.dropna(subset=["video_start_s", "time_remaining_seconds"]).copy()
    d["video_start_s"] = pd.to_numeric(d["video_start_s"], errors="coerce")
    d = d.dropna(subset=["video_start_s"])
    bad = []
    # CONFIRMED BUG (fixed): grouped by DATE and half only -- two games on the same day (Oshkosh @ Whitewater and Eau
    # Claire @ Stevens Point, both Jan 3) were put on one video timeline, so 25 clips looked out of order. By game now.
    gkey = [c for c in ("game_date", "game_code") if c in d.columns] + ["period"]
    for _gk, g in d.groupby(gkey, dropna=False):
        gd, per = _gk[0], _gk[-1]
        g = g.sort_values("video_start_s")
        clock = g["time_remaining_seconds"].astype(float).values
        for n in range(1, len(g)):
            # allow a few seconds: a clip starts before its event, and events can share a clock time
            if clock[n] > clock[:n].min() + 8:
                r = g.iloc[n]
                bad.append({"game_date": gd, "game_code": r.get("game_code"), "period": per, "clip_number": r.get("clip_number"),
                            "video_start_s": round(float(r["video_start_s"]), 1),
                            "clock": r["time_remaining_seconds"], "description": str(r.get("synergy_string"))[:70]})
    return pd.DataFrame(bad)


_order_bad = _clip_order_check(play_calls[play_calls["track_files"].notna()] if "track_files" in play_calls.columns else play_calls)
if "video_start_s" in play_calls.columns and play_calls["video_start_s"].notna().any():
    if _order_bad.empty:
        print("Clip order check: every tracked clip's spot in the game video agrees with the game clock.")
    else:
        print("  " + "!" * 100)
        print(f"  CLIP ORDER CHECK: {len(_order_bad)} clip(s) sit at a spot in the game video that doesn't match their game clock "
              f"(captured at the wrong place?):")
        print(_order_bad.head(15).to_string(index=False))
        print("  " + "!" * 100)
