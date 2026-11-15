"""AIを呼ぶところ（ここだけを差し替える）。

  研究会（Streamlit Community Cloud）… AI_PROVIDER = "gemini"（APIキーは Streamlit の Secrets）
  教室（Mac mini）……………………………… AI_PROVIDER = "ollama"（Mac の中のAI。外には何も送らない）

AIに送るのは、表の問い（波かっこつき）・机の人数・参加者が入れた短い言葉だけ。教科書の本文は送らない。
決められた秒数で答えなければ AiTimeout。呼ぶ側は、そのとき表の文（またはプログラムの1行）を出す。
"""
import json
import os
import threading
import urllib.request


class AiError(Exception):
    pass


def setting(key, default=""):
    """設定は Streamlit の Secrets → 環境変数 の順に読む（キーをプログラムに書かないため）。"""
    try:
        import streamlit as st
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key, default)


def provider():
    return setting("AI_PROVIDER", "gemini").lower()


def _gemini(system, user):
    from google import genai
    from google.genai import types
    key = setting("GEMINI_API_KEY")
    if not key:
        raise AiError("GEMINI_API_KEY が Secrets にありません")
    client = genai.Client(api_key=key)
    cfg = dict(system_instruction=system, temperature=0.3, max_output_tokens=300)
    try:   # 考えこむ時間を0にして、速く答えさせる（使えないモデルなら、つけずに聞く）
        res = client.models.generate_content(model=setting("GEMINI_MODEL", "gemini-flash-latest"), contents=user,
                                             config=types.GenerateContentConfig(**cfg, thinking_config=types.ThinkingConfig(thinking_budget=0)))
    except Exception as e:
        if "thinking" not in str(e).lower():
            raise
        res = client.models.generate_content(model=setting("GEMINI_MODEL", "gemini-flash-latest"), contents=user,
                                             config=types.GenerateContentConfig(**cfg))
    return res.text or ""


def _ollama(system, user, timeout):
    url = setting("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/chat"
    payload = {"model": setting("OLLAMA_MODEL", "qwen3.6:35b"), "stream": False, "think": False, "keep_alive": "60m",
               "options": {"temperature": 0.3, "num_predict": 200},
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)["message"]["content"]


def ask(system, user, timeout=8):
    """1回聞く。timeout 秒で答えなければ AiError。"""
    box = {}

    def work():
        try:
            box["text"] = _gemini(system, user) if provider() == "gemini" else _ollama(system, user, timeout)
        except Exception as e:
            box["error"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise AiError(f"{timeout}秒で返事がなかった")
    if "error" in box:
        raise AiError(f"AIにつながらない（{type(box['error']).__name__}）")
    lines = [x.strip() for x in (box.get("text") or "").strip().splitlines() if x.strip()]
    out = lines[0] if lines else ""
    if out.startswith("「") and out.endswith("」") and out.count("「") == 1:
        out = out[1:-1]
    return out


# ---------- 2つの使い方 ----------
def polish_question(vm, template, values):
    """Q9・Q10：波かっこのついた問いと、入れるものを渡して整えてもらう（設計メモの決まり2）。"""
    user = ("次の問いの波かっこに、下の番号や言葉を入れて、読みやすい問いにしてください。問いの文だけを返してください。\n"
            f"問い：{template}\n" + "\n".join(f"{{{k}}} → {v}" for k, v in values.items()))
    return ask("\n".join(vm["ai_rules"]), user, vm.get("ai_timeout", 8))


def describe_move(vm, before, after, names, diff=""):
    """①（話し合いの前）から②（話し合いの後）への動きを1行で。diff は、プログラムが計算した角ごとの変化。"""
    row = lambda c: "、".join(f"{names[k]} {v}人" for k, v in c.items() if v) or "なし"
    system = "\n".join(vm["ai_rules"][:1] + [
        "机のみんなが、物語の中心人物を三つの角のどこに置いたかの人数が、話し合いの前（①）と後（②）で渡されます。",
        "人数がどう動いたかを、1文で書いてください。60文字以内。",
        "人数が変わった場所だけを、「〇〇が□人増え」「〇〇が□人減った」の形で書いてください。数は、渡された変化のとおりにします。",
        "どの読みが正しいか、どこに置くべきかは言ってはいけません。本文の言葉も入れません。ほめ言葉や前置きは入れません。",
        "動いた角の名前を、渡されたとおりに使ってください。"])
    user = f"①（話し合いの前）：{row(before)}\n②（話し合いの後）：{row(after)}" + (f"\n変化（あいだは0.5人ずつ両方の角に数える）：{diff}\nこの変化とくいちがうことは書かないでください。" if diff else "")
    return ask(system, user, vm.get("ai_timeout", 8))
