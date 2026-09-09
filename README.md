# CoastSat 해안선 분석 GUI (Streamlit)

`example.py`(CoastSat, Kilian Vos WRL 2018)의 전체 파이프라인(1~8단계)을
브라우저에서 조작할 수 있는 한글 웹 GUI로 감싼 앱입니다.

## 1. 설치

CoastSat은 Google Earth Engine, geopandas, pyfes 등 무거운 지리공간 패키지가
필요하므로, **가상환경(conda 추천)에서 설치**하세요.

```bash
conda create -n coastsat python=3.10 -y
conda activate coastsat

# CoastSat 및 의존 패키지 설치
pip install -r requirements.txt

# Google Earth Engine 인증 (최초 1회, 브라우저 로그인 필요)
earthengine authenticate
```

> `pyfes`, `geopandas` 설치가 conda 환경에 따라 까다로울 수 있습니다.
> 잘 안 되면 CoastSat 공식 설치 가이드를 참고하세요:
> https://github.com/kvos/CoastSat

FES2022 조석모델(5단계에서 사용)은 별도 설정이 필요합니다:
https://github.com/kvos/CoastSat/blob/master/doc/FES2022_setup

## 2. 실행

```bash
streamlit run app.py
```

브라우저가 자동으로 열리며 `http://localhost:8501` 에서 GUI를 사용할 수 있습니다.

## 3. 사용 순서

사이드바에서 현재까지 완료된 단계를 확인할 수 있습니다.

| 탭 | 내용 | 원본 스크립트 섹션 |
|---|---|---|
| 1️⃣ 초기 설정 | GEE 인증, 관심영역(폴리곤), 날짜, 위성 목록 지정 | `#%% 1.` |
| 2️⃣ 영상 수집 | GEE에서 영상 다운로드 또는 기존 메타데이터 로드 | `#%% 2.` |
| 3️⃣ 해안선 탐지 | 전처리, 해안선 자동 추출, GeoJSON 저장 | `#%% 3.` |
| 4️⃣ 횡단면 분석 | 트랜섹트 정의, 교차점(시계열) 계산 | 트랜섹트 섹션 |
| 5️⃣ 조석 보정 | FES2022(또는 실측 CSV)로 조석 보정 | `#%% 5.` |
| 6️⃣ 시계열 후처리 | 이상치 제거, 계절/월별 평균 | `#%% 6.` |
| 7️⃣ 해변경사 추정 | Lomb-Scargle 스펙트럼 기반 경사 추정 | `#%% 7.` |
| 8️⃣ 현장관측 비교 | 실측 프로파일과 위성 시계열 비교(RMSE 등) | `#%% 8.` |

각 단계의 산출물은 세션 동안 메모리(`st.session_state`)에 저장되어
다음 단계에서 자동으로 이어받아 사용됩니다. 브라우저를 새로고침하면
초기화되니, CSV/GeoJSON 등은 각 단계의 다운로드 버튼으로 저장해 두세요.

## 4. GitHub → Streamlit Community Cloud 배포

웹사이트 URL로 접속할 수 있게 무료로 배포하는 절차입니다.

### 4.1 GEE 서비스 계정 만들기 (최초 1회)
서버에는 브라우저 로그인이 불가능하므로, "서비스 계정"으로 인증해야 합니다.
1. https://console.cloud.google.com 에서 GEE가 활성화된 프로젝트를 엽니다.
2. IAM 및 관리자 > 서비스 계정 > **서비스 계정 만들기**
3. 만든 계정에서 **키 추가 > JSON** 을 선택해 키 파일을 다운로드합니다.
4. 해당 서비스 계정 이메일을 Earth Engine에서 사용할 수 있도록 등록:
   https://developers.google.com/earth-engine/guides/service_account

### 4.2 GitHub 저장소에 올리기
```bash
cd coastsat_gui
git init
git add .
git commit -m "CoastSat 해안선 분석 GUI"
git branch -M main
git remote add origin https://github.com/<본인계정>/coastsat-gui.git
git push -u origin main
```
`.gitignore`에 의해 `secrets.toml`, `data/` 등 민감하거나 무거운 파일은
자동으로 제외됩니다. **서비스 계정 키 JSON은 절대 저장소에 커밋하지 마세요.**

### 4.3 Streamlit Community Cloud에 배포
1. https://share.streamlit.io 접속 후 GitHub 계정으로 로그인
2. **New app** → 방금 만든 저장소, 브랜치(`main`), 메인 파일(`app.py`) 선택
3. **Advanced settings > Secrets** 에 아래 내용을 붙여넣기
   (`.streamlit/secrets.toml.example` 참고, 실제 서비스 계정 키 내용으로 채우기):
   ```toml
   gee_service_account = "my-service-account@project-id.iam.gserviceaccount.com"
   gee_service_account_key = '''
   { ...다운받은 JSON 키 내용 전체... }
   '''
   ```
4. **Deploy** 클릭 → 몇 분 뒤 `https://<앱이름>.streamlit.app` 형태의
   공개 URL이 발급됩니다.
5. 배포된 앱의 "1️⃣ 초기 설정" 탭에서 **GEE 인증 방식 = 서비스 계정**을
   선택하면 Secrets에 등록한 값으로 자동 인증됩니다.

### 4.4 배포 시 참고사항
- `requirements.txt`에 있는 `geopandas`, `pyfes` 등은 Streamlit Cloud의
  기본 빌드 환경(Debian)에서 설치가 안 될 수 있습니다. 이 경우 저장소에
  `packages.txt` 파일을 추가해 필요한 시스템 라이브러리(예: `gdal-bin`,
  `libgdal-dev`)를 함께 설치해야 할 수 있습니다.
- 무료 플랜은 리소스(CPU/메모리/실행시간)에 제한이 있어, 대용량 위성영상
  다운로드나 장기간 해안선 추출은 타임아웃이 날 수 있습니다. 이런 무거운
  연산은 로컬/자체 서버에서 미리 돌려 결과 파일(pkl, csv, geojson)만
  올리고, 배포된 앱에서는 4~8단계(분석·시각화 위주)만 쓰는 방식도 고려해보세요.

## 5. 주의사항

- `coastsat` 패키지가 설치되어 있지 않으면 각 실행 버튼이 비활성화되고,
  화면에 설치 안내가 표시됩니다. 설정값 입력/확인은 패키지 없이도 가능합니다.
- Google Earth Engine 인증, 실제 영상 다운로드, FES2022 조석모델 로드는
  네트워크·자격증명이 필요한 무거운 작업으로 시간이 오래 걸릴 수 있습니다.
- 이 앱은 원본 스크립트의 함수 호출을 그대로 감싼 것이므로, coastsat
  버전에 따라 함수 시그니처가 다르면 오류가 날 수 있습니다. 그런 경우
  오류 메시지를 참고해 `app.py`의 해당 부분을 조정하세요.
