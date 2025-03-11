from __future__ import annotations

from typing import Union, TYPE_CHECKING

if TYPE_CHECKING:
    from .backend import ArloBackEnd
    from .background import ArloBackground
    from .cfg import ArloCfg
    from .logger import ArloLogger
    from .storage import ArloStorage


class ArloCore:
    """These are the core functionality of Arlo.

    They provide access to:
     - ArloBackEnd; how we speak to Arlo
     - ArloBackground; how we queue jobs to run
     - ArloCfg; how we get configuration
     - ArloLogger; how we get logs
     - ArloStorage; how we get storage

    They use to be provided by `PyArlo` but it got complicated with
    dependencies. Most Arlo objects, cameras etc, will take `Core` rather
    than individual components.

    These components shouldn't know anything about the Arlo objects, they are
    conciously-uncoupling from them.
    """

    def __init__(self):
        self.be: Union[ArloBackEnd, None] = None
        self.bg: Union[ArloBackground, None] = None
        self.cfg: Union[ArloCfg, None] = None
        self.log: Union[ArloLogger, None] = None
        self.st: Union[ArloStorage, None] = None
