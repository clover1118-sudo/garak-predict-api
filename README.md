# 내 지갑 방어 봇 — 예측 API 백엔드

카카오 챗봇용 예측 API 서버입니다. `webapp_dashboard.html`에 들어있던
가락시장 반입량 데이터와 전국 기후 데이터를 그대로 가져와서,
대시보드의 "기후-물가 상관분석" 탭과 동일한 방식(시차 상관계수, 최근 7일 추세)으로
품목별 공급/기온 신호를 계산해 응답합니다.

## 폴더 구성

```
backend/
├── app.py                  # Flask 서버 (핵심 로직)
├── requirements.txt        # 의존 패키지
├── Procfile                # Render 배포용 실행 명령
└── data/
    ├── garak_data.json     # 가락시장 반입량 데이터
    └── climate_data.json   # 전국 기후 데이터
```

## 로컬 테스트 방법 (선택)

```bash
pip install -r requirements.txt
python app.py
# 다른 터미널에서:
curl -X POST http://localhost:5000/api/predict \
  -H "Content-Type: application/json" \
  -d '{"userRequest": {"utterance": "배추 가격 어때"}}'
```

## Render.com 배포 방법 (무료)

### 1) GitHub에 새 저장소로 올리기
GitHub Pages에 쓰던 저장소(대시보드용)와는 **별도의 새 저장소**를 만드는 걸 추천합니다.
(정적 사이트용 저장소와 서버 코드용 저장소를 섞으면 헷갈립니다.)

1. GitHub에서 새 저장소 생성 (예: `garak-predict-api`)
2. 이 `backend` 폴더 안의 파일들(app.py, requirements.txt, Procfile, data/)을
   저장소 루트에 그대로 업로드

### 2) Render 가입 및 배포
1. https://render.com 접속 → GitHub 계정으로 가입/로그인
2. **New** → **Web Service** 클릭
3. 방금 만든 GitHub 저장소 선택 → **Connect**
4. 설정값 입력:
   - **Name**: 원하는 이름 (예: garak-predict-api)
   - **Region**: Singapore (한국과 가장 가까움)
   - **Branch**: main
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Instance Type**: Free
5. **Create Web Service** 클릭
6. 몇 분 기다리면 배포 완료. 화면 상단에 아래 형태의 URL이 생성됩니다.
   ```
   https://garak-predict-api.onrender.com
   ```

### 3) 최종 API 주소
카카오 오픈빌더 스킬에 등록할 주소는 다음과 같습니다.
```
https://<render에서-생성된-도메인>/api/predict
```

> ⚠️ Render 무료 플랜은 일정 시간 요청이 없으면 서버가 잠들고,
> 다음 요청 시 깨어나는 데 20~30초 정도 걸릴 수 있습니다.
> (챗봇 첫 응답이 느릴 수 있다는 뜻이며, 정상 동작입니다.)

## API 응답 형식

카카오 스킬 표준 응답(simpleText) 형식으로 반환합니다.

```json
{
  "version": "2.0",
  "template": {
    "outputs": [
      { "simpleText": { "text": "🥬 배추 공급·기온 분석 ..." } }
    ]
  }
}
```

## 지원 품목 확인 방법

`GET /` 로 접속하면 로드된 품목 수를 확인할 수 있습니다.
품목명은 발화 문장(예: "배추 가격 어때") 안에 실제 품목명이 포함되어 있어야 인식됩니다.
