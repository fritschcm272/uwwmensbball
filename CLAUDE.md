# CLAUDE.md — handoff notes for a new chat

Read this first in any new chat about the UW-Whitewater (UWW) men's basketball scouting project.
Last updated: Nov 9, 2026. Owner: Corey. (Sections 0, 4 and 7 are current; section 8 is the Nov 2 history.)

---

## 0. "Update all scouting briefs" -- what that means (READ THIS)

There are several kinds of scouting brief. When Corey asks to **update all scouting briefs** (or to change something "in the
briefs"), every one of them must be updated / re-run, and a change to the brief code (`87_build_html_scouting_brief_for_upcoming.py`)
must work for all of them:

| Brief | Built by | Output |
|---|---|---|
| **Upcoming opponent brief** -- our next game. Its *type* is picked automatically (`brief_type_for`, `BRIEF_TYPE = "auto"`): **preseason** (scrimmage / exhibition before the season, on last season's numbers), **first games** (either team has played < `BRIEF_FIRST_GAMES_MIN` = 3 games this season: small samples shown next to last season), **regular** | `parser_brief.ipynb` (`run_parser("brief")`; `REFERENCE_DATE` / `EXTRA_GAMES` in its first cell) | `data\scouting_briefs\scouting_brief_<team>.html` |
| **No-seniors copy** of a preseason / season-opener brief (last season's seniors removed instead of struck through, projected starters) | same run, automatically whenever a strike plan exists | `..._<team>_no_seniors.html` |
| **Team analysis** -- ANY team, this season, NO UW-Whitewater sections (no banner/matchup, keys to victory, head-to-head, team-stat comparison, what-to-play, two-for-one, needs-tagging, and nothing after the UW-WHITEWATER divider; the late-game foul list stays) | `parser_analysis.ipynb` (`run_parser("analysis")`; `TEAM`, `SEASON`, `REFERENCE_DATE`, `TEAM_URL`) -- one run per team | `F:\Backups\uwwmensbball_analysis\<Team>\scouting_briefs\scouting_brief_<team>.html` (fallback `data_analysis\<Team>\`; `ANALYSIS_DIR` overrides). Works on a copy of `data\` (table files + saves, logos, photos, brand), so the app's data is never touched |

So "update all briefs" = run `parser_brief` for the upcoming game AND re-run `parser_analysis` for every team that has a
folder under the analysis directory (list the folders; ask Corey if unsure which teams he still wants). Run
`parser_models` first if film/tags changed. Analysis mode is `ANALYSIS_MODE` in 87 (`_an` state in `add` / `section` /
`divider`) and `_pm_analysis_setup` in `00_parser_modes.py`; only the parser's CURRENT season works (past seasons stop
with a message -- their FastScout files are in `inputs_<season>`).

Brief data rule (11/9): once the season has switched, every table built from tagged clips (play calls, situations, the
offense breakdowns, screen coverage, ball-screen defense, coach notes, passing) uses **this season's clips only**
(`season_play_calls` in 47, `BRIEF_THIS_SEASON_ONLY = True`). `play_calls` itself keeps every season for Film Tagging,
tracking and the models.

---

## 1. What the project is

- **Parser** (`parser/`): reads FastScout pages, play-by-play, Synergy exports and the coaches' tags, then writes CSVs and the HTML scouting brief into `data/`.
- **Streamlit app** (`streamlit_app.py`, repo root): the coaches' app, deployed on Streamlit Community Cloud straight from GitHub. It shows only what's in `data/`, so **nothing changes in the app until Corey commits and pushes**.
- **Coaches**: Corey, plus Coach Jake, who does most of the Film Tagging in the app.

### Repo layout (Windows, inside OneDrive)
```
C:\Users\frits\OneDrive\Documents\GitHub\uwwmensbball\
  streamlit_app.py            the app (~1.2 MB)
  data\                       everything the app reads (CSVs, play_tag\, play_review\, scouting_briefs\)
  data\play_review_saves\     coaches' saved answers (also on the git branch 'saves')
  parser\
    parser_nb.ipynb           ALL settings + one cell per section (Corey never opens it directly)
    parser_models.ipynb       job: run_parser("models")  -- tracking, court, jersey reader, tag model, checks
    parser_tagging.ipynb      job: run_parser("tagging") -- new Film Tagging batches, fast
    parser_brief.ipynb        job: run_parser("brief")   -- scouting brief + app data (REFERENCE_DATE, EXTRA_GAMES in its first cell)
    parser_analysis.ipynb     job: run_parser("analysis") -- team analysis brief, no UWW sections (see section 0)
    parser_lib\NN_*.py        the code for each section (run_section("NN_name"))
    parser_lib\00_parser_modes.py   the job definitions (which sections each job runs, quiet mode)
    inputs\                   FastScout pages, rosters, logs (inputs\_logs\<job>_<time>.log)
F:\Backups\uwwmensbball_tracking\           Synergy Editor exports (one folder per game, 3-5 GB each)
F:\Backups\uwwmensbball_tracking\_tracking\ tracking files (TRACK_DIR) -- moved off C: on 11/2
```

### How Corey runs things
- He runs **only the three job notebooks** (models / tagging / brief). They execute `parser_nb.ipynb`'s cells from disk, so a setting change goes into `parser_nb.ipynb`. Don't tell him to open or reload it.
- All three jobs run in **quiet mode**: one "done" line per section, one live status line, and lines matching the job's `quiet_show` printed as they happen. Everything else goes to `parser\inputs\_logs\<job>_<YYYYMMDD_HHMMSS>.log`. **To analyze a run, stage the newest log and read it.**
- Sections 01-45 (the "core") are skipped on a re-run in the same kernel when nothing they read changed. The fingerprint includes the date and each section file's mtime.
- After a run: commit and push `data/` (plus `streamlit_app.py` when it changed) in GitHub Desktop.

---

## 2. How to work on his files (important)

- Corey's computer is reached through the `mcp__remote-devices__*` tools. **`device_bash` IS available now** (since 11/3):
  his repo is mounted at `$HOME/mnt/uwwmensbball`. Edit files IN PLACE there with a python read-modify-write
  (`assert s.count(old) == 1`), then check syntax with `python3 -c "import ast; ast.parse(open(f).read())"`
  (`py_compile` can fail with an I/O error writing `__pycache__` on the mount). Don't stage files just to edit them.
- `F:\Backups\uwwmensbball_tracking` is connected but often does NOT mount in `device_bash`; use `device_list_dir` /
  `device_stage_files` for it.
- Deleting needs Corey's approval (`device_request_delete_permission`); otherwise `mv -n` into a `_to_delete` / `_wrong_season_scrapes` folder.
- To analyze a run: newest `parser\inputs\_logs\<job>_<YYYYMMDD_HHMMSS>.log`, grep it (see section 6).
- Write `CONFIRMED CHANGE (requested: "...")` or `CONFIRMED BUG (fixed; ...)` comments at each change, quoting Corey. The whole code base does this; keep it up.
- Prefer verifying against real data (the log, the CSVs in `data\`, `inputs\`) over guessing.

### Standing rules from Corey
- **"I do not want anything you do to effect the games and clips that are currently in the film tagging section."** Never break or rebuild existing Film Tagging batches or saved answers. Saves on the `saves` branch must still count.
- Keep answers concise. Explain what changed and what he needs to run.
- Derived content is computed in the parser and exported as CSVs; the app only renders it.

---

## 3. The 11/2 incident (know this so it never repeats)

- `parser_nb.ipynb` on his computer got replaced by a **weeks-old copy**, probably from an editor tab holding a stale buffer. That copy had no `TRACK_DIR` and the Wheaton scrimmage as the upcoming opponent.
- The tagging run then:
  - looked for tracking files on C:, didn't find the `_reset.json` marker, and **re-ran the one-time tracking reset**;
  - deleted the tag-model files in `inputs\_tag_model` and the jersey-reader `.pt` / `reads`;
  - moved the court calibrations to `_before_reset`;
  - wrote a new reset time, so all Film Tagging saves were "set aside";
  - emptied the Carroll@Elmhurst batch.
- Restored:
  - the notebook (good copy committed);
  - `inputs\_tracking\_reset.json` → `{"id": "2026-10 restart on 1920 Synergy exports", "at": "2026-10-14T02:47:38+00:00"}`;
  - 8 court calibrations moved back.
- Corey discarded the `data/` changes in GitHub Desktop.
- **The tag model and the jersey reader need to retrain** on the next `parser_models` run. It's slower once.
- If anything looks like a reset happened again, check the `Tracking reset (` line in the log and the `_reset.json` files on both C: and F:.

---

## 4. Current state (Nov 9, 2026)

### Season / opponent
- **Season 2026-27** (`SEASON = "2026-27"` in parser_nb; the switch moved 2025-26 FastScout files to `parser\inputs_2025-26`
  and copied last season's tables to `data_2025-26`). `REFERENCE_DATE = "2026-11-8"` in parser_nb AND in parser_brief's first
  cell -> upcoming game **Ripon Red Hawks, Home, Nov 14 2026**. `EXTRA_GAMES = []`.
- UWW's first game: **@ Carroll, Nov 7 2026** (Synergy game `6ac6ee2d34559f81e3ab11c7`). FastScout had not posted its score /
  play-by-play as of 11/9, so the brief has no UWW season stats yet (many sections were made to handle empty tables).
- Ripon's first game: vs Elmhurst Nov 7 (Synergy `6abc2667a50466db6de75137`) -- exported from Synergy 11/9 for Film Tagging.
- Ripon's scout report not posted on FastScout yet.
- `FRAMES_STOP_IGNORE_GAMES = ["2025-11-07 WWW@RIP"]` (last season's Ripon game: Synergy page has only 175 clips).

### parser_models first cell (options passed to run_parser)
`TRAIN_MODELS`, `DO_PLAYER_TRACKING`, **`PLAYER_TRACKING_TYPE`** ("Starters" = 3 frames of the first clip until all 10
starters are placed; "5 Clips" / "20 Clips" per run after that), **`PLAYER_TRACKING_GAMES`** (replaces parser_nb's list;
currently WashU 11/7/25, Beloit@Carroll 11/12/25, `"11_7_26 UW-Whitewater @ Carroll (WI) Pioneers"` -- add each new game
here), `DO_FILM_TAGGING`, `FILM_TAGGING_SUGGESTIONS`, `ADD_GAMES`, `REOPEN_PLAYS`, `BANK_GAMES` (Platteville vs Thiel
`6aee1d6c9e04633c52349e89`; La Crosse vs St. John's commented out).

---

## 5. Key settings (parser_nb.ipynb)

| Cell | Settings |
|---|---|
| 2 | `EXTRA_GAMES` (upcoming game), `SEASON` |
| 108 (46 frame capture) | `TRACKING_RESET_ID`, `SYNERGY_EXPORT_DIR = F:\Backups\uwwmensbball_tracking`, `TRACK_DIR = F:\...\_tracking`, `PLAYER_TRACKING_GAMES`, `VISION_TRACK_FPS_TRACKING = 8` |
| 120 (50 tracking) | `TRACK_*` settings, `TRACK_HOLD_AT_CLIP = 8`, `TRACK_DIR = globals().get("TRACK_DIR") or ...` |
| 125 | `COURT_*` |
| 133 (55c play review / tagging) | `PLAY_REVIEW_*`, `PLAY_TAG_*`, `PLAY_TAG_INCLUDE_TRACKING_GAMES = True` |
| 202 (87 brief) | `ROSTER_LAYOUT = "table"`; optional `BRIEF_FILM_ON_FILE`, `BRIEF_FULL_BENCH_OPENER`, `PROJ_STARTER_POS_PENALTY` |

---

## 6. Useful log lines to grep

- `Film Tagging:` and the indented `YYYY-MM-DD ... clip(s) tagged` lines: batches and progress.
- `[saves]`: which saved review files were read.
- `Film on <team>:` (55e): film quality.
- `Tracking reset (` — **should never appear again**.
- `Struck through N ... senior(s)` and `Wrote ...scouting_brief_...html` (87).
- `[roster] <team>: 2026-27 roster -- N returning player(s) updated, M new player(s) added` (21).
- `[synergy]` (lookup, lineups), `[bank]`, `[export]` (Synergy Editor), `[export lineups]` (FastScout fallback).
- `This season only (2026-27): N of M clip(s)` (47), `ANALYSIS:` (parser_analysis setup).
- `[tracking] player model bank:` / `player-model backfill:` / `TRACK_NEW_GAME_PACE =`.


---

## 7. What was built Nov 3-9, 2026

**Synergy (no FastScout needed)** -- `46_frame_capture.py`
- `_syn_lookup` / `_syn_fill_video_urls`: a played game with no video link on FastScout is found on **Synergy's Games page**
  (`apps.synergysports.com/basketball/games?leagueId=...&seasonId=...&competitionKeys=<league>:ALL&teamAId=<team>&view=1`):
  our team id from `/api/users/getme`, season id from the seasons list, opponent team ids from UWW's games. Cache:
  `inputs\_synergy_ids.json`. `SYNERGY_LOOKUP = False` turns it off. Nothing is hard-coded (Corey: don't hard-code games).
- Every looked-up / banked game saves **both fives on every possession** from Synergy's `api/games/<id>/events`
  (`offensiveLineup` / `defensiveLineup`) to `inputs\_bank\<id>_lineups.csv`; starters = first possession's fives.
  47 attaches them (`_syn_attach_lineups`, matched by Synergy description, else half + clock + team).
- **Coach-tagged Export.csv games with no video** (e.g. `F:\...\STOUT\Export.csv` = Calvin @ UW-Stout 11/7/26): merged into
  `uww_plays.csv`; `_syn_export_lineups` gets their fives from Synergy; FastScout play-by-play fallback in 47
  (`_export_pbp_lineups`). They count for an opponent's brief when that team is upcoming.
- Banked games (`BANK_GAMES`, ID only): date / label / "for" looked up; Synergy starters + lineups; FastScout pbp fallback.
- Synergy Editor export box close (`_sst_close_export_box`) and cache clear (`_sst_clear_cache`, `SYNERGY_CACHE_DIR`) were
  still NOT confirmed working on 11/9: the close now searches inside the Editor window and dumps
  `inputs\_synergy_export_done_window.txt` on failure; the cache step prints Synergy folder sizes. Check after the next export.

**Season switch to 2026-27** -- 02 now switches FastScout's season selector when a team page opens on the wrong season
(`season=26` asked, `25` served); `_extra_find_team_url` forces the current season on links from old schedule files.
Bad wrong-season files went to `inputs_2025-26\_wrong_season_scrapes`.

**Player Number Tracking**
- Starters check: `PLAY_REVIEW_STARTERS` now defaults True (it was off while tracking waited on it -> stuck at clip 2);
  `STARTERS_PICTURES` (3 frames); Synergy starters prefilled for banked games; named "no box" rows count.
- `_NameNums`: jersey lookup ignores punctuation ("Greg Smith, Jr." = "Greg Smith Jr." = #42).
- Roster lists ignore Synergy's "1 Pts" (and-one) as a fake player.
- Player / not-a-player model now trains on **every game's checks ever** (`_tracking\player_model_bank.csv`); old checked
  clips are backfilled ONLY when their detections are already saved (`TRACK_BANK_BACKFILL`, `_MAX` 150) -- the first version
  ran the CPU detector on 8,589 frames (~3 h); don't repeat that.
- Jersey reader: `JERSEY_READER_MIN_ANSWERS` 6 -> 20 (it named players wrongly on 9 answers), `JERSEY_TRAIN_MIN_NEW` 150 -> 40.
- Detection runs on CPU (~1.5 s/frame); Corey's PC has 8 GB RAM (kernel died at 96% memory; he raised the page file).

**Brief / app data**
- Empty-season fixes (no UWW pbp/stats yet): 36 typed empty pbp, 44 numeric clock, 70 expected box skipped (empty
  projected tables), 80 `reindex`, 86 empty player lines, 11 margin "n/a".
- Offense breakdown / coverage tables, passing card, reads-to-roster etc. from earlier in the week (see the code comments).
- `parser_brief` first cell has `REFERENCE_DATE` / `EXTRA_GAMES` (applied at 00b; replace parser_nb's).
- Offense tables (11/9, Corey: "All of the offensive tables within briefs needs to also include the 5 person lineup that runs it most and any players that are best at scoring off of it"): `uww_offense_breakdown` has `top_lineup` / `top_scorers` on every situation / formation / play-call row (47 `_top_lineup`, `_top_scorers`); 87 `_offense_breakdown_card` shows them under each PLAY-CALL row ("Runs it:" / "Scores:") -- never on the "All" rows: Corey wants the All rows' Actions column empty. Applies to every brief kind (ours, theirs, analysis). Any NEW offensive table in a brief must carry the same two lines.
- Play-call names that differ only by capitals / spacing ("BLOB #1" vs "Blob #1") are merged to the most-used spelling for every season (47 `_pl_merge_spellings`, before all summaries). Corey wants such near-duplicates always combined in the briefs.

**App -- Film Tagging (11/9)**: one clip at a time (`render_film_tagging`): Previous / Next clip buttons, Go to clip list, saved every `FT_SAVE_EVERY` = 10 clips (only the clips opened since the last save) or with Save now; Enter = Next clip, space = play / pause (a small script in a zero-height component; ignored while typing or with a dropdown open). Answers live in `_pr_store` between clips; unsaved clips are lost if the page is reloaded.

**Corey's open items (11/9)**: Ripon brief needs UWW + Ripon this-season film tagged; Carroll player checks at "5 Clips";
delete the old `data_analysis\UW_Stout_Blue_Devils` folder in the repo (superseded by F:); first `parser_analysis` run for
UW-Stout not finished yet.

---

## 8. History: state on Nov 2, 2026 (superseded by sections 4 and 7)

### Season / opponent
- The parser is on the **2025-26** data (SEASON "auto"; UWW hasn't played 2026-27 yet). `EXTRA_GAMES` sets the upcoming game: **Carroll (WI) Pioneers, Away, real date Nov 7 2026** (UWW's 2026-27 opener). Run date is 2026-3-8.
- The brief type is **first_games → "SEASON OPENER BRIEF — FIRST GAMES"**, with last season's seniors struck through (`strike_seniors_plan`, `STRIKE_LAST_SEASON_SENIORS = "auto"`).
- Rosters: Carroll's 2026-27 roster page has been merged (`source = "... (new season)"`, `class_year_prev`). **UWW's 2026-27 roster is NOT merged yet**, so only graduated seniors can be dropped for UWW.

### Player Number Tracking — PAUSED
Corey said it's "good enough" for now; don't test more unless he asks.
- Game: `PLAYER_TRACKING_GAMES = ["11_7_25 Carroll (WI) Pioneers @ Washington-St. Louis Bears"]`. It gets 8 fps frames.
- Held at clip 8 (`TRACK_HOLD_AT_CLIP = 8`). Re-check pictures exist for clip 1.
- Last results:
  - jersey vote 10/11;
  - following 9/9;
  - all 1,072 frames on the court;
  - guess accuracy about 61%;
  - player model still needs 15 not-a-player labels (has 10).
- Main tracking code: `50_player_tracking.py` (~390 KB), `51_court_mapping.py`, `55c_play_review.py` (play review + Film Tagging), `48`/`49` (jersey reader), `46` (frames / exports).

### Beloit @ Carroll (11/12/25) — set up 11/3 for Film Tagging + Player Number Tracking
- `PLAYER_TRACKING_GAMES` now lists WashU AND `"11_12_25 Beloit Buccaneers @ Carroll (WI) Pioneers"`. Being listed is what gets it captured and exported, even outside the `VISION_RECENT_GAMES` window; `VISION_ONLY_GAME` stays None.
- New `ptg_setting()` in 46: `TRACK_HOLD_AT_CLIP` and `PLAY_REVIEW_RECHECK_CLIPS` can be dicts per game. They are now `{WashU: 8}` and `{WashU: [1]}`, so WashU stays paused and Beloit moves on.
- `PLAY_TAG_INCLUDE_TRACKING_GAMES = True`, so Beloit also gets a Film Tagging batch (Carroll's offense first).
- Next steps for Corey: run `parser_models` (Synergy export up to 90 min) → court calibration in the app if asked → starters check on clip 1 → player checks (one clip at a time, `TRACK_NEW_GAME_PACE`).

- 11/3 fixes:
  - A `_scout` file no longer counts as a played UWW game in `01._auto_reference_after_last_game` or `00b._ss_data_season`. The new 11_7_26 report had made the run date 11/8/26, shown "Season: 2026-27" and dropped EXTRA_GAMES. No files were moved; there is no `_season.json`.
  - 11: a report with "-" totals (written before any games) is skipped instead of crashing.
  - The Beloit export worked (178 clips, `Beloit@Carroll(WI) - Nov 12, 2025` on F:).

### Film Tagging
- Built by `parser_tagging` (55c `tag_queue`). Only "this run's" games get batches (`PLAY_TAG_RUN_ONLY`): the upcoming opponent's games plus our most recent game.
- Opponent games: the scouted team's offense first, then the rest once saved. UWW games: offense, then defense. The app shows 20 plays per page.
- `PLAY_TAG_INCLUDE_TRACKING_GAMES = True` (cell 133) now puts Carroll@WashU into Film Tagging too.
- Latest progress:
  - Carroll@WashU 0/221 (105 Carroll offensive plays in the batch);
  - Carroll@Elmhurst 82/160 (1 offensive play left, then 78 more);
  - UWW@WashU (3/7/26) 122/167.

### Scouting brief (`87_build_html_scouting_brief_for_upcoming.py`, ~335 KB) — what changed on 11/2
1. **"Film on file" line removed** from page 1. `BRIEF_FILM_ON_FILE = True` brings it back.
2. **"Who to attack"** (2-for-1 Attack/Avoid, `uww_two_for_one_attack`) moved from the Two-for-One section to the first read line of each opponent player in the roster. Struck seniors are skipped.
3. **Two copies for scrimmage / season-opener briefs** (whenever a strike plan exists):
   - `scouting_brief_<team>.html`: unchanged, seniors struck through.
   - `scouting_brief_<team>_no_seniors.html`: made by `_sb_drop_struck()`. It removes struck rows, items, keys (renumbered) and names with their "(n)", and changes the banner to "left out".
   - The app's Game Plan tab has two download buttons.
4. **Whole bench** in those briefs (`_sb_full_bench`, `BRIEF_FULL_BENCH_OPENER`). Adds "Bench — limited minutes", "Bench — no minutes" and "Bench — never played" (names from `uww_roster_no_minutes`).
5. **No-seniors copy always shows 5 starters** (`_no_senior_roster`):
   - Returning starters are untagged.
   - Each graduated starter's spot goes to the returning player of the **same kind** (guard / wing G/F / forward / big). Big = C, or a Post Scorer / Roll & Cut Big / Anchor Big role.
   - The best mpg wins, minus `PROJ_STARTER_POS_PENALTY = 6` minutes per step away from the right kind.
   - Tagged with a yellow **Projected starter** chip; first read "Projected starter — X minutes a game last season".
   - Players not on a new-season roster are treated as gone.
   - Drawn twice in the HTML between `<!--NS:strike-->` / `<!--NS:remove-->` markers; the run block keeps the right one in each file.
   - Carroll: McKenna, McNabb, Estepp + Tarjan (for Lamar Smith) + Greg Smith (for Naber). UWW: Madson, Marino + McEwen, Chestnut, Lukenbill.
6. **Roster table layout**: each player gets a purple **bio bar** row (#, pos, height, class, Off/Def roles; his name is hidden in it so strike / remove handle both rows), then his row with the **photo above the name**. No Bio column. **UWW has no Late game foul column** (10 columns vs the opponent's 11).
7. **Below-minimum lines** ("under the 6-attempt minimum for a shooting read") replaced by a red `*` after the name and one legend line at the bottom of the roster.
8. **Opponent bios / photos** fall back to the live roster (`_opp_ros_bio`) when a player isn't in `uww_opp_personnel` (fixed Nolan Groh and other freshmen with no photo).

### Other fixes on 11/2
- `21_roster_pages.py`: roster lines with a comma in the name ("GREG SMITH, JR.") were skipped entirely. Now commas are allowed and new/old seasons match ignoring Jr./Sr./II/III (`_ros_match_key`).
- `00_parser_modes.py`: `parser_tagging` now runs quiet like the other two jobs.
- `README.md` (repo root) now has step-by-step instructions for bringing a new game into Film Tagging and Player Number Tracking (worked example: Beloit @ Carroll, 11/12/25), including the player-check options.
- `41b_offensive_roles.py` (offensive roles):
  - A ball handler must also create for others: `ROLE_BALLHANDLER_MIN_AST` = 0.15 assists per possession. Non-creators go on through the scoring roles (Madson → Slasher, Bara → Off Screen Shooter; 11 players changed in total).
  - One team under two names ("UW-Whitewater" / "UW-Whitewater Warhawks") is merged when the names overlap and they share players (`_or_team_canon`). Possessions and assists in a game that's in both files are counted once.
  - Not seen in a real run yet.
- **Upcoming game's own scouting report** (Carroll 2026-27):
  - `BEFORE_SCOUT` setting (cell 2, now "no"; it was hard-coded "yes" in 01).
  - `02._extra_game_scout_report()` downloads the EXTRA_GAMES game's report from the opponent's NEXT-season documents page, matched on `real_date`, as `11_7_26 UW-Whitewater @ Carroll (WI) Pioneers_scout.html`. If none is posted yet it re-checks after `EXTRA_SCOUT_CHECK_HOURS` (6; cache `inputs\_extra_scout_check.json`).
  - 08 keeps two reports per opponent:
    - `scout_reports` = the past game's report, so 11 / 12 pair keys with that game via `all_game_plans_history`;
    - `scout_reports_upcoming` = the new one.
  - 10: `all_game_plans` (uww_opponent_game_plans) uses the new report and gains a `report_date` column.
  - 09: player notes and keys to defending come from the new report, matched by name; new players are added with no jersey.
  - 87: no "2025-26" tag on staff keys when `report_date` is this season.
  - Not seen in a real run yet.
- Known cosmetic issue: the quiet `!!` match also shows the coaches' "ATTACK THE PAINT!!!" key lines. Harmless; could use `^\s*!!`.

### Not verified yet / waiting on Corey
- Corey had not yet re-run `parser_brief` after the last three brief changes (asterisk legend, Groh photo, UWW foul column). Check the next brief log and HTML.
- UWW's own tracked game (3/7/26) shows "players named <NA>%" in the film quality line since the reset. It was noted to Corey but not fixed.

---
