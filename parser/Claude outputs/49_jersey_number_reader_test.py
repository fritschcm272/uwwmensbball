# 49_jersey_number_reader_test.py -- code for the notebook section "Jersey-number reader test: which reader can actually read these jerseys? -----------------"
# Runs inside the notebook via run_section("49_jersey_number_reader_test"); its settings are in that notebook cell.

# --- Jersey-number reader test: which reader can actually read these jerseys? ------------------------------------
# CONFIRMED CHANGE (requested: match all 10 players to their numbers). The lineup matching is only as good as the
# jersey readings, and a review of the first 5 Oshkosh possessions showed the first reader was exactly right on
# 5 of 66 crops where the number is plainly readable (it mostly answered "7"). So before tracking trusts ANY
# reader, it is scored here against an answer key of chest crops from those 5 possessions whose numbers were
# read by eye: 66 from the 768-wide frames (21 x18, 15 x12, 11 x9, 24 x7, 4 x7, 0 x7, 32 x4, 10 x2) and 48 from the
# 1024-wide recapture (15 x16, 11 x15, 24 x5, 4 x4, 21 x4, 32, 0, 10, 5). Only crops whose frames are on disk are
# used, so after the 1024 recapture the test runs on the 48. Two readers:
#   easyocr -- the first reader, now on a tight, contrast-boosted crop of the number, read as-is and inverted
#   trocr   -- Microsoft's TrOCR (printed text), ~250 MB downloaded once, same crop
# The best one is used by Player tracking (TRACK_OCR_ENGINE = "auto"), and jersey numbers are only used at all
# if it scores at least TRACK_READER_MIN_ACCURACY there. Results are saved; a rerun doesn't read these again.
# To grow the answer key: add rows to INPUT_DIR/jersey_answer_key.csv (columns: crop, number) -- same crop
# format as below ("<frame file>|x1|y1|x2|y2").
import json as _jn_json
import glob
import numpy as np          # this cell runs before any other cell that imports numpy

# CONFIRMED CHANGE (requested: speed). On the coach's 41 checked players only these earned their place: easyocr_find
# and paddle_find (reliable when confident -- together they're "combined") and the trained recognizer (improves as its
# training set grows). Dropped: easyocr, trocr, easyocr_local, paddle_rec, paddle_color, paddle_color_loose -- any of them
# can be put back in this list to test again (their code is still here).
# "trained" = the jersey-number recognizer trained on your film (the cell above); skipped until it has been trained.
# CONFIRMED CHANGE (requested: make PaddleOCR even more accurate). Two more PaddleOCR readers, scored like the rest:
#   paddle_color       -- the chest crop in COLOR (PaddleOCR learned from color photos; the grey, contrast-boosted crop
#                         was tuned for EasyOCR and can wash out e.g. gold digits on a black jersey)
#   paddle_color_loose -- the same, with a looser text finder (small, curved, partly hidden numbers get found more often;
#                         the test shows whether that costs accuracy)
# CONFIRMED CHANGE (requested: "try PaddleOCR or something similar that is really good at reading numbers" -- every
# EasyOCR/TrOCR variant misses numbers a coach reads at a glance). Two PaddleOCR readers:
#   paddle_find -- PaddleOCR finds AND reads the text on the whole chest (a much stronger text finder than EasyOCR's)
#   paddle_rec  -- PaddleOCR's reader alone, on the number patch the parser finds itself
# One-time install (paddlepaddle + paddleocr, a few hundred MB, then one kernel restart). Works with PaddleOCR 2.x or 3.x.
# CONFIRMED CHANGE (coach review: clearly visible numbers still missed -- the reader's own text finder can't locate
# them). "easyocr_local" first finds the number itself -- the high-contrast digit strokes of the right size on the
# chest (dark on a white jersey, light on a dark one) -- and hands the reader just that patch, turned dark-on-light.
# Coach-checked players (track_validation_*.json) with clearly visible numbers are added to the answer key, so the
# test grows with every batch of checks and is measured on the team's own film.
# CONFIRMED CHANGE (1024 test: easyocr 1/48, trocr 0/48 on numbers readable by eye). Looking at the crops the readers
# were given: the tight crop assumed the number sits dead-center on the chest, but a player turned even a little has
# it off to one side, so "15" lost its 5 and "11" a 1 at the crop's edge (some numbers fell below it entirely).
# "easyocr_find" gives the reader the WHOLE chest and lets EasyOCR's own text finder locate the number first.

# ---- ONE-TIME INSTALL for TrOCR: sentencepiece ------------------------------------------------------------------
# (first TrOCR run failed with "Couldn't instantiate the backend tokenizer ... You need to have sentencepiece or
# tiktoken installed"). Installed here, at the top of this cell, before any reader runs. transformers only notices
# it after a restart, so the cell stops and asks for ONE kernel restart right after installing it.
import importlib
def _jn_paddle_fix_or_skip(e):
    """PaddleOCR's known Anaconda problem ("cannot import name 'tarfile' from 'backports'") can appear at import OR when
    its reader starts -- fix it wherever it shows (install + one restart); anything else: show once, skip this run."""
    globals()["_jn_paddle_ok"] = False
    if "tarfile" in str(e) and "backports" in str(e):
        print("PaddleOCR needs one small fix (backports.tarfile) -- installing it...", flush=True)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "--upgrade", "--force-reinstall",
                               "backports.tarfile", "jaraco.context"])
        globals().pop("_jn_paddle_ok", None)
        raise RuntimeError("Fixed PaddleOCR's missing piece. RESTART THE KERNEL (Kernel > Restart) and run the parser again.")
    print(f"  [numbers] PaddleOCR couldn't start ({type(e).__name__}: {e}) -- its readers are skipped this run", flush=True)


# CONFIRMED BUG (fixed): PaddleOCR's text finder crashed on Windows -- "NotImplementedError: ConvertPirAttribute2Runtime
# Attribute not support ... onednn_instruction.cc" -- a known PaddlePaddle bug in its oneDNN (MKL-DNN) speed-up for Intel
# CPUs. The fix is to switch that speed-up off (slower, but correct). It must be set BEFORE PaddlePaddle first loads, so
# it's here at the top, and PaddleOCR is also told directly (enable_mkldnn=False).
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_pir_api", "0")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")   # skip the slow "checking connectivity" step
# ---- ONE-TIME INSTALL for PaddleOCR --------------------------------------------------------------------------------
if any(e.startswith("paddle") for e in JERSEY_READER_ENGINES) and importlib.util.find_spec("paddleocr") is None:
    print("Installing PaddleOCR (paddlepaddle + paddleocr, a few hundred MB, one time)...", flush=True)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "paddlepaddle", "paddleocr"])
    raise RuntimeError("PaddleOCR was installed. RESTART THE KERNEL (Kernel > Restart) and run the parser again.")
if any(e.startswith("paddle") for e in JERSEY_READER_ENGINES) and importlib.util.find_spec("paddleocr") is not None \
        and "_jn_paddle_ok" not in globals():
    # CONFIRMED BUG (fixed): PaddleOCR installed but wouldn't load -- "cannot import name 'tarfile' from 'backports'"
    # (Anaconda's own backports folder hides the small backports.tarfile package a PaddleOCR helper needs). Try loading
    # it ONCE here: that known error is fixed automatically (install + one restart); any other error is shown once and
    # the PaddleOCR readers are skipped this run (they used to retry the load for every crop).
    try:
        import paddleocr as _paddle_check
        globals()["_jn_paddle_ok"] = True
    except Exception as _e:
        _jn_paddle_fix_or_skip(_e)
if any(e.startswith("paddle") for e in JERSEY_READER_ENGINES) and globals().get("_jn_paddle_ok"):
    try:                                   # PaddleOCR can bring its own OpenCV; make sure the detector's still works
        import cv2 as _cv2_check
        _cv2_check.resize(np.zeros((4, 4), np.uint8), (2, 2))
    except Exception as _e:
        print("!! OpenCV broke after installing PaddleOCR -- run:  %pip install --force-reinstall opencv-contrib-python "
              f"  then restart the kernel ({type(_e).__name__}: {_e})", flush=True)
if "trocr" in JERSEY_READER_ENGINES and importlib.util.find_spec("sentencepiece") is None:
    print("Installing sentencepiece for TrOCR (one time)...", flush=True)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "sentencepiece", "protobuf"])
    raise RuntimeError("sentencepiece was installed. RESTART THE KERNEL (Kernel > Restart) and run the parser again "
                       "-- the text library only notices it after a restart.")
JERSEY_ANSWER_KEY = {
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t003.jpg|33|284|79|391": "24",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t021.jpg|159|295|198|397": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t006.jpg|218|273|256|373": "24",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t010.jpg|289|272|337|369": "24",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t023.jpg|156|294|191|390": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t004.jpg|104|289|144|382": "24",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t037.jpg|347|279|387|370": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t036.jpg|308|285|336|376": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t033.jpg|186|296|223|387": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t024.jpg|169|293|201|384": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t007.jpg|99|286|136|377": "4",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t009.jpg|303|279|335|370": "24",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t038.jpg|361|279|400|369": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t004.jpg|72|297|119|388": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t032.jpg|191|297|226|387": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t028.jpg|145|267|184|357": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t026.jpg|184|257|216|347": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t018.jpg|127|285|157|375": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t006.jpg|137|281|178|370": "4",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t020.jpg|364|266|392|355": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t019.jpg|363|265|391|354": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t005.jpg|163|287|204|376": "24",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t039.jpg|351|273|378|361": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t054.jpg|169|271|199|359": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t057.jpg|146|255|177|342": "0",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t014.jpg|377|294|413|381": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t020.jpg|257|247|291|334": "0",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t016.jpg|319|252|344|339": "0",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t008.jpg|291|283|330|370": "24",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t018.jpg|19|283|53|369": "4",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/3_171c3181_t011.jpg|184|287|218|373": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t052.jpg|168|273|200|359": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t021.jpg|211|286|248|372": "32",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t020.jpg|143|281|172|367": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t015.jpg|383|299|421|384": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/3_171c3181_t012.jpg|240|283|277|368": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/3_171c3181_t000.jpg|170|271|202|356": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t020.jpg|194|293|229|378": "32",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t025.jpg|177|267|205|351": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t019.jpg|173|300|201|384": "32",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t017.jpg|134|299|166|383": "32",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t026.jpg|179|284|215|367": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/4_bc50ccda_t004.jpg|368|285|403|368": "10",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t023.jpg|162|276|198|359": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t022.jpg|151|276|192|359": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/3_171c3181_t006.jpg|183|276|212|358": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/3_171c3181_t004.jpg|173|272|210|354": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/3_171c3181_t001.jpg|175|272|205|354": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/1_1450ff05_t007.jpg|442|268|489|350": "0",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/1_1450ff05_t005.jpg|373|254|399|336": "0",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t021.jpg|123|274|164|355": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t043.jpg|285|254|316|335": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t024.jpg|171|271|202|352": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t021.jpg|149|280|178|361": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t029.jpg|124|273|154|353": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t019.jpg|16|284|64|364": "4",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/3_171c3181_t014.jpg|270|269|295|349": "0",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t022.jpg|118|270|153|349": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t020.jpg|277|294|305|373": "10",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/2_b16e643f_t046.jpg|277|263|305|342": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t055.jpg|153|259|177|337": "0",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t038.jpg|188|243|231|321": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t020.jpg|17|274|53|352": "4",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/5_dd7b5498_t013.jpg|339|295|374|373": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/4_bc50ccda_t004.jpg|502|286|538|364": "4",
"Jan_2_2026_UWOshkosh@UWWhitewater/track/4_bc50ccda_t003.jpg|477|284|508|362": "4",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t041.jpg|223|359|282|512": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/4_bc50ccda_t009.jpg|493|351|544|497": "32",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t022.jpg|48|404|115|546": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t023.jpg|22|410|67|547": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/4_bc50ccda_t008.jpg|204|399|253|533": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/4_bc50ccda_t009.jpg|195|393|247|526": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/1_1450ff05_t013.jpg|401|360|451|493": "24",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t037.jpg|246|401|330|532": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t039.jpg|196|396|241|527": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/4_bc50ccda_t007.jpg|238|403|305|533": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t038.jpg|217|401|263|530": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/1_1450ff05_t007.jpg|80|388|140|516": "24",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t021.jpg|99|395|161|524": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t020.jpg|120|388|183|516": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t040.jpg|203|393|256|522": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/4_bc50ccda_t010.jpg|211|391|249|518": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/4_bc50ccda_t011.jpg|231|364|279|491": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/4_bc50ccda_t006.jpg|302|403|348|528": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/1_1450ff05_t010.jpg|313|371|376|495": "24",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/4_bc50ccda_t019.jpg|254|394|304|518": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t053.jpg|404|379|448|502": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/1_1450ff05_t008.jpg|175|384|227|506": "24",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t054.jpg|462|370|512|491": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t032.jpg|509|395|561|516": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t049.jpg|255|397|301|516": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t055.jpg|480|372|529|491": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/3_171c3181_t007.jpg|570|396|610|515": "4",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/1_1450ff05_t012.jpg|399|376|453|495": "24",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t031.jpg|498|391|547|509": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t023.jpg|183|376|247|494": "4",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/4_bc50ccda_t025.jpg|480|375|528|492": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/4_bc50ccda_t020.jpg|248|396|300|513": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/4_bc50ccda_t024.jpg|476|377|530|495": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t024.jpg|140|381|185|498": "4",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/4_bc50ccda_t003.jpg|477|402|556|520": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/1_1450ff05_t024.jpg|483|356|523|473": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/1_1450ff05_t023.jpg|484|356|521|473": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/3_171c3181_t019.jpg|707|358|733|475": "0",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/3_171c3181_t011.jpg|532|375|565|492": "10",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t043.jpg|238|379|287|495": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t042.jpg|227|383|282|499": "15",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/1_1450ff05_t022.jpg|485|356|523|472": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/4_bc50ccda_t022.jpg|339|386|400|501": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/5_dd7b5498_t003.jpg|512|377|557|492": "5",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/1_1450ff05_t025.jpg|477|358|514|473": "21",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t050.jpg|248|395|298|510": "11",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t035.jpg|23|380|67|494": "4",
"Jan_2_2026_UWOshkosh@UWWhitewater/track1024/2_b16e643f_t056.jpg|470|366|506|480": "11"
}


def _jn_prep(gray, box):
    """The number's crop: middle of the chest, contrast boosted, enlarged, plain margin (review-tuned)."""
    import cv2
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    crop = gray[max(int(y1 + 0.18 * h), 0):max(int(y1 + 0.48 * h), int(y1 + 0.18 * h) + 1),
                max(int(x1 + 0.18 * w), 0):max(int(x2 - 0.18 * w), int(x1 + 0.18 * w) + 1)]
    if crop.size == 0:
        return None
    crop = cv2.resize(crop, (max(8, int(crop.shape[1] * 96.0 / max(crop.shape[0], 1))), 96), interpolation=cv2.INTER_CUBIC)
    crop = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(2, 2)).apply(crop)
    return cv2.copyMakeBorder(crop, 12, 12, 16, 16, cv2.BORDER_CONSTANT, value=int(np.median(crop)))


def _jn_prep_wide(gray, box):
    """The whole chest, wide and tall (for readers that find the number themselves), enlarged ~3x."""
    import cv2
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    crop = gray[max(int(y1 + 0.10 * h), 0):max(int(y1 + 0.62 * h), int(y1 + 0.10 * h) + 1),
                max(int(x1 - 0.05 * w), 0):max(int(x2 + 0.05 * w), int(x1) + 1)]
    if crop.size == 0:
        return None
    crop = cv2.resize(crop, (max(8, int(crop.shape[1] * 3)), max(8, int(crop.shape[0] * 3))), interpolation=cv2.INTER_CUBIC)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(crop)


def _jn_prep_wide_color(img_bgr, box):
    """The whole chest in COLOR, enlarged 3x (no contrast boost) -- for PaddleOCR."""
    import cv2
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    crop = img_bgr[max(int(y1 + 0.10 * h), 0):max(int(y1 + 0.62 * h), int(y1 + 0.10 * h) + 1),
                   max(int(x1 - 0.05 * w), 0):max(int(x2 + 0.05 * w), int(x1) + 1)]
    if crop.size == 0:
        return None
    return cv2.resize(crop, (max(8, crop.shape[1] * 3), max(8, crop.shape[0] * 3)), interpolation=cv2.INTER_CUBIC)


def _jn_needs_color(engine):
    return str(engine).startswith("paddle_color") or engine == "trained"


def _jn_prep_for(engine):
    """Which crop each reader gets (the same choice in the test and in tracking)."""
    if _jn_needs_color(engine):
        return _jn_prep_wide_color
    if str(engine).endswith("_find"):
        return _jn_prep_wide
    if str(engine).endswith(("_local", "_rec")):
        return _jn_prep_local
    return _jn_prep


def _jn_prep_local(gray, box):
    """The number's own patch: digit strokes found on the chest, returned dark-on-light and enlarged (None = not found)."""
    import cv2
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    c = gray[max(int(y1 + 0.12 * h), 0):max(int(y1 + 0.60 * h), int(y1 + 0.12 * h) + 1),
             max(int(x1 - 0.05 * w), 0):max(int(x2 + 0.05 * w), int(x1) + 1)]
    if c.size == 0:
        return None
    c = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(
        cv2.resize(c, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))
    light = float(np.median(c)) > 130                       # white jersey -> dark digits
    ink = 255 - c if light else c
    _t, bw = cv2.threshold(ink, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n, _lab, st, _cen = cv2.connectedComponentsWithStats(bw, 8)
    H, W = bw.shape
    cand = [tuple(st[k][:4]) for k in range(1, n)
            if 0.12 * H <= st[k][3] <= 0.6 * H and st[k][2] <= 0.9 * st[k][3] and st[k][4] >= 0.15 * st[k][2] * st[k][3]
            and 0.1 * W < st[k][0] + st[k][2] / 2 < 0.9 * W]
    if not cand:
        return None
    cand.sort(key=lambda b: -b[3])
    ref = cand[0]
    grp = [b for b in cand if abs((b[1] + b[3] / 2) - (ref[1] + ref[3] / 2)) < 0.35 * ref[3]
           and abs(b[3] - ref[3]) < 0.4 * ref[3] and abs((b[0] + b[2] / 2) - (ref[0] + ref[2] / 2)) < 2.2 * ref[3]][:2]
    gx1, gy1 = min(b[0] for b in grp), min(b[1] for b in grp)
    gx2, gy2 = max(b[0] + b[2] for b in grp), max(b[1] + b[3] for b in grp)
    m = int(0.25 * (gy2 - gy1))
    patch = c[max(0, gy1 - m):min(H, gy2 + m), max(0, gx1 - m):min(W, gx2 + m)]
    patch = patch if light else 255 - patch                   # always dark digits on a light background
    patch = cv2.resize(patch, (max(8, int(patch.shape[1] * 64.0 / max(patch.shape[0], 1))), 64), interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(patch, 10, 10, 14, 14, cv2.BORDER_CONSTANT, value=int(np.median(patch)))


def _jn_paddle(kind):
    """PaddleOCR, loaded once: kind "find" = text finder + reader, "rec" = reader only. Handles PaddleOCR 2.x and 3.x."""
    key = f"_jn_paddle_{kind}"
    if key in globals():
        return globals()[key]
    import logging
    logging.getLogger("ppocr").setLevel(logging.ERROR)
    print(f"  [numbers] loading PaddleOCR ({'reader only' if kind == 'rec' else 'finder + reader'}"
          f"{', looser finder' if kind == 'find_loose' else ''}; models download once)...", flush=True)
    import paddleocr
    m = None
    if kind == "rec" and hasattr(paddleocr, "TextRecognition"):                       # 3.x reader only
        try:
            m = ("v3rec", paddleocr.TextRecognition(enable_mkldnn=False))
        except TypeError:
            m = ("v3rec", paddleocr.TextRecognition())
    elif hasattr(paddleocr.PaddleOCR, "predict"):                                      # 3.x full pipeline
        loose = dict(text_det_thresh=0.2, text_det_box_thresh=0.4, text_det_unclip_ratio=2.0) if kind == "find_loose" else {}
        try:
            m = ("v3", paddleocr.PaddleOCR(lang="en", use_doc_orientation_classify=False, use_doc_unwarping=False,
                                           use_textline_orientation=False, enable_mkldnn=False, **loose))
        except TypeError:
            try:
                m = ("v3", paddleocr.PaddleOCR(lang="en", use_doc_orientation_classify=False, use_doc_unwarping=False,
                                               use_textline_orientation=False))
            except TypeError:
                m = ("v3", paddleocr.PaddleOCR(lang="en"))
    else:                                                                              # 2.x
        loose2 = dict(det_db_thresh=0.2, det_db_box_thresh=0.4, det_db_unclip_ratio=2.0) if kind == "find_loose" else {}
        try:
            m = ("v2", paddleocr.PaddleOCR(use_angle_cls=False, lang="en", show_log=False, enable_mkldnn=False, **loose2))
        except TypeError:
            m = ("v2", paddleocr.PaddleOCR(use_angle_cls=False, lang="en", show_log=False))
    globals()[key] = m
    return m


def _jn_paddle_read(kind, img):
    """-> list of (text, confidence) from one image (grey is turned into 3 channels)."""
    import cv2
    im3 = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img
    ver, m = _jn_paddle(kind)
    out = []
    if ver == "v3rec":
        for r in m.predict(input=im3):
            out.append((str(r["rec_text"]), float(r["rec_score"])))
    elif ver == "v3":
        for r in m.predict(input=im3):
            out += [(str(t), float(c)) for t, c in zip(r["rec_texts"], r["rec_scores"])]
    else:
        res = m.ocr(im3, det=(kind != "rec"), rec=True, cls=False) or []
        for line in res:
            for item in (line or []):
                tc = item[1] if kind != "rec" else item
                out.append((str(tc[0]), float(tc[1])))
    return out


def _jn_digits(txt):
    return re.sub(r"[^0-9]", "", str(txt or ""))[:2]


def _jn_read(engine, crops, polarity=None):
    """Prepared crops -> one (digits, confidence) per crop. polarity: one of "as_is" / "invert" / None per crop
    (None = try both and keep the more confident read)."""
    polarity = polarity or [None] * len(crops)
    import importlib
    out = []
    if engine == "easyocr":
        if importlib.util.find_spec("easyocr") is None:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "easyocr"])
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "python-bidi", "pyclipper", "shapely",
                                   "scikit-image", "ninja", "PyYAML"])
        import easyocr
        rd = globals().get("_trk_ocr") or globals().setdefault("_trk_ocr", easyocr.Reader(["en"], gpu=False, verbose=False))
        for c in crops:
            best = ("", 0.0)
            if c is not None:
                for img in (c, 255 - c):
                    try:
                        for _b, t_, cf in rd.recognize(img, horizontal_list=[[0, img.shape[1], 0, img.shape[0]]], free_list=[],
                                                       allowlist="0123456789", detail=1):
                            if _jn_digits(t_) and cf > best[1]:
                                best = (_jn_digits(t_), float(cf))
                    except Exception:
                        pass
            out.append(best)
        return out
    if engine == "trained":
        res = jersey_recognizer_read(crops) if "jersey_recognizer_read" in globals() else None
        if res is None:
            globals()["_jn_trained_missing"] = True
            return [("", 0.0)] * len(crops)
        return res
    if engine in ("paddle_find", "paddle_rec", "paddle_color", "paddle_color_loose"):
        kind = {"paddle_find": "find", "paddle_rec": "rec", "paddle_color": "find", "paddle_color_loose": "find_loose"}[engine]
        if globals().get("_jn_paddle_ok") is False:
            return [("", 0.0)] * len(crops)
        try:
            _jn_paddle(kind)
        except Exception as _e:
            _jn_paddle_fix_or_skip(_e)                      # the known error: fixed + restart; others: skipped
            return [("", 0.0)] * len(crops)
        for c, pol in zip(crops, polarity):
            best = ("", 0.0)
            if c is not None:
                if kind == "rec" or _jn_needs_color(engine):
                    imgs = [c]                                # the patch is already dark-on-light / a color photo
                else:                                         # tracking knows the jersey: one read, not two
                    imgs = [c] if pol == "as_is" else [255 - c] if pol == "invert" else [c, 255 - c]
                for img in imgs:
                    try:
                        for t_, cf in _jn_paddle_read(kind, img):
                            if _jn_digits(t_) and cf > best[1]:
                                best = (_jn_digits(t_), float(cf))
                    except Exception as _e:
                        if not globals().get("_jn_paddle_warned"):
                            print(f"  [numbers] PaddleOCR read failed ({type(_e).__name__}: {_e})", flush=True)
                            if "onednn" in str(_e).lower() or "mkldnn" in str(_e).lower():
                                print("  [numbers] -> PaddlePaddle's oneDNN bug: RESTART THE KERNEL so the fix at the top of "
                                      "this cell (FLAGS_use_mkldnn=0) is in place before PaddlePaddle loads", flush=True)
                            globals()["_jn_paddle_warned"] = True
                        globals()["_jn_paddle_ok"] = False       # don't save crashed reads as "no answer"
            out.append(best)
        return out
    if engine == "easyocr_local":
        import easyocr
        rd = globals().get("_trk_ocr") or globals().setdefault("_trk_ocr", easyocr.Reader(["en"], gpu=False, verbose=False))
        for c in crops:
            best = ("", 0.0)
            if c is not None:
                try:
                    for _b, t_, cf in rd.recognize(c, horizontal_list=[[0, c.shape[1], 0, c.shape[0]]], free_list=[],
                                                   allowlist="0123456789", detail=1):
                        if _jn_digits(t_) and cf > best[1]:
                            best = (_jn_digits(t_), float(cf))
                except Exception:
                    pass
            out.append(best)
        return out
    if engine == "easyocr_find":
        if importlib.util.find_spec("easyocr") is None:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "easyocr"])
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "python-bidi", "pyclipper", "shapely",
                                   "scikit-image", "ninja", "PyYAML"])
        import easyocr
        rd = globals().get("_trk_ocr") or globals().setdefault("_trk_ocr", easyocr.Reader(["en"], gpu=False, verbose=False))
        for c, pol in zip(crops, polarity):
            best = ("", 0.0)
            if c is not None:
                for img in ([c] if pol == "as_is" else [255 - c] if pol == "invert" else [c, 255 - c]):
                    try:
                        for _b, t_, cf in rd.readtext(img, allowlist="0123456789", detail=1, text_threshold=0.5,
                                                      low_text=0.3, min_size=6, mag_ratio=1.5):
                            if _jn_digits(t_) and cf > best[1]:
                                best = (_jn_digits(t_), float(cf))
                    except Exception:
                        pass
            out.append(best)
        return out
    if engine == "trocr":
        # TrOCR's text decoder needs `sentencepiece` (first run: "Couldn't instantiate the backend tokenizer ...
        # You need to have sentencepiece or tiktoken installed"). transformers only checks for it when it's first
        # loaded, so after installing it the kernel must be restarted once.
        if importlib.util.find_spec("sentencepiece") is None:
            print("  [numbers] installing sentencepiece for TrOCR (one time)...", flush=True)
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "sentencepiece", "protobuf"])
            raise RuntimeError("sentencepiece was installed. RESTART THE KERNEL (Kernel > Restart) and run the parser again "
                               "-- the text library only notices it after a restart.")
        import torch
        from transformers import VisionEncoderDecoderModel, AutoTokenizer
        m = globals().get("_jn_trocr")
        if m is None:
            print(f"  [numbers] loading {JERSEY_TROCR_MODEL} (downloads once)...", flush=True)
            # CONFIRMED BUG (fixed): with sentencepiece installed, loading still failed ("Couldn't instantiate the
            # backend tokenizer ... You need to have sentencepiece or tiktoken installed"). Two causes: the library
            # only checks for sentencepiece when it first loads (a kernel started before the install can't see it),
            # and by default it CONVERTS TrOCR's decoder to a "fast" one, a step with its own requirements. Now:
            # say plainly when a restart is what's needed, and load the plain decoder (no conversion).
            # CONFIRMED BUG (fixed, third try): this transformers version insists on CONVERTING the small TrOCR's
            # SentencePiece vocabulary to a "fast" tokenizer, and that conversion kept failing even with
            # sentencepiece installed and use_fast=False. The library's tokenizer isn't needed at all: the model
            # outputs token numbers, and turning those into text only takes the vocabulary file
            # (sentencepiece.bpe.model) read with sentencepiece directly -- XLM-R style, where token n is
            # SentencePiece piece n-1 and 0-3 are the special tokens.
            import sentencepiece as _spm
            from huggingface_hub import hf_hub_download
            _sp = _spm.SentencePieceProcessor()
            _sp.Load(hf_hub_download(JERSEY_TROCR_MODEL, "sentencepiece.bpe.model"))

            class _SPDecode:
                def batch_decode(self, seqs, skip_special_tokens=True):
                    out_ = []
                    for seq in seqs:
                        ids = [int(x) for x in seq]
                        pieces = [_sp.IdToPiece(t - 1) for t in ids if t > 3 and 0 <= t - 1 < _sp.GetPieceSize()]
                        out_.append("".join(pieces).replace("\u2581", " ").strip())
                    return out_
            _tok = _SPDecode()
            m = globals()["_jn_trocr"] = (VisionEncoderDecoderModel.from_pretrained(JERSEY_TROCR_MODEL).eval(), _tok)
        model, tok = m
        for c in crops:
            best = ("", 0.0)
            if c is not None:
                for img in (c, 255 - c):
                    import cv2
                    rgb = cv2.cvtColor(cv2.resize(img, (384, 384), interpolation=cv2.INTER_CUBIC), cv2.COLOR_GRAY2RGB)
                    x = torch.from_numpy(((rgb.astype(np.float32) / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[None])
                    with torch.no_grad():
                        g = model.generate(pixel_values=x, max_new_tokens=5, output_scores=True, return_dict_in_generate=True)
                    txt = tok.batch_decode(g.sequences, skip_special_tokens=True)[0]
                    try:
                        sc = model.compute_transition_scores(g.sequences, g.scores, normalize_logits=True)
                        cf = float(torch.exp(sc[0]).mean())
                    except Exception:
                        cf = 0.5
                    if _jn_digits(txt) and cf > best[1]:
                        best = (_jn_digits(txt), cf)
            out.append(best)
        return out
    raise ValueError(f"unknown reader {engine!r}")


if RUN_JERSEY_READER_TEST:
    import cv2
    _jn_key = dict(JERSEY_ANSWER_KEY)
    _extra = os.path.join(INPUT_DIR, "jersey_answer_key.csv")
    if os.path.exists(_extra):
        _jn_key.update({str(r["crop"]): str(r["number"]) for _, r in pd.read_csv(_extra, dtype=str).iterrows()})
    _base = VISION_FRAMES_DIR if "VISION_FRAMES_DIR" in globals() else os.path.join(INPUT_DIR, "_vision_frames")
    # coach-checked players with clearly visible numbers join the answer key (their box from the saved detections)
    _n_coach = 0
    _coach_keys = set()
    try:
        # every checks file, merged (coach_checks_all in the Play calls section): the latest check of a box wins
        if "coach_checks_all" not in globals() or "_trk_numbers_for_game" not in globals():
            raise RuntimeError("run the notebook from the Play calls cell (or the whole notebook) first")
        _checks, _vf = coach_checks_all()
        _places = [_play_review_file_saves()]
        _st = {"files": len(_vf), "checks": 0, "numbered": 0, "on_disk": 0, "detected": 0}
        _dets = sorted(glob.glob(os.path.join(INPUT_DIR, "_tracking", "detections_*tiles*.pkl")), key=os.path.getmtime)
        _dets = [d_ for d_ in _dets if "jersey" not in d_]
        _det = pd.read_pickle(_dets[-1]) if _dets else {}
        _nums_by_game = {}
        for _ch in _checks:
            _gd, _gc = str(_ch.get("game") or "|").split("|", 1)
            if (_gd, _gc) not in _nums_by_game:
                _nums_by_game[(_gd, _gc)] = _trk_numbers_for_game(_gd, _gc)
            _nums = _nums_by_game[(_gd, _gc)]
            if True:
                _st["checks"] += 1
                _num = _nums.get(str(_ch.get("true_name") or "").lower())
                if not _num:
                    continue
                _st["numbered"] += 1
                _st["on_disk"] += int(os.path.exists(os.path.join(_base, str(_ch.get("frame_file")))))
                _dd = _det.get(_ch.get("frame_file"))
                if _dd is None or not len(_dd["p"]):
                    continue
                _st["detected"] += 1
                _p = _dd["p"]
                _j = int(np.argmin(np.hypot((_p[:, 0] + _p[:, 2]) / 2 - _ch["px"], _p[:, 3] - _ch["py"])))
                if "_jr_hidden" in globals() and _jr_hidden(_p, _j):
                    continue                           # partly hidden behind someone in front: not a fair answer-key crop
                _x1, _y1, _x2, _y2 = [int(v) for v in _p[_j, :4]]
                _k = f"{_ch['frame_file']}|{_x1}|{_y1}|{_x2}|{_y2}"
                # checks the recognizer TRAINS on can't also grade it
                if globals().get("JERSEY_TRAIN_USE_COACH") == "half" and "_jr_name" in globals() \
                        and _jr_coach_half(_jr_name(_ch["frame_file"], [_x1, _y1, _x2, _y2])) == "train":
                    continue
                _coach_keys.add(_k)
                if _k not in _jn_key:
                    _n_coach += 1
                _jn_key[_k] = _num                     # the merged (latest) check
        print(f"  coach checks: {_st['files']} file(s) found"
              + (f" ({'; '.join(_vf[:3])})" if _vf else f" -- looked in: {'; '.join(_places)}")
              + f"; {_st['checks']} check(s), {_st['numbered']} with a jersey number for the real player, "
              f"{_st['on_disk']} with their frame on disk, {_st['detected']} matched to a saved detection "
              f"(detections file: {os.path.basename(_dets[-1]) if _dets else 'none found'})", flush=True)
    except Exception as _e:
        print(f"  (coach checks not added to the answer key: {type(_e).__name__}: {_e})")
    _cp = os.path.join(INPUT_DIR, "_tracking", "jersey_reader_test.pkl")
    _saved = pd.read_pickle(_cp) if os.path.exists(_cp) else {}
    # CONFIRMED BUG (fixed): the answer-key crops live on the frames they were cut from, and when those frames were
    # deleted (the old track1024 folder) the test found 0 crops and switched jersey numbers off -- although every
    # reader's answers on them were already saved. A crop now counts if its frame is on disk OR every reader's
    # answer for it is saved (a reader's score doesn't need the frame once it's recorded).
    # CONFIRMED BUG (fixed): a crop without its frame needed a saved answer from EVERY reader, so adding a new reader
    # (never run on the old crops) dropped them all -> "0 answer-key crop(s)". Each reader is now scored on the crops it
    # can use: its own saved answers, plus fresh reads wherever the frame is on disk.
    _on = lambda k: os.path.exists(os.path.join(_base, k.split("|")[0]))
    _have = {k: v for k, v in _jn_key.items() if _on(k) or any((e, k) in _saved for e in JERSEY_READER_ENGINES)}
    _on_disk = sum(1 for k in _have if os.path.exists(os.path.join(_base, k.split("|")[0])))
    print(f"Jersey-number reader test: {len(_have)} answer-key crop(s) ({_on_disk} with their frame on disk, "
          f"{len(_have) - _on_disk} from saved answers; {_n_coach} added from coach checks)", flush=True)
    _have_all = _have
    for _eng in JERSEY_READER_ENGINES:
        # a run where PaddleOCR failed to load saved "no answer" for every crop: once it loads, read those again
        if _eng.startswith("paddle") and globals().get("_jn_paddle_ok") and not globals().get(f"_jn_reread_{_eng}"):
            for _kk in [kk for kk in list(_saved) if kk[0] == _eng and not _saved[kk][0]]:
                del _saved[_kk]
            globals()[f"_jn_reread_{_eng}"] = True
        if _eng.startswith("paddle") and globals().get("_jn_paddle_ok") is False:
            print(f"  {_eng:12}: not tested (PaddleOCR didn't start)", flush=True)
            continue
        if _eng == "trained":
            _mp = globals().get("JERSEY_MODEL_PATH", "")
            if not (_mp and os.path.exists(_mp)):
                print(f"  {_eng:12}: not tested (no trained recognizer yet -- see the Jersey-number recognizer cell)", flush=True)
                continue
            _mt = os.path.getmtime(_mp)
            if _saved.get(("__trained_model__", "")) != _mt:          # retrained: its old answers don't count
                for _kk in [kk for kk in list(_saved) if kk[0] == "trained"]:
                    del _saved[_kk]
                _saved[("__trained_model__", "")] = _mt
            if globals().get("JERSEY_TRAIN_USE_COACH") is True:
                print("  trained     : (trained ON your checked players -- its score on them is optimistic)", flush=True)
        _have = {k: v for k, v in _have_all.items() if _on(k) or (_eng, k) in _saved}   # what THIS reader can be scored on
        try:
            _todo = [k for k in _have if (_eng, k) not in _saved and os.path.exists(os.path.join(_base, k.split("|")[0]))]
            if _todo:
                _crops = []
                for k in _todo:
                    rel, x1, y1, x2, y2 = k.split("|")
                    g_ = cv2.imread(os.path.join(_base, rel), cv2.IMREAD_COLOR if _jn_needs_color(_eng) else cv2.IMREAD_GRAYSCALE)
                    _crops.append(_jn_prep_for(_eng)(g_, tuple(float(v) for v in (x1, y1, x2, y2))) if g_ is not None else None)
                _rs = _jn_read(_eng, _crops)
                if _eng.startswith("paddle") and globals().get("_jn_paddle_ok") is False:
                    print(f"  {_eng:12}: not tested (PaddleOCR didn't load)", flush=True)
                    continue
                for k, r_ in zip(_todo, _rs):
                    _saved[(_eng, k)] = r_
                os.makedirs(os.path.dirname(_cp), exist_ok=True)
                pd.to_pickle(_saved, _cp)
            _right = sum(1 for k, v in _have.items() if _saved.get((_eng, k), ("", 0))[0] == v)
            JERSEY_READER_ACCURACY[_eng] = _right / max(len(_have), 1)
            # CONFIRMED CHANGE (1024 test: easyocr_find read 11/48 and its misses were almost all "nothing", not wrong
            # numbers). For naming, what matters is how often it's RIGHT WHEN IT ANSWERS: a track has several chest crops,
            # so a reader that answers one crop in four but is right when it does still names most tracks. Measured
            # here, together with the lowest confidence at which it stays >= JERSEY_READER_TARGET_PRECISION.
            _ans = [(k, v, _saved.get((_eng, k), ("", 0))) for k, v in _have.items() if _saved.get((_eng, k), ("", 0))[0]]
            _best_c = None
            for _c in (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
                _a = [(v, r_) for _k, v, r_ in _ans if r_[1] >= _c]
                if len(_a) >= JERSEY_READER_MIN_ANSWERS and sum(r_[0] == v for v, r_ in _a) / len(_a) >= JERSEY_READER_TARGET_PRECISION:
                    _best_c = _c
                    break
            _c_use = _best_c if _best_c is not None else 0.0
            _a = [(v, r_) for _k, v, r_ in _ans if r_[1] >= _c_use]
            JERSEY_READER_PRECISION[_eng] = (sum(r_[0] == v for v, r_ in _a) / len(_a)) if _a else 0.0
            JERSEY_READER_ANSWERS[_eng] = len(_a)
            JERSEY_READER_CONF[_eng] = _c_use
            _wrong = pd.Series([f"{v}->{r_[0]}" for v, r_ in _a if r_[0] != v]).value_counts().head(4)
            _ck = [k for k in _have if k in _coach_keys]
            _ck_ans = [(k, _saved.get((_eng, k), ("", 0))) for k in _ck if _saved.get((_eng, k), ("", 0))[0]]
            _ck_right = sum(1 for k, r_ in _ck_ans if r_[0] == _have[k])
            JERSEY_READER_COACH_RIGHT[_eng] = _ck_right
            # right / wrong / checked players -- for the brief's METHODOLOGY metrics
            globals().setdefault("JERSEY_READER_COACH_SCORE", {})[_eng] = (_ck_right, len(_ck_ans) - _ck_right, len(_ck))
            print(f"  {_eng:12}: on YOUR {len(_ck)} checked players: {_ck_right} right, "
                  f"{len(_ck_ans) - _ck_right} wrong, {len(_ck) - len(_ck_ans)} no answer", flush=True)
            print(f"  {_eng:12}: [{len(_have)} crops] answered {len(_ans)}/{len(_have)}; right when it answers "
                  f"{JERSEY_READER_PRECISION[_eng]:.0%} ({sum(r_[0] == v for v, r_ in _a)}/{len(_a)} at confidence >= {_c_use:.1f}); "
                  f"wrong answers: {', '.join(f'{a} x{b}' for a, b in _wrong.items()) or 'none'}", flush=True)
            # CONFIRMED CHANGE (requested): right / wrong per jersey number on YOUR checked players, with what each wrong answer
            # was mistaken for -- shows which numbers fail and whether the biases (one number soaking up the answers) are gone.
            try:
                _pn = {}
                for _k_, _r_ in _ck_ans:
                    _t_ = _have[_k_]
                    _d_ = _pn.setdefault(_t_, [0, 0, {}])
                    _d_[1] += 1
                    if _r_[0] == _t_:
                        _d_[0] += 1
                    else:
                        _d_[2][_r_[0]] = _d_[2].get(_r_[0], 0) + 1
                if _pn:
                    _tab = pd.DataFrame([{"number": t_, "checked": d_[1], "right": d_[0], "right_pct": round(100 * d_[0] / d_[1]),
                                          "mistaken_for": ", ".join(f"{a} x{b}" for a, b in sorted(d_[2].items(), key=lambda kv: -kv[1])[:3])}
                                         for t_, d_ in sorted(_pn.items(), key=lambda kv: (-kv[1][1], kv[0]))])
                    _given = pd.Series([r_[0] for _k_, r_ in _ck_ans]).value_counts().head(3)
                    print(f"  {_eng:12}: right / wrong per jersey number on your checked players "
                          f"(answers given most often: {', '.join(f'{a} x{b}' for a, b in _given.items())}):", flush=True)
                    (_show if "_show" in globals() else print)(_tab)
            except Exception as _e2:
                print(f"  (per-number table skipped: {type(_e2).__name__}: {_e2})", flush=True)
        except Exception as _e:
            if "RESTART THE KERNEL" in str(_e):
                raise                                  # an install needs a restart: stop the run and say so
            print(f"  {_eng:8}: not tested ({type(_e).__name__}: {_e})", flush=True)
    # ---- "combined": every RELIABLE reader (>= 80% right when it answers, on >= 6 answers), each at its own confidence
    # level; a crop's reading is used only when all of them that answered AGREE. (41-player test: paddle_find and
    # easyocr_find each read a handful right, not always the same players.) Scored from the saved answers -- no new reads.
    _members = [(e, JERSEY_READER_CONF.get(e, 0.0)) for e in JERSEY_READER_PRECISION if e != "combined"
                and JERSEY_READER_ANSWERS.get(e, 0) >= JERSEY_READER_MIN_ANSWERS and JERSEY_READER_PRECISION[e] >= 0.80]
    if len(_members) >= 2:
        _ck_all = [k for k in _have_all if k in _coach_keys]
        _cmb = {}
        for k in _have_all:
            ans = {_saved.get((e, k), ("", 0))[0] for e, c in _members
                   if _saved.get((e, k), ("", 0))[0] and _saved.get((e, k), ("", 0))[1] >= c}
            if len(ans) == 1:
                _cmb[k] = ans.pop()
        _cr = sum(1 for k in _ck_all if _cmb.get(k) == _have_all[k])
        _cw = sum(1 for k in _ck_all if k in _cmb and _cmb[k] != _have_all[k])
        _all_ans = [k for k in _cmb]
        JERSEY_READER_PRECISION["combined"] = (sum(1 for k in _all_ans if _cmb[k] == _have_all[k]) / len(_all_ans)) if _all_ans else 0.0
        JERSEY_READER_ANSWERS["combined"] = len(_all_ans)
        JERSEY_READER_ACCURACY["combined"] = sum(1 for k in _all_ans if _cmb[k] == _have_all[k]) / max(len(_have_all), 1)
        JERSEY_READER_CONF["combined"] = 0.0
        JERSEY_READER_COACH_RIGHT["combined"] = _cr
        globals()["JERSEY_READER_COMBINED_MEMBERS"] = _members
        print(f"  combined    : ({' + '.join(f'{e} >= {c:.1f}' for e, c in _members)}, used only when they agree)", flush=True)
        print(f"  combined    : on YOUR {len(_ck_all)} checked players: {_cr} right, {_cw} wrong, "
              f"{len(_ck_all) - _cr - _cw} no answer", flush=True)
        print(f"  combined    : [{len(_have_all)} crops] answered {len(_all_ans)}; right when it answers "
              f"{JERSEY_READER_PRECISION['combined']:.0%}", flush=True)
    if JERSEY_READER_PRECISION:
        # CONFIRMED CHANGE (PaddleOCR read 6 of the coach's 18 clearly visible numbers vs 1 for easyocr_find, yet lost
        # because it was chosen by right-when-it-answers first, 86% vs 89%). A reader must be RELIABLE (>= 80% right when
        # it answers, on >= 6 answers); among the reliable ones, the most right answers on the coach-checked players
        # wins (the same crops for every reader) -- then right-when-it-answers.
        _reliable = [e for e in JERSEY_READER_PRECISION if JERSEY_READER_ANSWERS.get(e, 0) >= JERSEY_READER_MIN_ANSWERS
                     and JERSEY_READER_PRECISION[e] >= 0.80]
        _pool = _reliable or ([e for e in JERSEY_READER_PRECISION if JERSEY_READER_ANSWERS.get(e, 0) >= JERSEY_READER_MIN_ANSWERS]
                              or list(JERSEY_READER_PRECISION))
        JERSEY_READER_BEST = max(_pool, key=lambda e: (JERSEY_READER_COACH_RIGHT.get(e, 0), round(JERSEY_READER_PRECISION[e], 2),
                                                       JERSEY_READER_ACCURACY.get(e, 0)))
        print(f"  best reader: {JERSEY_READER_BEST} -- {JERSEY_READER_COACH_RIGHT.get(JERSEY_READER_BEST, 0)} of your checked "
              f"players read right; right {JERSEY_READER_PRECISION[JERSEY_READER_BEST]:.0%} of the time "
              f"it answers ({JERSEY_READER_ANSWERS[JERSEY_READER_BEST]} answers at confidence >= "
              f"{JERSEY_READER_CONF[JERSEY_READER_BEST]:.1f}); answers {JERSEY_READER_ACCURACY[JERSEY_READER_BEST]:.0%} of all crops "
              f"correctly", flush=True)
