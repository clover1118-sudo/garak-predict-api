# -*- coding: utf-8 -*-
"""
카카오톡 챗봇 '내 지갑 방어 봇' 예측 API
- 가락시장 반입량(GARAK_DATA) + 전국 기후(CLIMATE_DATA) 데이터를 이용해
  대시보드(webapp_dashboard.html)와 동일한 방식으로
  시차(lag)별 기온-반입량 상관관계 및 최근 공급/기온 추세를 계산한다.
- 카카오 i 오픈빌더 '스킬' 형식(JSON)으로 응답한다.
"""

import json
import os
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------
# 데이터 로드 (서버 시작 시 1회)
# --------------------------------------------------------------------------
with open(os.path.join(BASE_DIR, "data", "garak_data.json"), encoding="utf-8") as f:
    GARAK_DATA = json.load(f)  # [date(YYYYMMDD str), 품목명, 합계반입량]

with open(os.path.join(BASE_DIR, "data", "climate_data.json"), encoding="utf-8") as f:
    CLIMATE_DATA = json.load(f)  # [date(YYYY-MM-DD), 지점명, 평균기온, 최저, 최고, 강수량, 최대풍속, 평균풍속]

# 품목명 목록 (긴 이름부터 매칭해야 "양파(수입)"이 "양파"보다 먼저 잡히지 않음)
ITEM_NAMES = sorted({row[1] for row in GARAK_DATA}, key=len, reverse=True)

# 전국 평균 기온을 날짜별로 미리 계산 (YYYY-MM-DD -> 평균기온)
_nationwide_temp = {}
_sum_count = {}
for row in CLIMATE_DATA:
    date = row[0]
    temp = row[2]
    if date not in _sum_count:
        _sum_count[date] = [0, 0]
    _sum_count[date][0] += temp
    _sum_count[date][1] += 1
for date, (s, n) in _sum_count.items():
    _nationwide_temp[date] = s / n

# 가락시장 데이터를 date(YYYYMMDD) -> ISO(YYYY-MM-DD) 변환해서 품목별로 정리
GARAK_BY_ITEM = {}
for date_raw, item, amount in GARAK_DATA:
    iso = f"{date_raw[0:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
    GARAK_BY_ITEM.setdefault(item, {})[iso] = GARAK_BY_ITEM.setdefault(item, {}).get(iso, 0) + amount


# --------------------------------------------------------------------------
# 통계 함수 (대시보드 JS 로직과 동일)
# --------------------------------------------------------------------------
def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx2 = sum((x - mx) ** 2 for x in xs)
    dy2 = sum((y - my) ** 2 for y in ys)
    denom = (dx2 * dy2) ** 0.5
    return 0 if denom == 0 else num / denom


def add_days(iso_date, days):
    d = datetime.strptime(iso_date, "%Y-%m-%d") + timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def find_item_in_utterance(utterance):
    for name in ITEM_NAMES:
        if name and name in utterance:
            return name
    return None


def analyze(item):
    garak_by_date = GARAK_BY_ITEM.get(item, {})
    if not garak_by_date:
        return None

    garak_dates = sorted(garak_by_date.keys())
    if len(garak_dates) < 3:
        return {"error": "데이터가 부족합니다."}

    lags = [0, 7, 14, 30, 45, 60]
    corr_by_lag = []
    for lag in lags:
        xs, ys = [], []
        for d in garak_dates:
            lagged = add_days(d, -lag)
            t = _nationwide_temp.get(lagged)
            if t is not None:
                xs.append(t)
                ys.append(garak_by_date[d])
        r = pearson(xs, ys)
        if r is not None:
            corr_by_lag.append({"lag": lag, "r": r, "n": len(xs)})

    if not corr_by_lag:
        return {"error": "상관분석에 사용할 데이터가 부족합니다."}

    best = max(corr_by_lag, key=lambda c: abs(c["r"]))

    recent_dates = garak_dates[-7:]
    recent_avg = sum(garak_by_date[d] for d in recent_dates) / len(recent_dates)
    overall_avg = sum(garak_by_date[d] for d in garak_dates) / len(garak_dates)
    supply_change_pct = 0 if overall_avg == 0 else (recent_avg - overall_avg) / overall_avg * 100

    recent_temps = [t for t in (_nationwide_temp.get(d) for d in recent_dates) if t is not None]
    all_temps = [t for t in (_nationwide_temp.get(d) for d in garak_dates) if t is not None]
    recent_temp_avg = sum(recent_temps) / len(recent_temps) if recent_temps else 0
    overall_temp_avg = sum(all_temps) / len(all_temps) if all_temps else 0
    temp_deviation = recent_temp_avg - overall_temp_avg

    if supply_change_pct < -10 and temp_deviation > 2:
        signal = "공급 감소 + 고온 → 물가 상승 압력 신호"
    elif supply_change_pct < -10:
        signal = "공급 감소 신호"
    elif temp_deviation > 3:
        signal = "고온 신호 (공급 영향 관찰 필요)"
    else:
        signal = "뚜렷한 신호 없음"

    return {
        "item": item,
        "supply_change_pct": round(supply_change_pct, 1),
        "temp_deviation": round(temp_deviation, 1),
        "best_lag": best["lag"],
        "best_r": round(best["r"], 2),
        "signal": signal,
        "latest_date": garak_dates[-1],
    }


def build_kakao_text(result):
    if result is None:
        return (
            "죄송해요, 말씀하신 품목의 반입량 데이터를 찾지 못했어요.\n"
            "예: '배추 가격', '양파 가격', '대파 가격' 처럼 물어봐 주세요 🙏"
        )
    if "error" in result:
        return f"⚠️ {result['error']}"

    arrow = "📉" if result["supply_change_pct"] < 0 else "📈"
    dev_sign = "+" if result["temp_deviation"] >= 0 else ""

    return (
        f"🥬 {result['item']} 공급·기온 분석 (기준일 {result['latest_date']})\n\n"
        f"{arrow} 최근 7일 반입량 증감: {result['supply_change_pct']}% (전체기간 평균 대비)\n"
        f"🌡️ 최근 7일 기온 편차: {dev_sign}{result['temp_deviation']}°C\n"
        f"📐 최적 시차({result['best_lag']}일) 상관계수: {result['best_r']}\n\n"
        f"⚠️ {result['signal']}\n\n"
        f"※ 실제 소비자 가격이 아닌, 가락시장 반입량(공급량)과 전국 평균 기온의 "
        f"실측 상관관계에 근거한 간접 추정입니다."
    )


# --------------------------------------------------------------------------
# 라우트
# --------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "items_loaded": len(ITEM_NAMES)})


def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=1800"  # 30분 캐시
    return resp


@app.route("/data/garak.json", methods=["GET"])
def data_garak():
    # 대시보드가 fetch()로 가져다 쓰는 최신 가락시장 데이터
    return _cors(jsonify(GARAK_DATA))


@app.route("/data/climate.json", methods=["GET"])
def data_climate():
    # 대시보드가 fetch()로 가져다 쓰는 최신 기후 데이터
    return _cors(jsonify(CLIMATE_DATA))


@app.route("/api/predict", methods=["POST"])
def predict():
    body = request.get_json(silent=True) or {}
    utterance = (
        body.get("userRequest", {}).get("utterance")
        or body.get("utterance")
        or ""
    ).strip()

    item = find_item_in_utterance(utterance)
    result = analyze(item) if item else None
    text = build_kakao_text(result)

    return jsonify({
        "version": "2.0",
        "template": {
            "outputs": [
                {"simpleText": {"text": text}}
            ]
        }
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
