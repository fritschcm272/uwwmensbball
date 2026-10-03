# 90_model_versions.py -- code for the notebook section "Model versions"
# Runs inside the notebook via run_section("90_model_versions"); no settings.
#
# --- Model versions: which version of each model is in use, named by DATE ---------------------------------------------
# CONFIRMED CHANGE (requested: "track which version each of these models are on ... based on the date that the model was
# trained"). One row per model in <data>/uww_model_versions.csv (what the app shows) and a row added to
# <data>/uww_model_version_history.csv every time a model gets a new version.
#
# Version = vYYYY.MM.DD of the date the model was TRAINED (a second training on the same day: v2026.10.03.2).
#   * Models that learn (kind "trained"): the Tag model (one row per field it predicts, plus an overall row = the newest
#     field) and the Jersey-number recognizer. The date comes from the saved model itself (the Tag model's saved
#     trained_at; the recognizer's checkpoint), so a run that REUSED an unchanged model keeps its old version -- the
#     version only moves when the model is really retrained. Also recorded: how many examples it learned from.
#   * Models that don't learn (kind "pretrained + code" / "rules + code"): Player tracking (pretrained detector, pose and
#     image models), the Jersey-number reader test, Court mapping (plus its calibration files), the Offensive and
#     Defensive role models and the Player comparison. Their "version" is the date their code or model settings last
#     changed (a fingerprint of the script file(s) + the model names/settings is compared to the last run's); first time
#     seen, the newest file's modified date. Any edit to a script, even a comment, starts a new version.
import os
import glob
import json
import hashlib
import pandas as pd


def _mv_files(*names):
    lib = globals().get("PARSER_LIB") or os.path.join(os.getcwd(), "parser_lib")
    out = []
    for n in names:
        out += glob.glob(os.path.join(lib, n + "*.py")) if not n.endswith(".py") else [os.path.join(lib, n)]
    return sorted(set(out))


def _mv_code_fp(files, extra=()):
    h = hashlib.md5()
    for f in files:
        with open(f, "rb") as fh:
            h.update(fh.read())
    h.update(repr(extra).encode())
    newest = max((os.path.getmtime(f) for f in files), default=None)
    return h.hexdigest()[:12], (pd.Timestamp(newest, unit="s") if newest else pd.Timestamp.now())


def _mv_ver(ts):
    return "v" + pd.Timestamp(ts).strftime("%Y.%m.%d")


def model_versions():
    out_dir = globals().get("APP_DATA_DIR") or globals().get("OUTPUT_DIR") or "."
    cur_path = os.path.join(out_dir, "uww_model_versions.csv")
    his_path = os.path.join(out_dir, "uww_model_version_history.csv")
    cur = pd.read_csv(cur_path, dtype=str).fillna("") if os.path.exists(cur_path) else pd.DataFrame()
    his = pd.read_csv(his_path, dtype=str).fillna("") if os.path.exists(his_path) else pd.DataFrame()
    prev = {r["model"]: r for r in cur.to_dict("records")} if not cur.empty else {}
    now = pd.Timestamp.now()
    rows, new_hist = [], []

    def _next_version(model, when, signature):
        base = _mv_ver(when)
        used = [r["version"] for r in (his.to_dict("records") + new_hist) if r["model"] == model and r["version"].split(".")[0:3] == base.split(".")[0:3]]
        return base if not used else f"{base}.{len(used) + 1}"

    def _add(model, kind, signature, when, detail, scripts):
        """signature = what identifies THIS version (trained_at string, or a code fingerprint); a new signature = a new version."""
        p = prev.get(model)
        if p and p.get("signature") == signature:
            ver, dated = p["version"], p["version_date"]
        else:
            ver, dated = _next_version(model, when, signature), pd.Timestamp(when).strftime("%Y-%m-%d")
            new_hist.append({"model": model, "version": ver, "version_date": dated, "kind": kind,
                             "signature": signature, "detail": detail, "recorded": now.isoformat(timespec="seconds")})
        rows.append({"model": model, "kind": kind, "version": ver, "version_date": dated, "signature": signature,
                     "detail": detail, "scripts": scripts, "last_checked": now.isoformat(timespec="seconds")})

    # ---- trained: the Tag model, one row per field ------------------------------------------------------------------
    tag_dir = globals().get("TAG_MODEL_DIR")
    tag_times = []
    if tag_dir and os.path.isdir(tag_dir):
        try:
            import joblib
            for f in sorted(glob.glob(os.path.join(tag_dir, "*.joblib"))):
                field = os.path.splitext(os.path.basename(f))[0]
                try:
                    d = joblib.load(f)
                    t = pd.Timestamp(d.get("trained_at"))
                except Exception:
                    t = pd.Timestamp(os.path.getmtime(f), unit="s")
                    d = {}
                rr = d.get("report_row") or {}
                bits = [f"{rr['tagged_clips']} tagged clips" if rr.get("tagged_clips") not in (None, "") else None,
                        f"{rr['answers_learned']} answers learned" if rr.get("answers_learned") not in (None, "") else None,
                        "one answer only" if d.get("only") is not None and d.get("model") is None else None]
                tag_times.append((t, field))
                _add(f"Tag model: {field}", "trained", t.isoformat(timespec="seconds"), t,
                     ", ".join(b for b in bits if b), "53_tag_model.py")
        except Exception as e:
            print(f"Model versions: Tag model not read ({type(e).__name__}: {e})", flush=True)
    if tag_times:
        t, field = max(tag_times)
        _add("Tag model (overall)", "trained", t.isoformat(timespec="seconds"), t,
             f"newest of {len(tag_times)} field model(s); last retrained field: {field}", "53_tag_model.py")

    # ---- trained: the jersey-number recognizer ----------------------------------------------------------------------
    jp = globals().get("JERSEY_MODEL_PATH")
    if jp and os.path.exists(jp):
        t, detail = pd.Timestamp(os.path.getmtime(jp), unit="s"), ""
        try:
            import torch
            ck = torch.load(jp, map_location="cpu")
            t = pd.Timestamp(ck.get("trained_at") or t)
            detail = (f"{ck.get('n_train', '?')} training crops; {100 * float(ck.get('val_acc', 0)):.0f}% of held-back crops right"
                      + (f"; sources {ck.get('sources')}" if ck.get("sources") else ""))
        except Exception as e:
            detail = f"checkpoint not opened ({type(e).__name__})"
        _add("Jersey-number recognizer", "trained", t.isoformat(timespec="seconds"), t, detail, "48_jersey_number_recognizer.py")

    # ---- pretrained / rule-based: version = when its code or model settings last changed ---------------------------------
    g = globals()
    cal = sorted(glob.glob(os.path.join(g.get("INPUT_DIR") or ".", "court_calibration", "court_calibration_*.json")))
    specs = [
        ("Player tracking", "pretrained + code", ("50_player_tracking",),
         (g.get("TRACK_DETECTOR"), g.get("TRACK_POSE_MODEL"), g.get("TRACK_EMBED_MODEL")),
         f"detector {g.get('TRACK_DETECTOR')}, pose {g.get('TRACK_POSE_MODEL')}, appearance {g.get('TRACK_EMBED_MODEL')} (none retrained)"),
        ("Jersey-number reader test", "pretrained + code", ("49_jersey_number_reader_test",), (), "scores the OCR readers; none retrained here"),
        ("Court mapping", "rules + code", ("51_court_mapping",), tuple((os.path.basename(f), int(os.path.getmtime(f))) for f in cal),
         f"{len(cal)} calibration file(s)"),
        ("Offensive roles", "rules + code", ("41b_offensive_roles",), (), "12 BBall Index-style roles, Division III cut-offs"),
        ("Defensive roles", "rules + code", ("55d_defensive_roles",), (), "7 BBall Index-style roles, Division III cut-offs"),
        ("Player comparison", "rules + code", ("32_load_player_comparison", "33_surface_tag_based", "34_surface_llm", "35_blend_tag_based",
                                               "76_rebuild_player_comparisons"), (g.get("USE_LLM"),),
         f"tag-based similarity; LLM blend {'on' if g.get('USE_LLM') else 'off'}"),
    ]
    for model, kind, names, extra, detail in specs:
        files = _mv_files(*names)
        if not files:
            continue
        fp, newest = _mv_code_fp(files, extra)
        _add(model, kind, fp, newest, detail, ", ".join(os.path.basename(f) for f in files))

    df = pd.DataFrame(rows)
    order = {"trained": 0, "pretrained + code": 1, "rules + code": 2}
    df = df.assign(_o=df["kind"].map(order), _m=~df["model"].str.startswith("Tag model (overall)")).sort_values(["_o", "_m", "model"]).drop(columns=["_o", "_m"])
    os.makedirs(out_dir, exist_ok=True)
    df.to_csv(cur_path, index=False)
    if new_hist:
        pd.concat([his, pd.DataFrame(new_hist)], ignore_index=True).to_csv(his_path, index=False)
    for r in new_hist:
        print(f"Model versions: {r['model']} -> {r['version']}", flush=True)
    print(f"Model versions: {len(df)} model(s) -> {cur_path}" + ("" if new_hist else " (no new versions this run)"), flush=True)
    globals()["model_versions_table"] = df
    return df


model_versions()
