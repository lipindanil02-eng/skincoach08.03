"""Generate share card image — Chrome headless on desktop, PIL fallback on server."""
import subprocess, json, sys, os, tempfile, shutil, re, urllib.parse
from pathlib import Path

HTML_TPL = Path(__file__).parent / "static" / "share_card.html"
OUT_DIR = Path(__file__).parent / "static" / "cards"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATHS = [
    # Windows
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    # Linux / Railway
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/snap/bin/chromium",
]


def _find_chrome():
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    # fallback: try `which`
    for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
        try:
            r = subprocess.run(["which", name], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
    return None


# ── Beautiful PIL fallback ───────────────────────────────────────────────

def _gen_pil(diag_ru, confidence_pct, risk, top3, out_file):
    """PIL fallback — generates a beautiful card matching the Chrome HTML template."""
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
    import math, os

    W, H = 800, 700
    M = 40  # margin

    # ── Font loading ─────────────────────────────────────────────────────
    _FONT_CACHE = {}

    def _font(size, bold=False):
        key = (size, bold)
        if key in _FONT_CACHE:
            return _FONT_CACHE[key]
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
        # Fallback: bundled Noto Sans (Cyrillic support)
        bundled = os.path.join(os.path.dirname(__file__), "static", "fonts", "NotoSans.ttf")
        for fp in candidates + [bundled]:
            if os.path.exists(fp):
                try:
                    f = ImageFont.truetype(fp, size)
                    _FONT_CACHE[key] = f
                    return f
                except Exception:
                    pass
        # Ultimate fallback — download Noto Sans
        try:
            import urllib.request
            urllib.request.urlretrieve(
                "https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans%5Bwdth,wght%5D.ttf",
                bundled
            )
            f = ImageFont.truetype(bundled, size)
            _FONT_CACHE[key] = f
            return f
        except Exception:
            _FONT_CACHE[key] = ImageFont.load_default()
            return _FONT_CACHE[key]
        return f

    # ── Color palette ────────────────────────────────────────────────────
    C_BG_TOP = (26, 26, 46)       # #1a1a2e
    C_BG_MID = (22, 33, 62)       # #16213e
    C_BG_BOT = (15, 52, 96)       # #0f3460
    C_ACCENT = (233, 69, 96)      # #e94560
    C_ACCENT2 = (255, 107, 129)   # #ff6b81
    C_WHITE = (255, 255, 255)
    C_LABEL = (128, 128, 128, 180)  # rgba(255,255,255,0.5) approximated
    C_DIM = (255, 255, 255, 60)     # rgba(255,255,255,0.08-0.1)
    C_GREEN = (46, 204, 113)
    C_YELLOW = (241, 196, 15)
    C_RED = (231, 76, 60)
    C_CARD_BG = (255, 255, 255, 12)  # rgba(255,255,255,0.05)

    # ── Gradient helpers (numpy-fast) ────────────────────────────────────

    def _linear_gradient(w, h, top_color, bottom_color):
        """Vertical linear gradient from top_color to bottom_color."""
        r1, g1, b1 = top_color
        r2, g2, b2 = bottom_color
        rows = np.arange(h, dtype=np.float32) / max(h - 1, 1)
        r = (r1 + (r2 - r1) * rows).astype(np.uint8).reshape(-1, 1)
        g = (g1 + (g2 - g1) * rows).astype(np.uint8).reshape(-1, 1)
        b = (b1 + (b2 - b1) * rows).astype(np.uint8).reshape(-1, 1)
        arr = np.tile(np.stack([r, g, b], axis=2), (1, w, 1))
        return Image.fromarray(arr, "RGB")

    def _radial_gradient(w, h, cx, cy, inner_rgba, outer_rgba):
        """Radial gradient in RGBA mode from inner to outer."""
        ys, xs = np.mgrid[0:h, 0:w]
        dist = np.sqrt((xs - cx)**2 + (ys - cy)**2)
        max_dist = math.sqrt(max(cx, w - cx)**2 + max(cy, h - cy)**2)
        t = np.clip(dist / max_dist, 0, 1)
        r1, g1, b1, a1 = inner_rgba
        r2, g2, b2, a2 = outer_rgba
        r = (r1 + (r2 - r1) * t).astype(np.uint8)
        g = (g1 + (g2 - g1) * t).astype(np.uint8)
        b = (b1 + (b2 - b1) * t).astype(np.uint8)
        a = (a1 + (a2 - a1) * t).astype(np.uint8)
        arr = np.stack([r, g, b, a], axis=2)
        return Image.fromarray(arr, "RGBA")

    # ── Layered composition ──────────────────────────────────────────────

    # Layer 1: Background gradient (top → mid → bottom)
    top_half = _linear_gradient(W, H // 2, C_BG_TOP, C_BG_MID)
    bot_half = _linear_gradient(W, H - H // 2, C_BG_MID, C_BG_BOT)
    bg_img = Image.new("RGB", (W, H))
    bg_img.paste(top_half, (0, 0))
    bg_img.paste(bot_half, (0, H // 2))

    # Layer 2: Decorative radial orbs (composited via alpha blending)
    #   Top-right orb (red)
    orb_tr = _radial_gradient(400, 350, 350, 0, (233, 69, 96, 25), (233, 69, 96, 0))
    #   Bottom-left orb (green hint)
    orb_bl = _radial_gradient(300, 300, 0, 300, (46, 204, 113, 15), (46, 204, 113, 0))

    # Composite orbs onto background
    composite = bg_img.convert("RGBA")
    # Paste orb_tr at top-right corner
    composite = Image.alpha_composite(composite, orb_tr.convert("RGBA").resize(composite.size, Image.Resampling.LANCZOS))
    # For bottom-left, paste at (0, H-300)
    bl_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bl_layer.paste(orb_bl, (0, H - 300))
    composite = Image.alpha_composite(composite, bl_layer)

    img = composite.convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── Helper: rounded rect with optional fill/stroke ───────────────────
    def _rrect(x1, y1, x2, y2, r, fill=None, outline=None, width=1):
        draw.rounded_rectangle([(x1, y1), (x2, y2)], radius=r, fill=fill, outline=outline, width=width)

    # ── Layout ───────────────────────────────────────────────────────────

    # --- Header (y=0..80) ---
    # Logo area
    icon_x, icon_y = M, M
    _rrect(icon_x, icon_y, icon_x + 40, icon_y + 40, 12, fill=C_ACCENT)
    draw.text((icon_x + 10, icon_y + 8), "🔬", fill=C_WHITE, font=_font(18))

    # "Skin" "Coach" text
    logo_x = icon_x + 52
    draw.text((logo_x, icon_y + 9), "Skin", fill=C_WHITE, font=_font(20, bold=True))
    # Measure "Skin" to position "Coach"
    skin_w = draw.textbbox((0, 0), "Skin", font=_font(20, bold=True))[2]
    draw.text((logo_x + skin_w, icon_y + 9), "Coach", fill=C_ACCENT, font=_font(20, bold=True))

    # Badge "AI · 8-слойный анализ"
    badge_text = "AI · 8-слойный анализ"
    badge_font = _font(11, bold=True)
    bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    btw = bbox[2] - bbox[0]
    bth = bbox[3] - bbox[1]
    badge_pad_x, badge_pad_y = 14, 7
    badge_x = W - M - btw - badge_pad_x * 2
    badge_y = icon_y + 7
    _rrect(badge_x, badge_y, badge_x + btw + badge_pad_x * 2, badge_y + bth + badge_pad_y * 2, 20,
           fill=(233, 69, 96, 50), outline=(233, 69, 96, 76))
    draw.text((badge_x + badge_pad_x, badge_y + badge_pad_y), badge_text, fill=C_ACCENT, font=badge_font)

    # Header divider
    div_y = icon_y + 55
    draw.line([(M, div_y), (W - M, div_y)], fill=(255, 255, 255, 20), width=1)

    # --- Content section ---
    cy = div_y + 28

    # "ДИАГНОЗ" label
    draw.text((M, cy), "ДИАГНОЗ", fill=(255, 255, 255, 128), font=_font(11, bold=True))
    cy += 22

    # Diagnosis name
    draw.text((M, cy), diag_ru[:50], fill=C_WHITE, font=_font(36, bold=True))
    cy += 48

    # Confidence bar (max width 400px)
    try:
        pct_val = int(float(str(confidence_pct).replace("%", "").strip()))
    except Exception:
        pct_val = 85
    pct_val = min(max(pct_val, 0), 100)

    bar_w = 400
    bar_h = 8
    bar_r = bar_h // 2
    bar_y = cy
    _rrect(M, bar_y, M + bar_w, bar_y + bar_h, bar_r, fill=(255, 255, 255, 25))

    # Gradient fill for the confidence bar
    fill_w = int(bar_w * pct_val / 100)
    if fill_w > bar_r * 2:
        # Draw as rounded rect
        grad_fill = _linear_gradient(fill_w, bar_h, C_ACCENT, C_ACCENT2)
        # Mask: rounded rect region
        mask = Image.new("L", (fill_w, bar_h), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([(0, 0), (fill_w - 1, bar_h - 1)], radius=bar_r, fill=255)
        img.paste(grad_fill.crop((0, 0, fill_w, bar_h)), (M, bar_y), mask)
    elif fill_w > 0:
        draw.rounded_rectangle([(M, bar_y), (M + fill_w, bar_y + bar_h)], radius=bar_r, fill=C_ACCENT)

    cy = bar_y + bar_h + 24

    # --- Stats cards ---
    card_w = (W - 2 * M - 16) // 2  # two cards with 16px gap
    card_h = 72
    card_gap = 16

    # Card 1: Уверенность
    c1x = M
    _rrect(c1x, cy, c1x + card_w, cy + card_h, 16, fill=(255, 255, 255, 12), outline=(255, 255, 255, 16))
    draw.text((c1x + 18, cy + 12), "УВЕРЕННОСТЬ", fill=(255, 255, 255, 100), font=_font(10, bold=True))
    draw.text((c1x + 18, cy + 32), str(confidence_pct), fill=C_WHITE, font=_font(24, bold=True))

    # Card 2: Уровень риска
    c2x = c1x + card_w + card_gap
    _rrect(c2x, cy, c2x + card_w, cy + card_h, 16, fill=(255, 255, 255, 12), outline=(255, 255, 255, 16))
    draw.text((c2x + 18, cy + 12), "УРОВЕНЬ РИСКА", fill=(255, 255, 255, 100), font=_font(10, bold=True))

    risk_label = {"low": "Низкий", "medium": "Средний", "high": "Высокий — к врачу!"}
    risk_color_map = {"low": C_GREEN, "medium": C_YELLOW, "high": C_RED}
    rlbl = risk_label.get(risk, "Низкий")
    rcol = risk_color_map.get(risk, C_GREEN)

    # Risk badge (rounded rect)
    risk_badge_text = f"● {rlbl}"
    rbf = _font(12, bold=True)
    rbb = draw.textbbox((0, 0), risk_badge_text, font=rbf)
    rbw = rbb[2] - rbb[0]
    rbh = rbb[3] - rbb[1]
    rbp_x, rbp_y = 14, 6
    _rrect(c2x + 18, cy + 34, c2x + 18 + rbw + rbp_x * 2, cy + 34 + rbh + rbp_y * 2, 20,
           fill=(rcol[0], rcol[1], rcol[2], 38), outline=(rcol[0], rcol[1], rcol[2], 60))
    draw.text((c2x + 18 + rbp_x, cy + 34 + rbp_y), risk_badge_text, fill=rcol, font=rbf)

    cy += card_h + 28

    # --- Top 3 hypotheses ---
    if top3:
        draw.text((M, cy), "ТОП ГИПОТЕЗ", fill=(255, 255, 255, 128), font=_font(11, bold=True))
        cy += 24

        for i, (name, pct) in enumerate(top3[:3]):
            item_h = 44
            _rrect(M, cy, W - M, cy + item_h, 12, fill=(255, 255, 255, 8), outline=(255, 255, 255, 12))

            # Rank number (01, 02, 03)
            rank_text = f"{i + 1:02d}"
            rnk_font = _font(14, bold=True)
            rnk_box = draw.textbbox((0, 0), rank_text, font=rnk_font)
            rnk_w = rnk_box[2] - rnk_box[0]
            draw.text((M + 16, cy + (item_h - (rnk_box[3] - rnk_box[1])) // 2 - rnk_box[1]),
                      rank_text, fill=(255, 255, 255, 76), font=rnk_font)

            # Name
            name_font = _font(15)
            draw.text((M + 16 + rnk_w + 16, cy + (item_h - 1) // 2 - 8),
                      str(name)[:35], fill=C_WHITE, font=name_font)

            # Percentage
            pct_font = _font(14, bold=True)
            pct_box = draw.textbbox((0, 0), str(pct), font=pct_font)
            pct_w = pct_box[2] - pct_box[0]
            draw.text((W - M - pct_w - 16, cy + (item_h - (pct_box[3] - pct_box[1])) // 2 - pct_box[1]),
                      str(pct), fill=(255, 255, 255, 150), font=pct_font)

            cy += item_h + 8

    # --- Footer ---
    footer_y = H - 60
    draw.line([(M, footer_y), (W - M, footer_y)], fill=(255, 255, 255, 20), width=1)
    footer_y += 16

    draw.text((M, footer_y), "Попробовать бесплатно", fill=(255, 255, 255, 76), font=_font(12))
    draw.text((M, footer_y + 18), "@kinesispro01_bot", fill=C_ACCENT, font=_font(18, bold=True))

    # QR placeholder (right side)
    qr_size = 56
    qr_x = W - M - qr_size
    _rrect(qr_x, footer_y - 4, qr_x + qr_size, footer_y - 4 + qr_size, 12,
           fill=(255, 255, 255, 20), outline=(255, 255, 255, 25))
    qr_font = _font(26)
    qr_fbbox = draw.textbbox((0, 0), "📱", font=qr_font)
    qr_fw = qr_fbbox[2] - qr_fbbox[0]
    qr_fh = qr_fbbox[3] - qr_fbbox[1]
    draw.text((qr_x + (qr_size - qr_fw) // 2, qr_y := footer_y - 4 + (qr_size - qr_fh) // 2 - qr_fbbox[1]),
              "📱", fill=(255, 255, 255, 120), font=qr_font)

    # Save
    img.save(out_file)
    return out_file


# ── Public API ───────────────────────────────────────────────────────────

def generate_card(diag_ru: str, confidence_pct: str, risk: str = "low",
                   top3: list = None, user_id: str = "0") -> str:
    """Generate card image. Returns path to saved PNG."""
    top3 = top3 or []
    out_file = str(OUT_DIR / f"card_{user_id}.png")

    chrome = _find_chrome()
    if chrome:
        # Chrome headless
        t3_json = json.dumps(top3, ensure_ascii=False)
        params = f"?d={re.sub(r'[^а-яА-Яa-zA-Z0-9 ]', '', diag_ru).strip()}&c={confidence_pct.replace('%','')}&r={risk}&t={urllib.parse.quote(t3_json)}"
        url = f"file:///{HTML_TPL.as_posix()}{params}"
        try:
            subprocess.run([
                chrome, "--headless=new", f"--screenshot={out_file}",
                "--window-size=800,700", "--hide-scrollbars", "--disable-gpu", url
            ], check=True, capture_output=True, timeout=15)
            return out_file
        except Exception:
            # Chrome failed, fall through to PIL
            pass

    # PIL fallback
    return _gen_pil(diag_ru, confidence_pct, risk, top3, out_file)


if __name__ == "__main__":
    path = generate_card("Акне вульгарис", "93.5%", "low",
        [("Акне вульгарис", "93.5%"), ("Периоральный дерматит", "4.2%"), ("Розацеа", "2.3%")],
        "test")
    print(f"✅ Saved: {path} ({os.path.getsize(path)} bytes)")
