from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .backend import ArloBackEnd
    from .task_manager import ArloTaskManager
    from .cfg import ArloCfg
    from .logger import ArloLogger
    from .storage import ArloStorage


class ArloCore:
    """These are the core functionality of Arlo.

    They provide access to:
     - ArloBackEnd; how we speak to Arlo
     - ArloTaskManager; how we queue tasks to run
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
        self.be: ArloBackEnd | None = None
        self.tasks: ArloTaskManager | None = None
        self.cfg: ArloCfg | None = None
        self.log: ArloLogger | None = None
        self.st: ArloStorage | None = None


