"""
Отчёт по сменам (условные сутки 06:00-06:00 след. дня, три смены внутри)
- та же механика, что в chat-space-stats-bot.

Без аргументов - вчерашние условные сутки. С аргументом YYYY-MM-DD -
конкретный день.
"""
import sys
import json
import html
import re
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from db import get_connection
from report_common import CSS_TOKENS, bar_chart_html, stat_tile, kind_meta, normalize_kind, API_DATE_FMT, shift_bounds_utc
from config import TU_NAMES, TU_TEAMS
from fails import compute_fails
import generate_chat_pages

HERE = Path(__file__).parent
REPORTS_DIR = HERE / "reports"
MANIFEST_PATH = REPORTS_DIR / "manifest.json"

SHIFTS = [
    ("morning", "Утренняя смена", 6, 14),
    ("day", "Дневная смена", 14, 22),
    ("night", "Ночная смена", 22, 30),
]
FULL_DAY_SHIFT = ("total", "Общая статистика", 6, 30)


def to_local_str(created_date_utc: str) -> str:
    dt = datetime.strptime(created_date_utc, API_DATE_FMT).replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%H:%M:%S")


def fetch_shift_rows(conn, local_date: datetime, start_h: int, end_h: int):
    start_s, end_s = shift_bounds_utc(local_date, start_h, end_h)
    return conn.execute(
        """
        SELECT tu_id, ru_id, ru_name, author, kind, created_date
        FROM messages WHERE created_date >= ? AND created_date < ?
        ORDER BY created_date
        """,
        (start_s, end_s),
    ).fetchall()


def build_stats(rows):
    from_tu = Counter()
    from_ru = Counter()
    by_tu = defaultdict(lambda: {"sent": 0, "received": 0, "kinds": Counter()})
    by_ru = defaultdict(lambda: {"name": "", "tu_id": None, "sent": 0, "received": 0,
                                  "kinds": Counter(), "first": None, "last": None})

    for tu_id, ru_id, ru_name, author, raw_kind, created_date in rows:
        kind = normalize_kind(raw_kind)
        is_tu = author == "tu"
        (from_tu if is_tu else from_ru)[kind] += 1

        t = by_tu[tu_id]
        t["sent" if is_tu else "received"] += 1
        t["kinds"][kind] += 1

        key = (tu_id, ru_id)
        r = by_ru[key]
        r["name"] = ru_name or str(ru_id)
        r["tu_id"] = tu_id
        r["sent" if is_tu else "received"] += 1
        r["kinds"][kind] += 1
        local_time = to_local_str(created_date)
        if r["first"] is None:
            r["first"] = local_time
        r["last"] = local_time

    return from_tu, from_ru, by_tu, by_ru


def profile_table_html(by_tu: dict) -> str:
    if not by_tu:
        return '<p class="empty">Нет данных.</p>'
    rows = []
    for tu_id, data in sorted(by_tu.items(), key=lambda kv: (TU_TEAMS.get(kv[0], "?"), -(kv[1]["sent"] + kv[1]["received"]))):
        kinds_str = ", ".join(f"{kind_meta(k)[0]} ×{c}" for k, c in sorted(data["kinds"].items(), key=lambda kv: -kv[1]))
        rows.append(f"""<tr>
            <td>{html.escape(TU_NAMES.get(tu_id, str(tu_id)))} <span class="muted">({tu_id})</span></td>
            <td class="muted">{html.escape(TU_TEAMS.get(tu_id, "?"))}</td>
            <td class="num">{data['sent']}</td>
            <td class="num">{data['received']}</td>
            <td class="wrap-text muted">{html.escape(kinds_str)}</td>
            <td class="num total">{data['sent'] + data['received']}</td>
        </tr>""")
    return f"""
    <div class="table-wrap">
    <table>
      <thead><tr><th>Анкета</th><th>Команда</th><th class="num">Отправлено</th><th class="num">Получено</th><th>Разбивка по типам</th><th>Всего</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    </div>"""


def team_table_html(by_tu: dict) -> str:
    if not by_tu:
        return '<p class="empty">Нет данных.</p>'
    by_team = defaultdict(lambda: {"sent": 0, "received": 0, "profiles": 0})
    for tu_id, data in by_tu.items():
        t = by_team[TU_TEAMS.get(tu_id, "?")]
        t["sent"] += data["sent"]
        t["received"] += data["received"]
        t["profiles"] += 1
    rows = []
    for team, data in sorted(by_team.items(), key=lambda kv: -(kv[1]["sent"] + kv[1]["received"])):
        rows.append(f"""<tr>
            <td>{html.escape(team)}</td>
            <td class="num">{data['profiles']}</td>
            <td class="num">{data['sent']}</td>
            <td class="num">{data['received']}</td>
            <td class="num total">{data['sent'] + data['received']}</td>
        </tr>""")
    return f"""
    <div class="table-wrap">
    <table>
      <thead><tr><th>Команда</th><th class="num">Анкет</th><th class="num">Отправлено</th><th class="num">Получено</th><th class="num">Всего</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    </div>"""


def client_table_html(by_ru: dict) -> str:
    if not by_ru:
        return '<p class="empty">Нет данных.</p>'
    rows = []
    for (tu_id, ru_id), data in sorted(by_ru.items(), key=lambda kv: -(kv[1]["sent"] + kv[1]["received"])):
        kinds_str = ", ".join(f"{kind_meta(k)[0]} ×{c}" for k, c in sorted(data["kinds"].items(), key=lambda kv: -kv[1]))
        chat_href = f"chats/{tu_id}_{ru_id}.html"
        rows.append(f"""<tr>
            <td><a class="row-link" href="{html.escape(chat_href)}">{html.escape(data['name'])}</a></td>
            <td class="muted">{ru_id}</td>
            <td class="muted">{html.escape(TU_NAMES.get(tu_id, str(tu_id)))}</td>
            <td class="num">{data['sent']}</td>
            <td class="num">{data['received']}</td>
            <td class="wrap-text muted">{html.escape(kinds_str)}</td>
            <td class="num total">{data['sent'] + data['received']}</td>
            <td class="muted">{data['first']}–{data['last']}</td>
        </tr>""")
    return f"""
    <div class="table-wrap">
    <table>
      <thead><tr><th>Клиент</th><th>ID клиента</th><th>Анкета</th><th class="num">Отпр.</th><th class="num">Получ.</th><th>Что было</th><th>Всего</th><th>Период</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    </div>"""


PAGE_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Статистика {date_label}</title>
<style>
{css}
.tabs input[type="radio"] {{ display: none; }}
.tab-labels {{ display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid var(--gridline); flex-wrap: wrap; }}
.tab-labels label {{ padding: 9px 16px; font-size: 13px; color: var(--text-secondary); cursor: pointer;
                      border-bottom: 2px solid transparent; margin-bottom: -1px; }}
.tab-labels label:hover {{ color: var(--text-primary); }}
.tab-panel {{ display: none; }}
.fails-filter-section > input[type="radio"] {{ display: none; }}
.fails-filter-section > label {{ display: inline-block; padding: 6px 12px; font-size: 12px;
                                  border: 1px solid var(--border); border-radius: 999px; cursor: pointer;
                                  color: var(--text-secondary); margin: 0 6px 10px 0; }}
.fails-filter-section > input:checked + label {{ background: var(--text-primary); color: var(--surface-1); }}
{tab_show_rules}
</style>
</head>
<body>
<div class="wrap">
  <div class="nav"><a href="index.html">&larr; Все отчёты</a> &nbsp;·&nbsp; <a href="chats_index.html">Все чаты</a></div>
  <h1>Статистика отправленных и полученных сообщений</h1>
  <p class="subtitle">{period_label} · сгенерировано {generated_at}</p>

  <div class="tabs">
    {tab_inputs}
    <div class="tab-labels">
      {tab_labels}
    </div>
    {tab_panels}
  </div>

  <footer>helper-app-stats-bot</footer>
</div>
</body>
</html>
"""

SHIFT_PANEL_TEMPLATE = """
<div class="tab-panel tab-panel-{key}">
  <section>
    <h2>{title}{time_range}</h2>
    <div class="tiles">{tiles}</div>
  </section>
  <section>
    <div class="cols-2">{bar_tu}{bar_ru}</div>
  </section>
  <section>
    <h2>По командам</h2>
    {team_table}
  </section>
  <section>
    <h2>По анкете</h2>
    {profile_table}
  </section>
  <section>
    <h2>По клиенту <span style="font-weight:400; color:var(--text-secondary); font-size:12px;">(клик на имя — вся история с этим клиентом)</span></h2>
    {client_table}
  </section>
</div>
"""


FAILS_PANEL_TEMPLATE = """
<div class="tab-panel tab-panel-fails">
  <section>
    <h2>Фейлы <span style="font-weight:400; color:var(--text-secondary); font-size:13px;">(анкета не ответила клиенту за 3+ минуты)</span></h2>
    <div class="tiles">{tiles}</div>
  </section>
  <section>
    <h2>По командам</h2>
    {team_summary}
  </section>
  <section class="fails-filter-section">
    <h2>Все фейлы <span style="font-weight:400; color:var(--text-secondary); font-size:12px;">(кто, когда, на какой смене)</span></h2>
    <style>{team_filter_css}</style>
    {team_filter_inputs}
    {table}
  </section>
</div>
"""


def _shift_name_for(created_date_utc: str) -> str:
    dt = datetime.strptime(created_date_utc, API_DATE_FMT).replace(tzinfo=timezone.utc).astimezone()
    h = dt.hour
    if 6 <= h < 14:
        return "Утренняя"
    if 14 <= h < 22:
        return "Дневная"
    return "Ночная"


def _team_slug(team: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", team).strip("-").lower() or "unknown"


_SHIFT_NAME_TO_INDEX = {"Утренняя": 0, "Дневная": 1, "Ночная": 2}


def _operator_for(team: str, shift_name: str) -> str:
    """Имя кабинета - это 3 оператора по сменам (утро/день/ночь) через
    пробел. Достаём конкретного, зная, на какую смену пришёлся фейл."""
    parts = team.split()
    idx = _SHIFT_NAME_TO_INDEX.get(shift_name)
    if idx is None or len(parts) != 3:
        return team
    return parts[idx]


def fails_table_html(fail_list) -> str:
    if not fail_list:
        return '<p class="empty">Фейлов не найдено - анкеты отвечали вовремя.</p>'
    rows = []
    sort_key = lambda x: (_SHIFT_NAME_TO_INDEX.get(_shift_name_for(x["fail_start"]), 9), -x["wait_min"])
    for f in sorted(fail_list, key=sort_key):
        chat_href = f"chats/{f['tu_id']}_{f['ru_id']}.html"
        status_str = ("ещё не ответили" if f["status"] == "unanswered"
                      else f"ответили в {to_local_str(f['replied_at'])}")
        status_class = "muted" if f["status"] == "replied_late" else ""
        team = TU_TEAMS.get(f["tu_id"], "?")
        shift_name = _shift_name_for(f["fail_start"])
        operator = _operator_for(team, shift_name)
        rows.append(f"""<tr class="failrow team-{_team_slug(team)}">
            <td><a class="row-link" href="{html.escape(chat_href)}">{html.escape(f['ru_name'])}</a></td>
            <td class="muted">{f['ru_id']}</td>
            <td class="muted">{html.escape(TU_NAMES.get(f['tu_id'], str(f['tu_id'])))} ({f['tu_id']})</td>
            <td>{html.escape(operator)}</td>
            <td class="muted">{html.escape(shift_name)}</td>
            <td class="muted">{to_local_str(f['fail_start'])}</td>
            <td class="{status_class}">{status_str}</td>
            <td class="num total">{f['wait_min']} мин</td>
        </tr>""")
    return f"""
    <div class="table-wrap fails-wrap">
    <table>
      <thead><tr><th>Клиент</th><th>ID клиента</th><th>Анкета</th><th>Оператор</th><th>Смена</th><th>Написал в</th><th>Ответ</th><th class="num">Ждал</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    </div>"""


def fails_team_summary_html(fail_list) -> str:
    if not fail_list:
        return '<p class="empty">Фейлов не найдено.</p>'
    by_team = defaultdict(lambda: {"count": 0, "unanswered": 0})
    for f in fail_list:
        t = by_team[TU_TEAMS.get(f["tu_id"], "?")]
        t["count"] += 1
        if f["status"] == "unanswered":
            t["unanswered"] += 1
    rows = []
    for team, data in sorted(by_team.items(), key=lambda kv: -kv[1]["count"]):
        rows.append(f"""<tr>
            <td>{html.escape(team)}</td>
            <td class="num total">{data['count']}</td>
            <td class="num">{data['unanswered']}</td>
        </tr>""")
    return f"""
    <div class="table-wrap">
    <table>
      <thead><tr><th>Команда</th><th class="num">Фейлов</th><th class="num">Ещё не ответили</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    </div>"""


def render_fails_panel(fail_list):
    tiles = "".join([
        stat_tile(len(fail_list), "Всего фейлов"),
        stat_tile(sum(1 for f in fail_list if f["status"] == "unanswered"), "Ещё не ответили"),
        stat_tile(round(sum(f["wait_min"] for f in fail_list) / len(fail_list)) if fail_list else 0, "Средн. ожидание, мин"),
    ])

    team_counts = Counter(TU_TEAMS.get(f["tu_id"], "?") for f in fail_list)
    teams_present = sorted(team_counts, key=lambda t: -team_counts[t])
    filter_inputs = [f'<input type="radio" name="failteam" id="failteam-all" checked>'
                     f'<label for="failteam-all">Все ({len(fail_list)})</label>']
    filter_css_rules = []
    for team in teams_present:
        slug = _team_slug(team)
        filter_inputs.append(
            f'<input type="radio" name="failteam" id="failteam-{slug}">'
            f'<label for="failteam-{slug}">&quot;{html.escape(team)}&quot; ({team_counts[team]})</label>'
        )
        filter_css_rules.append(
            f'#failteam-{slug}:checked ~ .fails-wrap tr.failrow {{ display: none; }}\n'
            f'#failteam-{slug}:checked ~ .fails-wrap tr.failrow.team-{slug} {{ display: table-row; }}'
        )

    return FAILS_PANEL_TEMPLATE.format(
        tiles=tiles,
        team_summary=fails_team_summary_html(fail_list),
        team_filter_css="\n".join(filter_css_rules),
        team_filter_inputs="".join(filter_inputs),
        table=fails_table_html(fail_list),
    )


def render_shift_panel(key, title, time_range, rows):
    from_tu, from_ru, by_tu, by_ru = build_stats(rows)
    total = sum(from_tu.values()) + sum(from_ru.values())
    tiles = "".join([
        stat_tile(sum(from_tu.values()), "Отправлено анкетами"),
        stat_tile(sum(from_ru.values()), "Получено от клиентов"),
        stat_tile(len(by_tu), "Активных анкет"),
        stat_tile(len(by_ru), "Уникальных клиентов"),
    ])
    panel_html = SHIFT_PANEL_TEMPLATE.format(
        key=key, title=html.escape(title),
        time_range=f' <span style="font-weight:400; color:var(--text-secondary); font-size:13px;">({time_range})</span>' if time_range else "",
        tiles=tiles,
        bar_tu=bar_chart_html(from_tu, "Отправлено анкетами", f"tu-{key}"),
        bar_ru=bar_chart_html(from_ru, "Получено от клиентов", f"ru-{key}"),
        team_table=team_table_html(by_tu),
        profile_table=profile_table_html(by_tu),
        client_table=client_table_html(by_ru),
    )
    return panel_html, total, len(by_tu), len(by_ru)


def render_report(local_date: datetime, conn):
    all_shifts = [FULL_DAY_SHIFT] + SHIFTS
    panels, tab_inputs, tab_labels, tab_show_rules = [], [], [], []
    overall_total = overall_profiles = overall_clients = 0

    for key, title, start_h, end_h in all_shifts:
        rows = fetch_shift_rows(conn, local_date, start_h, end_h)
        if key == "total":
            time_range = None
        elif end_h > 24:
            time_range = f"{start_h % 24:02d}:00 {local_date.strftime('%d.%m')} – {end_h % 24:02d}:00 {(local_date + timedelta(days=1)).strftime('%d.%m')}"
        else:
            time_range = f"{start_h % 24:02d}:00–{end_h % 24:02d}:00"
        panel_html, total, n_profiles, n_clients = render_shift_panel(key, title, time_range, rows)
        panels.append(panel_html)
        checked = " checked" if key == "total" else ""
        tab_inputs.append(f'<input type="radio" name="shift-tab" id="tab-{key}"{checked}>')
        label_text = title.replace(" смена", "").replace(" статистика", "")
        tab_labels.append(f'<label for="tab-{key}">{html.escape(label_text)}</label>')
        tab_show_rules.append(f'#tab-{key}:checked ~ .tab-panel-{key} {{ display: block; }}')
        if key == "total":
            overall_total, overall_profiles, overall_clients = total, n_profiles, n_clients

    # Одна общая вкладка "Фейлы" на весь день (06:00-06:00 след. дня) -
    # с фильтром по командам и колонкой смены у каждого фейла.
    day_start, day_end = shift_bounds_utc(local_date, 6, 30)
    fail_list = compute_fails(conn, day_start, day_end)
    panels.append(render_fails_panel(fail_list))
    tab_inputs.append('<input type="radio" name="shift-tab" id="tab-fails">')
    fails_label = "Фейлы" + (f" ⚠{len(fail_list)}" if fail_list else "")
    tab_labels.append(f'<label for="tab-fails">{html.escape(fails_label)}</label>')
    tab_show_rules.append('#tab-fails:checked ~ .tab-panel-fails { display: block; }')

    date_label = local_date.strftime("%d.%m.%Y")
    next_day_label = (local_date + timedelta(days=1)).strftime("%d.%m.%Y")
    period_label = f"{date_label} 06:00 — {next_day_label} 06:00"
    html_out = PAGE_TEMPLATE.format(
        css=CSS_TOKENS, date_label=date_label, period_label=period_label,
        generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
        tab_show_rules="\n".join(tab_show_rules),
        tab_inputs="\n    ".join(tab_inputs),
        tab_labels="\n      ".join(tab_labels),
        tab_panels="\n".join(panels),
    )
    return html_out, overall_total, overall_profiles, overall_clients


INDEX_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Статистика — все отчёты</title>
<style>{css}</style>
</head>
<body>
<div class="wrap" style="max-width:720px;">
  <div class="nav"><a href="chats_index.html">Все чаты (детально по клиентам)</a></div>
  <h1>Статистика по дням</h1>
  <div class="table-wrap">
  <table>
    <thead><tr><th>День</th><th class="num">Сообщений</th><th class="num">Анкет</th><th class="num">Клиентов</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
</div>
</body>
</html>
"""


def rebuild_index():
    manifest = {}
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    rows = []
    for date_str in sorted(manifest.keys(), reverse=True):
        d = manifest[date_str]
        rows.append(
            f"<tr><td><a class='row-link' href='report_{date_str}.html'>{d['label']}</a></td>"
            f"<td class='num'>{d['total']}</td><td class='num'>{d['profiles']}</td>"
            f"<td class='num'>{d['clients']}</td></tr>"
        )
    (REPORTS_DIR / "index.html").write_text(
        INDEX_TEMPLATE.format(css=CSS_TOKENS, rows="".join(rows) or "<tr><td colspan='4'>Пока нет отчётов</td></tr>"),
        encoding="utf-8",
    )


def generate_for_date(conn, local_date: datetime):
    REPORTS_DIR.mkdir(exist_ok=True)
    html_out, total, n_profiles, n_clients = render_report(local_date, conn)
    date_str = local_date.strftime("%Y-%m-%d")
    out_path = REPORTS_DIR / f"report_{date_str}.html"
    out_path.write_text(html_out, encoding="utf-8")

    manifest = {}
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest[date_str] = {"label": local_date.strftime("%d.%m.%Y"), "total": total,
                           "profiles": n_profiles, "clients": n_clients}
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    rebuild_index()
    print(f"Отчёт сохранён: {out_path}")
    return out_path


def main():
    conn = get_connection()
    if len(sys.argv) > 1:
        local_date = datetime.strptime(sys.argv[1], "%Y-%m-%d")
    else:
        local_date = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    generate_for_date(conn, local_date)
    generate_chat_pages.generate_all()


if __name__ == "__main__":
    main()
