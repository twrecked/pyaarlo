#!/usr/bin/env python
#

import os
import sys
import time
import logging

import pyaarlo


USERNAME = os.environ.get('ARLO_USERNAME','test.login@gmail.com')
PASSWORD = os.environ.get('ARLO_PASSWORD','test-password')


# Turn on debugging
logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger('pyaarlo')


def camera_update_state(device, attr, value):
    _LOGGER.debug('callback:' + device.name + ':' + attr + ':' + str(value)[:80])


# Login. If 2FA is needed then choose to send code via SMS and enter it
# directly on the console
ar = pyaarlo.PyArlo( username=USERNAME,password=PASSWORD,
                        tfa_type='SMS',tfa_source='console',
                        storage_dir='aarlo' )
if not ar.is_connected:
    print('failed to connect')
    sys.exit(-1)

# list base stations
for base in ar.base_stations:
    print("base: name={},device_id={}".format(base.name,base.device_id))

# track camera motion detections
for camera in ar.cameras:
    print("camera: name={},device_id={}".format(camera.name,camera.device_id))
    camera.add_attr_callback('motionDetected', camera_update_state)

time.sleep( 300 )

