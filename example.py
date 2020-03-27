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
logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger('pyaarlo')


# Login. If 2FA is needed then choose to send code via SMS and enter it
# directly on the console
print("logging on")
ar = pyaarlo.PyArlo( username=USERNAME,password=PASSWORD,
                        tfa_type='SMS',tfa_source='console',verbose_debug=True,
                        save_state=False,dump=False,
                        storage_dir='aarlo' )
if not ar.is_connected:
    print('failed to connect')
    sys.exit(-1)

# list base stations
print("base stations")
for base in ar.base_stations:
    print("base: name={},device_id={},mode={}".format(base.name,base.device_id,base.mode))

time.sleep( 20 )
