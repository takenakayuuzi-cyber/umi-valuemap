"""バリューマップの部屋：表と判定の決まり（AIは使わない部分）。

・表（角・問い・判定の決まり・場面・AIに守らせる決まり）は data/<教材>.json。設計メモから ドクソウの取り込みの道具で作る
・どの問いを出すかは、ここで決める（AIではない）
・ドクソウ本体の server/valuemap.py と同じ決まり。研究会用（Streamlit）は、本文を持たないので本文との照らし合わせだけ しない
"""
import difflib
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name="海の命"):
    with open(os.path.join(HERE, "data", f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


PUNCT = re.compile(r"[\s、。，．,.・「」『』（）()！？!?…ー―\-〜~：:；;\"'“”]")


def norm(s):
    """「同じ言葉」かどうかは、空白と句読点を除いて文字が一致するかで見る。"""
    return PUNCT.sub("", str(s or ""))


def places_of(vm):
    return {p["code"]: p for p in vm["places"]}


def short(vm, code):
    """場所の短い名前（「あいだ」は「おとう・母」のように）。"""
    P = places_of(vm)
    p = P[code]
    return "・".join(P[c]["name"] for c in p["parts"]) if p["kind"] == "between" else p["name"]


def weights(vm, counts):
    """三つの角の人数（「あいだ」は両方の角に 0.5人ずつ）。"""
    P = places_of(vm)
    w = {c: float(counts.get(c, 0)) for c, p in P.items() if p["kind"] == "corner"}
    for c, p in P.items():
        if p["kind"] == "between":
            for x in p["parts"]:
                w[x] += counts.get(c, 0) / 2
    return w


# ---------- どの問いを出すか（判定の決まりを、上から順に確かめる） ----------
def judge(vm, counts, evidence=()):
    P = places_of(vm)
    counts = {c: max(0, int(counts.get(c) or 0)) for c in P}
    total = sum(counts.values())
    if not total:
        return None, {}
    corners = [c for c, p in P.items() if p["kind"] == "corner"]
    weight = weights(vm, counts)
    center = next((c for c, p in P.items() if p["kind"] == "center"), None)
    ev = [e for e in evidence if norm(e.get("word")) and e.get("place") in P]
    qs, r = vm["questions"], vm["ratios"]
    name = lambda c: P[c]["name"]
    by_kind = lambda kind, cs=None: next((q for q in qs.values() if q["kind"] == kind and (cs is None or sorted(q.get("corners", [])) == sorted(cs))), None)

    for rule in vm["order"]:
        k = rule["kind"]
        q = qs.get(rule["q"]) if rule["q"] else None
        if k == "same_word" and ev:   # 同じ言葉を根拠にした二人が、ちがう場所に置いている
            for i, a in enumerate(ev):
                b = next((b for b in ev[i + 1:] if norm(b["word"]) == norm(a["word"]) and b["place"] != a["place"]), None)
                if b:
                    return q or by_kind(k), {"言葉": a["word"].strip(), "番号A": f"{a['no']}番", "番号B": f"{b['no']}番",
                                             "角A": name(a["place"]), "角B": name(b["place"])}
        elif k == "diff_word" and ev:   # 机の8割以上が同じ場所で、その中に根拠の言葉がちがう二人がいる
            top = max(counts, key=counts.get)
            if counts[top] >= r["same_place"] * total:
                here = [e for e in ev if e["place"] == top]
                for i, a in enumerate(here):
                    b = next((b for b in here[i + 1:] if norm(b["word"]) != norm(a["word"])), None)
                    if b:
                        return q or by_kind(k), {"番号A": f"{a['no']}番", "番号B": f"{b['no']}番", "言葉A": a["word"].strip(), "言葉B": b["word"].strip()}
        elif k == "majority":   # 一つの角に8割以上
            for c in corners:
                if weight[c] >= r["majority"] * total and (q or by_kind(k, [c])):
                    return q or by_kind(k, [c]), {}
        elif k == "center" and center:   # 真ん中がいちばん多い
            if counts[center] > max(weight.values()):
                return q or by_kind(k), {}
        elif k == "spread":   # 三つの角のどれにも2割以上
            if all(weight[c] >= r["spread"] * total for c in corners):
                return q or by_kind(k), {}
        elif k == "pair":   # 人数の多い二つの角の組み合わせ（同数で決まらないときは、つぎの決まりへ）
            top = sorted(corners, key=lambda c: -weight[c])
            if len(top) >= 3 and weight[top[1]] > weight[top[2]] and weight[top[1]] > 0 and (q or by_kind(k, top[:2])):
                return q or by_kind(k, top[:2]), {}
        elif k == "tie":
            if q or by_kind("spread"):
                return q or by_kind("spread"), {}
    return by_kind("spread"), {}


def fill(text, values):
    return re.sub(r"\{(.+?)\}", lambda m: str(values.get(m.group(1), m.group(0))), text)


# ---------- AIの答えが、決まりを守っているか ----------
def sentences(s):
    return [x for x in re.split(r"(?<=[。？！?!])", s) if x.strip()]


def check_polished(out, filled, values, template, body=""):
    """守っていれば None、守っていなければ そのわけ。body（本文）がないときは、本文との照らし合わせはしない。"""
    if not out:
        return "からっぽ"
    pieces = [norm(x) for x in re.split(r"\{.+?\}|[、。，．,.？！?!]", template) if len(norm(x)) >= 2]
    n = norm(out)
    kept = lambda x: difflib.SequenceMatcher(None, x, n).find_longest_match(0, len(x), 0, len(n)).size >= 0.7 * len(x)
    if pieces and sum(1 for x in pieces if kept(x)) < 0.85 * len(pieces):   # 語尾を整えるくらいは よい
        return "問いの言葉を変えた"
    if len(sentences(out)) > 2:
        return "2文をこえた"
    for v in values.values():
        if v and norm(v) not in n:
            return f"「{v}」が消えた"
    if body:
        allowed, nb = norm(filled), norm(body)
        for i in range(len(n) - 7):   # 渡していない本文の言葉（8文字以上つづくもの）を入れていないか
            if n[i:i + 8] in nb and n[i:i + 8] not in allowed:
                return "渡していない本文の言葉を入れた"
    return None


# ---------- ①から②への動き ----------
def moves(vm, before, after):
    """角ごとの人数の変わり方（「あいだ」は0.5人ずつ）。[(角, ①, ②, 差)]"""
    a, b = weights(vm, before), weights(vm, after)
    out = [(c, a[c], b[c], b[c] - a[c]) for c in a]
    return sorted(out, key=lambda x: -abs(x[3]))


def fmt(x):
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"


def diff_text(vm, before, after):
    """AIにわたす、角ごとの変化（例：「おとう 4→1（−3）、与吉じいさ 1→3（+2）」）。"""
    P = places_of(vm)
    center = next((c for c, p in P.items() if p["kind"] == "center"), None)
    rows = [(P[c]["name"], a, b, d) for c, a, b, d in moves(vm, before, after)]
    if center and (before.get(center, 0) or after.get(center, 0)):
        a, b = before.get(center, 0), after.get(center, 0)
        rows.append((P[center]["name"], a, b, b - a))
    return "、".join(f"{n} {fmt(a)}→{fmt(b)}（{'+' if d > 0 else '−' if d < 0 else '±'}{fmt(abs(d))}）" for n, a, b, d in rows)


def move_line(vm, before, after):
    """AIが答えないときの1行（人数の差から、プログラムがつくる）。"""
    P = places_of(vm)
    ms = moves(vm, before, after)
    up = [m for m in ms if m[3] > 0]
    down = [m for m in ms if m[3] < 0]
    c1, c2 = before.get("C", 0), after.get("C", 0)
    if not up and not down:
        return "①と②で、三つの角へのちらばりは変わらなかった。" + (f"（真ん中 {c1}→{c2}人）" if c1 != c2 else "")
    nm = lambda m: f"{P[m[0]]['name']} {fmt(m[1])}→{fmt(m[2])}人"
    if up and down:
        return f"読みが {'・'.join(P[m[0]]['name'] for m in down)} から {'・'.join(P[m[0]]['name'] for m in up)} のほうへ動いた（{'、'.join(nm(m) for m in down + up)}）。"
    return f"{'・'.join(nm(m) for m in (up or down))}。" + (f"真ん中 {c1}→{c2}人。" if c1 != c2 else "")


KANSUJI = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def changes(vm, before, after):
    """変わったところ：[(名前, 差)]（三つの角＝あいだは0.5人ずつ、と 真ん中）。"""
    P = places_of(vm)
    out = [(P[c]["name"], d) for c, a, b, d in moves(vm, before, after) if d]
    center = next((c for c, p in P.items() if p["kind"] == "center"), None)
    if center and after.get(center, 0) != before.get(center, 0):
        out.append((P[center]["name"], after.get(center, 0) - before.get(center, 0)))
    return out


def check_move(out, vm, before, after):
    """AIの1行が、本当の人数の動きと合っているか。合っていなければ、そのわけ。
    変わった場所ごとに「名前 … 数 … 増／減」が そろっているかを、プログラムで確かめる。"""
    if not out:
        return "からっぽ"
    if len(sentences(out)) > 1 or len(out) > 80:
        return "1行をこえた"
    if any(w in out for w in ("正しい", "正解", "まちがい", "間違い")):
        return "どの読みが正しいかを言った"
    ch = changes(vm, before, after)
    names = sorted({p["name"] for p in vm["places"] if p["kind"] in ("corner", "center")}, key=len, reverse=True)
    spots = sorted((m.start(), n) for n in names for m in re.finditer(re.escape(n), out))
    spots = [x for k, x in enumerate(spots) if not any(x[0] > y[0] and x[0] < y[0] + len(y[1]) for y in spots[:k])]
    seg = {}
    for k, (pos, n) in enumerate(spots):   # 名前のうしろ、つぎの名前までが、その場所のこと
        seg.setdefault(n, "")
        seg[n] += out[pos + len(n): spots[k + 1][0] if k + 1 < len(spots) else len(out)]
    for name, d in ch:
        t = seg.get(name)
        if t is None:
            return f"「{name}」が入っていない"
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)] + [KANSUJI[x] for x in re.findall(r"([一二三四五六七八九十])人", t)]
        if abs(d) not in nums:
            return f"「{name}」の人数がちがう"
        if ("増" if d > 0 else "減") not in t:
            return f"「{name}」の増え方・減り方がちがう"
    unchanged = [n for n in names if n in seg and n not in dict(ch)]
    if any(re.search(r"[増減]", seg[n]) and not re.search(r"変わら", seg[n]) for n in unchanged):
        return "変わっていない場所が動いたと言った"
    return None


# ---------- 三角形のマップ（SVG） ----------
def spots(vm):
    corners = [p for p in vm["places"] if p["kind"] == "corner"]
    xy = {}
    for p, v in zip(corners, [(150, 62), (46, 226), (254, 226)]):
        xy[p["code"]] = v
    for p in vm["places"]:
        if p["kind"] == "center":
            xy[p["code"]] = (150, 171)
        if p["kind"] == "between":
            a, b = (xy[c] for c in p["parts"])
            xy[p["code"]] = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return xy


def triangle_svg(vm, counts, width=300):
    from html import escape
    xy, corners = spots(vm), [p for p in vm["places"] if p["kind"] == "corner"]
    color = {"corner": "#14a9ee", "center": "#8f7bff", "between": "#ff6fae"}
    tri = " ".join(f"{xy[p['code']][0]},{xy[p['code']][1]}" for p in corners)
    label = "".join(f'<text x="{xy[p["code"]][0]}" y="{16 if i == 0 else 290}" text-anchor="middle" font-size="15" font-weight="900" fill="#1b2a4a">{escape(p["name"])}</text>'
                    for i, p in enumerate(corners))
    dots = ""
    for p in vm["places"]:
        n = int(counts.get(p["code"], 0) or 0)
        x, y = xy[p["code"]]
        r = 13 + 6 * n ** 0.5 if n else 6
        faint = "" if n else ' fill-opacity="0.25"'
        dots += f'<circle cx="{x}" cy="{y}" r="{r:.1f}" fill="{color[p["kind"]]}"{faint}/>'
        if n:
            dots += f'<text x="{x}" y="{y + 6}" text-anchor="middle" font-size="17" font-weight="900" fill="#fff">{n}</text>'
    return (f'<svg viewBox="0 -6 300 304" width="{width}" style="max-width:100%;height:auto;font-family:sans-serif" role="img">'
            f'<polygon points="{tri}" fill="rgba(20,169,238,.06)" stroke="#b9dff5" stroke-width="3" stroke-linejoin="round"/>{label}{dots}</svg>')
