import logging


_LOGGER = logging.getLogger("pyaarlo")
_PACKET_LOGGER = logging.getLogger("pyaarlo.packet")

# Default packet logger to INFO so it does not inherit DEBUG from parent pyaarlo
if _PACKET_LOGGER.level == logging.NOTSET:
    _PACKET_LOGGER.setLevel(logging.INFO)


class ArloLogger:
    """An all-in-one-place logger.

    An instance is created very early on and passed to all sub-components.
    """

    def __init__(self, verbose: bool = False):
        self._last_error: str | None = None
        if verbose:
            _PACKET_LOGGER.setLevel(logging.DEBUG)

        self.debug("logger created")
        self.vdebug("verbose packet debug enabled")

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
        _PACKET_LOGGER.debug(msg)

