import base64
import csv
import os
from dotenv import load_dotenv
import requests

# --- LOAD ENVIRONMENT VARIABLES FROM .env ---
load_dotenv()

WP_URL = os.getenv("WP_URL", "https://www.touchbeauty.com.sg/wp-json/wp/v2")
USERNAME = os.getenv("WP_USERNAME")
APP_PASSWORD = os.getenv("WP_APP_PASSWORD")

CSV_FILE = "Wordpress-Image-Uploader.csv"
IMAGES_SUBFOLDER = "Images"

if not USERNAME or not APP_PASSWORD:
  print(
      "Error: WP_USERNAME or WP_APP_PASSWORD is missing. Check your .env file!"
  )
  exit()

credentials = f"{USERNAME}:{APP_PASSWORD}"
token = base64.b64encode(credentials.encode()).decode("utf-8")
headers = {"Authorization": f"Basic {token}"}

if not os.path.exists(CSV_FILE):
  print(f"Error: Could not find CSV file at '{CSV_FILE}'")
  exit()

print(f"Starting batch upload to {WP_URL}...\n")

success_count = 0
fail_count = 0

with open(CSV_FILE, mode="r", encoding="cp1252") as file:
  reader = csv.DictReader(file)

  for row_num, row in enumerate(reader, start=1):
    file_name = row["file_name"].strip()
    title = row["title"].strip()
    alt_text = row["alt_text"].strip()
    caption = row["caption"].strip()

    image_path = os.path.join(IMAGES_SUBFOLDER, file_name)

    if not os.path.exists(image_path):
      print(f"[{row_num}] SKIPPED: Local file not found -> {image_path}")
      fail_count += 1
      continue

    print(f"[{row_num}] Uploading: {image_path}...")

    try:
      with open(image_path, "rb") as img_file:
        image_data = img_file.read()

      ext = file_name.lower().split(".")[-1]
      if ext == "webp":
        content_type = "image/webp"
      elif ext == "png":
        content_type = "image/png"
      else:
        content_type = "image/jpeg"

      upload_headers = {
          **headers,
          "Content-Disposition": f'attachment; filename="{file_name}"',
          "Content-Type": content_type,
      }

      # allow_redirects=False ensures we never accidentally turn a POST into a GET
      response = requests.post(
          f"{WP_URL}/media",
          headers=upload_headers,
          data=image_data,
          allow_redirects=False,
      )

      if response.status_code == 201:
        media_id = response.json().get("id")

        update_data = {"title": title, "alt_text": alt_text, "caption": caption}

        update_response = requests.post(
            f"{WP_URL}/media/{media_id}",
            headers=headers,
            json=update_data,
            allow_redirects=False,
        )

        if update_response.status_code == 200:
          print(f"    -> Success! Media ID {media_id} uploaded & updated.")
          success_count += 1
        else:
          print(
              f"    -> Uploaded (ID {media_id}), but metadata update failed"
              f" ({update_response.status_code}): {update_response.text}"
          )
          fail_count += 1
      else:
        print(
            f"    -> Upload failed (Status {response.status_code}):"
            f" {response.text}"
        )
        fail_count += 1

    except Exception as e:
      print(f"    -> An error occurred: {str(e)}")
      fail_count += 1

print("\n--- Batch Upload Complete ---")
print(f"Successful: {success_count}")
print(f"Failed: {fail_count}")