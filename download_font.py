"""Fetch the redistributable official font for source builds; no account needed."""
from pathlib import Path
import hashlib
import urllib.request

FONT_SHA256 = '194018e6b2b293a7964f037b25c0249ce1418bc9ab3c971060a03aa57861e252'
URL = ('https://raw.githubusercontent.com/google/fonts/'
       '4efc2774c63917927efe769ca845def6bd6debae/ofl/notosanskr/NotoSansKR%5Bwght%5D.ttf')


def ensure_font():
    path = Path(__file__).resolve().parent/'assets/fonts/NotoSansKR.ttf'
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == FONT_SHA256:
        return path
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read(12_000_001)
    if hashlib.sha256(data).hexdigest() != FONT_SHA256:
        raise ValueError('Official font checksum mismatch')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(data)
    return path


if __name__ == '__main__':
    print(ensure_font())
