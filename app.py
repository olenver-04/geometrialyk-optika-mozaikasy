"""Геометриялық оптика мозаикасы · Интерактивті сабақ рефлексиясы.

Басты экран: /              Оқушы: /?view=student
Мұғалім: /?view=admin        ADMIN_PASSWORD — Streamlit Secrets ішінде.
"""

from __future__ import annotations

import base64
import csv
import hmac
import html
import json
import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path

import qrcode
import streamlit as st
import streamlit.components.v1 as components


BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
DB_FILE = BASE_DIR / "reflections.db"
COLS, ROWS = 15, 10
TILE_WIDTH, TILE_HEIGHT = 80, 60
PIECES_PER_ANSWER = 6
TOTAL_PIECES = COLS * ROWS
MOSAIC_ORDER = list(range(TOTAL_PIECES))
random.Random(2026).shuffle(MOSAIC_ORDER)

st.set_page_config(
    page_title="Геометриялық оптика мозаикасы",
    page_icon="🔭",
    layout="wide",
    initial_sidebar_state="collapsed",
)


@contextmanager
def database():
    connection = sqlite3.connect(DB_FILE, timeout=25)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 25000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with database() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS reflections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_name TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


def clean_text(value: str) -> str:
    return " ".join(value.strip().split())


def add_reflection(name: str, answer: str):
    name, answer = clean_text(name), clean_text(answer)
    if not (2 <= len(name) <= 60):
        raise ValueError("Аты-жөніңіз 2–60 таңба аралығында болуы керек.")
    if not (5 <= len(answer) <= 350):
        raise ValueError("Жауап 5–350 таңба аралығында болуы керек.")
    with database() as con:
        con.execute(
            "INSERT INTO reflections (student_name, answer, created_at) VALUES (?, ?, ?)",
            (name, answer, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def all_reflections():
    with database() as con:
        return con.execute("SELECT * FROM reflections ORDER BY id ASC").fetchall()


def remove_reflection(reflection_id: int):
    with database() as con:
        con.execute("DELETE FROM reflections WHERE id = ?", (reflection_id,))


def remove_all_reflections():
    with database() as con:
        con.execute("DELETE FROM reflections")


def safe_spreadsheet_cell(value: str) -> str:
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def csv_export(rows) -> bytes:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["№", "Оқушы", "Жауап", "Уақыты (UTC)"])
    for row in rows:
        writer.writerow(
            [row["id"], safe_spreadsheet_cell(row["student_name"]),
             safe_spreadsheet_cell(row["answer"]), row["created_at"]]
        )
    return buffer.getvalue().encode("utf-8-sig")


def admin_password() -> str:
    try:
        return str(st.secrets.get("ADMIN_PASSWORD", "")).strip()
    except (OSError, FileNotFoundError, KeyError):
        return ""


def get_urls():
    try:
        main_url = st.context.url.split("?", 1)[0].rstrip("/") + "/"
    except (AttributeError, RuntimeError):
        main_url = "http://localhost:8501/"
    return main_url, main_url + "?view=student", main_url + "?view=admin"


def qr_code_bytes(url: str) -> bytes:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    stream = BytesIO()
    qr.make_image(fill_color="#0A1B3C", back_color="#FFFFFF").save(stream, "PNG")
    return stream.getvalue()


def optics_image_uri() -> str:
    # Берілген референс кескін еш өзгертілмейді; оның орысша жазуы
    # мозаиканың SVG көру аймағынан төменде қалады.
    data = (ASSETS_DIR / "optics.webp").read_bytes()
    return "data:image/webp;base64," + base64.b64encode(data).decode("ascii")


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def mosaic_svg(rows, fresh_ids: set[int]) -> str:
    """Сурет 150 бөлшектен тұрады; әр жауап 6 жаңа бөлшекті ашады."""
    width, height = COLS * TILE_WIDTH, ROWS * TILE_HEIGHT
    unlocked = min(TOTAL_PIECES, len(rows) * PIECES_PER_ANSWER)
    base_tiles = []
    clips = []
    selectable = []
    highlights = []

    for position in range(TOTAL_PIECES):
        x = (position % COLS) * TILE_WIDTH
        y = (position // COLS) * TILE_HEIGHT
        tone = "#091A32" if (position % COLS + position // COLS) % 2 else "#0D2240"
        base_tiles.append(
            f'<rect x="{x}" y="{y}" width="{TILE_WIDTH}" height="{TILE_HEIGHT}" fill="{tone}"/>'
            f'<rect x="{x + 1}" y="{y + 1}" width="{TILE_WIDTH - 2}" height="{TILE_HEIGHT - 2}" '
            'fill="none" stroke="#4779A4" stroke-opacity=".24"/>'
        )

    for index in range(unlocked):
        position = MOSAIC_ORDER[index]
        x = (position % COLS) * TILE_WIDTH
        y = (position // COLS) * TILE_HEIGHT
        owner = rows[index // PIECES_PER_ANSWER]
        owner_id = int(owner["id"])
        clips.append(
            f'<rect x="{x}" y="{y}" width="{TILE_WIDTH}" height="{TILE_HEIGHT}"/>'
        )
        selectable.append(
            f'<g class="tile-hit" data-id="{owner_id}" tabindex="0" role="button" '
            f'aria-label="{esc(owner["student_name"])}: {esc(owner["answer"])}">'
            f'<title>{esc(owner["student_name"])} — {esc(owner["answer"])}</title>'
            f'<rect x="{x}" y="{y}" width="{TILE_WIDTH}" height="{TILE_HEIGHT}" fill="transparent"/>'
            '</g>'
        )
        if owner_id in fresh_ids:
            highlights.append(
                f'<rect class="new-tile" x="{x + 2}" y="{y + 2}" '
                f'width="{TILE_WIDTH - 4}" height="{TILE_HEIGHT - 4}" rx="3" '
                'fill="none" stroke="#B4E8FF" stroke-width="3"/>'
            )

    # Сурет ені SVG-мен бірдей, ал биіктігі 662 px. 600 px көрінетін
    # аумақта бастапқы референстің төменгі орысша тақырыбы жоқ.
    optics = optics_image_uri()
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"
        role="img" aria-label="Геометриялық оптиканың біртіндеп ашылатын мозаикасы">
      <defs>
        <clipPath id="revealed">{''.join(clips)}</clipPath>
        <linearGradient id="titleBackdrop" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#04112A" stop-opacity="0"/>
          <stop offset="1" stop-color="#04112A" stop-opacity=".94"/>
        </linearGradient>
        <filter id="neon"><feGaussianBlur stdDeviation="5" result="glow"/>
          <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
      <rect width="{width}" height="{height}" fill="#07162E"/>
      {''.join(base_tiles)}
      <g clip-path="url(#revealed)">
        <image href="{optics}" x="0" y="0" width="1200" height="662"
          preserveAspectRatio="none"/>
        <rect x="0" y="510" width="1200" height="90" fill="url(#titleBackdrop)"/>
        <text x="600" y="573" text-anchor="middle" font-size="42" font-weight="800"
          font-family="Arial, DejaVu Sans, sans-serif" letter-spacing="3"
          fill="#E4F8FF" stroke="#1C74C9" stroke-opacity=".5" stroke-width="2"
          paint-order="stroke" filter="url(#neon)">ГЕОМЕТРИЯЛЫҚ ОПТИКА</text>
      </g>
      {''.join(highlights)}
      {''.join(selectable)}
      <rect x="2" y="2" width="1196" height="596" rx="9" fill="none"
        stroke="#78CFFF" stroke-opacity=".56" stroke-width="3"/>
    </svg>'''


def mosaic_html(rows, new_ids: set[int]) -> str:
    svg = mosaic_svg(rows, new_ids)
    answer_map = {
        str(row["id"]): {"name": str(row["student_name"]), "answer": str(row["answer"])}
        for row in rows
    }
    payload = json.dumps(answer_map, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return '''<!doctype html><html lang="kk"><head><meta charset="utf-8">
    <style>
    *{box-sizing:border-box}
    body{margin:0;background:transparent;color:#e8f6ff;font-family:Arial,DejaVu Sans,sans-serif}
    .frame{padding:7px;border-radius:18px;background:#06122a;border:1px solid #2b6c9e;
       box-shadow:0 0 34px #205db222;overflow:hidden}
    svg{display:block;width:100%;height:auto;border-radius:10px}
    .tile-hit{cursor:pointer;outline:none}
    .tile-hit:hover rect,.tile-hit:focus rect{fill:#bdeeff30;stroke:#c9f5ff;stroke-width:2}
    .new-tile{animation:pop 1.6s ease-out 2;pointer-events:none}
    @keyframes pop{0%{opacity:1;stroke-width:6;filter:drop-shadow(0 0 12px #b0f4ff)}100%{opacity:0;stroke-width:1}}
    #detail{display:flex;align-items:center;justify-content:center;text-align:center;gap:10px;
      border:1px solid #254666;border-radius:13px;min-height:64px;margin-top:11px;
      background:#0a1c37;padding:12px;color:#b8d1e4;font-size:14px;line-height:1.55}
    #detail strong{color:#86d8ff}#detail span{overflow-wrap:anywhere}
    </style></head><body>
    <div class="frame">'''+svg+'''</div>
    <div id="detail">🧩 Ашылған бөлікке басыңыз — оқушының жауабын көресіз.</div>
    <script>
    const answers='''+payload+''';
    const detail=document.querySelector('#detail');
    document.querySelectorAll('.tile-hit').forEach(el=>{
      function show(){
        const a=answers[el.dataset.id]; if(!a)return;
        detail.replaceChildren();
        const n=document.createElement('strong');n.textContent='👤 '+a.name+': ';
        const t=document.createElement('span');t.textContent=a.answer;
        detail.append(n,t);
      }
      el.addEventListener('click',show);
      el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show()}});
    });
    </script></body></html>'''


def load_styles():
    st.markdown("<style>" + (BASE_DIR / "style.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)


def masthead(tag: str):
    st.markdown(
        f'<div class="brand"><span class="brand-mark">✦</span> OPTIKA LAB '
        f'<span class="brand-dot">/</span> {esc(tag)}</div>',
        unsafe_allow_html=True,
    )


def hero(student: bool):
    if student:
        kicker = "ФИЗИКА · СЕНІҢ ОЙЫҢ МАҢЫЗДЫ"
        heading = "Мозаиканың <em>бір бөлігін аш!</em>"
        description = "Бүгінгі сабақтан не үйрендің? Өз ойыңды жазып, ортақ оптика мозаикасын толықтыр."
    else:
        kicker = "ФИЗИКА · ИНТЕРАКТИВТІ РЕФЛЕКСИЯ"
        heading = "Геометриялық <em>оптика мозаикасы</em>"
        description = (
            "Жарықтың шағылуы мен сынуы, толық ішкі шағылу және оптикалық құрылғылар. "
            "Әр жауап — ортақ ғылыми суреттің жаңа бөлігі."
        )
    st.markdown(
        f'<section class="hero"><span class="hero-grid"></span>'
        f'<div class="hero-kicker">✧ {kicker}</div>'
        f'<h1>{heading}</h1><p>{description}</p>'
        f'<div class="hero-chips"><span>◇ Жарықтың шағылуы</span><span>◇ Жарықтың сынуы</span>'
        f'<span>◇ Толық ішкі шағылу</span><span>◇ Оптикалық құрылғылар</span></div>'
        f'</section>', unsafe_allow_html=True,
    )


def teacher_wall(student_url: str):
    left, right = st.columns([3.8, 1.05], gap="large", vertical_alignment="center")
    with left:
        hero(student=False)
    with right:
        st.markdown('<div class="qr-head">📱 QR-КОДТЫ СКАНЕРЛЕ</div>', unsafe_allow_html=True)
        st.image(qr_code_bytes(student_url), use_container_width=True)
        st.link_button("✍️ Жауап қалдыру", student_url, use_container_width=True)
        st.markdown('<div class="qr-caption">Телефоныңнан кіріп, өз ойыңды жаз</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-kicker">✦ ЖАРЫҚ ӘЛЕМІН БІРГЕ АШАМЫЗ</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-heading">Әр жауап — жаңа жарық сәулесі</div>', unsafe_allow_html=True)

    @st.fragment(run_every="3s")
    def live_section():
        rows = all_reflections()
        pieces = min(TOTAL_PIECES, len(rows) * PIECES_PER_ANSWER)
        current_ids = {int(row["id"]) for row in rows}
        old_ids = st.session_state.get("optics_seen_ids")
        new_ids = current_ids - old_ids if old_ids is not None else set()
        st.session_state["optics_seen_ids"] = current_ids
        st.markdown(
            f'<div class="stat-row"><span class="stat-tag">👥 Жауаптар <b>{len(rows)}</b></span>'
            f'<span class="stat-tag">🧩 Ашылған бөліктер <b>{pieces}/{TOTAL_PIECES}</b></span>'
            '<span class="live-tag"><i></i> ТІКЕЛЕЙ ЖАҢАРТУ · 3 С</span></div>',
            unsafe_allow_html=True,
        )
        st.progress(pieces / TOTAL_PIECES)
        mosaic_col, feedback_col = st.columns([1.75, 1], gap="large", vertical_alignment="top")
        with mosaic_col:
            components.html(mosaic_html(rows, new_ids), height=590, scrolling=False)
            if not rows:
                st.info("Алғашқы жауап мозаиканың алғашқы 6 бөлігін ашады!")
            elif pieces == TOTAL_PIECES:
                st.success("🎉 Мозаика толық ашылды! Барлық қатысушыларға рақмет!")
            else:
                st.markdown('<div class="under-mosaic">✦ Әр жауап мозаиканың 6 жаңа бөлігін ашады</div>', unsafe_allow_html=True)

        with feedback_col:
            st.markdown('<div class="feedback-heading">💬 Оқушылардың ойлары</div>', unsafe_allow_html=True)
            if not rows:
                st.markdown(
                    '<div class="feedback-card empty"><div class="empty-symbol">✧</div>'
                    'Әзірге жауап жоқ.<span>Оқушылар QR-код арқылы кіргеннен кейін жауаптар осы жерде пайда болады.</span></div>',
                    unsafe_allow_html=True,
                )
                return

            ids = [int(row["id"]) for row in rows]
            selected_id = st.session_state.get("optics_selected_id")
            following_latest = st.session_state.get("optics_follow_latest", True)
            if following_latest or selected_id not in ids:
                selected_index = len(ids) - 1
            else:
                selected_index = ids.index(selected_id)
            before, counter, after = st.columns([1, .55, 1], gap="small", vertical_alignment="center")
            with before:
                prev = st.button("← Артқа", disabled=selected_index == 0, use_container_width=True)
            with after:
                nxt = st.button("Алға →", disabled=selected_index == len(ids) - 1, use_container_width=True)
            if prev:
                selected_index -= 1
                st.session_state["optics_follow_latest"] = False
            if nxt:
                selected_index += 1
                st.session_state["optics_follow_latest"] = selected_index == len(ids) - 1
            with counter:
                st.markdown(f'<div class="counter">{selected_index + 1}/{len(ids)}</div>', unsafe_allow_html=True)
            st.session_state["optics_selected_id"] = ids[selected_index]
            entry = rows[selected_index]
            st.markdown(
                f'<div class="feedback-card"><div class="feedback-small">✧ ОҚУШЫНЫҢ ЖАУАБЫ</div>'
                f'<div class="feedback-name">👤 {esc(entry["student_name"])}</div>'
                f'<div class="feedback-text">{esc(entry["answer"])}</div></div>',
                unsafe_allow_html=True,
            )
            if not st.session_state.get("optics_follow_latest", True):
                if st.button("↪ Соңғы жауапқа өту", use_container_width=True):
                    st.session_state["optics_follow_latest"] = True
                    st.session_state["optics_selected_id"] = ids[-1]
                    st.rerun(scope="fragment")

    live_section()
    st.markdown('<div class="footer">✦ ГЕОМЕТРИЯЛЫҚ ОПТИКА · БІЛІМ МЕН ЖАРЫҚ ӘЛЕМІ ✦</div>', unsafe_allow_html=True)


def student_page(wall_url: str):
    masthead("ОҚУШЫ ПАРАҒЫ")
    hero(student=True)
    st.markdown('<div class="section-kicker">✦ ӨЗ ОЙЫҢДЫ БӨЛІС</div>', unsafe_allow_html=True)
    left, right = st.columns([1.6, 1], gap="large")
    with left:
        st.markdown(
            '<div class="prompt-card"><div class="prompt-label">💭 РЕФЛЕКСИЯ СҰРАҒЫ</div>'
            '<p>Бүгінгі сабақтан геометриялық оптика, толық ішкі шағылу немесе оптикалық құрылғылар '
            'туралы қандай жаңа мәлімет алдың? Саған не ерекше қызық болды?</p></div>',
            unsafe_allow_html=True,
        )
        with st.form("reflection_form", clear_on_submit=True):
            name = st.text_input("👤 Аты-жөнің", placeholder="Мысалы: Айдана", max_chars=60)
            answer = st.text_area(
                "✍️ Жауабың",
                placeholder="Мен бүгін жарықтың сынуы туралы білдім...",
                max_chars=350, height=155,
            )
            sent = st.form_submit_button("✦ Мозаика бөліктерін ашу", type="primary", use_container_width=True)
        if sent:
            try:
                add_reflection(name, answer)
            except ValueError as err:
                st.warning(str(err))
            except sqlite3.Error:
                st.error("Жауапты сақтау мүмкін болмады. Қайталап көріңіз.")
            else:
                st.success(f"✨ Рақмет, {clean_text(name)}! Сен мозаиканың 6 жаңа бөлігін аштың!")
                st.balloons()
        st.link_button("👁️ Ортақ мозаиканы көру", wall_url, use_container_width=True)
    with right:
        st.markdown(
            '<div class="tips-card"><div class="tips-title">💡 Жауапты осылай бастауға болады:</div>'
            '<div class="tip">«Мен бүгін білдім, ...»</div>'
            '<div class="tip">«Маған қызықты болғаны, ...»</div>'
            '<div class="tip">«Толық ішкі шағылу дегеніміз, ...»</div>'
            '<div class="tip">«Оптикалық құрылғылардың қызметі ...»</div>'
            '<p class="tips-note">Жауабың мұғалім экранында аты-жөніңмен бірге көрсетіледі.</p></div>',
            unsafe_allow_html=True,
        )
    st.markdown('<div class="footer">✦ ӘР ПІКІР — МАҢЫЗДЫ ✦</div>', unsafe_allow_html=True)


def admin_page(wall_url: str):
    masthead("МҰҒАЛІМ ПАНЕЛІ")
    st.title("🔐 Мозаиканы басқару")
    secret = admin_password()
    if not secret:
        st.error("Әкімші панелін қосу үшін Streamlit Secrets ішіне ADMIN_PASSWORD орнатыңыз.")
        st.code('ADMIN_PASSWORD = "өзіңіздің-күрделі-құпиясөзіңіз"', language="toml")
        return
    if not st.session_state.get("optics_admin_authenticated", False):
        with st.form("admin_login"):
            entered = st.text_input("Құпиясөз", type="password")
            login = st.form_submit_button("Кіру", type="primary")
        if login:
            if hmac.compare_digest(entered.encode(), secret.encode()):
                st.session_state["optics_admin_authenticated"] = True
                st.rerun()
            else:
                st.error("Құпиясөз дұрыс емес.")
        return
    if st.button("🚪 Шығу"):
        st.session_state["optics_admin_authenticated"] = False
        st.rerun()

    rows = all_reflections()
    a, b = st.columns(2)
    a.metric("Жауап саны", len(rows))
    b.metric("Ашылған бөліктер", f"{min(TOTAL_PIECES, len(rows) * PIECES_PER_ANSWER)} / {TOTAL_PIECES}")
    st.download_button(
        "⬇️ Барлық жауапты CSV ретінде жүктеу",
        data=csv_export(rows),
        file_name="optika_refleksiya_zhauaptar.csv",
        mime="text/csv",
        disabled=not rows,
        use_container_width=True,
    )
    st.divider()
    st.subheader("🗑️ Жеке жауапты жою")
    if rows:
        lookup = {int(row["id"]): row for row in rows}
        selection = st.selectbox(
            "Жауапты таңдаңыз", list(reversed(lookup)),
            format_func=lambda idx: f'#{idx} — {lookup[idx]["student_name"]}: {lookup[idx]["answer"][:55]}',
        )
        if st.button("Таңдалған жауапты жою"):
            remove_reflection(int(selection))
            st.rerun()
    else:
        st.info("Әзірге жауап жоқ.")
    st.divider()
    st.subheader("🧹 Мозаиканы тазарту")
    approved = st.checkbox("Барлық жауаптың жойылатынын түсінемін")
    if st.button("Барлық жауапты жою", type="primary", disabled=not (approved and rows)):
        remove_all_reflections()
        st.rerun()
    st.warning("Streamlit Community Cloud-та SQLite деректері қайта іске қосылғанда жоғалуы мүмкін. Сабақ аяқталғанда CSV файлын сақтаңыз.")
    st.link_button("↗ Басты экранды ашу", wall_url)


def main():
    init_db()
    load_styles()
    wall_url, student_url, _admin_url = get_urls()
    view = st.query_params.get("view", "wall")
    if view == "student":
        student_page(wall_url)
    elif view == "admin":
        admin_page(wall_url)
    else:
        teacher_wall(student_url)


if __name__ == "__main__":
    main()
