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


# ---------- Canva のバリューマップの絵の上に、人数の丸を重ねる ----------
def load_layout(vm, name="海の命"):
    """絵と、丸を出す場所（data/<教材>_マップ.json）。なければ None（三角形の絵を使う）。"""
    path = os.path.join(HERE, "data", f"{name}_マップ.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        lay = json.load(f)
    import base64
    for key in ("image", "image_small"):
        with open(os.path.join(HERE, "data", lay[key]), "rb") as f:
            lay[key + "_b64"] = base64.b64encode(f.read()).decode()
    with open(os.path.join(HERE, "data", lay["image"]), "rb") as f:
        lay["image_bytes"] = f.read()
    lay["pieces"] = {}   # 太一のこま（①1〜8・②1〜8）の絵：まとめたファイル（data/<教材>_こま.json）があれば、それを使う
    bundle = os.path.join(HERE, "data", f"{name}_こま.json")
    if os.path.exists(bundle):
        with open(bundle, encoding="utf-8") as f:
            for key, b64 in json.load(f).items():
                if key.startswith("face_"):   # 番号のない太一の顔（会場ぜんたいの人数に使う）
                    lay["pieces"][key] = b64
                elif not key.startswith("_"):
                    rnd, no = (int(x) for x in key.split("_"))
                    lay["pieces"][(rnd, no)] = base64.b64decode(b64)
                    lay["pieces"][key] = b64
    for rnd in (1, 2) if not lay["pieces"] else ():
        for no in range(1, 9):
            path = os.path.join(HERE, "data", "pieces", f"p{rnd}_{no}.png")
            if os.path.exists(path):
                with open(path, "rb") as f:
                    lay["pieces"][(rnd, no)] = f.read()
                    lay["pieces"][f"{rnd}_{no}"] = base64.b64encode(lay["pieces"][(rnd, no)]).decode()
    lay["place_names"] = {c: short(vm, c) for c in places_of(vm)}
    return lay


SPREAD = [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)]


def map_html(vm, lay, counts, small=False, mark="", pieces=None, rnd=1, ghost=None, positions=None, ghost_positions=None, words=None):
    """絵の上に、場所ごとの人数を丸で出す（mark は左上の小さな文字。①・②など）。
    pieces（{番号: 場所}）をわたすと、丸のかわりに 太一のこま を その場所に置いて見せる。"""
    if not lay:
        return triangle_svg(vm, counts, 220 if small else 360)
    W, H = lay["size"]
    if pieces and lay.get("pieces"):
        # ghost（①のこま）をわたすと、②の地図に うすく重ねる（Canva のボードと同じように、①から②への動きが1枚で見える）
        layers = ([(ghost, 1, 0.45, 2.2)] if ghost else []) + [(pieces, rnd, 1, -2.2 if ghost else 0)]
        imgs = ""
        pw, gap = (11.5, 10.5) if small else (6.6, 6.2)   # 小さい地図では、こまを大きめに
        if positions is not None:   # 置いた場所そのまま（一人一台で動かしたとき）
            layers = []
            for pp, r, alpha in ([(ghost_positions, 1, 0.45)] if ghost_positions else []) + [(positions, rnd, 1)]:
                for no, (x, y) in (pp or {}).items():
                    b64 = lay["pieces"].get(f"{r}_{no}")
                    if b64:
                        imgs += (f'<img src="data:image/png;base64,{b64}" style="position:absolute;left:{x / W * 100:.2f}%;top:{y / H * 100:.2f}%;'
                                 f'width:{pw}cqw;transform:translate(-50%,-50%);opacity:{alpha};filter:drop-shadow(0 0.4cqw 0.8cqw rgba(0,0,0,.5))">')
                    w = (words or {}).get(str(no), "").strip() if r == 1 and alpha == 1 else ""
                    if w:   # 根拠の言葉の吹き出し（机の画面と同じ）
                        from html import escape
                        right = x > W * 0.6   # 右のほうのこまは、吹き出しを左に（地図の外で切れないように）
                        side = (f"right:calc({100 - x / W * 100:.2f}% + {pw * 0.38:.1f}cqw)" if right else f"left:calc({x / W * 100:.2f}% + {pw * 0.38:.1f}cqw)")
                        imgs += (f'<div style="position:absolute;{side};top:calc({y / H * 100:.2f}% - {pw * 0.36:.1f}cqw);'
                                 f'transform:translateY(-100%);max-width:{30 if small else 24}cqw;width:max-content;padding:0.5cqw 1cqw;border-radius:1.2cqw 1.2cqw 1.2cqw 0.2cqw;'
                                 f'background:#fff8dc;color:#14254a;font-size:max(8px,{2.6 if small else 1.7}cqw);font-weight:800;line-height:1.35;'
                                 f'box-shadow:0 0.4cqw 1cqw rgba(0,0,0,.35);word-break:break-all">「{escape(w)}」</div>')
        for pcs, r, alpha, shift in layers:
            by_place = {}
            for no, place in sorted(pcs.items(), key=lambda x: int(x[0])):
                if place:
                    by_place.setdefault(place, []).append(int(no))
            for place, nos in by_place.items():
                x, y = lay["anchors"][place]
                for k, no in enumerate(nos):
                    dx, dy = SPREAD[k % len(SPREAD)]
                    b64 = lay["pieces"].get(f"{r}_{no}")
                    if b64:
                        imgs += (f'<img src="data:image/png;base64,{b64}" style="position:absolute;left:calc({x / W * 100:.2f}% + {dx * gap + shift * gap / 6.2:.1f}cqw);'
                                 f'top:calc({y / H * 100:.2f}% + {dy * gap:.1f}cqw);width:{pw}cqw;transform:translate(-50%,-50%);opacity:{alpha};'
                                 f'filter:drop-shadow(0 0.4cqw 0.8cqw rgba(0,0,0,.5))">')
        tag = f'<div style="position:absolute;left:8px;top:6px;color:#ffd54a;font-weight:900">{mark}</div>' if mark else ""
        return (f'<div style="position:relative;width:100%;container-type:inline-size;border-radius:18px;overflow:hidden;line-height:1">'
                f'<img src="data:image/jpeg;base64,{lay["image_b64"]}" style="width:100%;display:block">{tag}{imgs}</div>')
    color = {"corner": "#ffd54a", "center": "#8fdcff", "between": "#ff9ccb"}
    dots = ""
    face = (lay.get("pieces") or {}).get(f"face_{rnd}")
    for p in vm["places"]:
        n = int(counts.get(p["code"], 0) or 0)
        if not n:
            continue
        x, y = lay["anchors"][p["code"]]
        if face:   # 太一の顔の大きさで人数を見せ、右下に人数の数字
            size = 8.0 + 3.0 * n ** 0.5
            dots += (f'<div style="position:absolute;left:{x / W * 100:.2f}%;top:{y / H * 100:.2f}%;width:{size:.1f}cqw;height:{size:.1f}cqw;transform:translate(-50%,-50%)">'
                     f'<img src="data:image/png;base64,{face}" style="width:100%;filter:drop-shadow(0 0.5cqw 1cqw rgba(0,0,0,.5))">'
                     f'<span style="position:absolute;right:-0.6cqw;bottom:-0.6cqw;min-width:3.6cqw;height:3.6cqw;padding:0 0.6cqw;border-radius:2cqw;'
                     f'background:{"#ffd54a" if rnd == 2 else "#fff"};color:#14254a;font-weight:900;font-size:max(9px,2.6cqw);display:flex;'
                     f'align-items:center;justify-content:center;box-shadow:0 0 0 0.3cqw #14254a">{n}</span></div>')
            continue
        size = 4.2 + 2.0 * n ** 0.5   # 地図の横はばに対する割合（大きい地図でも小さい地図でも同じ見え方）
        dots += (f'<div style="position:absolute;left:{x / W * 100:.2f}%;top:{y / H * 100:.2f}%;width:{size:.1f}cqw;height:{size:.1f}cqw;'
                 f'transform:translate(-50%,-50%);border-radius:50%;background:{color[p["kind"]]};color:#14254a;display:flex;'
                 f'align-items:center;justify-content:center;font-weight:900;font-size:max(10px,{size * 0.5:.1f}cqw);'
                 f'box-shadow:0 0 0 0.35cqw rgba(255,255,255,.9),0 0.6cqw 1.6cqw rgba(0,0,0,.35)">{n}</div>')
    img = lay["image_small_b64" if small else "image_b64"]
    tag = f'<div style="position:absolute;left:8px;top:6px;color:#ffd54a;font-weight:900">{mark}</div>' if mark else ""
    return (f'<div style="position:relative;width:100%;container-type:inline-size;border-radius:{10 if small else 18}px;overflow:hidden;line-height:1">'
            f'<img src="data:image/jpeg;base64,{img}" style="width:100%;display:block">{tag}{dots}</div>')


def where(lay, x, y):
    """ボードの上の位置（写真の左上0・右下1000）が、どの場所か。AIではなく、Y字の線の形で決める。
    右がわの置き場（まだ置いていない こま）なら None。"""
    W, H = lay["board"]["size"]
    return where_px(lay, x / 1000 * W, y / 1000 * H)


def where_px(lay, px, py):
    """地図の上の位置（ボードの左上が0。1920×1080 のボードでの点）が、どの場所か。地図の外なら None。"""
    import math
    b = lay["board"]
    if px < 0 or py < 0 or px > b["map_width"] or py > b["size"][1]:
        return None
    cx, cy = b["center"]
    if math.hypot(px - cx, py - cy) <= b["radius"]:
        return "C"
    for code, (ex, ey) in b["lines"].items():   # 線の上・そば
        dx, dy = ex - cx, ey - cy
        t = max(0, min(1, ((px - cx) * dx + (py - cy) * dy) / (dx * dx + dy * dy)))
        if math.hypot(px - (cx + t * dx), py - (cy + t * dy)) <= b["near"]:
            return code
    ang = lambda ex, ey: math.atan2(ey - cy, ex - cx) % (2 * math.pi)
    a = ang(px, py)
    lines = sorted(((ang(*e), code) for code, e in b["lines"].items()))
    for i, (a1, c1) in enumerate(lines):   # となりあう2本の線のあいだ ＝ 2本に共通の角
        a2, c2 = lines[(i + 1) % len(lines)]
        inside = a1 <= a < a2 if a1 < a2 else (a >= a1 or a < a2)
        if inside:
            common = set(c1) & set(c2)
            return common.pop() if common else None
    return None


def crop_board(data):
    """スクリーンショットのまわり（Canva の白いわくなど）を切って、紺のボードだけにする。見つからなければ そのまま。"""
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(data)).convert("RGB")
        small = im.copy()
        small.thumbnail((400, 400))
        r, g, b = small.split()
        navy = Image.eval(Image.merge("RGB", (r, g, b)).convert("HSV").split()[0], lambda h: 255 if 150 <= h <= 180 else 0)   # 青っぽい色
        dark = Image.eval(small.convert("L"), lambda v: 255 if v < 90 else 0)
        from PIL import ImageChops
        box = ImageChops.multiply(navy, dark).getbbox()
        if not box:
            return data
        k = im.width / small.width
        x0, y0, x1, y1 = (int(v * k) for v in box)
        if (x1 - x0) * (y1 - y0) < 0.4 * im.width * im.height:
            return data
        buf = io.BytesIO()
        im.crop((x0, y0, x1, y1)).save(buf, "JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return data


def prepare_photo(data, lay):
    """写真を読む前に：紺のボードだけを切り出し、もとのボードの大きさ（1920×1080）にそろえる（小さいと読みまちがえる）。"""
    from PIL import Image
    import io
    cut = crop_board(data)
    im = Image.open(io.BytesIO(cut)).convert("RGB")
    W, H = (lay or {}).get("board", {}).get("size", (1920, 1080))
    if abs(im.width / im.height - W / H) < 0.12:
        im = im.resize((W, H), Image.LANCZOS)
    else:
        im.thumbnail((2048, 2048))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def pieces_of(lay, pos):
    """{番号: [x, y]}（地図の上の位置）→ {番号: 場所}。場所は線の形でプログラムが決める。"""
    out = {}
    for no, xy in (pos or {}).items():
        place = where_px(lay, xy[0], xy[1]) if xy else None
        if place:
            out[int(no)] = place
    return out


def photo_positions(data, lay):
    """写真から読んだ こま を、①②それぞれ {番号: [x, y]}（地図の上の位置）にする。"""
    W, H = lay["board"]["size"]
    out = {1: {}, 2: {}}
    for x in (data or {}).get("pieces") or []:
        try:
            rnd, no, px, py = int(x["round"]), int(x["no"]), float(x["x"]) / 1000 * W, float(x["y"]) / 1000 * H
        except (TypeError, ValueError, KeyError):
            continue
        if rnd in (1, 2) and 1 <= no <= 8 and str(no) not in out[rnd] and where_px(lay, px, py):
            out[rnd][str(no)] = [round(px), round(py)]
    return out[1], out[2]


def counts_of(pieces):
    """{番号: 場所} → {場所: 人数}"""
    out = {}
    for place in (pieces or {}).values():
        if place:
            out[place] = out.get(place, 0) + 1
    return out


def photo_places(vm, data, lay):
    """写真から読んだ こま を、①②それぞれ {番号: 場所} にする（場所は線の形でプログラムが決める）。"""
    P = places_of(vm)
    out = {1: {}, 2: {}}
    for x in (data or {}).get("pieces") or []:
        try:
            rnd, no = int(x.get("round")), int(x.get("no"))
            place = where(lay, float(x["x"]), float(x["y"])) if lay and lay.get("board") else str(x.get("place"))
        except (TypeError, ValueError, KeyError):
            continue
        if rnd in (1, 2) and 1 <= no <= 8 and place in P and no not in out[rnd]:
            out[rnd][no] = place
    return out[1], out[2]


def from_pieces(vm, data, lay=None):
    """写真から読んだ こま を、①②の人数と根拠の言葉にする（読めないものは すてる）。
    位置（x, y）があれば、場所はプログラムが線の形で決める。"""
    P = places_of(vm)
    seen, counts, places = set(), {1: {}, 2: {}}, {1: {}, 2: {}}
    for x in (data or {}).get("pieces") or []:
        try:
            rnd, no = int(x.get("round")), int(x.get("no"))
            if lay and lay.get("board") and x.get("x") is not None and x.get("y") is not None:
                place = where(lay, float(x["x"]), float(x["y"]))
                if place is None:
                    continue
            else:
                place = str(x.get("place"))
        except (TypeError, ValueError):
            continue
        if rnd not in (1, 2) or not 1 <= no <= 8 or place not in P or (rnd, no) in seen:
            continue
        seen.add((rnd, no))
        counts[rnd][place] = counts[rnd].get(place, 0) + 1
        places[rnd][no] = place
    words = []
    for w in (data or {}).get("words") or []:
        try:
            no, word = int(w.get("no")), str(w.get("word") or "").strip()[:40]
        except (TypeError, ValueError):
            continue
        if word and 1 <= no <= 8 and no in places[1]:
            words.append({"no": no, "place": places[1][no], "word": word})
    return counts[1], counts[2], words


# ---------- 壁打ち ----------
def wall_system(vm, question, counts, evidence):
    """壁打ちのAIへの指示（設計メモの「AIに守らせる決まり」＋ この机のようす）。"""
    P = places_of(vm)
    where = "、".join(f"{short(vm, c)} {n}人" for c, n in counts.items() if n)
    words = "、".join(f"{e['no']}番「{e['word']}」（{short(vm, e['place'])}）" for e in evidence) or "なし"
    rules = [r for r in vm["ai_rules"] if "6年生" not in r] + [
        "参加者は、物語の読みを話し合っている先生たちです。机のみんなの考えを深めるための壁打ち相手になってください。",
        "答えや「正しい位置」は言わず、根拠になる言葉や、ほかの角から見たときの見え方を問い返してください。",
        f"この机の問い：{question}", f"この机の人数：{where}", f"この机が入れた根拠の言葉：{words}"]
    return "\n".join(rules)


def check_wall(out):
    """壁打ちの返事：正しさを言わない・2文まで（長ければ2文で切る）。"""
    if not out:
        return None
    if any(w in out for w in ("正解は", "正しいのは", "答えは")):
        return None
    return "".join(sentences(out)[:2]) or out[:120]


# ---------- この机へのひとこと（叙述にもどる手がかり） ----------
def hint_context(vm, pieces, evidence):
    """この机で考えが分かれているところと、読みなおす場面（設計メモの場面の表から、プログラムが選ぶ）。
    pieces: {番号: 場所}。本文は使わない（研究会用の Gemini には本文を送らないため）。"""
    P = places_of(vm)
    pieces = {int(k): v for k, v in (pieces or {}).items() if v in P}
    counts = counts_of(pieces)
    w = weights(vm, counts)
    corners = [c for c in sorted(w, key=lambda c: -w[c]) if w[c] > 0]
    # 分かれ目の2人：いちばん多い角の人と、つぎに多い角（なければ ちがう場所）の人
    pair = None
    if pieces:
        main = corners[0] if corners else None
        a = next((n for n, p in sorted(pieces.items()) if p == main), None) or min(pieces)
        others = [n for n, p in sorted(pieces.items()) if p != pieces[a]]
        if len(corners) > 1:
            b = next((n for n in others if corners[1] in P[pieces[n]]["parts"] or pieces[n] == corners[1]), None)
        else:
            b = others[0] if others else None
        if b:
            pair = (a, pieces[a], b, pieces[b])
    # 読みなおす場面：分かれている角に いちばん多く関係する場面（同じなら、人数の少ない角に関係する場面を先に）
    involved = set(corners[:2]) or set(c for c, p in P.items() if p["kind"] == "corner")
    minority = corners[1] if len(corners) > 1 else None
    def score(s):
        cs = set(s["corners"])
        return (len(cs & involved), minority in cs, bool(s.get("page")))
    scene = max(vm.get("scenes") or [None], key=lambda s: score(s) if s else (0,)) if vm.get("scenes") else None
    ev = {int(e["no"]): e["word"] for e in evidence or [] if e.get("word")}
    name = lambda c: short(vm, c)
    who = lambda n: f"{n}番は" + (f"「{ev[n]}」から" if n in ev else "")
    if pair:   # 机が入れた根拠の言葉（叙述）があれば、それも入れる
        head = f"{who(pair[0])}{name(pair[1])}、{who(pair[2])}{name(pair[3])}に置いた。"
        tail = "2人の分かれ目になった言葉をさがそう。"
    else:
        only = next(iter(pieces.values()), None)
        head = f"みんなが{name(only)}に置いた。" if only else ""
        tail = "そこに置いた決め手の言葉を、一人ずつ指さそう。"
    where_ = f"{scene['page'] + 'の' if scene and scene.get('page') else ''}「{scene['scene']}」場面を読みなおして、" if scene else "本文を読みなおして、"
    keep = ([f"{pair[0]}番", f"{pair[2]}番"] if pair else []) + ([scene["scene"]] if scene else []) + [ev[n] for n in (pair[0], pair[2]) if n in ev] if pair else ([scene["scene"]] if scene else [])
    return {"pair": pair, "scene": scene, "words": list(ev.values()), "fallback": head + where_ + tail, "keep": keep,
            "numbers": sorted(pieces), "names": sorted({name(p) for p in pieces.values()} | {P[c]["name"] for c in P})}

