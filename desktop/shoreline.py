"""Single-scene CoastSat S2 shoreline candidates; preserve disconnected segments."""
import hashlib
import json
import math
import shutil
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from osgeo import osr
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree

from desktop.processing import compute_scene
from desktop.preview import scene_signature
from desktop.display import preview_rgb, stretch_ranges

DEFAULTS = {'min_beach_area': 1000, 'min_length_sl': 500, 'dist_clouds': 300}
MODEL_SHA = '092cafa924e67474880d2c8a55afcfb14a323996bcea12b2adf94704410e7704'


def settings_checked(settings):
    result = dict(DEFAULTS)
    result.update(settings or {})
    for key in DEFAULTS:
        value = float(result[key])
        if not math.isfinite(value) or value < 0 or (key != 'dist_clouds' and value == 0):
            raise ValueError('해안선 설정은 유효한 양수여야 합니다. 구름 거리는 0도 가능합니다.')
        result[key] = value
    return result


def pixel_world(points, transform):
    # Match CoastSat convert_pix2world: row/column integer origin, no half-pixel offset.
    p = np.asarray(points)
    return np.column_stack((transform[0] + p[:, 1]*transform[1] + p[:, 0]*transform[2],
                            transform[3] + p[:, 1]*transform[4] + p[:, 0]*transform[5]))


def water_contours(index, labels):
    """CoastSat-style balanced Otsu on the SAME SWIR/G index used for contours.

    Do not inherit the bundled contours2 NIR/SWIR threshold column mix-up.
    A local random generator makes repeats stable without changing global RNG.
    """
    from skimage.filters import threshold_otsu
    from skimage.measure import find_contours
    sand = index[labels[:, :, 0] & np.isfinite(index)]
    water = index[labels[:, :, 2] & np.isfinite(index)]
    if len(sand) >= 50 and len(water):
        rng = np.random.default_rng(0); count = min(len(sand),len(water))
        values = np.concatenate((rng.choice(sand,count,replace=False),rng.choice(water,count,replace=False)))
        method = 'CoastSat-based balanced sand/water Otsu; same SWIR/G index; seed=0'
    else:
        values = index[np.isfinite(index)]
        method = 'CoastSat-style full valid SWIR/G Otsu (fallback)'
    if len(values) < 2 or np.ptp(values) == 0:
        raise ValueError('물과 육지를 구분할 수 있는 지수 값이 부족합니다.')
    threshold = float(threshold_otsu(values))
    return find_contours(index,threshold), threshold, method


def split_segments(contours, transform, cloud, nodata, settings):
    trees = [(cKDTree(pixel_world(np.argwhere(mask), transform)), distance)
             for mask, distance in ((cloud, settings['dist_clouds']), (nodata, 30))
             if mask.any() and distance > 0]
    segments = []
    for contour in contours:
        xy = pixel_world(contour, transform)
        keep = np.all(np.isfinite(xy), axis=1)
        for tree, distance in trees:
            indexes = np.flatnonzero(keep)
            keep[indexes] &= tree.query(xy[indexes])[0] >= distance
        indices = np.flatnonzero(keep)
        for run in np.split(indices, np.flatnonzero(np.diff(indices) != 1) + 1):
            if len(run) < 2:
                continue
            length = float(np.linalg.norm(np.diff(xy[run], axis=0), axis=1).sum())
            if length >= settings['min_length_sl']:
                segments.append({'id': len(segments)+1, 'length_m': length,
                                 'pixels': np.asarray(contour)[run].tolist(), 'coordinates': xy[run].tolist()})
    return segments


def extract(scene, settings, folder, progress=None):
    if not scene.get('coastsat') or scene.get('satellite') != 'S2' or len(scene['bands']) != 5:
        raise ValueError('첫 해안선 추출 단계는 CoastSat Sentinel-2의 ms·swir·mask 장면을 지원합니다.')
    if not scene.get('apply_cloud_mask', True):
        raise ValueError('해안선 추출 전에 메인 화면의 구름 픽셀 제외를 켜 주세요.')
    settings = settings_checked(settings)
    signature = scene_signature(scene)
    steps = []
    def emit(message, fraction):
        steps.append(message)
        if progress:
            progress(message, fraction)
    emit('① 현재 설정으로 밴드 정렬·구름·결측 제외', .05)
    computed = compute_scene(scene)
    data, target = computed['data'], computed['target']
    transform = target.GetGeoTransform()
    srs = osr.SpatialReference(wkt=target.GetProjection())
    if not srs.IsProjected() or abs(srs.GetLinearUnits()-1) > 1e-8:
        raise ValueError('해안선 거리 계산에는 미터 단위 투영 좌표계가 필요합니다.')
    if transform[2] != 0 or transform[4] != 0 or not np.isclose(abs(transform[1]), abs(transform[5])):
        raise ValueError('첫 추출 단계는 회전되지 않은 정사각형 픽셀 격자를 지원합니다.')
    if not computed['known'].any():
        raise ValueError('구름 판정 자료가 없습니다. 같은 장면의 mask와 구름 확률 밴드를 확인하세요.')
    # Bound classifier memory separately from raster preprocessing (20 features/pixel).
    if computed['invalid'].size > 2_000_000:
        raise ValueError('첫 추출 단계는 200만 픽셀 이하 장면을 지원합니다. 관심영역으로 자른 자료를 사용하세요.')
    emit('② CoastSat 모델로 모래·포말·물 분류', .3)
    import joblib
    error_settings = np.geterr()
    from coastsat import SDS_shoreline, SDS_tools
    np.seterr(**error_settings)
    model_path = Path(__file__).resolve().parents[1]/'classification/models/NN_4classes_S2_new.pkl'
    if hashlib.sha256(model_path.read_bytes()).hexdigest() != MODEL_SHA:
        raise ValueError('배포된 해안선 분류 모델 검증에 실패했습니다.')
    notes = list(computed['warnings'])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        model = joblib.load(model_path)
    if caught:
        notes.append('CoastSat 분류 모델의 학습 버전과 실행 버전이 다릅니다. 시험 기능이며 후보선을 육안 검토해야 합니다.')
    invalid = computed['invalid'] | ~computed['known']
    data = data.copy(); data[invalid] = np.nan
    if np.count_nonzero(~invalid) < 50:
        raise ValueError('구름·미확인 영역 제외 후 해안선을 추출할 유효 픽셀이 부족합니다.')
    with np.errstate(all='ignore'):
        classes, labels = SDS_shoreline.classify_image_NN(
            data, invalid, max(1, math.ceil(settings['min_beach_area']/abs(transform[1]*transform[5]))), model)
        emit('③ CoastSat 수분지수 임계값으로 후보선 추출', .55)
        index = SDS_tools.nd_index(data[:, :, 4], data[:, :, 1], invalid)
        contours, threshold, method = water_contours(index, labels)
        if 'fallback' in method:
            notes.append('모래·물 분류가 부족하여 전체 유효 영역 임계값 방식으로 추출했습니다.')
    emit('④ 구름 주변·결측 주변·짧은 선 제외', .8)
    segments = split_segments(contours, transform, computed['cloud'] | (~computed['known'] & ~computed['nodata']),
                              computed['nodata'], settings)
    if signature != scene_signature(scene):
        raise ValueError('추출 중 입력이 바뀌었습니다. 다시 추출해 주세요.')
    out = Path(folder); out.mkdir(parents=True, exist_ok=False)
    step = computed['preview_step']
    rgb = preview_rgb(computed['before_rgb'], stretch_ranges(computed['before_rgb']))
    Image.fromarray(rgb).save(out/'original.png')
    color = np.zeros((*invalid.shape, 4), dtype=np.uint8)
    for label, rgba in [(1,(244,190,72,180)),(2,(220,255,255,180)),(3,(30,126,240,180))]:
        color[classes == label] = rgba
    color[invalid] = (140,140,140,210)
    Image.fromarray(color[::step,::step]).save(out/'classes.png')
    Image.new('RGBA',(rgb.shape[1],rgb.shape[0])).save(out/'empty.png')
    notes.append('조위 보정 전 관측 수제선 후보입니다. 하천·항만·내륙 수역 경계가 포함될 수 있으며 침식·퇴적 판정이 아닙니다.')
    if not segments:
        notes.append('남은 후보선이 없습니다. 구름 상태와 최소 길이·주변 제외 거리를 확인하세요. 빈 결과는 저장할 수 없습니다.')
    report = {'folder':str(out), 'scene':scene, 'signature':signature, 'settings':settings,
              'segments':segments,'threshold':float(threshold),'method':method,'model_sha256':MODEL_SHA,
              'projection_wkt':target.GetProjection(),'transform':list(transform),'preview_step':step,
              'created_utc':datetime.now(timezone.utc).isoformat(), 'warnings':notes, 'steps':steps,
              'coordinate_convention':'CoastSat pixel origin (no half-pixel shift)',
              'classification_counts':{str(i):int(np.count_nonzero(classes == i)) for i in range(4)}}
    (out/'candidate.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    draw_overlay(report, [s['id'] for s in segments], out/'shoreline.png')
    emit('⑤ 후보선 미리보기 준비 완료', 1)
    return report


def draw_overlay(report, selected, path):
    with Image.open(Path(report['folder'])/'original.png') as original:
        overlay = Image.new('RGBA',original.size)
    draw = ImageDraw.Draw(overlay)
    for segment in report['segments']:
        if segment['id'] in selected:
            points = [(p[1]/report['preview_step'],p[0]/report['preview_step']) for p in segment['pixels']]
            draw.line(points, fill=(255,50,90,255), width=2)
            draw.text(points[len(points)//2],str(segment['id']),fill='white',stroke_width=1,stroke_fill='black')
    overlay.save(path)


def export_reviewed(report, selected, destination):
    segments = [s for s in report['segments'] if s['id'] in selected]
    if not segments:
        raise ValueError('저장할 후보선을 하나 이상 선택하세요.')
    if scene_signature(report['scene']) != report['signature']:
        raise ValueError('원본 자료가 변경되었습니다. 다시 추출한 후 저장하세요.')
    root = Path(destination)/('shoreline_'+uuid.uuid4().hex[:10]);root.mkdir(parents=True,exist_ok=False)
    marker=root/'INCOMPLETE.txt';marker.write_text('저장 중',encoding='utf-8')
    source = osr.SpatialReference(wkt=report['projection_wkt']);source.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    wgs = osr.SpatialReference();wgs.ImportFromEPSG(4326);wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    conversion = osr.CoordinateTransformation(source,wgs)
    features = []
    for segment in segments:
        coords = [[float(x),float(y)] for x,y,*_ in conversion.TransformPoints(segment['coordinates'])]
        if not np.isfinite(coords).all():
            raise ValueError('해안선 좌표 변환에 실패했습니다.')
        features.append({'type':'Feature','properties':{'segment_id':segment['id'],'length_m':segment['length_m'],
            'scene':report['scene']['name'],'review':'user_selected','tide_corrected':False},
            'geometry':{'type':'LineString','coordinates':coords}})
    (root/'shoreline.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features},ensure_ascii=False),encoding='utf-8')
    saved = {**report,'segments':segments,'selected_ids':[s['id'] for s in segments],
             'review':'user_selected','saved_utc':datetime.now(timezone.utc).isoformat()}
    (root/'report.json').write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
    draw_overlay(report,selected,root/'overlay.png')
    with Image.open(Path(report['folder'])/'original.png') as base, Image.open(root/'overlay.png') as overlay:
        Image.alpha_composite(base.convert('RGBA'),overlay).convert('RGB').save(root/'preview.png')
    shutil.copy2(Path(report['folder'])/'classes.png',root/'classes.png')
    marker.unlink()
    return str(root)
