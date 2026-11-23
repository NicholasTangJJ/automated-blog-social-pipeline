import base64
import csv
import html
import json
import os
import sys
import time
from urllib.parse import urlparse

from dotenv import load_dotenv
import requests

# --- LOAD ENVIRONMENT VARIABLES FROM .env (same keys as upload_images.py) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

WP_URL = os.getenv("WP_URL", "https://www.touchbeauty.com.sg/wp-json/wp/v2")
USERNAME = os.getenv("WP_USERNAME")
APP_PASSWORD = os.getenv("WP_APP_PASSWORD")

CSV_FILE = os.path.join(BASE_DIR, "posts-to-upload.csv")
IMAGES_SUBFOLDER = os.path.join(BASE_DIR, "Images")

# Header row expected in posts-to-upload.csv
COLUMNS = [
    "post_id",          # if set, UPDATE this existing post instead of creating a new one
    "title",
    "slug",
    "status",           # draft (default) or publish
    "html_file",
    "seo_title",        # Yoast SEO title; blank -> duplicate `title`
    "meta_description", # Yoast meta description; also used as the excerpt
    "focus_keyphrase",  # Yoast focus keyword (optional)
    "category",         # single category NAME or slug -> assigned + set as primary
    "tags",             # comma-separated tag NAMES (resolved to ids, created if missing)
    "excerpt",          # optional; if blank, meta_description is used
    "featured_image",   # filename in Images/ to upload as featured (only if no featured_media_id)
    "featured_media_id",# already-uploaded media id to link as featured (preferred)
]


def resolve_path(value):
    """Resolve a path relative to this script's folder unless already absolute."""
    if not value:
        return value
    if os.path.isabs(value):
        return value
    return os.path.join(BASE_DIR, value)


def auth_headers():
    credentials = f"{USERNAME}:{APP_PASSWORD}"
    token = base64.b64encode(credentials.encode()).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def _norm(s):
    """HTML-unescape + lower + strip for tolerant term-name matching."""
    return html.unescape(s or "").strip().lower()


class TermCache:
    """Lazily fetch and cache categories / tags from WordPress."""

    def __init__(self, headers):
        self.headers = headers
        self._cats = None   # norm_name -> id, and slug -> id
        self._tags = None   # norm_name -> id

    def categories(self):
        if self._cats is None:
            self._cats = {}
            page = 1
            while True:
                r = requests.get(f"{WP_URL}/categories", headers=self.headers,
                                 params={"per_page": 100, "page": page, "context": "edit"})
                if r.status_code != 200:
                    break
                items = r.json()
                if not items:
                    break
                for c in items:
                    self._cats[_norm(c.get("name"))] = c["id"]
                    self._cats[c.get("slug", "")] = c["id"]
                if len(items) < 100:
                    break
                page += 1
        return self._cats

    def tags(self):
        if self._tags is None:
            self._tags = {}
            page = 1
            while True:
                r = requests.get(f"{WP_URL}/tags", headers=self.headers,
                                 params={"per_page": 100, "page": page})
                if r.status_code != 200:
                    break
                items = r.json()
                if not items:
                    break
                for t in items:
                    self._tags[_norm(t.get("name"))] = t["id"]
                if len(items) < 100:
                    break
                page += 1
        return self._tags

    def resolve_category(self, name_or_slug):
        if not name_or_slug:
            return None
        key = _norm(name_or_slug)
        return self.categories().get(key) or self.categories().get(name_or_slug.strip())

    def resolve_tag(self, name, dry_run=False):
        """Return a tag id; create the tag if missing (unless dry_run)."""
        if not name:
            return None
        key = _norm(name)
        existing = self.tags().get(key)
        if existing:
            return existing
        if dry_run:
            return "NEW:" + name.strip()
        r = requests.post(f"{WP_URL}/tags", headers=self.headers,
                          json={"name": name.strip()}, allow_redirects=False)
        if r.status_code in (200, 201):
            new_id = r.json().get("id")
            self.tags()[key] = new_id
            print(f"    -> Created new tag '{name.strip()}' (ID {new_id})")
            return new_id
        print(f"    -> Tag creation failed for '{name}' ({r.status_code}): {r.text}")
        return None


def upload_featured_image(headers, file_name):
    """Upload a local image from Images/ and return its WordPress media id."""
    image_path = os.path.join(IMAGES_SUBFOLDER, file_name)
    if not os.path.exists(image_path):
        print(f"    -> Featured image not found: {image_path}")
        return None

    ext = file_name.lower().split(".")[-1]
    content_type = {"webp": "image/webp", "png": "image/png"}.get(ext, "image/jpeg")

    with open(image_path, "rb") as img_file:
        image_data = img_file.read()

    upload_headers = {
        **headers,
        "Content-Disposition": f'attachment; filename="{file_name}"',
        "Content-Type": content_type,
    }

    response = requests.post(f"{WP_URL}/media", headers=upload_headers,
                             data=image_data, allow_redirects=False)
    if response.status_code == 201:
        media_id = response.json().get("id")
        print(f"    -> Featured image uploaded, Media ID {media_id}.")
        return media_id
    print(f"    -> Featured image upload failed ({response.status_code}): {response.text}")
    return None


def build_payload(row, terms, dry_run=False):
    title = (row.get("title") or "").strip()
    slug = (row.get("slug") or "").strip()
    status = (row.get("status") or "draft").strip() or "draft"
    html_file = resolve_path((row.get("html_file") or "").strip())
    meta_description = (row.get("meta_description") or "").strip()
    seo_title = (row.get("seo_title") or "").strip() or title
    focus_keyphrase = (row.get("focus_keyphrase") or "").strip()
    excerpt = (row.get("excerpt") or "").strip() or meta_description

    if not os.path.exists(html_file):
        print(f"    -> SKIPPED: HTML body file not found -> {html_file}")
        return None

    with open(html_file, "r", encoding="utf-8") as f:
        content = f.read()

    payload = {"title": title, "slug": slug, "status": status, "content": content}
    if excerpt:
        payload["excerpt"] = excerpt

    # Featured media: explicit id wins, else upload the named image.
    explicit_id = (row.get("featured_media_id") or "").strip()
    featured_image = (row.get("featured_image") or "").strip()
    if explicit_id:
        payload["featured_media"] = int(explicit_id)
    elif featured_image:
        if dry_run:
            payload["_featured_pending"] = featured_image
        else:
            fid = upload_featured_image(terms.headers, featured_image)
            if fid:
                payload["featured_media"] = fid

    # --- Yoast SEO meta (registered show_in_rest on this site) ---
    meta = {}
    if seo_title:
        meta["_yoast_wpseo_title"] = seo_title
    if meta_description:
        meta["_yoast_wpseo_metadesc"] = meta_description
    if focus_keyphrase:
        meta["_yoast_wpseo_focuskw"] = focus_keyphrase

    # --- Category (assigned + primary) ---
    cat_name = (row.get("category") or "").strip()
    cat_id = terms.resolve_category(cat_name) if cat_name else None
    if cat_name and not cat_id and not dry_run:
        print(f"    -> WARNING: category '{cat_name}' not found; post will keep default category.")
    if cat_id:
        payload["categories"] = [cat_id]
        meta["_yoast_wpseo_primary_category"] = str(cat_id)

    # --- Tags (resolve-or-create by name) ---
    raw_tags = (row.get("tags") or "").strip()
    if raw_tags:
        names = [t.strip() for t in raw_tags.replace(";", ",").split(",") if t.strip()]
        tag_ids = []
        for n in names:
            tid = terms.resolve_tag(n, dry_run=dry_run)
            if tid is not None and not isinstance(tid, str):
                tag_ids.append(tid)
            elif isinstance(tid, str):
                tag_ids.append(tid)  # keep NEW: marker for dry-run preview
        if tag_ids:
            payload["tags"] = tag_ids

    if meta:
        payload["meta"] = meta

    return payload


def save_post(headers, row, terms, dry_run=False):
    payload = build_payload(row, terms, dry_run=dry_run)
    if payload is None:
        return False

    post_id = (row.get("post_id") or "").strip()
    target = f"{WP_URL}/posts/{post_id}" if post_id else f"{WP_URL}/posts"
    action = f"UPDATE post {post_id}" if post_id else "CREATE post"

    if dry_run:
        preview = {k: (f"<{len(str(v))} chars>" if k == "content" else v)
                   for k, v in payload.items()}
        print(f"    -> DRY RUN [{action}] payload: {json.dumps(preview, ensure_ascii=False)}")
        return True

    response = requests.post(target, headers=headers, json=payload, allow_redirects=False)
    if response.status_code in (200, 201):
        data = response.json()
        pid = data.get("id")
        status = data.get("status")
        link = data.get("link", "")
        print(f"    -> Success! {action} -> Post ID {pid} [{status}] -> {link}")
        return True
    print(f"    -> {action} failed ({response.status_code}): {response.text}")
    return False


def main():
    dry_run = "--dry-run" in sys.argv
    status_override = None
    for arg in sys.argv:
        if arg.startswith("--status="):
            status_override = arg.split("=", 1)[1]

    if not USERNAME or not APP_PASSWORD:
        print("Error: WP_USERNAME or WP_APP_PASSWORD is missing. Check your .env file!")
        sys.exit(1)

    if not os.path.exists(CSV_FILE):
        print(f"Error: Could not find CSV file at '{CSV_FILE}'")
        print("Create it with headers: " + ",".join(COLUMNS))
        sys.exit(1)

    headers = auth_headers()

    me = requests.get(f"{WP_URL}/users/me", headers=headers, allow_redirects=False)
    if me.status_code != 200:
        print(f"Error: Authentication failed ({me.status_code}). Check .env credentials.")
        print(me.text)
        sys.exit(1)
    print(f"Authenticated as: {me.json().get('name')}")

    terms = TermCache(headers)
    print(f"Loaded {len(terms.categories())} categories, {len(terms.tags())} tags.\n")

    print(f"Starting batch post upload to {urlparse(WP_URL).netloc}...\n")

    success_count = 0
    fail_count = 0

    with open(CSV_FILE, mode="r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            print("Error: CSV is empty or has no header row.")
            sys.exit(1)

        for row_num, row in enumerate(reader, start=1):
            title = (row.get("title") or "").strip()
            if not title:
                continue  # ignore blank trailing rows
            if status_override:
                row["status"] = status_override
            print(f"[{row_num}] Processing post: {title}")
            if save_post(headers, row, terms, dry_run=dry_run):
                success_count += 1
            else:
                fail_count += 1
            time.sleep(0.5)

    print("\n--- Batch Post Upload Complete ---")
    print(f"Successful: {success_count}")
    print(f"Failed: {fail_count}")


if __name__ == "__main__":
    main()
