"""Пробуем /v2/trusted-users/list - вдруг это и есть официальный список
анкет (tuId), привязанных к текущему аккаунту."""
import json
from auth import build_session

BASE_V2 = "https://api.helper-app.com/v2"


def main():
    sess = build_session()
    for body in ({"items": [{}]}, {}, {"items": []}):
        r = sess.post(f"{BASE_V2}/trusted-users/list", json=body, timeout=30)
        print(f"body={body} -> status={r.status_code}")
        if r.status_code == 200:
            print(json.dumps(r.json(), ensure_ascii=False, indent=2)[:3000])
            print("---")


if __name__ == "__main__":
    main()
