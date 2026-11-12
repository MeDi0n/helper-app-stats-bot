"""
Автообновление TU_TEAMS (команда/кабинет анкеты) через
POST https://v3.management-api.helper-app.com/v2/cabinets/list -
тем же аккаунтом, что и всё остальное (никакой отдельный "админский"
логин не нужен, это один и тот же аккаунт).

Перезаписывает TU_TEAMS в config.py, оставляя TU_IDS/TU_NAMES как есть.
"""
import json
import re
from pathlib import Path

from auth import build_session

MGMT_BASE = "https://v3.management-api.helper-app.com"
CONFIG_PATH = Path(__file__).parent / "config.py"


def fetch_cabinets(sess):
    r = sess.post(f"{MGMT_BASE}/v2/cabinets/list", json={"items": [{}]}, timeout=30)
    r.raise_for_status()
    return r.json()["results"][0]["data"]["cabinets"]


def _clean_cabinet_name(raw: str) -> str:
    """'Ilona\"Gosha  Andrey Danya\"' -> 'Gosha Andrey Danya' (имя владельца
    и кавычки - обёртка сайта, внутри - 3 оператора по сменам)."""
    m = re.search(r'"([^"]*)"', raw)
    inner = m.group(1) if m else raw
    return " ".join(inner.split())


def build_tu_teams(cabinets):
    tu_teams = {}
    for cab in cabinets:
        name = _clean_cabinet_name(cab["name"])
        for tu_id in cab.get("tuIds", []):
            tu_teams[tu_id] = name
    return tu_teams


def write_tu_teams(tu_teams: dict):
    text = CONFIG_PATH.read_text(encoding="utf-8")
    lines = ["TU_TEAMS = {"]
    for tu_id in sorted(tu_teams):
        lines.append(f'    {tu_id}: {json.dumps(tu_teams[tu_id], ensure_ascii=False)},')
    lines.append("}")
    new_block = "\n".join(lines)

    pattern = re.compile(r"TU_TEAMS = \{.*?\n\}", re.DOTALL)
    if pattern.search(text):
        text = pattern.sub(new_block, text, count=1)
    else:
        text = text.rstrip() + "\n\n" + new_block + "\n"
    CONFIG_PATH.write_text(text, encoding="utf-8")


def main():
    sess = build_session()
    cabinets = fetch_cabinets(sess)
    tu_teams = build_tu_teams(cabinets)
    write_tu_teams(tu_teams)
    print(f"Команды обновлены: {len(cabinets)} кабинетов, {len(tu_teams)} анкет")
    for cab in sorted(cabinets, key=lambda c: c["name"]):
        print(f"  {_clean_cabinet_name(cab['name'])}: {len(cab.get('tuIds', []))} анкет")


if __name__ == "__main__":
    main()
