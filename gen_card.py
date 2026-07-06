"""Generate share card from HTML template using Chrome headless."""
import subprocess, json, sys, os, tempfile, shutil, re
from pathlib import Path

HTML_TPL = Path(__file__).parent / "static" / "share_card.html"
OUT_DIR = Path(__file__).parent / "static" / "cards"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
]


def _find_chrome():
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("Chrome not found. Install Chrome or add path to CHROME_PATHS.")


def generate_card(diag_ru: str, confidence_pct: str, risk: str = "low",
                   top3: list = None, user_id: str = "0") -> str:
    """Generate card image. Returns path to saved PNG."""
    top3 = top3 or []
    params = f"?d={re.sub(r'[^а-яА-Яa-zA-Z0-9 ]', '', diag_ru).strip()}&c={confidence_pct.replace('%','')}&r={risk}"
    url = f"file:///{HTML_TPL.as_posix()}{params}"

    out_file = str(OUT_DIR / f"card_{user_id}.png")
    chrome = _find_chrome()

    subprocess.run([
        chrome, "--headless=new", f"--screenshot={out_file}",
        "--window-size=800,700",
        "--hide-scrollbars",
        "--disable-gpu",
        url
    ], check=True, capture_output=True, timeout=15)

    return out_file


if __name__ == "__main__":
    path = generate_card("Акне вульгарис", "93.5%", "low",
        [("Акне вульгарис", "93.5%"), ("Периоральный дерматит", "4.2%"), ("Розацеа", "2.3%")],
        "test")
    print(f"✅ Saved: {path} ({os.path.getsize(path)} bytes)")
