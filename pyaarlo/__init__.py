import base64
import datetime
import os
import pprint
import threading
import time

from .constant import (
    BLANK_IMAGE,
    DEVICES_PATH,
    FAST_REFRESH_INTERVAL,
    PING_CAPABILITY,
    SLOW_REFRESH_INTERVAL,
    TOTAL_BELLS_KEY,
    TOTAL_CAMERAS_KEY,
    TOTAL_LIGHTS_KEY,
    LOCATIONS_PATH_FORMAT,
    LOCATIONS_EMERGENCY_PATH,
    VALID_DEVICE_STATES,
)
from .base_station import ArloBaseStation
from .camera import ArloCamera
from .core import ArloCore
from .core.backend import ArloBackEnd
from .core.background import ArloBackground
from .core.cfg import ArloCfg
from .core.logger import ArloLogger
from .core.storage import ArloStorage
from .doorbell import ArloDoorBell
from .light import ArloLight
from .location import ArloLocation
from .media import ArloMediaLibrary
from .objects import ArloObjects
from .sensor import ArloSensor
from .types import ArloTypes
from .utils import time_to_arlotime


__version__ = "0.8.0.18"


class PyArlo:
    """Entry point for all Arlo operations.

    This is used to login to Arlo, open and maintain an evenstream with Arlo, find and store devices and device
    state, provide keep-alive services and make sure media sources are kept up to date.

    Every device discovered and created is done in here, every device discovered and created uses this instance
    to log errors, info and debug, to access the state database and configuration settings.

    **Required `kwargs` parameters:**

    * **username** - Your Arlo username.
    * **password** - Your Arlo password.

    **Optional `kwargs` parameters:**

    * **wait_for_initial_setup** - Wait for initial devices states to load before returning from constructor.
      Default `True`. Setting to `False` and using saved state can increase startup time.
    * **last_format** - Date string format used when showing video file dates. Default ``%m-%d %H:%M``.
    * **library_days** - Number of days of recordings to load. Default is `30`. If you have a lot of recordings
      you can lower this value.
    * **save_state** - Store device state across restarts. Default `True`.
    * **state_file** - Where to store state. Default is `${storage_dir}/${name.}pickle`
    * **refresh_devices_every** - Time, in hours, to refresh the device list from Arlo. This can help keep the login
      from timing out.
    * **stream_timeout** - Time, in seconds, for the event stream to close after receiving no packets. 0 means
      no timeout. Default 0 seconds. Setting this to `120` can be useful for catching dead connections - ie, an
      ISP forced a new IP on you.
    * **synchronous_mode** - Wait for operations to complete before returing. If you are coming from Pyarlo this
      will make Pyaarlo behave more like you expect.
    * **save_media_to** - Save media to a local directory.

    **Debug `kwargs` parameters:**

    * **dump** - Save event stream packets to a file.
    * **dump_file** - Where to packets. Default is `${storage_dir}/packets.dump`
    * **name** - Name used for state and dump files.
    * **verbose_debug** - If `True`, provide extra debug in the logs. This includes packets in and out.

    **2FA authentication `kwargs` parameters:**

    These parameters are needed for 2FA.

    * **tfa_source** - Where to get the token from. Default is `console`. Can be `imap` to use email or
      `rest-api` to use rest API website.
    * **tfa_type** - How to get the 2FA token delivered. Default is `email` but can be `sms`.
    * **tfa_timeout** - When using `imap` or `rest-api`, how long to wait, in seconds, between checks.
    * **tfa_total_timeout** - When using `imap` or `rest-api`, how long to wait, in seconds, for all checks.
    * **tfa_host** - When using `imap` or `rest-api`, host name of server.
    * **tfa_username** - When using `imap` or `rest-api`, user name on server. If `None` will use
      Arlo username.
    * **tfa_password** - When using `imap` or `rest-api`, password/token on server. If `None`
      will use Arlo password.
    * **cipher_list** - Set if your IMAP server is using less secure ciphers.

    **Infrequently used `kwargs` parameters:**

    These parameters are very rarely changed.

    * **host** - Arlo host to use. Default `https://my.arlo.com`.
    * **storage_dir** - Where to store saved state.
    * **db_motion_time** - Time, in seconds, to show active for doorbell motion detected. Default 30 seconds.
    * **db_ding_time** - Time, in seconds, to show on for doorbell button press. Default 10 seconds.
    * **request_timeout** - Time, in seconds, for requests sent to Arlo to succeed. Default 60 seconds.
    * **recent_time** - Time, in seconds, for the camera to indicate it has seen motion. Default 600 seconds.
    * **no_media_upload** - Force a media upload after camera activity.
      Normally not needed but some systems fail to push media uploads. Default 'False'. Deprecated, use `media_retry`.
    * **media_retry** - Force a media upload after camera activity.
      Normally not needed but some systems fail to push media uploads. An
      integer array of timeout to use to get the update image. Default '[]'.
    * **no_media_upload** - Force a media upload after camera activity.
      Normally not needed but some systems fail to push media uploads. Default 'False'.
    * **user_agent** - Set what 'user-agent' string is passed in request headers. It affects what video stream type is
      returned. Default is `arlo`.
    * **mode_api** - Which api to use to set the base station modes. Default is `auto` which choose an API
      based on camera model. Can also be `v1`, `v2` or `v3`. Use `v3` for the new location API.
    * **reconnect_every** - Time, in minutes, to close and relogin to Arlo.
    * **snapshot_timeout** - Time, in seconds, to stop the snapshot attempt and return the camera to the idle state.
    * **mqtt_host** - specify the mqtt host to use, default mqtt-cluster.arloxcld.com
    * **mqtt_hostname_check** - disable MQTT host SSL certificate checking, default True
    * **mqtt_transport** - specify either `websockets` or `tcp`, default `tcp`
    * **ecdh_curve** - Sets initial ecdhCurve for Cloudscraper. Available options are `prime256v1`
      and `secp384r1`. Backend will try all options if login fails.
    * **send_source** - Add a `Source` item to the authentication header, default is False.

    **Attributes**

    Pyaarlo provides an asynchronous interface for receiving events from Arlo devices. To use it you register
    a callback for an attribute against a device. The following are a list of currently supported attributes:

    * **motionDetected** - called when motion start and stops
    * **audioDetected** - called when noise starts and stops
    * **activeMode** - called when a base changes mode
    * **more to come...** - I will flesh this out, but look in const.h for a good idea

    You can use the attribute `*` to register for all events.
    """

    _core: ArloCore = ArloCore
    _objs: ArloObjects = ArloObjects

    def __init__(self, **kwargs):
        """Constructor for the PyArlo object.
        """

        # Get logger initialised.
        self._core.log = ArloLogger(kwargs.get("verbose_debug", False))

        # Get version out early.
        self._core.log.info(f"pyarlo {__version__} starting...")

        # Now load the config.
        self._core.cfg = ArloCfg(self._core.log, **kwargs)

        # Create storage/scratch directory.
        try:
            if not os.path.exists(self._core.cfg.storage_dir):
                os.mkdir(self._core.cfg.storage_dir)
        except Exception:
            self.warning(f"Problem creating {self._core.cfg.storage_dir}")

        # Create remaining core components.
        self._core.bg = ArloBackground(self._core.log)
        self._core.st = ArloStorage(self._core.cfg, self._core.log)
        self._core.be = ArloBackEnd(self._core.cfg, self._core.log, self._core.bg)

        # Fill out the object store.
        # The lists are created empty but we need to add in the media library.
        self._objs.ml = ArloMediaLibrary(self._core, self._objs)

        # Failed to login, then stop now!
        if not self._core.be.is_connected:
            return

        self._lock = threading.Condition()

        # On day flip we do extra work, record today.
        self._today = datetime.date.today()

        # Every few hours we can refresh the device list.
        self._refresh_devices_at = time.monotonic() + self._core.cfg.refresh_devices_every

        # Every few minutes we can refresh the mode list.
        self._refresh_modes_at = time.monotonic() + self._core.cfg.refresh_modes_every

        # default blank image when waiting for camera image to appear
        self._blank_image = base64.standard_b64decode(BLANK_IMAGE)

        # Slow piece.
        # Get locations for multi location sites.
        # Get devices, fill local db, and create device instance.
        self.info("pyaarlo starting")
        self._started = False

        # Get locations if needed.
        if self._core.be.multi_location:
            self._refresh_locations()

        # Build Arlo objects.
        self._refresh_devices()
        self._build_objects()

        # Save out unchanging stats!
        self._core.st.set(["ARLO", TOTAL_CAMERAS_KEY], len(self._objs.cameras), prefix="aarlo")
        self._core.st.set(["ARLO", TOTAL_BELLS_KEY], len(self._objs.doorbells), prefix="aarlo")
        self._core.st.set(["ARLO", TOTAL_LIGHTS_KEY], len(self._objs.lights), prefix="aarlo")

        # Subscribe to events.
        self._core.be.start_monitoring()

        # Now ping the bases.
        self._ping_bases()

        # Start initial refresh and, if needed, wait for it to finish.
        self._initial_refresh(wait=self._core.cfg.synchronous_mode)
        if self._core.cfg.synchronous_mode or self._core.cfg.wait_for_initial_setup:
            with self._lock:
                while not self._started:
                    self.debug("waiting for initial setup...")
                    self._lock.wait(1)
            self.debug("initial setup finished...")

        # Register house keeping cron jobs.
        self.debug("registering cron jobs")
        self._core.bg.run_every(self._fast_refresh, FAST_REFRESH_INTERVAL)
        self._core.bg.run_every(self._slow_refresh, SLOW_REFRESH_INTERVAL)

    def __repr__(self):
        # Representation string of object.
        return "<{0}: {1}>".format(self.__class__.__name__, self._core.cfg.name)

    # Using this to indicate that we're using location-based modes, vs basestation-based modes.
    # also called Arlo app v4. Open to new ideas for what to call this.
    @property
    def _v3_modes(self):
        return self.cfg.mode_api.lower() == "v3"

    def _build_objects(self):
        """Convert devices into Arlo objects.
        """
        for device in self._devices:

            # Do we need to bother with this device?
            device_name = device.get("deviceName")
            device_state = device.get("state", "unknown").lower()
            if device_state not in VALID_DEVICE_STATES:
                self.info(f"skipping {device_name}: state is {device_state}")
                continue

            # Grab some more basic information.
            device_type = device.get("deviceType")
            model_id = device.get("modelId")

            # Check the type and create the appropriate object. Some devices
            # will create more than one object.
            if ArloTypes.is_a_base_station(device_type, model_id):
                self._objs.base_stations.append(ArloBaseStation(device_name, self._core, self._objs, device))
            if ArloTypes.can_be_own_base_station(model_id):
                parent_id = device.get("parentId", None)
                if parent_id is None or parent_id == device.get("deviceId", None):
                    self._objs.base_stations.append(ArloBaseStation(device_name, self._core, self._objs, device))
            if ArloTypes.is_a_camera(device_type, model_id):
                self._objs.cameras.append(ArloCamera(device_name, self._core, self._objs, device))
            if device_type == "doorbell":
                self._objs.doorbells.append(ArloDoorBell(device_name, self._core, self._objs, device))
            if device_type == "lights":
                self._objs.lights.append(ArloLight(device_name, self._core, self._objs, device))
            if device_type == "sensors":
                self._objs.sensors.append(ArloSensor(device_name, self._core, self._objs, device))

    def _refresh_devices(self):
        """Read in the devices list.

        This returns all devices known to the Arlo system. The newer devices
        include state information - battery levels etc - while the old devices
        don't. We update what we can.
        """
        url = DEVICES_PATH + "?t={}".format(time_to_arlotime())
        self._devices = self._core.be.get(url)
        if not self._devices:
            self.warning("No devices returned from " + url)
            self._devices = []
        self.vdebug(f"devices={pprint.pformat(self._devices)}")
        
        # Newer devices include information in this response. Be sure to update it.
        for device in self._devices:
            device_id = device.get("deviceId", None)
            props = device.get("properties", None)
            self.vdebug(f"device-id={device_id}")
            if device_id is not None and props is not None:
                device = self.lookup_device_by_id(device_id)
                if device is not None:
                    self.vdebug(f"updating {device_id} from device refresh")
                    device.update_resources(props)
                else:
                    self.vdebug(f"not updating {device_id} from device refresh")

    def _refresh_locations(self):
        """Retrieve location list from the backend
        """
        self.debug("_refresh_locations")
        self._objs.locations = []

        elocation_data = self._core.be.get(LOCATIONS_EMERGENCY_PATH)
        if elocation_data:
            self.debug("got something")
        else:
            self.debug("got nothing")

        url = LOCATIONS_PATH_FORMAT.format(self.be.user_id)
        location_data = self._core.be.get(url)
        if not location_data:
            self.warning("No locations returned from " + url)
        else:
            for user_location in location_data.get("userLocations", []):
                self._objs.locations.append(ArloLocation(self._core, self._objs, user_location, True))
            for shared_location in location_data.get("sharedLocations", []):
                self._objs.locations.append(ArloLocation(self._core, self._objs, shared_location, False))

        self.vdebug("locations={}".format(pprint.pformat(self._objs.locations)))

    def _refresh_camera_thumbnails(self, wait=False):
        """Request latest camera thumbnails, called at start up."""
        for camera in self._objs.cameras:
            camera.update_last_image(wait)

    def _refresh_camera_media(self, wait=False):
        """Rebuild cameras media library, called at start up or when day changes."""
        for camera in self._objs.cameras:
            camera.update_media(wait)

    def _refresh_ambient_sensors(self):
        for camera in self._objs.cameras:
            camera.update_ambient_sensors()

    def _refresh_doorbells(self):
        for doorbell in self._objs.doorbells:
            doorbell.update_silent_mode()

    def _ping_bases(self):
        for base in self._objs.base_stations:
            if base.has_capability(PING_CAPABILITY):
                base.ping()
            else:
                self.vdebug(f"NO ping to {base.device_id}")

    def _refresh_bases(self, initial):
        for base in self._objs.base_stations:
            base.update_modes(initial)
            base.keep_ratls_open()
            base.update_states()

    def _refresh_modes(self):
        self.vdebug("refresh modes")
        for base in self._objs.base_stations:
            base.update_modes()
            base.update_mode()
        for location in self._objs.locations:
            location.update_modes()
            location.update_mode()

    def _fast_refresh(self):
        self.vdebug("fast refresh")
        self._core.bg.run(self._core.st.save)
        self._ping_bases()

        # do we need to reload the modes?
        if self._core.cfg.refresh_modes_every != 0:
            now = time.monotonic()
            self.vdebug(
                "mode reload check {} {}".format(str(now), str(self._refresh_modes_at))
            )
            if now > self._refresh_modes_at:
                self.debug("mode reload needed")
                self._refresh_modes_at = now + self._core.cfg.refresh_modes_every
                self._core.bg.run(self._refresh_modes)
        else:
            self.vdebug("no mode reload")

        # do we need to reload the devices?
        if self._core.cfg.refresh_devices_every != 0:
            now = time.monotonic()
            self.vdebug(
                "device reload check {} {}".format(
                    str(now), str(self._refresh_devices_at)
                )
            )
            if now > self._refresh_devices_at:
                self.debug("device reload needed")
                self._refresh_devices_at = now + self._core.cfg.refresh_devices_every
                self._core.bg.run(self._refresh_devices)
        else:
            self.vdebug("no device reload")

        # if day changes then reload recording library and camera counts
        today = datetime.date.today()
        self.vdebug("day testing with {}!".format(str(today)))
        if self._today != today:
            self.debug("day changed to {}!".format(str(today)))
            self._today = today
            self._core.bg.run(self._objs.ml.load)
            self._core.bg.run(self._refresh_camera_media, wait=False)

    def _slow_refresh(self):
        self.vdebug("slow refresh")
        self._core.bg.run(self._refresh_bases, initial=False)
        self._core.bg.run(self._refresh_ambient_sensors)

    def _initial_refresh(self, wait: bool):
        self.debug(f"initial refresh, wait={wait}")
        self._core.bg.run(self._refresh_bases, initial=True)
        self._core.bg.run(self._refresh_modes)
        self._core.bg.run(self._refresh_ambient_sensors)
        self._core.bg.run(self._refresh_doorbells)
        self._core.bg.run(self._objs.ml.load)
        self._core.bg.run(self._refresh_camera_thumbnails, wait=wait)
        self._core.bg.run(self._refresh_camera_media, wait=wait)
        self._core.bg.run(self._initial_refresh_done)

    def _initial_refresh_done(self):
        self.debug("initial refresh done")
        with self._lock:
            self._started = True
            self._lock.notify_all()

    def stop(self, logout=False):
        """Stop connection to Arlo and, optionally, logout."""
        self._core.st.save()
        self._core.bg.stop()
        self._objs.ml.stop()
        if logout:
            self._core.be.logout()

    @property
    def entity_id(self):
        if self.cfg.serial_ids:
            return self.device_id
        else:
            return self.name.lower().replace(" ", "_")

    @property
    def name(self):
        return "ARLO CONTROLLER"

    @property
    def devices(self):
        return self._devices

    @property
    def device_id(self):
        return "ARLO"

    @property
    def model_id(self):
        return self.name

    @property
    def cfg(self):
        return self._core.cfg

    @property
    def bg(self):
        return self._core.bg

    @property
    def st(self):
        return self._core.st

    @property
    def be(self):
        return self._core.be

    @property
    def ml(self):
        return self._objs.ml

    @property
    def is_connected(self):
        """Returns `True` if the object is connected to the Arlo servers, `False` otherwise."""
        return self._core.be.is_connected

    @property
    def cameras(self):
        """List of registered cameras.

        :return: a list of cameras.
        :rtype: list(ArloCamera)
        """
        return self._objs.cameras

    @property
    def doorbells(self):
        """List of registered doorbells.

        :return: a list of doorbells.
        :rtype: list(ArloDoorBell)
        """
        return self._objs.doorbells

    @property
    def lights(self):
        """List of registered lights.

        :return: a list of lights.
        :rtype: list(ArloLight)
        """
        return self._objs.lights

    @property
    def base_stations(self):
        """List of base stations..

        :return: a list of base stations.
        :rtype: list(ArloBase)
        """
        return self._objs.base_stations

    @property
    def locations(self):
        """List of locations..

        :return: a list of locations.
        :rtype: list(ArloLocation)
        """
        return self._objs.locations

    @property
    def all_devices(self):
        return self.cameras + self.doorbells + self.lights + self.base_stations + self.locations

    @property
    def sensors(self):
        return self._objs.sensors

    @property
    def blank_image(self):
        """Return a binary representation of a blank image.

        :return: A bytes representation of a blank image.
        :rtype: bytearray
        """
        return self._blank_image

    def lookup_camera_by_id(self, device_id):
        """Return the camera referenced by `device_id`.

        :param device_id: The camera device to look for
        :return: A camera object or 'None' on failure.
        :rtype: ArloCamera
        """
        camera = list(filter(lambda cam: cam.device_id == device_id, self.cameras))
        if camera:
            return camera[0]
        return None

    def lookup_camera_by_name(self, name):
        """Return the camera called `name`.

        :param name: The camera name to look for
        :return: A camera object or 'None' on failure.
        :rtype: ArloCamera
        """
        camera = list(filter(lambda cam: cam.name == name, self.cameras))
        if camera:
            return camera[0]
        return None

    def lookup_doorbell_by_id(self, device_id):
        """Return the doorbell referenced by `device_id`.

        :param device_id: The doorbell device to look for
        :return: A doorbell object or 'None' on failure.
        :rtype: ArloDoorBell
        """
        doorbell = list(filter(lambda cam: cam.device_id == device_id, self.doorbells))
        if doorbell:
            return doorbell[0]
        return None

    def lookup_doorbell_by_name(self, name):
        """Return the doorbell called `name`.

        :param name: The doorbell name to look for
        :return: A doorbell object or 'None' on failure.
        :rtype: ArloDoorBell
        """
        doorbell = list(filter(lambda cam: cam.name == name, self.doorbells))
        if doorbell:
            return doorbell[0]
        return None

    def lookup_light_by_id(self, device_id):
        """Return the light referenced by `device_id`.

        :param device_id: The light device to look for
        :return: A light object or 'None' on failure.
        :rtype: ArloDoorBell
        """
        light = list(filter(lambda cam: cam.device_id == device_id, self.lights))
        if light:
            return light[0]
        return None

    def lookup_light_by_name(self, name):
        """Return the light called `name`.

        :param name: The light name to look for
        :return: A light object or 'None' on failure.
        :rtype: ArloDoorBell
        """
        light = list(filter(lambda cam: cam.name == name, self.lights))
        if light:
            return light[0]
        return None

    def lookup_base_station_by_id(self, device_id):
        """Return the base_station referenced by `device_id`.

        :param device_id: The base_station device to look for
        :return: A base_station object or 'None' on failure.
        :rtype: ArloDoorBell
        """
        base_station = list(filter(lambda cam: cam.device_id == device_id, self.base_stations))
        if base_station:
            return base_station[0]
        return None

    def lookup_base_station_by_name(self, name):
        """Return the base_station called `name`.

        :param name: The base_station name to look for
        :return: A base_station object or 'None' on failure.
        :rtype: ArloDoorBell
        """
        base_station = list(filter(lambda cam: cam.name == name, self.base_stations))
        if base_station:
            return base_station[0]
        return None

    def lookup_device_by_id(self, device_id):
        device = self.lookup_base_station_by_id(device_id)
        if device is None:
            device = self.lookup_camera_by_id(device_id)
        if device is None:
            device = self.lookup_doorbell_by_id(device_id)
        if device is None:
            device = self.lookup_light_by_id(device_id)
        return device

    def inject_response(self, response):
        """Inject a test packet into the event stream.

        **Note:** The method makes no effort to check the packet.

        :param response: packet to inject.
        :type response: JSON data
        """
        self.debug("injecting\n{}".format(pprint.pformat(response)))
        self._core.be.ev_inject(response)

    def attribute(self, attr):
        """Return the value of attribute attr.

        PyArlo stores its state in key/value pairs. This returns the value associated with the key.

        :param attr: Attribute to look up.
        :type attr: str
        :return: The value associated with attribute or `None` if not found.
        """
        return self._core.st.get(["ARLO", attr], None)

    def add_attr_callback(self, attr, cb):
        pass

    # TODO needs thinking about... track new cameras for example.
    def update(self, update_cameras=False, update_base_station=False):
        pass

    def error(self, msg):
        self._core.log.error(msg)

    @property
    def last_error(self):
        """Return the last reported error."""
        return self._core.log.last_error

    def warning(self, msg):
        self._core.log.warning(msg)

    def info(self, msg):
        self._core.log.info(msg)

    def debug(self, msg):
        self._core.log.debug(msg)

    def vdebug(self, msg):
        self._core.log.vdebug(msg)
