"""
Разовый скрипт: тянет полный список анкет аккаунта через management API
(https://v3.management-api.helper-app.com/v2/trusted-users/list) и
перезаписывает config.py актуальными TU_IDS/TU_NAMES (alias как имя).

TU_TEAMS (команда/кабинет) этим скриптом НЕ обновляется - эти данные видны
только на отдельном админ-аккаунте "Ilona" (Schedules > Profiles), бот туда
доступа не имеет. Существующие значения TU_TEAMS сохраняются как есть;
новым анкетам, которых там ещё не было, проставляется "?" - дозаполнить
вручную, посмотрев нужный кабинет на том аккаунте.
"""
import json
from auth import build_session
import config as _old_config

MGMT_BASE = "https://v3.management-api.helper-app.com"


def fetch_trusted_users(sess):
    r = sess.post(f"{MGMT_BASE}/v2/trusted-users/list", json={"items": [{}]}, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["results"][0]["data"]["trustedUsers"]


def main():
    sess = build_session()
    users = fetch_trusted_users(sess)
    users.sort(key=lambda u: u["tuId"])

    tu_ids = [u["tuId"] for u in users]
    tu_names = {u["tuId"]: (u.get("alias") or u.get("name") or str(u["tuId"])).strip() for u in users}
    old_teams = getattr(_old_config, "TU_TEAMS", {})
    tu_teams = {u["tuId"]: old_teams.get(u["tuId"], "?") for u in users}

    lines = []
    lines.append('"""')
    lines.append("ID анкет (tuId) этого аккаунта на helper-app.com - получены через")
    lines.append("management API (/v2/trusted-users/list), см. refresh_config.py.")
    lines.append('"""')
    lines.append(f"TU_IDS = {json.dumps(tu_ids)}")
    lines.append("")
    lines.append("TU_NAMES = {")
    for u in users:
        lines.append(f'    {u["tuId"]}: {json.dumps(tu_names[u["tuId"]], ensure_ascii=False)},')
    lines.append("}")
    lines.append("")
    lines.append("# Команда (кабинет) анкеты - вручную со Schedules > Profiles на аккаунте Ilona")
    lines.append("TU_TEAMS = {")
    for u in users:
        lines.append(f'    {u["tuId"]}: {json.dumps(tu_teams[u["tuId"]], ensure_ascii=False)},')
    lines.append("}")
    lines.append("")

    with open("config.py", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Записано {len(users)} анкет в config.py")


if __name__ == "__main__":
    main()
