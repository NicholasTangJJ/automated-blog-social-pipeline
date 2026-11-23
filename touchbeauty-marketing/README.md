# TOUCHBeauty Blog & Social Workflow — Portable Bundle

A **self-contained, migration-ready snapshot** of the TOUCHBeauty marketing
content pipeline: blog-post authoring → SEO/Yoast fields → image generation →
WordPress upload → social (Meta) publishing. It is packaged in the open
[Agent Skills](https://agentskills.io) format so it can move to Claude, an API
agent, or a local Ollama-backed agent.

This bundle was generated from the live QwenWork skill
(`touchbeauty-marketing`) and the `Blogpost Generation` project. It is a
**snapshot** — re-copy from the source if the live skill changes.

---

## Layout

```
touchbeauty-marketing/          # folder name == skill name (required for packaging)
├── SKILL.md                    # the workflow spec (PROTOCOL 1–4, STAGE A/B) — open Agent Skills format
├── references/
│   ├── products_catalog.csv    # product table (SKUs, Woo IDs, specs)
│   └── touchbeauty_master_pack.md   # brand voice, approved claims, URLs, compliance
├── scripts/
│   ├── select_reference.py     # rank reference_images/<device>/ for a clean product-only "base lock"
│   ├── upload_images.py        # POST images to /wp-json/wp/v2/media from Wordpress-Image-Uploader.csv
│   ├── upload_post.py          # create/update posts + Yoast fields + category/tags from posts-to-upload.csv
│   └── meta_publish.py         # publish feed/story to Facebook Page + Instagram via Graph API
├── templates/
│   ├── Wordpress-Image-Uploader.csv   # image_path,file_name,title,alt_text,caption
│   ├── posts-to-upload.csv            # post_id,title,slug,status,html_file,seo_title,meta_description,focus_keyphrase,category,tags,excerpt,featured_image,featured_media_id
│   ├── meta-posts-to-schedule.csv     # platform,post_type,image_file,image_url,primary_text,hashtags,schedule_time,action
│   ├── social-captions.csv            # url_slug,platform,post_type,image_file,ig_caption,hashtags
│   ├── .env.example                   # copy to .env and fill (WordPress + Meta secrets)
│   └── .env.meta.example              # Meta keys only
└── docs/
    ├── LEARNINGS.md            # verified platform gotchas (read this first!)
    ├── MIGRATION.md            # how to port to Claude / Ollama / API
    └── META_SETUP_GUIDE.md     # one-time Meta token setup
```

## How it runs (QwenWork today)

1. `[TB] GENERATE ARTICLE: <topic>` → **STAGE A** authors metadata + HTML + ASCII
   blueprints + image prompts, then **stops at the approval gate**.
2. On approval → **STAGE B** picks base reference locks (visually verified),
   generates featured + landscape infographic (webp) and 4:5 / 9:16 social cards
   (JPEG), uploads images to WordPress, writes the CSVs, and creates a **draft**.
3. `[TB] PUBLISH` → flips the draft live. Social publishing to Meta is PROTOCOL 4.

## Prerequisites on any platform

- **Python 3.10+** with `requests`, `python-dotenv`, `Pillow`.
- A `.env` (from `templates/.env.example`) with WordPress + Meta credentials.
- `reference_images/<device>/` folders populated (not included here — too large).
- Network access to the WordPress site and the Meta Graph API.
- Image generation + vision QA are **platform tools** — see `docs/MIGRATION.md §4`
  to re-implement them off QwenWork.

## Secrets & generated files

`.env` and all generated media are **git-ignored** and excluded from this bundle.
Never commit credentials. See `docs/LEARNINGS.md §10` for the site-specific IDs
that must be re-verified after any migration.
