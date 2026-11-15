# 85b_read_reconcile.py -- runs at the END of section 85 (run_section("85b_read_reconcile") on 85's last line); it has no
# notebook cell of its own, so every job that runs 85 runs this.
#
# CONFIRMED CHANGE (requested 11/14: "Contradiction pass on player lines ... a parser step that ranks sources (this-season
# film, then the coaches' report, then box-score rules) and drops or rewords the loser"). A player's roster card stacks
# lines from three places that never looked at each other:
#     film      uww_player_tendencies (47)  -- what he did on the tagged / Synergy clips
#     report    the coaches' Player Notes and Keys to Defending (source "Coach" in uww_scouting_notes)
#     numbers   the box-score reads, notes and keys written by 85 (source "Data-Driven")
# This step reads all three for each of the upcoming opponent's players and settles the places they disagree:
#     reword  a numbers line that the film contradicts (film beats the box score)
#     drop    a numbers KEY that tells the players the opposite of the coaches' key (the report beats the box score), or
#             one of two numbers lines that disagree with each other
#     flag    a line in the coaches' report that the film or the numbers contradict. The coaches' words are NEVER changed
#             or removed -- the roster card gets one "Check:" line above his reads with the numbers, and the staff decides.
# Nothing is settled on a small sample: film needs READ_FILM_MIN_POSS finished possessions, and the numbers lines only
# exist once 85's READ_MIN_GAMES / attempt floors are met.
#
# Writes uww_read_conflicts.csv (one row per change, with the ORIGINAL line, so nothing is lost and the app can show it)
# and saves uww_scouting_notes.csv again with the changed lines. The brief (87) only prints the result.

READ_FILM_MIN_POSS = int(globals().get("READ_FILM_MIN_POSS", 8) or 8)   # finished possessions on film before film overrules anything
READ_FILM_DRIVE_SHARE = 0.15       # under this share of his finishes being drives, "Driver" is not what the film shows
READ_FILM_SPOT_SHARE = 0.60        # a "driver" in the report who finishes this often on spot-ups (mostly catch-and-shoot)
READ_FILM_NO_SPOT_SHARE = 0.15     # a "shooter" in the report who spots up less than this
_RC_OUT = "uww_read_conflicts"
_RC_COLS = ["opponent", "player", "action", "line", "source", "against", "against_source", "reason", "brief_line"]
_RC_EM = "\N{EM DASH}"

_RC_SHOOTER = re.compile(r"c\s*&\s*s|catch[- ]and[- ]shoot|\bshooter\b|hunts? .{0,14}3|\b3'?s\b|\bthrees?\b|pick (and|&) pop",
                         re.I)
_RC_NONSHOOTER = re.compile(r"non[- ]?shooter|not a shooter|make him shoot|let him shoot|live with|go under|sag off|"
                            r"help off", re.I)
_RC_DRIVER = re.compile(r"\bdriver\b|slasher|downhill|attacks? the (rim|basket)|keep him in front|gets? to the rim", re.I)
_RC_INSIDE = re.compile(r"\bpost\b|\bcut|screener|\broll|putback|offensive (glass|rebound)|\bo-?reb", re.I)
_RC_FILM_KINDS = (("share_spot", "spot-ups"), ("share_post", "post-ups"), ("share_cut", "cuts"),
                  ("share_putback", "putbacks"), ("share_trans", "transition"), ("share_pr", "ball screens"),
                  ("share_iso", "isolations"))

_rc_rows = []


def _rc_split(v):
    t = "" if v is None else str(v).strip()
    return [] if t.lower() in ("", "nan", "none") else [x.strip() for x in t.split("|") if x.strip()]


def _rc_f(row, col):
    v = pd.to_numeric(pd.Series([row.get(col)]), errors="coerce").iloc[0]
    return 0.0 if pd.isna(v) else float(v)


def _rc_log(player, action, line, source, against, against_source, reason, brief_line=""):
    _rc_rows.append({"opponent": upcoming_opponent_short, "player": player, "action": action, "line": line,
                     "source": source, "against": against, "against_source": against_source, "reason": reason,
                     "brief_line": brief_line})


def _rc_film_table(short):
    """The upcoming opponent's players on film: name key -> their uww_player_tendencies row."""
    t = _pn_load("uww_player_tendencies")
    if t.empty or not {"player", "team", "possessions"} <= set(t.columns):
        return {}
    if "side" in t.columns:
        t = t[t["side"].astype(str) == "Opponent"]
    if "scouted_opponent" in t.columns:
        t = t[t["scouted_opponent"].astype(str) == str(short)]
    k = str(short).strip().lower()
    t = t[t["team"].astype(str).str.strip().str.lower().map(lambda x: bool(x) and (x in k or k in x))]
    return {_pn_key(r["player"]): r for _, r in t.iterrows()}


def _rc_film_top(f):
    """("post-ups", 0.43): what most of his finishes on film are."""
    best = max(_RC_FILM_KINDS, key=lambda kv: _rc_f(f, kv[0]))
    return best[1], _rc_f(f, best[0])


def reconcile_player_reads(notes, short):
    """Settle the disagreements on each player's lines (see the top of this file). Returns the notes table with the
    Data-Driven rows' strengths / weaknesses / keys_to_defending changed; every change is logged in _rc_rows."""
    if notes is None or notes.empty or not {"subject_type", "source", "name"} <= set(notes.columns):
        return notes
    notes = notes.copy()
    film = _rc_film_table(short)
    pl = notes[notes["subject_type"] == "player"]
    for idx, r in pl[pl["source"] == "Data-Driven"].iterrows():
        name = str(r["name"])
        S, W, K = _rc_split(r.get("strengths")), _rc_split(r.get("weaknesses")), _rc_split(r.get("keys_to_defending"))
        S0, W0, K0 = list(S), list(W), list(K)
        nt = "" if str(r.get("notes")) in ("nan", "None") else str(r.get("notes") or "")
        co = pl[(pl["source"] == "Coach") & (pl["name"].map(_pn_key) == _pn_key(name))]
        c_lines = [x for _, c in co.iterrows() for x in _rc_split(c.get("notes")) + _rc_split(c.get("keys_to_defending"))]
        c_txt = " | ".join(c_lines)
        _quote = lambda rx: next((x for x in c_lines if rx.search(x)), "")       # noqa: E731  the coaches' line it is about
        says_shoot = bool(_RC_SHOOTER.search(c_txt)) and not _RC_NONSHOOTER.search(c_txt)
        says_helpoff = bool(_RC_NONSHOOTER.search(c_txt))
        says_drive = bool(_RC_DRIVER.search(c_txt))
        f = film.get(_pn_key(name))
        n = _rc_f(f, "possessions") if f is not None else 0.0
        film_ok = f is not None and n >= READ_FILM_MIN_POSS
        drives = (_rc_f(f, "drives_left") + _rc_f(f, "drives_right")) if f is not None else 0.0

        # 1. numbers vs film: "Driver" off his rim share, when the film shows he doesn't get there on drives
        for x in list(S):
            m = re.match(r"^Driver \S+ (\d+)% of his shots at the rim(?:, (\d+)% there)?(.*)$", x)
            if m and film_ok and drives / n < READ_FILM_DRIVE_SHARE:
                kind, share = _rc_film_top(f)
                new = (f"{m.group(1)}% of his shots are at the rim" + (f" ({m.group(2)}% made)" if m.group(2) else "")
                       + f"{m.group(3)} {_RC_EM} on film {int(drives)} drive{'s' if int(drives) != 1 else ''} in "
                         f"{int(n)} finishes, mostly {kind}")
                S[S.index(x)] = new
                _rc_log(name, "reword", x, "numbers", f"{int(drives)} drive(s) in {int(n)} finishes; {round(100 * share)}% {kind}",
                        "film", "the play-by-play only says where he shot from; the film says how he got there", "")

        # 2. numbers vs numbers: FG% says one thing, true shooting (the notes) the other -- true shooting counts threes
        #    and free throws, so it wins
        for lab, opp in (("Efficient", "Inefficient:"), ("Inefficient", "Efficient:")):
            for col in (S, W):
                for x in list(col):
                    if x.startswith(lab + " ") and opp in nt:
                        col.remove(x)
                        _rc_log(name, "drop", x, "numbers", opp.rstrip(":") + " by true shooting (his notes)", "numbers",
                                "field-goal % and true shooting disagreed; true shooting counts threes and free throws", "")

        # 3. numbers vs numbers: "Top priority -- no easy catches" and "Let him be the one who shoots it" on one player
        if any(x.startswith("Top priority") for x in K):
            for x in [y for y in K if y.startswith("Let him be the one who shoots it")]:
                K.remove(x)
                _rc_log(name, "drop", x, "numbers", next(y for y in K if y.startswith("Top priority")), "numbers",
                        "two opposite instructions for the same player; their leading scorer stays the priority", "")

        # 4. the report vs the numbers on his three-point shooting
        _three = lambda col, lab: next((re.search(r"(\d+)% on (\d+)(.*)$", x) for x in col if x.startswith(lab)), None)  # noqa: E731
        cold, hot = _three(W, "Cold from three"), _three(S, "Shooter")
        if says_shoot and cold:
            _incl = " (incl. last season)" if "incl. last season" in cold.group(3) else ""
            _rc_log(name, "flag", _quote(_RC_SHOOTER), "report", f"{cold.group(1)}% on {cold.group(2)} threes{_incl}", "numbers",
                    "the report guards him as a shooter; the numbers say he has not been one",
                    f"Check: the report guards him as a shooter {_RC_EM} he is {cold.group(1)}% on {cold.group(2)} threes{_incl}")
            for x in [y for y in K if y.startswith("Live with the three")]:
                K.remove(x)
                _rc_log(name, "drop", x, "numbers", _quote(_RC_SHOOTER), "report",
                        "opposite of the coaches' key; the report beats a box-score rule", "")
        if says_helpoff and hot:
            _incl = " (incl. last season)" if "incl. last season" in hot.group(3) else ""
            _rc_log(name, "flag", _quote(_RC_NONSHOOTER), "report", f"{hot.group(1)}% on {hot.group(2)} threes{_incl}", "numbers",
                    "the report says to play off him; the numbers say he makes threes",
                    f"Check: the report plays off him {_RC_EM} he is {hot.group(1)}% on {hot.group(2)} threes{_incl}")
            for x in [y for y in K if y.startswith("Run him off the line")]:
                K.remove(x)
                _rc_log(name, "drop", x, "numbers", _quote(_RC_NONSHOOTER), "report",
                        "opposite of the coaches' key; the report beats a box-score rule", "")

        # 5. the report vs the film on HOW he scores
        if film_ok:
            spot_n, spot_cs = _rc_f(f, "spot_n"), _rc_f(f, "spot_cs")
            kind, share = _rc_film_top(f)
            if (says_drive and not _RC_SHOOTER.search(c_txt) and spot_n / n >= READ_FILM_SPOT_SHARE
                    and spot_n and spot_cs / spot_n >= 0.7 and drives / n < READ_FILM_DRIVE_SHARE):
                _rc_log(name, "flag", _quote(_RC_DRIVER), "report",
                        f"{int(spot_cs)} catch-and-shoot of {int(n)} finishes, {int(drives)} drive(s)", "film",
                        "the report calls him a driver; on film he spots up",
                        f"Check: the report calls him a driver {_RC_EM} on film {int(spot_cs)} of his {int(n)} finishes "
                        f"are catch-and-shoot, {int(drives)} drive{'s' if int(drives) != 1 else ''}")
            if (says_shoot and not _RC_DRIVER.search(c_txt) and not _RC_INSIDE.search(c_txt) and not hot
                    and _rc_f(f, "share_spot") < READ_FILM_NO_SPOT_SHARE and kind != "spot-ups"):
                _rc_log(name, "flag", _quote(_RC_SHOOTER), "report",
                        f"{int(spot_n)} spot-up(s) in {int(n)} finishes; {round(100 * share)}% {kind}", "film",
                        "the report guards him as a shooter; on film he rarely spots up",
                        f"Check: the report guards him as a shooter {_RC_EM} on film {int(spot_n)} of his {int(n)} finishes "
                        f"are spot-ups ({round(100 * share)}% {kind})")

        if (S, W, K) != (S0, W0, K0):
            notes.at[idx, "strengths"] = " | ".join(S)
            notes.at[idx, "weaknesses"] = " | ".join(W)
            notes.at[idx, "keys_to_defending"] = " | ".join(K)
    return notes


try:
    if isinstance(globals().get("scouting_notes"), pd.DataFrame) and upcoming_opponent_short:
        scouting_notes = reconcile_player_reads(scouting_notes, upcoming_opponent_short)
        scouting_notes.to_csv(os.path.join(APP_DATA_DIR, "uww_scouting_notes.csv"), index=False)
except Exception as _e:
    # a failed check must never cost the notes themselves: they stay as 85 wrote them
    _rc_rows = []
    print(f"  !! Read check stopped ({type(_e).__name__}: {_e}) -- the player lines are unchanged from section 85")

read_conflicts = pd.DataFrame(_rc_rows, columns=_RC_COLS)
read_conflicts.to_csv(os.path.join(APP_DATA_DIR, f"{_RC_OUT}.csv"), index=False)     # written even when empty: no stale rows
_rc_n = read_conflicts["action"].value_counts().to_dict() if not read_conflicts.empty else {}
print(f"Read check ({upcoming_opponent_short or 'no opponent'}): {_rc_n.get('reword', 0)} line(s) reworded, "
      f"{_rc_n.get('drop', 0)} dropped, {_rc_n.get('flag', 0)} of the report's lines flagged -> {_RC_OUT}.csv")
for _, _r in read_conflicts.iterrows():
    print(f"    {_r['action']:6s} {_r['player']}: \"{_r['line']}\" ({_r['source']}) vs {_r['against']} ({_r['against_source']})")
