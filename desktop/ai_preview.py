"""Experimental local-only cloud comparison; never changes export settings."""
import copy
import json
import os
import time
from pathlib import Path

import numpy as np
from PIL import Image
from osgeo import osr

from desktop.processing import compute_scene, write_tif
from desktop.preview import scene_signature
from desktop.display import stretch_ranges, preview_rgb
from desktop.ai_models import MODELS, REVISION, verify_models


def predict_local(inputs, folder):
    verify_models(folder)
    # Explicit local models avoid the library's automatic network download path.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    import torch
    from omnicloudmask import predict_from_array
    from omnicloudmask.model_utils import load_model_from_weights
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    models = [load_model_from_weights(model_name=arch, weights_path=Path(folder)/name,
              model_library='smp', device=torch.device('cpu'), dtype=torch.float32)
              for name, arch, *_ in MODELS]
    return predict_from_array(inputs, custom_models=models, inference_device='cpu',
        mosaic_device='cpu', inference_dtype='fp32', batch_size=1,
        patch_size=512, patch_overlap=128, no_data_value=0, apply_no_data_mask=False)


def compare_ai(scene, folder, models_folder, progress=None, predictor=None):
    emit = progress or (lambda *args: None)
    signature = scene_signature(scene); started = time.monotonic()
    # AI must see the unmasked input, not the result after existing cloud exclusion.
    source = copy.deepcopy(scene); source.pop('pan', None); source['apply_cloud_mask'] = False
    computed = compute_scene(source, allow_empty=True, progress=lambda s, state, msg:emit(msg, 0.1))
    data = computed['data']; nodata = computed['nodata']; target = computed['target']
    if min(data.shape[:2]) < 96:
        raise ValueError('AI 비교는 가로·세로가 각각 96픽셀 이상인 영상에서 지원합니다.')
    if not (~nodata).any():
        raise ValueError('AI가 판정할 유효 픽셀이 없습니다.')
    nir = data[:, :, 3] if data.shape[2] == 5 else np.zeros(data.shape[:2], dtype='float32')
    inputs = np.stack([data[:, :, 2], data[:, :, 1], nir]).astype('float32')
    inputs[:, nodata] = 0
    # Library normalisation uses zero as missing data; preserve that uncertainty.
    ai_valid = ~nodata & ~np.all(inputs == 0, axis=0)
    if not ai_valid.any():
        raise ValueError('AI 입력이 모두 결측 또는 0입니다. 밴드·보정값을 확인하세요.')
    emit('AI 구름·그림자 판정 중 · CPU에서는 수 분 이상 걸릴 수 있습니다.', 0.25)
    prediction = np.asarray((predictor or predict_local)(inputs, models_folder))
    if prediction.shape == (1, *nodata.shape):
        prediction = prediction[0]
    if prediction.shape != nodata.shape or not np.isin(prediction, [0, 1, 2, 3]).all():
        raise ValueError('AI 판정 결과 형식이 올바르지 않습니다.')
    if scene_signature(scene) != signature:
        raise ValueError('AI 분석 중 입력 파일이 바뀌었습니다. 다시 실행해 주세요.')
    classes = prediction.astype('uint8'); classes[~ai_valid] = 255
    cloud, known = computed['cloud'], computed['known']
    compare_valid = ai_valid & known
    difference = np.full(nodata.shape, 255, dtype='uint8')
    difference[compare_valid] = (cloud[compare_valid] != (classes[compare_valid] > 0)).astype('uint8')
    count = int(ai_valid.sum()); comparable = int(compare_valid.sum())
    percentages = {str(i):float(np.count_nonzero(classes == i)/count*100) for i in range(4)}
    srs = osr.SpatialReference(); srs.ImportFromWkt(target.GetProjection())
    gt = target.GetGeoTransform()
    warnings = ['AI 비교 시험 기능입니다. 해안의 파도·모래·어두운 바다는 오판할 수 있습니다.',
                'AI는 구름 확률 슬라이더를 사용하지 않습니다. PAN 선명화 전 파랑 밴드 격자로 비교했습니다.',
                '불일치율은 정확도 점수가 아닙니다. 기존 구름/그림자 후보와 AI 구름/그림자 후보를 비교합니다.']
    if data.shape[2] == 3:
        warnings.append('NIR 없음: 0으로 대체한 RGB 전용 시험 모드입니다. 실제 자료로 별도 검증이 필요합니다.')
    if not srs.IsProjected():
        warnings.append('좌표 단위가 도 단위이므로 미터 해상도를 자동 판단하지 않았습니다. 권장 10–50m인지 확인하세요.')
    else:
        res = [float(np.hypot(gt[1],gt[4])*srs.GetLinearUnits()), float(np.hypot(gt[2],gt[5])*srs.GetLinearUnits())]
        if any(v < 10 or v > 50 for v in res):
            warnings.append(f'해상도 {res[0]:.2f} × {res[1]:.2f}m: 권장 10–50m 범위 밖의 시험 결과입니다.')
    if not comparable:
        warnings.append('기존 구름 정보가 없어 불일치율은 계산하지 않았습니다.')
    step = computed['preview_step']; out = Path(folder); out.mkdir(parents=True, exist_ok=True)
    (out/'INCOMPLETE.txt').write_text('미완료 AI 비교 결과', encoding='utf-8')
    rgb = data[::step, ::step, [2,1,0]]
    Image.fromarray(preview_rgb(rgb, stretch_ranges(rgb))).save(out/'rgb.png')
    old = np.zeros((*nodata.shape,4),dtype='uint8')
    old[~known] = [157,92,226,255]; old[cloud & known] = [255,102,51,255]; old[nodata] = [130,144,159,255]
    palette = np.zeros((256,4),dtype='uint8')
    palette[1] = [255,102,51,255]; palette[2] = [255,205,60,255]
    palette[3] = [40,150,240,255]; palette[255] = [130,144,159,255]
    Image.fromarray(old[::step,::step]).save(out/'existing.png')
    Image.fromarray(palette[classes[::step,::step]]).save(out/'ai.png')
    # These are comparison artifacts only; regular preprocessed.tif is never written here.
    write_tif(out/'ai-comparison.tif', [classes,difference], target,
        ['AI classes: 0 clear, 1 thick cloud, 2 thin cloud, 3 shadow, 255 unknown',
         'Disagreement: 0 agree, 1 differ, 255 not comparable'], byte=True, nodata=255)
    info = {'folder':str(out.resolve()), 'name':scene['name'], 'signature':signature,
        'scene':scene, 'model_revision':REVISION, 'model_version':4, 'library_version':'1.7.1',
        'model_sha256':{m[0]:m[3] for m in MODELS}, 'device':'cpu', 'preview_only':True,
        'percentages':percentages, 'ai_valid_pixels':count, 'comparable_pixels':comparable,
        'disagreement_percent':float(np.mean(difference[compare_valid])*100) if comparable else None,
        'warnings':warnings, 'elapsed_seconds':round(time.monotonic()-started,2),
        'display_step':step, 'nir_available':data.shape[2] == 5}
    (out/'ai-comparison.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'INCOMPLETE.txt').unlink()
    emit('AI 비교 미리보기 완료', 1)
    return info
