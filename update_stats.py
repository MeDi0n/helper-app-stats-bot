"""
Кнопка. Двойной клик (через Обновить статистику.cmd) или
`python update_stats.py`: подтягивает всё новое, продлевает сессию,
пересобирает отчёты за вчера/сегодня (условные сутки 06:00-06:00).
"""
import sys
from datetime import datetime, timedelta

import requests

from auth import build_session, prolong, login
from db import get_connection
from sync import run_cycle
from verify_fails import verify_and_patch_for_date
import refresh_teams


def main():
    full_sweep = "--full" in sys.argv
    sess = build_session()
    if not prolong(sess):
        print("Продлить сессию не удалось (возможно, роль аккаунта не даёт прав на это) - "
              "пробую работать с текущей сессией как есть.")

    print("Полная проверка всех чатов..." if full_sweep else "Собираю всё новое...")
    conn = get_connection()
    try:
        stats = run_cycle(sess, conn, log=print, full_sweep=full_sweep)
    except requests.exceptions.HTTPError as e:
        if e.response is None or e.response.status_code != 401:
            raise
        print("Сессия протухла (401) - логинюсь заново по email/паролю из .env...")
        sess = login()
        stats = run_cycle(sess, conn, log=print, full_sweep=full_sweep)
    print(f"Готово: проверено {stats['chats_checked']} из {stats['chats_total']} чатов, "
          f"новых чатов {stats['new_chats']}, новых сообщений {stats['new_messages']}")

    now = datetime.now()
    operational_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now.hour < 6:
        operational_today -= timedelta(days=1)
    operational_yesterday = operational_today - timedelta(days=1)

    print("\nПроверяю фейлы на пропуски синхронизации...")
    for day in (operational_yesterday, operational_today):
        before, after, patched = verify_and_patch_for_date(sess, conn, day, log=print)
        if patched:
            print(f"  {day.strftime('%d.%m')}: {before} -> {after} фейлов, довставлено {patched} сообщений")

    print("\nОбновляю команды/кабинеты...")
    cabinets = refresh_teams.fetch_cabinets(sess)
    refresh_teams.write_tu_teams(refresh_teams.build_tu_teams(cabinets))
    print(f"  {len(cabinets)} кабинетов")

    # Импортируем после обновления config.py, чтобы TU_TEAMS подхватился свежим
    import generate_report
    import generate_chat_pages

    print("\nПересобираю отчёты...")
    generate_report.generate_for_date(conn, operational_yesterday)
    generate_report.generate_for_date(conn, operational_today)
    generate_chat_pages.generate_all()

    print("\nГотово! Открой reports/index.html")


if __name__ == "__main__":
    main()
