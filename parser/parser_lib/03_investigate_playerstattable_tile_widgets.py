# 03_investigate_playerstattable_tile_widgets.py -- code for the notebook section "Diagnostic: locate the "Top Rebounders/Scorers/3PT/FT" tile widgets on the schedule page -"
# Runs inside the notebook via run_section("03_investigate_playerstattable_tile_widgets"); its settings are in that notebook cell.

# --- Diagnostic: locate the "Top Rebounders/Scorers/3PT/FT" tile widgets on the schedule page -------------
# These are presumed to be a SEPARATE UI widget from the plain season stats table (tables[1], extracted
# above) -- likely rendered as div/card elements, not a <table>, so pd.read_html over page_tables never sees
# them. Re-parse the FULL page (not just the <table> elements already captured in `tables`) and search two
# ways since the exact markup isn't confirmed yet: (1) any element whose class attribute mentions "stat"
# (case-insensitive) that ISN'T a <table> itself, and (2) any element whose own text contains one of the
# known tile labels. Prints just enough of each match (tag, classes, a short text preview) to identify the
# real selector to parse against, without assuming a specific structure upfront.
tile_investigation_html = load_html_snapshot(uww_mhtml_path)
tile_investigation_soup = BeautifulSoup(tile_investigation_html, "lxml")


print("Elements with a 'stat'-like class attribute (excluding <table> itself):")
stat_class_matches = [
    el for el in tile_investigation_soup.find_all(True, class_=True)
    if el.name != "table" and any("stat" in c.lower() for c in el.get("class", []))
]
print(f"  found {len(stat_class_matches)}")
for el in stat_class_matches[:15]:
    preview = el.get_text(" ", strip=True)[:80]
    print(f"  <{el.name} class={el.get('class')}> -- text preview: {preview!r}")

print(f"\nElements whose text contains a known tile label {TILE_LABELS}:")
found_any = False
for label in TILE_LABELS:
    matches = tile_investigation_soup.find_all(string=re.compile(re.escape(label), re.IGNORECASE))
    if matches:
        found_any = True
    for txt in matches[:5]:
        ancestor = txt.parent
        for _ in range(3):
            if ancestor is None or ancestor.get("class") or ancestor.parent is None:
                break
            ancestor = ancestor.parent
        if ancestor is not None:
            print(f"  [{label}] <{ancestor.name} class={ancestor.get('class')}> -- text preview: {ancestor.get_text(' ', strip=True)[:120]!r}")
if not found_any:
    print("  (none found in this saved snapshot -- these tiles may not exist on this page, may use "
          "different wording, or may not have been present/loaded when this snapshot was captured)")

print(f"\nTotal <table> elements on this page: {len(tile_investigation_soup.find_all('table'))}")
