"""FFmpeg helpers: probe, audio extract, ASS caption burn-in, reframe, thumbnails."""
import json
import pathlib
import subprocess

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
FONT = "DejaVu Sans"  # installed on the VM (fc-list confirmed)
# Font families the VM can actually render (fc-list verified). Anything else
# submitted via the brand-kit form falls back to FONT.
ALLOWED_FONTS = ("DejaVu Sans", "DejaVu Serif", "Liberation Sans",
                 "Liberation Serif", "Noto Sans")


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _hex_to_ass(hex_color: str, default: str = "#FFFFFF") -> str:
    """#RRGGBB -> ASS &H00BBGGRR. Invalid input falls back to default."""
    import re
    c = (hex_color or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
        c = default
    r, g, b = c[1:3], c[3:5], c[5:7]
    return f"&H00{b}{g}{r}"


def probe(path: str) -> dict:
    """Return {'duration_sec', 'width', 'height', 'has_audio'}. Raises on failure."""
    p = _run([FFPROBE, "-v", "error", "-show_entries",
              "format=duration:stream=width,height,codec_type",
              "-of", "json", path])
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr[:300]}")
    info = json.loads(p.stdout or "{}")
    duration = float(info.get("format", {}).get("duration", 0) or 0)
    width = height = 0
    has_audio = False
    for s in info.get("streams", []):
        if s.get("codec_type") == "video" and not width:
            width = int(s.get("width") or 0)
            height = int(s.get("height") or 0)
        if s.get("codec_type") == "audio":
            has_audio = True
    if duration <= 0:
        raise RuntimeError("could not read media duration (corrupt or unsupported file?)")
    return {"duration_sec": duration, "width": width, "height": height, "has_audio": has_audio}


def extract_audio_wav(src: str, dst: str) -> None:
    """16 kHz mono WAV for Whisper."""
    p = _run([FFMPEG, "-y", "-v", "error", "-i", src,
              "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", dst])
    if p.returncode != 0:
        raise RuntimeError(f"audio extract failed: {p.stderr[:300]}")


def _fmt_ass_time(ms: int) -> str:
    s, ms = divmod(max(0, int(ms)), 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}.{ms // 10:02d}"


def make_ass(segments: list[dict], style: dict | None = None) -> str:
    """Build an ASS subtitle file with karaoke word timing.

    segments: [{'start_ms','end_ms','text','word_timings':[{'w','start_ms','end_ms'}],
                'is_keyword'}]
    style: {'uppercase': bool, 'emoji': bool, 'font_size': int,
            'font_family': str (must be in ALLOWED_FONTS),
            'font_color': '#RRGGBB', 'keyword_color': '#RRGGBB'}
    """
    style = style or {}
    uppercase = style.get("uppercase", False)
    emoji = style.get("emoji", False)
    font_size = int(style.get("font_size", 64))
    font_family = style.get("font_family") or FONT
    if font_family not in ALLOWED_FONTS:
        font_family = FONT
    font_color = _hex_to_ass(style.get("font_color", "#FFFFFF"))
    keyword_color = _hex_to_ass(style.get("keyword_color", "#0E7A64"), "#0E7A64")

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Clip,{font_family},{font_size},{font_color},{keyword_color},&H80000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # PrimaryColour = caption text, SecondaryColour = karaoke fill
    lines = [header]
    for seg in segments:
        words = seg.get("word_timings") or []
        text = seg.get("text", "")
        if uppercase:
            text = text.upper()
        if not words:
            # fallback: plain line event
            body = text.replace("\n", "\\N")
            if emoji and seg.get("is_keyword"):
                body = "✨ " + body
            lines.append(
                f"Dialogue: 0,{_fmt_ass_time(seg['start_ms'])},{_fmt_ass_time(seg['end_ms'])},"
                f"Clip,,0,0,0,,{body}"
            )
            continue
        # karaoke: one event per line of up to 6 words
        chunk, chunk_start = [], None
        def flush():
            if not chunk:
                return
            parts = []
            # keyword override colour in {\c&HBBGGRR&} form (strip alpha from ASS colour)
            kw_tag = "{\\c&H" + keyword_color[4:] + "&}"
            for w in chunk:
                dur_cs = max(1, (w["end_ms"] - w["start_ms"]) // 10)
                wt = w["w"].upper() if uppercase else w["w"]
                if emoji and seg.get("is_keyword"):
                    wt = "✨" + wt
                # keyword words get a coloured override
                if seg.get("is_keyword"):
                    parts.append(f"{{\\k{dur_cs}}}{kw_tag}{wt}{{\\c}}")
                else:
                    parts.append(f"{{\\k{dur_cs}}}{wt}")
            body = " ".join(parts)
            lines.append(
                f"Dialogue: 0,{_fmt_ass_time(chunk_start)},{_fmt_ass_time(chunk[-1]['end_ms'])},"
                f"Clip,,0,0,0,,{body}"
            )
        for w in words:
            if chunk_start is None:
                chunk_start = w["start_ms"]
            chunk.append(w)
            if len(chunk) >= 6 or (w["end_ms"] - chunk_start) > 2800:
                flush()
                chunk, chunk_start = [], None
        flush()
    return "\n".join(lines)


def _ass_with_fontsize(ass_text: str, font_size: int) -> str:
    # patch the Style line's Fontsize field (3rd field)
    out = []
    for line in ass_text.split("\n"):
        if line.startswith("Style: Clip,"):
            parts = line.split(",")
            # Style: Clip,Fontname,Fontsize,... -> index: 0='Style: Clip', 1=fontname, 2=fontsize
            if len(parts) > 2:
                parts[2] = str(font_size)
            line = ",".join(parts)
        out.append(line)
    return "\n".join(out)


def render_clip(src: str, start_ms: int, end_ms: int, layout: str,
                ass_path: str | None, out_path: str,
                width: int = 1080, height: int = 1920,
                logo_path: str | None = None,
                smart_plan: tuple | None = None) -> None:
    """Cut [start_ms, end_ms], reframe to width×height, burn ASS captions.

    logo_path: optional local PNG/JPG burned into the top-right corner
    (18% of output width, 40px margin). Missing/unreadable logos are skipped.
    smart_plan: optional (crop_w, crop_h, [(t_sec, x, y), ...]) from
    plan_smart_crop() — the fill layout then tracks the speaker instead of
    centre-cropping. None = classic centre crop.
    """
    start_s = max(0, start_ms / 1000)
    dur_s = max(0.5, (end_ms - start_ms) / 1000)

    if layout == "fit":
        vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
              f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
    elif layout == "split":
        # blurred full-bleed background + centred fit foreground
        vf = (f"split[a][b];[a]scale={width}:{height}:force_original_aspect_ratio=increase,"
              f"crop={width}:{height},gblur=sigma=40[bg];"
              f"[b]scale={width}:{int(height*0.62)}:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2")
    elif smart_plan is not None:  # fill + speaker tracking (crop in src coords)
        cw, ch, traj = smart_plan
        x_expr = _step_expr([(t, x) for t, x, _ in traj])
        y_expr = _step_expr([(t, y) for t, _, y in traj])
        vf = (f"crop={cw}:{ch}:x='{x_expr}':y='{y_expr}',"
              f"scale={width}:{height}")
    else:  # fill (default): scale to cover, centre crop
        vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
              f"crop={width}:{height}")

    if ass_path:
        # escape for filter parser
        esc = ass_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")
        vf += f",ass='{esc}'"

    logo_ok = bool(logo_path) and pathlib.Path(logo_path).exists()
    logo_w = max(64, int(width * 0.18))
    if logo_ok:
        # two inputs -> filter_complex: reframe+captions on [0:v], then overlay logo
        fc = (f"[0:v]{vf},format=yuv420p[base];"
              f"[1:v]scale={logo_w}:-1[logo];"
              f"[base][logo]overlay=(W-w-40):40,format=yuv420p[vout]")
        cmd = [FFMPEG, "-y", "-v", "error", "-ss", f"{start_s:.3f}", "-t", f"{dur_s:.3f}",
               "-i", src, "-i", logo_path,
               "-filter_complex", fc, "-map", "[vout]", "-map", "0:a?",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out_path]
    else:
        cmd = [FFMPEG, "-y", "-v", "error", "-ss", f"{start_s:.3f}", "-t", f"{dur_s:.3f}",
               "-i", src, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out_path]
    p = _run(cmd)
    if p.returncode != 0:
        raise RuntimeError(f"clip render failed: {p.stderr[:400]}")


# ------------------------- smart reframe (speaker tracking) -------------------------
# Face detector: OpenCV DNN res10 SSD. Weights (res10_300x300_ssd_iter_140000.
# caffemodel + deploy.prototxt) are distributed by the OpenCV team via the
# opencv_3rdparty repo for sample use; prototxt is Apache-2.0 (opencv repo).
# Provenance + licensing notes live in replica/build-log.md.
# IMPORTANT: opencv-python must stay on the 4.x line — 5.x removed the Caffe
# importer, and this model is Caffe-format.
MODELS_DIR = pathlib.Path(__file__).resolve().parent / "models"
_FACE_NET = None


def _face_net():
    """Lazily load the DNN face detector. Raises RuntimeError if weights missing."""
    global _FACE_NET
    if _FACE_NET is None:
        import cv2  # lazy: keeps worker import light when detection is unused
        proto = MODELS_DIR / "deploy.prototxt"
        weights = MODELS_DIR / "res10_300x300_ssd_iter_140000.caffemodel"
        if not proto.exists() or not weights.exists():
            raise RuntimeError("face detector weights missing (app/models/)")
        _FACE_NET = cv2.dnn.readNetFromCaffe(str(proto), str(weights))
    return _FACE_NET


def detect_faces_timeline(src: str, start_ms: int, end_ms: int,
                          sample_every_ms: int = 1000,
                          conf_thresh: float = 0.5) -> list:
    """Sample frames across [start_ms, end_ms] and run face detection.

    Returns [(t_ms, [(x1, y1, x2, y2, conf), ...]), ...] in source pixel coords.
    An empty box list means no face in that frame — the caller falls back
    gracefully (never crashes the pipeline).
    """
    import cv2
    net = _face_net()
    info = probe(src)
    sw, sh = info["width"], info["height"]
    cap = cv2.VideoCapture(src)
    try:
        out = []
        t = max(0, start_ms)
        while t < end_ms:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(t))
            ok, frame = cap.read()
            boxes = []
            if ok and frame is not None:
                fh, fw = frame.shape[:2]
                blob = cv2.dnn.blobFromImage(
                    cv2.resize(frame, (300, 300)), 1.0, (300, 300),
                    (104.0, 177.0, 123.0))
                net.setInput(blob)
                det = net.forward()
                sx, sy = sw / fw, sh / fh
                for i in range(det.shape[2]):
                    conf = float(det[0, 0, i, 2])
                    if conf >= conf_thresh:
                        x1, y1, x2, y2 = (det[0, 0, i, 3:7] * [fw, fh, fw, fh])
                        boxes.append((int(x1 * sx), int(y1 * sy),
                                      int(x2 * sx), int(y2 * sy),
                                      round(conf, 3)))
            out.append((t, boxes))
            t += sample_every_ms
    finally:
        cap.release()
    return out


def plan_smart_crop(src_w: int, src_h: int, detections: list,
                    out_w: int = 1080, out_h: int = 1920,
                    smooth_alpha: float = 0.35, t0_ms: int = 0) -> tuple:
    """Turn face detections into a crop-window trajectory for the fill layout.

    detections: [(t_ms, [boxes])] from detect_faces_timeline().
    Returns (crop_w, crop_h, [(t_sec, x, y), ...]) with x/y in source coords
    and t_sec relative to the clip start (t0_ms).

    Multi-speaker rule: if the union of detected faces fits inside the crop
    window, frame all of them; otherwise follow the largest face (ties break
    toward frame centre). The window is EMA-smoothed with a deadband so it
    never jitters; when no face is visible it holds the last position, and it
    falls back to centre when no face was ever seen.

    Honest limit: this tracks FACES, not true active speakers — there is no
    diarization signal (Groq Whisper provides none), so "speaker" here means
    "the most prominent visible face".
    """
    s = max(out_w / src_w, out_h / src_h)  # scale-to-cover factor
    crop_w = int(round(min(src_w, out_w / s)))
    crop_h = int(round(min(src_h, out_h / s)))

    def clamp(v, lo, hi):
        return lo if v < lo else hi if v > hi else v

    cx0, cy0 = src_w / 2, src_h / 2
    ex = int(round(clamp(cx0 - crop_w / 2, 0, src_w - crop_w)))
    ey = int(round(clamp(cy0 - crop_h / 2, 0, src_h - crop_h)))
    deadband = 0.02 * src_w
    traj = []
    for t_ms, boxes in detections:
        target = None
        if boxes:
            if len(boxes) > 1:
                ux1 = min(b[0] for b in boxes)
                uy1 = min(b[1] for b in boxes)
                ux2 = max(b[2] for b in boxes)
                uy2 = max(b[3] for b in boxes)
                if (ux2 - ux1) <= crop_w and (uy2 - uy1) <= crop_h:
                    target = ((ux1 + ux2) / 2, (uy1 + uy2) / 2)
            if target is None:
                b = max(boxes, key=lambda b: ((b[2] - b[0]) * (b[3] - b[1]),
                                              -abs((b[0] + b[2]) / 2 - cx0)))
                target = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
            des_x = int(round(clamp(target[0] - crop_w / 2, 0, src_w - crop_w)))
            des_y = int(round(clamp(target[1] - crop_h / 2, 0, src_h - crop_h)))
        else:
            des_x, des_y = ex, ey  # hold last position; don't whip-pan
        new_x = ex + smooth_alpha * (des_x - ex)
        new_y = ey + smooth_alpha * (des_y - ey)
        if traj and abs(new_x - ex) < deadband:
            new_x = ex
        if traj and abs(new_y - ey) < deadband:
            new_y = ey
        ex, ey = int(round(new_x)), int(round(new_y))
        traj.append(((t_ms - t0_ms) / 1000.0, ex, ey))
    return crop_w, crop_h, traj


def _step_expr(samples: list) -> str:
    """Build a nested if() ffmpeg expression: value holds from each sample
    time until the next. samples: [(t_sec, value), ...]."""
    vals = [(float(t), int(round(v))) for t, v in samples]
    expr = str(vals[-1][1])
    for t, v in reversed(vals[:-1]):
        expr = f"if(lt(t,{t:.3f}),{v},{expr})"
    return expr


def thumbnail(src: str, at_ms: int, out_path: str, width: int = 360) -> None:
    p = _run([FFMPEG, "-y", "-v", "error", "-ss", f"{at_ms/1000:.2f}", "-i", src,
              "-vframes", "1", "-vf", f"scale={width}:-1", out_path])
    if p.returncode != 0:
        raise RuntimeError(f"thumbnail failed: {p.stderr[:200]}")


def write_srt(segments: list[dict], out_path: str) -> None:
    def ts(ms):
        s, ms = divmod(max(0, int(ms)), 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    with open(out_path, "w") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n{ts(seg['start_ms'])} --> {ts(seg['end_ms'])}\n{seg['text']}\n\n")
