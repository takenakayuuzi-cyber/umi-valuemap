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
.block-container { padding-top: 4.2rem; max-width: 1400px; }   /* 上のバー（GitHub のマークなど）と重ならないように */
div.stButton > button { min-height: 3.1rem; font-size: 1.1rem; font-weight: 800; border-radius: 999px; }
div.stButton > button p { color: inherit !important; font-weight: 800; }   /* ボタンの文字は、ボタンの色に合わせる */
div.stButton > button[kind="primary"] { background: linear-gradient(180deg, #3dbdf6, #14a9ee); color: #fff; border: 0; }
div.stButton > button[kind="primary"]:hover { background: #0a86c4; color: #fff; }
.desk { display: inline-block; background: #14a9ee; color: #fff; border-radius: 14px; padding: 4px 20px; font-size: 1.6rem; font-weight: 900; }
.today { background: #e4f6fe; border-radius: 16px; padding: 14px 20px; margin: 10px 0 6px; }
.today small { color: #0a86c4; font-weight: 900; } .today b { display: block; color: #1b2a4a; font-size: 1.25rem; line-height: 1.5; }
.qbox { border: 4px dashed #f2b800; background: #fff8dc; border-radius: 18px; padding: 16px 22px; margin: 10px 0 14px; }
.qbox small { color: #8a6400; font-weight: 900; } .qbox p { color: #1b2a4a; font-size: 1.7rem; font-weight: 900; line-height: 1.6; margin: 6px 0 0; }
.qbox .hint { margin-top: 12px; padding-top: 10px; border-top: 2px dashed #f2d27a; color: #1b2a4a; font-size: 1.15rem; font-weight: 800; line-height: 1.6; }
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
        self.flag = os.path.join(os.path.dirname(self.path), "closed")   # 「研究会を終わる」を押したら、このファイルができる
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = {int(k): v for k, v in json.load(f).items()}
        except (OSError, ValueError):
            self.data = {}

    @property
    def closed(self):
        return os.path.exists(self.flag)

    def set_closed(self, on):
        os.makedirs(os.path.dirname(self.flag), exist_ok=True)
        if on:
            open(self.flag, "w").close()
        elif os.path.exists(self.flag):
            os.remove(self.flag)

    def put(self, desk, key, value):
        with self.lock:
            self.data.setdefault(desk, {})[key] = value
            if key == "r1":   # ①を入れ直したら、②はやり直し
                self.data[desk].pop("r2", None)
            self._save()

    def set_pos(self, desk, rnd, no, xy):
        """こま1つの位置（xy が None なら、置いていないにもどす）。ほかの人のこまは さわらない。"""
        with self.lock:
            pos = self.data.setdefault(desk, {}).setdefault(f"pos{rnd}", {})
            if xy:
                pos[str(no)] = [int(xy[0]), int(xy[1])]
            else:
                pos.pop(str(no), None)
            self._save()

    def set_word(self, desk, no, word):
        with self.lock:
            self.data.setdefault(desk, {}).setdefault("words", {})[str(no)] = str(word or "").strip()[:40]
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
def _board(version):
    return Board()


def board():
    """机の記録の置き場所。プログラムの Board を直したら（version が変わったら）作りなおす。
    記録はファイル（.store/board.json）から読みなおすので消えない。古い置き場所を使い続けてエラーになったため（2026-11-15）。"""
    import hashlib
    import inspect
    return _board(hashlib.md5(inspect.getsource(Board).encode()).hexdigest())


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


def make_hint(pieces, evidence, question):
    """この机へのひとこと：分かれ目の2人（と、その2人が入れた根拠の言葉）と、読みなおす場面を、プログラムが場面の表から1文にする。
    AIに整えさせると、問いを写したり場面を落としたりしたので（ためして 0/8）、AIは使わない。"""
    ctx = core.hint_context(VM, pieces, evidence)
    return {"hint": ctx["fallback"], "scene": (ctx["scene"] or {}).get("id")}


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


# 地図の上で こまを指で動かす部品（vm_board/index.html）。画像は部品のフォルダから読み、やりとりは位置の数字だけ
import streamlit.components.v1 as components
_vm_board = components.declare_component("vm_board", path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "vm_board"))
GEO = None
if LAY:
    _b = LAY["board"]
    GEO = {"size": LAY["size"], "center": _b["center"], "radius": _b["radius"], "near": _b["near"], "lines": _b["lines"],
           "names": {c: NAMES[c] for c in CODES}}


def board_map(n, rnd, pos, mine, ghost=None, words=None):
    """机のみんなのこまを地図に出し、自分のこまだけ動かせる。動かしたら、そのこまだけを机の記録に入れる。"""
    v = _vm_board(rnd=rnd, pos=pos, mine=mine, ghost=ghost or {}, words=words or {}, seats=SEATS, geo=GEO, key=f"map{rnd}_{n}", default=None)
    if v and v.get("seq") != st.session_state.get(f"seq{rnd}"):
        st.session_state[f"seq{rnd}"] = v.get("seq")
        if mine == "all" or int(v.get("no", 0)) == int(mine):   # 自分のこまだけ
            board().set_pos(n, rnd, int(v["no"]), v.get("xy"))
            st.rerun(scope="fragment")


def placed_text(pos):
    nos = sorted(int(k) for k in pos)
    return f"置いたこま {len(nos)}こ（" + "・".join(f"{x}番" for x in nos) + "）" if nos else "まだ だれも置いていません"


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
    if not st.toggle("📷 Canva のボードの写真から、こまを置く（使わなくてもよい）", key="photo_on"):
        return
    with st.container(border=True):
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
            c1, c2 = core.photo_positions(got, LAY)   # 写真の言葉は使わない（AIが作ってしまうことがあった）
            for no, xy in c1.items():
                board().set_pos(n, 1, int(no), xy)
            for no, xy in c2.items():
                board().set_pos(n, 2, int(no), xy)
            st.session_state.photo_note = (f"写真から読みとりました：① {len(c1)}こ" + (f"・② {len(c2)}こ" if c2 else "")
                                           + "。まちがいがないか確かめてください。")
            st.rerun()


def desk_view():
    # 机のみんなで1枚の地図（ロイロノートの共有ノートのように、だれでも どのこまでも動かせる）
    n, seat = st.session_state.desk, "all"
    top = st.columns([5, 1])
    top[0].markdown(f'<span class="desk">机 {n}</span>　<b>机のみんなで1枚の地図を使います。自分の番号のこまを動かしましょう。</b>', unsafe_allow_html=True)
    if top[1].button("机をかえる"):
        for k in list(st.session_state):
            if k != "role":
                st.session_state.pop(k)
        st.rerun()
    if TODAY:
        st.markdown(f'<div class="today"><small>今日の問い</small><b>{TODAY}</b></div>', unsafe_allow_html=True)
    if not GEO:
        st.error("地図のファイルが見つかりません（data フォルダを確かめてください）。")
        return
    # 根拠の言葉（自分の端末で、自分の番号の分を入れる。3秒ごとに新しくなる場所の外に置くので、書いている途中で消えない）
    words = board().get(n).get("words", {})
    with st.expander("✏️ 根拠にした本文の言葉を入れる（なくてもよい）", expanded=False):
        st.caption("入れて Enter（またはほかのところを押す）と、①の地図で、その番号の太一のそばに出ます。同じ言葉で ちがう場所に置いた人がいると、それを問いにします。")
        for no in range(1, SEATS + 1):
            key = f"word{no}"
            if key not in st.session_state:
                st.session_state[key] = words.get(str(no), "")
            st.text_input(f"{no}番の言葉", key=key, max_chars=40, on_change=lambda no=no: board().set_word(n, no, st.session_state[f"word{no}"]))
    photo_section(n)
    live(n, seat)
    rec = board().get(n)
    if rec.get("r1"):
        wall(n, rec, rec["r1"])


@st.fragment(run_every=1.5)
def live(n, seat):
    """地図・問い・動き（机のみんなの動きが 1.5秒ごとに反映される）。"""
    rec = board().get(n)
    pos1, pos2, words = rec.get("pos1", {}), rec.get("pos2", {}), rec.get("words", {})
    st.markdown('<div class="sec">① はじめの考え：自分の番号の太一のこまを、地図に置こう</div>', unsafe_allow_html=True)
    board_map(n, 1, pos1, seat, words=words)   # 根拠の言葉は、①の地図で太一のそばに吹き出しで出る
    p1 = core.pieces_of(LAY, pos1)
    st.caption(placed_text(pos1) + "。だれが「問いをもらう」を押しても、机のみんなに同じ問いが出ます。")
    r1 = rec.get("r1")
    if st.button("🎯 この机の問いをもらう" + ("（もう一度）" if r1 else ""), type="primary", disabled=not p1, key="ask_q"):
        evidence = [{"no": no, "place": place, "word": words[str(no)]} for no, place in sorted(p1.items()) if words.get(str(no))]
        c1 = core.counts_of(p1)
        with st.spinner("問いを えらんでいます…"):
            q = make_question(c1, evidence)
            q.update(make_hint(p1, evidence, q["question"]))
        board().put(n, "r1", {"pieces": {str(k): v for k, v in p1.items()}, "pos": pos1, "counts": c1, "evidence": evidence, **q, "at": time.time()})
        st.rerun()
    if not r1:
        return
    st.markdown(f'<div class="qbox"><small>この机の問い（{r1["qid"]}）</small><p>{r1["question"]}</p>'
                + (f'<div class="hint">📖 この机へのひとこと：{r1["hint"]}</div>' if r1.get("hint") else "") + "</div>", unsafe_allow_html=True)
    st.markdown('<div class="sec">② 話し合ったあとの考え：②のこまを置こう（①は うすく出ています。動かしません）</div>', unsafe_allow_html=True)
    board_map(n, 2, pos2, seat, ghost=r1.get("pos") or pos1)
    p2 = core.pieces_of(LAY, pos2)
    st.caption(placed_text(pos2))
    if st.button("➡ ①から②への動きを見る", type="primary", disabled=not p2, key="ask_m"):
        c2 = core.counts_of(p2)
        with st.spinner("動きを まとめています…"):
            m = make_move(r1["counts"], c2)
        board().put(n, "r2", {"pieces": {str(k): v for k, v in p2.items()}, "pos": pos2, "counts": c2, **m, "at": time.time()})
        st.rerun()
    r2 = rec.get("r2")
    if r2:
        st.markdown(f'<div class="mline">➡ {r2["line"]}<small>{core.diff_text(VM, r1["counts"], r2["counts"])}</small></div>', unsafe_allow_html=True)


def wall(n, rec, r1):
    st.markdown('<div class="sec">💬 壁打ち（AIと話して、考えを深める。机のみんなで見られます）</div>', unsafe_allow_html=True)
    st.caption("AIは答えや「正しい位置」は言いません。根拠や、ほかの角からの見え方を問い返します。")
    wall_log(n)
    said = st.chat_input("この机の考えや、聞いてみたいことを書いてください")
    if said:
        said = said.strip()[:300]
        rec = board().get(n)
        talk = rec.get("chat", [])
        system = core.wall_system(VM, r1["question"], (rec.get("r2") or r1)["counts"], r1.get("evidence", []))
        who = ""
        with st.spinner("考えています…"):
            try:
                out = core.check_wall(ai.chat(system, (talk + [{"role": "user", "text": said}])[-12:]))
            except ai.AiError:
                out = None
        board().talk(n, [{"role": "user", "who": who, "text": said, "at": time.time()},
                         {"role": "ai", "text": out or "うまく答えられませんでした。もう一度、問いにもどって、根拠の言葉をさがしてみましょう。", "at": time.time()}])
        st.rerun()


@st.fragment(run_every=3)
def wall_log(n):
    for m in board().get(n).get("chat", [])[-12:]:
        with st.chat_message("user" if m["role"] == "user" else "assistant", avatar="🧑‍🏫" if m["role"] == "user" else "🗺"):
            st.write((f"**{m['who']}**　" if m.get("who") else "") + m["text"])


# ---------- 先生の画面 ----------
@st.fragment(run_every=5)
def teacher_board():
    data = board().all()
    tot1 = {c: sum((d.get("r1") or {}).get("counts", {}).get(c, 0) for d in data.values()) for c in CODES}   # 問いをもらった机の①
    # ②がまだの机は、①のまま数える（まだ入れていない机を「動いた」と見ないように）
    tot2 = {c: sum((d.get("r2") or d.get("r1") or {}).get("counts", {}).get(c, 0) for d in data.values()) for c in CODES}
    # 「大きく見せる」を押すと、そのマップだけを画面いっぱいに（スクリーンに映して会場ぜんたいで見る）
    big = st.session_state.get("big")
    title = {"1": "会場ぜんたい ①（話し合いの前）", "2": "会場ぜんたい ②（話し合いの後）"}
    if big:
        top = st.columns([4, 1])
        top[0].markdown(f'<div class="sec" style="font-size:1.8rem">{"会場ぜんたい ①→②" if big == "both" else title[big]}</div>', unsafe_allow_html=True)
        if top[1].button("← もどる", use_container_width=True):
            st.session_state.big = None
            st.rerun(scope="fragment")
        fit = lambda html: f'<div style="max-width:calc(74vh * 1420 / 1080);margin:0 auto">{html}</div>'   # 画面の高さに おさまる大きさ
        if big == "both":
            a, b = st.columns(2)
            a.markdown('<div class="sec">①（話し合いの前）</div>' + core.map_html(VM, LAY, tot1, rnd=1), unsafe_allow_html=True)
            b.markdown('<div class="sec">②（話し合いの後）</div>' + core.map_html(VM, LAY, tot2, rnd=2), unsafe_allow_html=True)
        else:
            st.markdown(fit(core.map_html(VM, LAY, tot1 if big == "1" else tot2, rnd=int(big))), unsafe_allow_html=True)
        if any(d.get("r2") for d in data.values()):
            st.markdown(f'<div class="mline">➡ {core.move_line(VM, tot1, tot2)}</div>', unsafe_allow_html=True)
        st.caption(f"入れた机 {sum(1 for d in data.values() if d.get('r1'))} / {DESKS}・②まで {sum(1 for d in data.values() if d.get('r2'))}（5秒ごとに新しくなります）")
        return
    a, b = st.columns(2)
    a.markdown('<div class="sec">' + title["1"] + '</div>' + core.map_html(VM, LAY, tot1, rnd=1), unsafe_allow_html=True)
    b.markdown('<div class="sec">' + title["2"] + '</div>' + core.map_html(VM, LAY, tot2, rnd=2), unsafe_allow_html=True)
    for col, key, label in ((a, "1", "🔍 ①を大きく見せる"), (b, "2", "🔍 ②を大きく見せる")):
        if col.button(label, key=f"big{key}", use_container_width=True):
            st.session_state.big = key
            st.rerun(scope="fragment")
    if st.button("🔍 ①と②をならべて大きく見せる", use_container_width=True):
        st.session_state.big = "both"
        st.rerun(scope="fragment")
    with st.container():
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
                live1 = d.get("pos1") or {}
                if not r1:   # まだ問いをもらっていない机：置いている途中のこまを そのまま
                    st.markdown(f'<div class="dcard"><h4>机 {n}</h4>' + (core.map_html(VM, LAY, {}, small=True, mark="①", pieces=core.pieces_of(LAY, live1), rnd=1,
                                positions=live1) + '<span class="s">置いている途中</span>' if live1 else '<span class="s">まだ</span>') + "</div>", unsafe_allow_html=True)
                    continue
                # 机の画面と同じように、置いた場所そのままの太一のこま（②の地図には①を うすく重ねる）
                pos_or = lambda r: r.get("pos") if r.get("pos") else None
                maps = core.map_html(VM, LAY, r1["counts"], small=True, mark="①", pieces=r1.get("pieces"), rnd=1, positions=pos_or(r1)) + (
                    '<div style="height:6px"></div>' + core.map_html(VM, LAY, r2["counts"], small=True, mark="②", pieces=r2.get("pieces"), rnd=2,
                                                                       ghost=r1.get("pieces"), positions=pos_or(r2), ghost_positions=pos_or(r1)) if r2 else "")
                talks = sum(1 for m in d.get("chat", []) if m["role"] == "user")
                st.markdown(f'<div class="dcard"><h4>机 {n}　<small>{r1["qid"]}{"・AI" if r1["by"] == "ai" else ""}</small></h4>{maps}'
                            f'<div class="q">{r1["question"]}</div>' + (f'<div class="s">📖 {r1["hint"]}</div>' if r1.get("hint") else "")
                            + (f'<div class="m">➡ {r2["line"]}</div>' if r2 else '<div class="s">②はまだ</div>')
                            + (f'<div class="s">💬 壁打ち {talks}回</div>' if talks else "") + "</div>", unsafe_allow_html=True)


def teacher_view():
    st.title(f"🗺 先生用：{DESKS}机のバリューマップ")
    # ワンタッチで止める・再開する（止めているあいだは Gemini を使わない＝クレジットを使わない）
    if board().closed:
        c = st.columns([3, 1])
        c[0].error("⏹ 研究会を終わっています。AI（Gemini）は止まっていて、机の画面には「研究会は終わりました」と出ています。")
        if c[1].button("▶ 再開する", type="primary", use_container_width=True):
            board().set_closed(False)
            ai.STOPPED = False
            st.rerun()
    else:
        c = st.columns([3, 1])
        c[0].caption("研究会が終わったら、右のボタンを押してください。AI（Gemini）を止め、机の画面を閉じます。もう一度押すと再開できます。")
        if c[1].button("⏹ 研究会を終わる", use_container_width=True):
            board().set_closed(True)
            ai.STOPPED = True
            st.rerun()
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


# 研究会が終わっていたら、AIを一切使わない（どの画面から来ても）
ai.STOPPED = board().closed

role = st.session_state.get("role")
if role == "desk" and board().closed:
    st.title("🗺 「海の命」バリューマップの部屋")
    st.info("研究会は終わりました。ご参加ありがとうございました。")
    st.stop()
if role == "teacher":
    teacher_view()
elif role == "desk":
    if not st.session_state.get("desk"):
        pick_desk()
    else:
        desk_view()
else:
    login()
