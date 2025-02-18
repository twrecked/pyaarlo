import fnmatch
import pickle
import pprint
import threading

from .logger import ArloLogger
from .cfg import ArloCfg


class ArloStorage:
    
    _cfg: ArloCfg
    _log: ArloLogger
    _state_file: str
    _lock: threading.Lock = threading.Lock()
    # XXX is _db dict[str, str]

    def __init__(self, cfg: ArloCfg, log: ArloLogger):
        self._cfg = cfg
        self._log = log
        self._state_file = self._cfg.state_file
        self._db = {}
        # self._lock = threading.Lock()
        self.load()
        self._log.debug("storage: created")

    def _ekey(self, key):
        return key if not isinstance(key, list) else "/".join(key)

    def _keys_matching(self, key):
        mkeys = []
        ekey = self._ekey(key)
        for mkey in self._db:
            if fnmatch.fnmatch(mkey, ekey):
                mkeys.append(mkey)
        return mkeys

    def load(self):
        if self._state_file is not None:
            try:
                with self._lock:
                    with open(self._state_file, "rb") as dump:
                        self._db = pickle.load(dump)
            except Exception:
                self._log.debug("storage: file not read")

    def save(self):
        if self._state_file is not None:
            try:
                with self._lock:
                    with open(self._state_file, "wb") as dump:
                        pickle.dump(self._db, dump)
            except Exception:
                self._log.warning("storage: file not written")

    def file_name(self):
        return self._state_file

    def get(self, key, default=None):
        with self._lock:
            ekey = self._ekey(key)
            return self._db.get(ekey, default)

    def get_matching(self, key, default=None):
        with self._lock:
            gets = []
            for mkey in self._keys_matching(key):
                gets.append((mkey, self._db.get(mkey, default)))
            return gets

    def keys_matching(self, key):
        with self._lock:
            return self._keys_matching(key)

    def set(self, key, value, prefix=""):
        ekey = self._ekey(key)
        output = "set:" + ekey + "=" + str(value)
        self._log.debug(f"{prefix}: {output[:80]}")
        with self._lock:
            self._db[ekey] = value
            return value

    def unset(self, key):
        with self._lock:
            del self._db[self._ekey(key)]

    def clear(self):
        with self._lock:
            self._db = {}

    def dump(self):
        with self._lock:
            pprint.pprint(self._db)
