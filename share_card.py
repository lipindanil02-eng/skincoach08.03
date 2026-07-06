"""Generate shareable diagnosis card for SkinCoach."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

FONT_DIR = Path("C:/Windows/Fonts")
BOT_USERNAME = "@kinesispro01_bot"
OUT = Path(__file__).parent / "static" / "share_card.jpg"

COLORS = {
    "bg": "#1a1a2e", "card": "#16213e", "accent": "#e94560",
    "text": "#ffffff", "muted": "#a0a0b0",
    "green": "#2ecc71", "yellow": "#f1c40f", "red": "#e74c3c",
}

def _font(size: int, bold=False):
    try:
        return ImageFont.truetype(str(FONT_DIR / ("calibrib.ttf" if bold else "calibri.ttf")), size)
    except Exception:
        try:
            return ImageFont.truetype(str(FONT_DIR / ("arialbd.ttf" if bold else "arial.ttf")), size)
        except Exception:
            return ImageFont.load_default()

def make_card(diag_ru: str, confidence: str, risk: str = "low", top3: list = None) -> str:
    W, H = 800, 600
    img = Image.new("RGB", (W, H), COLORS["bg"])
    d = ImageDraw.Draw(img)
    f = _font

    # Card bg
    d.rounded_rectangle([(30, 30), (W - 30, H - 30)], 20, fill=COLORS["card"])
    # Header
    d.rectangle([(30, 30), (W - 30, 90)], fill=COLORS["accent"])
    d.text((W // 2, 60), "🔬 SkinCoach — AI Анализ Кожи", fill=COLORS["text"], font=f(22, True), anchor="mt")
    # Diagnosis
    d.text((W // 2, 160), diag_ru, fill=COLORS["text"], font=f(36, True), anchor="mt")
    d.text((W // 2, 220), f"Уверенность: {confidence}", fill=COLORS["muted"], font=f(20), anchor="mt")
    # Risk
    risk_col = {"high": COLORS["red"], "medium": COLORS["yellow"]}.get(risk, COLORS["green"])
    risk_lbl = {"high": "Высокий риск — к врачу!", "medium": "Средний риск"}.get(risk, "Низкий риск")
    d.rounded_rectangle([(W // 2 - 130, 270), (W // 2 + 130, 320)], 10, fill=risk_col)
    d.text((W // 2, 295), risk_lbl, fill=COLORS["bg"], font=f(16, True), anchor="mt")
    # Top 3
    y = 370
    d.text((50, y), "Топ-3 гипотезы:", fill=COLORS["muted"], font=f(16, True))
    y += 30
    if top3:
        for t in top3[:3]:
            diag = t.get("diagnosis_ru", t.get("diagnosis", "?"))
            pct = t.get("confidence_pct", f"{float(t.get('confidence', 0)) * 100:.1f}%")
            d.text((70, y), f"• {diag} — {pct}", fill=COLORS["text"], font=f(17))
            y += 28
    # Footer
    d.text((W // 2, H - 80), "Попробовать бесплатно:", fill=COLORS["muted"], font=f(14), anchor="mb")
    d.text((W // 2, H - 50), BOT_USERNAME, fill=COLORS["accent"], font=f(24, True), anchor="mt")
    d.text((W - 20, H - 20), "skincoach.app", fill=COLORS["muted"], font=f(10), anchor="rb")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(OUT), "JPEG", quality=92)
    return str(OUT)
