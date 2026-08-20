
import os
import json
from datetime import date, datetime
from flask import Flask, render_template, request, jsonify
from supabase import create_client, Client
from openai import OpenAI

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")

supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

client = OpenAI(
    api_key=OPENAI_API_KEY,
    timeout=150.0,
    max_retries=0
) if OPENAI_API_KEY else None

MEAL_ORDER = {"朝食": 1, "昼食": 2, "夕飯": 3, "夜食": 4, "間食": 5}
EXERCISES = ["腹筋", "腹斜筋", "スクワット", "ランニング", "ジム", "パーソナル"]


def ensure_db():
    if not supabase:
        raise RuntimeError("Supabaseの環境変数が設定されていません。")


def safe_rows(resp):
    return getattr(resp, "data", None) or []


def _shorten(text, limit):
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[:max(0, limit - 1)] + "…"


def build_tweet_text(selected_date, weight, meals, exercises, soreness):
    """Build a compact daily summary within 140 chars including fixed hashtag."""
    hashtag = "#じゃない方ダイエット"

    try:
        d = datetime.strptime(selected_date, "%Y-%m-%d")
        date_label = f"{d.month}/{d.day}"
    except Exception:
        date_label = selected_date

    meal_labels = {"朝食": "朝", "昼食": "昼", "夕飯": "夜", "間食": "間", "夜食": "夜食"}
    lines = [date_label]

    if weight not in (None, ""):
        lines.append(f"⚖️{weight}kg")

    grouped = {}
    for m in meals or []:
        meal_type = m.get("meal_type") or ""
        meal_text = (m.get("meal_text") or "").strip()
        if meal_text:
            grouped.setdefault(meal_type, []).append(meal_text)

    for meal_type in ["朝食", "昼食", "夕飯", "間食", "夜食"]:
        vals = grouped.get(meal_type)
        if vals:
            lines.append(f"{meal_labels[meal_type]}:{'・'.join(vals)}")

    ex_texts = []
    for e in exercises or []:
        name = (e.get("exercise_type") or "").strip()
        memo = (e.get("memo") or "").strip()
        amount = e.get("amount")
        unit = (e.get("unit") or ("分" if name == "ランニング" else "回")).strip()

        if name:
            amount_text = f"{amount}{unit}" if amount not in (None, "") else ""
            detail = "".join([
                f" {amount_text}" if amount_text else "",
                f" {memo}" if memo else ""
            ])
            ex_texts.append(name + detail)

    if ex_texts:
        lines.append("🏃" + "・".join(ex_texts))

    sore_names = [(s.get("muscle_name") or "").strip() for s in (soreness or [])]
    sore_names = [x for x in sore_names if x]
    if sore_names:
        lines.append("💪" + "・".join(sore_names))

    def with_tag(body_lines):
        body = "\n".join(body_lines).rstrip()
        return f"{body}\n\n{hashtag}"

    text = with_tag(lines)
    if len(text) <= 140:
        return text

    compact = [date_label]

    if weight not in (None, ""):
        compact.append(f"⚖️{weight}kg")

    for meal_type in ["朝食", "昼食", "夕飯", "間食", "夜食"]:
        vals = grouped.get(meal_type)
        if vals:
            compact.append(f"{meal_labels[meal_type]}:{_shorten('・'.join(vals), 14)}")

    if ex_texts:
        compact.append("🏃" + _shorten("・".join(ex_texts), 18))

    if sore_names:
        compact.append("💪" + _shorten("・".join(sore_names), 16))

    text = with_tag(compact)
    if len(text) <= 140:
        return text

    suffix = f"\n\n{hashtag}"
    body_limit = 140 - len(suffix)
    body = "\n".join(compact)

    if len(body) > body_limit:
        body = body[:max(0, body_limit - 1)] + "…"

    return body + suffix

@app.route("/")
def index():
    selected_date = request.args.get("date") or date.today().isoformat()
    return render_template(
        "index.html",
        selected_date=selected_date,
        meal_types=list(MEAL_ORDER.keys()),
        exercises=EXERCISES,
    )


@app.get("/api/day/<selected_date>")
def get_day(selected_date):
    ensure_db()

    daily = safe_rows(
        supabase.table("daily_logs").select("*").eq("log_date", selected_date).limit(1).execute()
    )
    meals = safe_rows(
        supabase.table("meal_logs").select("*").eq("log_date", selected_date).execute()
    )
    exercises = safe_rows(
        supabase.table("exercise_logs").select("*").eq("log_date", selected_date).execute()
    )
    soreness = safe_rows(
        supabase.table("muscle_soreness_logs").select("*").eq("log_date", selected_date).execute()
    )

    meals.sort(key=lambda r: (MEAL_ORDER.get(r.get("meal_type", ""), 99), r.get("id", 0)))
    return jsonify({
        "daily": daily[0] if daily else None,
        "meals": meals,
        "exercises": exercises,
        "soreness": soreness
    })


@app.post("/api/day")
def save_day():
    ensure_db()
    payload = request.get_json(force=True)
    selected_date = payload["date"]
    weight = payload.get("weight")
    meals = payload.get("meals", [])
    exercises = payload.get("exercises", [])
    soreness = payload.get("soreness", [])

    # Upsert daily log
    daily_payload = {
        "log_date": selected_date,
        "weight": float(weight) if weight not in (None, "") else None,
        "updated_at": datetime.utcnow().isoformat()
    }
    existing = safe_rows(
        supabase.table("daily_logs").select("id").eq("log_date", selected_date).limit(1).execute()
    )
    if existing:
        supabase.table("daily_logs").update(daily_payload).eq("id", existing[0]["id"]).execute()
    else:
        supabase.table("daily_logs").insert(daily_payload).execute()

    # Replace child rows for this date
    supabase.table("meal_logs").delete().eq("log_date", selected_date).execute()
    supabase.table("exercise_logs").delete().eq("log_date", selected_date).execute()
    supabase.table("muscle_soreness_logs").delete().eq("log_date", selected_date).execute()

    meal_rows = []
    for m in meals:
        text = (m.get("meal_text") or "").strip()
        meal_type = m.get("meal_type") or "朝食"
        vomited = bool(m.get("vomited"))
        if text or vomited:
            meal_rows.append({
                "log_date": selected_date,
                "meal_type": meal_type,
                "meal_text": text,
                "vomited": vomited
            })
    if meal_rows:
        supabase.table("meal_logs").insert(meal_rows).execute()

    exercise_rows = []
    for e in exercises:
        etype = e.get("exercise_type")
        amount = e.get("amount")
        unit = (e.get("unit") or ("分" if etype == "ランニング" else "回")).strip()
        memo = (e.get("memo") or "").strip()

        if etype in EXERCISES:
            try:
                amount_value = int(amount) if amount not in (None, "") else None
            except (TypeError, ValueError):
                amount_value = None

            # 種目だけ選んだ行も保存可能。回数/分は未入力でもOK。
            exercise_rows.append({
                "log_date": selected_date,
                "exercise_type": etype,
                "amount": amount_value,
                "unit": unit,
                "memo": memo
            })

    if exercise_rows:
        supabase.table("exercise_logs").insert(exercise_rows).execute()

    soreness_rows = [
        {"log_date": selected_date, "muscle_name": str(x).strip()}
        for x in soreness if str(x).strip()
    ]
    if soreness_rows:
        supabase.table("muscle_soreness_logs").insert(soreness_rows).execute()

    return jsonify({"ok": True})


@app.post("/api/ai-comment")
def ai_comment():
    ensure_db()
    if not client:
        return jsonify({"error": "OPENAI_API_KEY が設定されていません。"}), 400

    payload = request.get_json(force=True)
    selected_date = payload["date"]

    daily = safe_rows(
        supabase.table("daily_logs").select("*").eq("log_date", selected_date).limit(1).execute()
    )
    meals = safe_rows(
        supabase.table("meal_logs").select("*").eq("log_date", selected_date).execute()
    )
    exercises = safe_rows(
        supabase.table("exercise_logs").select("*").eq("log_date", selected_date).execute()
    )
    soreness = safe_rows(
        supabase.table("muscle_soreness_logs").select("*").eq("log_date", selected_date).execute()
    )

    previous_weight = None
    prev = safe_rows(
        supabase.table("daily_logs")
        .select("weight,log_date")
        .lt("log_date", selected_date)
        .not_.is_("weight", "null")
        .order("log_date", desc=True)
        .limit(1)
        .execute()
    )
    if prev:
        previous_weight = prev[0].get("weight")

    summary = {
        "date": selected_date,
        "weight": daily[0].get("weight") if daily else None,
        "previous_weight": previous_weight,
        "target_weight": 60.0,
        "meals": [
            {
                "type": m.get("meal_type"),
                "food": m.get("meal_text"),
                "vomited": bool(m.get("vomited")),
            }
            for m in meals
        ],
        "exercises": [
            {
                "type": e.get("exercise_type"),
                "amount": e.get("amount"),
                "unit": e.get("unit"),
                "memo": e.get("memo")
            }
            for e in exercises
        ],
        "muscle_soreness": [s.get("muscle_name") for s in soreness],
    }

    system = """
あなたは日々の体重・食事・運動・筋肉痛を見守るキャラクターです。

話し方は、アニメ『イナズマイレブン』の不動明王を思わせる、生意気で偉そう、ぶっきらぼうで挑発的な雰囲気にしてください。
ただし根底では相手のことをちゃんと見ていて、体調や努力を気にかけています。
作品中の実際のセリフを引用・再現せず、独自の言い回しで話してください。

【口調】
・最初から最後まで完全なタメ口。
・敬語は絶対に使わない。
・「〜してください」「〜しましょう」「〜ですよ」「〜ですね」「〜してくださいね」などは禁止。
・「〜だ」「〜だろ」「〜しろ」「〜するな」「〜じゃねえか」「〜ってわけだ」「ったく」などを自然に使う。
・少し偉そうで上から目線。
・軽く煽ったり茶化したりしてもいい。
・ただし罵倒、人格否定、傷つけるような言い方はしない。
・優しさを直接アピールせず、ぶっきらぼうな気遣いとして表現する。
・褒める場合も「偉いね」ではなく「ちゃんとやってんじゃねえか」「悪くねえ」など、このキャラクターらしい言い方にする。
・同じ語尾を連発しない。

【コメント内容】
目標体重は60kg。現在体重が記録されている場合は、60kgまでの差にも自然に触れる。
日本語で300〜500文字程度を目安に、5〜8文程度でコメントする。
短くまとめず、その日の記録をかなり具体的に振り返る。

記録されている内容に応じて、
・今日の体重
・目標体重までの差
・過去の体重記録との変化
・朝食
・昼食
・夕飯
・夜食
・間食
・嘔吐の有無
・運動内容
・運動回数や内容
・筋肉痛の部位
について、記録が存在するものにはできるだけ具体的に触れる。

単に記録を読み上げるだけではなく、
「今日全体としてどうだったか」
「食事のバランス」
「運動と休養のバランス」
「明日どうするとよさそうか」
までコメントする。

体重が増えていても責めない。
体重の数字だけで本人の価値を判断するような発言は絶対にしない。
短期的な体重変化について断定的な評価をしない。

嘔吐の記録がある場合、
「吐いたから摂取カロリーが減った」
「食べた分が帳消しになった」
「体重減少につながる」
など、嘔吐を減量手段として肯定する表現は絶対にしない。

嘔吐がある日は体調面を優先して触れる。
水分を取ることや身体を休めることに触れ、繰り返している場合には医療機関への相談を促す。
ただし、その場合も敬語にはせず、
「水分は切らすな」
「続くなら意地張らず病院行け」
などキャラクターの口調を維持する。

筋肉痛がある部位と、その日の運動で使った部位が重なりそうな場合は、
無理に追い込まず休ませるように言う。

食事については「良い・悪い」だけで終わらせず、
タンパク質、炭水化物、野菜など、記録から読み取れる範囲で具体的に触れる。
記録されていない栄養素や量を勝手に推測しない。

最後は、その日の総評と明日に向けた一言で締める。
説教ではなく「ちゃんと見てるぞ」という雰囲気を残す。
"""

    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=system,
        input=json.dumps(summary, ensure_ascii=False),
        reasoning={"effort": "minimal"},
        max_output_tokens=3000
    )
    comment = (response.output_text or "").strip()

    if not comment:
        try:
            app.logger.warning(
                "OpenAI response had empty output_text. status=%s incomplete_details=%s output=%r",
                getattr(response, "status", None),
                getattr(response, "incomplete_details", None),
                getattr(response, "output", None),
            )
        except Exception:
            app.logger.exception("Failed to log empty OpenAI response diagnostics.")

        comment = "今日はうまくコメントを作れなかった。もう一回保存してみろ。"

    existing = safe_rows(
        supabase.table("daily_logs").select("id").eq("log_date", selected_date).limit(1).execute()
    )
    if existing:
        supabase.table("daily_logs").update({"ai_comment": comment}).eq("id", existing[0]["id"]).execute()
    else:
        supabase.table("daily_logs").insert({
            "log_date": selected_date,
            "ai_comment": comment,
            "updated_at": datetime.utcnow().isoformat()
        }).execute()

    return jsonify({"comment": comment})


@app.get("/api/tweet/<selected_date>")
def get_tweet(selected_date):
    ensure_db()
    rows = safe_rows(
        supabase.table("tweet_logs").select("*").eq("log_date", selected_date).limit(1).execute()
    )
    return jsonify(rows[0] if rows else None)


@app.post("/api/tweet/generate")
def generate_tweet():
    ensure_db()
    payload = request.get_json(force=True)
    selected_date = payload["date"]

    daily = safe_rows(
        supabase.table("daily_logs").select("*").eq("log_date", selected_date).limit(1).execute()
    )
    meals = safe_rows(
        supabase.table("meal_logs").select("*").eq("log_date", selected_date).execute()
    )
    exercises = safe_rows(
        supabase.table("exercise_logs").select("*").eq("log_date", selected_date).execute()
    )
    soreness = safe_rows(
        supabase.table("muscle_soreness_logs").select("*").eq("log_date", selected_date).execute()
    )

    weight = daily[0].get("weight") if daily else None
    tweet_text = build_tweet_text(selected_date, weight, meals, exercises, soreness)

    existing = safe_rows(
        supabase.table("tweet_logs").select("id").eq("log_date", selected_date).limit(1).execute()
    )

    row = {
        "log_date": selected_date,
        "tweet_text": tweet_text,
        "updated_at": datetime.utcnow().isoformat()
    }

    if existing:
        supabase.table("tweet_logs").update(row).eq("id", existing[0]["id"]).execute()
    else:
        supabase.table("tweet_logs").insert(row).execute()

    return jsonify({"tweet_text": tweet_text, "count": len(tweet_text)})


@app.post("/api/tweet/save")
def save_tweet():
    ensure_db()
    payload = request.get_json(force=True)
    selected_date = payload["date"]
    tweet_text = (payload.get("tweet_text") or "").strip()
    hashtag = "#じゃない方ダイエット"

    if hashtag not in tweet_text:
        tweet_text = tweet_text.rstrip() + f"\n\n{hashtag}"
    elif not tweet_text.rstrip().endswith(hashtag):
        tweet_text = tweet_text.replace(hashtag, "").rstrip() + f"\n\n{hashtag}"

    if len(tweet_text) > 140:
        suffix = f"\n\n{hashtag}"
        body = tweet_text[:-len(suffix)].rstrip()
        body_limit = 140 - len(suffix)

        if len(body) > body_limit:
            body = body[:max(0, body_limit - 1)] + "…"

        tweet_text = body + suffix

    existing = safe_rows(
        supabase.table("tweet_logs").select("id").eq("log_date", selected_date).limit(1).execute()
    )

    row = {
        "log_date": selected_date,
        "tweet_text": tweet_text,
        "updated_at": datetime.utcnow().isoformat()
    }

    if existing:
        supabase.table("tweet_logs").update(row).eq("id", existing[0]["id"]).execute()
    else:
        supabase.table("tweet_logs").insert(row).execute()

    return jsonify({"ok": True, "count": len(tweet_text), "tweet_text": tweet_text})

@app.get("/api/tweets")
def list_tweets():
    ensure_db()
    rows = safe_rows(
        supabase.table("tweet_logs")
        .select("log_date,tweet_text,updated_at")
        .order("log_date", desc=True)
        .limit(90)
        .execute()
    )
    return jsonify(rows)


@app.get("/api/history")
def history():
    ensure_db()
    rows = safe_rows(
        supabase.table("daily_logs")
        .select("log_date,weight,ai_comment")
        .order("log_date", desc=True)
        .limit(60)
        .execute()
    )
    return jsonify(rows)


@app.get("/api/weights")
def weights():
    ensure_db()
    rows = safe_rows(
        supabase.table("daily_logs")
        .select("log_date,weight")
        .not_.is_("weight", "null")
        .order("log_date")
        .limit(365)
        .execute()
    )
    return jsonify(rows)


@app.get("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    app.run(debug=True)
