import os
import json
import time
import base64
import datetime
import tempfile
import urllib.parse

import requests
import gspread
from google import genai
from google.genai import errors
from google.oauth2.service_account import Credentials


# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
BRAND_NAME = os.environ.get("BRAND_NAME", "AI BUSINESS OS")
BRAND_TAGLINE = os.environ.get("BRAND_TAGLINE", "SMART AUTOMATION")
TEXT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

DEFAULT_BUSINESS = (
    "AI-powered customer reply automation for small and medium businesses. "
    "It instantly answers customer messages on Facebook, Instagram and WhatsApp "
    "24/7, so a business never misses a lead, replies within seconds, recovers "
    "sales lost to slow replies, and does it all without hiring extra staff."
)

FONT_URLS = {
    "Anton-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
    "HindSiliguri-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/hindsiliguri/HindSiliguri-Bold.ttf",
    "HindSiliguri-SemiBold.ttf": "https://github.com/google/fonts/raw/main/ofl/hindsiliguri/HindSiliguri-SemiBold.ttf",
    "HindSiliguri-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/hindsiliguri/HindSiliguri-Regular.ttf",
}
FONT_DIR = os.path.join(tempfile.gettempdir(), "ad_fonts")


def get_env_var(var_name: str) -> str:
    val = os.environ.get(var_name)
    if not val:
        raise ValueError(f"Missing required environment variable: {var_name}")
    return val


# ----------------------------------------------------------------------------
# 1. AI content: structured ad copy (English headline + Bangla body + caption)
# ----------------------------------------------------------------------------
def generate_content_with_retry(gemini_client, max_retries: int = 3) -> dict:
    business_context = os.environ.get("BUSINESS_CONTEXT", DEFAULT_BUSINESS)
    prompt = (
        "You are a senior performance-marketing copywriter and ad art director. "
        "Create ONE high-CTR social media ad (Instagram + Facebook) for this business:\n"
        f"BUSINESS: {business_context}\n\n"
        "Pick a fresh angle each time (missed night-time messages, slow replies losing "
        "sales, festival rush, 24/7 support, saving staff cost, faster order booking).\n\n"
        "Return STRICTLY valid JSON, no markdown, no code fences, EXACTLY these keys:\n"
        "{\n"
        '  "english_headline": "2 to 4 punchy UPPERCASE words for the big on-image headline",\n'
        '  "bangla_subheadline": "one short Bangla line under the headline",\n'
        '  "benefits_bangla": ["4 to 5 very short Bangla benefit points, 2-4 words each"],\n'
        '  "badge_english": "a short 2-3 word English badge like 24/7 AUTO REPLY",\n'
        '  "cta_bangla": "one short Bangla call-to-action line for the button",\n'
        '  "accent_color": "a hex color that fits the topic, e.g. #1e56ff",\n'
        '  "caption": "the FULL post caption in BANGLA: strong hook naming a real pain point, '
        "why customer-reply automation is needed, concrete benefits, a Bangla call-to-action, "
        'a few emojis, and 6-8 mixed Bangla/English hashtags",\n'
        '  "image_prompt": "English description of a CLEAN, PROFESSIONAL business background '
        'photo. Modern office/commerce/technology. NO text, NO letters, NO words, NO logos."\n'
        "}"
    )
    required = ["english_headline", "bangla_subheadline", "benefits_bangla",
                "badge_english", "cta_bangla", "accent_color", "caption", "image_prompt"]

    # Candidate models for automatic fallback
    models_to_try = [TEXT_MODEL, "gemini-1.5-flash", "gemini-2.0-flash"]
    # Remove duplicates preserving order
    models_to_try = list(dict.fromkeys(models_to_try))

    for model_name in models_to_try:
        print(f"--- Attempting generation with model: {model_name} ---")
        for attempt in range(1, max_retries + 1):
            try:
                print(f"Generating AI Content (Attempt {attempt}/{max_retries})...")
                response = gemini_client.models.generate_content(model=model_name, contents=prompt)
                text = response.text.strip()
                
                if text.startswith("```"):
                    text = text.split("\n", 1)[1]
                    if text.endswith("```"):
                        text = text.rsplit("```", 1)[0]
                    text = text.strip()
                
                data = json.loads(text)
                for key in required:
                    if key not in data:
                        raise ValueError(f"Model output missing key: {key}")
                
                if not isinstance(data["benefits_bangla"], list):
                    data["benefits_bangla"] = [str(data["benefits_bangla"])]
                data["benefits_bangla"] = [str(b).strip() for b in data["benefits_bangla"] if str(b).strip()][:5]
                
                return data

            except errors.ClientError as e:
                # 404/400 errors: model unavailable or invalid name. Break to try fallback model.
                print(f"ClientError with model '{model_name}': {e.message if hasattr(e, 'message') else e}")
                print("Switching to next available model...")
                break

            except errors.ServerError as e:
                # 503/500 errors: server busy/congestion. Pause and retry.
                print(f"Attempt {attempt} failed (Server Busy): {e.message if hasattr(e, 'message') else e}")
                if attempt < max_retries:
                    wait_time = attempt * 10
                    print(f"Waiting {wait_time}s before retrying...")
                    time.sleep(wait_time)

            except Exception as e:
                print(f"Attempt {attempt} failed ({type(e).__name__}): {e}")
                if attempt < max_retries:
                    time.sleep(5)

    raise RuntimeError("Failed content generation after testing all available models.")


# ----------------------------------------------------------------------------
# 2. Background image (AI, text-free) + fonts
# ----------------------------------------------------------------------------
def build_background_url(image_prompt: str) -> str:
    clean_prompt = urllib.parse.quote(image_prompt)
    seed = int(time.time())
    return f"[https://image.pollinations.ai/prompt/](https://image.pollinations.ai/prompt/){clean_prompt}?width=1080&height=1080&nologo=true&seed={seed}"


def fetch_bytes(url: str, timeout: int = 60) -> bytes:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def ensure_fonts() -> dict:
    os.makedirs(FONT_DIR, exist_ok=True)
    out = {}
    for fname, url in FONT_URLS.items():
        path = os.path.join(FONT_DIR, fname)
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            print(f"Downloading font {fname}...")
            with open(path, "wb") as f:
                f.write(fetch_bytes(url))
        with open(path, "rb") as f:
            out[fname] = base64.b64encode(f.read()).decode()
    return out


# ----------------------------------------------------------------------------
# 3. Build ad HTML + render to PNG with headless Chromium
# ----------------------------------------------------------------------------
def build_ad_html(content: dict, fonts: dict, bg_data_uri: str) -> str:
    accent = content.get("accent_color", "#1e56ff")
    bullets = "".join(
        f'<div class="b"><span class="ck">&#10003;</span><span>{b}</span></div>'
        for b in content["benefits_bangla"]
    )
    bg_layer = f'<div class="bg" style="background-image:url({bg_data_uri})"></div>' if bg_data_uri else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{font-family:Anton; src:url(data:font/ttf;base64,{fonts['Anton-Regular.ttf']});}}
@font-face {{font-family:HS; font-weight:700; src:url(data:font/ttf;base64,{fonts['HindSiliguri-Bold.ttf']});}}
@font-face {{font-family:HS; font-weight:600; src:url(data:font/ttf;base64,{fonts['HindSiliguri-SemiBold.ttf']});}}
@font-face {{font-family:HS; font-weight:400; src:url(data:font/ttf;base64,{fonts['HindSiliguri-Regular.ttf']});}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{width:1080px;height:1080px;overflow:hidden;font-family:HS;}}
.card{{position:relative;width:1080px;height:1080px;color:#fff;
  background:linear-gradient(135deg,#0b1a4a 0%,#12276e 55%,{accent} 100%);}}
.bg{{position:absolute;inset:0;background-size:cover;background-position:center;opacity:.16;}}
.wrap{{position:relative;padding:70px 70px 0 70px;height:100%;display:flex;flex-direction:column;}}
.top{{display:flex;justify-content:space-between;align-items:flex-start;}}
.logo{{font-family:Anton;font-size:42px;letter-spacing:1px;line-height:1;}}
.logo small{{display:block;font-family:HS;font-weight:400;font-size:15px;opacity:.85;letter-spacing:3px;margin-top:6px;}}
.badge{{background:#ffd21e;color:#0b1a4a;font-weight:700;font-size:22px;padding:12px 22px;
  border-radius:14px;box-shadow:0 8px 24px rgba(0,0,0,.3);white-space:nowrap;}}
.headline{{font-family:Anton;font-size:94px;line-height:.98;margin-top:64px;letter-spacing:1px;
  text-transform:uppercase;text-shadow:0 6px 30px rgba(0,0,0,.35);}}
.sub{{font-weight:600;font-size:34px;margin-top:26px;opacity:.96;max-width:900px;}}
.benefits{{margin-top:46px;display:flex;flex-direction:column;gap:22px;}}
.b{{display:flex;align-items:center;gap:18px;font-weight:600;font-size:34px;}}
.ck{{display:flex;align-items:center;justify-content:center;min-width:48px;height:48px;
  background:#22c55e;border-radius:50%;font-size:26px;font-weight:700;box-shadow:0 4px 12px rgba(0,0,0,.25);}}
.cta{{margin-top:auto;margin-bottom:60px;background:#ffd21e;color:#0b1a4a;font-weight:700;
  font-size:40px;text-align:center;padding:32px;border-radius:22px;box-shadow:0 12px 30px rgba(0,0,0,.35);}}
</style></head><body>
<div class="card">{bg_layer}<div class="wrap">
  <div class="top">
    <div class="logo">{BRAND_NAME}<small>{BRAND_TAGLINE}</small></div>
    <div class="badge">{content.get('badge_english','')}</div>
  </div>
  <div class="headline">{content['english_headline']}</div>
  <div class="sub">{content['bangla_subheadline']}</div>
  <div class="benefits">{bullets}</div>
  <div class="cta">{content['cta_bangla']}</div>
</div></div>
</body></html>"""


def render_html_to_png(html: str) -> bytes:
    from playwright.sync_api import sync_playwright
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        html_path = f.name
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1080, "height": 1080}, device_scale_factor=1)
            page.goto("file://" + html_path)
            page.wait_for_timeout(1200)
            png = page.screenshot(clip={"x": 0, "y": 0, "width": 1080, "height": 1080})
            browser.close()
        return png
    finally:
        try:
            os.remove(html_path)
        except OSError:
            pass


# ----------------------------------------------------------------------------
# 4. Host publicly (Instagram requires a public URL)
# ----------------------------------------------------------------------------
def upload_to_imgbb(png_bytes: bytes, api_key: str) -> str:
    resp = requests.post(
        "[https://api.imgbb.com/1/upload](https://api.imgbb.com/1/upload)",
        params={"key": api_key},
        data={"image": base64.b64encode(png_bytes).decode()},
        timeout=60,
    )
    res = resp.json()
    if not res.get("success"):
        raise Exception(f"imgbb upload failed: {res}")
    url = res["data"]["url"]
    print(f"Uploaded designed ad image: {url}")
    return url


def build_final_image_url(content: dict) -> str:
    imgbb_key = os.environ.get("IMGBB_API_KEY")
    bg_url = build_background_url(content["image_prompt"])

    if not imgbb_key:
        print("\n" + "=" * 70)
        print("!! NO TEXT ON IMAGE BECAUSE: IMGBB_API_KEY secret is NOT set.")
        print("!! Add it under GitHub -> Settings -> Secrets and variables -> Actions.")
        print("=" * 70 + "\n")
        return bg_url

    try:
        bg_data_uri = ""
        try:
            bg_bytes = fetch_bytes(bg_url, timeout=45)
            bg_data_uri = "data:image/jpeg;base64," + base64.b64encode(bg_bytes).decode()
        except Exception as bg_err:
            print(f"Background fetch failed (using gradient only): {bg_err}")

        fonts = ensure_fonts()
        html = build_ad_html(content, fonts, bg_data_uri)
        png = render_html_to_png(html)
        return upload_to_imgbb(png, imgbb_key)
    except Exception as e:
        print("\n" + "=" * 70)
        print("!! NO TEXT ON IMAGE BECAUSE THE AD RENDER/UPLOAD FAILED:")
        print(f"!! {type(e).__name__}: {e}")
        print("!! (Most common: Chromium not installed -> add the 'playwright install' "
              "step to main.yml, and 'playwright' to requirements.txt.)")
        print("=" * 70 + "\n")
        return bg_url


# ----------------------------------------------------------------------------
# 5. Google Sheets logging
# ----------------------------------------------------------------------------
def log_to_google_sheets(creds_json_str: str, sheet_name: str, row_data: list):
    scopes = ["[https://www.googleapis.com/auth/spreadsheets](https://www.googleapis.com/auth/spreadsheets)",
              "[https://www.googleapis.com/auth/drive](https://www.googleapis.com/auth/drive)"]
    creds_dict = json.loads(creds_json_str)
    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(credentials)
    sheet = gc.open(sheet_name).sheet1
    sheet.append_row(row_data)
    print("Logged status to Google Sheet successfully.")


# ----------------------------------------------------------------------------
# 6. Facebook / Instagram publishing
# ----------------------------------------------------------------------------
def get_page_access_token(page_id: str, user_or_system_token: str) -> str:
    url = f"[https://graph.facebook.com/v19.0/](https://graph.facebook.com/v19.0/){page_id}"
    params = {"fields": "access_token", "access_token": user_or_system_token}
    res = requests.get(url, params=params).json()
    if "access_token" not in res:
        raise Exception(
            "Could not retrieve Page access token. Check FB_PAGE_ID and that the token "
            f"has pages_show_list + pages_manage_posts. Response: {res}"
        )
    print("Resolved Page-specific access token.")
    return res["access_token"]


def post_to_facebook(page_id: str, access_token: str, caption: str, image_url: str) -> str:
    url = f"[https://graph.facebook.com/v19.0/](https://graph.facebook.com/v19.0/){page_id}/photos"
    payload = {"url": image_url, "caption": caption, "access_token": access_token}
    res_data = requests.post(url, data=payload).json()
    if "id" not in res_data:
        raise Exception(f"Facebook post failed: {res_data}")
    print(f"Published to Facebook! Post ID: {res_data['id']}")
    return res_data["id"]


def post_to_instagram(ig_user_id: str, access_token: str, caption: str, image_url: str) -> str:
    container_url = f"[https://graph.facebook.com/v19.0/](https://graph.facebook.com/v19.0/){ig_user_id}/media"
    container_payload = {"image_url": image_url, "caption": caption, "access_token": access_token}
    res = requests.post(container_url, data=container_payload).json()
    if "id" not in res:
        raise Exception(f"Instagram Container creation failed: {res}")
    container_id = res["id"]
    print(f"Instagram container created ({container_id}). Waiting for media processing...")
    time.sleep(10)
    publish_url = f"[https://graph.facebook.com/v19.0/](https://graph.facebook.com/v19.0/){ig_user_id}/media_publish"
    publish_payload = {"creation_id": container_id, "access_token": access_token}
    pub_res = requests.post(publish_url, data=publish_payload).json()
    if "id" not in pub_res:
        raise Exception(f"Instagram publishing failed: {pub_res}")
    print(f"Published to Instagram! Media ID: {pub_res['id']}")
    return pub_res["id"]


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def main():
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
        gemini_client = genai.Client(api_key=gemini_api_key)
        content = generate_content_with_retry(gemini_client)
        caption = content["caption"]
        print(f"\n--- GENERATED CAPTION ---\n{caption}\n")

        image_url = build_final_image_url(content)
        print(f"--- FINAL IMAGE URL ---\n{image_url}\n")

        page_access_token = get_page_access_token(fb_page_id, fb_access_token)
        post_to_facebook(fb_page_id, page_access_token, caption, image_url)
        post_to_instagram(ig_user_id, page_access_token, caption, image_url)
        status = "Published Successfully"
    except Exception as e:
        status = f"Failed: {str(e)}"
        print(f"Execution Error: {e}")
        raise e
    finally:
        try:
            log_to_google_sheets(gspread_creds_json, "Social Media Post Logs",
                                 [timestamp, caption, image_url, status])
        except Exception as sheet_err:
            print(f"Logging Error: {sheet_err}")


if __name__ == "__main__":
    main()
