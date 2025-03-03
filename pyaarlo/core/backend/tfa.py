from __future__ import annotations

import email
import imaplib
import re
import requests
import ssl
import time

from ..cfg import ArloCfg
from ..logger import ArloLogger

from ...constant import (
    TFA_CONSOLE_SOURCE,
    TFA_IMAP_SOURCE,
    TFA_REST_API_SOURCE,
)


class _TFABase:
    """Base  class for 2fa components.
    """

    _cfg: ArloCfg
    _log: ArloLogger
    _prefix: str = ""

    def __init__(self, cfg: ArloCfg, log: ArloLogger, prefix: str):
        self._cfg = cfg
        self._log = log
        self._prefix = prefix

    def _debug(self, msg):
        self._log.debug(f"{self._prefix}: {msg}")

    def start(self) -> bool:
        return True

    def get(self) -> str | None:
        return None

    def stop(self):
        pass


class _TFAConsole(_TFABase):
    """2FA authentication via console.
    Accepts input from console and returns that for 2FA.
    """

    def __init__(self, cfg: ArloCfg, log: ArloLogger):
        super().__init__(cfg, log, "2fa-console")

    def start(self):
        self._debug("starting")
        return True

    def get(self):
        self._debug("checking")
        return input("Enter Code: ")

    def stop(self):
        self._debug("stopping")


class _TFAPush(_TFABase):
    """2FA authentication via console.
    Dummy for PUSH support. Always returns an empty code.
    """

    def __init__(self, cfg: ArloCfg, log: ArloLogger):
        super().__init__(cfg, log, "2fa-push")

    def start(self):
        self._debug("starting")
        return True

    def get(self):
        self._debug("checking")
        return ""

    def stop(self):
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

    def start(self):
        self._debug("starting")

        # clean up
        if self._imap is not None:
            self.stop()

        try:
            # allow default ciphers to be specified
            cipher_list = self._cfg.cipher_list
            if cipher_list != "":
                ctx = ssl.create_default_context()
                ctx.set_ciphers(cipher_list)
                self._debug(f"imap is using custom ciphers {cipher_list}")
            else:
                ctx = None

            self._imap = imaplib.IMAP4_SSL(self._cfg.tfa_host, port=self._cfg.tfa_port, ssl_context=ctx)
            if self._cfg.verbose:
                self._imap.debug = 4
            res, status = self._imap.login(
                self._cfg.tfa_username, self._cfg.tfa_password
            )
            if res.lower() != "ok":
                self._debug("imap login failed")
                return False
            res, status = self._imap.select(mailbox='INBOX', readonly=True)
            if res.lower() != "ok":
                self._debug("imap select failed")
                return False
            res, self._old_ids = self._imap.search(
                None, "FROM", "do_not_reply@arlo.com"
            )
            if res.lower() != "ok":
                self._debug("imap search failed")
                return False
        except Exception as e:
            self._log.error(f"imap connection failed{str(e)}")
            return False

        self._new_ids = self._old_ids
        self._debug("old-ids={}".format(self._old_ids))
        if res.lower() == "ok":
            return True

        return False

    def get(self):
        self._debug("checking")

        # give tfa_total_timeout seconds for email to arrive
        start = time.time()
        while True:

            # wait a short while, stop after a total timeout
            # OK to do on first run gives email time to arrive
            time.sleep(self._cfg.tfa_timeout)
            if time.time() > (start + self._cfg.tfa_total_timeout):
                return None

            try:
                # grab new email ids
                self._imap.check()
                res, self._new_ids = self._imap.search(
                    None, "FROM", "do_not_reply@arlo.com"
                )
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
                    res, parts = self._imap.fetch(msg_id, "(BODY.PEEK[])")
                    # res, parts = self._imap.fetch(msg_id, "(RFC822)")

                    for msg in parts:
                        try:
                            if isinstance(msg[1], bytes):
                                for part in email.message_from_bytes(msg[1]).walk():
                                    if part.get_content_type() != "text/html":
                                        continue
                                    for line in part.get_payload(decode=True).splitlines():
                                        # match code in email, this might need some work if the email changes
                                        code = re.match(r"^\W+(\d{6})\W*$", line.decode())
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

    def stop(self):
        self._debug("stopping")

        self._imap.close()
        self._imap.logout()
        self._imap = None
        self._old_ids = None
        self._new_ids = None


class _TFARestAPI(_TFABase):
    """2FA authentication via rest API.
    Queries web site until code appears
    """

    def __init__(self, cfg: ArloCfg, log: ArloLogger):
        super().__init__(cfg, log, "2fa-rest-api")

    def start(self):
        self._debug("starting")
        if self._cfg.tfa_host is None or self._cfg.tfa_password is None:
            self._debug("invalid config")
            return False

        self._debug("clearing")
        response = requests.get(
            "{}/clear?email={}&token={}".format(
                self._cfg.tfa_host_with_scheme("https"),
                self._cfg.tfa_username,
                self._cfg.tfa_password,
            ),
            timeout=10,
        )
        if response.status_code != 200:
            self._debug("possible problem clearing")

        return True

    def get(self):
        self._debug("checking")

        # give tfa_total_timeout seconds for email to arrive
        start = time.time()
        while True:

            # wait a short while, stop after a total timeout
            # OK to do on first run gives email time to arrive
            time.sleep(self._cfg.tfa_timeout)
            if time.time() > (start + self._cfg.tfa_total_timeout):
                return None

            # Try for the token.
            self._debug("checking")
            response = requests.get(
                "{}/get?email={}&token={}".format(
                    self._cfg.tfa_host_with_scheme("https"),
                    self._cfg.tfa_username,
                    self._cfg.tfa_password,
                ),
                timeout=10,
            )
            if response.status_code == 200:
                code = response.json().get("data", {}).get("code", None)
                if code is not None:
                    self._debug("code={}".format(code))
                    return code

            self._debug("retrying")

    def stop(self):
        self._debug("stopping")


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

    _handler: _TFABase | None = None
    _type: str | None = None
    _factor_type: str = "BROWSER"
    
    def __init__(self, cfg: ArloCfg, log: ArloLogger):
        """Determine which tfa mechanism to use and set up the handlers if needed.
        """

        self._type = cfg.tfa_source
        if self._type == TFA_CONSOLE_SOURCE:
            self._handler = _TFAConsole(cfg, log)
        elif self._type == TFA_IMAP_SOURCE:
            self._handler = _TFAImap(cfg, log)
        elif self._type == TFA_REST_API_SOURCE:
            self._handler = _TFARestAPI(cfg, log)
        else:
            self._handler = _TFAPush(cfg, log)
            self._factor_type = ""
    
        self._handler.start()
    
    def code(self) -> str | None:
        """Get the "otp" from the tfa source.
    
        This returns one of 3 things:
         - a 6 digit one-time-pin code
         - None; meaning the tfa failed
         - an empty string which indicates "finishAuth" does the waiting
        """
        return self._handler.get()
    
    @property
    def type(self) -> str | None:
        return self._type
    
    @property
    def factor_type(self) -> str:
        return self._factor_type
    
    def stop(self):
        self._handler.stop()
        self._handler = None
        self._type = None

