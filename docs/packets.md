
# Arlo Packet Types
These are the packets we can receive over the _SSE_ or _MQTT_ back ends.

## Packet type #1
This is a subscription reply packet. This will be received about once a
minute for devices that need them.

```json
{ "action": "is",
  "from": "XXXXXXXXXXXXX",
  "properties": {"devices": ["XXXXXXXXXXXXX"]},
  "resource": "subscriptions/XXXXXXXXXXXXX24993_web",
  "to": "XXXXXXXXXXXXX24993_web",
  "transId": "web!33c2027d-9b96-4a9f-9b41-aaf412082e80"}
```

## Packet type #2
A base has changed its alarm mode, ie, gone from `disarmed` to `armed`. The
packet can appear when we change mode or another user changes the mode.

```json
{ "4R068BXXXXXXX": { "activeModes": ["mode1"],
                     "activeSchedules": [],
                     "timestamp": 1568142116238},
  "resource": "activeAutomations"}
```

## Packet type #3
These packets are updates from individual devices, they normally indicate some
sort of activity we are interested in; motion or sound or a temperature change.

```json
{ "action": "is",
  "from": "XXXXXXXXXXXXX",
  "properties": {"motionDetected": "True"},
  "resource": "cameras/XXXXXXXXXXXXX",
  "transId": "XXXXXXXXXXXXX!c87fdfa6!1675735611287"}
```

## Packet type #4
These packets are returned from base stations to describe themselves and their
child devices' states. We will periodically ask for this information to keep
our device information up to do.

```json
{ "action": "is",
  "devices": { "XXXXXXXXXXXXX": { "properties": { "activityState": "idle",
                                                  "alsReading": 32,
                                                  "alsSensitivity": 15,
                                                  "armed": "True",
                                                  "batteryLevel": 45,
                                                  "batteryTech": "Rechargeable",
                                                  "brightness": 0,
                                                  "chargeNotificationLedEnable": "False",
                                                  "chargerTech": "None",
                                                  "chargingState": "Off",
                                                  "colorMode": "single",
                                                  "connectionState": "available",
                                                  "duration": 300,
                                                  "flash": "off",
                                                  "hwVersion": "AL1101r3",
                                                  "interfaceVersion": 2,
                                                  "lampState": "off",
                                                  "modelId": "AL1101",
                                                  "motionDetected": "False",
                                                  "motionSetupModeEnabled": "False",
                                                  "motionSetupModeSensitivity": 80,
                                                  "multi": { "color1": "0xFF0008",
                                                             "color2": "0x23FF02",
                                                             "color3": "0x2100FF",
                                                             "cycle": 2},
                                                  "name": "",
                                                  "pattern": "flood",
                                                  "sensitivity": 80,
                                                  "serialNumber": "XXXXXXXXXXXXX",
                                                  "signalStrength": 0,
                                                  "single": "0xFFDEAD",
                                                  "sleepTime": 0,
                                                  "sleepTimeRel": 0,
                                                  "swVersion": "3.2.51",
                                                  "updateAvailable": "None"},
                                  "states": { "motionStart": { "enabled": "True",
                                                               "external": {},
                                                               "lightOn": { "brightness": 255,
                                                                            "colorMode": "white",
                                                                            "duration": 30,
                                                                            "enabled": "True",
                                                                            "flash": "off",
                                                                            "pattern": "flood"},
                                                               "pushNotification": { "enabled": "False"},
                                                               "sendEmail": { "enabled": "False",
                                                                              "recipients": [ ]},
                                                               "sensitivity": 80},
                                              "schemaVersion": 1}},
               "XXXXXXXXXXXXYY": { "properties": { "antiFlicker": { "autoDefault": 1,
                                                                    "mode": 0},
                                                  "apiVersion": 1,
                                                  "autoUpdateEnabled": "True",
                                                  "capabilities": ["bridge"],
                                                  "claimed": "True",
                                                  "connectivity": [ { "connected": "True",
                                                                      "ipAddr": "192.168.1.179",
                                                                      "signalStrength": 4,
                                                                      "ssid": "sprinterland",
                                                                      "type": "wifi"}],
                                                  "hwVersion": "ABB1000r1.0",
                                                  "interfaceVersion": 2,
                                                  "mcsEnabled": "True",
                                                  "modelId": "ABB1000",
                                                  "olsonTimeZone": "America/New_York",
                                                  "state": "idle",
                                                  "swVersion": "2.0.1.0_278_341",
                                                  "timeSyncState": "synchronized",
                                                  "timeZone": "EST5EDT,M3.2.0,M11.1.0",
                                                  "updateAvailable": "None"},
                                  "states": {}}},
  "from": "XXXXXXXXXXXXX",
  "resource": "devices",
  "to": "XXXXXXXXXXXXX24993_web",
  "transId": "web!c989b294-b117-4e5e-8647-bb039d9ff8d6"}
```

