# AI Social Media Automation Agent (Bangladesh Market)

Production-ready, zero-cost AI Social Media Agent designed for AI Automation agencies targeting Bangladeshi business owners (F-Commerce, E-Commerce, Retail Stores, Clinics, Academies, Agencies, etc.).

## 🚀 Features
- **35 Specific Store Niches Mapped:** Rotates through all 35 Bangladeshi store categories (Saree, Panjabi, Shoe Store, Perfume, Electronics, Mobile Shop, Furniture, Gift Shop, Pet Shop, etc.).
- **Gemini 2.0 Content Engine:** Generates hyper-converting Bangla captions and image headline hooks.
- **Google Imagen 3 Graphic Engine:** Renders high-CTR, 1:1 square 3D background visuals tailored to each specific product/niche.
- **Pillow Bangla Typography:** Burns crisp Bangla font overlays (`NotoSansBengali`), badges, and call-to-action buttons onto images.
- **Meta Graph API Auto-Publishing:** Simultaneously posts to connected Facebook Pages and Instagram Business feeds.
- **Zero-Cost Deployment:** Runs on GitHub Actions cron (3 times daily at 9 AM, 3 PM, 9 PM BST).

## 🛠️ Required GitHub Secrets
Add these secrets in **Settings > Secrets and variables > Actions**:
- `GEMINI_API_KEY`: Google AI Studio Key
- `IMGBB_API_KEY`: ImgBB Upload Key
- `FB_PAGE_ID`: Facebook Page Numeric ID
- `FB_PAGE_ACCESS_TOKEN`: Meta Never-Expiring System User Token
- `IG_USER_ID`: Instagram Business Account ID
