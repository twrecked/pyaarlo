from .constant import (
    AUTOMATION_EXCEPTION_SENSORS,
    MODE_ID_TO_NAME_KEY,
    MODE_KEY,
    MODE_NAME_TO_ID_KEY,
    LOCATION_MODES_PATH_FORMAT,
    LOCATION_AUTOMATION_PATH_FORMAT,
    LOCATION_ACTIVEMODE_PATH_FORMAT,
    MODE_REVISION_KEY,
    TIMEZONE_KEY,
)
from .core import ArloCore
from .object import ArloObject
from .objects import ArloObjects


AUTOMATION_ACTIVE_MODE = "automation/activeMode"
AUTOMATION_MODES = "automation/modes"
DEFAULT_MODES = {
    "standby": "Stand By",
    "armAway": "Armed Away",
    "armHome": "Armed Home"
}

# Key used to store the device_id -> custom_modes UUID map
CUSTOM_MODE_UUID_KEY = "customModeUuid"
# Sentinel stored as mode_id when the active mode is a V3 custom mode
CUSTOM_MODE_SENTINEL = "custom"


def location_name(name, user):
    if user:
        return f"user_location_{name}"
    return f"location_{name}"


class ArloLocation(ArloObject):
    """ Represents a Location object.

    Each Arlo account can have multiple owned locations and multiple shared locations.
    """
    def __init__(self, core: ArloCore, objs: ArloObjects, attrs, user=False):
        super().__init__(location_name(attrs.get("locationName", "unknown"), user),
                         core, objs, 
                         attrs=attrs,
                         id=attrs.get("locationId", "unknown"),
                         type="location")

        self._device_ids = attrs.get("gatewayDeviceIds", [])

    def _id_to_name(self, mode_id):
        return self._load([MODE_ID_TO_NAME_KEY, mode_id], None)

    def _name_to_id(self, mode_name):
        # Try exact match first
        result = self._load([MODE_NAME_TO_ID_KEY, mode_name], None)
        if result is not None:
            return result
        # Try case-insensitive match
        for key, value in self._load_matching([MODE_NAME_TO_ID_KEY, "*"]):
            if key.split("/")[-1].lower() == mode_name.lower():
                return value
        return None

    def _custom_uuid_for_device(self, device_id, mode_name_or_uuid):
        """Resolve a custom mode name or UUID to a UUID for a given device_id.

        Returns the UUID string, or None if not found.
        """
        # Try name -> uuid lookup first
        uuid = self._load([CUSTOM_MODE_UUID_KEY, device_id, mode_name_or_uuid], None)
        if uuid is not None:
            return uuid
        # Already a UUID? Check it exists in the map
        for key, stored_uuid in self._load_matching([CUSTOM_MODE_UUID_KEY, device_id, "*"]):
            if stored_uuid == mode_name_or_uuid:
                return mode_name_or_uuid
        return None

    def _uuid_to_custom_name(self, device_id, uuid):
        """Resolve a UUID to the custom mode name for a given device_id."""
        for key, stored_uuid in self._load_matching([CUSTOM_MODE_UUID_KEY, device_id, "*"]):
            if stored_uuid == uuid:
                return key.split("/")[-1]
        return uuid

    def _parse_custom_modes(self, custom_modes_properties):
        """Parse the customModes.properties.<deviceId> structure and store name->UUID map."""
        for device_id, modes in custom_modes_properties.items():
            if not isinstance(modes, dict):
                continue
            for uuid, mode_data in modes.items():
                if not isinstance(mode_data, dict):
                    continue
                name = mode_data.get("name", "")
                # For modes with empty or sentinel names (e.g. migrated V2 modes like
                # "armed", "disarmed", "schedule"), use the key itself as the name.
                if name in ("", "__DEFAULT_DISARMED__"):
                    name = uuid
                if not name:
                    continue
                self.debug(f"custom mode: {device_id} {uuid}<=CM=>{name}")
                self._save([CUSTOM_MODE_UUID_KEY, device_id, name], uuid)

    def _resolve_active_mode(self, properties):
        """Resolve the active mode from a V3 activeMode response properties dict.

        Returns a human-readable mode name or a plain mode_id string.
        """
        mode = properties.get("mode", None)
        if mode != CUSTOM_MODE_SENTINEL:
            # Standard mode: standby, armHome, armAway - return as-is
            return mode
        # Custom mode: resolve UUID -> name for each device
        custom = properties.get("custom", {})
        names = []
        for device_id, uuid in custom.items():
            name = self._uuid_to_custom_name(device_id, uuid)
            names.append(name)
        # Return the first resolved name (single base station setup)
        return names[0] if names else CUSTOM_MODE_SENTINEL


    def _extra_headers(self):
        return {
            "x-forwarded-user": self._core.be.user_id,
            "x-user-device-id": self._core.be.user_id,
        }

    def _parse_modes(self, modes):
        for mode in modes.items():
            mode_id = mode[0]
            mode_name = mode[1].get("name", "")
            if mode_id and mode_name != "":
                self.debug(mode_id + "<=M=>" + mode_name)
                self._save([MODE_ID_TO_NAME_KEY, mode_id], mode_name)
                self._save([MODE_NAME_TO_ID_KEY, mode_name], mode_id)

    def _event_handler(self, resource, event):
        self.debug(self.name + " LOCATION got " + resource)

        # A (user requested?) mode change.
        if resource == AUTOMATION_ACTIVE_MODE:
            props = event.get("properties", {})
            raw_props = props.get("properties", {})
            mode = self._resolve_active_mode(raw_props)
            if mode is not None:
                self._save_and_do_callbacks(MODE_KEY, mode)
                self._propagate_mode_to_bases(mode)
            mode_revision = props.get("revision", None)
            if mode_revision is not None:
                self._save(MODE_REVISION_KEY, mode_revision)

        # A mode list update
        if resource == AUTOMATION_MODES:
            self._parse_modes(event.get("properties", {}).get("properties", {}))

        # A (user requested?) mode change.
        if resource == "states":
            mode = event.get("states", {}).get("activeMode", None)
            if mode is not None:
                self._save_and_do_callbacks(MODE_KEY, mode)
                self._propagate_mode_to_bases(mode)

        # Handle Keypad Sensor Hub (SH1001) sensor open/close events
        if resource == AUTOMATION_EXCEPTION_SENSORS:
            self._parse_exception_sensors(event)

    def _parse_exception_sensors(self, event):
        if not self._objs:
            return

        source_hub = event.get("properties", {}).get("source")
        for sensor in self._objs.sensors:
            if source_hub and sensor.parent_id and sensor.parent_id != source_hub:
                continue
            if not source_hub and self._device_ids and sensor.parent_id not in self._device_ids:
                continue

            sensor.handle_exception_sensors(event)

    @property
    def available_modes(self):
        """Returns string list of available modes.

        For example:: ``['disarmed', 'armed', 'home']``
        """
        return list(self.available_modes_with_ids.keys())

    @property
    def available_modes_with_ids(self):
        """Returns dictionary of available modes mapped to Arlo ids.

        For example:: ``{'armed': 'mode1','disarmed': 'mode0','home': 'mode2'}``
        """
        modes = {}
        for key, mode_id in self._load_matching([MODE_NAME_TO_ID_KEY, "*"]):
            modes[key.split("/")[-1]] = mode_id
        if not modes:
            modes = DEFAULT_MODES
        return modes

    @property
    def device_ids(self):
        return self._device_ids

    @property
    def timezone(self) -> str | None:
        """Return the last time zone reported by the V3 automation API."""
        zone = self._load(TIMEZONE_KEY)
        if isinstance(zone, str):
            return zone.strip() or None
        return None

    @property
    def mode(self) -> str:
        """Returns the current mode."""
        return self._load(MODE_KEY, "unknown")

    @mode.setter
    def mode(self, id_or_name: str) -> None:
        """Set the location mode (sync wrapper).
        """
        self._core.tasks.run_now(self.set_mode, id_or_name=id_or_name)

    def _propagate_mode_to_bases(self, mode_id: str | None, device_id: str | None = None) -> None:
        """Update MODE_KEY on the base stations associated with this location.

        :param device_id: only update this base (a per-base custom mode change)
        """
        if not mode_id:
            return
        for base in self._objs.base_stations:
            if device_id is not None and base.device_id != device_id:
                continue
            for gid in self._device_ids:
                if gid == base.device_id or gid.endswith("_" + base.device_id):
                    base._save_and_do_callbacks(MODE_KEY, mode_id)
                    break

    async def set_mode(self, id_or_name, force: bool = False, device_id: str | None = None):
        """Set the location mode.

        :param id_or_name: mode to use, as returned by available_modes:
        :param force: if True, send mode change even if location.mode already matches
        :param device_id: the base station asking for its own custom mode; the
            mode is then resolved for that base only
        """
        # Convert to an ID.
        mode_id = self._name_to_id(id_or_name)
        if mode_id is None:
            mode_id = id_or_name
        if mode_id is None:
            self._core.log.error(f"passed invalid id or name {id_or_name}")
            return

        # Need to change?
        if not force and self.mode.lower() == mode_id.lower():
            self.debug("no mode change needed")
            return

        self.debug(f"new-mode={mode_id}({id_or_name})")
        mode_revision = self._load(MODE_REVISION_KEY, 1)
        self.vdebug(f"old-revision={mode_revision}")

        # Build the PUT body - standard modes vs V3 custom modes
        custom_uuid = None
        base_id = device_id
        if base_id is not None:
            # A base asked for its own mode. Resolve it for that base only: in a
            # location with several bases, other bases have custom modes with the
            # same names ("disarmed", "Home"), and picking theirs changes the
            # wrong base.
            base_modes = list(self._load_matching([CUSTOM_MODE_UUID_KEY, base_id, "*"]))
            uuid = self._custom_uuid_for_device(base_id, mode_id)
            if uuid is None:
                for key, stored_uuid in base_modes:
                    if key.split("/")[-1].lower() == mode_id.lower():
                        uuid = stored_uuid
                        break
            if uuid is not None:
                custom_uuid = (base_id, uuid)
            elif base_modes:
                self._core.log.error(f"base {base_id} has no custom mode {id_or_name}, not changing mode")
                return
        # First try with _device_ids (exact match)
        for device_id in ([] if base_id is not None else self._device_ids):
            uuid = self._custom_uuid_for_device(device_id, mode_id)
            if uuid is not None:
                custom_uuid = (device_id, uuid)
                break
        # If not found, search all device_ids in the custom mode cache (case-insensitive)
        if custom_uuid is None and base_id is None:
            for key, uuid in self._load_matching([CUSTOM_MODE_UUID_KEY, "*", "*"]):
                # key format: customModeUuid/<device_id>/<mode_name>
                parts = key.split("/")
                if len(parts) >= 2 and parts[-1].lower() == mode_id.lower():
                    device_id = parts[-2]
                    # strip userId prefix if present (e.g. "userId_deviceId" -> "deviceId")
                    if "_" in device_id:
                        device_id = device_id.split("_", 1)[-1]
                    custom_uuid = (device_id, uuid)
                    break

        if custom_uuid is not None:
            device_id, uuid = custom_uuid
            params = {
                "mode": CUSTOM_MODE_SENTINEL,
                "custom": {device_id: uuid}
            }
        else:
            params = {"mode": mode_id}

        data = await self._core.be.put(
            LOCATION_ACTIVEMODE_PATH_FORMAT.format(self._id) + f"&revision={mode_revision}",
            params=params,
            headers=self._extra_headers())

        if data is None:
            self._core.log.error("failed to set mode.")
            return

        mode_revision = data.get("revision")
        self.vdebug(f"new-revision={mode_revision}")

        self._save_and_do_callbacks(MODE_KEY, mode_id)
        self._save(MODE_REVISION_KEY, mode_revision)
        self._propagate_mode_to_bases(mode_id, base_id if custom_uuid and base_id else None)

    async def update_mode(self):
        """Check and update the base's current mode."""
        data = await self._core.be.get(LOCATION_ACTIVEMODE_PATH_FORMAT.format(self._id),
                                      headers=self._extra_headers())
        if data is None:
            self._core.log.error("failed to read active mode.")
            return
        mode_id = self._resolve_active_mode(data.get("properties", {}))
        mode_revision = data.get("revision")
        self._save_and_do_callbacks(MODE_KEY, mode_id)
        self._save(MODE_REVISION_KEY, mode_revision)
        self._propagate_mode_to_bases(mode_id)

    async def update_modes(self, _initial=False):
        """Get and update the available modes for the base."""
        data = await self._core.be.get(LOCATION_AUTOMATION_PATH_FORMAT.format(self._id),
                                       headers=self._extra_headers())
        if data is None:
            self._core.log.error("failed to read modes.")
            return

        info = data.get("info")
        properties = info.get("properties") if isinstance(info, dict) else None
        zone = properties.get(TIMEZONE_KEY) if isinstance(properties, dict) else None
        if isinstance(zone, str) and zone.strip():
            self._save(TIMEZONE_KEY, zone.strip())

        # Parse standard modes (standby, armHome, armAway)
        modes = data.get("modes", {}).get("properties", {})
        if modes:
            self._parse_modes(modes)

        # Parse custom modes (V3: customModes.properties.<deviceId>.<uuid> = {name:...})
        custom_modes = data.get("customModes", {}).get("properties", {})
        if custom_modes:
            self._parse_custom_modes(custom_modes)

    async def stand_by(self):
        await self.set_mode("standby")

    @property
    def is_stand_by(self):
        return self.mode == "standby"

    async def arm_home(self):
        await self.set_mode("armHome")

    @property
    def is_armed_home(self):
        return self.mode == "armHome"

    async def arm_away(self):
        await self.set_mode("armAway")

    @property
    def is_armed_away(self):
        return self.mode == "armAway"

