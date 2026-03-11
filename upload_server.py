"""
Временный upload-сервер для загрузки best_model.pth в Railway Volume.
После загрузки — удалить этот файл и вернуть Procfile к боту.
"""
import os
import http.server
import socketserver
from urllib.parse import urlparse, parse_qs

UPLOAD_TOKEN = os.getenv("UPLOAD_TOKEN", "")
UPLOAD_PATH = os.getenv("MODEL_PATH", "/data/best_model.pth")
PORT = int(os.getenv("PORT", "8080"))


class UploadHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        exists = os.path.exists(UPLOAD_PATH)
        size = os.path.getsize(UPLOAD_PATH) if exists else 0
        msg = f"Upload server ready.\nModel exists: {exists}\nSize: {size} bytes\nUpload path: {UPLOAD_PATH}\n"
        self.wfile.write(msg.encode())

    def do_POST(self):
        # Проверка токена
        token = self.headers.get("X-Upload-Token", "")
        if UPLOAD_TOKEN and token != UPLOAD_TOKEN:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Forbidden: invalid token\n")
            return

        content_length = int(self.headers.get("Content-Length", 0))

        os.makedirs(os.path.dirname(UPLOAD_PATH), exist_ok=True)

        print(f"Получаю файл: {content_length} байт → {UPLOAD_PATH}")

        received = 0
        with open(UPLOAD_PATH, "wb") as f:
            if content_length > 0:
                remaining = content_length
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)
                    remaining -= len(chunk)
            else:
                # chunked или без Content-Length
                while True:
                    chunk = self.rfile.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)

        if received == 0:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No data received\n")
            return

        size = os.path.getsize(UPLOAD_PATH)
        print(f"✅ Файл сохранён: {size} байт")

        self.send_response(200)
        self.end_headers()
        self.wfile.write(f"OK: saved {size} bytes to {UPLOAD_PATH}\n".encode())

    def log_message(self, format, *args):
        print(f"[{self.address_string()}] {format % args}")


if __name__ == "__main__":
    print(f"🚀 Upload server на порту {PORT}")
    print(f"📁 Файл будет сохранён в: {UPLOAD_PATH}")
    if UPLOAD_TOKEN:
        print(f"🔐 Токен защиты включён")
    else:
        print(f"⚠️  UPLOAD_TOKEN не задан — endpoint открыт!")

    with socketserver.TCPServer(("", PORT), UploadHandler) as httpd:
        httpd.serve_forever()
