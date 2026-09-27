"""CoastSat S2 inventory and header-only footprint comparison. No pixel processing."""
from pathlib import Path
import math
from osgeo import gdal, ogr, osr


def inventory(root):
    root = Path(root).resolve()
    if not (root/'S2').is_dir():
        raise ValueError('S2 폴더가 들어 있는 CoastSat 지역 폴더를 선택하세요.')
    grouped = {}
    for kind in ('ms', 'swir', 'mask', 'meta'):
        for path in sorted((root/'S2'/kind).glob('*')):
            if not path.is_file() or path.suffix.lower() not in (('.txt',) if kind == 'meta' else ('.tif', '.tiff')):
                continue
            stem = path.stem
            if kind != 'meta':
                if not stem.endswith('_'+kind):
                    continue
                stem = stem[:-len(kind)-1]
            grouped.setdefault(stem, {}).setdefault(kind, []).append(str(path))
    rows = []
    for name, files in sorted(grouped.items()):
        issues = [f'{k} 누락' for k in ('ms','swir','mask','meta') if k not in files]
        issues += [f'{k} 중복' for k, paths in files.items() if len(paths) > 1]
        rows.append({'site':str(root), 'name':name, 'files':files, 'issues':issues})
    if not rows:
        raise ValueError('CoastSat S2 파일 목록을 찾지 못했습니다.')
    return rows


def raster_header(path):
    ds = gdal.Open(str(path), gdal.GA_ReadOnly)
    if ds is None:
        raise ValueError('영상 파일을 읽지 못했습니다.')
    gt = ds.GetGeoTransform(can_return_null=True)
    wkt = ds.GetProjection()
    if gt is None or not wkt or not all(math.isfinite(v) for v in gt):
        raise ValueError('좌표계 또는 격자 정보가 없습니다.')
    w, h = ds.RasterXSize, ds.RasterYSize
    points = [[gt[0]+x*gt[1]+y*gt[2], gt[3]+x*gt[4]+y*gt[5]] for x,y in ((0,0),(w,0),(w,h),(0,h))]
    srs = osr.SpatialReference(wkt=wkt)
    return {'width':w,'height':h,'bands':ds.RasterCount,'transform':list(gt),
            'wkt':wkt,'crs':srs.GetAuthorityCode(None) or srs.GetName(),
            'projected':bool(srs.IsProjected()),'points':points,
            'pixel_size':[math.hypot(gt[1],gt[4]), math.hypot(gt[2],gt[5])]}


def same_grid(a,b):
    return (a['width']==b['width'] and a['height']==b['height']
            and osr.SpatialReference(wkt=a['wkt']).IsSame(osr.SpatialReference(wkt=b['wkt']))
            and all(abs(x-y)<1e-7 for x,y in zip(a['transform'],b['transform'])))


def inspect_row(row):
    result = dict(row, issues=list(row['issues']), headers={})
    for kind in ('ms','swir','mask'):
        paths = row['files'].get(kind, [])
        if len(paths) != 1:
            continue
        try:
            header = raster_header(paths[0]); result['headers'][kind] = header
            if header['bands'] != (5 if kind == 'ms' else 1):
                result['issues'].append(f'{kind} 밴드 수 확인 필요: {header["bands"]}')
        except Exception as error:
            result['issues'].append(f'{kind} 읽기 오류: {error}')
    base = result['headers'].get('ms')
    if base:
        for kind in ('swir','mask'):
            if kind in result['headers'] and not same_grid(base,result['headers'][kind]):
                result['issues'].append(f'{kind} 격자 정렬 필요')
    meta = row['files'].get('meta', [])
    if len(meta)==1:
        try:
            p = Path(meta[0])
            if p.stat().st_size>65536:
                raise ValueError('메타데이터 크기 초과')
            pairs = dict(line.split('\t',1) for line in p.read_text(encoding='utf-8-sig').splitlines() if '\t' in line)
            if len(row['files'].get('ms',[]))==1 and pairs.get('filename')!=Path(row['files']['ms'][0]).name:
                result['issues'].append('meta 파일명 불일치')
        except Exception as error:
            result['issues'].append(f'meta 읽기 오류: {error}')
    return result


def polygon(points):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x,y in points+[points[0]]:
        ring.AddPoint_2D(x,y)
    shape = ogr.Geometry(ogr.wkbPolygon); shape.AddGeometry(ring)
    return shape


def compare(reference, candidate):
    if reference['site'] != candidate['site']:
        raise ValueError('같은 지역 안에서 기준 영상을 선택하세요.')
    a,b = (r['headers'].get('ms') for r in (reference,candidate))
    if not a or not b:
        raise ValueError('두 장면의 ms 영상 정보 점검이 필요합니다.')
    if not a['projected'] or not b['projected']:
        raise ValueError('범위 면적 비교는 투영 좌표계 영상에서 지원합니다.')
    if not osr.SpatialReference(wkt=a['wkt']).IsSame(osr.SpatialReference(wkt=b['wkt'])):
        raise ValueError('좌표계가 다릅니다. 이번 단계에서는 자동 재투영하지 않습니다.')
    first,second=polygon(a['points']),polygon(b['points'])
    if min(first.GetArea(),second.GetArea())<=0:
        raise ValueError('영상 범위 면적이 올바르지 않습니다.')
    intersection=first.Intersection(second)
    if intersection is None:
        raise ValueError('공통 영역 계산 실패')
    area=intersection.GetArea()
    ref_percent=max(0,min(100,area/first.GetArea()*100))
    candidate_percent=max(0,min(100,area/second.GetArea()*100))
    label='동일 격자' if same_grid(a,b) else ('겹침 없음' if area==0 else '범위·격자 차이')
    return {'status':label,'reference_coverage_percent':ref_percent,
            'candidate_coverage_percent':candidate_percent,'intersection_wkt':intersection.ExportToWkt(),
            'note':'영상 외곽 범위 기준입니다. 구름·결측·위치 정확도는 평가하지 않습니다.'}
