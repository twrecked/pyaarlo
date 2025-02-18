from __future__ import annotations

import logging


_LOGGER = logging.getLogger("pyaarlo")


class ArloLogger:
    """An all-in-one-place logger.

    And instance is created very early on and passed to all sub-components.
    """
    _last_error: str | None = None
    _verbose_debug: bool = False

    def __init__(self, verbose: bool = False):
        self._verbose_debug = verbose
        self.debug("logger created")
        self.vdebug("verbose debug enabled")

    def error(self, msg):
        self._last_error = msg
        _LOGGER.error(msg)

    @property
    def last_error(self) -> str | None:
        """Return the last reported error.
        """
        return self._last_error

    def warning(self, msg):
        _LOGGER.warning(msg)

    def info(self, msg):
        _LOGGER.info(msg)

    def debug(self, msg):
        _LOGGER.debug(msg)

    def vdebug(self, msg):
        if self._verbose_debug:
            _LOGGER.debug(msg)
