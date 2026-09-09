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
# 1. 초기 설정
# ===========================================================================
with tabs[0]:
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
            ["대화형 인증 (로컬 PC 실행용)", "서비스 계정 (GitHub/Streamlit Cloud 배포용)"],
            help="서버에 배포하면 브라우저 로그인 창을 띄울 수 없으므로 서비스 계정 방식을 사용해야 합니다.",
        )

        if auth_mode.startswith("대화형"):
            if st.button("🔐 GEE 인증 및 초기화 (대화형)", disabled=not COASTSAT_AVAILABLE):
                try:
                    SDS_download.authenticate_and_initialize(project_name)
                    st.success("GEE 인증 완료")
                except Exception as e:
                    st.error(f"인증 실패: {e}")
        else:
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
                        key_path = "/tmp/gee_service_account.json"
                        with open(key_path, "wb") as f:
                            f.write(key_bytes)
                        key_json = json.loads(key_bytes)
                        email = sa_email or key_json.get("client_email")
                        credentials = ee.ServiceAccountCredentials(email, key_path)
                    elif hasattr(st, "secrets") and "gee_service_account_key" in st.secrets:
                        # Streamlit Cloud Secrets에 JSON 문자열로 등록해둔 경우
                        key_json_str = st.secrets["gee_service_account_key"]
                        key_path = "/tmp/gee_service_account.json"
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
                    st.success("서비스 계정으로 GEE 인증 완료")
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
                tmp_path = os.path.join("/tmp", up.name)
                with open(tmp_path, "wb") as f:
                    f.write(up.getbuffer())
                st.session_state["_polygon_geojson_path"] = tmp_path
                st.success(f"업로드됨: {up.name}")
        else:
            up = st.file_uploader("polygon.kml", type=["kml"])
            if up is not None:
                tmp_path = os.path.join("/tmp", up.name)
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
        if st.button("📊 사용 가능한 영상 개수 확인", disabled=not COASTSAT_AVAILABLE):
            try:
                SDS_download.check_images_available(st.session_state["inputs"])
                st.success("콘솔/터미널 로그에서 결과를 확인하세요.")
            except Exception as e:
                st.error(f"확인 실패: {e}")

# ===========================================================================
# 2. 영상 수집
# ===========================================================================
with tabs[1]:
    st.header("2. 위성 영상 수집")
    if st.session_state["inputs"] is None:
        st.info("먼저 1단계에서 입력값을 확정해 주세요.")
    else:
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

# ===========================================================================
# 3. 해안선 일괄 탐지
# ===========================================================================
with tabs[2]:
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
with tabs[3]:
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
                    tmp_path = os.path.join("/tmp", up.name)
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
with tabs[4]:
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
with tabs[5]:
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
with tabs[6]:
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
with tabs[7]:
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
