"""
VIDEO CODER TAB
===============
Paste this function into streamlit_app.py, then add "Video Coder": render_video_coder
to the _renderers dict inside render_analytics().

Requires:
  - ffmpeg installed on the machine (in PATH)
  - Ollama running locally: https://ollama.com  (ollama serve)
  - A vision model pulled in Ollama, e.g.:
      ollama pull moondream        (best for 8 GB RAM)
      ollama pull llava            (better accuracy, needs 16 GB)

All processing is 100% local. No data leaves the machine.
"""

import base64
import csv
import io
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

import pandas as pd
import streamlit as st


# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "moondream"          # swap to "llava" on 16 GB machines
FRAMES_PER_CLIP = 5                  # frames extracted per possession clip
FRAME_MAX_WIDTH = 960                # pixel width sent to the model

# ---------------------------------------------------------------------------
# CODING SYSTEM — injected as the system prompt for every classification
# ---------------------------------------------------------------------------

CODING_SYSTEM_PROMPT = """You are an expert basketball play coder. Analyze the video frames
of a single basketball possession and assign the correct code using the system below.

## OUTPUT — respond ONLY with this JSON, no other text:
{"title": "<coded title>", "confidence": "high|medium|low", "reasoning": "<one sentence>"}

## CODING FORMAT
Offensive formation - Offensive Play(Offensive Play Information) : Press(Press Type) - Defensive Type(Defensive Play Information)
- No press → use ": -" before defensive type
- No offensive play name → all info in parentheses: Formation - (info-details)

## OFFENSIVE FORMATIONS
5 out | Horns | Twins | Blob | Slob | Tran | Flow/Motion | 41 | Pinch | Stagger | Guards Cross

## OFFENSIVE PLAYS (capitalized = named play)
- BS / Ball Screen : ALWAYS include BS as first item in details → BS(BS, detail, ...)
- Pass, UCLA, Back Screen, Flair, Zoom (no play name → all goes into parentheses)

## OFFENSIVE PLAY INFORMATION (details inside parentheses)
ds | bs | reject | curl | flair | slip | post | b | zoom | pass 5 | pass wing | stagger

## DEFENSIVE TYPES
m2m | zone | hybrid

## PRESS TYPES
Press(M2M) | Press(R+J) | Press(Zone)

## DEFENSIVE DETAILS
drop | switch | hedge | hard hedge | under | H and D | Deny | BLOB

## NOTES
- Drop single-letter modifiers (D, H, etc.) and team designators (UWW) from defensive codes
- "UWW m2m D" → "m2m"
- Flow and Motion are offensive plays, not formations
"""

# ---------------------------------------------------------------------------
# FEW-SHOT EXAMPLES — loaded from already-coded clips
# ---------------------------------------------------------------------------

def _load_few_shot_examples(coded_csv_path: str, max_examples: int = 8) -> str:
    """Read already-coded rows from a CSV and format them as few-shot context."""
    if not coded_csv_path or not os.path.exists(coded_csv_path):
        return ""
    try:
        df = pd.read_csv(coded_csv_path)
        # Only rows that have a non-empty Title
        df = df[df["Title"].notna() & (df["Title"].str.strip() != "")]
        if df.empty:
            return ""
        # Sample a spread of examples
        sample = df.sample(min(max_examples, len(df)), random_state=42)
        lines = ["## EXAMPLE CODINGS FROM YOUR EXISTING LIBRARY\n"]
        for _, row in sample.iterrows():
            lines.append(f"Result: {row.get('Result', '')} | Player: {row.get('Player', '')} | "
                         f"Synergy: {row.get('Synergy String', '')}")
            lines.append(f"→ Title: {row['Title']}\n")
        return "\n".join(lines)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# FRAME EXTRACTION (local, ffmpeg)
# ---------------------------------------------------------------------------

def _extract_frames(video_path: str, n_frames: int = FRAMES_PER_CLIP,
                    max_width: int = FRAME_MAX_WIDTH) -> list[str]:
    """
    Extract n_frames evenly-spaced frames from video_path into a temp directory.
    Returns list of absolute paths to JPEG files.
    """
    tmp_dir = tempfile.mkdtemp(prefix="uww_coder_")

    # Get duration
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
        capture_output=True, text=True, check=True,
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])

    start = min(1.0, duration * 0.1)
    end = max(0.0, duration - 1.0)
    if end <= start:
        start, end = 0.0, duration

    timestamps = [start + (end - start) * i / (n_frames - 1) for i in range(n_frames)]

    paths = []
    for idx, ts in enumerate(timestamps):
        out = os.path.join(tmp_dir, f"frame_{idx+1:02d}.jpg")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "quiet",
             "-ss", str(ts), "-i", video_path,
             "-frames:v", "1", "-vf", f"scale={max_width}:-1",
             "-q:v", "3", out],
            check=True,
        )
        paths.append(out)
    return paths


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# OLLAMA CALL (local)
# ---------------------------------------------------------------------------

def _call_ollama(model: str, frame_paths: list[str], metadata: dict,
                 few_shot: str = "") -> dict:
    """
    Send frames + metadata to a locally running Ollama vision model.
    Returns {"title": ..., "confidence": ..., "reasoning": ...}
    """
    system = CODING_SYSTEM_PROMPT
    if few_shot:
        system += "\n\n" + few_shot

    # Build the user message: images first, then text
    images_b64 = [_encode_image(p) for p in frame_paths]

    user_text = f"""Analyze these {len(frame_paths)} frames (start → end of the possession) and code the play.

METADATA:
- Game: {metadata.get('Game', '')}
- Team (offense): {metadata.get('Team', '')}
- Player: {metadata.get('Player', '')}
- Result: {metadata.get('Result', '')}
- Duration: {metadata.get('Duration', '')}s
- Period: {metadata.get('Pd.', '')}, Clock: {metadata.get('Clock', '')}
- Synergy auto-tag: {metadata.get('Synergy String', '')}

Return ONLY the JSON object described in the system prompt."""

    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text, "images": images_b64},
        ],
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=req_data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    raw = body.get("message", {}).get("content", "").strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"title": raw, "confidence": "low", "reasoning": "JSON parse error"}


# ---------------------------------------------------------------------------
# OLLAMA HEALTH CHECK
# ---------------------------------------------------------------------------

def _ollama_running() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434", timeout=2)
        return True
    except Exception:
        return False


def _available_ollama_models() -> list[str]:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            data = json.loads(r.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# MAIN RENDER FUNCTION
# ---------------------------------------------------------------------------

def render_video_coder():
    """Video Coder tab — fully local play classification using Ollama vision models."""

    st.markdown("### 🎬 Video Coder")
    st.caption(
        "Automatically code basketball possessions from Synergy export CSV + video clips. "
        "100% local — no data leaves this machine."
    )

    # --- Ollama status banner ---
    ollama_ok = _ollama_running()
    if ollama_ok:
        available_models = _available_ollama_models()
        vision_models = [m for m in available_models
                         if any(v in m.lower() for v in ["llava", "moondream", "bakllava", "vision"])]
        if vision_models:
            st.success(f"✅ Ollama running · Vision models available: {', '.join(vision_models)}")
        else:
            st.warning(
                "⚠️ Ollama is running but no vision models are installed. "
                "Run `ollama pull moondream` in a terminal, then refresh."
            )
    else:
        st.error(
            "❌ Ollama is not running. "
            "Start it with `ollama serve` in a terminal, then refresh this page."
        )
        with st.expander("📦 First-time setup instructions"):
            st.markdown("""
**1. Install Ollama**
Download from [ollama.com](https://ollama.com) and run the installer.

**2. Start Ollama**
```
ollama serve
```

**3. Pull a vision model**

For 8 GB RAM machines:
```
ollama pull moondream
```
For 16 GB RAM machines (better accuracy):
```
ollama pull llava
```

**4. Refresh this page.**
""")
        return   # Nothing else to show until Ollama is up

    st.divider()

    # --- Configuration ---
    with st.expander("⚙️ Configuration", expanded=not st.session_state.get("vc_configured")):
        col1, col2 = st.columns(2)
        with col1:
            model_options = vision_models if vision_models else [DEFAULT_MODEL]
            selected_model = st.selectbox(
                "Vision model",
                model_options,
                index=0,
                key="vc_model",
                help="moondream = faster, less RAM. llava = slower, more accurate.",
            )
            n_frames = st.slider(
                "Frames per clip", min_value=3, max_value=8, value=FRAMES_PER_CLIP,
                key="vc_n_frames",
                help="More frames = more accurate but slower. 5 works well for most possessions.",
            )
        with col2:
            clips_dir = st.text_input(
                "Clips folder path",
                placeholder=r"C:\Users\You\Desktop\clips",
                key="vc_clips_dir",
                help="Folder containing video files named by their # from the CSV (e.g. 1.mp4, 2.mp4).",
            )
            coded_csv_path = st.text_input(
                "Already-coded CSV (optional, improves accuracy)",
                placeholder=r"C:\Users\You\Desktop\coded_plays.csv",
                key="vc_coded_csv",
                help="A CSV with correct Titles already filled in. Used as few-shot examples.",
            )

        if clips_dir and os.path.isdir(clips_dir):
            st.success(f"✅ Clips folder found")
            st.session_state["vc_configured"] = True
        elif clips_dir:
            st.error(f"❌ Folder not found: {clips_dir}")

    st.divider()

    # --- File upload ---
    st.markdown("#### 1. Upload Synergy Export CSV")
    uploaded_csv = st.file_uploader(
        "Drop your Synergy export here",
        type=["csv"],
        key="vc_upload",
        help="The CSV exported from Synergy with columns: #, Title, Notes, Result, Player, etc.",
    )

    if not uploaded_csv:
        st.info("Upload a Synergy export CSV to get started.")
        return

    # Parse the CSV
    try:
        df = pd.read_csv(uploaded_csv)
        df["#"] = df["#"].astype(str).str.strip()
    except Exception as e:
        st.error(f"Could not read CSV: {e}")
        return

    st.success(f"✅ {len(df)} possessions loaded")

    # Preview
    with st.expander("Preview CSV", expanded=False):
        st.dataframe(df[["#", "Title", "Player", "Result", "Duration", "Synergy String"]].head(10),
                     use_container_width=True)

    clips_dir = st.session_state.get("vc_clips_dir", "").strip()
    if not clips_dir or not os.path.isdir(clips_dir):
        st.warning("Set the clips folder path in Configuration above before running.")
        return

    st.divider()
    st.markdown("#### 2. Run Classification")

    col_run, col_skip = st.columns([2, 3])
    with col_run:
        only_empty = st.checkbox(
            "Only code rows with empty Title",
            value=True,
            key="vc_only_empty",
            help="Skip rows that already have a coded title.",
        )
    with col_skip:
        st.caption(
            f"Clips folder: `{clips_dir}`  ·  "
            f"Model: `{st.session_state.get('vc_model', DEFAULT_MODEL)}`  ·  "
            f"Frames: `{st.session_state.get('vc_n_frames', FRAMES_PER_CLIP)}`"
        )

    rows_to_code = df.copy()
    if only_empty:
        rows_to_code = rows_to_code[
            rows_to_code["Title"].isna() | (rows_to_code["Title"].str.strip() == "")
        ]

    st.info(f"{len(rows_to_code)} possession(s) to code.")

    if st.button("▶️ Start Coding", type="primary", key="vc_run",
                 disabled=not ollama_ok or len(rows_to_code) == 0):

        model = st.session_state.get("vc_model", DEFAULT_MODEL)
        n_frames = st.session_state.get("vc_n_frames", FRAMES_PER_CLIP)
        coded_csv = st.session_state.get("vc_coded_csv", "").strip()
        few_shot = _load_few_shot_examples(coded_csv, max_examples=8)

        progress_bar = st.progress(0)
        status_text = st.empty()
        results_placeholder = st.empty()

        results = []   # list of dicts, one per coded row

        for i, (_, row) in enumerate(rows_to_code.iterrows()):
            clip_num = row["#"]
            status_text.markdown(
                f"**Coding clip #{clip_num}** ({i+1}/{len(rows_to_code)}) — "
                f"{row.get('Player', '')} · {row.get('Result', '')}"
            )

            # Find clip file
            clip_path = None
            for ext in [".mp4", ".mov", ".avi", ".mkv"]:
                candidate = os.path.join(clips_dir, f"{clip_num}{ext}")
                if os.path.exists(candidate):
                    clip_path = candidate
                    break

            if not clip_path:
                results.append({
                    "row_index": row.name,
                    "clip": clip_num,
                    "suggested_title": "",
                    "confidence": "no_video",
                    "reasoning": f"No video file found for #{clip_num}",
                    "original_title": row.get("Title", ""),
                    "player": row.get("Player", ""),
                    "result": row.get("Result", ""),
                })
                progress_bar.progress((i + 1) / len(rows_to_code))
                continue

            # Extract frames
            try:
                frame_paths = _extract_frames(clip_path, n_frames=n_frames)
            except Exception as e:
                results.append({
                    "row_index": row.name,
                    "clip": clip_num,
                    "suggested_title": "",
                    "confidence": "error",
                    "reasoning": f"Frame extraction failed: {e}",
                    "original_title": row.get("Title", ""),
                    "player": row.get("Player", ""),
                    "result": row.get("Result", ""),
                })
                progress_bar.progress((i + 1) / len(rows_to_code))
                continue

            # Call Ollama
            try:
                response = _call_ollama(model, frame_paths, dict(row), few_shot=few_shot)
                results.append({
                    "row_index": row.name,
                    "clip": clip_num,
                    "suggested_title": response.get("title", ""),
                    "confidence": response.get("confidence", "unknown"),
                    "reasoning": response.get("reasoning", ""),
                    "original_title": row.get("Title", ""),
                    "player": row.get("Player", ""),
                    "result": row.get("Result", ""),
                    "frame_paths": frame_paths,
                })
            except Exception as e:
                results.append({
                    "row_index": row.name,
                    "clip": clip_num,
                    "suggested_title": "",
                    "confidence": "error",
                    "reasoning": f"Ollama error: {e}",
                    "original_title": row.get("Title", ""),
                    "player": row.get("Player", ""),
                    "result": row.get("Result", ""),
                })

            progress_bar.progress((i + 1) / len(rows_to_code))
            time.sleep(0.2)

        status_text.markdown("✅ **Classification complete!** Review suggestions below.")
        st.session_state["vc_results"] = results
        st.session_state["vc_df"] = df

    # --- REVIEW UI ---
    if "vc_results" not in st.session_state or not st.session_state["vc_results"]:
        return

    results = st.session_state["vc_results"]
    df = st.session_state["vc_df"]

    st.divider()
    st.markdown("#### 3. Review & Approve")

    # Summary metrics
    total = len(results)
    high_conf = sum(1 for r in results if r["confidence"] == "high")
    med_conf = sum(1 for r in results if r["confidence"] == "medium")
    errors = sum(1 for r in results if r["confidence"] in ("error", "no_video"))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total coded", total)
    m2.metric("High confidence", high_conf)
    m3.metric("Medium confidence", med_conf)
    m4.metric("Errors / missing", errors)

    st.caption("Edit any title below, then click **Accept** to apply it to the output CSV.")

    # Per-result review cards
    accepted_titles = {}   # row_index -> final title

    for r in results:
        conf = r["confidence"]
        conf_color = {"high": "#2e7d32", "medium": "#e65100", "low": "#c62828"}.get(conf, "#888")
        conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(conf, "⚪")

        with st.container():
            # Card header
            st.markdown(
                f'<div style="background:#1a1a2e;border-radius:8px;padding:10px 16px;margin-bottom:4px;">'
                f'<span style="color:#fff;font-weight:700;">Clip #{r["clip"]}</span>'
                f'&nbsp;&nbsp;<span style="color:#9DAAAC;font-size:0.9rem;">{r["player"]} · {r["result"]}</span>'
                f'&nbsp;&nbsp;<span style="color:{conf_color};font-size:0.85rem;">{conf_icon} {conf.upper()}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            col_frames, col_review = st.columns([3, 2])

            with col_frames:
                # Show extracted frames
                frame_paths = r.get("frame_paths", [])
                if frame_paths:
                    n = len(frame_paths)
                    frame_cols = st.columns(n)
                    for fi, (fc, fp) in enumerate(zip(frame_cols, frame_paths)):
                        if os.path.exists(fp):
                            fc.image(fp, caption=f"Frame {fi+1}", use_container_width=True)
                else:
                    st.caption(f"⚠️ {r['reasoning']}")

            with col_review:
                st.markdown(f"**Reasoning:** *{r['reasoning']}*")
                st.markdown(f"**Original title:** `{r['original_title'] or '(empty)'}`")

                # Editable suggested title
                edited = st.text_input(
                    "Suggested title (edit if needed)",
                    value=r["suggested_title"],
                    key=f"vc_edit_{r['row_index']}",
                )

                accept_key = f"vc_accept_{r['row_index']}"
                if st.button("✅ Accept", key=accept_key, type="primary"):
                    accepted_titles[r["row_index"]] = edited
                    st.success("Accepted!")

            st.divider()

    # Accept All button
    st.markdown("---")
    col_all, col_dl = st.columns(2)
    with col_all:
        if st.button("✅ Accept All Suggestions", key="vc_accept_all"):
            for r in results:
                accepted_titles[r["row_index"]] = st.session_state.get(
                    f"vc_edit_{r['row_index']}", r["suggested_title"]
                )
            st.session_state["vc_accepted"] = accepted_titles
            st.success(f"Accepted {len(accepted_titles)} titles!")

    # Persist individual accepts into session state
    if accepted_titles:
        existing = st.session_state.get("vc_accepted", {})
        existing.update(accepted_titles)
        st.session_state["vc_accepted"] = existing

    # --- Export ---
    accepted = st.session_state.get("vc_accepted", {})
    if accepted:
        # Apply accepted titles back to the dataframe
        output_df = df.copy()
        for row_idx, title in accepted.items():
            output_df.at[row_idx, "Title"] = title

        csv_buffer = io.StringIO()
        output_df.to_csv(csv_buffer, index=False)
        csv_bytes = csv_buffer.getvalue().encode("utf-8")

        with col_dl:
            st.download_button(
                label=f"⬇️ Download Updated CSV ({len(accepted)} titles applied)",
                data=csv_bytes,
                file_name="coded_output.csv",
                mime="text/csv",
                type="primary",
                key="vc_download",
            )
        st.caption(
            f"{len(accepted)}/{len(results)} titles accepted · "
            "Download the CSV and re-import to Synergy."
        )
