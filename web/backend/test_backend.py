"""
Быстрый тест бэкенда через TestClient.
"""
import os
import sys

BASE_DIR = r"C:\Users\Design\Desktop\skincoach\web\backend"
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

from fastapi.testclient import TestClient
from main import app


def run_tests():
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code in (200, 307)
        print("OK root")

        r = client.post("/api/auth/login", json={"name": "Тестовый"})
        assert r.status_code == 200
        data = r.json()
        assert data["user"]["name"] == "Тестовый"
        user_id = data["user"]["id"]
        print("OK login")

        r = client.get(f"/api/profile/?user_id={user_id}")
        assert r.status_code == 200
        print("OK profile")

        r = client.get(f"/api/program/?user_id={user_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["day"] == 1
        print("OK program")

        r = client.post("/api/analyze/", data={"user_id": user_id})
        assert r.status_code == 422
        print("OK analyze requires photo")

        print("\nВсе тесты пройдены")


if __name__ == "__main__":
    run_tests()
