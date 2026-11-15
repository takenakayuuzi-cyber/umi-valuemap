"""研究会用「海の命」バリューマップの部屋（Streamlit Community Cloud ＋ Gemini）。

・入口のパスコード（参加者用・先生用）と Gemini の APIキーは、Streamlit の Secrets に入れる（プログラムに書かない）
・机（1〜10）：① 話し合いの前の人数 → 問い（表と判定の決まりで選ぶ。Q9・Q10 だけAIが言葉を整える）
              ② 話し合いの後の人数 → ①から②への動きを1行（AI。答えなければ人数の差からプログラムが1行）
・先生：10机のちらばり・問い・動きの一覧（5秒ごと）。ほかの机の入力は、先生の画面だけで見える
・机の入力は、このアプリの中だけに置く（アプリが止まると消える。研究会の1日用）
"""
import json
import os
import threading
import time

import streamlit as st

import ai_backend as ai
import vm_core as core

st.set_page_config(page_title="海の命 バリューマップの部屋", page_icon="🗺", layout="wide")
VM = core.load(ai.setting("MATERIAL", "海の命"))
P = core.places_of(VM)
CODES = [p["code"] for p in VM["places"]]
NAMES = {c: core.short(VM, c) for c in CODES}
DESKS, SEATS = 10, 8

st.markdown("""<style>
.block-container { padding-top: 1.6rem; max-width: 1180px; }
div.stButton > button { min-height: 3.2rem; font-size: 1.15rem; font-weight: 800; border-radius: 999px; }
div.stButton > button[kind="primary"] { background: linear-gradient(180deg, #3dbdf6, #14a9ee); border: 0; }
.qcard { border: 5px solid #14a9ee; border-radius: 26px; padding: 22px 28px; background: #fff; margin: 8px 0 14px; }
.qcard small { color: #5d6e8f; font-weight: 800; }
.qcard p { font-size: 1.9rem; font-weight: 900; line-height: 1.6; margin: 6px 0 0; color: #1b2a4a; }
.mline { border-radius: 20px; padding: 14px 20px; background: #dcf8e9; font-size: 1.35rem; font-weight: 900; color: #1b2a4a; margin: 6px 0 12px; }
.dcard { border-radius: 20px; padding: 12px 14px; background: #f2f6fc; margin-bottom: 12px; min-height: 120px; }
.dcard h4 { margin: 0 0 4px; } .dcard .q { font-weight: 800; line-height: 1.5; } .dcard .m { color: #17804c; font-weight: 800; margin-top: 6px; }
.dcard small { color: #5d6e8f; }
</style>""", unsafe_allow_html=True)


# ---------- 机の入力を、すべての画面で共有する置き場所（研究会の1日用） ----------
class Board:
    def __init__(self):
        self.lock = threading.Lock()
        self.path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".store", "board.json")
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = {int(k): v for k, v in json.load(f).items()}
        except (OSError, ValueError):
            self.data = {}

    def put(self, desk, key, value):
        with self.lock:
            self.data.setdefault(desk, {})[key] = value
            if key == "r1":   # ①を入れ直したら、②はやり直し
                self.data[desk].pop("r2", None)
            self._save()

    def get(self, desk):
        with self.lock:
            return json.loads(json.dumps(self.data.get(desk, {})))

    def all(self):
        with self.lock:   # 机の番号は数のまま（json を通すと文字になるので もどす）
            return {int(k): v for k, v in json.loads(json.dumps(self.data)).items()}

    def clear(self):
        with self.lock:
            self.data = {}
            self._save()

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False)


@st.cache_resource
def board():
    return Board()


# ---------- 問いと動き（表で決めて、AIは言葉を整えるだけ） ----------
def make_question(counts, evidence):
    q, values = core.judge(VM, counts, evidence)
    filled = core.fill(q["text"], values)
    out = {"qid": q["id"], "question": filled, "by": "table", "why": ""}
    if values:   # Q9・Q10 だけ
        try:
            text = ai.polish_question(VM, q["text"], values)
            why = core.check_polished(text, filled, values, q["text"])
            out.update({"question": text, "by": "ai"} if not why else {"why": why})
        except ai.AiError as e:
            out["why"] = str(e)
    return out


def make_move(before, after):
    if not any(d for c, a, b, d in core.moves(VM, before, after)) and before.get("C", 0) == after.get("C", 0):
        return {"line": core.move_line(VM, before, after), "by": "table", "why": "動きなし"}   # 動いていなければ、AIに聞かない
    try:
        text = ai.describe_move(VM, before, after, NAMES, core.diff_text(VM, before, after))
        why = core.check_move(text, VM, before, after)
        if not why:
            return {"line": text, "by": "ai", "why": ""}
    except ai.AiError as e:
        why = str(e)
    return {"line": core.move_line(VM, before, after), "by": "table", "why": why}


def counts_inputs(prefix, start):
    cols = st.columns(2)
    out = {}
    for i, p in enumerate(VM["places"]):
        with cols[i % 2]:
            out[p["code"]] = int(st.number_input(f"{NAMES[p['code']]}（{p['desc'] if p['kind'] != 'between' else '二人のあいだ'}）",
                                                 min_value=0, max_value=40, step=1, value=int(start.get(p["code"], 0)), key=f"{prefix}_{p['code']}"))
    return out


# ---------- 入口 ----------
def login():
    st.title("🗺 「海の命」バリューマップの部屋")
    st.caption("研究会用。机の iPad で使います。")
    if not ai.setting("PASSCODE"):
        st.error("Streamlit の Secrets に PASSCODE が入っていません（公開の手順を見てください）。")
        return
    code = st.text_input("パスコード", type="password")
    if st.button("はいる", type="primary"):
        if code == ai.setting("PASSCODE"):
            st.session_state.role = "desk"
            st.rerun()
        elif ai.setting("TEACHER_PASSCODE") and code == ai.setting("TEACHER_PASSCODE"):
            st.session_state.role = "teacher"
            st.rerun()
        else:
            time.sleep(1)
            st.error("パスコードがちがいます。")


def pick_desk():
    st.title("🗺 机の番号をえらんでください")
    for row in range(2):
        cols = st.columns(5)
        for i in range(5):
            n = row * 5 + i + 1
            if cols[i].button(f"机 {n}", key=f"desk{n}", use_container_width=True):
                st.session_state.desk = n
                st.rerun()


def desk_view():
    n = st.session_state.desk
    rec = board().get(n)
    top = st.columns([4, 1])
    top[0].title(f"🗺 机 {n}　「海の命」バリューマップ")
    if top[1].button("机をかえる"):
        st.session_state.pop("desk")
        st.rerun()

    st.subheader("① 話し合いの前：机のみんなは、太一をどこに置いた？")
    left, right = st.columns([3, 2])
    with left:
        c1 = counts_inputs("r1", (rec.get("r1") or {}).get("counts", {}))
        with st.expander("根拠にした言葉も入れる（入れなくてもよい）"):
            st.caption("番号ごとに、置いた場所と、根拠にした本文の言葉を入れます。同じ言葉でちがう場所に置いた人がいると、それを問いにします。")
            evidence = []
            old = {e["no"]: e for e in (rec.get("r1") or {}).get("evidence", [])}
            for i in range(1, SEATS + 1):
                a, b = st.columns([2, 3])
                opts = [""] + CODES
                place = a.selectbox(f"{i}番の場所", opts, index=opts.index(old.get(i, {}).get("place", "")),
                                    format_func=lambda c: NAMES.get(c, "（えらばない）"), key=f"ev_p{i}")
                word = b.text_input(f"{i}番の言葉", value=old.get(i, {}).get("word", ""), max_chars=40, key=f"ev_w{i}")
                if place and word.strip():
                    evidence.append({"no": i, "place": place, "word": word.strip()})
    with right:
        st.markdown(core.triangle_svg(VM, c1), unsafe_allow_html=True)
        st.caption(f"ぜんぶで {sum(c1.values())}人")
    if st.button("🎯 問いをもらう", type="primary", disabled=not sum(c1.values())):
        with st.spinner("問いを えらんでいます…"):
            q = make_question(c1, evidence)
        board().put(n, "r1", {"counts": c1, "evidence": evidence, **q, "at": time.time()})
        st.rerun()

    r1 = rec.get("r1")
    if not r1:
        return
    st.markdown(f'<div class="qcard"><small>{r1["qid"]}・この机への問い</small><p>{r1["question"]}</p></div>', unsafe_allow_html=True)

    st.subheader("② 話し合いの後：もう一度、太一をどこに置いた？")
    left, right = st.columns([3, 2])
    with left:
        c2 = counts_inputs("r2", (rec.get("r2") or {}).get("counts", r1["counts"]))
    with right:
        st.markdown(core.triangle_svg(VM, c2), unsafe_allow_html=True)
        st.caption(f"ぜんぶで {sum(c2.values())}人")
    if st.button("➡ ①から②への動きを見る", type="primary", disabled=not sum(c2.values())):
        with st.spinner("動きを まとめています…"):
            m = make_move(r1["counts"], c2)
        board().put(n, "r2", {"counts": c2, **m, "at": time.time()})
        st.rerun()
    r2 = rec.get("r2")
    if r2:
        st.markdown(f'<div class="mline">➡ {r2["line"]}<br><small>{core.diff_text(VM, r1["counts"], r2["counts"])}</small></div>', unsafe_allow_html=True)


# ---------- 先生の画面 ----------
@st.fragment(run_every=5)
def teacher_board():
    data = board().all()
    tot1 = {c: sum((d.get("r1") or {}).get("counts", {}).get(c, 0) for d in data.values()) for c in CODES}
    # ②がまだの机は、①のまま数える（まだ入れていない机を「動いた」と見ないように）
    tot2 = {c: sum((d.get("r2") or d.get("r1") or {}).get("counts", {}).get(c, 0) for d in data.values()) for c in CODES}
    a, b, c = st.columns([1, 1, 2])
    a.markdown("**会場ぜんたい ①**" + core.triangle_svg(VM, tot1, 220), unsafe_allow_html=True)
    b.markdown("**会場ぜんたい ②**（②がまだの机は①のまま）" + core.triangle_svg(VM, tot2, 220), unsafe_allow_html=True)
    with c:
        st.markdown(f"**入れた机：** {sum(1 for d in data.values() if d.get('r1'))} / {DESKS}　**②まで：** {sum(1 for d in data.values() if d.get('r2'))}")
        if any(d.get("r2") for d in data.values()):
            st.markdown("**① から ② への動き（会場ぜんたい）：** " + core.move_line(VM, tot1, tot2))
        st.caption(f"AI：{ai.provider()}　（5秒ごとに新しくなります）")
    st.divider()
    for row in range(2):
        cols = st.columns(5)
        for i in range(5):
            n = row * 5 + i + 1
            d = data.get(n, {})
            r1, r2 = d.get("r1"), d.get("r2")
            with cols[i]:
                if not r1:
                    st.markdown(f'<div class="dcard"><h4>机 {n}</h4><small>まだ</small></div>', unsafe_allow_html=True)
                    continue
                tri = ('<div style="display:flex;gap:4px"><div style="flex:1"><small>①</small>' + core.triangle_svg(VM, r1["counts"], 120) + "</div>"
                       + ('<div style="flex:1"><small>②</small>' + core.triangle_svg(VM, r2["counts"], 120) + "</div>" if r2 else "") + "</div>")
                st.markdown(f'<div class="dcard"><h4>机 {n}　<small>{r1["qid"]}{"・AI" if r1["by"] == "ai" else ""}</small></h4>{tri}'
                            f'<div class="q">{r1["question"]}</div>'
                            + (f'<div class="m">➡ {r2["line"]}</div><small>{core.diff_text(VM, r1["counts"], r2["counts"])}</small>' if r2 else "<small>②はまだ</small>") + "</div>", unsafe_allow_html=True)


def teacher_view():
    st.title("🗺 先生用：10机のバリューマップ")
    teacher_board()
    with st.expander("机の入力をぜんぶ消す（研究会のはじめに）"):
        if st.checkbox("ほんとうに消す") and st.button("ぜんぶ消す"):
            board().clear()
            st.rerun()


role = st.session_state.get("role")
if role == "teacher":
    teacher_view()
elif role == "desk":
    if st.session_state.get("desk"):
        desk_view()
    else:
        pick_desk()
else:
    login()
