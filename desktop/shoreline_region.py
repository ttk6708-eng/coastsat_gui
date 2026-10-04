"""Clip existing shoreline candidates to a user-drawn polygon, without redetection."""
import copy
from datetime import datetime, timezone

import numpy as np
from shapely.geometry import LineString, Polygon
from shapely.validation import explain_validity

from desktop.shoreline import pixel_world


def clip_region(report, vertices, mode):
    """vertices are preview x/y coordinates; preserve separate line fragments."""
    if mode not in ('keep', 'exclude'):
        raise ValueError('지원하지 않는 영역 처리 방식입니다.')
    points = np.asarray(vertices, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
        raise ValueError('영상 위에 서로 다른 점을 3개 이상 찍어 영역을 그려 주세요.')
    step = float(report['preview_step'])
    if not np.isfinite(step) or step <= 0:
        raise ValueError('미리보기 배율 정보가 올바르지 않습니다.')
    # Source pixel x/y, not screen pixels: zoom and preview decimation do not alter geometry.
    polygon = Polygon(points * step)
    if not polygon.is_valid or polygon.area <= 1e-8:
        raise ValueError('영역 선이 서로 교차하거나 면적이 없습니다. 점을 되돌린 뒤 다시 그려 주세요. (' + explain_validity(polygon) + ')')
    transform = report['transform']
    if len(transform) != 6 or not np.isfinite(transform).all():
        raise ValueError('영상 좌표 변환 정보가 올바르지 않습니다.')
    segments = []

    def lines(geometry):
        if geometry.is_empty:
            return
        if geometry.geom_type == 'LineString':
            yield geometry
        elif hasattr(geometry, 'geoms'):
            for part in geometry.geoms:
                yield from lines(part)

    for segment in report['segments']:
        source = LineString([(p[1], p[0]) for p in segment['pixels']])
        clipped = source.intersection(polygon) if mode == 'keep' else source.difference(polygon)
        fragments = list(lines(clipped))
        fragments.sort(key=lambda line: source.project(line.interpolate(0)))
        for line in fragments:
            # Ignore point touches and numerical slivers, never connect separate fragments.
            if line.length <= 1e-8:
                continue
            xy = np.asarray(line.coords)
            if source.project(line.interpolate(0)) > source.project(line.interpolate(line.length)):
                xy = xy[::-1]
            pixels = xy[:, ::-1]
            world = pixel_world(pixels, transform)
            length = float(np.linalg.norm(np.diff(world, axis=0), axis=1).sum())
            if length <= 1e-6:
                continue
            segments.append({'id': len(segments)+1,
                             'source_segment_id':segment.get('source_segment_id',segment['id']),
                             'length_m':length,'pixels':pixels.tolist(),'coordinates':world.tolist()})
    if not segments:
        raise ValueError('선택 후 남는 후보선이 없습니다. 영역을 바꿔 주세요. 기존 후보는 유지됩니다.')
    result = copy.deepcopy(report)
    result['segments'] = segments
    history = result.setdefault('region_edits', [])
    history.append({'mode':mode,'preview_vertices':points.tolist(),
                    'source_pixel_vertices_xy':(points*step).tolist(),
                    'projected_vertices':pixel_world((points*step)[:, ::-1],transform).tolist(),
                    'before_segments':len(report['segments']),'after_segments':len(segments),
                    'after_length_m':sum(s['length_m'] for s in segments),
                    'time_utc':datetime.now(timezone.utc).isoformat()})
    result['region_edit_note'] = ('User polygon clips detected candidates only. No new shoreline detection, '
                                  'tide correction or erosion classification. Extraction minimum length is not reapplied after manual clipping.')
    return result
