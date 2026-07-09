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
    import math

    W, H = 800, 700
    M = 40

    # ── Font loading ─────────────────────────────────────────────────────
    _FONT_CACHE = {}

    def _font(size, bold=False):
        key = (size, bold)
        if key in _FONT_CACHE:
            return _FONT_CACHE[key]
        # Bundled NotoSans — works on Railway, variable font w/ Cyrillic support
        _noto = str(Path(__file__).parent / "static" / "fonts" / "NotoSans.ttf")
        candidates = [
            _noto,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
        for fp in candidates:
            if os.path.exists(fp):
                try:
                    f = ImageFont.truetype(fp, size)
                    _FONT_CACHE[key] = f
                    return f
                except Exception:
                    pass
        f = ImageFont.load_default()
        _FONT_CACHE[key] = f
        return f

    # ── Color palette ────────────────────────────────────────────────────
    C_BG_TOP = (26, 26, 46)        # #1a1a2e
    C_BG_MID = (22, 33, 62)        # #16213e
    C_BG_BOT = (15, 52, 96)        # #0f3460
    C_ACCENT = (233, 69, 96)       # #e94560
    C_ACCENT2 = (255, 107, 129)    # #ff6b81
    C_WHITE = (255, 255, 255)
    C_GREEN = (46, 204, 113)
    C_YELLOW = (241, 196, 15)
    C_RED = (231, 76, 60)
    C_ORB_RED = (233, 69, 96)
    C_ORB_GREEN = (46, 204, 113)

    # ── Gradient helpers (numpy-fast) ────────────────────────────────────

    def _linear_gradient(w, h, top_color, bottom_color):
        """Vertical linear gradient. Returns RGB."""
        r1, g1, b1 = top_color[:3]
        r2, g2, b2 = bottom_color[:3]
        rows = np.arange(h, dtype=np.float32) / max(h - 1, 1)
        r = (r1 + (r2 - r1) * rows).astype(np.uint8).reshape(-1, 1)
        g = (g1 + (g2 - g1) * rows).astype(np.uint8).reshape(-1, 1)
        b = (b1 + (b2 - b1) * rows).astype(np.uint8).reshape(-1, 1)
        arr = np.tile(np.stack([r, g, b], axis=2), (1, w, 1))
        return Image.fromarray(arr, "RGB")

    def _radial_gradient_rgba(w, h, cx, cy, inner_rgba, outer_rgba):
        """Radial gradient in RGBA mode."""
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

    # ── Build the background ─────────────────────────────────────────────
    bg_img = Image.new("RGB", (W, H))
    top_half = _linear_gradient(W, H // 2, C_BG_TOP, C_BG_MID)
    bot_half = _linear_gradient(W, H - H // 2, C_BG_MID, C_BG_BOT)
    bg_img.paste(top_half, (0, 0))
    bg_img.paste(bot_half, (0, H // 2))

    # Composite decorative radial orbs
    composite = bg_img.convert("RGBA")
    orb_tr = _radial_gradient_rgba(W, H, 550, 50, (*C_ORB_RED, 25), (*C_ORB_RED, 0))
    composite = Image.alpha_composite(composite, orb_tr)
    orb_bl = _radial_gradient_rgba(W, H, 50, 600, (*C_ORB_GREEN, 15), (*C_ORB_GREEN, 0))
    composite = Image.alpha_composite(composite, orb_bl)

    # Work in RGBA — draw calls respect alpha
    img = composite
    draw = ImageDraw.Draw(img)

    def _rrect(x1, y1, x2, y2, r, fill=None, outline=None, width=1):
        draw.rounded_rectangle([(x1, y1), (x2, y2)], radius=r, fill=fill, outline=outline, width=width)

    # ══════════════════════════════════════════════════════════════════════
    # LAYOUT
    # ══════════════════════════════════════════════════════════════════════

    # --- Header ---
    icon_x, icon_y = M, M
    _rrect(icon_x, icon_y, icon_x + 40, icon_y + 40, 12, fill=C_ACCENT)
    draw.text((icon_x + 10, icon_y + 8), "🔬", fill=C_WHITE, font=_font(18))

    logo_x = icon_x + 52
    draw.text((logo_x, icon_y + 9), "Skin", fill=C_WHITE, font=_font(20, bold=True))
    skin_w = draw.textbbox((0, 0), "Skin", font=_font(20, bold=True))[2]
    draw.text((logo_x + skin_w, icon_y + 9), "Coach", fill=C_ACCENT, font=_font(20, bold=True))

    # Badge
    badge_text = "AI · 8-слойный анализ"
    badge_font = _font(11, bold=True)
    bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    btw, bth = bbox[2] - bbox[0], bbox[3] - bbox[1]
    badge_pad_x, badge_pad_y = 14, 7
    badge_x = W - M - btw - badge_pad_x * 2
    badge_y = icon_y + 7
    _rrect(badge_x, badge_y,
           badge_x + btw + badge_pad_x * 2, badge_y + bth + badge_pad_y * 2, 20,
           fill=(233, 69, 96, 50), outline=(233, 69, 96, 76))
    draw.text((badge_x + badge_pad_x, badge_y + badge_pad_y),
              badge_text, fill=C_ACCENT, font=badge_font)

    # Divider
    div_y = icon_y + 55
    draw.rectangle([(M, div_y), (W - M, div_y + 1)], fill=(255, 255, 255, 20))

    # --- Content ---
    cy = div_y + 28

    # Diagnosis label
    draw.text((M, cy), "ДИАГНОЗ", fill=(255, 255, 255, 140), font=_font(11, bold=True))
    cy += 22

    # Diagnosis name
    draw.text((M, cy), diag_ru[:50], fill=C_WHITE, font=_font(36, bold=True))
    cy += 48

    # Confidence bar
    try:
        pct_val = int(float(str(confidence_pct).replace("%", "").strip()))
    except Exception:
        pct_val = 85
    pct_val = min(max(pct_val, 0), 100)

    bar_w, bar_h, bar_r = 400, 6, 3
    bar_y = cy
    _rrect(M, bar_y, M + bar_w, bar_y + bar_h, bar_r, fill=(255, 255, 255, 25))

    fill_w = int(bar_w * pct_val / 100)
    if fill_w > bar_r * 2:
        grad_fill = _linear_gradient(fill_w, bar_h, C_ACCENT, C_ACCENT2)
        mask = Image.new("L", (fill_w, bar_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (fill_w - 1, bar_h - 1)], radius=bar_r, fill=255)
        img.paste(grad_fill.crop((0, 0, fill_w, bar_h)), (M, bar_y), mask)
    elif fill_w > 0:
        _rrect(M, bar_y, M + fill_w, bar_y + bar_h, bar_r, fill=C_ACCENT)

    cy = bar_y + bar_h + 24

    # --- Stats cards ---
    card_w = (W - 2 * M - 16) // 2
    card_h = 72

    # Card 1: Confidence
    c1x = M
    _rrect(c1x, cy, c1x + card_w, cy + card_h, 16,
           fill=(255, 255, 255, 12), outline=(255, 255, 255, 16))
    draw.text((c1x + 18, cy + 12), "УВЕРЕННОСТЬ", fill=(255, 255, 255, 100),
              font=_font(10, bold=True))
    draw.text((c1x + 18, cy + 32), str(confidence_pct), fill=C_WHITE,
              font=_font(24, bold=True))

    # Card 2: Risk
    c2x = c1x + card_w + 16
    _rrect(c2x, cy, c2x + card_w, cy + card_h, 16,
           fill=(255, 255, 255, 12), outline=(255, 255, 255, 16))
    draw.text((c2x + 18, cy + 12), "УРОВЕНЬ РИСКА", fill=(255, 255, 255, 100),
              font=_font(10, bold=True))

    risk_label = {"low": "Низкий", "medium": "Средний", "high": "Высокий — к врачу!"}
    risk_colors = {"low": C_GREEN, "medium": C_YELLOW, "high": C_RED}
    rlbl = risk_label.get(risk, "Низкий")
    rcol = risk_colors.get(risk, C_GREEN)

    badge_txt = f"● {rlbl}"
    bf = _font(12, bold=True)
    bb = draw.textbbox((0, 0), badge_txt, font=bf)
    bw, bh = bb[2] - bb[0], bb[3] - bb[1]
    bx, by = c2x + 18, cy + 34
    _rrect(bx, by, bx + bw + 28, by + bh + 12, 20,
           fill=(*rcol, 38), outline=(*rcol, 60))
    draw.text((bx + 14, by + 6), badge_txt, fill=rcol, font=bf)

    cy += card_h + 28

    # --- Top 3 ---
    if top3:
        draw.text((M, cy), "ТОП ГИПОТЕЗ", fill=(255, 255, 255, 140),
                  font=_font(11, bold=True))
        cy += 24

        for i, (name, pct) in enumerate(top3[:3]):
            ih = 44
            _rrect(M, cy, W - M, cy + ih, 12,
                   fill=(255, 255, 255, 8), outline=(255, 255, 255, 12))

            rank = f"{i + 1:02d}"
            rf = _font(14, bold=True)
            rb = draw.textbbox((0, 0), rank, font=rf)
            rw, rh = rb[2] - rb[0], rb[3] - rb[1]
            draw.text((M + 16, cy + (ih - rh) // 2 - rb[1]),
                      rank, fill=(255, 255, 255, 76), font=rf)

            draw.text((M + 16 + rw + 16, cy + (ih - 1) // 2 - 8),
                      str(name)[:35], fill=C_WHITE, font=_font(15))

            pf = _font(14, bold=True)
            pb = draw.textbbox((0, 0), str(pct), font=pf)
            pw, ph = pb[2] - pb[0], pb[3] - pb[1]
            draw.text((W - M - pw - 16, cy + (ih - ph) // 2 - pb[1]),
                      str(pct), fill=(255, 255, 255, 150), font=pf)

            cy += ih + 8

    # --- Footer ---
    fy = H - 60
    draw.rectangle([(M, fy), (W - M, fy + 1)], fill=(255, 255, 255, 20))
    fy += 16

    draw.text((M, fy), "Попробовать бесплатно", fill=(255, 255, 255, 76), font=_font(12))
    draw.text((M, fy + 18), "@kinesispro01_bot", fill=C_ACCENT, font=_font(18, bold=True))

    # QR icon
    qs = 56
    qx = W - M - qs
    _rrect(qx, fy - 4, qx + qs, fy - 4 + qs, 12,
           fill=(255, 255, 255, 20), outline=(255, 255, 255, 25))
    draw.text((qx + 14, fy), "📱", fill=(255, 255, 255, 120), font=_font(26))

    # ── Flatten to RGB and save ──────────────────────────────────────────
    rgb_img = Image.new("RGB", (W, H), (0, 0, 0))
    rgb_img.paste(img, (0, 0), img)
    rgb_img.save(out_file)
    return out_file


# ── Public API ───────────────────────────────────────────────────────────

def generate_card(diag_ru: str, confidence_pct: str, risk: str = "low",
                   top3: list = None, user_id: str = "0") -> str:
    """Generate card image. Returns path to saved PNG."""
    top3 = top3 or []
    out_file = str(OUT_DIR / f"card_{user_id}.png")

    chrome = _find_chrome()
    if chrome:
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
            pass

    # PIL fallback
    return _gen_pil(diag_ru, confidence_pct, risk, top3, out_file)


if __name__ == "__main__":
    path = generate_card("Акне вульгарис", "93.5%", "low",
        [("Акне вульгарис", "93.5%"), ("Периоральный дерматит", "4.2%"), ("Розацеа", "2.3%")],
        "test")
    print(f"✅ Saved: {path} ({os.path.getsize(path)} bytes)")
