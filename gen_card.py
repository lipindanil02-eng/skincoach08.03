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


def _gen_pil(diag_ru, confidence_pct, risk, top3, out_file):
    """PIL fallback when Chrome is unavailable."""
    from PIL import Image, ImageDraw, ImageFont

    W, H = 800, 700
    img = Image.new("RGB", (W, H), "#1a1a2e")
    draw = ImageDraw.Draw(img)

    # Try fonts
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]

    def _font(size, bold=False):
        for fp in font_paths:
            if os.path.exists(fp):
                try:
                    return ImageFont.truetype(fp, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    f_big = _font(30)
    f_med = _font(18)
    f_small = _font(14)

    # Header
    draw.rectangle([(0, 0), (W, 60)], fill="#16213e")
    draw.text((20, 15), "🩺 SkinCoach", fill="#e94560", font=_font(22, bold=True))
    draw.text((W - 140, 18), "AI · 8 слоёв", fill="gray", font=_font(12))

    # Diagnosis
    y = 80
    draw.text((30, y), "ДИАГНОЗ", fill="gray", font=_font(12))
    y += 22
    draw.text((30, y), diag_ru[:40], fill="white", font=f_big)
    y += 50

    # Confidence bar
    try:
        pct_val = int(float(confidence_pct.replace("%", "")))
    except Exception:
        pct_val = 85
    bar_w = int(min(pct_val, 100) * 4)
    draw.rectangle([(30, y), (430, y + 6)], fill="#333")
    draw.rectangle([(30, y), (30 + bar_w, y + 6)], fill="#e94560")
    y += 30

    # Stats
    risk_label = {"low": "Низкий", "medium": "Средний", "high": "Высокий"}
    draw.text((30, y), f"Уверенность:  {confidence_pct}", fill="white", font=f_med)
    draw.text((30, y + 28), f"Риск:  {risk_label.get(risk, risk)}", fill="#2ecc71" if risk == "low" else "#f1c40f" if risk == "medium" else "#e74c3c", font=f_med)
    y += 70

    # Top 3
    if top3:
        draw.text((30, y), "ТОП ГИПОТЕЗ", fill="gray", font=_font(12))
        y += 22
        for i, (name, pct) in enumerate(top3[:3]):
            draw.rectangle([(30, y), (W - 30, y + 32)], fill="#16213e")
            draw.text((40, y + 4), f"{i+1:02d}", fill="gray", font=_font(14))
            draw.text((75, y + 4), str(name)[:30], fill="white", font=_font(15))
            draw.text((W - 90, y + 4), str(pct), fill="gray", font=_font(14))
            y += 38

    # Footer
    draw.text((30, H - 40), "Спасибо за доверие", fill="gray", font=_font(12))
    draw.text((W - 180, H - 40), "@kinesispro01_bot", fill="#e94560", font=_font(14))

    img.save(out_file)
    return out_file


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
