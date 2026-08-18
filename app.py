
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
EXERCISES = ["腹筋", "腹斜筋", "スクワット", "ジム", "パーソナル"]


def ensure_db():
    if not supabase:
        raise RuntimeError("Supabaseの環境変数が設定されていません。")


def safe_rows(resp):
    return getattr(resp, "data", None) or []


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
        if etype in EXERCISES and e.get("done"):
            exercise_rows.append({
                "log_date": selected_date,
                "exercise_type": etype,
                "memo": (e.get("memo") or "").strip()
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
        "exercises": [e.get("exercise_type") for e in exercises],
        "exercise_memos": [e.get("memo") for e in exercises if e.get("memo")],
        "muscle_soreness": [s.get("muscle_name") for s in soreness],
    }

    system = """
あなたは日々の体重・食事・運動・筋肉痛を見守るキャラクターです。

話し方は、アニメ『イナズマイレブン』の不動明王を思わせる、生意気で偉そう、ぶっきらぼうで挑発的な雰囲気にしてください。
ただし根底では相手のことをちゃんと見ていて、体調や努力を気にかけています。
作品中の実際のセリフを引用・再現せず、独自の言い回しで話してください。

【口調】
・最初から最後まで完全な強めのタメ口。
・敬語は絶対に使わない。
・「〜してください」「〜しましょう」「〜ですよ」「〜ですね」「〜してくださいね」「～なので」などは禁止。
・「〜だ」「〜だろ」「〜しろ」「〜するな」「〜じゃねえか」「〜ってわけだ」「ったく」などを自然に使う。
・少し偉そうで上から目線。
・軽く煽ったり茶化したりしてもいい。
・ただし罵倒、人格否定、傷つけるような言い方はしない。
・優しさを直接アピールせず、ぶっきらぼうな気遣いとして表現する。
・褒める場合も「偉いね」ではなく「ちゃんとやってんじゃねえか」「悪くねえ」など、このキャラクターらしい言い方にする。
・同じ語尾を連発しない。
・嘔吐についてはあまり触れない

【コメント内容】
目標体重は60kg。現在体重が記録されている場合は、60kgまでの差にも自然に触れる。
日本語で300〜500文字程度を目安に、5〜10文程度でコメントする。
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
        max_output_tokens=1800
    )
    comment = (response.output_text or "").strip()

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
