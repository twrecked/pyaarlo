from .constant import (
    MODE_ID_TO_NAME_KEY,
    MODE_KEY,
    MODE_NAME_TO_ID_KEY,
    LOCATION_MODES_PATH_FORMAT,
    LOCATION_AUTOMATION_PATH_FORMAT,
    LOCATION_ACTIVEMODE_PATH_FORMAT,
    MODE_REVISION_KEY
)
from .super import ArloSuper


AUTOMATION_ACTIVE_MODE = "automation/activeMode"
AUTOMATION_MODES = "automation/modes"
DEFAULT_MODES = {
    "standby": "Stand By",
    "armAway": "Armed Away",
    "armHome": "Armed Home"
}

# Key used to store the device_id → custom_modes UUID map
CUSTOM_MODE_UUID_KEY = "customModeUuid"
# Sentinel stored as mode_id when the active mode is a V3 custom mode
CUSTOM_MODE_SENTINEL = "custom"


def location_name(name, user):
    if user:
        return f"user_location_{name}"
    return f"location_{name}"


class ArloLocation(ArloSuper):
    """ Represents a Location object.

    Each Arlo account can have multiple owned locations and multiple shared locations.
    """
    def __init__(self, arlo, attrs, user=False):
        super().__init__(location_name(attrs.get("locationName", "unknown"), user),
                         arlo, attrs,
                         id=attrs.get("locationId", "unknown"),
                         type="location")

        self._device_ids = attrs.get("gatewayDeviceIds", [])

    def _id_to_name(self, mode_id):
        return self._load([MODE_ID_TO_NAME_KEY, mode_id], None)

    def _name_to_id(self, mode_name):
        return self._load([MODE_NAME_TO_ID_KEY, mode_name], None)

    def _custom_uuid_for_device(self, device_id, mode_name_or_uuid):
        """Resolve a custom mode name or UUID to a UUID for a given device_id.

        Returns the UUID string, or None if not found.
        """
        # Try name → uuid lookup first
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
        """Parse the customModes.properties.<deviceId> structure and store name→UUID map."""
        for device_id, modes in custom_modes_properties.items():
            if not isinstance(modes, dict):
                continue
            for uuid, mode_data in modes.items():
                if not isinstance(mode_data, dict):
                    continue
                name = mode_data.get("name", "")
                # Skip internal sentinels
                if name in ("", "__DEFAULT_DISARMED__"):
                    continue
                self.debug(f"custom mode: {device_id} {uuid}<=CM=>{name}")
                self._save([CUSTOM_MODE_UUID_KEY, device_id, name], uuid)

    def _resolve_active_mode(self, properties):
        """Resolve the active mode from a V3 activeMode response properties dict.

        Returns a human-readable mode name or a plain mode_id string.
        """
        mode = properties.get("mode", None)
        if mode != CUSTOM_MODE_SENTINEL:
            # Standard mode: standby, armHome, armAway — return as-is
            return mode
        # Custom mode: resolve UUID → name for each device
        custom = properties.get("custom", {})
        names = []
        for device_id, uuid in custom.items():
            name = self._uuid_to_custom_name(device_id, uuid)
            names.append(name)
        # Return the first resolved name (single base station setup)
        return names[0] if names else CUSTOM_MODE_SENTINEL

    def _extra_headers(self):
        return {
            "x-forwarded-user": self._arlo.be.user_id,
            "x-user-device-id": self._arlo.be.user_id,
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
    def mode(self):
        """Returns the current mode."""
        return self._load(MODE_KEY, "unknown")

    @mode.setter
    def mode(self, id_or_name):
        """Set the location mode.

        :param id_or_name: mode to use, as returned by available_modes:
        """
        # Convert to an ID.
        mode_id = self._name_to_id(id_or_name)
        if mode_id is None:
            mode_id = id_or_name
        if mode_id is None:
            self._arlo.error("passed invalid id or name {id_or_name}")
            return

        # Need to change?
        if self.mode == mode_id:
            self.debug("no mode change needed")
            return

        self.debug(f"new-mode={mode_id}({id_or_name})")
        mode_revision = self._load(MODE_REVISION_KEY, 1)
        self.vdebug(f"old-revision={mode_revision}")

        # Build the PUT body — standard modes vs V3 custom modes
        custom_uuid = None
        # First try with _device_ids
        for device_id in self._device_ids:
            uuid = self._custom_uuid_for_device(device_id, mode_id)
            if uuid is not None:
                custom_uuid = (device_id, uuid)
                break
        # If not found, search all device_ids in the custom mode cache
        if custom_uuid is None:
            for key, uuid in self._load_matching([CUSTOM_MODE_UUID_KEY, "*", mode_id]):
                # key format: customModeUuid/<device_id>/<mode_name>
                parts = key.split("/")
                if len(parts) >= 2:
                    device_id = parts[-2]
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

        data = self._arlo.be.put(
            LOCATION_ACTIVEMODE_PATH_FORMAT.format(self._id) + f"&revision={mode_revision}",
            params=params,
            headers=self._extra_headers())

        if data is None:
            self._arlo.error("failed to set mode.")
            return

        mode_revision = data.get("revision")
        self.vdebug(f"new-revision={mode_revision}")

        self._save_and_do_callbacks(MODE_KEY, mode_id)
        self._save(MODE_REVISION_KEY, mode_revision)

    @property
    def mode_name(self):
        """Returns the current mode using the Arlo friendly name."""
        return self._id_to_name(self._load(MODE_KEY, "standby"))

    def update_mode(self):
        """Check and update the base's current mode."""
        data = self._arlo.be.get(LOCATION_ACTIVEMODE_PATH_FORMAT.format(self._id),
                                 headers=self._extra_headers())
        if data is None:
            self._arlo.error("failed to read active mode.")
            return
        mode_id = self._resolve_active_mode(data.get("properties", {}))
        mode_revision = data.get("revision")
        self._save_and_do_callbacks(MODE_KEY, mode_id)
        self._save(MODE_REVISION_KEY, mode_revision)

    def update_modes(self, _initial=False):
        """Get and update the available modes for the base."""
        data = self._arlo.be.get(LOCATION_AUTOMATION_PATH_FORMAT.format(self._id),
                                 headers=self._extra_headers())
        if data is None:
            self._arlo.error("failed to read modes.")
            return

        # Parse standard modes (standby, armHome, armAway)
        modes = data.get("modes", {}).get("properties", {})
        if modes:
            self._parse_modes(modes)

        # Parse custom modes (V3: customModes.properties.<deviceId>.<uuid> = {name:...})
        custom_modes = data.get("customModes", {}).get("properties", {})
        if custom_modes:
            self._parse_custom_modes(custom_modes)

    def stand_by(self):
        self.mode = "standby"

    @property
    def is_stand_by(self):
        return self.mode == "standby"

    def arm_home(self):
        self.mode = "armHome"

    @property
    def is_armed_home(self):
        return self.mode == "armHome"

    def arm_away(self):
        self.mode = "armAway"

    @property
    def is_armed_away(self):
        return self.mode == "armAway"
