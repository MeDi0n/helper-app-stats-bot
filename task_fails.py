"""
Фейлы по "задачам" с сайта - отдельно от сообщений: клиент лайкнул/
подмигнул, зашёл премиум-пользователь. У каждой задачи есть свой
официальный таймер (timer_ms) с сайта - используем его напрямую, ничего
не хардкодим.

"Новые лимиты" (system) намеренно не считаем - сайт не хранит историю
закрытых задач в интерфейсе, человеку такой фейл нечем доказать задним
числом (см. SKIP_SUB_TYPES).

canceled / cancelByCommunicationBlock - ситуация сама отпала или клиент
заблокировал анкету, это не вина оператора, не фейл.

ghost - запись о задаче, которую сайт полностью удалил из своей ленты
(подробности в sync.py:verify_todo_tasks) - доказать нечем, не фейл.

Таймер оператора считаем от created_at (когда сайт реально создал
задачу), а НЕ от task_at (когда возникло исходное действие клиента) -
бывает, что сайт создаёт/закрывает задачу почти мгновенно, но у неё
task_at "унаследован" из прошлого (видели разрыв почти ровно в сутки у
gsaboats/Baubel/Fred, 16.11.2026) - при счёте от task_at это выглядело
как фейл на 1500+ минут при настоящем ответе за пару секунд.
"""
from datetime import datetime, timezone

API_DATE_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"

SKIP_STATUSES = {"canceled", "cancelByCommunicationBlock", "ghost"}
SKIP_SUB_TYPES = {"system"}

SUB_TYPE_LABELS = {
    "likeOrWink": "Лайк/подмигивание",
    "likeOrWinkPaidContact": "Платный лайк/подмигивание",
    "premiumRuOnline": "Премиум-онлайн",
    "vipRuOnline": "VIP-онлайн",
}


def _parse(dt_str: str) -> datetime:
    return datetime.strptime(dt_str, API_DATE_FMT).replace(tzinfo=timezone.utc)


def compute_task_fails(conn, window_start: str, window_end: str, now: datetime = None):
    """window_start/window_end - строки в формате API (UTC). Возвращает
    список фейлов по задачам, чья created_at попадает в это окно (не
    task_at - см. комментарий в начале файла)."""
    now = now or datetime.now(timezone.utc)

    rows = conn.execute(
        """
        SELECT t.tu_id, t.ru_id, t.sub_type, t.status, COALESCE(t.created_at, t.task_at) AS created_at,
               t.updated_at, t.timer_ms, t.operator_name, m.ru_name
        FROM tasks t
        LEFT JOIN (
            SELECT ru_id, ru_name FROM messages WHERE ru_name IS NOT NULL GROUP BY ru_id
        ) m ON m.ru_id = t.ru_id
        LEFT JOIN chats c ON c.tu_id = t.tu_id AND c.ru_id = t.ru_id
        WHERE COALESCE(t.created_at, t.task_at) >= ? AND COALESCE(t.created_at, t.task_at) < ?
          AND t.status NOT IN ({})
          AND t.sub_type NOT IN ({})
          AND COALESCE(c.blocked, 0) = 0
        """.format(",".join("?" * len(SKIP_STATUSES)), ",".join("?" * len(SKIP_SUB_TYPES))),
        (window_start, window_end, *SKIP_STATUSES, *SKIP_SUB_TYPES),
    ).fetchall()

    fails = []
    for tu_id, ru_id, sub_type, status, created_at, updated_at, timer_ms, operator_name, ru_name in rows:
        if timer_ms <= 0:
            continue
        if status == "todo":
            wait_ms = (now - _parse(created_at)).total_seconds() * 1000
            resolved_at = None
        else:
            wait_ms = (_parse(updated_at) - _parse(created_at)).total_seconds() * 1000
            resolved_at = updated_at

        if wait_ms <= timer_ms:
            continue

        fails.append({
            "tu_id": tu_id, "ru_id": ru_id, "ru_name": ru_name or str(ru_id),
            "sub_type": sub_type, "sub_type_label": SUB_TYPE_LABELS.get(sub_type, sub_type),
            "operator_name": operator_name or "?",
            "fail_start": created_at, "replied_at": resolved_at,
            "wait_min": round(wait_ms / 60000),
            "status": "unanswered" if status == "todo" else "replied_late",
        })

    fails.sort(key=lambda f: f["fail_start"])
    return fails
