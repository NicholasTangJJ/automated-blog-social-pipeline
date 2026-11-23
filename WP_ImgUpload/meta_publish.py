"""
meta_publish.py
---------------
Automate Meta (Facebook + Instagram) posting/scheduling of TOUCHBeauty social
infographics, driven by meta-posts-to-schedule.csv.

Feed posts   -> 3:4 portrait (portrait-infographics\\3x4\\...-portrait-ig.webp)
Stories      -> 9:16        (portrait-infographics\\9x16\\...-story-ig.webp)

Credentials & IDs come from .env (see META_SETUP_GUIDE.md).
Instagram images must be publicly reachable: if no image_url is given, the local
image_file is uploaded to WordPress media (same .env WP creds) and its source_url
is used.

Usage (from WP_ImgUpload):
    python meta_publish.py --dry-run     # validate tokens + print planned API calls
    python meta_publish.py               # execute per the CSV `action` column
"""

import base64
import csv
import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
import requests

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:  # pragma: no cover
    ZoneInfo = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

GRAPH_VER = os.getenv("META_GRAPH_VERSION", "v21.0")
GRAPH = f"https://graph.facebook.com/{GRAPH_VER}"

PAGE_ID = os.getenv("META_PAGE_ID")
PAGE_TOKEN = os.getenv("META_PAGE_ACCESS_TOKEN")
IG_ID = os.getenv("META_IG_USER_ID")
IG_TOKEN = os.getenv("META_IG_ACCESS_TOKEN") or PAGE_TOKEN
TZ = os.getenv("META_TZ", "Asia/Singapore")

CSV_FILE = os.path.join(BASE_DIR, "meta-posts-to-schedule.csv")
IMAGES_SUBFOLDER = os.path.join(BASE_DIR, "Images")

# WordPress hosting (reuse the existing WP creds) for Instagram public URLs
WP_URL = os.getenv("WP_URL", "https://www.touchbeauty.com.sg/wp-json/wp/v2")
WP_USER = os.getenv("WP_USERNAME")
WP_PASS = os.getenv("WP_APP_PASSWORD")

# Portrait social infographics live under the project portrait folders (4:5 feed, 9:16 story)
PORTRAIT_45 = os.path.join(BASE_DIR, "..", "portrait-infographics", "4x5")
PORTRAIT_916 = os.path.join(BASE_DIR, "..", "portrait-infographics", "9x16")


def wp_headers():
    tok = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode("utf-8")
    return {"Authorization": f"Basic {tok}"}


def find_local_image(file_name):
    """Locate the image in Images/ then the portrait 4x5 / 9x16 folders."""
    for folder in (IMAGES_SUBFOLDER, PORTRAIT_45, PORTRAIT_916):
        p = os.path.abspath(os.path.join(folder, file_name))
        if os.path.isfile(p):
            return p
    return None


def ensure_jpeg(local_path):
    """Instagram's Content Publishing API is JPEG-only (webp/PNG -> error 36001).
    Return a JPEG path, re-encoding losslessly with Pillow if the source isn't JPEG."""
    ext = os.path.splitext(local_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        return local_path
    try:
        from PIL import Image
    except ImportError:
        print("    -> ERROR: source is not JPEG and Pillow is unavailable to convert it.")
        return None
    out = os.path.join(IMAGES_SUBFOLDER, os.path.splitext(os.path.basename(local_path))[0] + ".jpg")
    os.makedirs(IMAGES_SUBFOLDER, exist_ok=True)
    Image.open(local_path).convert("RGB").save(out, "JPEG", quality=90)
    print(f"    -> Re-encoded to JPEG (Instagram is JPEG-only): {os.path.basename(out)}")
    return out


def check_ig_feed_ratio(local_path):
    """Instagram feed API only accepts aspect ratios within 4:5 (0.8) to 1.91. Warn otherwise."""
    try:
        from PIL import Image
    except ImportError:
        return
    try:
        w, h = Image.open(local_path).size
        ratio = w / h
        if not (0.8 <= ratio <= 1.91):
            print(f"    -> WARNING: IG feed ratio {ratio:.2f} is outside 4:5-1.91:1 (e.g. 3:4=0.75 fails). "
                  f"Instagram will reject this feed image (error 36003). Use a 4:5 render.")
    except Exception:
        pass


def host_image_to_wp(local_path):
    """Upload a local image to WordPress media and return its public source_url."""
    if not (WP_USER and WP_PASS):
        print("    -> ERROR: WP creds missing in .env; cannot host image for Instagram.")
        return None
    file_name = os.path.basename(local_path)
    ext = file_name.lower().split(".")[-1]
    ctype = {"webp": "image/webp", "png": "image/png"}.get(ext, "image/jpeg")
    with open(local_path, "rb") as fh:
        data = fh.read()
    headers = {
        **wp_headers(),
        "Content-Disposition": f'attachment; filename="{file_name}"',
        "Content-Type": ctype,
    }
    r = requests.post(f"{WP_URL}/media", headers=headers, data=data, allow_redirects=False)
    if r.status_code == 201:
        url = r.json().get("source_url")
        print(f"    -> Hosted on WordPress: {url}")
        return url
    print(f"    -> WordPress hosting failed ({r.status_code}): {r.text}")
    return None


def to_unix(schedule_time):
    """Parse an ISO-ish local datetime string into a Unix epoch using META_TZ."""
    if not schedule_time:
        return None
    s = schedule_time.strip()
    fmts = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"]
    dt = None
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            break
        except ValueError:
            continue
    if dt is None:
        # allow raw epoch seconds
        if s.isdigit():
            return int(s)
        raise ValueError(f"Unrecognised schedule_time '{schedule_time}'")
    if ZoneInfo:
        dt = dt.replace(tzinfo=ZoneInfo(TZ))
    return int(dt.timestamp())


def build_caption(row):
    text = (row.get("primary_text") or "").strip()
    tags = (row.get("hashtags") or "").strip()
    if tags:
        if not tags.startswith("#"):
            tags = " ".join(f"#{t.strip().lstrip('#')}" for t in tags.replace(",", " ").split() if t.strip())
        text = (text + "\n\n" + tags).strip()
    return text


def post_facebook(post_type, image_url, caption, sched_unix, action, dry):
    scheduled = action == "schedule" and sched_unix
    if post_type == "feed":
        params = {
            "caption": caption,
            "url": image_url,
            "access_token": PAGE_TOKEN,
        }
        if scheduled:
            params["published"] = "false"
            params["scheduled_publish_time"] = str(sched_unix)
        else:
            params["published"] = "true"
        url = f"{GRAPH}/{PAGE_ID}/photos"
        if dry:
            print(f"    -> [DRY][FB feed {'SCHEDULE ' + str(sched_unix) if scheduled else 'NOW'}] POST {url}")
            print(f"       params: {json.dumps({k: v for k, v in params.items() if k != 'access_token'})}")
            return True
        r = requests.post(url, data=params, allow_redirects=False)
        ok = r.status_code == 200
        print(f"    -> FB feed {'ok' if ok else 'FAILED'} ({r.status_code}): {r.text[:200]}")
        return ok
    # story
    params = {"media_url": image_url, "access_token": PAGE_TOKEN}
    url = f"{GRAPH}/{PAGE_ID}/stories"
    if scheduled:
        print("    -> NOTE: Facebook stories cannot be scheduled via the API; publishing now.")
    if dry:
        print(f"    -> [DRY][FB story NOW] POST {url} media_url={image_url}")
        return True
    r = requests.post(url, data=params, allow_redirects=False)
    ok = r.status_code == 200
    print(f"    -> FB story {'ok' if ok else 'FAILED'} ({r.status_code}): {r.text[:200]}")
    return ok


def post_instagram(post_type, image_url, caption, sched_unix, action, dry):
    scheduled = action == "schedule" and sched_unix
    if not IG_ID:
        print("    -> ERROR: META_IG_USER_ID not set; skipping Instagram.")
        return False
    container = {
        "image_url": image_url,
        "caption": caption,
        "access_token": IG_TOKEN,
    }
    if post_type == "story":
        container["story_visual"] = "true"
    if scheduled and post_type == "feed":
        container["scheduled_publish_time"] = str(sched_unix)
    curl = f"{GRAPH}/{IG_ID}/media"
    if dry:
        print(f"    -> [DRY][IG {post_type} container] POST {curl}")
        print(f"       params: {json.dumps({k: v for k, v in container.items() if k != 'access_token'})}")
        if not (scheduled and post_type == "feed"):
            print(f"       then: POST {GRAPH}/{IG_ID}/media_publish  creation_id=<container>")
        return True
    rc = requests.post(curl, data=container, allow_redirects=False)
    if rc.status_code != 200:
        print(f"    -> IG container FAILED ({rc.status_code}): {rc.text[:200]}")
        return False
    creation_id = rc.json().get("id")
    if scheduled and post_type == "feed":
        print(f"    -> IG feed scheduled (container {creation_id}); Meta publishes at {sched_unix}.")
        return True
    rp = requests.post(f"{GRAPH}/{IG_ID}/media_publish",
                       data={"creation_id": creation_id, "access_token": IG_TOKEN},
                       allow_redirects=False)
    ok = rp.status_code == 200
    print(f"    -> IG {post_type} {'published' if ok else 'FAILED'} ({rp.status_code}): {rp.text[:200]}")
    return ok


def process_row(row, dry):
    platform = (row.get("platform") or "").strip().lower()
    post_type = (row.get("post_type") or "feed").strip().lower()
    action = (row.get("action") or "schedule").strip().lower()
    caption = build_caption(row)
    image_file = (row.get("image_file") or "").strip()
    image_url = (row.get("image_url") or "").strip()
    sched_unix = to_unix(row.get("schedule_time"))

    if not caption:
        print("    -> SKIPPED: empty primary_text/hashtags.")
        return False

    # Resolve a public URL. Instagram needs a JPEG; convert if a webp/PNG slipped through.
    local_path = find_local_image(image_file) if image_file else None
    if local_path:
        if platform in ("instagram", "both"):
            if post_type == "feed":
                check_ig_feed_ratio(local_path)
            jpeg = ensure_jpeg(local_path)
            if not jpeg:
                return False
            local_path = jpeg
    if not image_url:
        if not local_path:
            print(f"    -> SKIPPED: image not found: {image_file}")
            return False
        if platform in ("instagram", "both"):
            if dry:
                image_url = f"WP-UPLOAD->{os.path.basename(local_path)}"
            else:
                image_url = host_image_to_wp(local_path)
                if not image_url:
                    return False
        else:
            # Facebook accepts a public URL best; without WP hosting we need one.
            image_url = f"file://{local_path}"

    results = []
    if platform in ("facebook", "both"):
        results.append(post_facebook(post_type, image_url, caption, sched_unix, action, dry))
    if platform in ("instagram", "both"):
        results.append(post_instagram(post_type, image_url, caption, sched_unix, action, dry))
    return all(results) if results else False


def validate_tokens():
    if not (PAGE_ID and PAGE_TOKEN):
        print("Error: META_PAGE_ID / META_PAGE_ACCESS_TOKEN not set. See META_SETUP_GUIDE.md")
        return False
    me = requests.get(f"{GRAPH}/me", params={"access_token": PAGE_TOKEN}).json()
    print(f"Page token OK for: {me.get('name', me)}")
    if IG_ID:
        ig = requests.get(f"{GRAPH}/{IG_ID}", params={"fields": "username,id", "access_token": IG_TOKEN}).json()
        if "error" in ig:
            print(f"Instagram check FAILED: {ig['error'].get('message')}")
        else:
            print(f"Instagram OK: @{ig.get('username')} ({ig.get('id')})")
    else:
        print("META_IG_USER_ID not set — Instagram rows will be skipped.")
    return True


def main():
    dry = "--dry-run" in sys.argv
    if not os.path.exists(CSV_FILE):
        print(f"Error: CSV not found: {CSV_FILE}")
        sys.exit(1)

    if not dry and not validate_tokens():
        sys.exit(1)
    elif dry:
        print("[DRY RUN] Token validation is skipped; only planned calls are shown.\n")

    ok = fail = 0
    with open(CSV_FILE, encoding="utf-8-sig", newline="") as f:
        for i, row in enumerate(csv.DictReader(f), start=1):
            if not (row.get("platform") or "").strip():
                continue
            print(f"[{i}] {row.get('platform')}/{row.get('post_type')} :: {(row.get('primary_text') or '')[:40]}")
            if process_row(row, dry):
                ok += 1
            else:
                fail += 1

    print(f"\n--- Meta publish complete ---\nSuccessful: {ok}\nFailed: {fail}")


if __name__ == "__main__":
    main()
