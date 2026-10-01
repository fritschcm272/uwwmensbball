# 06_investigate_myteam_analytics_dashboard_3.py -- code for the notebook section "06_investigate_myteam_analytics_dashboard_3"
# Runs inside the notebook via run_section("06_investigate_myteam_analytics_dashboard_3"); its settings are in that notebook cell.

dashboard_snapshot_path = os.path.join(schedules_dir, "myTeam - Analytics Dashboard.html")

if not os.path.exists(dashboard_snapshot_path):
    print(
        f"'{os.path.basename(dashboard_snapshot_path)}' doesn't exist yet in {schedules_dir} -- it's only saved "
        "the first time a live FastScout session actually bootstraps (Cell 4's _ensure_fastscout_login), which "
        "requires FASTSCOUT_USERNAME/FASTSCOUT_PASSWORD to be set. Run any cell that live-scrapes at least once "
        "with credentials, then re-run this cell."
    )
else:
    dashboard_html = load_html_snapshot(dashboard_snapshot_path)
    dashboard_soup = BeautifulSoup(dashboard_html, "lxml")
    dash_tile_labels = ["Top Rebounders", "Top Scorers", "Top 3PT", "Top FT", "Top Assists", "Leaders"]

    print("Elements with a 'stat'-like class attribute (excluding <table> itself):")
    dash_stat_matches = [
        el for el in dashboard_soup.find_all(True, class_=True)
        if el.name != "table" and any("stat" in c.lower() for c in el.get("class", []))
    ]
    print(f"  found {len(dash_stat_matches)}")
    for el in dash_stat_matches[:15]:
        preview = el.get_text(" ", strip=True)[:80]
        print(f"  <{el.name} class={el.get('class')}> -- text preview: {preview!r}")

    print(f"\nElements whose text contains a known tile label {dash_tile_labels}:")
    dash_found_any = False
    for label in dash_tile_labels:
        matches = dashboard_soup.find_all(string=re.compile(re.escape(label), re.IGNORECASE))
        if matches:
            dash_found_any = True
        for txt in matches[:5]:
            ancestor = txt.parent
            for _ in range(3):
                if ancestor is None or ancestor.get("class") or ancestor.parent is None:
                    break
                ancestor = ancestor.parent
            if ancestor is not None:
                print(f"  [{label}] <{ancestor.name} class={ancestor.get('class')}> -- text preview: {ancestor.get_text(' ', strip=True)[:120]!r}")
    if not dash_found_any:
        print("  (none found on the analytics/dashboard page either)")

    print(f"\nTotal <table> elements on this page: {len(dashboard_soup.find_all('table'))}")
