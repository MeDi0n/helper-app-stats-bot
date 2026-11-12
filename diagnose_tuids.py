"""
Разовая диагностика: открывает окно браузера УЖЕ залогиненным (через
сохранённый storage_state.json), слушает сетевые запросы и печатает
(без секретов) все tuId, которые встретились в communication/list или
chat/messages - чтобы узнать список анкет (tuId) этого аккаунта.

Открой в окне пару диалогов из разных анкет, подожди - скрипт сам
закроется через 40 секунд после старта.
"""
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
STORAGE_STATE_PATH = HERE / "storage_state.json"


def main():
    if not STORAGE_STATE_PATH.exists():
        print("Нет storage_state.json - сначала login_and_diagnose.py")
        return

    found_tu_ids = set()
    seen_paths = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(STORAGE_STATE_PATH))
        page = context.new_page()

        def scan(url, body):
            path = url.split("api.helper-app.com", 1)[-1].split("?")[0]
            seen_paths.add(path)
            for m in re.finditer(r'"tuId"\s*:\s*(\d+)', body or ""):
                found_tu_ids.add(int(m.group(1)))
            for m in re.finditer(r'"tuIds"\s*:\s*\[([\d,\s]+)\]', body or ""):
                for part in m.group(1).split(","):
                    part = part.strip()
                    if part.isdigit():
                        found_tu_ids.add(int(part))

        def on_request(req):
            if "api.helper-app.com" not in req.url:
                return
            scan(req.url, req.post_data)

        def on_response(res):
            if "api.helper-app.com" not in res.url:
                return
            try:
                scan(res.url, res.text())
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", on_response)

        page.goto("https://helper-app.com/")
        print("Если есть страница со списком ВСЕХ анкет/профилей аккаунта (например")
        print("'Мои анкеты', 'Профили', настройки) - открой её. Иначе просто")
        print("полистай/пощёлкай диалоги в левом меню, подольше и по разным анкетам.")
        print("Жду 180 секунд...")
        for i in range(9):
            page.wait_for_timeout(20000)
            print(f"  ...{(i+1)*20}с, уникальных tuId пока: {len(found_tu_ids)}")

        browser.close()

    print("\nНайденные tuId:", sorted(found_tu_ids))
    print("\nВиденные пути API (ищи что-то похожее на список анкет):")
    for p_ in sorted(seen_paths):
        print(" ", p_)
    (HERE / "found_tu_ids.json").write_text(
        json.dumps(sorted(found_tu_ids)), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
