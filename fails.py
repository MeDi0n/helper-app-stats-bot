"""
Фейл = клиент (ru) написал анкете (tu), а анкета не ответила в течение
FAIL_THRESHOLD_MIN минут. Если долго молчит КЛИЕНТ - это не фейл, это
нормально, молчание клиента не считается.

Смотрим ПОЛНУЮ переписку чата (не только окно отчёта), чтобы честно
понять, ответили вообще или нет, даже если ответ пришёл чуть позже
границы смены/дня. Сам фейл относим к дню/смене того момента, когда
клиент написал (не когда "протух" таймер).
"""
from datetime import datetime, timezone

API_DATE_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"
FAIL_THRESHOLD_MIN = 3

# Лайки и подмигивания - не настоящие сообщения, не запускают таймер фейла
NON_MESSAGE_KINDS = {"like", "wink"}


def _parse(dt_str: str) -> datetime:
    return datetime.strptime(dt_str, API_DATE_FMT).replace(tzinfo=timezone.utc)


def compute_fails(conn, window_start: str, window_end: str, now: datetime = None):
    """window_start/window_end - строки в формате API (UTC), как и created_date.
    Возвращает список фейлов, относящихся к сообщениям клиента в этом окне."""
    now = now or datetime.now(timezone.utc)

    kind_placeholders = ",".join("?" * len(NON_MESSAGE_KINDS))
    pairs = conn.execute(
        f"""
        SELECT DISTINCT m.tu_id, m.ru_id FROM messages m
        LEFT JOIN chats c ON c.tu_id = m.tu_id AND c.ru_id = m.ru_id
        WHERE m.author = 'ru' AND m.kind NOT IN ({kind_placeholders})
          AND m.created_date >= ? AND m.created_date < ?
          AND COALESCE(c.blocked, 0) = 0
        """,
        (*NON_MESSAGE_KINDS, window_start, window_end),
    ).fetchall()
    # Клиенты, заблокировавшие анкету, исключены выше - анкета физически не
    # может им ответить, это не вина оператора, не фейл.

    fails = []
    for tu_id, ru_id in pairs:
        rows = conn.execute(
            """
            SELECT author, created_date, ru_name, kind FROM messages
            WHERE tu_id = ? AND ru_id = ?
            ORDER BY created_date
            """,
            (tu_id, ru_id),
        ).fetchall()
        ru_name = next((r[2] for r in rows if r[2]), str(ru_id))

        pending_since = None
        for author, created_date, _, kind in rows:
            if author == "ru":
                if kind in NON_MESSAGE_KINDS:
                    continue  # лайк/подмигивание - не считается сообщением
                if pending_since is None:
                    pending_since = created_date
            elif author == "tu":
                if pending_since is not None:
                    wait_min = (_parse(created_date) - _parse(pending_since)).total_seconds() / 60
                    if wait_min > FAIL_THRESHOLD_MIN and window_start <= pending_since < window_end:
                        fails.append({
                            "tu_id": tu_id, "ru_id": ru_id, "ru_name": ru_name,
                            "fail_start": pending_since, "replied_at": created_date,
                            "wait_min": round(wait_min), "status": "replied_late",
                        })
                    pending_since = None

        if pending_since is not None and window_start <= pending_since < window_end:
            wait_min = (now - _parse(pending_since)).total_seconds() / 60
            if wait_min > FAIL_THRESHOLD_MIN:
                fails.append({
                    "tu_id": tu_id, "ru_id": ru_id, "ru_name": ru_name,
                    "fail_start": pending_since, "replied_at": None,
                    "wait_min": round(wait_min), "status": "unanswered",
                })

    fails.sort(key=lambda f: f["fail_start"])
    return fails
