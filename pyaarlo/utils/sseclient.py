import codecs
import http.client
import re
import time
import warnings
import socket
import asyncio

import requests

try:
    from curl_cffi.requests import AsyncSession as cffi_AsyncSession
except ImportError:
    cffi_AsyncSession = None  # type: ignore[assignment, misc]

# Technically, we should support streams that mix line endings.  This regex,
# however, assumes that a system will provide consistent line endings.
end_of_field = re.compile(r"\r\n\r\n|\r\r|\n\n")


class AsyncSSEClient:
    def __init__(
        self,
        log,
        url,
        last_id=None,
        retry=3000,
        session=None,
        chunk_size=1024,
        reconnect_cb=None,
        **kwargs
    ):
        self.log = log
        self.url = url
        self.last_id = last_id
        self.retry = retry
        self.chunk_size = chunk_size
        self.running = True
        self.reconnect_cb = reconnect_cb

        # Optional support for passing in a requests.Session()
        self.session = session

        # Any extra kwargs will be fed into the requests.get call later.
        self.requests_kwargs = kwargs

        # The SSE spec requires making requests with Cache-Control: nocache
        if "headers" not in self.requests_kwargs:
            self.requests_kwargs["headers"] = {}
        self.requests_kwargs["headers"]["Cache-Control"] = "no-cache"

        # The 'Accept' header is not required, but explicit > implicit
        self.requests_kwargs["headers"]["Accept"] = "text/event-stream"

        # Remove these.
        self.requests_kwargs["headers"]["Content-Type"] = None
        self.requests_kwargs["headers"]["host"] = None

        # Keep data here as it streams in
        self.buf = u""

    async def stop(self):
        self.debug("stop called")
        self.running = False
        if hasattr(self, "resp") and self.resp:
            if getattr(self, "_is_async_session", False) and hasattr(self.resp, "close") and asyncio.iscoroutinefunction(self.resp.close):
                await self.resp.close()
            elif hasattr(self.resp, "close"):
                await asyncio.to_thread(self.resp.close)

    async def disconnect(self):
        await self.stop()

    async def _connect(self):
        if self.last_id:
            self.requests_kwargs["headers"]["Last-Event-ID"] = self.last_id

        # Use session if set. Otherwise fall back to requests module.
        is_async = (cffi_AsyncSession is not None and isinstance(self.session, cffi_AsyncSession)) or (
            self.session is not None and asyncio.iscoroutinefunction(getattr(self.session, "get", None))
        )
        if is_async:
            self._is_async_session = True
            self.resp = await self.session.get(self.url, stream=True, **self.requests_kwargs)
            self.resp_iterator = self.resp.iter_content(chunk_size=self.chunk_size)
        else:
            self._is_async_session = False
            sess = self.session if self.session is not None else requests
            def _do_get():
                return sess.get(self.url, stream=True, **self.requests_kwargs)
            self.resp = await asyncio.to_thread(_do_get)
            self._sync_iterator = self.resp.iter_content(chunk_size=self.chunk_size)

        if self.resp.status_code != 200:
            self.log.error(f"sseclient: connect failed {self.resp.status_code}")

    def _event_complete(self):
        return re.search(end_of_field, self.buf) is not None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not hasattr(self, "resp"):
            await self._connect()

        encoding = getattr(self.resp, "encoding", None) or "utf-8"
        decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
        while not self._event_complete():
            try:
                if self._is_async_session:
                    next_chunk = await self.resp_iterator.__anext__()
                else:
                    def _get_next_chunk():
                        try:
                            return next(self._sync_iterator)
                        except StopIteration:
                            raise EOFError()
                    next_chunk = await asyncio.to_thread(_get_next_chunk)

                if not next_chunk:
                    raise EOFError()
                self.buf += decoder.decode(next_chunk)

            except (
                StopAsyncIteration,
                EOFError,
            ) as e:
                if not self.running:
                    self.debug("stopping #1")
                    raise StopAsyncIteration

                self.debug("error={}".format(type(e).__name__))
                await asyncio.sleep(self.retry / 1000.0)
                await self._connect()

                # The SSE spec only supports resuming from a whole message, so
                # if we have half a message we should throw it out.
                head, sep, tail = self.buf.rpartition("\n")
                self.buf = head + sep
                continue
            except Exception as e:
                self.debug("exception={}".format(type(e).__name__))
                if not self.running:
                    raise StopAsyncIteration
                await asyncio.sleep(self.retry / 1000.0)
                await self._connect()
                continue

        if not self.running:
            self.debug("stopping #2")
            raise StopAsyncIteration

        # Split the complete event (up to the end_of_field) into event_string,
        # and retain anything after the current complete event in self.buf
        # for next time.
        (event_string, self.buf) = re.split(end_of_field, self.buf, maxsplit=1)
        msg = Event.parse(event_string)

        # If the server requests a specific retry delay, we need to honor it.
        if msg.retry:
            self.retry = msg.retry

        # last_id should only be set if included in the message.  It's not
        # forgotten if a message omits it.
        if msg.id:
            self.last_id = msg.id

        return msg

    def debug(self, msg):
        self.log.debug(f"sseclient: {msg}")


class SSEClient:
    def __init__(
        self,
        log,
        url,
        last_id=None,
        retry=3000,
        session=None,
        chunk_size=1024,
        reconnect_cb=None,
        **kwargs
    ):
        self.log = log
        self.url = url
        self.last_id = last_id
        self.retry = retry
        self.chunk_size = chunk_size
        self.running = True
        self.reconnect_cb = reconnect_cb

        # Optional support for passing in a requests.Session()
        self.session = session

        # Any extra kwargs will be fed into the requests.get call later.
        self.requests_kwargs = kwargs

        # The SSE spec requires making requests with Cache-Control: nocache
        if "headers" not in self.requests_kwargs:
            self.requests_kwargs["headers"] = {}
        self.requests_kwargs["headers"]["Cache-Control"] = "no-cache"

        # The 'Accept' header is not required, but explicit > implicit
        self.requests_kwargs["headers"]["Accept"] = "text/event-stream"

        # Remove these.
        self.requests_kwargs["headers"]["Content-Type"] = None
        self.requests_kwargs["headers"]["host"] = None

        # Keep data here as it streams in
        self.buf = u""

        self._connect()

    def stop(self):
        self.debug("stop called")
        self.running = False
        if hasattr(self, 'resp') and self.resp:
            raw_response = self.resp

            # This navigates through urllib3 down to the actual python socket object
            if hasattr(raw_response, 'raw') and raw_response.raw:
                urllib3_connection = raw_response.raw._connection
                if urllib3_connection and urllib3_connection.sock:
                    raw_socket = urllib3_connection.sock

                    # 2. THE MAGIC BULLET: Shatter the socket pipeline at the OS level
                    # SHUT_RDWR tells the OS: "Stop reading and stop writing right now."
                    raw_socket.shutdown(socket.SHUT_RDWR)

                    # 3. Now close the wrapper safely
                    raw_socket.close()

            # Fallback to standard close just in case
            raw_response.close()

    def disconnect(self):
        self.stop()

    def _connect(self):
        if self.last_id:
            self.requests_kwargs["headers"]["Last-Event-ID"] = self.last_id

        # Use session if set.  Otherwise fall back to requests module.
        requester = self.session or requests
        self.resp = requester.get(self.url, stream=True, **self.requests_kwargs)
        self.resp_iterator = self.resp.iter_content(chunk_size=self.chunk_size)

        # TODO: Ensure we're handling redirects.  Might also stick the 'origin'
        # attribute on Events like the Javascript spec requires.
        self.resp.raise_for_status()

    def _event_complete(self):
        return re.search(end_of_field, self.buf) is not None

    def __iter__(self):
        return self

    def __next__(self):
        decoder = codecs.getincrementaldecoder(self.resp.encoding)(errors="replace")
        while not self._event_complete():
            try:
                next_chunk = next(self.resp_iterator)
                if not next_chunk:
                    raise EOFError()
                self.buf += decoder.decode(next_chunk)

            except (
                StopIteration,
                requests.RequestException,
                EOFError,
                http.client.IncompleteRead,
            ) as e:
                if not self.running:
                    self.debug("stopping #1")
                    return None

                self.debug("error={}".format(type(e).__name__))
                time.sleep(self.retry / 1000.0)
                self._connect()

                # signal up!
                # if self.reconnect_cb:
                #     self.reconnect_cb()

                # The SSE spec only supports resuming from a whole message, so
                # if we have half a message we should throw it out.
                head, sep, tail = self.buf.rpartition("\n")
                self.buf = head + sep
                continue

        if not self.running:
            self.debug("stopping #2")
            return None

        # Split the complete event (up to the end_of_field) into event_string,
        # and retain anything after the current complete event in self.buf
        # for next time.
        (event_string, self.buf) = re.split(end_of_field, self.buf, maxsplit=1)
        msg = Event.parse(event_string)

        # If the server requests a specific retry delay, we need to honor it.
        if msg.retry:
            self.retry = msg.retry

        # last_id should only be set if included in the message.  It's not
        # forgotten if a message omits it.
        if msg.id:
            self.last_id = msg.id

        return msg

    def debug(self, msg):
        self.log.debug(f"sseclient: {msg}")


class Event:
    sse_line_pattern = re.compile("(?P<name>[^:]*):?( ?(?P<value>.*))?")

    def __init__(self, data="", event="message", id=None, retry=None):
        self.data = data
        self.event = event
        self.id = id
        self.retry = retry

    def dump(self):
        lines = []
        if self.id:
            lines.append("id: %s" % self.id)

        # Only include an event line if it's not the default already.
        if self.event != "message":
            lines.append("event: %s" % self.event)

        if self.retry:
            lines.append("retry: %s" % self.retry)

        lines.extend("data: %s" % d for d in self.data.split("\n"))
        return "\n".join(lines) + "\n\n"

    @classmethod
    def parse(cls, raw):
        """
        Given a possibly-multiline string representing an SSE message, parse it
        and return a Event object.
        """
        msg = cls()
        for line in raw.splitlines():
            m = cls.sse_line_pattern.match(line)
            if m is None:
                # Malformed line.  Discard but warn.
                warnings.warn('Invalid SSE line: "%s"' % line, SyntaxWarning)
                continue

            name = m.group("name")
            if name == "":
                # line began with a ":", so is a comment.  Ignore
                continue
            value = m.group("value")

            if name == "data":
                # If we already have some data, then join to it with a newline.
                # Else this is it.
                if msg.data:
                    msg.data = "%s\n%s" % (msg.data, value)
                else:
                    msg.data = value
            elif name == "event":
                msg.event = value
            elif name == "id":
                msg.id = value
            elif name == "retry":
                msg.retry = int(value)

        return msg

    def __str__(self):
        return self.data
