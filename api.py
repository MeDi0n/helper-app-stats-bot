import time

import requests

from config import TU_IDS

BASE = "https://api.helper-app.com/v1"
BATCH_SIZE = 25  # сколько чатов тянуть за один POST к chat/messages


def _post(sess, url, json_body, timeout=30, retries=2, backoff=3):
    """sess.post с ретраями на сетевые сбои (таймаут/обрыв) - один
    "зависший" запрос к сайту иначе роняет весь update_stats.py (см.
    разбор 16.11.2026 - ReadTimeout на /tasks/list посреди прогона)."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return sess.post(url, json=json_body, timeout=timeout)
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    raise last_exc


class TrustedUserUnavailable(Exception):
    """communication/list отвечает 200, но с results=[] и errors=[{code:1101,
    details:{tuId:...}}], если среди tuIds есть анкета, к которой у аккаунта
    больше нет доступа (см. разбор 16.11.2026 - Dawris/186897462). Опасно
    тем, что ОДНА такая анкета обнуляет ВЕСЬ batch-запрос молча (без HTTP-
    ошибки), а discover_chats без этой проверки просто решает, что диалогов
    вообще нет."""
    def __init__(self, tu_id):
        self.tu_id = tu_id
        super().__init__(f"tuId {tu_id} недоступен аккаунту (Trusted user is not available)")


def fetch_dialog_list_page(sess, cursor=None, tu_ids=None):
    """Одна страница списка диалогов. cursor - объект из предыдущего
    ответа (data['nextCursor']), не строка. tu_ids=None - берёт TU_IDS из
    config.py; явный список нужен, когда discover_chats ретраит без
    отвалившейся анкеты (см. TrustedUserUnavailable)."""
    item = {"tuIds": tu_ids if tu_ids is not None else TU_IDS, "filter": "all", "channels": ["chat"]}
    if cursor:
        item["cursor"] = cursor
    r = _post(sess, f"{BASE}/communication/list", {"items": [item]})
    r.raise_for_status()
    data = r.json()
    errors = data.get("errors")
    if errors:
        err = errors[0]
        if err.get("code") == 1101 and err.get("details", {}).get("field") == "tuIds":
            raise TrustedUserUnavailable(err["details"]["tuId"])
        raise RuntimeError(f"communication/list: {err}")
    results = data.get("results", [])
    if not results:
        return [], None
    d = results[0].get("data", {})
    return d.get("items", []), d.get("nextCursor")


def fetch_ru_profiles(sess, pairs):
    """pairs: список dict {tuId, ruId}. Возвращает список результатов с
    data.name и т.д. - для подписи имени клиента."""
    if not pairs:
        return []
    r = _post(sess, f"{BASE}/ru/profiles", {"items": pairs})
    r.raise_for_status()
    return r.json().get("results", [])


TASK_SUB_TYPES = ["likeOrWink", "likeOrWinkPaidContact", "premiumRuOnline", "vipRuOnline"]
# "system" (новые лимиты) намеренно не отслеживаем - сайт не хранит
# историю закрытых задач, человеку такой фейл нечем доказать задним числом.


def fetch_tasks_page(sess, sub_types=None, tu_ids=None, cursor=None, limit=50):
    """Одна страница 'задач' (лайки/подмигивания, премиум-онлайн, новые
    лимиты) - /v1/tasks/list, сортировка от новых к старым (desc).
    tu_ids=None (или []) - все анкеты сразу; список - только по ним."""
    item = {"tuIds": tu_ids or [], "limit": limit, "dateOrder": "desc",
            "subTypes": sub_types or TASK_SUB_TYPES}
    if cursor:
        item["cursor"] = cursor
    r = _post(sess, f"{BASE}/tasks/list", {"items": [item]})
    r.raise_for_status()
    data = r.json()
    results = data.get("results", [])
    if not results:
        return [], None
    d = results[0].get("data", {})
    return d.get("items", []), d.get("nextCursor")


_EMPTY_MESSAGES_RESULT = {"data": {"items": [], "nextCursor": None}}


def fetch_messages_batch(sess, pairs):
    """pairs: список dict {tuId, ruId, limit, cursor(опц.)}.
    Возвращает список результатов (по одному на пару), в том же порядке,
    длина всегда равна len(pairs).

    Если среди пар есть недоступная аккаунту анкета (см. TrustedUserUnavailable
    в fetch_dialog_list_page), сайт не роняет весь batch, а возвращает
    результаты по остальным парам + отдельный errors[] с индексами плохих -
    но индексы в results при этом не совпадают с позицией в pairs (плохие
    просто выпадают). Докладываем их пустым результатом (как будто у чата
    нет новых сообщений), а не падаем - эту анкету чинить нечем, кроме как
    дождаться, пока refresh_config.py уберёт её из TU_IDS."""
    if not pairs:
        return []
    r = _post(sess, f"{BASE}/chat/messages", {"items": pairs})
    r.raise_for_status()
    data = r.json()
    out = [_EMPTY_MESSAGES_RESULT] * len(pairs)
    for res in data.get("results", []):
        idx = res.get("index")
        if idx is not None and 0 <= idx < len(pairs):
            out[idx] = res
    return out
