# parser_lib

The code of `parser_nb.ipynb`, one file per notebook section (numbered in notebook order).

* Keep this folder **next to `parser_nb.ipynb`** (the notebook runs from its own folder).
* Each notebook section cell holds only its **settings**, then runs its file with `run_section("<file>")`.
  The file runs inside the notebook, exactly as if its code were still in the cell: every function and table it
  creates is available to the cells after it.
* To change a **setting**: edit it in the notebook cell. To change **how something works**: edit the `.py` file here,
  then rerun that notebook cell (no restart needed -- the file is read fresh every time).
* Errors point to the file and line in here (e.g. `parser_lib\50_player_tracking.py, line 812`).

## Tests to send back

Some features are **tested on your own player checks first** and only switch on in Player tracking if the test passes.
Each test cell prints a short report and saves files in `inputs\_tracking\`. To show Claude the results, send:
**(1)** the printed lines (copy the cell output), and **(2)** the files listed below.

| Notebook cell | Code | What it tests | Send these files | Turns on in tracking when |
|---|---|---|---|---|
| Outfit check (test) | `50c_outfit_check.py` | Can Fashion-CLIP tell players from referees / coaches / bench / fans by their clothes? | `outfit_check_test.json`, `outfit_check_scores.csv` | flagged boxes are really non-players >= `OUTFIT_MIN_PRECISION` (90%) of the time and it catches >= `OUTFIT_MIN_RECALL` (25%) of them (`TRACK_OUTFIT_CHECK = "auto"`) |
| Re-ID check (test) | `50d_reid_check.py` | Does an unnamed player look like the player you checked in the same game? (OSNet vs DINOv2) | `reid_check_test.json`, `reid_check_results.csv` | its picks are right >= `REID_MIN_PRECISION` (80%) of the time on >= `REID_MIN_COVERAGE` (15%) of the question boxes (`TRACK_REID_NAMES = "auto"`) |
| Jersey-number reader test (with `JERSEY_CROP_STYLE = "compare"`) | `48_...`, `49_...` | Fixed chest crop (`trained`) vs shoulders-to-hips crop (`trained_pose`) | the printed lines, including both per-number tables | the better reader wins automatically |

### How to read the printed reports

**Outfit check.** `AUC` = how well the score separates non-players from players (0.5 = coin flip, 1.0 = perfect).
The table lists score cutoffs: *boxes flagged* at that cutoff, how many of them *really are not players*, the share
of all non-players *caught*, and *real players lost*. `PASSED` / `NOT PASSED` says whether tracking will use it.

**Re-ID check.** One line per model: `right X% overall` (vs `guessing at random among the candidates`), then the
smallest *margin* (how much the best-matching player beat the second best) at which its picks were right >= 80%, and
on how many boxes. `CHOSEN: osnet` (or `dinov2`) = tracking will use it; names it gives show as **re-id match** in the
app's Player Number Tracking metrics, so your later checks measure it like every other naming method.

`reid_check_results.csv` has one row per question box: `model, game, clip_key, frame_file, side, true_name, picked,
right, margin, true_has_references, candidates` -- `true_has_references = False` means you hadn't checked that player in
the reference half of that game, so the model couldn't have known him.

### If a test can't run
* `transformers was installed. RESTART THE KERNEL` -> restart the kernel (Kernel > Restart) and run again.
* `boxmot is not installed` -> run `%pip install boxmot` in a new cell, restart the kernel, run again
  (or set `REID_MODELS = ["dinov2"]` to test only the model you already have).
* Any other error -> send the printed lines; nothing in tracking changes when a test fails.
