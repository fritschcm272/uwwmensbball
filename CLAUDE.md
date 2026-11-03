# CLAUDE.md — handoff notes for a new chat

Read this first in any new chat about the UW-Whitewater (UWW) men's basketball scouting project.
Last updated: Nov 2, 2026 (end of day). Owner: Corey.

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
    parser_brief.ipynb        job: run_parser("brief")   -- scouting brief + app data
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

- Corey's computer is reached through the `mcp__remote-devices__*` tools. **`device_bash` has NOT been available**, so the workflow is:
  1. `device_stage_files` (copies the file to `/mnt/user-data/uploads/...`). Wait about 2 seconds before reading it.
  2. Edit a copy under `/mnt/user-data/outputs/...` (python read-modify-write with exact `old` / `new` and `assert count == 1`), then `python3 -m py_compile`.
  3. `device_commit_files` with `expectedMtimeMs` from the stage.
  4. **VERIFY**: `device_list_dir` or re-stage, and check the file **size on the device equals the local size**.
     **Seen twice:** re-saving a file from the SAME outputs path after editing it again can write the OLD copy (a stale
     snapshot). Copy the edited file to a NEW path (e.g. `outputs/v2/<name>`) and save from there, then verify. On 11/2 a commit reported "written" but the device kept the old file. That run printed the old output and cost a whole parser run.
- 30 MB per file commit limit. You can't delete files on the device (no `device_bash`).
- Write `CONFIRMED CHANGE (requested: "...")` or `CONFIRMED BUG (fixed; ...)` comments at each change, quoting Corey. The whole code base does this; keep it up.
- Prefer verifying against real data (stage the CSV or log) over guessing.

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

## 4. Current state (Nov 2, 2026)

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
