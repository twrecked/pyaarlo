import os
import threading
from datetime import datetime, timedelta
from string import Template
from slugify import slugify

from .constant import (
    LIBRARY_PATH,
    VIDEO_CONTENT_TYPES
)
from .core import ArloCore
from .objects import ArloObjects
from .util import arlotime_strftime, arlotime_to_datetime, http_get, http_stream


class ArloMediaDownloader(threading.Thread):
    def __init__(self, core: ArloCore, save_format):
        super().__init__()
        self._core = core
        self._save_format = save_format
        self._lock = threading.Condition()
        self._queue = []
        self._stopThread = False
        self._downloading = False

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

    def _download(self, media):
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
            os.makedirs(os.path.dirname(save_file), exist_ok=True)
            if not os.path.exists(save_file):
                # Download to temporary file before renaming it.
                self.debug(f"dowloading for {media.camera.name} --> {save_file}")
                save_file_tmp = f"{save_file}.tmp"
                media.download_video(save_file_tmp)
                os.rename(save_file_tmp, save_file)
                return 1
            else:
                self.vdebug(
                    f"skipping dowload for {media.camera.name} --> {save_file}"
                )
                return 0
        except OSError as _e:
            self._core.log.error(f"failed to download: {save_file}")
            return -1

    def run(self):
        if self._save_format == "":
            self.debug("not starting downloader")
            return
        with self._lock:
            while not self._stopThread:
                media = None
                result = 0
                if len(self._queue) > 0:
                    media = self._queue.pop(0)
                    self._downloading = True

                self._lock.release()
                if media is not None:
                    result = self._download(media)
                self._lock.acquire()

                self._downloading = False
                # Nothing else to do then just wait.
                if len(self._queue) == 0:
                    self.vdebug(f"waiting for media")
                    self._lock.wait(60.0)
                # We downloaded a file so inject a small delay.
                elif result == 1:
                    self._lock.wait(0.5)

    def queue_download(self, media):
        if self._save_format == "":
            return
        with self._lock:
            self._queue.append(media)
            if len(self._queue) == 1:
                self._lock.notify()

    def stop(self):
        if self._save_format == "":
            return
        with self._lock:
            self._stopThread = True
            self._lock.notify()
        self.join(10)

    @property
    def processing(self):
        with self._lock:
            return len(self._queue) > 0 or self._downloading

    def debug(self, msg):
        self._core.log.debug(f"media-downloader: {msg}")

    def vdebug(self, msg):
        self._core.log.vdebug(f"media-downloader: {msg}")


class ArloMediaLibrary:
    """Arlo Library Media module implementation."""

    _code: ArloCore
    _objs: ArloObjects

    def __init__(self, core: ArloCore, objs: ArloObjects):
        self._core = core
        self._objs = objs

        self._lock = threading.Lock()
        self._load_cbs_ = []
        self._count = 0
        self._videos = []
        self._video_keys = []
        self._snapshots = {}

        self._downloader = ArloMediaDownloader(core, self._core.cfg.save_media_to)
        self._downloader.name = "ArloMediaDownloader"
        self._downloader.daemon = True
        self._downloader.start()

    def __repr__(self):
        return "<{0}:{1}>".format(self.__class__.__name__, self._core.cfg.name)

    def _fetch_library(self, date_from, date_to):
        """Get the library.

        Override as needed.
        """
        return self._core.be.post(
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

    def _sync_library(self, date_from, date_to, keys):
        """Read library between dates given, add videos not present.

        Passing an empty keys will cause all video information in the given
        date range to be recorded.
        """

        # Fetch video metadata.
        data = self._fetch_library(date_from, date_to)
        if data is None:
            self._core.log.warning("error loading the image library")
            return None, None, None

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
                    self.debug(f"adding snapshot for {camera.name}")
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
                if key in keys:
                    self.vdebug(f"skipping {key} for {camera.name}")
                    continue
                self.debug(f"adding {key} for {camera.name}")
                video = self._create_video(video, camera,)
                videos.append(video)
                self._downloader.queue_download(video)
                keys.append(key)

        return videos, snapshots, keys

    # grab recordings from last day, add to existing library if not there
    def update(self):
        self.debug("updating image library")

        # Get known videos.
        with self._lock:
            keys = self._video_keys

        # Get today's new videos.
        date_to = datetime.today().strftime("%Y%m%d")
        videos, snapshots, keys = self._sync_library(date_to, date_to, keys)
        if videos is None:
            self._core.log.warning("error updating the image library")
            return

        # Append the new videos.
        with self._lock:
            self._count += 1
            self._videos = videos + self._videos
            self._video_keys = keys
            self._snapshots = snapshots
            self.debug(f"update-count={self._count}, video-count={len(videos)}, snapshot-count={len(snapshots)}")
            cbs = self._load_cbs_
            self._load_cbs_ = []

        # run callbacks with no locks held
        for cb in cbs:
            cb()

    def load(self):

        # set beginning and end
        days = self._core.cfg.library_days
        now = datetime.today()
        date_from = (now - timedelta(days=days)).strftime("%Y%m%d")
        date_to = now.strftime("%Y%m%d")
        self.debug(f"loading image library ({days} days)")

        # save videos for cameras we know about
        videos, snapshots, keys = self._sync_library(date_from, date_to, [])
        if videos is None:
            self._core.log.warning("error loading the image library")
            return

        # Set the initial library values.
        with self._lock:
            self._count += 1
            self._videos = videos
            self._video_keys = keys
            self._snapshots = snapshots
            self.debug(f"load-count={self._count}, video-count={len(videos)}, snapshot-count={len(snapshots)}")

    def snapshot_for(self, camera):
        with self._lock:
            return self._snapshots.get(camera.device_id, None)

    @property
    def videos(self):
        with self._lock:
            return self._count, self._videos

    @property
    def count(self):
        with self._lock:
            return self._count

    def videos_for(self, camera):
        camera_videos = []
        with self._lock:
            for video in self._videos:
                if camera.device_id == video.camera.device_id:
                    camera_videos.append(video)
            return self._count, camera_videos

    def queue_update(self, cb):
        with self._lock:
            if not self._load_cbs_:
                self.debug("queueing image library update")
                self._core.bg.run_low_in(self.update, 2)
            self._load_cbs_.append(cb)

    def stop(self):
        self._downloader.stop()

    def debug(self, msg):
        self._core.log.debug(f"media-library: {msg}")

    def vdebug(self, msg):
        self._core.log.vdebug(f"media-library: {msg}")


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

    def download_thumbnail(self, filename=None):
        return http_get(self.thumbnail_url, filename)


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

    def download_video(self, filename=None):
        return http_get(self.video_url, filename)

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
