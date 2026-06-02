import logging


_LOGGER = logging.getLogger("pyaarlo")


class ArloLogger:
    """An all-in-one-place logger.

    And instance is created very early on and passed to all sub-components.
    """

    def __init__(self, verbose: bool = False):
        self._verbose_debug: bool = verbose
        self._last_error: str | None = None

        self.debug("logger created")
        self.vdebug("verbose debug enabled")

    def error(self, msg: str) -> None:
        self._last_error = msg
        _LOGGER.error(msg)

    @property
    def last_error(self) -> str | None:
        """Return the last reported error.
        """
        return self._last_error

    def warning(self, msg: str) -> None:
        _LOGGER.warning(msg)

    def info(self, msg: str) -> None:
        _LOGGER.info(msg)

    def debug(self, msg: str) -> None:
        _LOGGER.debug(msg)

    def vdebug(self, msg: str) -> None:
        if self._verbose_debug:
            _LOGGER.debug(msg)

