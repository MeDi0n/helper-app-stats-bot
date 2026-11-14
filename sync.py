"""
Сбор данных с helper-app.com.

1. discover_chats() - один запрос /communication/list сразу даёт ПОЛНЫЙ
   список активных диалогов по всем анкетам (в отличие от chat-space.ai,
   тут не нужно гадать по урезанной ленте - этот список действительно
   полный).

2. sync_all() - тянет сообщения БАТЧАМИ (до BATCH_SIZE чатов за один
   POST к /chat/messages) - новые чаты и обновление уже известных.
   Если в каком-то чате после пачки не достали до уже известного
   сообщения (разрыв) - докачивает именно этот чат отдельно, курсором
   назад, пока не состыкуется или не упрётся в дату отсечения.

Данные от сегодняшнего дня (BACKFILL_CUTOFF, фиксируется один раз).
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from api import (
    fetch_dialog_list_page, fetch_messages_batch, fetch_ru_profiles, BATCH_SIZE,
    fetch_tasks_page, TASK_SUB_TYPES,
)
from db import (
    get_connection, upsert_chat, get_chat, list_chats,
    update_chat_progress, insert_messages, message_exists,
    get_state, set_state, insert_tasks,
)

API_DATE_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"
TRACKING_START_PATH = Path(__file__).parent / "tracking_start.json"
TASK_TRACKING_START_PATH = Path(__file__).parent / "task_tracking_start.json"
BACKFILL_PAGE_CAP = 15
REQUEST_DELAY_SEC = 0.3


def _get_tracking_start(path: Path) -> str:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["cutoff"]
    today_local = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_utc = today_local.astimezone().astimezone(timezone.utc)
    cutoff = today_utc.strftime(API_DATE_FMT)[:-3] + "Z"  # мс до 3 знаков
    path.write_text(json.dumps({"cutoff": cutoff}), encoding="utf-8")
    return cutoff


BACKFILL_CUTOFF = _get_tracking_start(TRACKING_START_PATH)
# Задачи (лайки/премиум/лимиты) - отдельная, более узкая дата отсечения:
# фиксируется в свой момент (день первого запуска этой фичи), а не
# привязана к дате отсечения сообщений.
TASK_BACKFILL_CUTOFF = _get_tracking_start(TASK_TRACKING_START_PATH)


def _now_iso() -> str:
    """Тот же формат, что и createdAt/lastAt из API - чтобы last_synced_at
    можно было честно сравнивать строками с last_activity_at."""
    return datetime.now(timezone.utc).strftime(API_DATE_FMT)[:-3] + "Z"


def _chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def _effective_kind(msg: dict) -> str:
    """kind='reaction' на самом деле прячет разные вещи в subKind -
    разводим их на нормальные категории вместо одного 'reaction'."""
    kind = msg.get("kind")
    if kind == "reaction":
        sub = msg.get("subKind")
        if sub == "wink":
            return "wink"
        if sub in ("likePhoto", "likePost", "like"):
            return "like"
        return sub or "reaction"
    return kind


def _message_to_row(msg: dict, tu_id: int, ru_id: int, ru_name: str) -> dict:
    return {
        "message_id": str(msg["id"]),
        "tu_id": tu_id,
        "ru_id": ru_id,
        "ru_name": ru_name,
        "author": msg.get("author"),
        "kind": _effective_kind(msg),
        "created_date": msg.get("createdAt"),
        "content_json": json.dumps(msg, ensure_ascii=False),
    }


DISCOVERY_MARK_KEY = "discovery_high_water_mark"  # chatAt строкой - самый свежий виденный диалог


def discover_chats(sess, conn, full_sweep=False, log=print):
    """Список диалогов отсортирован от новых к старым, поэтому при обычном
    (не full_sweep) проходе можно остановиться, как только дошли до уже
    виденной раньше отметки - дальше в прошлое ничего нового не будет.
    full_sweep=True листает до конца (на случай полной сверки)."""
    high_water_mark = get_state(conn, DISCOVERY_MARK_KEY)
    newest_seen = None
    new_count = 0
    total_seen = 0
    cursor = None
    pages = 0
    MAX_PAGES = 5000  # защита от зацикливания

    while pages < MAX_PAGES:
        pages += 1
        items, cursor = fetch_dialog_list_page(sess, cursor)
        if not items:
            break
        for d in items:
            tu_id, ru_id = d["tuId"], d["ruId"]
            last_at = d.get("lastAt")
            blocked = bool((d.get("flags") or {}).get("blocked"))
            if newest_seen is None:
                newest_seen = last_at
            existing = get_chat(conn, tu_id, ru_id)
            upsert_chat(conn, tu_id, ru_id, (existing or {}).get("ru_name"),
                        last_activity_at=last_at, blocked=blocked)
            if existing is None:
                new_count += 1
            total_seen += 1
        if pages % 20 == 0:
            log(f"  ...страница {pages}, просмотрено {total_seen} диалогов")
        oldest_on_page = items[-1].get("lastAt", "")
        if oldest_on_page < BACKFILL_CUTOFF:
            break  # дальше в истории только то, что нам не нужно (раньше даты отсечения)
        if not full_sweep and high_water_mark and oldest_on_page <= high_water_mark:
            break
        if not cursor:
            break

    conn.commit()
    if newest_seen and (not high_water_mark or newest_seen > high_water_mark):
        set_state(conn, DISCOVERY_MARK_KEY, newest_seen)
        conn.commit()
    log(f"Список диалогов: {pages} страниц, {total_seen} просмотрено"
        f"{' (полная сверка)' if full_sweep else ''}")
    return new_count, total_seen


TASK_PAGE_CAP = 40  # на подтип за прогон - с запасом, объём задач небольшой


def _task_to_row(t: dict) -> dict:
    return {
        "task_id": str(t["id"]),
        "tu_id": t["tuId"],
        "ru_id": t["ruId"],
        "sub_type": t["subType"],
        "status": t["status"],
        "task_at": t["taskAt"],
        "updated_at": t.get("updatedAt") or t["taskAt"],
        "timer_ms": t.get("timerMs") or 0,
        "operator_name": (t.get("operator") or {}).get("firstName"),
        "content_json": json.dumps(t, ensure_ascii=False),
    }


def discover_tasks(sess, conn, log=print):
    """Лайки/подмигивания, премиум-онлайн, новые лимиты - отдельная лента
    задач с сайта. Объём небольшой, поэтому просто перечитываем недавнюю
    историю по каждому подтипу целиком при каждом прогоне (UPSERT сам
    подхватит смену статуса todo -> done/expired)."""
    total_new = 0
    for sub_type in TASK_SUB_TYPES:
        cursor = None
        pages = 0
        while pages < TASK_PAGE_CAP:
            pages += 1
            items, cursor = fetch_tasks_page(sess, sub_types=[sub_type], cursor=cursor, limit=50)
            if not items:
                break
            rows = [_task_to_row(t) for t in items if t.get("taskAt", "") >= TASK_BACKFILL_CUTOFF]
            total_new += insert_tasks(conn, rows)
            oldest_task_at = items[-1].get("taskAt", "")
            if oldest_task_at < TASK_BACKFILL_CUTOFF or not cursor:
                break
            time.sleep(REQUEST_DELAY_SEC)
        conn.commit()
    log(f"Задачи (лайки/премиум/лимиты): докачано/обновлено {total_new}")
    return total_new


def enrich_names(sess, conn):
    """Дозаполняет имена клиентов (ru_name) там, где их ещё нет."""
    rows = conn.execute("SELECT tu_id, ru_id FROM chats WHERE ru_name IS NULL").fetchall()
    if not rows:
        return
    for batch in _chunked(rows, BATCH_SIZE):
        pairs = [{"tuId": tu_id, "ruId": ru_id} for tu_id, ru_id in batch]
        results = fetch_ru_profiles(sess, pairs)
        for (tu_id, ru_id), res in zip(batch, results):
            name = res.get("data", {}).get("name")
            if name:
                upsert_chat(conn, tu_id, ru_id, name)
        time.sleep(REQUEST_DELAY_SEC)
    conn.commit()


def _deep_paginate(sess, conn, tu_id, ru_id, ru_name, cursor) -> int:
    """Докачивает один чат назад курсором, пока не состыкуется с уже
    известным сообщением, не упрётся в дату отсечения или в лимит страниц."""
    total_new = 0
    pages = 0
    while cursor and pages < BACKFILL_PAGE_CAP:
        pages += 1
        time.sleep(REQUEST_DELAY_SEC)
        results = fetch_messages_batch(sess, [{"tuId": tu_id, "ruId": ru_id, "limit": 20, "cursor": cursor}])
        if not results:
            break
        data = results[0].get("data", {})
        msgs = data.get("items", [])
        if not msgs:
            break
        rows = [_message_to_row(m, tu_id, ru_id, ru_name) for m in msgs if m["createdAt"] >= BACKFILL_CUTOFF]
        total_new += insert_messages(conn, rows)
        oldest = min(msgs, key=lambda m: m["createdAt"])
        if message_exists(conn, str(oldest["id"])) or oldest["createdAt"] < BACKFILL_CUTOFF:
            break
        cursor = data.get("nextCursor")
    return total_new


def sync_all(conn, sess, chat_rows=None, log=print):
    chat_rows = chat_rows if chat_rows is not None else list_chats(conn)
    total_new = 0
    deep_needed = []

    for batch in _chunked(chat_rows, BATCH_SIZE):
        items = [{"tuId": c["tu_id"], "ruId": c["ru_id"], "limit": 20} for c in batch]
        results = fetch_messages_batch(sess, items)
        for chat_row, res in zip(batch, results):
            data = res.get("data", {})
            msgs = data.get("items", [])
            next_cursor = data.get("nextCursor")
            rows = [_message_to_row(m, chat_row["tu_id"], chat_row["ru_id"], chat_row["ru_name"])
                    for m in msgs if m["createdAt"] >= BACKFILL_CUTOFF]
            n = insert_messages(conn, rows)
            total_new += n

            if msgs:
                oldest = min(msgs, key=lambda m: m["createdAt"])
                newest = max(msgs, key=lambda m: m["createdAt"])
                gap = (not message_exists(conn, str(oldest["id"]))
                       and oldest["createdAt"] >= BACKFILL_CUTOFF and next_cursor)
                if gap:
                    deep_needed.append((chat_row["tu_id"], chat_row["ru_id"], chat_row["ru_name"], next_cursor))
                update_chat_progress(conn, chat_row["tu_id"], chat_row["ru_id"], backfilled=True,
                                      newest_message_id=str(newest["id"]),
                                      oldest_message_id=str(oldest["id"]),
                                      last_synced_at=_now_iso())
            else:
                update_chat_progress(conn, chat_row["tu_id"], chat_row["ru_id"], backfilled=True,
                                      last_synced_at=_now_iso())
        conn.commit()
        time.sleep(REQUEST_DELAY_SEC)

    for tu_id, ru_id, ru_name, cursor in deep_needed:
        total_new += _deep_paginate(sess, conn, tu_id, ru_id, ru_name, cursor)
    conn.commit()

    return total_new, len(deep_needed)


def run_cycle(sess, conn, log=print, full_sweep=False):
    new_chats, total_dialogs = discover_chats(sess, conn, full_sweep=full_sweep, log=log)
    if new_chats:
        log(f"Обнаружено новых чатов: {new_chats}")
    enrich_names(sess, conn)
    discover_tasks(sess, conn, log=log)

    all_chats = list_chats(conn)
    if full_sweep:
        chat_rows = all_chats
    else:
        chat_rows = [
            c for c in all_chats
            if not c["backfilled"]
            or not c["last_activity_at"]
            or not c["last_synced_at"]
            or c["last_activity_at"] > c["last_synced_at"]
        ]
    log(f"Чатов к проверке: {len(chat_rows)} из {len(all_chats)} известных"
        f"{' (полный прогон)' if full_sweep else ''}")

    new_messages, deep_count = sync_all(conn, sess, chat_rows, log=log)
    if deep_count:
        log(f"Докачка разрывов понадобилась для {deep_count} чатов")
    return {"chats_total": len(all_chats), "chats_checked": len(chat_rows),
            "new_chats": new_chats, "new_messages": new_messages}
