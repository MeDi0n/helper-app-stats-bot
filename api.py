from config import TU_IDS

BASE = "https://api.helper-app.com/v1"
BATCH_SIZE = 25  # сколько чатов тянуть за один POST к chat/messages


def fetch_dialog_list_page(sess, cursor=None):
    """Одна страница списка диалогов. cursor - объект из предыдущего
    ответа (data['nextCursor']), не строка."""
    item = {"tuIds": TU_IDS, "filter": "all", "channels": ["chat"]}
    if cursor:
        item["cursor"] = cursor
    r = sess.post(f"{BASE}/communication/list", json={"items": [item]}, timeout=30)
    r.raise_for_status()
    data = r.json()
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


TASK_SUB_TYPES = ["system", "likeOrWink", "likeOrWinkPaidContact", "premiumRuOnline", "vipRuOnline"]


def fetch_tasks_page(sess, sub_types=None, cursor=None, limit=50):
    """Одна страница 'задач' (лайки/подмигивания, премиум-онлайн, новые
    лимиты) - /v1/tasks/list, сортировка от новых к старым (desc)."""
    item = {"tuIds": [], "limit": limit, "dateOrder": "desc",
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
