"""
Защита от ложных фейлов из-за пропусков синхронизации (см. разбор чата
Captain/Atriyani - 11.11.2026): для каждого найденного фейла точечно
докачивает полную историю именно этой пары (tu_id, ru_id) от сайта,
вставляет то, чего не хватало, и сообщает, что изменилось.

Запускать перед generate_report.py, когда не уверен в честности фейлов
(например, после первого полного прогона).
"""
import sys
import time

from auth import build_session
from api import fetch_messages_batch
from db import get_connection, insert_messages
from sync import _message_to_row, BACKFILL_CUTOFF, REQUEST_DELAY_SEC
from fails import compute_fails
from report_common import shift_bounds_utc
from datetime import datetime, timedelta


def patch_pair(sess, conn, tu_id: int, ru_id: int, ru_name) -> int:
    cursor = None
    total_new = 0
    pages = 0
    while pages < 30:  # щедрый, но конечный предел на пару
        pages += 1
        item = {"tuId": tu_id, "ruId": ru_id, "limit": 30}
        if cursor:
            item["cursor"] = cursor
        results = fetch_messages_batch(sess, [item])
        data = results[0].get("data", {})
        msgs = data.get("items", [])
        if not msgs:
            break
        rows = [_message_to_row(m, tu_id, ru_id, ru_name) for m in msgs if m["createdAt"] >= BACKFILL_CUTOFF]
        total_new += insert_messages(conn, rows)
        oldest = min(msgs, key=lambda m: m["createdAt"])
        if oldest["createdAt"] < BACKFILL_CUTOFF:
            break
        cursor = data.get("nextCursor")
        if not cursor:
            break
        time.sleep(REQUEST_DELAY_SEC)
    return total_new


def verify_and_patch_for_date(sess, conn, local_date, log=print):
    """Для всех фейлов конкретного операционного дня точечно докачивает
    полную историю пары, чтобы не считать фейлом то, что на самом деле
    просто не досинхронизировалось. Возвращает (было, стало, довставлено)."""
    day_start, day_end = shift_bounds_utc(local_date, 6, 30)
    fail_list = compute_fails(conn, day_start, day_end)
    pairs = sorted({(f["tu_id"], f["ru_id"]) for f in fail_list})
    patched_new_msgs = 0
    for tu_id, ru_id in pairs:
        ru_name = next((f["ru_name"] for f in fail_list if f["tu_id"] == tu_id and f["ru_id"] == ru_id), None)
        n = patch_pair(sess, conn, tu_id, ru_id, ru_name)
        if n:
            patched_new_msgs += n
            log(f"  фейлы: {tu_id}/{ru_id} - была дыра в синхронизации, +{n} сообщений")
        conn.commit()
    fail_list_after = compute_fails(conn, day_start, day_end)
    return len(fail_list), len(fail_list_after), patched_new_msgs


def main():
    if len(sys.argv) > 1:
        local_date = datetime.strptime(sys.argv[1], "%Y-%m-%d")
    else:
        now = datetime.now()
        local_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now.hour < 6:
            local_date -= timedelta(days=1)

    sess = build_session()
    conn = get_connection()
    before, after, patched = verify_and_patch_for_date(sess, conn, local_date)
    print(f"\nДо проверки: {before} фейлов. После докачки пропусков: {after}.")
    print(f"Довставлено сообщений в базу: {patched}")


if __name__ == "__main__":
    main()
