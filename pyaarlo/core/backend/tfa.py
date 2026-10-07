from __future__ import annotations

import email
import imaplib
import re
import asyncio
import ssl
import time
import requests

from typing import Union

from ..cfg import ArloCfg
from ..logger import ArloLogger
from ...constant import (
    TFA_CONSOLE_SOURCE,
    TFA_IMAP_SOURCE,
    TFA_REST_API_SOURCE,
)

try:
    from curl_cffi.requests import AsyncSession as cffi_AsyncSession
except ImportError:
    cffi_AsyncSession = None  # type: ignore[assignment, misc]


class _TFABase:
    """Base  class for 2fa components.
    """

    def __init__(self, cfg: ArloCfg, log: ArloLogger, prefix: str):
        self._cfg: ArloCfg = cfg
        self._log: ArloLogger = log

        self._prefix: str = prefix

    def _debug(self, msg):
        self._log.debug(f"{self._prefix}: {msg}")

    async def start(self) -> bool:
        return True

    async def get(self) -> Union[str, None]:
        return None

    async def stop(self):
        pass


class _TFAConsole(_TFABase):
    """2FA authentication via console.
    Accepts input from console and returns that for 2FA.
    """

    def __init__(self, cfg: ArloCfg, log: ArloLogger):
        super().__init__(cfg, log, "2fa-console")

    async def start(self):
        self._debug("starting")
        return True

    async def get(self):
        self._debug("checking")
        return await asyncio.to_thread(input, "Enter Code: ")

    async def stop(self):
        self._debug("stopping")


class _TFAPush(_TFABase):
    """2FA authentication via console.
    Dummy for PUSH support. Always returns an empty code.
    """

    def __init__(self, cfg: ArloCfg, log: ArloLogger):
        super().__init__(cfg, log, "2fa-push")

    async def start(self):
        self._debug("starting")
        return True

    async def get(self):
        self._debug("checking")
        return ""

    async def stop(self):
        self._debug("stopping")


class _TFAImap(_TFABase):
    """2FA authentication via IMAP
    Connects to IMAP server and waits for email from Arlo with 2FA code in it.

    Note: will probably need tweaking for other IMAP setups...
    """

    def __init__(self, cfg: ArloCfg, log: ArloLogger):
        super().__init__(cfg, log, "2fa-imap")

        self._imap = None
        self._old_ids = None
        self._new_ids = None

    async def start(self):
        self._debug("starting")

        # clean up
        if self._imap is not None:
            await self.stop()

        try:
            # allow default ciphers to be specified
            cipher_list = self._cfg.cipher_list
            if cipher_list != "":
                ctx = ssl.create_default_context()
                ctx.set_ciphers(cipher_list)
                self._debug(f"imap is using custom ciphers {cipher_list}")
            else:
                ctx = None

            def _do_login():
                imap = imaplib.IMAP4_SSL(self._cfg.tfa_host, port=self._cfg.tfa_port, ssl_context=ctx)
                if self._cfg.verbose:
                    imap.debug = 4
                res, status = imap.login(
                    self._cfg.tfa_username, self._cfg.tfa_password
                )
                if res.lower() != "ok":
                    return None, "login failed"
                res, status = imap.select(mailbox='INBOX', readonly=True)
                if res.lower() != "ok":
                    return None, "select failed"
                res, old_ids = imap.search(
                    None, "FROM", "do_not_reply@arlo.com"
                )
                if res.lower() != "ok":
                    return None, "search failed"
                return imap, old_ids

            self._imap, self._old_ids = await asyncio.to_thread(_do_login)
            if self._imap is None:
                self._debug(f"imap login/setup failed: {self._old_ids}")
                return False
        except Exception as e:
            self._log.error(f"imap connection failed{str(e)}")
            return False

        self._new_ids = self._old_ids
        self._debug("old-ids={}".format(self._old_ids))
        return True

    async def get(self):
        self._debug("checking")

        # give tfa_total_timeout seconds for email to arrive
        start = time.time()
        while True:

            # wait a short while, stop after a total timeout
            # OK to do on first run gives email time to arrive
            await asyncio.sleep(self._cfg.tfa_timeout)
            if time.time() > (start + self._cfg.tfa_total_timeout):
                return None

            try:
                # grab new email ids
                def _do_check():
                    self._imap.check()
                    res, new_ids = self._imap.search(
                        None, "FROM", "do_not_reply@arlo.com"
                    )
                    return res, new_ids

                res, self._new_ids = await asyncio.to_thread(_do_check)
                self._debug("new-ids={}".format(self._new_ids))
                if self._new_ids == self._old_ids:
                    self._debug("no change in emails")
                    continue

                # New message. Reverse so we look at the newest one first.
                old_ids = self._old_ids[0].split()
                msg_ids = self._new_ids[0].split()
                msg_ids.reverse()
                for msg_id in msg_ids:

                    # Seen it?
                    if msg_id in old_ids:
                        continue

                    # New message. Look at all the parts and try to grab the code, if we catch an exception
                    # just move onto the next part.
                    self._debug("new-msg={}".format(msg_id))
                    
                    def _do_fetch():
                        return self._imap.fetch(msg_id, "(BODY.PEEK[])")
                    
                    res, parts = await asyncio.to_thread(_do_fetch)

                    for msg in parts:
                        try:
                            if isinstance(msg[1], bytes):
                                for part in email.message_from_bytes(msg[1]).walk():
                                    if part.get_content_type() not in ("text/plain", "text/html"):
                                        continue
                                    payload = part.get_payload(decode=True)
                                    if not payload:
                                        continue
                                    charset = part.get_content_charset() or "utf-8"
                                    try:
                                        body_text = payload.decode(charset, errors="replace")
                                    except Exception as e:
                                        self._debug(f"decode failed: {e}")
                                        continue
                                    for line in body_text.splitlines():
                                        # match code in email, this might need some work if the email changes
                                        code = re.match(r"^\W*(\d{6})\W*$", line.strip())
                                        if code is not None:
                                            self._debug(f"code={code.group(1)}")
                                            return code.group(1)
                        except Exception as e:
                            self._debug(f"trying next part {str(e)}")

                # Update old so we don't keep trying new.
                # Yahoo can lose ids so we extend the old list.
                self._old_ids.extend(new_id for new_id in self._new_ids if new_id not in self._old_ids)

            # problem parsing the message, force a fail
            except Exception as e:
                self._log.error(f"imap message read failed{str(e)}")
                return None

        return None

    async def stop(self):
        self._debug("stopping")

        if self._imap:
            def _do_logout():
                try:
                    self._imap.close()
                    self._imap.logout()
                except Exception:
                    pass
            await asyncio.to_thread(_do_logout)
        self._imap = None
        self._old_ids = None
        self._new_ids = None


class _TFARestAPI(_TFABase):
    """2FA authentication via rest API.
    Queries web site until code appears
    """

    def __init__(self, cfg: ArloCfg, log: ArloLogger):
        super().__init__(cfg, log, "2fa-rest-api")
        self._session: Union[cffi_AsyncSession, None] = None

    async def start(self):
        self._debug("starting")
        if self._cfg.tfa_host is None or self._cfg.tfa_password is None:
            self._debug("invalid config")
            return False

        if cffi_AsyncSession is not None:
            self._session = cffi_AsyncSession()

        self._debug("clearing")
        url = "{}/clear?email={}&token={}".format(
                self._cfg.tfa_host_with_scheme("https"),
                self._cfg.tfa_username,
                self._cfg.tfa_password,
            )
        
        if self._session:
            response = await self._session.get(url, timeout=10)
            status_code = response.status_code
        else:
            response = await asyncio.to_thread(requests.get, url, timeout=10)
            status_code = response.status_code
            
        if status_code != 200:
            self._debug("possible problem clearing")

        return True

    async def get(self):
        self._debug("checking")

        # give tfa_total_timeout seconds for email to arrive
        start = time.time()
        while True:

            # wait a short while, stop after a total timeout
            # OK to do on first run gives email time to arrive
            await asyncio.sleep(self._cfg.tfa_timeout)
            if time.time() > (start + self._cfg.tfa_total_timeout):
                return None

            # Try for the token.
            self._debug("checking")
            url = "{}/get?email={}&token={}".format(
                    self._cfg.tfa_host_with_scheme("https"),
                    self._cfg.tfa_username,
                    self._cfg.tfa_password,
                )
            
            if self._session:
                response = await self._session.get(url, timeout=10)
                status_code = response.status_code
                body = response.json() if status_code == 200 else {}
            else:
                response = await asyncio.to_thread(requests.get, url, timeout=10)
                status_code = response.status_code
                body = response.json() if status_code == 200 else {}
                
            if status_code == 200:
                code = body.get("data", {}).get("code", None)
                if code is not None:
                    self._debug("code={}".format(code))
                    return code

            self._debug("retrying")

    async def stop(self):
        self._debug("stopping")
        if self._session:
            await self._session.close()
            self._session = None


class ArloTFA:
    """Arlo Two Factor Authentication handler.

    This is created as needed. We currentl have these options:
    - CONSOLE; input is typed in, message is usually sent by SMS or EMAIL and
      user has to type it
    - IMAP; code is sent by email and automtically read by pyaarlo
    - REST_API; deprecated...
    - PUSH; user has to accept a prompt on their Arlo app

    PUSH is odd because the code doesn't retrieve an otp, we have to wait for
    finishAuth to return a 200.
    """


    def __init__(self, cfg: ArloCfg, log: ArloLogger):
        """Determine which tfa mechanism to use and set up the handlers if needed.
        """
        self._cfg = cfg
        self._log = log
        self._type: str = cfg.tfa_source

        self._handler: Union[_TFABase, None] = None
        self._factor_type: str = "BROWSER"
        if self._type == TFA_CONSOLE_SOURCE:
            self._handler = _TFAConsole(cfg, log)
        elif self._type == TFA_IMAP_SOURCE:
            self._handler = _TFAImap(cfg, log)
        elif self._type == TFA_REST_API_SOURCE:
            self._handler = _TFARestAPI(cfg, log)
        else:
            self._handler = _TFAPush(cfg, log)
            self._factor_type = ""
    
    async def start(self) -> bool:
        if self._handler is not None:
            return await self._handler.start()
        return False
    
    async def code(self) -> Union[str, None]:
        """Get the "otp" from the tfa source.
    
        This returns one of 3 things:
         - a 6 digit one-time-pin code
         - None; meaning the tfa failed
         - an empty string which indicates "finishAuth" does the waiting
        """
        if self._handler is not None:
            return await self._handler.get()
        return None
    
    @property
    def type(self) -> Union[str, None]:
        return self._type
    
    @property
    def factor_type(self) -> str:
        return self._factor_type
    
    async def stop(self):
        await self._handler.stop()
        self._handler = None
        self._type = None

