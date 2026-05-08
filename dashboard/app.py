"""Eidos Memory Dashboard — Streamlit UI.

Usage:
    streamlit run dashboard/app.py
"""

import sys
import time
from pathlib import Path
from typing import Any

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.dashboard import extended_report, timeseries_report

st.set_page_config(
    page_title="Эйдос · Дашборд памяти",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🧠 Эйдос — Мониторинг памяти")
st.caption("Дашборд состояния эпизодической, семантической и рабочей памяти")


def _fmt_bytes(b: int) -> str:
    for unit in ("B", "KB", "MB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} GB"


def _gauge(val: float, max_val: float, label: str, unit: str = "") -> str:
    pct = min(val / max_val * 100, 100) if max_val else 0
    blocks = int(pct / 10)
    bar = "█" * blocks + "░" * (10 - blocks)
    return f"{bar} {val:.0f}{unit} / {max_val:.0f}{unit}"


@st.fragment(run_every=5)
def _refreshable_gauges(report: dict[str, Any]) -> None:
    ep = report.get("episodic", {})
    sm = report.get("semantic", {})
    wm = report.get("working", {})

    g1, g2, g3, g4 = st.columns(4)
    with g1:
        st.metric("Эпизоды", ep.get("total_episodes", 0), delta=None)
    with g2:
        st.metric("Принципы", sm.get("principles", 0), delta=None)
    with g3:
        st.metric("Рабочая память", wm.get("event_count", 0), delta=None)
    with g4:
        st.metric("Суждений (мораль)", report.get("moral", {}).get("judgments", 0))

    g1, g2, g3, g4 = st.columns(4)
    with g1:
        st.caption(
            _gauge(
                ep.get("total_episodes", 0),
                max(ep.get("total_episodes", 0), 1000),
                "Эпизоды",
            )
        )
    with g2:
        st.caption(
            _gauge(
                sm.get("principles", 0),
                max(sm.get("principles", 0), 50),
                "Принципы",
            )
        )
    with g3:
        wm_count = wm.get("event_count", 0)
        st.caption(
            _gauge(
                wm_count,
                max(wm_count, 50),
                "События WM",
            )
        )
    with g4:
        st.caption(
            f"Здоровье: {'✅ ok' if report.get('health') == 'ok' else '⚠ warning'}"
        )


@st.fragment(run_every=10)
def _refreshable_charts() -> None:
    series = timeseries_report(limit=500)
    if series:
        st.subheader("📈 Salience эпизодов (по времени)")
        chart_data = {
            "timestamp": [s["ts_human"] for s in series],
            "salience": [s["salience"] for s in series],
            "summary_len": [s["summary_len"] for s in series],
        }
        st.area_chart(chart_data, x="timestamp", y=["salience", "summary_len"])

        # Tag frequency bar
        st.subheader("🏷️ Частота тегов")
        st.caption("Топ-10 тегов среди всех эпизодов")

    st.caption(f"Обновлено: {time.strftime('%H:%M:%S')}")


# ── Main layout ──

# Sidebar
with st.sidebar:
    st.header("⚙️ Управление")
    refresh = st.button("🔄 Обновить сейчас")
    st.divider()
    st.subheader("📋 Базы данных")
    st.code("""
data/
├── working/   current.json
├── episodic/  episodes.db / moral.db
├── semantic/  knowledge.db
├── external/  documents.db
├── goals/     goals.db
└── journal/   INDEX.md + *.md
    """)
    st.divider()
    st.caption("Эйдос v0.1 · Memory Dashboard")

# Main area
report = extended_report()

with st.expander("📊 Общее состояние", expanded=True):
    _refreshable_gauges(report)

with st.expander("🗂️ Эпизодическая память", expanded=True):
    ep = report.get("episodic", {})
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Всего эпизодов", ep.get("total_episodes", 0))
        st.metric("Средняя salience", f"{ep.get('avg_salience', 0):.2f}")
    with c2:
        st.metric("Средняя access_count", ep.get("avg_access_count", "—"))
        st.metric("Всего доступов", ep.get("total_access_count", "—"))
    with c3:
        dist = ep.get("salience_distribution", {})
        st.write("**Распределение salience**")
        for k, v in dist.items():
            st.caption(f"  {k}: {v}")
    st.caption(f"Размер БД: {_fmt_bytes(ep.get('size_bytes', 0))}")

    # Tags
    top_tags = ep.get("top_tags", [])
    if top_tags:
        st.write("**Топ тегов:**")
        for tag, cnt in top_tags:
            st.caption(f"  #{tag}: {cnt}")

with st.expander("🧠 Семантическая память", expanded=True):
    sm = report.get("semantic", {})
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Принципов", sm.get("principles", 0))
    with c2:
        st.metric("Средняя уверенность", f"{sm.get('avg_confidence', 0):.2f}")
    with c3:
        dist = sm.get("confidence_distribution", {})
        st.write("**Распределение confidence**")
        for k, v in dist.items():
            st.caption(f"  {k}: {v}")
    st.caption(f"Размер БД: {_fmt_bytes(sm.get('size_bytes', 0))}")

with st.expander("💼 Рабочая память (WM)", expanded=False):
    wm = report.get("working", {})
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Событий в буфере", wm.get("event_count", 0))
    with c2:
        role_br = wm.get("role_breakdown", {})
        if role_br:
            st.write("**Роль → кол-во:**")
            for role, cnt in role_br.items():
                st.caption(f"  [{role}]: {cnt}")
    session_title = wm.get("session_title")
    if session_title:
        st.info(f"Текущая сессия: **{session_title}**")

with st.expander("🔧 Инструментальная память", expanded=True):
    inst = report.get("instrumental", {})
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Инструментов", inst.get("total_tools", 0))
    with c2:
        st.metric("Средний confidence", f"{inst.get('avg_confidence', 0):.0%}")
    with c3:
        st.metric("Высокий ≥80%", inst.get("high_confidence", 0))
    tools = inst.get("tools_detail", [])
    if tools:
        st.write("**Все инструменты:**")
        for t in tools:
            pct = f"{t['confidence']:.0%}"
            hint = t.get("context_hint", "") or ""
            s = t.get("success_count", 0)
            f = t.get("fail_count", 0)
            st.caption(f"  [{pct}] {t['tool_name']}/{t['method']} — {hint[:100]} ({s}✓ / {f}✗)")

with st.expander("🌐 Внешняя память", expanded=False):
    ext = report.get("external", {})
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Документов", ext.get("documents", 0))
    with c2:
        st.metric("Уникальных источников", ext.get("unique_sources", 0))
    with c3:
        st.caption(f"Размер: {_fmt_bytes(ext.get('size_bytes', 0))}")

with st.expander("🎯 Цели (Goals)", expanded=False):
    goals = report.get("goals", {})
    if goals:
        for status, cnt in goals.items():
            st.caption(f"  {status}: {cnt}")
    else:
        st.caption("Нет активных целей")

with st.expander("📓 Журнал (последние сессии)", expanded=False):
    jl = report.get("journal_recent", [])
    if jl:
        for line in jl:
            st.text(line)
    else:
        st.caption("Нет записей")

# Charts (auto-refresh every 10s)
_refreshable_charts()

# Bottom info
st.divider()
st.caption(f"Последний полный снимок: {report.get('ts_human', '—')}")
