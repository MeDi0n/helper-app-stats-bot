"""
Авторизация на helper-app.com - через cookies (accessToken/refreshToken,
httpOnly), не через Bearer-токен в заголовке, как было на chat-space.ai.

Два способа получить сессию:
1. Автоматически - login() шлёт POST /v1/auth/login с email/паролем из
   .env (который ты сам заполняешь руками, см. .env.example - он никогда
   не попадает в чат) и сохраняет полученные cookies в storage_state.json.
2. Вручную - login_and_diagnose.py (отдельное окно браузера), если вдруг
   автологин перестанет работать (например, сайт потребует капчу).

build_session() читает storage_state.json (от любого из двух способов).
prolong() держит сессию живой без повторного логина, пока это возможно.
"""
import json
import os
from pathlib import Path

import requests

HERE = Path(__file__).parent
STORAGE_STATE_PATH = HERE / "storage_state.json"
LOGIN_URL = "https://api.helper-app.com/v1/auth/login"

BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "x-requested-by": "chat-v3",
}


def _load_dotenv():
    env_path = HERE / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


def _save_session_cookies(sess: requests.Session):
    cookies = [
        {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path or "/"}
        for c in sess.cookies
    ]
    STORAGE_STATE_PATH.write_text(
        json.dumps({"cookies": cookies, "origins": []}, ensure_ascii=False), encoding="utf-8"
    )


def login() -> requests.Session:
    """Логин по email/паролю из .env (HELPERAPP_EMAIL/HELPERAPP_PASSWORD),
    без браузера. Сохраняет cookies в storage_state.json и возвращает
    готовую сессию."""
    email = os.environ.get("HELPERAPP_EMAIL")
    password = os.environ.get("HELPERAPP_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "Нет HELPERAPP_EMAIL/HELPERAPP_PASSWORD. Создай .env (см. .env.example) "
            "и впиши туда свои данные - или запусти login_and_diagnose.py для ручного входа."
        )
    sess = requests.Session()
    sess.headers.update(BASE_HEADERS)
    r = sess.post(LOGIN_URL, json={"items": [{"email": email, "password": password}]}, timeout=20)
    r.raise_for_status()
    _save_session_cookies(sess)
    return sess


def build_session() -> requests.Session:
    if not STORAGE_STATE_PATH.exists():
        return login()
    data = json.loads(STORAGE_STATE_PATH.read_text(encoding="utf-8"))
    sess = requests.Session()
    sess.headers.update(BASE_HEADERS)
    for c in data.get("cookies", []):
        sess.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
    return sess


def prolong(sess: requests.Session) -> bool:
    r = sess.post("https://api.helper-app.com/v1/auth/prolong", json={"items": [{}]}, timeout=20)
    if r.status_code != 200:
        return False
    data = r.json()
    results = data.get("results", [])
    return bool(results and results[0].get("data", {}).get("ok"))
