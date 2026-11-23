# Automated Blog + Social Content Pipeline

Turn **one product brief** into a fully AEO-optimised WordPress article, AI-generated
infographics uploaded to the media library, and lifestyle brand-overlay social cards with
paired Facebook & Instagram captions — all keyed to a single `url_slug` so every asset
stays in sync.

> **This is a sanitised public snapshot.** It ships the reusable workflow — scripts, the
> `touchbeauty-marketing` skill, CSV/env templates, and a demo video. Business-specific
> data (the product catalog and master spec pack) and any generated articles, images or
> `.env` secrets are **intentionally excluded**. Bring your own data and credentials.

---

## What it does

The pipeline is organised into "protocols" that an agent (or you, manually) drive:

- **PROTOCOL 1 — Blog article + media (two stages)**
  - *Stage A (authoring):* produces Yoast/AEO metadata (SEO title, slug, ≤140-char meta
    description, focus keyphrase, keyword tags, primary category), a long-form article in
    a single self-contained HTML block (question-based `<h2>` headings, a bolded "Direct
    Answer" BLUF under each, FAQ JSON-LD, mobile-responsive tables, a WooCommerce product
    spotlight), two ASCII infographic blueprints, and a featured-image prompt — then stops
    at a human **approval gate**.
  - *Stage B (production):* auto-selects clean product-only reference images, generates the
    16:9 featured hero + blog infographic, uploads them to WordPress media, builds portrait
    4:5 / 9:16 social cards, assembles the post HTML, and creates a **draft**.
- **PROTOCOL 5 — Lifestyle photo brand overlays:** composites a deterministic Pillow overlay
  (logo + device-name lower-third) onto real lifestyle photos and logs HSA-safe Facebook +
  Instagram captions.
- **PROTOCOL 4 — Meta publishing (roadmap):** auto-posts the social cards to Facebook +
  Instagram (feed = 4:5, story = 9:16). Included here as scripts/templates but treated as an
  optional, gated step.

**Safety gates:** every article defaults to `draft`, and nothing publishes to WordPress or
Meta without an explicit `[TB] PUBLISH` keyword.

---

## Repository layout

```
.
├── README.md                         # this file
├── TOUCHBeauty_Content_Pipeline_Demo.mp4   # ~2:22 silent walkthrough
├── overlay_brand.py                  # PROTOCOL 5 brand-overlay compositor
├── select_reference.py               # ranks product-only reference images
├── WP_ImgUpload/
│   ├── upload_images.py              # CSV-driven WordPress media uploader
│   ├── upload_post.py                # CSV-driven post create/update (draft/publish)
│   └── meta_publish.py               # PROTOCOL 4 Meta feed/story publishing
└── touchbeauty-marketing/            # the agent skill that orchestrates everything
    ├── README.md
    ├── SKILL.md                      # protocol rules, compliance, audience matrix
    ├── scripts/                      # copies of the pipeline scripts
    └── templates/                    # CSV + .env templates (see Setup)
```

---

## Prerequisites

- **Python 3.10+** with `Pillow`, `requests`, `python-dotenv`, and `imageio`
  (+ `imageio-ffmpeg` if you regenerate the demo video).
- A **WordPress** site with the REST API enabled and **Application Passwords**.
- **WooCommerce** (for the product spotlight shortcode) and **Yoast SEO**.
- *(Optional, PROTOCOL 4)* a **Facebook Page + Instagram Business** account with a Meta app.
- Image generation + vision QA are performed by the agent runtime the skill runs inside;
  the scripts themselves handle upload, HTML assembly, overlays and publishing.

---

## Setup

1. **WordPress credentials.** Copy `touchbeauty-marketing/templates/.env.example` to a
   `.env` in the folder your scripts run from (e.g. `WP_ImgUpload/.env`) and fill in:

   ```
   WP_URL=https://your-site.example/wp-json/wp/v2
   WP_USERNAME=your_wp_user
   WP_APP_PASSWORD=xxxx_xxxx_xxxx_xxxx_xxxx_xxxx
   ```

   The Meta keys (`META_APP_ID`, `META_APP_SECRET`, `META_ACCESS_TOKEN`, `META_PAGE_ID`,
   `META_IG_USER_ID`) are only needed for PROTOCOL 4. **Never commit `.env`.**

2. **CSV templates** (in `touchbeauty-marketing/templates/`) define the inputs the scripts
   consume: `Wordpress-Image-Uploader.csv`, `posts-to-upload.csv`, `social-captions.csv`,
   `meta-posts-to-schedule.csv`, plus the batch queues `articles-to-generate.csv` and
   `lifestyle-manifest.csv`. Copy them into place and fill per run.

3. **Bring your own data.** The skill expects a product catalog (SKUs ↔ WooCommerce Product
   IDs) and a device spec/compliance pack. These are deliberately not in this snapshot —
   add your own under `touchbeauty-marketing/references/` if you fork it.

---

## Usage

Run the workflow through the `touchbeauty-marketing` skill using its triggers:

| Trigger | Effect |
|---|---|
| `[TB] GENERATE ARTICLE: <topic>` | PROTOCOL 1 Stage A → approval gate → Stage B (draft) |
| `[TB] OVERLAY` + photo(s) | PROTOCOL 5 lifestyle overlays + FB/IG caption logging |
| `[TB] PUBLISH` | Publish the WordPress draft (and, with `[TB] PUBLISH SOCIAL`, the Meta cards) |

The scripts can also be run directly, e.g.:

```
python upload_images.py            # uploads images listed in the CSV
python upload_post.py --dry-run    # validate a post row without writing
python upload_post.py --status=draft
python overlay_brand.py "<photo>" --slug <slug> --name "<Device (SKU)>" --headline "<hook>"
```

---

## Demo

`TOUCHBeauty_Content_Pipeline_Demo.mp4` is a ~2-minute-22 silent, motion-graphics walkthrough
of the workflow, including real screenshots captured from a live published post.

---

## Disclaimer

Shared as a reference implementation of an automated content pipeline. It contains no
credentials or proprietary product data. Brand names and product references shown are for
demonstration of the workflow only.
