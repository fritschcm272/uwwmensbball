# parser_lib

The code of `parser_nb.ipynb`, one file per notebook section (numbered in notebook order).

* Keep this folder **next to `parser_nb.ipynb`** (the notebook runs from its own folder).
* Each notebook section cell holds only its **settings**, then runs its file with `run_section("<file>")`.
  The file runs inside the notebook, exactly as if its code were still in the cell: every function and table it
  creates is available to the cells after it.
* To change a **setting**: edit it in the notebook cell. To change **how something works**: edit the `.py` file here,
  then rerun that notebook cell (no restart needed -- the file is read fresh every time).
* Errors point to the file and line in here (e.g. `parser_lib\50_player_tracking.py, line 812`).
