#!/usr/bin/env python3
"""
overlay_brand.py — deterministic lifestyle-image post-processing for TOUCHBeauty social.

Adds an elegant, consistent brand overlay to a real lifestyle photo:
  * a corner logo bug (top-left) from a transparent PNG, or a styled wordmark fallback
  * a lower-third gradient scrim carrying an optional headline + the device name
Outputs exact-ratio JPEGs for Instagram/Facebook: 4:5 feed (1080x1350) and 9:16 story (1080x1920).

This is deliberately NOT AI text generation — logos and brand names must be pixel-exact
and repeatable across a batch. Uses Pillow only.

Usage:
  python overlay_brand.py INPUT [--name "VITA Heated Eyelash Curler (TB-1859)"]
         [--headline "Heat, don't crease."] [--logo path/to/logo.png]
         [--sizes 45,916] [--outdir DIR] [--slug my-post] [--focus 0.4]
         [--logo-scale 0.16] [--scrim 200]
         [--fb-caption "..."] [--ig-caption "..."] [--hashtags "#a #b"]
         [--log-csv PATH] [--no-log]

By default the 4:5 overlay is written to portrait-infographics/4x5/ and the 9:16
overlay to portrait-infographics/9x16/ (relative to this script), so PROTOCOL 4
(meta_publish.py) can publish them directly. Pass --outdir to force both into one
folder (e.g. a preview scratch dir).

Each run also appends one row to the continuous lifestyle-post log (default
WP_ImgUpload/lifestyle-social-log.csv), keyed on the 4:5 image filename, recording
slug, device name, headline, both output filenames and the FB/IG captions. Use
--no-log to skip it, or --log-csv to point elsewhere.

INPUT may be a single image file or a folder (batch). For folders, --name/--headline,
if omitted, are read from an optional manifest.csv (slug,name,headline) beside the images.

BATCH MANIFEST MODE (queue many posts, each with its own image + copy, in one run):
   python overlay_brand.py --manifest lifestyle-manifest.csv
Each manifest row is one lifestyle post, tied to a blog article by url_slug so the
device name, headline and FB/IG copy stay in sync with that post's topic + infographic.
Manifest columns (header required):
   image,url_slug,device_name,headline,fb_caption,ig_caption,hashtags,focus,scrim,sizes
   - image       : path to the source lifestyle photo (absolute, or relative to the
                   manifest folder / this script / cwd — first hit wins). REQUIRED.
   - url_slug    : the blog post slug this social set belongs to. REQUIRED (the key).
   - device_name : lower-third device display name (e.g. "VITA Heated Eyelash Curler (TB-1859)").
   - headline    : optional short hook above the name.
   - fb_caption / ig_caption / hashtags : social copy written to the log for this row.
   - focus / scrim / sizes : optional per-row overrides (else the CLI/global defaults).
Logo auto-discovery and the 4x5/9x16 output folders work exactly as in single mode.
"""
import argparse, os, sys, glob, csv, datetime

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    sys.exit("Pillow is required: pip install Pillow")

# ---- brand system ----
CHARCOAL = (26, 32, 44)        # #1a202c
ORANGE   = (255, 118, 64)      # #FF7640
WHITE    = (255, 255, 255)
SIZES = {"45": (1080, 1350), "916": (1080, 1920)}
LOG_HEADER = ["created_date", "url_slug", "device_name", "headline",
              "image_file_45", "image_file_916", "fb_caption", "ig_caption", "hashtags"]
MANIFEST_COLUMNS = ["image", "url_slug", "device_name", "headline",
                    "fb_caption", "ig_caption", "hashtags", "focus", "scrim", "sizes"]
FONT_CANDIDATES_BOLD = [
    r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\calibrib.ttf", "DejaVuSans-Bold.ttf",
]
FONT_CANDIDATES_REG = [
    r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\calibri.ttf", "DejaVuSans.ttf",
]

def load_font(cands, size):
    for c in cands:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()

def crop_to_ratio(im, ratio, focus=0.4):
    W, H = im.size
    cur = W / H
    if cur > ratio:                      # too wide -> trim sides (centered)
        nw = int(H * ratio); left = (W - nw) // 2
        return im.crop((left, 0, left + nw, H))
    nh = int(W / ratio)                  # too tall -> trim top/bottom (focus bias)
    top = int((H - nh) * focus)
    return im.crop((0, top, W, top + nh))

def make_scrim(size, band_frac, max_alpha):
    """Vertical transparent->charcoal gradient over the bottom `band_frac` of the image."""
    w, h = size
    scrim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = scrim.load()
    start = int(h * (1 - band_frac))
    for y in range(start, h):
        t = (y - start) / max(1, (h - start))
        a = int(max_alpha * (t ** 1.35))          # ease-in so the very bottom is densest
        for x in range(w):
            px[x, y] = (CHARCOAL[0], CHARCOAL[1], CHARCOAL[2], a)
    return scrim

def text_w(draw, txt, font):
    b = draw.textbbox((0, 0), txt, font=font)
    return b[2] - b[0]

def wrap(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if text_w(draw, t, font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines

def fit_font(draw, text, cands, size_frac, max_w, cw, max_lines=2):
    """Largest font (from size_frac, shrinking) whose wrapped text fits in max_lines."""
    size = max(16, int(cw * size_frac))
    for _ in range(14):
        f = load_font(cands, size)
        if not text or len(wrap(draw, text, f, max_w)) <= max_lines:
            return f, size
        size = int(size * 0.9)
    return load_font(cands, size), size

def draw_logo(img, logo_path, margin, target_w, shadow=True):
    lg = Image.open(logo_path).convert("RGBA")
    lw, lh = lg.size
    scale = target_w / lw
    lg = lg.resize((int(lw * scale), int(lh * scale)), Image.LANCZOS)
    if shadow:  # soft panel behind an unknown-colour logo for legibility
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        sd.rounded_rectangle([margin - 6, margin - 6,
                              margin + lg.width + 6, margin + lg.height + 6],
                             radius=10, fill=(0, 0, 0, 90))
        sh = sh.filter(ImageFilter.GaussianBlur(6))
        img.alpha_composite(sh)
    img.alpha_composite(lg, (margin, margin))

def corner_luminance(img, margin, w, h):
    """Mean brightness (0-255) of the region where the logo bug will sit."""
    from PIL import ImageStat
    box = (margin, margin, margin + w, margin + h)
    g = img.convert("RGB").crop(box).convert("L")
    return ImageStat.Stat(g).mean[0]

def draw_wordmark(img, draw, margin, font_size):
    f = load_font(FONT_CANDIDATES_BOLD, font_size)
    txt = "TOUCHBeauty"
    # subtle shadow then crisp white wordmark (fallback when no logo PNG supplied)
    draw.text((margin + 2, margin + 2), txt, font=f, fill=(0, 0, 0, 150))
    draw.text((margin, margin), txt, font=f, fill=WHITE + (255,))

def overlay_one(src, out, size_key, name, headline, logo, opts):
    cw, ch = SIZES[size_key]
    ratio = cw / ch
    img = Image.open(src).convert("RGB")
    img = crop_to_ratio(img, ratio, focus=opts.focus)
    img = img.resize((cw, ch), Image.LANCZOS).convert("RGBA")

    band = 0.30 if size_key == "916" else 0.26
    img.alpha_composite(make_scrim((cw, ch), band, opts.scrim))
    draw = ImageDraw.Draw(img)

    margin = int(cw * opts.margin_pct)
    logo_w = int(cw * opts.logo_scale)
    # logo / wordmark (top-left). If a white+orange pair is supplied, auto-pick by
    # the corner's brightness so the bug is legible on any background.
    white = getattr(opts, "logo_white", "") or ""
    orange = getattr(opts, "logo_orange", "") or ""
    if white and orange and os.path.exists(white) and os.path.exists(orange):
        est_h = int(logo_w * 83 / 800) + 2 * margin
        lum = corner_luminance(img, margin, logo_w + 2 * margin, est_h)
        chosen = orange if lum >= 140 else white       # light bg -> orange, dark bg -> white
        draw_logo(img, chosen, margin, logo_w, shadow=False)
    elif logo and os.path.exists(logo):
        draw_logo(img, logo, margin, logo_w, shadow=True)
    else:
        draw_wordmark(img, draw, margin, int(cw * 0.052))

    # lower-third text block, bottom-aligned, word-wrapped + auto-fit (no clipping)
    max_w = cw - 2 * margin
    head_font = head_size = None; head_lines = []
    if headline:
        head_font, head_size = fit_font(draw, headline, FONT_CANDIDATES_REG, 0.040, max_w, cw, 2)
        head_lines = wrap(draw, headline, head_font, max_w)
    name_font = name_size = None; name_lines = []
    if name:
        name_font, name_size = fit_font(draw, name, FONT_CANDIDATES_BOLD, 0.062, max_w, cw, 2)
        name_lines = wrap(draw, name, name_font, max_w)

    pad_bottom = int(ch * 0.055)
    lh_name = int(name_size * 1.20) if name_size else 0
    lh_head = int(head_size * 1.30) if head_size else 0
    y = ch - pad_bottom

    for line in reversed(name_lines):
        y -= lh_name
        draw.text((margin, y), line, font=name_font, fill=WHITE + (255,))
    if name_lines:
        rule_y = y - int(ch * 0.016)
        draw.rectangle([margin, rule_y, margin + int(cw * 0.14), rule_y + int(ch * 0.006)],
                       fill=ORANGE + (255,))
        y = rule_y
    for line in reversed(head_lines):
        y -= lh_head
        draw.text((margin, y), line, font=head_font, fill=(255, 255, 255, 225))

    out_path = os.path.join(out["dir"], f"{out['stem']}{out['suffix']}.jpg")
    img.convert("RGB").save(out_path, "JPEG", quality=90)
    return out_path

def append_log(log_path, row):
    """Append one lifestyle-post row to the continuous log CSV (create with header if missing)."""
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    new = not os.path.exists(log_path) or os.path.getsize(log_path) == 0
    with open(log_path, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        if new:
            w.writerow(LOG_HEADER)
        w.writerow(row)
    return log_path

def resolve_image(raw, base_dirs):
    """Find a manifest image path: absolute, else relative to each base dir (first hit wins)."""
    if os.path.isabs(raw) and os.path.exists(raw):
        return raw
    for b in base_dirs:
        cand = os.path.normpath(os.path.join(b, raw))
        if os.path.exists(cand):
            return cand
    return None

def dir_for(sk, opts, feed_dir, story_dir):
    if opts.outdir:
        return opts.outdir
    return feed_dir if sk == "45" else story_dir

def process_job(job, opts, logo, feed_dir, story_dir, log_path, today, write_log):
    """Overlay one image at its requested sizes + (optionally) append its log row.
    job keys: src, stem, name, headline, fb, ig, tags, focus, scrim, size_keys."""
    import copy
    row_opts = copy.copy(opts)
    if job.get("focus") is not None:
        row_opts.focus = job["focus"]
    if job.get("scrim") is not None:
        row_opts.scrim = job["scrim"]
    produced = {"45": "", "916": ""}
    written = []
    for sk in job["size_keys"]:
        d = dir_for(sk, opts, feed_dir, story_dir)
        os.makedirs(d, exist_ok=True)
        suffix = "-portrait-ig" if sk == "45" else "-story-ig"
        out = {"dir": d, "stem": job["stem"], "suffix": suffix}
        p = overlay_one(job["src"], out, sk, job["name"], job["headline"], logo, row_opts)
        produced[sk] = os.path.basename(p)
        written.append(p)
        print("WROTE", p, SIZES[sk])
    if write_log:
        append_log(log_path, [today, job["stem"], job["name"], job["headline"],
                              produced["45"], produced["916"],
                              job["fb"], job["ig"], job["tags"]])
        print("LOGGED ->", log_path, "|", job["stem"])
    return written, produced

def read_manifest(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh)]
    return rows

def main():
    ap = argparse.ArgumentParser(description="TOUCHBeauty deterministic social overlay (logo + device name).")
    ap.add_argument("input", nargs="?", default="", help="image file or folder (single/folder mode)")
    ap.add_argument("--manifest", default="", help="CSV queue: one lifestyle post per row (batch mode)")
    ap.add_argument("--name", default="", help="device name shown in the lower third")
    ap.add_argument("--headline", default="", help="optional short headline above the name")
    ap.add_argument("--logo", default="", help="single transparent logo PNG (top-left bug)")
    ap.add_argument("--logo-white", default="", help="white wordmark for dark backgrounds")
    ap.add_argument("--logo-orange", default="", help="orange wordmark for light backgrounds")
    ap.add_argument("--sizes", default="45,916", help="comma list of 45 / 916")
    ap.add_argument("--outdir", default="", help="output folder (default: portrait-infographics 4x5/9x16)")
    ap.add_argument("--slug", default="", help="output filename stem (default: input stem)")
    ap.add_argument("--focus", type=float, default=0.4, help="vertical crop bias 0(top)-1(bottom)")
    ap.add_argument("--logo-scale", type=float, default=0.16, help="logo width as fraction of canvas")
    ap.add_argument("--margin-pct", type=float, default=0.055, help="safe margin fraction")
    ap.add_argument("--scrim", type=int, default=200, help="bottom scrim max alpha (0-255)")
    ap.add_argument("--fb-caption", default="", help="Facebook post caption for the log")
    ap.add_argument("--ig-caption", default="", help="Instagram post caption for the log")
    ap.add_argument("--hashtags", default="", help="space-separated hashtags for the log")
    ap.add_argument("--log-csv", default="", help="lifestyle log CSV path (default WP_ImgUpload\\lifestyle-social-log.csv)")
    ap.add_argument("--no-log", action="store_true", help="skip writing to the lifestyle log CSV")
    opts = ap.parse_args()

    if not opts.input and not opts.manifest:
        sys.exit("Provide an INPUT image/folder, or --manifest CSV.")
    if opts.input and opts.manifest:
        sys.exit("Use either INPUT (single/folder mode) or --manifest (batch mode), not both.")

    def parse_sizes(val, default):
        ks = [s.strip() for s in str(val).split(",") if s.strip() in SIZES] if val else []
        return ks or default

    default_keys = [s.strip() for s in opts.sizes.split(",") if s.strip() in SIZES]
    if not default_keys:
        sys.exit("No valid sizes (use 45 and/or 916).")

    here = os.path.dirname(os.path.abspath(__file__))
    feed_dir = os.path.join(here, "portrait-infographics", "4x5")
    story_dir = os.path.join(here, "portrait-infographics", "9x16")
    log_path = opts.log_csv or os.path.join(here, "WP_ImgUpload", "lifestyle-social-log.csv")
    write_log = not opts.no_log
    today = datetime.date.today().isoformat()

    logo = opts.logo or None
    # auto-discover the TOUCHBeauty white/orange wordmarks if not passed explicitly
    if not (opts.logo_white and opts.logo_orange):
        for base in (os.getcwd(), here):
            w = os.path.join(base, "TB_Logo_header.png")   # white
            o = os.path.join(base, "TB_Logo_footer.png")    # orange
            if os.path.exists(w) and os.path.exists(o):
                opts.logo_white, opts.logo_orange = w, o
                break

    jobs = []
    if opts.manifest:
        if not os.path.exists(opts.manifest):
            sys.exit(f"Manifest not found: {opts.manifest}")
        base_dirs = [os.path.dirname(os.path.abspath(opts.manifest)), here, os.getcwd()]
        rows = read_manifest(opts.manifest)
        for i, r in enumerate(rows, 1):
            raw_img = (r.get("image") or "").strip()
            stem = (r.get("url_slug") or "").strip()
            if not raw_img or not stem:
                print(f"SKIP row {i}: image and url_slug are required."); continue
            src = resolve_image(raw_img, base_dirs)
            if not src:
                print(f"SKIP row {i} ({stem}): image not found -> {raw_img}"); continue
            focus = r.get("focus"); scrim = r.get("scrim")
            jobs.append({
                "src": src, "stem": stem,
                "name": (r.get("device_name") or "").strip(),
                "headline": (r.get("headline") or "").strip(),
                "fb": (r.get("fb_caption") or "").strip(),
                "ig": (r.get("ig_caption") or "").strip(),
                "tags": (r.get("hashtags") or "").strip(),
                "focus": float(focus) if str(focus).strip() else None,
                "scrim": int(scrim) if str(scrim).strip() else None,
                "size_keys": parse_sizes(r.get("sizes"), default_keys),
            })
        if not jobs:
            sys.exit("No valid manifest rows to process.")
    else:
        if os.path.isdir(opts.input):
            files = [f for f in glob.glob(os.path.join(opts.input, "*"))
                     if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
        else:
            files = [opts.input]
        if not files:
            sys.exit("No input images found.")
        for f in files:
            stem = opts.slug or os.path.splitext(os.path.basename(f))[0]
            jobs.append({"src": f, "stem": stem, "name": opts.name, "headline": opts.headline,
                         "fb": opts.fb_caption, "ig": opts.ig_caption, "tags": opts.hashtags,
                         "focus": None, "scrim": None, "size_keys": default_keys})

    all_written = []
    for job in jobs:
        w, _ = process_job(job, opts, logo, feed_dir, story_dir, log_path, today, write_log)
        all_written.extend(w)

    targets = sorted(set(os.path.dirname(p) for p in all_written))
    mode = "manifest" if opts.manifest else ("folder" if os.path.isdir(opts.input) else "single")
    print(f"\n[{mode}] {len(jobs)} post(s), {len(all_written)} image(s) -> " + ", ".join(targets))
    if write_log:
        print("LOG:", log_path)
    if opts.logo_white and opts.logo_orange:
        print(f"LOGO: auto-picked by corner brightness -> white={opts.logo_white} orange={opts.logo_orange}")
    elif not logo:
        print("NOTE: no logo found; used the 'TOUCHBeauty' wordmark fallback. "
              "Pass --logo, or --logo-white/--logo-orange (or drop TB_Logo_header.png + TB_Logo_footer.png beside the script).")

if __name__ == "__main__":
    main()
