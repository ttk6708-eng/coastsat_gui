"""Evidence-based processing status, never inferred from dates or pixel ranges."""
from pathlib import Path
import re


def correction_status(scene, bands):
    evidence = []
    levels = set()
    complete_levels = []
    for row in bands:
        if row.get('role') not in ('Blue','Green','Red','NIR','SWIR1') or row.get('error'):
            continue
        level = row.get('processing_level', '미확인')
        row_levels = set()
        if level != '미확인':
            evidence.append(f"{row['role']} 파일 처리 수준: {level}")
            token = str(level).upper().replace('LEVEL-', 'L')
            for match in re.findall(r'(?<![A-Z0-9])(?:MSI)?(L1C|L2A)(?![A-Z0-9])', token):
                levels.add(match)
                row_levels.add(match)
        complete_levels.append(row_levels)
    sidecar = {}
    if scene.get('coastsat') and scene.get('bands'):
        ms = Path(scene['bands'][0]['path'])
        if ms.parent.name == 'ms' and ms.name.endswith('_ms.tif'):
            meta = ms.parent.parent/'meta'/(ms.name[:-7]+'.txt')
            if meta.is_file() and meta.stat().st_size <= 65536:
                try:
                    for line in meta.read_text(encoding='utf-8-sig').splitlines():
                        key, sep, value = line.partition('\t')
                        if sep and key in ('filename','tile','epsg','acc_georef','image_quality'):
                            sidecar[key] = value
                    if sidecar.get('filename') != ms.name:
                        evidence.append('CoastSat TXT의 파일명이 일치하지 않아 품질정보를 사용하지 않았습니다.')
                        sidecar = {}
                    else:
                        evidence.append(f"CoastSat TXT: {meta.name} / 좌표 품질 {sidecar.get('acc_georef','미확인')} / 영상 품질 {sidecar.get('image_quality','미확인')}")
                except (OSError, UnicodeError):
                    evidence.append('CoastSat TXT 읽기 실패: 보정 완료 여부를 판단하지 않았습니다.')
    complete = len(complete_levels) == len(scene.get('bands',[])) and all(len(v) == 1 for v in complete_levels)
    known_level = next(iter(levels)) if complete and len(levels) == 1 and scene.get('satellite') == 'S2' else None
    atmosphere = '확인 불가'
    reason = 'L1C/L2A 등 원본 제품 수준이 없습니다. 날짜·픽셀 값·PASSED만으로 대기 보정 여부를 판단하지 않습니다.'
    if known_level == 'L2A':
        atmosphere = '메타데이터상 수행됨'
        reason = 'Sentinel-2 L2A 표기가 있습니다. 지표반사도 제품으로 식별되며 실제 정확도까지 검증한 것은 아닙니다.'
    elif known_level == 'L1C':
        atmosphere = '메타데이터상 미수행'
        reason = 'Sentinel-2 L1C 표기가 있습니다. 대기 상단 반사도이므로 대기 보정된 지표반사도가 아닙니다.'
    elif len(levels) > 1:
        reason = '입력 밴드의 L1C/L2A 정보가 서로 충돌합니다. 원본 제품을 확인하세요.'
    valid_rows = [r for r in bands if r.get('role') in ('Blue','Green','Red','NIR','SWIR1') and not r.get('error')]
    aligned = bool(valid_rows) and len(valid_rows) == len(scene.get('bands',[])) and all(r.get('alignment') == '파랑 밴드와 동일' for r in valid_rows)
    rows = [
        {'name':'방사 보정','input_status':'처리 수준 일부 확인' if known_level else '확인 불가',
         'evidence':f'Sentinel-2 {known_level} 표기' if known_level else '센서별 원래 보정 이력·계수를 확인할 자료가 부족합니다.',
         'app_action':'지정된 scale·offset만 적용합니다. 새 센서 방사 보정이나 대기 보정은 수행하지 않습니다.'},
        {'name':'대기 보정','input_status':atmosphere,'evidence':reason,
         'app_action':'수행하지 않음. 지원되는 원본 제품과 부가자료 또는 이미 대기 보정된 제품이 필요합니다.'},
        {'name':'정사 보정','input_status':'확인 불가',
         'evidence':'좌표정보나 품질 PASSED만으로 원본의 지형 보정 이력을 확정하지 않습니다.',
         'app_action':'수행하지 않음. 재처리에는 DEM 및 원본 센서 기하 정보 등이 필요합니다.'},
        {'name':'기하 보정','input_status':'현재 밴드 격자 일치' if aligned else '정렬 필요 또는 점검 불가',
         'evidence':'좌표·해상도·격자를 비교한 결과입니다. 실제 위치 오차를 검증한 것은 아닙니다.',
         'app_action':'기존 좌표로 밴드를 정렬합니다. 기준점·기준영상 기반 위치 교정은 수행하지 않습니다.'},
    ]
    return {'rows':rows,'evidence':evidence,'coastsat_metadata':sidecar,
            'note':'이 화면은 보정 상태를 설명합니다. 보정을 추가 실행하거나 원본을 바꾸지 않습니다.'}
