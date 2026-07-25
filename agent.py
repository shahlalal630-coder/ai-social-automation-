import os
import json
import time
import urllib.parse
import datetime
import requests
import gspread
from google import genai
from google.oauth2.service_account import Credentials


def get_env_var(var_name: str) -> str:
    """Retrieves environment variable or raises helpful error if missing."""
    val = os.environ.get(var_name)
    if not val:
        raise ValueError(f"Missing required environment variable: {var_name}")
    return val


def generate_content_with_retry(gemini_client, max_retries: int = 3):
    """Generates post caption and image prompt using Gemini API with retry logic."""
    # Model name is configurable so future Google deprecations are a secret change,
    # not a code edit. gemini-2.5-flash was retired for new API keys.
    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

    # What the business actually sells. Edit this (or set the BUSINESS_CONTEXT
    # secret) to change the product the posts advertise.
    business_context = os.environ.get(
        "BUSINESS_CONTEXT",
        "AI-powered customer reply automation for small and medium businesses. "
        "It instantly answers customer messages on Facebook, Instagram and WhatsApp "
        "24/7, so a business never misses a lead, replies within seconds, recovers "
        "sales lost to slow replies, and does it all without hiring extra staff.",
    )

    prompt = (
        "You are a senior performance-marketing copywriter and art director creating a "
        "high-CTR paid social ad (Instagram + Facebook) for this business:\n"
        f"BUSINESS: {business_context}\n\n"
        "Write the CAPTION in BANGLA (Bengali script). The caption must:\n"
        "- Open with a strong scroll-stopping HOOK naming a real pain point the business "
        "owner feels (e.g. missed messages, slow replies, lost customers at night, staff cost).\n"
        "- Clearly explain WHY automated customer reply is needed for their specific business "
        "and the concrete BENEFITS (more sales, faster response, 24/7, no missed leads).\n"
        "- Sound persuasive and modern, use a few relevant emojis, short punchy lines.\n"
        "- End with a clear Bangla call-to-action (e.g. message/comment to get started).\n"
        "- Include 6-8 relevant hashtags (mix of Bangla and English business hashtags).\n\n"
        "Write the IMAGE_PROMPT in ENGLISH (image models understand English best). It must "
        "describe a polished, ad-style, high-CTR visual that VISUALLY tells a before/after or "
        "problem->solution story: e.g. a stressed business owner buried in unread chat bubbles "
        "and missed-call notifications on one side, and a calm owner with an AI chatbot auto-"
        "replying to happy customers on the other. Modern, clean, professional advertising "
        "photography/illustration, strong focal point, bright commercial lighting, leave some "
        "clean negative space at top or bottom for a headline. IMPORTANT: keep any on-image "
        "text to at most 2-3 very short bold words, because AI image generators garble long "
        "text; carry the real message in the caption, not the image.\n\n"
        "Return STRICTLY valid JSON with no markdown wrapping, no code fences:\n"
        "{\n"
        '  "caption": "Bangla caption with line breaks, emojis and hashtags",\n'
        '  "image_prompt": "English ad-style problem/solution visual description"\n'
        "}"
    )

    for attempt in range(1, max_retries + 1):
        try:
            print(f"Generating AI Content (Attempt {attempt}/{max_retries})...")
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            text = response.text.strip()

            # Strip markdown formatting block if returned by model
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text.rsplit("```", 1)[0]
                text = text.strip()

            data = json.loads(text)
            return data["caption"], data["image_prompt"]

        except Exception as e:
            print(f"Attempt {attempt} failed: {e}")
            if attempt < max_retries:
                time.sleep(5)
            else:
                raise RuntimeError("Failed content generation after max retries.") from e


def build_image_url(image_prompt: str) -> str:
    """Generates direct, public HTTPS image URL using Pollinations AI engine."""
    clean_prompt = urllib.parse.quote(image_prompt)
    seed = int(time.time())
    # 1080x1080 square format optimized for Instagram/Facebook feeds
    return f"https://image.pollinations.ai/prompt/{clean_prompt}?width=1080&height=1080&nologo=true&seed={seed}"


def log_to_google_sheets(creds_json_str: str, sheet_name: str, row_data: list):
    """Logs automation metadata directly to Google Sheets."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_dict = json.loads(creds_json_str)
    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(credentials)

    sheet = gc.open(sheet_name).sheet1
    sheet.append_row(row_data)
    print("Logged status to Google Sheet successfully.")


def get_page_access_token(page_id: str, user_or_system_token: str) -> str:
    """Exchanges a User/System-User token for the Page-specific access token.

    Publishing to a Page requires a Page token. Posting with a user or system-user
    token directly triggers the misleading '(#200) publish_actions' error, so we
    always resolve the real Page token first.
    """
    url = f"https://graph.facebook.com/v19.0/{page_id}"
    params = {"fields": "access_token", "access_token": user_or_system_token}
    res = requests.get(url, params=params).json()
    if "access_token" not in res:
        raise Exception(
            "Could not retrieve Page access token. Check that FB_PAGE_ID is correct "
            "and the token has pages_show_list + pages_manage_posts. Response: "
            f"{res}"
        )
    print("Resolved Page-specific access token.")
    return res["access_token"]


def post_to_facebook(page_id: str, access_token: str, caption: str, image_url: str) -> str:
    """Publishes photo and caption directly to Facebook Page via Graph API."""
    url = f"https://graph.facebook.com/v19.0/{page_id}/photos"
    payload = {
        "url": image_url,
        "caption": caption,
        "access_token": access_token,
    }
    response = requests.post(url, data=payload)
    res_data = response.json()

    if "id" not in res_data:
        raise Exception(f"Facebook post failed: {res_data}")

    print(f"Published to Facebook! Post ID: {res_data['id']}")
    return res_data["id"]


def post_to_instagram(ig_user_id: str, access_token: str, caption: str, image_url: str) -> str:
    """Publishes photo and caption to Instagram Business account via Graph API."""
    # Step 1: Create Media Container
    container_url = f"https://graph.facebook.com/v19.0/{ig_user_id}/media"
    container_payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": access_token,
    }
    res = requests.post(container_url, data=container_payload).json()
    if "id" not in res:
        raise Exception(f"Instagram Container creation failed: {res}")

    container_id = res["id"]
    print(f"Instagram container created ({container_id}). Waiting 10s for media processing...")
    time.sleep(10)

    # Step 2: Publish Container
    publish_url = f"https://graph.facebook.com/v19.0/{ig_user_id}/media_publish"
    publish_payload = {
        "creation_id": container_id,
        "access_token": access_token,
    }
    pub_res = requests.post(publish_url, data=publish_payload).json()
    if "id" not in pub_res:
        raise Exception(f"Instagram publishing failed: {pub_res}")

    print(f"Published to Instagram! Media ID: {pub_res['id']}")
    return pub_res["id"]


def main():
    # 1. Fetch Environment Variables
    fb_page_id = get_env_var("FB_PAGE_ID")
    ig_user_id = get_env_var("IG_USER_ID")
    fb_access_token = get_env_var("FB_PAGE_ACCESS_TOKEN")
    gemini_api_key = get_env_var("GEMINI_API_KEY")
    gspread_creds_json = get_env_var("GSPREAD_CREDS_JSON")

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    caption = "N/A"
    image_url = "N/A"
    status = "Pending"

    try:
        # 2. Initialize Gemini AI Client
        gemini_client = genai.Client(api_key=gemini_api_key)

        # 3. Generate Caption & Image Prompt
        caption, image_prompt = generate_content_with_retry(gemini_client)
        print(f"\n--- GENERATED CAPTION ---\n{caption}\n")

        # 4. Generate Image URL
        image_url = build_image_url(image_prompt)
        print(f"--- IMAGE URL ---\n{image_url}\n")

        # 5. Resolve the Page-specific token (fixes the #200 publish_actions error)
        page_access_token = get_page_access_token(fb_page_id, fb_access_token)

        # 6. Execute Posts using the Page token
        post_to_facebook(fb_page_id, page_access_token, caption, image_url)
        post_to_instagram(ig_user_id, page_access_token, caption, image_url)

        status = "Published Successfully"

    except Exception as e:
        status = f"Failed: {str(e)}"
        print(f"Execution Error: {e}")
        raise e

    finally:
        # 6. Always append output record to Google Sheet
        try:
            log_to_google_sheets(
                gspread_creds_json,
                "Social Media Post Logs",
                [timestamp, caption, image_url, status],
            )
        except Exception as sheet_err:
            print(f"Logging Error: {sheet_err}")


if __name__ == "__main__":
    main()
