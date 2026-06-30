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

client = TestClient(app)


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["message"] == "SkinCoach Web API"
    print("OK root")


def test_auth_dev():
    r = client.post("/api/auth/telegram", json={"init_data": ""})
    assert r.status_code == 200
    data = r.json()
    assert data["user"]["username"] == "dev"
    print("OK auth dev")


def test_analyze_without_photo():
    r = client.post("/api/analyze/", data={"init_data": ""})
    # без файла должна быть ошибка валидации
    assert r.status_code == 422
    print("OK analyze requires photo")


def test_program():
    r = client.get("/api/program/?init_data=")
    assert r.status_code == 200
    data = r.json()
    assert data["day"] == 1
    print("OK program")


def test_profile():
    r = client.get("/api/profile/?init_data=")
    assert r.status_code == 200
    data = r.json()
    assert "user" in data
    print("OK profile")


if __name__ == "__main__":
    test_root()
    test_auth_dev()
    test_analyze_without_photo()
    test_program()
    test_profile()
    print("\nВсе тесты пройдены")
