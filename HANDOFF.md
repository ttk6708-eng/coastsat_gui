# 인수인계 문서 — CoastSat 해안선 분석 GUI

> Claude Code로 넘어가서 이 프로젝트를 이어서 작업할 때 참고할 문서입니다.
> 이전 대화(claude.ai)에서 진행된 내용을 정리했습니다.

## 프로젝트 개요

- **무엇**: [CoastSat](https://github.com/kvos/CoastSat)(위성영상 기반 해안선 변화 분석 파이썬 툴킷)의
  1~8단계 파이프라인을 Streamlit 웹 GUI로 감싼 앱 (전부 한글 UI)
- **원본**: Kilian Vos 외, UNSW Water Research Laboratory, GPL v3
- **배포 상태**: GitHub → Streamlit Community Cloud 로 이미 배포 완료
  - GitHub 저장소: `ttk6708-eng/coastsat_gui` (계정 `ttk6708-eng` 소유, main 브랜치)
  - Streamlit 앱: `https://coastsatgui-...streamlit.app` (정확한 주소는 Streamlit Cloud "Manage app"에서 확인)
- **로컬 실행도 가능**: `conda create -n coastsat python=3.11` 후 `pip install -r requirements.txt`,
  `streamlit run app.py` (GitHub/배포 없이 그냥 PC에서 돌리는 용도)

## 폴더 구조

```
coastsat_gui/
├── app.py                     # 메인 Streamlit 앱 (전체 로직)
├── requirements.txt           # pip 의존성
├── packages.txt               # Streamlit Cloud용 apt 시스템 패키지 (GDAL 등)
├── README.md                  # 설치·배포 안내 (GitHub→Streamlit Cloud 절차 포함)
├── .gitignore
├── .streamlit/secrets.toml.example   # Streamlit Cloud Secrets 예시 (실제 키는 여기 X)
├── coastsat/                  # CoastSat 원본 소스 그대로 vendor(포함)함 — pip 설치 불가한 패키지라서
│   ├── __init__.py
│   ├── SDS_download.py        # ⚠️ 무한 재시도 버그 수정함 (아래 참고)
│   ├── SDS_preprocess.py
│   ├── SDS_shoreline.py
│   ├── SDS_slope.py
│   ├── SDS_tools.py
│   ├── SDS_transects.py
│   ├── SDS_classify.py
│   └── gdal_merge.py
└── classification/
    └── models/                # 해안선 분류용 사전학습 신경망 모델 (.pkl 9개, ~950KB)
```

## 왜 이런 구조인가 (중요한 배경)

1. **`coastsat`은 PyPI에 없고, GitHub에서 `pip install git+https://...`도 안 됨**
   (`setup.py`/`pyproject.toml`이 없는 저장소라서). 그래서 **소스 코드를 통째로 우리 저장소에
   복사(vendor)**해서, `app.py`가 그냥 옆 폴더의 `coastsat` 패키지를 import하는 방식으로 우회함.
2. **`classification/models/*.pkl`도 원본 저장소에서 복사해온 것.** `SDS_shoreline.py`가
   `os.path.join(os.getcwd(), 'classification', 'models')` 로 상대경로를 찾기 때문에,
   반드시 `app.py`와 **같은 레벨**에 있어야 함 (`coastsat/` 폴더 안이 아님).
3. **`gdal` 버전을 `3.10.3`으로 고정함** (`requirements.txt` 마지막 줄). Streamlit Cloud의
   apt로 깔리는 `libgdal-dev` 버전과 파이썬 `gdal` 패키지 버전이 정확히 일치해야 해서
   버전을 안 박으면 최신 버전을 받으려다 빌드가 실패함. **이 서버의 libgdal 버전이 바뀌면
   이 숫자도 같이 바꿔야 할 수 있음.**

## `coastsat/SDS_download.py`에 가한 패치 (원본 대비 변경점)

`get_image_info()` 함수 원본은 GEE 조회 실패 시 `while True: try...except: continue` 로
**무한 재시도**했음 (에러 없이 화면만 계속 로딩). 이걸 **최대 5회 재시도 후 RuntimeError를
발생**시키도록 수정함. app.py의 "조사 가능한 전체 기간 확인" 기능에서 이 함수를 개별 호출하는데,
그 기능을 쓰다가 무한 로딩되는 버그를 여기서 잡은 것.

## GEE 인증 방식 3가지 (app.py 1️⃣ 초기 설정 탭)

| 방식 | 용도 | 비고 |
|---|---|---|
| 대화형 인증 | 로컬 PC 실행 (`streamlit run app.py`) | 서버 배포 시 작동 안 함 |
| 서비스 계정 | 배포 후 관리자 계정 하나로 통일 | Streamlit Secrets에 `gee_service_account`, `gee_service_account_key` 등록 필요 (`.streamlit/secrets.toml.example` 참고) |
| 각자 로그인 | 배포 후 접속자마다 자기 GEE 할당량 사용 | `ee.oauth`의 비공개 함수(`_nonce_table` 등)를 이용한 "노트북 인증" 흐름을 커스텀 구현 (`generate_ee_login_url`, `exchange_ee_auth_code` 함수, app.py 상단). **각자 로그인하는 사람이 자기 소유의 GCP 프로젝트 ID를 별도 입력해야 함** (관리자 프로젝트 ID 쓰면 권한 에러 남 — 실제로 겪었던 버그, 지금은 입력창 분리해서 고침). **⚠️ 이 로그인 흐름은 끝까지 실사용 테스트가 안 됐음. 다음 작업자가 실제로 한 번 처음부터 끝까지 로그인해보고 확인 필요.**

사이드바에 "🔐 GEE 인증 상태" 표시 있음 (✅/❌ + "지금 연결 상태 확인" 버튼).

## app.py 탭 구성

- 🏠 홈 — 프로젝트 소개, 출처/논문 인용, 6가지 핵심기능, 8단계 사용법 요약
- 1️⃣ 초기 설정 — GEE 인증(3방식), 폴리곤/기간/위성 입력, **조사 가능한 전체 기간 확인** 기능
- 2️⃣ 영상 수집 — 저장 폴더 커스터마이즈(충돌 방지용 고유 폴더명 자동생성), 다운로드,
  **결과를 zip으로 압축해 사용자 PC로 다운로드하는 기능**
- 3️⃣ 해안선 탐지 — 전처리, 자동 탐지, GeoJSON 저장
- 4️⃣ 횡단면 분석 — 트랜섹트 정의, 교차점 계산
- 5️⃣ 조석 보정 — FES2022 or 실측 CSV
- 6️⃣ 시계열 후처리 — 이상치 제거, 계절/월평균
- 7️⃣ 해변경사 추정
- 8️⃣ 현장관측 비교

## 지금까지 실제로 배포/테스트해서 확인된 것

- ✅ GitHub push → Streamlit Cloud 배포 성공 (여러 번의 requirements.txt/packages.txt 시행착오 끝에)
- ✅ 1단계 폴리곤 입력, 2단계 "조사 가능한 전체 기간 확인" 버튼까지는 화면에서 직접 확인함
- ✅ `classification/models` 누락 에러 → 해결
- ⚠️ 3~8단계는 화면 UI만 만들어졌고, **실제 GEE 데이터로 끝까지 돌려본 적은 없음** (이 부분이 다음
  작업의 핵심일 가능성이 큼 — 실제 영상 다운로드→해안선 추출→트랜섹트까지 되는지 확인 필요)
- ⚠️ "각자 로그인" 인증 흐름 미검증 (위 표 참고)
- ⚠️ pyfes, netCDF4 등 무거운 패키지들의 Streamlit Cloud 빌드 성공 여부 — gdal 문제 해결 후
  전체 빌드가 끝까지 도는지 마지막으로 확인이 필요함 (지금까지는 부분적 성공만 확인)

## 다음 작업 후보 (사용자가 언급했거나 자연스럽게 이어질 만한 것)

1. 3~8단계를 실제 위성 데이터로 end-to-end 테스트
2. "각자 로그인" 흐름 실사용 검증
3. (사용자가 궁금해했던) 예전에 zip으로 받은 데이터를 다시 업로드해서 이어서 작업하는 기능 —
   아직 미구현, 필요하면 추가
4. Streamlit Cloud 무료 플랜 리소스 한도 내에서 대용량 처리 시 안정성 점검

## 참고 링크

- 원본 저장소: https://github.com/kvos/CoastSat
- 배포 저장소: https://github.com/ttk6708-eng/coastsat_gui
- FES2022 설정 가이드: https://github.com/kvos/CoastSat/blob/master/doc/FES2022_setup
- GEE 서비스 계정 발급: https://developers.google.com/earth-engine/guides/service_account
