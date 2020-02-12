# Hue Emulation for Home Assistant

Convert your Home Assistant instance to a fully functional Philips HUE bridge!
Control all lights connected to your Home Assistant box with HUE compatible apps/devices like the official Hue app, Hue essentials and Philips Ambilight+Hue etc.

## Features
- Rooms will be auto created based on areas created in Home Assistant.
- All lights will be supported with full functionality.
- For now only support for light entities as it's primary use case is to give you HUE control over your HASS lights.
- Allow you to create your own HUE groups and scenes.
- Secured connection and authentication flow (unlike default emulated hue component in hass).
- Fully emulates a "V2" HUE bridge.
- Loosely coupled with HomeAssistant over low-latency websockets.
- Experimental support for HUE Entertainment (see below).

## Use cases
- You or your family like to use the HUE app for control over ALL your lights, so even non-Zigbee/HUE lights...
- You've replaced the Official HUE bridge with ZHA/zigbee2mqtt and you miss some original HUE features.
- You'd like to sync your lights with your TV/game (e.g. HUE Sync, Ambilight+HUE).

## How ro run/install/use this thing ?
- Run it manually, just download the source code and install the requirements. run.py needs some self-explained params.
- Supervisor add-on, just click install and it will work automagically.
- Once started, it will automaically be available as a HUE bridge on your network.

## How to connect to the virtual bridge ?
- From your app/device (for example the official HUE app) search for HUE bridges.
- Once the bridge is found by your app/device, there's a notification sent to Home Assistant if you want to enable pairing mode (same as pressing the physical button on the real bridge). It will show you a message in the notification area WITHIN Home Assistant.
- Once you enabled pairing mode, your app has 30 seconds to connect.


## Backlog / TODO / Ideas:
- Support other device types, like switches ?
- Read HASS scenes to HUE ?
- Create HUE scenes, push to HASS scenes ?
- Support for routines / automations ?

Please use the Github issue tracker for feature requests (including motivation) and off course for reporting any issues you may find!

