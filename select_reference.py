"""
select_reference.py
-------------------
Pick the most appropriate product reference ("base lock") image(s) for each
TOUCHBeauty device spotlighted in a blog article, from the local
`reference_images/<device>/` folders.

It is a deterministic filename-based ranking helper. The agent is expected to
visually confirm the top pick (e.g. with media_read) when the score is close or
ambiguous, then feed the chosen absolute path(s) into the image-generation
prompt as `mode="edit"` reference images.

Usage:
    python select_reference.py TB-1796 TB-2382
    python select_reference.py --top TB-2343 TB-2546
    python select_reference.py --json TB-1767
    python select_reference.py --list

Keys accepted: WooCommerce SKU (TB-1796), product name (Lift2, VITA Laser Comb,
GLAM Mask, ...), or the folder slug (lift2, vita_laser_comb, ...).
"""

import argparse
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REF_ROOT = os.path.join(BASE_DIR, "reference_images")

# folder slug -> list of accepted aliases (lower-cased for matching)
DEVICE_FOLDERS = {
    "revive": ["revive", "tb-1796", "tb1796", "1796"],
    "lift2": ["lift2", "lift 2", "tb-2382", "tb2382", "2382"],
    "trifecta": ["trifecta", "3-in-1", "tb-1767", "tb1767", "1767"],
    "vita_laser_comb": [
        "vita laser comb", "laser comb", "vitacomb", "vita comb",
        "tb-2343", "tb2343", "2343",
    ],
    "vita_helmet": [
        "vita helmet", "scalp rejuvenating helmet", "led helmet", "helmet",
        "tb-2546", "tb2546", "2546",
    ],
    "glam_mask": [
        "glam mask", "glam", "led mask", "light therapy mask",
        "tb-2386", "tb2386", "2386",
    ],
    "hair_trimmer": [
        "nose trimmer", "nose hair trimmer", "hair trimmer", "trimmer",
        "tb-1951", "tb1951", "1951",
    ],
    "eyelash_curler": [
        "eyelash curler", "heated curler", "vita eyelash curler",
        "tb-1859", "tb1859", "1859",
    ],
    "sonic_eye_massager": [
        "eye massager", "sonic eye", "eye/lip massager", "eye lip massager",
        "lip massager", "tb-1583", "tb1583", "1583",
    ],
}

# Filename tokens that signal a clean, product-only base shot -> +score
POSITIVE_TOKENS = {
    "front_facing": 40, "front-facing": 40, "front": 18,
    ".main.": 30, "main": 12,
    "with-cap": 14, "closed": 12, "top": 10,
    "product": 16, "studio": 16, "packshot": 20, "hero": 14,
    "device": 6,
}

# Tokens that signal a crop, part, in-use or marketing overlay -> -score
NEGATIVE_TOKENS = {
    "lifestyle": -45, "model-usage": -50, "model": -35, "usage": -30,
    "in-use": -45, "active": -25, "session": -30, "relax": -30,
    "macro": -40, "comb_head": -40, "comb-head": -40, "bristle": -40,
    "deconstructed": -40, "components": -40, "diagram": -45, "layout": -30,
    "control": -30, "sensor": -30, "indicator": -30, "switch": -30,
    "step_": -25, "step-": -25, "feature_": -20, "feature-": -20,
    "360": -15, "precision": -10, "angled": -12, "back": -8,
    "_n.": -55,  # facebook/instagram scrape pattern (e.g. ..._n.jpg)
    "20250617": -30, "20240530": -30,  # raw timestamped camera dumps
}

# File extension preference (clean studio shots are usually png/webp)
EXT_SCORE = {".png": 10, ".webp": 8, ".jpg": -6, ".jpeg": -6}


def _norm(name: str) -> str:
    return name.lower()


def resolve_folder(query: str):
    """Map a SKU / name / slug query to a folder slug, or None."""
    q = _norm(query).strip()
    if q in DEVICE_FOLDERS:
        return q
    for slug, aliases in DEVICE_FOLDERS.items():
        if q in aliases:
            return slug
    # substring fallback
    for slug, aliases in DEVICE_FOLDERS.items():
        for a in aliases:
            if a and (a in q or q in a):
                return slug
    return None


def score_file(fname: str) -> int:
    n = _norm(fname)
    score = 0
    for tok, pts in POSITIVE_TOKENS.items():
        if tok in n:
            score += pts
    for tok, pts in NEGATIVE_TOKENS.items():
        if tok in n:
            score += pts
    ext = os.path.splitext(n)[1]
    score += EXT_SCORE.get(ext, 0)
    # A bare numeric gallery name like "2382.1.png", "TB-1796_03.png",
    # "2546W.1.webp", "GLAM_Mask_1.png" is almost always a studio product shot.
    stem = os.path.splitext(os.path.basename(n))[0]
    if re.fullmatch(r"[a-z0-9_\-.\s]*\d+", stem) and "lifestyle" not in n:
        score += 15
    return score


def rank_folder(slug: str):
    folder = os.path.join(REF_ROOT, slug)
    if not os.path.isdir(folder):
        return None
    out = []
    for fn in os.listdir(folder):
        full = os.path.join(folder, fn)
        if not os.path.isfile(full):
            continue
        if os.path.splitext(fn)[1].lower() not in EXT_SCORE:
            continue
        out.append({"file": fn, "path": full, "score": score_file(fn)})
    out.sort(key=lambda r: (-r["score"], r["file"].lower()))
    return out


def main():
    ap = argparse.ArgumentParser(description="Rank TOUCHBeauty reference images per device.")
    ap.add_argument("queries", nargs="*", help="SKUs / product names / folder slugs")
    ap.add_argument("--top", action="store_true", help="print only the best pick path per device")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--list", action="store_true", help="list known devices and exit")
    ap.add_argument("-n", "--count", type=int, default=5, help="candidates to show per device (default 5)")
    args = ap.parse_args()

    if args.list or not args.queries:
        print("Known devices (folder slug  <-  accepted keys):")
        for slug, aliases in DEVICE_FOLDERS.items():
            print(f"  {slug:20s}  {', '.join(aliases[:4])}")
        return

    results = {}
    for q in args.queries:
        slug = resolve_folder(q)
        if not slug:
            results[q] = {"error": "unknown device", "folder": None, "candidates": []}
            continue
        ranked = rank_folder(slug)
        if ranked is None:
            results[q] = {"error": f"folder not found: {slug}", "folder": slug, "candidates": []}
            continue
        results[q] = {"folder": slug, "candidates": ranked}

    if args.json:
        print(json.dumps(results, indent=2))
        return

    if args.top:
        for q, r in results.items():
            cands = r.get("candidates") or []
            if not cands:
                print(f"{q}: NO IMAGE ({r.get('error', 'empty')})", file=sys.stderr)
            else:
                print(cands[0]["path"])
        return

    for q, r in results.items():
        print(f"\n=== {q}  ->  folder: {r.get('folder')} ===")
        if r.get("error"):
            print(f"    ERROR: {r['error']}")
            continue
        for i, c in enumerate(r["candidates"][: args.count], start=1):
            tag = "  <-- BEST" if i == 1 else ""
            print(f"    [{c['score']:>4}] {c['file']}{tag}")


if __name__ == "__main__":
    main()
