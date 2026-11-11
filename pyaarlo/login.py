"""Interactive, resumable Arlo login.

For callers - typically a setup UI - that want to list an account's 2FA
factors and let the user pick one, rather than committing to a `tfa_source`
and `tfa_type` up front the way `PyArlo` does.
"""

from __future__ import annotations

from typing import Any

from .core.backend import ArloBackEnd, LoginStep
from .core.cfg import ArloCfg
from .core.logger import ArloLogger
from .core.task_manager import ArloTaskManager


class ArloLogin:
    """A standalone, step by step Arlo login.

    Unlike `PyArlo` this does not read devices or start the event stream, it
    only gets as far as a logged in session:

    ```python
    login = ArloLogin(username=USER, password=PASS, storage_dir=DIR)
    step = await login.start()
    if step == LoginStep.NEEDS_FACTOR:
        factor_id = ...  # let the user pick one of login.factors
        step = await login.choose_factor(factor_id)
    while step == LoginStep.AWAITING_PUSH:
        await asyncio.sleep(login.push_poll)
        step = await login.poll_push()
    if step == LoginStep.AWAITING_CODE:
        step = await login.submit_code(code)
    await login.close()
    ```

    A `SUCCESS` step means the session and cookies are saved in
    `storage_dir`. A later `PyArlo` with the same `username`, `storage_dir`
    and `user_agent` picks them up and, because the browser is now trusted,
    doesn't need the 2FA again.
    """

    def __init__(self, **kwargs: Any):
        self._log = ArloLogger(kwargs.get("verbose_debug", False))
        self._cfg = ArloCfg(self._log, **kwargs)
        self._tasks = ArloTaskManager(self._log)
        self._be = ArloBackEnd(self._cfg, self._log, self._tasks)

    @property
    def factors(self) -> list[dict[str, Any]]:
        """The 2FA factors offered after `start()` returns `NEEDS_FACTOR`.

        Each entry carries at least `factorId`, `factorType` - `EMAIL`, `SMS`
        or `PUSH` - `factorRole` and `factorNickname`. Pass the `factorId` of
        the one used here as the `tfa_factor_id` option to keep using it.
        """
        return self._be.login_factors

    @property
    def push_poll(self) -> float:
        """How long to wait, in seconds, between `poll_push()` calls."""
        return self._cfg.tfa_push_poll

    @property
    def last_error(self) -> str | None:
        """The last reported error, if any."""
        return self._log.last_error

    async def start(self) -> LoginStep:
        """Sign in with the password and see whether 2FA is needed."""
        return await self._be.login_start()

    async def choose_factor(self, factor_id: str) -> LoginStep:
        """Start 2FA with one of the factors from `factors`."""
        return await self._be.login_choose_factor(factor_id)

    async def poll_push(self) -> LoginStep:
        """One check of a push login started with `choose_factor()`."""
        return await self._be.login_poll_push()

    async def submit_code(self, code: str) -> LoginStep:
        """Finish an EMAIL or SMS login with the code the user typed in."""
        return await self._be.login_submit_code(code)

    async def close(self) -> None:
        """Drop the HTTP connections. The saved session stays valid.

        Doesn't log out, that would throw away the token we just saved.
        """
        await self._be.login_close()
