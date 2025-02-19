from __future__ import annotations


# noinspection PyUnresolvedReferences
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

    be: ArloBackEnd | None = None
    bg: ArloBackground | None = None
    cfg: ArloCfg | None = None
    log: ArloLogger | None = None
    st: ArloStorage | None = None
