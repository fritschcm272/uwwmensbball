# UWW Basketball Scouting — Portable (No Databricks)

This is a self-contained version of the UW-Whitewater men's basketball scouting system
that runs entirely outside Databricks. No Spark, no Unity Catalog, no Databricks SDK.

## Project Structure

```
uww-basketball-scouting-portable/
├── README.md                    # This file
├── requirements.txt             # Streamlit app dependencies
├── streamlit_app.py             # Main app (portable — reads from ./data/)
├── .streamlit/
│   └── config.toml              # (copy from original)
├── data/                        # CSV data files (copy from original app)
│   ├── uww_schedule.csv
│   ├── uww_season_stats.csv
│   ├── uww_pbp_events.csv
│   ├── uww_pbp_box_score.csv
│   ├── uww_lineup_stints.csv
│   ├── uww_coaching_flags.csv
│   ├── uww_opponent_rosters.csv
│   ├── uww_player_profiles.csv
│   ├── uww_opponent_game_plans.csv
│   ├── uww_ktv_splits.csv
│   ├── uww_ktv_game_categories.csv
│   ├── uww_opponent_team_totals.csv
│   ├── uww_projected_box_score.csv
│   ├── uww_opponent_projected_box_score.csv
│   ├── uww_player_comparisons.csv
│   ├── uww_opp_lineup_season_box.csv
│   ├── uww_opponent_schedules.csv
│   ├── uww_pbp_derived_keys.csv
│   ├── uww_clutch_events.csv    # Last-5-min/OT, score within 8 -- powers the Analytics, Team, and Previous
│   │                             # Games pages' clutch-performance sections
│   ├── uww_scoring_runs.csv     # Each game's biggest run + largest lead/deficit, with lineups on the floor
│   ├── uww_coach_notes.csv      # Per-clip coach notes (play calls, execution grades) from "*_recap.csv"
│   │                             # inputs -- also merged onto uww_pbp_events.coach_note where a clock/player
│   │                             # match is found, so notes show up inline on the play-by-play tables too
│   ├── name_aliases.json        # Known player-name spelling mismatches between data sources —
│   │                             # shared by streamlit_app.py and the parser, so a fix only has to be made once
│   └── logo/                    # Team logos (PNG)
│       ├── UW-Whitewater.png
│       └── <opponent>.png
├── parser/
│   ├── requirements.txt         # Parser script dependencies
│   ├── player_comparison.py     # Portable comparison algorithms module
│   └── parser_nb.ipynb          # Parser notebook — already portable; convert to parser.py, see below
└── inputs/                      # Raw scouting data (you provide)
    ├── UW-Whitewater - Schedule.mhtml
    ├── <Opponent>_schedule.mhtml
    ├── <date>_<opponent>_scout.pdf
    ├── <date>_<opponent>_pbp.mhtml
    ├── <date>_<opponent>_video.mhtml
    └── <matchup>_recap.csv          # Optional per-game coach-note export (see "Coach Notes" below)
```

## What Was Replaced

| Databricks Feature | Original Usage | Portable Replacement |
|---|---|---|
| `databricks-sdk` (WorkspaceClient) | OAuth token for Foundation Model API | Standard `OPENAI_API_KEY` env var |
| Foundation Model endpoint | `{host}/serving-endpoints` with `databricks-meta-llama-3-3-70b-instruct` | Any OpenAI-compatible API (OpenAI, Azure, Ollama, vLLM) |
| Unity Catalog Volumes | `/Volumes/ads-predictive-analytics/.../inputs/` | Local `./inputs/` directory |
| `spark.createDataFrame` + `spark.sql` with `ai_query()` | LLM player comparison in notebook | Direct OpenAI client calls in `player_comparison.py` |
| `%run` notebook magic | Imports comparison algorithms notebook | Normal `from parser.player_comparison import ...` |
| `display()` | Renders DataFrames in Databricks UI | `print(df)` or Jupyter `display()` |
| `dbutils.library.restartPython()` | Restart after pip install | Not needed (install deps beforehand) |
| Delta table export (`saveAsTable`) | Persists to Unity Catalog | Skipped — CSV export is the only output needed |
| `app.yaml` | Databricks Apps deployment config | Direct `streamlit run` command |

## Quick Start — Streamlit App

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) Set up AI chat — any OpenAI-compatible provider
export OPENAI_API_KEY="sk-..."          # Your API key
export AI_MODEL="gpt-4o-mini"            # Model name (default)
# export OPENAI_BASE_URL="http://localhost:11434/v1"  # For Ollama/local models

# 3. Run the app
streamlit run streamlit_app.py
```

The app will start at http://localhost:8501. All data is read from `./data/*.csv`.
If `OPENAI_API_KEY` is not set, the Home page chat feature shows a friendly error
but all other pages (Upcoming Game, Previous Games, Team, Players) work normally.

## Quick Start — Parser Script

The parser converts raw MHTML/PDF scouting files into the CSV data the app needs.

```bash
cd parser/
pip install -r requirements.txt
playwright install chromium   # one-time browser download, only needed for live opponent scraping

# Set up for LLM-based player comparisons (optional)
export OPENAI_API_KEY="sk-..."
export AI_MODEL="gpt-4o-mini"

# Set up for live opponent-schedule scraping (optional) -- FastScout login, via Hudl's identity provider.
# Without these, every opponent falls back to its local backup "<Opponent> - Schedule.mhtml" file instead.
export FASTSCOUT_USERNAME="you@example.com"
export FASTSCOUT_PASSWORD="your-password"
# Or drop a ".env" file (git-ignored!) in this directory with the same two variables instead of exporting
# them every session -- picked up automatically via python-dotenv.

# Run the parser (you need to convert the notebook to a .py script first — see below)
python parser.py --input-dir ../inputs --output-dir ../data
```

UWW's own schedule always comes from `UW-Whitewater - Schedule.mhtml` in `--input-dir`. Every opponent that
appears in UWW's schedule is scraped live from its FastScout `opponent_url` (requires the credentials
above); if that fails for any reason, the parser falls back to a local `"<Opponent> - Schedule.mhtml"`
backup file in `--input-dir` if one exists, or skips that opponent otherwise.

## Coach Notes (optional per-game recap CSVs)

Drop a `"<matchup>_recap.csv"` file in `--input-dir` for any game to bring in coach-written notes on
individual plays — an offensive play call and how it was executed, or a defensive breakdown of what went
right/wrong on a given possession. This is a per-clip export from the video-tagging tool: one row per
tagged clip, with a `Text Overlay` column holding the note, plus `Pd.` / `Clock` / `Player` / `Team` /
`Result` columns the parser uses to match each note back to its corresponding play-by-play event.

Not every game needs one of these — an opponent with no recap CSV just has no notes, same as any other
optional input. The parser attaches a matched note directly onto that play in `uww_pbp_events.coach_note`
(visible inline on the Previous Games / Team play-by-play tables), and also keeps every note — matched or
not — in its own `uww_coach_notes.csv`, which powers the Analytics page's "Coach-Tagged Play Notes" section
(play-call frequency and make/miss rate, and the most common `+`/`-` flagged themes across all notes).

## Converting the Parser Notebook to a Script

The notebook (`parser_nb.ipynb`, 137 cells) is already fully portable — no Databricks-only APIs
(`dbutils`, `display()`, Spark DataFrames, Unity Catalog Volume paths) remain anywhere in it, and
`INPUT_DIR`/`OUTPUT_DIR`/`USE_LLM`/`reference_date_str` are already plain configurable variables set near the
top of the notebook. The remaining step is mechanical, not a rewrite:

```bash
cd parser/
jupyter nbconvert --to script parser_nb.ipynb --output parser
```

This produces `parser.py`. Open it afterward and:

1. Confirm `INPUT_DIR` / `OUTPUT_DIR` / `USE_LLM` / `reference_date_str` (set near the top of the file) are
   correct for your environment, or wire them up to CLI args / environment variables if you want to run the
   parser non-interactively (e.g. via `argparse` around those four values) instead of editing the script
   before each run.
2. Remove any leftover diagnostic/inspection cells you don't need in production runs — a handful of cells in
   the notebook exist purely to preview intermediate DataFrames while developing (`print(df)` or similar);
   harmless to keep, but noisy in a scheduled/non-interactive run.
3. Run it: `python parser.py --input-dir ../inputs --output-dir ../data`.

No manual cell-by-cell rewriting is needed beyond that.

## Hosting Options

| Option | Cost | Setup |
|---|---|---|
| **Local machine** | Free | Just `streamlit run streamlit_app.py` |
| **Streamlit Community Cloud** | Free | Push to GitHub, connect at share.streamlit.io |
| **Railway / Render** | ~$5/mo | Docker or buildpack deploy |
| **Docker** | Free (local) | See Dockerfile example below |
| **AWS/GCP/Azure VM** | ~$5-20/mo | Install Python, pip, run Streamlit |

### Dockerfile (optional)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

## LLM Provider Options

The AI chat feature (Home page) and player comparison LLM work with any OpenAI-compatible API:

| Provider | OPENAI_BASE_URL | AI_MODEL | Notes |
|---|---|---|---|
| OpenAI | (leave unset) | `gpt-4o-mini` | Default, easiest |
| Azure OpenAI | `https://<resource>.openai.azure.com/openai/deployments/<deploy>/` | Your deployment name | Need Azure SDK or API key |
| Ollama (local) | `http://localhost:11434/v1` | `llama3.1` | Free, runs on your machine |
| vLLM (local) | `http://localhost:8000/v1` | Your model name | High-performance local inference |
| Together AI | `https://api.together.xyz/v1` | `meta-llama/Llama-3-70b-chat-hf` | Pay-per-token cloud |

## Notes

- The app is already 95% portable — it reads all data from local CSV files, not from a database
- The only Databricks dependency in the app was the LLM authentication (WorkspaceClient OAuth)
- The parser's only Spark usage was for Delta table export (redundant with CSV export)
  and `ai_query()` SQL function (replaced with direct OpenAI client calls)
- If you don't need the AI chat or LLM player comparisons, you can skip `openai` entirely
"# uwwmensbball" 
