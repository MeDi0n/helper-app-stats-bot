"""
Разовый вход + диагностика в одном. Открывает отдельное окно браузера
(не трогает твой обычный Chrome/Edge). Логинишься вручную -> скрипт:
  - сохраняет сессию (storage_state.json) для дальнейшей работы без браузера
  - печатает (с замаскированным паролем) структуру запроса логина
  - печатает структуру первого ответа от /v1/chat/messages (чтобы понять
    формат сообщений на этой площадке)
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
STORAGE_STATE_PATH = HERE / "storage_state.json"

SECRET_FIELDS = {"password", "pass", "pwd", "secret", "accesstoken", "token", "refreshtoken"}


def redact(obj):
    if isinstance(obj, dict):
        return {k: ("<redacted>" if k.lower() in SECRET_FIELDS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def redact_raw(body_str):
    if not body_str:
        return None
    try:
        return json.dumps(redact(json.loads(body_str)), ensure_ascii=False)
    except Exception:
        return "<non-json body>"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        captured_login = []
        captured_messages = []

        def on_request(req):
            if "api.helper-app.com" not in req.url:
                return
            path = req.url.split("api.helper-app.com", 1)[1].split("?")[0]
            if any(k in path.lower() for k in ("auth", "login", "/token", "sign-in", "session")):
                captured_login.append({
                    "url": req.url, "method": req.method,
                    "body": redact_raw(req.post_data),
                })
            if "/chat/messages" in req.url:
                captured_messages.append({"type": "request", "url": req.url,
                                           "body": redact_raw(req.post_data)})

        def on_response(res):
            if "/chat/messages" in res.url and len(captured_messages) < 6:
                try:
                    body = res.text()
                except Exception:
                    body = "<unavailable>"
                captured_messages.append({"type": "response", "url": res.url, "status": res.status,
                                           "body": body[:3000]})

        page.on("request", on_request)
        page.on("response", on_response)

        page.goto("https://helper-app.com/")
        print("Окно открыто. Войди вручную, затем открой пару диалогов с сообщениями.")
        print("Жду появления AUTH_DATA (до 10 минут)...")

        try:
            page.wait_for_function(
                "() => !!localStorage.getItem('AUTH_DATA')", timeout=10 * 60 * 1000
            )
        except Exception:
            print("Не дождался входа.")
            browser.close()
            return

        print("Вход замечен. Открой пару диалогов с сообщениями, подожди 30 секунд...")
        page.wait_for_timeout(30000)

        context.storage_state(path=str(STORAGE_STATE_PATH))
        print(f"\nСессия сохранена: {STORAGE_STATE_PATH}")

        print("\n--- Запросы логина (пароль скрыт) ---")
        for entry in captured_login[:5]:
            print(json.dumps(entry, ensure_ascii=False, indent=2))

        print("\n--- chat/messages (запрос/ответ) ---")
        for entry in captured_messages[:6]:
            print(json.dumps(entry, ensure_ascii=False, indent=2)[:2000])

        (HERE / "diagnose_dump.json").write_text(
            json.dumps({"login": captured_login, "messages": captured_messages}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nПолный дамп сохранён: {HERE / 'diagnose_dump.json'}")

        browser.close()


if __name__ == "__main__":
    main()
