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
        assert r.status_code == 200
        assert r.json()["message"] == "SkinCoach Web API"
        print("OK root")

        r = client.post("/api/auth/telegram", json={"init_data": ""})
        assert r.status_code == 200
        data = r.json()
        assert data["user"]["username"] == "dev"
        print("OK auth dev")

        r = client.post("/api/analyze/", data={"init_data": ""})
        assert r.status_code == 422
        print("OK analyze requires photo")

        r = client.get("/api/program/?init_data=")
        assert r.status_code == 200
        data = r.json()
        assert data["day"] == 1
        print("OK program")

        r = client.get("/api/profile/?init_data=")
        assert r.status_code == 200
        data = r.json()
        assert "user" in data
        print("OK profile")

        print("\nВсе тесты пройдены")


if __name__ == "__main__":
    run_tests()
