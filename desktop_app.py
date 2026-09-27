"""Separate desktop entrypoint; legacy app.py is intentionally preserved."""
from datetime import date, timedelta
from pathlib import Path
import json
import os
import uuid

import pandas as pd
import streamlit as st

from desktop import jobs
from desktop.processing import inspect, NAMES, scan_coastsat
from desktop.preview import scene_signature, blended_preview

st.set_page_config(page_title='CoastSat · 위성영상 전처리', page_icon='🌊', layout='wide')
st.markdown('''<style>
.stApp {background:#f5f8fb} [data-testid="stSidebar"] {background:#eaf1f7}
h1,h2,h3 {color:#14384a} .stButton button[kind="primary"] {background:#087d8c;border:0}
.block-container {padding-top:2rem;max-width:1240px}
</style>''', unsafe_allow_html=True)
st.title('위성영상 전처리')
st.caption('CoastSat Desktop · 파일 불러오기 또는 위성영상 수집 → 전처리 → 결과 저장')
root = jobs.state_root()
with st.sidebar:
    st.header('작업 선택')
    page = st.radio('입력 방법', ['내 파일 전처리', 'Google에서 영상 수집', 'CoastSat 폴더 전처리'], label_visibility='collapsed')
    st.divider()
    st.write('해안선 탐지 이전 단계까지 처리합니다.')
    st.caption('내 파일과 CoastSat 폴더는 로그인 없이 사용할 수 있습니다.')
    st.caption('CoastSat: Kilian Vos 외 · GPL-3.0')
    st.link_button('원본 프로젝트', 'https://github.com/kvos/CoastSat')

active = st.session_state.get('job')
busy = bool(active and jobs.status(active)['state'] == 'running')
if active:
    completed_state = jobs.status(active)
    if completed_state.get('preview'):
        st.session_state[f'preview_{completed_state["preview_context"]}'] = completed_state['preview']


def begin(spec):
    if busy:
        st.warning('현재 작업이 끝나거나 중지된 후 시작해 주세요.')
    else:
        if spec['mode'] in ('authenticate', 'check'):
            st.session_state.pop('connected_project', None)
        st.session_state['job'] = jobs.start(spec)
        st.rerun()


def output_path():
    return st.text_input('결과 저장 폴더', value=str(root / 'results'), key=f'output_{page}')


def preview_panel(scene, context):
    st.subheader('미리보기 · 설정 비교')
    st.caption('설정을 바꾼 뒤 갱신 버튼을 누르세요. 한 장면을 실제 저장과 같은 해상도로 계산하고 화면만 축소해 보여줍니다. 최종 GeoTIFF는 저장하지 않습니다.')
    if st.button('미리보기 갱신', key=f'preview_run_{context}', disabled=busy or scene is None):
        try:
            begin({'mode':'preview', 'scene':scene, 'signature':scene_signature(scene), 'preview_context':context})
        except Exception as error:
            st.error(str(error))
    preview = st.session_state.get(f'preview_{context}')
    if not preview:
        st.info('입력과 밴드를 지정하고 미리보기를 갱신하면 여기에 비교 화면이 표시됩니다.')
        return
    try:
        stale = scene is None or preview['signature'] != scene_signature(scene)
    except (OSError, ValueError):
        stale = True
    if stale:
        st.warning('설정 또는 입력 파일이 변경되었습니다. 아래는 이전 설정의 미리보기입니다. 갱신 버튼을 눌러 다시 확인하세요.')
    else:
        st.success('현재 설정과 일치하는 미리보기입니다.')
    shown = preview['scene']
    threshold_text = f"구름 확률 기준 {shown.get('cloud_threshold',40)}%" if shown.get('probability') else '확률 기준 미사용'
    st.caption(f"표시 장면: {shown['name']} · {threshold_text} · 구름 제외 {'켜짐' if shown.get('apply_cloud_mask',True) else '꺼짐'} · 선명화 {'켜짐' if shown.get('pan') else '꺼짐'}")
    overlay = st.checkbox('구름·결측 마스크 겹쳐 보기', value=True, key=f'preview_overlay_{context}')
    opacity = st.slider('마스크 투명도 · 오른쪽으로 갈수록 색이 진해집니다', 0, 100, 45, key=f'preview_opacity_{context}', disabled=not overlay) / 100
    left, right = st.columns(2)
    folder = Path(preview['folder'])
    if overlay:
        left.image(blended_preview(folder, 'before', opacity), caption='원본 보기 · 구름 제외·선명화 전', width='stretch')
        right.image(blended_preview(folder, 'after', opacity), caption='처리 결과 · 위에 표시된 설정', width='stretch')
        st.caption('주황: 구름 / 회색: 결측 / 보라: 구름 정보 미확인. 겹쳐 보기는 결과 파일의 값을 바꾸지 않습니다.')
    else:
        left.image(str(folder / 'before.png'), caption='원본 보기 · 구름 제외·선명화 전', width='stretch')
        right.image(str(folder / 'after.png'), caption='처리 결과 · 위에 표시된 설정', width='stretch')
    st.caption('원본 보기는 비교를 위해 밴드 정렬·스케일을 적용한 영상입니다. 두 화면은 같은 명암 기준을 사용합니다. 제외 픽셀은 검정으로 표시합니다.')
    a,b,c,d = st.columns(4)
    a.metric('남는 픽셀', f"{preview['valid_percent']:.1f}%")
    b.metric('구름', '정보 없음' if preview['cloud_percent'] is None else f"{preview['cloud_percent']:.1f}%")
    c.metric('구름 미확인', f"{preview['unknown_percent']:.1f}%")
    d.metric('결측', f"{preview['nodata_percent']:.1f}%")
    st.caption('비율은 전체 출력 픽셀 수를 기준으로 계산합니다.')
    for warning in preview['warnings']:
        st.warning(warning)
    if not preview['can_export']:
        st.error('남는 픽셀이 없습니다. 구름 기준이나 제외 설정을 조정한 뒤 다시 확인하세요.')


if page == '내 파일 전처리':
    st.subheader('1. 파일 불러오기')
    st.write('GeoTIFF(.tif/.tiff) 또는 좌표정보가 있는 JP2 파일을 사용할 수 있습니다.')
    path_text = st.text_area('파일 경로 · 여러 파일은 한 줄에 하나씩', placeholder='D:\\위성영상\\image.tif')
    uploads = st.file_uploader('또는 파일을 여기에 놓으세요 · 파일당 최대 1GB', type=['tif', 'tiff', 'jp2'], accept_multiple_files=True)
    if st.button('파일 확인', disabled=busy):
        try:
            paths = [x.strip().strip('"') for x in path_text.splitlines() if x.strip()]
            if uploads:
                upload_dir = root / 'imports' / uuid.uuid4().hex
                upload_dir.mkdir(parents=True)
                for uploaded in uploads:
                    target = upload_dir / Path(uploaded.name).name
                    target.write_bytes(uploaded.getbuffer())
                    paths.append(str(target))
            if not paths:
                raise ValueError('파일을 추가해 주세요.')
            st.session_state['rasters'] = [inspect(path) for path in paths]
            st.session_state['input_revision'] = uuid.uuid4().hex
        except Exception as error:
            st.error(str(error))
    rasters = st.session_state.get('rasters', [])
    if rasters:
        st.dataframe(pd.DataFrame([{'파일': Path(r['path']).name, '너비': r['width'], '높이': r['height'], '밴드 수': r['bands']} for r in rasters]), hide_index=True)
        st.subheader('2. 밴드와 처리 설정')
        st.info('파일 이름만으로 밴드를 추측하지 않습니다. 각 파일의 밴드 설명을 확인하고 직접 지정해 주세요. 서로 다른 날짜의 영상은 한 장면으로 섞지 마세요.')
        with st.expander('파일별 밴드 설명 확인'):
            for raster in rasters:
                st.write(raster['path'])
                st.json(raster['descriptions'])
        rgb_only = st.checkbox('RGB 3개 밴드만 처리 · NIR/SWIR1 없음', value=False)
        required = NAMES[:3] if rgb_only else NAMES
        choices = {f'{i+1}. {Path(r["path"]).name} / 밴드 {b}': {'path': r['path'], 'band': b}
                   for i, r in enumerate(rasters) for b in range(1, r['bands'] + 1)}
        selected = []
        for name in required:
            choice = st.selectbox(name, ['선택해 주세요'] + list(choices), key=f'{st.session_state["input_revision"]}_{name}')
            selected.append(choices.get(choice))
        satellite = st.selectbox('위성 종류', ['OTHER', 'L5', 'L7', 'L8', 'L9', 'S2'],
                                 format_func=lambda x: {'OTHER':'기타 / 모름', 'S2':'Sentinel-2'}.get(x, 'Landsat '+x[1:]))
        qa_type = st.selectbox('구름 정보 형식', ['없음', 'binary', 'landsat_qa_pixel', 's2_qa60', 's2_scl', 's2cloudless'],
            format_func=lambda x: {'없음':'없음 · 구름 판정 없이 처리', 'binary':'구름 마스크 (0=맑음, 그 외=구름)',
            'landsat_qa_pixel':'Landsat Collection 2 QA_PIXEL', 's2_qa60':'Sentinel-2 QA60', 's2_scl':'Sentinel-2 SCL', 's2cloudless':'s2cloudless 확률 (0~100)'}.get(x, x))
        qa_choice = None
        if qa_type != '없음':
            qa_choice = st.selectbox('구름 정보 밴드', ['선택해 주세요'] + list(choices))
        else:
            st.warning('구름 정보가 없으면 구름은 제거되지 않습니다. 결측 처리·밴드 정렬은 가능합니다.')
        threshold = st.slider('구름 확률 기준 (%)', 0, 100, 40) if qa_type == 's2cloudless' else 40
        if qa_type == 's2cloudless':
            st.caption('기준을 낮추면 더 많은 픽셀이 구름 후보가 됩니다. 확률이 기준보다 큰 픽셀에 CoastSat 마스크 정리를 적용합니다.')
        apply_cloud_mask = st.checkbox('구름 픽셀을 처리 결과에서 제외', value=True, disabled=qa_type == '없음')
        cloud_mask_issue = st.checkbox('Landsat 모래·포말 오인 완화', value=False) if qa_type == 'landsat_qa_pixel' else False
        pan_choice = None
        if satellite in ('L7', 'L8', 'L9') and not rgb_only:
            pan_choice = st.selectbox('PAN 밴드로 선명화', ['사용하지 않음'] + list(choices))
        st.caption('출력 격자: 첫 번째(Blue) 밴드 기준. 선명화를 선택하면 PAN 기준. 좌표계와 위치정보를 유지합니다.')
        calibration = st.checkbox('밴드별 스케일·오프셋 직접 입력')
        calibration_rows = None
        if calibration:
            calibration_rows = st.data_editor(pd.DataFrame({'밴드': required, 'scale': [1.0]*len(required), 'offset': [0.0]*len(required)}),
                                             disabled=['밴드'], hide_index=True)
        else:
            st.caption('파일에 기록된 스케일·오프셋을 적용합니다. 기록이 없으면 원래 값을 유지합니다. 대기보정은 수행하지 않습니다.')
        scene = None
        try:
            if any(entry is None for entry in selected):
                raise ValueError('모든 영상 밴드를 지정해 주세요.')
            if len({(e['path'], e['band']) for e in selected}) != len(selected):
                raise ValueError('동일한 밴드를 중복 지정할 수 없습니다.')
            candidate = {'name': Path(selected[0]['path']).stem, 'satellite': satellite, 'bands': [dict(e) for e in selected],
                         'cloud_threshold': threshold, 'apply_cloud_mask': apply_cloud_mask, 'cloud_mask_issue': cloud_mask_issue}
            if calibration_rows is not None:
                for entry, (_, row) in zip(candidate['bands'], calibration_rows.iterrows()):
                    entry.update(scale=float(row['scale']), offset=float(row['offset']))
            if qa_type != '없음':
                if qa_choice not in choices:
                    raise ValueError('구름 정보 밴드를 선택해 주세요.')
                key = 'probability' if qa_type == 's2cloudless' else 'qa'
                candidate[key] = dict(choices[qa_choice], kind=qa_type)
            if pan_choice in choices:
                candidate['pan'] = dict(choices[pan_choice])
            scene = candidate
        except (ValueError, TypeError) as error:
            st.caption(str(error))
        preview_panel(scene, 'local')
        st.subheader('3. 현재 설정으로 결과 저장')
        output = output_path()
        confirmed = st.checkbox('밴드 순서·촬영 장면·구름 정보 형식을 확인했습니다.')
        if st.button('전처리 시작', type='primary', disabled=busy or not confirmed or scene is None):
            try:
                if not output.strip():
                    raise ValueError('결과 저장 폴더를 입력해 주세요.')
                begin({'mode': 'process', 'scenes': [scene], 'output': output})
            except Exception as error:
                st.error(str(error))

elif page == 'Google에서 영상 수집':
    st.subheader('1. 내 Google 계정 연결')
    st.write('본인이 사용할 수 있는 Earth Engine 프로젝트 ID를 입력해 주세요. 로그인은 기본 브라우저에서 진행합니다.')
    st.link_button('Earth Engine 프로젝트 등록 안내', 'https://developers.google.com/earth-engine/guides/auth')
    project = st.text_input('Google Cloud 프로젝트 ID', placeholder='ee-my-project').strip()
    a, b = st.columns(2)
    if a.button('Google 로그인 / 계정 변경', disabled=busy or not project):
        begin({'mode': 'authenticate', 'project': project})
    if b.button('기존 로그인 연결 확인', disabled=busy or not project):
        begin({'mode': 'check', 'project': project})
    connected = st.session_state.get('connected_project') == project and bool(project)
    if connected:
        st.success('이 프로젝트로 연결을 확인했습니다.')
    st.subheader('2. 수집 범위')
    st.caption('경도·위도(WGS84)로 작은 사각형 영역을 지정합니다. 종료일은 포함하지 않습니다.')
    a,b,c,d = st.columns(4)
    west = a.number_input('서쪽 경도', -180.0, 180.0, 129.10, format='%.5f')
    east = b.number_input('동쪽 경도', -180.0, 180.0, 129.13, format='%.5f')
    south = c.number_input('남쪽 위도', -85.0, 85.0, 35.14, format='%.5f')
    north = d.number_input('북쪽 위도', -85.0, 85.0, 35.17, format='%.5f')
    a,b = st.columns(2)
    start = a.date_input('시작일', date.today()-timedelta(days=90), min_value=date(1984,1,1), max_value=date.today())
    end = b.date_input('종료일 (미포함)', date.today(), min_value=date(1984,1,1), max_value=date.today())
    sats = st.multiselect('위성', ['L5','L7','L8','L9','S2'], default=['S2'])
    download_dir = st.text_input('영상 저장 폴더', str(root / 'downloads'))
    site = st.text_input('조사 지역 이름', 'my_coast')
    st.caption('새 수집마다 고유 폴더를 만들어 기존 파일과 분리합니다.')
    if st.button('위성영상 수집 시작', type='primary', disabled=busy or not connected):
        try:
            if west >= east or south >= north or start >= end or not sats:
                raise ValueError('좌표·기간·위성을 확인해 주세요.')
            if east-west > .15 or north-south > .15:
                raise ValueError('초기 버전은 경도·위도 폭 각각 0.15도 이하의 영역을 지원합니다.')
            if not site or any(c in site for c in '\\/:*?"<>|') or site in ('.','..'):
                raise ValueError('조사 지역 이름에 경로 문자나 특수문자를 사용할 수 없습니다.')
            inputs = {'filepath': download_dir, 'sitename': site+'_'+uuid.uuid4().hex[:8],
                      'polygon': [[[west,south],[east,south],[east,north],[west,north],[west,south]]],
                      'dates': [str(start),str(end)], 'sat_list': sats, 'landsat_collection': 'C02'}
            begin({'mode':'download', 'project': project, 'inputs': inputs})
        except Exception as error:
            st.error(str(error))

else:
    st.subheader('CoastSat 영상 폴더 전처리')
    site = st.text_input('사이트 폴더 · L5/L7/L8/L9/S2 폴더가 들어 있는 위치', st.session_state.get('downloaded_site', ''))
    if st.button('장면 목록 불러오기', disabled=busy):
        try:
            if not site.strip():
                raise ValueError('사이트 폴더를 입력해 주세요.')
            st.session_state['folder_scenes'] = scan_coastsat(site, pansharpen=True)
            st.session_state['folder_scenes_path'] = str(Path(site).expanduser().resolve())
            st.session_state['folder_revision'] = uuid.uuid4().hex
        except Exception as error:
            st.error(str(error))
    pan = st.checkbox('Landsat 7/8/9 PAN 밴드로 선명화')
    threshold = st.slider('Sentinel-2 구름 확률 기준 (%)', 0, 100, 40)
    st.caption('확률 기준은 Sentinel-2의 s2cloudless에만 적용됩니다. QA60에서 구름으로 판정한 픽셀은 확률 기준을 높여도 구름으로 유지됩니다.')
    apply_cloud_mask = st.checkbox('구름 픽셀을 처리 결과에서 제외', value=True)
    cloud_mask_issue = st.checkbox('Landsat 모래·포말 오인 완화', value=False)
    folder_scenes = st.session_state.get('folder_scenes', [])
    if not site.strip() or str(Path(site).expanduser().resolve()) != st.session_state.get('folder_scenes_path'):
        folder_scenes = []
    configured_scenes = json.loads(json.dumps(folder_scenes))
    for candidate in configured_scenes:
        candidate.update(cloud_threshold=threshold, apply_cloud_mask=apply_cloud_mask, cloud_mask_issue=cloud_mask_issue)
        if not pan:
            candidate.pop('pan', None)
    selected_scene = None
    if configured_scenes:
        index = st.selectbox('미리볼 장면', range(len(configured_scenes)),
            format_func=lambda i: f"{configured_scenes[i]['satellite']} · {configured_scenes[i]['name']}",
            key=f'folder_scene_{st.session_state["folder_revision"]}')
        selected_scene = configured_scenes[index]
        st.caption(f'총 {len(configured_scenes)}개 장면. 미리보기는 선택한 한 장면, 최종 저장은 목록 전체에 적용합니다.')
    preview_panel(selected_scene, 'folder')
    st.subheader('현재 설정으로 전체 장면 저장')
    output = output_path()
    if st.button('폴더 확인 및 전처리 시작', type='primary', disabled=busy):
        try:
            if not site.strip() or not output.strip():
                raise ValueError('입력·출력 폴더를 지정해 주세요.')
            if not configured_scenes:
                raise ValueError('장면 목록을 먼저 불러와 주세요.')
            begin({'mode':'process', 'scenes':configured_scenes, 'output':output})
        except Exception as error:
            st.error(str(error))


@st.fragment(run_every='2s' if busy else None)
def show_job():
    job = st.session_state.get('job')
    if not job:
        return
    state = jobs.status(job)
    st.divider()
    st.subheader('작업 상태')
    if state['state'] == 'running':
        st.progress(float(state.get('progress', 0)), text=state['message'])
        if st.button('현재 작업 중지'):
            job['process'].terminate()
            job['process'].wait(timeout=10)
            st.rerun()
    elif state['state'] == 'error':
        st.error(state['message'])
    else:
        if job['mode'] in ('authenticate', 'check'):
            st.session_state['connected_project'] = job['project']
        if state.get('site'):
            st.session_state['downloaded_site'] = state['site']
            st.success('수집 완료. 왼쪽의 CoastSat 폴더 전처리에서 이어서 처리하세요.')
            st.code(state['site'], language=None)
        else:
            st.success('작업 완료')
        for item in state.get('results', []):
            folder = Path(item['folder'])
            st.code(str(folder), language=None)
            for warning in item['warnings']:
                st.warning(warning)
            st.image(str(folder / 'preview.png'), caption='RGB 미리보기 · 표시용 명암 조정 적용')
            if st.button('결과 폴더 열기', key=str(folder)):
                os.startfile(str(folder))
    for failed in state.get('failed', []):
        st.error(f'{failed["name"]}: {failed["error"]}')
    with st.expander('상세 로그'):
        logfile = Path(job['folder']) / 'job.log'
        st.code(logfile.read_text(encoding='utf-8', errors='replace')[-16000:] if logfile.exists() else '준비 중', language=None)
    if busy and state['state'] != 'running':
        st.rerun()


show_job()
