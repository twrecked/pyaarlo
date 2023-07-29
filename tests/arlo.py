import logging
from pyaarlo.cfg import ArloCfg


_LOGGER = logging.getLogger("pyaarlo")


class PyArlo(object):

    def __init__(self, **kwargs):
        """Constructor for the PyArlo object."""
        self._last_error = None
        self._cfg = ArloCfg(self, **kwargs)

    @property
    def cfg(self):
        return self._cfg

    def error(self, msg):
        self._last_error = msg
        _LOGGER.error(msg)

    @property
    def last_error(self):
        """Return the last reported error."""
        return self._last_error

    def warning(self, msg):
        _LOGGER.warning(msg)

    def info(self, msg):
        _LOGGER.info(msg)

    def debug(self, msg):
        _LOGGER.debug(msg)

    def vdebug(self, msg):
        if self._cfg.verbose:
            _LOGGER.debug(msg)
