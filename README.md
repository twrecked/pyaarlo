# Pyaarlo

## Alpha Build

Welcome to the Pyaarlo alpha build. I'm using the 0.8.x stream to split
`pyaarlo` out from `hass-aarlo`. This is partly motivated by thinking about
getting `hass-aarlo` back into Home Assistant and partly motivated by my
desire to stop having to commit bug fixes in 2 places.

### Breaking Changes

#### Cached Session
The code will now save the session details and reuse the authentication token
when possible. This can drastically reduce the number of authentication
requests the code will make (and 2FA requests if needed). If this doesn't work
for you pass `save_session=False` as a parameter to `PyArlo()`.


## Table of Contents
- [Introduction](#introduction)
- [Installation](#installation)
- [Usage](#usage)
- [Pyaarlo Executable](#executable)
- [User Agent](#user-agent)
- [Saving Media](#saving-media)
- [2 Factor Authentication](#2fa)
  * [Manual](#2fa-manual)
  * [IMAP](#2fa-imap)
- [Error Reporting](#errors)
- [Limitations](#limitations)
- [Other 2 Factor Authentication](#2fa-other)


<a name="introduction"></a>
## Introduction

Pyaarlo is a module for Python that provides asynchronous access to Netgear
Arlo cameras.

When you start Pyaarlo, it starts a background thread that opens a single,
persistant connection, an *event stream*, to the Arlo servers. As things happen
to the Arlo devices - motion detected, battery level changes, mode changes,
etc... - the Arlo servers post these events onto the event stream. The
background thread reads these events from the stream, updates Pyaarlo's internal
state and calls any user registered callbacks.

#### Differences from Pyarlo

The biggest difference is Pyaarlo defaults to asynchronous mode by default. The
following code brought from Pyarlo might not work:

```python
base.mode = 'armed'
if base.mode == 'armed':
    print('it worked!')
```

This is because between setting `mode` and reading `mode` the code has to:
* build and send a mode change packet to Arlo
* read the mode change packet back from the Arlo event stream
* update its internal state for `base`

I say "might" not work because it might work, it all depends on timing, and
context switches and network speed...

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
* [Pyarlo](https://github.com/tchellomello/python-arlo) and
  [Arlo](https://github.com/jeffreydwalter/arlo) for doing the original heavy
  lifting and the free Python lesson!
* [sseclient](https://github.com/btubbs/sseclient) for reading from the event
  stream
* [JetBrains](https://www.jetbrains.com/?from=hass-aarlo) for the excellent
  **PyCharm IDE** and providing me with an open source license to speed up the
  project development.

  [![JetBrains](/images/jetbrains.svg)](https://www.jetbrains.com/?from=hass-aarlo)


<a name="installation"></a>
## Installation

Proper PIP support is coming but for now, this will install the latest version.

```bash
pip install git+https://github.com/twrecked/pyaarlo
```

<a name="usage"></a>
## Usage

You can read the developer documentation here:
[https://pyaarlo.readthedocs.io/](https://pyaarlo.readthedocs.io/)

The following example will login to your Arlo system, use 2FA if needed,
register callbacks for all events on all base stations and cameras and then wait
10 minutes printing out any events that arrive during that time.

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
for camera in arlo.cameras:
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

As mentioned, it uses the [Pyarlo](https://github.com/tchellomello/python-arlo)
API where possible so the following code from the original
[Usage](https://github.com/tchellomello/python-arlo#usage) will still work:

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


<a name="user-agent"></a>
## User Agent

The `user_agent` option will control what kind of stream Arlo sends to you.
The options are:
- `arlo`; the original user agent, returns an `rtsps` stream.
- `ipad`; returns a `HLS` stream
- `mac`; returns a `HLS` stream
- `linux`; returns a `MPEG-DASH` stream


<a name="saving-media"></a>
## Saving Media

If you use the `save_media_to` parameter to specify a file naming scheme
`praarlo` will use that to save all media - videos and snapshots - locally. You
can use the following substitutions:

- `SN`; the device serial number
- `N`; the device name
- `Y`; the year of the recording, include century
- `m`; the month of the year as a number (range 01 to 12)
- `d`; the day of the month as a number (range 01 to 31)
- `H`; the hour of the day (range 00 to 23)
- `M`; the minute of the hour (range 00 to 59)
- `S`; the seconds of the minute (range 00 to 59)
- `F`; a short cut for `Y-m-d`
- `T`; a short cut for `H:M:S`
- `t`; a short cut for `H-M-S`
- `s`; the number of seconds since the epoch

You specify the substitution by prefixing it with a `$` in the format string.
You can optionally use curly brackets to remove any ambiguity. For example,
the following configuration will save all media under `/config/media`
organised by serial number then date. The code will add the correct file
extension.

```yaml
  save_media_to: "/config/media/${SN}/${Y}/${m}/${d}/${T}"
```

The first time you configure `save_media_to` the system can take several
minutes to download all the currently available media. The download is
throttled to not overload Home Assistant or Arlo. Once the initial download is
completed updates should happen a lot faster.

The code doesn't provide any management of the downloads, it will keep
downloading them until your device is full. It also doesn't provide a NAS
interface, you need to mount the NAS device and point `save_media_to` at it.


<a name="2fa"></a>
## 2FA

Pyaarlo supports 2 factor authentication.


<a name="2fa-manual"></a>
#### Manual

Start `PyArlo` specifying `tfa_source` as `console`. Whenever `PyArlo` needs a
secondary code it will prompt you for it.

```python
ar = pyaarlo.PyArlo(username=USERNAME, password=PASSWORD,
                    tfa_source='console', tfa_type='SMS')
```

<a name="2fa-imap"></a>
#### IMAP

__I recommend using `IMAP`, it's well tested now and it works. The other
methods haven't been tested or looked at in a while.__

Automatic is trickier. Support is there but needs testing. For automatic 2FA
PyArlo needs to access and your email account form where it reads the token Arlo
sent.

```python
ar = pyaarlo.PyArlo(username=USERNAME, password=PASSWORD,
                    tfa_source='imap',tfa_type='email',
                    tfa_host='imap.host.com',
                    tfa_username='your-user-name',
                    tfa_password='your-imap-password' )
```

It's working well with my gmail account, see
[here](https://support.google.com/mail/answer/185833?hl=en) for help setting up
single app passwords.


<a name="executable"></a>
## Pyaarlo Executable

The pip installation adds an executable `pyaarlo`. You can use this to list
devices, perform certain simple actions and anonymize and encrypt logs for
debugging purposes. _Device operations are currently limited..._

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

When reporting errors please include the version of Pyaarlo you are using and
what Arlo devices you have. Please turn on DEBUG level logging, capture the
output and include as much information as possible about what you were trying to
do.

You can use the `pyaarlo` executable to anonymize and encrypt feature on
arbitrary data like log files or source code. If you are only encrypting you
don't need your username and password.

```bash
# encrypt an existing file
cat output-file | pyaarlo encrypt

# anonymize and then encrypt a file
cat output-file | pyaarlo -u 'your-user-name' -p 'your-password' anonymize | pyaarlo encrypt
```

If you installed from git you can use a shell script in `bin/` to encrypt your
logs. No anonymizing is possible this way.
 
```bash
# encrypt an existing file
cat output-file | ./bin/pyaarlo-encrypt encrypt
```

`pyaarlo-encrypt` is a fancy wrapper around:

```bash
curl -s -F 'plain_text_file=@-;filename=clear.txt' https://pyaarlo-tfa.appspot.com/encrypt
```

You can also encrypt your output on this [webpage](https://pyaarlo-tfa.appspot.com/).


<a name="limitations"></a>
## Limitations
The component uses the Arlo webapi.
* There is no documentation so the API has been reverse engineered using browser
  debug tools.
* There is no support for smart features, you only get motion detection
  notifications, not what caused the notification. (Although, you can pipe a
  snapshot into deepstack...) This isn't strictly true, you can get "what
  caused" the notifications but only after Arlo has analysed the footage.
* Streaming times out after 30 minutes.
* The webapi doesn't seem like it was really designed for permanent connections
  so the system will sometimes appear to lock up. Various work arounds are in
  the code and can be configured at the `arlo` component level. See next
  paragraph.

If you do find the component locks up after a while (I've seen reports of hours,
days or weeks), you can add the following to the main configuration. Start from
the top and work down: 
* `refresh_devices_every`, tell Pyaarlo to request the device list every so
  often. This will sometimes prevent the back end from aging you out. The value
  is in hours and a good starting point is 3.
* `stream_timeout`, tell Pyaarlo to close and reopen the event stream after a
  certain period of inactivity. Pyaarlo will send keep alive every minute so a
  good starting point is 180 seconds.
* `reconnect_every`, tell Pyaarlo to logout and back in every so often. This
  establishes a new session at the risk of losing an event notification. The
  value is minutes and a good starting point is 90.
* `request_timeout`, the amount of time to allow for a http request to work. A
  good starting point is 120 seconds.

Alro will allow shared accounts to give cameras their own name. If you find
cameras appearing with unexpected names (or not appearing at all), log into the
Arlo web interface with your Home Assistant account and make sure the camera
names are correct.

You can change the brightness on the light but not while it's turned on. You
need to turn it off and back on again for the change to take. This is how the
web interface does it.


<a name="2fa-other"></a>
## Other 2 Factor Authentication

__I recommend using `IMAP`, it's well tested now and it works. These following
methods haven't been tested or looked at in a while.__

<a name="2fa-rest-api"></a>
#### Rest API

This mechanism allows you to an external website. When you start authenticating
Pyarlo makes a `clear` request and repeated `look-up` requests to a website to
retrieve your TFA code. The format of these requests and their responses are well
defined but the host Pyarlo uses is configurable.

```python
ar = pyaarlo.PyArlo(username=USERNAME, password=PASSWORD,
                    tfa_source='rest-api',tfa_type='email',
                    tfa_host='custom-host',
                    tfa_username='test@test.com',
                    tfa_password='1234567890' )
```

* Pyaarlo will clear the current code with this HTTP GET request:
```http request
https://custom-host/clear?email=test@test.com&token=1234567890
``` 

* And the server will respond with this on success:
```json
{ "meta": { "code": 200 },
  "data": { "success": True, "email": "test@test.com" } }
```

* Pyaarlo will look up the current code with this HTTP GET request:
```http request
https://custom-host/get?email=test@test.com&token=1234567890
``` 

* And the server will respond with this on success:
```json
{ "meta": { "code": 200 },
  "data": { "success": True, "email": "test@test.com", "code": "123456", "timestamp": "123445666" } }
```

* Failures always have `code` value of anything other than 200.
```json
{ "meta": { "code": 400 },
  "data": { "success": False, "error": "permission denied" }}
```

Pyaarlo doesn't care how you get the codes into the system only that they are
there. Feel free to roll your own server or...

##### Using My Server

I have a website running at https://pyaarlo-tfa.appspot.com that can provide
this service. It's provided as-is, it's running as a Google app so it should be
pretty reliable and the only information I have access to is your email address,
access token for my website and whatever your last code was. (_Note:_ if you're
not planning on using email forwarding the `email` value isn't strictly
enforced, a unique ID is sufficient.)

_If you don't trust me and my server - and I won't be offended - you can get the
source from [here](https://github.com/twrecked/pyaarlo-tfa-helper) and set up
your own._

To use the REST API with my website do the following:

* Register with my website. You only need to do this once and I'm sorry for the
  crappy interface. Go to [registration
  page](https://pyaarlo-tfa.appspot.com/register) and enter your email address
  (or unique ID). The website will reply with a json document containing your
  _token_, keep this _token_ and use it in all REST API interactions.
```json
{"email":"testing@testing.com",
 "fwd-to":"pyaarlo@thewardrobe.ca",
 "success":true,
 "token":"4f529ea4dd20ca65e102e743e7f18914bcf8e596b909c02d"}
```

* To add a code send the following HTTP GET request:
```http request
https://custom-host/add?email=test@test.com&token=4f529ea4dd20ca65e102e743e7f18914bcf8e596b909c02d&code=123456
```

You can replace `code` with `msg` and the server will try and parse the code out
value of `msg`, use it for picking apart SMS messages.

##### Using IFTTT

You have your server set up or are using mine, one way to send codes is to use
[IFTTT](https://ifttt.com/) to forward SMS messages to the server. I have an
Android phone so use the `New SMS received from phone number` trigger and match
to the Arlo number sending me SMS codes. (I couldn't get the match message to
work, maybe somebody else will have better luck.)

I pair this with `Make a web request` action to forward the SMS code into my
server, I use the following recipe. Modify the email and token as necessary.
```
URL: https://pyaarlo-tfa.appspot.com/add?email=test@test.com&token=4f529ea4dd20ca65e102e743e7f18914bcf8e596b909c02d&msg={{Text}}
Method: GET
Content Type: text/plain
```

Make sure to configure Pyaarlo to request a token over SMS with `tfa_type='SMS`.
Now, when you login in, Arlo will send an SMS to your phone, the IFTTT app will
forward this to the server and Pyaarlo will read it from the server.

##### Using EMAIL

If you run your own `postfix` server you can use [this
script](https://github.com/twrecked/pyaarlo-tfa-helper/blob/master/postfix/pyaarlo-fwd.in)
to set up an email forwarding alias. Use an alias like this:
```text
pyaarlo:  "|/home/test/bin/pyaarlo-fwd"
```

Make sure to configure Pyaarlo to request a token over SMS with
`tfa_type='EMAIL`. Then set up your email service to forward Arlo code message
to your email forwarding alias.

