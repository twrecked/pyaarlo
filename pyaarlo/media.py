import asyncio
import inspect
import os
from typing import Any, Callable
from datetime import datetime, timedelta
from string import Template
from slugify import slugify

from dataclasses import dataclass
from pathlib import Path
import time

from .constant import (
    LIBRARY_PATH,
    MEDIA_EXTENSIONS,
    VIDEO_CONTENT_TYPES
)
from .core import ArloCore
from .objects import ArloObjects
from .utils import (arlotime_strftime, arlotime_to_datetime, http_get_async,
http_stream)


@dataclass
class MediaFileInfo:
    path: Path
    size: int
    mtime: float
    age_days: float

    @property
    def formatted_size(self) -> str:
        return format_bytes(self.size)


def format_bytes(num_bytes: int) -> str:
    """Format bytes as human-readable string (e.g. "12.4 MB")."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{num_bytes} B"


def extract_base_dir_from_format(save_format: str) -> str:
    """Extract root base directory from a save_media_to template format string."""
    if not save_format:
        return ""
    idx = save_format.find("$")
    if idx != -1:
        prefix = save_format[:idx]
        base_dir = os.path.dirname(prefix) if prefix else "."
    else:
        base_dir = os.path.dirname(save_format)
    return base_dir if base_dir else "."


def scan_prunable_media(
    root_dir: str | Path,
    retention_days: int,
    extensions: set[str] | None = None,
    camera_filter: str | None = None,
    now: float | None = None,
) -> list[MediaFileInfo]:
    """Scan root_dir for media files older than retention_days.

    :param root_dir: Directory to scan.
    :param retention_days: Keep files newer than this many days.
    :param extensions: Set of file extensions to include (default: MEDIA_EXTENSIONS).
    :param camera_filter: Optional substring to match in path (e.g. camera name or serial).
    :param now: Optional timestamp representing "now" (defaults to time.time()).
    :return: List of MediaFileInfo objects older than retention_days.
    """
    root_path = Path(root_dir).resolve()
    if not root_path.is_dir():
        return []

    exts = {e.lower() for e in (extensions or MEDIA_EXTENSIONS)}
    current_time = time.time() if now is None else now
    cutoff_ts = current_time - (retention_days * 86400.0)

    prunable: list[MediaFileInfo] = []
    cam_filter_lower = camera_filter.lower() if camera_filter else None

    for dirpath, _, filenames in os.walk(root_path):
        for fname in filenames:
            file_path = Path(dirpath) / fname
            if file_path.suffix.lower() not in exts:
                continue

            if cam_filter_lower and cam_filter_lower not in str(file_path).lower():
                continue

            try:
                stat = file_path.stat()
                mtime = stat.st_mtime
                if mtime < cutoff_ts:
                    age_days = max(0.0, (current_time - mtime) / 86400.0)
                    prunable.append(
                        MediaFileInfo(
                            path=file_path,
                            size=stat.st_size,
                            mtime=mtime,
                            age_days=age_days,
                        )
                    )
            except OSError:
                continue

    prunable.sort(key=lambda x: x.mtime)
    return prunable


def prune_media_files(
    candidates: list[MediaFileInfo],
    remove_empty_dirs: bool = True,
    root_dir: str | Path | None = None,
) -> tuple[int, int, int]:
    """Prune candidate media files and optionally remove empty parent directories.

    :param candidates: List of MediaFileInfo candidate files to delete.
    :param remove_empty_dirs: If True, remove directories that become empty.
    :param root_dir: Root directory boundary. Deletion of empty dirs stops before root_dir.
    :return: Tuple of (files_deleted_count, bytes_freed_total, dirs_removed_count).
    """
    files_deleted = 0
    bytes_freed = 0
    dirs_removed = 0

    root_resolved = Path(root_dir).resolve() if root_dir else None
    touched_dirs: set[Path] = set()

    for item in candidates:
        try:
            if root_resolved and root_resolved not in item.path.resolve().parents:
                continue
            item.path.unlink()
            files_deleted += 1
            bytes_freed += item.size
            if remove_empty_dirs:
                touched_dirs.add(item.path.parent)
        except OSError:
            continue

    if remove_empty_dirs and touched_dirs:
        sorted_dirs = sorted(
            touched_dirs,
            key=lambda p: len(p.resolve().parts),
            reverse=True,
        )
        for d in sorted_dirs:
            curr = d
            while curr != root_resolved and curr != curr.parent:
                try:
                    if not any(curr.iterdir()):
                        curr.rmdir()
                        dirs_removed += 1
                        curr = curr.parent
                    else:
                        break
                except OSError:
                    break

    return files_deleted, bytes_freed, dirs_removed


class ArloMediaDownloader:
    def __init__(self, core: ArloCore, save_format: str, retention_days: int = 0):
        self._core = core
        self._save_format = save_format
        self._retention_days = retention_days
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._downloading = False
        self._task: asyncio.Task[Any] | None = None
        self._prune_task_id: str | None = None

    def start(self):
        if self._save_format:
            self._task = asyncio.create_task(self._run())
            if self._retention_days > 0:
                self._start_retention_tasks()

    def _start_retention_tasks(self):
        tasks = getattr(self._core, "tasks", None)
        if tasks is not None:
            if hasattr(tasks, "run_in"):
                tasks.run_in(self._retention_cleanup, 30)
            if hasattr(tasks, "run_every"):
                self._prune_task_id = tasks.run_every(self._retention_cleanup, 86400)

    async def _retention_cleanup(self):
        if self._retention_days <= 0 or not self._save_format:
            return
        base_dir = extract_base_dir_from_format(self._save_format)
        if not base_dir or not os.path.isdir(base_dir):
            return
        self.debug(f"starting media retention cleanup (retention={self._retention_days} days, dir={base_dir})")
        loop = asyncio.get_running_loop()

        def _do_prune():
            candidates = scan_prunable_media(base_dir, self._retention_days)
            if not candidates:
                return 0, 0, 0
            return prune_media_files(candidates, remove_empty_dirs=True, root_dir=base_dir)

        try:
            deleted, freed, dirs = await loop.run_in_executor(None, _do_prune)
            if deleted > 0:
                self.debug(
                    f"retention cleanup: deleted {deleted} file(s), freed {format_bytes(freed)}, removed {dirs} dir(s)"
                )
            else:
                self.vdebug("retention cleanup: no expired files found")
        except Exception as e:
            self._core.log.error(f"retention cleanup error: {e}")

    # noinspection PyPep8Naming
    def _output_name(self, media):
        """Calculate file name from media object.

        Uses `self._save_format` to work out the substitions.

        :param media: ArloMediaObject to download
        :return: The file name.
        """
        when = arlotime_to_datetime(media.created_at)
        Y = str(when.year).zfill(4)
        m = str(when.month).zfill(2)
        d = str(when.day).zfill(2)
        H = str(when.hour).zfill(2)
        M = str(when.minute).zfill(2)
        S = str(when.second).zfill(2)
        F = f"{Y}-{m}-{d}"
        T = f"{H}:{M}:{S}"
        t = f"{H}-{M}-{S}"
        s = str(int(when.timestamp())).zfill(10)
        try:
            return (
                Template(self._save_format).substitute(
                    SN=media.camera.device_id,
                    N=media.camera.name,
                    NN=slugify(media.camera.name, separator='_'),
                    Y=Y,
                    m=m,
                    d=d,
                    H=H,
                    M=M,
                    S=S,
                    F=F,
                    T=T,
                    t=t,
                    s=s,
                )
                + f".{media.extension}"
            )
        except KeyError as _e:
            self._core.log.error(f"format error: {self._save_format}")
            return None

    async def _download(self, media):
        """Download a single piece of media.

        :param media: ArloMediaObject to download
        :return: 1 if a file was downloaded, 0 if the file present and skipped or -1 if an error occured
        """
        # Calculate name.
        save_file = self._output_name(media)
        if save_file is None:
            return -1
        try:
            # See if it exists.
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: os.makedirs(os.path.dirname(save_file), exist_ok=True))
            
            exists = await loop.run_in_executor(None, os.path.exists, save_file)
            if not exists:
                # Download to temporary file before renaming it.
                self.debug(f"dowloading for {media.camera.name} --> {save_file}")
                save_file_tmp = f"{save_file}.tmp"
                await media.download_video(save_file_tmp)
                await loop.run_in_executor(None, os.rename, save_file_tmp, save_file)
                try:
                    when = arlotime_to_datetime(media.created_at)
                    ts = when.timestamp()
                    await loop.run_in_executor(None, lambda: os.utime(save_file, (ts, ts)))
                except OSError:
                    pass
                return 1
            else:
                self.vdebug(
                    f"skipping dowload for {media.camera.name} --> {save_file}"
                )
                return 0
        except OSError as _e:
            self._core.log.error(f"failed to download: {save_file}")
            return -1

    async def _run(self):
        while True:
            try:
                media = await self._queue.get()
                self._downloading = True
                
                result = await self._download(media)
                
                self._queue.task_done()
                self._downloading = False
                
                if result == 1:
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._core.log.error(f"media-downloader error: {e}")
                self._downloading = False

    def queue_download(self, media):
        if self._save_format == "":
            return
        self._queue.put_nowait(media)

    def stop(self):
        if self._task:
            self._task.cancel()
        tasks = getattr(self._core, "tasks", None)
        if self._prune_task_id and tasks is not None and hasattr(tasks, "cancel"):
            tasks.cancel(self._prune_task_id)
            self._prune_task_id = None

    @property
    def processing(self):
        return not self._queue.empty() or self._downloading

    def debug(self, msg):
        self._core.log.debug(f"media-downloader: {msg}")

    def vdebug(self, msg):
        self._core.log.vdebug(f"media-downloader: {msg}")


class ArloMediaLibrary:
    """Arlo Library Media module implementation."""

    _core: ArloCore
    _objs: ArloObjects

    def __init__(self, core: ArloCore, objs: ArloObjects):
        self._core = core
        self._objs = objs

        self._load_cbs_: list[Callable[..., Any]] = []
        self._update_pending: bool = False
        self._count = 0
        self._videos: list[Any] = []
        self._video_keys: list[str] = []
        self._snapshots: dict[str, Any] = {}

        retention = getattr(self._core.cfg, "media_retention_days", 0)
        self._downloader = ArloMediaDownloader(core, self._core.cfg.save_media_to, retention)
        self._downloader.start()

    def __repr__(self):
        return "<{0}:{1}>".format(self.__class__.__name__, self._core.cfg.name)

    async def _fetch_library(self, date_from, date_to):
        """Get the library.

        Override as needed.
        """
        return await self._core.be.post(
            LIBRARY_PATH, {"dateFrom": date_from, "dateTo": date_to}
        )

    def _create_video(self, video, camera):
        """Build the video object.

        Override as needed.
        """
        return ArloVideo(video, camera)

    def _create_snapshot(self, video, camera):
        """Build the snapshot object.

        Override as needed.
        """
        return ArloSnapshot(video, camera)

    def _lookup_camera_by_id(self, device_id: str):
        camera = list(filter(lambda cam: cam.device_id == device_id, self._objs.cameras))
        if camera:
            return camera[0]
        return None

    async def _sync_library(self, date_from, date_to, keys):
        """Read library between dates given, add videos not present.

        Passing an empty keys will cause all video information in the given
        date range to be recorded.
        """
        data = await self._fetch_library(date_from, date_to)
        if data is None:
            return None, None, None

        known_keys = set(keys)
        videos = []
        snapshots = {}
        for video in data:
            # Look for camera, skip if not found.
            camera = self._lookup_camera_by_id(video.get("deviceId"))
            if camera is None:
                key = "{0}:{1}".format(
                    video.get("deviceId"),
                    arlotime_strftime(video.get("utcCreatedDate")),
                )
                self.vdebug("skipping {0}".format(key))
                continue

            # snapshots, use first found
            if video.get("reason", "") == "snapshot":
                if camera.device_id not in snapshots:
                    self.vdebug(f"adding snapshot for {camera.name}")
                    snapshots[camera.device_id] = self._create_snapshot(
                        video, camera
                    )
                continue

            content_type = video.get("contentType", "")

            # videos, add missing
            if content_type.startswith("video/") or content_type in VIDEO_CONTENT_TYPES:
                key = "{0}:{1}".format(
                    camera.device_id, arlotime_strftime(video.get("utcCreatedDate"))
                )
                if key in known_keys:
                    self.vdebug(f"skipping {key} for {camera.name}")
                    continue
                self.vdebug(f"adding {key} for {camera.name}")
                video_obj = self._create_video(video, camera)
                videos.append(video_obj)
                self._downloader.queue_download(video_obj)
                keys.append(key)
                known_keys.add(key)

        return videos, snapshots, keys

    # grab recordings from last day, add to existing library if not there
    async def update(self):
        self.debug("updating image library")

        # Get known videos.
        keys = list(self._video_keys)

        # Get today's new videos.
        date_to = datetime.today().strftime("%Y%m%d")
        videos, snapshots, updated_keys = await self._sync_library(date_to, date_to, keys)
        if videos is None:
            self._update_pending = False
            self._core.log.warning("error updating the image library")
            return

        # Append the new videos.
        self._count += 1
        self._videos = videos + self._videos
        self._video_keys = updated_keys
        self._snapshots = snapshots
        self.debug(f"update-count={self._count}, video-count={len(videos)}, snapshot-count={len(snapshots)}")
        cbs = self._load_cbs_
        self._load_cbs_ = []
        self._update_pending = False

        # run callbacks
        for cb in cbs:
            if asyncio.iscoroutinefunction(cb):
                await cb()
            else:
                cb()

    async def load(self):
        # set beginning and end
        cfg = getattr(self._core, "cfg", None)
        days = getattr(cfg, "library_days", 7)
        now = datetime.today()
        date_from = (now - timedelta(days=days)).strftime("%Y%m%d")
        date_to = now.strftime("%Y%m%d")
        self.debug(f"loading image library ({days} days)")

        videos, snapshots, keys = await self._sync_library(date_from, date_to, [])
        if videos is None:
            self._core.log.warning("error loading the image library")
            return

        # Set the initial library values.
        self._count += 1
        self._videos = videos
        self._video_keys = keys
        self._snapshots = snapshots
        self.debug(f"load-count={self._count}, video-count={len(videos)}, snapshot-count={len(snapshots)}")

    def snapshot_for(self, camera):
        return self._snapshots.get(camera.device_id, None)

    @property
    def videos(self):
        return self._count, self._videos

    @property
    def count(self):
        return self._count

    def videos_for(self, camera):
        camera_videos = []
        for video in self._videos:
            if camera.device_id == video.camera.device_id:
                camera_videos.append(video)
        return self._count, camera_videos

    def queue_update(self, cb):
        tasks = getattr(self._core, "tasks", None)
        if not self._update_pending:
            self.debug("queueing image library update")
            if tasks is not None and hasattr(tasks, "run_in"):
                tasks.run_in(self.update, 2)
            self._update_pending = True
        # Camera refreshes read the latest cache, not individual events.
        if cb not in self._load_cbs_:
            self._load_cbs_.append(cb)

    def stop(self):
        self._downloader.stop()

    def debug(self, msg):
        log = getattr(self._core, "log", None)
        if log is not None and hasattr(log, "debug"):
            log.debug(f"media-library: {msg}")
        elif hasattr(self._core, "debug"):
            self._core.debug(f"media-library: {msg}")

    def vdebug(self, msg):
        log = getattr(self._core, "log", None)
        if log is not None and hasattr(log, "vdebug"):
            log.vdebug(f"media-library: {msg}")
        elif hasattr(self._core, "vdebug"):
            self._core.vdebug(f"media-library: {msg}")


class ArloMediaObject:
    """Object for Arlo Video file."""

    def __init__(self, attrs, camera):
        """Video Object."""
        # self._arlo = arlo
        self._attrs = attrs
        self._camera = camera

    def __repr__(self):
        """Representation string of object."""
        return "<{0}:{1}>".format(self.__class__.__name__, self.name)

    @property
    def name(self):
        return "{0}:{1}".format(
            self._camera.device_id, arlotime_strftime(self.created_at)
        )

    # pylint: disable=invalid-name
    @property
    def id(self):
        """Returns unique id representing the video."""
        return self._attrs.get("name", None)

    @property
    def created_at(self):
        """Returns date video was creaed."""
        return self._attrs.get("utcCreatedDate", None)

    def created_at_pretty(self, date_format=None):
        """Returns date video was taken formated with `last_date_format`"""
        if date_format:
            return arlotime_strftime(self.created_at, date_format=date_format)
        return arlotime_strftime(self.created_at)

    @property
    def created_today(self):
        """Returns `True` if video was taken today, `False` otherwise."""
        return self.datetime.date() == datetime.today().date()

    @property
    def datetime(self):
        """Returns a python datetime object of when video was created."""
        return arlotime_to_datetime(self.created_at)

    @property
    def content_type(self):
        """Returns the video content type.

        Usually `video/mp4`
        """
        return self._attrs.get("contentType", None)

    @property
    def extension(self):
        if self.content_type.endswith("mp4"):
            return "mp4"
        if self.content_type in VIDEO_CONTENT_TYPES:
            return "mp4"
        return "jpg"

    @property
    def camera(self):
        return self._camera

    @property
    def triggered_by(self):
        return self._attrs.get("reason", None)

    @property
    def url(self):
        """Returns the URL of the video."""
        return self._attrs.get("presignedContentUrl", None)

    @property
    def thumbnail_url(self):
        """Returns the URL of the thumbnail image."""
        return self._attrs.get("presignedThumbnailUrl", None)

    async def download_thumbnail(self, filename=None):
        """Download thumbnail image file to disk or return image bytes.

        :param filename: Optional path to save image file to. If None, returns raw bytes.
        :return: True if saved to filename, or image bytes if filename is None.
        """
        return await http_get_async(self.thumbnail_url, filename)


class ArloVideo(ArloMediaObject):
    """Object for Arlo Video file."""

    def __init__(self, attrs, camera):
        """Video Object."""
        super().__init__(attrs, camera)

    @property
    def media_duration_seconds(self):
        """Returns how long the recording last."""
        return self._attrs.get("mediaDurationSecond", None)

    @property
    def object_type(self):
        """Returns what object caused the video to start.

        Currently is `vehicle`, `person`, `animal` or `other`.
        """
        return self._attrs.get("objCategory", None)

    @property
    def object_region(self):
        """Returns the region of the thumbnail showing the object."""
        return self._attrs.get("objRegion", None)

    @property
    def video_url(self):
        """Returns the URL of the video."""
        return self._attrs.get("presignedContentUrl", None)

    async def download_video(self, filename=None):
        """Download video file to disk or return video bytes.

        :param filename: Optional path to save video file to. If None, returns raw bytes.
        :return: True if saved to filename, or video bytes if filename is None.
        """
        return await http_get_async(self.video_url, filename)

    @property
    def stream_video(self):
        return http_stream(self.video_url)


class ArloSnapshot(ArloMediaObject):
    """Object for Arlo Snapshot file."""

    def __init__(self, attrs, camera):
        """Snapshot Object."""
        super().__init__(attrs, camera)

    @property
    def image_url(self):
        """Returns the URL of the video."""
        return self._attrs.get("presignedContentUrl", None)


# vim:sw=4:ts=4:et:
