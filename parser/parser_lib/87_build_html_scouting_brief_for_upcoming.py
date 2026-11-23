# 87_build_html_scouting_brief_for_upcoming.py -- code for the notebook section "Build a one-file HTML scouting brief for the upcoming opponent ---------------------------"
# Runs inside the notebook via run_section("87_build_html_scouting_brief_for_upcoming"); its settings are in that notebook cell.

# --- Build a one-file HTML scouting brief for the upcoming opponent ----------------------------------------
# An executive summary the staff can read (or print, or forward) BEFORE they sit down to write their own
# scouting reports -- the handful of things from across this whole notebook that change how you prepare,
# not a dump of every table.
#
# Reads the CSVs the export cell just wrote rather than the in-memory DataFrames above. That is deliberate:
# those CSVs are exactly what the Streamlit app reads, so the brief and the app can never quietly disagree
# about a number -- and a coach who checks a figure in the app against the emailed brief gets the same
# answer. It also means this cell can be re-run on its own without re-running the notebook.
#
# Output is a single self-contained file: no images, no scripts, no external CSS, so it survives being sent
# as an email attachment and prints cleanly.
#
# Every section stands or falls on its own. With before_scout="yes" there is no game plan, no player notes
# and no tag-based comparisons, so those sections drop out and the footer names the tables that were empty
# -- a coach should never have to wonder whether data was missing or the brief was broken.
import html as _sb_html

_SB_OUT_DIR = os.path.join(APP_DATA_DIR, "scouting_briefs")

# ---- THE BOTTOM LINE: when a conditional sentence is printed ------------------------------------------
# Some Bottom Line sentences only appear past a threshold -- below it the difference isn't big enough to
# change how we prepare, and printing it anyway trains the staff to skim the section. These are the ONLY
# place the thresholds live: the rule text in each sentence's note (which the brief links to, and the app
# prints) is generated from them, so changing a number here updates the explanation too.
# Roster layout. "table" = one wide row per player (the original). "stacked" = a header bar per player
# (photo, name, bio) with the full width below for the box-score line, WHERE HE SHOOTS FROM (from the
# play-by-play) and the reads. Stacked replaces the separate SHOT LOCATIONS section, whose zone split is a
# placeholder; with "table" that section stays where it was.

BOTTOM_LINE_RULES = {
    # Tempo: printed when EITHER is true.
    "tempo_pace_gap": 5,          # their possessions per game minus ours, either direction
    "tempo_early_share": 40,      # % of their tagged possessions that shoot inside 10 seconds
    # Four factors: printed when BOTH are true, so it names one clear story rather than a close call.
    "ff_min_weighted": 1.0,       # the top factor's weighted gap, absolute
    "ff_dominance": 2.0,          # ...and at least this many times the second-largest factor's
    # Style matchups (TEAMS LIKE ... panels, no longer their own sections): printed when ALL are true.
    "style_min_games": 3,         # games behind the record
    "style_min_confidence": 0.35, # best match in the panel at least this confident (the app's amber/red cut)
    "style_lopsided": 0.75,       # win share at/above this, or at/below 1 minus this
    # Rebounding thresholds live in REBOUND_RULES (Keys to Victory cell), because the key, this sentence
    # and the roster read must all fire on the same numbers. Read from there, never restated here.
}


_SB_UWW = "UW-Whitewater"

# Settings (notebook cell): STRIKE_LAST_SEASON_SENIORS = "auto" / True / False, STRIKE_SENIORS_KEEP = [names].
# The same code as streamlit_app.py's, so the brief and the app strike exactly the same things.
# ---- Strike through last season's seniors (a scrimmage played between seasons) -------------------------
# CONFIRMED CHANGE (requested): the MSOE scrimmage is played after the 2025-26 season and before 2026-27, but
# every number we have on both teams is 2025-26 -- so anything about a player who was a senior that year is
# about someone who won't be on the floor. Those names (and a sentence / table row / list item that is only
# about them) are drawn struck through. A line that also names a returning player keeps its text and only the
# senior's name is struck. Links, photos and other attributes are never touched.
import html as _sk_html
_SK_SENIOR_CLASSES = {"SR", "GR", "GRAD", "GRADUATE", "SENIOR", "5TH", "5THYR", "FIFTH"}
_SK_SUFFIX = {"JR", "SR", "II", "III", "IV", "V"}


def _sk_real_date(note):
    """The 'real date ...' in a schedule note (a scrimmage parked on a placeholder date), or None."""
    m = re.search(r"real\s+date\s*:?\s*([A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|\d{4}-\d{1,2}-\d{1,2}"
                  r"|\d{1,2}/\d{1,2}/\d{4})", str(note or ""), re.I)
    if not m:
        return None
    d = pd.to_datetime(re.sub(r"(\d)(st|nd|rd|th)", r"\1", m.group(1)), errors="coerce")
    return None if pd.isna(d) else pd.Timestamp(d)


def last_season_record_label(game):
    """CONFIRMED CHANGE (requested: the first game of a new season "really has to be different from any other scouting brief
    ... it should say 'Last Season' on these records"). True when the upcoming game is in the season AFTER the one our records
    are from (an EXTRA_GAMES game with a real date after it) and neither team has played a game of the new season yet
    (new_season_games, the schedule cell's new-season check)."""
    get = (lambda c: game.get(c)) if hasattr(game, "get") else (lambda c: None)
    if str(get("new_season_games") or "").strip() not in ("", "nan", "None"):
        return False
    rd = pd.to_datetime(get("real_date"), errors="coerce") if str(get("real_date") or "").strip() not in ("", "nan", "None") else None
    sm = re.match(r"\s*(\d{4})", str(get("season") or ""))
    return bool(rd is not None and not pd.isna(rd) and sm and rd >= pd.Timestamp(int(sm.group(1)) + 1, 8, 1))


def last_season_text(record, streak):
    """("Last season: 21-8", "Ended last season on a 1-game loss streak")."""
    rec = f"Last season: {record}" if str(record or "").strip() else ""
    stk = str(streak or "").strip()
    return rec, (f"Ended last season on a {stk}" if stk else "")


BRIEF_FIRST_GAMES_MIN = 3        # (requested) a team needs this many games this season before the brief is a regular one


def brief_type_for(game, n_uww, n_opp, setting="auto"):
    """CONFIRMED CHANGE (requested: "there really should be at least 3 different types of scouting briefs: 1) Exhibition /
    Scrimmage games before the season, 2) First games for each team, 3) Regular games that we have season data for").
    -> {"type": "preseason" | "first_games" | "regular", "last_season": the numbers are all last season's, "title", "sub",
    "n_uww", "n_opp"}. n_uww / n_opp = games each team has played this season before this one. A team needs
    BRIEF_FIRST_GAMES_MIN (3) of them for a regular brief. setting = "auto" or one of the three types (BRIEF_TYPE)."""
    get = (lambda c: game.get(c)) if hasattr(game, "get") else (lambda c: None)
    kind = " ".join(str(get(c) or "") for c in ("game_type", "note")).lower()
    exhib = bool(re.search(r"scrimmage|exhibition", kind))
    nxt = last_season_record_label(game)                 # a game in the NEXT season: every number is last season's
    sm = re.match(r"\s*(\d{4})", str(get("season") or ""))
    last = f"{sm.group(1)}-{str(int(sm.group(1)) + 1)[-2:]}" if sm else "last season"
    if nxt:
        n_uww = n_opp = 0
    s = str(setting or "auto").strip().lower().replace("-", "_").replace(" ", "_")
    try:
        _min = int(globals().get("BRIEF_FIRST_GAMES_MIN", 3))
    except Exception:
        _min = 3
    if s in ("preseason", "first_games", "regular"):
        t = s
    elif exhib and (nxt or n_uww == 0):
        t = "preseason"
    elif nxt or min(n_uww, n_opp) < _min:
        t = "first_games"
    else:
        t = "regular"
    if t == "preseason":
        title = "PRESEASON BRIEF \u2014 " + ("SCRIMMAGE" if "scrimmage" in kind else "EXHIBITION" if exhib else "BEFORE THE SEASON")
        sub = (f"Built on last season ({last}): the records, tendencies and player numbers below are last season's and are "
               f"marked that way. Last season's seniors are crossed out.")
    elif t == "first_games" and nxt:
        title = "SEASON OPENER BRIEF \u2014 FIRST GAMES"
        sub = (f"Neither team has played this season yet, so everything below is last season ({last}) and marked that way "
               f"(last season's seniors are crossed out). It becomes a regular brief once both teams "
               f"have played {_min} games.")
    elif t == "first_games":
        title = "FIRST GAMES BRIEF \u2014 SMALL SAMPLES"
        sub = (f"We've played {n_uww} game(s) this season and they've played {n_opp}: this season's numbers are small "
               f"samples, shown next to last season's. It becomes a regular brief once both teams have played {_min} games.")
    else:
        title, sub = "", ""
    return {"type": t, "last_season": bool(nxt),
            "season": last, "title": title, "sub": sub, "n_uww": n_uww, "n_opp": n_opp}


def roster_changes(rosters, team):
    """(back, gone, new) for one team from the roster table: back = [(name, this season's class)], gone = last season's
    seniors / players not on this season's roster, new = [(name, class)]. Only meaningful once the roster has been updated
    to the new season (class_year_prev, the roster cell); before that, gone = last season's seniors."""
    if rosters is None or getattr(rosters, "empty", True) or "team" not in rosters.columns:
        return [], [], []
    t = str(team or "").strip().lower()
    r = rosters[rosters["team"].astype(str).str.strip().str.lower() == t]
    if r.empty:
        r = rosters[rosters["team"].astype(str).str.lower().str.contains(re.escape(t), na=False)]
    if r.empty:
        return [], [], []
    srs = {"SR", "GR", "GRAD", "GRADUATE", "SENIOR", "5TH", "5THYR", "FIFTH"}
    clean = lambda v: re.sub(r"[^A-Z0-9]", "", str(v or "").upper())
    if "class_year_prev" in r.columns and r["source"].astype(str).str.contains("new season", na=False).any():
        on_new = r["source"].astype(str).str.contains("new season", na=False)
        prev = r["class_year_prev"]
        back = [(n, c) for n, c, p, o in zip(r["name"], r["class_year"], prev, on_new) if o and pd.notna(p)]
        new = [(n, c) for n, c, p, o in zip(r["name"], r["class_year"], prev, on_new) if o and pd.isna(p)]
        gone = [n for n, o in zip(r["name"], on_new) if not o]
    else:
        gone = [n for n, c in zip(r["name"], r["class_year"]) if clean(c) in srs]
        back = [(n, c) for n, c in zip(r["name"], r["class_year"]) if clean(c) not in srs]
        new = []
    return back, gone, new


def _sc_norm(x):
    return re.sub(r"[^a-z0-9 ]+", " ", str(x or "").lower()).strip()


def _sc_is(team_val, name, is_uww):
    t = _sc_norm(team_val)
    if is_uww:
        return "whitewater" in t
    n = _sc_norm(name)
    return bool(t) and bool(n) and (t == n or t.startswith(n) or n.startswith(t))


def _sc_line(load, team, is_uww):
    """One season's per-game line for a team: (games, {stat: value}) from that season's tables. load(name) -> DataFrame."""
    out = {}
    sched = load("uww_schedule" if is_uww else "uww_opponent_schedules")
    if isinstance(sched, pd.DataFrame) and not sched.empty and "outcome" in sched.columns:
        s = sched
        if is_uww:
            if "team" in s.columns:
                s = s[s["team"].astype(str).str.contains("whitewater", case=False, na=False)]
            if "Upcoming" in s.columns:
                s = s[s["Upcoming"].astype(str).str.strip().str.lower() != "yes"]
        else:
            s = s[s["opponent"].map(lambda v: _sc_is(v, team, False))] if "opponent" in s.columns else s.iloc[0:0]
        s = s[s["outcome"].astype(str).str.upper().isin(["W", "L"])]
        if len(s):
            w = int((s["outcome"].astype(str).str.upper() == "W").sum())
            out["Record"] = f"{w}-{len(s) - w}"
            ts = pd.to_numeric(s.get("team_score"), errors="coerce")
            os_ = pd.to_numeric(s.get("opponent_score"), errors="coerce")
            if ts is not None and ts.notna().any():
                out["PPG"] = ts.mean()
                out["Opp PPG"] = os_.mean()
                out["Margin"] = (ts - os_).mean()
    n_games = int(out.get("Record", "0-0").split("-")[0]) + int(out.get("Record", "0-0").split("-")[1]) if "Record" in out else 0
    box = load("uww_pbp_box_score" if is_uww else "uww_opponent_prior_games_box_score")
    if isinstance(box, pd.DataFrame) and not box.empty and {"team", "game_date"}.issubset(box.columns):
        b = box.copy()
        key = ["opponent", "game_date"] if "opponent" in b.columns else ["game_date"]
        # only the team whose games the table is about (the opponent's own schedule of games -- a team that merely
        # played them shows up in one or two of those games, which is not its season)
        _games_by_team = b.drop_duplicates(key + ["team"])["team"].value_counts()
        _subject = _games_by_team.index[0] if len(_games_by_team) else None
        mine = b[b["team"].map(lambda v: _sc_is(v, team, is_uww))] if _subject is not None \
            and _sc_is(_subject, team, is_uww) else b.iloc[0:0]
        if not mine.empty:
            cols = [c for c in ("PTS", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "REB", "AST", "STL", "TO")
                    if c in b.columns]
            for c in cols:
                b[c] = pd.to_numeric(b[c], errors="coerce")
            mine = b.loc[mine.index]
            g = mine.groupby(key)[cols].sum()
            n_box = len(g)
            if n_box:
                t = g.sum()
                per = lambda c: t[c] / n_box if c in t else None
                pct = lambda m, a: (100.0 * t[m] / t[a]) if m in t and a in t and t[a] else None
                if "PPG" not in out and "PTS" in t:
                    out["PPG"] = per("PTS")
                if {"FGA", "OREB", "TO", "FTA"}.issubset(t.index):
                    out["Pace (poss/g)"] = (t["FGA"] - t["OREB"] + t["TO"] + 0.475 * t["FTA"]) / n_box
                out["FG%"] = pct("FGM", "FGA")
                out["3P%"] = pct("FG3M", "FG3A")
                out["3PA/g"] = per("FG3A")
                out["FT%"] = pct("FTM", "FTA")
                out["FTA/g"] = per("FTA")
                out["REB/g"] = per("REB")
                out["OREB/g"] = per("OREB")
                out["AST/g"] = per("AST")
                out["TO/g"] = per("TO")
                out["STL/g"] = per("STL")
                out["_box_games"] = n_box
                n_games = max(n_games, n_box)
    return n_games, out


def season_compare(load_this, load_last, team, is_uww, last_label="Last season"):
    """CONFIRMED CHANGE (requested: first-games briefs show this season "side by side" with last season). -> DataFrame
    [stat, This season (N g), Last season (2025-26)] for one team, or None when neither season has anything. A team's
    last-season box line is only there when we scouted its games last season; its record and scoring come from the
    schedules either way."""
    n1, a = _sc_line(load_this, team, is_uww) if load_this else (0, {})
    n0, b = _sc_line(load_last, team, is_uww) if load_last else (0, {})
    if not a and not b:
        return None
    order = ["Record", "PPG", "Opp PPG", "Margin", "Pace (poss/g)", "FG%", "3P%", "3PA/g", "FT%", "FTA/g", "REB/g",
             "OREB/g", "AST/g", "TO/g", "STL/g"]
    fmt = lambda k, v: ("--" if v is None or (isinstance(v, float) and pd.isna(v)) else v if isinstance(v, str)
                        else f"{v:+.1f}" if k == "Margin" else f"{v:.1f}")
    rows = [(k, fmt(k, a.get(k)), fmt(k, b.get(k))) for k in order if k in a or k in b]
    c1 = f"This season ({n1} g)"
    c0 = f"{last_label} ({n0} g)" if n0 else last_label
    return pd.DataFrame(rows, columns=["", c1, c0])


def _sk_name_parts(name):
    toks = [t for t in re.sub(r"\s+", " ", str(name or "")).strip().split(" ") if t]
    while len(toks) > 2 and toks[-1].upper().strip(".,") in _SK_SUFFIX:
        toks = toks[:-1]
    return toks


def strike_seniors_plan(game, rosters, uww_team, opp_team, setting="auto", keep=(), today=None):
    """Who to strike for this game, or None.

    setting: "auto" (default) = only when the game is a scrimmage/exhibition whose real date (the schedule
    note's "real date ...", else today) falls after the season the data is from; True = always; False = never.
    Seniors come from the live roster scrape (class SR / GR). A team whose roster scrape is already from a
    different season than the game's is left alone -- its SRs would be THIS year's seniors.
    """
    s = str(setting).strip().lower()
    if s in ("false", "0", "no", "off", "never", "none", ""):
        return None
    get = (lambda c: game.get(c)) if hasattr(game, "get") else (lambda c: None)
    season = str(get("season") or "")
    sm = re.match(r"\s*(\d{4})\s*[-/]\s*(\d{2,4})", season)
    if s not in ("true", "1", "yes", "on", "always"):
        kind = " ".join(str(get(c) or "") for c in ("game_type", "note")).lower()
        # CONFIRMED CHANGE (requested: the Carroll game is the FIRST game of 2026-27, not a scrimmage): any game with a real
        # date (EXTRA_GAMES' "real_date") after the season our data is from strikes last season's seniors too
        _rd = pd.to_datetime(get("real_date"), errors="coerce") if str(get("real_date") or "").strip() not in ("", "nan", "None") else None
        _rd = None if _rd is None or pd.isna(_rd) else pd.Timestamp(_rd)
        if not (re.search(r"scrimmage|exhibition", kind) or _rd is not None) or not sm:
            return None
        # (the new season has started -- UWW or the opponent has played a game in it: not between seasons any more)
        if str(get("new_season_games") or "").strip() not in ("", "nan", "None"):
            return None
        when = _rd or _sk_real_date(get("note")) or (pd.Timestamp(today) if today is not None else pd.Timestamp.now())
        if when < pd.Timestamp(int(sm.group(1)) + 1, 5, 1):
            return None
    if rosters is None or getattr(rosters, "empty", True) or not {"team", "name"} <= set(rosters.columns):
        return None
    ros = rosters.copy()
    ros["team"] = ros["team"].astype(str)
    ros["name"] = ros["name"].astype(str).str.strip()
    ros = ros[ros["name"].str.len() > 0]
    # (last season's class when the roster was updated to the new season -- see the roster cell)
    cls = (ros["class_year_prev"].fillna("")              # (a player new this season wasn't a senior last season)
           if "class_year_prev" in ros.columns else
           ros["class_year"] if "class_year" in ros.columns else pd.Series("", index=ros.index))
    ros["_sr"] = cls.astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True).isin(_SK_SENIOR_CLASSES)
    keep_l = {re.sub(r"\s+", " ", str(k)).strip().lower() for k in (keep or ())}
    want = f"{int(sm.group(1))}-{int(sm.group(1)) + 1}" if sm else None

    def team_rows(t):
        t = str(t or "").strip().lower()
        if not t:
            return ros.iloc[0:0]
        hit = ros[ros["team"].str.strip().str.lower() == t]
        if hit.empty:
            hit = ros[ros["team"].str.lower().str.contains(re.escape(t), na=False)]
        return hit

    teams, in_play = {}, []
    for t in (opp_team, uww_team):
        rows = team_rows(t)
        if rows.empty:
            continue
        if want and "photo_url" in rows.columns:
            seen = set(rows["photo_url"].astype(str).str.extract(r"/(\d{4}-\d{4})/")[0].dropna())
            if seen and want not in seen:
                continue  # this team's roster scrape is already a different season
        in_play.append(rows)
        srs = [n for n in rows.loc[rows["_sr"], "name"] if n.lower() not in keep_l]
        if srs:
            teams[str(rows["team"].iloc[0])] = srs
    if not teams:
        return None
    seniors = [n for v in teams.values() for n in v]
    sen_l = {n.lower() for n in seniors}
    play = pd.concat(in_play)
    others = sorted({n for n in play["name"] if n.lower() not in sen_l})
    sen_last = {_sk_name_parts(n)[-1].lower() for n in seniors if _sk_name_parts(n)}
    look = sorted({n for n in ros["name"] if n.lower() not in sen_l and _sk_name_parts(n)
                   and _sk_name_parts(n)[-1].lower() in sen_last})
    return {"teams": teams, "seniors": seniors, "others": others, "lookalikes": look,
            "season": season}


class _SeniorStrike:
    """Finds struck seniors in text and wraps them. One instance per (seniors, others) set."""

    _SPLIT = re.compile(r"(?<=[.!?;])\s+(?=\S)|\s+\|\s+|\s+·\s+")
    _URL = re.compile(r"(?:https?:|data:|file:|www\.)\S+|\S+/\S+\.(?:jpe?g|png|gif|webp|svg)\b", re.I)
    _MD_PROTECT = re.compile(r"~~.+?~~|`[^`]*`|\]\([^)]*\)|<[^>\n]*>|(?:https?://|www\.)\S+", re.I)
    _MD_LEAD = re.compile(r"^\s*(?:(?:[-*+]|\d+[.)])\s+|#{1,6}\s+|>\s*)*")

    def __init__(self, seniors, others=(), lookalikes=()):
        def full_rx(parts):
            body = r"\s+".join(re.escape(p) for p in parts)
            return rf"(?i:{body})(?:\s+(?i:jr|sr|ii|iii|iv|v)\b\.?(?!\s+[A-Z]))?"

        sen_parts = [p for p in (_sk_name_parts(n) for n in seniors) if len(p) >= 2]
        oth_parts = [p for p in (_sk_name_parts(n) for n in others) if len(p) >= 2]
        look_parts = [p for p in (_sk_name_parts(n) for n in lookalikes) if len(p) >= 2]
        oth_last = {p[-1].lower() for p in oth_parts}
        sen_last = {p[-1].lower() for p in sen_parts}
        # a senior's last name on its own only counts when no returning player in play shares it
        self._last_only = {l for l in sen_last if l not in oth_last and len(l) >= 3}
        self._look_full = {" ".join(p).lower() for p in look_parts + oth_parts}
        alts = []
        for p in sorted(sen_parts, key=lambda p: -len(" ".join(p))):
            alts.append(full_rx(p))
            alts.append(rf"(?i:{re.escape(p[-1])},\s*{re.escape(p[0])})")
            alts.append(rf"{re.escape(p[0][0].upper())}\.\s*(?=[A-Z])(?i:{re.escape(p[-1])})")
        for l in sorted(self._last_only, key=len, reverse=True):
            alts.append(rf"(?=[A-Z])(?i:{re.escape(l)})")
        self._rx = re.compile(r"(?<![\w'\-])(?:" + "|".join(alts) + r")(?![\w\-])") if alts else None
        oalts = [full_rx(p) for p in sorted(oth_parts + look_parts, key=lambda p: -len(" ".join(p)))]
        oalts += [rf"(?=[A-Z])(?i:{re.escape(l)})" for l in sorted(oth_last - sen_last, key=len, reverse=True)
                  if len(l) >= 3]
        self._orx = re.compile(r"(?<![\w'\-])(?:" + "|".join(oalts) + r")(?![\w\-])") if oalts else None
        q = sorted(sen_last, key=len, reverse=True)
        self._quick = re.compile("|".join(re.escape(l) for l in q), re.I) if q else None

    # ---- matching ----
    def hit(self, text):
        return bool(self._rx is not None and isinstance(text, str) and self._quick.search(text))

    def _spans(self, text, protect=None):
        bad = [m.span() for m in protect.finditer(text)] if protect is not None else []
        inside = lambda s, e: any(a < e and s < b for a, b in bad)
        sen = []
        for m in self._rx.finditer(text):
            s, e = m.span()
            if inside(s, e) or text[max(0, s - 2):s] == "~~" or text[max(0, s - 3):s].lower() == "<s>":
                continue
            t = m.group()
            if t.lower() in self._last_only:
                pw = re.search(r"([A-Za-z][\w'\-]*)\s+$", text[:s])
                if pw and f"{pw.group(1)} {t}".lower() in self._look_full:
                    continue  # "Oliver Adams" -- someone else with a struck senior's last name
            sen.append((s, e))
        oth = []
        if self._orx is not None and sen:
            oth = [m.span() for m in self._orx.finditer(text)
                   if not inside(*m.span()) and not any(a < m.end() and m.start() < b for a, b in sen)]
        return sen, oth, bad

    _GAP = re.compile(r"\s*(?:,\s*(?:and\s+|&\s*)?|(?:and|&|/|\+)\s*)", re.I)

    def _grouped(self, text, sen, oth):
        """Lineups / combos: 3+ player names in a row ("A, B, C", "A, B and C", "A / B / C") that include a
        struck senior are ONE struck item -- that group won't be on the floor together. Returns (sen, oth) with
        each such group merged into a single senior span and its returning players taken out of oth."""
        allsp = sorted([(s, e, 1) for s, e in sen] + [(s, e, 0) for s, e in oth])
        groups, cur = [], []
        for sp in allsp:
            if cur and self._GAP.fullmatch(text[cur[-1][1]:sp[0]]):
                cur.append(sp)
            else:
                if cur:
                    groups.append(cur)
                cur = [sp]
        if cur:
            groups.append(cur)
        nsen, noth = [], []
        for g in groups:
            if len(g) >= 3 and any(k for _, _, k in g):
                nsen.append((g[0][0], g[-1][1]))
            else:
                nsen += [(s, e) for s, e, k in g if k]
                noth += [(s, e) for s, e, k in g if not k]
        return nsen, noth

    def _apply(self, text, wrap, protect=None, whole_ok=None, lead=None):
        if not self.hit(text):
            return text
        sen, oth, bad = self._spans(text, protect)
        if not sen:
            return text
        sen, oth = self._grouped(text, sen, oth)
        cuts = [m.span() for m in self._SPLIT.finditer(text)
                if not any(a < m.end() and m.start() < b for a, b in sen + oth + bad)]
        segs, pos = [], 0
        for a, b in cuts:
            segs.append((pos, a))
            pos = b
        segs.append((pos, len(text)))
        out, last = [], 0
        for i, (a, b) in enumerate(segs):
            ss = [(s, e) for s, e in sen if a <= s and e <= b]
            if not ss:
                continue
            seg = text[a:b]
            lo = lead.match(seg).end() if (lead is not None and i == 0) else 0
            lo += len(seg[lo:]) - len(seg[lo:].lstrip())
            core = seg[lo:].rstrip()
            only_seniors = not any(a <= s and e <= b for s, e in oth)
            if only_seniors and core and (whole_ok is None or whole_ok(core)):
                out.append(text[last:a + lo])
                out.append(wrap(core))
                last = a + lo + len(core)
            else:
                for s, e in ss:
                    out.append(text[last:s])
                    out.append(wrap(text[s:e]))
                    last = e
        out.append(text[last:])
        return "".join(out)

    # ---- the three kinds of text ----
    @staticmethod
    def _md_balanced(t):
        t2 = t.replace("**", "")
        return (t.count("**") % 2 == 0 and t2.count("*") % 2 == 0 and t.count("__") % 2 == 0
                and "`" not in t and "$" not in t and t.count("[") == t.count("]")
                and t.count("(") == t.count(")") and not t.startswith("|") and "~~" not in t)

    def md(self, text):
        if not self.hit(text):
            return text
        return "\n".join(self._apply(ln, lambda x: f"~~{x}~~", self._MD_PROTECT, self._md_balanced, self._MD_LEAD)
                         if not ln.lstrip().startswith("|") else
                         self._apply(ln, lambda x: f"~~{x}~~", self._MD_PROTECT, lambda x: False)
                         for ln in text.split("\n"))

    def plain(self, text):
        if not self.hit(text) or self._URL.fullmatch(text.strip()):
            return text
        strike = lambda x: "".join(c + "\u0336" for c in x)
        return self._apply(text, strike, self._URL)

    _TAG = re.compile(r"(<!--.*?-->|<[^>]*>)", re.S)
    _TAGNAME = re.compile(r"<\s*(/)?\s*([A-Za-z][A-Za-z0-9]*)")
    # A table row is about one thing (a player, a lineup), so a row that LEADS with a struck senior (or a lineup
    # with one) is struck whole. Other elements only when short -- a card's "name + stat line", not a section
    # that happens to mention one of them (that falls back to striking just the sentence that does).
    _BLOCKS = {"tr", "li", "p", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "caption", "figcaption",
               "div", "td", "th", "span", "a", "b", "strong", "em", "label"}
    _BLOCK_MAX = 160
    _RAW = {"style", "script", "title", "textarea", "code", "pre"}
    _STRUCK = {"s", "del", "strike"}

    def html(self, text):
        if not self.hit(text):
            return text
        parts = self._TAG.split(text)
        whole, raw = set(), [False] * len(parts)
        stack, raw_tag, struckd = [], None, 0
        for i in range(1, len(parts), 2):
            m = self._TAGNAME.match(parts[i])
            if raw_tag is not None:
                # inside <style>/<script>/...: only its own closing tag counts (a CSS comment can say "<pre>")
                if m and m.group(1) and m.group(2).lower() == raw_tag:
                    raw_tag = None
                elif i + 1 < len(parts):
                    raw[i + 1] = True
                continue
            if not m:
                continue
            closing, tag = bool(m.group(1)), m.group(2).lower()
            selfclose = parts[i].rstrip().endswith("/>")
            if tag in self._RAW and not closing and not selfclose:
                raw_tag = tag
                if i + 1 < len(parts):
                    raw[i + 1] = True
                continue
            if tag in self._STRUCK and not selfclose:
                struckd = max(0, struckd - 1) if closing else struckd + 1
            if i + 1 < len(parts) and struckd:
                raw[i + 1] = True
            if tag not in self._BLOCKS or selfclose:
                continue
            if not closing:
                if stack and stack[-1][0] == tag and tag in ("li", "tr", "p", "dt", "dd"):
                    self._close_block(parts, stack.pop()[1], i, whole, raw)
                stack.append((tag, i))
            elif any(t == tag for t, _ in stack):
                while stack:
                    t, j = stack.pop()
                    self._close_block(parts, j, i, whole, raw)
                    if t == tag:
                        break
        for t, j in stack:
            self._close_block(parts, j, len(parts), whole, raw)
        out = []
        for i, p in enumerate(parts):
            if i % 2 == 1 or raw[i] or not p.strip():
                out.append(p)
            elif i in whole:
                out.append("\n".join(self._wrap_line(ln) for ln in p.split("\n")))
            else:
                out.append("\n".join(self._apply(ln, lambda x: f"<s>{x}</s>", self._URL, None, self._MD_LEAD)
                                     for ln in p.split("\n")))
        return "".join(out)

    def _wrap_line(self, ln):
        lo = self._MD_LEAD.match(ln).end()
        lo += len(ln[lo:]) - len(ln[lo:].lstrip())
        core = ln[lo:].rstrip()
        return ln[:lo] + f"<s>{core}</s>" + ln[lo + len(core):] if core else ln

    def _close_block(self, parts, j, k, whole, raw):
        """Mark a block's text for whole strike when the block is about struck seniors. A table row: its first
        real text (after a bare rank / jersey number) is a struck senior, or a lineup that includes one --
        the row goes whole even if a later cell names someone else (his matchup, his read). A short element:
        it names no returning player AND either starts with the senior or is a single sentence. Anything else
        is left to sentence-level striking."""
        idx = [x for x in range(j + 1, k) if x % 2 == 0 and not raw[x] and parts[x].strip()]
        if not idx:
            return
        txt = "\n".join(_sk_html.unescape(parts[x]).strip() for x in idx)
        is_row = parts[j][1:3].lower() == "tr" and not parts[j][3:4].isalnum()
        if not self.hit(txt) or (not is_row and len(txt) > self._BLOCK_MAX):
            return
        sen, oth, _ = self._spans(txt)
        if not sen:
            return
        sen, oth = self._grouped(txt, sen, oth)
        p0 = re.match(r"[#\d\s.,:)(\-\u2013\u2014|]*", txt).end()
        p0 = min(p0, sen[0][0]) if re.fullmatch(r"[#\d\s.,:)(\-\u2013\u2014|]*", txt[:sen[0][0]]) else p0
        about = any(s == p0 or (s <= p0 + 4 and re.fullmatch(r"#?\d{1,2}\s+", txt[p0:s] or "x")) for s, _ in sen)
        if is_row:
            if about:
                whole.update(idx)
            return
        single = not any(not any(a < m.end() and m.start() < b for a, b in sen + oth)
                         for m in self._SPLIT.finditer(txt))
        if not oth and (about or single):
            whole.update(idx)

    def frame(self, data):
        """A DataFrame (or Styler) with struck text cells, for st.dataframe / st.table."""
        sty = data if (hasattr(data, "data") and hasattr(data, "set_properties")) else None
        df = sty.data if sty is not None else data
        if not isinstance(df, pd.DataFrame) or df.empty:
            return data
        out = None
        for j, c in enumerate(df.columns):
            col = df.iloc[:, j]
            if not (pd.api.types.is_object_dtype(col) or pd.api.types.is_string_dtype(col)):
                continue
            mask = col.map(self.hit)
            if not mask.any():
                continue
            if out is None:
                out = df.copy()
            out.iloc[:, j] = col.map(lambda v: self.plain(v) if self.hit(v) else v)
        if (sty is None and not isinstance(df.index, pd.MultiIndex)
                and (pd.api.types.is_object_dtype(df.index) or pd.api.types.is_string_dtype(df.index))):
            if df.index.map(self.hit).any():
                out = (df.copy() if out is None else out)
                out.index = df.index.map(lambda v: self.plain(v) if self.hit(v) else v)
        if out is None:
            return data
        if sty is not None:
            sty.data = out
            return sty
        return out

_SB_STRUCK = set()  # normalized names struck in THIS build (set in the run block below)


def _sb_drop_struck(doc):
    """The struck-through brief with last season's seniors LEFT OUT (requested: a second copy of a scrimmage / season-
    opener brief). Works on _SeniorStrike's output: a table row, list item or paragraph that is only about struck
    seniors (nothing left once the <s>...</s> text is gone but numbers and punctuation) is removed whole; a struck name
    or sentence inside other text is removed with its separator ("A, <s>B</s> and C" -> "A and C"); tables, lists and
    roster tiers left empty go too."""
    _sp = re.compile(r"<s>.*?</s>", re.S)
    _tg = re.compile(r"<[^>]+>")
    _junk = re.compile(r"[\s#\d.,:;()\-\u2013\u2014|/%+\u00b7\u2022\u2714\u2718]*")

    def _only_struck(block):
        if "<s>" not in block:
            return False
        rest = _sk_html.unescape(_tg.sub("", _sp.sub("", block)))
        return _junk.fullmatch(rest) is not None

    def _leads_struck(block):
        """The item STARTS with struck text (after its number): a key, read or note about a senior / a lineup with one
        -- the rest of it is his explanation, so the whole item goes."""
        body = re.sub(r'^<[^>]+>\s*(?:<span class="n">[^<]*</span>\s*)?', "", block)
        m = re.search(r"<s>|[^\s<>]", re.sub(r"<(?!s>)[^>]+>", "", body))
        return bool(m and m.group(0) == "<s>")

    # keep <style> / <script> untouched
    keep = []

    def _stash(m):
        keep.append(m.group(0))
        return f"\x00{len(keep) - 1}\x00"
    doc = re.sub(r"<(style|script)\b.*?</\1>", _stash, doc, flags=re.S | re.I)
    # the keys to victory: a key whose title is struck goes whole, and the keys left are numbered 1, 2, 3 again
    _parts = re.split(r'(?=<div class="sect">)', doc)
    for _i, _pt in enumerate(_parts):
        _n0 = _pt.count('class="ktv-sentence"')
        _pt = re.sub(r'<div class="ktv-sentence">(?:(?!<div\b).)*?</div>',
                     lambda m: "" if ("<s>" in m.group(0) and _leads_struck(m.group(0))) else m.group(0), _pt, flags=re.S)
        if _pt.count('class="ktv-sentence"') != _n0:
            _k = iter(range(1, 1000))
            _pt = re.sub(r'(<div class="ktv-sentence"><span class="n">)\d+\.', lambda m: f"{m.group(1)}{next(_k)}.", _pt)
        _parts[_i] = _pt
    doc = "".join(_parts)
    doc = re.sub(r"<li\b[^>]*>(?:(?!<li\b).)*?</li>",
                 lambda m: "" if ("<s>" in m.group(0) and _leads_struck(m.group(0))) else m.group(0), doc, flags=re.S)
    for tag in ("tr", "li", "p", "dt", "dd", "td"):
        rx = re.compile(rf"<{tag}\b[^>]*>(?:(?!<{tag}\b).)*?</{tag}>", re.S)
        if tag == "td":
            # a cell keeps its place in the row (the columns must still line up): only its struck text goes
            doc = rx.sub(lambda m: (re.sub(r">.*</td>$", "></td>", m.group(0), flags=re.S)
                                    if _only_struck(m.group(0)) else m.group(0)), doc)
        else:
            doc = rx.sub(lambda m: "" if _only_struck(m.group(0)) else m.group(0), doc)
    _sep = r"(?:,|&middot;|\u00b7|\||&amp;|\band\b|\bor\b)"        # (not ";" -- it ends every &entity;)
    _st = r"<s>(?:(?!</?s>).)*</s>(?:\s*\([^()<>]{0,60}\))?"                        # a struck name and its "(49)" / "(4.5 fouls/40)"
    doc = re.sub(rf"{_st}\s*{_sep}\s*", "", doc, flags=re.S)             # "<s>A</s> (3), B" -> "B"
    doc = re.sub(rf"\s*{_sep}?\s*{_st}", "", doc, flags=re.S)            # "A, <s>B</s>" -> "A"
    for _ in range(3):
        doc = re.sub(r"<ul\b[^>]*>\s*</ul>", "", doc)
        doc = re.sub(r"<table\b[^>]*>(?:(?!<table\b).)*?<tbody>\s*</tbody>\s*</table>", "", doc, flags=re.S)
        # a roster tier header with nothing under it any more
        doc = re.sub(r'<div class="tier-h">[^<]*</div>\s*(?:<p class="tier-c">[^<]*</p>\s*)?(?=<div class="tier-h">|</div>|<p class="mini">)',
                     "", doc)
    doc = re.sub(r"([Ll])ast season(?:'|&#x27;|&#39;|\u2019)s seniors are crossed out",
                 lambda m: m.group(1) + "ast season\u2019s seniors are left out", doc)
    doc = re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], doc)
    return doc


# --------------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------------

class _SbData:
    """CSV access that never raises on a missing or empty table.

    A scouting report assembled from twenty-odd tables should not fail to build because one of
    them hasn't been produced yet -- an early-season run legitimately has no lineup data, and a
    before_scout run legitimately has no game plan. Missing is recorded, not fatal.
    """

    def __init__(self, data_dir):
        self.dir = data_dir
        self.missing = []
        self.sample_dropped = []
        self._cache = {}

    def __call__(self, name):
        if name not in self._cache:
            path = os.path.join(self.dir, f"{name}.csv")
            try:
                df = pd.read_csv(path)
            except Exception:
                df = pd.DataFrame()
            # No sample data on the brief (requested). Placeholder rows (is_sample True) are dropped HERE,
            # once, for every table the brief reads, so a section whose data is all placeholder simply
            # doesn't print. The app reads the CSVs itself and still shows them, labelled as sample.
            if not df.empty and "is_sample" in df.columns:
                _is_s = df["is_sample"].astype(str).str.strip().str.lower().isin(["true", "1"])
                if _is_s.any():
                    self.sample_dropped.append(name)
                    df = df[~_is_s].reset_index(drop=True)
            if df.empty:
                self.missing.append(name)
            self._cache[name] = df
        return self._cache[name]


def _sb_num(series):
    return pd.to_numeric(series, errors="coerce")


def _sb_pct(made, att):
    made, att = float(made or 0), float(att or 0)
    return round(100 * made / att, 1) if att else None


def _sb_fmt(value, digits=1, dash="--"):
    if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
        return dash
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}" if digits else f"{value:.0f}"
    return str(value)


def _sb_esc(value):
    return _sb_html.escape("" if value is None else str(value))


def _sb_clean(value):
    """One scalar's worth of the same test _sb_has_text applies to a column."""
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in ("nan", "none") else text


def _sb_has_text(series):
    """True where a column holds a real value. An empty tag round-trips through CSV as NaN, and
    NaN.astype(str) is the literal text "nan" -- which passes a `!= ""` check and then shows up in the brief
    as a coverage (or a player) called "nan". Every "is this blank?" filter on CSV data goes through here."""
    return series.notna() & ~series.astype(str).str.strip().str.lower().isin(["", "nan", "none"])


def _sb_split(value):
    """Split a pipe-joined field into its items, dropping anything blank.

    Reads go through here rather than `str(value or "").split(" | ")`, which looks safe and isn't: an
    empty CSV cell arrives from pandas as a float NaN, and NaN is TRUTHY, so the `or ""` never fires and
    str(NaN) yields the literal text "nan" -- which then renders as a bullet point reading "nan".
    """
    text = _sb_clean(value)
    return [part.strip() for part in text.split(" | ") if part.strip()] if text else []


def _sb_has_text(series):
    """True where a column holds something a coach would actually read.

    A missing scouting note arrives here three different ways -- a real NaN, an empty string, or
    the literal text "nan" left behind by an earlier astype(str) -- and all three have to count as
    empty, or a player with no notes gets his own write-up block containing nothing.
    """
    # fillna BEFORE astype(str): in this pandas version .astype(str) on a float NaN leaves a real
    # null rather than the text "nan", so every subsequent comparison returns True and a player
    # with no notes passes the filter. The same trap is documented in the parser itself.
    cleaned = series.fillna("").astype(str).str.strip()
    return cleaned.ne("") & ~cleaned.str.lower().isin(["nan", "none"])


# --------------------------------------------------------------------------------------------
# Who are we playing
# --------------------------------------------------------------------------------------------

def _sb_resolve_matchup(_sb_d):
    """The upcoming game, and the opponent's short name as every other table spells it.

    uww_schedule holds every team's rows (_SB_UWW's own plus each opponent's), so filter to _SB_UWW's
    before looking for the Upcoming flag. The short name is then resolved against the tables that
    actually key on it, rather than assumed to equal the schedule's own opponent text -- those two
    agree in the normal case, but the whole point of pinning it down here is so that they can't
    quietly disagree in the report.
    """
    sched = _sb_d("uww_schedule")
    if sched.empty or "Upcoming" not in sched.columns:
        return None, None, None

    uww_rows = sched[sched["team"].astype(str).str.contains("Whitewater", case=False, na=False)]
    upcoming = uww_rows[uww_rows["Upcoming"].astype(str).str.strip().str.lower() == "yes"]
    if upcoming.empty:
        return None, None, None
    game = upcoming.iloc[0]
    scheduled_name = str(game["opponent"]).strip()

    candidates = set()
    for table, col in (("uww_player_profiles", "opponent"), ("uww_opponent_team_totals", "opponent"),
                       ("uww_opponent_rosters", "opponent")):
        df = _sb_d(table)
        if not df.empty and col in df.columns:
            candidates |= set(df[col].dropna().astype(str))

    short = next(
        (c for c in sorted(candidates, key=len, reverse=True)
         if c.lower() in scheduled_name.lower() or scheduled_name.lower() in c.lower()),
        scheduled_name,
    )
    return game, scheduled_name, short


# --------------------------------------------------------------------------------------------
# Team-level numbers
# --------------------------------------------------------------------------------------------

def _sb_team_line(box, team_col, team_value, invert=False):
    """Per-game team averages straight from a play-by-play-derived box score.

    Deliberately NOT read off uww_player_profiles: that table mixes conventions (PTS/REB/MIN are
    per game, AST/STL/BLK/TO are season totals awaiting a games-played divisor), which is exactly
    the kind of thing that produces a report where two numbers on the same row mean different
    things. A raw box score has one convention: totals. Divide once, here.
    """
    if box.empty or team_col not in box.columns:
        return {}
    mask = box[team_col].astype(str) == str(team_value)
    rows = box[~mask] if invert else box[mask]
    if rows.empty:
        return {}

    games = rows["game_date"].nunique() if "game_date" in rows.columns else 0
    if not games:
        return {}

    total = {c: _sb_num(rows[c]).sum() if c in rows.columns else 0
             for c in ("PTS", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA",
                       "REB", "OREB", "DREB", "AST", "STL", "BLK", "TO")}
    return {
        "games": games,
        "PTS": total["PTS"] / games,
        "REB": total["REB"] / games,
        "AST": total["AST"] / games,
        "TO": total["TO"] / games,
        "STL": total["STL"] / games,
        "BLK": total["BLK"] / games,
        "FG%": _sb_pct(total["FGM"], total["FGA"]),
        "3P%": _sb_pct(total["FG3M"], total["FG3A"]),
        "FT%": _sb_pct(total["FTM"], total["FTA"]),
        "3PA": total["FG3A"] / games,
        "FGA": total["FGA"] / games,
        # Pace: possessions per game, same estimate the app's tempo table uses (FGA - OREB + TO +
        # 0.475*FTA) over the same rows -- players AND the synthetic TEAM row, which carries team
        # turnovers. Left out entirely when the box has no OREB column: the sum above would silently
        # treat it as zero and overstate pace by every offensive rebound.
        "PACE": ((total["FGA"] - total["OREB"] + total["TO"] + 0.475 * total["FTA"]) / games
                 if "OREB" in rows.columns else None),
    }


# --- Four Factors ---------------------------------------------------------------------------------------
# Dean Oliver's own weighting -- shooting matters most, free throws least. Copied from the app rather than
# re-chosen, so the brief's table and the app's dialog can't rank the factors differently.
_SB_FF_WEIGHTS = {"eFG%": 0.40, "TOV%": 0.25, "ORB%": 0.20, "FT Rate": 0.15}
# Higher is better for three of them; TOV% is the exception -- a turnover is a lost possession.
_SB_FF_HIGHER_IS_BETTER = {"eFG%": True, "TOV%": False, "ORB%": True, "FT Rate": True}


def _sb_possessions(fga, oreb, to, fta):
    """The standard possession estimate. A box score carries no possession count, so this is the widely
    used approximation: a possession ends on a made shot, a defensive rebound, a turnover, or the last free
    throw of a trip -- 0.475 approximating how often a college FTA is the last of its trip. CONFIRMED CHANGE
    (requested): Ken Pomeroy's (KenPom) college coefficient everywhere possessions are estimated; it was 0.44 (the
    NBA version) here, so the Four Factors' TOV% and PACE above used different possession counts."""
    return fga - oreb + to + 0.475 * fta


def _sb_four_factors(team_box, opp_box):
    """eFG%, TOV%, ORB% and FT Rate for team_box's side. opp_box (the other side over the same games) is
    required for ORB%, whose denominator is the opponent's defensive rebounds."""
    def total(df, col):
        return _sb_num(df[col]).sum() if col in df.columns else 0

    fgm, fga = total(team_box, "FGM"), total(team_box, "FGA")
    fg3m, to = total(team_box, "FG3M"), total(team_box, "TO")
    fta, oreb = total(team_box, "FTA"), total(team_box, "OREB")
    opp_dreb = total(opp_box, "DREB")
    poss = _sb_possessions(fga, oreb, to, fta)
    return {
        "eFG%": ((fgm + 0.5 * fg3m) / fga * 100) if fga > 0 else None,
        "TOV%": (to / poss * 100) if poss > 0 else None,
        "ORB%": (oreb / (oreb + opp_dreb) * 100) if (oreb + opp_dreb) > 0 else None,
        "FT Rate": (fta / fga * 100) if fga > 0 else None,
    }


def _sb_player_table(_sb_d, short):
    """One row per opponent player: identity from the roster, production from their own film."""
    box = _sb_d("uww_opponent_prior_games_box_score")
    profiles = _sb_d("uww_player_profiles")

    rows = []
    if not box.empty and "team" in box.columns:
        own = box[box["team"].astype(str) == str(short)]
        own = own[own["player"].astype(str) != "TEAM"]
        if not own.empty:
            grouped = own.groupby("player")
            for name, g in grouped:
                games = g["game_date"].nunique() if "game_date" in g.columns else len(g)
                total = {c: _sb_num(g[c]).sum() if c in g.columns else 0
                         for c in ("PTS", "REB", "AST", "STL", "BLK", "TO", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA")}
                rows.append({
                    "name": str(name),
                    "games": games,
                    "PTS": total["PTS"] / games if games else None,
                    "REB": total["REB"] / games if games else None,
                    "AST": total["AST"] / games if games else None,
                    "STL": total["STL"] / games if games else None,
                    "BLK": total["BLK"] / games if games else None,
                    "TO": total["TO"] / games if games else None,
                    "FG%": _sb_pct(total["FGM"], total["FGA"]),
                    "3P%": _sb_pct(total["FG3M"], total["FG3A"]),
                    "FT%": _sb_pct(total["FTM"], total["FTA"]),
                    # Season totals kept alongside the per-game rates: the reads below need volume to
                    # decide whether a percentage means anything, and a rate alone can't say that.
                    "FGA": total["FGA"],
                    "3PA": total["FG3A"],
                    "FTA": total["FTA"],
                    "PTS_total": total["PTS"],
                })

    table = pd.DataFrame(rows)
    if table.empty:
        return table

    ident_cols = ["name", "jersey_number", "position", "height", "class_year", "role",
                  "player_notes", "keys_to_defending", "notes_tags_display", "keys_tags_display"]
    # Two identity sources, tried in order, the second only filling gaps the first left. Both are
    # built from the scouting report, so with before_scout="yes" neither exists and this is a no-op
    # -- which is why the jersey fallback below reads the play-by-play name itself.
    for ident_table in (profiles, _sb_d("uww_opponent_rosters")):
        if ident_table.empty or not {"opponent", "name"}.issubset(ident_table.columns):
            continue
        ident = ident_table[ident_table["opponent"].astype(str) == str(short)]
        ident = ident[[c for c in ident_cols if c in ident.columns]].drop_duplicates("name")
        if ident.empty:
            continue
        table = table.merge(ident, on="name", how="left", suffixes=("", "_alt"))
        for col in ident_cols:
            alt = f"{col}_alt"
            if alt in table.columns:
                table[col] = table[col].where(_sb_has_text(table[col]), table[alt])
                table = table.drop(columns=[alt])

    for col in ident_cols:
        if col not in table.columns:
            table[col] = None

    # Some play-by-play feeds prefix the jersey onto the name ("3 Jalen Ward"); others carry no
    # number at all. Take one off the front when it's there, and strip it from the displayed name so
    # it isn't printed twice. When neither the roster nor the feed has a number the column stays
    # blank, which is the honest answer -- better than inventing one.
    parsed = table["name"].astype(str).str.extract(r"^#?\s*(\d{1,2})\s+(.*)$")
    table["jersey_number"] = table["jersey_number"].where(
        _sb_has_text(table["jersey_number"]), parsed[0])
    table["name"] = parsed[1].where(parsed[1].notna(), table["name"])

    table["role"] = table["role"].fillna("Bench")
    # Season volume first: ordering by PPG put a one-game 15-point night above a four-game 13.5 ppg starter.
    return table.sort_values(["PTS_total", "PTS"], ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------------------------

# --------------------------------------------------------------------------------------------
# Presentation -- deliberately the app's own visual language
# --------------------------------------------------------------------------------------------
# Every value below is lifted from streamlit_app.py rather than invented here: Montserrat and the
# --warhawk-* variables from its global stylesheet, #1a1a2e / 10px radius / #9DAAAC labels from the
# Upcoming Game banner, the 1px #e0e0e0 + 8px radius bordered box from section_header(), and the
# "N. <headline>" + dimmed 0.8rem evidence line from the Keys to Victory renderer. A coach
# reading this next to the app should not be able to tell they came from different code.

_SB_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&display=swap');

:root {
  --warhawk-purple: #4E2A84;
  --warhawk-gray: #9DAAAC;
  --warhawk-light: #F0EDF5;
  --banner: #1a1a2e;
  --edge: #e0e0e0;
  --body: #262730;
  --dim: #666;
  --win: #2e7d32;
  --loss: #c62828;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 18px 18px 56px;
  background: #fff; color: var(--body);
  font-family: 'Montserrat', -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 15px; line-height: 1.5;
  -webkit-text-size-adjust: 100%;
}
.page { max-width: 1000px; margin: 0 auto; }
p { margin: 0 0 0.65rem; }

/* section_header() */
.sect { border: 1px solid var(--edge); border-radius: 8px; padding: 12px 16px; margin: 1.5rem 0 0.75rem; }
.sect .t { font-weight: 800; font-size: 1.05rem; letter-spacing: 0.5px; color: var(--warhawk-purple); }
.cmpwrap { display: flex; flex-wrap: wrap; gap: 14px; } .cmp { flex: 1 1 260px; } .cmp table { width: 100%; }
.sect .t .lsn { font-size: 0.7rem; font-weight: 700; color: #fff; background: #8a6d1f; border-radius: 4px; padding: 1px 6px;
  margin-left: 6px; vertical-align: middle; letter-spacing: 0.3px; }
.btype { border-left: 5px solid #8a6d1f; background: #fbf6e9; border-radius: 6px; padding: 8px 14px; margin: 10px 0 4px; }
.btype.bt-preseason { border-left-color: #2e7d32; background: #eef7ee; }
.btype .btt { font-weight: 800; letter-spacing: 0.5px; font-size: 0.95rem; color: #3b2a00; }
.btype.bt-preseason .btt { color: #1b4d1e; }
.btype .bts { font-size: 0.8rem; color: #444; margin-top: 2px; }
.rcwrap { display: flex; gap: 18px; flex-wrap: wrap; font-size: 0.82rem; }
.rcwrap .rc { flex: 1 1 280px; }
.rcwrap .rct { font-weight: 800; margin-bottom: 4px; }
.card { border: 1px solid var(--edge); border-radius: 8px; padding: 12px 16px; margin: 0 0 0.75rem; }
.card .hd { font-weight: 800; font-size: 1.05rem; letter-spacing: 0.5px; margin-bottom: 8px; }

/* Two panels side by side, the way the app pairs Team Stats with Last Five Games. min-width:0 is
   load-bearing: without it a flex child refuses to shrink below its content's intrinsic width, and
   the roster table's eight columns push the pair wider than the page instead of compressing. */
.cols { display: flex; gap: 16px; align-items: flex-start; }
.cols > .col { flex: 1; min-width: 0; }
.cols .sect { margin-top: 0; }
.cols table { font-size: 0.78rem; }
.cols th, .cols td { padding-left: 5px; padding-right: 5px; }
.lede { font-size: 0.95rem; }
ul.bl { margin: 0; padding-left: 1.1rem; }
ul.bl li { font-size: 0.95rem; margin-bottom: 5px; }
ul.bl li::marker { color: var(--warhawk-purple); }
ul.bl li:last-child { margin-bottom: 0; }

/* banner */
.banner { background: var(--banner); border-radius: 10px; padding: 22px 32px; margin-bottom: 0.75rem;
          display: flex; align-items: center; justify-content: space-between; }
.banner .side { text-align: center; flex: 1; display: flex; flex-direction: column; align-items: center; }
.banner .mid { justify-content: center; }
.banner .crest { height: 64px; display: flex; align-items: center; justify-content: center; margin-bottom: 8px; }
.banner .crest img { max-height: 64px; max-width: 90px; object-fit: contain; }
.banner .team { color: #fff; font-weight: 800; font-size: 1.4rem; letter-spacing: 0.5px; }
.banner .rec { color: var(--warhawk-gray); font-size: 1.05rem; font-weight: 600; margin-top: 3px; }
.banner .streak { color: #aabbcc; font-size: 0.8rem; font-style: italic; margin-top: 2px; }
.banner .when { color: var(--warhawk-gray); font-size: 1rem; font-weight: 500; }
.banner .vs { color: #fff; font-size: 1.6rem; font-weight: 700; margin: 4px 0; }
.banner .where { color: var(--warhawk-gray); font-size: 0.95rem; }

/* team stats: UWW left, stat centre, opponent right */
.cmp .row { display: flex; align-items: center; justify-content: space-between;
            padding: 7px 4px; border-bottom: 1px solid #f0f0f0; }
.cmp .row:last-child { border-bottom: 0; }
.cmp .us, .cmp .them { flex: 1; font-size: 0.95rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.cmp .us { color: var(--warhawk-purple); }
.cmp .them { color: #222; text-align: right; }
.cmp .stat { flex: 1.1; text-align: center; font-size: 0.8rem; color: var(--dim); font-weight: 600; }
.cmp .who { display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 8px; padding: 0 4px; }
.cmp .who .l { font-size: 0.95rem; font-weight: 700; color: var(--warhawk-purple); }
.cmp .who .c { font-size: 0.85rem; color: #888; }
.cmp .who .r { font-size: 0.95rem; font-weight: 700; color: #222; }
.lead { font-size: 0.68rem; font-weight: 700; padding: 1px 6px; border-radius: 8px; margin-left: 6px;
        vertical-align: middle; }
.lead.us { background: var(--warhawk-light); color: var(--warhawk-purple); }
.lead.them { background: #f1f1f1; color: #555; }

.ff-lede { font-size: 0.88rem; margin: 0 0 6px; }
td.ff-us { color: var(--warhawk-purple); font-weight: 700; }
td.ff-them { color: var(--loss); font-weight: 700; }

/* keys */
.ktvcat { font-size: 0.72rem; font-weight: 800; letter-spacing: 0.8px; text-transform: uppercase;
          color: var(--warhawk-purple); border-bottom: 2px solid var(--warhawk-light);
          padding-bottom: 4px; margin: 14px 0 10px; }
.ktvcat:first-child { margin-top: 0; }
.key { margin-bottom: 14px; }
.key .hl { font-size: 0.95rem; font-weight: 700; }
/* The lineup and shot-look keys carry multi-line captions ("Worst +/- lineups:" then one unit per
   line). pre-line keeps those breaks without turning the text into a <pre> block. */
.key .ev { font-size: 0.8rem; color: var(--dim); margin: 0 0 6px 18px; white-space: pre-line; }
.key .why { font-size: 0.88rem; margin: 0 0 0 18px; font-style: italic; color: #333;
            white-space: pre-line; }
.key .src { border: 1px solid #666; background: #fff; font-size: 0.65rem; font-weight: 600;
            padding: 1px 7px; border-radius: 8px; margin-left: 4px; white-space: nowrap; }

/* tables */
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th { text-align: right; font-weight: 700; color: var(--dim); font-size: 0.72rem; letter-spacing: 0.3px;
     padding: 0 8px 6px; border-bottom: 1px solid var(--edge); white-space: nowrap; }
td { text-align: right; padding: 7px 8px; border-bottom: 1px solid #f0f0f0; white-space: nowrap;
     font-variant-numeric: tabular-nums; }
tr:last-child td { border-bottom: 0; }
th:first-child, td:first-child { text-align: left; white-space: normal; }
td.wrap { text-align: left; white-space: normal; font-variant-numeric: normal; }
th.read, td.read { text-align: left; white-space: normal; font-variant-numeric: normal; min-width: 130px; }
.dot { display: block; font-size: 0.76rem; line-height: 1.35; padding-left: 10px; position: relative; }
.dot::before { content: "\u25aa"; position: absolute; left: 0; }
.dot.good { color: #1b5e20; }
.dot.bad { color: #8c1d2c; }
tr.starter td { font-weight: 700; }
td.jersey { color: var(--warhawk-purple); font-weight: 700; }
th.num, td.num { text-align: right; width: 2.4rem; }
.meta { color: #888; font-weight: 500; font-size: 0.78rem; margin-left: 7px; }

/* player notes, mirroring the Player Details dialog */
.player { border: 1px solid var(--edge); border-radius: 8px; padding: 12px 16px; margin-bottom: 10px; }
.player .nm { font-weight: 700; font-size: 1rem; }
.player .role { font-size: 0.6rem; font-weight: 700; letter-spacing: 0.4px; text-transform: uppercase;
                background: var(--warhawk-light); color: var(--warhawk-purple); border-radius: 8px;
                padding: 2px 7px; margin-left: 6px; vertical-align: middle; }
.player .statline { font-size: 0.8rem; color: var(--dim); font-variant-numeric: tabular-nums;
                    margin-top: 2px; }
.player .reads { margin-top: 6px; }
.player .ln { color: #888; font-weight: 500; font-size: 0.8rem; margin-left: 8px; }
.player .lbl { font-weight: 700; font-size: 0.85rem; }
.player .notes { font-style: italic; color: #333; font-size: 0.88rem; margin: 4px 0 0; }
.player .keys { font-size: 0.88rem; margin: 4px 0 0; }
.srcblock { border-left: 3px solid var(--edge); padding: 2px 0 2px 10px; margin: 8px 0 0; }
.srcblock.coach { border-left-color: var(--warhawk-purple); }
.srcblock.derived { border-left-color: #37474f; }
.srclabel { font-size: 0.65rem; font-weight: 700; letter-spacing: 0.4px; text-transform: uppercase;
            color: #888; margin-bottom: 2px; }
.kd { margin-top: 4px; }
.kd .lbl { font-weight: 700; font-size: 0.8rem; display: block; }
.kdline { font-size: 0.85rem; padding-left: 10px; position: relative; }
.kdline::before { content: "\u25aa"; position: absolute; left: 0;
                 color: var(--warhawk-purple); }

/* last five */
.five { display: flex; flex-wrap: wrap; gap: 10px; }
.five .g { border: 1px solid var(--edge); border-radius: 8px; padding: 10px 14px; min-width: 150px; flex: 1; }
.five .d { color: #888; font-size: 0.78rem; }
.five .o { font-size: 0.92rem; font-weight: 600; margin: 2px 0; }
.five .r { font-weight: 700; font-size: 0.92rem; }
.five .r.w { color: var(--win); }
.five .r.l { color: var(--loss); }

/* style matchup cards */
.matchrow { display: flex; gap: 10px; align-items: stretch; }
.matchrow > .match { flex: 1; min-width: 0; margin-bottom: 0; }
.match { border: 1px solid #eee; border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; }
.match .nm { font-weight: 700; font-size: 0.95rem; color: var(--warhawk-purple); }
.match .score { font-size: 1.6rem; font-weight: 800; line-height: 1.1; }
.match .score .of { font-size: 0.7rem; color: #888; font-weight: 600; }
.match .sub { font-size: 0.68rem; color: #999; }
.match .conf { font-size: 0.68rem; font-weight: 700; }
.match .conf.hi { color: #2e7d32; }
.match .conf.mid { color: #8a6d3b; }
.match .conf.lo { color: #b3261e; }
.match .meet { font-size: 0.85rem; margin-top: 2px; }
.match .meet .w { color: var(--win); font-weight: 700; }
.match .meet .l { color: var(--loss); font-weight: 700; }
.match .alike { font-size: 0.75rem; color: #2e7d32; margin-top: 6px; }
.match .differs { font-size: 0.75rem; color: #c62828; }
.match .gap { font-size: 0.72rem; color: #666; margin-top: 2px; }
.strip { border: 1px solid #eee; border-radius: 8px; padding: 10px 12px; margin-top: 8px; font-size: 0.85rem; }
.strip .lb { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.4px; color: var(--warhawk-purple);
             text-transform: uppercase; margin-bottom: 2px; }
.thin { font-size: 0.78rem; color: #8a6d3b; background: #fdf6e3; border-radius: 6px; padding: 8px 10px;
        margin: 0 0 8px; }

.flag { margin-bottom: 10px; }
.flag .fl { font-size: 0.9rem; }
.flag .conf-tag { font-size: 0.62rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.4px;
                  color: #888; border: 1px solid var(--edge); border-radius: 8px; padding: 1px 6px;
                  margin-left: 4px; white-space: nowrap; }

.note { font-size: 0.78rem; color: var(--dim); margin: 8px 0 0; }

/* SAMPLE DATA boxes. Anything generated as a placeholder (is_sample=True in its CSV) is drawn inside one of
   these and nowhere else, so a coach can never mistake a placeholder for scouting. */
.sample { border: 2px solid #c62828; background: #fff5f5; border-radius: 8px; padding: 10px 14px 12px;
          margin: 0 0 0.75rem; }
.sample .sample-tag { display: inline-block; background: #c62828; color: #fff; font-size: 0.66rem;
                      font-weight: 800; letter-spacing: 0.6px; text-transform: uppercase; border-radius: 6px;
                      padding: 2px 8px; margin-bottom: 6px; }
.sample .sample-why { font-size: 0.78rem; color: #8c1d2c; margin: 0 0 8px; }
.sample table td { border-bottom-color: #f6dada; }
.sect.sample-sect { border: 2px solid #c62828; background: #fff5f5; }
.pc-grid { display: flex; gap: 12px; flex-wrap: wrap; }
/* ---- condensed layout (#6) ---- */
.pb { break-after: page; page-break-after: always; height: 0; }
.hs-ls { color: #777; font-style: italic; }
.divider { margin: 18px 0 10px; padding: 10px 14px; border-radius: 8px; background: var(--banner); color: #fff; }
.divider .dt { font-size: 1.05rem; font-weight: 800; letter-spacing: 0.6px; }
.divider .ds { font-size: 0.78rem; color: var(--warhawk-gray); margin-top: 2px; }
.linkbar { font-size: 0.8rem; margin: -4px 0 10px; }
a.applink { color: var(--warhawk-purple); font-weight: 700; text-decoration: none; white-space: nowrap; }
a.applink:hover { text-decoration: underline; }
.applink.off { color: var(--dim); font-weight: 600; font-style: italic; }
a.nmlink { color: inherit; text-decoration: none; border-bottom: 1px dotted #b9a9d3; }
sup.fn { font-size: 0.62rem; color: var(--warhawk-purple); font-weight: 700; margin-left: 2px; }
sup.fn a.fnlink { color: inherit; text-decoration: none; border-bottom: 1px dotted #b9a9d3; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; align-items: start; }
/* Newspaper-style flow: cards fill the first column then the second, so a short card never strands the rest
   of a page the way a grid row does in print. */
.flow2 { column-count: 2; column-gap: 12px; }
.flow2 > .player, .flow2 > .gcell { display: inline-block; width: 100%; break-inside: avoid; }
.grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0 10px; align-items: start; }
.player, .key, .match { break-inside: avoid; page-break-inside: avoid; }
.chips { display: flex; flex-wrap: wrap; gap: 4px 6px; margin-top: 6px; }
.chip { font-size: 0.68rem; border-radius: 10px; padding: 1px 8px; background: #f3f0f8; color: var(--body); }
.chip.warn { background: #fdf6e3; color: #8a6d3b; }
.ktvline { display: flex; gap: 6px; align-items: baseline; padding: 3px 0; border-bottom: 1px solid #f2f2f2; font-size: 0.9rem; }
.ktvline:last-child { border-bottom: 0; }
.ktvline .n { font-weight: 800; color: var(--warhawk-purple); min-width: 1.6em; }
.ktvline .src { font-size: 0.6rem; font-weight: 700; letter-spacing: 0.3px; text-transform: uppercase; border: 1px solid; border-radius: 8px; padding: 0 6px; margin-left: 4px; white-space: nowrap; vertical-align: middle; }
.tier-h { font-size: 0.8rem; font-weight: 800; letter-spacing: 0.5px; text-transform: uppercase; color: var(--warhawk-purple); margin: 12px 0 2px; }
.tier-c { font-size: 0.76rem; color: var(--dim); margin: 0 0 6px; }
table.compact td, table.compact th { padding: 4px 6px; font-size: 0.78rem; }
td.nm { font-weight: 700; white-space: nowrap; }
/* roster: each player's bio bar, then his row with the photo above his name */
table.roster tr.p-hd td { text-align: left; background: #f4f2f8; border-top: 2px solid #d9d3e6; padding: 3px 8px;
                          font-size: 0.74rem; color: #444; white-space: normal; }
table.roster tr.p-hd .p-hd-nm { display: none; }
/* (requested: Option A -- the numbers across, the reads under them in two labeled columns, Offense / Defense) */
table.roster tr.p-rd .p-hd-nm { display: none; }
table.roster tr.p-rd td { padding: 0 0 6px; border-top: none; white-space: normal; text-align: left; }
.rd2 { display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid #e6e1ee; }
.rd2 > div { padding: 5px 10px 2px; font-size: 0.76rem; line-height: 1.35; }
.rd2 > div + div { border-left: 1px solid #e6e1ee; }
.rd2 .rd-h { display: block; font-size: 0.62rem; font-weight: 800; letter-spacing: 0.8px; color: var(--warhawk-purple); margin-bottom: 2px; }
.rd2 ul { margin: 0; padding-left: 14px; } .rd2 li { margin: 0 0 1px; }
.rd2 li.key { font-weight: 700; }
.rd2 .none { color: var(--dim); font-style: italic; }
.rd2 .rd-role { margin: 0 0 2px; }
/* the player card (requested: "I still need the display to look better") */
table.pc2 { width: 100%; border: 1px solid #ddd6e8; border-radius: 8px; border-collapse: separate; border-spacing: 0;
            overflow: hidden; margin: 0 0 8px; break-inside: avoid; page-break-inside: avoid; }
table.pc2 td { padding: 0; border: none; text-align: left; white-space: normal; }
table.pc2 .p-hd-nm { display: none; }
.pc-top-in { display: flex; align-items: center; gap: 10px; padding: 6px 10px; background: #f4f2f8; }
.pc-top-in .photo-thumb { width: 46px; height: 46px; margin: 0; flex: none; }
.pc-who { flex: 1; min-width: 0; }
.pc-nm { font-weight: 800; font-size: 0.95rem; }
.pc-nm a { color: inherit; }
.pc-bio { font-size: 0.72rem; color: #555; }
.pc-chips { margin-top: 2px; }
.pc-chip { display: inline-block; font-size: 0.66rem; font-weight: 700; background: #fff3b0; color: #5c4a00; border-radius: 9px;
           padding: 1px 7px; margin-right: 4px; }
.pc-foul { font-size: 0.7rem; border: 1px solid #ddd; background: #fff; border-radius: 10px; padding: 2px 8px; white-space: nowrap;
           color: #666; }
.pc-foul.yes { color: #1e7b34; border-color: #9fd3ad; font-weight: 700; }
.pc-foul.no { color: #b3261e; border-color: #eba9a4; font-weight: 700; }
.pc-grid { display: grid; grid-template-columns: repeat(8, 1fr); text-align: center; border-bottom: 1px solid #ece8f2;
           position: relative; }
.pc-grid > div { padding: 4px 2px 3px; }
.pc-grid b { display: block; font-size: 0.9rem; }
.pc-grid span { display: block; font-size: 0.58rem; font-weight: 700; letter-spacing: 0.6px; color: #888; }
.pc-grid .pc-sub { display: inline; font-size: 0.6rem; font-weight: 400; color: #888; letter-spacing: 0; }
.pc-grid .pc-src { grid-column: 1 / -1; font-size: 0.62rem; color: #8a6d00; padding: 0 0 3px; }
.pc-none { font-size: 0.74rem; color: var(--dim); font-style: italic; padding: 5px 10px; border-bottom: 1px solid #ece8f2; }
table.pc2 .rd2 { border-top: none; }
table.pc2 .rd2 > div { padding: 5px 10px 4px; }
table.pc2 .rd-o { background: #fbfaf7; }
/* (requested: "Remove all of the 'All caps' and bold writing so that everything looks similar font") -- the roster card in
   one weight and normal case; headings are told apart by color and size only */
table.pc2, table.pc2 * { font-weight: 400 !important; text-transform: none !important; letter-spacing: normal !important; }
table.pc2 .pc-nm { font-size: 0.95rem; }
table.pc2 .pc-grid b { font-size: 0.88rem; }
table.pc2 .pc-grid span { font-size: 0.62rem; color: #888; }
table.pc2 .rd-h { font-size: 0.7rem; color: var(--warhawk-purple); }
table.pc2 li.key { color: #1f5e2e; }
/* CONFIRMED BUG (fixed; "The player roster is too wide now"): the cards ran to ~2x the page. The page already has a
   ".pc-grid > div { min-width: 260px }" rule (another section's grid, same class name) that hit the stat strip, and the
   auto-sized table grew to the reads' full line length. Fixed layout + zero minimum widths keep each card on the page. */
table.pc2 { table-layout: fixed; width: 100%; max-width: 100%; }
table.pc2 .rd2 { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
table.pc2 .pc-grid { grid-template-columns: repeat(8, minmax(0, 1fr)); }
table.pc2 .pc-grid > div, table.pc2 .rd2 > div { min-width: 0; flex: none; }
table.pc2 li, table.pc2 .pc-bio { overflow-wrap: anywhere; }
/* the "How they run Motion" table wraps its long cells instead of running off the page */
table.mb-tbl { width: 100%; table-layout: fixed; }
/* the situation > formation > what they run table (requested look: banded like "How they score against each defense") */
table.ob-tbl { width: 100%; border-collapse: collapse; font-size: 0.74rem; table-layout: fixed; }
table.ob-tbl col.c1 { width: 15%; }
table.ob-tbl th, table.ob-tbl td { padding: 4px 6px; text-align: right; white-space: normal; overflow-wrap: anywhere; }
details.ob-det { margin: 6px 0 10px; }
.pcs-h, .pcs-r > summary, .pcs-sum { display: grid; grid-template-columns: 1fr 90px 90px; gap: 0; font-size: 0.74rem; }
.pcs-h { color: #666; font-weight: 600; border-bottom: 1px solid #ddd; }
.pcs-h > span, .pcs-r > summary > span, .pcs-sum > span { padding: 5px 6px; }
.pcs-h .t1, .pcs-r .t1 { background: #f7f5fb; text-align: right; }
.pcs-h .l, .pcs-r .l { text-align: left; }
.pcs-r { border-bottom: 1px solid #ece8f2; }
.pcs-r > summary { cursor: pointer; list-style: none; }
.pcs-r > summary::-webkit-details-marker { display: none; }
.pcs-r > summary > span.l { position: relative; padding-left: 22px; font-weight: 600; color: var(--warhawk-purple, #4E2A84); }
.pcs-none .pcs-sum > span.l { padding-left: 22px; }
.pcs-r > summary > span.l::before { content: ""; position: absolute; left: 7px; top: 50%; margin-top: -5px; width: 0; height: 0;
  border-left: 6px solid var(--warhawk-purple, #4E2A84); border-top: 5px solid transparent; border-bottom: 5px solid transparent; }
.pcs-r[open] > summary > span.l::before { transform: rotate(90deg); }
.pcs-r[open] > summary { background: #f4f1f9; }
.pcs-b { padding: 4px 8px 10px 22px; }
.pcs-g { margin: 6px 0 10px; }
.pcs-gh { font-size: 0.78rem; padding: 3px 0; border-bottom: 1px solid #e3ddef; margin-bottom: 2px; }
table.pcs-t { table-layout: auto; }
table.pcs-t td, table.pcs-t th { white-space: normal; }
.pd-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 10px; }
.pd-card { border: 1px solid #ddd; border-radius: 8px; padding: 6px; break-inside: avoid; }
.pd-card .pd-t { font-weight: 700; font-size: 0.8rem; margin-bottom: 4px; }
.pd-card img { width: 100%; height: auto; display: block; }
details.ob-det > summary { cursor: pointer; font-weight: 700; color: var(--purple, #4E2A84); padding: 6px 10px;
  border: 1px solid #ddd; border-radius: 6px; background: #f6f3fa; list-style: revert; }
details.ob-det[open] > summary { margin-bottom: 6px; }
ul.ob-sum { margin: 0; padding-left: 18px; font-size: 0.8rem; line-height: 1.4; }
ul.ob-sum li { margin: 2px 0; }
table.ob-tbl .ob-who { margin-top: 3px; font-size: 0.66rem; line-height: 1.25; color: #555; overflow-wrap: normal; }
table.ob-tbl th { color: #666; font-weight: 600; }
table.ob-tbl th.ob-b1 { border-top: 3px solid var(--warhawk-purple); background: #f4f1f9; color: var(--warhawk-purple);
                        font-size: 0.66rem; letter-spacing: 0.6px; text-align: center; }
table.ob-tbl th.ob-b2 { border-top: 3px solid #2e7d32; background: #ecf5ec; color: #2e7d32; font-size: 0.66rem;
                        letter-spacing: 0.6px; text-align: center; }
table.ob-tbl .t1 { background: #f7f5fb; } table.ob-tbl .t2 { background: #eef6ee; }
table.ob-tbl .t3 { background: #eaf2fb; }
table.ob-tbl th.ob-b3 { border-top: 3px solid #1565c0; background: #eaf2fb; color: #1565c0; font-size: 0.66rem; letter-spacing: .5px; }
table.ob-tbl .l { text-align: left; } table.ob-tbl td.w { font-size: 0.7rem; line-height: 1.3; }
table.ob-tbl tr.ob-sit td { border-top: 2px solid #cfc4e2; font-weight: 700; }
table.ob-tbl tr.ob-sit td.w { font-weight: 400; }
table.ob-tbl tr.ob-form td { border-top: 1px solid #ece8f2; }
table.ob-tbl tr.ob-form td.n { font-weight: 400; color: #444; }
table.ob-tbl td.ob-fm { vertical-align: middle; }
table.ob-tbl td.ob-pcall { vertical-align: middle; text-align: left; font-size: 0.7rem; border-top: 1px solid #ece8f2; }
table.ob-tbl td.ob-all { color: #666; font-style: italic; }
table.ob-tbl tr.ob-act td { font-size: 0.68rem; color: #444; border-top: 1px dotted #eee; }
table.ob-tbl tr.ob-pc td { border-top: 1px solid #f0edf5; }
table.ob-tbl td.ob-vs { border-top: 2px solid #cfc4e2; border-right: 1px solid #e3ddef; vertical-align: middle; text-align: center;
  padding: 4px 2px; }
table.ob-tbl td.ob-vs div { writing-mode: vertical-rl; transform: rotate(180deg); margin: 0 auto; font-weight: 800;
  color: var(--warhawk-purple); white-space: nowrap; }
table.ob-tbl tr.ob-cov td { font-size: 0.92em; color: #555; padding-top: 1px; padding-bottom: 1px; }
table.ob-tbl tr.ob-kind td { font-size: 0.78em; font-weight: 700; color: #4E2A84; text-transform: uppercase; letter-spacing: .5px; padding-top: 6px; padding-bottom: 0; }
table.pc2 .rd-tend { margin-top: 4px; padding-top: 3px; border-top: 1px dashed #e2dcec; }
table.pc2 .rd-sub { display: block; font-size: 0.66rem; color: var(--warhawk-purple); }
table.mb-tbl td, table.mb-tbl th { white-space: normal; overflow-wrap: anywhere; text-align: left; }
.rd-lead { font-size: 0.72rem; color: #6b5a1e; background: #fff8dc; padding: 2px 10px; }
table.roster thead th:first-child { text-align: center; }
.thin-ast { color: #8c1d2c; font-weight: 700; margin-left: 1px; }
table.roster td.nm.p-cell { text-align: center; vertical-align: top; white-space: normal; padding-top: 4px; }
table.roster td.nm.p-cell .photo-thumb { margin: 0 auto 3px; width: 44px; height: 44px; }
.mini { font-size: 0.74rem; color: var(--dim); }
.results { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.foul-icon { font-size: 1rem; text-align: center; }
tr.serrow td { font-weight: 700; background: var(--warhawk-light); }
tr.setrow td:first-child { padding-left: 12px; }
td.foul-icon { font-size: 0.95rem; font-weight: 700; }
.tbl-bul { margin: 0; padding-left: 14px; }
.tbl-bul li { margin: 0 0 1px; }
/* Defense-family table: THEIR offense and OUR defense sit under separate labelled bands with different
   tints, so a coach can't mistake "PPP allowed" (ours) for "PPP" (theirs) at a glance. */
table.dfam .dfam-band th { font-size: 0.6rem; letter-spacing: 0.5px; text-transform: uppercase;
                            text-align: center; padding: 3px 4px; border-bottom: 0; }
table.dfam th.band-them, table.dfam td.band-them { background: #f6f3fa; }
table.dfam th.band-us, table.dfam td.band-us { background: #eaf3ea; }
table.dfam .dfam-band th.band-them { color: var(--warhawk-purple); border-top: 2px solid var(--warhawk-purple); }
table.dfam .dfam-band th.band-us { color: #2e7d32; border-top: 2px solid #2e7d32; }
/* ---- stacked roster (ROSTER_LAYOUT = "stacked") ---- */
.pcard { border: 1px solid var(--edge); border-radius: 8px; margin: 0 0 10px; overflow: hidden;
         break-inside: avoid; page-break-inside: avoid; }
.pcard .ph { display: flex; align-items: center; gap: 10px; background: var(--warhawk-light);
             border-bottom: 2px solid var(--warhawk-purple); padding: 6px 10px; }
.pcard .ph img, .pcard .ph .photo-thumb { width: 42px; height: 42px; }
.pcard .ph-name { font-weight: 800; font-size: 0.95rem; }
.pcard .ph-bio { font-weight: 400; font-size: 0.72rem; color: var(--dim); }
.pcard .ph-foul { margin-left: auto; font-size: 0.72rem; font-weight: 700; white-space: nowrap; }
.pcard .ph-clutch { margin-left: 8px; color: #5c4a00; background: #fff3b0; border-radius: 9px;
  padding: 2px 8px; font-size: 0.68rem; }
.pc-chip.clutch { background: #fff3b0; color: #5c4a00; border: 1px solid #e3cf7a; }
.pcard table.pstats { width: 100%; margin: 4px 0 0; }
.pcard table.pstats th, .pcard table.pstats td { text-align: center; }
.pcard table.sz-row { width: 100%; border-collapse: collapse; table-layout: fixed; margin: 2px 0 0; }
.pcard table.sz-row td { border: 0; padding: 3px 10px; vertical-align: top; text-align: left; }
.pcard .sz-cap { font-size: 0.62rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.4px;
                 color: var(--warhawk-purple); padding-bottom: 0 !important; }
.pcard .sz-cap .mini { text-transform: none; letter-spacing: 0; font-weight: 400; }
.pcard .sz-l { font-size: 0.66rem; color: var(--dim); font-weight: 400; }
.pcard .sz-bar { height: 6px; background: #ece8f3; border-radius: 3px; overflow: hidden; margin: 2px 0; }
.pcard .sz-bar span { display: block; height: 100%; background: var(--warhawk-purple); }
.pcard .sz-v { font-size: 0.74rem; font-weight: 400; }
.pcard .p-reads { padding: 2px 10px 6px; font-size: 0.76rem; }
.teamrow { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 4px; }
/* ---- alternative offense layout #2 (_TEST): usage x efficiency quadrants ---- */
/* Flex, not CSS grid: the brief gets printed and PDF'd, and older print/WebKit engines silently collapse
   `display:grid` to a single stacked column -- which turns a 2x2 quadrant into a meaningless list. */
.quad { display: flex; flex-wrap: wrap; margin: 0 -4px; }
/* The UWW section carries five labelled lines per set; at half width those wrap into an unreadable
   column, so that section stacks its cells full width instead. */
.quad.quad-rich .quad-cell { width: 100%; }
.quad-cell { width: 50%; box-sizing: border-box; margin: 0 0 8px; padding: 7px 9px;
             border: 1px solid var(--edge); border-radius: 6px; border-top-width: 3px;
             break-inside: avoid; float: left; }
.quad-cell.q-good { border-top-color: #2e7d32; }
.quad-cell.q-up   { border-top-color: #1565c0; }
.quad-cell.q-bad  { border-top-color: #c62828; }
.quad-cell.q-dim  { border-top-color: #9e9e9e; }
.pc-flag { display: inline-block; font-size: 0.62rem; font-weight: 700; padding: 0 5px; border-radius: 8px; white-space: nowrap;
  line-height: 1.5; vertical-align: 1px; }
.pc-flag.q-bad { background: #fdecea; color: #c62828; } .pc-flag.q-up { background: #e3eefb; color: #1565c0; }
.pc-flag.q-good { background: #e8f5ec; color: #2e7d32; } .pc-flag.q-dim { background: #f0f0f0; color: #666; }
.quad-h { font-size: 0.8rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.4px;
          display: flex; align-items: baseline; }
.quad-n { margin-left: auto; font-size: 0.68rem; font-weight: 700; color: var(--dim); }
.quad-sub { font-size: 0.68rem; color: var(--dim); margin-bottom: 5px; }
.quad-row { border-top: 1px dotted var(--edge); padding: 3px 0 2px; }
.quad-row:first-of-type { border-top: 0; }
.quad-set { font-weight: 700; font-size: 0.8rem; }
.quad-num { float: right; font-size: 0.78rem; font-weight: 700; }
.quad-meta { font-size: 0.68rem; color: var(--dim); clear: both; line-height: 1.35; }
.quad-meta .qk { display: inline-block; min-width: 54px; font-weight: 700; color: var(--warhawk-purple);
                 text-transform: uppercase; font-size: 0.58rem; letter-spacing: 0.3px; }
.quad-cov { font-size: 0.68rem; color: var(--warhawk-purple); font-weight: 600; clear: both; }
.quad-empty, .quad-more { font-size: 0.7rem; color: var(--dim); font-style: italic; padding-top: 3px; }
/* ---- alternative offense layout (_TEST) ---- */
.ot-situ { display: flex; align-items: baseline; gap: 8px; margin: 10px 0 4px;
           border-bottom: 2px solid var(--warhawk-purple); padding-bottom: 2px; }
.ot-situ-name { font-size: 0.82rem; font-weight: 800; text-transform: uppercase;
                letter-spacing: 0.5px; color: var(--warhawk-purple); }
.ot-situ-n { font-size: 0.68rem; color: var(--dim); margin-left: auto; }
.ot-row { margin: 5px 0 7px; break-inside: avoid; }
.ot-head { display: flex; align-items: baseline; gap: 8px; }
.ot-name { font-weight: 700; font-size: 0.84rem; }
.ot-num { margin-left: auto; font-size: 0.78rem; font-weight: 700; white-space: nowrap; }
.ot-bar { height: 7px; background: #ece8f3; border-radius: 4px; overflow: hidden; margin: 2px 0 3px; }
.ot-fill { display: block; height: 100%; background: var(--warhawk-purple); }
.ot-fill.ot-good { background: #2e7d32; }
.ot-fill.ot-bad { background: #c62828; }
.ot-num.ot-good { color: #2e7d32; }
.ot-num.ot-bad { color: #c62828; }
.ot-detail { font-size: 0.78rem; padding-left: 2px; }
.ot-cov { font-size: 0.72rem; color: var(--dim); }
/* Horizontal team-stat strip: one narrow column per stat, running left to right across the full width.
   Columns are allowed to shrink but not wrap mid-stat, so the strip stays one scannable row. */
.hstat { display: flex; align-items: stretch; gap: 0; width: 100%; overflow: hidden; }
.hs-col { flex: 1 1 0; min-width: 0; text-align: center; padding: 3px 2px; border-left: 1px solid var(--edge); }
.hs-col:first-child { border-left: 0; }
.hs-key { flex: 0 0 auto; text-align: right; padding-right: 8px; color: var(--dim); font-weight: 700; }
.hs-l { font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.3px; color: var(--dim);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hs-v { font-size: 0.86rem; line-height: 1.5; white-space: nowrap; }
.hs-win { font-weight: 800; color: var(--warhawk-purple); }
.fnhold { float: right; }
.tchip { border: 1px solid var(--edge); border-radius: 12px; padding: 2px 10px; font-size: 0.8rem; font-weight: 600; }
.strip-line { font-size: 0.8rem; margin: 4px 0; }
.results .rs { border: 1px solid var(--edge); border-radius: 6px; padding: 2px 8px; font-size: 0.74rem; }
.results .rs b.w { color: var(--win); } .results .rs b.l { color: var(--loss); }
.dayg { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 8px; }
.dayg .day { border: 1px solid var(--edge); border-radius: 6px; padding: 6px 8px; font-size: 0.74rem; break-inside: avoid; }
.sample .dayg .day { border-color: #f6dada; background: #fff; }
.dayg .day .dh { font-weight: 800; color: var(--warhawk-purple); margin-bottom: 4px; }
.dayg .day .sg { margin: 2px 0; } .dayg .day .sg .tie { color: var(--dim); }
.cols .matchrow { flex-direction: column; }
@media print {
  body { font-size: 10pt; padding: 0; }
  .card, .sample { padding: 6px 10px; margin-bottom: 6px; }
  .sect { padding: 4px 10px; margin: 8px 0 4px; }
  .player { padding: 6px 10px; }
  a.applink, a.nmlink { color: var(--warhawk-purple); }
  @page { size: letter; margin: 0.45in; }
}
.pc-grid > div { flex: 1; min-width: 260px; }
.pc-sub { font-size: 0.72rem; font-weight: 800; letter-spacing: 0.6px; text-transform: uppercase;
          color: var(--warhawk-purple); margin: 10px 0 4px; }
td.ppp-good { color: #1b5e20; font-weight: 700; }
td.ppp-bad { color: #8c1d2c; font-weight: 700; }
.pc-raw { color: #888; font-size: 0.74rem; }
.photo-thumb { width: 34px; height: 34px; border-radius: 50%; object-fit: cover; display: block; }
.photo-thumb-blank { background: #e0dbea; border: 1px solid var(--edge); }
.bio { display: flex; align-items: center; gap: 10px; margin: 6px 0 8px; padding: 4px 6px; border-radius: 6px; }
.bio.sample-bio { background: #fff5f5; border: 1px solid #f6dada; }
.bio-text { font-size: 0.82rem; color: var(--dim); }
details.gloss summary { cursor: pointer; font-size: 0.8rem; color: var(--warhawk-purple); font-weight: 700; margin-top: 8px; }
details.gloss table { margin-top: 6px; }
.sect.sample-sect .t { color: #c62828; }
.legend { font-size: 0.8rem; color: var(--dim); margin: 0 0 0.75rem; display: flex; gap: 14px; flex-wrap: wrap; }
.legend .sw { display: inline-block; width: 12px; height: 12px; border-radius: 3px; vertical-align: -2px;
              margin-right: 5px; }
.legend .sw.real { border: 1px solid var(--edge); background: #fff; }
.legend .sw.fake { border: 2px solid #c62828; background: #fff5f5; }
.pill-thin { font-size: 0.62rem; font-weight: 700; letter-spacing: 0.3px; text-transform: uppercase;
             color: #8a6d3b; background: #fdf6e3; border-radius: 8px; padding: 1px 7px; margin-left: 6px;
             vertical-align: middle; }
.caution { background: #fdf6e3; border: 1px solid #f0dca8; }
.caution .row { font-size: 0.85rem; padding: 4px 0; border-bottom: 1px solid #f3e6c4; }
.caution .row:last-child { border-bottom: 0; }
.caution .area { font-weight: 700; color: #8a6d3b; margin-right: 6px; }
td.call-foul { color: #1b5e20; font-weight: 700; }
td.call-nofoul { color: #8c1d2c; font-weight: 700; }
tr.dayhead td { background: var(--warhawk-light); color: var(--warhawk-purple); font-weight: 800;
                font-size: 0.78rem; letter-spacing: 0.4px; text-transform: uppercase; }
.sample tr.dayhead td { background: #fde3e3; color: #8c1d2c; }
.foot { margin-top: 1.5rem; padding-top: 12px; border-top: 1px solid var(--edge);
        font-size: 0.75rem; color: var(--dim); }

@media screen and (max-width: 820px) {
  .cols { display: block; }
  .matchrow { display: block; }
  .matchrow > .match { margin-bottom: 8px; }
  .cols .col + .col .sect { margin-top: 1.5rem; }
}
@media screen and (max-width: 720px) {
  .banner { padding: 16px; }
  .banner .team { font-size: 1rem; }
  .banner .crest, .banner .crest img { height: 44px; max-height: 44px; }
  .five .g { min-width: 130px; }
}
@media print {
  /* CONFIRMED BUG (fixed here): the responsive rules above used to be plain (max-width: ...) queries, and a
     Letter page is narrower than 820px -- so in print every side-by-side layout collapsed to one column.
     This block also used to forbid ANY card or table from splitting across pages, which left half-empty
     pages wherever a tall section didn't fit. Only small, self-contained blocks are kept whole now. */
  body { padding: 0; font-size: 9.5pt; line-height: 1.35; }
  .banner, .divider, .sample, .sect, .chip, td.ppp-good, td.ppp-bad { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .player, .key, .match, .gcell, .dayg .day, tr, .ktvline { break-inside: avoid; }
  .sect { break-after: avoid; }
  .banner { padding: 10px 14px; }
  .banner .crest, .banner .crest img { height: 40px; max-height: 40px; }
  .card, .sample { padding: 6px 10px; margin-bottom: 6px; }
  .sect { padding: 3px 10px; margin: 6px 0 4px; }
  .player { padding: 6px 10px; margin-bottom: 6px; }
  .photo-thumb { width: 28px; height: 28px; }
  /* Starter cards: reads as wrapping inline chips, note/key text a size down, so five fit one page. */
  .flow2 .player .reads { display: flex; flex-wrap: wrap; gap: 0 10px; margin: 2px 0; }
  .flow2 .player .reads .dot { font-size: 7.5pt; }
  .flow2 .player .notes { font-size: 8pt; line-height: 1.3; margin: 2px 0; }
  .flow2 .player .kdline { font-size: 8pt; line-height: 1.3; }
  .flow2 .player .statline, .flow2 .player .bio-text { font-size: 7.5pt; }
  .flow2 .player .bio { margin: 2px 0 4px; padding: 2px 4px; }
  .flow2 .player .srcblock { margin-top: 4px; padding-left: 8px; }
  .flow2 .player .nm { font-size: 10pt; }
}

/* Full-width KTV sentences with reasoning (requested) */
.sechead { font-size: 0.9rem; line-height: 1.35; margin: 0 0 7px; padding: 0 2px; }
.sechead b { color: var(--warhawk-purple); }
/* ---- expand all ------------------------------------------------------------------------------- */
.xall { display: none; justify-content: flex-end; margin: 0 0 6px; }
.js .xall { display: flex; }
.xbtn { font-family: inherit; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.3px; cursor: pointer;
        color: var(--warhawk-purple); background: #fff; border: 1px solid #cfc4e2; border-radius: 12px;
        padding: 3px 12px; }
.xbtn:hover { background: var(--warhawk-light); }
@media print { .xall { display: none !important; } }
/* ---- the three lineup cards above the lineup tables -------------------------------------------- */
.lc-lab { font-size: 0.68rem; font-weight: 800; letter-spacing: 0.6px; text-transform: uppercase;
          color: var(--warhawk-purple); margin: 2px 0 4px; }
/* (11/22) a lineup label that follows the "Full roster" bar needs air above it; a label that opens a card does not */
details.rosdet { margin: 8px 0 12px; }
details.rosdet + .lc-lab, details.rosdet + .tier-h { margin-top: 22px; }
/* (11/22, "add that extra spacing other places") a label under cards, a note or a table needs the same air as one under a bar */
.lcards + .lc-lab, p.mini + .lc-lab, table + .lc-lab { margin-top: 20px; }
.lcards + .pc-sub, table + .pc-sub, details + .pc-sub, p.mini + .pc-sub { margin-top: 16px; }
.sechead + details.rosdet, .sechead + .card { margin-top: 10px; }
.lcards + details.rosdet, .lcards + details.ob-det, .card + details.ob-det { margin-top: 12px; }
.lc-lab + .lcards, .lc-lab + .ro-strip { margin-top: 4px; }
.lcards { display: flex; gap: 8px; align-items: stretch; margin: 0 0 10px; }
.lcards .lc { flex: 1 1 0; min-width: 0; border: 1px solid var(--edge); border-radius: 8px; padding: 8px 10px;
              break-inside: avoid; }
.lcards .lc-t { font-size: 0.62rem; font-weight: 800; letter-spacing: 0.5px; text-transform: uppercase;
                color: var(--dim); }
.lcards .lc-n { font-weight: 800; font-size: 0.82rem; line-height: 1.25; margin-top: 2px; }
.lcards .lc-v { font-size: 0.95rem; font-weight: 800; color: var(--warhawk-purple); margin-top: 3px;
                font-variant-numeric: tabular-nums; }
.lcards .lc-s { font-size: 0.68rem; color: var(--dim); font-variant-numeric: tabular-nums; margin-top: 1px; }
.lcards .lc-x { font-size: 0.7rem; color: #333; line-height: 1.35; margin-top: 6px; padding-top: 5px;
                border-top: 1px dotted var(--edge); }
.lcards .lc-x + .lc-x { margin-top: 4px; padding-top: 0; border-top: 0; }
.lcards .lc-x b { color: var(--warhawk-purple); }
@media screen and (max-width: 820px) { .lcards { flex-wrap: wrap; } .lcards .lc { flex: 1 1 45%; } }
.lcards.ktv-cards .lc { flex: 1 1 0; min-width: 0; }
.lcards.ktv-cards .lc-t { display: flex; align-items: center; gap: 6px; color: var(--dim); }
.lcards.ktv-cards .lc-t .ktv-right { margin-left: auto; display: flex; align-items: center; gap: 5px; }
.lcards.ktv-cards .lc-t > .src { margin-left: auto; }   /* a key with no score: the badge still sits right */
.lcards.ktv-cards .lc-t .src, .lcards.ktv-cards .lc-t .ktv-score, .lcards.ktv-cards .lc-t .lsn { text-transform: none;
  letter-spacing: 0; font-weight: 700; }
.lcards.ktv-cards .lc-n { font-size: 0.86rem; }
.lcards.ktv-cards .lc-n a { color: inherit; }
.lcards.ktv-cards .lc-t .ktv-n { font-size: 0.62rem; font-weight: 700; color: var(--dim); }
.lcards .lc.lc-empty .lc-n { color: var(--dim); font-weight: 600; font-size: 0.95rem; }
.photo-note { font-size: 0.56rem; line-height: 1.1; color: var(--dim); text-align: center; margin-top: 2px; max-width: 64px; overflow-wrap: anywhere; }
.lcards.ktv-cards .lc-x.ktv-more { border-top: 0; padding-top: 0; margin-top: 5px; font-weight: 700; font-size: 0.74rem; }
.lcards.ktv-cards .lc-x.ktv-more a { color: inherit; }
.lcards.ktv-cards .lc-x.mini { font-weight: 400; color: var(--dim); }
.lcards.ktv-cards .lc-s.ktv-why { font-variant-numeric: normal; line-height: 1.35; margin-top: 4px; }
/* CONFIRMED BUG (fixed 11/19: "All keys table is way too wide"). The page's own `td` rule is
   `white-space: nowrap`, which is right for a stat cell and wrong for a sentence: each key's reasoning sat on one
   unbroken line and pushed the table far past the 1000px page. The Key column wraps, and the four columns get fixed
   widths so the text column takes the room instead of the badges. */
table.ktv-tbl { table-layout: fixed; width: 100%; }
table.ktv-tbl th, table.ktv-tbl td { white-space: normal; overflow-wrap: anywhere; }
table.ktv-tbl th:nth-child(1), table.ktv-tbl td:nth-child(1) { width: 8%; }
table.ktv-tbl th:nth-child(2), table.ktv-tbl td:nth-child(2) { width: 46%; }
table.ktv-tbl th:nth-child(3), table.ktv-tbl td:nth-child(3) { width: 6%; }
table.ktv-tbl th:nth-child(4), table.ktv-tbl td:nth-child(4) { width: 28%; }
table.ktv-tbl th:nth-child(5), table.ktv-tbl td:nth-child(5) { width: 12%; }
table.ktv-tbl td { vertical-align: top; }
table.ktv-tbl tr.ktv-on td { background: #fffbe9; }
.pcs-r.ktv-on > summary { background: #fffbe9; }
table.ktv-tbl .mini { color: var(--dim); font-weight: 400; }
/* ---- the five starters across the top of a roster ---------------------------------------------- */
.sfive { display: flex; gap: 8px; align-items: stretch; margin: 0 0 8px; }
.sfive .sf { flex: 1 1 0; min-width: 0; border: 1px solid var(--edge); border-radius: 8px; padding: 8px;
             text-align: center; break-inside: avoid; }
.sfive .sf-ph .photo-thumb { width: 54px; height: 54px; margin: 0 auto 4px; }
.sfive .sf-nm { font-weight: 800; font-size: 0.86rem; line-height: 1.2; }
.sfive .sf-bio { font-size: 0.68rem; color: var(--dim); margin-top: 1px; }
.sfive .sf-st { font-size: 0.74rem; font-variant-numeric: tabular-nums; margin-top: 3px; }
.sfive .sf-role { font-size: 0.7rem; margin-top: 3px; text-align: left; line-height: 1.25; }
.sfive .sf-role .sf-k { display: inline-block; min-width: 2.2em; margin-right: 5px; font-size: 0.6rem;
                        font-weight: 800; letter-spacing: 0.4px; text-transform: uppercase;
                        color: var(--warhawk-purple); }
/* CONFIRMED BUG (fixed 11/18): "OFF" is wider than the 1.9em it was given at this size, so the label ran
   straight into the role -- "OFFStationary Shooter". The min-width now fits the longer of the two labels and
   a margin guarantees the gap whatever the font does. */
.sfive .sf-role strong { font-weight: 700; }
.sfive .sf-say { font-size: 0.7rem; color: #333; text-align: left; margin-top: 5px; padding-top: 4px;
                 border-top: 1px dotted var(--edge); line-height: 1.3; }
.sfive .sf-foul { margin-top: 6px; }
.sfive .sf-foul .pc-foul { font-size: 0.66rem; }
table.compact tr.rsub td { background: #f6f4ef; font-weight: 700; font-size: 0.72rem; text-align: left; padding-top: 5px; }
.lc .lc-split { margin-top: 4px; border-top: 1px dotted #e3e0d8; padding-top: 4px; }
.sfive .sf-clutch { margin-top: 5px; }
.sfive .sf-clutch .pc-chip { font-size: 0.62rem; white-space: normal; line-height: 1.25; }
details.rosdet > summary { cursor: pointer; list-style: none; display: flex; align-items: baseline; gap: 8px;
                           border: 1px solid var(--edge); border-radius: 6px; padding: 5px 10px;
                           background: #fafafa; }
details.rosdet > summary::-webkit-details-marker { display: none; }
details.rosdet > summary .rd-open { font-weight: 800; font-size: 0.8rem; color: var(--warhawk-purple); }
details.rosdet > summary .rd-open::before { content: ""; display: inline-block; width: 0; height: 0;
    margin-right: 7px; border-left: 6px solid var(--warhawk-purple);
    border-top: 4px solid transparent; border-bottom: 4px solid transparent; transition: transform 0.12s; }
details.rosdet[open] > summary .rd-open::before { transform: rotate(90deg); }
details.rosdet > summary .rd-sub { font-size: 0.72rem; color: var(--dim); }
details.rosdet > summary:hover { background: var(--warhawk-light); }
details.rosdet[open] > summary { margin-bottom: 8px; }
@media screen and (max-width: 820px) { .sfive { flex-wrap: wrap; } .sfive .sf { flex: 1 1 45%; } }
/* ---- collapsible sections: the header bar IS the summary --------------------------------------- */
details.secdet { margin: 0; }
details.secdet > summary { list-style: none; cursor: pointer; }
details.secdet > summary::-webkit-details-marker { display: none; }
details.secdet > summary .sect { display: flex; align-items: center; gap: 10px; }
details.secdet > summary .sect .t { flex: 1; }
details.secdet > summary .sect::after { content: ""; flex: none; width: 0; height: 0;
    border-left: 8px solid var(--warhawk-purple);
    border-top: 6px solid transparent; border-bottom: 6px solid transparent; transition: transform 0.12s; }
details.secdet[open] > summary .sect::after { transform: rotate(90deg); }
details.secdet > summary:hover .sect { background: var(--warhawk-light); }
details.secdet:not([open]) > summary .sect { border-style: dashed; }
/* ---- FOUR FACTORS (the one-page digest under the keys) ---------------------------------------- */
/* its header bar is the verdict, so that one reads as a sentence rather than a section title */
.lcards.wm-cards .lc-n { font-size: 0.9rem; line-height: 1.25; }
.lcards.wm-cards .lc-v { font-size: 1.05rem; }
.wm-verdict { font-size: 0.95rem; font-weight: 600; line-height: 1.35; margin: 0 0 8px; }
.wm-verdict b { color: var(--warhawk-purple); }
table.wm-ff { margin: 2px 0 10px; font-size: 0.82rem; }
table.wm-ff th { text-align: right; } table.wm-ff th:first-child, table.wm-ff td:first-child { text-align: left; }
table.wm-ff td { text-align: right; }
table.wm-ff td.wm-say { text-align: left; color: #333; font-size: 0.78rem; }
table.wm-ff td.wm-net { font-weight: 800; white-space: nowrap; }
table.wm-ff .wm-real { text-align: right; color: #555; font-size: 0.76rem; white-space: nowrap; }
table.wm-ff td.wm-us { color: #2e7d32; } table.wm-ff td.wm-them { color: #c62828; }
table.wm-ff tr.wm-top td { background: #faf7ff; }
.ktv-sentence { 
    display: flex; align-items: flex-start; gap: 8px; margin-bottom: 10px; font-size: 0.9rem; line-height: 1.4;
}
.ktv-sentence .n { 
    font-weight: 700; color: var(--warhawk-purple); flex-shrink: 0; min-width: 20px;
}
.ktv-sentence .src {
    margin-left: auto; flex-shrink: 0;
}
.ktv-sentence .ktv-right { margin-left: auto; flex-shrink: 0; display: flex; align-items: center; gap: 6px; }
.ktv-sentence .ktv-right .src { margin-left: 0; }
.ktv-sentence .ktv-score { font-size: 0.7rem; color: var(--warhawk-purple); border: 1px solid #cfc4e2; border-radius: 9px;
                           padding: 0 6px; white-space: nowrap; }
.ktv-sentence .ktv-score::after { content: " / 100"; color: #999; font-size: 0.62rem; }
.ktv-sentence .lsn { font-size: 0.7rem; font-weight: 700; color: #fff; background: #8a6d1f; border-radius: 4px;
  padding: 1px 6px; letter-spacing: 0.3px; }
/* last season's seniors before a between-seasons scrimmage */
s { opacity: 0.55; }
.pcard.gone { opacity: 0.55; }
.pcard.gone, .pcard.gone * { text-decoration: line-through; }
.strike-note { font-size: 0.85rem; color: #555; margin: 0 0 10px; }
/* no-seniors brief: a player moved into the starting five in place of a graduated senior starter */
.proj-start { display: inline-block; margin-top: 2px; padding: 0 5px; border-radius: 3px; background: #fff3cd;
              color: #7a5200; border: 1px solid #e0b84a; font-size: 0.66rem; font-weight: 700; white-space: nowrap; }
"""


def _sb_headshot_b64(name):
    """A player's headshot from data/player_images as base64, or "" -- the same folder and filename variants
    the app's _get_player_img_b64() uses. This is the fallback when the FastScout roster page's own photo URL
    isn't available for a player (no live scrape yet for that team, or the scrape found no photo for him),
    which is why our own players showed no picture while the opponent's did: opponent headshots also get
    extracted from scouting-report PDFs into this folder, and UWW's don't come from a report at all.
    Embedded rather than linked so the brief stays a single self-contained file, like the crests."""
    import base64 as _sb_b64
    img_dir = os.path.join(APP_DATA_DIR, "player_images")
    if not name or not os.path.isdir(img_dir):
        return ""
    raw = re.sub(r"\s+", " ", str(name)).strip()
    variants = {raw, re.sub(r"[^\w\s\-]", "", raw).strip()}
    for stem in variants:
        for ext in ("png", "jpeg", "jpg"):
            path = os.path.join(img_dir, f"{stem}.{ext}")
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    return _sb_b64.b64encode(f.read()).decode()
    # Last resort: case-insensitive match on the directory listing.
    lower = {f.lower(): f for f in os.listdir(img_dir)}
    for stem in variants:
        for ext in ("png", "jpeg", "jpg"):
            hit = lower.get(f"{stem}.{ext}".lower())
            if hit:
                with open(os.path.join(img_dir, hit), "rb") as f:
                    return _sb_b64.b64encode(f.read()).decode()
    return ""


def _sb_logo_b64(*candidates):
    """Team logo as base64, using the same lookup the app's find_logo_b64() uses.

    The banner is the most recognisable thing on the Upcoming Game page and the crests are most of
    why -- a brief with empty squares where the app has logos reads as a different document. Same
    data/logo directory, same exact/prefix/reverse-prefix order, so a team that has a crest in the
    app has one here.
    """
    import base64 as _sb_b64
    logo_dir = os.path.join(APP_DATA_DIR, "logo")
    if not os.path.isdir(logo_dir):
        return ""
    stems = sorted((os.path.splitext(f)[0] for f in os.listdir(logo_dir) if f.lower().endswith(".png")),
                   key=len, reverse=True)

    def _read(stem):
        with open(os.path.join(logo_dir, f"{stem}.png"), "rb") as f:
            return _sb_b64.b64encode(f.read()).decode()

    for name in candidates:
        if not name or (isinstance(name, float) and pd.isna(name)):
            continue
        name = str(name).strip()
        if not name:
            continue
        if os.path.exists(os.path.join(logo_dir, f"{name}.png")):
            return _read(name)
        for stem in stems:
            if name.startswith(stem) and len(stem) >= 3:
                return _read(stem)
        for stem in stems:
            if stem.startswith(name) and len(name) >= 3:
                return _read(stem)
    return ""


def _sb_record_and_streak(games):
    """Win-loss record and current streak from a set of completed games, newest last."""
    if games.empty or "outcome" not in games.columns:
        return "", ""
    played = games[games["outcome"].astype(str).str.upper().isin(["W", "L"])]
    if played.empty:
        return "", ""
    wins = int((played["outcome"].astype(str).str.upper() == "W").sum())
    losses = int((played["outcome"].astype(str).str.upper() == "L").sum())
    count, kind = 0, ""
    for outcome in played["outcome"].astype(str).str.upper().iloc[::-1]:
        if count == 0:
            kind, count = outcome, 1
        elif outcome == kind:
            count += 1
        else:
            break
    streak = f"{count}-game {'win' if kind == 'W' else 'loss'} streak" if count else ""
    return f"{wins}-{losses}", streak


def _sb_strip_mascot(name):
    """"Aurora Spartans" -> "Aurora", the way the banner shows it.

    The app has a full known-mascot list for this; a brief only needs the banner line, so this
    trims the trailing mascot word conservatively and leaves anything it isn't sure about alone
    rather than mangling a real team name.
    """
    text = str(name or "").strip()
    if not text or text.endswith(")"):
        return text
    words = text.split()
    # CONFIRMED BUG (fixed here): a since-removed branch collapsed any 3+-word "UW-..." name down to just
    # its first word, on the assumption a UW campus name is always one word. It isn't -- "UW-Stevens Point
    # Pointers" has a two-word campus name ("Stevens Point"), so that branch dropped BOTH "Point" and the
    # real mascot "Pointers", leaving "UW-Stevens" on every banner and section header. Stripping only the
    # trailing word works correctly for every UW campus regardless of how many words its name has --
    # "UW-Eau Claire Blugolds" -> "UW-Eau Claire", "UW-Whitewater Warhawks" -> "UW-Whitewater", etc.
    # CONFIRMED BUG (fixed; the Ripon brief said "RIPON RED"): a two-word mascot ("Red Hawks") lost only its last word.
    if len(words) >= 3 and " ".join(words[-2:]).lower() in _SB_TWO_WORD_MASCOTS:
        return " ".join(words[:-2])
    if len(words) >= 2 and words[-1][:1].isupper():
        return " ".join(words[:-1])
    return text


_SB_TWO_WORD_MASCOTS = {
    "red hawks", "red devils", "blue devils", "blue jays", "golden eagles", "golden bears", "golden gophers",
    "fighting hawks", "fighting scots", "purple eagles", "purple aces", "big red", "sea gulls", "red raiders",
    "red storm", "blue hose", "blue hawks", "black bears", "golden knights", "golden flashes", "golden griffins",
    "green knights", "fighting saints", "red foxes", "great danes", "blue streaks", "scarlet knights", "red wolves",
    "nittany lions", "tar heels", "sun devils", "golden hurricane", "mountain hawks", "river hawks", "storm petrels",
    "flying dutchmen", "tommies", "running rebels", "yellow jackets", "war hawks", "fighting irish", "ice dogs",
}


# Filled in by _sb_build_html so the run can report which players ended up with no headshot -- a silent
# blank circle is how our own players' pictures went missing without anyone noticing.
_sb_photo_report = {}

# Filled in by _sb_build_html with the methodology notes, in the order they were registered. The brief only
# prints the ⓘ markers now (they deep-link into the app), so this is what the app reads to show the text --
# and the numbering here is what those markers point at, so it has to stay in registration order.
_sb_notes_report = []


def _sb_film_status():
    """How the automatic film work stands -> (summary dict, metric rows). CONFIRMED CHANGE (requested: the
    METHODOLOGY section explains how film is watched, players and plays are tagged, how many games and reviews
    went in, and how well the models are performing). Also written to uww_film_ai_status.csv for the app."""
    g_ = globals()
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "--"
    info, rows = {}, []
    # --- data so far
    cf = g_.get("clip_frames")
    if isinstance(cf, pd.DataFrame) and not cf.empty:
        info["games_captured"] = int(cf.get("source_url", pd.Series(dtype=str)).nunique())
        info["clips_captured"] = len(cf)
    pc = g_.get("play_calls")
    if isinstance(pc, pd.DataFrame) and not pc.empty:
        info["games_tagged"] = int(pc.groupby(["game_date", "game_code"]).ngroups) if {"game_date", "game_code"} <= set(pc.columns) else None
        info["clips_tagged"] = len(pc)
        if "track_files" in pc.columns:
            _t = pc[pc["track_files"].notna()]
            info["games_tracked"] = int(_t.groupby(["game_date", "game_code"]).ngroups) if len(_t) else 0
            info["clips_tracked"] = len(_t)
            info["frames_tracked"] = int(_t["track_files"].astype(str).str.count(";").add(1).sum()) if len(_t) else 0
    try:
        _checks = coach_checks_all()[0] if "coach_checks_all" in g_ else []
    except Exception:
        _checks = []
    info["player_checks"] = len(_checks)
    info["plays_checked"] = len({c.get("clip_key") for c in _checks})
    try:
        if "title_review_answers" in g_:
            title_review_answers()
        _marks = g_.get("_title_review_marks") or {}
    except Exception:
        _marks = {}
    info["title_answers"] = len(_marks)
    info["plays_title_reviewed"] = len({ck for ck, _f in _marks})
    if isinstance(pc, pd.DataFrame) and "tag_validation" in pc.columns:
        info["validation_plays"] = int(pc["tag_validation"].fillna(False).astype(bool).sum())

    # --- how well it's working = how often the film's automatic answer AGREED WITH THE COACHES' CHECK
    # CONFIRMED CHANGE (requested: "a comparison of how accurate the automatic film creation did against the coach
    # checks"). Every row is something a coach checked; coverage numbers (players named from evidence, frames on the
    # court) moved to the "So far" line -- they say how much the film covers, not whether it's right.
    sl = g_.get("trk_lineup_slots")
    if isinstance(sl, pd.DataFrame) and not sl.empty and "how" in sl.columns:
        info["players_from_evidence"] = int(sl["how"].map(
            lambda h: any(x not in ("best guess", "not located") for x in str(h).split(";"))).sum())
        info["player_slots"] = len(sl)
    cr = g_.get("court_report")
    if isinstance(cr, pd.DataFrame) and not cr.empty and "mapped_pct" in cr.columns:
        _c = cr[cr.get("calibrated", True) == True]
        if len(_c):
            info["court_mapped_pct"] = round(float(_c["mapped_pct"].mean()))
    agree = lambda r_, n_: f"{r_} of {n_} ({pct(r_, n_)})"
    if _checks:
        _n_real = sum(1 for c in _checks if c.get("verdict") != "not a player")
        rows.append(("Players", "Real player (not a referee, coach or fan)", agree(_n_real, len(_checks)),
                     "every box a coach checked"))
        _side = [c for c in _checks if c.get("verdict") != "not a player"]
        if _side:
            rows.append(("Players", "Right team", agree(sum(1 for c in _side if c.get("verdict") != "wrong team"), len(_side)),
                         "boxes that were players; 'wrong team' counts against"))
        _named = [c for c in _checks if c.get("assigned")]

        def _misses(cs):
            """Which wrong answers the coaches gave, e.g. '2 really someone else, 1 wrong team'."""
            lab = {"wrong": "really someone else", "wrong team": "wrong team", "not a player": "not a player"}
            n_ = {}
            for c in cs:
                v = c.get("verdict")
                if v != "correct":
                    n_[lab.get(v, str(v))] = n_.get(lab.get(v, str(v)), 0) + 1
            return ", ".join(f"{v_} {k_}" for k_, v_ in sorted(n_.items(), key=lambda x: -x[1]))

        if _named:
            _r = sum(1 for c in _named if c.get("verdict") == "correct")
            _m = _misses(_named)
            rows.append(("Players", "Right name -- all names the film gave",
                         agree(_r, len(_named)) + (f" -- {_m}" if _m else ""), "named boxes a coach checked"))
            by = {}
            for c in _named:
                by.setdefault(c.get("assigned_how") or "other", []).append(c)
            for h, cs in sorted(by.items(), key=lambda x: -len(x[1])):
                _r = sum(1 for c in cs if c.get("verdict") == "correct")
                _m = _misses(cs)
                rows.append(("Players", f"Right name -- named by {h}", agree(_r, len(cs)) + (f" -- {_m}" if _m else ""), ""))
    sc = (g_.get("JERSEY_READER_COACH_SCORE") or {})
    best = g_.get("JERSEY_READER_BEST")
    for eng, (r_, w_, n_) in sc.items():
        if eng == best or eng == "trained":
            rows.append(("Jersey numbers", f"Number read by the '{eng}' reader"
                         + (" (in use)" if eng == best else " (not reliable enough to use yet)"),
                         f"{agree(r_, r_ + w_)} of its answers; no answer on {n_ - r_ - w_} of {n_}",
                         "coach-checked players it never trained on"))
    # automatic Title: one row per field, every kind of coach check side by side
    tv = g_.get("tag_model_validation")
    tr = g_.get("tag_model_report")
    rep = {}
    for (_ck, f), a_ in _marks.items():
        # untouched prefilled "wrong" answers just repeat the coach-Title comparison -- not counted as reviews
        if a_.get("verdict") in ("right", "wrong") and not a_.get("prefilled"):
            rep.setdefault(f, [0, 0])
            rep[f][1] += 1
            rep[f][0] += int(a_["verdict"] == "right")
    for f in ["situation", "formation", "play_call", "primary_action", "defense", "press", "ball_screen_coverage",
              "offball_coverage", "screener", "screen_defender"]:
        parts_ = []
        if f in rep:
            parts_.append(f"coach reviews {agree(*rep[f])}")
        if isinstance(tv, pd.DataFrame) and not tv.empty and "field" in tv.columns and (tv["field"] == f).any():
            r = tv[tv["field"] == f].iloc[0]
            parts_.append(f"coach Titles, validation plays {agree(int(r['right']), int(r['validation_plays']))}")
        if isinstance(tr, pd.DataFrame) and not tr.empty and "accuracy_pct" in tr.columns and (tr["field"] == f).any():
            r = tr[tr["field"] == f].iloc[0]
            if pd.notna(r.get("accuracy_pct")) and pd.notna(r.get("clips_scored")):
                parts_.append(f"coach Titles, held-out plays {r['accuracy_pct']:.0f}% of {int(r['clips_scored'])}"
                              + (f" (always guessing the usual answer: {r['baseline_pct']:.0f}%)"
                                 if pd.notna(r.get("baseline_pct")) else ""))
        if parts_:
            rows.append(("Automatic Title", f.replace("_", " ").capitalize(), "\n".join(parts_),
                         "plays the model never trained on, or coaches' right/wrong marks"))
    return info, rows


def _sb_pd_key(x):
    """the app's play-diagram file key (streamlit_app._pd_key) -- keep the two the same"""
    k = re.sub(r"\([^)]*\)", " ", str(x).lower())
    k = re.sub(r"\b(?:option|opt)\b\.?", " ", k)
    return re.sub(r"[^a-z0-9#]+", "", k).replace("#", "n") or "x"


def _sb_play_diagrams(team, _names, pc_rows):
    """<details> with every uploaded diagram of this team's play calls (most possessions first), or "" when none."""
    d = os.path.join(APP_DATA_DIR, "play_diagrams")
    if not os.path.isdir(d):
        return ""
    tk = _sb_pd_key(team)
    best = {}
    for n in sorted(os.listdir(d)):
        parts = n.rsplit(".", 1)[0].split("__")
        if len(parts) >= 3 and parts[0] == tk:
            best[parts[1]] = os.path.join(d, n)
    if not best:
        return ""
    # the team's play calls, most possessions first (all formations together)
    order = []
    if pc_rows is not None and len(pc_rows):
        _n = pd.to_numeric(pc_rows["possessions"], errors="coerce").fillna(0)
        order = list(_n.groupby(pc_rows["label"].astype(str)).sum().sort_values(ascending=False).index)
    names = {_sb_pd_key(x): x for x in order}
    keys = [k for k in (_sb_pd_key(x) for x in order) if k in best] + [k for k in best if k not in names]
    import base64
    cards = []
    for k in keys:
        try:
            from PIL import Image as _PdI
            import io as _pdio
            im = _PdI.open(best[k])
            im = im.convert("RGB")
            if im.width > 1100:
                im = im.resize((1100, int(im.height * 1100 / im.width)))
            buf = _pdio.BytesIO()
            im.save(buf, "JPEG", quality=82)
            src = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception:
            continue
        cards.append(f'<div class="pd-card"><div class="pd-t">{_sb_esc(names.get(k, k))}</div><img src="{src}" alt=""></div>')
    if not cards:
        return ""
    return ('<details class="ob-det"><summary>Play diagrams (' + str(len(cards)) + ')</summary><div class="pd-grid">'
            + "".join(cards) + "</div></details>")


def _sb_build_html(_sb_d, game, scheduled_name, short):
    parts = []
    # Output goes to whichever list is on top of _sinks, so a block can be rendered into a side-by-side
    # column (see capture()) with the exact same code that renders it full width.
    _sinks = [parts]

    # CONFIRMED CHANGE (requested: parser_analysis -- "the same as the scouting briefs, but not including any of the
    # UW-Whitewater information"). ANALYSIS_MODE: the banner and the matchup sections before the opponent's part are left out
    # (except the late-game foul list), the opponent's part is kept minus the sections about playing them, and everything
    # from the UW-WHITEWATER divider to the footer is left out.
    _an = {"on": bool(globals().get("ANALYSIS_MODE")), "pre": True, "skip": bool(globals().get("ANALYSIS_MODE")), "ours": False}
    _AN_DROP = re.compile(r"KEYS TO VICTORY|TEAM COMPARISON|FOUR FACTORS|WHEN WE'VE PLAYED|WHAT TO PLAY|TWO-FOR-ONE|NEEDS TAGGING|SELF-SCOUT|WHITEWATER|"
                          r"\bOUR\b|\bVS\.? UW", re.I)

    def add(html_text):
        if _an["on"] and (_an["skip"] or _an["ours"]):
            return
        _sinks[-1].append(html_text)

    def capture(fn, *args, **kwargs):
        _sinks.append([])
        try:
            fn(*args, **kwargs)
        finally:
            out = _sinks.pop()
        return out

    # ---- links into the app (#7) -------------------------------------------------------------------
    # CONFIRMED CHANGE (requested): the brief is condensed, and every place detail was cut links into the
    # app instead. Links carry query parameters the app reads on load (see handle_brief_deeplink in
    # streamlit_app.py): page, tab, and optionally key / player+team / set / section. The hosted URL comes
    # from APP_BASE_URL (set it in the config cell) or the UWW_APP_URL environment variable; with neither,
    # links degrade to plain "(in the app: ...)" text rather than pointing nowhere.
    from urllib.parse import urlencode as _sb_urlencode

    def _sb_normalize_app_url(raw):
        """Force an absolute https:// URL, or nothing.

        A bare host ("uwwmensbball-new.streamlit.app") in an href is a RELATIVE url: the browser resolves
        it against wherever the brief happens to sit, so a link opens
        file:///C:/.../scouting_briefs/uwwmensbball-new.streamlit.app/?page=... instead of the app. The
        brief is emailed around and opened from disk, so this fails silently for every reader. Normalizing
        happens HERE, at the point of use, rather than only in the config cell -- app_href re-reads the raw
        global/env value, so a fix applied only at config time is bypassed whenever the value arrives by
        another route (env var, a re-run config cell, an edit made after this cell ran).
        """
        u = str(raw or "").strip().strip('"\'').rstrip("/")
        if not u:
            return ""
        # Typos that would otherwise sail through as "has no scheme": https//host, https:/host, http:host.
        u = re.sub(r"^(https?)(?::/{0,2}|/{1,2})", r"\1://", u, flags=re.I)
        if not re.match(r"^https?://", u, flags=re.I):
            u = "https://" + u
        return u.rstrip("/")

    _app_url = _sb_normalize_app_url(globals().get("APP_BASE_URL") or os.environ.get("UWW_APP_URL"))

    # Every app link opens in a NEW TAB (requested). rel="noopener" goes with target="_blank" as a matter
    # of course: without it the opened page gets a handle on the opener via window.opener, and "noreferrer"
    # keeps the local file:// path of the brief out of the referrer header when it is opened from disk.
    _SB_NEWTAB = ' target="_blank" rel="noopener noreferrer"'

    def app_href(**params):
        q = _sb_urlencode({k: v for k, v in params.items() if v not in (None, "")})
        return f"{_app_url}/?{q}" if _app_url else ""

    def app_link(label, **params):
        href = app_href(**params)
        if href:
            return f'<a class="applink" href="{_sb_esc(href)}"{_SB_NEWTAB}>{_sb_esc(label)} &rarr;</a>'
        return f'<span class="applink off">{_sb_esc(label)} (in the app)</span>'

    def name_link(text, **params):
        href = app_href(**params)
        return f'<a class="nmlink" href="{_sb_esc(href)}"{_SB_NEWTAB}>{_sb_esc(text)}</a>' if href else _sb_esc(text)

    def _name_two_lines(name):
        """First name, line break, last name -- for the compact roster table, where the name column has to
        stay narrow. Splits on the first space only, so a suffix or two-word last name ("Agape Keyes Jr.")
        stays together on the second line."""
        first, sep, rest = str(name).partition(" ")
        return f"{_sb_esc(first)}<br>{_sb_esc(rest)}" if sep else _sb_esc(name)

    def name_link_lines(name, **params):
        href = app_href(**params)
        label = _name_two_lines(name)
        return f'<a class="nmlink" href="{_sb_esc(href)}"{_SB_NEWTAB}>{label}</a>' if href else label

    # ---- footnotes (#6) ----------------------------------------------------------------------------
    # Long methodology paragraphs used to sit under each table, then on a Notes page at the end of the
    # brief. They live in the APP now (requested) -- the brief keeps only the small numbered ⓘ at each
    # section title, hyperlinked to that note in the app, so the explanation is one tap away without
    # spending brief pages on it. Still collected here because the numbering has to match what the app
    # prints, and because the export below is what the app reads.
    footnotes = []

    def footnote(text):
        text = _sb_clean(text)
        if not text:
            return ""
        footnotes.append(text)
        _n = len(footnotes)
        _href = app_href(page="upcoming", tab="notes", note=_n)
        if not _href:
            # No app URL configured -- a numbered marker pointing at a page the reader can't reach (and
            # that isn't printed here any more) is worse than no marker at all.
            return ""
        return (f' <sup class="fn"><a class="fnlink" href="{_sb_esc(_href)}"{_SB_NEWTAB} '
                f'title="Why this number is what it is \u2014 opens the app">\u24d8{_n}</a></sup>')

    def page_break():
        add('<div class="pb"></div>')

    def divider(title, sub=""):
        if _an["on"]:
            if "WHITEWATER" in str(title).upper():
                _an["ours"] = True                    # our own part of the brief: left out to the footer
                return
            if _an["pre"] and "opponent" in str(sub).lower():
                _an["pre"], _an["skip"] = False, False
                title, sub = f"TEAM ANALYSIS: {title}", (f"{globals().get('SEASON_NOW') or ''} -- every game before "
                                                         f"{globals().get('REFERENCE_DATE') or 'today'}")
        # CONFIRMED CHANGE (requested 11/22): "Remove the 'Scouting the opponent' text from Hope header." The sub-line is
        # still passed in (ANALYSIS_MODE above matches on it) but is not drawn on the normal brief.
        if sub in ("Scouting the opponent", "Our own personnel, offense and week"):
            sub = ""
        add(f'<div class="divider"><div class="dt">{title}</div>'
            + (f'<div class="ds">{sub}</div>' if sub else "") + "</div>")

    _bt_box = {"bt": None}                 # the brief's type (set after the records below)

    def _staff_keys_this_season():
        """CONFIRMED CHANGE (Carroll's 2026-27 report): the staff's written keys come from the UPCOMING game's report
        when there is one (uww_opponent_game_plans' report_date is after the season our numbers are from) -- then
        they are this season's and get no last-season tag."""
        try:
            gp_ = _sb_d("uww_opponent_game_plans")
            if gp_.empty or "report_date" not in gp_.columns:
                return False
            d_ = pd.to_datetime(gp_[gp_["opponent"].astype(str) == str(short)]["report_date"], errors="coerce").dropna()
            m_ = re.match(r"(\d{4})", str((_bt_box["bt"] or {}).get("season") or ""))
            return bool(len(d_) and m_ and d_.max() >= pd.Timestamp(int(m_.group(1)) + 1, 8, 1))
        except Exception:
            return False

    def section_html(title):
        # (preseason / season-opener brief: every section built on last season's numbers says so)
        _b = _bt_box["bt"]
        # (KEYS TO VICTORY: the season goes on the staff's own keys, next to their "Keys to Victory" tag -- requested)
        if _b and _b["last_season"] and not re.search(r"ROSTER|NEEDS TAGGING|METHODOLOGY|CAUTION|WHEN WE'VE PLAYED|"
                                                       r"KEYS TO VICTORY", str(title), re.I):
            title = f'{title} <span class="lsn">{_sb_esc(_b["season"])}</span>'
        return f'<div class="sect"><div class="t">{title}</div></div>'

    # CONFIRMED CHANGE (requested 11/18): "Do the same with all other sections as well" -- the treatment the
    # Four Factors, roster and recent-results sections got. A section that emits a headline straight after its
    # header keeps the header AND the headline on the page and puts everything else behind one expander; it is
    # never wrapped in a section expander of its own, so the line a coach needs cannot be collapsed away.
    # Each headline is computed from the very data its own section is about to render, so the two cannot
    # disagree, and it prints nothing at all when that data is missing.
    def _sb_sechead(html):
        if _sb_clean(html):
            add(f'<div class="sechead">{html}</div>')

    def _lu_short(lineup, n=5):
        """"Aidyn Boone, Dominic Trelenberg, ..." -> "Boone / Trelenberg / ..." -- five full names do not fit
        on a headline and the surnames are what a coach says out loud."""
        _p = [x.strip() for x in str(lineup or "").split(",") if x.strip()][:n]
        return " / ".join(x.split()[-1] for x in _p)

    def _sb_pc_top(side_val):
        """Their (or our) most-used tagged set: the same uww_play_call_summary rows the section's own tables
        are built from."""
        # CONFIRMED BUG (fixed 11/18; Corey: "something doesn't seem correct with the headlines"). This read
        # uww_play_call_summary directly, and `side` names the FILE a clip came from, not whose possession it
        # was -- the Opponent file carries our own offensive possessions from that game, as possession_side
        # "Defense". So "HOW ELMHURST RUNS OFFENSE" was headlined "Most-used set: Motion -- 14 tagged, 0.43
        # points each", which is OUR Motion run against them (hence the key "Feature our best look: Motion").
        # Their own most-used set is Flow, 7 tagged at 1.43 -- exactly what the key "Take away their go-to
        # set: Flow" says. It now goes through _offense_rows(), the same filter the section's own tables use,
        # and drops the "unspecified" bucket the same way they do.
        _d = _offense_rows(side_val)
        if _d.empty or not {"level", "name", "uses"} <= set(_d.columns):
            return ""
        _d = _d[(_d["level"].astype(str) == "Play call")
                & ~_d["name"].astype(str).str.contains("unspecified", na=False)]
        _d = _d.assign(_u=pd.to_numeric(_d["uses"], errors="coerce")).dropna(subset=["_u"])
        if _d.empty or not _d["_u"].max():
            return ""
        _r = _d.loc[_d["_u"].idxmax()]
        _ppp = pd.to_numeric(pd.Series([_r.get("ppp")]), errors="coerce").iloc[0]
        # (requested 11/18) no possession counts in the brief's visible text -- the set is named and what it
        # produced is given; how many clips it rests on is in the section's own table underneath
        return (f'Most-used set: <b>{_sb_esc(_r["name"])}</b>'
                + (f' \u2014 {_ppp:.2f} points a possession' if pd.notna(_ppp) else ""))

    def section(title, bare=False):
        if _an["on"] and not _an["ours"]:
            _an["skip"] = (not re.search(r"LATE-GAME FOUL", str(title), re.I)) if _an["pre"] else bool(_AN_DROP.search(str(title)))
        if not bare:         # bare = no header bar (requested 11/22: recent results + starters sit straight under the team divider)
            add(section_html(title))

    # ---- banner (same markup and values as render_upcoming_game) ---------------------------
    sched = _sb_d("uww_schedule")
    uww_games = sched[sched["team"].astype(str).str.contains("Whitewater", case=False, na=False)] \
        if not sched.empty else pd.DataFrame()
    uww_before = uww_games.loc[:game.name].iloc[:-1] if not uww_games.empty else pd.DataFrame()
    uww_record, uww_streak = _sb_record_and_streak(uww_before)

    opp_sched = _sb_d("uww_opponent_schedules")
    opp_before = pd.DataFrame()
    if not opp_sched.empty and "opponent" in opp_sched.columns:
        opp_before = opp_sched[opp_sched["opponent"].astype(str).str.strip() == str(short).strip()]
    opp_record, opp_streak = _sb_record_and_streak(opp_before)
    _n_played = lambda d: int(d["outcome"].astype(str).str.upper().isin(["W", "L"]).sum()) \
        if isinstance(d, pd.DataFrame) and not d.empty and "outcome" in d.columns else 0
    _bt = brief_type_for(game, _n_played(uww_before), _n_played(opp_before), globals().get("BRIEF_TYPE", "auto"))
    # (requested) scrimmage / season-opener briefs list the whole bench, every tier
    _sb_full_bench = bool(globals().get("BRIEF_FULL_BENCH_OPENER", True)) and (
        _bt["type"] == "preseason" or (_bt["type"] == "first_games" and _bt["last_season"]))
    _bt_box["bt"] = _bt
    print(f"  Brief type: {_bt['type']}" + (f" -- {_bt['title']}" if _bt["title"] else ""), flush=True)
    if last_season_record_label(game):                 # the season opener: these are LAST season's records
        uww_record, uww_streak = last_season_text(uww_record, uww_streak)
        opp_record, opp_streak = last_season_text(opp_record, opp_streak)

    opp_display = _sb_strip_mascot(short)
    uww_logo = _sb_logo_b64("UW-Whitewater")
    opp_logo = _sb_logo_b64(short, scheduled_name, opp_display)

    def crest(b64):
        return (f'<div class="crest"><img src="data:image/png;base64,{b64}" alt=""></div>'
                if b64 else '<div class="crest"></div>')

    add('<div class="banner">')
    add(f'<div class="side">{crest(uww_logo)}'
        f'<div class="team">UW-WHITEWATER</div>'
        f'<div class="rec">{_sb_esc(uww_record)}</div>'
        + (f'<div class="streak">{_sb_esc(uww_streak)}</div>' if uww_streak else "")
        + "</div>")
    _note = game.get("note") if hasattr(game, "get") else None      # a scrimmage: "scrimmage, real date ..."
    _when = _note if isinstance(_note, str) and _note.strip() else game.get("date", "-")
    add(f'<div class="side mid"><div class="when">{_sb_esc(_when)}</div>'
        f'<div class="vs">VS</div>'
        f'<div class="where">{_sb_esc(game.get("location", "-"))}</div></div>')
    add(f'<div class="side">{crest(opp_logo)}'
        f'<div class="team">{_sb_esc(str(opp_display).upper())}</div>'
        f'<div class="rec">{_sb_esc(opp_record)}</div>'
        + (f'<div class="streak">{_sb_esc(opp_streak)}</div>' if opp_streak else "")
        + "</div>")
    add("</div>")
    # the brief's type, right under the banner (preseason / first games -- a regular brief has none)
    if _bt["title"]:
        add(f'<div class="btype bt-{_bt["type"]}"><div class="btt">{_sb_esc(_bt["title"])}</div>'
            f'<div class="bts">{_sb_esc(_bt["sub"])}</div></div>')
    # (requested: no ROSTER CHANGES section -- the struck-through seniors already show who's gone)
    # this season next to last season (first-games / preseason brief once the parser is on the new season's data --
    # season switch, 00b_season_switch: last season's tables are in LAST_SEASON_DATA_DIR)
    _ls_dir = globals().get("LAST_SEASON_DATA_DIR")
    # CONFIRMED CHANGE (requested: 'Instead of a "THIS SEASON vs LAST SEASON" table, create a "Last Season" row in TEAM
    # STATS'): the separate section is off (BRIEF_SEASON_COMPARE_TABLE = True brings it back); see TEAM STATS below.
    if (globals().get("BRIEF_SEASON_COMPARE_TABLE", False) and _bt["type"] in ("preseason", "first_games")
            and not _bt["last_season"] and _ls_dir and os.path.isdir(_ls_dir)):
        try:
            def _ls_load(name, _d=_ls_dir):
                try:
                    return pd.read_csv(os.path.join(_d, f"{name}.csv"))
                except Exception:
                    return pd.DataFrame()
            _ls_lbl = f"Last season ({globals().get('LAST_SEASON') or 'last season'})"
            _cmp = [(lbl, season_compare(_sb_d, _ls_load, tm, u, _ls_lbl))
                    for lbl, tm, u in (("UW-Whitewater", "UW-Whitewater", True), (opp_display, short, False))]
            _cmp = [(l, t) for l, t in _cmp if t is not None]
            if _cmp:
                section("\U0001f4ca THIS SEASON vs LAST SEASON")
                _h = '<div class="card"><div class="cmpwrap">'
                for _l, _t in _cmp:
                    _h += (f'<div class="cmp"><div class="rct">{_sb_esc(_l)}</div><table class="compact"><tr>'
                           + "".join(f"<th>{_sb_esc(c)}</th>" for c in _t.columns) + "</tr>"
                           + "".join("<tr>" + "".join(f"<td>{_sb_esc(v)}</td>" for v in r) + "</tr>"
                                     for r in _t.itertuples(index=False)) + "</table></div>")
                add(_h + '</div><p class="note">This season\u2019s numbers are a few games \u2014 small samples. '
                    'Last season\u2019s box-score lines are only there for teams we scouted last season; records and '
                    'scoring come from the schedules.</p></div>')
        except Exception as _cme:
            print(f"  (this season vs last season not shown: {type(_cme).__name__}: {_cme})", flush=True)
    # CONFIRMED CHANGE (requested, film-tracking review): page 1 says how much film is on file for them and for us, and how
    # much of it can be trusted (film-quality cell, uww_film_quality.csv) -- the same line the Upcoming Game page shows
    # CONFIRMED CHANGE (requested: "This section is not needed or misleading"): the film-on-file line is no longer in the
    # brief (the app's Video tracking page still shows it). BRIEF_FILM_ON_FILE = True puts it back.
    try:
        if not globals().get("BRIEF_FILM_ON_FILE", False):
            raise StopIteration
        _fq1 = _sb_d("uww_film_quality")
        _fq1_parts = []
        if not _fq1.empty and {"team", "film_line"} <= set(_fq1.columns):
            _fq1_t = _fq1["team"].astype(str)
            _fq1_up = _fq1[_fq1_t == str(short)]
            if _fq1_up.empty and "is_upcoming" in _fq1.columns:
                _fq1_up = _fq1[_fq1["is_upcoming"].astype(str).str.lower() == "true"]
            _fq1_us = (_fq1[_fq1["is_uww"].astype(str).str.lower() == "true"] if "is_uww" in _fq1.columns
                       else _fq1[_fq1_t.str.lower().str.contains("whitewater")])
            for _lbl, _d in ((opp_display, _fq1_up), ("Us", _fq1_us)):
                if len(_d) and _sb_clean(_d.iloc[0].get("film_line")):
                    _fq1_parts.append(f"<b>{_sb_esc(_lbl)}:</b> {_sb_esc(_d.iloc[0]['film_line'])}")
        if _fq1_parts:
            add('<p class="note">\U0001f3a5 Film on file &mdash; ' + " &middot; ".join(_fq1_parts) + ". "
                + app_link("Video tracking", page="upcoming", tab="game_plan", section="film_tracking") + "</p>")
    except StopIteration:
        pass
    except Exception as _fq1_err:
        print(f"  (film-on-file line skipped: {_fq1_err})")

    # ---- gather ---------------------------------------------------------------------------
    us = _sb_team_line(_sb_d("uww_pbp_box_score"), "team", _SB_UWW)
    them = _sb_team_line(_sb_d("uww_opponent_prior_games_box_score"), "team", short)
    them_allowed = _sb_team_line(_sb_d("uww_opponent_prior_games_box_score"), "team", short, invert=True)
    us_allowed = _sb_team_line(_sb_d("uww_pbp_box_score"), "team", _SB_UWW, invert=True)

    totals = _sb_d("uww_opponent_team_totals")
    if not totals.empty and "opponent" in totals.columns:
        row = totals[totals["opponent"].astype(str) == str(short)]
        if not row.empty:
            them.setdefault("PTS", _sb_num(row["team_ppg"]).iloc[0])
            them_allowed.setdefault("PTS", _sb_num(row["opp_ppg_allowed"]).iloc[0])

    players = _sb_player_table(_sb_d, short)

    # ---- staff-input / sample sections ---------------------------------------------------------
    # One renderer for every table the game-plan cell writes. When the table is SAMPLE (is_sample True on
    # every row), the card is drawn as a red box with a SAMPLE DATA tag and a line saying what real input
    # would replace it. When the staff has supplied the file, the same table renders as an ordinary card.
    def staff_rows(table_name):
        df = _sb_d(table_name)
        if df.empty:
            return df, False
        if "opponent" in df.columns:
            df = df[df["opponent"].astype(str) == str(short)]
        is_sample = bool("is_sample" in df.columns and not df.empty
                         and df["is_sample"].astype(str).str.lower().isin(["true", "1"]).all())
        return df, is_sample

    def open_card(is_sample, why):
        if is_sample:
            add('<div class="sample"><div class="sample-tag">Sample data \u2014 not from your files</div>')
            if why:
                add(f'<p class="sample-why">{_sb_esc(why)}</p>')
        else:
            add('<div class="card">')

    def staff_cell(value):
        if isinstance(value, float) and not pd.isna(value) and float(value).is_integer():
            return str(int(value))
        return _sb_clean(value)

    def staff_table(table_name, title, columns, why_sample, note=None):
        df, is_sample = staff_rows(table_name)
        if df.empty:
            return
        add('<div class="gcell">')
        add(f'<div class="sect{" sample-sect" if is_sample else ""}"><div class="t">{title}'
            f'{footnote(note) if note else ""}</div></div>')
        open_card(is_sample, why_sample)
        add("<table><thead><tr>" + "".join(
            f'<th style="text-align:left">{_sb_esc(label)}</th>' for _, label in columns) + "</tr></thead><tbody>")
        for _, r in df.iterrows():
            add("<tr>" + "".join(f'<td class="wrap">{_sb_esc(staff_cell(r.get(col)))}</td>'
                                 for col, _ in columns) + "</tr>")
        add("</tbody></table>")
        add("</div></div>")

    # ---- team stats and four factors, side by side ----------------------------------------
    # Collected into lists first rather than written straight out, so the top two can be dropped into
    # one flex row. Either panel can be absent -- no box score, or not enough of one to compute the
    # factors -- and a lone panel is emitted full width instead of stranded in half a row.
    team_parts, ff_parts = [], []
    t_add, f_add = team_parts.append, ff_parts.append

    # ---- team stats -----------------------------------------------------------------------
    # Laid out HORIZONTALLY (requested): each stat is its own narrow column reading top-to-bottom
    # (label, our number, theirs), and the columns run left to right across the full width of the
    # section. The old "cmp" layout stacked one stat per line down the page, which made this a tall
    # narrow list instead of a strip a coach can scan in one pass.
    # CONFIRMED CHANGE (requested: a "Last Season" row in TEAM STATS): on a preseason / first-games brief (once the parser is
    # on the new season), each team's last-season per-game line sits under this season's, from last season's tables
    # (LAST_SEASON_DATA_DIR) -- the same numbers the old THIS SEASON vs LAST SEASON table showed.
    _ls_lines = []
    if (_bt["type"] in ("preseason", "first_games") and not _bt["last_season"] and _ls_dir and os.path.isdir(_ls_dir)):
        def _ls_load2(name, _d=_ls_dir):
            try:
                return pd.read_csv(os.path.join(_d, f"{name}.csv"))
            except Exception:
                return pd.DataFrame()
        for _lab_, _tm_, _u_ in (("UWW", "UW-Whitewater", True), (str(opp_display).upper(), short, False)):
            try:
                _n_, _d_ = _sc_line(_ls_load2, _tm_, _u_)
            except Exception:
                _n_, _d_ = 0, {}
            if _d_:
                _ls_lines.append((_lab_, _n_, _d_))
    _LS_KEY = {"PTS": "PPG", "PACE": "Pace (poss/g)", "FG%": "FG%", "3P%": "3P%", "3PA": "3PA/g", "REB": "REB/g",
               "AST": "AST/g", "TO": "TO/g", "STL": "STL/g"}
    if (us and them) or _ls_lines:
        us, them = us or {}, them or {}
        t_add('<span class="fnhold">' + footnote(
            "Team stats: both sides are built the same way, from play-by-play box scores rather than a scouting "
            "report, so they compare like with like. Their figures cover only the games before this matchup.")
            + "</span>")
        comparisons = [
            # Pace sits right after scoring (requested): points per game only mean something next to how
            # many possessions produced them. Neither direction is "better", so it is never bolded.
            ("Points", "PTS", True), (None, None, None), ("Pace (poss/g)", "PACE", None),
            ("Field Goal %", "FG%", True), ("3PT %", "3P%", True), ("3PA", "3PA", None),
            ("Rebounds", "REB", True), ("Assists", "AST", True),
            ("Turnovers", "TO", False), ("Steals", "STL", True), ("Blocks", "BLK", True),
        ]
        _cells = []
        _team_stat_rows = globals().setdefault("_TEAM_STAT_ROWS", [])
        _team_stat_rows.clear()
        for label, key, higher_is_better in comparisons:
            if key is None:
                label, a, b, higher_is_better = "Points Against", (us_allowed or {}).get("PTS"), (them_allowed or {}).get("PTS"), False
            else:
                a, b = us.get(key), them.get(key)
            _lsv = [(_d_.get("Opp PPG") if key is None else _d_.get(_LS_KEY.get(key, "")) if key else None)
                    for _l_, _n_, _d_ in _ls_lines]
            if a is None and b is None and all(v is None or (isinstance(v, float) and pd.isna(v)) for v in _lsv):
                continue
            _us_cls, _them_cls = "hs-v", "hs-v"
            if higher_is_better is not None and a is not None and b is not None and abs(float(a) - float(b)) >= 0.05:
                if (float(a) > float(b)) == bool(higher_is_better):
                    _us_cls += " hs-win"
                else:
                    _them_cls += " hs-win"
                # CONFIRMED CHANGE (requested 11/18): TEAM COMPARISON's cards name the biggest season-average
                # edge each way. Collected HERE, as the strip is built, so a card and the row it came from
                # cannot disagree -- including on which way is better, which only this loop knows.
                _den = max(abs(float(a)), abs(float(b))) or 1.0
                _team_stat_rows.append({"label": label, "us": float(a), "them": float(b),
                                        "ours": (float(a) > float(b)) == bool(higher_is_better),
                                        "gap": abs(float(a) - float(b)) / _den})
            _cells.append(f'<div class="hs-col"><div class="hs-l">{_sb_esc(label)}</div>'
                          f'<div class="{_us_cls}">{_sb_fmt(a)}</div>'
                          f'<div class="{_them_cls}">{_sb_fmt(b)}</div>'
                          + "".join(f'<div class="hs-v hs-ls">{_sb_fmt(v) if v is not None and not (isinstance(v, float) and pd.isna(v)) else "--"}</div>'
                                    for v in _lsv) + '</div>')
        t_add('<div class="hstat"><div class="hs-col hs-key"><div class="hs-l">&nbsp;</div>'
              f'<div class="hs-v">UWW</div><div class="hs-v">{_sb_esc(str(opp_display).upper())}</div>'
              + "".join(f'<div class="hs-v hs-ls">{_sb_esc(_l_)} last season'
                        + (f' <span class="mini">({_n_} g)</span>' if _n_ else "") + "</div>"
                        for _l_, _n_, _d_ in _ls_lines) + '</div>'
              + "".join(_cells) + "</div>")
        t_add('<p class="mini">Per game, before this matchup. Bold is the better number.</p>')

    # ---- four factors ---------------------------------------------------------------------
    # Same computation and the same weighted ranking as the app's Four Factors dialog. Ours come from
    # our own games, theirs from their prior games, so neither side is adjusted for who they played
    # -- stated under the table rather than left for a coach to assume one way or the other.
    _ff_box = _sb_d("uww_pbp_box_score")
    _ff_prior = _sb_d("uww_opponent_prior_games_box_score")
    _ff_top, _ff_rows = None, []
    if not _ff_box.empty and not _ff_prior.empty and "team" in _ff_box.columns and "team" in _ff_prior.columns:
        _ff_us = _sb_four_factors(_ff_box[_ff_box["team"] == _SB_UWW],
                                  _ff_box[_ff_box["team"] != _SB_UWW])
        _ff_them = _sb_four_factors(_ff_prior[_ff_prior["team"].astype(str) == str(short)],
                                    _ff_prior[_ff_prior["team"].astype(str) != str(short)])
        _ff_rows = []
        for _factor, _weight in _SB_FF_WEIGHTS.items():
            _a, _b = _ff_us.get(_factor), _ff_them.get(_factor)
            if _a is None or _b is None:
                continue
            # Edge is stated so positive always favours us -- which for turnovers means a LOWER rate.
            _edge = (_a - _b) if _SB_FF_HIGHER_IS_BETTER[_factor] else (_b - _a)
            _ff_rows.append({"factor": _factor, "uww": _a, "opp": _b, "edge": _edge,
                             "weight": _weight, "weighted": _edge * _weight})
        if _ff_rows:
            _ff_rows.sort(key=lambda r: abs(r["weighted"]), reverse=True)
            _ff_top = _ff_rows[0]
            # The table itself is gone from the brief (requested) -- every factor is one tap away in the app's
            # Four Factors dialog. The methodology note is registered on THE BOTTOM LINE sentence itself (when
            # it prints), not here: a note registered here had no marker anywhere in the brief pointing to it.

    def two_up(left, right):
        """Two panels in one flex row, or whichever one exists full width. A lone panel stranded in
        half a row reads as a rendering failure rather than as missing data."""
        if left and right:
            return ('<div class="cols"><div class="col">' + "\n".join(left) + "</div>"
                    + '<div class="col">' + "\n".join(right) + "</div></div>")
        return "\n".join(left + right)


    # =====================================================================================================
    # CONDENSED LAYOUT (requested): Page 1 game plan -> opponent (glance, starters, bench, lineups, offense,
    # context, tagging-dependent) -> UWW mirror (starters, bench, lineups, offense, context, our week) -> notes.
    # Nothing was removed: detail that no longer fits a page is one link away in the app, and every
    # methodology paragraph is on the Notes page under its ⓘ number.
    # =====================================================================================================
    OPP_UP = _sb_esc(str(opp_display).upper())
    _team_gp = int(them.get("games") or 0)
    add('<div class="linkbar">' + app_link("Open this matchup in the app", page="upcoming") + "</div>")

    # ---- shared data --------------------------------------------------------------------------------
    _notes_tbl = _sb_d("uww_scouting_notes")
    if not _notes_tbl.empty and "opponent" in _notes_tbl.columns:
        _notes_tbl = _notes_tbl[_notes_tbl["opponent"].astype(str) == str(short)]
    _tiers = _sb_d("uww_personnel_tiers")
    if not _tiers.empty and "scouted_opponent" in _tiers.columns:
        _tiers = _tiers[_tiers["scouted_opponent"].astype(str) == str(short)]
    _pcs_all = _sb_d("uww_play_call_summary")
    _pcc_all = _sb_d("uww_play_calls")
    if not _pcs_all.empty and "scouted_opponent" in _pcs_all.columns:
        _pcs_all = _pcs_all[_pcs_all["scouted_opponent"].astype(str) == str(short)]

    def _offense_rows(side):
        """play_call_summary rows for one side's OWN OFFENSE.

        side alone is not enough any more: it names the FILE a clip came from, and those files now carry
        defensive possessions too. Without the possession_side filter our offensive tables pick up
        possessions where the opponent had the ball -- which is how a SLOB finished by a Ripon player
        turned up under our own sets. Rows written before possession_side existed have no value for it and
        are treated as offensive, which is what they were.
        """
        if _pcs_all.empty or "side" not in _pcs_all.columns:
            return pd.DataFrame()
        rows = _pcs_all[_pcs_all["side"] == side]
        if "possession_side" in rows.columns:
            rows = rows[rows["possession_side"].astype(str) != "Defense"]
        return rows
    if not _pcc_all.empty and "scouted_opponent" in _pcc_all.columns:
        _pcc_all = _pcc_all[_pcc_all["scouted_opponent"].astype(str) == str(short)]
    _flags = _sb_d("uww_coaching_flags")
    _live_ros = _sb_d("uww_live_rosters")
    _avail, _avail_sample = staff_rows("uww_uww_availability")

    def _norm(n):
        return re.sub(r"\s+", " ", str(n)).strip().lower()

    def _sb_title(n):
        """ALL-CAPS roster names read as shouting in running prose. Title-case them, but leave a name that
        already has mixed case alone -- "McEwen" and "Mur Martin" are correct as tagged and .title() would
        wreck them."""
        n = re.sub(r"\s+", " ", str(n)).strip()
        if not n or n != n.upper():
            return n
        return " ".join(w[:1].upper() + w[1:].lower() if w else w for w in n.split(" "))

    def players_for(box_name, team_value):
        """Per-game lines for any team's players -- same math as _sb_player_table, which is opponent-only."""
        box = _sb_d(box_name)
        if box.empty or "team" not in box.columns:
            return pd.DataFrame()
        own = box[(box["team"].astype(str) == str(team_value)) & (box["player"].astype(str) != "TEAM")]
        rows = []
        for name, g in own.groupby("player"):
            games = g["game_date"].nunique() if "game_date" in g.columns else len(g)
            t = {c: _sb_num(g[c]).sum() if c in g.columns else 0
                 for c in ("PTS", "REB", "AST", "STL", "BLK", "TO", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "MIN")}
            rows.append({"name": str(name), "games": games,
                         **{k: (t[k] / games if games else None) for k in ("PTS", "REB", "AST", "STL", "BLK", "TO", "MIN")},
                         "FG%": _sb_pct(t["FGM"], t["FGA"]), "3P%": _sb_pct(t["FG3M"], t["FG3A"]),
                         "FT%": _sb_pct(t["FTM"], t["FTA"]), "FTM": t["FTM"], "FTA": t["FTA"],
                         "PTS_total": t["PTS"]})
        return pd.DataFrame(rows)

    def stat_line(p):
        return (f'{_sb_fmt(p["games"], 0)} GP &middot; {_sb_fmt(p.get("MIN"))} MIN &middot; {_sb_fmt(p["PTS"])} PTS &middot; '
                f'{_sb_fmt(p["REB"])} REB &middot; {_sb_fmt(p["AST"])} AST &middot; {_sb_fmt(p["TO"])} TO &middot; '
                f'{_sb_fmt(p["FG%"])}% FG &middot; {_sb_fmt(p["3P%"])}% 3P &middot; {_sb_fmt(p["FT%"])}% FT')

    def tier_groups(side, player_names):
        """[(label, caption, [names])] in the app's order. Falls back to one group when no tiers exist."""
        t = _tiers[_tiers["side"] == side] if not _tiers.empty and "side" in _tiers.columns else pd.DataFrame()
        if t.empty:
            return None, [("Players", "No personnel tiers on file yet -- ordered by production.", list(player_names))], "", []
        n = int(t["recent_n"].max() or 0)
        basis = _sb_clean(t["starter_basis"].iloc[0])
        by = lambda label: list(t[t["tier"] == label].sort_values("mpg", ascending=False)["player"])  # noqa: E731
        starters = by("Starter")
        # "Bench -- limited minutes" is no longer printed (requested): under-8-minute players filled a
        # third of the roster pages without changing how anyone prepares. They are still tiered in the
        # data and still in the app -- the list comes back here so the brief can say how many were left
        # out and point the staff at them, rather than silently shortening the roster.
        # "No minutes in last N games" is no longer printed either (requested) -- it lives in the app. Both
        # omitted tiers are returned so the roster's single app link can say how many were left out.
        _limited = by("Bench \u2014 limited minutes") + by("Bench \u2014 no minutes")
        bench = [
            ("Bench \u2014 rotation", f"Played in the last {n} game(s) and averaging 8+ minutes.", by("Bench \u2014 rotation")),
        ]
        # CONFIRMED CHANGE (requested: "for scrimmages and season opener briefs ... include everyone on the bench instead of
        # filtering out the ones with 8 or fewer minutes played"): a preseason / season-opener brief lists every tier.
        if _sb_full_bench:
            bench += [("Bench \u2014 limited minutes", f"Played in the last {n} game(s), under 8 minutes a game.",
                       by("Bench \u2014 limited minutes")),
                      ("Bench \u2014 no minutes", f"No minutes in the last {n} game(s).", by("Bench \u2014 no minutes"))]
            _limited = []
        return starters, bench, basis, _limited

    # ---- personnel identity (photo / # / pos / ht / yr) ------------------------------------------------
    _pers_tbl, _pers_is_sample = staff_rows("uww_opp_personnel")
    _opp_bio = {_norm(r["player"]): r for _, r in _pers_tbl.iterrows()} if not _pers_tbl.empty else {}
    _uww_bio = {}
    if not _live_ros.empty and "team" in _live_ros.columns:
        _uww_labels = {_norm(_SB_UWW)}
        _sched_all = _sb_d("uww_schedule")
        if not _sched_all.empty and "team" in _sched_all.columns:
            _uww_labels |= {_norm(t) for t in _sched_all["team"].dropna().unique() if "whitewater" in str(t).lower()}
        _uww_ros_rows = _live_ros[_live_ros["team"].astype(str).str.contains("whitewater", case=False, na=False)
                                  | _live_ros["team"].astype(str).map(_norm).isin(_uww_labels)]
        for _, r in _uww_ros_rows.iterrows():
            _uww_bio[_norm(r["name"])] = {"player": r["name"], "jersey": r.get("jersey_number"),
                                          "position": r.get("position"), "height": r.get("height"),
                                          "class_year": r.get("class_year"), "photo_url": r.get("photo_url")}
    # CONFIRMED BUG (fixed; "Why does Nolan Groh not have a photo on the brief?"): the opponent's photo / # / position /
    # height / class came only from uww_opp_personnel, which lists the players on film. A player who has never played
    # (a freshman like Groh, now listed with the whole bench) had no bio and no photo even though the live roster page has
    # both -- he now gets them from the live roster.
    _opp_ros_bio = {}
    if not _live_ros.empty and {"team", "name"} <= set(_live_ros.columns):
        for _, r in _live_ros[_live_ros["team"].astype(str) == str(short)].iterrows():
            _opp_ros_bio[_norm(r["name"])] = {"player": r["name"], "jersey": r.get("jersey_number"),
                                              "position": r.get("position"), "height": r.get("height"),
                                              "class_year": r.get("class_year"), "photo_url": r.get("photo_url")}
    _avail_by = {_norm(r["player"]): r for _, r in _avail.iterrows()} if not _avail.empty else {}

    _photo_stats = {"Opponent": [0, []], "UWW": [0, []]}

    # CONFIRMED CHANGE (requested 11/19: "you could do a fall back of getting the roster pictures from the
    # previous year ... Just make a note of that in the application and the scouting reports"). 82_ writes
    # where each picture came from; a photo that is not from THIS season's report says so under the face,
    # because an old picture of a player who has changed a lot is worse than useless if nobody knows it is old.
    _sb_photo_src = {}
    try:
        _psrc = _sb_d("uww_player_image_sources")
        if not _psrc.empty and {"player", "source"} <= set(_psrc.columns):
            for _, _pr in _psrc.iterrows():
                _sb_photo_src[_norm(_pr.get("player"))] = (str(_pr.get("source") or ""),
                                                           str(_pr.get("detail") or ""))
    except Exception:
        pass

    def _photo_note(name):
        """"last season (2025-26)" / "hope.edu" -- or "" when it came from this season's report."""
        _src, _det = _sb_photo_src.get(_norm(name), ("", ""))
        if not _src or _src == "scouting report":
            return ""
        return f"{_src} ({_det})" if _det else _src

    def photo_cell(url, name=None, side=None):
        url = _sb_clean(url)
        if not url and name:
            b64 = _sb_headshot_b64(name)
            if b64:
                url = f"data:image/png;base64,{b64}"
        if side in _photo_stats and name:
            if url:
                _photo_stats[side][0] += 1
            else:
                _photo_stats[side][1].append(str(name))
        if not url:
            return '<div class="photo-thumb photo-thumb-blank"></div>'
        _note = _photo_note(name) if name else ""
        return (f'<img src="{_sb_esc(url)}" class="photo-thumb" alt=""'
                + (f' title="Photo: {_sb_esc(_note)}">' if _note else ">")
                + (f'<div class="photo-note">{_sb_esc(_note)}</div>' if _note else ""))

    def bio_bits(r, extra=None):
        bits = []
        if r is not None:
            if _sb_clean(r.get("jersey")):
                bits.append(f"#{_sb_esc(_sb_clean(r.get('jersey')))}")
            for c in ("position", "height", "hand", "class_year", "status"):
                if _sb_clean(r.get(c)):
                    bits.append(_sb_esc(_sb_clean(r.get(c))))
        return bits + (extra or [])

    # ---- one full card (starters) ----------------------------------------------------------------------
    def opp_card(name, p):
        rows = (_notes_tbl[(_notes_tbl["subject_type"] == "player") & (_notes_tbl["name"].map(_norm) == _norm(name))]
                if not _notes_tbl.empty else pd.DataFrame())
        bio = _opp_bio.get(_norm(name))
        title = name_link(name, page="upcoming", tab="personnel", team="opponent", player=name)
        if p is not None and _team_gp > 1 and float(p["games"]) < 0.5 * _team_gp:
            title += f' <span class="pill-thin">{int(p["games"])} of {_team_gp} games</span>'
        add('<div class="player">')
        add(f'<div class="nm">{title}</div>')
        gof = _sb_clean(bio.get("games_on_film")) if bio is not None else ""
        add(f'<div class="bio{" sample-bio" if _pers_is_sample else ""}">'
            f'{photo_cell(bio.get("photo_url") if bio is not None else None, name, "Opponent")}'
            f'<div class="bio-text">{" &middot; ".join(bio_bits(bio, [f"{_sb_esc(gof)} games on film"] if gof else []))}'
            f'</div></div>')
        if p is not None:
            add(f'<div class="statline">{stat_line(p)}</div>')
        good, bad = [], []
        for _, r in rows.iterrows():
            good += _sb_split(r.get("strengths"))
            bad += _sb_split(r.get("weaknesses"))
        if good or bad:
            add('<div class="reads">' + "".join(f'<span class="dot good">{_sb_esc(i)}</span>' for i in good)
                + "".join(f'<span class="dot bad">{_sb_esc(i)}</span>' for i in bad) + "</div>")
        for src in ("Coach", "Data-Driven"):
            r = rows[rows["source"] == src] if not rows.empty else pd.DataFrame()
            if r.empty:
                continue
            r = r.iloc[0]
            notes, keys = _sb_clean(r.get("notes")), _sb_clean(r.get("keys_to_defending"))
            if not notes and not keys:
                continue
            add(f'<div class="srcblock {"coach" if src == "Coach" else "derived"}"><div class="srclabel">{_sb_esc(src)}</div>')
            if notes:
                add(f'<p class="notes">{_sb_esc(notes)}</p>')
            if keys:
                add('<div class="kd"><span class="lbl">Keys to Defending</span>'
                    + "".join(f'<div class="kdline">{_sb_esc(k)}</div>' for k in _sb_split(keys)) + "</div>")
            add("</div>")
        add("</div>")

    def uww_player_calls(name):
        if _pcc_all.empty or "side" not in _pcc_all.columns:
            return ""
        c = _pcc_all[(_pcc_all["side"] == "UWW") & (_pcc_all["player"].astype(str).map(_norm) == _norm(name))
                     & (~_pcc_all["decode_quality"].isin(["Needs review", "Untagged"]))]
        named = c[c["play_call"].notna() & ~c["play_call"].astype(str).str.contains("unspecified", na=False)]
        vc = named["play_call"].value_counts()
        vc = vc[vc >= 3]
        if vc.empty:
            return ""
        pts = pd.to_numeric(c["points"], errors="coerce")
        ppp = pts.sum() / pts.notna().sum() if pts.notna().any() else None
        # (requested 11/18) the per-set counts stay -- they are the content -- but not the possession total
        return (f"Tagged film: featured in " + ", ".join(f"{n} ({int(k)}x)" for n, k in vc.head(3).items())
                + (f" \u2014 {ppp:.2f} PPP." if ppp is not None else "."))

    def uww_card(name, p):
        bio = _uww_bio.get(_norm(name))
        av = _avail_by.get(_norm(name))
        extra = []
        if av is not None and _sb_clean(av.get("status")):
            extra.append(_sb_esc(_sb_clean(av.get("status"))) + (" (sample)" if _avail_sample else "")
                         + (f" \u2014 {_sb_esc(_sb_clean(av.get('note')))}" if _sb_clean(av.get("note")) else ""))
        add('<div class="player">')
        add(f'<div class="nm">{name_link(name, page="upcoming", tab="personnel", team="uww", player=name)}</div>')
        add(f'<div class="bio">{photo_cell(bio.get("photo_url") if bio else None, name, "UWW")}'
            f'<div class="bio-text">{" &middot; ".join(bio_bits(bio, extra)) or "No roster-page details on file"}</div></div>')
        if p is not None:
            add(f'<div class="statline">{stat_line(p)}</div>')
        pf = (_flags[_flags["player"].astype(str).map(_norm) == _norm(name)]
              if not _flags.empty and "player" in _flags.columns else pd.DataFrame())
        if not pf.empty:
            for label, sentiment in (("Lean on", "positive"), ("Clean up", "negative")):
                sel = pf[pf["sentiment"].astype(str).str.lower() == sentiment]
                if sel.empty:
                    continue
                add(f'<div class="srcblock derived"><div class="srclabel">{label}</div>')
                for _, f in sel.iterrows():
                    # Confidence labels read like "Low (n=3 Off Screen attempts -- small sample, re-check...)"; the
                    # tier and the count are what a card needs -- the full sentence stays in the app.
                    _conf = _sb_clean(f.get("confidence"))
                    _cm = re.match(r"^(\w+)\s*\((n=\d+)", _conf)
                    _conf = f"{_cm.group(1)}, {_cm.group(2)}" if _cm else _conf
                    add(f'<p class="notes"><strong>{_sb_esc(_sb_clean(f.get("flag")))}</strong>'
                        + (f' <span class="conf-tag">{_sb_esc(_conf)}</span>' if _conf else "")
                        + f' \u2014 {_sb_esc(_sb_clean(f.get("evidence")))}</p>')
                    if _sb_clean(f.get("recommendation")):
                        add(f'<div class="kdline">{_sb_esc(_sb_clean(f.get("recommendation")))}</div>')
                add("</div>")
        calls = uww_player_calls(name)
        if calls:
            add(f'<div class="srcblock derived"><div class="srclabel">Play calls</div><p class="notes">{_sb_esc(calls)}</p></div>')
        add("</div>")

    # CONFIRMED CHANGE (requested): the standalone Late-Game Foul List is gone; its call now rides along in
    # the opponent's roster table beside each player's FT%, which is where a coach reads it anyway.
    _foul_tbl, _ = staff_rows("uww_late_game_foul_list")
    _foul_by = {_norm(r["player"]): r for _, r in _foul_tbl.iterrows()} if not _foul_tbl.empty else {}

    def foul_cell(name):
        r = _foul_by.get(_norm(name))
        if r is None:
            return '<td class="mini">--</td>'
        call = _sb_clean(r.get("call"))
        # Icon rather than words (requested): a check means foul him, a cross means don't. The words stay in
        # the cell's tooltip and are spelled out under the table, so the icon is never the only explanation.
        icon, cls = {"Foul": ("\u2714", "call-foul"),
                     "Do not foul": ("\u2718", "call-nofoul")}.get(call, ("\u2013", "mini"))
        return (f'<td class="{cls} foul-icon" title="{_sb_esc(call)} \u2014 {_sb_fmt(r.get("ft_pct"))}% FT">'
                f'{icon}</td>')

    # ---- compact roster rows ---------------------------------------------------------------------------
    # One table shape for every tier, with fixed column widths so the starters, rotation, limited-minutes and
    # no-minutes tables all line up down the page instead of each sizing itself to its own content.
    # CONFIRMED CHANGE (requested: "put the picture right above the player name. Instead of a bio column, make that
    # information into kind of a header row for each player"): 11 columns -- player (photo over name), the 8 stats, late
    # game foul, reads -- and each player's bio (#, position, height, class, Off / Def role) is a bar across the table
    # right above his row.
    # CONFIRMED CHANGE (requested: Option A): no reads column any more -- the reads go in a row of their own under the
    # numbers, so the 8 stats (and the opponent's late game foul call) spread across the full width
    _ROSTER_COLS = ('<colgroup><col style="width:18%">'
                    '<col style="width:9%"><col style="width:9%"><col style="width:9%"><col style="width:9%">'
                    '<col style="width:9%"><col style="width:9%"><col style="width:9%"><col style="width:9%">'
                    '<col style="width:10%"></colgroup>')
    # (requested: "UWW doesn't need 'Late game foul' column") -- our own roster: 10 columns, the reads get the room
    _ROSTER_COLS_UWW = ('<colgroup><col style="width:20%">'
                        '<col style="width:10%"><col style="width:10%"><col style="width:10%"><col style="width:10%">'
                        '<col style="width:10%"><col style="width:10%"><col style="width:10%"><col style="width:10%">'
                        '</colgroup>')

    _DEF_FAMILY_MIN = 6      # possessions before a family is reported at all
    _DEF_SPLIT_MIN = 4       # possessions before a per-player / per-series split is reported

    # CONFIRMED BUG (fixed here; Carroll brief after Coach Jake's 2/24 Elmhurst tags): a clip with no press tag has press_faced
    # = NaN, and bool(NaN) is True -- so 26 of Carroll's 28 tagged possessions (no defense tagged at all) were counted as
    # "Press" ("1.31 PPP vs Press", "turnover rate moves +19.2 points under pressure"). Only a real True counts now.
    def _press_true(v):
        return v is not None and not (isinstance(v, float) and pd.isna(v)) and str(v).strip().lower() in ("true", "1", "1.0", "yes")

    def _def_family(row):
        """man / zone / press, from the decoded defense fields. Press is its own family because it's a
        separate decision and a separate practice block -- a pressing man team lands in 'press'."""
        if _press_true(row.get("press_faced")):
            return "Press"
        d = _sb_clean(row.get("defense_faced"))
        if not d:
            return ""
        return "Zone" if "zone" in d.lower() else ("Man" if "man" in d.lower() else d)

    def _pf_clips(side_val, team_val=None):
        """Decoded, reviewable clips for one side with a defense read on them."""
        if _pcc_all.empty or "defense_faced" not in _pcc_all.columns:
            return pd.DataFrame()
        # OFFENSIVE possessions only. On a mixed file a defensive clip's defense tag is what this team
        # PLAYED, which would silently invert every row in this section.
        d = _pcc_all[(_pcc_all["side"] == side_val) & (~_pcc_all["decode_quality"].isin(["Needs review", "Untagged"]))].copy()
        if "possession_side" in d.columns:
            d = d[d["possession_side"].astype(str) != "Defense"]
        if team_val is not None and "offense_team" in d.columns:
            d = d[d["offense_team"].astype(str) == str(team_val)]
        if d.empty:
            return d
        d["_fam"] = d.apply(_def_family, axis=1)
        d = d[d["_fam"].astype(str) != ""]
        if d.empty:
            return d
        _res = d["result"].astype(str).str.lower() if "result" in d.columns else pd.Series("", index=d.index)
        d["_pts"] = pd.to_numeric(d.get("points"), errors="coerce")
        d["_to"] = _res.str.contains("turnover|violation|kicked", regex=True)
        d["_fga"] = _res.str.startswith(("make", "miss")) & _res.str.contains("2|3", regex=True)
        d["_fgm"] = _res.str.startswith("make") & _res.str.contains("2|3", regex=True)
        return d

    def _ppp_of(grp):
        _known = grp["_pts"].notna().sum()
        return (grp["_pts"].sum() / _known) if _known else None

    def _ppp_cls(v, base):
        if v is None or base is None or pd.isna(v) or pd.isna(base):
            return ""
        return "ppp-good" if v >= base + 0.15 else ("ppp-bad" if v <= base - 0.15 else "")


    # ---- Defense splits in the Player Notes (requested; replaces the "Who changes by defense" table) -----
    # A player gets a note only when his scoring really moves with the defense family he faces. Each
    # family's PPP is shrunk toward his own overall PPP as if shrink_poss average possessions were added, so
    # 4-for-4 against a zone can't read as a real split; the gap is judged on the shrunk numbers and the raw
    # numbers are what the note prints.
    DEF_SPLIT_RULES = {
        "min_poss_each": _DEF_FAMILY_MIN,  # possessions against a family before it's compared
        "shrink_poss": 8,                   # average possessions added to each family before comparing
        "min_gap": 0.30,                    # shrunk PPP gap (points per possession) worth a note
    }
    _def_split_note = {}
    _pf_opp = _pf_clips("Opponent", short)
    if not _pf_opp.empty and "player" in _pf_opp.columns:
        _plx = _pf_opp[_sb_has_text(_pf_opp["player"]) & _pf_opp["_pts"].notna()]
        for _who, _g in _plx.groupby(_plx["player"].astype(str)):
            _overall = _g["_pts"].mean()
            _fams = {}
            for _fam, _fg in _g.groupby("_fam"):
                _n = len(_fg)
                if _n >= DEF_SPLIT_RULES["min_poss_each"]:
                    _k = DEF_SPLIT_RULES["shrink_poss"]
                    _fams[_fam] = (_fg["_pts"].mean(), _n, (_fg["_pts"].sum() + _k * _overall) / (_n + _k))
            if len(_fams) < 2:
                continue
            _hi = max(_fams.items(), key=lambda kv: kv[1][2])
            _lo = min(_fams.items(), key=lambda kv: kv[1][2])
            if _hi[1][2] - _lo[1][2] < DEF_SPLIT_RULES["min_gap"]:
                continue
            _def_split_note[_norm(_who)] = (
                f"Scores {_hi[1][0]:.2f} PPP vs {_hi[0].lower()} ({_hi[1][1]} poss) but {_lo[1][0]:.2f} vs "
                f"{_lo[0].lower()} ({_lo[1][1]}) \u2014 stay attached to him against {_hi[0].lower()}, "
                f"help off him in {_lo[0].lower()}")

    # Who dominates their offensive glass, if anyone -- keyed by normalised name for the roster read above.
    _reb_crasher = {}
    # CONFIRMED CHANGE (requested: "move the 'Who to attack' up to the player roster section when it's applicable"). The
    # two-for-one cell's Attack / Avoid call on a player (uww_two_for_one_attack) is now a line on his roster entry instead
    # of a table in the TWO-FOR-ONE section. Only players still on the roster get it (a struck-through senior doesn't).
    _tf_attack_by = {}
    _tfa_df, _ = staff_rows("uww_two_for_one_attack")
    if not _tfa_df.empty and {"player", "verdict"} <= set(_tfa_df.columns):
        for _, _a in _tfa_df.iterrows():
            if str(_a["verdict"]) in ("Attack", "Avoid") and _norm(_a["player"]) not in globals().get("_SB_STRUCK", ()):
                _tf_attack_by[_norm(_a["player"])] = _a

    def _tf_attack_line(name):
        a = _tf_attack_by.get(_norm(name))
        if a is None:
            return None
        _f40 = pd.to_numeric(a.get("fouls_per_40"), errors="coerce")
        _lf = int(pd.to_numeric(a.get("late_fouls"), errors="coerce") or 0)
        _ls = pd.to_numeric(a.get("late_share_pct"), errors="coerce")
        _why = ", ".join(x for x in (
            f"{_f40:.1f} fouls/40" if pd.notna(_f40) else "",
            f"{_lf} foul{'s' if _lf != 1 else ''} defending 2-for-1 possessions",
            f"on the floor {int(_ls)}% of the time late in halves" if pd.notna(_ls) else "") if x)
        return (("Attack him late in a half (2-for-1 window)" if str(a["verdict"]) == "Attack"
                 else "Don\u2019t attack him late in a half (2-for-1 window)") + (f" \u2014 {_why}" if _why else ""))
    _RRr = globals().get("REBOUND_RULES") or {"min_paired": 20, "player_share": 35, "player_min": 5}
    _rsr = _sb_d("uww_rebound_summary")
    if not _rsr.empty and {"opponent", "metric", "player", "value", "count", "paired"}.issubset(_rsr.columns):
        _rsr = _rsr[(_rsr["opponent"].astype(str) == str(short)) & (_rsr["metric"] == "their_oreb_player")]
        for _, _cr in _rsr.iterrows():
            _share = pd.to_numeric(_cr["value"], errors="coerce")
            _cnt = int(pd.to_numeric(_cr["count"], errors="coerce") or 0)
            if (pd.notna(_share) and _share >= _RRr["player_share"] and _cnt >= _RRr["player_min"]
                    and int(pd.to_numeric(_cr["paired"], errors="coerce") or 0) >= _RRr["min_paired"]):
                _reb_crasher[_norm(_cr["player"])] = (f"Crashes the offensive glass \u2014 {_cnt} of their "
                                                      f"offensive rebounds after misses ({_share:.0f}%)")

    # Why a player is in an unexpected tier (a returning starter, or the starter he displaced) -- shown as
    # that player's first roster line so the promotion is never unexplained.
    _tier_note = {}
    _tn = _sb_d("uww_personnel_tiers")
    if not _tn.empty and {"player", "tier_note", "side"}.issubset(_tn.columns):
        for _, _t in _tn.iterrows():
            if _sb_clean(_t.get("tier_note")):
                _tier_note[(_t["side"], _norm(_t["player"]))] = _sb_clean(_t["tier_note"])

    _proj_note = {}      # (side, name) -> "Projected starter ..." line, only while the no-seniors roster is drawn
    _thin_mins = {}      # read kind -> (minimum, "attempt"/"shot"), from the below-minimum lines (the * legend)
    _thin_seen = [0]     # players drawn with an * (too few attempts for any read)

    # CONFIRMED CHANGE (requested: last season's numbers for transfers like Logan Steffensmeier, "and somehow flag that
    # they are transfers"). A player on a team's NEW-season roster with no line for that team last season, who shows up in
    # another team's box scores we have (any game in uww_opponent_prior_games_box_score / uww_pbp_box_score), is a
    # transfer: his roster row uses those games' per-game averages and carries a "Transfer -- from <team>" tag.
    _xfer_cache = {}

    def _xkey(n):
        t = re.sub(r"[.,']", " ", str(n or "")).lower().split()
        while len(t) > 2 and t[-1] in ("jr", "sr", "ii", "iii", "iv"):
            t = t[:-1]
        return " ".join(t)

    def _transfer_of(name, side):
        k = (side, _xkey(name))
        if k in _xfer_cache:
            return _xfer_cache[k]
        _xfer_cache[k] = None
        own = "whitewater" if side == "UWW" else _norm(short)
        lr = _live_ros
        if lr.empty or "source" not in lr.columns:
            return None
        _mine = lr[lr["team"].astype(str).map(_norm).str.contains(own, regex=False)]
        if not (_mine["source"].astype(str).str.contains("new season", na=False).any()
                and (_mine["name"].map(_xkey) == _xkey(name)).any()):
            return None
        bx = pd.concat([d for d in (_sb_d("uww_opponent_prior_games_box_score"), _sb_d("uww_pbp_box_score"))
                        if not d.empty and {"team", "player", "game_date"} <= set(d.columns)], ignore_index=True)
        if bx.empty:
            return None
        bx = bx[bx["player"].map(_xkey) == _xkey(name)].drop_duplicates(["game_date", "team", "player"])
        if bx.empty or bx["team"].astype(str).map(_norm).str.contains(own, regex=False).any():
            return None
        team_from = bx["team"].astype(str).value_counts().index[0]
        g = bx[bx["team"].astype(str) == team_from]
        num = lambda c: pd.to_numeric(g[c], errors="coerce") if c in g.columns else pd.Series(dtype=float)  # noqa: E731
        n = len(g)
        pct = lambda m, a: round(100 * num(m).sum() / num(a).sum(), 1) if num(a).sum() else None  # noqa: E731
        p = pd.Series({"games": n, "MIN": round(num("MIN").mean(), 1) if num("MIN").notna().any() else None,
                       "PTS": round(num("PTS").sum() / n, 1), "REB": round(num("REB").sum() / n, 1),
                       "AST": round(num("AST").sum() / n, 1), "TO": round(num("TO").sum() / n, 1),
                       "FG%": pct("FGM", "FGA"), "3P%": pct("FG3M", "FG3A"), "FT%": pct("FTM", "FTA"),
                       "FTM": num("FTM").sum(), "FTA": num("FTA").sum(), "PTS_total": num("PTS").sum()})
        vs = ", ".join(sorted({str(x) for x in g.get("opponent", pd.Series(dtype=str)).dropna() if str(x) != team_from}))
        _xfer_cache[k] = {"team": team_from, "p": p, "games": n, "vs": vs}
        return _xfer_cache[k]

    # CONFIRMED CHANGE (requested: offensive tendencies on the roster -- "which of the actions is McNabb most aggressive",
    # "what types of cuts", "add other things that describe the player on offense"): uww_player_tendencies (built in 47)
    _tend_tbl = _sb_d("uww_player_tendencies")

    # CONFIRMED CHANGE (requested: the "<OPP> reads off their actions" table "needs to be added just to the roster
    # section for the player"): each player's reads (uww_action_reads, 2+ uses) become lines in his card's
    # Tendencies, e.g. "Screener on Ball Screen: Roll 5 of 5 (100%), 1.60 PPP".
    _reads_tbl = _sb_d("uww_action_reads")
    # CONFIRMED CHANGE (requested 11/18): the reads were gated at 2+ uses, and 47 of the table's 58 rows sit at 1, so
    # most of the trigger / screener split never reached the page. A read a coach tagged once is still a read -- the Uses
    # column says how thin it is. BRIEF_READS_MIN_USES raises the bar again if it ever gets noisy.
    _READS_MIN = int(globals().get("BRIEF_READS_MIN_USES", 1))

    # CONFIRMED CHANGE (requested 11/14: the contradiction pass on player lines). Where the film or the numbers contradict
    # a line in the coaches' report, 85b_read_reconcile writes a "Check: ..." line (uww_read_conflicts, action "flag"); it
    # rides above the player's reads. The coaches' own line is never changed. Read straight from the file (not _sb_d): an
    # empty table is the normal case and must not be listed as "not available for this build".
    _read_flags = {}
    try:
        _rcf = pd.read_csv(os.path.join(_sb_d.dir, "uww_read_conflicts.csv"))
    except Exception:
        _rcf = pd.DataFrame()
    if not _rcf.empty and {"opponent", "player", "action", "brief_line"} <= set(_rcf.columns):
        for _, _c in _rcf[(_rcf["opponent"].astype(str) == str(short)) & (_rcf["action"].astype(str) == "flag")].iterrows():
            if _sb_clean(_c.get("brief_line")):
                _read_flags.setdefault(_norm(_c["player"]), []).append(_sb_clean(_c["brief_line"]))

    def _reads_of(name, side):
        r = _reads_tbl
        if r.empty or not {"player", "offense_team", "uses"} <= set(r.columns):
            return []
        own = "whitewater" if side == "UWW" else _norm(short)
        r = r[r["offense_team"].astype(str).map(_norm).str.contains(own, regex=False)
              & (pd.to_numeric(r["uses"], errors="coerce") >= _READS_MIN)]
        r = r[r["player"].astype(str).str.replace(r"^#\S+\s+", "", regex=True).map(_xkey) == _xkey(name)]
        out = []
        for _, x in r.sort_values("uses", ascending=False).head(3).iterrows():
            u = int(pd.to_numeric(x["uses"], errors="coerce"))
            sh = pd.to_numeric(x.get("share_pct"), errors="coerce")
            tot = round(u * 100 / sh) if pd.notna(sh) and sh > 0 else None
            pp = pd.to_numeric(x.get("ppp"), errors="coerce")
            out.append(f"{_sb_clean(x.get('role'))} on {_sb_clean(x.get('action'))}: {_sb_clean(x.get('read'))} "
                       + (f"{u} of {tot} ({int(sh)}%)" if tot else f"{u}x")
                       + (f", {pp:.2f} PPP" if pd.notna(pp) else ""))
        return out

    def _tendencies_of(name, side):
        return _reads_of(name, side) + _tendencies_base(name, side)

    def _tendencies_base(name, side):
        if _tend_tbl.empty or not {"player", "team", "tendencies"} <= set(_tend_tbl.columns):
            return []
        t = _tend_tbl[_tend_tbl["side"].astype(str) == side] if "side" in _tend_tbl.columns else _tend_tbl
        if "scouted_opponent" in t.columns:
            t = t[t["scouted_opponent"].astype(str) == str(short)]
        own = "whitewater" if side == "UWW" else _norm(short)
        t = t[t["team"].astype(str).map(_norm).str.contains(own, regex=False)]
        t = t[t["player"].map(_xkey) == _xkey(name)]
        return _sb_split(t.iloc[0]["tendencies"]) if not t.empty else []

    # CONFIRMED CHANGE (requested: "list out what type of defender will the player struggle against"). Read from how he
    # scores (uww_player_tendencies' numbers): a shooter who rarely puts it on the floor -> a long closeout defender; a rim
    # attacker -> a physical on-ball defender with a big behind; a one-way driver -> a defender who forces his other hand;
    # a post scorer -> a strong post defender who fronts; a weak ball-screen handler -> a mobile big who switches / hedges;
    # a putback threat -> a big who boxes out. On the opponent's cards each type names OUR returning players with that
    # defensive role (uww_defensive_roles). It is a read of his tendencies, not a measured matchup result.
    _dr_tbl = _sb_d("uww_defensive_roles")

    def _our_fits(roles):
        if _dr_tbl.empty or not {"team", "player", "defensive_role"} <= set(_dr_tbl.columns):
            return []
        u = _dr_tbl[_dr_tbl["team"].astype(str).str.contains("whitewater", case=False, na=False)
                    & _dr_tbl["defensive_role"].isin(roles)].copy()
        u = u[~u["player"].map(_norm).isin(globals().get("_SB_STRUCK") or set())]
        u = u[~u["player"].astype(str).str.contains("whitewater", case=False)]
        if "role_basis" in u.columns:                    # a role from his position alone isn't evidence he defends that way
            u = u[u["role_basis"].astype(str) != "position only"]
        _q = {"coach tags + film": 0, "film tracking": 1, "play-by-play only": 2, "position only": 3}
        u["_q"] = u.get("role_basis", pd.Series("", index=u.index)).map(lambda b: _q.get(str(b), 2))
        u["_r"] = u["defensive_role"].map(lambda r: roles.index(r) if r in roles else 9)
        u = u.sort_values(["_r", "_q"])
        return [f"{_sb_title(r['player'])} ({r['defensive_role']})" for _, r in u.head(2).iterrows()]

    def _struggles_of(name, side):
        if _tend_tbl.empty or "share_spot" not in _tend_tbl.columns:
            return []
        t = _tend_tbl[_tend_tbl["side"].astype(str) == side] if "side" in _tend_tbl.columns else _tend_tbl
        if "scouted_opponent" in t.columns:
            t = t[t["scouted_opponent"].astype(str) == str(short)]
        own = "whitewater" if side == "UWW" else _norm(short)
        t = t[t["team"].astype(str).map(_norm).str.contains(own, regex=False) & (t["player"].map(_xkey) == _xkey(name))]
        if t.empty:
            return []
        m = t.iloc[0]
        f = lambda c: float(pd.to_numeric(m.get(c), errors="coerce")) if pd.notna(pd.to_numeric(m.get(c), errors="coerce")) else 0.0  # noqa: E731
        n = f("possessions")
        out = []
        if f("spot_n") >= 5 and f("spot_cs") / f("spot_n") >= 0.7:
            out.append(("A long, active closeout defender who runs him off the line",
                        f"catch-and-shoot on {int(f('spot_cs'))} of {int(f('spot_n'))} spot-ups -- rarely puts it on the floor",
                        ["Wing Stopper", "Chaser", "Point of Attack"]))
        if n >= 10 and f("rim_finishes") / n >= 0.45:
            out.append(("A physical on-ball defender who keeps him in front, with a big waiting at the rim",
                        f"{int(f('rim_finishes'))} of {int(n)} finishes are at the rim", ["Point of Attack", "Wing Stopper"]))
        dl, dr = f("drives_left"), f("drives_right")
        if dl + dr >= 5 and max(dl, dr) / (dl + dr) >= 0.65:
            _to, _away = ("right", "left") if dr > dl else ("left", "right")
            out.append((f"A defender who sits on his {_to} hand and forces him {_away}",
                        f"drives {_to} on {int(max(dl, dr))} of {int(dl + dr)}", ["Point of Attack", "Wing Stopper"]))
        if f("post_n") >= 5:
            _b = _sb_clean(m.get("post_block")).lower()
            out.append(("A strong post defender who fronts him and takes away the " + (_b or "block"),
                        f"{int(f('post_n'))} post-ups" + (f", mostly {_b}" if _b else "")
                        + (f", {_sb_clean(m.get('post_shoulder')).lower()} turn" if _sb_clean(m.get("post_shoulder")) else ""),
                        ["Anchor Big", "Mobile Big"]))
        _pp = pd.to_numeric(m.get("pr_ppp"), errors="coerce")
        if f("pr_n") >= 4 and pd.notna(_pp) and _pp < 0.85:
            out.append(("A mobile big who switches or hedges his ball screens", f"{_pp:.2f} PPP as the ball-screen handler",
                        ["Mobile Big"]))
        if n >= 10 and f("share_putback") >= 0.15:
            out.append(("A big who finds him and boxes him out", f"{round(100 * f('share_putback'))}% of his finishes are putbacks",
                        ["Anchor Big", "Mobile Big"]))
        if n >= 10 and f("share_trans") >= 0.3:
            out.append(("Defenders who sprint back and match up early", f"{round(100 * f('share_trans'))}% of his finishes "
                        "come in transition", []))
        res = []
        for typ, why, roles in out[:3]:
            fits = _our_fits(roles) if side == "Opponent" and roles else []
            res.append(f"{typ} -- {why}" + (f". Our fit: {', '.join(fits)}" if fits else ""))
        return res

    # CONFIRMED CHANGE (requested 11/18: "I want the roster sections to have a subsection under Offense that says how
    # well they do during 'Clutch' moments based on our definition"). OUR definition, not a new one: section 47's
    # _gs_situation stamps every clip with game_situation, and clutch is "not the first half, 5:00 or less on the clock,
    # margin 8 or fewer" (_GS_CLUTCH_SECONDS = 300, _GS_CLUTCH_MARGIN = 8) -- the same rule the clutch-time event log and
    # the game plan use. It is applied to pbp_events and pbp_events_upcoming alike, so a scouted opponent's clutch comes
    # from THEIR games. side alone is not enough (it names the file a clip came from), so possession_side == "Offense"
    # keeps it to possessions where this player's team had the ball.
    def _clutch_tbl(side, poss="Offense"):
        if _pcc_all.empty or not {"game_situation", "player", "side"} <= set(_pcc_all.columns):
            return pd.DataFrame()
        t = _pcc_all[_pcc_all["game_situation"].astype(str).str.startswith("Clutch")
                     & (_pcc_all["side"].astype(str) == side)]
        if "possession_side" in t.columns:
            t = t[t["possession_side"].astype(str) == poss]
        return t

    def _clutch_of(name, side):
        """How this player's team has done with the ball in the clutch when he is the man in the possession.
        Small samples are normal here (a game has a handful of clutch trips), so the count leads and the rate is
        only shown once there are 3 -- and fouls drawn are named, because a trip that ends at the line scores no
        points on the clip itself and would otherwise read as a wasted possession."""
        t = _clutch_tbl(side)
        if t.empty:
            return []
        mine = t[t["player"].astype(str).map(_xkey) == _xkey(name)]
        n = len(mine)
        if not n:
            return []
        pts = float(pd.to_numeric(mine.get("points"), errors="coerce").fillna(0).sum())
        res = mine.get("result", pd.Series(dtype=object)).astype(str)
        fouls = int(res.str.contains("foul", case=False, na=False).sum())
        tos = int(res.str.contains("turnover", case=False, na=False).sum())
        made = int(res.str.contains("make", case=False, na=False).sum())
        shots = int(res.str.contains("make|miss", case=False, regex=True, na=False).sum())
        _team_n = len(t)
        _team_ppp = (float(pd.to_numeric(t.get("points"), errors="coerce").fillna(0).sum()) / _team_n) if _team_n else None
        line = (f"HIM: the ball on {n} clutch possession{'s' if n != 1 else ''} on film \u2014 they produced "
                f"{pts:g} point{'s' if pts != 1 else ''}")
        if n >= 3:
            line += f", {pts / n:.2f} PPP"
            if _team_ppp is not None and _team_n >= 8:
                line += f" (the team {_team_ppp:.2f} on {_team_n})"
        out = [line]
        bits = []
        if shots:
            bits.append(f"{made} of {shots} from the floor")
        if fouls:
            bits.append(f"{fouls} foul{'s' if fouls != 1 else ''} drawn")
        if tos:
            bits.append(f"{tos} turnover{'s' if tos != 1 else ''}")
        if bits:
            # the same rule as the defensive card: what happened ON those trips is not a personal stat line
            out.append("ON THOSE TRIPS: " + ", ".join(bits) + ".")
        return out

    # CONFIRMED CHANGE (requested 11/18: "add information for each player that was on the court on defense during
    # clutch moments"). Defense has no "the man in the possession", so this one goes by WHO WAS ON THE FLOOR:
    # defense_lineup on a clutch possession his team defended. Same clutch rule as above. Lower is better here, so the
    # team's own number rides along for scale, and being on the floor for most of them is itself the point -- the count
    # is "on the floor for N of the team's M".
    def _clutch_def_of(name, side):
        t = _clutch_tbl(side, "Defense")
        if t.empty or "defense_lineup" not in t.columns:
            return []
        _k = _xkey(name)
        _on = t["defense_lineup"].astype(str).map(
            lambda v: _k in {_xkey(x) for x in str(v).split(",") if str(x).strip()})
        mine = t[_on]
        n, _team_n = len(mine), len(t)
        if not n:
            return []
        pts = float(pd.to_numeric(mine.get("points"), errors="coerce").fillna(0).sum())
        # CONFIRMED CHANGE (requested 11/18: "Defensive clutch information needs to be clear what are things the player
        # did and things the team did"). Nothing below is his own stat line -- there is no individual defensive box score
        # here. The ONLY thing about him is that he was on the floor; everything after it is what the five he was in gave
        # up, and it says so in those words.
        out = [f"HIM: on the floor for {n} of the team's {_team_n} clutch defensive possession"
               f"{'s' if _team_n != 1 else ''}" + (" \u2014 every one of them" if n == _team_n and n > 1 else "") + "."]
        line = (f"THE FIVE HE WAS IN (team numbers, not his): {pts:g} point{'s' if pts != 1 else ''} allowed on "
                f"{n} possession{'s' if n != 1 else ''}")
        if n >= 3:
            line += f", {pts / n:.2f} PPP"
            if _team_n >= 8 and _team_n > n:
                line += (f" \u2014 the team allowed "
                         f"{float(pd.to_numeric(t.get('points'), errors='coerce').fillna(0).sum()) / _team_n:.2f} "
                         f"PPP across all {_team_n}")
        out.append(line + ".")
        res = mine.get("result", pd.Series(dtype=object)).astype(str)
        made = int(res.str.contains("make", case=False, na=False).sum())
        shots = int(res.str.contains("make|miss", case=False, regex=True, na=False).sum())
        tos = int(res.str.contains("turnover", case=False, na=False).sum())
        fouls = int(res.str.contains("foul", case=False, na=False).sum())
        bits = ([f"{made} of {shots} shooting against"] if shots else []) \
            + ([f"{tos} turnover{'s' if tos != 1 else ''} forced"] if tos else []) \
            + ([f"{fouls} foul{'s' if fouls != 1 else ''} given up"] if fouls else [])
        if bits:
            out[-1] = out[-1][:-1] + ": " + ", ".join(bits) + "."
        return out

    # CONFIRMED CHANGE (requested 11/18: "Put a flag on the players that are the best clutch offensive and defensive
    # players"). One flag each per side, and only when the flag means something: an offensive flag needs 3+ clutch
    # possessions of his own and at least two players who clear that bar, and a defensive flag needs him on the floor for
    # 3+ (and at least 40% of the team's clutch defensive possessions) AND two different rates among those who qualify --
    # otherwise every man in a five that never changed would be "the best". The defensive one is a FIVE-MAN number and
    # the chip's tooltip says so, in line with how the cards read.
    _clutch_best_cache = {}

    def _clutch_best(side):
        if side in _clutch_best_cache:
            return _clutch_best_cache[side]
        out = {"off": None, "def": None}
        o = _clutch_tbl(side)
        if not o.empty and "player" in o.columns:
            _r = []
            for k, g in o.groupby(o["player"].astype(str).map(_xkey)):
                if k and len(g) >= 3:
                    _r.append((k, float(pd.to_numeric(g.get("points"), errors="coerce").fillna(0).sum()) / len(g), len(g)))
            if len(_r) >= 2:
                out["off"] = max(_r, key=lambda x: (x[1], x[2]))
        d = _clutch_tbl(side, "Defense")
        if not d.empty and "defense_lineup" in d.columns:
            _pts = pd.to_numeric(d.get("points"), errors="coerce").fillna(0).tolist()
            _by = {}
            for _i, (_, r_) in enumerate(d.iterrows()):
                for nm in str(r_.get("defense_lineup") or "").split(","):
                    if nm.strip():
                        _by.setdefault(_xkey(nm), []).append(_pts[_i])
            _floor = max(3, round(0.4 * len(d)))
            _r = [(k, sum(v) / len(v), len(v)) for k, v in _by.items() if len(v) >= _floor]
            if len({round(x[1], 3) for x in _r}) >= 2:
                out["def"] = min(_r, key=lambda x: (x[1], -x[2]))
        _clutch_best_cache[side] = out
        return out

    def _clutch_flags(name, side):
        """[(chip text, tooltip)] -- at most one of each."""
        _cb, _k, out = _clutch_best(side), _xkey(name), []
        if _cb.get("off") and _cb["off"][0] == _k:
            out.append(("Clutch \u2014 best with the ball",
                        f"{_cb['off'][1]:.2f} PPP on the {_cb['off'][2]} clutch possessions he ran"))
        if _cb.get("def") and _cb["def"][0] == _k:
            out.append(("Clutch \u2014 best five on defense",
                        f"{_cb['def'][1]:.2f} PPP allowed over the {_cb['def'][2]} clutch possessions he was on the "
                        f"floor for \u2014 a five-man number, not his alone"))
        return out

    def _roster_player(name, stats_df, side, bullets):
        """Everything one roster entry needs, assembled once so the table layout and the stacked layout
        can't show different reads, keys or flags for the same player."""
        _thin = False
        s_ = stats_df[stats_df["name"].map(_norm) == _norm(name)] if not stats_df.empty else pd.DataFrame()
        p = s_.iloc[0] if not s_.empty else None
        _xf = _transfer_of(name, side) if p is None else None
        if _xf is not None:
            p = _xf["p"]
        reads, keys, _tfat, _crash, _dsplit, pf, calls = [], [], None, None, None, pd.DataFrame(), None
        if side == "Opponent":
            bio = _opp_bio.get(_norm(name))
            if bio is None:
                bio = _opp_ros_bio.get(_norm(name))
            rows = (_notes_tbl[(_notes_tbl["subject_type"] == "player") & (_notes_tbl["name"].map(_norm) == _norm(name))]
                    if not _notes_tbl.empty else pd.DataFrame())
            reads = [x for _, r in rows.iterrows() for x in _sb_split(r.get("strengths")) + _sb_split(r.get("weaknesses"))]
            keys = [x for _, r in rows.iterrows() for x in _sb_split(r.get("keys_to_defending"))]
            # CONFIRMED CHANGE (requested: "It should have brought in information for Logan Steffensmeier"): a player with
            # no read from the numbers (a transfer or freshman, no box-score line) shows the coaches' own Player Notes
            # from the scouting report instead of an empty cell
            if not reads and "source" in rows.columns:
                reads = [x for _, r in rows[rows["source"].astype(str) == "Coach"].iterrows() for x in _sb_split(r.get("notes"))]
            items = reads[:2] + keys[:1]
            # No real read: show the stats that fell short of a minimum (or that nothing met a threshold)
            # rather than a blank cell -- requested, because a blank looked like the notes had failed.
            # CONFIRMED CHANGE (requested: "remove the minimum descriptions on every player ... just an asterisk next to
            # them with one line near the bottom that explains the asterisks"): the below-minimum lines are no longer
            # printed; the player gets an * by his name and the roster ends with one line explaining it.
            if not items and "below_minimum" in rows.columns:
                _bm = [x for _, r in rows.iterrows() for x in _sb_split(r.get("below_minimum"))]
                if _bm:
                    _thin = True
                    for x in _bm:
                        m_ = re.search(r"under the (\d+)-(attempt|shot) minimum for an? ([\w-]+) read", str(x))
                        if m_:
                            _thin_mins[m_.group(3)] = (int(m_.group(1)), m_.group(2))
            # Rebounding read (requested): only for the one player who dominates their offensive glass, by
            # the same REBOUND_RULES as the key and the Bottom Line. Goes FIRST so it survives the top-three
            # cut -- if he's doing this, it's the thing to know about him.
            _crash = _reb_crasher.get(_norm(name))
            _dsplit = _def_split_note.get(_norm(name))
            if _dsplit:
                items = [_dsplit] + items
            if _crash:
                items = [_crash] + items
            _tfat = _tf_attack_line(name)       # (requested) the 2-for-1 Attack / Avoid call goes first
            if _tfat:
                items = [_tfat] + items
            if bullets and len(items) < 3:
                # Fill to three from whatever is left, keys first -- an instruction beats another label.
                items += [x for x in keys[1:] + reads[2:] if x not in items][:3 - len(items)]
            team = "opponent"
        else:
            bio = _uww_bio.get(_norm(name))
            pf = (_flags[_flags["player"].astype(str).map(_norm) == _norm(name)]
                  if not _flags.empty and "player" in _flags.columns else pd.DataFrame())
            items = [_sb_clean(f.get("flag")) for _, f in pf.iterrows()]
            calls = uww_player_calls(name)
            items += [calls] if calls else []
            team = "uww"
        if _tier_note.get((side, _norm(name))):
            items = [_tier_note[(side, _norm(name))]] + items
        if _proj_note.get((side, _norm(name))):          # (no-seniors brief) why he's in the starting five now
            items = [_proj_note[(side, _norm(name))]] + items
        # CONFIRMED CHANGE (requested: the film goes into the existing sections, not its own): the player's film line
        # (player tracking -- _film_player_note, built in "THE FILM" above the roster) rides along as one more line
        _film = _film_player_note.get((side, _norm(name)))
        detail = (("<ul class=\"tbl-bul\">" + "".join(f"<li>{_sb_esc(x)}</li>" for x in items[:3])
                   + (f'<li class="film">\U0001f3a5 {_sb_esc(_film)}</li>' if _film else "") + "</ul>")
                  if bullets else " \u00b7 ".join([_sb_esc(x) for x in items] + ([f"\U0001f3a5 {_sb_esc(_film)}"] if _film else [])))
        bits = " ".join(bio_bits(bio)) if bio is not None else ""
        _bits_bio, _role_html, _drole_html = bits, "", ""
        # his offensive role (BBall Index's 12) -- the same lookup every roster table uses
        _team_q = short if side == "Opponent" else "Whitewater"
        # CONFIRMED CHANGE (same card as the role fix): a role worked out with no film behind it says so, so a coach
        # can see the difference between "we watched him" and "we counted his assists".
        # CONFIRMED CHANGE (requested 11/18: "I don't think you need to mention '(low sample)' or '(box score only)'").
        # A role is a role; how thin the evidence behind it is belongs in the methodology, not beside every name on
        # every card. "(position only)" stays -- that one says there is no data at all behind the label.
        _q = lambda bb: (" (position only)" if str(bb) == "position only" else "")  # noqa: E731
        if "offensive_role_for" in globals():
            _role, _basis = offensive_role_for(name, _team_q)
            if _role:
                bits = (bits + " &middot; " if bits else "") + f'Off: <strong>{_sb_esc(_role)}</strong><span class="mini">{_q(_basis)}</span>'
                _role_html = f'Role: <strong>{_sb_esc(_role)}</strong><span class="mini">{_q(_basis)}</span>'
        if "defensive_role_for" in globals():
            _drole, _dbasis = defensive_role_for(name, _team_q)
            if _drole:
                bits = (bits + " &middot; " if bits else "") + f'Def: <strong>{_sb_esc(_drole)}</strong><span class="mini">{_q(_dbasis)}</span>'
                _drole_html = f'Role: <strong>{_sb_esc(_drole)}</strong><span class="mini">{_q(_dbasis)}</span>'
        if _xf is not None:
            _xl = (f"Transfer from {_xf['team']} \u2014 his numbers are last season's there "
                   f"({_xf['games']} game{'s' if _xf['games'] != 1 else ''} on file" + (f", vs {_xf['vs']}" if _xf["vs"] else "") + ")")
            detail = (("<ul class=\"tbl-bul\"><li>" + _sb_esc(_xl) + "</li>" + detail[len('<ul class="tbl-bul">'):])
                      if detail.startswith('<ul class="tbl-bul">') else _sb_esc(_xl) + (" \u00b7 " + detail if detail else ""))
        # CONFIRMED CHANGE (requested: Option A, reads under "Offense" and "Defense" -- "Let's just do Offense and
        # Defense"). Offense = how he scores / plays with the ball, plus the coaches' keys to guarding him (bold);
        # Defense = how he defends: steals / blocks / fouls, the 2-for-1 attack-him call, where he plays off his man
        # (film). The transfer / projected-starter / tier notes ride above both.
        _off, _dfn, _lead = [], [], []
        _DRX = re.compile(r"steal|spg|block|bpg|active hands|deflect|defend|on[- ]ball|guarded|fouls?/40|2-for-1|"
                          r"off his man|sags|helps|closeout|switch|point of attack", re.I)
        _add = lambda col, x, key=False: col.append((x, key)) if x and x not in [a for a, _k in col] else None  # noqa: E731
        if side == "Opponent":
            if _tfat:
                _add(_dfn, _tfat)
            if _crash:
                _add(_off, _crash)
            if _dsplit:
                _add(_dfn, _dsplit)
            for x in reads:
                _add(_dfn if _DRX.search(x) else _off, x)
            for x in keys:
                _add(_dfn if re.search(r"attack him|go at him|post him|make him guard", x, re.I) else _off, x, True)
        else:
            for _, f_ in pf.iterrows():
                x = _sb_clean(f_.get("flag"))
                _add(_dfn if _DRX.search(x) else _off, x)
            if calls:
                _add(_off, calls)
        if _film:
            _add(_dfn, "\U0001f3a5 " + _film)
        for _k in ("_tier", "_proj"):
            _nt = (_tier_note if _k == "_tier" else _proj_note).get((side, _norm(name)))
            if _nt:
                _lead.append(_nt)
        if side == "Opponent":                           # (11/14) the report vs the film / the numbers -- at most two
            _lead += (_read_flags.get(_norm(name)) or [])[:2]
        if _xf is not None:
            _lead.insert(0, f"Transfer from {_xf['team']} \u2014 his numbers are last season's there "
                            f"({_xf['games']} game{'s' if _xf['games'] != 1 else ''} on file"
                            + (f", vs {_xf['vs']}" if _xf["vs"] else "") + ")")
        return {"p": p, "bio": bio, "bits": bits, "items": items, "detail": detail, "team": team, "film": _film,
                "off": _off[:3], "def": _dfn[:3], "lead": _lead, "xfer": _xf, "tend": _tendencies_of(name, side)[:8],
                "struggle": _struggles_of(name, side), "clutch": _clutch_of(name, side),
                "clutch_def": _clutch_def_of(name, side), "clutch_flag": _clutch_flags(name, side),
                "bits_bio": _bits_bio, "role_off": _role_html, "role_def": _drole_html,
                "thin": _thin}

    def _ft_cell(p):
        # A bare "100.0" invites exactly the question asked about Hillmer's free throws -- real, or one
        # attempt? The makes-attempts pair rides along whenever the sample is thin -- unless it's already
        # 100%, where the fraction adds nothing a coach needs at a glance.
        return (f'<td title="{int(p.get("FTM") or 0)}-for-{int(p.get("FTA") or 0)}">{_sb_fmt(p["FT%"])}'
                + (f' <span class="mini">({int(p.get("FTM") or 0)}-{int(p.get("FTA") or 0)})</span>'
                   if (p.get("FTA") or 0) and p["FTA"] < 10
                   and round(float(p.get("FT%") or 0), 1) != 100.0 else "") + "</td>")

    def bench_table(names, stats_df, side, bullets=False, tags=None):
        """bullets=True (starters): the last column holds up to three bulleted items instead of a one-line
        summary -- the same table the bench uses, with room for more of each starter's read."""
        if ROSTER_LAYOUT == "stacked":
            return stacked_roster(names, stats_df, side, bullets)
        # CONFIRMED CHANGE (requested: "I still need the display to look better than this"): each player is ONE card --
        # a header band (photo, name, #/pos/ht/class, transfer / projected-starter tags, the late-game foul call), a stat
        # strip with each number labelled under it, and the Offense | Defense reads. One small table per player, so a
        # struck senior's card (every row starts with his name) is struck / left out whole.
        _opp = side == "Opponent"
        _li = lambda col: ("<ul>" + "".join(f'<li class="key">{_sb_esc(x)}</li>' if k_ else f"<li>{_sb_esc(x)}</li>"  # noqa: E731
                                            for x, k_ in col) + "</ul>") if col else '<span class="none">nothing on file yet</span>'
        _labs = ("GP", "MIN", "PTS", "REB", "AST", "FG%", "3P%", "FT%")
        for name in names:
            r = _roster_player(name, stats_df, side, bullets)
            p, bio = r["p"], r["bio"]
            _thin_seen[0] += 1 if r.get("thin") else 0
            _hid = f'<span class="p-hd-nm">{_sb_esc(name)} </span>'
            _chips = ""
            # (a projected starter's note -- with his minutes -- is the yellow line above the reads, so no chip for it)
            if r.get("xfer"):
                _chips += f'<span class="pc-chip">Transfer \u2014 {_sb_esc(r["xfer"]["team"])}</span>'
            for _ct, _cttl in r.get("clutch_flag") or []:
                _chips += (f'<span class="pc-chip clutch" title="{_sb_esc(_cttl)}">\u2605 {_sb_esc(_ct)}</span>')
            _foul = ""
            if _opp:
                _fr = _foul_by.get(_norm(name))
                _call = _sb_clean(_fr.get("call")) if _fr is not None else ""
                _foul = {"Foul": '<span class="pc-foul yes">\u2714 Foul him late</span>',
                         "Do not foul": '<span class="pc-foul no">\u2718 Don\u2019t foul late</span>'}.get(
                    _call, '<span class="pc-foul">Late foul: \u2013</span>')
            add('<table class="pc2"><tbody>')
            add(f'<tr class="pc-top"><td><div class="pc-top-in">'
                f'{photo_cell(bio.get("photo_url") if bio is not None else None, name, side)}'
                f'<div class="pc-who"><div class="pc-nm">{name_link(name, page="upcoming", tab="personnel", team=r["team"], player=name)}'
                + ('<span class="thin-ast" title="Too few attempts for a read">*</span>' if r.get("thin") else "")
                + f'</div><div class="pc-bio">{r.get("bits_bio") or "No roster-page details on file"}</div>'
                + (f'<div class="pc-chips">{_chips}</div>' if _chips else "") + f'</div>{_foul}</div></td></tr>')
            if p is not None:
                _vals = [_sb_fmt(p["games"], 0), _sb_fmt(p.get("MIN")), _sb_fmt(p["PTS"]), _sb_fmt(p["REB"]),
                         _sb_fmt(p["AST"]), _sb_fmt(p["FG%"]), _sb_fmt(p["3P%"]), _sb_fmt(p["FT%"])]
                _ft = (f'<span class="pc-sub">{int(p.get("FTM") or 0)}-{int(p.get("FTA") or 0)}</span>'
                       if (p.get("FTA") or 0) and p["FTA"] < 10 and round(float(p.get("FT%") or 0), 1) != 100.0 else "")
                add(f'<tr class="pc-st"><td>{_hid}<div class="pc-grid">'
                    + "".join(f'<div><b>{v}{(" " + _ft) if l_ == "FT%" and _ft else ""}</b><span>{l_}</span></div>' for v, l_ in zip(_vals, _labs))
                    + (f'<div class="pc-src">{r["xfer"]["games"]} game(s) at {_sb_esc(r["xfer"]["team"])}</div>' if r.get("xfer") else "")
                    + "</div></td></tr>")
            else:
                add(f'<tr class="pc-st"><td>{_hid}<div class="pc-none">No box-score line \u2014 hasn\u2019t played in a game we have</div></td></tr>')
            add(f'<tr class="pc-rd"><td>{_hid}'
                + "".join(f'<div class="rd-lead">{_sb_esc(x)}</div>' for x in r.get("lead") or [] if not x.startswith("Transfer from"))
                + f'<div class="rd2"><div class="rd-o"><span class="rd-h">Offense</span>'
                + (f'<div class="rd-role">{r["role_off"]}</div>' if r.get("role_off") else "") + f'{_li(r.get("off"))}'
                + ('<div class="rd-tend"><span class="rd-sub">In the clutch (last 5 min, margin &le; 8)</span><ul>'
                   + "".join(f"<li>{_sb_esc(x)}</li>" for x in r.get("clutch") or []) + "</ul></div>" if r.get("clutch") else "")
                + ('<div class="rd-tend"><span class="rd-sub">Tendencies (from the film)</span><ul>'
                   + "".join(f"<li>{_sb_esc(x)}</li>" for x in r.get("tend") or []) + "</ul></div>" if r.get("tend") else "")
                + ('<div class="rd-tend"><span class="rd-sub">Struggles against</span><ul>'
                   + "".join(f"<li>{_sb_esc(x)}</li>" for x in r.get("struggle") or []) + "</ul></div>" if r.get("struggle") else "")
                + '</div>'
                  f'<div class="rd-d"><span class="rd-h">Defense</span>'
                + (f'<div class="rd-role">{r["role_def"]}</div>' if r.get("role_def") else "") + f'{_li(r.get("def"))}'
                + ('<div class="rd-tend"><span class="rd-sub">In the clutch (last 5 min, margin &le; 8)</span><ul>'
                   + "".join(f"<li>{_sb_esc(x)}</li>" for x in r.get("clutch_def") or []) + "</ul></div>"
                   if r.get("clutch_def") else "")
                + '</div></div></td></tr>')
            add("</tbody></table>")

    # ---- STACKED roster layout (requested example) ---------------------------------------------------
    # Each player gets a HEADER BAR -- photo, name, bio, late-game foul call -- and the full width below
    # it goes to the numbers: the box-score line, then the shot profile (where he shoots from and how well,
    # from the play-by-play), then the reads. The table layout above has to fit all of that into one row,
    # which is why name and bio were squeezed into narrow columns and there was no room for shot data.
    _shot_prof = _sb_d("uww_player_shot_profile")

    def _shot_line(name, side):
        if _shot_prof.empty or "player" not in _shot_prof.columns:
            return ""
        sp = _shot_prof[(_shot_prof["side"] == side) & (_shot_prof["player"].map(_norm) == _norm(name))]
        if side == "Opponent" and "opponent" in sp.columns:
            sp = sp[sp["opponent"].astype(str) == str(short)]
        if sp.empty:
            return ""
        r = sp.iloc[0]
        fga = int(pd.to_numeric(r.get("fga"), errors="coerce") or 0)
        if fga < 5:
            return ""
        # A TABLE, not flex: the brief is printed and PDF'd, and older print engines lay a wrapping flex row
        # out unpredictably -- the caption and the three zones collapsed into one squeezed line in testing.
        cells = []
        for key, label in (("rim", "At the rim"), ("other2", "Other 2s"), ("three", "Threes")):
            share = pd.to_numeric(r.get(f"{key}_share"), errors="coerce")
            fg = pd.to_numeric(r.get(f"{key}_fg"), errors="coerce")
            att = int(pd.to_numeric(r.get(f"{key}_att"), errors="coerce") or 0)
            share = int(share) if pd.notna(share) else 0
            cells.append(f'<td class="sz"><div class="sz-l">{label}</div>'
                         f'<div class="sz-bar"><span style="width:{max(share, 2)}%"></span></div>'
                         f'<div class="sz-v"><strong>{share}%</strong> of shots &middot; '
                         + (f'{fg:.0f}% FG' if pd.notna(fg) else "no attempts" if not att else "--")
                         + (f' <span class="mini">({att})</span>' if att else "") + "</div></td>")
        return (f'<table class="sz-row"><tr><td class="sz-cap" colspan="3">Where he shoots '
                f'<span class="mini">{fga} FGA, from the play-by-play</span></td></tr><tr>'
                + "".join(cells) + "</tr></table>")

    def stacked_roster(names, stats_df, side, bullets=False):
        for name in names:
            r = _roster_player(name, stats_df, side, bullets)
            p, bio = r["p"], r["bio"]
            # The header has room for words, which are clearer than the table's check / cross icon.
            _foul = ""
            _fr = _foul_by.get(_norm(name)) if side == "Opponent" else None
            if _fr is not None:
                _call = _sb_clean(_fr.get("call"))
                if _call in ("Foul", "Do not foul"):
                    # Built outside the f-string: a backslash escape inside an f-string EXPRESSION is a
                    # SyntaxError before Python 3.12.
                    _fl = "Foul him late" if _call == "Foul" else "Don\u2019t foul late"
                    _fc = "call-foul" if _call == "Foul" else "call-nofoul"
                    _foul = (f'<span class="ph-foul {_fc}">{_fl} '
                             f'<span class="mini">({_sb_fmt(_fr.get("ft_pct"))}% FT)</span></span>')
            _foul = "".join(f'<span class="ph-foul ph-clutch" title="{_sb_esc(_cttl)}">\u2605 {_sb_esc(_ct)}</span>'
                            for _ct, _cttl in r.get("clutch_flag") or []) + _foul
            add('<div class="pcard gone">' if _norm(name) in globals().get("_SB_STRUCK", ()) else '<div class="pcard">')
            add(f'<div class="ph">{photo_cell(bio.get("photo_url") if bio is not None else None, name, side)}'
                f'<div class="ph-name">{name_link(name, page="upcoming", tab="personnel", team=r["team"], player=name)}'
                f'<div class="ph-bio">{r["bits"]}</div></div>{_foul}</div>')
            if p is not None:
                add('<table class="compact pstats"><thead><tr><th>GP</th><th>MIN</th><th>PTS</th><th>REB</th>'
                    '<th>AST</th><th>FG%</th><th>3P%</th><th>FT%</th></tr></thead><tbody><tr>'
                    f'<td>{_sb_fmt(p["games"], 0)}</td><td>{_sb_fmt(p.get("MIN"))}</td><td>{_sb_fmt(p["PTS"])}</td>'
                    f'<td>{_sb_fmt(p["REB"])}</td><td>{_sb_fmt(p["AST"])}</td><td>{_sb_fmt(p["FG%"])}</td>'
                    f'<td>{_sb_fmt(p["3P%"])}</td>' + _ft_cell(p) + "</tr></tbody></table>")
            else:
                add('<p class="mini">No box-score line.</p>')
            add(_shot_line(name, side))
            if r["items"]:
                add('<div class="p-reads">' + ("<ul class=\"tbl-bul\">" + "".join(
                    f"<li>{_sb_esc(x)}</li>" for x in r["items"][:3]) + "</ul>") + "</div>")
            if r.get("film"):
                add(f'<div class="p-reads mini">\U0001f3a5 {_sb_esc(r["film"])}</div>')
            add("</div>")

    def personnel_pages(side, team_title, stats_df, card_fn, extra_no_min="", break_first=True, lead=None):
        names_by_prod = list(stats_df.sort_values("PTS_total", ascending=False)["name"]) if not stats_df.empty else []
        starters, bench, basis, limited = tier_groups(side, names_by_prod)
        if starters is None:
            starters, bench = names_by_prod[:5], [("Bench", "No personnel tiers on file yet.", names_by_prod[5:])]
            basis = "no tier table -- top five by production"
        # CONFIRMED CHANGE (requested: the season-opener brief starts the coaches' five): when the coaches' scouting report
        # for THIS game lists its starters (uww_opponent_rosters, upcoming_report = True), they are the starters; last
        # season's starters who aren't in it move to the top of the bench.
        if side == "Opponent":
            try:
                _or = _sb_d("uww_opponent_rosters")
                if not _or.empty and {"upcoming_report", "role", "name", "opponent"} <= set(_or.columns):
                    _rs = _or[(_or["opponent"].astype(str) == str(short))
                              & (_or["upcoming_report"].astype(str).str.lower() == "true")
                              & (_or["role"].astype(str) == "Starter")]["name"].astype(str).tolist()
                    if 3 <= len(_rs) <= 5:
                        _everyone = list(starters) + [n for g in bench for n in g[2]] + \
                            [x.strip() for x in str(extra_no_min or "").split(",") if x.strip()] + list(limited or [])
                        _by = {_xkey(n): n for n in _everyone}
                        _new_st = [_by.get(_xkey(n), n) for n in _rs]
                        _ks = {_xkey(n) for n in _new_st}
                        _was = [n for n in starters if _xkey(n) not in _ks]
                        bench = [(lab, cap, [n for n in names if _xkey(n) not in _ks]) for lab, cap, names in bench]
                        if bench:
                            bench[0] = (bench[0][0], bench[0][1], _was + bench[0][2])
                        else:
                            bench = [("Bench", "", _was)]
                        extra_no_min = ", ".join(x.strip() for x in str(extra_no_min or "").split(",")
                                                 if x.strip() and _xkey(x) not in _ks)
                        limited = [n for n in (limited or []) if _xkey(n) not in _ks]
                        starters = _new_st
                        basis = "the coaches' scouting report for this game (FastScout)"
            except Exception as _e:
                print(f"  (coaches' starters not used: {type(_e).__name__}: {_e})")
        if not starters and not any(g[2] for g in bench):
            return
        if break_first:
            page_break()
        if lead:
            lead()  # e.g. the team divider, kept on the same page as the starters it introduces
        _ros_sec(side, f"\U0001f465 {team_title} - ROSTER"
                + footnote(f"{team_title} starters: {basis}. Per-game averages from their own film. "
                           "After each bio: 'Off' = his offensive role (BBall Index's 12) from his play types; 'Def' "
                           "= his defensive role (BBall Index's 7) from coverage tags with his number, film tracking "
                           "where he was identified for sure, and his steals/blocks -- '(position only)' when "
                           "there's no data behind the label at all. "
                           + ("Photo, jersey, position, height and class come from the FastScout roster page when "
                              "a live scrape has run; hand and status aren't on that page and stay blank. Coach "
                              "notes pass through as written; data-driven lines are stated against the team's own "
                              "averages with attempt floors." if side == "Opponent" else
                              "Flags come from our own season film (highest-confidence first in the app). Play-call "
                              "lines need 3+ tagged uses of a set.")
                           + (" " + _film_roster_note if side == "Opponent" and _film_roster_note else "")))
        # CONFIRMED CHANGE (requested: "on the no_seniors scouting briefs ... always 5 starters"). When last season's
        # seniors are struck (scrimmage / season opener), the roster is drawn twice: the struck-through copy exactly as
        # before, and -- for the no-seniors copy -- one without the seniors where every graduated senior STARTER is
        # replaced by the returning player most likely to take his spot, tagged "Projected starter". The run block keeps
        # the right one in each file (<!--NS:strike--> / <!--NS:remove-->).
        _ns = _no_senior_roster(side, starters, bench, extra_no_min)
        if _ns is None:
            _roster_card(side, stats_df, starters, bench, limited, extra_no_min)
            return
        add("<!--NS:strike-->")
        _roster_card(side, stats_df, starters, bench, limited, extra_no_min)
        add("<!--/NS--><!--NS:remove-->")
        _ns_starters, _ns_bench, _ns_extra, _ns_tags = _ns
        try:
            _roster_card(side, stats_df, _ns_starters, _ns_bench, [], _ns_extra, tags=_ns_tags,
                         proj_note=bool(_ns_tags))
        finally:
            _proj_note.clear()
        add("<!--/NS-->")

    def _no_senior_roster(side, starters, bench, extra_no_min):
        """(starters, bench, never-played names, {name: tag}) without last season's seniors and with five starters, or
        None when no senior is on this roster. A returning starter stays a starter, untagged. Each open spot goes to the
        returning player who played the most minutes a game last season (then starts in the recent games, then games),
        and he is tagged."""
        struck = globals().get("_SB_STRUCK") or set()
        if not struck:
            return None
        # CONFIRMED BUG (fixed; "Is Greg Smith really a freshman still?"): once a team's roster has been updated to the new
        # season, a player who is NOT on it (Carroll's Greg Smith, Gray Dingwall, Brandon Keaton -- last season's rows, so
        # still listed "FR") has left the program. He was projected into Carroll's five; in this copy he is treated like a
        # graduated senior -- not on the roster, never projected, and his starting spot (if he had one) is filled.
        _gone_ns = set()
        try:
            _b, _g, _n = roster_changes(_sb_d("uww_live_rosters"), "UW-Whitewater Warhawks" if side == "UWW" else short)
            if _n or any(True for _ in _b):
                _src = _sb_d("uww_live_rosters")
                if "source" in _src.columns and _src["source"].astype(str).str.contains("new season", na=False).any():
                    _gone_ns = {_norm(x) for x in _g}
        except Exception:
            _gone_ns = set()
        struck = set(struck) | _gone_ns
        extra = [x.strip() for x in str(extra_no_min or "").split(",") if x.strip()]
        everyone = list(starters) + [n for g in bench for n in g[2]] + extra
        if not any(_norm(n) in struck for n in everyone):
            return None
        keep = lambda names: [n for n in names if _norm(n) not in struck]  # noqa: E731
        st = keep(starters)
        t = _tiers[_tiers["side"] == side] if not _tiers.empty and "side" in _tiers.columns else pd.DataFrame()
        info = {_norm(r["player"]): r for _, r in t.iterrows()} if not t.empty else {}
        num = lambda r, c: float(pd.to_numeric(r.get(c), errors="coerce") or 0) if r is not None else 0.0  # noqa: E731
        n_recent = int(num(t.iloc[0], "recent_n")) if not t.empty else 0
        pool = [n for n in keep([n for g in bench for n in g[2]] + extra) if n not in st]
        # CONFIRMED CHANGE (requested: "a little bit more logic ... I don't believe that Carroll is going to start 5 guards
        # and UWW is going to start 3 forwards"). Each graduated senior starter's spot goes to a returning player of the
        # SAME kind -- guard, wing (G/F), forward or big -- so the five keeps last season's shape. Kind = roster position
        # (live roster), and a big is a C or a player whose role is Post Scorer / Roll & Cut Big / Anchor Big. Among the
        # candidates the most minutes a game wins, but each step away from the right kind costs PROJ_STARTER_POS_PENALTY
        # minutes (6): a 12.8-minute wing beats a 1.3-minute forward for a forward's spot; a 15.8-minute guard does not.
        _lr = _sb_d("uww_live_rosters")
        pos = {}
        if not _lr.empty and {"team", "name", "position"} <= set(_lr.columns):
            _tm = _lr["team"].astype(str)
            _lr = _lr[_tm.str.contains("whitewater", case=False)] if side == "UWW" else _lr[_tm == str(short)]
            pos = {_norm(r["name"]): str(r["position"] if pd.notna(r["position"]) else "").upper() for _, r in _lr.iterrows()}

        def kind(n):
            r, p_ = info.get(_norm(n)), pos.get(_norm(n), "")
            off = str(r.get("offensive_role") or "") if r is not None else ""
            dfn = str(r.get("defensive_role") or "") if r is not None else ""
            if "C" in p_.split("/") or off in ("Post Scorer", "Roll & Cut Big") or dfn == "Anchor Big":
                return "big"
            return {"G": "guard", "G/F": "wing", "F": "forward", "F/C": "big"}.get(p_, "unknown")
        _pref = {"guard": ["guard", "wing", "unknown", "forward", "big"],
                 "wing": ["wing", "forward", "guard", "unknown", "big"],
                 "forward": ["forward", "wing", "big", "unknown", "guard"],
                 "big": ["big", "forward", "wing", "unknown", "guard"],
                 "unknown": ["guard", "wing", "forward", "big", "unknown"]}
        _pen = float(globals().get("PROJ_STARTER_POS_PENALTY", 6))
        gone = sorted([n for n in starters if _norm(n) in struck], key=lambda n: -num(info.get(_norm(n)), "mpg"))
        tags = {}
        n_open = max(0, min(5, len(st) + len(pool)) - len(st))
        for i in range(n_open):
            if not pool:
                break
            want = kind(gone[i]) if i < len(gone) else "unknown"
            order = _pref[want] if want != "unknown" else None
            score = lambda c: ((num(info.get(_norm(c)), "mpg") - (_pen * order.index(kind(c)) if order else 0)),  # noqa: E731
                               num(info.get(_norm(c)), "starts_recent"), num(info.get(_norm(c)), "games"))
            n = max(pool, key=score)
            pool.remove(n)
            st.append(n)
            tags[n] = "Projected starter"
            r = info.get(_norm(n))
            bits = []
            if r is not None and num(r, "mpg"):
                bits.append(f"{num(r, 'mpg'):.1f} minutes a game last season")
            _proj_note[(side, _norm(n))] = "Projected starter" + (" \u2014 " + ", ".join(bits) if bits else "")
        taken = set(st)
        nb = [(lab, cap, [n for n in keep(names) if n not in taken]) for lab, cap, names in bench]
        ex = ", ".join(n for n in keep(extra) if n not in taken)
        return st, nb, ex, tags

    def _starter_strip(side, names, stats_df):
        """The five starters across the top of the roster: photo, name, bio, the per-game line, both roles and
        a sentence or two. CONFIRMED CHANGE (requested 11/18): "Just put the 5 starters in a horizontal line
        with their photos, offensive and defensive roles and main information (one to two sentences) about
        them. Then there should be a collapsible section underneath that opens the current roster section."
        Everything here comes from _roster_player(), the same builder the roster table below it uses, so the
        strip can never say something different from the card a reader opens underneath it."""
        _five = [n for n in (names or [])][:5]
        if not _five:
            return
        _dot = " \u00b7 "
        add('<div class="sfive">')
        for _nm in _five:
            _r = _roster_player(_nm, stats_df, side, True)
            _p, _bio = _r["p"], _r["bio"]
            _url = _bio.get("photo_url") if _bio is not None else None
            _st = []
            for _c, _lab in (("PTS", "pts"), ("REB", "reb"), ("AST", "ast")):
                _v = _p.get(_c) if _p is not None else None
                if _v is not None and not (isinstance(_v, float) and pd.isna(_v)):
                    _st.append(f"{_sb_fmt(_v)} {_lab}")
            # one or two sentences: his lead notes first (the 2-for-1 call, a transfer line, the coaches' own
            # read), then whatever the offense and defense columns lead with
            _flat = lambda col: [x[0] if isinstance(x, (tuple, list)) else x for x in col]
            _say, _seen = [], set()
            for _x in (_r["lead"] or []) + _flat(_r["off"]) + _flat(_r["def"]):
                _t = _sb_clean(_x)
                if _t and _t.casefold() not in _seen:
                    _seen.add(_t.casefold())
                    _say.append(_t)
                if len(_say) == 2:
                    break
            _team_q = short if side == "Opponent" else _SB_UWW
            add('<div class="sf">')
            add(f'<div class="sf-ph">{photo_cell(_url, _nm, side)}</div>')
            add('<div class="sf-nm">'
                + name_link(_nm, page="upcoming", tab="personnel", player=_nm, team=_team_q) + "</div>")
            if _r["bits_bio"]:
                add(f'<div class="sf-bio">{_r["bits_bio"]}</div>')
            if _st:
                add('<div class="sf-st">' + _sb_esc(_dot.join(_st)) + "</div>")
            for _lab, _html in (("Off", _r["role_off"]), ("Def", _r["role_def"])):
                if _html:
                    add(f'<div class="sf-role"><span class="sf-k">{_lab}</span>'
                        + _html.replace("Role: ", "", 1) + "</div>")
            if _say:
                add('<div class="sf-say">' + " ".join(f"{_sb_esc(x.rstrip('.'))}." for x in _say) + "</div>")
            # CONFIRMED CHANGE (requested 11/18): "Add the foul late and don't foul late flags to the bottom of
            # the starters cards. But only those 2 flags." So no neutral "Late foul: -" chip -- a card says
            # something here only when the call is one of the two, and nothing at all otherwise. Same source,
            # wording and styling as the player card's own flag (_foul_by, the late-game foul list's table),
            # and only for the opponent: those calls are about fouling THEM.
            # CONFIRMED CHANGE (requested 11/18): "Add the clutch flags also to the starters list." Same chips, same
            # rules and same tooltips as the roster card's -- _clutch_flags is the single source -- and for both sides,
            # since who to have on the floor late is a question about our five as much as theirs.
            _cfl = "".join(f'<span class="pc-chip clutch" title="{_sb_esc(_cttl)}">\u2605 {_sb_esc(_ct)}</span>'
                           for _ct, _cttl in _clutch_flags(_nm, side))
            if _cfl:
                add(f'<div class="sf-clutch">{_cfl}</div>')
            if side == "Opponent":
                _fr = _foul_by.get(_norm(_nm))
                _call = _sb_clean(_fr.get("call")) if _fr is not None else ""
                if _call in ("Foul", "Do not foul"):
                    _fl = "Foul him late" if _call == "Foul" else "Don\u2019t foul late"
                    _ic = "\u2714 " if _call == "Foul" else "\u2718 "
                    _cls = "yes" if _call == "Foul" else "no"
                    add(f'<div class="sf-foul"><span class="pc-foul {_cls}">{_ic}{_sb_esc(_fl)}</span></div>')
            add("</div>")
        add("</div>")

    def _ros_sec(side, title):
        # CONFIRMED CHANGE (requested 11/22): "Instead of the header section called 'HOPE - ROSTER', just put 'Starters'
        # above the 5 person starters row with the same formatting as 'Five-man units' below. These sections should be
        # combined." The opponent's roster has no header bar: a "Starters" label (the lineup cards' own lc-lab) carries the
        # footnote, and it sits straight under their recent results. Applied to our own roster too (11/22).
        section(title, bare=True)
        # CONFIRMED CHANGE (requested 11/22): the footnote after "Starters" is removed from the label. The note still exists:
        # it rides on the "Full roster" bar below the strip, the way the lineup note rides on "Full tables".
        _ros_fn[0] = title.split("- ROSTER", 1)[1] if "- ROSTER" in title else ""

    _ros_fn = [""]
    _RC_END = '</div><!--rc-->'

    def _open_or_join_card():
        """CONFIRMED CHANGE (requested 11/22: "These need to both be in the overall section. Starters subsection, then
        Five-man units subsection, then 3-man combos subsections."): the lineup block continues the roster's card instead
        of opening a second one. The roster card ends with a marker chunk; if that is the last thing printed, take it
        back and carry on in the same card. (A preseason / opener brief's two roster copies end in <!--/NS-->, so those
        keep a card of their own.)"""
        _sk = _sinks[-1]
        if _sk and _sk[-1] == _RC_END:
            _sk.pop()
            return
        add('<div class="card">')

    def _roster_card(side, stats_df, starters, bench, limited, extra_no_min, tags=None, proj_note=False):
        # CONFIRMED CHANGE (requested): starters and every bench tier live in ONE roster section, in the same
        # table shape. Starters get up to three bullets in the last column; each player's full card (every
        # read, note and key) is one click away in the app.
        add('<div class="card">')
        add('<div class="lc-lab">Starters</div>')
        _thin0 = _thin_seen[0]
        _starter_strip(side, starters, stats_df)
        # everything under the strip -- every starter's full card, every bench tier, the reads -- is one click
        # away instead of several pages of brief
        add('<details class="rosdet"><summary><span class="rd-open">Full roster</span>'
            '<span class="rd-sub">every starter\'s card, the bench and the reads</span>' + _ros_fn[0] + '</summary>')
        add('<div class="tier-h">Starters</div>')
        bench_table(starters, stats_df, side, bullets=True, tags=tags)
        for label, caption, names in bench:
            if not names:
                continue
            add(f'<div class="tier-h">{_sb_esc(label)}</div><p class="tier-c">{_sb_esc(caption)}</p>')
            bench_table(names, stats_df, side)
        if side == "Opponent" and _film_names_gate:
            add(_film_names_gate)          # why there are no film lines yet (tracking can't name enough players)
        # Players never on the floor in any game on film are also app-only now; count them with the rest.
        _extra_n = len([x for x in str(extra_no_min or "").split(",") if x.strip()])
        if _sb_full_bench and _extra_n:
            # (requested: everyone on the bench in a preseason / season-opener brief) -- their names, no stat line
            add('<div class="tier-h">Bench \u2014 never played</div><p class="tier-c">On the roster, no minutes in any '
                'game we have a box score for.</p>')
            bench_table([x.strip() for x in str(extra_no_min).split(",") if x.strip()], stats_df, side)
            _extra_n = 0
        if _thin_seen[0] > _thin0:
            _mins = [f"{n} {u}s for {'an' if k[:1] in 'aeiou' else 'a'} {k} read" for k, (n, u) in _thin_mins.items()]
            # CONFIRMED BUG (fixed 11/14): this said "last season" in every brief, all season long. And a read now also
            # needs READ_MIN_GAMES games (85), so the line names both.
            add('<p class="mini"><span class="thin-ast">*</span> Too few attempts or games on file for a scouting read on him'
                + (" (the minimums: " + ", ".join(_mins) + ")" if _mins else "") + ".</p>")
        if side == "Opponent" and _foul_by:
            add('<p class="mini">Late game foul: <span class="call-foul">\u2714</span> foul him '
                '(62% or worse on 8+ attempts) &middot; <span class="call-nofoul">\u2718</span> do not foul '
                '(75% or better, or 85%+ on as few as 4 attempts) &middot; \u2013 neutral or too few '
                'attempts to say.</p>')
        # ONE link out of the roster, not two (requested). Under-8-minute players are tiered but no longer
        # printed, so the count rides on this same line rather than earning a second identical hyperlink.
        _omitted = len(limited) + _extra_n
        add('<p class="mini">'
            + (f'{_omitted} more player(s) \u2014 under 8 minutes a game or not playing recently \u2014 are '
               f'not listed here. ' if _omitted else "")
            + app_link("Full card for any player", page="upcoming", tab="personnel",
                       team="uww" if side == "UWW" else "opponent") + "</p>")
        add("</details>")
        add(_RC_END)

    # ---- compact tables used by several sections -------------------------------------------------------
    def pc_table(rows, cols, team_ppp=None, row_class=""):
        out = ["<table class=\"compact\"><thead><tr>"
               + "".join(f'<th style="text-align:{"left" if k in ("name", "top_player", "situation") else "right"}">{_sb_esc(l)}</th>' for k, l in cols)
               + "</tr></thead><tbody>"]
        _rc = f' class="{row_class}"' if row_class else ""
        for _, r in rows.iterrows():
            cells = []
            for k, _l in cols:
                v = r.get(k)
                if k == "ppp":
                    cls = ""
                    if pd.notna(v) and team_ppp is not None and pd.notna(team_ppp):
                        cls = "ppp-good" if v >= team_ppp + 0.15 else ("ppp-bad" if v <= team_ppp - 0.15 else "")
                    cells.append(f'<td class="{cls}">{_sb_fmt(v, 2)}</td>')
                elif k == "fg":
                    cells.append(f'<td>{int(r["fgm"])}/{int(r["fga"])}</td>' if int(r.get("fga") or 0) else "<td>--</td>")
                elif k in ("name", "top_player", "situation"):
                    cells.append(f'<td class="wrap">{_sb_esc(_sb_clean(v))}</td>')
                else:
                    cells.append(f"<td>{_sb_fmt(v, 0)}</td>")
            out.append(f"<tr{_rc}>" + "".join(cells) + "</tr>")
        out.append("</tbody></table>")
        return "".join(out)

    # ---- how TOP LINEUPS & 3-MAN COMBOS picks the BEST units (requested) -----------------------------
    # Both teams, five-man units and trios alike, are ranked the same way the "Feature the ... combo" key
    # ranks trios: scoring margin per 40 minutes, shrunk toward zero as if shrink_minutes of an even game
    # were added, so a unit that was +9 in 6 minutes can't outrank one that was +30 in 90. A unit must also
    # clear a minutes floor; if fewer than three do, the table fills with the next best and marks them *.
    # Ours use competitive minutes only (garbage time set aside). Theirs can't: their lineup data has no
    # score at the start of each stint.
    _CRt = globals().get("COMBO_RULES") or {"shrink_minutes": 40, "min_minutes": 40, "min_games": 3,
                                            "min_on_off": 0.0}
    LINEUP_TABLE_RULES = {
        "shrink_minutes": _CRt["shrink_minutes"],
        "five_min_minutes": globals().get("_KTV_OPP_LU_MIN_MINUTES", 8.0),     # same floor as the lineup keys
        "opp_three_min_minutes": globals().get("_KTV_OPP_3MAN_MIN_MINUTES", 12.0),
        "uww_three_min_minutes": _CRt["min_minutes"],                          # same bar as the combo key
        "uww_three_min_games": _CRt["min_games"],
        "uww_three_min_on_off": _CRt["min_on_off"],
    }

    def _rank_units(df, min_col, pm_col, floor, n=3, elig=None, collapse_twins=False):
        """Top n units by shrunk margin per 40. Adds _rmin, _rpm, _per40, _shrunk, _below, _twins."""
        d = df.copy()
        d["_rmin"] = pd.to_numeric(d[min_col], errors="coerce").fillna(0)
        d["_rpm"] = pd.to_numeric(d[pm_col], errors="coerce").fillna(0)
        d = d[d["_rmin"] > 0]
        if d.empty:
            return d
        d["_per40"] = d["_rpm"] / d["_rmin"] * 40
        d["_shrunk"] = d["_rpm"] / (d["_rmin"] + LINEUP_TABLE_RULES["shrink_minutes"]) * 40
        d = d.sort_values(["_shrunk", "_rmin"], ascending=[False, False], kind="stable")
        d["_twins"] = 0
        if collapse_twins:
            # Trios cut from one five-man unit that only ever played together have identical numbers --
            # show the first once and say how many others share it, instead of three identical rows.
            _sig = d["_rmin"].round(2).astype(str) + "|" + d["_rpm"].round(2).astype(str)
            d["_twins"] = _sig.map(_sig.value_counts()) - 1
            d = d[~_sig.duplicated()]
        _ok = d["_rmin"] >= floor
        if elig is not None:
            _ok &= elig.reindex(d.index).fillna(False).astype(bool)
        d["_below"] = ~_ok
        return pd.concat([d[_ok], d[~_ok]]).head(n)

    def _signed(v, digits=1):
        return ("+" if pd.notna(v) and v > 0 else "") + _sb_fmt(v, digits)

    def lineups_table(lu_df, side, note_rows=True):
        if lu_df.empty or "lineup" not in lu_df.columns:
            return
        # PPP per five-man unit, from the play-call summary's own per-lineup rows (level "Personnel grouping"),
        # so it means the same thing here as everywhere else in the brief.
        _lu_ppp = {}
        if not _pcs_all.empty and "level" in _pcs_all.columns:
            _lp = _offense_rows(side)
            _lp = _lp[_lp["level"] == "Personnel grouping"] if not _lp.empty else _lp
            _lu_ppp = {str(r["name"]): (r.get("ppp"), r.get("uses")) for _, r in _lp.iterrows()}
        # CONFIRMED CHANGE (requested: "list out the best 2 5-man lineups for each of MIN, +/-, per 40, PPP and 3P%. Make their
        # values bold in that column if they are in the top 2 and why they were added to the table", plus the "Be aware of"
        # five (the one on the floor for the most tagged possessions) in this table instead of a sentence). Every unit that
        # is top 2 in any of those columns is listed once; its top-2 values are bold (no "Why" column -- removed on request). per 40 and 3P% only
        # rank units with LINEUP_TABLE_RULES["five_min_minutes"]+ minutes (all units if fewer than two have that), 3P% needs
        # 3+ attempts, PPP 3+ tagged possessions.
        _clean = side == "UWW" and {"clean_min", "clean_pm"}.issubset(lu_df.columns)
        d = lu_df.copy()
        d["_rmin"] = pd.to_numeric(d["clean_min" if _clean else "MIN"], errors="coerce").fillna(0)
        d["_rpm"] = pd.to_numeric(d["clean_pm" if _clean else "+/-"], errors="coerce").fillna(0)
        d = d[d["_rmin"] > 0].copy()
        if d.empty:
            return
        d["_per40"] = d["_rpm"] / d["_rmin"] * 40
        _setkey = lambda v: frozenset(_norm(x) for x in re.split(r"[,/|]", str(v)) if x.strip())  # noqa: E731
        _ppp_by = {_setkey(k_): v_ for k_, v_ in _lu_ppp.items()}
        d["_ppp"] = [pd.to_numeric((_ppp_by.get(_setkey(l_)) or (None, None))[0], errors="coerce") for l_ in d["lineup"]]
        d["_pn"] = [pd.to_numeric((_ppp_by.get(_setkey(l_)) or (None, 0))[1], errors="coerce") for l_ in d["lineup"]]
        d["_3p"] = pd.to_numeric(d["3P%"], errors="coerce") if "3P%" in d.columns else pd.Series(float("nan"), index=d.index)
        d["_3pa"] = pd.to_numeric(d["FG3A"], errors="coerce") if "FG3A" in d.columns else pd.Series(99, index=d.index)
        _floor = LINEUP_TABLE_RULES["five_min_minutes"]
        _big = d[d["_rmin"] >= _floor] if (d["_rmin"] >= _floor).sum() >= 2 else d
        _picks = [("_rmin", "Top 2 minutes", d), ("_rpm", "Top 2 +/-", d), ("_per40", "Top 2 per 40", _big),
                  ("_ppp", "Top 2 PPP", d[d["_pn"].fillna(0) >= 3]), ("_3p", "Top 2 3P%", _big[_big["_3pa"].fillna(0) >= 3])]
        _why, _bold, _order = {}, {}, []
        for col, lab, pool in _picks:
            pool = pool[pool[col].notna()]
            for ix in pool.sort_values([col, "_rmin"], ascending=[False, False]).index[:2]:
                _why.setdefault(ix, []).append(lab)
                _bold.setdefault(ix, set()).add(col)
                if ix not in _order:
                    _order.append(ix)
        # the five on the floor for the most tagged possessions ("Be aware of")
        if d["_pn"].notna().any() and d["_pn"].max() > 0:
            ix = d["_pn"].idxmax()
            _why.setdefault(ix, []).append(f"On the floor most on film ({int(d.at[ix, '_pn'])} tagged possessions)")
            if ix not in _order:
                _order.append(ix)
        if not _order:
            return
        top = d.loc[_order]
        # What each unit actually runs (requested), from the parser's per-lineup play-call table, plus its
        # grouping shape so the row says who is on the floor as well as what they call.
        _lu_calls, _lu_group = {}, {}
        _lpc = _sb_d("uww_lineup_play_calls")
        if not _lpc.empty and "lineup" in _lpc.columns:
            _lpc = _lpc[_lpc["side"] == side] if "side" in _lpc.columns else _lpc
            _lu_calls = {str(r["lineup"]): _sb_clean(r.get("top_calls")) for _, r in _lpc.iterrows()}
            _lu_group = {str(r["lineup"]): _sb_clean(r.get("grouping")) for _, r in _lpc.iterrows()}
        _B = lambda ix, col, txt: f"<b>{txt}</b>" if col in _bold.get(ix, set()) else txt  # noqa: E731
        add('<table class="compact"><thead><tr><th style="text-align:left">Lineup</th>'
            + f'<th style="text-align:left">Group</th><th>GP</th><th>{_min_head(side)}</th>'
            + '<th>+/-</th><th>per 40</th><th>PPP</th>' + ("<th>FG%</th><th>3P%</th>" if "FG%" in lu_df.columns else "")
            + '<th style="text-align:left">What they run</th>'
            + ('<th style="text-align:left">Key</th>' if note_rows else "") + "</tr></thead><tbody>")
        for ix, u in top.iterrows():
            key = ""
            if note_rows and not _notes_tbl.empty:
                nr = _notes_tbl[(_notes_tbl["subject_type"] == "lineup") & (_notes_tbl["name"] == str(u["lineup"]))]
                ks = [k for _, r in nr.iterrows() for k in _sb_split(r.get("keys_to_defending"))]
                key = ks[0] if ks else ""
            _ppp, _pn = u["_ppp"], u["_pn"]
            add(f'<tr><td class="wrap" title="{_sb_esc(u["lineup"])}">{_sb_esc(_lu_short(u["lineup"]))}</td>'
                f'<td class="mini">{_sb_esc(_lu_group.get(str(u["lineup"]), ""))}</td>'
                f'<td>{_sb_fmt(u.get("GP"), 0)}</td>'
                + (lambda _pg, _tot: f'<td title="{_tot:.1f} minutes in all">'
                     f'{_B(ix, "_rmin", _sb_fmt(_pg))}</td>')(*_min_pg(side, u["_rmin"]))
                + f'<td>{_B(ix, "_rpm", _signed(u["_rpm"], 0))}</td>'
                f'<td>{_B(ix, "_per40", _signed(u["_per40"]))}</td>'
                + (f'<td title="{int(_pn)} tagged possessions">{_B(ix, "_ppp", _sb_fmt(_ppp, 2))}</td>'
                   if pd.notna(_ppp) else '<td class="mini">--</td>')
                + (f'<td>{_sb_fmt(u.get("FG%"))}</td><td>{_B(ix, "_3p", _sb_fmt(u.get("3P%")))}</td>' if "FG%" in lu_df.columns else "")
                + f'<td class="wrap mini">{_sb_esc(_lu_calls.get(str(u["lineup"]), "--"))}</td>'
                + (f'<td class="wrap mini">{_sb_esc(key)}</td>' if note_rows else "") + "</tr>")
        add("</tbody></table>")
        # (the top scorers on tagged plays -- what the "Be aware of" sentence used to say, built in 47)
        try:
            _osm_ = _sb_d("uww_offense_summary")
            _sc_ = _osm_[(_osm_["kind"] == "scorers") & (_osm_["scouted_opponent"].astype(str) == str(short))
                         & (_osm_["perspective"].fillna("Opponent").astype(str) == side)] if not _osm_.empty else _osm_
            if len(_sc_):
                add(f'<p class="mini">{_sb_esc(_sb_clean(_sc_.iloc[0]["text"]))}</p>')
        except Exception:
            pass

    # CONFIRMED CHANGE (requested 11/18): the roster's "cards always open, full table behind the bar" shape,
    # applied to OUR TOP LINEUPS & 3-MAN COMBOS -- three cards for the five-man units and three for the trios
    # (most minutes, best +/-, best points per possession), then the full tables behind one expander.
    # These three helpers were lifted out of combos_table so the cards and the table match possessions to
    # units the same way: one implementation, as that function's own note demands.
    def _unit_clips(side):
        """Tagged OFFENSIVE possessions with the five on the floor, names normalised."""
        if _pcc_all.empty or "on_court_lineup" not in _pcc_all.columns:
            return pd.DataFrame()
        c = _pcc_all[(_pcc_all["side"] == side) & (~_pcc_all["decode_quality"].isin(["Needs review", "Untagged"]))
                     & _pcc_all["on_court_lineup"].notna()].copy()
        if "possession_side" in c.columns:
            c = c[c["possession_side"].astype(str) != "Defense"]
        if c.empty:
            return c
        c["_five"] = c["on_court_lineup"].astype(str).map(
            lambda v: {_norm(x) for x in re.split(r"[,/|]", v) if x.strip()})
        c["_pts"] = pd.to_numeric(c.get("points"), errors="coerce")
        return c

    def _unit_clips_def(side):
        """The same, for the possessions this side DEFENDED. Checked on the data before relying on it: on a
        defensive row, on_court_lineup is the DEFENDING team's five (UWW defending Alma lists our five;
        Elmhurst defending DePauw lists theirs), so a unit's points allowed can be measured the same way its
        offense is."""
        if _pcc_all.empty or not {"on_court_lineup", "possession_side"} <= set(_pcc_all.columns):
            return pd.DataFrame()
        c = _pcc_all[(_pcc_all["side"] == side) & (~_pcc_all["decode_quality"].isin(["Needs review", "Untagged"]))
                     & _pcc_all["on_court_lineup"].notna()
                     & (_pcc_all["possession_side"].astype(str) == "Defense")].copy()
        if c.empty:
            return c
        c["_five"] = c["on_court_lineup"].astype(str).map(
            lambda v: {_norm(x) for x in re.split(r"[,/|]", v) if x.strip()})
        c["_pts"] = pd.to_numeric(c.get("points"), errors="coerce")
        return c

    def _unit_on(clips, names):
        """The possessions with every one of `names` on the floor."""
        if clips is None or clips.empty or not names:
            return pd.DataFrame()
        return clips[clips["_five"].map(lambda f: set(names) <= f)]

    def _unit_ppp(clips, names):
        """(points per tagged possession, how many) for a unit."""
        _on = _unit_on(clips, names)
        _k = int(_on["_pts"].notna().sum()) if not _on.empty else 0
        return ((_on["_pts"].sum() / _k) if _k else None), _k

    def _five_ppp_map(side):
        """{frozenset of normalised names: (ppp, tagged possessions)} for five-man units -- the same
        "Personnel grouping" rows lineups_table ranks its PPP column on."""
        _lp = _offense_rows(side)
        if _lp.empty or "level" not in _lp.columns:
            return {}
        _lp = _lp[_lp["level"] == "Personnel grouping"]
        return {frozenset(_norm(x) for x in re.split(r"[,/|]", str(r["name"])) if x.strip()):
                (pd.to_numeric(pd.Series([r.get("ppp")]), errors="coerce").iloc[0],
                 pd.to_numeric(pd.Series([r.get("uses")]), errors="coerce").iloc[0])
                for _, r in _lp.iterrows()}

    def _side_games(side):
        """Games on file for one side -- from the same box scores TEAM COMPARISON counts.

        CONFIRMED BUG (fixed 11/18; Corey: "I don't think a 3 man lineup can be averaging this many minutes
        per game"). The arithmetic was right and the COLUMN HEADING was wrong: MIN in the lineup tables is a
        SEASON TOTAL, not a per-game average -- Boone / Trelenberg / Cherry's 60.3 is 20.1 a game across three
        games. Validated four ways before changing anything: the five-man units sum to 118.6 minutes against
        120 of game time (40 x 3); the trios to 1186 against the 1200 expected, since every five contains
        C(5,3) = 10 trios; no trio exceeds the season minutes of its own least-used player (60.3 against
        Cherry's 66.7); and that cap check passed for every trio. So nothing changed in the numbers -- the
        headings now carry the game count, and "MIN (3 g)" cannot be read as per game."""
        _b = _sb_d("uww_pbp_box_score") if side == "UWW" else _sb_d("uww_opponent_prior_games_box_score")
        if _b.empty or not {"team", "game_date"} <= set(_b.columns):
            return 0
        _b = (_b[_b["team"].astype(str).str.contains("Whitewater", case=False, na=False)] if side == "UWW"
              else _b[_b["team"].astype(str).str.strip() == str(short)])
        return int(_b["game_date"].nunique())

    def _min_head(side):
        # CONFIRMED CHANGE (requested 11/18): "Let's make the Minutes be a 'Per Game' metric in the top
        # lineups tables." The underlying number stays the season total -- the ranking, the minutes floors and
        # per 40 are all computed from it -- and only the DISPLAY is divided by the games on file, with the
        # total on the cell's tooltip. Dividing before per 40 would have quietly broken that column.
        return "MIN/G" if _side_games(side) else "MIN"

    def _min_pg(side, total):
        """One unit's minutes per game, for display, and the total for the tooltip."""
        _n = _side_games(side)
        return (float(total) / _n if _n else float(total)), float(total)

    def _lu_box(side):
        """Per-player season totals for one side, from the box scores, plus games on file."""
        _b = _sb_d("uww_pbp_box_score") if side == "UWW" else _sb_d("uww_opponent_prior_games_box_score")
        if _b.empty or "player" not in _b.columns:
            return pd.DataFrame(), 0
        _b = (_b[_b["team"].astype(str).str.contains("Whitewater", case=False, na=False)] if side == "UWW"
              else _b[_b["team"].astype(str).str.strip() == str(short)]).copy()
        if _b.empty:
            return pd.DataFrame(), 0
        _g = _b["game_date"].nunique() if "game_date" in _b.columns else 0
        for _c in ("FG3A", "FG3M", "OREB", "PTS"):
            _b[_c] = _sb_num(_b[_c]) if _c in _b.columns else 0
        return _b.groupby("player")[["FG3A", "FG3M", "OREB", "PTS"]].sum(), _g

    def _lu_read(side, lineup, grouping=""):
        """(who shoots it, what the group is) for one unit -- the two lines under the numbers on a card.

        CONFIRMED CHANGE (requested 11/18): the card says who the shooters are, what share of the floor the
        unit is out there for and what shape it is. Every clause is read off the same box scores and the same
        grouping string the lineup tables use, and any clause whose data is missing is simply left out."""
        _bx, _g = _lu_box(side)
        if _bx.empty or not _g:
            return "", ""
        _mem = [x.strip() for x in str(lineup).split(",") if x.strip()]
        _rows = [(m, _bx.loc[m]) for m in _mem if m in _bx.index]
        if not _rows:
            return "", ""
        _last = lambda n: str(n).split()[-1]
        # who takes threes: 1.5+ attempts a game, most first, four at most -- a fifth name is the one nobody
        # is closing out on, and the line stops being a list of who to chase
        _W = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}
        _sh = sorted([(m, r) for m, r in _rows if r["FG3A"] / _g >= 1.5], key=lambda x: -x[1]["FG3A"])[:4]
        _shoot = ""
        if _sh:
            _bits = []
            for _i, (_m, _r) in enumerate(_sh):
                _pct = f" ({_r['FG3M'] / _r['FG3A'] * 100:.0f}%)" if _r["FG3A"] else ""
                _nm = f"<b>{_sb_esc(_last(_m))}</b>" if _i < 2 else _sb_esc(_last(_m))
                _bits.append(f"{_nm} {_r['FG3A'] / _g:.1f} 3PA{_pct}")
            _verb = "takes" if len(_sh) == 1 else "take"
            _shoot = ((f"All {_W.get(len(_rows), len(_rows)).lower()} {_verb} threes: "
                       if len(_sh) == len(_rows) else
                       f"{_W.get(len(_sh), len(_sh))} of {_W.get(len(_rows), len(_rows)).lower()} {_verb} threes: ")
                      + ", ".join(_bits))
        # the shape, from the grouping the play-call table already carries (3G-2B = three guards, two bigs)
        _read = ""
        if grouping and "B" not in str(grouping).upper():
            _read = "Five out, no true big. " if len(_mem) == 5 else "No true big. "
        # and the one man on the offensive glass, when it really is one man
        _or = sorted(_rows, key=lambda x: -x[1]["OREB"])
        if _or and _or[0][1]["OREB"] / _g >= 1.0:
            _first, _second = _or[0][1]["OREB"], (_or[1][1]["OREB"] if len(_or) > 1 else 0)
            _only = _second <= _first / 3
            _read += (f"<b>{_sb_esc(_last(_or[0][0]))}</b> "
                      + ("is the only one on the glass" if _only else "leads the group on the glass")
                      + f" ({_first / _g:.1f} offensive boards a game).")
        return _shoot, _read.strip()

    def _lu_groupings(side):
        """{frozenset of normalised names: position shape} from the per-lineup play-call table."""
        _d = _sb_d("uww_lineup_play_calls")
        if _d.empty or not {"lineup", "grouping"} <= set(_d.columns):
            return {}
        if "side" in _d.columns:
            _d = _d[_d["side"] == side]
        if "scouted_opponent" in _d.columns:
            _d = _d[_d["scouted_opponent"].astype(str) == str(short)]
        return {frozenset(_norm(x) for x in re.split(r"[,/|]", str(r["lineup"])) if x.strip()):
                _sb_clean(r.get("grouping")) for _, r in _d.iterrows()}

    def _lu_two_way(side):
        """(offense clips, defense clips, team offense PPP, team defense PPP) for one side, once per card
        block -- the baselines a unit's own numbers are read against."""
        _o, _d = _unit_clips(side), _unit_clips_def(side)
        _p = lambda c: (c["_pts"].sum() / c["_pts"].notna().sum()) if (not c.empty and c["_pts"].notna().any()) else None
        return _o, _d, _p(_o), _p(_d)

    def _lu_cards(side, five_df):
        """Three cards for the five-man units and three for the trios: most minutes, best +/-, best points
        per possession. Always visible, with the full tables behind the expander under them (requested:
        the roster's shape). Every number comes from the same frames and the same clip matching the tables
        use, so a card and the row it stands for can never disagree. PPP needs 3+ tagged possessions, the
        same floor the table's PPP column ranks on; a card prints nothing when its number does not exist."""
        _clips = _unit_clips(side)
        _ppp5 = _five_ppp_map(side)
        _grp = _lu_groupings(side)
        _floor_min = 40.0 * (_side_games(side) or 1)   # a team is on the floor 40 minutes a game
        _oc, _dc, _team_off, _team_def = _lu_two_way(side)

        def _two_way(names, kind):
            """CONFIRMED CHANGE (requested 11/18): "Also include what each lineup has struggled with
            defensively and offensively", then "Make that based on which card is shown." Each card gets the
            side of the ball its own metric is about: the minutes card gets both, the +/- card leads with
            whichever end the margin came from, the PPP card stays on offense. Both numbers are points per
            tagged possession with those players on the floor -- their own offense, and what they gave up --
            against the same team's own rate. Under 5 possessions either way, nothing is said."""
            # CONFIRMED BUG (caught before shipping): with a 5-possession floor this printed "0.14 allowed
            # (team 0.61)" for Elmhurst. Their whole tagged pool is 38 offensive and 38 defensive possessions
            # with a lineup attached -- 0.61 allowed is not a defensive rate, it is a team whose film is
            # barely tagged, and a unit's slice of 38 is a handful of clips. The line needs a pool worth
            # reading (100+ possessions on that end) and a real slice of it (10+ for the unit). Ours clears
            # both -- 706 offensive and 564 defensive, 85 to 115 per unit -- so this shows for us now and for
            # an opponent once enough of their film is tagged, rather than inventing a number tonight.
            # 10 was still too few at the unit end: a four-minute five "allowed 0.31", which is four points
            # across a dozen possessions, not a defensive identity. 20 keeps the units a coach actually plans
            # for and drops the rest.
            _POOL, _UNIT = 100, 20
            _pool_o = int(_oc["_pts"].notna().sum()) if not _oc.empty else 0
            _pool_d = int(_dc["_pts"].notna().sum()) if not _dc.empty else 0
            _o, _on = _unit_ppp(_oc, names)
            _d, _dn = _unit_ppp(_dc, names)
            _ok_o = _o is not None and _on >= _UNIT and _pool_o >= _POOL
            _ok_d = _d is not None and _dn >= _UNIT and _pool_d >= _POOL
            if not (_ok_o or _ok_d):
                return ""
            _vs = lambda v, b: (f"{v:.2f}" + (f" (team {b:.2f})" if b is not None else ""))
            if kind == "ppp" or not _ok_d:
                return (f"Offense with them out there: {_vs(_o, _team_off)} a possession" if _ok_o else "")
            if not _ok_o:
                return f"Defense with them out there: {_vs(_d, _team_def)} allowed"
            if kind == "pm":
                # a tenth of a point either way is the difference worth naming; inside that, say so rather
                # than crediting an end that only wins after rounding
                _TOL = 0.05
                _dd = (_team_def - _d) if (_team_def is not None) else 0.0
                _od = (_o - _team_off) if (_team_off is not None) else 0.0
                _edge = ("the defense" if _dd >= _TOL and _dd >= _od
                         else "the offense" if _od >= _TOL else "")
                return ((f"That margin is {_edge}: " if _edge else "Neither end stands out: ")
                        + f"{_vs(_o, _team_off)} scored, {_vs(_d, _team_def)} allowed")
            return f"With them out there: {_vs(_o, _team_off)} scored, {_vs(_d, _team_def)} allowed"

        # CONFIRMED CHANGE (requested 11/19: "add a card for best clutch group for 5 and 3 man lineups"). The other
        # three cards rank a whole season of floor time; this one ranks the handful of possessions that decided games --
        # OUR clutch, the same rule as everywhere else (47's _gs_situation: not the first half, 5:00 or less, margin 8
        # or fewer). A group is judged on both ends, because a clutch five that scores and gives it straight back is not
        # the five to close with: points a possession with them on the floor MINUS points a possession they allowed. It
        # needs possessions at BOTH ends and _CL_MIN in total, so a group that only ever defended cannot win it.
        def _clutch_units(three):
            """{key: [off poss, points for, def poss, points against, display]} for this side's clutch possessions."""
            t = _pcc_all
            if t.empty or not {"game_situation", "side", "possession_side"} <= set(t.columns):
                return {}
            t = t[t["game_situation"].astype(str).str.startswith("Clutch") & (t["side"].astype(str) == side)]
            out = {}
            for _poss, _col, _i in (("Offense", "offense_lineup", 0), ("Defense", "defense_lineup", 2)):
                if _col not in t.columns:
                    continue
                for _, r_ in t[t["possession_side"].astype(str) == _poss].iterrows():
                    _nm = [x.strip() for x in str(r_.get(_col) or "").split(",") if x.strip()]
                    if len(_nm) < (3 if three else 5):
                        continue
                    _p = float(pd.to_numeric(pd.Series([r_.get("points")]), errors="coerce").fillna(0).iloc[0])
                    _groups = ([(_nm[a], _nm[b], _nm[c])
                                for a in range(len(_nm)) for b in range(a + 1, len(_nm)) for c in range(b + 1, len(_nm))]
                               if three else [tuple(_nm)])
                    for _g in _groups:
                        _k = frozenset(_norm(x) for x in _g)
                        _v = out.setdefault(_k, [0, 0.0, 0, 0.0, ", ".join(_g)])
                        _v[_i] += 1
                        _v[_i + 1] += _p
            return out

        def _clutch_card(three):
            _cu = _clutch_units(three)
            # CONFIRMED BUG (caught before shipping): with "a possession at each end" as the only floor, Elmhurst's
            # card read "+1.00 PPP net" off TWO offensive clutch possessions -- 2.00 scored is one three. Each end now
            # needs 3, the same floor the lineup tables' own PPP column ranks on, so a rate is never built on one play.
            # A team whose clutch film is barely tagged gets no card rather than a flattering one.
            _CL_END, _CL_MIN = 3, 8 if three else 6
            _CL_MARGIN_TXT = "eight points"
            _cand = [(k, v) for k, v in _cu.items()
                     if v[0] >= _CL_END and v[2] >= _CL_END and (v[0] + v[2]) >= _CL_MIN]
            if not _cand:
                # CONFIRMED CHANGE (requested 11/19: "leave the card empty and note that there isn't a 5 man
                # lineup"). Returning "" left a hole in the row with nothing to explain it, and a missing card
                # looks the same as a team with no clutch film at all. The card now prints and says which it is,
                # with the nearest group's own counts so the gap is countable rather than asserted. Hope are the
                # case that found this: 19 clutch possessions, only 4 of them with the ball, so their busiest
                # five has 2 and 5 -- a five-man card would be a rate off two possessions.
                _unit = "trio" if three else "five"
                if not _cu:
                    _why = ("No clutch possessions of theirs are on film yet \u2014 their games on file were "
                            "never inside " + str(_CL_MARGIN_TXT) + " in the last five minutes, or are untagged.")
                    _near = ""
                else:
                    _bk, _bv = max(_cu.items(), key=lambda kv: (kv[1][0] + kv[1][2], kv[1][0]))
                    _why = (f"No {_unit} has {_CL_END} clutch possessions at each end yet, so a rate here would "
                            f"rest on one or two plays.")
                    _near = (f'<div class="lc-x">Closest: {_sb_esc(_lu_short(_bv[4], 3 if three else 5))} '
                             f'\u2014 {_bv[0]} with the ball, {_bv[2]} defending.</div>')
                return (f'<div class="lc lc-empty"><div class="lc-t">Best in the clutch</div>'
                        f'<div class="lc-n">No {_unit} qualifies</div>'
                        f'<div class="lc-s">{_sb_esc(_why)}</div>' + _near
                        + '<div class="lc-x">Needs 3 clutch possessions at each end \u2014 scored and allowed '
                          'are both part of the ranking.</div></div>')
            _net = lambda v: v[1] / v[0] - v[3] / v[2]      # noqa: E731
            _k, _v = max(_cand, key=lambda kv: (_net(kv[1]), kv[1][0] + kv[1][2]))
            _o, _d, _n = _v[1] / _v[0], _v[3] / _v[2], _v[0] + _v[2]
            _shoot, _read = _lu_read(side, _v[4], _grp.get(_k, ""))
            return (f'<div class="lc"><div class="lc-t">Best in the clutch</div>'
                    f'<div class="lc-n">{_sb_esc(_lu_short(_v[4], 3 if three else 5))}</div>'
                    f'<div class="lc-v">{_net(_v):+.2f} PPP net ({_n} Poss)</div>'
                    f'<div class="lc-s">{_o:.2f} PPP scored \u00b7 {_d:.2f} PPP allowed</div>'
                    f'<div class="lc-s">{_v[0]} with the ball \u00b7 {_v[2]} defending</div>'
                    + (f'<div class="lc-x">{_shoot}</div>' if _shoot else "")
                    + '<div class="lc-x">Last 5 min, margin &le; 8 \u2014 every clutch possession on film, '
                      'both ends.</div></div>')

        def _rows(df, min_col, pm_col, three):
            d = df.copy()
            d["_m"] = pd.to_numeric(d[min_col], errors="coerce").fillna(0)
            d["_p"] = pd.to_numeric(d[pm_col], errors="coerce").fillna(0)
            d = d[d["_m"] > 0]
            if d.empty:
                return d
            _key = lambda v: frozenset(_norm(x) for x in re.split(r"[,/|]", str(v)) if x.strip())
            _pp, _nn = [], []
            for _l in d["lineup"]:
                if three:
                    _v, _k = _unit_ppp(_clips, _key(_l))
                else:
                    _v, _k = _ppp5.get(_key(_l)) or (None, 0)
                _pp.append((_v if (_k or 0) >= 3 else None))
                _nn.append(_k or 0)
            d["_ppp"], d["_npos"] = _pp, _nn
            return d

        def _cards(d, label, floor, three=False):
            """CONFIRMED CHANGE: the cards rank only units that clear the same minutes floor the tables below
            them use -- without it, "Best +/-" and "Best PPP" both landed on a five-man unit that played FOUR
            minutes (+9, 1.71), which is the small-sample trap every other ranking in this file guards
            against. If nothing clears the floor the best of what there is shows with a *, the same
            convention the lineup tables use for a unit shown below their floor."""
            if d.empty:
                _cl0 = _clutch_card(three)
                if _cl0:
                    add(f'<div class="lc-lab">{_sb_esc(label)}</div>')
                    add('<div class="lcards">' + _cl0 + "</div>")
                return
            _thin = d["_m"] < floor
            d = d.copy()
            d["_star"] = _thin
            if (~_thin).any():
                d = d[~_thin]
            _g = _side_games(side) or 1
            _pg = lambda r: r["_m"] / _g       # noqa: E731  (minutes per game, as the tables now show)
            _picks = [("Most minutes", "_m", lambda r: f'{_pg(r):.1f} Min/G', "min"),
                      ("Best +/-", "_p", lambda r: f'{r["_p"]:+.0f} in {_pg(r):.1f} Min/G', "pm"),
                      ("Best points per possession", "_ppp", lambda r: f'{r["_ppp"]:.2f} PPP', "ppp")]
            # CONFIRMED CHANGE (requested 11/18): "Don't dynamically group the top lineups by MIN, +/-, and
            # PPP even if they are the same lineups. List all three of them separately." So three cards, in
            # that order, always -- one unit topping two or three columns simply appears on each of them.
            _out = []
            for _ttl, _col, _fmt, _kind in _picks:
                _c = pd.to_numeric(d[_col], errors="coerce")
                if not _c.notna().any():
                    continue
                _r = d.loc[_c.idxmax()]
                _key_l = frozenset(_norm(x) for x in re.split(r"[,/|]", str(_r["lineup"])) if x.strip())
                _shoot, _read = _lu_read(side, _r["lineup"], _grp.get(_key_l, ""))
                # CONFIRMED CHANGE (requested 11/18): the share of floor time belongs with the minutes, not
                # in the card's title, and the margin and PPP get a line of their own under it.
                _share = f'{100 * _r["_m"] / _floor_min:.0f}% of {"our" if side == "UWW" else "their"} floor time'
                _out.append(f'<div class="lc"><div class="lc-t">{_sb_esc(_ttl)}</div>'
                            f'<div class="lc-n">{_sb_esc(_lu_short(_r["lineup"]))}'
                            + ('<span class="thin-ast">*</span>' if _r.get("_star") else "") + "</div>"
                            f'<div class="lc-v">{_sb_esc(_fmt(_r))}</div>'
                            f'<div class="lc-s">{_pg(_r):.1f} Min/G \u00b7 {_sb_esc(_share)}</div>'
                            # no possession counts in the brief's visible text (requested 11/18); the
                            # 3-possession floor still decides whether a PPP is ranked on at all
                            + f'<div class="lc-s">{_r["_p"]:+.0f} +/-'
                            + (f' \u00b7 {_r["_ppp"]:.2f} PPP' if pd.notna(_r["_ppp"]) else "") + "</div>"
                            # who shoots it, and what the group is -- requested 11/18, combining the two
                            # lines Corey picked out of the mock-ups
                            + (f'<div class="lc-x">{_shoot}</div>' if _shoot else "")
                            + (f'<div class="lc-x">{_read}</div>' if _read else "")
                            + (lambda _tw: f'<div class="lc-x">{_tw}</div>' if _tw else "")(
                                _two_way({_norm(x) for x in re.split(r"[,/|]", str(_r["lineup"])) if x.strip()},
                                         _kind))
                            + "</div>")
            _cl = _clutch_card(three)
            if _cl:
                _out.append(_cl)
            if _out:
                add(f'<div class="lc-lab">{_sb_esc(label)}</div>')
                add('<div class="lcards">' + "".join(_out) + "</div>")
                if any('class="thin-ast"' in x for x in _out):
                    add(f'<p class="mini"><span class="thin-ast">*</span> under '
                        f'{floor / _g:.1f} Min/G together ({floor:.0f} minutes in all) -- nothing on file '
                        "clears that bar yet, so read these as what little there is.</p>")

        _clean = side == "UWW" and {"clean_min", "clean_pm"}.issubset(five_df.columns)
        _cards(_rows(five_df, "clean_min" if _clean else "MIN", "clean_pm" if _clean else "+/-", False),
               "Five-man units", LINEUP_TABLE_RULES["five_min_minutes"])
        _c3 = _sb_d("uww_three_man_combos")
        if not _c3.empty and {"lineup", "side"} <= set(_c3.columns):
            _c3 = _c3[_c3["side"] == side]
            if "scouted_opponent" in _c3.columns:
                _c3 = _c3[_c3["scouted_opponent"].astype(str) == str(short)]
            if not _c3.empty:
                _c3clean = side == "UWW" and {"clean_min", "clean_pm"}.issubset(_c3.columns)
                _cards(_rows(_c3, "clean_min" if _c3clean else "MIN", "clean_pm" if _c3clean else "+/-", True),
                       "3-man combos",
                       LINEUP_TABLE_RULES["uww_three_min_minutes" if side == "UWW" else "opp_three_min_minutes"],
                       three=True)

    def combos_table(side):
        """Top three 3-man combos (alongside the five-man units).

        UWW's own combos are sorted by PPP with a minutes-per-game floor (requested) -- the opponent's stay
        sorted by minutes, since we're not trying to pick their best combo to run, just show what's real.
        Same table the Keys to Victory's combo keys are built from (uww_three_man_combos, exported by the
        KTV cell), so a combo named in a key and the combo shown here can never disagree. PPP and "What they
        run" come from tagged possessions with all three on the floor; per-100 margin is shown next to raw
        +/- because a trio's minutes vary far more than a five's, and raw +/- mostly measures playing time.
        """
        df = _sb_d("uww_three_man_combos")
        if df.empty or "lineup" not in df.columns or "side" not in df.columns:
            return False
        df = df[df["side"] == side]
        if "scouted_opponent" in df.columns:
            df = df[df["scouted_opponent"].astype(str) == str(short)]
        if df.empty:
            return False
        df = df.assign(_min=pd.to_numeric(df["MIN"], errors="coerce"),
                       _pm=pd.to_numeric(df["+/-"], errors="coerce"))
        _gp_exact = bool(df["gp_exact"].astype(str).str.lower().eq("true").all()) if "gp_exact" in df.columns else True

        # Tagged possessions with all three on the floor -- offensive possessions only, matched on
        # normalised names so "Jake Quast" and "JAKE QUAST" count as the same player.
        _clips = _unit_clips(side)

        def _combo_detail(lineup_str):
            """(ppp, n tagged possessions, "what they run" text) for one trio, computed once and reused by
            both the PPP-sort above and the row rendering below -- no duplicate clip-matching."""
            _trio = {_norm(x) for x in str(lineup_str).split(",") if x.strip()}
            if _clips.empty or len(_trio) != 3:
                return None, 0, "--"
            _on = _unit_on(_clips, _trio)
            _ppp, _k = _unit_ppp(_clips, _trio)
            _run = "--"
            if not _on.empty and "play_call" in _on.columns:
                _vc = (_on["play_call"].dropna().astype(str)
                       .loc[lambda x: ~x.str.contains("unspecified", na=False)].value_counts())
                if len(_vc):
                    _run = ", ".join(f"{n} ({int(c)}x)" for n, c in _vc.head(2).items())
            return _ppp, _k, _run

        # CONFIRMED CHANGE (requested 11/18): "The 3 man lineup table should be formatted similar to the 5 man
        # lineup with the top 2 of each of the 3 metrics." It used to rank every trio by shrunk margin per 40
        # and print the best three. Now it is picked the way lineups_table picks fives: the top 2 in MINUTES,
        # in +/- and in PPP, each unit listed once however many columns it tops, with its top-2 values bold.
        R = LINEUP_TABLE_RULES
        _clean3 = side == "UWW" and {"clean_min", "clean_pm"}.issubset(df.columns)
        d = df.copy()
        d["_rmin"] = pd.to_numeric(d["clean_min" if _clean3 else "MIN"], errors="coerce").fillna(0)
        d["_rpm"] = pd.to_numeric(d["clean_pm" if _clean3 else "+/-"], errors="coerce").fillna(0)
        d = d[d["_rmin"] > 0].copy()
        if _clean3:
            # the "Feature the ... combo" key's own bar, kept: games played, and on/off positive
            _el = pd.to_numeric(d.get("clean_gp"), errors="coerce").fillna(0) >= R["uww_three_min_games"]
            if "on_off" in d.columns:
                _el &= pd.to_numeric(d["on_off"], errors="coerce").fillna(-999) > R["uww_three_min_on_off"]
            if _el.any():
                d = d[_el]
        if d.empty:
            return False
        d["_per40"] = d["_rpm"] / d["_rmin"] * 40
        _det = {str(l): _combo_detail(l) for l in d["lineup"]}
        d["_ppp"] = [pd.to_numeric(pd.Series([_det[str(l)][0]]), errors="coerce").iloc[0] for l in d["lineup"]]
        d["_pn"] = [_det[str(l)][1] for l in d["lineup"]]
        # trios cut from one five that only ever played together have identical numbers: show the first and
        # say how many share it, rather than near-duplicate rows (the old _rank_units collapse_twins)
        _sig = d["_rmin"].round(2).astype(str) + "|" + d["_rpm"].round(2).astype(str)
        d["_twins"] = _sig.map(_sig.value_counts()) - 1
        d = d[~_sig.duplicated()]
        _floor3 = R["uww_three_min_minutes"] if side == "UWW" else R["opp_three_min_minutes"]
        d["_below"] = d["_rmin"] < _floor3
        _big3 = d[~d["_below"]] if (~d["_below"]).sum() >= 2 else d
        _picks3 = [("_rmin", d), ("_rpm", d), ("_ppp", d[pd.to_numeric(d["_pn"], errors="coerce").fillna(0) >= 3])]
        _bold3, _order3 = {}, []
        for _col, _pool in _picks3:
            _pool = _pool[_pool[_col].notna()]
            for _ix in _pool.sort_values([_col, "_rmin"], ascending=[False, False]).index[:2]:
                _bold3.setdefault(_ix, set()).add(_col)
                if _ix not in _order3:
                    _order3.append(_ix)
        if not _order3:
            return False
        top = d.loc[_order3]
        _B3 = lambda ix, col, txt: f"<b>{txt}</b>" if col in _bold3.get(ix, set()) else txt  # noqa: E731

        add('<table class="compact"><thead><tr><th style="text-align:left">Combo</th>'
            + ("<th>GP</th>" if _gp_exact else "")
            + f"<th>{_min_head(side)}</th><th>+/-</th><th>per 40</th><th>PPP</th>"
            + '<th style="text-align:left">What they run</th></tr></thead><tbody>')
        for _ix, u in top.iterrows():
            _run = _det[str(u["lineup"])][2]
            _ppp, _k = u["_ppp"], u["_pn"]
            _ppp_cell = (f'<td title="{int(_k)} tagged possessions">{_B3(_ix, "_ppp", _sb_fmt(_ppp, 2))}</td>'
                         if pd.notna(_ppp) else '<td class="mini">--</td>')
            _twin_txt = (f' <span class="mini">(+{int(u["_twins"])} identical)</span>' if u["_twins"] > 0 else "")
            add(f'<tr><td class="wrap" title="{_sb_esc(str(u["lineup"]))}">{_sb_esc(_lu_short(u["lineup"], 3))}'
                f'{_twin_txt}</td>'
                + (f'<td>{_sb_fmt(u.get("GP"), 0)}</td>' if _gp_exact else "")
                + (lambda _pg, _tot: f'<td title="{_tot:.1f} minutes in all">'
                     f'{_B3(_ix, "_rmin", _sb_fmt(_pg))}{"*" if u["_below"] else ""}</td>')(*_min_pg(side, u["_rmin"]))
                + f'<td>{_B3(_ix, "_rpm", _signed(u["_rpm"], 0))}</td>'
                + f'<td>{_signed(u["_per40"])}</td>'
                + _ppp_cell
                + f'<td class="wrap mini">{_sb_esc(_run)}</td></tr>')
        add("</tbody></table>")
        return True

    # Reconciliation-only now (requested: the "shows its top set..." explanation moved to a visible line
    # under each section header instead of staying a footnote -- see the description added right after
    # section() in the offense sections below). This one stays a footnote: it's a caveat about missing
    # data, not a description of what's shown.
    _SERIES_PIVOT_NOTE = (
        "Not every tagged possession in HOW {OPP} RUNS OFFENSE or HOW WE RUN OFFENSE ran a named set -- some "
        "are tagged with the situation only (untagged, flagged for rewatch, or the title named only a player). "
        "The full list of named sets and their clips is in the app.")

    def _film_clip_lookup():
        """normalized set name -> clip count, from uww_film_clips -- only ever populated for the Opponent
        side (see the game-plan cell). Used to badge the matching rows in HOW {OPP} RUNS OFFENSE instead of
        listing them again in their own FILM SESSION section (requested). clip_group arrives as
        "Set Name (Situation)"; the situation is dropped and counts are summed, so a set tagged in more than
        one situation badges with its full clip count wherever it appears."""
        df, _ = staff_rows("uww_film_clips")
        out = {}
        if df.empty or "clip_group" not in df.columns:
            return out
        for _, r in df.iterrows():
            _group = _sb_clean(r.get("clip_group"))
            m = re.match(r"^(.*) \((.*)\)$", _group)
            _name = m.group(1) if m else _group
            if not _name:
                continue
            out[_norm(_name)] = out.get(_norm(_name), 0) + int(pd.to_numeric(r.get("clips"), errors="coerce") or 0)
        return out


    _CLOCK_ORDER = ["Early clock (0-9 sec used)", "Organized offense (10-19 sec used)", "Late clock (20+ sec used)"]
    _SIT_ORDER = ["Leading by 10+", "Trailing by 10+", "Clutch (last 5 min, margin \u2264 8)"]

    # =====================================================================================================
    # PAGE 1 -- GAME PLAN
    # =====================================================================================================
    lede = []
    if them.get("games"):
        lede.append(f"Scoring {_sb_fmt(them.get('PTS'))} a game and allowing {_sb_fmt(them_allowed.get('PTS'))}, "
                    f"over {int(them['games'])} game{'s' if them['games'] != 1 else ''} of film.")
    if not players.empty:
        _tg = int(them.get("games") or players["games"].max() or 1)
        _regular = players[players["games"] >= max(1, 0.5 * _tg)].sort_values("PTS_total", ascending=False)
        _team_pts_total = float(players["PTS_total"].sum()) or None
        if not _regular.empty:
            top = _regular.iloc[0]
            share = round(100 * float(top["PTS_total"]) / _team_pts_total) if _team_pts_total else None
            lede.append(f"{top['name']} leads them at {_sb_fmt(top['PTS'])} a night"
                        + (f" \u2014 {share}% of their points on film." if share else "."))
            if len(_regular) > 1:
                second = _regular.iloc[1]
                lede.append(f"{second['name']} is the next threat at {_sb_fmt(second['PTS'])} "
                            f"({_sb_fmt(second['REB'])} reb, {_sb_fmt(second['AST'])} ast).")
    if them.get("3P%") is not None and them.get("3PA") is not None:
        lede.append(f"They shoot {_sb_fmt(them['3P%'])}% from three on {_sb_fmt(them['3PA'])} attempts a game.")
    # Pace moved out of its own section (requested) -- the full tempo table stays in the app. It earns a
    # Bottom Line sentence only when it would change preparation; the thresholds are BOTTOM_LINE_RULES at
    # the top of this cell, and the sentence carries a note stating them so the staff can see the rule.
    _R = BOTTOM_LINE_RULES
    _tp, _tp_sample = staff_rows("uww_tempo_profile")
    if not _tp.empty and not _tp_sample and {"opponent", "metric", "value"}.issubset(_tp.columns):
        def _tv(team, metric):
            _r = _tp[(_tp["opponent"].astype(str) == str(team)) & (_tp["metric"].astype(str) == metric)]
            return pd.to_numeric(_r["value"].iloc[0], errors="coerce") if not _r.empty else None
        _their_pace = _tv(short, "Possessions per game")
        _our_pace = _tv("UW-Whitewater", "Possessions per game")
        _early = _tv(short, "Early-offense share")
        _bits = []
        if _their_pace is not None and _our_pace is not None and pd.notna(_their_pace) and pd.notna(_our_pace) \
                and abs(_their_pace - _our_pace) >= _R["tempo_pace_gap"]:
            _bits.append(f"they play {'faster' if _their_pace > _our_pace else 'slower'} than we do "
                         f"({_their_pace:.0f} possessions a game to our {_our_pace:.0f})")
        if _early is not None and pd.notna(_early) and _early >= _R["tempo_early_share"]:
            _bits.append(f"{_early:.0f}% of their tagged possessions shoot inside 10 seconds, so transition "
                         "defense needs its own work")
        if _bits:
            lede.append("Tempo: " + "; ".join(_bits) + ".")
    # Four Factors no longer gets its own table (requested) -- call out the biggest weighted gap here instead,
    # but only when it's genuinely decisive: the top factor's weighted edge has to clear both an absolute floor
    # (so a game with four small, similar factors stays quiet) and a relative one (at least double the next
    # factor, so it reads as THE story, not just nominally first).
    if _ff_top is not None and len(_ff_rows) > 1:
        _ff_second = _ff_rows[1]
        _ff_others_sum = sum(abs(r["weighted"]) for r in _ff_rows[1:])
        if (abs(_ff_top["weighted"]) >= BOTTOM_LINE_RULES["ff_min_weighted"]
                and abs(_ff_top["weighted"]) >= BOTTOM_LINE_RULES["ff_dominance"] * abs(_ff_second["weighted"])):
            _whose = "our" if _ff_top["edge"] > 0 else f"{_sb_clean(opp_display)}'s"
            _tail = (", more than the other three factors combined."
                     if abs(_ff_top["weighted"]) > _ff_others_sum
                     else f", well clear of the next-largest factor ({_ff_second['factor']}, "
                          f"{_ff_second['weighted']:+.2f}).")
            lede.append(f"The clearest statistical edge is {_ff_top['factor']} \u2014 {_whose} edge "
                        f"(UWW {_ff_top['uww']:.1f} vs {_ff_top['opp']:.1f}), a {_ff_top['edge']:+.1f} point gap "
                        f"worth {_ff_top['weighted']:+.2f} weighted" + _tail)

    # ---- Rebounding: only when lopsided (REBOUND_RULES, shared with the key and the roster read) -------
    _RR = globals().get("REBOUND_RULES") or {"min_paired": 20, "crash_rate": 35, "soft_rate": 65,
                                              "player_share": 35, "player_min": 5}
    _rs = _sb_d("uww_rebound_summary")
    if not _rs.empty and "opponent" in _rs.columns:
        _rs = _rs[_rs["opponent"].astype(str) == str(short)]
    _reb_bits = []
    if not _rs.empty and "metric" in _rs.columns:
        def _rv(metric):
            _r = _rs[_rs["metric"] == metric]
            return _r.iloc[0] if not _r.empty else None
        _o, _d = _rv("their_oreb_pct"), _rv("their_dreb_pct")
        _our_dreb_base = _rv("our_dreb_allowed_base")
        _our_oreb_base = _rv("our_oreb_base")
        if _o is not None and int(_o["paired"]) >= _RR["min_paired"] and float(_o["value"]) >= _RR["crash_rate"]:
            _top = _rs[_rs["metric"] == "their_oreb_player"].sort_values("count", ascending=False)
            # "Is 38% a lot?" (requested) -- compared against what we usually allow ourselves, from our own
            # season's play-by-play, not a bare percentage with nothing to judge it against.
            _vs = (f" (we usually allow {float(_our_dreb_base['value']):.0f}%)" if _our_dreb_base is not None else "")
            _reb_bits.append(f"they grab {float(_o['value']):.0f}% of their own misses{_vs}"
                             + (f", {_sb_title(_top.iloc[0]['player'])} the most ({int(_top.iloc[0]['count'])})"
                                if not _top.empty else ""))
        if _d is not None and int(_d["paired"]) >= _RR["min_paired"] and float(_d["value"]) <= _RR["soft_rate"]:
            _vs2 = (f" (we usually get {float(_our_oreb_base['value']):.0f}%)" if _our_oreb_base is not None else "")
            _reb_bits.append(f"they secure only {float(_d['value']):.0f}% of opponents' misses{_vs2}, so our "
                             "misses are live balls")
    if _reb_bits:
        lede.append("Rebounding: " + "; ".join(_reb_bits) + ".")

    # ---- Style matchups: only when the record is lopsided, on enough games, at real confidence ---------
    _sm = _sb_d("uww_style_matchups")
    if not _sm.empty and {"opponent", "direction", "dir_wins", "dir_losses", "confidence"}.issubset(_sm.columns):
        _sm = _sm[_sm["opponent"].astype(str) == str(short)]
        for _dir in ("like_them", "like_us"):
            _g = _sm[_sm["direction"] == _dir]
            if _g.empty:
                continue
            _w = pd.to_numeric(_g["dir_wins"], errors="coerce").iloc[0]
            _l = pd.to_numeric(_g["dir_losses"], errors="coerce").iloc[0]
            _conf = pd.to_numeric(_g["confidence"], errors="coerce").max()
            if pd.isna(_w) or pd.isna(_l) or pd.isna(_conf):
                continue
            _n = int(_w) + int(_l)
            _share = (_w / _n) if _n else 0.5
            if (_n < BOTTOM_LINE_RULES["style_min_games"] or _conf < BOTTOM_LINE_RULES["style_min_confidence"]
                    or (1 - BOTTOM_LINE_RULES["style_lopsided"]) < _share < BOTTOM_LINE_RULES["style_lopsided"]):
                continue
            _teams = ", ".join(_sb_strip_mascot(t) for t in _g.sort_values("rank")["team"].head(3))
            _pf = pd.to_numeric(_g["dir_pf"], errors="coerce").iloc[0] if "dir_pf" in _g.columns else None
            _pa = pd.to_numeric(_g["dir_pa"], errors="coerce").iloc[0] if "dir_pa" in _g.columns else None
            _sc = f", averaging {_pf:.0f}-{_pa:.0f}" if _pf is not None and _pa is not None and pd.notna(_pf) \
                and pd.notna(_pa) else ""
            if _dir == "like_them":
                lede.append(f"Against teams that play like them ({_teams}) we're {int(_w)}-{int(_l)}{_sc}.")
            else:
                lede.append(f"Teams that play like us ({_teams}) went {int(_w)}-{int(_l)} against them{_sc}.")
    # Read-with-caution items are rendered at the very END of the brief (requested) -- they qualify numbers
    # throughout, so they read better as a closing caveat than as a wall of warnings on the game-plan page.
    _warn_df, _ = staff_rows("uww_sample_size_warnings")

    _SB_SOURCE_COLORS = {"Data-Driven": "#37474f", "Keys to Victory": "#4E2A84", "Team Strengths": "#c62828",
                         "Lineup Scouting": "#5d4037", "Coach Notes": "#00695c", "Game Plan": "#FF6B6B"}

    def source_badge(source):
        source = _sb_clean(source)
        if not source:
            return ""
        color = _SB_SOURCE_COLORS.get(source, "#666")
        return f' <span class="src" style="border-color:{color};color:{color};">{_sb_esc(source)}</span>'

    ktv = _sb_d("uww_ktv_keys")
    if not ktv.empty and "opponent" in ktv.columns:
        ktv = ktv[ktv["opponent"].astype(str) == str(short)]
        if "key_number" in ktv.columns:
            ktv = ktv.sort_values("key_number")

    # --- Synthesize key insights from THE BOTTOM LINE into KEYS TO VICTORY ---
    # If information was important enough for THE BOTTOM LINE (conditional or core), it belongs in KEYS TO VICTORY
    _synthesized_keys = []
    _next_key_number = int(ktv["key_number"].max()) + 1 if not ktv.empty and "key_number" in ktv.columns else 1

    # Map lede items to synthesized keys with appropriate categories
    if lede:
        # Extract the insights that came from conditions (these are the ones most worth highlighting)
        for _lede_item in lede:
            _item_text = _lede_item[0] if isinstance(_lede_item, tuple) else _lede_item
            _category = "General"
            _headline = None

            # Categorize and shorten the lede insight for KTV display
            if "Tempo:" in _item_text:
                _category = "Offense"
                _headline = "Tempo adjustment: " + _item_text.replace("Tempo: ", "").rstrip(".")
            elif "Four Factors" in _item_text or "statistical edge" in _item_text:
                _category = "Defense" if "edge" in _item_text.lower() else "Offense"
                # Extract just the factor name and which team's edge
                if "—" in _item_text:
                    _factor_part = _item_text.split("—")[1].split("(")[0].strip()
                    _headline = f"Focus on {_factor_part.lower()}"
                else:
                    _headline = "Key statistical edge"
            elif "Rebounding:" in _item_text:
                _category = "Defense"
                _headline = "Rebounding edge: " + _item_text.replace("Rebounding: ", "").rstrip(".")
            elif "teams that play" in _item_text.lower():
                _category = "General"
                _headline = "Style matchup: " + _item_text.rstrip(".")
            elif "shoot" in _item_text.lower() and "three" in _item_text.lower():
                _category = "Defense"
                _headline = "Monitor three-point shooting"
            elif "leads them" in _item_text.lower() or "threat at" in _item_text.lower():
                _category = "Personnel"
                _headline = _item_text.rstrip(".")
            elif "Scoring" in _item_text and "allowing" in _item_text:
                _category = "General"
                _headline = "Scoring/pace context"

            if _headline and len(_headline) > 8:
                # Edge size for the priority model: their top scorer and a Four Factors edge are the
                # biggest game-plan items; a bare scoring/pace summary is context, not a key.
                if _category == "Personnel" or _headline.startswith("Focus on"):
                    _gp_impact = 0.7
                elif _headline.startswith("Monitor three"):
                    _gp_impact = 0.6
                elif _headline.startswith("Style matchup"):
                    _gp_impact = 0.4
                else:
                    _gp_impact = 0.5
                _synthesized_keys.append({
                    "key_number": _next_key_number,
                    "opponent": str(short),
                    "headline": _headline,
                    "category": _category,
                    "source": "Game Plan",
                    "impact": _gp_impact,
                    "confidence": 0.6,
                    "brief_eligible": _headline != "Scoring/pace context",
                })
                _next_key_number += 1

    # Append synthesized keys to the ktv dataframe
    if _synthesized_keys:
        _synth_df = pd.DataFrame(_synthesized_keys)
        ktv = pd.concat([ktv, _synth_df], ignore_index=True) if not ktv.empty else _synth_df
        ktv = ktv.sort_values("key_number") if "key_number" in ktv.columns else ktv

    # Only the highest-priority keys go on the brief (KTV_BRIEF_RULES / ktv_select_for_brief, defined in the
    # key-building cell). The app still shows every key from uww_ktv_keys.csv.
    _ktv_total = len(ktv)
    _ktv_select = globals().get("ktv_select_for_brief")
    ktv_brief = _ktv_select(ktv) if (_ktv_select and not ktv.empty) else ktv
    _KBR = globals().get("KTV_BRIEF_RULES") or {"min_score": 55, "max_keys": 6}

    if not ktv_brief.empty:
        # How the data-driven keys that pick PEOPLE are chosen, stated from the same settings the parser
        # uses (COMBO_RULES, REBOUND_RULES), so the explanation can't drift from what the code does.
        _CRn = globals().get("COMBO_RULES") or {"garbage_margin": 15, "garbage_from_period": 2, "min_minutes": 40,
                                                "min_games": 3, "shrink_minutes": 40, "min_on_off": 0.0}
        _RRn = globals().get("REBOUND_RULES") or {"min_paired": 20, "crash_rate": 35, "soft_rate": 65}
        section("\U0001f511 KEYS TO VICTORY" + footnote(
            f"The brief shows the {len(ktv_brief)} highest-priority of {_ktv_total} keys; every key is on the "
            "app. Each key is scored 0-100: who says so (staff-written keys score highest), how big the edge "
            "is, how much data backs it, and whether it is an instruction. Keys scoring "
            f"{_KBR['min_score']}+ are shown, best first, up to {_KBR['max_keys']}, one per topic. "
            "Keys are built by the parser into uww_ktv_keys.csv and rendered identically by the app. Each key's "
            "evidence (the numbers behind it) and full reasoning are on the app's Keys to Victory tab -- click a "
            "key to open it there. "
            "HOW \"FEATURE THE ... COMBO\" IS CHOSEN: every 3-player group from our lineup stints, counting "
            f"competitive minutes only -- a stint that starts in the 2nd half or OT with the margin at "
            f"{_CRn['garbage_margin']}+ is garbage time and set aside. A trio needs {_CRn['min_minutes']}+ "
            f"competitive minutes across {_CRn['min_games']}+ games. It is ranked by scoring margin per 40 "
            f"minutes, shrunk toward zero as if {_CRn['shrink_minutes']} more minutes of an even game were added, "
            "so a short hot streak can't top the list. It must also be on/off positive: we do better with those "
            "three on the floor than with them off, which separates the trio from whoever else was out there. "
            "If no trio clears all of that, there is no combo key -- a missing key means none qualified yet, not "
            "that it wasn't checked. When the top trio has numbers identical to other trios (they only ever played "
            "together as one group), no single trio can be singled out, so the key names the whole group as a "
            "\"unit\" instead. Season-wide, not specific to this opponent. "
            f"REBOUNDING KEYS: \"box out\" when they rebound {_RRn['crash_rate']}%+ of their own misses, \"crash "
            f"the glass\" when they secure {_RRn['soft_rate']}% or less of opponents' misses, each on "
            f"{_RRn['min_paired']}+ paired misses from their play-by-play."))
        # CONFIRMED CHANGE (requested 11/18: "create a card style format for the KEYS TO VICTORY section"). The keys
        # were a list of numbered sentences; they are now the same cards the rest of the brief uses (lcards / lc), three
        # to a row, with the key's number and its score + source badge on the top strip, the instruction in bold and the
        # reasoning underneath. BRIEF_KTV_CARDS = False goes back to the sentence list. Nothing about WHICH keys are
        # shown, their order, their links or their scoring changes -- this is the layout only.
        _ktv_cards = bool(globals().get("BRIEF_KTV_CARDS", True))
        # CONFIRMED CHANGE (requested 11/19: "I want the Keys to Victory cards to better match the Keys to Victory
        # section in the application. So maybe three cards for Offense, Defense and Personnel, Rotation &
        # Intangibles"). One row, three cards, by the SAME `category` column the app groups on -- so a coach reading
        # the brief and a coach reading the app see the keys sorted the same way. Each card leads with its group's
        # best-scoring key and lists the rest under it; "Personnel, rotation & intangibles" takes Personnel and
        # anything with no category of its own (General), which is how the app's own "Other" bucket behaves.
        # BRIEF_KTV_KEYS_PER_CARD (4) caps a card; the rest are a "+N more below" line, and every key is in the
        # expander underneath either way. BRIEF_KTV_CARDS = False still gives the old numbered sentences.
        _ktv_row = max(1, int(globals().get("BRIEF_KTV_CARDS_MAX", 5)))         # the sentence path's own cap
        _KTV_PER = max(1, int(globals().get("BRIEF_KTV_KEYS_PER_CARD", 4)))
        _KTV_GROUPS = (("Offense", lambda c: c == "offense"),
                       ("Defense", lambda c: c == "defense"),
                       ("Personnel, rotation &amp; intangibles", lambda c: c not in ("offense", "defense")))

        def _ktv_key_html(k):
            """(headline as a link where the app has the key, its score + source badge)."""
            _h = _sb_clean(k.get("headline")).rstrip(".")
            _ak = int(k["key_number"]) if pd.notna(k.get("key_number")) else None
            _hh = (name_link(_h, page="upcoming", tab="keys", key=_ak)
                   if _ak and str(k.get("source")) != "Game Plan" else _sb_esc(_h))
            _p = pd.to_numeric(k.get("priority_score"), errors="coerce")
            _sc = (f'<span class="ktv-score" title="Priority score (0-100)">{int(round(_p))}</span>'
                   if pd.notna(_p) else "")
            return _hh, _sc + (source_badge(k.get("source")) or "")

        _ktv_on_card = set()
        if _ktv_cards:
            _kk = ktv.copy()
            _kk["_ps"] = pd.to_numeric(_kk.get("priority_score"), errors="coerce")
            _kk["_cat"] = _kk.get("category", pd.Series("", index=_kk.index)).astype(str).str.strip().str.lower()
            _kk = _kk.sort_values("_ps", ascending=False, na_position="last")
            _cards_out = []
            for _gname, _gtest in _KTV_GROUPS:
                _g = _kk[_kk["_cat"].map(_gtest)]
                if _g.empty:
                    continue
                _shown = _g.head(_KTV_PER)
                _ktv_on_card |= {str(x) for x in _shown.get("key_number", pd.Series(dtype=object)).dropna().astype(str)}
                # CONFIRMED CHANGE (requested 11/19): under the lead key goes its REASONING -- "They get 46% of their
                # own misses back -- a stop isn't a stop until we secure the rebound; find Orion Yant on every shot"
                # -- not its score and source tag. The number and the tag say where a key came from; the reasoning
                # says what to do about it, which is what a coach reads a card for. Both are still in the table below.
                _lead, _lead_badge = _ktv_key_html(_shown.iloc[0])
                _lead_why = (_sb_clean(_shown.iloc[0].get("reasoning")).rstrip(".")
                             or _sb_clean(_shown.iloc[0].get("evidence")).rstrip("."))
                _rest = "".join(f'<div class="lc-x ktv-more">{_ktv_key_html(r_)[0]}</div>'
                                for _, r_ in _shown.iloc[1:].iterrows())
                # CONFIRMED CHANGE (requested 11/19): "I don't need the '7 KEYS' or the '+3 More in the Table'
                # notes." Both were housekeeping ABOUT the card rather than coaching: the count said how many
                # keys the category holds and the overflow line said the table has the rest, which the table
                # directly below already shows. The card now carries only the keys themselves.
                _cards_out.append(
                    f'<div class="lc"><div class="lc-t">{_gname}</div>'
                    f'<div class="lc-n">{_lead}</div>'
                    + (f'<div class="lc-s ktv-why">{_sb_esc(_lead_why)}.</div>' if _lead_why else "") + _rest
                    + "</div>")
            if _cards_out:
                add('<div class="lcards ktv-cards">' + "".join(_cards_out) + "</div>")
            else:
                _ktv_cards = False      # nothing to group (no categories at all) -- fall back to the sentences
        if not _ktv_cards:
            add('<div class="card">')
        for _ki, (_, k) in enumerate(ktv_brief.iterrows()):
            if _ktv_cards:
                break                   # the cards above replace the per-key list
            if _ki >= _ktv_row:
                break
            _rank = int(k["brief_rank"]) if "brief_rank" in k and pd.notna(k.get("brief_rank")) else ""
            _app_key = int(k["key_number"]) if pd.notna(k.get("key_number")) else None
            _headline = _sb_clean(k.get("headline")).rstrip(".")
            _reasoning = _sb_clean(k.get("reasoning")).rstrip(".")
            _source = source_badge(k.get("source"))
            # Bottom Line keys exist only in the brief, so only the app's own keys link to an entry there.
            _head_html = (name_link(_headline, page="upcoming", tab="keys", key=_app_key)
                          if _app_key and str(k.get("source")) != "Game Plan" else _sb_esc(_headline))

            # Sentence format: "N. Headline — reason."
            _sentence = f'<span class="n">{_rank}.</span> <span>{_head_html}'
            if _reasoning:
                _sentence += f' — {_sb_esc(_reasoning)}'
            _sentence += '.</span>'

            # CONFIRMED CHANGE (requested: the 2025-26 tag next to the "Keys to Victory" tags on the right instead of in the
            # section header): the staff's keys from last season's game carry the season beside their source tag
            _bt_k = _bt_box["bt"]
            if _source and _bt_k and _bt_k["last_season"] and not _staff_keys_this_season() \
                    and _sb_clean(k.get("source")) == "Keys to Victory":
                _source = (f' <span class="ktv-right"><span class="lsn">{_sb_esc(_bt_k["season"])}</span>'
                           f'{_source}</span>')
            # CONFIRMED CHANGE (requested: "Show the priority score on the briefs"): each key's 0-100 priority score sits on
            # the right, before its source tag
            _ps = pd.to_numeric(k.get("priority_score"), errors="coerce")
            _score = (f'<span class="ktv-score" title="Priority score (0-100): who says so, how big the edge, how much data, '
                      f'whether it is an instruction">{int(round(_ps))}</span>') if pd.notna(_ps) else ""
            if _score:
                _source = (_source.replace('<span class="ktv-right">', '<span class="ktv-right">' + _score, 1)
                           if 'class="ktv-right"' in _source else f'<span class="ktv-right">{_score}{_source}</span>')
            add(f'<div class="ktv-sentence">{_sentence} {_source}</div>')   # a space: copied text reads "... reason. Data-Driven"
        if not _ktv_cards:
            add("</div>")
        # CONFIRMED CHANGE (requested 11/18: "Make a table of keys to victory that can be expanded with all of them
        # available"). The cards are the six the brief leads with; this is EVERY key the parser built for this game
        # behind one expander -- the same <details> the other sections use, so "Expand all" opens it and printing
        # unfolds it. Best first by priority score, the six already on a card marked, and a key with no reasoning
        # falls back to its evidence line (what the app shows when you click a key).
        _ktv_all = ktv.copy()
        if not _ktv_all.empty and "priority_score" in _ktv_all.columns:
            _ktv_all = _ktv_all.assign(_ps=pd.to_numeric(_ktv_all["priority_score"], errors="coerce")) \
                               .sort_values("_ps", ascending=False, na_position="last")
        # CONFIRMED CHANGE (requested 11/19): the app link belongs inside the expander, under the table it refers to,
        # not loose beneath the closed bar. It stays outside only when there is no expander to put it in.
        _ktv_link = ('<p class="mini">'
                     + app_link(f"All {_ktv_total} keys with evidence and reasoning", page="upcoming", tab="keys")
                     + "</p>")
        _ktv_expander = False
        if len(_ktv_all) > (len(_ktv_on_card) if _ktv_cards else len(ktv_brief)):
            # only the keys that actually made the row are marked -- with cards capped at one row, a key the brief
            # selected but did not card is new information down here and must not be flagged as seen above
            _on_card = _ktv_on_card if _ktv_cards else {
                str(x) for x in ktv_brief.get("key_number", pd.Series(dtype=object)).dropna().astype(str)}
            _ktv_rows = []

            def _score_why(k, _total):
                # CONFIRMED CHANGE (requested 11/22: "a column for reason why for the score"). Rebuilds the 83 priority
                # model's parts for this key -- source, impact, confidence, wording -- so each point of the score is named.
                try:
                    R = KTV_BRIEF_RULES
                    src = str(k.get("source") or "")
                    staff = src in R["staff_sources"]
                    hl = str(k.get("headline") or "").strip().lower()
                    imp = _ktv_num(k.get("impact"), R["default_impact"])
                    conf = _ktv_num(k.get("confidence"), 1.0 if staff else R["default_confidence"])
                    sp = R["source_points"].get(src, 12)
                    act = 15 if (staff or hl.startswith(_KTV_ACTION_VERBS)) else 8
                    parts = [f"{src or 'Source'} +{sp:g}"]
                    parts.append(f"edge size {imp:.2f} +{40 * imp:.0f}" if pd.notna(pd.to_numeric(k.get("impact"), errors="coerce"))
                                 else f"edge size not measured (default) +{40 * imp:.0f}")
                    parts.append(f"data behind it {conf:.2f} +{15 * conf:.0f}" if pd.notna(pd.to_numeric(k.get("confidence"), errors="coerce"))
                                 else f"data behind it {'staff-written' if staff else 'default'} +{15 * conf:.0f}")
                    parts.append(f"{'an instruction' if act == 15 else 'a description'} +{act}")
                    calc = sp + 40 * imp + 15 * conf + act
                    if pd.notna(_total) and abs(calc - float(_total)) >= 1:
                        parts.append(f"other adjustment {float(_total) - calc:+.0f}")
                    return " \u00b7 ".join(parts)
                except Exception:
                    return ""
            for _, k in _ktv_all.iterrows():
                _hl = _sb_clean(k.get("headline")).rstrip(".")
                if not _hl:
                    continue
                _kn = str(k.get("key_number")) if pd.notna(k.get("key_number")) else ""
                _why = _sb_clean(k.get("reasoning")).rstrip(".") or _sb_clean(k.get("evidence")).rstrip(".")
                _psv = pd.to_numeric(k.get("priority_score"), errors="coerce")
                _area = _sb_clean(k.get("category")) or "—"
                _star = (" ★ on a card above") if (_kn and _kn in _on_card) else ""
                _sc = str(int(round(_psv))) if pd.notna(_psv) else ""
                # CONFIRMED CHANGE (requested 11/22: "instead of extra columns, make that be expandable rows similar to how we
                # formatted the Play Calls table"). Same pcs-r markup as the play-call summary: the row is key / score / area,
                # and opening it shows the reasoning, where it came from and the parts of the score.
                _why_sc = _score_why(k, _psv)
                _body = ((f'<div class="mini" style="margin:2px 0 6px">{_sb_esc(_why)}.</div>' if _why else "")
                         + f'<div class="pcs-gh"><b>Why {_sc or "this"}</b> <span class="mini">{_sb_esc(_why_sc)}</span></div>'
                         + f'<div class="pcs-gh"><b>Source</b> {source_badge(k.get("source"))}</div>')
                _ktv_rows.append(
                    f'<details class="pcs-r{" ktv-on" if _star else ""}"><summary>'
                    f'<span class="l">{_sb_esc(_hl)}'
                    + (f' <span class="mini">{_sb_esc(_star)}</span>' if _star else "")
                    + f'</span><span class="t1">{_sc}</span><span class="t1">{_sb_esc(_area)}</span></summary>'
                    f'<div class="pcs-b">{_body}</div></details>')
            add('<details class="rosdet"><summary><span class="rd-open">All ' + str(_ktv_total)
                + ' keys</span><span class="rd-sub">every key the parser built for this game, best first -- click one for its reasoning and score</span>'
                "</summary>"
                '<div class="card pcs"><div class="pcs-h"><span class="l">Key</span><span class="t1">Score</span>'
                '<span class="t1">Area</span></div>' + "".join(_ktv_rows)
                + "</div>" + _ktv_link + "</details>")
            _ktv_expander = True
        if not _ktv_expander:
            add(_ktv_link)

    # ---- WHAT MATTERS: the one page a coach reads if he reads nothing else (requested) ----------------
    # Sits directly under KEYS TO VICTORY on purpose. The keys are the INSTRUCTIONS; this page is the
    # EVIDENCE under them -- the four factors converted into points per game, the players who actually
    # decide it, and which key each number belongs to. Built only from numbers already on the brief
    # (uww_pbp_box_score, uww_opponent_prior_games_box_score, uww_offensive_roles, uww_player_tendencies),
    # so it can never disagree with the sections below it, and so the two can be merged later if wanted.
    def _wm_sides():
        """(our box rows, rows our opponents put up against us, their box rows, rows their opponents put up,
        our games, their games) -- or None when either side has no box score yet."""
        _ub = _sb_d("uww_pbp_box_score")
        _ob = _sb_d("uww_opponent_prior_games_box_score")
        if _ub.empty or _ob.empty or "team" not in _ub.columns or "team" not in _ob.columns:
            return None
        _us = _ub[_ub["team"].astype(str).str.contains("Whitewater", case=False, na=False)]
        _usa = _ub[~_ub.index.isin(_us.index)]
        _disp = _sb_strip_mascot(short)
        _them = _ob[_ob["team"].astype(str).str.strip() == str(short).strip()]
        if _them.empty and _disp:
            _them = _ob[_ob["team"].astype(str).str.contains(re.escape(str(_disp)), case=False, na=False)]
        _thema = _ob[~_ob.index.isin(_them.index)]
        if _us.empty or _them.empty:
            return None
        _gu = _us["game_date"].nunique() if "game_date" in _us.columns else 0
        _gt = _them["game_date"].nunique() if "game_date" in _them.columns else 0
        if not _gu or not _gt:
            return None
        return _us, _usa, _them, _thema, _gu, _gt

    def _wm_ff(team_box, opp_box):
        """The four factors for team_box's side plus the totals the points conversion needs."""
        _t = lambda d, c: float(_sb_num(d[c]).sum()) if c in d.columns else 0.0
        fgm, fga, fg3m = _t(team_box, "FGM"), _t(team_box, "FGA"), _t(team_box, "FG3M")
        to, fta, oreb = _t(team_box, "TO"), _t(team_box, "FTA"), _t(team_box, "OREB")
        ftm, pts = _t(team_box, "FTM"), _t(team_box, "PTS")
        opp_dreb = _t(opp_box, "DREB")
        _p = _sb_possessions(fga, oreb, to, fta)
        return {"eFG": (fgm + 0.5 * fg3m) / fga * 100 if fga else None,
                "TOV": to / _p * 100 if _p else None,
                "ORB": oreb / (oreb + opp_dreb) * 100 if (oreb + opp_dreb) else None,
                "FTR": fta / fga * 100 if fga else None,
                "FGpct": fgm / fga * 100 if fga else None,
                "FTpct": ftm / fta * 100 if fta else None,
                "poss": _p, "fga": fga, "fgm": fgm, "fta": fta, "ftm": ftm, "pts": pts}

    def _wm_what_matters():
        _sides = _wm_sides()
        if not _sides:
            return
        _us, _usa, _them, _thema, _gu, _gt = _sides
        OUR, OURD = _wm_ff(_us, _usa), _wm_ff(_usa, _us)          # what we do / what we allow
        THR, THRD = _wm_ff(_them, _thema), _wm_ff(_thema, _them)  # what they do / what they allow
        if None in (OUR["eFG"], THR["eFG"], OURD["eFG"], THRD["eFG"]):
            return
        # CONFIRMED BUG (fixed 11/17; Corey, on the first Elmhurst page: "Do these net ratings look correct?" --
        # they did not). Three faults, all in this calculation:
        #  1. BASELINE. It compared each team with the OTHER TEAM'S SCHEDULE -- our 52.8 eFG against "Elmhurst
        #     allow 43.0" -- and then ADDED both halves. Their 43.0 was earned against DePauw, Hope and Ripon,
        #     and the two halves are the same schedule comparison from opposite ends, so adding them counts it
        #     twice instead of cancelling it. Shot quality printed +7.0 FOR US when the matchup estimate is
        #     -2.8 AGAINST us, and the page's total was +9.8 -- a blowout nothing in the data supports.
        #  2. Free throws were multiplied by 2 AND by the free-throw percentage: a free throw is worth about
        #     0.66 points, not 1.3.
        #  3. Offensive boards used possessions x 0.30 as a stand-in for rebound chances. The chances are the
        #     missed shots, and the board is a fresh possession.
        # What a team should do IN THIS GAME is the midpoint of its own rate and the other team's matching
        # defensive rate (the usual matchup estimate without a league average to divide by). Comparing the two
        # midpoints leaves both schedules out of it. Cross-checked against expected points built independently
        # from the same rates: 72.3 us / 68.6 them, +3.7 from shooting and free throws, which is what the
        # shot-quality and free-throw rows add up to.
        _EXP_U = {k: (OUR[k] + THRD[k]) / 2 for k in ("eFG", "TOV", "ORB", "FTR", "FGpct")}
        _EXP_T = {k: (THR[k] + OURD[k]) / 2 for k in ("eFG", "TOV", "ORB", "FTR", "FGpct")}
        _pos_g = (OUR["poss"] / _gu + THR["poss"] / _gt) / 2
        _ftp = ((OUR["FTpct"] if OUR["FTpct"] is not None else 68.0)
                + (THR["FTpct"] if THR["FTpct"] is not None else 68.0)) / 2 / 100

        # CONFIRMED BUG (fixed 11/17, second pass; Corey: "I also am not sure that the net ratings are correct
        # yet"). The first fix got the baseline right but kept converting each factor to points on its own, and
        # the free-throw row was still badly wrong: it counted extra trips as PURE ADDED POINTS. They are not
        # free. A trip to the line uses up the possession it came from -- the possession identity itself says so
        # (P = FGA - OREB + TO + 0.475*FTA) -- so those trips REPLACE field-goal attempts worth about a point
        # each. Counting only the gain made free throws +6.5 a game, when the whole edge is worth about +1, and
        # it flipped the page's verdict: it called a game we should expect to trail "+1.9 to us".
        # So points are no longer converted factor by factor. FGA is solved out of the possession identity with
        # TO = TOV*P, FTA = FTR*FGA and OREB = ORB*(1-FG%)*FGA, which gives
        #     FGA = P*(1-TOV) / (1 + 0.475*FTR - ORB*(1-FG%))
        # and then points = 2*eFG*FGA + FTR*FGA*FT%. Each factor is then worth what we LOSE by playing it at
        # their rate instead of ours, everything else held: swap one, recompute, take the difference. The rows
        # add up to the expected margin because they are differences of one model, not four conversions.
        # VALIDATION (repeat this if any of it is touched): fed a team's OWN rates and pace, the engine has to
        # return that team's real scoring. UW-Whitewater: 75.5 points on 54.5 attempts, against 75.5 on 54.5
        # actual -- exact. Elmhurst: 74.7 on 63.1 against 72.7 on 61.3, about two points high because ORB% has
        # its own denominator (offensive rebounds over offensive plus defensive, not over missed shots).
        def _wm_points(f):
            _fga = (_pos_g * (1 - f["TOV"] / 100)
                    / (1 + 0.475 * f["FTR"] / 100 - f["ORB"] / 100 * (1 - f["FGpct"] / 100)))
            return 2 * f["eFG"] / 100 * _fga + f["FTR"] / 100 * _fga * _ftp

        _pts_u, _pts_t = _wm_points(_EXP_U), _wm_points(_EXP_T)

        # CONFIRMED CHANGE (requested 11/17; Corey: "I don't understand how 44.0 is +.9 compared to 27"). The
        # rate columns show a 17-point gap and NET shows +0.9, because the model charges free throws for the
        # possessions they use: at 44% we take 24.6 from the line and 55.9 from the floor, at 27% it is 16.4 and
        # 60.6 -- +5.4 points of free throws against -4.5 points of field goals. The countable version of each
        # row now sits on the page next to the rate, so the size of the gap and what it is worth are both
        # visible instead of only the net.
        def _wm_counts(f):
            _fga = (_pos_g * (1 - f["TOV"] / 100)
                    / (1 + 0.475 * f["FTR"] / 100 - f["ORB"] / 100 * (1 - f["FGpct"] / 100)))
            return {"fga": _fga, "fta": f["FTR"] / 100 * _fga, "to": f["TOV"] / 100 * _pos_g,
                    "oreb": f["ORB"] / 100 * (1 - f["FGpct"] / 100) * _fga,
                    "fgpts": 2 * f["eFG"] / 100 * _fga}

        _CU, _CT = _wm_counts(_EXP_U), _wm_counts(_EXP_T)
        _REAL = {"eFG": ("fgpts", "points from the floor"), "TOV": ("to", "giveaways"),
                 "ORB": ("oreb", "second shots"), "FTR": ("fta", "free throws")}

        def _wm_worth(k):
            """What that factor is worth to us: the points we lose playing it at their rate, all else held."""
            _sw = dict(_EXP_U)
            _sw[k] = _EXP_T[k]
            if k == "eFG":                      # eFG and FG% move together -- the same shots
                _sw["FGpct"] = _EXP_T["FGpct"]
            return _pts_u - _wm_points(_sw)

        _NET = {k: _wm_worth(k) for k in ("eFG", "TOV", "ORB", "FTR")}
        _NAMES = {"eFG": "Shot quality (eFG%)", "TOV": "Turnovers (TOV%)",
                  "ORB": "Offensive boards (ORB%)", "FTR": "Free-throw rate"}
        _SAY = {
            "eFG": ("we should get the better looks against this defense",
                    "they are the better bet to score against ours"),
            "TOV": ("we should handle their pressure better than they handle ours",
                    "they should take care of it better than we do"),
            "ORB": ("we should get more of our misses back than they get of theirs",
                    "they should get more second shots than we do"),
            "FTR": ("we should get to the line far more than they do",
                    "they should get to the line more than we do"),
        }
        rows = [{"k": k, "net": _NET[k], "us": _EXP_U[k], "them": _EXP_T[k],
                 "real": f"{_CU[_REAL[k][0]]:.0f} v {_CT[_REAL[k][0]]:.0f} {_REAL[k][1]}",
                 "say": _SAY[k][0 if _NET[k] >= 0 else 1]} for k in ("eFG", "TOV", "ORB", "FTR")]
        rows.sort(key=lambda r: -abs(r["net"]))
        _tot = _pts_u - _pts_t

        # the three players who actually decide it: their own box score, with film behind each line
        _COLS = ("FGA", "FG3A", "FG3M", "FGM", "FTA", "FTM", "AST", "OREB", "TO", "STL", "PF", "MIN")
        _pl = _them.copy()
        _pl["_pts"] = _sb_num(_pl["PTS"]) if "PTS" in _pl.columns else 0
        for c in _COLS:
            _pl[c] = _sb_num(_pl[c]) if c in _pl.columns else 0
        _all = _pl.groupby("player", dropna=True).agg(
            PTS=("_pts", "sum"), **{c: (c, "sum") for c in _COLS}).reset_index()
        _all = _all[~_all["player"].astype(str).str.strip().str.upper().isin(("", "TEAM", "NAN"))]


        # CONFIRMED CHANGE (requested 11/18; Corey: "Instead of 'FOUR FACTORS', I want it to say 'This game
        # turns on shot quality: ...' before it is expanded. Expanding the section will give the full Four
        # Factors table."). The section header IS the verdict now -- collapsed, the brief shows the sentence
        # that answers the question, and opening it gives the table underneath. The verdict therefore has to
        # be built BEFORE section() is called, which is why the whole block sits up here.
        # The "<!-- FOUR FACTORS -->" in the title is load-bearing and invisible to a reader: ANALYSIS_MODE
        # decides what to leave out by matching _AN_DROP against the section title, and BRIEF_OPEN_SECTIONS
        # matches the same way, so with the title now a sentence about us and them there would be nothing for
        # either to match on. _sb_collapse strips comment markers before matching so the name still works.
        # CONFIRMED CHANGE (requested 11/17; Corey, reading "... free-throw rate ... and Dominic Trelenberg is the
        # one to take away (16.0 a game)": "Why is the Dominic Trelenberg comment in there? Shouldn't it list out
        # which player of theirs gets to the free throw line the most?"). It named the leading scorer whatever the
        # factor was. The man named is now the one who drives THE FACTOR THAT WON, and the sentence says what he
        # does about it -- the leading scorer is the right answer only when shot quality is the factor. A minutes
        # floor keeps a 4-minute player with 2 fouls from leading a per-game rate.
        def _wm_face(k, net):
            """(names already marked up, what they do) for the opponent player this factor runs through, or
            ("", ""). Returns the names as HTML because a tie names two of them."""
            _e = _all[_sb_num(_all["MIN"]) / _gt >= 8] if "MIN" in _all.columns else _all
            if _e.empty:
                _e = _all
            if _e.empty:
                return "", ""
            _nm = lambda r: f'<b>{_sb_esc(str(r["player"]))}</b>'

            def _top_by(col, one, many):
                """The leader, or the two who share the lead -- idxmax() hands a tie to whoever sorts first
                (the 11/14 _pn_sole_leader bug: Jose Gonzales called "primary creator" over three players with
                the same 2 assists). Three or more tied and nobody is named."""
                _c = _sb_num(_e[col]) if col in _e.columns else None
                if _c is None or not _c.max():
                    return "", ""
                _tied = _e[_c == _c.max()]
                if len(_tied) > 2:
                    return "", ""
                _v = float(_c.max()) / _gt
                if len(_tied) == 2:
                    return f"{_nm(_tied.iloc[0])} and {_nm(_tied.iloc[1])}", many.format(v=_v)
                return _nm(_tied.iloc[0]), one.format(v=_v)

            if k == "eFG":
                _r = _e.sort_values("PTS", ascending=False).iloc[0]
                _3 = f", {float(_r['FG3M']) / float(_r['FG3A']) * 100:.0f}% from three" if float(_r["FG3A"]) else ""
                return _nm(_r), f"is the one to take away ({float(_r['PTS']) / _gt:.1f} a game{_3})"
            if k == "FTR":          # net our way = WE are the ones getting there, so the man is whoever fouls
                return (_top_by("PF", "fouls the most ({v:.1f} a game) \u2014 go at him",
                                "foul the most ({v:.1f} a game each) \u2014 go at them") if net >= 0
                        else _top_by("FTA", "lives at the line ({v:.1f} attempts a game)",
                                     "live at the line ({v:.1f} attempts a game each)"))
            if k == "ORB":
                return _top_by("OREB", "is the one to box out ({v:.1f} offensive boards a game)",
                               "are the ones to box out ({v:.1f} offensive boards a game each)")
            if k == "TOV":
                return (_top_by("TO", "gives it away most ({v:.1f} a game)",
                                "give it away most ({v:.1f} a game each)") if net >= 0
                        else _top_by("STL", "is the one who takes it off us ({v:.1f} steals a game)",
                                     "are the ones who take it off us ({v:.1f} steals a game each)"))
            return "", ""

        # CONFIRMED CHANGE (requested 11/18): the one-sentence verdict that was this section's header is now
        # four cards, in the shape the roster and lineup sections use -- the expected score, the factor that
        # decides it, the next thing after it, and the man to take away. Same numbers the sentence carried,
        # one per card, so a coach can stop at the one he needs.
        _top = rows[0]
        _who_html, _does = _wm_face(_top["k"], _top["net"])
        _tw = "us" if _tot >= 0 else "them"
        _sz = ("a one-possession game" if abs(_tot) <= 4 else
               "about two possessions" if abs(_tot) <= 8 else "a comfortable edge")
        _name_of = lambda r: _NAMES[r["k"]].split(" (")[0]        # noqa: E731
        _ppg = lambda r: ("+" if r["net"] >= 0 else "\u2212") + f'{abs(r["net"]):.1f} PPG'   # noqa: E731
        _cap = lambda t: (t[0].upper() + t[1:]) if t else ""      # noqa: E731

        def _wm_card(title, name, value, sub, note, more=""):
            return (f'<div class="lc"><div class="lc-t">{_sb_esc(title)}</div>'
                    f'<div class="lc-n">{name}</div>'
                    + (f'<div class="lc-v">{_sb_esc(value)}</div>' if value else "")
                    + (f'<div class="lc-s">{_sb_esc(sub)}</div>' if sub else "")
                    + (f'<div class="lc-x">{note}</div>' if note else "")
                    + (f'<div class="lc-x">{more}</div>' if more else "") + "</div>")

        # CONFIRMED CHANGE (requested 11/22): "I do not want the 'Expected here' card and rename the 'What decides it'
        # to 'Biggest of Four Factors'. Remove the 'Where we gain' card. Now that there are only 3 cards, you can add
        # more information to each of them." The expected score still prints in the detail under the cards.
        # Card 1 now also names the opponent player the factor runs through and lists the other three factors;
        # cards 2 and 3 now list the next two biggest season-average edges for that side.
        _others = [r for r in rows if r["k"] != _top["k"]]
        _more1 = ""
        if _who_html:
            _more1 += f'<b>Who:</b> {_who_html} {_sb_esc(_does)}.<br>'
        if _others:
            _more1 += "<b>The other three:</b> " + " \u00b7 ".join(
                f'{_sb_esc(_name_of(r))} {_ppg(r)}' for r in _others)
        _wm_cards = [_wm_card("Biggest of Four Factors", _sb_esc(_name_of(_top)), _ppg(_top), _top["real"],
                              _sb_esc(_cap(_top["say"])) + ".", _more1)]
        _ts = [r for r in (globals().get("_TEAM_STAT_ROWS") or [])]
        for _mine in (True, False):
            _side_rows = sorted((r for r in _ts if r["ours"] is _mine), key=lambda r: -r["gap"])
            if not _side_rows:
                continue
            _b = _side_rows[0]
            _fmt_gap = lambda r: (f'{abs(r["us"] - r["them"]):.1f}'                      # noqa: E731
                                  + (" pts" if "%" in str(r["label"]) else ""))
            _nx = "<br>".join(
                f'<b>{_sb_esc(r["label"])}</b> {r["us"]:.1f} \u2014 {r["them"]:.1f} ({_fmt_gap(r)})'
                for r in _side_rows[1:3])
            _wm_cards.append(_wm_card(
                "What we do better" if _mine else "What they do better",
                _sb_esc(_b["label"]),
                f'{_b["us"]:.1f} \u2014 {_b["them"]:.1f}',
                f'{"us" if _mine else "them"} by {abs(_b["us"] - _b["them"]):.1f}'
                + (" percentage points" if "%" in str(_b["label"]) else " a game"),
                _sb_esc("Season averages, before this matchup."),
                ("<b>Next:</b><br>" + _nx) if _nx else ""))


        section("\U0001f4ca TEAM COMPARISON" + footnote(
            "The one page to read if you read nothing else. It adds nothing new -- it is the numbers already "
            "on this brief, ranked. KEYS TO VICTORY above says what to do; this says what it is worth. "
            "THESE ARE DEAN OLIVER'S FOUR FACTORS, with his definitions of eFG% and ORB%; free-throw rate is "
            "attempts per field-goal attempt (the Basketball-Reference form of it) and possessions use 0.475, "
            "Ken Pomeroy's college coefficient, rather than Oliver's 0.44. What is NOT his is the ranking: "
            "his 40 / 25 / 20 / 15 are fixed league-average weights, used in the app's Four Factors dialog, "
            "while this prices each factor for this matchup. The two can lead with different factors -- "
            "free throws most of all, which weigh heavily on fixed weights and much less once the "
            "possessions the trips use up are charged against them. "
            "WHAT THE US AND THEM COLUMNS ARE: not season averages -- what each team should do IN THIS GAME. "
            "Every rate is one team's offense and the other team's defense at the same time, so each side's "
            "expected rate is the midpoint of the two: our shooting against their shooting defense, theirs "
            "against ours. Comparing the two midpoints is what takes the two schedules out of it -- a defense "
            "that has only faced weak offenses looks better than it is, and measuring ourselves against what "
            "it has allowed would count that difference twice. "
            "HOW THE POINTS ARE WORKED OUT: both sides' expected rates are run through one scoring model and "
            "PPG DIFFERENCE is what each factor is worth -- the points a game we lose if we play that one "
            "factor at their rate "
            "and everything else stays as it is. The model works the shot attempts out of the possession "
            "count itself, so nothing is counted twice and nothing is counted free: a trip to the line uses "
            "up the possession it came from, so free throws are worth the difference between the trip and the "
            "shot it replaced, not the whole trip. Fed a team's own rates it returns that team's real scoring, "
            "which is the check that it is right. A positive PPG difference is points for us, and the rows "
            "add up to the expected margin. "
            "IN THIS GAME is the countable thing behind the rate -- what each side should actually do, with "
            "every factor working at once. It can show a bigger gap than the PPG difference, and that is not "
            "a contradiction: those counts carry everything together, while the PPG difference moves one "
            "factor and holds the rest. Free throws are the clearest case. 44% against 27% is 25 trips to the line against 17 -- "
            "worth about five and a half points -- but the possessions those trips use up are possessions "
            "that do not end in a shot, so we take about five fewer attempts from the floor, worth about four "
            "and a half. The line is a real edge; it is worth roughly a third of a point a trip, not the "
            "whole trip. "
            f"These are small samples -- {_gu} game{'s' if _gu != 1 else ''} of ours and {_gt} of theirs -- so "
            "read the order of the rows, which is stable, before the size of any one number. Everything here "
            "comes from the box scores, the offensive roles and the film tendencies printed further down this "
            "brief, so it cannot disagree with them."))
        _sb_sechead('<div class="lcards wm-cards">' + "".join(_wm_cards) + "</div>")
        add('<div class="card">')
        add('<table class="wm-ff"><tr><th>What decides it</th><th>Us here</th><th>Them here</th>'
            '<th class="wm-real">In this game</th><th>PPG difference</th>'
            '<th class="wm-say" style="text-align:left">Why</th></tr>')
        for i, r in enumerate(rows):
            _cls = ' class="wm-top"' if i == 0 else ""
            _net = r["net"]
            _nc = "wm-net wm-us" if _net >= 0 else "wm-net wm-them"
            _sign = "+" if _net >= 0 else "−"
            add(f'<tr{_cls}><td>{_sb_esc(_NAMES[r["k"]])}</td>'
                f'<td>{r["us"]:.1f}%</td><td>{r["them"]:.1f}%</td>'
                f'<td class="wm-real">{_sb_esc(r["real"])}</td>'
                f'<td class="{_nc}">{_sign}{abs(_net):.1f}</td>'
                f'<td class="wm-say">{_sb_esc(r["say"])}</td></tr>')
        add("</table>")
        # CONFIRMED CHANGE (requested 11/17, "Leave them and label them"): the app's Four Factors dialog ranks
        # the same four by Dean Oliver's fixed weights (40/25/20/15) on each side's season rates, and can put a
        # different factor on top -- for Elmhurst it leads with free-throw rate where this leads with shot
        # quality. Both are right about different questions, and a coach with the brief and the app open needs
        # that said on the page rather than only in the footnote, which nobody opens mid-practice.
        add('<p class="mini">Ranked by what each factor is worth <i>against this opponent</i>, with free throws '
            'charged for the possessions they use. The app\'s Four Factors dialog ranks the same four by Dean '
            'Oliver\'s fixed weights on season rates and can put a different one first -- that asks how much a '
            'factor usually matters, this asks what it is worth here. '
            + app_link("Four Factors in the app", page="upcoming", tab="keys") + "</p>")

        # CONFIRMED CHANGE (requested 11/17; Corey, on the player cards and the key list: "I think we need
        # to remove this part of that section because it's duplicated throughout the scouting report").
        # WHO DECIDES IT repeated the personnel section's own cards -- the same tendencies line and the same
        # offensive role -- and THE KEY THAT COVERS IT repeated the keys printed directly above it. What is
        # left is what appears nowhere else: the verdict, the four factors priced for this matchup, and the
        # expected score. The man named in the verdict stays: one name tied to the factor, not a roster block.

        # CONFIRMED CHANGE (requested 11/19): "add more explanation to 'Expected here'". The two numbers were
        # printed with no account of where they come from or how much weight to put on them, which invites a
        # coach to read a projection off season rates as a prediction of a result. What it is, how it is built
        # and what it cannot see now sit with it.
        add(f'<p class="mini">Expected here: UW-Whitewater {_pts_u:.0f}, '
            f'{_sb_esc(_sb_strip_mascot(short))} {_pts_t:.0f}. '
            f"This is what the season rates project for this matchup, not a prediction of a final score. Each "
            f"team is credited with the midpoint of its own rate and the other team's matching defensive rate "
            f"in all four factors -- shot quality, turnovers, offensive rebounds and free-throw rate -- played "
            f"at {_pos_g:.0f} possessions, the average of the two teams' pace. Those rates become points through "
            f"the possession identity, so free throws are charged for the possessions they use rather than "
            f"added on top. Because each team is measured against the other and not against a league average, "
            f"the estimate says nothing about the strength of who either team has played so far. "
            f'Built on {_gu} UW-Whitewater game{"s" if _gu != 1 else ""} and {_gt} '
            f'{_sb_esc(_sb_strip_mascot(short))} game{"s" if _gt != 1 else ""}'
            + (" -- few enough that one outlier still moves it several points, so read the gap as a range "
               "rather than a number. " if min(_gu, _gt) < 6 else ". ")
            + app_link("Every number behind this", page="upcoming", tab="keys") + "</p>")
        add("</div>")
        # CONFIRMED CHANGE (requested 11/18): "Combine these two sections into a 'Team Comparison' section."
        # The season-average strip that used to be TEAM STATS renders here, under the four factors.
        if team_parts:
            add('<div class="pc-sub">Season averages, per game</div>')
            add('<div class="card">' + "".join(team_parts) + "</div>")

    _wm_what_matters()


    # ---- head-to-head: how the previous meeting(s) went (requested) ------------------------------------
    _h2h = _sb_d("uww_head_to_head")
    if not _h2h.empty:
        # Scope to what's actually useful for THIS matchup (requested): if we've already played them this
        # season, last season's numbers are stale -- show only this season's meeting(s). Otherwise fall back
        # to the most recent seasons on file. Either way, cap at the 3 most recent -- head_to_head is already
        # sorted season desc, date desc, so .head(3) is exactly that.
        _this_season = _sb_clean(game.get("season"))
        _h2h_this_season = _h2h[_h2h["season"].astype(str) == _this_season] if _this_season else pd.DataFrame()
        _h2h = (_h2h_this_season if not _h2h_this_season.empty else _h2h).head(3)
    # CONFIRMED CHANGE (requested: "remove the WHEN WE'VE PLAYED <OPP> section from the scouting briefs and leave it in the
    # application"). The app's "When we've played ..." panel is unchanged; BRIEF_HEAD_TO_HEAD = True brings it back here.
    if not globals().get("BRIEF_HEAD_TO_HEAD", False):
        _h2h = pd.DataFrame()
    if not _h2h.empty:
        _h2h_w = int((_h2h["outcome"].astype(str).str.upper() == "W").sum())
        section(f"\U0001f501 WHEN WE'VE PLAYED {OPP_UP}" + footnote(
            "Previous meetings with this opponent, from our own schedules. Scoped to this matchup: if we've "
            "already played them this season, only this season's meeting(s) are shown, since an earlier "
            "season's numbers are the less relevant read once there's a current one; otherwise it's the most "
            "recent seasons on file. Capped at the 3 most recent meetings either way. Each meeting's play-by-play "
            "is pulled from its own box score and cached, so the numbers below are that game's real box score. "
            "\\\"How this team is different now\\\" compares who played in that meeting against this year's roster "
            "and box scores -- points shown in brackets are what that player scored against US in the meeting, "
            "not a season average."))
        add('<div class="card">')
        # CONFIRMED CHANGE (coach: "not formatted to help coaches know if the previous games against the upcoming
        # opponent matter"). The section opens with the VERDICT -- computed in the parser from how long ago the
        # meetings were and how much of each team's scoring in them is still on its roster -- then one compact
        # table of the meetings with each team's top scorer marked still there / gone.
        _cont = _sb_d("uww_head_to_head_continuity")
        if not _cont.empty and "opponent" in _cont.columns:
            _cont = _cont[_cont["opponent"].astype(str) == str(short)]
        if not _cont.empty and _sb_clean(_cont.iloc[0].get("verdict_headline")):
            _c0 = _cont.iloc[0]
            _vc = {"Yes": "#1b7a3a", "Partly": "#b06b00", "Mostly no": "#b3261e"}.get(_sb_clean(_c0.get("verdict")), "#4E2A84")
            add(f'<p class="ff-lede"><strong style="color:{_vc}">Do these games matter? {_sb_esc(_sb_clean(_c0.get("verdict_headline")))}.</strong></p>'
                f'<p>{_sb_esc(_sb_clean(_c0.get("verdict_why")))} {_sb_esc(_sb_clean(_c0.get("verdict_use")))}</p>')
        _h2h_box_all = _sb_d("uww_head_to_head_box")
        _chg_all = _sb_d("uww_head_to_head_roster_change")
        if not _chg_all.empty and "opponent" in _chg_all.columns:
            _chg_all = _chg_all[_chg_all["opponent"].astype(str) == str(short)]
        _status = {_norm(r["player"]): r["status"] for _, r in _chg_all.iterrows()} if not _chg_all.empty else {}

        def _top_scorer(md, uww):
            if _h2h_box_all.empty or "meeting_date" not in _h2h_box_all.columns:
                return None
            _m = _h2h_box_all[_h2h_box_all["meeting_date"].astype(str) == str(md)]
            _m = _m[_m["team"].astype(str).str.contains("whitewater", case=False, na=False) == uww]
            if _m.empty:
                return None
            _m = _m.assign(_p=pd.to_numeric(_m["PTS"], errors="coerce")).sort_values("_p", ascending=False)
            return _m.iloc[0]["player"], _m.iloc[0]["_p"]

        add(f'<p class="mini">{_h2h_w}-{len(_h2h) - _h2h_w} in the {len(_h2h)} meeting{"s" if len(_h2h) != 1 else ""} shown.</p>')
        add('<table class="compact"><thead><tr><th style="text-align:left">Meeting</th><th style="text-align:left">Result</th>'
            '<th style="text-align:left">Their top scorer</th><th style="text-align:left">Our top scorer</th></tr></thead><tbody>')
        for _, _g in _h2h.iterrows():
            _oc = _sb_clean(_g.get("outcome")).upper()
            _score = (f'{int(_g["team_score"])}-{int(_g["opponent_score"])}'
                      if pd.notna(_g.get("team_score")) and pd.notna(_g.get("opponent_score")) else "")
            _ts, _us = _top_scorer(_g.get("date"), False), _top_scorer(_g.get("date"), True)
            _mark = ""
            if _ts:
                _st = _status.get(_norm(_ts[0]))
                _mark = (' <span class="ppp-good">&#10003; still there</span>' if _st == "Returning" else
                         ' <span class="mini">&#10007; gone</span>' if _st == "Gone" else "")
            add(f'<tr><td style="text-align:left">{_sb_esc(_sb_clean(_g.get("date")))}'
                + (f' &middot; {_sb_esc(_sb_clean(_g.get("home_away")))}' if _sb_clean(_g.get("home_away")) else "")
                + f'<br><span class="mini">{_sb_esc(_sb_clean(_g.get("season")))}</span></td>'
                f'<td style="text-align:left"><span class="{"call-foul" if _oc == "W" else "call-nofoul"}">{_sb_esc(_oc)} {_sb_esc(_score)}</span></td>'
                f'<td style="text-align:left">{(_sb_esc(_ts[0]) + " " + _sb_fmt(_ts[1], 0) + _mark) if _ts else "<span class=mini>--</span>"}</td>'
                f'<td style="text-align:left">{(_sb_esc(_us[0]) + " " + _sb_fmt(_us[1], 0)) if _us else "<span class=mini>--</span>"}</td></tr>')
        add("</tbody></table>")

        # ---- what we ran in each meeting, what defense, and whether it worked (requested) ----------------
        # From the tagged clips of that game, joined on the meeting's real date (head_to_head.game_date).
        # "Worked" is measured against our own season average, not an absolute number: 0.95 PPP is good
        # for some teams and bad for others, and the question is whether the plan beat what we normally do.
        # Most meetings are from earlier seasons that were never tagged -- when NONE of them are, this says
        # so and shows a clearly-labelled sample of what the block will look like, so the staff knows the
        # section exists and what tagging it needs, rather than it silently not appearing.
        def _h2h_clip_view():
            # CONFIRMED BUG (fixed here): filtering to side == "UWW" missed meetings tagged from the OTHER
            # team's file -- e.g. our 2/24/2025 game vs Stevens Point is tagged inside opponent_plays.csv
            # (144 clips, both teams' possessions) because that is whose season file it belongs to, not
            # ours. "side" says which team's file a clip came from, not who had the ball, so it is not the
            # right filter for "every clip of a specific date". Every clip on the meeting's date matters,
            # from either file.
            #
            # possession_side is similarly file-relative -- it is computed against whichever team OWNS the
            # file the clip came from (UWW in uww_plays.csv, the opponent in opponent_plays.csv), so
            # "Offense" on an opponent-side clip means the OPPONENT had the ball, not us. offense_team is
            # already the unambiguous, side-agnostic field (computed once, downstream of possession_side),
            # so it is what decides whether WE had the ball here.
            if _pcc_all.empty or "game_date" not in _h2h.columns or "game_date" not in _pcc_all.columns:
                return []
            _c = _pcc_all[~_pcc_all["decode_quality"].isin(["Needs review", "Untagged"])].copy()
            if _c.empty:
                return []
            _c["_d"] = pd.to_datetime(_c["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            _c["_pts"] = pd.to_numeric(_c.get("points"), errors="coerce")
            _c["_off"] = _c.get("offense_team", pd.Series(_SB_UWW, index=_c.index)).astype(str).str.contains(
                "whitewater", case=False, na=False)

            def _ppp(g):
                k = g["_pts"].notna().sum()
                return (g["_pts"].sum() / k) if k else None

            # Season baselines -- what "worked" is measured against.
            _base_off = _ppp(_c[_c["_off"]])
            _base_def = _ppp(_c[~_c["_off"]])
            # The defense split (defense_faced / defense_played) is ALSO file-relative -- populated against
            # whichever team owns the file, same root cause as _off above. On any one clip only one of the
            # pair is ever non-null (see decode_defense_tag), and whichever one it is always describes the
            # defense of whoever did NOT have the ball -- so coalescing them recovers that value regardless
            # of which file it came from, and _off (now side-agnostic) says whose defense it is.
            if "defense_faced" in _c.columns and "defense_played" in _c.columns:
                _c["_def_tag"] = _c["defense_faced"].combine_first(_c["defense_played"])
            else:
                _c["_def_tag"] = pd.Series(pd.NA, index=_c.index)
            views = []
            for _, _g in _h2h.iterrows():
                _gd = _sb_clean(_g.get("game_date"))
                if not _gd:
                    continue
                _m = _c[_c["_d"] == _gd]
                if _m.empty:
                    continue
                views.append((_g, _m[_m["_off"]], _m[~_m["_off"]], _base_off, _base_def, _ppp))
            return views

        def _verdict(v, base, lower_is_better=False):
            if v is None or base is None or pd.isna(v) or pd.isna(base):
                return ""
            d = v - base
            good = (d <= -0.10) if lower_is_better else (d >= 0.10)
            bad = (d >= 0.10) if lower_is_better else (d <= -0.10)
            tag = "worked" if good else ("didn't work" if bad else "about normal")
            cls = "ppp-good" if good else ("ppp-bad" if bad else "")
            return f'<span class="{cls}"><strong>{tag}</strong></span> ({v:.2f} vs our usual {base:.2f})'

        def _top_calls(g, _ppp, n=3):
            if g.empty or "play_call" not in g.columns:
                return ""
            g = g[g["play_call"].notna() & ~g["play_call"].astype(str).str.contains("unspecified", na=False)]
            out = []
            for _name, _cg in g.groupby(g["play_call"].astype(str)):
                out.append((_name, len(_cg), _ppp(_cg)))
            out.sort(key=lambda x: -x[1])
            return ", ".join(f"{_sb_esc(nm)} {k}x" + (f" ({p:.2f})" if p is not None else "")
                             for nm, k, p in out[:n])

        def _def_mix(g, col):
            if g.empty or col not in g.columns or g[col].isna().all():
                return ""
            vc = g[col].dropna().astype(str).value_counts()
            return ", ".join(f"{_sb_esc(k)} {round(100 * int(v) / int(vc.sum()))}%" for k, v in vc.head(2).items())

        _views = _h2h_clip_view()
        if _views:
            add('<div class="pc-sub">What we ran, and did it work</div>')
            add('<table class="compact"><thead><tr><th style="text-align:left">Meeting</th>'
                '<th style="text-align:left">Our offense</th><th style="text-align:left">Our defense</th>'
                "</tr></thead><tbody>")
            for _g, _off, _def, _bo, _bd, _ppp in _views:
                _off_ppp, _def_ppp = _ppp(_off), _ppp(_def)
                _o = []
                if len(_off):
                    _o.append(f"{len(_off)} tagged possessions \u2014 {_verdict(_off_ppp, _bo)}")
                    _tc = _top_calls(_off, _ppp)
                    if _tc:
                        _o.append(f"Ran most: {_tc}")
                    _dm = _def_mix(_off, "_def_tag")
                    if _dm:
                        _o.append(f"They played: {_dm}")
                else:
                    _o.append('<span class="mini">not tagged</span>')
                _d = []
                if len(_def):
                    _d.append(f"{len(_def)} tagged possessions \u2014 {_verdict(_def_ppp, _bd, lower_is_better=True)}")
                    _dm = _def_mix(_def, "_def_tag")
                    if _dm:
                        _d.append(f"We played: {_dm}")
                    _tc = _top_calls(_def, _ppp)
                    if _tc:
                        _d.append(f"They ran: {_tc}")
                else:
                    _d.append('<span class="mini">not tagged</span>')
                # Meeting cell now carries everything the standalone table used to (site, result, margin,
                # leading scorers) -- requested, folded into this table instead of a separate one above it.
                _oc = _sb_clean(_g.get("outcome")).upper()
                _score = (f'{int(_g["team_score"])}-{int(_g["opponent_score"])}'
                          if pd.notna(_g.get("team_score")) and pd.notna(_g.get("opponent_score")) else "")
                _m = _g.get("margin")
                _margin_txt = (" (" + ("+" if pd.notna(_m) and _m > 0 else "") + _sb_fmt(_m, 0) + ")"
                              if pd.notna(_m) else "")
                _leaders = ", ".join(x for x in [
                    f"Us: {_sb_esc(_sb_clean(_g.get('uww_leader')))}" if _sb_clean(_g.get("uww_leader")) else "",
                    f"Them: {_sb_esc(_sb_clean(_g.get('opp_leader')))}" if _sb_clean(_g.get("opp_leader")) else "",
                ] if x)
                add(f'<tr><td class="wrap">{_sb_esc(_sb_clean(_g.get("date")))}'
                    + (f' &middot; {_sb_esc(_sb_clean(_g.get("home_away")))}' if _sb_clean(_g.get("home_away")) else "")
                    + '<br><span class="mini">' + _sb_esc(_sb_clean(_g.get("season")))
                    + f' &middot; <span class="{"call-foul" if _oc == "W" else "call-nofoul"}">{_sb_esc(_oc)}'
                    + f' {_sb_esc(_score)}{_margin_txt}</span></span>'
                    + (f'<br><span class="mini">{_leaders}</span>' if _leaders else "") + '</td>'
                    f'<td class="wrap mini">{"<br>".join(_o)}</td>'
                    f'<td class="wrap mini">{"<br>".join(_d)}</td></tr>')
            add("</tbody></table>")
            add('<p class="mini">"Worked" means 0.10+ PPP better than our season average (on defense, 0.10+ '
                'fewer allowed); numbers in brackets are PPP. Meetings without tagged clips are left out.</p>')
        else:
            add(f'<p class="mini">These meetings have no tagged play calls yet, so what we ran in them isn\'t shown.</p>')

        # ---- their players: who from those games is still there (the useful list), who's gone, who's new ---------
        _h2h_chg = _chg_all
        if not _h2h_chg.empty:
            _ret = _h2h_chg[_h2h_chg["status"] == "Returning"].assign(_p=lambda d: pd.to_numeric(d["prev_pts"], errors="coerce"))
            _gone = _h2h_chg[_h2h_chg["status"] == "Gone"].assign(_p=lambda d: pd.to_numeric(d["prev_pts"], errors="coerce"))
            _new = _h2h_chg[_h2h_chg["status"] == "New since then"]
            add('<div class="pc-sub">Their players from those games</div>')
            if not _ret.empty:
                _ret = _ret.sort_values("_p", ascending=False)
                add('<p class="mini"><strong>Still there</strong> (points against us in those games): '
                    + _sb_esc(", ".join(f"{r['player']} ({int(r['_p'])})" if pd.notna(r["_p"]) else str(r["player"])
                                        for _, r in _ret.iterrows())) + "</p>")
            else:
                add('<p class="mini"><strong>Still there:</strong> nobody who played against us.</p>')
            if not _gone.empty:
                _gone = _gone.sort_values("_p", ascending=False)
                _top_g = ", ".join(f"{r['player']} ({int(r['_p'])})" for _, r in _gone.head(3).iterrows() if pd.notna(r["_p"]))
                add(f'<p class="mini"><strong>Gone:</strong> {len(_gone)} player(s)'
                    + (f", including {_sb_esc(_top_g)}" if _top_g else "") + ".</p>")
            if not _new.empty:
                _new_names = [str(x) for x in _new["player"].astype(str)]
                _new_box = players_for("uww_opponent_prior_games_box_score", short)
                _cur = {_norm(r["name"]): r for _, r in _new_box.iterrows()} if not _new_box.empty and "name" in _new_box.columns else {}
                _ranked = []
                for _nm in _new_names:
                    _row = _cur.get(_norm(_nm))
                    _ranked.append((_nm, pd.to_numeric(_row.get("MIN"), errors="coerce") if _row is not None else None,
                                    pd.to_numeric(_row.get("PTS"), errors="coerce") if _row is not None else None))
                _worth = sorted([x for x in _ranked if (pd.notna(x[1]) and x[1] >= 8) or (pd.notna(x[2]) and x[2] >= 4)],
                                key=lambda x: (-(x[1] if pd.notna(x[1]) else 0), -(x[2] if pd.notna(x[2]) else 0)))[:5]
                if _worth:
                    add('<p class="mini"><strong>New since then</strong> (who plays): '
                        + _sb_esc(", ".join(_sb_title(n) + (f" ({p:.1f} ppg)" if pd.notna(p) else "") for n, _m, p in _worth))
                        + (f" + {len(_new_names) - len(_worth)} more who barely play" if len(_new_names) > len(_worth) else "")
                        + "</p>")
                else:
                    add(f'<p class="mini"><strong>New since then:</strong> {len(_new_names)}, none averaging real minutes yet.</p>')
        add("</div>")

    def foul_list_block():
        _foul, _ = staff_rows("uww_late_game_foul_list")
        if _foul.empty:
            return
        add('<div class="gcell">')
        section("\u23f1\ufe0f LATE-GAME FOUL LIST" + footnote(
            "From their own free-throw shooting on film. The two calls need different evidence: FOUL him takes 8+ "
            "attempts and a rate at 62% or worse, because it's a deliberate act; DO NOT FOUL takes 8+ attempts "
            "at 75% or better, OR as few as 4 attempts when he hasn't missed (85%+) -- avoiding a shooter "
            "costs nothing if we're wrong. Rates are shrunk toward a 70% baseline before the call, so 6-for-6 "
            "doesn't read as a true 100% shooter; the makes-attempts pair shown is raw. Check who is actually "
            "on the floor before the call."))
        add('<div class="card"><table class="compact"><thead><tr><th style="text-align:left">Player</th>'
            '<th style="text-align:left">Call</th><th>FT%</th><th>FTM-FTA</th></tr></thead><tbody>')
        for _, _f in _foul.iterrows():
            _cls = {"Foul": "call-foul", "Do not foul": "call-nofoul"}.get(_sb_clean(_f.get("call")), "")
            # Games-played detail removed from this table (requested) -- thin samples are flagged on page 1.
            add(f'<tr><td class="nm">{_sb_esc(_f["player"])}</td>'
                f'<td class="{_cls}">{_sb_esc(_f["call"])}</td><td>{_sb_fmt(_f["ft_pct"])}</td>'
                f'<td>{int(_f["ftm"])}-{int(_f["fta"])}</td></tr>')
        add("</tbody></table></div></div>")

    # TEAM STATS is no longer a section of its own: its strip is inside TEAM COMPARISON, under the four
    # factors (requested). Its headline went with it, and good riddance -- it read "Biggest gap: FT Rate" off
    # _ff_top, Dean Oliver's FIXED weighting, while the table right above it had free throws fourth at +0.9
    # and shot quality first. Two rankings of the same four factors contradicting each other on one page,
    # which is the very thing the 11/17 labels were meant to keep apart.
    # TEAMS LIKE ... sections removed from the brief (requested) -- the full panels stay in the app's Tools
    # tab. The record only reaches the brief as a Bottom Line sentence, and only when it's lopsided on
    # enough games at non-low confidence (BOTTOM_LINE_RULES "style_*").

    # =====================================================================================================
    # OPPONENT
    # =====================================================================================================
    page_break()
    divider(f"{OPP_UP}", "Scouting the opponent")

    # ---- recent results ------------------------------------------------------------------------------
    if not opp_before.empty:
        # CONFIRMED CHANGE (requested 11/22): "Remove the header of 'Hope Recent Results' and just move the section up."
        # Kept on a last-season brief, where the header is what says the games are from last year.
        section(f"\U0001f4c5 {OPP_UP} " + ("\u2014 HOW THEY FINISHED LAST SEASON" if _bt["last_season"] else "RECENT RESULTS"),
                bare=not _bt["last_season"])
        # CONFIRMED CHANGE (requested 11/18, the roster treatment applied here too): the last five games are
        # always on the page -- this section is in _SB_FIXED, so it cannot be collapsed -- and the rest of
        # their season sits behind one expander under it, the same shape as the roster's "Full roster".
        def _rs_chip(g):
            _o = _sb_clean(g.get("outcome")).upper()
            _sc = (f' {int(g["team_score"])}-{int(g["opponent_score"])}'
                   if pd.notna(g.get("team_score")) and pd.notna(g.get("opponent_score")) else "")
            _home = _sb_clean(g.get("location")).lower() == "home"
            return (f'<span class="rs">{_sb_esc(g.get("game_date"))} {"vs" if _home else "@"} '
                    f'{_sb_esc(_sb_strip_mascot(g.get("vs_opponent")))} <b class="{"w" if _o == "W" else "l"}">'
                    f'{_sb_esc(_o)}{_sc}</b></span>')

        add('<div class="card">')
        _rs_all = opp_before
        _rs_last = _rs_all.tail(5)
        # their record, and how it splits home and away -- the one line a coach wants above the games
        _rs_o = _rs_all["outcome"].astype(str).str.upper() if "outcome" in _rs_all.columns else pd.Series(dtype=str)
        _rs_w, _rs_l = int((_rs_o == "W").sum()), int((_rs_o == "L").sum())
        if _rs_w + _rs_l:
            _rs_home = _rs_all["location"].astype(str).str.lower().eq("home") if "location" in _rs_all.columns \
                else pd.Series(False, index=_rs_all.index)
            _hw, _hl = int((_rs_o.eq("W") & _rs_home).sum()), int((_rs_o.eq("L") & _rs_home).sum())
            _aw, _al = _rs_w - _hw, _rs_l - _hl
            _bits = [f"{_rs_w}-{_rs_l} so far"]
            if _hw + _hl:
                _bits.append(f"{_hw}-{_hl} at home")
            if _aw + _al:
                _bits.append(f"{_aw}-{_al} away")
            add('<p class="mini">' + _sb_esc(" \u00b7 ".join(_bits)) + "</p>")
        add('<div class="results">')
        for _, g in _rs_last.iterrows():
            add(_rs_chip(g))
        add("</div>")
        _rs_rest = _rs_all.iloc[:-len(_rs_last)] if len(_rs_all) > len(_rs_last) else _rs_all.iloc[0:0]
        if not _rs_rest.empty:
            add('<details class="rosdet"><summary><span class="rd-open">Every other game</span>'
                f'<span class="rd-sub">{len(_rs_rest)} earlier game'
                f'{"s" if len(_rs_rest) != 1 else ""} this season</span></summary>')
            add('<div class="results">')
            for _, g in _rs_rest.iterrows():
                add(_rs_chip(g))
            add("</div></details>")
        add("</div>")

    _sm_unused = None
    if not _sm.empty and "opponent" in _sm.columns:
        _sm = _sm[_sm["opponent"].astype(str) == str(short)]


    # =====================================================================================================
    # THE FILM (player tracking + court mapping) -- CONFIRMED CHANGE (requested: "the scouting brief should not have
    # a separate FROM THE FILM section ... built directly into the Players, Offensive and Defensive sections that
    # already exist"). What the tracked film shows about the opponent now rides inside their own sections:
    #   ROSTER                  each player's film line (who he guarded most, how far off his man he plays, how he
    #                           plays screens, who he screens for) -- _film_player_note, in _roster_player
    #   HOW <OPP> RUNS OFFENSE  recurring alignments, inbounds, and (court mapping good enough) shot chart, screen
    #                           spots, play diagrams -- _film_off_cards
    #   HOW <OPP> GUARDS SCREENS how their defenders play each screen on film, the defenders who play it differently,
    #                           zone / press, court traps -- _film_def_cards
    # Every film table stays in the app (Film tracking, Court view). Only the upcoming opponent's film is used
    # (TRACK_BRIEF_TEAM can name it when the spelling differs). The film-quality cell gates it: per-player lines need
    # tracking to name players on FILM_NAMES_OK_PCT of floor spots; court pictures need the court mapping to pass.
    # Prepared here, before the roster, because the roster carries each player's line.
    # =====================================================================================================
    _tk_clips = _sb_d("uww_trk_clips")
    _fq = _sb_d("uww_film_quality")
    _fq_of = lambda t: (_fq[_fq["team"].astype(str) == str(t)].iloc[0].to_dict()
                        if t and not _fq.empty and "team" in _fq.columns and (_fq["team"].astype(str) == str(t)).any() else {})
    _fq_true = lambda v: str(v).strip().lower() in ("true", "1")
    _fq_pct = lambda v: (lambda x: f"{int(round(x))}" if pd.notna(x) else None)(pd.to_numeric(v, errors="coerce"))
    _tk_unnamed = lambda v: "unnamed" in str(v).lower() or not _sb_clean(v)
    _tk_team = None
    if not _tk_clips.empty and {"offense_team", "defense_team"} <= set(_tk_clips.columns):
        def _tk_is(team, label):
            words = {w for w in re.split(r"[\s\-@()]+", str(label).lower()) if len(w) > 3 and w not in ("titans", "warhawks")}
            return any(w in str(team).lower() for w in words)
        _tk_teams = pd.concat([_tk_clips["offense_team"], _tk_clips["defense_team"]]).dropna().astype(str)
        _tk_teams = _tk_teams[~_tk_teams.str.lower().str.contains("whitewater")]
        _tk_team = next((t for t in _tk_teams.value_counts().index
                         if _tk_is(t, globals().get("TRACK_BRIEF_TEAM") or short)), None)
    _tk_n = (int(((_tk_clips["offense_team"].astype(str) == str(_tk_team))
                  | (_tk_clips["defense_team"].astype(str) == str(_tk_team))).sum()) if _tk_team else 0)
    _tk_q = _fq_of(_tk_team) if _tk_team else {}
    _tk_names_ok = _fq_true(_tk_q.get("names_ok")) if _tk_q else False
    _tk_court_ok = _fq_true(_tk_q.get("court_ok")) if _tk_q else False
    _D = lambda name, col: ((lambda d: d[d[col].astype(str) == str(_tk_team)] if not d.empty and col in d.columns
                             else pd.DataFrame())(_sb_d(name)) if _tk_team else pd.DataFrame())
    _film_app_link = lambda label="Film tracking": app_link(label, page="upcoming", tab="game_plan", section="film_tracking")

    def _tk_table(df, cols, heads, limit=10):
        if df.empty:
            return ""
        h = "".join(f'<th style="text-align:left">{_sb_esc(x)}</th>' for x in heads)
        body = ""
        for _, r in df.head(limit).iterrows():
            body += "<tr>" + "".join(f'<td style="text-align:left">{_sb_esc(_sb_clean(r.get(c)))}</td>' for c in cols) + "</tr>"
        more = f'<p class="mini">+{len(df) - limit} more in the app.</p>' if len(df) > limit else ""
        return f'<table class="compact"><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>{more}'

    _film_cards_n = [0]             # film cards drawn so far (a section's trailing note / link only follows real cards)

    def _film_card(title, body):
        if not body:
            return
        _film_cards_n[0] += 1
        add(f'<div class="card"><div class="pc-sub">\U0001f3a5 {title}</div>{body}</div>')

    def _cz_png(shots=None, diagram=None, title=""):
        """Half court (basket at top) as an embedded PNG: shots (green made / red missed) or a play diagram."""
        import base64, io
        from PIL import Image, ImageDraw
        S, W, H = 6, 300, 290
        im = Image.new("RGB", (W, H), (236, 214, 170))
        d = ImageDraw.Draw(im)
        P = lambda hx, hy: (hy * S, hx * S + 4)
        white, ink = (255, 255, 255), (40, 40, 40)
        d.rectangle([P(0, 0), P(47, 50)], outline=white, width=2)
        d.rectangle([P(0, 19), P(19, 31)], outline=white, width=2)
        d.ellipse([P(13, 19), P(25, 31)], outline=white, width=2)
        d.line([P(0, 3.33), P(9.83, 3.33)], fill=white, width=2)
        d.line([P(0, 46.67), P(9.83, 46.67)], fill=white, width=2)
        arc = [P(5.25 + 22.146 * np.cos(a), 25 + 22.146 * np.sin(a)) for a in np.linspace(-1.35, 1.35, 60)]
        d.line(arc, fill=white, width=2)
        d.line([P(4, 22), P(4, 28)], fill=ink, width=2)
        d.ellipse([P(4.5, 24.25), P(6.0, 25.75)], outline=(200, 60, 30), width=2)
        if shots is not None:
            for _, s_ in shots.iterrows():
                x, y = P(float(s_["hx"]), float(s_["hy"]))
                col = (40, 150, 60) if str(s_["made"]) == "True" else (200, 40, 40)
                d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=col, outline=ink)
        if diagram is not None:
            dg = diagram if isinstance(diagram, dict) else (globals().get("_trk_json") or __import__("json")).loads(diagram)
            pos = {}
            for p_ in dg.get("players", []):
                pts = [P(hx, hy) for _, hx, hy in p_["path"]]
                if not pts:
                    continue
                if p_["side"] == "offense" and p_.get("num"):
                    pos[p_["num"]] = {int(t): P(hx, hy) for t, hx, hy in p_["path"]}
                    if len(pts) > 1:
                        d.line(pts, fill=ink, width=2)
                        (x1, y1), (x2, y2) = pts[-2], pts[-1]
                        ang = np.arctan2(y2 - y1, x2 - x1)
                        d.polygon([(x2, y2), (x2 - 9 * np.cos(ang - 0.4), y2 - 9 * np.sin(ang - 0.4)),
                                   (x2 - 9 * np.cos(ang + 0.4), y2 - 9 * np.sin(ang + 0.4))], fill=ink)
                    x0, y0 = pts[0]
                    d.ellipse([x0 - 8, y0 - 8, x0 + 8, y0 + 8], fill=(255, 255, 255), outline=ink, width=2)
                    d.text((x0 - 3, y0 - 6), str(p_["num"]), fill=ink)
                elif p_["side"] == "defense":
                    x, y = pts[0]
                    d.line([x - 4, y - 4, x + 4, y + 4], fill=(30, 110, 190), width=2)
                    d.line([x - 4, y + 4, x + 4, y - 4], fill=(30, 110, 190), width=2)
            for ps in dg.get("passes", []):
                a, b = pos.get(ps["from"], {}), pos.get(ps["to"], {})
                if a and b:
                    pa = a[min(a, key=lambda t: abs(t - ps["t"]))]
                    pb = b[min(b, key=lambda t: abs(t - ps["t"]))]
                    for k in range(0, 10, 2):   # dashed pass line
                        d.line([(pa[0] + (pb[0] - pa[0]) * k / 10, pa[1] + (pb[1] - pa[1]) * k / 10),
                                (pa[0] + (pb[0] - pa[0]) * (k + 1) / 10, pa[1] + (pb[1] - pa[1]) * (k + 1) / 10)], fill=ink, width=2)
            sc = dg.get("screen")
            if sc:
                x, y = P(sc["hx"], sc["hy"])
                d.line([x - 7, y, x + 7, y], fill=(200, 40, 40), width=3)   # the screen "T"
                d.line([x, y, x, y - 7], fill=(200, 40, 40), width=3)
        if title:
            d.text((4, H - 12), title[:48], fill=ink)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return f'<img src="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}" width="{W}" height="{H}" style="margin:4px"/>'

    # ---- the roster: each player's film line, and why it's missing when it is -------------------------
    _film_player_note = {}
    _film_roster_note = ""          # added to the roster's footnote
    _film_names_gate = ""           # one line under the roster while names aren't trusted yet
    if _tk_team:
        _film_roster_note = (
            f"\U0001f3a5 lines are from player tracking on {_tk_n} tracked clip(s) of {_tk_team}: who he guarded most, how "
            "far off his man he plays, how he plays screens and who he screens for. Only once tracking names players "
            f"on {int(globals().get('FILM_NAMES_OK_PCT', 50))}%+ of their floor spots, and never from a player it "
            "couldn't name; names on film are partly best guesses until the coaches' player checks confirm them. "
            "Approximate feet, small sample.")
        if not _tk_names_ok:
            _film_names_gate = (
                '<p class="mini">\U0001f3a5 Each player\'s film read (who he guards, how far off his man he plays, how he '
                "plays screens, who he screens for) goes here once tracking names the players on at least "
                f"{int(globals().get('FILM_NAMES_OK_PCT', 50))}% of {_sb_esc(_tk_team)} floor spots"
                + (f" (now {_fq_pct(_tk_q.get('named_share_pct'))}%)" if _fq_pct(_tk_q.get("named_share_pct")) is not None else "")
                + ": " + _film_app_link() + "</p>")
        else:
            _orl = _sb_d("uww_offensive_roles")
            _role_of = ({_norm(p): r for p, r in zip(_orl["player"], _orl["offensive_role"])}
                        if not _orl.empty and {"player", "offensive_role"} <= set(_orl.columns) else {})
            _fp = {}
            _m = _D("uww_trk_matchups", "defense_team")
            if not _m.empty and {"defender", "guards", "possessions"} <= set(_m.columns):
                _m = _m[[not (_tk_unnamed(a) or _tk_unnamed(b)) for a, b in zip(_m["defender"], _m["guards"])]].copy()
                _m["_poss"] = pd.to_numeric(_m["possessions"], errors="coerce").fillna(0)
                for _dn, _g in _m.groupby("defender"):
                    _tot = _g["_poss"].sum()
                    if _tot < 3:
                        continue
                    _top = _g.sort_values("_poss", ascending=False).iloc[0]
                    _rl = _g.assign(_r=_g["guards"].map(lambda n: _role_of.get(_norm(n)))).dropna(subset=["_r"])
                    _rtxt = ""
                    if len(_rl):
                        _rs = _rl.groupby("_r")["_poss"].sum().sort_values(ascending=False)
                        _rtxt = f" -- {round(100 * _rs.iloc[0] / _tot)}% of them on our {_rs.index[0]}s"
                    _fp.setdefault(_norm(_dn), []).append(
                        f"guarded {_sb_title(_top['guards'])} most ({int(_top['_poss'])} of {int(_tot)} poss{_rtxt})")
            _hh = _D("uww_trk_help", "defense_team")
            if not _hh.empty and "defender" in _hh.columns:
                for _, r in _hh[[not _tk_unnamed(x) for x in _hh["defender"]]].iterrows():
                    _ws = pd.to_numeric(r.get("approx_ft_off_man_weak side"), errors="coerce")
                    if pd.notna(_ws):
                        _fp.setdefault(_norm(r["defender"]), []).append(
                            f"plays about {_ws:.0f} ft off his man on the weak side"
                            + (f" ({_sb_clean(r.get('tendency'))})" if _sb_clean(r.get("tendency")) else ""))
            _c = _D("uww_trk_screen_coverage", "defense_team")
            if not _c.empty and {"defender", "screen_type", "coverage", "times"} <= set(_c.columns):
                _c = _c[[not _tk_unnamed(x) for x in _c["defender"]]].copy()
                _c["_t"] = pd.to_numeric(_c["times"], errors="coerce").fillna(0)
                for (_dn, _stp), _g in _c.groupby(["defender", "screen_type"]):
                    _top = _g.sort_values("_t", ascending=False).iloc[0]
                    if _top["_t"] >= 2:
                        _fp.setdefault(_norm(_dn), []).append(
                            f"{_stp.lower()}s: {_top['coverage']} {int(_top['_t'])} of {int(_g['_t'].sum())}")
            _sp = _D("uww_trk_screen_pairs", "offense_team")
            if not _sp.empty and {"screener", "screened", "times"} <= set(_sp.columns):
                _sp = _sp[[not (_tk_unnamed(a) or _tk_unnamed(b)) for a, b in zip(_sp["screener"], _sp["screened"])]].copy()
                _sp["_t"] = pd.to_numeric(_sp["times"], errors="coerce").fillna(0)
                for _sn, _g in _sp.groupby("screener"):
                    _top = _g.sort_values("_t", ascending=False).iloc[0]
                    if _top["_t"] < 2:
                        continue
                    _after = ", ".join(f"{k} {int(_g[c].sum())}" for k, c in (("rolls", "rolls"), ("pops", "pops"), ("slips", "slips"))
                                       if c in _g.columns and int(pd.to_numeric(_g[c], errors="coerce").fillna(0).sum()))
                    _fp.setdefault(_norm(_sn), []).append(
                        f"screens for {_sb_title(_top['screened'])} most ({int(_top['_t'])}x)" + (f", then {_after}" if _after else ""))
            if _tk_court_ok:
                _ch = _D("uww_court_help", "defense_team")
                if not _ch.empty and "defender" in _ch.columns:
                    for _, r in _ch[[not _tk_unnamed(x) for x in _ch["defender"]]].iterrows():
                        _ip = pd.to_numeric(r.get("weak_side_in_paint_pct"), errors="coerce")
                        if pd.notna(_ip):
                            _fp.setdefault(_norm(r["defender"]), []).append(f"in the paint on {_ip:.0f}% of his weak-side frames")
            _film_player_note = {("Opponent", k): "Film: " + "; ".join(v[:3]) for k, v in _fp.items() if v}

    # ---- their defense on film: built into HOW <OPP> GUARDS SCREENS ------------------------------------
    _film_def_note = (f"\U0001f3a5 From the film: player tracking on {_tk_n} tracked clip(s) of {_tk_team}. Each tracked "
                      "screen's coverage is the coaches' tag when the clip has one, else tracking's own estimate (marked *: "
                      "stayed attached vs went under / behind). Defenders who play it differently need tracking to name "
                      "players first. Small sample -- a lead to check on film." if _tk_team else "")

    def _film_def_cards():
        if not _tk_team:
            return
        _scr = _D("uww_trk_screens", "defense_team")
        _film_main = {}
        if not _scr.empty and "screen_type" in _scr.columns:
            _scr = _scr.assign(_cov=_scr["coverage"].fillna("unclear").astype(str),
                               _est=_scr.get("coverage_source", pd.Series("", index=_scr.index)).astype(str).eq("tracking estimate"),
                               _pts=pd.to_numeric(_scr.get("points"), errors="coerce"))
            # "Usually by" (a defender's name) only when tracking names enough players to trust it
            _rows = ['<table class="compact"><thead><tr><th style="text-align:left">Screen</th><th>Tracked</th>'
                     '<th style="text-align:left">Main coverage</th><th>PPP</th><th style="text-align:left">Also</th>'
                     + ('<th style="text-align:left">Usually by</th>' if _tk_names_ok else "") + '</tr></thead><tbody>']
            for _st, _g in sorted(_scr.groupby("screen_type"), key=lambda x: -len(x[1])):
                _vc = _g.groupby("_cov").agg(n=("_cov", "size"), est=("_est", "mean"), ppp=("_pts", "mean")).sort_values("n", ascending=False)
                _mc, _mr = _vc.index[0], _vc.iloc[0]
                _film_main[_st] = _mc
                _star = "*" if _mr["est"] > 0.5 else ""
                _also = ", ".join(f"{_sb_esc(c)}{'*' if r_['est'] > 0.5 else ''} {round(100 * r_['n'] / len(_g))}% ({int(r_['n'])})"
                                  for c, r_ in _vc.iloc[1:4].iterrows()) or "&mdash;"
                _by = (_g[_g["_cov"] == _mc]["screened_defender"].dropna().astype(str).value_counts()
                       if "screened_defender" in _g.columns and _tk_names_ok else pd.Series(dtype=int))
                _by = _by[[not _tk_unnamed(x) for x in _by.index]] if len(_by) else _by
                _thin = "*" if len(_g) < 5 else ""
                _rows.append(f'<tr><td style="text-align:left">{_sb_esc(_st)}{_thin}</td><td>{len(_g)}</td>'
                             f'<td style="text-align:left"><b>{_sb_esc(_mc)}{_star}</b> {round(100 * _mr["n"] / len(_g))}% ({int(_mr["n"])})</td>'
                             f'<td>{_sb_fmt(_mr["ppp"], 2)}</td><td style="text-align:left">{_also}</td>'
                             + (f'<td style="text-align:left">{_sb_esc(_by.index[0]) if len(_by) else "&mdash;"}</td>'
                                if _tk_names_ok else "") + '</tr>')
            _rows.append("</tbody></table>")
            _exc = []
            _c = _D("uww_trk_screen_coverage", "defense_team")
            if not _c.empty and "defender" in _c.columns:
                _c = _c[[not _tk_unnamed(x) for x in _c["defender"]]]
            if _tk_names_ok and not _c.empty and {"defender", "screen_type", "coverage", "times"} <= set(_c.columns):
                for (_st, _who), _g in _c.groupby(["screen_type", "defender"]):
                    _top = _g.sort_values("times", ascending=False).iloc[0]
                    _n = int(_g["times"].sum())
                    if int(_top["times"]) >= 2 and str(_top["coverage"]) != str(_film_main.get(_st)):
                        _exc.append((_n, f"<b>{_sb_esc(_who)}</b> &mdash; {_sb_esc(_st)}: {_sb_esc(_top['coverage'])} "
                                         f"{int(_top['times'])} of {_n} (team: {_sb_esc(_film_main.get(_st, '?'))})"))
            if _exc:
                _rows.append('<div class="pc-sub">Defenders who play it differently on film</div><ul class="mini">'
                             + "".join(f"<li>{t}</li>" for _, t in sorted(_exc, key=lambda x: -x[0])[:5]) + "</ul>")
            _rows.append('<p class="mini">* main coverage mostly from tracking\'s own estimate (no coach tag); screen types '
                         'marked * have under 5 tracked. PPP = points on those possessions.</p>')
            _film_card("On film: how their defenders play screens", "".join(_rows))
        _zp = _D("uww_trk_zone_press", "defense_team")
        if not _zp.empty and {"zone", "press"} <= set(_zp.columns):
            _z, _p = _zp[_zp["zone"].astype(str) == "True"], _zp[_zp["press"].astype(str) == "True"]
            if len(_z) or len(_p):
                _zt = (f"Zone on {len(_z)} tracked clip(s)"
                       + (f", spread about {_sb_fmt(pd.to_numeric(_z.get('zone_width_ft_approx'), errors='coerce').mean(), 0)} ft wide and "
                          f"{_sb_fmt(pd.to_numeric(_z.get('zone_depth_ft_approx'), errors='coerce').mean(), 0)} ft deep")
                       + f", {_sb_fmt(pd.to_numeric(_z['points'], errors='coerce').mean(), 2)} PPP. " if len(_z) else "No zone clips tracked. ")
                _trapped = _p[pd.to_numeric(_p.get("trap_frames"), errors="coerce").fillna(0) > 0] if len(_p) else _p
                _pt = (f"Pressed on {len(_p)} clip(s); trapped on {len(_trapped)}"
                       + (f", first trap about {_sb_fmt(pd.to_numeric(_trapped['first_trap_seconds_into_clip'], errors='coerce').mean(), 1)} s into the clip" if len(_trapped) else "")
                       + "." if len(_p) else "No press clips tracked.")
                _film_card("On film: zone and press", f'<p class="mini">{_sb_esc(_zt + _pt)} Layouts are drawn in the app.</p>')
        if _tk_court_ok:
            _zc = _D("uww_court_zone_press", "defense_team")
            if not _zc.empty:
                _al = _zc["alignment"].dropna().value_counts() if "alignment" in _zc.columns else pd.Series(dtype=int)
                _tp = _zc["trap_spot"].dropna().value_counts() if "trap_spot" in _zc.columns else pd.Series(dtype=int)
                if len(_al) or len(_tp):
                    _film_card("On the court: zone alignment and trap spots", '<p class="mini">'
                               + _sb_esc(("Zone read from the court: " + ", ".join(f"{a} x{n}" for a, n in _al.items()) + ". ") if len(_al) else "")
                               + _sb_esc(("Traps: " + ", ".join(f"{a} x{n}" for a, n in _tp.items()) + ".") if len(_tp) else "") + "</p>")

    # ---- their offense on film: built into HOW <OPP> RUNS OFFENSE -------------------------------------
    _film_off_note = (f"\U0001f3a5 From the film: player tracking on {_tk_n} tracked clip(s) of {_tk_team}. Recurring "
                      "alignments are the same spots on the floor seen again and again (drawn in the app); inbounds are "
                      "grouped by situation. Court pictures (shot chart, screen spots, play diagrams) only once the court "
                      "mapping passes the film-quality check. Small sample -- a lead to check on film." if _tk_team else "")

    def _film_off_cards():
        if not _tk_team:
            return
        _n0 = _film_cards_n[0]
        _st = _D("uww_trk_sets", "offense_team")
        if not _st.empty and {"most_common_call", "call_share_pct"} <= set(_st.columns):
            _st = _st.assign(call=_st["most_common_call"].astype(str) + " ("
                             + pd.to_numeric(_st["call_share_pct"], errors="coerce").fillna(0).astype(int).astype(str) + "%)")
            _film_card("On film: recurring alignments (diagrams in the app)",
                       _tk_table(_st, ["set_id", "clips", "call", "situations", "ppp"],
                                 ["Alignment", "Clips", "Most common tagged call", "Situations", "PPP"]))
        _ib = _D("uww_trk_inbounds", "offense_team")
        if not _ib.empty and {"situation", "alignment"} <= set(_ib.columns):
            _ib = (_ib.groupby(["situation", "alignment"]).agg(clips=("clip_key", "count"), ppp=("points", "mean"))
                   .reset_index().sort_values("clips", ascending=False))
            _ib["ppp"] = _ib["ppp"].round(2)
            _film_card("On film: inbounds alignments",
                       _tk_table(_ib, ["situation", "alignment", "clips", "ppp"], ["Situation", "Alignment", "Clips", "PPP"]))
        _cz_any = not _sb_d("uww_court_report").empty or not _sb_d("uww_court_shots").empty
        if _tk_court_ok:
            _sh = _D("uww_court_shots", "offense_team")
            _zn = _D("uww_court_shot_zones", "offense_team")
            if not _sh.empty:
                _zt = _zn[_zn["shooter"] == "TEAM"].sort_values("attempts", ascending=False) if not _zn.empty else pd.DataFrame()
                # only spots that match the play-by-play (a 3 outside the arc, a 2 inside it, ...) -- see _cz_shots
                _n_all = len(_sh)
                if "location_ok" in _sh.columns:
                    _sh = _sh[_sh["location_ok"].astype(str).str.lower() == "true"]
                _aside = _n_all - len(_sh)
                _film_card("On the court: where they shoot (tracked shots)",
                           _cz_png(shots=_sh, title=f"{len(_sh)} tracked shots" + (f" ({_aside} set aside)" if _aside else ""))
                           + (f'<p class="mini">{_aside} of {_n_all} tracked shots were left off: the shooter\'s spot on film '
                              "didn't match the shot in the play-by-play (a 3 inside the arc, a 2 outside it, a layup far from "
                              "the rim). They come back as tracking improves.</p>" if _aside else "")
                           + (_tk_table(_zt.assign(fg=_zt["makes"].astype(int).astype(str) + "/" + _zt["attempts"].astype(int).astype(str)),
                                        ["zone", "fg", "fg_pct", "pts_per_shot"], ["Zone", "Made/Att", "FG%", "Pts/shot"])
                              if not _zt.empty else ""))
            _scz = _D("uww_court_screen_zones", "offense_team")
            if not _scz.empty:
                _film_card("On the court: where they set screens, and how they were guarded",
                           _tk_table(_scz.sort_values("screens", ascending=False), ["zone", "screen_type", "coverage", "screens", "ppp"],
                                     ["Spot", "Screen", "Coverage", "Screens", "PPP"]))
            _sets_c = _D("uww_trk_sets", "offense_team")
            _dg = _sb_d("uww_court_diagrams")
            if not _sets_c.empty and not _dg.empty and "example_clip" in _sets_c.columns:
                pics = ""
                for _, s_ in _sets_c.sort_values("clips", ascending=False).head(2).iterrows():
                    hit = _dg[_dg["clip_key"] == s_["example_clip"]]
                    if len(hit):
                        pics += _cz_png(diagram=hit.iloc[0]["diagram"], title=f"{s_['set_id']} ({int(s_['clips'])} clips)")
                if pics:
                    _film_card("On the court: their most common alignments, drawn from a real possession "
                               "(numbers = offense, x = defense, dashed = pass, red T = screen)", pics)
        if _film_cards_n[0] == _n0:
            return                      # nothing on film to show -- no note or link on their own
        if not _tk_court_ok and _cz_any:
            add('<p class="mini">\U0001f3a5 Court-mapped film (shot chart, screen spots, play diagrams) stays in the app until '
                f"the court mapping places {int(globals().get('FILM_COURT_OK_MAPPED', 60))}%+ of frames and shot spots agree "
                f"{int(globals().get('FILM_COURT_OK_ZONE', 80))}%+ with the play-by-play"
                + (f" (now {_fq_pct(_tk_q.get('court_mapped_pct')) or '?'}% and {_fq_pct(_tk_q.get('shot_zone_agree_pct')) or '?'}%)"
                   if _tk_q else "") + ": " + _film_app_link("Court view") + "</p>")
        add('<p class="mini">' + _film_app_link("Film tracking: diagrams, possession replays, search by player") + "</p>")

    # ---- personnel: starters page + bench page (#3) ---------------------------------------------------
    _no_min = _sb_d("uww_roster_no_minutes")
    _no_min_names = ""
    if not _no_min.empty and "opponent" in _no_min.columns:
        _no_min = _no_min[_no_min["opponent"].astype(str) == str(short)]
        if not _no_min.empty and int(_no_min.iloc[0].get("count") or 0):
            _no_min_names = _sb_clean(_no_min.iloc[0]["names"])
    _opp_stats = players_for("uww_opponent_prior_games_box_score", short)
    # (11/22: no page break -- the starters sit directly under the recent results)
    personnel_pages("Opponent", OPP_UP, _opp_stats, opp_card, extra_no_min=_no_min_names, break_first=False)

    # ---- lineups, offense, context --------------------------------------------------------------------
    # (11/22: no page break -- the lineups are part of the roster's card, under the starters)
    lineups = _sb_d("uww_opp_lineup_season_box")
    # This table has no opponent column. The key-building cell checks its names against this opponent's
    # roster and sets _ktv_opp_lu to None when it's a stale table from the previous opponent -- honour that
    # here too, instead of printing someone else's lineups under this opponent's name.
    if not lineups.empty and globals().get("_ktv_opp_lu", "unchecked") is None:
        print(f"TOP LINEUPS skipped: uww_opp_lineup_season_box doesn't match {short}'s roster (stale table?).")
        lineups = pd.DataFrame()
    if not lineups.empty and "lineup" in lineups.columns:
        # CONFIRMED CHANGE (requested 11/18): "Remove the 'OUR TOP LINEUPS & 3-MAN COMBOS' header ...
        # And this also needs to be done for their top lineups." No section bar at all: the cards are the
        # heading now. The methodology note that hung off the title rides on the "Full tables" bar instead,
        # so the link to it is not lost with the header.
        _lu_note = footnote(
            "Five-man units: the top 2 in each of MIN, +/-, per 40, PPP and 3P% (bold = top 2 in that column), plus the five on the floor for the most tagged possessions. per 40 and 3P% rank units with "f"{LINEUP_TABLE_RULES['five_min_minutes']:.0f}+ minutes (3P% needs 3+ attempts, PPP 3+ tagged possessions). "
            "3-man combos: their best three, ranked by scoring margin per 40 "
            f"minutes, shrunk toward zero as if {LINEUP_TABLE_RULES['shrink_minutes']:.0f} minutes of an even "
            "game were added, so a short hot stretch can't top the list. A five-man unit needs "
            f"{LINEUP_TABLE_RULES['five_min_minutes']:.0f}+ minutes and a combo "
            f"{LINEUP_TABLE_RULES['opp_three_min_minutes']:.0f}+; * marks a unit shown below that floor "
            "because fewer than three cleared it. Includes all minutes: their lineup data has no score at the "
            "start of each stint, so garbage time can't be set aside. A combo's minutes are every stint with "
            "all three on the floor, whoever the other two were. GP isn't shown for their combos: games "
            "played can't be counted exactly from their lineup data. The key shown "
            "is the first data-driven key for that unit. \"What they run\" is the sets tagged on possessions with "
            "that exact five on the floor, and \"Group\" is its position shape (3G-2B = three guards and two "
            "bigs, from roster positions). Every lineup's full strengths, weaknesses and keys are in the app.")
        _open_or_join_card()
        _lu_cards("Opponent", lineups)
        add('<details class="rosdet"><summary><span class="rd-open">Full tables</span>'
            '<span class="rd-sub">every five-man unit and 3-man combo, with what they run</span>'
            + _lu_note + "</summary>")
        lineups_table(lineups, "Opponent")
        # Top three 3-man combos under the five-man units (requested). Captured first so the sub-heading
        # only prints when there is a table to put under it.
        _combo_html = capture(combos_table, "Opponent")
        if _combo_html:
            add('<div class="pc-sub">Top 3-man combos</div>')
            add("".join(_combo_html))
        add('<p class="mini">' + app_link("All lineups and combos with full reads", page="upcoming",
                                          tab="personnel", section="lineups") + "</p>")
        add("</details></div>")

    # =====================================================================================================
    # HOW THEY GUARD SCREENS (requested) -- from the structured tags' defensive details ("5tl" = defender #5
    # top-locked the down screen). Rendered from uww_screen_coverage_summary, built in the play-calls cell;
    # nothing is computed here beyond picking rows. Perspective "Opponent defense" = the upcoming opponent
    # DEFENDING, from their own defensive possessions in opponent_plays.csv. Every row prints its count.
    # =====================================================================================================
    # CONFIRMED CHANGE (requested): how their defenders play screens ON FILM (player tracking) is built into this
    # section instead of a separate FROM THE FILM section -- after the coach-tag card, or on its own when their
    # defense isn't coach-tagged yet. See _film_def_cards ("THE FILM", above the roster).
    _fd_html = capture(_film_def_cards)

    # CONFIRMED CHANGE (requested 11/22): "Change 'HOW HOPE RUNS OFFENSE' to 'HOPE OFFENSE' and create a 'HOPE DEFENSE' section as
    # well with 5 cards. One of these cards should include the 'HOW HOPE GUARDS SCREEN' section." The screens section is now
    # the Screens card plus, behind "Show the detail", the tables it always had. Cards: base defense, pressure, screens,
    # points allowed, and who closes things down. No possession counts in the visible text (requested 11/18).
    def _dcard(title, name, value, sub, note=""):
        return (f'<div class="lc"><div class="lc-t">{_sb_esc(title)}</div><div class="lc-n">{name}</div>'
                + (f'<div class="lc-v">{_sb_esc(value)}</div>' if value else "")
                + (f'<div class="lc-s">{_sb_esc(sub)}</div>' if sub else "")
                + (f'<div class="lc-x">{note}</div>' if note else "") + "</div>")

    def _def_cards(screen_line):
        _cards = []
        _od = _sb_d("uww_opp_defense")
        _od = _od[_od["opponent"].astype(str) == str(short)] if not _od.empty and "opponent" in _od.columns else _od
        _item = lambda k: next((str(r.get("what_they_do") or "") for _, r in _od.iterrows()       # noqa: E731
                                if str(r.get("item")).strip().lower() == k), "") if not _od.empty else ""
        _nocount = lambda t: re.sub(r"\s*\(\d+x\)", "", re.sub(r"\s+of\s+\d+\s+tagged possessions?", "", t))                # noqa: E731
        _ds = _sb_d("uww_defense_by_situation")
        _ds = _ds[_ds["opponent"].astype(str) == str(short)] if not _ds.empty and "opponent" in _ds.columns else _ds
        # 1. base defense
        _base = _nocount(_item("base defense"))
        if _base:
            _bits = []
            if not _ds.empty:
                for _, r in _ds.iterrows():
                    if str(r.get("situation")) in ("Half court", "Transition", "BLOB", "SLOB") and pd.notna(r.get("primary_defense")):
                        _bits.append(f'{_sb_esc(r["situation"])}: {_sb_esc(r["primary_defense"])} {int(pd.to_numeric(r.get("freq_pct"), errors="coerce") or 0)}%')
            _m = re.match(r"\s*([^;]+?)\s+on\s+(\d+)%", _base)
            _cards.append(_dcard("Base defense", _sb_esc(_m.group(1)) if _m else _sb_esc(_base.split(";")[0]),
                                 f"{_m.group(2)}% of their possessions" if _m else "", "",
                                 ((_sb_esc(_base.split(";", 1)[1].strip()) + "<br>") if ";" in _base else "")
                                 + " \u00b7 ".join(_bits)))
        # 2. pressure
        _pr = _item("pressure")
        _pm = re.search(r"Pressed on (\d+) of (\d+)", _pr)
        if _pr:
            _pp = int(round(100 * int(_pm.group(1)) / max(int(_pm.group(2)), 1))) if _pm else None
            _kinds = _pr.split("--", 1)[1].strip() if "--" in _pr else ""
            _kl = [k.strip() for k in _kinds.split(",") if k.strip()]
            _cards.append(_dcard("Pressure", _sb_esc(_kl[0]) if _kl else "Presses",
                                 f"presses on {_pp}% of possessions" if _pp is not None else "", "",
                                 _sb_esc(", ".join(_kl[1:]))))
        # 3. screens (the old HOW <OPP> GUARDS SCREENS headline, plus the coverages named in their defense row)
        _bsc = _item("ball-screen coverage")
        if screen_line or _bsc:
            _cards.append(_dcard("Screens", screen_line or _sb_esc(_nocount(_bsc)), "" , "",
                                 (_sb_esc(_nocount(_bsc)) if screen_line and _bsc else "")
                                 + ("<br>Full tables below." if screen_line else "")))
        # 4. points allowed, from their own defensive possessions (possession_side Defense in their files)
        try:
            _spc = globals().get("season_play_calls")
            _pc_s = _spc(_pcc_all) if callable(_spc) else _pcc_all           # this season only, like the offense tables
            _dp = _pc_s[(_pc_s["side"].astype(str) == "Opponent") & (_pc_s["possession_side"].astype(str) == "Defense")]
            _dp = _dp[~_dp["synergy_string"].astype(str).str.lower().str.contains("non possession", na=False)]
            _dp = _dp.assign(_pt=pd.to_numeric(_dp["points"], errors="coerce")).dropna(subset=["_pt"])
        except Exception:
            _dp = pd.DataFrame()
        if len(_dp) >= 10:
            _ppp = _dp["_pt"].mean()
            _by = _dp.groupby(_dp["play_situation"].astype(str))["_pt"].agg(["mean", "count"])
            _by = _by[_by["count"] >= 5].sort_values("mean")
            _tov = (_dp["result"].astype(str) == "Turnover").mean() * 100
            _fl = (_dp["result"].astype(str).str.contains("Foul", na=False)).mean() * 100
            _lines = []
            if len(_by) >= 2:
                _lines.append(f'<b>Best against:</b> {_sb_esc(_by.index[0])} {_by.iloc[0]["mean"]:.2f} PPP')
                _lines.append(f'<b>Worst against:</b> {_sb_esc(_by.index[-1])} {_by.iloc[-1]["mean"]:.2f} PPP')
            _cards.append(_dcard("Points allowed", f"{_ppp:.2f} PPP", f"{_tov:.0f}% of trips end in a turnover",
                                 f"{_fl:.0f}% end in a foul", "<br>".join(_lines)))
        # 5. who closes things down: steals + blocks a game, from the box scores
        _dr = _sb_d("uww_defensive_roles")
        if not _dr.empty and {"team", "player", "steals_blocks_per_game", "games"} <= set(_dr.columns):
            _dr = _dr[(_dr["team"].astype(str) == str(short)) & (_dr["player"].astype(str) != str(short))].copy()
            _dr["_sb"] = pd.to_numeric(_dr["steals_blocks_per_game"], errors="coerce")
            _dr = _dr[pd.to_numeric(_dr["games"], errors="coerce") >= 2].sort_values("_sb", ascending=False)
            if not _dr.empty and _dr.iloc[0]["_sb"] > 0:
                _t = _dr.iloc[0]
                _rest = "<br>".join(f'<b>{_sb_esc(r["player"].split()[-1])}</b> {r["_sb"]:.1f} \u00b7 {_sb_esc(str(r.get("defensive_role") or ""))}'
                                    for _, r in _dr.iloc[1:4].iterrows() if r["_sb"] > 0)
                _cards.append(_dcard("Who closes it down", _sb_esc(str(_t["player"])), f'{_t["_sb"]:.1f} steals + blocks a game',
                                     _sb_esc(str(_t.get("defensive_role") or "")), _rest))
        return ('<div class="lcards wm-cards">' + "".join(_cards) + "</div>") if len(_cards) >= 2 else ""

    _scv_s = _sb_d("uww_screen_coverage_summary")
    if not _scv_s.empty and {"perspective", "level", "scouted_opponent"}.issubset(_scv_s.columns):
        _scv_s = _scv_s[(_scv_s["scouted_opponent"].astype(str) == str(short))
                        & (_scv_s["perspective"] == "Opponent defense")]
    else:
        _scv_s = pd.DataFrame()
    if not _scv_s.empty:
        _scv_thin_n = globals().get("SCREEN_COVERAGE_RULES", {}).get("thin_screens", 5)
        _scv_t = _scv_s[_scv_s["level"] == "Screen x coverage"].copy()
        _scv_d = _scv_s[_scv_s["level"] == "Defender x screen x coverage"].copy()
        _scr_line = ""
        section(f"\U0001f6e1\ufe0f {OPP_UP} DEFENSE" + footnote(
            "From the coaches' coverage tags on their defensive possessions: each tag names the defender "
            "(by jersey) and how he played the screen, paired with the screen it answered. % is the share of "
            "that screen type. PPP is points on the possessions where that coverage was used -- what happened "
            f"after, not proof the coverage caused it. * = under {_scv_thin_n} tagged screens of that type: "
            "confirm on film." + (" " + _film_def_note if _fd_html else "")))
        if not _scv_t.empty and {"screen_type", "coverage", "uses"} <= set(_scv_t.columns):
            _sc_u = _scv_t.assign(_u=pd.to_numeric(_scv_t["uses"], errors="coerce")).dropna(subset=["_u"])
            if not _sc_u.empty and _sc_u["_u"].sum():
                _sc_ty = _sc_u.groupby("screen_type")["_u"].sum().sort_values(ascending=False)
                _sc_t1 = _sc_ty.index[0]
                _sc_cv = _sc_u[_sc_u["screen_type"] == _sc_t1].groupby("coverage")["_u"].sum().sort_values(ascending=False)
                # the table marks a thin screen type with *; a headline a coach may act on says it in words
                _sc_thin = (" \u2014 thin sample, confirm on film"
                            if int(_sc_ty.iloc[0]) < (globals().get("_scv_thin_n") or _scv_thin_n or 0) else "")
                # (11/22) this headline is now the Screens card of the defense section; no possession counts in the text
                _scr_line = (f'Against the <b>{_sb_esc(str(_sc_t1).lower())}</b> they mostly '
                             f'<b>{_sb_esc(str(_sc_cv.index[0]).lower())}</b>'
                             + (" \u2014 thin sample, confirm on film" if _sc_thin else ""))
        _sb_sechead(_def_cards(_scr_line))
        add('<div class="card">')
        add('<div class="pc-sub">How they guard screens</div>')
        add('<table class="compact"><thead><tr><th style="text-align:left">Screen</th><th>Tagged</th>'
            '<th style="text-align:left">Main coverage</th><th>PPP</th>'
            '<th style="text-align:left">Also</th><th style="text-align:left">Usually by</th></tr></thead><tbody>')
        _scv_types = _scv_t.groupby(["screen_family", "screen_type"])["uses"].sum().sort_values(ascending=False)
        _scv_main = {}
        for (_fam, _st), _tot in _scv_types.items():
            _g = _scv_t[(_scv_t["screen_type"] == _st) & (_scv_t["screen_family"] == _fam)].sort_values(
                "uses", ascending=False)
            _m = _g.iloc[0]
            _scv_main[_st] = _m["coverage"]
            _also = ", ".join(f"{_sb_esc(r['coverage'])} {int(r['share_pct'])}% ({int(r['uses'])})"
                              for _, r in _g.iloc[1:4].iterrows()) or "&mdash;"
            _thin = "*" if str(_m.get("thin_sample")).lower() == "true" else ""
            add(f'<tr><td style="text-align:left">{_sb_esc(_st)}{_thin}</td><td>{int(_tot)}</td>'
                f'<td style="text-align:left"><b>{_sb_esc(_m["coverage"])}</b> {int(_m["share_pct"])}% '
                f'({int(_m["uses"])})</td><td>{_sb_fmt(_m.get("ppp"), 2)}</td>'
                f'<td style="text-align:left">{_also}</td>'
                f'<td style="text-align:left">{_sb_esc(_sb_clean(_m.get("top_defender")))}</td></tr>')
        add("</tbody></table>")
        # Defenders who play a screen differently from the team's main call -- the actionable exceptions
        # (who to screen with, who to attack). Needs 2+ tags of that coverage from that defender.
        _scv_exc = []
        for (_st, _who), _g in (_scv_d.groupby(["screen_type", "defender"]) if not _scv_d.empty else []):
            _top = _g.sort_values("uses", ascending=False).iloc[0]
            _n = int(_g["uses"].sum())
            if int(_top["uses"]) >= 2 and _top["coverage"] != _scv_main.get(_st):
                _scv_exc.append((_n, f"<b>{_sb_esc(_who)}</b> &mdash; {_sb_esc(_st)}: "
                                     f"{_sb_esc(_top['coverage'])} {int(_top['uses'])} of {_n} "
                                     f"(team: {_sb_esc(_scv_main.get(_st, '?'))})"))
        if _scv_exc:
            add('<div class="pc-sub">Defenders who guard it differently</div><ul class="mini">'
                + "".join(f"<li>{t}</li>" for _, t in sorted(_scv_exc, key=lambda x: -x[0])[:5]) + "</ul>")
        # CONFIRMED CHANGE (requested): their ball-screen defense BY DEFENDER (coach tags that name the defender) --
        # who to put in the screen. Defenders with 2+ tagged screens (SCREEN_DEFENDER_MIN), most screens first.
        _sdf = _sb_d("uww_screen_defenders")
        if not _sdf.empty and {"perspective", "defense_team"} <= set(_sdf.columns):
            _sdf = _sdf[(_sdf["perspective"] == "Opponent defense")
                        & (_sdf["scouted_opponent"].astype(str) == str(short))].head(8)
            if not _sdf.empty:
                add('<div class="pc-sub">By defender &mdash; who to put in the screen</div>'
                    '<table class="compact"><thead><tr><th style="text-align:left">Defender</th>'
                    '<th style="text-align:left">Screen</th><th>Tagged</th><th style="text-align:left">How he plays it</th>'
                    '<th>PPP allowed</th></tr></thead><tbody>'
                    + "".join(f'<tr><td class="nm">{_sb_esc(r["defender"])}</td><td style="text-align:left">'
                              f'{_sb_esc(r["screen_family"])}</td><td>{int(r["screens"])}</td>'
                              f'<td style="text-align:left">{_sb_esc(r["coverages"])}</td>'
                              f'<td>{_sb_fmt(r.get("ppp_allowed"), 2)}</td></tr>' for _, r in _sdf.iterrows())
                    + "</tbody></table>")
        # CONFIRMED CHANGE (requested: Film Tagging's Tagger -- the defender who helps on the screen action -- in the
        # screen-defense tables, "so you can see who helps most and how often"): uww_screen_taggers (play-calls cell)
        _stg = _sb_d("uww_screen_taggers")
        if not _stg.empty and {"perspective", "scouted_opponent", "tagger"} <= set(_stg.columns):
            _stg = _stg[(_stg["perspective"] == "Opponent defense")
                        & (_stg["scouted_opponent"].astype(str) == str(short))].sort_values("helps", ascending=False).head(8)
            if not _stg.empty:
                add('<div class="pc-sub">Who helps on the screen (the tagger)</div>'
                    '<table class="compact"><thead><tr><th style="text-align:left">Defender</th>'
                    '<th style="text-align:left">Screen</th><th>Helped</th><th>Of their tagged screens</th>'
                    '<th style="text-align:left">Most on</th><th style="text-align:left">In coverage</th>'
                    '<th>PPP allowed</th></tr></thead><tbody>'
                    + "".join(f'<tr><td class="nm">{_sb_esc(r["tagger"])}</td><td style="text-align:left">'
                              f'{_sb_esc(r["screen_family"])}</td><td>{int(r["helps"])}</td>'
                              f'<td>{_sb_fmt(r.get("share_pct"), 0)}%</td>'
                              f'<td style="text-align:left">{_sb_esc(_sb_clean(r.get("most_on")))}</td>'
                              f'<td style="text-align:left">{_sb_esc(_sb_clean(r.get("in_coverage")))}</td>'
                              f'<td>{_sb_fmt(r.get("ppp_allowed"), 2)}</td></tr>' for _, r in _stg.iterrows())
                    + "</tbody></table>")
        add('<p class="mini">' + app_link("Every screen coverage, by defender", page="upcoming",
                                          tab="game_plan", section="screen_coverage") + "</p>")
        add("</div>")
        add("".join(_fd_html))
    elif _fd_html:
        section(f"\U0001f6e1\ufe0f {OPP_UP} DEFENSE" + footnote(_film_def_note))
        _sb_sechead(_def_cards(""))
        add(f'<p class="mini">{_sb_esc(OPP_UP)}\u2019s defense isn\u2019t coach-tagged yet -- this is the player '
            "tracking's read of the film.</p>")
        add("".join(_fd_html))
    elif _def_cards(""):
        section(f"\U0001f6e1\ufe0f {OPP_UP} DEFENSE")
        _sb_sechead(_def_cards(""))

    # CONFIRMED CHANGE (requested: no separate sections -- build it into the ones that exist): the reads off actions
    # are a card inside HOW <OPP> RUNS OFFENSE / HOW WE RUN OFFENSE instead of their own "READS OFF ..." sections.
    _READS_NOTE = ("Reads: from the coaches' Film Tagging -- for each action in a play, what the ball handler / trigger did "
                   "(use, reject or split the ball screen, Cobra, Fox, ...) and what the screener did after (roll, pop, "
                   "slip). Share = of that player's reads of that action. A play's points are credited to every action in "
                   "it. Players with 2+ uses of a read.")

    def _reads_card(team, title):
        """Ball handler / screener reads from Film Tagging's Actions (uww_action_reads), 2+ uses, as one card (HTML),
        or "" when there are none."""
        _ar = _sb_d("uww_action_reads")
        if _ar.empty or "offense_team" not in _ar.columns:
            return ""
        _ar = _ar[(_ar["offense_team"].astype(str) == str(team)) & (pd.to_numeric(_ar["uses"], errors="coerce") >= _READS_MIN)
                  & ~_ar["player"].astype(str).str.startswith("(")]
        if _ar.empty:
            return ""
        return ('<div class="card"><div class="pc-sub">' + _sb_esc(title) + '</div>'
                '<table class="compact"><thead><tr><th style="text-align:left">Player</th>'
                '<th style="text-align:left">Role</th><th style="text-align:left">Action</th><th style="text-align:left">Read</th>'
                '<th>Uses</th><th>Share</th><th>PPP</th></tr></thead><tbody>'
                + "".join(f'<tr><td class="nm">{_sb_esc(r["player"])}</td><td style="text-align:left">{_sb_esc(r["role"])}</td>'
                          f'<td style="text-align:left">{_sb_esc(r["action"])}</td><td style="text-align:left">{_sb_esc(r["read"])}</td>'
                          f'<td>{int(r["uses"])}</td><td>{int(pd.to_numeric(r.get("share_pct"), errors="coerce") or 0)}%</td>'
                          f'<td>{_sb_fmt(r.get("ppp"), 2)}</td></tr>'
                          for _, r in _ar.sort_values("uses", ascending=False).head(12).iterrows())
                + "</tbody></table><p class=\"mini\">"
                + app_link("Every read, by player", page="upcoming", tab="game_plan", section="reads") + "</p></div>")


    # =====================================================================================================
    # WHAT TO PLAY THEM IN -- everything here is only possible now that offense AND defense are tagged on
    # the same possession. It answers the questions a staff argues about BEFORE anyone watches film.
    #
    # In opponent_plays.csv the tagged defense is the defense the OPPONENT FACED, so these read as "how
    # Aurora's offense did against X", not "what Aurora plays on defense" (that's DEFENSE TYPE BY SITUATION
    # further down). Everything aggregates at defense FAMILY level (man / zone / press), not specific
    # coverage: with ~120 tagged possessions a specific set against a specific coverage is 2-3 clips, which
    # is noise. Clip counts are printed on every row so nobody reads a percentage off a sample of three.
    # =====================================================================================================
    _pf_opp = _pf_clips("Opponent", short)
    _pf_uww = _pf_clips("UWW")
    _pf_any = (not _pf_opp.empty) or (not _pf_uww.empty)

    # CONFIRMED CHANGE (requested 11/22): WHAT TO PLAY is no longer a section -- its data lives in the offense cards
    # ("What they're good at" / "What they struggle with"). BRIEF_WHAT_TO_PLAY_SECTION = True brings it back.
    # CONFIRMED CHANGE (requested 11/22): the "How they score against each defense" table stays, inside the Hope offense
    # section's "Show the full table" details. The block below still builds it, into a captured sink (_DFAM_CHUNKS)
    # that _offense_breakdown_card prints; only with BRIEF_WHAT_TO_PLAY_SECTION does it also get a section of its own.
    _WTP = bool(globals().get("BRIEF_WHAT_TO_PLAY_SECTION", False))
    _DFAM_CHUNKS = []
    if _pf_any:
        _sinks.append([])
        if _WTP:
            page_break()
        (section if _WTP else (lambda *_a, **_k: None))(f"\U0001f3af WHAT TO PLAY {OPP_UP} IN" + footnote(
            "Every row here is the defense the opponent's offense FACED on a tagged possession, so it reads "
            "as how they did against that look -- not what they run on defense themselves. Man, Zone and "
            "Press are families, not specific coverages: at this sample size a named coverage is a handful "
            "of clips. PPP is points per tagged possession. Treat these as things to CONFIRM on film, not "
            "as settled reads -- the clip count on each row is how much weight it carries."))
        if not _pf_opp.empty and {"_fam", "_pts"} <= set(_pf_opp.columns):
            _wp = _pf_opp.groupby("_fam")["_pts"].agg(["mean", "count"])
            _wp = _wp[_wp["count"] >= 3]
            if not _wp.empty:
                _wp_r = _wp.sort_values("mean").iloc[0]
                # CONFIRMED CHANGE (requested 11/18): no possession counts in the brief's visible text --
                # the 3-clip floor above still decides whether this line prints at all.
                (_sb_sechead if _WTP else (lambda *_a: None))(f'Play them in <b>{_sb_esc(str(_wp.sort_values("mean").index[0]).lower())}</b> '
                            f'\u2014 {_wp_r["mean"]:.2f} points a possession')
        add('<div class="card">')

        # ---- 1+2. Each defense, AND whether pressing is worth it -- one table ----------------------
        # These used to be two tables, and the second ("Do they handle pressure") repeated the Press row
        # of the first (requested: combine). Press is already a row here; the only thing the second table
        # added was the turnover-rate COMPARISON against not being pressed, so that is now a sentence under
        # the table instead of its own grid.
        #
        # Their columns and ours are grouped under two labelled header bands (requested: make it clear which
        # columns are OUR defense) -- a bare "We allow" sitting next to "PPP" was easy to read as theirs.
        if not _pf_opp.empty:
            _base = _ppp_of(_pf_opp)
            _ours = pd.DataFrame()
            if not _pcc_all.empty and "defense_played" in _pcc_all.columns:
                _ours = _pcc_all[(_pcc_all["side"] == "UWW")
                                 & (~_pcc_all["decode_quality"].isin(["Needs review", "Untagged"]))
                                 & _pcc_all["defense_played"].notna()].copy()
                if not _ours.empty:
                    _ours["_pts"] = pd.to_numeric(_ours.get("points"), errors="coerce")
                    _ores = _ours["result"].astype(str).str.lower() if "result" in _ours.columns \
                        else pd.Series("", index=_ours.index)
                    _ours["_to"] = _ores.str.contains("turnover|violation|kicked", regex=True)
                    _ours["_fam"] = _ours.apply(
                        lambda r: "Press" if _press_true(r.get("press_played")) else
                        ("Zone" if "zone" in str(r.get("defense_played") or "").lower() else
                         ("Man" if "man" in str(r.get("defense_played") or "").lower() else "")), axis=1)
                    _ours = _ours[_ours["_fam"] != ""]
            _have_ours = not _ours.empty

            add('<div class="tier-h">How they score against each defense</div>')
            add('<table class="compact dfam"><thead>'
                '<tr class="dfam-band"><th></th>'
                f'<th colspan="4" class="band-them">{_sb_esc(OPP_UP)} OFFENSE vs this defense</th>'
                + ('<th colspan="3" class="band-us">OUR DEFENSE when we play it</th>' if _have_ours else "")
                + '<th></th></tr>'
                '<tr><th style="text-align:left">Defense</th>'
                '<th class="band-them">Poss</th><th class="band-them">PPP</th>'
                '<th class="band-them">FG%</th><th class="band-them">TO%</th>'
                + ('<th class="band-us">Poss</th><th class="band-us">PPP allowed</th>'
                   '<th class="band-us">TO% forced</th>' if _have_ours else "")
                + '<th style="text-align:left">What they went to most</th>'
                "</tr></thead><tbody>")
            _fam_rows = []
            for _fam, _g in _pf_opp.groupby("_fam"):
                if len(_g) < _DEF_FAMILY_MIN:
                    continue
                _fam_rows.append((_fam, _g, _ppp_of(_g)))
            # Fixed order so Press is always last and reads as "and when you pressure them".
            _order = {"Man": 0, "Zone": 1, "Press": 2}
            for _fam, _g, _p in sorted(_fam_rows, key=lambda x: (_order.get(x[0], 9), -len(x[1]))):
                _fga, _fgm = int(_g["_fga"].sum()), int(_g["_fgm"].sum())
                _top = ""
                if "play_series" in _g.columns and _g["play_series"].notna().any():
                    _tc = _g["play_series"].dropna().astype(str).value_counts()
                    if len(_tc):
                        _top = f"{_tc.index[0]} ({int(_tc.iloc[0])}x)"
                _ours_cells = ""
                if _have_ours:
                    _og = _ours[_ours["_fam"] == _fam]
                    if len(_og):
                        _op = _ppp_of(_og)
                        _ours_cells = (f'<td class="band-us">{len(_og)}</td>'
                                       f'<td class="band-us">{_sb_fmt(_op, 2) if _op is not None else "--"}</td>'
                                       f'<td class="band-us">{_sb_fmt(100 * _og["_to"].sum() / len(_og), 1)}</td>')
                    else:
                        _ours_cells = '<td class="band-us" colspan="3"><span class="mini">not run yet</span></td>'
                add(f'<tr class="serrow"><td class="wrap">{_sb_esc(_fam)}</td>'
                    f'<td class="band-them">{len(_g)}</td>'
                    f'<td class="band-them {_ppp_cls(_p, _base)}">{_sb_fmt(_p, 2)}</td>'
                    f'<td class="band-them">{_sb_fmt(100 * _fgm / _fga, 1) if _fga else "--"}</td>'
                    f'<td class="band-them">{_sb_fmt(100 * _g["_to"].sum() / len(_g), 1)}</td>'
                    + _ours_cells
                    + f'<td class="wrap mini">{_sb_esc(_top)}</td></tr>')
            if not _fam_rows:
                add(f'<tr><td colspan="{9 if _have_ours else 6}" class="mini">No defense family has reached '
                    f'{_DEF_FAMILY_MIN} tagged possessions yet.</td></tr>')
            add("</tbody></table>")

            _notes = []
            if _fam_rows:
                _best = min(_fam_rows, key=lambda x: (x[2] if x[2] is not None else 9))
                _worst = max(_fam_rows, key=lambda x: (x[2] if x[2] is not None else -9))
                if _best[0] != _worst[0] and _best[2] is not None and _worst[2] is not None:
                    _notes.append(f"They struggle most against <strong>{_sb_esc(_best[0])}</strong> "
                                  f"({_sb_fmt(_best[2], 2)} PPP) and hurt you most against "
                                  f"<strong>{_sb_esc(_worst[0])}</strong> ({_sb_fmt(_worst[2], 2)} PPP).")
            # The pressure verdict -- what the separate table used to say, in one line.
            if "press_faced" in _pf_opp.columns:
                _pressed = _pf_opp[_pf_opp["press_faced"].astype(bool)]
                _unpressed = _pf_opp[~_pf_opp["press_faced"].astype(bool)]
                if len(_pressed) >= _DEF_FAMILY_MIN and len(_unpressed) >= _DEF_FAMILY_MIN:
                    _to_p = 100 * _pressed["_to"].sum() / len(_pressed)
                    _to_u = 100 * _unpressed["_to"].sum() / len(_unpressed)
                    _forms = (_pressed["press_formation_faced"].dropna().astype(str).value_counts()
                              if "press_formation_faced" in _pressed.columns else pd.Series(dtype=int))
                    _notes.append(
                        f"<strong>Pressure</strong> moves their turnover rate {_to_p - _to_u:+.1f} points "
                        f"({_to_u:.1f}% unpressed \u2192 {_to_p:.1f}% pressed) \u2014 "
                        + ("worth pressing." if _to_p - _to_u >= 5 else "not enough to be worth the risk.")
                        + (f" Presses seen: {_sb_esc(', '.join(_forms.index[:3]))}." if len(_forms) else ""))
            for _n in _notes:
                add(f'<p class="strip-line">{_n}</p>')

        # ---- 3. Counters: what a coverage change makes them do ------------------------------------
        # CONFIRMED CHANGE (requested: remove "When you change the coverage, what do they go to" -- the
        # Situation / formation table's coverage lines now carry the play calls). BRIEF_COVERAGE_COUNTERS = True
        # brings it back.
        if globals().get("BRIEF_COVERAGE_COUNTERS", False) and not _pf_opp.empty and "coverage_faced" in _pf_opp.columns:
            _cov = _pf_opp[_sb_has_text(_pf_opp["coverage_faced"])]
            if not _cov.empty:
                _cov_rows = []
                for _cname, _g in _cov.groupby(_cov["coverage_faced"].astype(str)):
                    if len(_g) < _DEF_SPLIT_MIN:
                        continue
                    _went = ""
                    if "play_call" in _g.columns and _g["play_call"].notna().any():
                        _wc = _g["play_call"].dropna().astype(str)
                        _wc = _wc[~_wc.str.contains("unspecified", na=False)].value_counts()
                        if len(_wc):
                            _went = ", ".join(f"{n} ({int(c)}x)" for n, c in _wc.head(2).items())
                    _cov_rows.append((_cname, _g, _ppp_of(_g), _went))
                if _cov_rows:
                    _cbase = _ppp_of(_cov)
                    add('<div class="tier-h">When you change the coverage, what do they go to</div>')
                    add('<table class="compact"><thead><tr><th style="text-align:left">Coverage they saw</th>'
                        '<th>Poss</th><th>PPP</th><th style="text-align:left">What they called</th>'
                        "</tr></thead><tbody>")
                    for _cname, _g, _p, _went in sorted(_cov_rows, key=lambda x: -len(x[1])):
                        add(f'<tr class="serrow"><td class="wrap">{_sb_esc(_cname)}</td><td>{len(_g)}</td>'
                            f'<td class="{_ppp_cls(_p, _cbase)}">{_sb_fmt(_p, 2)}</td>'
                            f'<td class="wrap mini">{_sb_esc(_went)}</td></tr>')
                    add("</tbody></table>")

        # ---- 4. Personnel x defense: moved into the opponent Player Notes (DEF_SPLIT_RULES, above the
        # roster) -- only players whose gap is large enough get a line.

        # ---- 5. Confirm on film -------------------------------------------------------------------
        # The brief's job before film is to hand over HYPOTHESES to confirm, not conclusions. Ordered by
        # how much the claim would change the plan, with the clip count behind each one stated.
        _checks = []
        if not _pf_opp.empty:
            _fams = {f: g for f, g in _pf_opp.groupby("_fam") if len(g) >= _DEF_FAMILY_MIN}
            if len(_fams) >= 2:
                _ranked = sorted(_fams.items(), key=lambda kv: (_ppp_of(kv[1]) or 9))
                _b, _w = _ranked[0], _ranked[-1]
                _checks.append((abs((_ppp_of(_w[1]) or 0) - (_ppp_of(_b[1]) or 0)),
                                f"They score {_sb_fmt(_ppp_of(_b[1]), 2)} PPP against {_b[0]} vs "
                                f"{_sb_fmt(_ppp_of(_w[1]), 2)} against {_w[0]} \u2014 watch whether that's the "
                                f"defense or just shot-making.", len(_b[1]) + len(_w[1])))
            _pr = _pf_opp[_pf_opp["press_faced"].astype(bool)] if "press_faced" in _pf_opp.columns else pd.DataFrame()
            if len(_pr) >= _DEF_FAMILY_MIN:
                _rest = _pf_opp[~_pf_opp["press_faced"].astype(bool)]
                if len(_rest):
                    _d = 100 * _pr["_to"].sum() / len(_pr) - 100 * _rest["_to"].sum() / len(_rest)
                    _checks.append((abs(_d) / 10,
                                    f"Their turnover rate moves {_d:+.1f} points under pressure \u2014 check "
                                    f"who is actually bringing it up and whether they have a second handler.",
                                    len(_pr)))
        if not _pf_uww.empty:
            _ufams = {f: g for f, g in _pf_uww.groupby("_fam") if len(g) >= _DEF_FAMILY_MIN}
            if len(_ufams) >= 2:
                _ur = sorted(_ufams.items(), key=lambda kv: -(_ppp_of(kv[1]) or 0))
                _checks.append((abs((_ppp_of(_ur[0][1]) or 0) - (_ppp_of(_ur[-1][1]) or 0)),
                                f"Our own offense scores best against {_ur[0][0]} "
                                f"({_sb_fmt(_ppp_of(_ur[0][1]), 2)} PPP) \u2014 confirm they'll actually show "
                                f"it before building around it.", len(_ur[0][1])))
        # CONFIRMED CHANGE (requested: remove the "Confirm these on film" list from the briefs);
        # BRIEF_CONFIRM_ON_FILM = True brings it back
        if _checks and globals().get("BRIEF_CONFIRM_ON_FILM", False):
            add('<div class="tier-h">Confirm these on film</div>')
            add('<ul class="bl">')
            for _w8, _text, _n in sorted(_checks, key=lambda x: -x[0])[:5]:
                add(f'<li>{_sb_esc(_text)} <span class="mini">({_n} tagged possessions)</span></li>')
            add("</ul>")
        add("</div>")
        _DFAM_CHUNKS = _sinks.pop()
        if _WTP:
            for _dchunk in _DFAM_CHUNKS:
                add(_dchunk)




    # =====================================================================================================
    # TWO-FOR-ONE -- end of each half. CONFIRMED CHANGE (requested): how to take advantage of the upcoming
    # opponent when 2-for-1 chances come up (which play calls worked, who to attack). Built by the parser's
    # two-for-one cell (uww_two_for_one_*); the brief prints the reads and the top rows, the app's Game Plan
    # tab has every table and possession.
    # =====================================================================================================
    _tf_plan, _ = staff_rows("uww_two_for_one_plan")
    # CONFIRMED CHANGE (requested: remove the TWO-FOR-ONE section from the briefs, keep it in the app -- Game Plan tab);
    # BRIEF_TWO_FOR_ONE = True brings it back. Each player's "Attack him late in a half" read stays on the roster.
    if not _tf_plan.empty and globals().get("BRIEF_TWO_FOR_ONE", False):
        section(f"\u23f1\ufe0f TWO-FOR-ONE vs {OPP_UP}" + footnote(
            "A team that gets the ball with about 0:35-1:00 left in a half can shoot early on purpose: the other team "
            "then has to shoot before the horn, and the first team gets the last shot -- two possessions to one. "
            "NCAA men's rules (30-second shot clock, 20 after an offensive rebound). The chance is the first "
            "possession of the half that starts in that window; went for it = first shot, free-throw trip or "
            "turnover with 0:33+ left; got it = a second real possession (3+ seconds) and more trips than the other "
            "team. End of the 2nd half / overtime counts only for a team that's behind -- ahead or tied, teams hold "
            "for the last shot. Possessions are rebuilt from every game's play-by-play (no possession column exists), "
            "so every half on file counts, not just tagged clips. Play calls appear once the coaches have tagged 2+ "
            "end-of-half possessions with one; until then it's Synergy's play type. Who to attack (on each player in the roster) weighs foul rate "
            "(box scores), fouls while defending 2-for-1 possessions, defensive role and how often he's on the floor "
            "at the end of a half."))
        add('<div class="card">')
        # (requested) "Who to attack" now lives on each player in the roster, not here
        _tf_plan = _tf_plan[~_tf_plan["part"].astype(str).str.contains("who to attack", case=False)]
        for _part, _g in _tf_plan.sort_values("order").groupby("part", sort=False):
            add(f'<div class="tier-h">{_sb_esc(_part)}</div><ul class="bl">')
            for _, _r in _g.iterrows():
                add(f'<li>{_sb_esc(_r["headline"])} <span class="mini">&mdash; {_sb_esc(_sb_clean(_r.get("detail")))} '
                    f'(n = {int(pd.to_numeric(_r.get("sample_n"), errors="coerce") or 0)})</span></li>')
            add("</ul>")
        _tf_calls, _ = staff_rows("uww_two_for_one_calls")
        if not _tf_calls.empty:
            _tf_show = _tf_calls[((_tf_calls["who"] == "UWW offense") | _tf_calls["who"].astype(str).str.startswith("Against "))
                                 & (pd.to_numeric(_tf_calls["uses"], errors="coerce") >= 3)]
            _tf_show = _tf_show.sort_values(["who", "moment", "ppp"], ascending=[False, True, False]).groupby(
                ["who", "moment"], sort=False).head(2)
            if not _tf_show.empty:
                add('<div class="tier-h">What worked at the end of halves</div>'
                    '<table class="compact"><thead><tr><th style="text-align:left">Whose possessions</th>'
                    '<th style="text-align:left">Moment</th><th style="text-align:left">What they ran</th>'
                    '<th>Poss.</th><th>PPP</th><th style="text-align:left">Most often by</th></tr></thead><tbody>')
                for _, _r in _tf_show.iterrows():
                    add(f'<tr><td class="wrap">{_sb_esc(_r["who"])}</td><td class="wrap">{_sb_esc(_r["moment"])}</td>'
                        f'<td class="wrap">{_sb_esc(_r["name"])} <span class="mini">({_sb_esc(str(_r["kind"]).lower())})</span></td>'
                        f'<td>{int(_r["uses"])}</td><td>{_sb_fmt(_r["ppp"], 2)}</td>'
                        f'<td class="wrap">{_sb_esc(_sb_clean(_r.get("top_player")))}</td></tr>')
                add("</tbody></table>")
        _tf_att = pd.DataFrame()                 # (requested) moved to the roster -- see _tf_attack_by
        if not _tf_att.empty:
            _tf_att = _tf_att[_tf_att["verdict"].astype(str).isin(["Attack", "Avoid"])]
        if not _tf_att.empty:
            add('<div class="tier-h">Who to attack late in a half</div>'
                '<table class="compact"><thead><tr><th style="text-align:left">Player</th><th style="text-align:left">Call</th>'
                '<th>On floor late</th><th>Fouls/40</th><th>Fouls in 2-for-1 spots</th>'
                '<th style="text-align:left">Defensive role</th></tr></thead><tbody>')
            for _, _r in _tf_att.iterrows():
                _cls = "call-foul" if _r["verdict"] == "Attack" else "call-nofoul"
                add(f'<tr><td class="nm">{_sb_esc(_r["player"])}</td><td class="{_cls}">{_sb_esc(_r["verdict"])}</td>'
                    f'<td>{int(pd.to_numeric(_r["late_share_pct"], errors="coerce") or 0)}%</td>'
                    f'<td>{_sb_fmt(_r["fouls_per_40"])}</td><td>{int(pd.to_numeric(_r["late_fouls"], errors="coerce") or 0)}</td>'
                    f'<td class="wrap">{_sb_esc(_sb_clean(_r.get("defensive_role")))}</td></tr>')
            add("</tbody></table>")
        add('<p class="mini">' + app_link("Every 2-for-1 possession and the full what-worked table", page="upcoming",
                                          tab="game_plan", section="two_for_one") + "</p>")
        add("</div>")

    # =====================================================================================================
    # HOW THEY RUN OFFENSE -- the quadrant view, built for the defensive side of the ball. Replaced an
    # other side of the ball. The axes are the same (how often x how well), but the QUESTION flips: on our
    # own sets the answer is "call it more / stop calling it", which is meaningless for an opponent we
    # don't coach. Here the same two axes answer "what do we have to take away, and what can we live with",
    # so the quadrant names, the ordering and the per-row detail are all defensive. The scary cell is
    # low-usage / high-efficiency -- the thing they don't run often enough to have shown up on film, which
    # is exactly what beats an under-prepared defense.
    # =====================================================================================================
    def _offense_breakdown_card(side):
        """CONFIRMED CHANGE (requested: one table -- "which actions are being run out of situations and formations"): the
        opening table of HOW <OPP> RUNS OFFENSE (uww_offense_breakdown, built in 47). It replaces the separate Actions and
        "How they run Motion" tables in the brief (BRIEF_ACTION_TABLES = True brings those back)."""
        try:
            ob = _sb_d("uww_offense_breakdown")
        except Exception:
            return
        if ob.empty or "label" not in ob.columns:
            return
        # CONFIRMED CHANGE (requested: the same table for how WE run offense and how they might defend it): side "UWW"
        # reads the perspective == "UWW" rows (our offense; green = their defense in their own games).
        _pv = ob["perspective"].fillna("Opponent").astype(str) if "perspective" in ob.columns else pd.Series("Opponent", index=ob.index)
        ob = ob[(ob["scouted_opponent"].astype(str) == str(short)) & (_pv == side)]
        if side == "Opponent":
            ob = ob[ob["team"].astype(str) == str(short)]
        else:
            ob = ob[ob["team"].astype(str).str.contains("whitewater", case=False, na=False)]
            if not ob.empty:
                ob = ob[ob["team"] == ob["team"].value_counts().index[0]]
        if ob.empty:
            return
        _us = side == "UWW"
        # CONFIRMED CHANGE (requested: "Remove Transition and Offensive Rebound from the list."): hidden in the brief
        # only; the rows stay in uww_offense_breakdown.
        ob = ob[~ob["situation"].astype(str).str.lower().isin(["transition", "offensive rebound"])]
        if ob.empty:
            return
        ob = ob.sort_values("order")
        _last_kind = None
        _c = lambda v: _sb_esc(_sb_clean(v)) or "--"  # noqa: E731
        _FL = globals().get("_SB_PC_FLAGS") or {}
        _FLS = ({"q-good": "Keep calling it", "q-up": "Call it more", "q-bad": "Fix or cut", "q-dim": "Shelve it"} if _us else
                {"q-bad": "Take away", "q-up": "Thin sample", "q-good": "Make them run it", "q-dim": "Live with it"})

        _TP = globals().get("_SB_TEAM_PPP")

        def _pcs(v, lvl="situation", counts=""):
            """Play calls with flags. CONFIRMED CHANGE (requested option 3): the season flag only on the All rows; on a
            formation / coverage line, a red "Scored here" flag when a play they otherwise don't score with (Make them run
            it / Live with it) scored 0.25+ PPP above their average there in 2+ possessions."""
            t = _sb_clean(v)
            if not t:
                return "--"
            _n = {}
            for x in str(counts or "").split(";"):
                if "=" in x:
                    k_, _, v_ = x.rpartition("=")
                    _n[_norm(k_)] = int(pd.to_numeric(v_, errors="coerce") or 0)
            out = []
            for part in t.split(" \u00b7 "):
                m_ = re.match(r"^(.*?)\s*\(([\d.]+)\)\s*$", part)
                nm, pp = (m_.group(1).strip(), float(m_.group(2))) if m_ else (part.strip(), None)
                f = _FL.get(_norm(nm))
                tag = ""
                if f and lvl == "situation":
                    tag = (f' <span class="pc-flag {f[1]}" title="{_sb_esc(f[0] + (" -- " + f[2] if f[2] else ""))}">'
                           f'{_FLS.get(f[1], f[0])}</span>')
                elif (f and f[1] in ("q-good", "q-dim") and pp is not None and _TP is not None
                      and pp >= _TP + 0.25 and _n.get(_norm(nm), 0) >= 2):
                    _tt = _sb_esc(f"Season: {f[0]} -- but {pp:.2f} PPP in {_n.get(_norm(nm))} possessions here")
                    tag = f' <span class="pc-flag q-bad" title="{_tt}">Scored here</span>'
                out.append(_sb_esc(part) + tag)
            return " \u00b7 ".join(out)
        # CONFIRMED CHANGE (requested: play calls as their own rows under each formation, like Situation and Formation,
        # with "No Play Call" for the rest): Situation (vertical) > Formation > Play call > coverage lines.
        # CONFIRMED CHANGE (requested: a few bullets right above the table -- what they run most out of each formation, what
        # worked best, the lineup / players to be aware of, the defense their opponents played, and whether we should do
        # the same or something different). Built in 47 (uww_offense_summary); the brief only prints them.
        try:
            _osm = _sb_d("uww_offense_summary")
        except Exception:
            _osm = pd.DataFrame()
        if not _osm.empty and {"text", "perspective", "scouted_opponent", "team"} <= set(_osm.columns):
            _osm = _osm[(_osm["scouted_opponent"].astype(str) == str(short))
                        & (_osm["perspective"].fillna("Opponent").astype(str) == side)
                        & _osm["team"].astype(str).isin(set(ob["team"].astype(str)))
                        & ~_osm["kind"].astype(str).isin(["players", "scorers", "defense", "advice"])].sort_values("order")  # (in TOP LINEUPS now; no "Their opponents' ball-screen defense" or "Do the same" lines -- requested)
            if len(_osm) and globals().get("BRIEF_OFFENSE_BULLETS", False):
                _ico = {"formation": "\U0001f4cb", "success": "\u2705", "players": "\U0001f440", "defense": "\U0001f6e1\ufe0f",
                        "advice": "\U0001f449"}
                add('<div class="card"><ul class="ob-sum">' + "".join(
                    f'<li>{_sb_esc(_sb_clean(r_.get("text")))}</li>' for _, r_ in _osm.iterrows())
                    + "</ul></div>")
        # CONFIRMED CHANGE (requested: the table under HOW <OPP> RUNS OFFENSE in a collapsible section coaches open to view
        # it): a <details> block, closed by default (it opens by itself when the brief is printed -- see _SB_PRINT_OPEN_JS)
        # CONFIRMED CHANGE (requested: right above the full table, a collapsible summary table of Play Call, Possessions and
        # PPP): every play call added up over all situations / formations, most possessions first.
        try:
            _sp = ob[ob["level"].astype(str) == "play_call"].copy()
            _sp["_n"] = pd.to_numeric(_sp["possessions"], errors="coerce").fillna(0)
            _sp["_pts"] = _sp["_n"] * pd.to_numeric(_sp["ppp"], errors="coerce")
            _sp["_pn"] = _sp["_n"].where(pd.to_numeric(_sp["ppp"], errors="coerce").notna(), 0)
            _sg = _sp.groupby(_sp["label"].astype(str)).agg(n=("_n", "sum"), pts=("_pts", "sum"), pn=("_pn", "sum"))
            _sg = _sg[_sg["n"] > 0].sort_values("n", ascending=False)
            if len(_sg):
                # CONFIRMED CHANGE (requested 11/22: "click on 'Zoom' and then either get information about those plays that
                # make up the data ... and see the video" -> options A + C): every play call opens to the clips behind its
                # numbers -- game, clip number, half and clock, who finished it, result, the five on the floor -- with a link
                # to the game in Synergy (the same breakdown link the "Possibly mis-tagged" table uses). No video is embedded:
                # the brief is one HTML file that gets emailed, and a clip is ~3 MB.
                _syn_pcs = {}
                try:
                    import json as _pcs_json             # this section has no json import of its own
                    with open(os.path.join(globals().get("INPUT_DIR", "./inputs"), "_synergy_ids.json"),
                              encoding="utf-8") as _pfh:
                        for _gid, _g in (_pcs_json.load(_pfh).get("games") or {}).items():
                            if _g.get("name"):
                                _syn_pcs[str(_g["name"])] = str(_gid)
                except Exception:
                    pass

                def _pcs_sur(lineup):
                    _out_ = []
                    for _nm in str(lineup or "").split(","):
                        _w = [x for x in _nm.split() if x.strip(".").lower() not in ("jr", "sr", "ii", "iii", "iv")]
                        if _w:
                            _out_.append(_w[-1])
                    return " / ".join(_out_)

                def _pcs_clock(period, secs):
                    _sec = pd.to_numeric(secs, errors="coerce")
                    if pd.isna(_sec):
                        return "--" if pd.isna(period) or str(period).lower() == "nan" else str(period)
                    return f"{period} {int(_sec // 60)}:{int(_sec % 60):02d}"

                def _pcs_clips(label):
                    """The clips behind one row: the same side, possessions only, this play call as the coaches tagged it."""
                    _cl = _pcc_all
                    if not isinstance(_cl, pd.DataFrame) or _cl.empty or not {"play_call", "offense_team"} <= set(_cl.columns):
                        return _cl.iloc[0:0] if isinstance(_cl, pd.DataFrame) else pd.DataFrame()
                    # THIS SEASON ONLY, like the numbers on the row (47 season_play_calls, BRIEF_THIS_SEASON_ONLY): without
                    # it "5 Out Motion" showed 14 possessions and listed 80 clips, 56 of them from last March.
                    _spc = globals().get("season_play_calls")
                    if callable(_spc):
                        _cl = _spc(_cl)
                    _mine_ = _cl["offense_team"].astype(str) == _SB_UWW
                    _cl = _cl[_mine_] if _us else _cl[~_mine_ & _cl["offense_team"].notna()]
                    if "possession_side" in _cl.columns:
                        _cl = _cl[_cl["possession_side"].astype(str) != "Defense"]
                    if "call_names_other_team" in _cl.columns:
                        _cl = _cl[_cl["call_names_other_team"].isna()]
                    # Same rule as the row's own count (47 _pl_offense_breakdown): every clip the coaches tagged, i.e. not
                    # "Untagged". That count also takes in "Non Possession" clips (a foul with the ball kept, a violation);
                    # they are listed too, and marked, so the list always adds up to the Poss column.
                    if "decode_quality" in _cl.columns:
                        _cl = _cl[_cl["decode_quality"].astype(str) != "Untagged"]
                    # The row's Poss only counts clips run out of half court / BLOB / SLOB / ATO (47 builds the play-call
                    # rows under those situations' formations), so the list takes the same ones: transition, offensive
                    # rebounds and openers are in the app's tables but not in this count.
                    _sit = _cl["play_situation"].astype(str).str.replace(r"\s*\(ATO\)$", "", regex=True) \
                        if "play_situation" in _cl.columns else pd.Series("", index=_cl.index)
                    _cl = _cl[_sit.isin(["Half court", "BLOB", "SLOB", "ATO"])]
                    _pc = _cl["play_call"].astype(str).str.strip()
                    _hit = _pc.str.lower() == str(label).strip().lower()
                    # "No Play Call" (our side: "Flow", which 47 renames it to) is every clip with NO call.
                    if str(label).strip().lower() == "no play call" or (_us and str(label).strip().lower() == "flow"):
                        _hit = _hit | _cl["play_call"].isna() | _pc.isin(["", "nan", "No Play Call"])
                    _cl = _cl[_hit]
                    return _cl.sort_values(["game_date", "clip_number"], ascending=[False, True]) \
                        if {"game_date", "clip_number"} <= set(_cl.columns) else _cl

                def _pcs_watch(iids, title):
                    """Synergy's video player (editor-web) opened on these plays. The play page's own "watch" links use exactly
                    this form for one play: playlistUrl = .../possessionplaylists/statistics/37/clips?expression=<base64 of
                    "iid eq N">; several plays are joined with " or " (NOT yet confirmed in Synergy -- one play per link is)."""
                    import base64 as _b64
                    import urllib.parse as _up
                    _ex = _b64.b64encode(" or ".join(f"iid eq {i}" for i in iids).encode()).decode()
                    _api = ("https://basketball.synergysportstech.com/api/possessionplaylists/statistics/37/clips?expression="
                            + _up.quote(_ex, safe="") + "&sort=gameDate:desc&take=500")
                    return ("https://editor-web.synergysports.com/video?playlistUrl=" + _up.quote(_api, safe="")
                            + "&title=" + _up.quote(title))

                def _pcs_body(label):
                    _cl = _pcs_clips(label)
                    if _cl.empty:
                        return ""
                    _gh = []
                    # CONFIRMED CHANGE (requested 11/22, after the cross-game test link worked in Synergy): one link at the
                    # top of the row that plays this play call's plays from EVERY game together.
                    _all_ids = [str(int(float(x))) for x in _cl.get("synergy_iid", pd.Series(dtype=object)).dropna()]
                    _all_g = _cl.loc[_cl.get("synergy_iid", pd.Series(dtype=object)).notna(), "game_code"].astype(str).nunique()
                    if len(_all_ids) > 1 and _all_g > 1:
                        _gh.append('<div class="pcs-gh"><b>All games</b> <span class="mini">'
                                   f'<a class="applink" href="{_sb_esc(_pcs_watch(_all_ids, label + " - all games"))}"{_SB_NEWTAB} '
                                   f'title="Opens Synergy\u2019s video player on these plays">watch all {len(_all_ids)} plays '
                                   f'({_all_g} games) in Synergy</a></span></div>')
                    for (_gc, _gdate), _gr in _cl.groupby([_cl["game_code"].astype(str), _cl["game_date"].astype(str)], sort=False):
                        _opp = _sb_strip_mascot(str(_gr.iloc[0].get("opponent") or "").strip()) or _gc
                        _sid = _syn_pcs.get(_gc) or next((str(x) for x in _gr.get("synergy_game_id", pd.Series(dtype=object)).dropna()), "")
                        _iids = [str(int(float(x))) for x in _gr.get("synergy_iid", pd.Series(dtype=object)).dropna()]
                        _ttl = f"{label} - {_opp} {_gdate}"
                        _bd = (f"https://apps.synergysports.com/basketball/games/{_sid}/breakdown" if _sid else "")
                        # THE GAME ROW (requested 11/22: the link is on "watch N plays in Synergy", not on the opponent's name):
                        # with Synergy play ids it opens the video player on this play call's plays from that game; without
                        # them it links to the game's breakdown page.
                        _name = _sb_esc(_opp)
                        if _iids:
                            _how = (f'<a class="applink" href="{_sb_esc(_pcs_watch(_iids, _ttl))}"{_SB_NEWTAB} '
                                    f'title="Opens Synergy\u2019s video player on these plays">watch {len(_iids)} '
                                    f'play{"s" if len(_iids) != 1 else ""} in Synergy</a>')
                        elif _bd:
                            _how = (f'<a class="applink" href="{_sb_esc(_bd)}"{_SB_NEWTAB}>open the game in Synergy</a> '
                                    '(play links not fetched yet)')
                        else:
                            _how = ""
                        _tr_ = []
                        for _, _c_ in _gr.iterrows():
                            _no = pd.to_numeric(_c_.get("clip_number"), errors="coerce")
                            _no_s = str(int(_no)) if pd.notna(_no) else "--"
                            _pts = pd.to_numeric(_c_.get("points"), errors="coerce")
                            _res = str(_c_.get("result") or "").strip()
                            _res_s = _res + (f" ({int(_pts)} pt{'s' if int(_pts) != 1 else ''})" if pd.notna(_pts) and _res else "")
                            if "non possession" in str(_c_.get("synergy_string") or "").lower():
                                _res_s += " \u2014 not a possession"
                            _tr_.append(
                                f'<tr><td class="t1">{_sb_esc(_no_s)}</td>'
                                f'<td class="l">{_sb_esc(_pcs_clock(_c_.get("period"), _c_.get("time_remaining_seconds")))}</td>'
                                f'<td class="l">{_sb_esc(str(_c_.get("player") or "").strip())}</td>'
                                f'<td class="l">{_sb_esc(_res_s)}</td>'
                                f'<td class="l">{_sb_esc(_pcs_sur(_c_.get("offense_lineup") or _c_.get("on_court_lineup")))}</td></tr>')
                        _gh.append(
                            f'<div class="pcs-g"><div class="pcs-gh"><b>vs {_name}</b> <span class="mini">{_sb_esc(_gdate)} \u00b7 '
                            f'{len(_gr)} play{"s" if len(_gr) != 1 else ""} \u00b7 {_how}</span></div>'
                            '<table class="ob-tbl pcs-t"><thead><tr><th class="t1">Clip</th><th class="l">When</th>'
                            '<th class="l">Player</th><th class="l">Result</th><th class="l">Five on the floor</th>'
                            '</tr></thead><tbody>' + "".join(_tr_) + '</tbody></table></div>')
                    return ('<div class="pcs-b">' + "".join(_gh)
                            + '<p class="mini">Click "watch N plays in Synergy" to see this play call\u2019s plays from that game in Synergy\u2019s video player '
                              '(you must be signed in to Synergy). Without play links, it opens the game and you go to the clip number shown.'
                              '</p></div>')

                _pcs_rows = []
                for i, r_ in _sg.iterrows():
                    _ppp_s = _sb_fmt(r_.pts / r_.pn, 2) if r_.pn else "--"
                    _head = (f'<span class="l">{_sb_esc(i)}</span><span class="t1">{int(r_.n)}</span>'
                             f'<span class="t1">{_ppp_s}</span>')
                    try:
                        _body = _pcs_body(i)
                    except Exception as _pbe:
                        print(f"  (play call clips not shown for {i}: {type(_pbe).__name__}: {_pbe})", flush=True)
                        _body = ""
                    if _body:
                        _pcs_rows.append(f'<details class="pcs-r"><summary>{_head}</summary>{_body}</details>')
                    else:
                        _pcs_rows.append(f'<div class="pcs-r pcs-none"><div class="pcs-sum">{_head}</div></div>')
                add('<details class="ob-det"><summary>Play call summary (' + str(len(_sg)) + ')</summary><div class="card pcs">'
                    '<div class="pcs-h"><span class="l">Play call <span class="mini">(click one to see its plays)</span></span>'
                    '<span class="t1">Poss</span><span class="t1">PPP</span></div>'
                    + "".join(_pcs_rows) + '</div></details>')
                # CONFIRMED CHANGE (requested 11/23): CLUTCH SITUATIONS, laid out like the play call summary -- every clutch
                # possession by game with its play call, action and result, and Synergy links: one for ALL of them, one per game.
                try:
                    _ctab = _clutch_poss("UWW" if _us else "Opponent")
                    if len(_ctab):
                        _cids = [str(int(float(x))) for x in _ctab.get("synergy_iid", pd.Series(dtype=object)).dropna()]
                        _cg = _ctab.loc[_ctab.get("synergy_iid", pd.Series(dtype=object)).notna(), "game_code"].astype(str).nunique()
                        _chead = ""
                        if _cids:
                            _chead = ('<div class="pcs-gh"><b>All clutch possessions</b> <span class="mini">'
                                      f'<a class="applink" href="{_sb_esc(_pcs_watch(_cids, "Clutch situations"))}"{_SB_NEWTAB} '
                                      f'title="Opens Synergy\u2019s video player on these plays">watch all {len(_cids)} plays '
                                      f'({_cg} game{"s" if _cg != 1 else ""}) in Synergy</a></span></div>')
                        _cgs = []
                        for (_gc, _gdate), _gr in _ctab.groupby([_ctab["game_code"].astype(str), _ctab["game_date"].astype(str)], sort=False):
                            _opp = _sb_strip_mascot(str(_gr.iloc[0].get("opponent") or "").strip()) or _gc
                            _sid = _syn_pcs.get(_gc) or next((str(x) for x in _gr.get("synergy_game_id", pd.Series(dtype=object)).dropna()), "")
                            _gi = [str(int(float(x))) for x in _gr.get("synergy_iid", pd.Series(dtype=object)).dropna()]
                            if _gi:
                                _how = (f'<a class="applink" href="{_sb_esc(_pcs_watch(_gi, "Clutch - " + _opp + " " + _gdate))}"{_SB_NEWTAB}>'
                                        f'watch {len(_gi)} play{"s" if len(_gi) != 1 else ""} in Synergy</a>')
                            elif _sid:
                                _how = (f'<a class="applink" href="https://apps.synergysports.com/basketball/games/{_sb_esc(_sid)}/breakdown"'
                                        f'{_SB_NEWTAB}>open the game in Synergy</a> (play links not fetched yet)')
                            else:
                                _how = ""
                            _ctr = []
                            for _, _c_ in _gr.iterrows():
                                _no = pd.to_numeric(_c_.get("clip_number"), errors="coerce")
                                _pts = pd.to_numeric(_c_.get("points"), errors="coerce")
                                _res = str(_c_.get("result") or "").strip()
                                _res_s = _res + (f" ({int(_pts)} pt{'s' if int(_pts) != 1 else ''})" if pd.notna(_pts) and _res else "")
                                _pcv = _c_.get("play_call")
                                _pcv = "No play call" if not isinstance(_pcv, str) or not _pcv.strip() or _pcv.strip().lower() == "nan" else _sb_clean(_pcv)
                                _al = [x.strip() for x in str(_c_.get("play_actions") or "").split("|") if x.strip() and x.strip().lower() != "nan"]
                                if not _al and str(_c_.get("primary_action") or "").strip().lower() not in ("", "nan", "none"):
                                    _al = [str(_c_.get("primary_action")).strip()]
                                _ctr.append(
                                    f'<tr><td class="t1">{_sb_esc(str(int(_no)) if pd.notna(_no) else "--")}</td>'
                                    f'<td class="l">{_sb_esc(_pcs_clock(_c_.get("period"), _c_.get("time_remaining_seconds")))}</td>'
                                    f'<td class="l">{_sb_esc(_pcv)}</td><td class="l">{_sb_esc(", ".join(_al) or "--")}</td>'
                                    f'<td class="l">{_sb_esc(str(_c_.get("player") or "").strip())}</td>'
                                    f'<td class="l">{_sb_esc(_res_s)}</td>'
                                    f'<td class="l">{_sb_esc(_pcs_sur(_c_.get("offense_lineup") or _c_.get("on_court_lineup")))}</td></tr>')
                            _cgs.append(
                                f'<div class="pcs-g"><div class="pcs-gh"><b>vs {_sb_esc(_opp)}</b> <span class="mini">{_sb_esc(_gdate)} \u00b7 '
                                f'{len(_gr)} possession{"s" if len(_gr) != 1 else ""} \u00b7 {_how}</span></div>'
                                '<table class="ob-tbl pcs-t"><thead><tr><th class="t1">Clip</th><th class="l">When</th>'
                                '<th class="l">Play call</th><th class="l">Actions</th><th class="l">Player</th>'
                                '<th class="l">Result</th><th class="l">Five on the floor</th></tr></thead><tbody>'
                                + "".join(_ctr) + '</tbody></table></div>')
                        add('<details class="ob-det"><summary>Clutch situations (' + str(len(_ctab)) + ')</summary><div class="card pcs">'
                            '<div class="pcs-b"><p class="mini">Clutch = second half, 5:00 or less on the clock, score within 8 \u2014 '
                            'the same rule as the clutch lines on the roster cards. This season\u2019s tagged possessions with the ball. '
                            + ('Click <b>watch all</b> to see every one of them in Synergy\u2019s video player, or the link on a game for just that game '
                               '(you must be signed in to Synergy).' if _cids else
                               'Open the game in Synergy and go to the clip numbers shown (play links not fetched yet).')
                            + '</p>' + _chead + "".join(_cgs) + '</div></div></details>')
                except Exception as _cse:
                    print(f"  (clutch situations not shown: {type(_cse).__name__}: {_cse})", flush=True)
        except Exception as _spe:
            print(f"  (play call summary not shown: {type(_spe).__name__}: {_spe})", flush=True)
        # CONFIRMED CHANGE (requested 11/19: "create an expandable section that lists things that you believe are
        # tagged incorrectly like these. And if possible can you make a link to the plays in the application or in
        # Synergy"). Two checks, and they are NOT equally sure of themselves, so the table says which is which:
        #   1. the call names a team that did not have the ball -- a contradiction, the Ripon Motion #1 case;
        #   2. the call is one the OTHER side runs often (3+ possessions) and we have at most 2 -- a question,
        #      not a verdict, since "Stagger" and "BLOB Motion" are words anyone can use.
        # Nothing is corrected here: a coach's answer is only ever questioned out loud, with the clip named and a
        # way to open it.
        def _mistag_rows(for_us):
            _cl = _pcc_all
            if not isinstance(_cl, pd.DataFrame) or _cl.empty or "play_call" not in _cl.columns:
                return []
            _cl = _cl[_cl["play_call"].notna() & _cl.get("offense_team", pd.Series(dtype=object)).notna()]
            if _cl.empty:
                return []
            _mine = _cl["offense_team"].astype(str) == _SB_UWW
            _side = _cl[_mine] if for_us else _cl[~_mine]
            if _side.empty:
                return []

            def _tword(t):
                for _w in re.split(r"[^A-Za-z]+", str(t or "")):
                    if len(_w) > 3 and _w.lower() not in ("college", "university", "state", "saint"):
                        return _w.lower()
                return ""

            _teams = {_tword(x) for x in _cl["offense_team"].dropna().unique()}
            _teams |= {_tword(x) for x in _cl.get("opponent", pd.Series(dtype=object)).dropna().unique()}
            _teams.discard("")
            # Counted WITHIN A GAME, not across the season. Season-wide this flagged "Flow", "Set", "5 Out",
            # "SLOB Motion" -- words every team in the country uses -- and a list of noise is a list nobody
            # opens. In ONE game, the other team running a call three or more times while this side has it
            # once or twice is a real question about those one or two.
            _oth = _cl[~_cl.index.isin(_side.index)]
            _other_uses = _oth.groupby([_oth["game_code"].astype(str), _oth["play_call"].astype(str)]).size()
            _own_uses = _side.groupby([_side["game_code"].astype(str), _side["play_call"].astype(str)]).size()
            _out = []
            for _, _r in _side.iterrows():
                _call = str(_r.get("play_call") or "").strip()
                if not _call:
                    continue
                _own = str(_r.get("offense_team") or "")
                _first = _tword(_call.split()[0])
                _why, _sure = "", 0
                if _first and _first in _teams and _first not in re.sub(r"[^a-z]", " ", _own.lower()):
                    _why = f"names {_call.split()[0]}, but {_sb_strip_mascot(_own)} had the ball"
                    _sure = 2
                else:
                    _gk = (str(_r.get("game_code") or ""), _call)
                    _them, _usn = int(_other_uses.get(_gk, 0)), int(_own_uses.get(_gk, 0))
                    if _them >= 3 and _usn <= 2:
                        _why = (f"the other team ran this {_them} times in this game; "
                                f"{'we have' if for_us else 'they have'} it {_usn}")
                        _sure = 1
                if not _why:
                    continue
                _out.append({"clip": str(_r.get("clip_number") or "").strip(),
                             "game": str(_r.get("game_code") or "").strip(),
                             "call": _call, "why": _why, "sure": _sure,
                             "when": str(_r.get("video_start_s") or "").strip()})
            _out.sort(key=lambda d_: (-d_["sure"], d_["game"], d_["clip"]))
            return _out

        def _mistag_details(for_us):
            _rows = _mistag_rows(for_us)
            if not _rows:
                return ""
            _syn = {}
            try:
                import json as _mt_json          # this section has no json import of its own
                with open(os.path.join(globals().get("INPUT_DIR", "./inputs"), "_synergy_ids.json"),
                          encoding="utf-8") as _sfh:
                    for _gid, _g in (_mt_json.load(_sfh).get("games") or {}).items():
                        if _g.get("name"):
                            _syn[str(_g["name"])] = str(_gid)
            except Exception:
                pass
            _tr = []
            for _d in _rows[:40]:
                _open = app_link("App", page="analytics", game=_d["game"], clip=_d["clip"])
                _sid = _syn.get(_d["game"])
                if _sid:
                    _open += (f' <a class="applink" href="https://apps.synergysports.com/basketball/games/'
                              f'{_sb_esc(_sid)}/breakdown"{_SB_NEWTAB}>Synergy &rarr;</a>')
                _mark = "❗" if _d["sure"] == 2 else "?"
                _tr.append(f'<tr><td class="t1">{_mark}</td><td class="t1">{_sb_esc(_d["clip"])}</td>'
                           f'<td class="l">{_sb_esc(_d["game"])}</td><td class="l">{_sb_esc(_d["call"])}</td>'
                           f'<td class="l">{_sb_esc(_d["why"])}</td><td class="l">{_open}</td></tr>')
            _n2 = sum(1 for _d in _rows if _d["sure"] == 2)
            return ('<details class="ob-det"><summary>Possibly mis-tagged (' + str(len(_rows)) + ')</summary>'
                    '<div class="card"><p class="mini">Tagged answers that argue with the play-by-play. '
                    + (f'<b>❗ {_n2}</b> contradict it outright; ' if _n2 else "")
                    + 'a <b>?</b> is only a question. Nothing here is corrected automatically — open the clip '
                      'and retag it if it is wrong.</p>'
                      '<table class="ob-tbl"><thead><tr><th class="t1"></th><th class="t1">Clip</th>'
                      '<th class="l">Game</th><th class="l">Tagged as</th><th class="l">Why it looks wrong</th>'
                      '<th class="l">Open</th></tr></thead><tbody>' + "".join(_tr) + '</tbody></table></div></details>')

        add(_mistag_details(_us))

        add('<details class="ob-det"><summary>Show the full table (situation \u203a formation \u203a play call)</summary>')
        if side == "Opponent" and not globals().get("BRIEF_WHAT_TO_PLAY_SECTION", False):
            for _dchunk in _DFAM_CHUNKS:
                add(_dchunk)
        add('<div class="card"><table class="ob-tbl"><colgroup><col style="width:4%"><col style="width:9%"><col style="width:12%">'
            '<col style="width:12%"><col style="width:6%"><col style="width:6%"><col style="width:15%"><col style="width:10%">'
            '<col style="width:10%"><col style="width:8%"><col style="width:8%"></colgroup><thead><tr><th colspan="4"></th>'
            '<th colspan="3" class="ob-b1">' + ("OUR OFFENSE" if _us else _sb_esc(OPP_UP) + " OFFENSE") + '</th>'
            '<th colspan="2" class="ob-b3">OPPONENTS\u2019 DEFENSE</th>'
            '<th colspan="2" class="ob-b2">' + (_sb_esc(OPP_UP) + " DEFENSE IN IT" if _us else "OUR DEFENSE IN IT") + '</th></tr><tr>'
            '<th class="l" colspan="2">Situation / formation</th><th class="l">Play call</th><th class="l">Action</th><th class="t1">Poss</th>'
            '<th class="t1">PPP</th><th class="t1 l">Runs it / scores</th><th class="t3 l">Ball screen coverage</th>'
            '<th class="t3 l">Off-ball screen coverage</th><th class="t2">Poss</th><th class="t2">PPP allowed</th></tr></thead><tbody>')
        _lv = ob["level"].astype(str).tolist()
        # CONFIRMED CHANGE (requested: "Collapse the bottom three rows into the total row above them and put the PPP next to
        # the three types of ball coverages in the same row"): EVERY coverage line folds into its play-call row -- each
        # coverage with its possessions and PPP ("Switch 2 (1.50) · Drop 1 (0.00) · No coverage tagged 6 (0.67)") in the
        # ball-screen / off-ball-screen column ("No coverage tagged" goes with the ball-screen coverages).
        _drop, _onecov = [], {}
        for _j, (_ix, _l) in enumerate(zip(ob.index, _lv)):
            if _l == "play_call":
                _k = _j + 1
                _bs, _ofb = [], []
                while _k < len(_lv) and _lv[_k] == "coverage":
                    _cr = ob.iloc[_k]
                    _drop.append(ob.index[_k])
                    _cn = pd.to_numeric(_cr.get("possessions"), errors="coerce")
                    _cn = int(_cn) if pd.notna(_cn) else 0
                    _cp = pd.to_numeric(_cr.get("ppp"), errors="coerce")
                    _txt = (f'{_c(_cr.get("label"))} {_cn}' + (f' <span class="mini">({_cp:.2f})</span>' if pd.notna(_cp) else ""))
                    (_ofb if str(_cr.get("cov_kind")) == "Off-ball screen" else _bs).append(_txt)
                    _k += 1
                if _bs or _ofb:
                    _onecov[_ix] = (" \u00b7 ".join(_bs), " \u00b7 ".join(_ofb))
        ob = ob.drop(index=_drop)
        _lv = ob["level"].astype(str).tolist()
        _ids = list(ob.index)
        _span = {}
        for _j, (_ix, _l) in enumerate(zip(_ids, _lv)):
            if _l in ("situation", "formation", "play_call"):
                _stop = {"situation": ("situation",), "formation": ("situation", "formation"),
                         "play_call": ("situation", "formation", "play_call")}[_l]
                _k = _j + 1
                while _k < len(_lv) and _lv[_k] not in _stop:
                    _k += 1
                _span[_ix] = _k - _j

        # CONFIRMED CHANGE (requested: "we don't need these rows duplicated"): a formation with only ONE play call
        # skips its "All" row -- the play-call row carries the formation name and our (green) numbers.
        _solo = {}                                # play-call row index -> its formation row
        for _j, (_ix, _l) in enumerate(zip(_ids, _lv)):
            if _l == "formation":
                _k, _pcs_ = _j + 1, []
                while _k < len(_lv) and _lv[_k] not in ("situation", "formation"):
                    if _lv[_k] == "play_call":
                        _pcs_.append(_ids[_k])
                    _k += 1
                if len(_pcs_) == 1:
                    _solo[_pcs_[0]] = _ix
        _sit_of = None
        for _ix, _l in zip(_ids, _lv):              # the skipped "All" row no longer counts in its situation's span
            if _l == "situation":
                _sit_of = _ix
            elif _l == "formation" and _ix in _solo.values() and _sit_of in _span:
                _span[_sit_of] -= 1

        # CONFIRMED CHANGE (requested: "move the Actions out of it column to the right of the Play Call column so that it is
        # also creating a row for each of the different Actions"): each play call's row is its "All" line, then one row per
        # action group (possessions, PPP) under it.
        def _num(v):
            x = pd.to_numeric(v, errors="coerce")
            return int(x) if pd.notna(x) else 0

        def _cov_cells(ix):
            if ix in _onecov:
                bs, ofb = _onecov[ix]
                return f'<td class="t3 l w">{bs}</td><td class="t3 l w">{ofb}</td>'
            return '<td class="t3 l w"></td><td class="t3 l w"></td>'

        def _green(r, show):
            un = _num(r.get("our_possessions"))
            if not show:
                return '<td class="t2"></td><td class="t2"></td>'
            return (f'<td class="t2">{un if un else "--"}</td>'
                    f'<td class="t2">{_sb_fmt(pd.to_numeric(r.get("our_ppp_allowed"), errors="coerce"), 2) if un else "--"}</td>')

        # CONFIRMED CHANGE (requested: "Flag based on that row's own numbers" -- STAGGER showed "Take away" next to 1 poss /
        # 0.00 because the flag came from all of its possessions). Each play-call row is rated on ITS OWN possessions and PPP:
        # used often = at least the median possessions of the play-call rows in this table, efficient = at or above the
        # team's own PPP; a row needs _RQMIN (2 theirs / 3 ours) possessions to get a flag at all.
        _RQMIN = 3 if _us else 2
        _pcr = ob[ob["level"].astype(str) == "play_call"]
        _pcr_n = pd.to_numeric(_pcr["possessions"], errors="coerce")
        _row_cut = float(_pcr_n[_pcr_n >= _RQMIN].median()) if (_pcr_n >= _RQMIN).any() else None
        _row_tp = None          # (this table's own PPP over every situation -- the right team for ours AND theirs)
        if _row_tp is None:
            _all_rows = ob[ob["level"].astype(str) == "situation"]
            _w = pd.to_numeric(_all_rows["possessions"], errors="coerce")
            _pp_ = pd.to_numeric(_all_rows["ppp"], errors="coerce")
            _row_tp = float((_w * _pp_).sum() / _w[_pp_.notna()].sum()) if _w[_pp_.notna()].sum() else None
        _QN = {"q-bad": "Take this away", "q-up": "Haven't seen it enough", "q-good": "Make them keep running it",
               "q-dim": "Live with it"} if not _us else {"q-good": "Keep calling it", "q-up": "Call it more",
                                                          "q-bad": "Fix it or cut it", "q-dim": "Shelve it"}

        def _row_flag(n, pp):
            if n < _RQMIN or pd.isna(pp) or _row_tp is None or _row_cut is None:
                return None
            often, good = n >= _row_cut, pp >= _row_tp
            if _us:
                return "q-good" if often and good else "q-up" if good else "q-bad" if often else "q-dim"
            return "q-bad" if often and good else "q-up" if good else "q-good" if often else "q-dim"

        def _pc_label(r):
            nm = _sb_clean(r.get("label"))
            pp = pd.to_numeric(r.get("ppp"), errors="coerce")
            n = _num(r.get("possessions"))
            q = _row_flag(n, pp)
            tag = ""
            if q:
                _tt = _sb_esc(f"{_QN.get(q, '')} -- {n} possessions here at {pp:.2f} PPP (team {_row_tp:.2f}; "
                              f"run often = {_row_cut:.0f}+ here)")
                tag = f' <span class="pc-flag {q}" title="{_tt}">{_FLS.get(q, _QN.get(q, ""))}</span>'
            # CONFIRMED CHANGE (requested: "The BLOB and SLOB sections do not need that repeated in the Play Call Name"):
            # "BLOB Set" under BLOB shows as "Set" (the flag still comes from the full name).
            _sit = str(r.get("situation") or "").strip()
            if _sit.upper() in ("BLOB", "SLOB"):
                nm = re.sub(rf"^\s*{_sit}\s+", "", nm, flags=re.I) or nm
            return _sb_esc(nm) + tag

        # CONFIRMED CHANGE (requested: "All of the offensive tables within briefs needs to also include the 5 person lineup
        # that runs it most and any players that are best at scoring off of it"): under each row, the five that runs it most
        # (possessions, PPP) and its top scorers (points, scoring possessions) -- top_lineup / top_scorers from 47.
        def _who(r):
            lu, sc = _sb_clean(r.get("top_lineup")), _sb_clean(r.get("top_scorers"))
            bits = ([f"<b>Runs it:</b> {_sb_esc(lu)}"] if lu else []) + ([f"<b>Scores:</b> {_sb_esc(sc)}"] if sc else [])
            return ('<div class="mini ob-who">' + "<br>".join(bits) + "</div>") if bits else ""

        # CONFIRMED CHANGE (requested: "the poss % should not be on the 'All' rows but on the other rows"): a formation's
        # % (next to its name) is its share of its situation; a play call's % is its share of its formation.
        _sit_n, _form_n = 0, 0
        _pct = lambda a, b: f' <span class="mini">({round(100 * a / b)}%)</span>' if b else ""  # noqa: E731
        for _ri, r in ob.iterrows():
            lvl = str(r.get("level"))
            n = _num(r.get("possessions"))
            _p = pd.to_numeric(r.get("ppp"), errors="coerce")
            _pt = f'<td class="t1">{_sb_fmt(_p, 2) if n else "--"}</td>'
            if lvl == "situation":
                _sit_n = n
                add(f'<tr class="ob-sit"><td class="ob-vs" rowspan="{_span.get(_ri, 1)}"><div>{_c(r.get("label"))}</div></td>'
                    f'<td class="l n" colspan="3">All</td>'
                    f'<td class="t1">{n}</td>'
                    + _pt + '<td class="t1 l w"></td>' + _cov_cells(None) + _green(r, True) + "</tr>")  # "All" rows: nothing in the Actions column (requested twice -- not even the lineup / scorers)
            elif lvl == "formation" and _ri in _solo.values():
                _form_n = n
                continue
            elif lvl == "formation":
                _form_n = n
                _lab = _c(r.get("label"))
                if _lab == "(none tagged)":
                    _lab = "No Formation"  # CONFIRMED CHANGE (requested: "(none tagged)" -> "No Formation")
                add(f'<tr class="ob-form"><td class="l n ob-fm" rowspan="{_span.get(_ri, 1)}">{_lab}{_pct(n, _sit_n)}</td>'
                    f'<td class="l ob-pcall ob-all" colspan="2">All</td><td class="t1">{n}</td>' + _pt
                    + '<td class="t1 l w"></td>' + _cov_cells(None) + _green(r, True) + "</tr>")  # "All" row: nothing in the Actions column (requested twice -- not even the lineup / scorers)
            elif lvl == "play_call":
                _fr = ob.loc[_solo[_ri]] if _ri in _solo else None
                _fcell = ""
                if _fr is not None:
                    _fl = _c(_fr.get("label"))
                    _fl = "No Formation" if _fl == "(none tagged)" else _fl
                    _fcell = f'<td class="l n ob-fm" rowspan="{_span.get(_ri, 1)}">{_fl}{_pct(_num(_fr.get("possessions")), _sit_n)}</td>'
                add(f'<tr class="{"ob-form" if _fr is not None else "ob-pc"}">{_fcell}<td class="l ob-pcall" rowspan="{_span.get(_ri, 1)}">{_pc_label(r)}</td>'
                    f'<td class="l ob-all">All</td><td class="t1">{n}{"" if _fr is not None else _pct(n, _form_n)}</td>' + _pt
                    + '<td class="t1 l w"></td>'
                    + _cov_cells(None) + (_green(_fr, True) if _fr is not None else _green(r, False)) + "</tr>")
            elif lvl == "action":   # one row per action under its play call: its own lineup / scorers / coverages
                add(f'<tr class="ob-act"><td class="l">{_c(r.get("label"))}</td><td class="t1">{n}</td>' + _pt
                    + f'<td class="t1 l w">{_who(r)}</td>'
                    + f'<td class="t3 l w">{_sb_esc(_sb_clean(r.get("cov_ball")))}</td>'
                    + f'<td class="t3 l w">{_sb_esc(_sb_clean(r.get("cov_offball")))}</td>' + _green(r, False) + "</tr>")
            else:   # coverage line under a play call
                _off = str(r.get("cov_kind") or "Ball screen") == "Off-ball screen"
                add(f'<tr class="ob-cov"><td class="t1">{n if n else "--"}</td>' + _pt + '<td class="t1"></td>'
                    + ('<td class="t3"></td>' if _off else "") + f'<td class="t3 l w">{_c(r.get("label"))}</td>'
                    + ("" if _off else '<td class="t3"></td>') + _green(r, False) + "</tr>")
        add("</tbody></table>"
            '<p class="mini">Each situation (down the left) and its total ("All"), then each formation and its total, then '
            "each play call they ran out of it (No Play Call = none tagged) and, on the same row, how defenses guarded it "
            "(ball-screen and off-ball-screen coverages in their own columns, each with its possessions and PPP). Under each play call, one row per action run out of it (possessions, PPP). " + ("Green = their own defensive possessions (their games) in the same situation / formation."
                             if _us else "Green = our own defensive possessions in the same situation / formation.") + "</p>"
            + ((f'<p class="mini">Play call flags rate each row on its OWN possessions ({_RQMIN}+): run often = '
                f'{_row_cut:.0f}+ possessions in that row, efficient = at or above the team\u2019s {_row_tp:.2f} PPP in this '
                'table. ' + ('<span class="pc-flag q-good">Keep calling it</span> often, scores · <span class="pc-flag q-up">Call it '
                             'more</span> scores, rarely called · <span class="pc-flag q-bad">Fix or cut</span> often, doesn\u2019t '
                             'score · <span class="pc-flag q-dim">Shelve it</span> rare, doesn\u2019t score.' if _us else
                             '<span class="pc-flag q-bad">Take away</span> often, scores · <span class="pc-flag q-up">Thin '
                             'sample</span> scores, rarely seen · <span class="pc-flag q-good">Make them run it</span> often, '
                             'doesn\u2019t score · <span class="pc-flag q-dim">Live with it</span> rare, doesn\u2019t score.')
                + "</p>") if _row_cut is not None and _row_tp is not None else "")
            + "</div></details>")  # (end of the collapsible full table)
        # CONFIRMED CHANGE (requested: coaches upload a picture of each play in the app -- Analytics > Play Diagrams -- and
        # "a collapsed section in all of the briefs that allow the coaches to view these images"): the team's diagrams,
        # most-run play first, in a <details> under the table (the newest upload per play; copied by the parser's saves
        # fetch into <data>/play_diagrams).
        try:
            _pd_pc = ob[ob["level"].astype(str) == "play_call"]
            _pd_html = _sb_play_diagrams(str(ob["team"].astype(str).value_counts().index[0]), None, _pd_pc)
            if _pd_html:
                add(_pd_html)
        except Exception as _pde:
            print(f"  (play diagrams not shown: {type(_pde).__name__}: {_pde})", flush=True)
        # CONFIRMED CHANGE (requested: passes per possession -- "a simple analysis on the scouting briefs"): one short card
        # under the table from uww_pass_summary (built after Player tracking): how often a possession ends on a pass
        # (Synergy, every game) and, on tracked games, the estimated passes per possession and PPP by passes.
        try:
            _ps = _sb_d("uww_pass_summary")
        except Exception:
            _ps = pd.DataFrame()
        if not _ps.empty and {"scouted_opponent", "team"} <= set(_ps.columns):
            _ps = _ps[_ps["scouted_opponent"].astype(str) == str(short)]
            _ps = (_ps[_ps["team"].astype(str).str.contains("whitewater", case=False, na=False)] if _us
                   else _ps[_ps["team"].astype(str) == str(short)])
            if not _ps.empty:
                _r = _ps.sort_values("possessions", ascending=False).iloc[0]
                _f = lambda v, d=2: _sb_fmt(pd.to_numeric(v, errors="coerce"), d)  # noqa: E731
                _who = "We" if _us else _sb_esc(opp_display)
                _lines = []
                if pd.notna(pd.to_numeric(_r.get("ends_on_pass_pct"), errors="coerce")):
                    _lines.append(f"<b>{int(_r['ends_on_pass_pct'])}%</b> of {('our' if _us else 'their')} "
                                  f"{int(_r['possessions'])} possessions end on a pass to the finisher "
                                  f"({_f(_r.get('ppp_ends_on_pass'))} PPP) vs {_f(_r.get('ppp_no_final_pass'))} PPP "
                                  "when the finisher creates his own shot. <span class=\"mini\">(Synergy)</span>")
                _nt = int(pd.to_numeric(_r.get("tracked_possessions"), errors="coerce") or 0)
                if _nt >= 20:
                    _b = " · ".join(f"{lab}: {_f(_r.get('ppp_' + k))} PPP ({int(pd.to_numeric(_r.get('poss_' + k), errors='coerce') or 0)})"
                                    for lab, k in (("0–1 passes", "0_1"), ("2–3", "2_3"), ("4+", "4_plus")))
                    _lines.append(f"{_who} average about <b>{_f(_r.get('avg_passes'), 1)} passes</b> a possession -- {_b}. "
                                  f"<span class=\"mini\">(estimate from player tracking, {_nt} possessions)</span>")
                if _lines:
                    add('<div class="card"><div class="pc-sub">Passing</div>'
                        + "".join(f'<p class="strip-line">{x}</p>' for x in _lines) + "</div>")

    def _action_freq_card(side):
        """CONFIRMED CHANGE (requested: "under HOW <OPP> RUNS OFFENSE ... the first thing should be a table that lists the
        Action (coach-tagged)"): every action group, how many of the team's coach-tagged possessions include it, and the
        share -- No action tagged first, then most-run first (uww_action_frequency, built in 47)."""
        try:
            af = _sb_d("uww_action_frequency")
        except Exception:
            return
        if af.empty or not {"side", "team", "action"} <= set(af.columns):
            return
        af = af[(af["side"].astype(str) == side) & (af["scouted_opponent"].astype(str) == str(short))]
        if side == "Opponent":
            af = af[af["team"].astype(str) == str(short)]
        else:
            af = af[af["team"].astype(str).str.contains("whitewater", case=False, na=False)]
        if af.empty:
            return
        af = af[af["team"] == af.groupby("team")["tagged_possessions"].max().idxmax()].copy()
        af["_p"] = pd.to_numeric(af["possessions"], errors="coerce").fillna(0)
        af["_o"] = pd.to_numeric(af["order"], errors="coerce").fillna(99)
        af = pd.concat([af[af["_o"] == 0], af[af["_o"] != 0].sort_values(["_p", "_o"], ascending=[False, True])])
        n = int(pd.to_numeric(af["tagged_possessions"], errors="coerce").max() or 0)
        ng = int(pd.to_numeric(af["games"], errors="coerce").max() or 0)
        add('<div class="card"><div class="pc-sub">Actions (coach-tagged)</div><table class="compact">'
            '<thead><tr><th style="text-align:left">Action (coach-tagged)</th><th>Possessions</th>'
            f'<th>% of {n}</th></tr></thead><tbody>')
        for _, r in af.iterrows():
            add(f'<tr><td style="text-align:left">{_sb_esc(r["action"])}</td><td>{int(r["_p"])}</td>'
                f'<td>{_sb_fmt(r.get("pct"))}%</td></tr>')
        add("</tbody></table>"
            f'<p class="mini">Out of {n} coach-tagged possessions on offense in {ng} game(s). One possession can include '
            "several actions, so the shares add to more than 100%. \u201cNo action tagged\u201d is mostly transition and "
            "putbacks; it makes every other share a minimum.</p></div>")

    # CONFIRMED CHANGE (requested 11/18: "format the 'HOW ELMHURST RUNS OFFENSE' and 'HOW WE RUN OFFENSE' sections the
    # same way with 5 of the most important pieces of information as cards above an expandable section ... Motion, Plays,
    # Actions, BLOB/SLOB and Tempo"). The cards ride in the _sb_sechead slot, so _sb_collapse keeps them beside the
    # header and puts the tables behind one "Show the detail" expander -- the same shape as TEAM COMPARISON and the
    # lineup sections. They are built from _offense_rows(side), the SAME rows the section's own tables use, so a card can
    # never contradict the table under it (the 11/18 headline bug was exactly that). Rates are shown against the side's
    # own average (team_ppp), never a league number, and no card quotes a tagged-possession denominator (requested
    # earlier: nothing should read "... on 85 tagged").
    # CONFIRMED CHANGE (requested 11/23: "a card next to Actions ... that says what each team will do in 'Clutch Situations' ... then
    # a section similar to Play Call Summary ... that lists out the Clutch Situations and how to view them all in Synergy").
    # OUR clutch definition (section 47's _gs_situation, the same rule the clutch lines on the roster cards use): not the first
    # half, 5:00 or less, margin 8 or fewer. This season's tagged possessions with the ball, for one side ("UWW" / "Opponent");
    # a call that names the other team is left out, as in every other offense table.
    def _clutch_poss(side):
        try:
            t = _clutch_tbl("UWW" if side == "UWW" else "Opponent")
            if t is None or t.empty:
                return pd.DataFrame()
            _spc = globals().get("season_play_calls")
            if callable(_spc):
                t = _spc(t)
            if "call_names_other_team" in t.columns:
                t = t[t["call_names_other_team"].isna()]
            if "decode_quality" in t.columns:
                t = t[t["decode_quality"].astype(str) != "Untagged"]
            if {"game_date", "clip_number"} <= set(t.columns):
                t = t.sort_values(["game_date", "clip_number"], ascending=[False, True])
            return t
        except Exception as _ce:
            print(f"  (clutch possessions not built: {type(_ce).__name__}: {_ce})", flush=True)
            return pd.DataFrame()

    def _clutch_counts(t):
        """(play calls, actions) counted over the clutch possessions, most used first."""
        calls, acts = {}, {}
        for _, r in t.iterrows():
            _pc = r.get("play_call")
            _pc = "No play call" if not isinstance(_pc, str) or not _pc.strip() or _pc.strip().lower() == "nan" else _sb_clean(_pc)
            calls[_pc] = calls.get(_pc, 0) + 1
            _al = [x.strip() for x in str(r.get("play_actions") or "").split("|") if x.strip() and x.strip().lower() != "nan"]
            if not _al:
                _pa = str(r.get("primary_action") or "").strip()
                _al = [_pa] if _pa and _pa.lower() not in ("nan", "none") else []
            for _a_ in dict.fromkeys(_al):
                acts[_sb_clean(_a_)] = acts.get(_sb_clean(_a_), 0) + 1
        _srt = lambda d: sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))
        return _srt(calls), _srt(acts)

    def _off_cards(side):
        # CONFIRMED CHANGE (requested 11/18, second pass: "make each of those 5 cards be actually informative for coaches
        # and not just how many possessions and PPP"). Every card now answers who runs it, what it turns into, what shape
        # they are in, what shots come out of it and what it costs -- all columns the summary already carries
        # (top_player, top_action, personnel_grouping_mode, fga/fg3a/fg_pct, turnovers, fouls_drawn), none of them
        # computed here. The read line at the bottom is the one a coach repeats in a staff meeting.
        sm = _offense_rows(side)
        if sm.empty or not {"level", "name", "uses", "ppp"} <= set(sm.columns):
            return ""
        _mine = side == "UWW"
        _us, _our = ("we", "our") if _mine else ("they", "their")

        def _lvl(name):
            d = sm[sm["level"].astype(str) == name].copy()
            if d.empty:
                return d
            d["_u"] = pd.to_numeric(d["uses"], errors="coerce").fillna(0)
            d["_p"] = pd.to_numeric(d["ppp"], errors="coerce")
            return d[~d["name"].astype(str).str.contains("unspecified", case=False, na=False)].sort_values("_u", ascending=False)

        _t = pd.to_numeric(sm.get("team_ppp"), errors="coerce").dropna()
        _team = float(_t.iloc[0]) if len(_t) else None
        _n = lambda r, c: (float(pd.to_numeric(r.get(c), errors="coerce")) if pd.notna(pd.to_numeric(r.get(c), errors="coerce")) else None)  # noqa: E731
        _last = lambda x: str(x).split()[-1] if str(x).strip() else ""  # noqa: E731

        def _rate(d):
            d = d[d["_p"].notna()] if not d.empty else d
            u = float(d["_u"].sum()) if not d.empty else 0.0
            return (float((d["_p"] * d["_u"]).sum()) / u) if u else None

        def _poss(n, p=None):
            # CONFIRMED CHANGE (requested 11/18): the rate leads and the sample rides in brackets --
            # "0.97 PPP (30 Poss)", not "30 possessions, 0.97 a trip".
            return f"{p:.2f} PPP ({int(n)} Poss)" if p is not None else f"{int(n)} Poss"

        def _who(r, verb="in"):
            """Who the possession ran through, and how often -- surname only, the way it is said out loud."""
            nm, u = _last(_sb_clean(r.get("top_player"))), _n(r, "top_player_uses")
            return f"{nm} {verb} {int(u)}" if nm and u else (nm or "")

        def _shape(r):
            g = _sb_clean(r.get("personnel_grouping_mode"))
            return g if g and g.lower() != "nan" else ""

        def _into(r):
            a = _sb_clean(r.get("top_action"))
            return f"into {a}" if a and a.lower() != "nan" else ""

        def _shots(r):
            """What comes out of it: how many of the shots are threes, and how they shoot overall."""
            fga, fg3a, pct = _n(r, "fga"), _n(r, "fg3a"), _n(r, "fg_pct")
            if not fga:
                return ""
            out = f"{int(fg3a)} of {int(fga)} shots from three" if fg3a else f"{int(fga)} shots, none from three"
            return out + (f", {pct:.0f}% overall" if pct is not None and fga >= 4 else "")

        def _cost(r):
            to, fd = _n(r, "turnovers"), _n(r, "fouls_drawn")
            bits = ([f"{int(to)} turnover" + ("s" if int(to) != 1 else "")] if to else []) \
                + ([f"{int(fd)} foul" + ("s" if int(fd) != 1 else "") + " drawn"] if fd else [])
            return ", ".join(bits)

        def _vs(p):
            if p is None or _team is None:
                return ""
            d = p - _team
            return ("above " if d > 0.05 else "below " if d < -0.05 else "right at ") + f"{_our} average ({_team:.2f})"

        def _card(t, name, value, sub, note, split=""):
            # `split` is a second sub-line of its own (the trigger / screener split), not more text on the first
            return (f'<div class="lc"><div class="lc-t">{_sb_esc(t)}</div><div class="lc-n">{_sb_esc(name)}</div>'
                    + (f'<div class="lc-v">{_sb_esc(value)}</div>' if value else "")
                    + (f'<div class="lc-s">{_sb_esc(sub)}</div>' if sub else "")
                    + (f'<div class="lc-s lc-split">{_sb_esc(split)}</div>' if split else "")
                    + (f'<div class="lc-x">{_sb_esc(note)}</div>' if note else "") + "</div>")

        # CONFIRMED BUG (fixed 11/18; Corey: "Plays and Actions cards don't match the bullet points underneath").
        # The cards were ranking play_call_summary rows while the bullets under them come from
        # uww_offense_summary, which 47 builds from the clips with its own grouping (ACTION_GROUPS folds "DHO /
        # handoff" into one, OB_SUMMARY_MIN_POSS gates it) -- so the card said "Cheetah scores best (1.80 on 5)"
        # while the bullet said "BLOB (2x, 2.50 PPP) \u00b7 Cheetah (5x, 1.80 PPP) \u00b7 Zoom (3x, 1.67 PPP)". The
        # most-successful half of both cards is now LIFTED FROM THAT BULLET's own text, numbers and all, so the two
        # read the same words. Most-used still comes from the summary table, and both halves are now labelled.
        def _best_from_bullets(kind):
            try:
                _os_ = _sb_d("uww_offense_summary")
            except Exception:
                return []
            if _os_.empty or "kind" not in _os_.columns:
                return []
            _r = _os_[(_os_["kind"].astype(str) == kind)
                      & (_os_["perspective"].astype(str) == side)]
            if "scouted_opponent" in _r.columns:
                _r = _r[_r["scouted_opponent"].astype(str) == str(short)]
            if _r.empty:
                return []
            return [(m.group(1).strip(" \u00b7"), int(m.group(2)), float(m.group(3)))
                    for m in re.finditer(r"([^\u00b7:]+?)\s*\((\d+)x,\s*([\d.]+)\s*PPP\)", str(_r.iloc[0]["text"]))]

        def _best_line(kind, fallback_df=None):
            _b = _best_from_bullets(kind)
            if _b:
                return "Most successful: " + ", ".join(f"{n_} {p_:.2f} PPP ({c_} Poss)" for n_, c_, p_ in _b[:3])
            if fallback_df is not None and not fallback_df.empty:
                _f = fallback_df[fallback_df["_p"].notna() & (fallback_df["_u"] >= 2)].sort_values("_p", ascending=False)
                if len(_f):
                    return (f"Most successful: {_sb_clean(_f.iloc[0]['name'])} {_f.iloc[0]['_p']:.2f} PPP "
                            f"({int(_f.iloc[0]['_u'])} Poss)")
            return ""

        # CONFIRMED CHANGE (requested 11/22: the bullets above the offense table "should not be their own section ...
        # this information should be in the cards"). The formation and BLOB/SLOB bullets (uww_offense_summary kinds
        # "formation" / "oob") are read here and folded into the Plays and BLOB / SLOB cards; the success bullets were
        # already the "Most successful" lines of the Plays / Actions cards, and the bullet list is no longer printed.
        def _bullet_texts(kind):
            try:
                _o = _sb_d("uww_offense_summary")
                _o = _o[(_o["kind"].astype(str) == kind) & (_o["perspective"].astype(str) == side)]
                if "scouted_opponent" in _o.columns:
                    _o = _o[_o["scouted_opponent"].astype(str) == str(short)]
                return [str(t) for t in _o.sort_values("order")["text"]]
            except Exception:
                return []

        def _formation_line():
            out = []
            for t in _bullet_texts("formation"):
                m = re.match(r"^When (?:they are running|we run|they run) (.+?),.*?(?:they run|we run) (.+?) the most "
                             r"\((\d+)%, ([\d.]+) PPP\)", t)
                if m:
                    out.append(f"{m.group(1)}: {m.group(2)} most ({m.group(3)}%, {float(m.group(4)):.2f} PPP)")
            return ("By formation \u2014 " + " \u00b7 ".join(out)) if out else ""

        def _oob_bits():
            out = {}
            for t in _bullet_texts("oob"):
                m = re.match(r"^On (BLOB|SLOB) .*?(?:they|we) run (.+?) the most \((\d+)%, ([\d.]+) PPP\)", t)
                if m:
                    out[m.group(1)] = f"{m.group(1)} most run: {m.group(2)} ({m.group(3)}%, {float(m.group(4)):.2f} PPP)"
                else:
                    m = re.match(r"^On (BLOB|SLOB) ", t)
                    if m and "no play call" in t:
                        out[m.group(1)] = f"{m.group(1)}: no play call tagged yet"
            return out

        _dot = lambda *x: " \u00b7 ".join([y for y in x if y])  # noqa: E731
        _cap1 = lambda t: (t[:1].upper() + t[1:]) if t else t   # noqa: E731  (str.capitalize() would eat PPP / DHO)

        # CONFIRMED CHANGE (requested 11/18: "the scouting brief ... not splitting actions into trigger and screen
        # actions"). Film Tagging's Actions table records the two halves of every action separately -- what the man with
        # the ball did (trigger_actions: "Ball Screen (#3): Use Ball Screen") and what the screener did
        # (screener_actions: "Ball Screen (#35): Roll") -- but nothing in the brief ever read those two columns: the
        # Actions card, the breakdown table and the "most successful actions" bullet all counted the action TYPE and
        # stopped there. uww_action_reads does carry the split, per player, but it is gated at 2+ uses and most rows sit
        # at 1, so almost none of it reached the page. This reads the clip columns straight, so the split shows from the
        # first tagged possession.
        _ACT_RX = re.compile(r"^\s*(.*?)\s*(?:\(#(\d{1,2})\))?\s*:\s*(.+?)\s*$")

        def _role_reads(_side):
            """("Ball handler: Use Ball Screen 31 (0.87 PPP) \u00b7 Reject 3", "Screener: Roll 30 (0.87 PPP) \u00b7 Pop 6")."""
            if _pcc_all.empty or "side" not in _pcc_all.columns:
                return ""
            t = _pcc_all[_pcc_all["side"].astype(str) == _side]
            if "possession_side" in t.columns:
                t = t[t["possession_side"].astype(str) == "Offense"]
            if t.empty:
                return ""
            out = []
            for col, lab in (("trigger_actions", "Ball handler"), ("screener_actions", "Screener")):
                if col not in t.columns:
                    continue
                _n, _p = {}, {}
                for _, r_ in t.iterrows():
                    v = str(r_.get(col) or "")
                    if not v.strip() or v == "nan":
                        continue
                    _pts = float(pd.to_numeric(pd.Series([r_.get("points")]), errors="coerce").fillna(0).iloc[0])
                    for part in v.split(" | "):
                        m = _ACT_RX.match(part)
                        if not m:
                            continue
                        _read = _sb_clean(m.group(3))
                        if not _read or _read.lower() == "trigger":   # "Trigger" is the box being ticked, not a read
                            continue
                        _n[_read] = _n.get(_read, 0) + 1
                        _p[_read] = _p.get(_read, 0.0) + _pts
                if not _n:
                    continue
                _top = sorted(_n, key=lambda k: (-_n[k], k))[:3]
                out.append(f"{lab}: " + " \u00b7 ".join(
                    f"{k} {_n[k]}" + (f" ({_p[k] / _n[k]:.2f} PPP)" if k == _top[0] and _n[k] >= 3 else "")
                    for k in _top))
            return " \u2014 ".join(out)
        _MOT = r"(?i)motion|flow|5 ?out|four ?out|open ?post"
        cards = []
        ser, calls, act, sit, sc = (_lvl("Series"), _lvl("Play call"), _lvl("Primary action"),
                                    _lvl("Situation"), _lvl("Shot clock"))

        # 1. Motion -- the no-call offense: who it runs through, what it becomes, what it shoots
        mot = ser[ser["name"].astype(str).str.contains(_MOT, regex=True, na=False)] if not ser.empty else ser
        if not mot.empty and mot["_u"].sum():
            _b, _r = mot.iloc[0], _rate(mot)
            cards.append(_card("Motion", _sb_clean(_b["name"]), _poss(mot["_u"].sum(), _r),
                               _dot(_who(_b), _into(_b), _shape(_b)),
                               _cap1(_dot(_shots(_b), _cost(_b), _vs(_r))) + "."
                               if _dot(_shots(_b), _cost(_b), _vs(_r)) else ""))

        # 2. Plays -- the called sets, with the one that actually scores named
        if not calls.empty:
            plays = calls[~calls["name"].astype(str).str.contains(_MOT + r"|blob|slob", regex=True, na=False)]
            if not plays.empty and plays["_u"].sum():
                _top = plays.iloc[0]
                _bn = _best_line("success", plays)
                cards.append(_card("Plays", _sb_clean(_top["name"]), _poss(_top["_u"], _n(_top, "ppp")),
                                   _dot("Most used", _who(_top), _into(_top), f"{len(plays)} named sets"),
                                   _dot(_bn, f"nothing run more than {int(_top['_u'])} times yet"
                                        if _top["_u"] < 3 else "") + ("." if _bn or _top["_u"] < 3 else ""),
                                   split=_formation_line()))

        # 3. Actions -- what they run into, and how it has gone against each coverage
        if not act.empty and act["_u"].sum():
            _a = act.iloc[0]
            _cov = _lvl("Ball screen coverage faced")
            _cov = _cov[_cov["_p"].notna() & (_cov["_u"] >= 1)] if not _cov.empty else _cov
            _covtxt = ""
            if not _cov.empty and re.search(r"(?i)ball ?screen|p&r|pnr|dho|hand ?off", str(_a["name"])):
                _covtxt = "Against " + ", ".join(f"{_sb_clean(r['name'])} {r['_p']:.2f} PPP on {int(r['_u'])}"
                                                 for _, r in _cov.head(2).iterrows())
            _rest = act.iloc[1:3]
            _abest = _best_line("success_actions", act)
            _split = _role_reads(side)
            cards.append(_card("Actions", _sb_clean(_a["name"]), _poss(_a["_u"], _n(_a, "ppp")),
                               _dot("Most used", _who(_a, "runs it"), _shape(_a)),
                               _dot(_abest, _covtxt,
                                    "then " + ", ".join(f"{_sb_clean(r['name'])} ({int(r['_u'])} Poss)"
                                                        for _, r in _rest.iterrows()) if len(_rest) else "")
                               + ("." if _abest or _covtxt or len(_rest) else ""), split=_split))

        # CONFIRMED CHANGE (requested 11/23): CLUTCH card beside Actions -- what the team runs when the game is close late.
        try:
            _ct = _clutch_poss(side)
            if len(_ct):
                _cc, _ca = _clutch_counts(_ct)
                _cp = pd.to_numeric(_ct.get("points"), errors="coerce").fillna(0).sum() / len(_ct)
                _named = [k for k, v in _cc if k != "No play call"]
                cards.append(_card(
                    "Clutch", (_named[0] if _named else _cc[0][0]), _poss(len(_ct), float(_cp)),
                    "Plays: " + ", ".join(f"{('Flow' if (side == 'UWW' and k == 'No play call') else k)} ({v})" for k, v in _cc[:4]),
                    ("Actions: " + ", ".join(f"{k} ({v})" for k, v in _ca[:4])) if _ca else "No actions tagged on these yet"))
        except Exception as _e:
            print(f"[offense cards] clutch card skipped: {type(_e).__name__}: {_e}")

        # 4. BLOB / SLOB -- the two inbounds as a pair: where each one goes and which one hurts
        if not sit.empty:
            _ib = {k: sit[sit["name"].astype(str).str.fullmatch(k, case=False, na=False)] for k in ("BLOB", "SLOB")}
            _have = {k: v.iloc[0] for k, v in _ib.items() if not v.empty and v["_u"].sum()}
            if _have:
                _rs = {k: _n(r, "ppp") for k, r in _have.items() if _n(r, "ppp") is not None}
                _name = " \u00b7 ".join(f"{k} {int(_have[k]['_u'])}" for k in _have)
                _val = " \u00b7 ".join(f"{k} {_rs[k]:.2f} PPP ({int(_have[k]['_u'])} Poss)" for k in _rs) if _rs else ""
                _sub = _dot(*[f"{k} to {_who(r, 'in')}".replace(" in ", " \u2014 ") + (f", {_into(r)}" if _into(r) else "")
                              for k, r in _have.items() if _who(r)])
                if _rs and max(_rs.values()) == 0:
                    _note = f"No points off either yet \u2014 {_us} have put up "
                    _note += ", ".join(f"{int(_n(r, 'fga') or 0)} shot(s) on {k}" for k, r in _have.items()) + "."
                elif len(_rs) == 2:
                    _hi = max(_rs, key=_rs.get)
                    _note = (f"{_hi} is the one that hurts ({_rs[_hi]:.2f} against {_rs[min(_rs, key=_rs.get)]:.2f})."
                             if _rs[_hi] > min(_rs.values()) else "Both score about the same.")
                else:
                    _k0 = next(iter(_rs), None)
                    _note = (f"{_k0} is {_vs(_rs[_k0])}." if _k0 else "")
                _ob = _oob_bits()
                _note = _dot(*[_ob[k] for k in ("BLOB", "SLOB") if k in _ob], _note)
                cards.append(_card("BLOB / SLOB", _name, _val, _sub, _note))

        # 5. Tempo -- the whole clock distribution, where they are best, and how much is transition
        if not sc.empty and sc["_u"].sum():
            _short = lambda n: ("early" if "early" in str(n).lower() else
                                "late" if "late" in str(n).lower() else "organized")  # noqa: E731
            _by = {_short(r["name"]): r for _, r in sc.iterrows()}
            _order = [k for k in ("early", "organized", "late") if k in _by]
            _name = " \u00b7 ".join(f"{k.capitalize()} {int(_by[k]['_u'])}" for k in _order)
            _bestsc = sc[sc["_p"].notna()].sort_values("_p", ascending=False)
            _tr = sit[sit["name"].astype(str).str.fullmatch("transition", case=False, na=False)] if not sit.empty else sm.iloc[0:0]
            _trtxt = ""
            if not _tr.empty and _tr["_u"].sum():
                _trr = _n(_tr.iloc[0], "ppp")
                _trtxt = (f"{_trr:.2f} PPP in transition ({int(_tr['_u'].sum())} Poss)" if _trr is not None
                          else f"{int(_tr['_u'].sum())} Poss in transition")
            _bb = _bestsc.iloc[0] if len(_bestsc) else None
            cards.append(_card(
                "Tempo", _name,
                (f"best with the clock {_short(_bb['name'])}: {_bb['_p']:.2f} PPP ({int(_bb['_u'])} Poss)"
                 if _bb is not None else ""),
                _dot(_trtxt, _who(_by[_order[0]]) if _order else ""),
                ((f"{_us.capitalize()} spend most of it {_short(sc.iloc[0]['name'])} "
                  f"({_shots(sc.iloc[0]) or 'no shots logged'})." if _shots(sc.iloc[0]) else "")
                 + (f" Worst {_short(_bestsc.iloc[-1]['name'])}: {_bestsc.iloc[-1]['_p']:.2f}."
                    if len(_bestsc) > 1 else "")).strip()))

        # CONFIRMED CHANGE (requested 11/22: "2 rows of cards ... What they're good at, and What they struggle with.
        # What to Play Hope In should not be its own section ... that data should end up in the cards"). The two new
        # cards carry what the WHAT TO PLAY section used to say: how this offense scores against each defense family
        # (man / zone / press), what pressure does to its turnovers, plus its best and worst sets, actions and clocks.
        try:
            _pfx = _pf_opp if side == "Opponent" else _pf_uww
            _fmin = int(globals().get("_DEF_FAMILY_MIN", 3))
            _fr = []
            if _pfx is not None and not _pfx.empty and "_fam" in _pfx.columns:
                for _f_, _g_ in _pfx.groupby("_fam"):
                    _p_ = _ppp_of(_g_)
                    if len(_g_) >= _fmin and _p_ is not None:
                        _fr.append((str(_f_), _p_))
            _fr.sort(key=lambda x: x[1])
            _pres = ""
            if _pfx is not None and not _pfx.empty and "press_faced" in _pfx.columns and "_to" in _pfx.columns:
                _pd_ = _pfx[_pfx["press_faced"].astype(bool)]
                _up_ = _pfx[~_pfx["press_faced"].astype(bool)]
                if len(_pd_) >= _fmin and len(_up_) >= _fmin:
                    _tp, _tu = 100 * _pd_["_to"].sum() / len(_pd_), 100 * _up_["_to"].sum() / len(_up_)
                    _pres = f"Pressure moves {_us} turnover rate {_tp - _tu:+.1f} points ({_tu:.1f}% to {_tp:.1f}%)"

            def _ranked(d, hi):
                d = d[d["_p"].notna() & (d["_u"] >= 2)] if not d.empty else d
                return d.sort_values("_p", ascending=not hi) if not d.empty else d
            _pl = calls[~calls["name"].astype(str).str.contains(r"(?i)blob|slob", regex=True, na=False)] if not calls.empty else calls
            _bs, _ws = _ranked(_pl, True), _ranked(_pl, False)
            _ba, _wa = _ranked(act, True), _ranked(act, False)
            _bc, _wc = _ranked(sc, True), _ranked(sc, False)
            _sc_short = lambda n: ("early clock" if "early" in str(n).lower() else
                                   "late clock" if "late" in str(n).lower() else "organized offense")  # noqa: E731
            _row = lambda r: f"{_sb_clean(r['name'])} {r['_p']:.2f} PPP ({int(r['_u'])} Poss)"  # noqa: E731
            if len(_fr) or len(_bs) or len(_ba):
                _good_sub = f"Best against {_fr[-1][0]}: {_fr[-1][1]:.2f} PPP" if _fr else ""
                _good_note = _cap1(_dot(
                    ("Best set: " + _row(_bs.iloc[0])) if len(_bs) else "",
                    ("best action: " + _row(_ba.iloc[0])) if len(_ba) else "",
                    ("best clock: " + _sc_short(_bc.iloc[0]["name"]) + f" {_bc.iloc[0]['_p']:.2f}") if len(_bc) else "")) 
                _good_note = (_good_note + ".") if _good_note else ""
                cards.append(_card((_us + "\u2019re good at").capitalize() if False else "What " + _us + "\u2019re good at",
                                   _sb_clean(_bs.iloc[0]["name"]) if len(_bs) else (_fr[-1][0] if _fr else "--"),
                                   f"{_bs.iloc[0]['_p']:.2f} PPP ({int(_bs.iloc[0]['_u'])} Poss)" if len(_bs) else "",
                                   _good_sub, _good_note))
                _w_name = (f"Press" if False else (_fr[0][0] if _fr else (_sb_clean(_ws.iloc[0]["name"]) if len(_ws) else "--")))
                _st_sub = _dot((f"Hurt most against {_fr[-1][0]}: {_fr[-1][1]:.2f} PPP" if len(_fr) > 1 and _fr[-1][1] > _fr[0][1] else ""),
                               _pres)
                _st_note = _cap1(_dot(
                    ("Weakest set: " + _row(_ws.iloc[0])) if len(_ws) and (not len(_bs) or _ws.iloc[0]["name"] != _bs.iloc[0]["name"]) else "",
                    ("weakest action: " + _row(_wa.iloc[0])) if len(_wa) and (not len(_ba) or _wa.iloc[0]["name"] != _ba.iloc[0]["name"]) else "",
                    ("weakest clock: " + _sc_short(_wc.iloc[0]["name"]) + f" {_wc.iloc[0]['_p']:.2f}") if len(_wc) and len(_bc) and _wc.iloc[0]["name"] != _bc.iloc[0]["name"] else ""))
                _st_note = (_st_note + ".") if _st_note else ""
                cards.append(_card("What " + _us + " struggle with", _w_name,
                                   (f"{_fr[0][1]:.2f} PPP against {_fr[0][0]}" if _fr else
                                    (f"{_ws.iloc[0]['_p']:.2f} PPP ({int(_ws.iloc[0]['_u'])} Poss)" if len(_ws) else "")),
                                   _st_sub, _st_note))
        except Exception as _e:
            print(f"[offense cards] good-at / struggle cards skipped: {type(_e).__name__}: {_e}")

        if len(cards) < 2:
            return _sb_pc_top(side)                        # not enough tagged yet -- the one-line headline instead
        _r1 = [c for c in cards if any(f'lc-t">{t}<' in c for t in ("Motion", "Plays", "Actions", "Clutch"))]
        _r2 = [c for c in cards if c not in _r1]
        _rows = [r for r in (_r1, _r2) if r]
        return "".join('<div class="lcards wm-cards">' + "".join(r) + "</div>" for r in _rows)

    def offense_section_test2(side, title, extra=None, extra_note=""):
        """extra: HTML cards built into this section (requested: their film and reads go in here, not in sections of
        their own) -- after the quadrant card, or the section's only content when their offense isn't tagged yet."""
        def _extra_only():
            # CONFIRMED BUG (fixed): with no rated play calls AND no film cards, the section (and its Situation /
            # formation table) was skipped even when coach-tagged possessions exist -- e.g. Ripon, whose only tags are
            # situations from our game against them. The table now prints whenever it has rows.
            try:
                _obd = _sb_d("uww_offense_breakdown")
                _has_tbl = (not _obd.empty and "perspective" in _obd.columns
                            and ((_obd["perspective"].astype(str) == side)
                                 & (_obd["scouted_opponent"].astype(str) == str(short))).any())
            except Exception:
                _has_tbl = False
            if extra or _has_tbl:
                section(title + footnote(extra_note))
                _sb_sechead(_off_cards("Opponent" if side == "Opponent" else "UWW"))
                (_action_freq_card if globals().get("BRIEF_ACTION_TABLES", False) else _offense_breakdown_card)(side)
                add(f'<p class="mini">{_sb_esc(OPP_UP)}\u2019s offense isn\u2019t coach-tagged enough for the set '
                    "breakdown yet -- what follows is from the film.</p>")
                add("".join(extra or []))
        sm = _offense_rows(side)
        if sm.empty:
            return _extra_only()
        calls = sm[(sm["level"] == "Play call")
                   & ~sm["name"].astype(str).str.contains("unspecified", na=False)].copy()
        if calls.empty:
            return _extra_only()
        calls["_uses"] = pd.to_numeric(calls["uses"], errors="coerce").fillna(0)
        calls["_ppp"] = pd.to_numeric(calls["ppp"], errors="coerce")
        _QSHOW = 3     # plays listed per quadrant; the rest collapse to "+ N more"
        _QMIN = 2      # lower than our own side: a set they ran twice and scored on is still a warning
        _rated = calls[(calls["_uses"] >= _QMIN) & calls["_ppp"].notna()]
        if _rated.empty:
            return _extra_only()
        team_ppp = calls["team_ppp"].dropna().iloc[0] if calls["team_ppp"].notna().any() else _rated["_ppp"].mean()
        _use_cut = _rated["_uses"].median()
        _meta_df, _meta_sample = staff_rows("uww_opp_sets")
        _meta = {_norm(r["set_name"]): r for _, r in _meta_df.iterrows()} if not _meta_df.empty else {}
        _film = _film_clip_lookup() if side == "Opponent" else {}

        section(title + footnote(
            "Play call flags in the table sort each set by how often they run it against how "
            f"well it scores. The usage line is the median ({_use_cut:.0f} uses) and the efficiency line is "
            f"their own average ({team_ppp:.2f} PPP), so this is relative to them, not to the league. Sets "
            f"with fewer than {_QMIN} tagged possessions are left out. \"Haven't seen it enough\" is the "
            "cell to read twice: those are efficient looks with a thin sample, which is what beats a "
            "defense that only prepared for the obvious." + (" " + extra_note if extra and extra_note else "")))
        _sb_sechead(_off_cards("Opponent" if side == "Opponent" else "UWW"))

        _quads = [
            ("Take this away", "They run it a lot and it works", "q-bad",
             lambda r: r["_uses"] >= _use_cut and r["_ppp"] >= team_ppp, "ppp"),
            ("Haven't seen it enough", "Efficient, but thin sample \u2014 don't get surprised", "q-up",
             lambda r: r["_uses"] < _use_cut and r["_ppp"] >= team_ppp, "ppp"),
            # Sorted by USAGE, not PPP: the point of this cell is "they keep going to it and it doesn't
            # work", so their most-run sets lead. Sorting by PPP here put the least-bad sets first and cut
            # their two most-run sets (4-1 Ball Screen, OK State Pat Miller) off the bottom.
            ("Make them keep running it", "They go to it often and it doesn't score", "q-good",
             lambda r: r["_uses"] >= _use_cut and r["_ppp"] < team_ppp, "uses"),
            ("Live with it", "Rare and ineffective \u2014 don't spend practice on it", "q-dim",
             lambda r: r["_uses"] < _use_cut and r["_ppp"] < team_ppp, "ppp"),
        ]
        # CONFIRMED CHANGE (requested: "Instead of having a separate chart below the table, I want the rows that are for
        # each of these to be flagged"): each rated play call gets its quadrant as a coloured flag in the Situation /
        # formation table; the four-box chart only prints with BRIEF_QUADRANT = True.
        _flags = {}
        for _qname, _qsub, _qcls, _test, _sort in _quads:
            for _, r in _rated[_rated.apply(_test, axis=1)].iterrows():
                _m = _meta.get(_norm(r["name"]))
                _flags[_norm(_sb_clean(r["name"]))] = (_qname, _qcls, _sb_clean(_m.get("our_call")) if _m is not None else "")
        globals()["_SB_PC_FLAGS"] = _flags
        globals()["_SB_TEAM_PPP"] = float(team_ppp) if pd.notna(team_ppp) else None
        (_action_freq_card if globals().get("BRIEF_ACTION_TABLES", False) else _offense_breakdown_card)(side)
        globals()["_SB_PC_FLAGS"] = {}
        add('<div class="card">')
        if not globals().get("BRIEF_QUADRANT", False):
            _quads = []
        if _quads:
            add('<div class="quad">')
        for _qname, _qsub, _qcls, _test, _sort in _quads:
            # Most dangerous first by default; "Make them keep running it" leads with what they run most.
            _order = ["_uses", "_ppp"] if _sort == "uses" else ["_ppp", "_uses"]
            _rows = _rated[_rated.apply(_test, axis=1)].sort_values(_order, ascending=[False, False])
            add(f'<div class="quad-cell {_qcls}">'
                f'<div class="quad-h">{_sb_esc(_qname)}<span class="quad-n">{len(_rows)}</span></div>'
                f'<div class="quad-sub">{_sb_esc(_qsub)}</div>')
            if _rows.empty:
                add('<div class="quad-empty">Nothing here yet.</div>')
            for _, r in _rows.head(_QSHOW).iterrows():
                # Defensive detail: who finishes it, where it happens, and our coverage call -- the three
                # things a defender needs. (Our own version showed "best vs defense", which is an offensive
                # read and has no meaning for a team we don't call plays for.)
                _who = _sb_clean(r.get("top_player"))
                _where = _sb_clean(r.get("top_location"))
                _m = _meta.get(_norm(r["name"]))
                _cov = _sb_clean(_m.get("our_call")) if _m is not None else ""
                _cn = _film.get(_norm(r["name"]))
                _meta_bits = " &middot; ".join(x for x in (_who, _where) if x)
                add(f'<div class="quad-row"><span class="quad-set">{_sb_esc(_sb_clean(r["name"]))}</span>'
                    + (f' <span class="mini">\U0001f3ac {_cn}</span>' if _cn else "")
                    + f'<span class="quad-num">{r["_ppp"]:.2f} PPP<span class="mini"> in {int(r["_uses"])} possession{"" if int(r["_uses"]) == 1 else "s"}</span></span>'
                    + (f'<div class="quad-meta">{_sb_esc(_meta_bits)}</div>' if _meta_bits else "")
                    + (f'<div class="quad-cov">{_sb_esc(_cov)}</div>' if _cov else "")
                    + "</div>")
            if len(_rows) > _QSHOW:
                add(f'<div class="quad-more">+ {len(_rows) - _QSHOW} more</div>')
            add("</div>")
        if _quads:
            add("</div>")
        if _meta_sample:
            add('<p class="mini">Coverage calls are a generated placeholder until '
                'staff_inputs/opp_sets.csv exists.</p>')
        # CONFIRMED CHANGE (requested: "I don't want anything to just say 'motion' ... every team runs a motion offense but
        # they all do things differently"): how THIS team runs its Motion -- one row per Motion family (uww_motion_breakdown,
        # built in 47): how often, PPP, the usual actions in order, who triggers it, who screens, how it ends.
        try:
            _mb = _sb_d("uww_motion_breakdown")
        except Exception:
            _mb = pd.DataFrame()
        if not globals().get("BRIEF_ACTION_TABLES", False):
            _mb = pd.DataFrame()                      # (the combined situation / formation table replaces it)
        if not _mb.empty and "side" in _mb.columns:
            _mb = _mb[(_mb["side"].astype(str) == side)
                      & (_mb["scouted_opponent"].astype(str) == str(short) if "scouted_opponent" in _mb.columns else True)]
            if not _mb.empty:
                _tm = _mb.groupby("team")["uses"].sum().sort_values(ascending=False).index[0]
                _mb = _mb[_mb["team"] == _tm].copy()
                _mb["_u"] = pd.to_numeric(_mb["uses"], errors="coerce").fillna(0)
                _mb = _mb.sort_values("_u", ascending=False)
                _tot = int(_mb["_u"].sum())
                add('<div class="card"><div class="quad-h">How they run Motion'
                    f'<span class="quad-n">{_tot}</span></div>'
                    '<div class="quad-sub">Motion split by the first action that defines it -- every team’s motion is '
                    'different</div><table class="compact mb-tbl"><tr><th>Motion</th><th>Uses</th><th>PPP</th><th>Usual actions</th>'
                    '<th>Triggered by</th><th>Screener</th><th>How it ends</th></tr>')
                for _, _r in _mb.iterrows():
                    _pp = pd.to_numeric(_r.get("ppp"), errors="coerce")
                    _sh = pd.to_numeric(_r.get("share_pct"), errors="coerce")
                    add("<tr>" + "".join(f"<td>{x}</td>" for x in (
                        _sb_esc(_sb_clean(_r.get("motion_family"))),
                        f"{int(_r['_u'])}" + (f' <span class="mini">({int(_sh)}%)</span>' if pd.notna(_sh) else ""),
                        f"{_pp:.2f}" if pd.notna(_pp) else "--",
                        _sb_esc(_sb_clean(_r.get("actions"))) or "--",
                        _sb_esc(_sb_clean(_r.get("trigger"))) or "--",
                        _sb_esc(_sb_clean(_r.get("screener"))) or "--",
                        _sb_esc(_sb_clean(_r.get("finish"))) or "--")) + "</tr>")
                add("</table>")
                _na = _mb[_mb["motion_family"].astype(str).str.contains("no action", case=False)]["_u"].sum()
                if _na:
                    add(f'<p class="mini">{int(_na)} Motion possession(s) were tagged without an action -- '
                        "they stay “no action tagged” until the action is added in Film Tagging.</p>")
                add("</div>")
        add('<p class="mini">' + app_link("Every set, clip and spot", page="upcoming", tab="game_plan",
                                          section=f"play_calls_{side.lower()}") + "</p>")
        add("</div>")
        if extra:
            add("".join(extra))

    _ro_card = ""  # CONFIRMED CHANGE: opponent reads now live on each player's roster card (_reads_of)
    _fo_html = capture(_film_off_cards)
    offense_section_test2("Opponent", f"\U0001f3ac {OPP_UP} OFFENSE", extra=([_ro_card] if _ro_card else []) + _fo_html,
                          extra_note=" ".join(x for x in ((_READS_NOTE if _ro_card else ""), (_film_off_note if _fo_html else "")) if x))

    # ---- sections that need tagging or staff input (kept, laid out two-up) ---------------------------------
    # Only real rows reach these tables now (sample rows are dropped at load), so the section prints only
    # when at least one of them has something to show.
    def _staff_input_tables():
        # THEIR DEFENSE & HOW WE ATTACK IT, DEFENSE TYPE BY SITUATION and BALL SCREEN COVERAGE moved out of
        # this block: they are real now (defense tagging) and all three are combined into "What they will play
        # against us" at the top of HOW WE RUN OFFENSE. The tables are still exported for the app.
        # HELP & ROTATION removed from the brief (requested) -- still built and shown in the app's Game Plan tab.
        # MATCHUP HISTORY removed from the brief (requested) -- still exported for the app.
        staff_table("uww_play_counters", "\U0001f504 WHEN WE TAKE AWAY THEIR SET",
                    [("set", "Set"), ("their_counter", "Their counter"), ("our_adjustment", "Our adjustment")],
                    "A title captures one action, not a sequence.",
                    note="Counters: tag a second clip when a denied action leads into another, linked to the first clip's "
                         "number. Value: High, but hardest to tag consistently -- a season-two addition.")
        if ROSTER_LAYOUT != "stacked":   # stacked roster carries a real per-player shot line instead
            staff_table("uww_opp_shot_zones", "\U0001f3af SHOT LOCATIONS \u2014 TOP FIVE",
                    [("player", "Player"), ("rim", "Rim"), ("paint_non_rim", "Paint"), ("midrange", "Mid"),
                     ("corner_3", "C3"), ("above_break_3", "AB3")],
                    "Three-point share is real; the zone split is a placeholder.",
                    note="Shot locations: tag a zone (rim / paint / mid / corner 3 / above-break 3) on every shot. The decoder "
                         "reads some spots from titles (\"LW 3\") but never for twos. Value: High.")
        staff_table("uww_opp_tendencies", "\U0001f3c3 TRANSITION, GLASS &amp; BENCH",
                    [("item", "Area"), ("detail", "What they do")],
                    "Placeholders (staff_inputs/opp_tendencies.csv).",
                    note="Transition/glass/bench: tag \"Transition\" as its own situation (Early clock is only a rough "
                         "stand-in); glass crashers need a rebounder tag; timeouts and officials aren't in the play-by-play. "
                         "Value: Medium.")
        # REBOUND TENDENCIES removed as a section (requested). The full table stays in the app; the brief
        # carries rebounding only when it's lopsided -- a Keys to Victory key (built in the KTV cell), a Bottom
        # Line sentence, and a roster read on the player doing the crashing. Rules: REBOUND_RULES.
        staff_table("uww_shot_quality_by_contest", "\U0001f3af SHOT QUALITY BY CONTEST",
                    [("contest_level", "Contest"), ("freq_pct", "%"), ("fg_pct", "FG%")],
                    "Contest level isn't tagged beyond Synergy's guarded/open.",
                    note="Shot quality: tag wide open / open / contested / tightly contested on every shot. Value: Medium.")
        staff_table("uww_double_team_tendencies", "\U0001f465 DOUBLE-TEAMS",
                    [("trigger", "Trigger"), ("from_where", "From"), ("escape_read", "Escape")],
                    "Double teams aren't tagged.",
                    note="Double teams: tag when one occurs, from where, and the read. Value: Medium, narrow scope.")
        staff_table("uww_offball_screen_navigation", "\U0001f504 OFF-BALL SCREEN NAVIGATION",
                    [("screen_type", "Screen"), ("technique", "Technique"), ("freq_pct", "%")],
                    "Off-ball screen technique isn't tagged.",
                    note="Off-ball screens: tag over/under/switch/fight-through on down screens, pin downs and staggers. "
                         "Value: Medium-to-low; pairs with Ball Screen Coverage.")

    _staff_html = capture(_staff_input_tables)
    if _staff_html:
        page_break()
        section("\U0001f52c NEEDS TAGGING OR STAFF INPUT" + footnote(
            "Each section's own \u24d8 note says what to tag and how much it would add. Controlled vocabulary for "
            "play titles: every title decoded correctly only because the decoder absorbs spelling variance "
            "(\"Blob-Box-Curl\" vs \"BLOB- Box- Curl\"); a dropdown or autocomplete built from the playbook "
            "would remove that fragility. Value: process, not new data."))
        add('<div class="flow2">')
        add("".join(_staff_html))
        add("</div>")

    # =====================================================================================================
    # UW-WHITEWATER -- mirrors the opponent section
    # =====================================================================================================
    _uww_stats = players_for("uww_pbp_box_score", _SB_UWW)
    personnel_pages("UWW", "UW-WHITEWATER", _uww_stats, uww_card, break_first=True,
                    lead=lambda: divider("UW-WHITEWATER", "Our own personnel, offense and week"))

    # (11/22: no page break -- our lineups are part of the roster's card, under the starters)
    # MATCHUPS removed from the brief (requested) -- still built and shown in the app's Game Plan tab.
    _uww_lu = _sb_d("uww_uww_lineup_season")
    if not _uww_lu.empty:
        _lu_note = footnote(
            "Five-man units: the top 2 in each of MIN, +/-, per 40, PPP and 3P% (bold = top 2 in that column), plus the five on the floor for the most tagged possessions. per 40 and 3P% rank units with "f"{LINEUP_TABLE_RULES['five_min_minutes']:.0f}+ minutes (3P% needs 3+ attempts, PPP 3+ tagged possessions). "
            "3-man combos: our best three this season, from the play-by-play's "
            "lineup stints, ranked by scoring margin per 40 minutes shrunk toward zero as if "
            f"{LINEUP_TABLE_RULES['shrink_minutes']:.0f} minutes of an even game were added. Competitive "
            "minutes only: MIN and +/- leave out stints that start in the 2nd half or later with the margin "
            "already lopsided. A five-man unit needs "
            f"{LINEUP_TABLE_RULES['five_min_minutes']:.0f}+ minutes; a combo meets the same bar as the "
            f"\"Feature the ... combo\" key ({LINEUP_TABLE_RULES['uww_three_min_minutes']:.0f}+ minutes, "
            f"{LINEUP_TABLE_RULES['uww_three_min_games']}+ games, better with them on than off), so that "
            "combo is the top row. * marks a unit shown below the bar because fewer than three cleared it. "
            "PPP is offense only, from tagged possessions, and does not affect the order.")
        # the one-line headline this section used to carry is gone: the cards say the same thing with the
        # numbers next to it, and three of them beat one sentence (requested)
        _open_or_join_card()      # (a second, stray "card" open used to sit here too -- one is enough)
        _lu_cards("UWW", _uww_lu)
        add('<details class="rosdet"><summary><span class="rd-open">Full tables</span>'
            '<span class="rd-sub">every five-man unit and 3-man combo, with what they run</span>'
            + _lu_note + "</summary>")
        lineups_table(_uww_lu, "UWW", note_rows=False)
        _combo_html = capture(combos_table, "UWW")
        if _combo_html:
            add('<div class="pc-sub">Top 3-man combos</div>')
            add("".join(_combo_html))
        add('<p class="mini">' + app_link("All of our lineups and combos", page="upcoming", tab="stats",
                                          section="uww_lineups") + "</p></details></div>")

    # =====================================================================================================
    # HOW WE RUN OFFENSE -- the same quadrant idea as the opponent's section above, but the question flips:
    # table and the bar layout used for the opponent. Scouting THEM is about recognition ("what are they
    # about to run"); scouting OURSELVES is a different question -- what should we call more, and what
    # should we stop calling. So this one drops the situation-by-situation structure entirely and sorts
    # every set into a usage x efficiency quadrant, which turns the table into a decision instead of a
    # reference. Cut whichever of the three loses.
    # =====================================================================================================
    def offense_section_test_uww(side, title, extra=None, extra_note=""):
        """extra: HTML cards built into this section (our reads off our actions) -- after the quadrant card, or on
        their own when our offense has no rated sets yet."""
        def _extra_only():
            if extra:
                section(title + footnote(extra_note))
                _sb_sechead(_off_cards("Opponent" if side == "Opponent" else "UWW"))
                add("".join(extra))
        sm = _offense_rows(side)
        if sm.empty:
            return _extra_only()
        calls = sm[(sm["level"] == "Play call")
                   & ~sm["name"].astype(str).str.contains("unspecified", na=False)].copy()
        if calls.empty:
            return _extra_only()
        calls["_uses"] = pd.to_numeric(calls["uses"], errors="coerce").fillna(0)
        calls["_ppp"] = pd.to_numeric(calls["ppp"], errors="coerce")
        # A set needs enough reps for its PPP to mean anything before it can be told to call it more or less.
        _QMIN = 3
        _QSHOW = 3     # sets listed per quadrant; the rest collapse to "+ N more"
        _rated = calls[(calls["_uses"] >= _QMIN) & calls["_ppp"].notna()]
        if _rated.empty:
            return _extra_only()
        team_ppp = calls["team_ppp"].dropna().iloc[0] if calls["team_ppp"].notna().any() else _rated["_ppp"].mean()
        # Split on the median so the quadrants always have something in them -- a fixed usage cutoff would
        # empty out early in the season and overflow late.
        _use_cut = _rated["_uses"].median()

        r_uses_cut = _use_cut

        def _q_context(set_name):
            """The four things a coach asked for on every quadrant row, each computed from that set's own
            clips: who finishes it (and how often, so "Jake Quast" can't be misread as a recommendation),
            which personnel group and clock window it lives in, and WHY it landed in this quadrant --
            shooting, turnovers, or simply how rarely we call it."""
            blank = {"who": "", "lineup": "", "clock": "", "driver": "", "unit": ""}
            if _pcc_all.empty or "play_call" not in _pcc_all.columns:
                return blank
            d = _pcc_all[(_pcc_all["side"] == side)
                        & (_pcc_all["play_call"].astype(str) == str(set_name))
                        & (~_pcc_all["decode_quality"].isin(["Needs review", "Untagged"]))].copy()
            if "possession_side" in d.columns:
                d = d[d["possession_side"].astype(str) != "Defense"]
            if d.empty:
                return blank
            n = len(d)
            d["_pts"] = pd.to_numeric(d.get("points"), errors="coerce")
            _res = d["result"].astype(str).str.lower() if "result" in d.columns else pd.Series("", index=d.index)
            d["_to"] = _res.str.contains("turnover|violation|kicked", regex=True)
            d["_fga"] = _res.str.startswith(("make", "miss")) & _res.str.contains("2|3", regex=True)
            d["_fgm"] = _res.str.startswith("make") & _res.str.contains("2|3", regex=True)
            out = dict(blank)

            # WHO -- stated as observed usage, never as a recommendation.
            if "player" in d.columns and d["player"].notna().any():
                _vc = d["player"].dropna().astype(str).value_counts()
                if len(_vc):
                    out["who"] = f"Finished by {_sb_title(_vc.index[0])} on {int(_vc.iloc[0])} of {n}"

            def _ppp_txt(g):
                k = g["_pts"].notna().sum()
                return f"{g['_pts'].sum() / k:.2f}" if k else "--"

            def _split_best(col, label_fmt):
                """Best- and worst-scoring bucket of a split, WITH what the split doesn't cover.

                Personnel and shot clock only exist on clips matched to a play-by-play event, so a split
                usually covers only part of the set's possessions. Without saying so, "worst 1.43" could sit
                above the set's 1.30 -- because the low-scoring possessions were the ones left out. So every
                bucket carries its count, and the uncovered remainder is stated with its own PPP; the pieces
                then reconcile with the number in the header."""
                if col not in d.columns:
                    return ""
                has = d[_sb_has_text(d[col])]
                rest = d.drop(has.index)
                _rest_txt = (f" &middot; {len(rest)} with no {'personnel' if 'personnel' in col else 'clock'} "
                             f"read (no play-by-play match) \u2014 {_ppp_txt(rest)}" if len(rest) else "")
                if has.empty:
                    return (f"No {'personnel' if 'personnel' in col else 'clock'} read on any of the {n} "
                            "(none matched to the play-by-play)")
                agg = has.groupby(has[col].astype(str)).agg(
                    n=("_pts", "size"), pts=("_pts", "sum"), known=("_pts", lambda x: x.notna().sum()))
                agg["ppp"] = agg["pts"] / agg["known"].replace(0, pd.NA)
                agg = agg.dropna(subset=["ppp"]).sort_values("ppp", ascending=False)
                if agg.empty:
                    return ""
                _top = agg.iloc[0]
                if len(agg) == 1:
                    return (label_fmt.format(kind="All", name=agg.index[0], ppp=_top["ppp"], n=int(_top["n"]))
                            + _rest_txt)
                _bot = agg.iloc[-1]
                return (label_fmt.format(kind="Best", name=agg.index[0], ppp=_top["ppp"], n=int(_top["n"]))
                        + f" &middot; worst {_bot.name} \u2014 {_bot['ppp']:.2f} ({int(_bot['n'])})" + _rest_txt)

            out["lineup"] = _split_best("personnel_grouping_type",
                                        "{kind} in {name} \u2014 {ppp:.2f} ({n})")
            out["clock"] = _split_best("shot_clock_situation",
                                       "{kind} on {name} \u2014 {ppp:.2f} ({n})")

            # UNIT -- the five- or three-man group it runs with most. on_court_lineup is a full five;
            # trimmed to three names so it fits a quadrant cell without wrapping to four lines.
            if "on_court_lineup" in d.columns and d["on_court_lineup"].notna().any():
                _lu = d["on_court_lineup"].dropna().astype(str).value_counts()
                if len(_lu) and int(_lu.iloc[0]) >= 2:
                    _names = [x.strip() for x in re.split(r"[,/|]", _lu.index[0]) if x.strip()]
                    _trio = ", ".join(_sb_title(x) for x in _names[:3])
                    out["unit"] = (f"Most with {_trio}"
                                   + (f" +{len(_names) - 3}" if len(_names) > 3 else "")
                                   + f" ({int(_lu.iloc[0])}x)")

            # HOW -- every possession and every point, so the header's PPP is explained, not asserted.
            # (It replaced a WHY line that only described the possessions that ended in a shot -- 6 of 11 in
            # the case that prompted this -- leaving fouls, turnovers and resets, and their points, invisible.)
            # Points include free throws: a possession that ends in a shooting foul scores at the line.
            def _outcome(r):
                t = str(r or "").lower()
                if t.startswith("make 3"):
                    return "made 3"
                if t.startswith("make"):
                    return "made 2"
                if t.startswith("miss"):
                    return "missed shot"
                if "turnover" in t:
                    return "turnover"
                if t in ("foul", "free throw", "1 pts", "0 pts") or "free throw" in t:
                    return "fouled"
                return "no shot"          # non-shooting foul, kicked ball, no violation, reset
            d["_out"] = d["result"].map(_outcome) if "result" in d.columns else "no shot"
            _order = ["made 3", "made 2", "fouled", "missed shot", "turnover", "no shot"]
            _labels = {"made 3": ("made three", "made threes"), "made 2": ("made two", "made twos"),
                       "fouled": ("fouled", "fouled"), "missed shot": ("missed shot", "missed shots"),
                       "turnover": ("turnover", "turnovers"),
                       "no shot": ("reset / non-shooting foul", "resets / non-shooting fouls")}
            _parts = []
            for _o in _order:
                _g = d[d["_out"] == _o]
                if _g.empty:
                    continue
                _k = len(_g)
                _p = _g["_pts"].sum()
                _name = _labels[_o][0 if _k == 1 else 1]
                if _o == "fouled":
                    _parts.append(f"{_k} {_name} \u2192 {_p:.0f} at the line")
                elif _p > 0:
                    _parts.append(f"{_k} {_name} ({_p:.0f})")
                else:
                    _parts.append(f"{_k} {_name}")
            _known = int(d["_pts"].notna().sum())
            _total = d["_pts"].sum()
            _head = f"{n} possessions, {_total:.0f} points"
            if _known < n:
                _head += f" ({n - _known} with no points read, left out of PPP)"
            out["driver"] = _head + ": " + " &middot; ".join(_parts)
            if r_uses_cut is not None and n < r_uses_cut:
                out["driver"] += " &middot; small sample"
            return out

        def _q_best_defense(set_name):
            """Highest-PPP defense this set scored against. Same rule as the main section's "Best vs.
            defense" column."""
            if _pcc_all.empty or "defense_faced" not in _pcc_all.columns or "play_call" not in _pcc_all.columns:
                return ""
            d = _pcc_all[(_pcc_all["side"] == side)
                        & (_pcc_all["play_call"].astype(str) == str(set_name))
                        & _pcc_all["defense_faced"].notna()
                        & (~_pcc_all["decode_quality"].isin(["Needs review", "Untagged"]))].copy()
            if "possession_side" in d.columns:
                d = d[d["possession_side"].astype(str) != "Defense"]
            if d.empty:
                return ""
            d["_pts"] = pd.to_numeric(d.get("points"), errors="coerce")
            by = d.groupby("defense_faced").agg(uses=("defense_faced", "size"), pts=("_pts", "sum"),
                                                known=("_pts", lambda s: s.notna().sum()))
            by["ppp"] = by["pts"] / by["known"].replace(0, pd.NA)
            if len(by) == 1:
                return _sb_clean(by.index[0])
            by = by[by["uses"] >= 2].dropna(subset=["ppp"])
            return _sb_clean(by.sort_values("ppp", ascending=False).index[0]) if not by.empty else ""

        section(title + footnote(
            "Play call flags in the table sort each set by how often we call it against "
            f"how well it scores. The usage line is the median ({_use_cut:.0f} uses) and the efficiency line "
            f"is our own average ({team_ppp:.2f} PPP), so this is relative to us, not to the league. Sets "
            f"with fewer than {_QMIN} tagged possessions are left out -- not enough reps to judge. Read it "
            "as a call sheet, not a verdict: a low-efficiency set may still be there to set up something "
            "else." + (" " + extra_note if extra and extra_note else "")))
        _sb_sechead(_off_cards("Opponent" if side == "Opponent" else "UWW"))
        _quads = [
            ("Keep calling it", "Called often, scores well", "q-good",
             lambda r: r["_uses"] >= _use_cut and r["_ppp"] >= team_ppp),
            ("Call it more", "Scores well, we barely call it", "q-up",
             lambda r: r["_uses"] < _use_cut and r["_ppp"] >= team_ppp),
            ("Fix it or cut it", "Called often, does not score", "q-bad",
             lambda r: r["_uses"] >= _use_cut and r["_ppp"] < team_ppp),
            ("Shelve it", "Rarely called, does not score", "q-dim",
             lambda r: r["_uses"] < _use_cut and r["_ppp"] < team_ppp),
        ]
        # CONFIRMED CHANGE (requested: our offense in the same Situation > Formation > Play call table, flagged)
        _flags = {}
        for _qname, _qsub, _qcls, _test in _quads:
            for _, r in _rated[_rated.apply(_test, axis=1)].iterrows():
                _flags[_norm(_sb_clean(r["name"]))] = (_qname, _qcls, "")
        globals()["_SB_PC_FLAGS"] = _flags
        _offense_breakdown_card("UWW")
        globals()["_SB_PC_FLAGS"] = {}
        add('<div class="card">')
        # ---- What they will play against us -- replaces three separate sections --------------------
        # THEIR DEFENSE & HOW WE ATTACK IT, DEFENSE TYPE BY SITUATION and BALL SCREEN COVERAGE all
        # described the same thing -- the opponent's own defense -- three ways, and each partly restated
        # the others (requested: combine). It lives HERE rather than in WHAT TO PLAY THEM IN because that
        # section is about THEIR OFFENSE; this is the other side of the ball, and it is exactly what our
        # sets below have to beat. Computed straight from the clips (defense_PLAYED on the opponent's
        # defensive possessions) so the base-defense, by-situation and coverage numbers can't disagree.
        _td = pd.DataFrame()
        if not _pcc_all.empty and "defense_played" in _pcc_all.columns:
            _td = _pcc_all[(_pcc_all["side"] == "Opponent")
                           & (~_pcc_all["decode_quality"].isin(["Needs review", "Untagged"]))
                           & _pcc_all["defense_played"].notna()].copy()
            if "possession_side" in _td.columns:
                _td = _td[_td["possession_side"].astype(str) == "Defense"]
        _TD_MIN = 4
        if len(_td) >= _TD_MIN:
            _td["_pts"] = pd.to_numeric(_td.get("points"), errors="coerce")
            add(f'<div class="tier-h">What {_sb_esc(OPP_UP)} will play against us</div>')
            add('<table class="compact"><thead><tr><th style="text-align:left">Situation</th><th>Poss</th>'
                '<th style="text-align:left">Base defense</th><th style="text-align:left">Changes to</th>'
                '<th>PPP allowed</th></tr></thead><tbody>')
            # Overall first, then each situation that has enough possessions to say something.
            _groups = [("All", _td)]
            if "play_situation" in _td.columns:
                _so = ["Half court", "Transition", "BLOB", "SLOB", "ATO"]
                for _sit in _so + [x for x in _td["play_situation"].dropna().astype(str).unique() if x not in _so]:
                    _sg = _td[_td["play_situation"].astype(str) == _sit]
                    if len(_sg) >= _TD_MIN:
                        _groups.append((_sit, _sg))
            for _lbl, _g in _groups:
                _vc = _g["defense_played"].astype(str).value_counts()
                _base_txt = f"{_vc.index[0]} ({round(100 * int(_vc.iloc[0]) / len(_g))}%)"
                _chg = (f"{_vc.index[1]} ({round(100 * int(_vc.iloc[1]) / len(_g))}%)" if len(_vc) > 1 else "--")
                _known = _g["_pts"].notna().sum()
                _ppp = (_g["_pts"].sum() / _known) if _known else None
                add(f'<tr class="{"serrow" if _lbl == "All" else "setrow"}"><td class="wrap">{_sb_esc(_lbl)}</td>'
                    f'<td>{len(_g)}</td><td class="wrap">{_sb_esc(_base_txt)}</td>'
                    f'<td class="wrap mini">{_sb_esc(_chg)}</td><td>{_sb_fmt(_ppp, 2)}</td></tr>')
            add("</tbody></table>")

            _lines = []
            # Ball-screen coverage, with what it gives up -- the coverage that leaks most is the one to attack.
            if "coverage_played" in _td.columns:
                _cv = _td[_sb_has_text(_td["coverage_played"])]
                if not _cv.empty:
                    _cvs = []
                    for _cn, _cg in _cv.groupby(_cv["coverage_played"].astype(str)):
                        _k = _cg["_pts"].notna().sum()
                        _cvs.append((_cn, len(_cg), (_cg["_pts"].sum() / _k) if _k else None))
                    _cvs.sort(key=lambda x: -x[1])
                    _lines.append("<strong>Ball screens:</strong> " + ", ".join(
                        f"{_sb_esc(n)} {c}x" + (f" ({p:.2f} allowed)" if p is not None else "")
                        for n, c, p in _cvs[:4]))
                    _leak = [x for x in _cvs if x[1] >= 3 and x[2] is not None]
                    if len(_leak) >= 2:
                        _worst_cov = max(_leak, key=lambda x: x[2])
                        _lines[-1] += (f" \u2014 attack <strong>{_sb_esc(_worst_cov[0])}</strong>, "
                                       f"it gives up the most.")
            if "press_played" in _td.columns and int(_td["press_played"].astype(bool).sum()):
                _pr = _td[_td["press_played"].astype(bool)]
                _pf = (_pr["press_formation_played"].dropna().astype(str).value_counts()
                       if "press_formation_played" in _pr.columns else pd.Series(dtype=int))
                _lines.append(f"<strong>Pressure:</strong> pressed on {len(_pr)} of {len(_td)} possessions"
                              + (f" ({_sb_esc(', '.join(_pf.index[:2]))})" if len(_pf) else "") + ".")
            # Staff's "how we attack it" notes carry over when the staff has actually written them -- the
            # generated sample text never does.
            _sd, _sd_sample = staff_rows("uww_opp_defense")
            if not _sd.empty and not _sd_sample and "how_we_attack" in _sd.columns:
                for _, _sr in _sd.iterrows():
                    _how = _sb_clean(_sr.get("how_we_attack"))
                    if _how:
                        _lines.append(f"<strong>{_sb_esc(_sb_clean(_sr.get('item')))}:</strong> "
                                      f"{_sb_esc(_how)}")
            for _l in _lines:
                add(f'<p class="strip-line">{_l}</p>')
            add('<p class="mini">Each set below shows which defense it beat \u2014 read the two together.</p>')
        else:
            add(f'<p class="mini">{_sb_esc(OPP_UP)}\'s own defense isn\'t tagged yet, so what they\'ll play '
                'against us isn\'t shown. It appears here once their defensive possessions are tagged.</p>')

        # CONFIRMED CHANGE (requested: "replace our four-box quadrant just like Carroll's chart with flags"): the flags
        # are on our play-call rows in the table above; the chart only prints with BRIEF_QUADRANT = True.
        if not globals().get("BRIEF_QUADRANT", False):
            _quads = []
        if _quads:
            add('<div class="quad quad-rich">')
        for _qname, _qsub, _qcls, _test in _quads:
            _rows = _rated[_rated.apply(_test, axis=1)].sort_values(
                ["_ppp", "_uses"], ascending=[False, False])
            add(f'<div class="quad-cell {_qcls}">'
                f'<div class="quad-h">{_sb_esc(_qname)}<span class="quad-n">{len(_rows)}</span></div>'
                f'<div class="quad-sub">{_sb_esc(_qsub)}</div>')
            if _rows.empty:
                add('<div class="quad-empty">Nothing here yet.</div>')
            for _, r in _rows.head(_QSHOW).iterrows():
                _vs = _q_best_defense(r["name"])
                _cx = _q_context(r["name"])
                # Each line answers a different question, so they are labelled rather than run together:
                # who actually finishes it, what it runs with, when it runs, and why it scores the way it
                # does. The "who" line in particular is phrased as observed usage -- a bare name read as
                # "we should run this for him", which is not what the number says.
                _lines = []
                if _cx["who"]:
                    _lines.append(("Who", _cx["who"] + (f" &middot; best vs {_sb_esc(_vs)}" if _vs else "")))
                elif _vs:
                    _lines.append(("Who", f"best vs {_sb_esc(_vs)}"))
                if _cx["unit"]:
                    _lines.append(("Unit", _cx["unit"]))
                if _cx["lineup"]:
                    _lines.append(("Personnel", _cx["lineup"]))
                if _cx["clock"]:
                    _lines.append(("Clock", _cx["clock"]))
                if _cx["driver"]:
                    _lines.append(("How", _cx["driver"]))
                add(f'<div class="quad-row"><span class="quad-set">{_sb_esc(_sb_clean(r["name"]))}</span>'
                    f'<span class="quad-num">{r["_ppp"]:.2f} PPP<span class="mini"> in {int(r["_uses"])} possession{"" if int(r["_uses"]) == 1 else "s"}</span></span>'
                    + "".join(f'<div class="quad-meta"><span class="qk">{k}</span> {v}</div>'
                              for k, v in _lines)
                    + "</div>")
            if len(_rows) > _QSHOW:
                add(f'<div class="quad-more">+ {len(_rows) - _QSHOW} more</div>')
            add("</div>")
        if _quads:
            add("</div>")
        add('<p class="mini">' + app_link("Every set, clip and spot", page="upcoming", tab="game_plan",
                                          section="play_calls_uww") + "</p>")
        add("</div>")
        if extra:
            add("".join(extra))

    _ar_uww = next((t for t in _sb_d("uww_action_reads").get("offense_team", pd.Series(dtype=str)).dropna().astype(str).unique()
                    if "whitewater" in t.lower()), _SB_UWW)
    _ru_card = ""  # CONFIRMED CHANGE: our reads now live on each player's roster card (_reads_of)
    offense_section_test_uww("UWW", "\U0001f3c0 UW-WHITEWATER OFFENSE", extra=[_ru_card] if _ru_card else [],
                             extra_note=_READS_NOTE if _ru_card else "")

    # CONFIRMED CHANGE (requested 11/22: "Also do the same for us."): our offense is "UW-WHITEWATER OFFENSE" and there is a
    # "UW-WHITEWATER DEFENSE" with the same five cards, from OUR defensive possessions (possession_side Defense in the
    # UWW files). Cards with no data drop out; the screens card reads the "UWW defense" rows of uww_screen_coverage_summary.
    def _our_def_section():
        _spc = globals().get("season_play_calls")
        try:
            _all_ = _spc(_pcc_all) if callable(_spc) else _pcc_all
            _dp = _all_[(_all_["side"].astype(str) == "UWW") & (_all_["possession_side"].astype(str) == "Defense")]
            _dp = _dp[~_dp["synergy_string"].astype(str).str.lower().str.contains("non possession", na=False)]
        except Exception:
            return
        if len(_dp) < 10:
            return
        _cards = []
        # 1. base defense, and how it changes by situation
        _dt = _dp[_dp["defense_type"].notna()]
        if len(_dt) >= 10:
            _vc = _dt["defense_type"].astype(str).value_counts(normalize=True) * 100
            _bits = []
            for _sit in ("Half court", "Transition", "BLOB", "SLOB"):
                _g = _dt[_dt["play_situation"].astype(str) == _sit]["defense_type"].astype(str).value_counts(normalize=True) * 100
                if len(_g) and len(_dt[_dt["play_situation"].astype(str) == _sit]) >= 5:
                    _bits.append(f"{_sit}: {_sb_esc(_g.index[0])} {int(round(_g.iloc[0]))}%")
            _cards.append(_dcard("Base defense", _sb_esc(_vc.index[0]), f"{int(round(_vc.iloc[0]))}% of our possessions", "",
                                 (("also " + ", ".join(f"{_sb_esc(k)} {int(round(v))}%" for k, v in _vc.iloc[1:3].items()) + "<br>")
                                  if len(_vc) > 1 else "") + " \u00b7 ".join(_bits)))
        # 2. pressure
        if "defense_press" in _dp.columns and _dp["defense_press"].notna().sum() >= 10:
            _pv = _dp["defense_press"].dropna().astype(str).str.lower().isin(["true", "1", "yes"])
            _pp = int(round(100 * _pv.mean()))
            _kinds = _dp.loc[_dp["defense_press"].astype(str).str.lower().isin(["true", "1", "yes"]), "defense_press_formation"] \
                .dropna().astype(str).value_counts()
            _kl = list(_kinds.index)
            _cards.append(_dcard("Pressure", _sb_esc(_kl[0]) if _kl else "We rarely press", f"we press on {_pp}% of possessions",
                                 "", _sb_esc(", ".join(_kl[1:3]))))
        # 3. screens: how we have guarded them (tagged coverages, thin until more defense is tagged)
        _scv = _sb_d("uww_screen_coverage_summary")
        _scr_rows = pd.DataFrame()
        if not _scv.empty and {"perspective", "level", "screen_type", "coverage", "uses"} <= set(_scv.columns):
            _scr_rows = _scv[(_scv["perspective"] == "UWW defense") & (_scv["level"] == "Screen x coverage")
                             & (_scv["scouted_opponent"].astype(str) == str(short))].copy()
            _scr_rows["_u"] = pd.to_numeric(_scr_rows["uses"], errors="coerce")
        if not _scr_rows.empty and _scr_rows["_u"].sum():
            _by = _scr_rows.groupby("coverage")["_u"].sum().sort_values(ascending=False)
            _ty = _scr_rows.groupby("screen_type")["_u"].sum().sort_values(ascending=False)
            _thin_ = _by.sum() < (globals().get("SCREEN_COVERAGE_RULES", {}).get("thin_screens", 5))
            _cards.append(_dcard("Screens", f'Mostly <b>{_sb_esc(str(_by.index[0]).lower())}</b>', "", "",
                                 "<br>".join(f"{_sb_esc(k)}" for k in _by.index[1:3])
                                 + ("<br>Thin sample -- confirm on film." if _thin_ else "")))
        # 4. points allowed
        _dpp = _dp.assign(_pt=pd.to_numeric(_dp["points"], errors="coerce")).dropna(subset=["_pt"])
        if len(_dpp) >= 10:
            _by = _dpp.groupby(_dpp["play_situation"].astype(str))["_pt"].agg(["mean", "count"])
            _by = _by[_by["count"] >= 5].sort_values("mean")
            _lines = ([f'<b>Best:</b> {_sb_esc(_by.index[0])} {_by.iloc[0]["mean"]:.2f} PPP',
                       f'<b>Worst:</b> {_sb_esc(_by.index[-1])} {_by.iloc[-1]["mean"]:.2f} PPP'] if len(_by) >= 2 else [])
            _cards.append(_dcard("Points allowed", f'{_dpp["_pt"].mean():.2f} PPP',
                                 f'{(_dpp["result"].astype(str) == "Turnover").mean() * 100:.0f}% of trips end in a turnover',
                                 f'{_dpp["result"].astype(str).str.contains("Foul", na=False).mean() * 100:.0f}% end in a foul',
                                 "<br>".join(_lines)))
        # 5. who closes things down -- current roster only (the roles file also holds last season's players)
        _dr = _sb_d("uww_defensive_roles")
        try:
            _cur = {str(p) for p in _uww_stats["player"]}
        except Exception:
            _cur = set()
        if not _dr.empty and {"team", "player", "steals_blocks_per_game", "games"} <= set(_dr.columns) and _cur:
            _dr = _dr[(_dr["team"].astype(str).str.contains("Whitewater", case=False)) & _dr["player"].astype(str).isin(_cur)].copy()
            _dr["_sb"] = pd.to_numeric(_dr["steals_blocks_per_game"], errors="coerce")
            _dr = _dr[pd.to_numeric(_dr["games"], errors="coerce") >= 2].sort_values("_sb", ascending=False)
            if not _dr.empty and _dr.iloc[0]["_sb"] > 0:
                _t = _dr.iloc[0]
                _rest = "<br>".join(f'<b>{_sb_esc(r["player"].split()[-1])}</b> {r["_sb"]:.1f} \u00b7 {_sb_esc(str(r.get("defensive_role") or ""))}'
                                    for _, r in _dr.iloc[1:4].iterrows() if r["_sb"] > 0)
                _cards.append(_dcard("Who closes it down", _sb_esc(str(_t["player"])), f'{_t["_sb"]:.1f} steals + blocks a game',
                                     _sb_esc(str(_t.get("defensive_role") or "")), _rest))
        if len(_cards) < 2:
            return
        section("\U0001f6e1\ufe0f UW-WHITEWATER DEFENSE")
        _sb_sechead('<div class="lcards wm-cards">' + "".join(_cards) + "</div>")
        add('<p class="mini">Our own defensive possessions this season. Steals + blocks are per game from the box scores. '
            + app_link("Our defense in the app", page="upcoming", tab="game_plan", section="screen_coverage") + "</p>")

    _our_def_section()

    # CONFIRMED CHANGE (requested 11/18: "Give the trigger/screener split its own section ... per player"). The split
    # rides on the Actions card as a team total; this is the same thing player by player, from uww_action_reads, both
    # teams side by side: who uses the screen and who rejects it, who rolls and who pops. Offense only -- the defenders'
    # reactions are in the app's READS OFF ACTIONS table, which shows every row without a minimum.
    def _trigger_screen_section():
        _ar = _sb_d("uww_action_reads")
        if _ar.empty or not {"offense_team", "role", "player", "action", "read", "uses"} <= set(_ar.columns):
            return
        _ar = _ar[_ar["role"].astype(str).str.contains(r"(?i)ball handler|trigger|screener", regex=True, na=False)
                  & (pd.to_numeric(_ar["uses"], errors="coerce") >= _READS_MIN)
                  & ~_ar["player"].astype(str).str.startswith("(")]
        if "side_of_ball" in _ar.columns:
            _ar = _ar[_ar["side_of_ball"].astype(str) == "Offense"]
        if _ar.empty:
            return
        _blocks = []
        for _tm, _ttl in ((str(short), f"{OPP_UP}"), (_ar_uww, _SB_UWW.upper())):
            _t = _ar[_ar["offense_team"].astype(str) == str(_tm)]
            if _t.empty:
                continue
            _rows = []
            for _role, _lab in (("Ball handler (trigger)", "Trigger \u2014 the man with the ball"),
                                ("Screener", "Screener")):
                _g = _t[_t["role"].astype(str).str.fullmatch(re.escape(_role), case=False, na=False)]
                if _g.empty:
                    continue
                _rows.append(f'<tr class="rsub"><td colspan="5">{_sb_esc(_lab)}</td></tr>')
                for _, _r in _g.sort_values("uses", ascending=False).head(10).iterrows():
                    _sh = pd.to_numeric(_r.get("share_pct"), errors="coerce")
                    _rows.append(
                        f'<tr><td class="nm">{_sb_esc(_r["player"])}</td>'
                        f'<td style="text-align:left">{_sb_esc(_r["action"])}</td>'
                        f'<td style="text-align:left"><b>{_sb_esc(_r["read"])}</b></td>'
                        f'<td>{int(pd.to_numeric(_r["uses"], errors="coerce"))}'
                        + (f' <span class="mini">({int(_sh)}%)</span>' if pd.notna(_sh) and _sh > 0 else "")
                        + f'</td><td>{_sb_fmt(_r.get("ppp"), 2)}</td></tr>')
            if _rows:
                _blocks.append('<div class="card"><div class="pc-sub">' + _sb_esc(_ttl) + "</div>"
                               '<table class="compact"><thead><tr><th style="text-align:left">Player</th>'
                               '<th style="text-align:left">Action</th><th style="text-align:left">Did</th>'
                               '<th>Uses</th><th>PPP</th></tr></thead><tbody>' + "".join(_rows)
                               + "</tbody></table></div>")
        if not _blocks:
            return
        section("\U0001f501 TRIGGER &amp; SCREENER READS" + footnote(
            "Film Tagging records the two halves of every action separately: what the man with the ball did with it "
            "(use it, reject it, Cobra, Twirl) and what the screener did (roll, pop, slip). This is that split, player "
            "by player. A read tagged once is still listed -- Uses says how thin it is. The defenders' reactions to "
            "these same actions are in the app."))
        _sb_sechead("")
        add("".join(_blocks))
        add('<p class="mini">' + app_link("Every read, by player, with the defenders' reactions",
                                          page="upcoming", tab="game_plan", section="reads") + "</p>")

    # CONFIRMED CHANGE (requested 11/22: remove TRIGGER & SCREENER READS; the info goes in the team offense cards or the
    # players' roster info). Both already carry it: the Actions card's Ball handler / Screener line is the team split, and
    # every player's roster card lists his own reads (_reads_of, same uww_action_reads rows, same BRIEF_READS_MIN_USES).
    # BRIEF_TRIGGER_SECTION = True brings the section back.
    if globals().get("BRIEF_TRIGGER_SECTION", False):
        _trigger_screen_section()

    # AVAILABILITY and SCOUT TEAM removed from the brief (requested) -- still built and shown in full in
    # the app's Game Plan tab. Availability status still feeds the roster's per-player flag (see _avail_by
    # above), so that lookup stays; only the standalone OUR WEEK section is gone.

    # PRACTICE PLAN removed from the brief (requested) -- still built and shown in full in the app's Game
    # Plan tab. The brief's defensive recommendation and press verdict still feed it there.

    # =====================================================================================================
    # NOTES
    # =====================================================================================================
    _sb_photo_report.clear()
    _sb_photo_report.update({k: (v[0], list(v[1])) for k, v in _photo_stats.items()})
    _sb_notes_report.clear()
    _sb_notes_report.extend(footnotes)

    gl = _sb_d("uww_play_glossary")
    # The Notes list and the play-title glossary live in the APP now (requested). READ WITH CAUTION stays
    # -- it's a warning about the numbers on THIS page, not reference material, so it has to travel with
    # the brief. What's left here is a pointer: the ⓘ markers throughout already deep-link to individual
    # notes, and this card covers the two whole collections.
    _fs_info, _fs_rows = _sb_film_status()
    try:
        # The app renders this (Upcoming Game ?tab=notes&section=film, and Analytics > Video Tracking). Written even
        # with no metric rows yet, so the "what went in" counts still reach the app.
        _fs_info = dict(_fs_info, review_overrides_title=bool(globals().get("TAG_MODEL_REVIEW_OVERRIDES_TITLE", True)))
        pd.DataFrame(_fs_rows or [[None, None, None, None]], columns=["area", "measure", "value", "detail"]).assign(
            **{k: v for k, v in _fs_info.items()}).to_csv(os.path.join(APP_DATA_DIR, "uww_film_ai_status.csv"), index=False)
    except Exception:
        pass
    # CONFIRMED CHANGE (requested): HOW THE FILM IS WATCHED AUTOMATICALLY (how it works, what went in, how well it's
    # working, how the coaches' answers are used) lives only in the app now -- the brief links to it from the
    # Methodology card at the bottom. The opponent's film is built into their own sections; SELF-SCOUT FROM THE FILM
    # stays in the brief, here at the end.
    _film_link = bool(_fs_rows or _fs_info.get("clips_captured") or _fs_info.get("player_checks"))
    def _self_scout_film():
        # CONFIRMED CHANGE (requested): the opponent's film is built into their own sections (roster, HOW <OPP> RUNS
        # OFFENSE, HOW <OPP> GUARDS SCREENS -- see "THE FILM" above the roster). Our self-scout from the film is still
        # its own section, drawn here at the end, after our own sections (so its footnote number stays in order).
        # Self-scout: UWW's own coverage execution and spacing
        _ce = _sb_d("uww_trk_coverage_execution")
        # CONFIRMED CHANGE (requested): "our screen coverage vs the plan" only once a plan exists (the Game Plan tab's
        # coverage plan, or staff_inputs/uww_coverage_plan.csv) -- without one every row was tracking's estimate on an
        # unnamed defender with no plan to compare to. The app still shows it.
        if not _ce.empty and not ("planned" in _ce.columns and _ce["planned"].map(_sb_clean).astype(bool).any()):
            _ce = pd.DataFrame()
        if not _ce.empty and "defender" in _ce.columns:
            _ce = _ce[[not _tk_unnamed(x) for x in _ce["defender"]]]
        _spc = _sb_d("uww_trk_spacing")
        # our spacing on the court (court mapping) -- only when OUR film's court mapping passes the film-quality check
        _uq = _fq_of(next((t for t in (_fq["team"] if not _fq.empty and "team" in _fq.columns else [])
                           if "whitewater" in str(t).lower()), None))
        _spc_c = _sb_d("uww_court_spacing") if (_uq and _fq_true(_uq.get("court_ok"))) else pd.DataFrame()
        if not _ce.empty or not _spc.empty or not _spc_c.empty:
            section("\U0001fa9e SELF-SCOUT FROM THE FILM" + footnote(
                "Our defense: the coverage we played on each tracked screen vs the plan entered in the app (Game Plan > Our "
                "screen coverage plan) or staff_inputs/uww_coverage_plan.csv. Our offense: spacing by lineup -- average "
                "distance to the nearest teammate, how wide the five are, and how often two teammates (not screening) were "
                "within 6 ft. Approximate feet; small sample."))
            if not _ce.empty:
                _ce = _ce.assign(cov=_ce["coverage"].astype(str) + _ce["coverage_source"].map(lambda s: "*" if s == "tracking estimate" else ""))
                add('<div class="card"><div class="pc-sub">Our screen coverage vs the plan</div>'
                    + _tk_table(_ce, ["defender", "role", "screen_type", "cov", "times", "planned", "followed_pct"],
                                ["Our defender", "Role", "Screen", "Coverage", "Times", "Planned", "Followed %"]) + "</div>")
            if not _spc.empty:
                add('<div class="card"><div class="pc-sub">Our spacing by lineup (approx ft)</div>'
                    + _tk_table(_spc, ["lineup", "possessions", "spacing_ft_approx", "width_ft_approx", "crowded_pct", "ppp"],
                                ["Lineup", "Poss.", "Nearest teammate", "Width", "Crowded %", "PPP"], limit=8) + "</div>")
            if not _spc_c.empty:
                add('<div class="card"><div class="pc-sub">Our spacing on the court, by lineup</div>'
                    + _tk_table(_spc_c, ["lineup", "possessions", "both_corners_pct", "paint_crowded_pct", "spacing_ft", "ppp"],
                                ["Lineup", "Poss.", "Both corners filled %", "Paint crowded %", "Nearest teammate ft", "PPP"], limit=8) + "</div>")
            add('<p class="mini">' + _film_app_link("Film tracking: diagrams, possession replays, search by player") + "</p>")
    # CONFIRMED CHANGE (requested: remove SELF-SCOUT FROM THE FILM from the brief, keep it in the app -- Film tracking);
    # BRIEF_SELF_SCOUT_FILM = True brings it back
    _film_html = capture(_self_scout_film) if globals().get("BRIEF_SELF_SCOUT_FILM", False) else []
    if _film_html:
        page_break()
        for _h in _film_html:
            add(_h)
    # CONFIRMED CHANGE (requested: "remove the METHODOLOGY section and just have a link to it in the app down in the section
    # that starts with 'Generated ...'"). The Methodology card is gone; the footer links to the app's Notes instead.
    # CONFIRMED CHANGE (requested: "READ WITH CAUTION should also be removed from the briefs and should only be in the
    # application") -- the sample-size warnings (uww_sample_size_warnings) show in the app only.

    # ---- footer ---------------------------------------------------------------------------
    _an["skip"] = _an["ours"] = False                 # (parser_analysis: the footer is kept)
    try:
        generated = datetime.now().strftime("%B %-d, %Y at %-I:%M %p")
    except ValueError:
        # "%-d"/"%-I" are a glibc strftime extension that Windows' CRT rejects outright -- the same
        # portability trap the play-by-play cells already hit with "%-m"/"%-d". Fall back rather
        # than let a timestamp take down the whole report.
        generated = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    add('<div class="foot">')
    # CONFIRMED CHANGE (requested 11/18): "This information should be in a collapsible section as well and be
    # collapsed by default." Where the brief came from matters when a number is challenged, and the rest of
    # the time it is four paragraphs between the coach and the end of the page.
    add('<details class="rosdet"><summary><span class="rd-open">How this brief was built</span>'
        '<span class="rd-sub">sources, the film tagged behind it, methodology</span></summary>')
    add(f"<p>Generated {_sb_esc(generated)} from the scouting parser's exported data \u2014 the same "
        f"tables the scouting app reads, reconstructed from play-by-play, video-tagging and box-score "
        f"exports. Sample (placeholder) data is left out of this report; it still shows in the app.</p>")
    # CONFIRMED CHANGE (requested 11/14, review of the Elmhurst brief's "Built from:"): the "Not available for this build:
    # uww_double_team_tendencies, ..." line is gone -- internal table names mean nothing to a coach. The run's log still
    # lists them ("Tables that were empty or missing").
    add("<p>Prepared ahead of the staff's own scouting reports. Numbers will move as more film is "
        "tagged.</p>")
    # CONFIRMED CHANGE (requested 11/18: "add a part in 'How this brief was built' that shows our metric definitions").
    # Every number here is OUR definition, written from the constants the code actually uses -- the Four Factors weights
    # come straight out of _SB_FF_WEIGHTS, so this list cannot drift from the ranking it describes. Where the repo
    # departs from Dean Oliver's original (FT Rate on attempts, 0.475 on free throws) it says so.
    _defs = [
        ("Possession", "FGA \u2212 OREB + TO + 0.475 \u00d7 FTA. The 0.475 is KenPom's: it counts the share of free-throw "
                       "attempts that end a trip, rather than Oliver's original 0.44."),
        ("Points a possession (PPP)", "points \u00f7 possessions. On a play-call or lineup table it is the points scored on "
                                      "that set's or that unit's own tagged possessions."),
        ("Clutch", "not the first half, 5:00 or less on the clock, and the margin 8 points or fewer \u2014 the same rule "
                   "the clutch event log and the game plan use, applied to each team's own games."),
        ("Clutch, on offense", "the possessions where he was the man with the ball. The points are the "
                               "POSSESSION'S points, not his own scoring \u2014 a kick-out that someone else finishes "
                               "counts here \u2014 and the rate appears once there are three of them. A trip that ends at "
                               "the line scores nothing on the clip itself, so fouls drawn are counted separately."),
        ("Clutch, on defense", "there is no individual defensive box score here, so the card separates the two: "
                               "\u201cHIM\u201d is the one thing that is his \u2014 that he was on the floor for those "
                               "possessions \u2014 and \u201cTHE FIVE HE WAS IN\u201d is what the defense gave up while "
                               "he was out there, a team number that belongs to all five. Lower is better, and the team's "
                               "rate across every clutch defensive possession rides along for scale."),
        ("Clutch flags on a card", "the gold \u2605 chips. \u201cBest with the ball\u201d is the highest points a "
                                   "trip among players with at least three clutch possessions of their own. \u201cBest "
                                   "five on defense\u201d is the fewest points allowed a possession with him on the floor, "
                                   "among players on for at least three and 40% of the team's clutch defensive "
                                   "possessions \u2014 a five-man number, so it credits the lineup he was in, not him "
                                   "alone. Neither is given when too few players clear the bar, or when everyone who "
                                   "does has the same number."),
        ("Leading / Trailing by 10+", "the margin is 10 or more, either way, outside the clutch window above."),
        ("eFG%", "(FGM + 0.5 \u00d7 3PM) \u00f7 FGA \u2014 a three counted at its real worth."),
        ("TOV%", "turnovers \u00f7 possessions."),
        ("ORB%", "offensive rebounds \u00f7 (our offensive rebounds + their defensive rebounds) \u2014 the share of "
                 "available misses rebounded."),
        ("FT Rate", "FTA \u00f7 FGA, the Basketball-Reference form (how often they get to the line). Oliver's original "
                    "uses FTM \u00f7 FGA, which measures getting there AND making them."),
        ("Four Factors ranking", "the FOUR FACTORS table ranks the four at fixed weights \u2014 "
                                 + ", ".join(f"{k} {int(v * 100)}%" for k, v in _SB_FF_WEIGHTS.items())
                                 + " \u2014 Oliver's own order of importance. TEAM COMPARISON does something different: it "
                                   "prices each factor for THIS matchup, so the two can disagree about what matters most."),
        ("PPG difference", "points scored minus points allowed, a game."),
        ("Min/G (lineups)", "that unit's minutes on the floor divided by the games it appeared in \u2014 not its total "
                            "minutes, and not minutes a game for the players in it."),
        ("Shot clock", "seconds USED, scaled to a 30-second clock: Early 0\u20139, Organized 10\u201319, Late 20+."),
        ("\u201cOn film\u201d / \u201ctagged\u201d", "from the clips the coaches have tagged in the app, not the full "
                                               "season's box score \u2014 so these counts grow as tagging continues."),
    ]
    add('<p><b>What the numbers mean</b></p><ul class="tbl-bul">'
        + "".join(f"<li><b>{_sb_esc(k)}</b> \u2014 {_sb_esc(v)}</li>" for k, v in _defs) + "</ul>")
    # CONFIRMED CHANGE (requested: "On the bottom of the scouting briefs, make sure to include notes about the scouting
    # reports, player number tracking and film tracking that was used in creation").
    _src = []
    try:
        _ind = globals().get("INPUT_DIR") or "./inputs"
        _key = re.sub(r"[^a-z0-9]+", "", str(short).lower())[:8]
        _reps = []
        for _fn in sorted(os.listdir(_ind)):
            _m = re.match(r"^(\d{1,2})_(\d{1,2})_(\d{2}) (.+?)_scout\.(html|pdf)$", _fn, re.I)
            if _m and _key and _key in re.sub(r"[^a-z0-9]+", "", _m.group(4).lower()):
                _d = pd.Timestamp(year=2000 + int(_m.group(3)), month=int(_m.group(1)), day=int(_m.group(2)))
                _reps.append((_d, _m.group(4)))
        if _reps:
            _src.append("<b>Scouting reports (FastScout):</b> " + "; ".join(
                f"{_sb_esc(t)} ({d.month}/{d.day}/{d.strftime('%y')})"
                + (" \u2014 the upcoming game's report" if d >= pd.Timestamp.now().normalize() - pd.Timedelta(days=30)
                   else " \u2014 last meeting with us")
                for d, t in sorted(_reps)) + ".")
    except Exception:
        pass
    # CONFIRMED CHANGE (requested 11/14: "Drop Player Number Tracking and tracked games unless a section used them"). The
    # Elmhurst brief said "173 coach player check(s) in use" while its per-player film reads and court sections were OFF.
    # Tracking is named only when the film-quality gate (55e names_ok / court_ok) let it into this brief for either team.
    _trk_used = False
    try:
        if not _fq.empty and {"is_upcoming", "is_uww"} <= set(_fq.columns):
            _fqu = _fq[(_fq["is_upcoming"].astype(str) == "True") | (_fq["is_uww"].astype(str) == "True")]
            _trk_used = any(_fqu[c].astype(str).str.lower().eq("true").any() for c in ("names_ok", "court_ok") if c in _fqu.columns)
    except Exception:
        _trk_used = False
    try:
        _ptg = _sb_d("uww_player_tracking_games") if _trk_used else pd.DataFrame()
        _trr = _sb_d("uww_tracking_report") if _trk_used else pd.DataFrame()
        if not _ptg.empty and "game" in _ptg.columns:
            _bits = []
            for _g in _ptg["game"].astype(str):
                _r = _trr[_trr["game"].astype(str) == _g].iloc[0].to_dict() if (not _trr.empty and "game" in _trr.columns
                                                                                  and (_trr["game"].astype(str) == _g).any()) else {}
                _dt, _, _gc = _g.partition("|")
                _bits.append(f"{_sb_esc(_gc)} ({_sb_esc(_dt)})"
                             + (f": {int(_r['clips'])} clip(s) tracked, {int(_r.get('tracks_named') or 0)} player track(s) "
                                "named" if _r.get("clips") == _r.get("clips") and _r.get("clips") is not None else ""))
            # CONFIRMED CHANGE (requested: "only the checks in use"): the coach checks on THESE tracked games, made on the
            # current frames (coach_checks_all already sets aside the ones from before the tracking reset)
            _games = set(_ptg["game"].astype(str))
            try:
                _cc = [c for c in (coach_checks_all()[0] if "coach_checks_all" in globals() else []) if str(c.get("game")) in _games]
            except Exception:
                _cc = []
            _src.append("<b>Player Number Tracking:</b> " + "; ".join(_bits)
                        + (f" \u2014 {len(_cc)} coach player check(s) in use, on {len({c.get('clip_key') for c in _cc})} play(s)"
                           if _cc else "") + ".")
    except Exception:
        pass
    try:
        if not _fq.empty and "team" in _fq.columns:
            _rows_fq = _fq[(_fq.get("is_upcoming").astype(str) == "True") | (_fq.get("is_uww").astype(str) == "True")]
            _bits = [f"{_sb_esc(r['team'])} \u2014 {_sb_esc(_sb_clean(r.get('film_line')))}" for _, r in _rows_fq.iterrows()
                     if _sb_clean(r.get("film_line"))]
            if _bits and _trk_used:               # (11/14) the tagged counts are in the lines below, split by what is used
                _src.append("<b>Film tracking:</b> " + "; ".join(_bits) + ".")
    except Exception:
        pass
    # CONFIRMED CHANGE (requested: "Is there not any coach-tagged data for Carroll vs Elmhurst?" -- there is; the film line
    # only names the PLAYER-TRACKED games). Every game with coach-tagged possessions, per team, on offense.
    # CONFIRMED CHANGE (requested 11/14, review of the Elmhurst brief). This list said "Elmhurst: 126 coach-tagged
    # possessions on offense" when 82 were last season's (Carroll@Elmhurst 2/24/26) and the tables use this season's clips
    # only (BRIEF_THIS_SEASON_ONLY) -- 44 possessions, one game. And it never said that Elmhurst@Ripon had 89 Elmhurst
    # possessions nobody had tagged. Three lines now, each per team on offense:
    #   used in this brief          this season's tagged possessions, by game
    #   last season, not used       tagged, but left out of the tables
    #   still untagged this season  possessions on film with no tag yet (what to tag next)
    try:
        _pcf = _sb_d("uww_play_calls")
        if not _pcf.empty and {"game_date", "game_code", "offense_team", "decode_quality"} <= set(_pcf.columns):
            if "scouted_opponent" in _pcf.columns:
                _pcf = _pcf[_pcf["scouted_opponent"].astype(str) == str(short)]
            _pcf = _pcf.assign(_d=pd.to_datetime(_pcf["game_date"], errors="coerce"),
                               _tag=_pcf["decode_quality"].astype(str) != "Untagged")
            _split = bool(globals().get("BRIEF_THIS_SEASON_ONLY", True)) and bool(globals().get("LAST_SEASON"))
            _start = pd.Timestamp(int(globals().get("SEASON_START_YEAR") or 2000), 8, 1)
            _now = (_pcf["_d"] >= _start) if _split else pd.Series(True, index=_pcf.index)
            _fmt = lambda gt: ", ".join(                                                    # noqa: E731
                f"{_sb_esc(gc)} {pd.Timestamp(gd).month}/{pd.Timestamp(gd).day}/{pd.Timestamp(gd).strftime('%y')} ({int(n_)})"
                for (gd, gc), n_ in gt.sort_index().items())
            _used, _old, _todo = [], [], []
            _ot = _pcf["offense_team"].astype(str)
            _teams = [(str(short), _ot == str(short))] + ([] if _an["on"] else
                                                          [(_SB_UWW, _ot.str.contains("whitewater", case=False, na=False))])
            for _team, _mk in _teams:
                _g = lambda m: _pcf[m].groupby(["game_date", "game_code"]).size()           # noqa: E731
                _u, _o, _t = _g(_mk & _now & _pcf["_tag"]), _g(_mk & ~_now & _pcf["_tag"]), _g(_mk & _now & ~_pcf["_tag"])
                _used.append(f"{_sb_esc(_team)} \u2014 " + (f"{int(_u.sum())} possession{'s' if int(_u.sum()) != 1 else ''} in "
                                                             f"{len(_u)} game{'s' if len(_u) != 1 else ''}: {_fmt(_u)}"
                                                             if len(_u) else "none tagged yet"))
                if len(_o):
                    _old.append(f"{_sb_esc(_team)} \u2014 {int(_o.sum())} in {len(_o)} game{'s' if len(_o) != 1 else ''}"
                                + (f": {_fmt(_o)}" if len(_o) <= 3 else ""))
                if len(_t):
                    _todo.append(f"{_sb_esc(_team)} \u2014 {_fmt(_t)}")
            _src.append("<b>Tagged offense used in this brief" + (" (this season)" if _split else "") + ":</b> "
                        + "; ".join(_used) + ".")
            if _old:
                _src.append("<b>Tagged last season, not used in the tables:</b> " + "; ".join(_old) + ".")
            if _todo:
                _src.append("<b>Still untagged this season (offensive possessions on film):</b> " + "; ".join(_todo) + ".")
    except Exception as _e:
        print(f"  !! Built from: the tagged-film lines could not be built ({type(_e).__name__}: {_e})")
    if _src:
        add('<p><b>Built from:</b></p><ul class="bl">' + "".join(f"<li>{x}</li>" for x in _src) + "</ul>")
    if footnotes or not gl.empty or _film_link:
        add("<p>" + app_link("Methodology", page="upcoming", tab="notes")
            + " \u2014 how every number on this brief was built"
            + (", how the film is watched automatically" if _film_link else "")
            + (" and how the play titles were decoded" if not gl.empty else "") + ".</p>")
    add("</details>")
    add("</div>")

    # CONFIRMED CHANGE (requested 11/18; Corey, with Streamlit's lazy-loading expander example: "I'm looking
    # for the scouting briefs to show the most important information and then hide the rest of it behind an
    # expander"). Every section is wrapped in a <details> whose summary IS its own header bar, so the brief
    # opens as a page of headings with the sections that decide the game already open and everything else one
    # click away. Printing is unaffected: the script in <head> opens every <details> on beforeprint and closes
    # them again afterwards, which was already there for the collapsed tables.
    # BRIEF_OPEN_SECTIONS (set it in the notebook cell) decides what starts open -- matched case-insensitively
    # against the section title, so "KEYS" is enough for "KEYS TO VICTORY".
    # FOUR FACTORS is not in the default list on purpose: its header bar is the verdict sentence, so closed it
    # already says what the section concluded, and opening it is for the table behind that sentence.
    _open_cfg = globals().get("BRIEF_OPEN_SECTIONS")
    _SB_OPEN = [str(t).upper() for t in (_open_cfg if _open_cfg is not None else ())]
    # CONFIRMED CHANGE (requested 11/18): "KEYS TO VICTORY can be kept out of a collapsible section and should
    # always be visible", and then the same for the rosters -- "I want these removed from the roster
    # collapsible section. So the five starters row should always be visible." Not expanders that happen to
    # start open: no expander at all, so there is no chevron to click and no way for anyone to collapse the
    # two things a coach opens the brief for. The rosters keep their own inner "Full roster" expander, which
    # is what holds the cards, the bench and the reads -- only the five-across strip is always on the page.
    _SB_FIXED = [str(t).upper() for t in (globals().get("BRIEF_FIXED_SECTIONS")
                                          or ("KEYS TO VICTORY", "ROSTER", "RECENT RESULTS",
                                              "HOW THEY FINISHED LAST SEASON"))]
    # (the lineup blocks have no section header of their own any more -- requested -- so they ride inside the
    # roster section above them, which is itself always visible)

    def _sb_collapse(chunks):
        """Each run of output from one section header to the next becomes a <details>. Dividers, the banner
        and the footer are left alone -- they are not sections and a reader needs them on sight."""
        _is_sect = lambda c: isinstance(c, str) and c.lstrip().startswith('<div class="sect"')
        _is_stop = lambda c: isinstance(c, str) and (_is_sect(c) or c.lstrip().startswith('<div class="divider"')
                                                     or c.lstrip().startswith('<div class="foot"'))
        out, i = [], 0
        while i < len(chunks):
            if not _is_sect(chunks[i]):
                out.append(chunks[i])
                i += 1
                continue
            _head = chunks[i]
            _title = re.sub(r"<[^>]+>", " ", _head.replace("<!--", " ").replace("-->", " ")).upper()
            j = i + 1
            while j < len(chunks) and not _is_stop(chunks[j]):
                j += 1
            _body = chunks[i + 1:j]
            # a headline emitted by _sb_sechead rides with the header, and the rest goes behind one expander
            _line = _body[0] if _body and str(_body[0]).lstrip().startswith('<div class="sechead"') else None
            if _line is not None and len(_body) > 1:
                out.append(_head)
                out.append(_line)
                out.append('<details class="rosdet"><summary><span class="rd-open">Show the detail</span>'
                           '<span class="rd-sub">tables, reads and notes</span></summary>'
                           + "\n".join(_body[1:]) + "</details>")
            elif not _body or any(t in _title for t in _SB_FIXED):
                out.append(_head)               # always visible, or a header with nothing under it
                out.extend(_body)
            else:
                _open = " open" if any(t in _title for t in _SB_OPEN) else ""
                out.append(f'<details class="secdet"{_open}><summary>{_head}</summary>'
                           + "\n".join(_body) + "</details>")
            i = j
        return out

    body = "\n".join(_sb_collapse(parts) if globals().get("BRIEF_COLLAPSE_SECTIONS", True) else parts)
    # CONFIRMED CHANGE (requested 11/18): "Create an expand all button or option somewhere." One button at the
    # top right that opens every <details> on the page -- the sections, the full-roster blocks and the
    # play-call tables -- and turns into "Collapse all" once everything is open. It keeps itself in step with
    # the chevrons: clicking any section on its own re-labels the button, via a capturing listener for the
    # toggle event (toggle does not bubble, so capture is how one listener hears all of them).
    # Shown only when scripting is on -- a dead button is worse than none -- and never printed.
    if globals().get("BRIEF_COLLAPSE_SECTIONS", True):
        body = ('<div class="xall"><button type="button" id="xallbtn" class="xbtn">Expand all</button></div>\n'
                + body
                + '\n<script>(function(){document.documentElement.className+=" js";'
                  'var b=document.getElementById("xallbtn");if(!b)return;'
                  'function all(){return document.querySelectorAll("details");}'
                  'function sync(){var c=0;all().forEach(function(d){if(!d.open)c++;});'
                  'b.textContent=c?"Expand all":"Collapse all";b.dataset.mode=c?"open":"close";}'
                  'b.addEventListener("click",function(){var o=b.dataset.mode!=="close";'
                  'all().forEach(function(d){d.open=o;});sync();});'
                  'document.addEventListener("toggle",sync,true);sync();})();</script>')
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        + (f"<title>{_sb_esc(short)} &mdash; team analysis</title>\n" if _an["on"] else
           f"<title>{_sb_esc(_SB_UWW)} vs {_sb_esc(short)} &mdash; scouting brief</title>\n")
        + f"<style>{_SB_CSS}</style>\n"
        # (a collapsed table still prints: every <details> opens before printing and closes again after)
        + "<script>window.addEventListener('beforeprint',function(){document.querySelectorAll('details').forEach(function(d){"
          "if(!d.open){d.open=true;d.dataset.pr='1';}});});window.addEventListener('afterprint',function(){"
          "document.querySelectorAll('details[data-pr]').forEach(function(d){d.open=false;delete d.dataset.pr;});});</script>"
        + f"\n</head>\n<body>\n<div class=\"page\">\n{body}\n</div>\n</body>\n</html>\n"
    )


# --- Run it ------------------------------------------------------------------------------------------------
_sb_data = _SbData(APP_DATA_DIR)
_sb_game, _sb_scheduled_name, _sb_short = _sb_resolve_matchup(_sb_data)

# Prefer the name this notebook already resolved (see the "Identify the upcoming opponent" cell, including
# its no-scout-report fallback) over the one derived from the CSVs -- one source of truth for who we are
# playing, rather than two that agree right up until they don't.
_sb_notebook_short = globals().get("upcoming_opponent_short")
if _sb_notebook_short:
    _sb_short = _sb_notebook_short

if _sb_game is None:
    print("No upcoming game found in uww_schedule.csv -- no brief written. Check that the CSV export cell "
          "ran, and that reference_date falls on or before the next game you want a brief for.")
else:
    # CONFIRMED CHANGE (requested): a scrimmage played between seasons (MSOE, Nov 2026) is scouted off the
    # previous season's numbers, so that season's seniors -- both teams -- are struck through in the brief.
    _sb_strike = strike_seniors_plan(_sb_game, _sb_data("uww_live_rosters"), _SB_UWW, _sb_scheduled_name,
                                     globals().get("STRIKE_LAST_SEASON_SENIORS", "auto"),
                                     globals().get("STRIKE_SENIORS_KEEP") or ())
    _SB_STRUCK = {re.sub(r"\s+", " ", str(n)).strip().lower() for n in (_sb_strike["seniors"] if _sb_strike else [])}
    _sb_document = _sb_build_html(_sb_data, _sb_game, _sb_scheduled_name, _sb_short)
    if _sb_strike:
        _sb_document = _SeniorStrike(_sb_strike["seniors"], _sb_strike["others"],
                                     _sb_strike["lookalikes"]).html(_sb_document)
        _sb_tc = lambda n: " ".join(w[:1].upper() + w[1:].lower() for w in str(n).split()) if str(n) == str(n).upper() else str(n)
        _sb_who = "; ".join(f"{_sb_esc(t)}: " + ", ".join(f"<s>{_sb_esc(_sb_tc(n))}</s>" for n in v)
                            for t, v in _sb_strike["teams"].items())
        # (requested: no "struck through" note at the top -- the SEASON OPENER / PRESEASON box says it)
        print(f"Struck through {len(_sb_strike['seniors'])} {_sb_strike['season']} senior(s) -- this game is after "
              "that season: " + "; ".join(f"{t}: {', '.join(_sb_tc(n) for n in v)}" for t, v in _sb_strike["teams"].items())
              + ". (STRIKE_LAST_SEASON_SENIORS / STRIKE_SENIORS_KEEP in the notebook cell.)")
    if _sb_data.sample_dropped:
        print("Sample data left out of the brief (still in the app): " + ", ".join(sorted(set(_sb_data.sample_dropped))))
    # (no-seniors brief) the roster is drawn twice when seniors are struck -- each copy keeps its own
    _sb_doc_all = _sb_document
    _sb_ns_pick = lambda doc, drop: re.sub(r"<!--NS:(?:strike|remove)-->|<!--/NS-->", "",  # noqa: E731
                                          re.sub(rf"<!--NS:{drop}-->.*?<!--/NS-->", "", doc, flags=re.S))
    _sb_document = _sb_ns_pick(_sb_doc_all, "remove")
    os.makedirs(_SB_OUT_DIR, exist_ok=True)
    _sb_slug = re.sub(r"[^\w]+", "_", str(_sb_short)).strip("_") or "opponent"
    _sb_path = os.path.join(_SB_OUT_DIR, f"scouting_brief_{_sb_slug}.html")
    with open(_sb_path, "w", encoding="utf-8") as _sb_f:
        _sb_f.write(_sb_document)
    print(f"Wrote {os.path.abspath(_sb_path)} ({len(_sb_document):,} bytes) -- open it in a browser, or "
          f"attach it to an email as-is.")
    # CONFIRMED CHANGE (requested: "for scrimmages and season opener briefs ... 2 different copies": one exactly as before,
    # last season's seniors struck through; one with anything about them removed). The second copy is the first with every
    # struck row / item / sentence taken out: scouting_brief_<team>_no_seniors.html. Any other brief has no second copy
    # (an old one is deleted so it can't be mistaken for this game's).
    _sb_path2 = os.path.join(_SB_OUT_DIR, f"scouting_brief_{_sb_slug}_no_seniors.html")
    if _sb_strike:
        _sb_doc2 = _sb_drop_struck(_sb_ns_pick(_sb_doc_all, "strike"))
        with open(_sb_path2, "w", encoding="utf-8") as _sb_f:
            _sb_f.write(_sb_doc2)
        print(f"Wrote {os.path.abspath(_sb_path2)} ({len(_sb_doc2):,} bytes) -- the same brief with last season's seniors "
              f"left out ({_sb_document.count('<s>') - _sb_doc2.count('<s>')} struck item(s) removed).")
    elif os.path.exists(_sb_path2):
        try:
            os.remove(_sb_path2)
        except OSError:
            pass
    # The Notes page moved out of the brief and into the app (requested), so the app needs the text. Note
    # numbers are the deep-link target the brief's ⓘ markers point at, so they're stored explicitly rather
    # than left to row order.
    _sb_notes_df = pd.DataFrame({"note": range(1, len(_sb_notes_report) + 1),
                                 "opponent": str(_sb_short),
                                 "text": _sb_notes_report})
    _sb_notes_df.to_csv(os.path.join(APP_DATA_DIR, "uww_brief_notes.csv"), index=False)
    print(f"  {len(_sb_notes_df)} methodology note(s) -> uww_brief_notes.csv (the brief links to these "
          f"instead of printing them).")
    if not str(globals().get("APP_BASE_URL") or os.environ.get("UWW_APP_URL") or "").strip():
        print("  NOTE: APP_BASE_URL is blank, so the brief's \u24d8 markers and the Methodology links are "
              "omitted entirely -- with the notes no longer printed in the brief, there is currently no "
              "way for a reader to reach them. Set APP_BASE_URL in the config cell.")
    for _side, (_hit, _miss) in _sb_photo_report.items():
        if _hit or _miss:
            print(f"  {_side} headshots: {_hit} found, {len(_miss)} missing"
                  + (f" -- {', '.join(_miss[:6])}{' ...' if len(_miss) > 6 else ''}" if _miss else "")
                  + ("" if _hit else " (no live roster scrape for this team yet, and no files in "
                                    "data/player_images -- see the Roster pages cell)"))
    if _sb_data.missing:
        print("  Tables that were empty or missing (their sections were left out of the brief): "
              + ", ".join(sorted(set(_sb_data.missing))))

# CONFIRMED CHANGE (requested 11/14: "Brief check after every run"). Reads the finished brief file(s) written above
# against the data folder and prints what looks wrong -- see parser_lib/87b_brief_check.py. It changes nothing in the brief.
run_section("87b_brief_check")
