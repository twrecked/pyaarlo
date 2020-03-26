# pyaarlo
Asynchronous Arlo Component for Python

Python Aarlo is a library that provides asynchronous access to  Netgear Arlo cameras.

It is based on the [pyarlo library](https://github.com/tchellomello/python-arlo) and aims to provide a similar interface.

### Installation

```bash
pip install git+https://github.com/twrecked/pyaarlo
```

### Differences from Pyarlo

The biggest difference is `pyaarlo` is asynchronous. This means:

* When you start `pyaarlo` it starts a thread that opens a single, persistant connection to the Arlo servers. As notifications come in - motion detected, battery level changes, mode changes - the state changes are noted internally and, optionally, any user registered callbacks are made.
* When you make a change PyArlo forwards the request to Arlo and updates its internal state when the Arlo notifies us of the change.

What does this mean. When you call this code:

```python
	base.mode = 'armed'
```

This happens:
* `pyaarlo` maps the `armed` mode to the real value.
* `pyaarlo` sends the mode change request to Arlo.
* The function returns and your code continues.
* Time passes. (Milliseconds...)
* Arlo signals the mode change on the event stream.
* `pyaarlo` reads the event from the stream and updates its internal state.
* `pyaarlo` will call any user registered callbacks.


### 2FA

Pyaarlo supports 2 factor authentication.

#### Manual

Start `PyArlo` specifying `tfa_source` as `console`. Whenever `PyArlo` needs a secondary code it will prompt you for it.

```python
ar = pyaarlo.PyArlo( username=USERNAME, password=PASSWORD,
						tfa_source='console', tfa_type='SMS')
```

#### Automatic

Automatic is trickier. Support is there but needs testing. For automatic 2FA PyArlo needs to access and your email account form where it reads the token Arlo sent.

```python
ar = pyaarlo.PyArlo( username=USERNAME, password=PASSWORD,
						tfa_source='imap',tfa_type='email',
						imap_host='imap.host.com', imap_username='your-user-name', imap_password='your-imap-password' )
```


### Usage

**This needs updating...**

Start by looking at [here](https://github.com/tchellomello/python-arlo/blob/master/README.rst) at the docs for the original project.

``` python
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
for camera in arlo.camera_stations:
    print("camera: name={},device_id={},state={}".format(camera.name,camera.device_id,camera.state))
    camera.add_attr_callback('*', attribute_changed)

# disarm then arm the first base station
base = arlo.base_stations[0]
base.mode = 'disarmed'
time.sleep(5)
base.mode = 'armed'

# wait five minutes, try moving in front of a camera to see motionDetected events
time.sleep(300)

```



### ToDo

* Provide some sync mappings for some settings.

