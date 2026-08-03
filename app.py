import os
import sys
import time
from datetime import datetime

import streamlit as st

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
os.chdir(PROJECT_DIR)

try:
    from core.pipeline import (
        process_query,
        build_azure_client,
        load_ml_router,
        Budget,
        DEPLOYMENT_MODEL,
        DEFAULT_SCHEMA,
    )
    from core.schema_store import SchemaStore
    BACKEND_OK = True
except ImportError as e:
    BACKEND_OK = False
    BACKEND_ERR = str(e)

st.set_page_config(
    page_title="Oracle → PostgreSQL",
    page_icon="🐘",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');

:root {
    --bg: #0f1117;
    --bg-card: #161b27;
    --bg-elevated: #1d2333;
    --border: #2a3147;
    --border-soft: #222840;
    --text: #e8ecf4;
    --text-2: #8b93b0;
    --text-3: #525b7a;
    --blue: #4d9ef7;
    --blue-soft: #0f2040;
    --blue-border: #1a3a6b;
    --green: #3dd68c;
    --green-soft: #0a2318;
    --green-border: #1a4d36;
    --red: #f76d6d;
    --red-soft: #2a0f0f;
    --red-border: #5a1f1f;
    --amber: #f5a623;
    --amber-soft: #2a1a05;
    --amber-border: #5a3a10;
    --purple: #a78bfa;
    --purple-soft: #1a0f2e;
    --radius: 8px;
    --radius-lg: 12px;
    --shadow: 0 1px 3px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.03);
}

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
    background: var(--bg) !important;
    color: var(--text) !important;
}

#MainMenu, footer, .stDeployButton { display: none !important; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: var(--bg-card) !important;
    border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] h3 {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.62rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
    color: var(--text-3) !important;
    margin: 1.5rem 0 0.5rem !important;
}
[data-testid="stSidebarCollapseButton"] { display: none !important; }

/* Main */
.main .block-container {
    padding: 1.5rem 2rem 3rem;
    max-width: 1440px;
}

/* Header */
.pg-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding-bottom: 1.25rem;
    border-bottom: 1px solid var(--border);
    margin-bottom: 1.5rem;
}
.pg-title {
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: var(--text);
}
.pg-title span { color: var(--blue); }
.pg-sub {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    color: var(--text-3);
    margin-top: 4px;
}

/* Metric strip */
.metric-strip {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin-bottom: 1.25rem;
}
.metric-tile {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.8rem 1rem;
}
.metric-num {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.5rem;
    font-weight: 600;
    line-height: 1;
}
.metric-lbl {
    font-size: 0.65rem;
    font-weight: 600;
    color: var(--text-3);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 5px;
}

/* Section label */
.sec-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--text-3);
    margin-bottom: 0.5rem;
    display: flex;
    align-items: center;
    gap: 8px;
}
.sec-label::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
}

/* Pill */
.pill {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 2px 8px;
    border-radius: 99px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    font-weight: 600;
    white-space: nowrap;
}
.pill-green { background: var(--green-soft); color: var(--green); border: 1px solid var(--green-border); }
.pill-red   { background: var(--red-soft);   color: var(--red);   border: 1px solid var(--red-border); }
.pill-blue  { background: var(--blue-soft);  color: var(--blue);  border: 1px solid var(--blue-border); }
.pill-amber { background: var(--amber-soft); color: var(--amber); border: 1px solid var(--amber-border); }
.pill-purple{ background: var(--purple-soft);color: var(--purple);border: 1px solid #3d2a6b; }
.pill-gray  { background: var(--bg-elevated);color: var(--text-3);border: 1px solid var(--border); }

/* Budget bar */
.budget-wrap {
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.7rem 0.9rem;
    margin-bottom: 0.75rem;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
}
.budget-track {
    height: 4px;
    background: var(--border);
    border-radius: 99px;
    overflow: hidden;
    margin-top: 8px;
}
.budget-fill {
    height: 100%;
    border-radius: 99px;
    transition: width 0.4s ease;
}

/* Status box */
.status-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 1rem;
    padding: 0.75rem 1rem;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
}
.cost-line {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    color: var(--text-3);
}

/* SQL lang tag */
.lang-tag {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.58rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    padding: 2px 7px;
    border-radius: 4px;
    display: inline-block;
    margin-bottom: 4px;
}
.lang-oracle { background: #2a1500; color: #f5a623; border: 1px solid #5a3a10; }
.lang-pg     { background: var(--blue-soft); color: var(--blue); border: 1px solid var(--blue-border); }

/* Error box */
.err-box {
    background: var(--red-soft);
    border: 1px solid var(--red-border);
    border-radius: 6px;
    padding: 0.5rem 0.75rem;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.68rem;
    color: var(--red);
    margin-top: 6px;
    word-break: break-all;
}

/* Connection badge */
.conn-ok {
    display: flex; align-items: center; gap: 7px;
    padding: 0.5rem 0.75rem;
    background: var(--green-soft);
    border: 1px solid var(--green-border);
    border-radius: 7px;
    font-size: 0.73rem; font-weight: 600; color: var(--green);
}
.conn-warn {
    padding: 0.5rem 0.75rem;
    background: var(--amber-soft);
    border: 1px solid var(--amber-border);
    border-radius: 7px;
    font-size: 0.73rem; color: var(--amber);
}
.dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; flex-shrink: 0; }

/* Track badge */
.track-badge {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 2px 8px;
    border-radius: 5px;
}
.tb-fast   { background: var(--green-soft); color: var(--green); border: 1px solid var(--green-border); }
.tb-deep   { background: var(--blue-soft);  color: var(--blue);  border: 1px solid var(--blue-border); }
.tb-human  { background: var(--red-soft);   color: var(--red);   border: 1px solid var(--red-border); }

/* TextArea */
.stTextArea textarea {
    background: var(--bg-elevated) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    color: var(--text) !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.78rem !important;
}
.stTextArea textarea:focus {
    border-color: var(--blue) !important;
    box-shadow: 0 0 0 2px rgba(77, 158, 247, 0.15) !important;
}

/* Buttons */
.stButton > button {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.8rem !important;
    border-radius: 7px !important;
    background: var(--bg-elevated) !important;
    border: 1px solid var(--border) !important;
    color: var(--text-2) !important;
    transition: all 0.15s !important;
}
.stButton > button:hover {
    border-color: var(--blue) !important;
    color: var(--blue) !important;
}
.stButton > button[kind="primary"] {
    background: var(--blue) !important;
    border-color: var(--blue) !important;
    color: #fff !important;
}
.stButton > button[kind="primary"]:hover {
    background: #3a8ae0 !important;
    box-shadow: 0 0 16px rgba(77,158,247,0.25) !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    background: var(--bg-elevated) !important;
    border-radius: 8px !important;
    padding: 3px !important;
    gap: 2px !important;
    border: 1px solid var(--border) !important;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.78rem !important;
    color: var(--text-3) !important;
    border-radius: 6px !important;
    padding: 5px 14px !important;
}
.stTabs [aria-selected="true"] {
    background: var(--bg-card) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
}

/* Expander */
div[data-testid="stExpander"] {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
}

/* Toggle */
.stToggle label { font-size: 0.78rem !important; }

/* Number input */
.stNumberInput input {
    background: var(--bg-elevated) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: var(--radius) !important;
    font-family: 'IBM Plex Mono', monospace !important;
}

/* Log area */
.log-area {
    background: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.75rem 1rem;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.7rem;
    color: var(--text-2);
    min-height: 60px;
    line-height: 1.7;
}

/* Code blocks */
.stCode {
    background: var(--bg-elevated) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
}

/* Progress */
.stProgress > div > div {
    background: var(--blue) !important;
}

hr { border-color: var(--border) !important; }

.footer {
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.62rem;
    color: var(--text-3);
    display: flex;
    justify-content: space-between;
}
</style>
""", unsafe_allow_html=True)

if not BACKEND_OK:
    st.error(f"Backend yüklenemedi: {BACKEND_ERR}")
    st.stop()

SAMPLES = {
    "NVL + ROWNUM": (
        "SELECT ROWNUM, NVL(amount, 0) AS amount\n"
        "FROM orders\nWHERE status = 'ACTIVE';"
    ),
    "DECODE + SYSDATE": (
        "SELECT employee_id,\n"
        "  DECODE(dept_id, 10,'HR', 20,'IT', 30,'Finance','Other') AS dept,\n"
        "  SYSDATE AS today\n"
        "FROM employees\nWHERE hire_date > SYSDATE - 365;"
    ),
    "Oracle Outer Join": (
        "SELECT e.name, d.dept_name\n"
        "FROM employees e, departments d\n"
        "WHERE e.dept_id = d.dept_id(+);"
    ),
    "CONNECT BY": (
        "SELECT employee_id, manager_id, last_name\n"
        "FROM employees\nSTART WITH manager_id IS NULL\n"
        "CONNECT BY PRIOR employee_id = manager_id;"
    ),
    "PIVOT": (
        "SELECT * FROM (\n  SELECT department_id, job_id, salary\n  FROM employees\n)\n"
        "PIVOT (\n  AVG(salary) FOR job_id IN ('IT_PROG','SA_REP')\n);"
    ),
    "Window Function": (
        "SELECT employee_id, salary,\n"
        "  RANK() OVER (PARTITION BY dept_id ORDER BY salary DESC) AS rnk,\n"
        "  LAG(salary, 1) OVER (ORDER BY hire_date) AS prev_salary\n"
        "FROM employees;"
    ),
}

_defaults = {
    "sql_input": "",
    "last_result": None,
    "history": [],
    "budget_spent": 0.0,
    "budget_limit": 0.80,
    "do_semantic": True,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

@st.cache_resource
def _load_client():
    return build_azure_client()

@st.cache_resource
def _load_router():
    return load_ml_router()

@st.cache_resource
def _load_schema():
    return SchemaStore(DEFAULT_SCHEMA)

client = _load_client()
ml_model, feature_cols = _load_router()
schema_store = _load_schema()

with st.sidebar:
    st.markdown("""
    <div style="padding:0 0 1.25rem;">
        <div style="font-size:1rem;font-weight:700;color:#e8ecf4;">Oracle → PostgreSQL</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.6rem;color:#525b7a;margin-top:3px;">
            Rule → Val-A → Smart Router → Deep Track → Fallback
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### Bütçe")
    budget_limit = st.number_input(
        "Limit ($)", min_value=0.10, max_value=50.0,
        value=float(st.session_state.budget_limit),
        step=0.10, format="%.2f"
    )
    st.session_state.budget_limit = budget_limit

    spent = st.session_state.budget_spent
    pct = min(100.0, spent / budget_limit * 100) if budget_limit > 0 else 0.0
    bar_color = "#3dd68c" if pct < 60 else "#f5a623" if pct < 85 else "#f76d6d"

    st.markdown(f"""
    <div class="budget-wrap">
        <div style="display:flex;justify-content:space-between;color:#8b93b0;">
            <span>Harcanan</span>
            <span style="color:#e8ecf4;font-weight:600;">${spent:.4f} / ${budget_limit:.2f}</span>
        </div>
        <div class="budget-track">
            <div class="budget-fill" style="width:{pct:.1f}%;background:{bar_color};"></div>
        </div>
        <div style="font-size:0.62rem;color:#525b7a;margin-top:5px;">%{pct:.1f} kullanıldı · {
            f'${budget_limit - spent:.4f} kaldı'
        }</div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("Bütçeyi Sıfırla", use_container_width=True):
        st.session_state.budget_spent = 0.0
        st.rerun()

    st.markdown("### Ayarlar")
    do_semantic = st.toggle(
        "Semantic Doğrulama (OpenAI)",
        value=st.session_state.do_semantic,
        help="Val-A ve Val-B kontrollerini OpenAI ile yapar. Kapalıysa sadece syntax kontrolü yapılır."
    )
    st.session_state.do_semantic = do_semantic

    st.markdown("### Bağlantı")
    if client:
        st.markdown(f"""
        <div class="conn-ok">
            <div class="dot"></div>
            <div>Azure OpenAI ({DEPLOYMENT_MODEL})</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="conn-warn">
            ⚠ Azure OpenAI bağlı değil<br>
            <span style="font-size:0.65rem;opacity:0.7;font-family:'IBM Plex Mono',monospace;">
                AZURE_OPENAI_ENDPOINT ayarlayın
            </span>
        </div>
        """, unsafe_allow_html=True)

    if ml_model is not None:
        st.markdown("""
        <div style="margin-top:0.5rem;padding:0.5rem 0.75rem;background:var(--blue-soft);
                    border:1px solid var(--blue-border);border-radius:7px;
                    font-size:0.73rem;font-weight:600;color:var(--blue);
                    display:flex;align-items:center;gap:7px;">
            <div class="dot"></div>ML Router yüklendi
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="margin-top:0.5rem;padding:0.5rem 0.75rem;background:var(--bg-elevated);
                    border:1px solid var(--border);border-radius:7px;
                    font-size:0.7rem;color:var(--text-3);">
            ML Router yüklenmedi — pattern matching kullanılıyor
        </div>
        """, unsafe_allow_html=True)

    st.markdown("### Örnek Sorgular")
    for name in SAMPLES:
        if st.button(name, key=f"s_{name}", use_container_width=True):
            st.session_state.sql_input = SAMPLES[name]
            st.rerun()

st.markdown("""
<div class="pg-header">
    <div>
        <div class="pg-title">Oracle to <span>PostgreSQL</span></div>
        <div class="pg-sub">Rule Engine → Semantic Val-A → Smart Router → Deep Track → GPT Fallback</div>
    </div>
</div>
""", unsafe_allow_html=True)

tab_translate, tab_history = st.tabs(["Çeviri", "Geçmiş"])

with tab_translate:
    col_l, col_r = st.columns(2, gap="large")

    with col_l:
        st.markdown('<div class="sec-label">Oracle SQL</div>', unsafe_allow_html=True)
        oracle_input = st.text_area(
            "oracle_in", value=st.session_state.sql_input, height=300,
            placeholder="-- Oracle SQL sorgusunu buraya yapıştırın...",
            label_visibility="collapsed",
        )
        c1, c2 = st.columns([3, 1])
        with c1:
            translate_btn = st.button("Çevir →", type="primary", use_container_width=True)
        with c2:
            if st.button("Temizle", use_container_width=True):
                st.session_state.sql_input = ""
                st.session_state.last_result = None
                st.rerun()

    with col_r:
        st.markdown('<div class="sec-label">PostgreSQL Çıktısı</div>', unsafe_allow_html=True)
        result = st.session_state.last_result
        if result and result.get("pg_sql"):
            st.text_area(
                "pg_out", value=result["pg_sql"], height=300,
                label_visibility="collapsed"
            )
            st.download_button(
                "⬇ .sql indir", data=result["pg_sql"],
                file_name=f"pg_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql",
                mime="text/plain", use_container_width=True
            )
        else:
            st.text_area(
                "pg_empty", value="", height=300,
                placeholder="-- Çevrilen PostgreSQL buraya gelecek...",
                label_visibility="collapsed", disabled=True
            )

    if translate_btn:
        sql_to_run = oracle_input.strip()
        if not sql_to_run:
            st.warning("Lütfen bir Oracle SQL sorgusu girin.")
        else:
            budget_obj = Budget(
                limit=st.session_state.budget_limit,
                initial_spent=st.session_state.budget_spent,
            )
            if budget_obj.exceeded():
                st.error(
                    f"Bütçe limiti aşıldı "
                    f"(${budget_obj.spent:.4f} / ${budget_obj.limit:.2f}). "
                    "Lütfen bütçeyi sıfırlayın."
                )
            else:
                log_messages: list[str] = []
                log_ph = st.empty()
                prog = st.progress(0, text="Pipeline başlatılıyor...")

                def log_fn(msg: str):
                    log_messages.append(msg)
                    display = log_messages[-10:]
                    log_ph.markdown(
                        '<div class="log-area">'
                        + "<br>".join(display)
                        + "</div>",
                        unsafe_allow_html=True,
                    )

                prog.progress(10, text="Kural motoru çalışıyor...")
                log_fn("🚀 Pipeline başlatıldı")

                result = process_query(
                    oracle_sql=sql_to_run,
                    client=client,
                    ml_model=ml_model,
                    feature_cols=feature_cols,
                    schema_store=schema_store,
                    budget=budget_obj,
                    do_semantic=st.session_state.do_semantic,
                    log_fn=log_fn,
                )

                prog.progress(100, text="Tamamlandı ✓")
                time.sleep(0.3)
                prog.empty()
                log_ph.empty()

                st.session_state.budget_spent = budget_obj.spent
                st.session_state.last_result = result
                st.session_state.history.append({
                    "ts": datetime.now().strftime("%H:%M:%S"),
                    "status": result["status"],
                    "track": result["track"],
                    "source": result["source"],
                    "cost": result["total_cost"],
                    "fallback": result["fallback_used"],
                    "duration": result["duration_s"],
                    "preview": sql_to_run[:70],
                })
                st.rerun()

    result = st.session_state.last_result
    if result:
        st.markdown("---")

        status    = result.get("status", "HUMAN_REVIEW")
        track     = result.get("track", "unknown")
        source    = result.get("source", "failed")
        syn_ok    = result.get("syntax_ok", False)
        sem_ok    = result.get("semantic_ok")
        cost      = result.get("total_cost", 0.0)
        cost_tr   = result.get("cost_translate", 0.0)
        cost_sem  = result.get("cost_semantic", 0.0)
        fallback  = result.get("fallback_used", False)
        dur       = result.get("duration_s", 0.0)

        status_pill = (
            '<span class="pill pill-green">✔ Başarılı</span>'
            if status == "SUCCESS"
            else '<span class="pill pill-red">✗ Human Review</span>'
        )
        track_label = {
            "fast": "⚡ Fast Track",
            "deep_direct": "🔵 Deep Track",
            "fast_to_deep": "🔵 Fast→Deep",
            "fast_fallback_deep": "🔵 Fallback→Deep",
        }.get(track, track)
        track_cls = (
            "tb-fast" if track == "fast"
            else "tb-human" if status == "HUMAN_REVIEW"
            else "tb-deep"
        )
        sem_pill = (
            "" if sem_ok is None
            else '<span class="pill pill-green">Semantic ✔</span>' if sem_ok
            else '<span class="pill pill-amber">Semantic ✗</span>'
        )
        fb_pill = (
            '<span class="pill pill-purple">GPT Fallback ✔</span>'
            if fallback and status == "SUCCESS"
            else '<span class="pill pill-amber">GPT Fallback ✗</span>'
            if fallback and status != "SUCCESS"
            else ""
        )
        src_pill = (
            f'<span class="pill pill-blue">{source}</span>'
        )

        st.markdown(f"""
<div class="status-row">
{status_pill}
<span class="track-badge {track_cls}">{track_label}</span>
{src_pill}
{sem_pill}
{fb_pill}
<span class="cost-line" style="margin-left:auto;">
    çeviri ${cost_tr:.5f} · semantic ${cost_sem:.5f} · toplam <b>${cost:.5f}</b> · {dur}s
</span>
</div>
""", unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown('<div class="lang-tag lang-oracle">Oracle</div>', unsafe_allow_html=True)
            st.code(result.get("oracle_sql", ""), language="sql")
        with c2:
            st.markdown('<div class="lang-tag lang-pg">PostgreSQL</div>', unsafe_allow_html=True)
            st.code(result.get("pg_sql") or "-- Çeviri başarısız", language="sql")

        if result.get("parse_error"):
            st.markdown(
                f'<div class="err-box">⚠ Syntax: {result["parse_error"]}</div>',
                unsafe_allow_html=True
            )
        if result.get("semantic_issues"):
            st.markdown(
                f'<div class="err-box">⚠ Semantic: {result["semantic_issues"][:300]}</div>',
                unsafe_allow_html=True
            )

with tab_history:
    history = st.session_state.get("history", [])

    if not history:
        st.markdown("""
        <div style="text-align:center;padding:4rem 1rem;color:#525b7a;">
            <div style="font-size:2rem;margin-bottom:0.75rem;opacity:0.4;">○</div>
            <div style="font-family:'IBM Plex Mono',monospace;font-size:0.78rem;">
                Bu oturumda henüz çeviri yapılmadı
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        total_cost   = sum(h["cost"] for h in history)
        success_cnt  = sum(1 for h in history if h["status"] == "SUCCESS")
        fallback_cnt = sum(1 for h in history if h.get("fallback"))

        st.markdown(f"""
        <div class="metric-strip">
            <div class="metric-tile">
                <div class="metric-num">{len(history)}</div>
                <div class="metric-lbl">Toplam Çeviri</div>
            </div>
            <div class="metric-tile">
                <div class="metric-num" style="color:#3dd68c;">{success_cnt}</div>
                <div class="metric-lbl">Başarılı</div>
            </div>
            <div class="metric-tile">
                <div class="metric-num" style="color:#f76d6d;">{len(history) - success_cnt}</div>
                <div class="metric-lbl">Human Review</div>
            </div>
            <div class="metric-tile">
                <div class="metric-num" style="color:#4d9ef7;">${total_cost:.4f}</div>
                <div class="metric-lbl">Toplam Maliyet</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="sec-label">Oturum Geçmişi</div>', unsafe_allow_html=True)

        for h in reversed(history):
            pill = '<span class="pill pill-green">✔</span>' \
                if h["status"] == "SUCCESS" else '<span class="pill pill-red">✗</span>'
            
            st.markdown(f"""
<div style="background:var(--bg-card);border:1px solid var(--border-soft);border-radius:var(--radius);
            padding:0.7rem 1rem;margin-bottom:0.4rem;display:flex;align-items:center;gap:10px;">
    <div style="font-family:'JetBrains Mono',monospace;font-size:0.7rem;color:var(--text-3);flex-shrink:0;">{h['ts']}</div>
    {pill}
    <div style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;color:var(--text-2);
                flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{h['preview']}…</div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:0.68rem;color:var(--text-3);flex-shrink:0;">
        {h['source']} · ${h['cost']:.5f}</div>
</div>
""", unsafe_allow_html=True)
        if st.button("Geçmişi Temizle"):
            st.session_state.history = []
            st.session_state.last_result = None
            st.rerun()

st.markdown("""
<div class="footer">
    <span>Oracle → PostgreSQL Migration Platform</span>
    <span>Rule Engine · Semantic Val · Smart Router · Deep Track · GPT Fallback</span>
</div>
""", unsafe_allow_html=True)