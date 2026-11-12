"""
reports/chats/<tuId>_<ruId>.html - полная история одного чата.
reports/chats_index.html - список всех чатов со ссылками, по активности.
"""
import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from db import get_connection
from report_common import CSS_TOKENS, bar_chart_html, stat_tile, kind_meta, normalize_kind, content_preview
from config import TU_NAMES

HERE = Path(__file__).parent
REPORTS_DIR = HERE / "reports"
CHATS_DIR = REPORTS_DIR / "chats"
HELPER_APP_DIALOG_URL = "https://helper-app.com/v3/chatmanager"
# см. комментарий в generate_report.py - прямые ссылки на конкретный диалог
# не поддерживаются сайтом для этого аккаунта, нужен ручной поиск по ID.

API_DATE_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def to_local_str(created_date_utc: str, fmt="%d.%m.%Y %H:%M:%S") -> str:
    dt = datetime.strptime(created_date_utc, API_DATE_FMT).replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime(fmt)


CHAT_PAGE_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>{ru_name} ({ru_id}) — анкета {tu_id}</title>
<style>
{css}
.msg-row {{ display: grid; grid-template-columns: 140px 90px 1fr; gap: 12px; padding: 8px 12px; border-bottom: 1px solid var(--gridline); font-size: 13px; }}
.msg-row:last-child {{ border-bottom: none; }}
.msg-time {{ color: var(--text-muted); font-variant-numeric: tabular-nums; }}
.msg-text {{ white-space: pre-wrap; word-break: break-word; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="nav"><a href="../chats_index.html">&larr; Все чаты</a> &nbsp;·&nbsp; <a href="../index.html">Отчёты по дням</a>
    &nbsp;·&nbsp; <a href="{live_href}" target="_blank" title="Вставить ID клиента ({ru_id}) в поиск справа, выключив 'Online'">Панель чатов на сайте ↗ (ID клиента: {ru_id})</a></div>
  <h1>{ru_name} <span style="font-weight:400; color:var(--text-secondary);">({ru_id})</span></h1>
  <p class="subtitle">Анкета {tu_name} · первое сообщение {first_date} · последнее {last_date}</p>

  <section>
    <h2>Итого за всё время (с момента начала отслеживания)</h2>
    <div class="tiles">
      {tiles}
    </div>
  </section>

  <section>
    <div class="cols-2">
      {bar_tu}
      {bar_ru}
    </div>
  </section>

  <section>
    <h2>Вся переписка ({count} сообщений)</h2>
    <div class="table-wrap">
      {timeline}
    </div>
  </section>

  <footer>helper-app-stats-bot</footer>
</div>
</body>
</html>
"""


def render_chat_page(conn, tu_id: int, ru_id: int):
    rows = conn.execute(
        """
        SELECT message_id, author, kind, created_date, content_json, ru_name
        FROM messages WHERE tu_id = ? AND ru_id = ?
        ORDER BY created_date
        """,
        (tu_id, ru_id),
    ).fetchall()
    if not rows:
        return None

    ru_name = rows[-1][5] or str(ru_id)
    from_tu = Counter()
    from_ru = Counter()
    timeline_html = []
    for message_id, author, kind, created_date, content_json, _ in rows:
        is_tu = author == "tu"
        (from_tu if is_tu else from_ru)[normalize_kind(kind)] += 1
        pill = '<span class="pill pill-tu">Анкета</span>' if is_tu else '<span class="pill pill-ru">Клиент</span>'
        label = kind_meta(normalize_kind(kind))[0]
        msg = json.loads(content_json)
        preview = content_preview(msg)
        timeline_html.append(f"""
        <div class="msg-row">
          <div class="msg-time">{to_local_str(created_date)}</div>
          <div>{pill}<br><span style="font-size:11px;color:var(--text-muted);">{html.escape(label)}</span></div>
          <div class="msg-text">{html.escape(preview)}</div>
        </div>""")

    total = len(rows)
    tiles = "".join([
        stat_tile(sum(from_tu.values()), "Отправлено анкетой"),
        stat_tile(sum(from_ru.values()), "Получено от клиента"),
        stat_tile(total, "Всего сообщений"),
    ])

    html_out = CHAT_PAGE_TEMPLATE.format(
        css=CSS_TOKENS,
        ru_name=html.escape(ru_name), ru_id=ru_id, tu_id=tu_id,
        tu_name=html.escape(f"{TU_NAMES.get(tu_id, tu_id)} ({tu_id})"),
        live_href=html.escape(HELPER_APP_DIALOG_URL.format(tu_id=tu_id, ru_id=ru_id)),
        first_date=to_local_str(rows[0][3]), last_date=to_local_str(rows[-1][3]),
        tiles=tiles,
        bar_tu=bar_chart_html(from_tu, "Анкета отправила", f"tu-{tu_id}-{ru_id}"),
        bar_ru=bar_chart_html(from_ru, "Клиент отправил", f"ru-{tu_id}-{ru_id}"),
        count=total, timeline="".join(timeline_html),
    )
    return html_out, ru_name, sum(from_tu.values()), sum(from_ru.values()), total, rows[-1][3]


INDEX_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Все чаты — статистика</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <div class="nav"><a href="index.html">Отчёты по дням</a></div>
  <h1>Все чаты</h1>
  <p class="subtitle">{count} диалогов · отсортировано по последней активности</p>
  <div class="table-wrap">
  <table>
    <thead><tr><th>Клиент</th><th>Анкета</th><th class="num">От анкеты</th><th class="num">От клиента</th><th class="num">Всего</th><th>Последняя активность</th></tr></thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  </div>
</div>
</body>
</html>
"""


def generate_all():
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    chat_pairs = conn.execute("SELECT DISTINCT tu_id, ru_id FROM messages").fetchall()

    index_rows = []
    for tu_id, ru_id in chat_pairs:
        result = render_chat_page(conn, tu_id, ru_id)
        if result is None:
            continue
        html_out, ru_name, sent_n, recv_n, total, last_date = result
        fname = f"{tu_id}_{ru_id}.html"
        (CHATS_DIR / fname).write_text(html_out, encoding="utf-8")
        index_rows.append((last_date, ru_name, ru_id, tu_id, sent_n, recv_n, total, fname))

    index_rows.sort(key=lambda r: r[0], reverse=True)
    rows_html = []
    for last_date, ru_name, ru_id, tu_id, sent_n, recv_n, total, fname in index_rows:
        rows_html.append(
            f"<tr><td><a class='row-link' href='chats/{fname}'>{html.escape(ru_name)}</a></td>"
            f"<td class='muted'>{html.escape(TU_NAMES.get(tu_id, str(tu_id)))}</td>"
            f"<td class='num'>{sent_n}</td><td class='num'>{recv_n}</td>"
            f"<td class='num total'>{total}</td>"
            f"<td class='muted'>{to_local_str(last_date)}</td></tr>"
        )

    (REPORTS_DIR / "chats_index.html").write_text(
        INDEX_TEMPLATE.format(css=CSS_TOKENS, count=len(index_rows), rows="".join(rows_html) or "<tr><td colspan='6'>Пока нет данных</td></tr>"),
        encoding="utf-8",
    )
    print(f"Сгенерировано страниц чатов: {len(index_rows)}")


if __name__ == "__main__":
    generate_all()
