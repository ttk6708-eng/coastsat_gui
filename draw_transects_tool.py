"""
마우스로 트랜섹트(횡단면)를 그리는 콘솔 도구.

Streamlit 웹앱은 화면에 창을 띄울 수 없는 matplotlib 백엔드(Agg)를 쓰기 때문에
CoastSat 원본의 마우스 클릭 방식 트랜섹트 그리기(draw_transects)를 브라우저에서는
쓸 수 없습니다. 이 스크립트는 웹앱이 아니라 이 콘솔에서 직접 실행해서,
실제 창을 띄우고 마우스로 클릭해 트랜섹트를 그릴 수 있게 해줍니다.

사용법:
    venv\\Scripts\\python.exe draw_transects_tool.py --site-dir "저장폴더\\사이트이름" --shorelines "사이트이름_output_lines.geojson"

--site-dir: app.py의 2~3단계에서 쓴 데이터 저장 폴더 중 이 사이트의 하위 폴더
            (예: C:\\coastsat_data\\NARRA3, jpg_files 폴더가 그 안에 있어야 함)
--shorelines: app.py의 3단계에서 "GeoJSON으로 저장" 버튼으로 저장한
              *_output_lines.geojson 또는 *_output_points.geojson 파일 경로

실행하면 지도 창이 뜹니다:
    - 두 점을 클릭해 트랜섹트 하나를 정의 (첫 클릭 = 육지쪽 시작점, 두번째 클릭 = 바다쪽 끝점)
    - 계속 클릭해서 트랜섹트를 여러 개 추가
    - 다 그렸으면 Enter를 누르면 저장되고 창이 닫힘

결과는 site-dir 안에 {사이트이름}_transects.geojson 으로 저장됩니다.
이 파일을 웹앱의 "4. 횡단면(Transect) 분석" 탭에서 업로드하면 됩니다.
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import geopandas as gpd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coastsat import SDS_transects


def load_output_from_geojson(path):
    gdf = gpd.read_file(path)
    shorelines = []
    dates = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom.geom_type == "LineString":
            coords = list(geom.coords)
        elif geom.geom_type == "MultiPoint":
            coords = [(p.x, p.y) for p in geom.geoms]
        else:
            raise ValueError(f"지원하지 않는 geometry 타입입니다: {geom.geom_type}")
        shorelines.append(np.array(coords))
        date_val = row.get("date", "")
        if hasattr(date_val, "to_pydatetime"):
            date = date_val.to_pydatetime()
        else:
            try:
                date = datetime.strptime(date_val, "%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError):
                date = datetime(1970, 1, 1)
        dates.append(date)

    epsg = gdf.crs.to_epsg() if gdf.crs is not None else None
    return {"shorelines": shorelines, "dates": dates}, epsg


def main():
    parser = argparse.ArgumentParser(description="마우스로 트랜섹트 그리기 (콘솔 전용)")
    parser.add_argument("--site-dir", required=True, help="이 사이트의 데이터 폴더 (jpg_files가 들어있는 폴더)")
    parser.add_argument("--shorelines", required=True, help="3단계에서 저장한 *_output_lines(or points).geojson 경로")
    parser.add_argument("--epsg", type=int, default=None, help="output_epsg (생략하면 geojson의 CRS에서 자동 인식)")
    args = parser.parse_args()

    site_dir = os.path.abspath(args.site_dir)
    sitename = os.path.basename(site_dir.rstrip("\\/"))
    filepath = os.path.dirname(site_dir)

    os.makedirs(os.path.join(site_dir, "jpg_files"), exist_ok=True)

    output, epsg_from_file = load_output_from_geojson(args.shorelines)
    epsg = args.epsg or epsg_from_file
    if epsg is None:
        print("경고: geojson에 CRS 정보가 없어서 output_epsg를 알 수 없습니다. --epsg 옵션으로 지정해주세요.")
        sys.exit(1)

    settings = {
        "inputs": {"sitename": sitename, "filepath": filepath},
        "output_epsg": epsg,
    }

    print(f"사이트: {sitename}")
    print(f"저장 위치: {os.path.join(site_dir, sitename + '_transects.geojson')}")
    print("지도 창이 뜨면: 두 점씩 클릭해서 트랜섹트를 그리고, 다 그렸으면 Enter를 누르세요.")

    transects = SDS_transects.draw_transects(output, settings)
    print(f"{len(transects)}개의 트랜섹트가 저장되었습니다.")


if __name__ == "__main__":
    main()
