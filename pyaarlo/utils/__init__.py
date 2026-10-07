import asyncio
import base64
import time
from datetime import datetime, timezone
from typing import Any

import requests

try:
    from curl_cffi.requests import AsyncSession as cffi_AsyncSession
except ImportError:
    cffi_AsyncSession = None  # type: ignore[assignment, misc]


async def http_get_async(url, filename=None):
    """Download HTTP data (async)."""
    if url is None:
        return None

    if cffi_AsyncSession is not None:
        async with cffi_AsyncSession() as session:
            response = await session.get(url)
            if response.status_code != 200:
                return False if filename else None
            content = response.content
    else:
        def _do_get():
            try:
                ret = requests.get(url)
                if ret.status_code == 200:
                    return ret.content
            except Exception:
                pass
            return None
        content = await asyncio.get_running_loop().run_in_executor(None, _do_get)

    if content is None:
        return False if filename else None

    if filename is None:
        return content

    def _save_file():
        with open(filename, "wb") as data:
            data.write(content)
    await asyncio.get_running_loop().run_in_executor(None, _save_file)
    return True


async def http_get_img_async(url, ignore_date=False):
    """Download HTTP image data (async)."""
    if url is None:
        return None, datetime.now().astimezone()

    if cffi_AsyncSession is not None:
        async with cffi_AsyncSession() as session:
            response = await session.get(url)
            if response.status_code != 200:
                return None, datetime.now().astimezone()
            content = response.content
            headers = response.headers
    else:
        def _do_get():
            try:
                ret = requests.get(url)
                if ret.status_code == 200:
                    return ret.content, ret.headers
            except Exception:
                pass
            return None, {}
        content, headers = await asyncio.get_running_loop().run_in_executor(None, _do_get)

    if content is None:
        return None, datetime.now().astimezone()

    date = None
    if not ignore_date:
        date = headers.get("Last-Modified", None)
        if date is not None:
            date = httptime_to_datetime(date)
    if date is None:
        date = datetime.now().astimezone()

    return content, date


def utc_to_local(utc_dt):
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(tz=None)


def the_epoch():
    return utc_to_local(datetime.fromtimestamp(0, tz=timezone.utc))


def arlotime_to_time(timestamp):
    """Convert Arlo timestamp to Unix timestamp."""
    return int(timestamp / 1000)


def arlotime_to_datetime(timestamp):
    """Convert Arlo timestamp to Python datetime."""
    return utc_to_local(datetime.fromtimestamp(int(timestamp / 1000), tz=timezone.utc))


def arlotime_strftime(timestamp, date_format="%Y-%m-%dT%H:%M:%S"):
    """Convert Arlo timestamp to time string."""
    return arlotime_to_datetime(timestamp).strftime(date_format)


def time_to_arlotime(timestamp=None):
    """Convert Unix timestamp to Arlo timestamp."""
    if timestamp is None:
        timestamp = time.time()
    return int(timestamp * 1000)


def now_strftime(date_format="%Y-%m-%dT%H:%M:%S"):
    """Convert now to time string."""
    return datetime.now().strftime(date_format)


def days_until(when):
    now = datetime.now()
    when = datetime.utcfromtimestamp(when)
    if when <= now:
        return 0
    return (when - now).days


def httptime_to_datetime(http_timestamp):
    """Convert HTTP timestamp to Python datetime."""
    return utc_to_local(datetime.strptime(http_timestamp, "%a, %d %b %Y %H:%M:%S GMT"))


def httptime_strftime(http_timestamp, date_format="%Y-%m-%dT%H:%M:%S"):
    """Convert HTTP timestamp to time string."""
    return httptime_to_datetime(http_timestamp).strftime(date_format)


def _http_get(url):
    """Download HTTP data."""

    if url is None:
        return None

    try:
        ret = requests.get(url)
    except requests.exceptions.SSLError:
        return None
    except Exception:
        return None

    if ret.status_code != 200:
        return None
    return ret


def http_get(url, filename=None):
    """Download HTTP data."""

    ret = _http_get(url)
    if ret is None:
        return False

    if filename is None:
        return ret.content

    with open(filename, "wb") as data:
        data.write(ret.content)
    return True


def http_get_img(url, ignore_date=False):
    """Download HTTP image data."""

    ret = _http_get(url)
    if ret is None:
        return None, datetime.now().astimezone()

    date = None
    if not ignore_date:
        date = ret.headers.get("Last-Modified", None)
        if date is not None:
            date = httptime_to_datetime(date)
    if date is None:
        date = datetime.now().astimezone()

    return ret.content, date


async def http_stream(url, chunk=4096):
    """Generate stream for a given record video.

    :param url: url of stream to read
    :param chunk: chunk bytes to read per time
    :returns async generator object
    """
    if cffi_AsyncSession is not None:
        async with cffi_AsyncSession() as session:
            response = await session.get(url, stream=True)
            async for data in response.iter_content(chunk):
                yield data
    else:
        # Fallback to sync requests in thread pool if curl_cffi is not available
        # This is tricky for a generator, but we can use a queue
        queue = asyncio.Queue()

        def _do_stream():
            try:
                ret = requests.get(url, stream=True)
                ret.raise_for_status()
                for data in ret.iter_content(chunk):
                    asyncio.run_coroutine_threadsafe(queue.put(data), asyncio.get_running_loop())
            except Exception:
                pass
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), asyncio.get_running_loop())

        _ = asyncio.get_running_loop().run_in_executor(None, _do_stream)
        while True:
            data = await queue.get()
            if data is None:
                break
            yield data


def rgb_to_hex(rgb):
    """Convert HA color to Arlo color."""
    return "#{:02x}{:02x}{:02x}".format(rgb[0], rgb[1], rgb[2])


def hex_to_rgb(h):
    """Convert Arlo color to HA color."""
    return {"red": int(h[1:3], 16), "green": int(h[3:5], 16), "blue": int(h[5:7], 16)}


def to_b64(in_str):
    """Convert a string into a base64 string."""
    return base64.b64encode(in_str.encode()).decode()
