"""研究会用「海の命」バリューマップの部屋（Streamlit Community Cloud ＋ Gemini）。

・入口のパスコード（参加者用・先生用）と Gemini の APIキーは、Streamlit の Secrets に入れる（プログラムに書かない）
・机（1〜20。Secrets の DESKS で変えられる）：📷 Canva のバリューマップの写真 → AIが こまの場所を読んで人数を入れる（机が確かめて直す）
              ① 話し合いの前の人数 → 問い（表と判定の決まりで選ぶ。Q9・Q10 だけAIが言葉を整える）
              ② 話し合いの後の人数 → ①から②への動きを1行（AI。合わなければ人数の差からプログラムが1行）
              💬 壁打ち → 答えは言わず、問い返すAI（2文まで）
・先生：机のマップ・問い・動き・壁打ちの回数を一覧（5秒ごと）。ほかの机の入力は、先生の画面だけで見える
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
MATERIAL = ai.setting("MATERIAL", "海の命")
VM = core.load(MATERIAL)
P = core.places_of(VM)
CODES = [p["code"] for p in VM["places"]]
NAMES = {c: core.short(VM, c) for c in CODES}
DESKS = int(ai.setting("DESKS", "20") or 20)   # 机の数（1つの机に4人 × 20 ＝ 80人）。Secrets の DESKS で変えられる
SEATS = 8   # こまの番号（Canva のボードに合わせて 1〜8。4人の机は 1〜4 だけ置く）


@st.cache_resource
def layout(version):
    """地図とこまの絵。data フォルダのファイルが変わったら（version が変わったら）読みなおす。"""
    return core.load_layout(VM, MATERIAL)


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LAY = layout(tuple(sorted((f, os.path.getmtime(os.path.join(DATA_DIR, f)), os.path.getsize(os.path.join(DATA_DIR, f))) for f in os.listdir(DATA_DIR))))
MISSING_PIECES = bool(LAY) and not LAY.get("pieces")
TODAY = (LAY or {}).get("today", "")

# 白い画面（ドクソウと同じ方針。ダークにしない）。Canva のバリューマップの絵（紺）は、白い画面の中のカードとして置く
st.markdown("""<style>
.block-container { padding-top: 4.2rem; max-width: 1240px; }   /* 上のバー（GitHub のマークなど）と重ならないように */
div.stButton > button { min-height: 3.1rem; font-size: 1.1rem; font-weight: 800; border-radius: 999px; }
div.stButton > button p { color: inherit !important; font-weight: 800; }   /* ボタンの文字は、ボタンの色に合わせる */
div.stButton > button[kind="primary"] { background: linear-gradient(180deg, #3dbdf6, #14a9ee); color: #fff; border: 0; }
div.stButton > button[kind="primary"]:hover { background: #0a86c4; color: #fff; }
.desk { display: inline-block; background: #14a9ee; color: #fff; border-radius: 14px; padding: 4px 20px; font-size: 1.6rem; font-weight: 900; }
.today { background: #e4f6fe; border-radius: 16px; padding: 14px 20px; margin: 10px 0 6px; }
.today small { color: #0a86c4; font-weight: 900; } .today b { display: block; color: #1b2a4a; font-size: 1.25rem; line-height: 1.5; }
.qbox { border: 4px dashed #f2b800; background: #fff8dc; border-radius: 18px; padding: 16px 22px; margin: 10px 0 14px; }
.qbox small { color: #8a6400; font-weight: 900; } .qbox p { color: #1b2a4a; font-size: 1.7rem; font-weight: 900; line-height: 1.6; margin: 6px 0 0; }
.sec { color: #0a86c4; font-weight: 900; font-size: 1.25rem; margin: 18px 0 6px; }
.mline { border-radius: 18px; padding: 12px 18px; background: #dcf8e9; border-left: 8px solid #2cc97b; color: #1b2a4a; font-size: 1.3rem; font-weight: 900; margin: 6px 0 12px; }
.mline small { display: block; color: #5d6e8f; font-size: .85rem; font-weight: 700; margin-top: 4px; }
.dcard { border-radius: 16px; padding: 10px 12px; background: #f2f6fc; margin-bottom: 12px; color: #1b2a4a; }
.dcard h4 { margin: 0 0 6px; color: #1b2a4a; } .dcard h4 small { color: #0a86c4; }
.dcard .q { font-weight: 800; line-height: 1.5; margin-top: 6px; } .dcard .m { color: #17804c; font-weight: 800; margin-top: 6px; }
.dcard .s { color: #5d6e8f; font-size: .8rem; }
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

    def talk(self, desk, msgs):
        with self.lock:
            self.data.setdefault(desk, {}).setdefault("chat", []).extend(msgs)
            self.data[desk]["chat"] = self.data[desk]["chat"][-40:]
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
    if not core.changes(VM, before, after):
        return {"line": core.move_line(VM, before, after), "by": "table", "why": "動きなし"}   # 動いていなければ、AIに聞かない
    try:
        text = ai.describe_move(VM, before, after, NAMES, core.diff_text(VM, before, after))
        why = core.check_move(text, VM, before, after)
        if not why:
            return {"line": text, "by": "ai", "why": ""}
    except ai.AiError as e:
        why = str(e)
    return {"line": core.move_line(VM, before, after), "by": "table", "why": why}


def piece_inputs(rnd, start, words=None):
    """太一のこま（番号1〜8）ごとに、どこに置いたかを選ぶ。words があれば、こまごとに根拠の言葉も入れる。
    写真から読んだ場所は、session_state から入る。返すもの：({番号: 場所}, [根拠の言葉])"""
    opts = [""] + CODES
    pieces, evidence = {}, []
    for no in range(1, SEATS + 1):
        key = f"p{rnd}_{no}"
        if key not in st.session_state:
            st.session_state[key] = start.get(str(no), start.get(no, ""))
        cols = st.columns([1, 3, 4] if words is not None else [1, 4])
        img = (LAY or {}).get("pieces", {}).get((rnd, no))
        if img:
            cols[0].image(img, width=46)
        else:
            cols[0].markdown(f"**{no}**")
        place = cols[1].selectbox(f"{'①' if rnd == 1 else '②'}{no}", opts, format_func=lambda c: NAMES.get(c, "置かない"),
                                  key=key, label_visibility="collapsed")
        if place:
            pieces[no] = place
        if words is not None:
            wkey = f"w{rnd}_{no}"
            if wkey not in st.session_state:
                st.session_state[wkey] = words.get(no, "")
            word = cols[2].text_input(f"{no}の言葉", key=wkey, max_chars=40, label_visibility="collapsed", placeholder="根拠の言葉（なくてもよい）")
            if place and word.strip():
                evidence.append({"no": no, "place": place, "word": word.strip()})
    return pieces, evidence


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
    for row in range((DESKS + 4) // 5):
        cols = st.columns(5)
        for i in range(5):
            n = row * 5 + i + 1
            if n > DESKS:
                break
            if cols[i].button(f"机 {n}", key=f"desk{n}", use_container_width=True):
                st.session_state.desk = n
                st.rerun()


def photo_section(n):
    with st.container(border=True):
        st.markdown('<div class="sec" style="margin-top:0">📷 Canva のバリューマップの写真から、人数を入れる（入れなくてもよい）</div>', unsafe_allow_html=True)
        st.caption("こまを置いた Canva のボードの スクリーンショット（ボード全体）がいちばん正確です。写真でもかまいません。それを入れると、AIが こまの場所を読んで ①② の人数を入れます。"
                   "まちがいがないか確かめて、直してから進んでください。どの問いを出すかは、AIではなく表で決めます。")
        up = st.file_uploader("写真をえらぶ", type=["png", "jpg", "jpeg", "heic", "webp"], key=f"photo{n}")
        if up and st.button("📷 写真を読む", type="primary"):
            data = core.prepare_photo(up.getvalue(), LAY)   # 紺のボードだけを切り出して、もとの大きさに
            with st.spinner("AIが写真を読んでいます…（20秒ほど）"):
                try:
                    got = ai.read_photo(LAY, data, "image/jpeg")   # 見本の絵はわたさない（位置がずれた）
                except ai.AiError as e:
                    st.error(f"写真を読めませんでした（{e}）。人数を手で入れてください。")
                    return
            c1, c2 = core.photo_places(VM, got, LAY)   # 写真の言葉は使わない（AIが作ってしまうことがあった）
            for no in range(1, SEATS + 1):
                st.session_state[f"p1_{no}"] = c1.get(no, "")
                st.session_state.pop(f"p2_{no}", None)
            # ②のらんは、①の問いが出るまで画面にない（Streamlit は、画面にないらんの値を すててしまう）ので、別に覚えておく
            st.session_state.photo_p2 = {str(k): v for k, v in c2.items()} if c2 else None
            st.session_state.photo_note = (f"写真から読みとりました：① {len(c1)}こ" + (f"・② {len(c2)}こ" if c2 else "")
                                           + "。まちがいがないか確かめてください。")
            st.rerun()


def desk_view():
    n = st.session_state.desk
    rec = board().get(n)
    top = st.columns([5, 1])
    top[0].markdown(f'<span class="desk">机 {n}</span>', unsafe_allow_html=True)
    if top[1].button("机をかえる"):
        for k in list(st.session_state):
            if k != "role":
                st.session_state.pop(k)
        st.rerun()
    if TODAY:
        st.markdown(f'<div class="today"><small>今日の問い</small><b>{TODAY}</b></div>', unsafe_allow_html=True)
    if MISSING_PIECES:
        st.warning(f"太一のこまの絵のファイルが見つかりません（GitHub の data フォルダに「{MATERIAL}_こま.json」があるか確かめてください）。数字の丸で表示しています。")
    photo_section(n)
    if st.session_state.get("photo_note"):
        st.success(st.session_state.pop("photo_note"))

    st.markdown('<div class="sec">① はじめの考え：太一のこまを、どこに置いた？</div>', unsafe_allow_html=True)
    old1 = rec.get("r1") or {}
    left, right = st.columns([3, 2])
    with right:
        st.caption("こまごとに置いた場所を選びます。根拠にした本文の言葉も入れられます（同じ言葉で ちがう場所に置いた人がいると、それを問いにします）。")
        p1, evidence = piece_inputs(1, old1.get("pieces", {}), {e["no"]: e["word"] for e in old1.get("evidence", [])})
    c1 = core.counts_of(p1)
    with left:
        st.markdown(core.map_html(VM, LAY, c1, pieces=p1, rnd=1), unsafe_allow_html=True)
        st.caption(f"置いたこま {len(p1)}こ")
    if st.button("🎯 この机の問いをもらう", type="primary", disabled=not p1):
        with st.spinner("問いを えらんでいます…"):
            q = make_question(c1, evidence)
        board().put(n, "r1", {"pieces": {str(k): v for k, v in p1.items()}, "counts": c1, "evidence": evidence, **q, "at": time.time()})
        st.rerun()

    r1 = rec.get("r1")
    if not r1:
        return
    st.markdown(f'<div class="qbox"><small>この机の問い（{r1["qid"]}）</small><p>{r1["question"]}</p></div>', unsafe_allow_html=True)

    st.markdown('<div class="sec">② 話し合ったあとの考え：②のこまを、どこに置いた？（①は動かさない）</div>', unsafe_allow_html=True)
    left, right = st.columns([3, 2])
    with right:
        p2, _ = piece_inputs(2, (rec.get("r2") or {}).get("pieces") or st.session_state.get("photo_p2") or r1.get("pieces", {}))
    c2 = core.counts_of(p2)
    with left:
        st.markdown(core.map_html(VM, LAY, c2, pieces=p2, rnd=2, ghost=r1.get("pieces")), unsafe_allow_html=True)
        st.caption(f"置いたこま {len(p2)}こ")
    if st.button("➡ ①から②への動きを見る", type="primary", disabled=not p2):
        with st.spinner("動きを まとめています…"):
            m = make_move(r1["counts"], c2)
        board().put(n, "r2", {"pieces": {str(k): v for k, v in p2.items()}, "counts": c2, **m, "at": time.time()})
        st.rerun()
    r2 = rec.get("r2")
    if r2:
        st.markdown(f'<div class="mline">➡ {r2["line"]}<small>{core.diff_text(VM, r1["counts"], r2["counts"])}</small></div>', unsafe_allow_html=True)

    wall(n, rec, r1)


def wall(n, rec, r1):
    st.markdown('<div class="sec">💬 壁打ち（AIと話して、考えを深める）</div>', unsafe_allow_html=True)
    st.caption("AIは答えや「正しい位置」は言いません。根拠や、ほかの角からの見え方を問い返します。")
    talk = rec.get("chat", [])
    for m in talk[-12:]:
        with st.chat_message("user" if m["role"] == "user" else "assistant", avatar="🧑‍🏫" if m["role"] == "user" else "🗺"):
            st.write(m["text"])
    said = st.chat_input("この机の考えや、聞いてみたいことを書いてください")
    if said:
        said = said.strip()[:300]
        system = core.wall_system(VM, r1["question"], (rec.get("r2") or r1)["counts"], r1.get("evidence", []))
        with st.spinner("考えています…"):
            try:
                out = core.check_wall(ai.chat(system, (talk + [{"role": "user", "text": said}])[-12:]))
            except ai.AiError:
                out = None
        board().talk(n, [{"role": "user", "text": said, "at": time.time()},
                         {"role": "ai", "text": out or "うまく答えられませんでした。もう一度、問いにもどって、根拠の言葉をさがしてみましょう。", "at": time.time()}])
        st.rerun()


# ---------- 先生の画面 ----------
@st.fragment(run_every=5)
def teacher_board():
    data = board().all()
    tot1 = {c: sum((d.get("r1") or {}).get("counts", {}).get(c, 0) for d in data.values()) for c in CODES}
    # ②がまだの机は、①のまま数える（まだ入れていない机を「動いた」と見ないように）
    tot2 = {c: sum((d.get("r2") or d.get("r1") or {}).get("counts", {}).get(c, 0) for d in data.values()) for c in CODES}
    a, b, c = st.columns([2, 2, 2])
    a.markdown('<div class="sec">会場ぜんたい ①</div>' + core.map_html(VM, LAY, tot1), unsafe_allow_html=True)
    b.markdown('<div class="sec">会場ぜんたい ②</div>' + core.map_html(VM, LAY, tot2), unsafe_allow_html=True)
    with c:
        st.markdown(f"**入れた机：** {sum(1 for d in data.values() if d.get('r1'))} / {DESKS}　**②まで：** {sum(1 for d in data.values() if d.get('r2'))}")
        if any(d.get("r2") for d in data.values()):
            st.markdown("**① から ② への動き（会場ぜんたい）：** " + core.move_line(VM, tot1, tot2))
        st.caption(f"②がまだの机は、①のまま数えています。AI：{ai.provider()} {ai.model_name()}（5秒ごとに新しくなります）")
    st.divider()
    for row in range((DESKS + 4) // 5):
        cols = st.columns(5)
        for i in range(5):
            n = row * 5 + i + 1
            if n > DESKS:
                break
            d = data.get(n, {})
            r1, r2 = d.get("r1"), d.get("r2")
            with cols[i]:
                if not r1:
                    st.markdown(f'<div class="dcard"><h4>机 {n}</h4><span class="s">まだ</span></div>', unsafe_allow_html=True)
                    continue
                maps = core.map_html(VM, LAY, r1["counts"], small=True, mark="①") + (
                    '<div style="height:6px"></div>' + core.map_html(VM, LAY, r2["counts"], small=True, mark="②") if r2 else "")
                talks = sum(1 for m in d.get("chat", []) if m["role"] == "user")
                st.markdown(f'<div class="dcard"><h4>机 {n}　<small>{r1["qid"]}{"・AI" if r1["by"] == "ai" else ""}</small></h4>{maps}'
                            f'<div class="q">{r1["question"]}</div>'
                            + (f'<div class="m">➡ {r2["line"]}</div>' if r2 else '<div class="s">②はまだ</div>')
                            + (f'<div class="s">💬 壁打ち {talks}回</div>' if talks else "") + "</div>", unsafe_allow_html=True)


def teacher_view():
    st.title(f"🗺 先生用：{DESKS}机のバリューマップ")
    teacher_board()
    data = board().all()
    talked = [n for n in sorted(data) if data[n].get("chat")]
    if talked:
        with st.expander("💬 机ごとの壁打ちを読む"):
            n = st.selectbox("机", talked, format_func=lambda x: f"机 {x}")
            for m in data[n]["chat"]:
                st.markdown(f"{'🧑‍🏫' if m['role'] == 'user' else '🗺'} {m['text']}")
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
