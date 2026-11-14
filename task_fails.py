"""
Фейлы по "задачам" с сайта - отдельно от сообщений: клиент лайкнул/
подмигнул, зашёл премиум-пользователь, открылся новый лимит. У каждой
задачи есть свой официальный таймер (timer_ms) с сайта - используем его
напрямую, ничего не хардкодим.

canceled / cancelByCommunicationBlock - ситуация сама отпала или клиент
заблокировал анкету, это не вина оператора, не фейл.
"""
from datetime import datetime, timezone

API_DATE_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"

SKIP_STATUSES = {"canceled", "cancelByCommunicationBlock"}

SUB_TYPE_LABELS = {
    "system": "Новый лимит",
    "likeOrWink": "Лайк/подмигивание",
    "likeOrWinkPaidContact": "Платный лайк/подмигивание",
    "premiumRuOnline": "Премиум-онлайн",
    "vipRuOnline": "VIP-онлайн",
}


def _parse(dt_str: str) -> datetime:
    return datetime.strptime(dt_str, API_DATE_FMT).replace(tzinfo=timezone.utc)


def compute_task_fails(conn, window_start: str, window_end: str, now: datetime = None):
    """window_start/window_end - строки в формате API (UTC). Возвращает
    список фейлов по задачам, чья task_at попадает в это окно."""
    now = now or datetime.now(timezone.utc)

    rows = conn.execute(
        """
        SELECT t.tu_id, t.ru_id, t.sub_type, t.status, t.task_at, t.updated_at,
               t.timer_ms, t.operator_name, m.ru_name
        FROM tasks t
        LEFT JOIN (
            SELECT ru_id, ru_name FROM messages WHERE ru_name IS NOT NULL GROUP BY ru_id
        ) m ON m.ru_id = t.ru_id
        LEFT JOIN chats c ON c.tu_id = t.tu_id AND c.ru_id = t.ru_id
        WHERE t.task_at >= ? AND t.task_at < ?
          AND t.status NOT IN ({})
          AND COALESCE(c.blocked, 0) = 0
        """.format(",".join("?" * len(SKIP_STATUSES))),
        (window_start, window_end, *SKIP_STATUSES),
    ).fetchall()

    fails = []
    for tu_id, ru_id, sub_type, status, task_at, updated_at, timer_ms, operator_name, ru_name in rows:
        if timer_ms <= 0:
            continue
        if status == "todo":
            wait_ms = (now - _parse(task_at)).total_seconds() * 1000
            resolved_at = None
        else:
            wait_ms = (_parse(updated_at) - _parse(task_at)).total_seconds() * 1000
            resolved_at = updated_at

        if wait_ms <= timer_ms:
            continue

        fails.append({
            "tu_id": tu_id, "ru_id": ru_id, "ru_name": ru_name or str(ru_id),
            "sub_type": sub_type, "sub_type_label": SUB_TYPE_LABELS.get(sub_type, sub_type),
            "operator_name": operator_name or "?",
            "fail_start": task_at, "replied_at": resolved_at,
            "wait_min": round(wait_ms / 60000),
            "status": "unanswered" if status == "todo" else "replied_late",
        })

    fails.sort(key=lambda f: f["fail_start"])
    return fails
