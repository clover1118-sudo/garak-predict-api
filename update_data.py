# -*- coding: utf-8 -*-
"""
매일 1회 실행되는 데이터 수집 스크립트.
- 가락시장 반입물량(정산후) API → data/garak_data.json 에 신규 날짜 행 추가
- 기상청 API Hub ASOS 일자료 → data/climate_data.json 에 신규 날짜 행 추가

GitHub Actions에서 실행되며, 아래 두 환경변수를 필요로 합니다.
  GARAK_API_KEY : 서울시농수산식품공사(garak.co.kr) 발급 인증키
  KMA_API_KEY   : 기상청 API Hub 발급 authKey

⚠️ 가락시장 API는 응답 필드명이 확정되지 않아 DEBUG_RAW=1로 실행하면
   원본 응답을 그대로 출력합니다. 처음 한 번은 반드시 DEBUG_RAW=1로 실행해서
   실제 필드명을 확인한 뒤, parse_garak_xml() 안의 태그명을 맞춰주세요.
"""

import os
import sys
import json
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GARAK_PATH = os.path.join(BASE_DIR, "data", "garak_data.json")
CLIMATE_PATH = os.path.join(BASE_DIR, "data", "climate_data.json")

GARAK_API_KEY = os.environ.get("GARAK_API_KEY", "")
KMA_API_KEY = os.environ.get("KMA_API_KEY", "")
DEBUG_RAW = os.environ.get("DEBUG_RAW", "0") == "1"

# 기존 데이터에 등장하는 기상 관측 지점명 (전국 14개 주요 지점) — 지점번호 매핑용
# 기상청 API 응답에는 지점번호(STN)만 나오므로, 이름으로 바꿔주기 위한 매핑표입니다.
# ⚠️ 실제 서비스에 쓰시는 지점 코드와 다르면 이 표를 수정해주세요.
STATION_CODE_TO_NAME = {
    "108": "서울", "112": "인천", "133": "대전", "143": "대구",
    "152": "울산", "156": "광주", "159": "부산", "184": "제주",
    "185": "고산", "279": "구미", "247": "남원", "165": "목포",
    "192": "진주", "189": "서귀포",
}


def fetch_url(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# 가락시장 반입물량 API
# --------------------------------------------------------------------------
def build_garak_url(target_date):
    """
    target_date: datetime.date
    ⚠️ 아래 endpoint와 파라미터명은 garak.co.kr 신청 페이지에서 확인한
       실제 값으로 반드시 교체해주세요. 지금은 공공데이터포털에 등록된
       일반적인 패턴(인증키=certKey, 검색일자=saleDate)으로 채워둔 상태입니다.
    """
    endpoint = "https://www.garak.co.kr/openapi/wholesalePrdlstAmt.do"  # TODO: 실제 endpoint로 교체
    params = {
        "certKey": GARAK_API_KEY,       # TODO: 실제 파라미터명으로 교체 (예: cert_id, serviceKey 등)
        "saleDate": target_date.strftime("%Y%m%d"),  # TODO: 실제 파라미터명 확인
    }
    return endpoint + "?" + urllib.parse.urlencode(params)


def parse_garak_xml(xml_text, target_date):
    """
    응답 XML을 [date(YYYYMMDD str), 품목명, 합계반입량] 형태의 리스트로 변환.
    ⚠️ 태그명(item, pumNm, qty 등)은 실제 응답을 보고 맞춰야 합니다.
    """
    rows = []
    root = ET.fromstring(xml_text)
    date_str = target_date.strftime("%Y%m%d")
    for item in root.iter("item"):  # TODO: 실제 반복 태그명 확인
        name = item.findtext("pumNm")   # TODO: 품목명 태그명 확인
        qty_text = item.findtext("qty")  # TODO: 반입량 태그명 확인
        if name is None or qty_text is None:
            continue
        try:
            qty = int(float(qty_text))
        except ValueError:
            continue
        rows.append([date_str, name.strip(), qty])
    return rows


def fetch_garak_day(target_date):
    url = build_garak_url(target_date)
    raw = fetch_url(url)
    if DEBUG_RAW:
        print("===== GARAK RAW RESPONSE =====")
        print(raw[:3000])
        print("===============================")
    try:
        return parse_garak_xml(raw, target_date)
    except ET.ParseError as e:
        print(f"[WARN] 가락시장 응답 파싱 실패: {e}")
        print(raw[:1000])
        return []


# --------------------------------------------------------------------------
# 기상청 API Hub ASOS 일자료
# --------------------------------------------------------------------------
def build_kma_url(target_date):
    date_str = target_date.strftime("%Y%m%d")
    endpoint = "https://apihub.kma.go.kr/api/typ01/url/kma_sfcdd3.php"
    params = {
        "tm1": date_str,
        "tm2": date_str,
        "stn": "0",  # 0 = 전체 지점
        "help": "0",
        "authKey": KMA_API_KEY,
    }
    return endpoint + "?" + urllib.parse.urlencode(params)


def parse_kma_text(text, target_date):
    """
    ASOS 일자료 텍스트 응답을 [date(YYYY-MM-DD), 지점명, 평균기온, 최저, 최고, 강수량, 최대풍속, 평균풍속] 로 변환.
    표준 컬럼 순서: TM STN WS_AVG WS_MAX WD_MAX WS_MAX_TM WS_INS WD_INS WS_INS_TM
                    TA_AVG TA_MAX TA_MAX_TM TA_MIN TA_MIN_TM ... RN_DAY ...
    ⚠️ 실제 컬럼 순서는 API Hub 문서의 "지상(종합) 일자료" 페이지에서 재확인 필요.
    """
    rows = []
    iso_date = target_date.strftime("%Y-%m-%d")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cols = line.split()
        if len(cols) < 14:
            continue
        stn_code = cols[1]
        station = STATION_CODE_TO_NAME.get(stn_code)
        if not station:
            continue  # 관심 지점이 아니면 skip
        try:
            ws_avg = float(cols[2])
            ta_avg = float(cols[9])
            ta_max = float(cols[10])
            ta_min = float(cols[12])
            rn_day = float(cols[33]) if len(cols) > 33 else 0.0
            ws_max = float(cols[3])
        except (ValueError, IndexError):
            continue
        # 결측치는 보통 -9 / -9.0 등으로 표기됨
        def clean(v):
            return 0 if v <= -9 else round(v)
        rows.append([
            iso_date, station,
            clean(ta_avg), clean(ta_min), clean(ta_max),
            clean(rn_day), clean(ws_max), clean(ws_avg),
        ])
    return rows


def fetch_kma_day(target_date):
    url = build_kma_url(target_date)
    raw = fetch_url(url)
    if DEBUG_RAW:
        print("===== KMA RAW RESPONSE (first 2000 chars) =====")
        print(raw[:2000])
        print("================================================")
    return parse_kma_text(raw, target_date)


# --------------------------------------------------------------------------
# 메인
# --------------------------------------------------------------------------
def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ": "))


def main():
    # 기본값: 어제 날짜 (기상/유통 데이터는 보통 전일 데이터가 그날 오전에 확정됨)
    target_date = datetime.date.today() - datetime.timedelta(days=1)
    if len(sys.argv) > 1:
        target_date = datetime.datetime.strptime(sys.argv[1], "%Y%m%d").date()

    print(f"[INFO] 대상 날짜: {target_date}")

    garak_data = load_json(GARAK_PATH)
    climate_data = load_json(CLIMATE_PATH)

    existing_garak_dates = {row[0] for row in garak_data}
    existing_climate_dates = {row[0] for row in climate_data}

    date_str = target_date.strftime("%Y%m%d")
    iso_date = target_date.strftime("%Y-%m-%d")

    added_garak = 0
    if date_str not in existing_garak_dates:
        new_rows = fetch_garak_day(target_date)
        garak_data.extend(new_rows)
        added_garak = len(new_rows)
    else:
        print(f"[INFO] 가락시장 {date_str} 데이터 이미 존재 — 스킵")

    added_climate = 0
    if iso_date not in existing_climate_dates:
        new_rows = fetch_kma_day(target_date)
        climate_data.extend(new_rows)
        added_climate = len(new_rows)
    else:
        print(f"[INFO] 기후 {iso_date} 데이터 이미 존재 — 스킵")

    if added_garak:
        save_json(GARAK_PATH, garak_data)
    if added_climate:
        save_json(CLIMATE_PATH, climate_data)

    print(f"[DONE] 가락시장 {added_garak}건 / 기후 {added_climate}건 추가")

    # GitHub Actions에서 "변경 있음"을 감지할 수 있도록 상태 파일 기록
    changed = bool(added_garak or added_climate)
    with open(os.path.join(BASE_DIR, "scripts", "_last_run_changed"), "w") as f:
        f.write("1" if changed else "0")


if __name__ == "__main__":
    main()
