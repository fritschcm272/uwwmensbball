# 77_rebuild_player_comparisons_with_pbp_2.py -- code for the notebook section "OPTIONAL: re-derive the coach-note theme taxonomy with an LLM ----------------------------"
# Runs inside the notebook via run_section("77_rebuild_player_comparisons_with_pbp_2"); its settings are in that notebook cell.

# --- OPTIONAL: re-derive the coach-note theme taxonomy with an LLM ----------------------------------------
# The app groups free-text clip notes into themes by PHRASE MATCHING against data/note_themes.json. That is
# deliberate: classifying a note costs nothing and needs no network, so every new note the parser writes is
# grouped the moment the app reads it, forever.
#
# This cell is the other half of that arrangement: the one place a model is allowed to touch the taxonomy.
# Run it when the staff's vocabulary has drifted far enough that notes are landing in "no theme" -- it reads
# the notes THIS parser just produced, asks the model to propose themes and the phrases that identify them,
# and rewrites note_themes.json. Nothing at runtime changes; the app still only does string matching.
#
# Guards, because a bad rewrite here silently degrades every theme in the app:
#   * USE_LLM must be True AND REBUILD_NOTE_THEMES must be True -- neither alone does anything.
#   * The existing file is backed up next to itself before being replaced.
#   * The model's output is validated (shape, theme count, phrase count) and REJECTED wholesale on anything
#     unexpected, leaving the current file untouched.
#   * Existing phrases are MERGED IN rather than replaced, so a hand-tuned phrase never disappears because
#     the model didn't think of it this time.




def _strip_note_play_call(text):
    """Same play-call strip the app applies before classifying -- the play name is its own column, and
    leaving it in makes every note from one set look thematically identical."""
    t = re.sub(r"^[A-Z][A-Z0-9\-&' ]{1,24}?\s+EXECUTION\b[.,:=]*\s*", "", str(text).strip())
    t = re.sub(r"^[A-Z0-9\-' ]{2,20}=\s*", "", t.strip())
    return t.strip(" ,.=")


def rebuild_note_themes(notes_series, path=NOTE_THEMES_PATH, max_notes=400):
    """Ask the model for a theme taxonomy over these notes; write it only if it validates."""
    if not USE_LLM or not REBUILD_NOTE_THEMES:
        print("Note-theme rebuild skipped (needs USE_LLM=True and REBUILD_NOTE_THEMES=True). "
              "The app keeps using the existing data/note_themes.json -- classification is unaffected.")
        return None

    bodies = [_strip_note_play_call(n) for n in notes_series.dropna().astype(str)]
    bodies = [b for b in bodies if len(b) > 3][:max_notes]
    if len(bodies) < 20:
        print(f"Only {len(bodies)} usable note(s) -- too few to derive themes from. Leaving the file alone.")
        return None

    existing = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                existing = {t["theme"]: t for t in json.load(fh).get("themes", [])}
        except Exception as read_error:
            print(f"  Could not read the existing theme file ({type(read_error).__name__}) -- treating it as empty.")

    prompt = (
        "You are organizing a college basketball staff's own video-clip notes into themes so a coach can "
        "group similar corrections together.\n\n"
        "Return 12-18 themes covering the notes below. For each theme give:\n"
        '  "theme": a short noun phrase a coach would recognize (e.g. "Switching & Screen Coverage")\n'
        '  "side": one of "Offense", "Defense", "Both"\n'
        '  "phrases": 10-30 lowercase words/phrases that IDENTIFY the theme in note text. Use the staff\'s '
        "own vocabulary and abbreviations exactly as written (e.g. \"trans. def\", \"oreb\", \"wall up\", "
        "\"x-out\"). Prefer distinctive multi-word phrases; avoid generic words like \"good\", \"the\", "
        "\"play\" that would match everything.\n\n"
        "These phrases are used for literal substring matching later -- no model runs at classification "
        "time -- so they must be words that actually appear in notes of that theme.\n\n"
        'Respond with ONLY a JSON object: {"themes": [{"theme": "...", "side": "...", "phrases": ["..."]}]}\n\n'
        "NOTES:\n" + "\n".join(f"- {b}" for b in bodies)
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
        print(f"Theme rebuild FAILED ({type(llm_error).__name__}: {llm_error}) -- existing file left untouched.")
        return None

    themes = parsed.get("themes")
    if not isinstance(themes, list) or not (8 <= len(themes) <= 30):
        print(f"Rejected the model's response: expected 8-30 themes, got {len(themes) if isinstance(themes, list) else 'none'}. "
              "Existing file left untouched.")
        return None
    clean = []
    for t in themes:
        name = str(t.get("theme", "")).strip()
        phrases = [str(p).strip().lower() for p in t.get("phrases", []) if str(p).strip()]
        phrases = [p for p in phrases if 2 < len(p) <= 40]
        if not name or len(phrases) < 4:
            print(f"  Dropping theme {name!r}: {len(phrases)} usable phrase(s), need 4+.")
            continue
        side = str(t.get("side", "Both")).strip().title()
        if side not in ("Offense", "Defense", "Both"):
            side = "Both"
        # Merge, never replace: a phrase someone added by hand survives a rebuild.
        if name in existing:
            phrases = sorted(set(phrases) | set(existing[name].get("phrases", [])))
        clean.append({"theme": name, "side": side, "phrases": sorted(set(phrases))})
    if len(clean) < 8:
        print(f"Rejected: only {len(clean)} theme(s) survived validation. Existing file left untouched.")
        return None

    # Any theme the model dropped this run is KEPT -- notes already classified under it would otherwise
    # silently become unclassified.
    kept = [existing[n] for n in existing if n not in {c["theme"] for c in clean}]
    if kept:
        print(f"Keeping {len(kept)} existing theme(s) the model didn't propose this run: "
              f"{', '.join(t['theme'] for t in kept)}")
    clean.extend(kept)

    if os.path.exists(path):
        backup = path.replace(".json", f".backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
        try:
            os.replace(path, backup)
            print(f"Backed up the previous taxonomy to {os.path.basename(backup)}")
        except Exception as backup_error:
            print(f"  Could not back up the existing file ({type(backup_error).__name__}) -- aborting rather than overwriting it.")
            return None

    payload = {
        "version": 1,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "notes": ("Lexical theme taxonomy for coach-note grouping. Runtime classification in the app is pure "
                  "string matching -- no model call, no tokens. Edit phrases here to retune."),
        "themes": clean,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"Wrote {len(clean)} theme(s), {sum(len(t['phrases']) for t in clean)} phrase(s) to {path}")
    for t in clean:
        print(f"  {t['side']:<8} {t['theme']} ({len(t['phrases'])} phrases)")
    return payload


_note_theme_result = rebuild_note_themes(
    coach_notes["coach_note"] if "coach_note" in coach_notes.columns else pd.Series(dtype=object)
)
