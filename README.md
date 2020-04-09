# Pyaarlo

## Table of Contents
- [Introduction](#introduction)
- [Installation](#installation)
- [Usage](#usage)
- [Pyaarlo Executable](#executable)
- [2 Factor Authentication](#2fa)
- [Error Reporting](#error)
- [Limitations](#limitations)

<a name="introduction"></a>
## Introduction

Pyaarlo is a module for for Python that provides asynchronous access to Netgear Arlo cameras.

When you start Pyaarlo, it starts a background thread that opens a single, persistant connection, an *event stream*, to the Arlo servers. As things happen to the Arlo devices - motion detected, battery level changes, mode changes, etc... - the Arlo servers post these events onto the event stream. The background thread reads these events from the stream, updates Pyaarlo's internal state and calls any user registered callbacks.

#### Differences from Pyarlo

The biggest difference is Pyaarlo defaults to asynchronous mode by default. The following code brought from Pyarlo might not work:

```python
base.mode = 'armed'
if base.mode == 'armed':
    print('it worked!')
```

This is because between setting `mode` and reading `mode` the code has to:
* build and send a mode change packet to Arlo
* read the mode change packet back from the Arlo event stream
* update its internal state for `base`

I say "might" not work because it might work, it all depends on timing, and context switches and network speed...

To enable synchronous mode you need to specify it when starting PyArlo.

```python
# login, use console for 2FA if needed
arlo = pyaarlo.PyArlo( username=USERNAME,password=PASSWORD,
                       tfa_type='SMS',tfa_source='console',
                       synchronous_mode=True)
```

<a name="introduction-thanks"></a>
#### Thanks 
Many thanks to:
* [Pyarlo](https://github.com/tchellomello/python-arlo) and [Arlo](https://github.com/jeffreydwalter/arlo) for doing the original heavy lifting and the free Python lesson!
* [sseclient](https://github.com/btubbs/sseclient) for reading from the event stream
* [![JetBrains](/images/jetbrains.svg)](https://www.jetbrains.com/?from=hass-aarlo) for the excellent **PyCharm IDE** and providing me with an open source license to speed up the project development.


<a name="installation"></a>
## Installation

Proper PIP support is coming but for now, this will install the latest version.

```bash
pip install git+https://github.com/twrecked/pyaarlo
```

<a name="usage"></a>
## Usage

You can read the developer documentation here: [https://pyaarlo.readthedocs.io/](https://pyaarlo.readthedocs.io/)

The following example will login to your Arlo system, use 2FA if needed, register callbacks for all events on all base stations and cameras and then wait 10 minutes printing out any events that arrive during that time.

```python
# code to trap when attributes change
def attribute_changed(device, attr, value):
    print('attribute_changed', time.strftime("%H:%M:%S"), device.name + ':' + attr + ':' + str(value)[:80])

# login, use console for 2FA if needed
arlo = pyaarlo.PyArlo( username=USERNAME,password=PASSWORD,
                       tfa_type='SMS',tfa_source='console')

# get base stations, list their statuses, register state change callbacks
for base in arlo.base_stations:
    print("base: name={},device_id={},state={}".format(base.name,base.device_id,base.state))
    base.add_attr_callback('*', attribute_changed)

# get cameras, list their statuses, register state change callbacks
# * is any callback, you can use motionDetected just to get motion events
for camera in arlo.camera_stations:
    print("camera: name={},device_id={},state={}".format(camera.name,camera.device_id,camera.state))
    camera.add_attr_callback('*', attribute_changed)

# disarm then arm the first base station
base = arlo.base_stations[0]
base.mode = 'disarmed'
time.sleep(5)
base.mode = 'armed'

# wait 10 minutes, try moving in front of a camera to see motionDetected events
time.sleep(600)

```

As mentioned, it uses the [Pyarlo](https://github.com/tchellomello/python-arlo) API where possible so the following code from the original [Usage](https://github.com/tchellomello/python-arlo#usage) will still work:

```python

# login, use console for 2FA if needed, turn on synchronous_mode for maximum compatibility
arlo = pyaarlo.PyArlo( username=USERNAME,password=PASSWORD,
                       tfa_type='SMS',tfa_source='console',synchronous_mode=True)

# listing devices
arlo.devices

# listing base stations
arlo.base_stations

# get base station handle
# assuming only 1 base station is available
base = arlo.base_stations[0]

# get the current base station mode
base.mode  # 'disarmed'

# listing Arlo modes
base.available_modes # ['armed', 'disarmed', 'schedule', 'custom']

# Updating the base station mode
base.mode = 'custom'

# listing all cameras
arlo.cameras

# showing camera preferences
cam = arlo.cameras[0]

# check if camera is connected to base station
cam.is_camera_connected  # True

# printing camera attributes
cam.serial_number
cam.model_id
cam.unseen_videos

# get brightness value of camera
cam.brightness
```


<a name="2fa"></a>
## 2FA

Pyaarlo supports 2 factor authentication.

#### Manual

Start `PyArlo` specifying `tfa_source` as `console`. Whenever `PyArlo` needs a secondary code it will prompt you for it.

```python
ar = pyaarlo.PyArlo(username=USERNAME, password=PASSWORD,
                    tfa_source='console', tfa_type='SMS')
```

#### Automatic

Automatic is trickier. Support is there but needs testing. For automatic 2FA PyArlo needs to access and your email account form where it reads the token Arlo sent.

```python
ar = pyaarlo.PyArlo(username=USERNAME, password=PASSWORD,
                    tfa_source='imap',tfa_type='email',
                    imap_host='imap.host.com',
                    imap_username='your-user-name',
                    imap_password='your-imap-password' )
```

It's working well with my gmail account, see [here](https://support.google.com/mail/answer/185833?hl=en) for help setting up single app passwords.

#### Rest API

_I will be adding to this section..._

This mechanism allows you to hook a custom method for getting your code into a REST API. The short version is:
When you start authenticating Pyarlo makes a clear request and repeated get requests to a website to retrieve your TFA. The format of the clear and get requests and their reponses are well defined but the host Pyarlo uses is configurable.
* The clear is a GET request with the following format.
```http request
https://custom-host/clear?email=test@test.com&token=1234567890
``` 

* The get is a GET request with the following format:
```http request
https://custom-host/get?email=test@test.com&token=1234567890
``` 

* When you receive a code from Arlo you call this URL and the code will be picked up by Arlo.
```http request
https://custom-host/get?email=test@test.com&token=1234567890&code=123456
``` 

_How to get the code into the system... I have a working email to URL gateway but other options should be available. I'm thinking IFTTT._

I have a website running at https://pyaarlo-tfa.appspot.com that can provide this service. Email if interested.
 
<a name="executable"></a>
## Pyaarlo Executable

The pip installation adds an executable `pyaarlo`. You can use this to list devices, perform certain simple actions and anonymize and encrypt logs for debugging purposes. _Device operations are currently limited..._

The git installation has `bin/pyaarlo` which functions in a similar manner.

```bash
# To show the currently available actions:
pyaarlo --help

# To list all the known devices:
pyaarlo -u 'your-user-name' -p 'your-password' list all

# this version will anonymize the output
pyaarlo -u 'your-user-name' -p 'your-password' --anonymize list all

# this version will anonymize and encrypt the output
pyaarlo -u 'your-user-name' -p 'your-password' --anonymize --encrypt list all
```


<a name="errors"></a>
## Error Reporting

When reporting errors please include the version of Pyaarlo you are using and what Arlo devices you have. Please turn on DEBUG level logging, capture the output and include as much information as possible about what you were trying to do.

You can use the `pyaarlo` executable to anonymize and encrypt feature on arbitrary data like log files or source code. If you are only encrypting you don't need your username and password.

```bash
# encrypt an existing file
cat output-file | pyaarlo encrypt

# anonymize and then encrypt a file
cat output-file | pyaarlo -u 'your-user-name' -p 'your-password' anonymize | pyaarlo encrypt
```

If you installed from git you can use a shell script in `bin/` to encrypt your logs. No anonymizing is possible this way.
 
```bash
# encrypt an existing file
cat output-file | ./bin/pyaarlo-encrypt encrypt
```

`pyaarlo-encrypt` is a fancy wrapper around:

```bash
curl -s -F 'plain_text_file=@-;filename=clear.txt' https://pyaarlo-tfa.appspot.com/encrypt
```


<a name="limitations"></a>
## Limitations
The component uses the Arlo webapi.
* There is no documentation so the API has been reverse engineered using browser debug tools.
* There is no support for smart features, you only get motion detection notifications, not what caused the notification. (Although, you can pipe a snapshot into deepstack...)
* Streaming times out after 30 minutes.
* The webapi doesn't seem like it was really designed for permanent connections so the system will sometimes appear to lock up. Various work arounds are in the code and can be configured at the `arlo` component level. See next paragraph.

If you do find the component locks up after a while (I've seen reports of hours, days or weeks), you can add the following to the main configuration. Start from the top and work down: 
* `refresh_devices_every`, tell Pyaarlo to request the device list every so often. This will sometimes prevent the back end from aging you out. The value is in hours and a good starting point is 3.
* `stream_timeout`, tell Pyaarlo to close and reopen the event stream after a certain period of inactivity. Pyaarlo will send keep alive every minute so a good starting point is 180 seconds.
* `reconnect_every`, tell Pyaarlo to logout and back in every so often. This establishes a new session at the risk of losing an event notification. The value is minutes and a good starting point is 90.
* `request_timout`, the amount of time to allow for a http request to work. A good starting point is 120 seconds.

Alro will allow shared accounts to give cameras their own name. If you find cameras appearing with unexpected names (or not appearing at all), log into the Arlo web interface with your Home Assistant account and make sure the camera names are correct.

You can change the brightness on the light but not while it's turned on. You need to turn it off and back on again for the change to take. This is how the web interface does it.
