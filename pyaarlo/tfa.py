import email
import imaplib
import re
import time

import requests


class Arlo2FAConsole:
    """2FA authentication via console.
    Accepts input from console and returns that for 2FA.
    """

    def __init__(self, arlo):
        self._arlo = arlo

    def start(self):
        self._arlo.debug("2fa-console: starting")
        return True

    def get(self):
        self._arlo.debug("2fa-console: checking")
        return input("Enter Code: ")

    def stop(self):
        self._arlo.debug("2fa-console: stopping")


class Arlo2FAImap:
    """2FA authentication via IMAP
    Connects to IMAP server and waits for email from Arlo with 2FA code in it.

    Note: will probably need tweaking for other IMAP setups...
    """

    def __init__(self, arlo):
        self._arlo = arlo
        self._imap = None
        self._old_ids = None
        self._MAIL_COUNT_TO_READ = 10
        self._continue_checking_mail_body = True

    def start(self):
        self._arlo.debug("2fa-imap: starting")

        # clean up
        if self._imap is not None:
            self.stop()

        try:
            self._imap = imaplib.IMAP4_SSL(
                self._arlo.cfg.tfa_host, port=self._arlo.cfg.tfa_port
            )
            res, status = self._imap.login(
                self._arlo.cfg.tfa_username, self._arlo.cfg.tfa_password
            )
            if res.lower() != "ok":
                self._arlo.debug("imap login failed")
                return False
            res, status = self._imap.select()
            if res.lower() != "ok":
                self._arlo.debug("imap select failed")
                return False
        except Exception as e:
            self._arlo.error(f"imap connection failed{str(e)}")
            return False

        if res.lower() == "ok":
            return True

        return False

    def get(self):
        self._arlo.debug("2fa-imap: checking")
        self._old_ids = None

        # Give tfa_total_timeout seconds for email to arrive
        start = time.time()
        while True:
            # Wait a short while, stop after a total timeout
            # Ok to do on first run, gives the email time to arrive
            time.sleep(self._arlo.cfg.tfa_timeout)
            if time.time() > (start + self._arlo.cfg.tfa_total_timeout):
                return None

            try:
                # Get all mail ids
                self._imap.check()
                res, all_mail_ids = self._imap.search(None, "ALL")

                # Only keep the last self._MAIL_COUNT_TO_READ
                recent_ids = all_mail_ids[0].split()
                recent_ids.reverse()
                del recent_ids[self._MAIL_COUNT_TO_READ:]
                self._arlo.debug("2fa-imap: recent_ids={}".format(recent_ids))

                # If we are looking at the same list of mails then wait for new ones
                if self._old_ids == recent_ids and not self._continue_checking_mail_body:
                    continue
                # After this iteration do not check the mails if they are from Arlo
                # No need to check because the mails are the same as last time we checked
                self._continue_checking_mail_body = False

                # Use list comprehension to find the last received Arlo mail and check if it contains a code
                # If we find the code in one of the mails then save it, otherwise save None
                mail_id = next((x for x in recent_ids if self.is_arlo_mail(x) and self.get_code(x) is not None), None)

                # If we found the code then return it and delete the mail
                # We should not use unnecessary space in the inbox
                if mail_id is not None:
                    code = self.get_code(mail_id)
                    self._arlo.debug("2fa-imap: code={}".format(code))
                    self.delete_mail(mail_id)
                    return code

                # Set the self._old_ids to the mail ids we just searched
                self._arlo.debug("2fa-imap: Setting old value")
                self._old_ids = recent_ids

            # Problem parsing the message, force a fail
            except Exception as e:
                self._arlo.error(f"imap message read failed{str(e)}")
                return None

        return None

    # Fetch the mail and look at the sender, if Arlo the return True, otherwise False
    def is_arlo_mail(self, mail_id):
        self._arlo.debug("2fa-imap: Checking if mail is Arlo mail, mail id: " + format(mail_id))
        res, msg = self._imap.fetch(mail_id, "(RFC822)")
        if isinstance(msg[0][1], bytes):
            message = email.message_from_bytes(msg[0][1])
            self._arlo.debug("2fa-imap: From: {}".format(message.get("From")))
            sender = message.get("From")
            if sender.find("Arlo") != -1:
                self._arlo.debug("2fa-imap: Arlo mail found")
                return True
        else:
            # If we did not read the mail successfully then try again
            self._continue_checking_mail_body = True
        return False

    # This is only called if we have found a mail we need to check for a valid code in
    # Fetch the mail and loop through each line in the body to look for a line with a valid code
    # Return the code if found, otherwise None
    def get_code(self, mail_id):
        res, msg = self._imap.fetch(mail_id, "(BODY[])")
        if isinstance(msg[0][1], bytes):
            for part in email.message_from_bytes(msg[0][1]).walk():
                if part.get_content_type() == "text/html":
                    for line in part.get_payload(decode=True).splitlines():
                        # Match code in email, this might need some work if the email changes
                        code = re.match(r"^\W*(\d{6})\W*$", line.decode())
                        if code is not None:
                            return code.group(1)
        return None

    # This is only called if we have extracted the code we need
    # Delete the mail with the code in
    def delete_mail(self, mail_id):
        self._imap.store(mail_id, '+FLAGS', '\\Deleted')
        self._arlo.debug("2fa-imap: Deleted mail with code")

    def stop(self):
        self._arlo.debug("2fa-imap: stopping")
        if self._imap is not None:
            self._imap.close()
            self._imap.logout()
            self._imap = None
        self._old_ids = None


class Arlo2FARestAPI:
    """2FA authentication via rest API.
    Queries web site until code appears
    """

    def __init__(self, arlo):
        self._arlo = arlo

    def start(self):
        self._arlo.debug("2fa-rest-api: starting")
        if self._arlo.cfg.tfa_host is None or self._arlo.cfg.tfa_password is None:
            self._arlo.debug("2fa-rest-api: invalid config")
            return False

        self._arlo.debug("2fa-rest-api: clearing")
        response = requests.get(
            "{}/clear?email={}&token={}".format(
                self._arlo.cfg.tfa_host,
                self._arlo.cfg.tfa_username,
                self._arlo.cfg.tfa_password,
            ),
            timeout=10,
        )
        if response.status_code != 200:
            self._arlo.debug("2fa-rest-api: possible problem clearing")

        return True

    def get(self):
        self._arlo.debug("2fa-rest-api: checking")

        # give tfa_total_timeout seconds for email to arrive
        start = time.time()
        while True:

            # wait a short while, stop after a total timeout
            # ok to do on first run gives email time to arrive
            time.sleep(self._arlo.cfg.tfa_timeout)
            if time.time() > (start + self._arlo.cfg.tfa_total_timeout):
                return None

            # Try for the token.
            self._arlo.debug("2fa-rest-api: checking")
            response = requests.get(
                "{}/get?email={}&token={}".format(
                    self._arlo.cfg.tfa_host,
                    self._arlo.cfg.tfa_username,
                    self._arlo.cfg.tfa_password,
                ),
                timeout=10,
            )
            if response.status_code == 200:
                code = response.json().get("data", {}).get("code", None)
                if code is not None:
                    self._arlo.debug("2fa-rest-api: code={}".format(code))
                    return code

            self._arlo.debug("2fa-rest-api: retrying")

    def stop(self):
        self._arlo.debug("2fa-rest-api: stopping")
