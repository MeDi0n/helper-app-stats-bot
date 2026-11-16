from config import TU_IDS

BASE = "https://api.helper-app.com/v1"
BATCH_SIZE = 25  # сколько чатов тянуть за один POST к chat/messages


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
    r = sess.post(f"{BASE}/communication/list", json={"items": [item]}, timeout=30)
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
    r = sess.post(f"{BASE}/ru/profiles", json={"items": pairs}, timeout=30)
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
    r = sess.post(f"{BASE}/tasks/list", json={"items": [item]}, timeout=30)
    r.raise_for_status()
    data = r.json()
    results = data.get("results", [])
    if not results:
        return [], None
    d = results[0].get("data", {})
    return d.get("items", []), d.get("nextCursor")


def fetch_messages_batch(sess, pairs):
    """pairs: список dict {tuId, ruId, limit, cursor(опц.)}.
    Возвращает список результатов (по одному на пару), в том же порядке."""
    if not pairs:
        return []
    body = {"items": pairs}
    r = sess.post(f"{BASE}/chat/messages", json=body, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("results", [])
