#!/usr/bin/env python
#

import os
import time
import logging

import pyaarlo

logging.basicConfig(level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
_LOGGER = logging.getLogger('pyaarlo')

USERNAME = os.environ.get('ARLO_USERNAME','test.login@gmail.com')
PASSWORD = os.environ.get('ARLO_PASSWORD','test-password')

def attribute_changed(device, attr, value):
    print('attribute_changed', time.strftime("%H:%M:%S"), device.name + ':' + attr + ':' + str(value)[:80])

arlo = pyaarlo.PyArlo( username=USERNAME,password=PASSWORD,
                        tfa_type='SMS',tfa_source='console',
                        save_state=False,dump=False,storage_dir='aarlo' )

print('logged in')
first_base = None
original_mode = None
for base in arlo.base_stations:
    print("base: name={},device_id={},state={}".format(base.name,base.device_id,base.state))
    base.add_attr_callback('*', attribute_changed)
    if first_base is None:
        first_base = base
        original_mode = base.mode

url = None
for camera in arlo.cameras:
    if url is None:
        url = camera.get_stream()

time.sleep(30)
print('arming')
first_base.mode = 'armed'

time.sleep(10)
print('disarming')
first_base.mode = 'disarmed'

time.sleep(10)
print('setting original mode')
first_base.mode = original_mode

time.sleep(600)
