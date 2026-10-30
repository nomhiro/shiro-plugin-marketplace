"""着地のスナップショットを2列に並べた1枚にする（目視用）。

    python sheet.py <unit-slug> <フレーム番号...>   # 出力: videos/<unit>/.hyperframes/sheet.jpg

フレーム番号は音声の wav 番号（1始まり）。snapshots は shot_times.py が「各フレーム3枚（開始直後・途中・着地）」で撮る。
"""
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import course_config  # noqa: E402

root = course_config.load().unit(sys.argv[1])
ims = []
for f in sys.argv[2:]:
    i = (int(f) - 1) * 3 + 2                       # 着地の枚（各フレーム3枚の3枚目）
    p = next((root / "snapshots").glob(f"frame-{i:02d}-at-*.png"))
    ims.append(Image.open(p).resize((960, 540)))
rows = (len(ims) + 1) // 2
W = Image.new("RGB", (1920, 540 * rows), "white")
for k, im in enumerate(ims):
    W.paste(im, ((k % 2) * 960, (k // 2) * 540))
dst = root / ".hyperframes" / "sheet.jpg"
W.save(dst, quality=85)
print(f"OK: {dst}")
