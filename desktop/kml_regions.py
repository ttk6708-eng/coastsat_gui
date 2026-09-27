"""Read local KML polygons without following links or resolving XML entities."""
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from shapely.geometry import Polygon
from shapely.geometry.polygon import orient


def read_regions(path):
    path = Path(path)
    if path.suffix.lower() != '.kml':
        raise ValueError('영역을 .kml 파일로 저장한 뒤 선택해 주세요.')
    if path.stat().st_size > 5_000_000:
        raise ValueError('KML 파일은 5MB 이하로 준비해 주세요.')
    raw = path.read_bytes()
    # Reject declarations even in UTF-16/32 files; never load external resources.
    probe = raw.replace(b'\x00', b'').upper()
    if b'<!DOCTYPE' in probe or b'<!ENTITY' in probe:
        raise ValueError('외부 문서 또는 엔터티 선언이 있는 KML은 지원하지 않습니다.')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError('KML 문법을 읽을 수 없습니다. 파일을 다시 저장해 주세요.') from error
    for node in root.iter():
        node.tag = node.tag.rsplit('}', 1)[-1]
    if root.tag != 'kml':
        raise ValueError('올바른 KML 문서가 아닙니다.')

    def ring(boundary):
        text = boundary.findtext('LinearRing/coordinates', '')
        tokens = text.split()
        if not 3 <= len(tokens) <= 10000:
            raise ValueError('영역 경계는 3~10,000개 좌표로 구성해 주세요.')
        values = []
        try:
            for token in tokens:
                parts = token.split(',')
                x, y = float(parts[0]), float(parts[1])
                if not (math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90):
                    raise ValueError()
                values.append([x, y])
        except (ValueError, IndexError) as error:
            raise ValueError('KML 경도·위도 좌표가 올바르지 않습니다.') from error
        if values[0] != values[-1]:
            values.append(values[0].copy())
        return values

    regions = []
    for placemark in root.iter('Placemark'):
        name = (placemark.findtext('name') or '이름 없는 영역').strip()[:160]
        polygons = list(placemark.iter('Polygon'))
        for index, polygon in enumerate(polygons, 1):
            outer = polygon.find('outerBoundaryIs')
            if outer is None:
                raise ValueError(f'{name}: 외곽 경계가 없습니다.')
            shape = Polygon(ring(outer), [ring(inner) for inner in polygon.findall('innerBoundaryIs')])
            if not shape.is_valid or shape.is_empty or shape.area <= 0:
                raise ValueError(f'{name}: 경계가 교차하거나 면적이 없는 영역입니다.')
            shape = orient(shape, sign=1.0)
            regions.append({'name':name + (f' · {index}' if len(polygons) > 1 else ''),
                'polygon':[[list(p) for p in shape.exterior.coords]] + [[list(p) for p in r.coords] for r in shape.interiors],
                'bounds':list(shape.bounds), 'source':str(path.resolve())})
            if len(regions) > 500:
                raise ValueError('KML은 500개 이하의 영역으로 나눠 주세요.')
    if not regions:
        raise ValueError('KML에 면 영역(Polygon)이 없습니다. 점·경로 대신 닫힌 다각형을 그려 저장해 주세요.')
    return regions


def validate_bounds(bounds):
    west, south, east, north = bounds
    if (not all(math.isfinite(v) for v in bounds) or not (-180 <= west < east <= 180)
            or not (-85 <= south < north <= 85) or east-west > .150000001 or north-south > .150000001):
        raise ValueError('수집 영역은 경도·위도 폭 각각 0.15도 이하, 위도 ±85도 안쪽이어야 합니다. KML 영역을 더 작게 나눠 주세요.')
