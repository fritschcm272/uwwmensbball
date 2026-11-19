# 87b_brief_check.py -- runs at the END of section 87 (run_section("87b_brief_check") on 87's last line); it has no
# notebook cell of its own, so every job that writes a brief (parser_brief, parser_analysis) checks it.
#
# CONFIRMED CHANGE (requested 11/14: "Brief check after every run. A script that reads the finished HTML against the CSVs
# and lists mismatches, empty sections and leftovers like '<NA>%' in the log"). It reads the brief file(s) 87 just wrote --
# the finished HTML, the way a coach gets it -- and looks for:
#     leftovers        "<NA>", "nan", "NaT", "inf", an unfilled "{name}" in the text a coach reads
#     empty sections   a section heading with nothing under it
#     missing sections KEYS TO VICTORY / ROSTER not in the brief at all
#     stale tables     a table in the data folder that is for a DIFFERENT opponent than this brief (the "two tables that
#                      should mean the same thing drift apart" pattern: e.g. after a parser_models run for the next
#                      opponent, uww_player_tendencies is theirs while uww_scouting_notes is still the last opponent's)
#     keys             a key printed on the brief that is not in uww_ktv_keys.csv; no keys at all
#     roster           the same player drawn twice; more than one "Leading scorer" / "Primary creator" / "Leads them on
#                      the glass"; a struck-through name left in the no-seniors copy
#     numbers          a percentage over 100 or under 0; "0 of 0"
#     links / photos   an empty or "None" link, an image with no source
# It CHANGES NOTHING in the brief. Problems print with "!!" (so the job's "done 87_..." line shows them) and everything
# goes to uww_brief_check.csv (opponent, file, severity, check, detail). severity "problem" = look at it before the brief
# goes out; "note" = worth knowing.
import html as _bc_html

_BC_OUT = "uww_brief_check"
_BC_COLS = ["opponent", "file", "severity", "check", "detail"]
BRIEF_CHECK_MIN_BYTES = 50_000      # a brief smaller than this did not build properly (a normal one is 400 KB+)
# single-opponent tables keyed by "opponent" (most tables with an "opponent" column hold every game's opponent and are
# not checked); every table with a "scouted_opponent" column is checked
_BC_OPP_TABLES = ("uww_ktv_keys", "uww_scouting_notes", "uww_read_conflicts", "uww_brief_notes")
_BC_LEFTOVER = re.compile(r"<NA>|\bnan\b|\bNaN\b|\bNaT\b|\binf\b|None%|\{_?[A-Za-z][\w.\[\]'\" ]*\}")
_BC_SOLE = ("Leading scorer", "Primary creator", "Leads them on the glass")


def _bc_text(fragment):
    """The text a reader sees in a piece of the brief."""
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", fragment)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", _bc_html.unescape(t)).strip()


def _bc_ctx(text, m, width=45):
    return ("..." + text[max(0, m.start() - width):m.end() + width] + "...").replace("\n", " ")


def brief_check(path, short, data_dir, analysis=False, no_seniors=False):
    """Every finding for one brief file: a list of (severity, check, detail)."""
    out = []
    add = lambda sev, chk, det: out.append((sev, chk, str(det)[:400]))      # noqa: E731
    try:
        with open(path, encoding="utf-8") as fh:
            doc = fh.read()
    except Exception as e:
        return [("problem", "file", f"could not read the brief: {e}")]
    if len(doc) < BRIEF_CHECK_MIN_BYTES:
        add("problem", "file", f"only {len(doc):,} bytes -- a full brief is 400,000+")
    body = re.sub(r'(src|href)="data:[^"]*"', r'\1="data:"', doc)            # embedded pictures are not text
    body = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", body)
    text = _bc_text(body)

    # ---- leftovers ------------------------------------------------------------------------------------------
    seen = set()
    for m in _BC_LEFTOVER.finditer(text):
        k = (m.group(0), text[max(0, m.start() - 25):m.start()])
        if k in seen:
            continue
        seen.add(k)
        if len(seen) <= 8:
            add("problem", "leftover", f'"{m.group(0)}" in: {_bc_ctx(text, m)}')
    if len(seen) > 8:
        add("problem", "leftover", f"{len(seen) - 8} more leftover value(s) not listed")

    # ---- sections -------------------------------------------------------------------------------------------
    marks = [(m.start(), m.end(), _bc_text(m.group(1))) for m in
             re.finditer(r'<div class="sect"><div class="t">(.*?)</div></div>', body, flags=re.S)]
    stops = sorted([a for a, _b, _t in marks] + [m.start() for m in re.finditer(r'<div class="(?:divider|foot)"', body)]
                   + [len(body)])
    titles = []
    for a, b, title in marks:
        title = re.sub(r"\s*ⓘ\d*\s*$", "", title).strip()               # (the circled-i note marker)
        titles.append(title)
        nxt = next(s for s in stops if s > a)
        if len(_bc_text(body[b:nxt])) < 15:
            add("problem", "empty section", f'"{title}" has nothing under it')
    want = ("ROSTER",) if analysis else ("KEYS TO VICTORY", "ROSTER")
    for w in want:
        if not any(w in t.upper() for t in titles):
            add("problem", "missing section", f"no {w} section in the brief")
    if short and _bc_text(str(short)).split()[0].lower() not in text.lower():
        add("problem", "file", f"{short} is not named anywhere in the brief")

    # ---- stale tables ---------------------------------------------------------------------------------------
    try:
        names = sorted(f[:-4] for f in os.listdir(data_dir) if f.startswith("uww_") and f.endswith(".csv"))
    except Exception:
        names = []
    stale = {}
    for name in names:
        p = os.path.join(data_dir, name + ".csv")
        try:
            cols = list(pd.read_csv(p, nrows=0).columns)
            col = "scouted_opponent" if "scouted_opponent" in cols else ("opponent" if name in _BC_OPP_TABLES and "opponent" in cols else None)
            if not col:
                continue
            vals = {str(v).strip() for v in pd.read_csv(p, usecols=[col])[col].dropna().unique()} - {"", "nan"}
        except Exception:
            continue
        if vals and str(short).strip() not in vals:
            stale.setdefault(", ".join(sorted(vals)[:3]), []).append(name)
    for other, tabs in stale.items():                 # one line per other opponent, not one per table
        add("problem", "stale table", f"{len(tabs)} table(s) are for {other}, not {short} (last written by a run for a "
                                      f"different opponent): {', '.join(tabs)}")

    # ---- keys -----------------------------------------------------------------------------------------------
    if not analysis:
        # CONFIRMED BUG (fixed 11/14; first real run flagged "Monitor three-point shooting." and two more): the Bottom Line
        # keys (source tag "Game Plan") are written by the brief itself and are never in uww_ktv_keys.csv -- not checked.
        _not_gp = lambda blob: ('class="src"' not in blob  # noqa: E731
                                or not re.search(r'class="src"[^>]*>\s*Game Plan\s*<', blob))
        shown = [_bc_text(m.group(2)) for m in
                 re.finditer(r'<div class="ktv-sentence">((?:(?!<div\b).)*?<span>(?:<a [^>]*>)?(.*?)(?:</a>| — |</span>)'
                             r'(?:(?!<div\b).)*?)</div>', body, flags=re.S)
                 if _not_gp(m.group(1))]
        # CONFIRMED BUG (fixed 11/19): the keys became CARDS on 11/18 (lcards ktv-cards / lc-n) and this check still
        # only knew the old "ktv-sentence" markup, so the 11/18 21:05 run reported "no Keys to Victory are printed"
        # on a brief that printed ten of them -- and, worse, silently stopped checking that every printed key is in
        # uww_ktv_keys.csv. Both shapes are read now, so the membership check below runs whichever the brief used.
        if not shown:
            shown = [_bc_text(m.group(2)) for m in
                     re.finditer(r'<div class="lc-t">Key[^<]*((?:(?!<div class="lc\b").)*?)</div>'
                                 r'<div class="lc-n">(?:<a [^>]*>)?(.*?)(?:</a>)?</div>', body, flags=re.S)
                     if _not_gp(m.group(1))]
        if not shown:
            add("problem", "keys", "no Keys to Victory are printed")
        else:
            try:
                k = pd.read_csv(os.path.join(data_dir, "uww_ktv_keys.csv"))
                have = {re.sub(r"\W+", "", str(h)).lower() for h in k.get("headline", pd.Series(dtype=str)).dropna()}
            except Exception:
                have = set()
            norm = lambda s: re.sub(r"\W+", "", re.sub(r"</?s>", "", s)).lower()     # noqa: E731
            for h in shown:
                if have and not any(norm(h) == x or norm(h).startswith(x) or x.startswith(norm(h)) for x in have):
                    add("problem", "keys", f'"{h[:90]}" is on the brief but not in uww_ktv_keys.csv')

    # ---- roster ---------------------------------------------------------------------------------------------
    cards = [_bc_text(m.group(1)).rstrip("*").strip() for m in re.finditer(r'<div class="pc-nm">(.*?)</div>', body, flags=re.S)]
    dup = sorted({c for c in cards if c and cards.count(c) > 1})
    if dup:
        add("problem", "roster", "drawn more than once: " + ", ".join(dup[:8]))
    if not cards:
        add("problem", "roster", "no player cards in the brief")
    for lab in _BC_SOLE:
        n = len(re.findall(r"<li[^>]*>\s*" + re.escape(lab) + r"\b", body))
        if n > 1:
            add("problem", "roster", f'"{lab}" is on {n} players -- it can only be one')
    if no_seniors and "<s>" in body:
        add("problem", "roster", f"{body.count('<s>')} struck-through item(s) left in the no-seniors copy")
    n_none = body.count("nothing on file yet")
    if n_none:
        add("note", "roster", f'{n_none} Offense / Defense box(es) say "nothing on file yet"')

    # ---- numbers --------------------------------------------------------------------------------------------
    bad = []
    for m in re.finditer(r"(?<![\w.])(-?\d+(?:\.\d+)?)%", text):
        v = float(m.group(1))
        if v > 100 or v < 0:
            bad.append(_bc_ctx(text, m, 30))
    for b_ in bad[:5]:
        add("problem", "numbers", f"a percentage outside 0-100: {b_}")
    for m in list(re.finditer(r"\b0 of 0\b", text))[:3]:
        add("note", "numbers", f'"0 of 0" in: {_bc_ctx(text, m, 30)}')

    # ---- links and photos -----------------------------------------------------------------------------------
    n_bad = len(re.findall(r'href="(?:|None|nan|#)"', body))
    if n_bad:
        add("problem", "links", f"{n_bad} link(s) that go nowhere")
    n_img = len(re.findall(r'<img[^>]*\bsrc="(?:|None|nan)"', body))
    if n_img:
        add("note", "photos", f"{n_img} picture(s) with no source")
    return out


_bc_rows = []
try:
    _bc_files = []
    if globals().get("_sb_game") is not None and os.path.exists(str(globals().get("_sb_path") or "")):
        _bc_files.append((_sb_path, False))
        if globals().get("_sb_strike") and os.path.exists(str(globals().get("_sb_path2") or "")):
            _bc_files.append((_sb_path2, True))
    for _bc_p, _bc_ns in _bc_files:
        for _sev, _chk, _det in brief_check(_bc_p, _sb_short, APP_DATA_DIR, analysis=bool(globals().get("ANALYSIS_MODE")),
                                            no_seniors=_bc_ns):
            _bc_rows.append({"opponent": str(_sb_short), "file": os.path.basename(_bc_p), "severity": _sev,
                             "check": _chk, "detail": _det})
    brief_check_table = pd.DataFrame(_bc_rows, columns=_BC_COLS)
    brief_check_table.to_csv(os.path.join(APP_DATA_DIR, f"{_BC_OUT}.csv"), index=False)
    _bc_prob = brief_check_table[brief_check_table["severity"] == "problem"]
    if not _bc_files:
        print("Brief check: no brief was written this run -- nothing to check.")
    elif _bc_prob.empty:
        print(f"Brief check: {len(_bc_files)} file(s) read, no problems"
              + (f" ({len(brief_check_table)} note(s))" if len(brief_check_table) else "") + f" -> {_BC_OUT}.csv")
    else:
        print(f"  !! Brief check: {len(_bc_prob)} problem(s) in the finished brief -- details in {_BC_OUT}.csv and below")
    for _, _r in brief_check_table.iterrows():
        print(("  !! " if _r["severity"] == "problem" else "     note: ") + f"[{_r['check']}] {_r['detail']}"
              + (f"  ({_r['file']})" if len(_bc_files) > 1 else ""))
except Exception as _e:
    print(f"  !! Brief check could not run ({type(_e).__name__}: {_e}) -- the brief itself is not affected")
