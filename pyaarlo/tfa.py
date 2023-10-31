import email
import imaplib
import re
import time
import ssl

import requests


class Arlo2FAConsole:
    """2FA authentication via console.
    Accepts input from console and returns that for 2FA.
    """

    def __init__(self, arlo):
        self._arlo = arlo

    def start(self):
        self.debug("starting")
        return True

    def get(self):
        self.debug("checking")
        return input("Enter Code: ")

    def stop(self):
        self.debug("stopping")

    def debug(self, msg):
        self._arlo.debug(f"2fa-console: {msg}")


class Arlo2FAImap:
    """2FA authentication via IMAP
    Connects to IMAP server and waits for email from Arlo with 2FA code in it.

    Note: will probably need tweaking for other IMAP setups...
    """

    def __init__(self, arlo):
        self._arlo = arlo
        self._imap = None
        self._old_ids = None
        self._new_ids = None

    def start(self):
        self.debug("starting")

        # clean up
        if self._imap is not None:
            self.stop()

        try:
            # allow default ciphers to be specified
            cipher_list = self._arlo.cfg.cipher_list
            if cipher_list != "":
                ctx = ssl.create_default_context()
                ctx.set_ciphers(cipher_list)
                self.debug(f"imap is using custom ciphers {cipher_list}")
            else:
                ctx = None

            self._imap = imaplib.IMAP4_SSL(self._arlo.cfg.tfa_host, port=self._arlo.cfg.tfa_port, ssl_context=ctx)
            res, status = self._imap.login(
                self._arlo.cfg.tfa_username, self._arlo.cfg.tfa_password
            )
            if res.lower() != "ok":
                self.debug("imap login failed")
                return False
            res, status = self._imap.select(mailbox='INBOX', readonly=True)
            if res.lower() != "ok":
                self.debug("imap select failed")
                return False
            res, self._old_ids = self._imap.search(
                None, "FROM", "do_not_reply@arlo.com"
            )
            if res.lower() != "ok":
                self.debug("imap search failed")
                return False
        except Exception as e:
            self._arlo.error(f"imap connection failed{str(e)}")
            return False

        self._new_ids = self._old_ids
        self.debug("old-ids={}".format(self._old_ids))
        if res.lower() == "ok":
            return True

        return False

    def get(self):
        self.debug("checking")

        # give tfa_total_timeout seconds for email to arrive
        start = time.time()
        while True:

            # wait a short while, stop after a total timeout
            # ok to do on first run gives email time to arrive
            time.sleep(self._arlo.cfg.tfa_timeout)
            if time.time() > (start + self._arlo.cfg.tfa_total_timeout):
                return None

            try:
                # grab new email ids
                self._imap.check()
                res, self._new_ids = self._imap.search(
                    None, "FROM", "do_not_reply@arlo.com"
                )
                self.debug("new-ids={}".format(self._new_ids))
                if self._new_ids == self._old_ids:
                    self.debug("no change in emails")
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
                    self.debug("new-msg={}".format(msg_id))
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
                                            self.debug(f"code={code.group(1)}")
                                            return code.group(1)
                        except Exception as e:
                            self.debug(f"trying next part {str(e)}")

                # Update old so we don't keep trying new.
                # Yahoo can lose ids so we extend the old list.
                self._old_ids.extend(new_id for new_id in self._new_ids if new_id not in self._old_ids)

            # problem parsing the message, force a fail
            except Exception as e:
                self._arlo.error(f"imap message read failed{str(e)}")
                return None

        return None

    def stop(self):
        self.debug("stopping")

        self._imap.close()
        self._imap.logout()
        self._imap = None
        self._old_ids = None
        self._new_ids = None

    def debug(self, msg):
        self._arlo.debug(f"2fa-imap: {msg}")


class Arlo2FARestAPI:
    """2FA authentication via rest API.
    Queries web site until code appears
    """

    def __init__(self, arlo):
        self._arlo = arlo

    def start(self):
        self.debug("starting")
        if self._arlo.cfg.tfa_host is None or self._arlo.cfg.tfa_password is None:
            self.debug("invalid config")
            return False

        self.debug("clearing")
        response = requests.get(
            "{}/clear?email={}&token={}".format(
                self._arlo.cfg.tfa_host_with_scheme("https"),
                self._arlo.cfg.tfa_username,
                self._arlo.cfg.tfa_password,
            ),
            timeout=10,
        )
        if response.status_code != 200:
            self.debug("possible problem clearing")

        return True

    def get(self):
        self.debug("checking")

        # give tfa_total_timeout seconds for email to arrive
        start = time.time()
        while True:

            # wait a short while, stop after a total timeout
            # ok to do on first run gives email time to arrive
            time.sleep(self._arlo.cfg.tfa_timeout)
            if time.time() > (start + self._arlo.cfg.tfa_total_timeout):
                return None

            # Try for the token.
            self.debug("checking")
            response = requests.get(
                "{}/get?email={}&token={}".format(
                    self._arlo.cfg.tfa_host_with_scheme("https"),
                    self._arlo.cfg.tfa_username,
                    self._arlo.cfg.tfa_password,
                ),
                timeout=10,
            )
            if response.status_code == 200:
                code = response.json().get("data", {}).get("code", None)
                if code is not None:
                    self.debug("code={}".format(code))
                    return code

            self.debug("retrying")

    def stop(self):
        self.debug("stopping")

    def debug(self, msg):
        self._arlo.debug(f"2fa-rest-api: {msg}")
