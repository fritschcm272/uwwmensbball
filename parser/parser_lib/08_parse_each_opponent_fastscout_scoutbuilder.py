# 08_parse_each_opponent_fastscout_scoutbuilder.py -- code for the notebook section "FastScout "ScoutBuilder" game-plan reports, now sourced EXCLUSIVELY from PDF exports -- MH"
# Runs inside the notebook via run_section("08_parse_each_opponent_fastscout_scoutbuilder"); its settings are in that notebook cell.

# FastScout "ScoutBuilder" game-plan reports, now sourced EXCLUSIVELY from PDF exports -- MHTML is retired.
# PDF exports render everything server-side before printing, so their tables are fully populated (unlike MHTML
# "Save Page As" snapshots, whose live-data stat widgets are empty placeholders). The original ai_parse_document()
# approach fails on this classic cluster because that routine only runs on serverless AI Functions compute, so this
# cell falls back to pdfplumber and reconstructs the same element schema used downstream: section_header / text / table.
# Loop through every "*_scout.pdf" file in the inputs volume so newly added reports are picked up automatically
# without touching this code. 
try:
    import pdfplumber
except ModuleNotFoundError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pdfplumber"])
    import pdfplumber

logging.getLogger("pdfminer").setLevel(logging.ERROR)

GAME_PLAN_HEADERS = {
    "TEAM STRENGTHS", "KEYS TO VICTORY",
    "Overall Defensive Scheme", "Attacking their man defense", "Ball Screen & DHO Defense",
    "Ball Screen Actions & Reads", "Speciality Defensive Notes", "Potential Adjustments",
    "Defending Their Action", "Overall OFFENSIVE SCHEME", "Ball Screen Actions & Personnel",
    "Ball Screen Coverage(s)", "ELOB & SLOB",
}

volume_dir = INPUT_DIR
# Confirmed by the user: no PDF is ever needed -- reports auto-downloaded going forward are saved as the live
# report page's own rendered HTML ("*_scout.html", see Cell 4) instead of a Chromium-printed PDF, which never
# rendered cleanly no matter the approach tried. Manually-uploaded reports from before this change stay as
# "*_scout.pdf". Both are parsed below (by their own dedicated parser) into the identical element schema, so
# every downstream cell keeps working unchanged regardless of which format a given opponent's report is in.
# find_scout_files() (Configuration cell) applies the `before_scout` switch -- with before_scout="yes" the
# upcoming game's report is excluded here too, so no scout_reports entry is built for that opponent and
# every downstream cell behaves exactly as it does for an opponent whose report hasn't been made yet.
scout_pdf_files = find_scout_files(volume_dir, extensions=("pdf",))
scout_html_files = find_scout_files(volume_dir, extensions=("html",))
scout_report_files = sorted(scout_pdf_files + scout_html_files)
print(f"Found {len(scout_pdf_files)} PDF scout report(s) and {len(scout_html_files)} HTML scout report(s):")
for f in scout_report_files:
    print(" -", os.path.basename(f))


def normalize_text(text):
    text = text.replace("• ", "•").replace(" •", "•")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def grouped_lines(page):
    # Bucketing words by a bare round(word["top"]) is fragile: the LEFT half's baseline ("Player Notes:")
    # and the RIGHT half's baseline ("Keys to Defending:") of the SAME visual header line can land on
    # different sub-pixel tops that round to ADJACENT integers (e.g. 556 vs 557) rather than the same one.
    # When that happens, the two halves get split into two separate one-sided rows, the "Player Notes" +
    # "Keys to Defending" combined-header detection below never fires on either row, and that whole player's
    # notes/keys bullets get silently dropped (confirmed for Michael Asman and Kolby Williams on the Ripon
    # PDF's STARTERS page -- their header row split 556/557 and 684/685). Cluster words within a small
    # vertical tolerance into the same row instead of relying on exact/rounded top equality.
    split_x = page.width / 2
    words = page.extract_words()
    ordered = sorted(words, key=lambda w: (w["top"], w["x0"]))
    clusters = []
    row_top_tolerance = 2
    for word in ordered:
        if clusters and abs(word["top"] - clusters[-1]["top"]) <= row_top_tolerance:
            clusters[-1]["words"].append(word)
        else:
            clusters.append({"top": word["top"], "words": [word]})

    rows = []
    for cluster in clusters:
        line_words = sorted(cluster["words"], key=lambda w: w["x0"])
        rows.append({
            "top": cluster["top"],
            "left": normalize_text(" ".join(w["text"] for w in line_words if w["x0"] < split_x)),
            "right": normalize_text(" ".join(w["text"] for w in line_words if w["x0"] >= split_x)),
            "full": normalize_text(" ".join(w["text"] for w in line_words)),
        })
    return rows


def parse_game_plan_page(page, elements):
    segments = []
    for side_name in ["left", "right"]:
        current = None
        for row in grouped_lines(page):
            if row["top"] < 80:
                continue
            text = row[side_name]
            if not text or PAGE_NUM_RE.fullmatch(text) or text in {"STARTERS", "BENCH"}:
                continue
            header_candidate = text.rstrip(" -•")
            if header_candidate in GAME_PLAN_HEADERS:
                current = {
                    "top": row["top"],
                    "side": 0 if side_name == "left" else 1,
                    "header": header_candidate,
                    "texts": [],
                }
                segments.append(current)
            elif text.upper() == text and len(text) > 8 and not re.match(r"^\d+\.", text):
                continue
            elif current is not None:
                current["texts"].append(text)

    for segment in sorted(segments, key=lambda s: (s["top"], s["side"])):
        elements.append(("section_header", segment["header"]))
        for text in segment["texts"]:
            elements.append(("text", text))


def parse_roster_page(page, elements):
    in_notes_block = False
    for row in grouped_lines(page):
        if row["top"] < 80:
            continue
        left, right, full = row["left"], row["right"], row["full"]
        if PAGE_NUM_RE.fullmatch(full):
            continue
        if full in {"STARTERS", "BENCH"}:
            elements.append(("section_header", full))
            in_notes_block = False
            continue
        if PLAYER_LINE_RE.match(left or full):
            elements.append(("text", left or full))
            in_notes_block = False
            continue
        if (
            left.startswith("GP-GS")
            or full.startswith("GP-GS")
            or left.startswith("Last Season")
            or full.startswith("Last Season")
            or re.match(r"^\d{2}-\d{2}\s*\(", left or full)
            or re.match(r"^\d{2}-\d{2}\s*\(", full)
        ):
            continue
        if "Player Notes" in full or "Keys to Defending" in full:
            in_notes_block = True
            continue
        if in_notes_block:
            if left:
                elements.append(("section_header", "Player Notes"))
                elements.append(("text", left))
            if right:
                elements.append(("section_header", "Keys to Defending"))
                elements.append(("text", right))


def parse_boxscore_page(page, elements):
    lines = [
        row["full"].replace("", "").strip()
        for row in grouped_lines(page)
        if row["top"] >= 80 and row["full"].strip()
    ]
    box_idx = next((i for i, line in enumerate(lines) if "BOXSCORE" in line.upper()), None)
    header_idx = next((i for i in range(box_idx + 1, len(lines)) if lines[i].startswith("# PLAYER ")), None) if box_idx is not None else None
    if box_idx is None or header_idx is None:
        return

    stop_idx = next(
        (
            i for i in range(header_idx + 1, len(lines))
            if lines[i].startswith("Top Scorers")
            or lines[i].startswith("3PT Shooters")
            or PAGE_NUM_RE.fullmatch(lines[i])
        ),
        len(lines),
    )
    header_tokens = lines[header_idx].split()
    stat_cols = header_tokens[2:]
    rows = []
    for line in lines[header_idx + 1:stop_idx]:
        tokens = line.split()
        if len(tokens) < 2 + len(stat_cols):
            continue
        name = " ".join(tokens[1:-len(stat_cols)])
        if name == "TeamTotal":
            name = "Team Total"
        rows.append([tokens[0], name] + tokens[-len(stat_cols):])

    if rows:
        box_df = pd.DataFrame(rows, columns=["#", "PLAYER"] + stat_cols)
        elements.append(("section_header", lines[box_idx]))
        elements.append(("table", box_df.to_html(index=False)))


def parse_scout_pdf_elements(path):
    elements = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if "BOXSCORE" in page_text:
                parse_boxscore_page(page, elements)
            elif "STARTERS" in page_text or "BENCH" in page_text or re.search(r"#\d+•", page_text):
                parse_roster_page(page, elements)
            else:
                parse_game_plan_page(page, elements)

    # pd.DataFrame([]) on an empty list produces a DataFrame with NO COLUMNS at all (not just 0 rows) --
    # explicitly pin the expected columns so a PDF that yields zero elements (e.g. a page layout these
    # heuristics don't recognize) still reports "0 elements, 0 tables" downstream instead of crashing with
    # a KeyError on element_type.
    return pd.DataFrame(
        [
            {"element_index": idx, "element_type": element_type, "element_content": element_content}
            for idx, (element_type, element_content) in enumerate(elements)
        ],
        columns=["element_index", "element_type", "element_content"],
    )


# NOTE: home/away-aware opponent-name extraction for scout report filenames -- ported as-is from the original
# notebook cell, which called an "opponent_from_scout_filename()" that was never actually defined there
# either (a pre-existing bug in the source notebook, not introduced by this portable conversion). This local
# helper fills that gap using the same "<date> <A> @ <B>_scout.<ext>" filename convention documented below --
# handles both the legacy "_scout.pdf" and the new "_scout.html" extension.
def opponent_from_scout_filename(path):
    name = re.sub(r"_scout\.(pdf|html)$", "", os.path.basename(path))
    name = re.sub(r"^\d+_\d+_\d+\s+", "", name)
    if " @ " not in name:
        return name
    left, right = [side.strip() for side in name.split(" @ ", 1)]
    return right if "whitewater" in left.lower() else left


def normalize_html_text(text):
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _has_exact_class(tag, cls):
    # BeautifulSoup's class_=lambda predicate is invoked once PER CLASS TOKEN (as a bare string), not once
    # per tag with the full class list -- so a naive "cls in tag['class']" substring/membership check done
    # the wrong way (e.g. "Tile" in "EditableTile") can silently match an unrelated wrapper class too. Do the
    # membership check explicitly against the tag's own parsed class LIST instead, so only an exact token
    # match counts (confirmed: without this, "Tile" incorrectly matched "EditableTile" and duplicated every
    # game-plan/roster element).
    classes = tag.get("class")
    return bool(classes) and cls in classes


def _draft_editor_blocks(tile):
    """Every paragraph/bullet line inside a Tile's rich-text (Draft.js) content shares the class
    'public-DraftStyleDefault-block', whether it's wrapped in an <li> (bulleted/numbered list) or a plain
    <div> (unformatted lines, e.g. KEYS TO VICTORY's numbered lines) -- selecting on that class uniformly
    covers both cases in visual top-to-bottom order, instead of special-casing <li> vs plain paragraphs."""
    draft = tile.find(class_="public-DraftEditor-content")
    if draft is None:
        return []
    blocks = [b for b in draft.find_all(True) if _has_exact_class(b, "public-DraftStyleDefault-block")]
    return [normalize_html_text(b.get_text(" ", strip=True)) for b in blocks]


def parse_scout_html_elements(path):
    """HTML counterpart to parse_scout_pdf_elements() -- reconstructs the identical element schema
    (element_index, element_type in {section_header, text, table}, element_content) directly from the
    ScoutBuilder report's own live DOM (saved by Cell 4's download step), instead of from a printed PDF.
    Confirmed structurally MORE reliable than pdfplumber's text-clustering heuristics: game-plan bullets,
    player notes, and keys-to-defending are each their own clean DOM node here, with no PDF column-merging
    to work around (the Eureka-style merged notes/keys blob that split_combined_notes_keys() exists for in
    Cell 9 simply can't happen with this source).
    """
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")
    printable = soup.find(class_="PrintableNode")
    elements = []
    if printable is None:
        return pd.DataFrame([], columns=["element_index", "element_type", "element_content"])

    # ---- game-plan tiles: any exact-class "Tile" whose title span matches a known header, in document order.
    # Confirmed the site does NOT reliably split these across pages the same way every time (unlike the PDF
    # export) -- parsing the whole PrintableNode in one pass sidesteps relying on any particular page boundary.
    for tile in printable.find_all("div"):
        if not _has_exact_class(tile, "Tile"):
            continue
        title_el = tile.find("span", class_="scout-tile-title")
        if title_el is None:
            continue
        header = normalize_html_text(title_el.get_text(strip=True))
        if header not in GAME_PLAN_HEADERS:
            continue
        elements.append(("section_header", header))
        for block in _draft_editor_blocks(tile):
            elements.append(("text", block))

    # ---- roster tiles: STARTERS/BENCH section headers interleaved with each player's own "playerGroup" tile,
    # in document order (this interleaving matters -- Cell 9 infers Starter vs Bench role from each player's
    # position relative to the BENCH header).
    for tile in printable.find_all("div"):
        if not _has_exact_class(tile, "Tile"):
            continue
        classes = tile.get("class")
        if "section" in classes:
            header_text = normalize_html_text(tile.get_text(" ", strip=True))
            if header_text in ("STARTERS", "BENCH"):
                elements.append(("section_header", header_text))
        elif "playerGroup" in classes:
            info_span = tile.find("span", class_="player-info-line")
            if info_span is None:
                continue
            info_div = info_span.find("div", class_=lambda c: c and "display-flex" in c)
            # Direct-child <span>s only (jersey/name/pos/height/weight/class in order) -- reading them
            # positionally (rather than via .stripped_strings, which silently DROPS an empty span, e.g. a
            # player missing a weight) keeps all 6 fields and 5 "•" separators intact even when one field is
            # blank, matching Cell 9's PLAYER_LINE_RE exactly (it already tolerates an empty weight group).
            field_spans = info_div.find_all("span", recursive=False) if info_div else []
            fields = [normalize_html_text(s.get_text(" ", strip=True)) for s in field_spans]
            elements.append(("text", " • ".join(fields)))

            for text_tile in tile.find_all("div"):
                if not (_has_exact_class(text_tile, "Tile") and _has_exact_class(text_tile, "text")):
                    continue
                blocks = [b for b in _draft_editor_blocks(text_tile) if b]
                if not blocks:
                    continue
                label = blocks[0].lower()
                if label.startswith("player notes"):
                    section_name = "Player Notes"
                elif label.startswith("keys to defending"):
                    section_name = "Keys to Defending"
                else:
                    continue
                elements.append(("section_header", section_name))
                for block in blocks:
                    if block.lower().startswith(section_name.lower()):
                        continue
                    elements.append(("text", block))

    # ---- season boxscore: confirmed against a real live-downloaded report -- once loaded (Cell 4's download
    # step explicitly waits for it), it's a genuine <table> (not a div-grid as originally guessed), with the
    # same PLAYER/Team Total/Opponent row shape as the PDF version. Emit the same (section_header, "table")
    # element pair the PDF path produces (a "...BOXSCORE" header immediately followed by a table element) so
    # extract_team_totals_from_pdf() downstream picks it up unchanged regardless of source format.
    boxscore_tile = next(
        (t for t in printable.find_all("div") if _has_exact_class(t, "Tile") and _has_exact_class(t, "boxscore")),
        None,
    )
    if boxscore_tile is not None:
        boxscore_table = boxscore_tile.find("table")
        boxscore_tbody = boxscore_table.find("tbody") if boxscore_table is not None else None
        if boxscore_tbody is not None and boxscore_tbody.find("tr") is not None:
            title_el = boxscore_tile.find("span", class_="scout-tile-title")
            header_text = normalize_html_text(title_el.get_text(strip=True)) if title_el else "BOXSCORE"
            elements.append(("section_header", header_text))
            elements.append(("table", str(boxscore_table)))
        else:
            print(
                f"    NOTE: '{os.path.basename(path)}' boxscore Tile has no populated table yet (still "
                f"loading, or the wait in Cell 4 didn't catch it this time) -- season-stat cells relying on "
                f"it will be incomplete for this opponent."
            )

    return pd.DataFrame(
        [
            {"element_index": idx, "element_type": element_type, "element_content": element_content}
            for idx, (element_type, element_content) in enumerate(elements)
        ],
        columns=["element_index", "element_type", "element_content"],
    )


scout_reports = {}  # opponent short name (from filename) -> parsed element table (element_index, element_type, element_content)
for path in scout_report_files:
    # Filenames are either "<date> UW-Whitewater @ <Opponent>_scout.<ext>" (away game) or
    # "<date> <Opponent> @ UW-Whitewater_scout.<ext>" (home game, e.g. the Aurora report) -- reuse the
    # same home/away-aware extraction defined above instead of always taking the text after "@", which
    # would mislabel every home game's report as "UW-Whitewater". Dispatch to the parser matching this
    # specific file's format -- older manually-uploaded reports are PDFs, auto-downloaded ones are HTML.
    opponent_short = opponent_from_scout_filename(path)
    parser_fn = parse_scout_html_elements if path.lower().endswith(".html") else parse_scout_pdf_elements
    elements_df = parser_fn(path)
    scout_reports[opponent_short] = elements_df
    n_tables = (elements_df["element_type"] == "table").sum()
    print(f"  Parsed '{opponent_short}' ({os.path.splitext(path)[1]}): {len(elements_df)} elements, {n_tables} tables")

# Flag any opponent that only has an MHTML report -- since MHTML is no longer used as a source at all, they're
# excluded from every downstream cell until a PDF version is added for them too.
mhtml_only_files = sorted(glob.glob(f"{volume_dir}/*_scout.mhtml"))
mhtml_opponents = {re.search(r"@ (.+)_scout\.mhtml$", os.path.basename(f)).group(1) for f in mhtml_only_files}
dropped_opponents = mhtml_opponents - set(scout_reports)
if dropped_opponents:
    print(f"\nWARNING: no PDF scout report exists yet for {sorted(dropped_opponents)} -- "
          f"MHTML is retired as a source, so these opponents are excluded from the analysis below.")
