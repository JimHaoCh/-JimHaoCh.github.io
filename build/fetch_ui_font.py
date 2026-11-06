"""Fetch the unmodified OFL UI font from a pinned, hash-verified source."""
from pathlib import Path
import hashlib
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / 'assets/fonts/NotoSansCJKtc-Regular.otf'
SHA256 = 'dce08bd4fd91aa8aa76ed8fea4b694c2dfb8550f67871e326843212ddbeb88b4'
URL = ('https://raw.githubusercontent.com/notofonts/noto-cjk/'
       'f8d157532fbfaeda587e826d4cd5b21a49186f7c/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Regular.otf')


def fetch():
    if FONT.is_file() and hashlib.sha256(FONT.read_bytes()).hexdigest() == SHA256:
        return
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read(25_000_001)
    if len(data) > 25_000_000 or hashlib.sha256(data).hexdigest() != SHA256:
        raise RuntimeError('UI font checksum mismatch; build stopped.')
    FONT.parent.mkdir(parents=True, exist_ok=True)
    temp = FONT.with_suffix('.otf.part')
    temp.write_bytes(data)
    temp.replace(FONT)


if __name__ == '__main__':
    fetch()
    print('Verified Noto Sans CJK TC UI font; OFL license in assets/fonts/OFL.txt.')
