# 79_head_to_head.py -- code for the notebook section "Head-to-head: every previous meeting with the upcoming opponent, this season and earlier -"
# Runs inside the notebook via run_section("79_head_to_head"); its settings are in that notebook cell.

# --- Head-to-head: every previous meeting with the upcoming opponent, this season and earlier ---------------
# CONFIRMED CHANGE (requested): opponents recur -- conference teams twice a season, and most of them again the
# following year -- so the brief opens with how the last meeting(s) actually went. Three sources, in this order:
#   1. THIS season's schedule (uww_schedule, already parsed above): any earlier meeting that has been played.
#   2. Local schedule snapshots for OTHER seasons. Schedule captures are already saved per season (see
#      _add_season_suffix_to_path -- "UW-Whitewater - Schedule_2024.html"), so a previous year's file that is
#      already on disk is read straight off it, with no scraping at all.
#   3. A live scrape of previous seasons, only for the seasons with no local file. FastScout's own team URL
#      takes a season code (FASTSCOUT_DOCS_SEASON is "25" for 2025-26), so "24" is 2024-25; the scraped HTML is
#      saved season-suffixed, which means this is a once-per-season cost, not a once-per-run one.
# Every meeting found is exported to uww_head_to_head.csv for the brief and the app to render.
_H2H_UWW = "UW-Whitewater"
_H2H_SEASONS_BACK = 2          # how many earlier seasons to look for (2024-25 and 2023-24 when it's 2025-26)
_h2h_problems = []


def _h2h_schedule_from_html(html, source_label):
    """Every game on one of UWW's own schedule pages, unfiltered.

    build_team_schedule_from_html() above deliberately narrows UWW's own schedule to scouted opponents plus the
    upcoming game -- right for the scouting pipeline, wrong here, where the point is to find a meeting that was
    never scouted (a previous season's game, or an early-season one before scouting started). This repeats only
    the parsing half of that function, reusing its own helpers (split_opponent, split_result,
    extract_season_start_year, parse_schedule_date), and skips the filtering half."""
    page_soup = BeautifulSoup(html, "lxml")
    tables = page_soup.find_all("table")
    if not tables:
        raise ValueError(f"{source_label}: no schedule table on the page")
    raw = pd.read_html(StringIO(str(tables[0])))[0]
    # The box-score link per row -- the entry point scrape_pbp_live() needs to pull a previous meeting's
    # full play-by-play (see the pbp cell). Same extraction build_team_schedule_from_html does.
    game_urls = []
    for row_el in [r for r in tables[0].find_all("tr") if r.find_all("td")]:
        hrefs = [a["href"] for a in row_el.find_all("a", href=True)]
        box = [h for h in hrefs if "/teams/" in h and "/boxscore" in h]
        game_urls.append(_resolve_team_link(box[0]) if box else None)
    raw["game_url"] = game_urls[:len(raw)] + [None] * max(0, len(raw) - len(game_urls))
    team_name_raw = page_soup.find("h1").get_text(strip=True)
    team_name = re.match(r"^([^\d]+)", team_name_raw).group(1).strip()
    out = pd.DataFrame()
    out["date"] = raw["Date"]
    out["opponent"] = raw["Opponent"].apply(lambda v: split_opponent(v)[0])
    out["team"] = team_name
    out["location"] = raw["Location"]
    res = raw["Result"].apply(split_result)
    out["outcome"] = res.apply(lambda x: x[0])
    out["team_score"] = res.apply(lambda x: x[1])
    out["opponent_score"] = res.apply(lambda x: x[2])
    out["game_url"] = raw["game_url"]
    year = extract_season_start_year(page_soup, fallback=_DEFAULT_SEASON_START_YEAR)
    out["season"] = f"{year}-{str(year + 1)[-2:]}"
    out["season_start_year"] = year
    out["_parsed_date"] = out["date"].apply(lambda d: parse_schedule_date(d, year))
    return out[out["outcome"].astype(str).str.upper().isin(["W", "L"])]


def _h2h_same_team(a, b):
    """Do two schedule spellings mean the same program? Mascots and abbreviations drift between seasons
    ("Aurora Spartans" vs "Aurora University" vs "Aurora"), so this compares the distinctive words rather than
    the whole string."""
    # CONFIRMED BUG (fixed here): matching on ANY shared word paired "Eureka Red Devils" with "Ripon Red
    # Hawks" -- both are "Red" -- and would have put another team's game in the head-to-head table. Mascot and
    # colour words are ignored, so only the school's own name can make a match.
    _MASCOT = {"red", "blue", "green", "black", "white", "gold", "golden", "purple", "crimson", "scarlet",
               "fighting", "flying", "big", "little", "hawks", "devils", "eagles", "spartans", "warriors",
               "warhawks", "tigers", "lions", "bears", "wolves", "panthers", "cardinals", "knights", "titans",
               "pioneers", "raiders", "falcons", "vikings", "bulldogs", "wildcats", "cougars", "yellowjackets",
               "blugolds", "pointers", "gusties", "celts", "foresters"}
    stop = {"university", "college", "the", "of", "state", "saint", "st"} | _MASCOT
    words = lambda t: {w for w in re.findall(r"[a-z]+", str(t).lower()) if len(w) > 2 and w not in stop}  # noqa: E731
    wa, wb = words(a), words(b)
    return bool(wa & wb) if wa and wb else False


def _h2h_local_schedule_files():
    """UWW's own schedule snapshots on disk, newest season first, one file per season."""
    hits = {}
    for path in sorted(glob.glob(f"{schedules_dir}/*.html") + glob.glob(f"{schedules_dir}/*.mhtml")):
        base = os.path.basename(path)
        if "schedule" not in base.lower() or "whitewater" not in base.lower():
            continue
        year = re.search(r"_(\d{4})\.[^.]+$", base)
        hits[int(year.group(1)) if year else _DEFAULT_SEASON_START_YEAR] = path
    return hits


def _h2h_scrape_season(page, season_code, year, timeout_ms=30000):
    """One earlier season's schedule, via FastScout's own season parameter on the team URL."""
    url = f"{FASTSCOUT_ORIGIN}/teams/myTeam?league={FASTSCOUT_DOCS_LEAGUE}&season={season_code}"
    print(f"    [scrape] {year}-{str(year + 1)[-2:]} schedule: {url}")
    _goto_with_auth_retry(page, url, "text=SCHEDULE", timeout_ms)
    _click_tab_by_text(page, "SCHEDULE", timeout_ms)
    page.wait_for_selector("#myTeamSchedule", timeout=timeout_ms)
    page.wait_for_selector("#myTeamSchedule tr", timeout=timeout_ms)
    html = page.content()
    _save_scraped_html(html, os.path.join(schedules_dir, f"UW-Whitewater - Schedule_{year}.html"),
                       f"UW-Whitewater's {year}-{str(year + 1)[-2:]} schedule")
    return html


_h2h_rows = []
_h2h_current_year = None
try:
    _h2h_current_year = int(str(uww_team_schedule["season"].dropna().iloc[0]).split("-")[0])
except Exception:
    _h2h_current_year = _DEFAULT_SEASON_START_YEAR

# ---- 1. this season's earlier meetings ---------------------------------------------------------------
if upcoming_opponent_short and not uww_team_schedule.empty:
    _played = uww_team_schedule[uww_team_schedule["outcome"].astype(str).str.upper().isin(["W", "L"])]
    for _, g in _played.iterrows():
        if _h2h_same_team(g.get("opponent"), upcoming_opponent_short):
            _h2h_rows.append({"season": g.get("season") or f"{_h2h_current_year}-{str(_h2h_current_year + 1)[-2:]}",
                              "date": g.get("date"), "location": g.get("location"), "outcome": g.get("outcome"),
                              "team_score": g.get("team_score"), "opponent_score": g.get("opponent_score"),
                              "opponent_as_listed": g.get("opponent"), "game_url": g.get("game_url"),
                              "source": "this season's schedule"})

# ---- 2 and 3. earlier seasons: local files first, scrape only what's missing -------------------------
_h2h_local = _h2h_local_schedule_files()
_h2h_want = [_h2h_current_year - n for n in range(1, _H2H_SEASONS_BACK + 1)]
_h2h_html_by_year = {y: _h2h_local[y] for y in _h2h_want if y in _h2h_local}
_h2h_missing = [y for y in _h2h_want if y not in _h2h_html_by_year]

if _h2h_missing and fastscout_username and fastscout_password:
    def _run_h2h_scrape(login_page):
        found = {}
        for _y in _h2h_missing:
            _code = str(int(FASTSCOUT_DOCS_SEASON) - (_h2h_current_year - _y))
            try:
                found[_y] = _h2h_scrape_season(login_page, _code, _y)
            except Exception as e:
                _h2h_problems.append(f"{_y}-{str(_y + 1)[-2:]} schedule: {type(e).__name__}: {e}")
        return found

    try:
        for _y, _html in run_in_fastscout_session(_run_h2h_scrape).items():
            _h2h_html_by_year[_y] = _html
    except Exception as _e:
        _h2h_problems.append(f"could not open a FastScout session for earlier seasons: {type(_e).__name__}: {_e}")
elif _h2h_missing:
    _h2h_problems.append(f"no local schedule file for {_h2h_missing} and no FastScout credentials -- earlier "
                         f"seasons skipped.")

for _y, _src in sorted(_h2h_html_by_year.items(), reverse=True):
    try:
        _html = load_html_snapshot(_src) if isinstance(_src, str) and os.path.exists(str(_src)) else _src
        _sched = _h2h_schedule_from_html(_html, f"{_y}-{str(_y + 1)[-2:]} schedule")
    except Exception as e:
        _h2h_problems.append(f"{_y}-{str(_y + 1)[-2:]} schedule could not be parsed: {type(e).__name__}: {e}")
        continue
    for _, g in _sched.iterrows():
        if _h2h_same_team(g.get("opponent"), upcoming_opponent_short):
            _h2h_rows.append({"season": g.get("season"), "date": g.get("date"), "location": g.get("location"),
                              "outcome": g.get("outcome"), "team_score": g.get("team_score"),
                              "opponent_score": g.get("opponent_score"),
                              "opponent_as_listed": g.get("opponent"), "game_url": g.get("game_url"),
                              "source": f"{_y}-{str(_y + 1)[-2:]} schedule"})

head_to_head = pd.DataFrame(_h2h_rows, columns=["season", "date", "location", "outcome", "team_score",
                                                "opponent_score", "opponent_as_listed", "game_url", "source"])
if not head_to_head.empty:
    head_to_head = head_to_head.drop_duplicates(subset=["season", "date"])
    head_to_head["team_score"] = pd.to_numeric(head_to_head["team_score"], errors="coerce")
    head_to_head["opponent_score"] = pd.to_numeric(head_to_head["opponent_score"], errors="coerce")
    head_to_head["margin"] = head_to_head["team_score"] - head_to_head["opponent_score"]
    head_to_head["home_away"] = head_to_head["location"].astype(str).str.strip().str.lower().map(
        {"home": "Home", "away": "Away", "neutral": "Neutral"}).fillna(head_to_head["location"])

    # A real calendar date for each meeting. "date" is the schedule's display string ("Wed, Nov 20") with no
    # year, so nothing could be JOINED to it -- in particular the tagged play calls, which the brief now reads
    # per meeting (what we ran, what defense, did it work). Resolved once here with the season's start year.
    def _h2h_iso(row):
        try:
            _p = parse_schedule_date(row["date"], int(str(row["season"]).split("-")[0]))
        except Exception:
            return None
        _p = pd.Timestamp(_p) if _p is not None else None
        return None if _p is None or pd.isna(_p) else _p.strftime("%Y-%m-%d")
    head_to_head["game_date"] = head_to_head.apply(_h2h_iso, axis=1)

    # Who led each side in a meeting we have a box score for. Only games this pipeline parsed play-by-play
    # for will have one -- a previous season's game usually won't, and that column is simply left blank
    # rather than filled with something from the wrong game.
    # CONFIRMED BUG (fixed here): this referenced pbp_box_score directly and raised NameError -- the cell had
    # been placed right after the upcoming opponent is identified, which is long before any box score is built.
    # The cell now sits after the box-score cells (see the notebook order), and this reads the table through
    # globals() anyway, so running it early degrades to "no leading scorers" instead of crashing the run.
    _h2h_box = globals().get("pbp_box_score")
    if _h2h_box is None:
        _h2h_box = pd.DataFrame()

    def _h2h_leaders(row):
        if _h2h_box.empty or "game_date" not in _h2h_box.columns:
            return pd.Series({"uww_leader": None, "opp_leader": None})
        # CONFIRMED BUG (fixed here): this called .date() on parse_schedule_date()'s return value, which is a
        # datetime.date already (not a datetime), so it raised AttributeError. Normalised through
        # pd.Timestamp so either kind of return value compares correctly.
        parsed = parse_schedule_date(row["date"], int(str(row["season"]).split("-")[0]))
        parsed = pd.Timestamp(parsed) if parsed is not None else None
        if parsed is None or pd.isna(parsed):
            return pd.Series({"uww_leader": None, "opp_leader": None})
        game = _h2h_box[pd.to_datetime(_h2h_box["game_date"], errors="coerce").dt.date == parsed.date()]
        game = game[game["player"].astype(str) != "TEAM"]
        if game.empty:
            return pd.Series({"uww_leader": None, "opp_leader": None})
        out = {}
        for key, mask in (("uww_leader", game["team"].astype(str).str.contains("Whitewater", case=False, na=False)),
                          ("opp_leader", ~game["team"].astype(str).str.contains("Whitewater", case=False, na=False))):
            side = game[mask]
            if side.empty:
                out[key] = None
                continue
            top = side.loc[pd.to_numeric(side["PTS"], errors="coerce").idxmax()]
            out[key] = f"{top['player']} {int(pd.to_numeric(top['PTS'], errors='coerce'))}"
        return pd.Series(out)

    head_to_head = pd.concat([head_to_head, head_to_head.apply(_h2h_leaders, axis=1)], axis=1)
    head_to_head = head_to_head.sort_values(["season", "date"], ascending=[False, False]).reset_index(drop=True)

head_to_head.to_csv(os.path.join(APP_DATA_DIR, "uww_head_to_head.csv"), index=False)

# ==========================================================================================================
# The previous meeting in full, plus how that opponent's roster has changed since (requested)
# ==========================================================================================================
# Each meeting's own play-by-play is pulled from its box-score link the same way every other game in this
# notebook is (scrape_pbp_live -> build_pbp_events -> box_score_from_pbp_events), cached to disk so a season
# is scraped once. Whatever can't be fetched degrades to the scoreline already shown above.
_h2h_box_rows = []
_h2h_meetings_parsed = []
if not head_to_head.empty:
    _h2h_want_pbp = head_to_head[head_to_head["game_url"].notna()]

    def _h2h_pbp_path(row):
        _safe = re.sub(r"[^\w]+", "_", f"{row['season']} {row['date']}").strip("_")
        return os.path.join(schedules_dir, f"{upcoming_opponent_short} - PBP {_safe}.html")

    def _h2h_parse_meeting(row, html_or_raw):
        """One meeting -> player box-score lines for both sides."""
        raw = parse_pbp_html(html_or_raw) if isinstance(html_or_raw, str) else html_or_raw
        _date = pd.Timestamp(parse_schedule_date(row["date"], int(str(row["season"]).split("-")[0])))
        events = build_pbp_events(raw, row["opponent_as_listed"], _date.date(), self_team=_H2H_UWW)
        box = box_score_from_pbp_events(events, label=f"{row['season']} meeting", verbose=False)
        if box.empty:
            return []
        box = box[box["player"].astype(str) != "TEAM"].copy()
        box["season"] = row["season"]
        box["meeting_date"] = row["date"]
        return box.to_dict("records")

    _h2h_need_scrape = []
    for _, _row in _h2h_want_pbp.iterrows():
        _path = _h2h_pbp_path(_row)
        if os.path.exists(_path):
            try:
                _h2h_box_rows += _h2h_parse_meeting(_row, load_html_snapshot(_path))
                _h2h_meetings_parsed.append(f"{_row['season']} {_row['date']} (cached)")
            except Exception as e:
                _h2h_problems.append(f"{_row['season']} {_row['date']} play-by-play could not be parsed: "
                                     f"{type(e).__name__}: {e}")
        else:
            _h2h_need_scrape.append(_row)

    if _h2h_need_scrape and fastscout_username and fastscout_password:
        def _run_h2h_pbp(login_page):
            got = {}
            for _row in _h2h_need_scrape:
                try:
                    got[(_row["season"], _row["date"])] = scrape_pbp_live(
                        login_page, _row["game_url"], save_path=_h2h_pbp_path(_row))
                except Exception as e:
                    _h2h_problems.append(f"{_row['season']} {_row['date']} play-by-play: {type(e).__name__}: {e}")
            return got

        try:
            for _key, _raw in run_in_fastscout_session(_run_h2h_pbp).items():
                _match = [r for _, r in _h2h_want_pbp.iterrows() if (r["season"], r["date"]) == _key]
                if _match:
                    try:
                        _h2h_box_rows += _h2h_parse_meeting(_match[0], _raw)
                        _h2h_meetings_parsed.append(f"{_key[0]} {_key[1]} (scraped)")
                    except Exception as e:
                        _h2h_problems.append(f"{_key[0]} {_key[1]}: {type(e).__name__}: {e}")
        except Exception as e:
            _h2h_problems.append(f"could not open a FastScout session for meeting play-by-play: "
                                 f"{type(e).__name__}: {e}")
    elif _h2h_need_scrape:
        _h2h_problems.append(f"{len(_h2h_need_scrape)} meeting(s) have no cached play-by-play and no FastScout "
                             f"credentials -- the brief shows their scoreline only.")

head_to_head_box = pd.DataFrame(_h2h_box_rows)


def _h2h_norm_name(n):
    return re.sub(r"\s+", " ", str(n)).strip().lower()


def _h2h_known_uww_names():
    """Every UWW player we know: this season's stats, the roster page, UWW's play-by-play."""
    known = {_h2h_norm_name(n) for n in (globals().get("uww_roster_names") or set())}
    lr = globals().get("live_rosters")
    if isinstance(lr, pd.DataFrame) and not lr.empty and {"team", "name"} <= set(lr.columns):
        known |= {_h2h_norm_name(n) for n in lr[lr["team"].astype(str).str.contains("whitewater", case=False, na=False)]["name"]}
    pe = globals().get("pbp_events")
    if isinstance(pe, pd.DataFrame) and not pe.empty and {"team", "player"} <= set(pe.columns):
        known |= {_h2h_norm_name(n) for n in pe[pe["team"].astype(str).str.contains("whitewater", case=False, na=False)]["player"].dropna()}
    return known - {"team", ""}


# CONFIRMED BUG (fixed; coach's brief showed "UW-Stevens Point: Luke Bara 15, Collin Madson 12..." and "UW-Whitewater:
# Josiah Butler 20, Seth Miron 20..." -- the two teams' labels swapped -- and "How this team is different now" counting
# OUR players as their "Gone"). A meeting's play-by-play doesn't reliably say which side is which. For each meeting the
# group of players that overlaps our known players IS UWW; if it carries the opponent's label, the labels are swapped back.
_h2h_swapped = 0
if not head_to_head_box.empty and {"team", "player", "meeting_date"} <= set(head_to_head_box.columns):
    _known_uww = _h2h_known_uww_names()
    for _md, _grp in head_to_head_box.groupby("meeting_date"):
        _labels = list(_grp["team"].astype(str).unique())
        if len(_labels) != 2 or not _known_uww:
            continue
        _hits = {lab: int(_grp[_grp["team"].astype(str) == lab]["player"].map(_h2h_norm_name).isin(_known_uww).sum())
                 for lab in _labels}
        _uww_by_name = [lab for lab in _labels if _h2h_same_team(lab, _H2H_UWW)]
        _uww_by_players = max(_labels, key=lambda lab: _hits[lab])
        if _hits[_uww_by_players] > 0 and _hits[_uww_by_players] > min(_hits.values()) \
                and _uww_by_name and _uww_by_name[0] != _uww_by_players:
            _other = [lab for lab in _labels if lab != _uww_by_players][0]
            _idx = _grp.index
            head_to_head_box.loc[_idx, "team"] = _grp["team"].astype(str).map(
                {_uww_by_players: _uww_by_name[0], _other: _uww_by_players})
            _h2h_swapped += 1
    if _h2h_swapped:
        print(f"  Meeting box scores: team labels were swapped in {_h2h_swapped} meeting(s) -- fixed (the side whose "
              f"players are ours is UWW).")
head_to_head_box.to_csv(os.path.join(APP_DATA_DIR, "uww_head_to_head_box.csv"), index=False)

# ---- how their roster has changed since that meeting -------------------------------------------------
# Who played in the previous meeting, and whether they are still on this year's team: returning players are
# matched against this season's roster and box score, so "returning" means genuinely available now, not just
# listed. Production is stated in that game's own terms (what they did TO US), which is the number a coach
# actually wants -- "their leading scorer against us last year is gone" is the useful sentence.
_h2h_change_rows = []
if not head_to_head_box.empty and upcoming_opponent_short:
    _prev = head_to_head_box[head_to_head_box["team"].astype(str).apply(
        lambda t: _h2h_same_team(t, upcoming_opponent_short))]
    # This year's squad: the live roster page and this season's box scores, keyed by a normalised name so a
    # spelling difference between the two sources doesn't read as a different player.
    _cur_by_key = {}
    for _src in (globals().get("live_rosters"), globals().get("pbp_box_score_upcoming")):
        if _src is None or getattr(_src, "empty", True):
            continue
        _col = "name" if "name" in _src.columns else "player"
        _rows = _src
        if "team" in _src.columns:
            _rows = _src[_src["team"].astype(str).apply(lambda t: _h2h_same_team(t, upcoming_opponent_short))]
        for _n in _rows[_col].dropna():
            if str(_n).strip().upper() == "TEAM":
                continue
            _cur_by_key.setdefault(re.sub(r"\s+", " ", str(_n)).strip().lower(), str(_n).strip())
    _cur_names = set(_cur_by_key)

    _prev_totals = (_prev.groupby("player")[["PTS", "REB", "AST"]].sum().reset_index()
                    if not _prev.empty else pd.DataFrame())
    for _, r in _prev_totals.sort_values("PTS", ascending=False).iterrows():
        _key = re.sub(r"\s+", " ", str(r["player"])).strip().lower()
        _h2h_change_rows.append({"opponent": upcoming_opponent_short, "player": r["player"],
                                 "status": "Returning" if _key in _cur_names else "Gone",
                                 "prev_pts": r["PTS"], "prev_reb": r["REB"], "prev_ast": r["AST"]})
    _played_then = {re.sub(r"\s+", " ", str(p)).strip().lower() for p in _prev_totals.get("player", [])}
    for _name in sorted(_cur_names - _played_then):
        _h2h_change_rows.append({"opponent": upcoming_opponent_short, "player": _cur_by_key.get(_name, _name.title()),
                                 "status": "New since then",
                                 "prev_pts": None, "prev_reb": None, "prev_ast": None})

head_to_head_roster_change = pd.DataFrame(_h2h_change_rows,
                                          columns=["opponent", "player", "status", "prev_pts", "prev_reb", "prev_ast"])
head_to_head_roster_change.to_csv(os.path.join(APP_DATA_DIR, "uww_head_to_head_roster_change.csv"), index=False)

# ---- Do these games matter? (requested: "help coaches know if the previous games against the upcoming opponent
# matter") -- how long ago, and how much of EACH team's scoring in those games is still on its roster. Computed here,
# shown by the brief (and app) from uww_head_to_head_continuity.csv.
def _h2h_season_start(s_):
    m = re.match(r"\s*(\d{4})", str(s_ or ""))
    return int(m.group(1)) if m else None


_h2h_cont_rows = []
if not head_to_head_box.empty and upcoming_opponent_short and "season" in head_to_head_box.columns:
    _ref = pd.Timestamp(globals().get("reference_date") or pd.Timestamp.now())
    _cur_start = _ref.year if _ref.month >= 8 else _ref.year - 1
    _box_seasons = sorted({x for x in head_to_head_box["season"].map(_h2h_season_start) if x}, reverse=True)
    if _box_seasons:
        _scope_start = _box_seasons[0]
        _scope = head_to_head_box[head_to_head_box["season"].map(_h2h_season_start) == _scope_start]
        _seasons_ago = _cur_start - _scope_start
        _last_date = str(_scope["meeting_date"].iloc[0]) if "meeting_date" in _scope.columns else ""
        # who is on each roster NOW
        _known_uww_now = _h2h_known_uww_names()
        _them_now = set(globals().get("_cur_names") or set())

        def _side_share(rows, now):
            tot = rows.groupby("player")["PTS"].sum()
            back = tot[[(_h2h_norm_name(p) in now) for p in tot.index]]
            return len(tot), len(back), float(tot.sum()), float(back.sum())

        _sides = {"Opponent": (_scope[_scope["team"].astype(str).apply(lambda t: _h2h_same_team(t, upcoming_opponent_short))], _them_now),
                  "UWW": (_scope[_scope["team"].astype(str).apply(lambda t: _h2h_same_team(t, _H2H_UWW))], _known_uww_now)}
        _pct = {}
        for _sd, (_rows, _now) in _sides.items():
            if _rows.empty or not _now:
                continue
            _n, _nb, _p, _pb = _side_share(_rows, _now)
            _pct[_sd] = 100 * _pb / _p if _p else None
            _h2h_cont_rows.append({"opponent": upcoming_opponent_short, "side": _sd, "season": _scope["season"].iloc[0],
                                   "last_meeting": _last_date, "seasons_ago": _seasons_ago, "players_then": _n,
                                   "players_back": _nb, "points_then": round(_p), "points_back": round(_pb),
                                   "pct_points_back": round(_pct[_sd]) if _pct[_sd] is not None else None})
        _t, _u = _pct.get("Opponent"), _pct.get("UWW")
        _both = [x for x in (_t, _u) if x is not None]
        if _seasons_ago <= 0:
            _lvl = "Yes" if (_t is None or _t >= 50) else "Partly"
        elif _seasons_ago == 1:
            _lvl = ("Yes" if _both and min(_both) >= 60 else
                    "Partly" if (_both and min(_both) >= 40) or (_both and max(_both) >= 60) else "Mostly no")
        else:
            _lvl = "Partly" if _both and len(_both) == 2 and min(_both) >= 60 else "Mostly no"
        _when = ("this season" if _seasons_ago <= 0 else "last season" if _seasons_ago == 1
                 else f"{_seasons_ago} seasons ago")
        _headline = {"Yes": "Yes -- mostly the same teams", "Partly": "Partly -- useful for the players still there",
                     "Mostly no": "Mostly no -- different teams now"}[_lvl]
        _why = (f"Last met {_last_date} ({_when})."
                + (f" {_t:.0f}% of their points against us came from players still on their roster" if _t is not None else "")
                + (f", and {_u:.0f}% of ours from players still on ours." if _u is not None else "."))
        _use = {"Yes": "Their tendencies and our matchups from those games still apply.",
                "Partly": "Lean on what the returning players did; treat the results as background.",
                "Mostly no": "Use the returning players' history only -- the results don't tell us much."}[_lvl]
        for _r in _h2h_cont_rows:
            _r.update(verdict=_lvl, verdict_headline=_headline, verdict_why=_why, verdict_use=_use)
        print(f"  Do the previous meetings matter? {_headline}. {_why}")

head_to_head_continuity = pd.DataFrame(_h2h_cont_rows)
head_to_head_continuity.to_csv(os.path.join(APP_DATA_DIR, "uww_head_to_head_continuity.csv"), index=False)
if _h2h_meetings_parsed:
    print(f"  Meeting play-by-play parsed: {', '.join(_h2h_meetings_parsed)}.")
    if not head_to_head_roster_change.empty:
        _ret = head_to_head_roster_change[head_to_head_roster_change["status"] == "Returning"]
        _gone = head_to_head_roster_change[head_to_head_roster_change["status"] == "Gone"]
        print(f"  Roster continuity: {len(_ret)} of {len(_ret) + len(_gone)} players who faced us are back; "
              f"{_gone['prev_pts'].sum():.0f} of their points against us are gone.")

if head_to_head.empty:
    print(f"No previous meetings with {upcoming_opponent_short or 'the upcoming opponent'} found "
          f"(this season or the last {_H2H_SEASONS_BACK}).")
else:
    _w = int((head_to_head["outcome"].astype(str).str.upper() == "W").sum())
    print(f"Head-to-head vs {upcoming_opponent_short}: {len(head_to_head)} previous meeting(s), "
          f"{_w}-{len(head_to_head) - _w}.")
    _show(head_to_head[["season", "date", "home_away", "outcome", "team_score", "opponent_score"]])
if _h2h_problems:
    print("Head-to-head problems:")
    for _p in _h2h_problems:
        print(f"  - {_p}")
