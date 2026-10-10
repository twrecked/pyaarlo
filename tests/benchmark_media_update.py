"""Offline full-update benchmark. Synthetic recordings, no cloud or downloads."""
import json
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
import pyaarlo.media as media


class Downloader:
    def __init__(self, *_):
        self.downloads = 0

    def start(self):
        pass

    def queue_download(self, _video):
        self.downloads += 1


media.ArloMediaDownloader = Downloader
rows = []
for size in (100, 1000, 10000):
    samples = []
    fresh_count = max(1, size // 10)
    records = [
        {"deviceId": "test-camera", "contentType": "video/mp4",
         "utcCreatedDate": 1700000000000 + i * 1000, "name": str(i)}
        for i in range(size + fresh_count)
    ]
    expected = [str(i) for i in range(size, size + fresh_count)] + [str(i) for i in range(size)]
    for _ in range(5):
        current = records[:size]
        camera = SimpleNamespace(device_id="test-camera", name="Synthetic", base_station=None)
        arlo = SimpleNamespace(
            cfg=SimpleNamespace(save_media_to="", library_days=7),
            be=SimpleNamespace(post=lambda *_: current),
            lookup_camera_by_id=lambda _: camera,
            debug=lambda _: None, vdebug=lambda _: None, warning=lambda _: None,
        )
        library = media.ArloMediaLibrary(arlo)
        library.load()
        current = records + records[size:]
        started = time.perf_counter()
        library.update()
        samples.append(time.perf_counter() - started)
        assert [v.id for v in library.videos[1]] == expected
        assert library._downloader.downloads == size + fresh_count
    rows.append({"cached_recordings": size, "response_records": len(current),
                 "new_recordings": fresh_count,
                 "median_ms": round(statistics.median(samples) * 1000, 3),
                 "samples_ms": [round(x * 1000, 3) for x in samples]})
print(json.dumps({"source": sys.argv[1], "benchmark": "synthetic full media update, no network",
                  "correct_order_and_download_count": True, "rows": rows}, indent=2))
