# -*- coding: utf-8 -*-
"""
CoastSat 해안선 분석 GUI (한글)
=================================
원본 스크립트(example.py, CoastSat - Kilian Vos WRL 2018)의
1~8단계 파이프라인을 Streamlit 탭으로 감싼 웹 GUI입니다.

⚠️ 중요
- 이 앱은 CoastSat 패키지(coastsat), pyfes, geopandas, earthengine-api 등이
  설치되어 있고 Google Earth Engine 인증이 완료된 "로컬 PC"에서 실행해야
  실제로 동작합니다. (샌드박스 환경에서는 GEE 접속이 불가능하여 실행 테스트를
  진행하지 못했습니다.)
- 실행 방법: 터미널에서  `streamlit run app.py`

실행 순서: 1.초기설정 → 2.영상수집 → 3.해안선탐지 → 4.횡단면분석
          → 5.조석보정 → 6.시계열후처리 → 7.해변경사추정 → 8.현장관측비교
각 단계의 결과는 st.session_state 에 저장되어 다음 단계에서 재사용됩니다.
"""

import os
import io
import json
import pickle
import tempfile
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import gridspec

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# CoastSat 및 관련 무거운 패키지는 설치되어 있지 않을 수 있으므로 안전하게 import
# ---------------------------------------------------------------------------
COASTSAT_AVAILABLE = True
IMPORT_ERROR_MSG = ""
try:
    from pyproj import CRS
    from coastsat import (
        SDS_download,
        SDS_preprocess,
        SDS_shoreline,
        SDS_tools,
        SDS_transects,
        SDS_slope,
    )
except Exception as e:  # pragma: no cover
    COASTSAT_AVAILABLE = False
    IMPORT_ERROR_MSG = str(e)

try:
    import pytz
except Exception:
    pytz = None

try:
    from scipy import interpolate, stats
except Exception:
    interpolate = None
    stats = None


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------
st.set_page_config(page_title="CoastSat 해안선 분석 GUI", layout="wide")

DEFAULTS = {
    "inputs": None,
    "metadata": None,
    "settings": None,
    "output": None,
    "transects": None,
    "settings_transects": None,
    "cross_distance": None,
    "cross_distance_corrected": None,
    "dates_ts": None,
    "tides_ts": None,
    "tides_sat": None,
    "centroid": None,
    "ocean_tide": None,
    "load_tide": None,
    "slope_est": None,
    "slope_cis": None,
    "topo_profiles": None,
    "_coverage_df": None,
    "_ee_authenticated": False,
    "_download_zip_bytes": None,
    "_download_zip_name": None,
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


def require_coastsat():
    """coastsat 패키지가 없으면 안내 메시지를 띄우고 True/False 반환."""
    if not COASTSAT_AVAILABLE:
        st.error(
            "❌ `coastsat` 패키지(또는 관련 의존성)를 불러오지 못했습니다.\n\n"
            f"오류 메시지: `{IMPORT_ERROR_MSG}`\n\n"
            "아래 안내에 따라 로컬 환경에 설치한 뒤 다시 실행해 주세요."
        )
        with st.expander("📦 설치 방법 보기"):
            st.code(
                "conda create -n coastsat python=3.10 -y\n"
                "conda activate coastsat\n"
                "pip install coastsat earthengine-api geopandas pyfes pytz\n"
                "earthengine authenticate",
                language="bash",
            )
        return False
    return True


def generate_ee_login_url():
    """사용자별 GEE 로그인 링크 생성 (Earth Engine '노트북 인증' 방식).

    각 사용자가 자기 구글 계정으로 로그인하도록, earthengine-api가 원격/노트북
    환경에서 쓰는 공식 OAuth 흐름(code.earthengine.google.com/client-auth)을
    그대로 이용합니다. 이 함수는 요청 정보(nonce)만 생성하고, 실제 토큰 발급은
    exchange_ee_auth_code()에서 사용자가 붙여넣은 코드로 처리합니다.
    자격 정보는 세션별로만 메모리에 보관하며 디스크에 저장하지 않습니다.
    """
    import ee.oauth as oauth
    import urllib.parse

    nonces = ["request_id", "token_verifier", "client_verifier"]
    request_info = oauth._nonce_table(*nonces)
    auth_url = oauth.AUTH_URL_TEMPLATE.format(
        scopes=urllib.parse.quote(" ".join(oauth.SCOPES)), **request_info
    )
    code_verifier = ":".join(request_info[k] for k in nonces)
    return auth_url, code_verifier


def exchange_ee_auth_code(auth_code: str, code_verifier: str):
    """사용자가 붙여넣은 인증 코드를 구글 자격 증명(Credentials) 객체로 교환."""
    import json as _json
    import urllib.request as _urlreq
    import ee.oauth as oauth
    from google.oauth2.credentials import Credentials

    request_id, verifier, client_verifier = code_verifier.split(":")
    fetch_data = {"request_id": request_id, "client_verifier": client_verifier}
    data = _json.dumps(fetch_data).encode()
    headers = {"Content-Type": "application/json; charset=UTF-8"}
    req = _urlreq.Request(oauth.FETCH_URL, data=data, headers=headers)
    fetched_info = _json.loads(_urlreq.urlopen(req).read().decode())
    if "error" in fetched_info:
        raise RuntimeError(fetched_info["error"])

    client_id = fetched_info["client_id"]
    client_secret = fetched_info["client_secret"]
    scopes = fetched_info.get("scopes") or oauth.SCOPES

    refresh_token = oauth.request_token(
        auth_code.strip(), verifier, client_id=client_id, client_secret=client_secret
    )
    credentials = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri=oauth.TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
    )
    return credentials


def check_ee_connected():
    """GEE에 실제로 연결되어 있는지 가벼운 테스트 요청으로 확인."""
    try:
        import ee

        ee.Number(1).getInfo()
        return True
    except Exception:
        return False


def show_fig(fig):
    st.pyplot(fig, clear_figure=True)


def df_download_button(df: pd.DataFrame, label: str, filename: str):
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(label, data=csv, file_name=filename, mime="text/csv")


def plot_shorelines(output, transects=None, title=""):
    fig = plt.figure(figsize=[10, 6], tight_layout=True)
    plt.axis("equal")
    plt.xlabel("Eastings")
    plt.ylabel("Northings")
    plt.grid(linestyle=":", color="0.5")
    if title:
        plt.title(title)
    for i in range(len(output["shorelines"])):
        sl = output["shorelines"][i]
        date = output["dates"][i]
        plt.plot(sl[:, 0], sl[:, 1], ".", label=date.strftime("%d-%m-%Y"))
    if transects:
        for key in transects.keys():
            plt.plot(transects[key][0, 0], transects[key][0, 1], "bo", ms=5)
            plt.plot(transects[key][:, 0], transects[key][:, 1], "k-", lw=1)
            plt.text(
                transects[key][0, 0] - 100,
                transects[key][0, 1] + 100,
                key,
                va="center",
                ha="right",
                bbox=dict(boxstyle="square", ec="k", fc="w"),
            )
    return fig


# ---------------------------------------------------------------------------
# 사이드바 : 전역 상태 요약
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🌊 CoastSat GUI")
    st.caption("위성영상 기반 해안선 변화 분석")
    if not COASTSAT_AVAILABLE:
        st.warning("coastsat 패키지 미설치 상태 (설정 입력은 가능)")

    st.markdown("---")
    st.markdown("### 🔐 GEE 인증 상태")
    if st.session_state.get("_ee_authenticated"):
        st.success("✅ 인증됨")
    else:
        st.error("❌ 미인증 — '1️⃣ 초기 설정'에서 인증해주세요")
    if st.button("🔄 지금 연결 상태 확인", disabled=not COASTSAT_AVAILABLE, key="_sidebar_ee_check"):
        with st.spinner("확인 중..."):
            connected = check_ee_connected()
        st.session_state["_ee_authenticated"] = connected
        if connected:
            st.success("연결 정상")
        else:
            st.error("연결 안 됨 — 재인증이 필요합니다")

    st.markdown("---")
    st.markdown("### 진행 상태")
    checklist = [
        ("① 초기 설정", st.session_state["inputs"] is not None),
        ("② 영상 수집", st.session_state["metadata"] is not None),
        ("③ 해안선 탐지", st.session_state["output"] is not None),
        ("④ 횡단면 분석", st.session_state["cross_distance"] is not None),
        ("⑤ 조석 보정", st.session_state["cross_distance_corrected"] is not None),
        ("⑥ 시계열 후처리", False),
        ("⑦ 해변경사 추정", st.session_state["slope_est"] is not None),
        ("⑧ 현장관측 비교", st.session_state["topo_profiles"] is not None),
    ]
    for label, done in checklist:
        st.write(("✅ " if done else "⬜ ") + label)

# ---------------------------------------------------------------------------
# 탭 구성
# ---------------------------------------------------------------------------
tabs = st.tabs(
    [
        "🏠 홈",
        "1️⃣ 초기 설정",
        "2️⃣ 영상 수집",
        "3️⃣ 해안선 탐지",
        "4️⃣ 횡단면 분석",
        "5️⃣ 조석 보정",
        "6️⃣ 시계열 후처리",
        "7️⃣ 해변경사 추정",
        "8️⃣ 현장관측 비교",
    ]
)

# ===========================================================================
# 0. 홈 (소개 화면)
# ===========================================================================
with tabs[0]:
    st.title("🌊 CoastSat 해안선 분석 GUI")
    st.markdown(
        "**위성영상만으로 전 세계 어디든 해안선의 위치 변화를 시계열로 뽑아내는 오픈소스 툴킷, "
        "CoastSat을 웹 화면으로 감싼 GUI입니다.**"
    )
    st.markdown(
        "위성 원격탐사는 현장 관측 장비가 없는 지역에서도 해안 과학자·엔지니어가 필요로 하는 시간 단위의 "
        "저비용 장기 해안선 데이터를 제공할 수 있습니다. CoastSat은 전문가가 아니어도 Landsat 5/7/8/9, "
        "Sentinel-2 영상에서 해안선을 추출할 수 있게 해줍니다. 서브픽셀 경계 분할(sub-pixel border "
        "segmentation)과 영상 분류를 결합한 탐지 알고리즘을 사용하며, 특히 **모래 해변(sandy beach)** "
        "환경에 최적화되어 있습니다."
    )

    st.markdown("---")
    st.subheader("📚 출처 (Source)")
    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown(
            "- **원본 저장소**: [github.com/kvos/CoastSat](https://github.com/kvos/CoastSat)\n"
            "- **개발**: Kilian Vos 외, Water Research Laboratory, UNSW Sydney (2018~)\n"
            "- **라이선스**: GPL v3\n"
            "- **공개 데이터 포털**: [coastsat.space](http://coastsat.space) — CoastSat으로 만든 "
            "태평양·대서양 해안선 데이터셋을 바로 탐색/다운로드할 수 있습니다.\n"
            "- **DOI**: [10.5281/zenodo.2779293](https://doi.org/10.5281/zenodo.2779293)"
        )
    with c2:
        st.markdown(
            "**대표 논문**\n"
            "- Vos et al. (2019), *Environmental Modelling & Software* — "
            "해안선 탐지 알고리즘 원 논문 (Open Access) · "
            "[doi.org/10.1016/j.envsoft.2019.104528](https://doi.org/10.1016/j.envsoft.2019.104528)\n"
            "- Vos et al. (2019), *Coastal Engineering* — 정확도 검증 · "
            "[doi.org/10.1016/j.coastaleng.2019.04.004](https://doi.org/10.1016/j.coastaleng.2019.04.004)\n"
            "- Vos et al. (2020), *Geophysical Research Letters* — 해변 경사 추정 · "
            "[doi.org/10.1029/2020GL088365](https://doi.org/10.1029/2020GL088365)\n"
            "- Vos et al. (2023), *Nature Geoscience* — 태평양 전역 침식/퇴적 패턴 · "
            "[doi.org/10.1038/s41561-022-01117-8](https://doi.org/10.1038/s41561-022-01117-8)"
        )
    st.caption(
        "이 GUI는 CoastSat 파이프라인을 그대로 호출하는 인터페이스일 뿐, 알고리즘 자체를 재구현한 것이 "
        "아닙니다. 연구/논문에 결과를 인용할 때는 반드시 위 CoastSat 원 논문을 인용해 주세요."
    )

    st.markdown("---")
    st.subheader("🧭 CoastSat의 6가지 핵심 기능")
    st.markdown(
        "1. 관심 영역·기간을 지정하면 Google Earth Engine에서 위성영상을 자동 수집 "
        "(밴드 재투영, 팬샤프닝, 구름 마스킹 등 최신 전처리 포함)\n"
        "2. 서브픽셀 정밀도로 모든 영상에서 해안선을 자동 추출 (품질관리 옵션 제공)\n"
        "3. 사용자가 정의한 해안 직각 트랜섹트와 2D 해안선의 교차점으로 변화 시계열 생성\n"
        "4. FES2022 전지구 조석모델로 해안선 시계열을 조석 보정하고, 촬영 시점 조위를 추출\n"
        "5. 시계열 후처리 — 이상치 제거(despiking)와 계절별 평균화\n"
        "6. 위성 유래 해안선과 예측 조위로 해변 경사 추정"
    )

    st.markdown("---")
    st.subheader("📋 이 GUI의 사용 순서 (왼쪽부터 순서대로 진행하세요)")

    steps_info = [
        ("1️⃣", "초기 설정", "GEE 인증, 분석하고 싶은 해안 영역(폴리곤), 분석 기간, 사용할 위성(Landsat/Sentinel-2)을 지정합니다."),
        ("2️⃣", "영상 수집", "설정한 조건에 맞는 위성영상을 Google Earth Engine에서 다운로드합니다."),
        ("3️⃣", "해안선 탐지", "다운로드한 영상에서 구름을 걸러내고, 물과 육지의 경계(해안선)를 자동으로 찾아냅니다."),
        ("4️⃣", "횡단면 분석", "해안선에 수직인 기준선(트랜섹트)을 그어, 그 선과 해안선이 만나는 지점의 위치 변화를 시계열로 계산합니다."),
        ("5️⃣", "조석 보정", "촬영 당시 조수 높이에 따라 해안선 위치가 달라 보이는 오차를 보정합니다."),
        ("6️⃣", "시계열 후처리", "튀는 값(이상치)을 걸러내고, 계절별·월별 평균으로 정리해 추세를 보기 쉽게 만듭니다."),
        ("7️⃣", "해변경사 추정", "위성 시계열만으로 해변의 평균 경사를 통계적으로 추정합니다."),
        ("8️⃣", "현장관측 비교", "실제 현장에서 측량한 데이터와 위성 분석 결과를 비교해 정확도를 검증합니다 (선택사항)."),
    ]
    for emoji, title, desc in steps_info:
        c1, c2 = st.columns([1, 9])
        with c1:
            st.markdown(f"### {emoji}")
        with c2:
            st.markdown(f"**{title}**")
            st.caption(desc)

    st.markdown("---")
    st.subheader("✅ 시작하기 전에 필요한 것")
    st.markdown(
        "- **Google Earth Engine 계정** (무료 가입 필요, https://earthengine.google.com)\n"
        "- 분석하고 싶은 **해안 지역의 대략적인 위경도 범위**\n"
        "- (선택) 정밀 비교를 위한 **현장관측 데이터** — 8단계에서만 필요\n\n"
        "왼쪽 사이드바에서 지금까지 어느 단계까지 완료했는지 실시간으로 확인할 수 있습니다. "
        "준비되셨으면 위의 **'1️⃣ 초기 설정'** 탭으로 이동해 시작하세요."
    )

    if not COASTSAT_AVAILABLE:
        st.warning(
            "⚠️ 현재 이 환경에는 `coastsat` 패키지 로드에 실패한 상태입니다. "
            "설정값 입력이나 화면 탐색은 가능하지만, 실제 실행 버튼들은 비활성화되어 있어요."
        )

# 1. 초기 설정
# ===========================================================================
with tabs[1]:
    st.header("1. 초기 설정 (GEE 인증 · 관심영역 · 기간 · 위성)")

    col1, col2 = st.columns(2)
    with col1:
        project_name = st.text_input(
            "GEE 프로젝트 이름",
            value="coastsat-eu",
            help="터미널에서 `gcloud config get-value project` 로 확인",
        )

        auth_mode = st.radio(
            "GEE 인증 방식",
            [
                "대화형 인증 (로컬 PC 실행용)",
                "서비스 계정 (관리자 계정 공유, 배포용)",
                "각자 로그인 (사용자별 Google 계정, 배포용)",
            ],
            help=(
                "서버에 배포하면 브라우저 로그인 창을 띄울 수 없으므로 서비스 계정 또는 "
                "각자 로그인 방식을 사용해야 합니다. 여러 사람이 함께 쓸 GUI라면 "
                "'각자 로그인'을 쓰면 사용량이 관리자 계정 한 곳에 몰리지 않습니다."
            ),
        )

        if auth_mode.startswith("대화형"):
            if st.button("🔐 GEE 인증 및 초기화 (대화형)", disabled=not COASTSAT_AVAILABLE):
                try:
                    SDS_download.authenticate_and_initialize(project_name)
                    st.session_state["_ee_authenticated"] = True
                    st.success("GEE 인증 완료")
                except Exception as e:
                    st.error(f"인증 실패: {e}")
        elif auth_mode.startswith("서비스 계정"):
            st.caption(
                "① GEE 서비스 계정을 만들고 키(JSON)를 발급받으세요: "
                "https://developers.google.com/earth-engine/guides/service_account\n\n"
                "② Streamlit Cloud에 배포할 경우, 이 키 내용을 앱의 **Secrets**에 등록해두면 "
                "아래에서 파일 업로드 없이 자동으로 인증됩니다 (Secrets 설정법은 배포 가이드 참고)."
            )
            sa_email = st.text_input(
                "서비스 계정 이메일",
                value=st.secrets.get("gee_service_account", "") if hasattr(st, "secrets") else "",
                placeholder="my-service-account@project-id.iam.gserviceaccount.com",
            )
            sa_key_file = st.file_uploader("서비스 계정 키 파일 (.json)", type=["json"], key="sa_key_upload")

            if st.button("🔐 서비스 계정으로 GEE 인증", disabled=not COASTSAT_AVAILABLE):
                try:
                    import ee

                    key_data = None
                    if sa_key_file is not None:
                        key_bytes = sa_key_file.getvalue()
                        key_path = os.path.join(tempfile.gettempdir(), "gee_service_account.json")
                        with open(key_path, "wb") as f:
                            f.write(key_bytes)
                        key_json = json.loads(key_bytes)
                        email = sa_email or key_json.get("client_email")
                        credentials = ee.ServiceAccountCredentials(email, key_path)
                    elif hasattr(st, "secrets") and "gee_service_account_key" in st.secrets:
                        # Streamlit Cloud Secrets에 JSON 문자열로 등록해둔 경우
                        key_json_str = st.secrets["gee_service_account_key"]
                        key_path = os.path.join(tempfile.gettempdir(), "gee_service_account.json")
                        with open(key_path, "w") as f:
                            f.write(key_json_str)
                        key_json = json.loads(key_json_str)
                        email = sa_email or key_json.get("client_email")
                        credentials = ee.ServiceAccountCredentials(email, key_path)
                    else:
                        raise RuntimeError(
                            "키 파일을 업로드하거나, Streamlit Secrets에 "
                            "`gee_service_account_key` 값을 등록해 주세요."
                        )

                    ee.Initialize(credentials, project=project_name)
                    st.session_state["_ee_authenticated"] = True
                    st.success("서비스 계정으로 GEE 인증 완료")
                except Exception as e:
                    st.error(f"인증 실패: {e}")
        else:  # 각자 로그인 (사용자별 Google 계정)
            st.caption(
                "이 방식은 접속한 사람이 **본인 Google 계정**으로 로그인해서, "
                "각자의 Earth Engine 할당량으로 영상을 받습니다. "
                "단, 로그인하는 계정이 미리 Earth Engine 사용 승인을 받은 상태여야 합니다 "
                "(https://code.earthengine.google.com/register 에서 신청). "
                "여기서 발급받은 인증 정보는 서버 파일이 아니라 **이 브라우저 세션에만** 보관됩니다."
            )
            st.warning(
                "⚠️ 위쪽 'GEE 프로젝트 이름'은 **관리자 계정 소유의 프로젝트**라서 다른 사람이 "
                "로그인하면 권한 오류가 납니다. 아래에 **본인 명의의 GCP 프로젝트 ID**를 따로 "
                "입력해 주세요."
            )
            personal_project_name = st.text_input(
                "본인 GCP 프로젝트 ID",
                value="",
                placeholder="예: ee-내구글계정이름",
                help=(
                    "Earth Engine 가입 시 자동으로 만들어진 프로젝트 ID입니다. "
                    "https://code.earthengine.google.com 접속 후 좌측 상단 프로젝트 선택 메뉴에서 "
                    "확인할 수 있습니다."
                ),
            )

            if st.button("1️⃣ 로그인 링크 만들기", disabled=not COASTSAT_AVAILABLE):
                try:
                    auth_url, code_verifier = generate_ee_login_url()
                    st.session_state["_ee_code_verifier"] = code_verifier
                    st.session_state["_ee_auth_url"] = auth_url
                except Exception as e:
                    st.error(f"로그인 링크 생성 실패: {e}")

            if st.session_state.get("_ee_auth_url"):
                st.markdown(f"👉 [여기를 눌러 Google 계정으로 로그인하기]({st.session_state['_ee_auth_url']})")
                st.caption("로그인 후 화면에 나오는 인증 코드를 복사해서 아래에 붙여넣으세요.")
                auth_code_input = st.text_input("2️⃣ 인증 코드 붙여넣기", key="_ee_auth_code_input")
                if st.button("3️⃣ 로그인 완료 (이 코드로 인증)", disabled=not COASTSAT_AVAILABLE):
                    if not personal_project_name.strip():
                        st.error("본인 GCP 프로젝트 ID를 먼저 입력해 주세요.")
                    else:
                        try:
                            import ee

                            credentials = exchange_ee_auth_code(
                                auth_code_input, st.session_state["_ee_code_verifier"]
                            )
                            ee.Initialize(credentials, project=personal_project_name.strip())
                            st.session_state["_ee_user_credentials"] = credentials
                            st.session_state["_ee_authenticated"] = True
                            st.success("본인 Google 계정으로 GEE 인증 완료! (이 세션에서만 유지됩니다)")
                        except Exception as e:
                            st.error(f"인증 실패: {e}")

        sitename = st.text_input("사이트 이름 (sitename)", value="NARRA")
        filepath_data = st.text_input(
            "데이터 저장 경로", value=os.path.join(os.getcwd(), "data")
        )
        sat_list = st.multiselect(
            "위성 목록", ["L5", "L7", "L8", "L9", "S2"], default=["L5", "L7", "L8", "L9"]
        )
        date_range = st.date_input(
            "날짜 범위",
            value=(datetime(1984, 1, 1), datetime(2025, 1, 1)),
        )

    with col2:
        st.markdown("**관심영역(폴리곤) 입력 방법**")
        polygon_mode = st.radio(
            "입력 방식 선택",
            ["직접 좌표 입력", "GeoJSON 파일 업로드", "KML 파일 업로드"],
            horizontal=False,
        )

        polygon_coords = None
        if polygon_mode == "직접 좌표 입력":
            default_poly = pd.DataFrame(
                {
                    "경도(lon)": [151.301454, 151.311453, 151.307237, 151.294220, 151.301454],
                    "위도(lat)": [-33.700754, -33.702075, -33.739761, -33.736329, -33.700754],
                }
            )
            edited = st.data_editor(default_poly, num_rows="dynamic", key="poly_editor")
            polygon_coords = edited.values.tolist()
        elif polygon_mode == "GeoJSON 파일 업로드":
            up = st.file_uploader("polygon.geojson", type=["geojson", "json"])
            if up is not None:
                tmp_path = os.path.join(tempfile.gettempdir(), up.name)
                with open(tmp_path, "wb") as f:
                    f.write(up.getbuffer())
                st.session_state["_polygon_geojson_path"] = tmp_path
                st.success(f"업로드됨: {up.name}")
        else:
            up = st.file_uploader("polygon.kml", type=["kml"])
            if up is not None:
                tmp_path = os.path.join(tempfile.gettempdir(), up.name)
                with open(tmp_path, "wb") as f:
                    f.write(up.getbuffer())
                st.session_state["_polygon_kml_path"] = tmp_path
                st.success(f"업로드됨: {up.name}")

    if st.button("✅ 입력값(inputs) 확정", type="primary"):
        try:
            if polygon_mode == "직접 좌표 입력":
                polygon = [[list(p) for p in polygon_coords]]
            elif polygon_mode == "GeoJSON 파일 업로드":
                if not COASTSAT_AVAILABLE:
                    raise RuntimeError("coastsat 미설치로 geojson 파싱 불가")
                polygon = SDS_tools.polygon_from_geojson(
                    st.session_state["_polygon_geojson_path"]
                )
            else:
                if not COASTSAT_AVAILABLE:
                    raise RuntimeError("coastsat 미설치로 kml 파싱 불가")
                polygon = SDS_tools.polygon_from_kml(st.session_state["_polygon_kml_path"])

            if COASTSAT_AVAILABLE:
                polygon = SDS_tools.smallest_rectangle(polygon)

            dates = [d.strftime("%Y-%m-%d") for d in date_range]

            inputs = {
                "polygon": polygon,
                "dates": dates,
                "sat_list": sat_list,
                "sitename": sitename,
                "filepath": filepath_data,
            }
            st.session_state["inputs"] = inputs
            st.success("inputs 딕셔너리가 생성되었습니다. 아래에서 확인하세요.")
        except Exception as e:
            st.error(f"입력값 생성 실패: {e}")

    if st.session_state["inputs"] is not None:
        st.json(st.session_state["inputs"])

        colA, colB = st.columns(2)
        with colA:
            if st.button("📊 현재 설정한 기간 내 영상 개수 확인", disabled=not COASTSAT_AVAILABLE):
                try:
                    im_dict_T1, im_dict_T2 = SDS_download.check_images_available(
                        st.session_state["inputs"]
                    )
                    rows = []
                    for satname, im_list in im_dict_T1.items():
                        rows.append({"위성": satname, "영상 개수": len(im_list)})
                    st.dataframe(pd.DataFrame(rows), use_container_width=True)
                except Exception as e:
                    st.error(f"확인 실패: {e}")

        with colB:
            if st.button("📅 이 위치에서 조사 가능한 전체 기간 확인", disabled=not COASTSAT_AVAILABLE):
                col_names_T1 = {
                    "L5": "LANDSAT/LT05/C02/T1_TOA",
                    "L7": "LANDSAT/LE07/C02/T1_TOA",
                    "L8": "LANDSAT/LC08/C02/T1_TOA",
                    "L9": "LANDSAT/LC09/C02/T1_TOA",
                    "S2": "COPERNICUS/S2_HARMONIZED",
                }
                wide_dates = ["1982-01-01", datetime.now().strftime("%Y-%m-%d")]
                polygon = st.session_state["inputs"]["polygon"]
                sat_list_check = st.session_state["inputs"]["sat_list"]

                coverage_rows = []
                progress = st.progress(0.0, text="조회 시작...")
                for idx, satname in enumerate(sat_list_check):
                    progress.progress(idx / len(sat_list_check), text=f"{satname} 조회 중...")
                    try:
                        im_list = SDS_download.get_image_info(
                            col_names_T1[satname], satname, polygon, wide_dates
                        )
                        if satname == "S2":
                            im_list = SDS_download.filter_S2_collection(im_list)
                        if len(im_list) == 0:
                            coverage_rows.append(
                                {"위성": satname, "영상 개수": 0, "최초 촬영일": "-", "최근 촬영일": "-", "비고": ""}
                            )
                        else:
                            ts_list = [im["properties"]["system:time_start"] / 1000 for im in im_list]
                            first_date = datetime.utcfromtimestamp(min(ts_list)).strftime("%Y-%m-%d")
                            last_date = datetime.utcfromtimestamp(max(ts_list)).strftime("%Y-%m-%d")
                            coverage_rows.append(
                                {
                                    "위성": satname,
                                    "영상 개수": len(im_list),
                                    "최초 촬영일": first_date,
                                    "최근 촬영일": last_date,
                                    "비고": "",
                                }
                            )
                    except Exception as e:
                        coverage_rows.append(
                            {"위성": satname, "영상 개수": "-", "최초 촬영일": "-", "최근 촬영일": "-", "비고": f"조회 실패: {e}"}
                        )
                progress.progress(1.0, text="완료")
                st.session_state["_coverage_df"] = pd.DataFrame(coverage_rows)
                st.success("이 지역에서 조사 가능한 기간을 확인했습니다. (일부 위성은 실패했을 수 있어요, 표의 '비고' 확인)")

        if st.session_state.get("_coverage_df") is not None:
            df_cov = st.session_state["_coverage_df"]
            st.dataframe(df_cov, use_container_width=True)

            # "영상 개수"에 실패시 "-" 문자열이 섞여 있을 수 있으므로 숫자만 안전하게 비교
            counts_numeric = pd.to_numeric(df_cov["영상 개수"], errors="coerce")
            valid = df_cov[counts_numeric > 0]
            failed = df_cov[df_cov["비고"] != ""]

            if not valid.empty:
                earliest = min(valid["최초 촬영일"])
                latest = max(valid["최근 촬영일"])
                st.info(
                    f"📌 이 위치는 **{earliest} ~ {latest}** 기간까지 위성영상 기반 해안선 조사가 "
                    f"가능합니다 (선택한 위성들을 통틀어서). 위성마다 커버 기간이 다르니 표를 참고해 "
                    f"'1️⃣ 초기 설정'의 날짜 범위를 조정하세요. "
                    f"(참고: Landsat 5는 대략 1984년~2013년, Landsat 7은 1999년~현재, "
                    f"Landsat 8은 2013년~현재, Landsat 9는 2021년~현재, Sentinel-2는 2015년~현재 "
                    f"운영되었습니다 — 단, 실제 촬영 여부는 지역마다 다릅니다.)"
                )
            elif failed.empty:
                st.warning("선택한 위성/영역에서는 사용 가능한 영상을 찾지 못했습니다. 폴리곤 위치나 위성 목록을 확인해주세요.")

            if not failed.empty:
                if valid.empty:
                    st.error(
                        "⚠️ 모든 위성 조회가 실패했습니다. 대부분 **GEE 인증이 안 되어 있거나 만료된 경우**입니다. "
                        "위쪽 'GEE 인증 및 초기화' 버튼을 다시 눌러 인증부터 완료한 뒤 재시도해 주세요."
                    )
                with st.expander("🔍 실패한 위성의 전체 오류 메시지 보기"):
                    for _, row in failed.iterrows():
                        st.markdown(f"**{row['위성']}**")
                        st.code(row["비고"], language=None)

# ===========================================================================
# 2. 영상 수집
# ===========================================================================
with tabs[2]:
    st.header("2. 위성 영상 수집")
    if st.session_state["inputs"] is None:
        st.info("먼저 1단계에서 입력값을 확정해 주세요.")
    else:
        with st.expander("📁 저장 폴더 설정 (본인 폴더 지정)", expanded=True):
            st.caption(
                "여러 사람이 이 앱을 함께 쓸 경우, 서로 같은 폴더에 저장하면 데이터가 "
                "섞이거나 덮어써질 수 있어요. 본인만의 폴더명을 지정해 두세요."
            )
            c1, c2 = st.columns([2, 1])
            with c1:
                custom_filepath = st.text_input(
                    "데이터 저장 경로",
                    value=st.session_state["inputs"]["filepath"],
                    key="_custom_filepath",
                )
                custom_sitename = st.text_input(
                    "사이트 이름 (폴더명)",
                    value=st.session_state["inputs"]["sitename"],
                    key="_custom_sitename",
                )
            with c2:
                st.write("")
                st.write("")
                if st.button("🔀 겹치지 않는 이름 자동 생성"):
                    import uuid

                    unique_suffix = uuid.uuid4().hex[:6]
                    st.session_state["_custom_sitename"] = (
                        f"{st.session_state['inputs']['sitename']}_{unique_suffix}"
                    )
                    st.rerun()

            if st.button("✅ 이 폴더로 저장하기"):
                updated_inputs = dict(st.session_state["inputs"])
                updated_inputs["filepath"] = custom_filepath
                updated_inputs["sitename"] = custom_sitename
                st.session_state["inputs"] = updated_inputs
                st.success("저장 폴더가 반영되었습니다.")

            resolved_path = os.path.join(
                st.session_state["inputs"]["filepath"], st.session_state["inputs"]["sitename"]
            )
            st.code(resolved_path, language=None)
            st.caption("👆 실제로 영상과 결과가 저장될 전체 경로입니다.")

        colA, colB = st.columns(2)
        with colA:
            skip_l7_slc = st.checkbox(
                "L7 SLC(Scan-Line-Correction) 오류 영상 제외 (2003.5.31 이후)"
            )
            include_t2 = st.checkbox("Landsat Tier 2 영상 포함 (시계열 분석에는 비권장)")

        inputs = dict(st.session_state["inputs"])
        if skip_l7_slc:
            inputs["skip_L7_SLC"] = True
        if include_t2:
            inputs["include_T2"] = True

        with colB:
            if st.button("⬇️ 영상 다운로드 (GEE에서 새로 수집)", disabled=not COASTSAT_AVAILABLE):
                try:
                    with st.spinner("영상을 다운로드하는 중입니다... (시간이 오래 걸릴 수 있습니다)"):
                        metadata = SDS_download.retrieve_images(inputs)
                    st.session_state["metadata"] = metadata
                    st.session_state["inputs"] = inputs
                    st.success("다운로드 완료")
                except Exception as e:
                    st.error(f"다운로드 실패: {e}")

            if st.button("📂 이미 다운로드된 메타데이터 불러오기", disabled=not COASTSAT_AVAILABLE):
                try:
                    metadata = SDS_download.get_metadata(inputs)
                    st.session_state["metadata"] = metadata
                    st.session_state["inputs"] = inputs
                    st.success("메타데이터를 불러왔습니다")
                except Exception as e:
                    st.error(f"불러오기 실패: {e}")

        if st.session_state["metadata"] is not None:
            st.success("메타데이터가 준비되었습니다.")
            try:
                summary = {
                    sat: len(v.get("dates", []))
                    for sat, v in st.session_state["metadata"].items()
                }
                st.write("위성별 영상 개수")
                st.table(pd.DataFrame(summary.items(), columns=["위성", "영상 개수"]))
            except Exception:
                pass

            st.markdown("---")
            st.subheader("💾 내 컴퓨터로 받기")
            st.caption(
                "여기 저장된 영상·데이터는 서버(클라우드) 안에 있는 것이라, 앱을 껐다 켜면 "
                "사라질 수 있어요. 꼭 보관하고 싶은 결과는 압축해서 본인 PC로 받아두세요."
            )
            site_folder = os.path.join(
                st.session_state["inputs"]["filepath"], st.session_state["inputs"]["sitename"]
            )
            if st.button("📦 이 사이트 폴더 전체를 zip으로 압축하기"):
                try:
                    import shutil

                    if not os.path.isdir(site_folder):
                        st.error(f"폴더를 찾을 수 없습니다: {site_folder}")
                    else:
                        zip_base = os.path.join(tempfile.gettempdir(), st.session_state["inputs"]["sitename"])
                        with st.spinner("압축하는 중..."):
                            zip_path = shutil.make_archive(zip_base, "zip", site_folder)
                        with open(zip_path, "rb") as f:
                            st.session_state["_download_zip_bytes"] = f.read()
                        st.session_state["_download_zip_name"] = (
                            st.session_state["inputs"]["sitename"] + ".zip"
                        )
                        st.success(
                            f"압축 완료 ({len(st.session_state['_download_zip_bytes']) / 1e6:.1f} MB). "
                            "아래 버튼으로 받으세요."
                        )
                except Exception as e:
                    st.error(f"압축 실패: {e}")

            if st.session_state.get("_download_zip_bytes"):
                st.download_button(
                    "⬇️ 내 컴퓨터로 zip 다운로드",
                    data=st.session_state["_download_zip_bytes"],
                    file_name=st.session_state["_download_zip_name"],
                    mime="application/zip",
                )

# ===========================================================================
# 3. 해안선 일괄 탐지
# ===========================================================================
with tabs[3]:
    st.header("3. 해안선 일괄 탐지 (Batch shoreline detection)")
    if st.session_state["metadata"] is None:
        st.info("먼저 2단계에서 메타데이터를 준비해 주세요.")
    else:
        st.subheader("탐지 설정 (settings)")
        c1, c2, c3 = st.columns(3)
        with c1:
            cloud_thresh = st.slider("cloud_thresh (최대 구름 비율)", 0.0, 1.0, 0.1, 0.05)
            dist_clouds = st.number_input("dist_clouds (구름 주변 제외 거리, m)", value=300)
            output_epsg = st.number_input("output_epsg (출력 좌표계)", value=28356, step=1)
        with c2:
            check_detection = st.checkbox("check_detection (탐지 결과 사용자 검수)", value=False)
            adjust_detection = st.checkbox("adjust_detection (임계값 수동 조정)", value=False)
            save_figure = st.checkbox("save_figure (탐지 결과 이미지 저장)", value=True)
            cloud_mask_issue = st.checkbox("cloud_mask_issue (모래가 구름으로 오탐지됨)", value=False)
            pan_off = st.checkbox("pan_off (팬샤프닝 끄기, Landsat7/8/9)", value=False)
        with c3:
            min_beach_area = st.number_input("min_beach_area (㎡)", value=1000)
            min_length_sl = st.number_input("min_length_sl (m)", value=500)
            sand_color = st.selectbox("sand_color", ["default", "latest", "dark", "bright"])
            s2cloudless_prob = st.number_input("s2cloudless_prob (%)", value=40)

        settings = {
            "cloud_thresh": cloud_thresh,
            "dist_clouds": dist_clouds,
            "output_epsg": int(output_epsg),
            "check_detection": check_detection,
            "adjust_detection": adjust_detection,
            "save_figure": save_figure,
            "min_beach_area": min_beach_area,
            "min_length_sl": min_length_sl,
            "cloud_mask_issue": cloud_mask_issue,
            "sand_color": sand_color,
            "pan_off": pan_off,
            "s2cloudless_prob": s2cloudless_prob,
            "inputs": st.session_state["inputs"],
        }
        st.session_state["settings"] = settings

        st.markdown("---")
        colX, colY, colZ = st.columns(3)
        with colX:
            if st.button("🖼️ 전처리 이미지 저장 (JPG)", disabled=not COASTSAT_AVAILABLE):
                try:
                    with st.spinner("전처리 중..."):
                        SDS_preprocess.save_jpg(
                            st.session_state["metadata"], settings, use_matplotlib=True
                        )
                    st.success("전처리 이미지 저장 완료")
                except Exception as e:
                    st.error(f"실패: {e}")

        with colY:
            if st.button("🎞️ 타임랩스 애니메이션(GIF) 생성", disabled=not COASTSAT_AVAILABLE):
                try:
                    inputs = st.session_state["inputs"]
                    fn_animation = os.path.join(
                        inputs["filepath"], inputs["sitename"], "%s_animation_RGB.gif" % inputs["sitename"]
                    )
                    fp_images = os.path.join(inputs["filepath"], inputs["sitename"], "jpg_files", "preprocessed")
                    SDS_tools.make_animation_mp4(fp_images, 4, fn_animation)
                    st.success(f"저장됨: {fn_animation}")
                except Exception as e:
                    st.error(f"실패: {e}")

        with colZ:
            max_dist_ref = st.number_input("max_dist_ref (기준선에서 허용 거리, m)", value=100)
            if st.button("📍 기준 해안선(reference shoreline) 그리기", disabled=not COASTSAT_AVAILABLE):
                try:
                    settings["reference_shoreline"] = SDS_preprocess.get_reference_sl(
                        st.session_state["metadata"], settings
                    )
                    settings["max_dist_ref"] = max_dist_ref
                    st.session_state["settings"] = settings
                    st.success("기준 해안선 설정 완료 (지도가 새 창으로 표시됩니다)")
                except Exception as e:
                    st.error(f"실패: {e}")

        st.markdown("---")
        georef_thresh = st.number_input("지오레퍼런싱 오차 임계값 (m)", value=10)
        if st.button("🌊 해안선 추출 실행", type="primary", disabled=not COASTSAT_AVAILABLE):
            try:
                with st.spinner("해안선을 추출하는 중입니다..."):
                    output = SDS_shoreline.extract_shorelines(
                        st.session_state["metadata"], settings
                    )
                    output = SDS_tools.remove_duplicates(output)
                    output = SDS_tools.remove_inaccurate_georef(output, georef_thresh)
                st.session_state["output"] = output
                st.success(f"{len(output['shorelines'])}개의 해안선이 추출되었습니다.")
            except Exception as e:
                st.error(f"추출 실패: {e}")

        if st.session_state["output"] is not None:
            fig = plot_shorelines(st.session_state["output"], title="추출된 해안선")
            show_fig(fig)

            geomtype = st.radio("GeoJSON geometry 타입", ["lines", "points"], horizontal=True)
            if st.button("💾 GeoJSON으로 저장", disabled=not COASTSAT_AVAILABLE):
                try:
                    inputs = st.session_state["inputs"]
                    gdf = SDS_tools.output_to_gdf(st.session_state["output"], geomtype)
                    if gdf is None:
                        raise Exception("output에 매핑된 해안선이 없습니다")
                    gdf.crs = CRS(settings["output_epsg"])
                    out_path = os.path.join(
                        inputs["filepath"],
                        inputs["sitename"],
                        "%s_output_%s.geojson" % (inputs["sitename"], geomtype),
                    )
                    gdf.to_file(out_path, driver="GeoJSON", encoding="utf-8")
                    st.success(f"저장됨: {out_path}")
                except Exception as e:
                    st.error(f"저장 실패: {e}")

# ===========================================================================
# 4. 횡단면(transect) 분석
# ===========================================================================
with tabs[4]:
    st.header("4. 횡단면(Transect) 분석")
    if st.session_state["output"] is None:
        st.info("먼저 3단계에서 해안선을 추출해 주세요.")
    else:
        st.subheader("트랜섹트 정의")
        tmode = st.radio(
            "트랜섹트 입력 방식",
            ["GeoJSON 파일 업로드", "직접 좌표 입력 (원점 → 방향점)"],
            horizontal=False,
        )

        transects = None
        if tmode == "GeoJSON 파일 업로드":
            up = st.file_uploader("transects.geojson", type=["geojson", "json"], key="transect_upload")
            if up is not None and st.button("트랜섹트 불러오기", disabled=not COASTSAT_AVAILABLE):
                try:
                    tmp_path = os.path.join(tempfile.gettempdir(), up.name)
                    with open(tmp_path, "wb") as f:
                        f.write(up.getbuffer())
                    transects = SDS_tools.transects_from_geojson(tmp_path)
                    st.session_state["transects"] = transects
                    st.success(f"{len(transects)}개의 트랜섹트를 불러왔습니다")
                except Exception as e:
                    st.error(f"불러오기 실패: {e}")
        else:
            st.caption("각 트랜섹트는 [원점(x1,y1), 방향점(x2,y2)] 두 점으로 정의합니다. (좌표계는 output_epsg와 동일)")
            default_t = pd.DataFrame(
                {
                    "이름": ["NA1"],
                    "x1": [16843142.0], "y1": [-3989358.0],
                    "x2": [16843457.0], "y2": [-3989535.0],
                }
            )
            edited_t = st.data_editor(default_t, num_rows="dynamic", key="transect_editor")
            if st.button("트랜섹트 딕셔너리 생성"):
                try:
                    transects = {}
                    for _, row in edited_t.iterrows():
                        transects[row["이름"]] = np.array(
                            [[row["x1"], row["y1"]], [row["x2"], row["y2"]]]
                        )
                    st.session_state["transects"] = transects
                    st.success(f"{len(transects)}개의 트랜섹트가 생성되었습니다")
                except Exception as e:
                    st.error(f"생성 실패: {e}")

        if st.session_state["transects"] is not None:
            fig = plot_shorelines(
                st.session_state["output"], st.session_state["transects"], title="해안선 + 트랜섹트"
            )
            show_fig(fig)

            st.subheader("교차점 계산 설정 (Quality-Control)")
            c1, c2, c3 = st.columns(3)
            with c1:
                along_dist = st.number_input("along_dist (연안방향 평균 거리, m)", value=25)
                min_points = st.number_input("min_points (최소 포인트 수)", value=3)
            with c2:
                max_std = st.number_input("max_std (최대 표준편차, m)", value=15)
                max_range = st.number_input("max_range (최대 범위, m)", value=30)
            with c3:
                min_chainage = st.number_input("min_chainage (육지쪽 최대 음수값, m)", value=-100)
                multiple_inter = st.selectbox("multiple_inter (이상치 처리 방식)", ["auto", "nan", "max"])
                auto_prc = st.number_input("auto_prc", value=0.1, step=0.01, format="%.2f")

            settings_transects = {
                "along_dist": along_dist,
                "min_points": min_points,
                "max_std": max_std,
                "max_range": max_range,
                "min_chainage": min_chainage,
                "multiple_inter": multiple_inter,
                "auto_prc": auto_prc,
            }
            st.session_state["settings_transects"] = settings_transects

            if st.button("📐 교차점(cross-shore distance) 계산", type="primary", disabled=not COASTSAT_AVAILABLE):
                try:
                    cross_distance = SDS_transects.compute_intersection_QC(
                        st.session_state["output"], st.session_state["transects"], settings_transects
                    )
                    st.session_state["cross_distance"] = cross_distance
                    st.success("계산 완료")
                except Exception as e:
                    st.error(f"계산 실패: {e}")

        if st.session_state["cross_distance"] is not None:
            cross_distance = st.session_state["cross_distance"]
            output = st.session_state["output"]

            fig = plt.figure(figsize=[10, 2.5 * len(cross_distance)], tight_layout=True)
            gs = gridspec.GridSpec(len(cross_distance), 1)
            for i, key in enumerate(cross_distance.keys()):
                if np.all(np.isnan(cross_distance[key])):
                    continue
                ax = fig.add_subplot(gs[i, 0])
                ax.grid(linestyle=":", color="0.5")
                ax.set_ylim([-50, 50])
                ax.plot(output["dates"], cross_distance[key] - np.nanmedian(cross_distance[key]), "-o", ms=4, mfc="w")
                ax.set_ylabel("거리 [m]", fontsize=10)
                ax.text(0.5, 0.9, key, ha="center", va="top", transform=ax.transAxes,
                        bbox=dict(boxstyle="square", ec="k", fc="w"))
            show_fig(fig)

            out_dict = {"dates": output["dates"]}
            for key in cross_distance.keys():
                out_dict["Transect " + key] = cross_distance[key]
            df_cd = pd.DataFrame(out_dict)
            st.dataframe(df_cd, use_container_width=True)
            df_download_button(df_cd, "⬇️ 시계열 CSV 다운로드", "transect_time_series.csv")

# ===========================================================================
# 5. 조석 보정
# ===========================================================================
with tabs[5]:
    st.header("5. 조석 보정 (Tidal correction)")
    if st.session_state["cross_distance"] is None:
        st.info("먼저 4단계에서 횡단면 교차점을 계산해 주세요.")
    else:
        st.caption(
            "FES2022 전역 조석모델을 사용합니다. 사전 설정 방법: "
            "https://github.com/kvos/CoastSat/blob/master/doc/FES2022_setup"
        )
        tide_mode = st.radio("조석 데이터 소스", ["FES2022 전역 모델 사용", "직접 측정한 조석 CSV 업로드"])

        if tide_mode == "FES2022 전역 모델 사용":
            yaml_path = st.text_input(
                "fes2022.yaml 경로 (전체 모델 로드용)",
                value=os.path.join(os.pardir, "CoastSat.webgis", "aviso-fes-main", "data", "fes2022b", "fes2022.yaml"),
            )
            band_configs_path = st.text_input(
                "band_configs.json 경로 (저사양 RAM용, 위도별 클리핑 모델)",
                value=os.path.join(os.getcwd(), "examples", "tide_model_clipping", "fes2022_by_latitude", "band_configs.json"),
            )
            use_low_ram = st.checkbox("RAM이 부족하여 위도별 클리핑 모델 사용", value=True)

            if st.button("🌐 조석 모델 로드", disabled=not COASTSAT_AVAILABLE):
                try:
                    import pyfes
                    inputs = st.session_state["inputs"]
                    polygon = inputs["polygon"]
                    centroid = np.mean(polygon[0], axis=0)
                    if centroid[0] < 0:
                        centroid[0] += 360

                    selected_yaml = yaml_path
                    if use_low_ram:
                        with open(band_configs_path, "r") as f:
                            band_configs = json.load(f)
                        selected_band = SDS_slope.select_yaml_for_centroid(centroid, band_configs)
                        selected_yaml = selected_band["yaml"]

                    if int(pyfes.__version__.split(".")[0]) < 2026:
                        handlers = pyfes.load_config(selected_yaml)
                        ocean_tide = handlers["tide"]
                        load_tide = handlers["radial"]
                    else:
                        config = pyfes.config.load(selected_yaml)
                        ocean_tide = config.models["tide"]
                        load_tide = config.models["radial"]

                    st.session_state["centroid"] = centroid
                    st.session_state["ocean_tide"] = ocean_tide
                    st.session_state["load_tide"] = load_tide
                    st.success("조석 모델 로드 완료")
                except Exception as e:
                    st.error(f"로드 실패: {e}")

            if st.session_state.get("ocean_tide") is not None:
                timestep = st.number_input("타임스텝 (초)", value=900, step=100)
                if st.button("📈 조석 시계열 계산", disabled=not COASTSAT_AVAILABLE):
                    try:
                        output = st.session_state["output"]
                        inputs = st.session_state["inputs"]
                        d0 = datetime.strptime(inputs["dates"][0], "%Y-%m-%d")
                        d1 = datetime.strptime(inputs["dates"][1], "%Y-%m-%d")
                        date_range = [pytz.utc.localize(d0), pytz.utc.localize(d1)]
                        dates_ts, tides_ts = SDS_slope.compute_tide(
                            st.session_state["centroid"], date_range, timestep,
                            st.session_state["ocean_tide"], st.session_state["load_tide"],
                        )
                        tides_sat = SDS_slope.compute_tide_dates(
                            st.session_state["centroid"], output["dates"],
                            st.session_state["ocean_tide"], st.session_state["load_tide"],
                        )
                        st.session_state["dates_ts"] = dates_ts
                        st.session_state["tides_ts"] = tides_ts
                        st.session_state["tides_sat"] = tides_sat
                        st.success("조석 시계열 계산 완료")
                    except Exception as e:
                        st.error(f"계산 실패: {e}")
        else:
            up = st.file_uploader("조석 CSV (dates, tide 컬럼, UTC 기준)", type=["csv"])
            if up is not None and st.button("📈 CSV에서 조석 데이터 불러오기", disabled=not COASTSAT_AVAILABLE):
                try:
                    tide_data = pd.read_csv(up, parse_dates=["dates"])
                    dates_ts = [pd.to_datetime(x).to_pydatetime() for x in tide_data["dates"]]
                    tides_ts = np.array(tide_data["tide"])
                    output = st.session_state["output"]
                    tides_sat = SDS_tools.get_closest_datapoint(output["dates"], dates_ts, tides_ts)
                    st.session_state["dates_ts"] = dates_ts
                    st.session_state["tides_ts"] = tides_ts
                    st.session_state["tides_sat"] = tides_sat
                    st.success("조석 데이터 로드 완료")
                except Exception as e:
                    st.error(f"불러오기 실패: {e}")

        if st.session_state.get("tides_sat") is not None:
            output = st.session_state["output"]
            fig, ax = plt.subplots(1, 1, figsize=(10, 3.5), tight_layout=True)
            ax.grid(which="major", linestyle=":", color="0.5")
            ax.plot(st.session_state["dates_ts"], st.session_state["tides_ts"], "-", color="0.6", label="전체 시계열")
            ax.plot(output["dates"], st.session_state["tides_sat"], "-o", color="k", ms=5, mfc="w", lw=1, label="영상 촬영 시점")
            ax.set(ylabel="조위 [m]", title="영상 촬영 시점의 조위")
            ax.legend()
            show_fig(fig)

            st.subheader("보정 적용")
            reference_elevation = st.number_input("reference_elevation (기준 고도, m)", value=0.7)
            beach_slope = st.number_input("beach_slope (해변 경사)", value=0.1)

            if st.button("🌊 조석 보정 적용", type="primary", disabled=not COASTSAT_AVAILABLE):
                try:
                    cross_distance = st.session_state["cross_distance"]
                    tides_sat = st.session_state["tides_sat"]
                    corrected = {}
                    correction = (tides_sat - reference_elevation) / beach_slope
                    for key in cross_distance.keys():
                        corrected[key] = cross_distance[key] + correction
                    st.session_state["cross_distance_corrected"] = corrected
                    st.success("조석 보정 완료")
                except Exception as e:
                    st.error(f"보정 실패: {e}")

        if st.session_state["cross_distance_corrected"] is not None:
            output = st.session_state["output"]
            cross_distance = st.session_state["cross_distance"]
            corrected = st.session_state["cross_distance_corrected"]

            fig = plt.figure(figsize=[10, 2.5 * len(cross_distance)], tight_layout=True)
            gs = gridspec.GridSpec(len(cross_distance), 1)
            for i, key in enumerate(cross_distance.keys()):
                if np.all(np.isnan(cross_distance[key])):
                    continue
                ax = fig.add_subplot(gs[i, 0])
                ax.grid(linestyle=":", color="0.5")
                ax.set_ylim([-50, 50])
                med = np.nanmedian(cross_distance[key])
                ax.plot(output["dates"], cross_distance[key] - med, "-o", ms=5, mfc="w", label="원본")
                ax.plot(output["dates"], corrected[key] - med, "-o", ms=5, mfc="w", label="조석보정")
                ax.set_ylabel("거리 [m]", fontsize=10)
                ax.text(0.5, 0.9, key, ha="center", va="top", transform=ax.transAxes,
                        bbox=dict(boxstyle="square", ec="k", fc="w"))
            plt.legend()
            show_fig(fig)

            out_dict = {"dates": output["dates"]}
            for key in corrected.keys():
                out_dict["Transect " + key] = corrected[key]
            df_corr = pd.DataFrame(out_dict)
            st.dataframe(df_corr, use_container_width=True)
            df_download_button(df_corr, "⬇️ 조석보정 시계열 CSV 다운로드", "transect_time_series_tidally_corrected.csv")

# ===========================================================================
# 6. 시계열 후처리
# ===========================================================================
with tabs[6]:
    st.header("6. 시계열 후처리 (이상치 제거 · 계절/월별 평균)")
    src = st.session_state["cross_distance_corrected"] or st.session_state["cross_distance"]
    if src is None:
        st.info("먼저 4~5단계에서 시계열을 계산해 주세요. (조석보정본이 있으면 우선 사용)")
    else:
        output = st.session_state["output"]
        st.subheader("6.1 이상치 제거 (despiking)")
        c1, c2 = st.columns(2)
        with c1:
            otsu_min = st.number_input("otsu_threshold 최소값", value=-0.5, step=0.1)
            otsu_max = st.number_input("otsu_threshold 최대값", value=0.0, step=0.1)
        with c2:
            max_cross_change = st.number_input("max_cross_change (연속 관측 최대 변화량, m)", value=40)
            plot_fig_outlier = st.checkbox("중간 결과 플롯 표시", value=False)

        if st.button("🧹 이상치 제거 실행", disabled=not COASTSAT_AVAILABLE):
            try:
                settings_outliers = {
                    "otsu_threshold": [otsu_min, otsu_max],
                    "max_cross_change": max_cross_change,
                    "plot_fig": plot_fig_outlier,
                }
                cleaned = SDS_transects.reject_outliers(dict(src), output, settings_outliers)
                st.session_state["cross_distance_clean"] = cleaned
                st.success("이상치 제거 완료")
            except Exception as e:
                st.error(f"실패: {e}")

        clean = st.session_state.get("cross_distance_clean", src)

        st.markdown("---")
        st.subheader("6.2 / 6.3 계절별 · 월별 평균")
        if clean:
            key_sel = st.selectbox("트랜섹트 선택", list(clean.keys()))
            avg_mode = st.radio("평균 방식", ["계절별 (DJF/MAM/JJA/SON)", "월별"], horizontal=True)
            if st.button("📊 평균 계산 및 플롯", disabled=not COASTSAT_AVAILABLE):
                try:
                    dates = output["dates"]
                    chainage = np.array(clean[key_sel])
                    idx_nan = np.isnan(chainage)
                    dates_nonan = [dates[i] for i in np.where(~idx_nan)[0]]
                    chainage_nonan = chainage[~idx_nan]

                    fig, ax = plt.subplots(1, 1, figsize=[10, 4], tight_layout=True)
                    ax.grid(which="major", linestyle=":", color="0.5")
                    ax.set_title(f"시계열: {key_sel}", x=0, ha="left")
                    ax.set(ylabel="거리 [m]")
                    ax.plot(dates_nonan, chainage_nonan, "+", lw=1, color="k", mfc="w", ms=4, alpha=0.5, label="원자료")

                    if avg_mode.startswith("계절"):
                        dict_seas, dates_seas, chainage_seas, list_seas = SDS_transects.seasonal_average(
                            dates_nonan, chainage_nonan
                        )
                        ax.plot(dates_seas, chainage_seas, "-", lw=1, color="k", label="계절평균")
                        season_colors = {"DJF": "C3", "MAM": "C1", "JJA": "C2", "SON": "C0"}
                        for seas in dict_seas.keys():
                            ax.plot(dict_seas[seas]["dates"], dict_seas[seas]["chainages"], "o",
                                    mec="k", color=season_colors.get(seas, "C0"), label=seas, ms=5)
                    else:
                        dict_month, dates_month, chainage_month, list_month = SDS_transects.monthly_average(
                            dates_nonan, chainage_nonan
                        )
                        ax.plot(dates_month, chainage_month, "-", lw=1, color="k", label="월평균")

                    ax.legend(loc="lower left", ncol=6, fontsize=8)
                    show_fig(fig)
                except Exception as e:
                    st.error(f"실패: {e}")

# ===========================================================================
# 7. 해변경사 추정
# ===========================================================================
with tabs[7]:
    st.header("7. 해변경사(Beach slope) 추정")
    st.caption("자세한 방법론: https://github.com/kvos/CoastSat.slope")
    src = st.session_state.get("cross_distance_clean") or st.session_state["cross_distance"]
    if src is None or st.session_state.get("tides_sat") is None:
        st.info("먼저 4~6단계(횡단면 시계열)와 5단계(조석 데이터)가 준비되어야 합니다.")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            slope_min = st.number_input("slope_min", value=0.035, format="%.3f")
            slope_max = st.number_input("slope_max", value=0.2, format="%.3f")
            delta_slope = st.number_input("delta_slope", value=0.005, format="%.3f")
        with c2:
            n0 = st.number_input("n0 (Nyquist 파라미터)", value=50)
            prc_conf = st.number_input("prc_conf (신뢰구간 %)", value=0.05, format="%.2f")
            n_days = st.number_input("n_days (샘플링 주기, 일)", value=8)
        with c3:
            year_start = st.number_input("분석 시작 연도", value=1999, step=1)
            year_end = st.number_input("분석 종료 연도", value=2022, step=1)

        if st.button("📐 해변경사 추정 실행", type="primary", disabled=not COASTSAT_AVAILABLE):
            try:
                output = st.session_state["output"]
                days_in_year = 365.2425
                seconds_in_day = 24 * 3600
                settings_slope = {
                    "slope_min": slope_min,
                    "slope_max": slope_max,
                    "delta_slope": delta_slope,
                    "n0": n0,
                    "freq_cutoff": 1.0 / (seconds_in_day * 30),
                    "delta_f": 100 * 1e-10,
                    "prc_conf": prc_conf,
                    "plot_fig": True,
                }
                beach_slopes = SDS_slope.range_slopes(slope_min, slope_max, delta_slope)

                settings_slope["date_range"] = [
                    pytz.utc.localize(datetime(int(year_start), 5, 1)),
                    pytz.utc.localize(datetime(int(year_end), 1, 1)),
                ]
                idx_dates = [
                    np.logical_and(d > settings_slope["date_range"][0], d < settings_slope["date_range"][1])
                    for d in output["dates"]
                ]
                dates_sat = [output["dates"][i] for i in np.where(idx_dates)[0]]
                cross_distance = {k: np.array(v)[idx_dates] for k, v in src.items()}
                settings_slope["n_days"] = n_days

                tides_sat_full = st.session_state["tides_sat"]
                tides_sat = np.array(tides_sat_full)[idx_dates] if len(tides_sat_full) == len(output["dates"]) else tides_sat_full

                settings_slope["freqs_max"] = SDS_slope.find_tide_peak(dates_sat, tides_sat, settings_slope)

                slope_est, cis = {}, {}
                progress = st.progress(0.0)
                keys = list(cross_distance.keys())
                for idx, key in enumerate(keys):
                    chain = cross_distance[key]
                    idx_nan = np.isnan(chain)
                    d_ = [dates_sat[i] for i in np.where(~idx_nan)[0]]
                    tide_ = tides_sat[~idx_nan]
                    composite = chain[~idx_nan]
                    tsall = SDS_slope.tide_correct(composite, tide_, beach_slopes)
                    slope_est[key], cis[key] = SDS_slope.integrate_power_spectrum(d_, tsall, settings_slope, key)
                    progress.progress((idx + 1) / len(keys))

                st.session_state["slope_est"] = slope_est
                st.session_state["slope_cis"] = cis
                st.success("해변경사 추정 완료")
            except Exception as e:
                st.error(f"추정 실패: {e}")

        if st.session_state["slope_est"] is not None:
            rows = []
            for key, val in st.session_state["slope_est"].items():
                ci = st.session_state["slope_cis"][key]
                rows.append({"트랜섹트": key, "추정 경사": round(float(val), 4),
                             "95% CI 하한": round(float(ci[0]), 4), "95% CI 상한": round(float(ci[1]), 4)})
            df_slope = pd.DataFrame(rows)
            st.dataframe(df_slope, use_container_width=True)
            df_download_button(df_slope, "⬇️ 해변경사 결과 CSV 다운로드", "beach_slope_estimates.csv")

# ===========================================================================
# 8. 현장관측(survey) 비교
# ===========================================================================
with tabs[8]:
    st.header("8. 현장관측 데이터와 비교/검증")
    st.caption("예: Narrabeen 현장관측 자료 (http://narrabeen.wrl.unsw.edu.au/)")

    up = st.file_uploader("현장관측 CSV (Profile ID, Date, Chainage, Elevation 컬럼)", type=["csv"])
    contour_level = st.number_input("등고선(contour) 레벨 (m)", value=0.7)

    if up is not None and st.button("📥 현장관측 자료 처리", disabled=(interpolate is None)):
        try:
            df = pd.read_csv(up)
            pf_names = list(np.unique(df["Profile ID"]))
            topo_profiles = {}
            for name in pf_names:
                df_pf = df.loc[df["Profile ID"] == name]
                dates_str = df["Date"]
                dates_unique = np.unique(df_pf["Date"])
                topo_profiles[name] = {"dates": [], "chainages": []}
                for date in dates_unique:
                    df_date = df_pf.loc[df_pf["Date"] == date]
                    chainages = np.array(df_date["Chainage"])
                    elevations = np.array(df_date["Elevation"])
                    if len(chainages) == 0:
                        continue
                    f = interpolate.interp1d(elevations, chainages, bounds_error=False)
                    chainage_contour = f(contour_level)
                    topo_profiles[name]["chainages"].append(chainage_contour)
                    date_utc = pytz.utc.localize(datetime.strptime(date, "%Y-%m-%d"))
                    topo_profiles[name]["dates"].append(date_utc)
            st.session_state["topo_profiles"] = topo_profiles
            st.success(f"{len(pf_names)}개 프로파일 처리 완료")
        except Exception as e:
            st.error(f"처리 실패: {e}")

    if st.session_state["topo_profiles"] is not None:
        topo_profiles = st.session_state["topo_profiles"]
        fig = plt.figure(figsize=[10, 2.5 * len(topo_profiles)], tight_layout=True)
        gs = gridspec.GridSpec(len(topo_profiles), 1)
        for i, key in enumerate(topo_profiles.keys()):
            ax = fig.add_subplot(gs[i, 0])
            ax.grid(linestyle=":", color="0.5")
            ax.plot(topo_profiles[key]["dates"], topo_profiles[key]["chainages"], "-o", ms=4, mfc="w")
            ax.set_ylabel("거리 [m]", fontsize=10)
            ax.text(0.5, 0.9, key, ha="center", va="top", transform=ax.transAxes,
                    bbox=dict(boxstyle="square", ec="k", fc="w"))
        show_fig(fig)

        st.markdown("---")
        st.subheader("위성 시계열과 비교")
        src = st.session_state.get("cross_distance_clean") or st.session_state["cross_distance"]
        output = st.session_state["output"]
        if src is None or output is None:
            st.info("위성 시계열(4~6단계)이 준비되어야 비교할 수 있습니다.")
        else:
            transect_keys = list(src.keys())
            survey_keys = list(topo_profiles.keys())
            key_map = st.data_editor(
                pd.DataFrame({"위성 트랜섹트": transect_keys[: len(survey_keys)], "현장관측 프로파일": survey_keys[: len(transect_keys)]}),
                num_rows="dynamic",
                key="key_mapping",
            )

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                min_days = st.number_input("min_days", value=3)
            with c2:
                max_days = st.number_input("max_days", value=10)
            with c3:
                binwidth = st.number_input("binwidth", value=3)
            with c4:
                lim = st.number_input("plot lim (±m)", value=50)

            if st.button("📊 비교 실행", type="primary", disabled=(stats is None)):
                try:
                    sett = {"min_days": min_days, "max_days": max_days, "binwidth": binwidth, "lims": [-lim, lim]}
                    results = []
                    for _, row in key_map.iterrows():
                        tkey, skey = row["위성 트랜섹트"], row["현장관측 프로파일"]
                        if tkey not in src or skey not in topo_profiles:
                            continue
                        chainage = np.array(src[tkey])
                        idx_nan = np.isnan(chainage)
                        dates_nonan = [output["dates"][k] for k in np.where(~idx_nan)[0]]
                        chain_nonans = chainage[~idx_nan]

                        gt = topo_profiles[skey]
                        chain_int = np.nan * np.ones(len(dates_nonan))
                        for k, date in enumerate(dates_nonan):
                            days_diff = np.array([(d - date).days for d in gt["dates"]])
                            if len(days_diff) == 0 or np.min(np.abs(days_diff)) > sett["max_days"]:
                                chain_int[k] = np.nan
                            elif np.min(np.abs(days_diff)) < sett["min_days"]:
                                idx_closest = np.where(np.abs(days_diff) == np.min(np.abs(days_diff)))
                                chain_int[k] = float(np.array(gt["chainages"])[idx_closest[0][0]])
                            else:
                                if np.sum(days_diff > 0) == 0:
                                    continue
                                idx_after = np.where(days_diff > 0)[0][0]
                                idx_before = idx_after - 1
                                x = [gt["dates"][idx_before].toordinal(), gt["dates"][idx_after].toordinal()]
                                y = [gt["chainages"][idx_before], gt["chainages"][idx_after]]
                                f = interpolate.interp1d(x, y, bounds_error=True)
                                chain_int[k] = float(f(date.toordinal()))

                        idx_nan2 = np.isnan(chain_int)
                        chain_sat = chain_nonans[~idx_nan2]
                        chain_sur = chain_int[~idx_nan2]
                        if len(chain_sat) < 2:
                            continue
                        slope, intercept, rvalue, pvalue, std_err = stats.linregress(chain_sur, chain_sat)
                        chain_error = chain_sat - chain_sur
                        rmse = float(np.sqrt(np.mean(chain_error ** 2)))
                        mean_e = float(np.mean(chain_error))
                        std_e = float(np.std(chain_error))
                        q90 = float(np.percentile(np.abs(chain_error), 90))
                        results.append({
                            "트랜섹트": tkey, "프로파일": skey, "R²": round(rvalue ** 2, 3),
                            "RMSE(m)": round(rmse, 2), "평균오차(m)": round(mean_e, 2),
                            "표준편차(m)": round(std_e, 2), "90퍼센타일 오차(m)": round(q90, 2), "n": len(chain_sat),
                        })
                    if results:
                        df_res = pd.DataFrame(results)
                        st.dataframe(df_res, use_container_width=True)
                        df_download_button(df_res, "⬇️ 비교 결과 CSV 다운로드", "survey_comparison_stats.csv")
                    else:
                        st.warning("비교 가능한 데이터가 없습니다. 매칭 및 기간을 확인해 주세요.")
                except Exception as e:
                    st.error(f"비교 실패: {e}")

st.markdown("---")
st.caption(
    "이 GUI는 CoastSat(Kilian Vos, WRL 2018)의 example.py 파이프라인을 감싼 인터페이스입니다. "
    "각 버튼은 원본 스크립트의 해당 단계 함수를 그대로 호출합니다."
)
