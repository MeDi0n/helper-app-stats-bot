"""Общие куски для generate_report.py, generate_chat_pages.py и
verify_fails.py (shift_bounds_utc тут, а не в generate_report.py, чтобы
verify_fails не тянул за собой generate_report и тем самым не захватывал
TU_TEAMS из config.py ДО того, как update_stats.py успеет его обновить)."""
import html
import json
from datetime import datetime, timedelta, timezone

API_DATE_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def shift_bounds_utc(local_midnight: datetime, start_h: int, end_h: int):
    start_local = (local_midnight + timedelta(hours=start_h)).astimezone()
    end_local = (local_midnight + timedelta(hours=end_h)).astimezone()
    return (start_local.astimezone(timezone.utc).strftime(API_DATE_FMT)[:-3] + "Z",
            end_local.astimezone(timezone.utc).strftime(API_DATE_FMT)[:-3] + "Z")


KIND_META = {
    "text":        ("Сообщения",      "#2a78d6", "#3987e5"),
    "sticker":     ("Стикеры",        "#eda100", "#c98500"),
    "gift":        ("Подарки",        "#008300", "#008300"),
    "paidContent": ("Посты",          "#4a3aa7", "#9085e9"),
    "media":       ("Медиа",          "#e87ba4", "#d55181"),
    "post":        ("Посты",          "#1baf7a", "#199e70"),
    "like":        ("Лайки",          "#e34948", "#e66767"),
    "wink":        ("Подмигивания",   "#eb6834", "#d95926"),
}
OTHER_META = ("Другое", "#898781", "#898781")


def normalize_kind(kind: str) -> str:
    return kind if kind in KIND_META else "OTHER"


def kind_meta(kind: str):
    return KIND_META.get(kind, OTHER_META)


def content_preview(msg: dict) -> str:
    kind = msg.get("kind")
    if kind == "text":
        text = (msg.get("text") or "").strip()
        text = " ".join(text.split())
        return (text[:160] + "…") if len(text) > 160 else (text or "(пусто)")
    if kind == "sticker":
        return "[стикер]"
    if kind == "gift":
        return "[подарок] " + (msg.get("text") or "")[:100]
    if kind == "paidContent":
        text = (msg.get("text") or "").strip()
        return f"[пост] {text[:120]}"
    if kind == "media":
        return "[медиа]"
    if kind == "wink":
        return "[подмигивание]"
    if kind == "like":
        return "[лайк]"
    return f"[{kind}]"


CSS_TOKENS = """
  :root {
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --page-plane:     #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --text-muted:     #898781;
    --gridline:       #e1e0d9;
    --border:         rgba(11,11,11,0.10);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      color-scheme: dark;
      --surface-1:      #1a1a19;
      --page-plane:     #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted:     #898781;
      --gridline:       #2c2c2a;
      --border:         rgba(255,255,255,0.10);
    }
    .bar-fill { background: var(--bar-color-dark) !important; }
    .pill-tu { background: rgba(57,135,229,0.18) !important; color: #86b6ef !important; }
    .pill-ru { background: rgba(217,89,38,0.18) !important; color: #f0a378 !important; }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--page-plane);
    color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  .wrap { max-width: 1400px; margin: 0 auto; padding: 32px 20px 64px; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .subtitle { color: var(--text-secondary); margin: 0 0 24px; font-size: 14px; }
  .nav { font-size: 13px; margin-bottom: 20px; }
  .nav a { color: var(--text-secondary); text-decoration: none; }
  .nav a:hover { text-decoration: underline; }
  section { margin-bottom: 36px; }
  h2 { font-size: 15px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: .04em; margin: 0 0 14px; }
  .cols-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 720px) { .cols-2 { grid-template-columns: 1fr; } }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
  .tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .tile-value { font-size: 28px; font-variant-numeric: tabular-nums; font-weight: 600; }
  .tile-label { font-size: 13px; color: var(--text-secondary); margin-top: 4px; }
  .bar-chart { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; }
  .bar-chart h3 { font-size: 13px; color: var(--text-secondary); margin: 0 0 12px; font-weight: 500; }
  .bar-row { display: grid; grid-template-columns: 100px 1fr 40px; align-items: center; gap: 10px; padding: 6px 0; }
  .bar-label { font-size: 13px; color: var(--text-secondary); }
  .bar-track { background: var(--gridline); border-radius: 4px; height: 13px; overflow: hidden; }
  .bar-fill { height: 100%; background: var(--bar-color-light); border-radius: 4px; min-width: 4px; }
  .bar-value { font-size: 13px; text-align: right; font-variant-numeric: tabular-nums; }
  .empty { color: var(--text-muted); font-size: 14px; }
  .table-wrap { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--gridline); white-space: nowrap; }
  th { color: var(--text-secondary); font-weight: 500; font-size: 12px; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  td.total { font-weight: 600; }
  td.muted { color: var(--text-muted); }
  td.wrap-text { white-space: normal; max-width: 420px; }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr:hover { background: var(--page-plane); }
  a.row-link { color: var(--text-primary); text-decoration: none; font-weight: 500; }
  a.row-link:hover { text-decoration: underline; }
  .pill { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 600; }
  .pill-tu { background: #e3edfb; color: #184f95; }
  .pill-ru { background: #fde4d6; color: #a1431a; }
  footer { color: var(--text-muted); font-size: 12px; margin-top: 40px; }
"""


def bar_chart_html(counter, title: str, dom_suffix: str) -> str:
    if not counter:
        return f'<div class="bar-chart"><h3>{html.escape(title)}</h3><p class="empty">Нет данных.</p></div>'
    max_count = max(counter.values())
    items = sorted(counter.items(), key=lambda kv: kv[1], reverse=True)
    rows_html = []
    for kind, count in items:
        label, color_light, color_dark = kind_meta(kind)
        pct = round(count / max_count * 100, 1)
        rows_html.append(f"""
        <div class="bar-row" style="--bar-color-light:{color_light}; --bar-color-dark:{color_dark};">
          <div class="bar-label">{html.escape(label)}</div>
          <div class="bar-track">
            <div class="bar-fill" style="width:{pct}%;" title="{html.escape(label)}: {count}"></div>
          </div>
          <div class="bar-value">{count}</div>
        </div>""")
    return f'<div class="bar-chart"><h3>{html.escape(title)}</h3>' + "".join(rows_html) + "</div>"


def stat_tile(value, label):
    return f"""
    <div class="tile">
      <div class="tile-value">{value}</div>
      <div class="tile-label">{html.escape(str(label))}</div>
    </div>"""
