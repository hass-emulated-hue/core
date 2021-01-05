# Hue Emulation for Home Assistant

Convert your Home Assistant instance to a fully functional Philips HUE bridge!
Control all lights connected to your Home Assistant box with HUE compatible apps/devices like the official Hue app, Hue essentials and Philips Ambilight+Hue etc.

## Features
- Your Areas in Home Assistant will be auto created as rooms in the HUE app.
- All your Home Assistant lights will be supported with full functionality.
- Allow you to create your own HUE groups and scenes.
- Secured connection and authentication flow (unlike default emulated hue component in hass).
- Fully emulates a "V2" HUE bridge.
- Loosely coupled with HomeAssistant over low-latency websockets.
- Experimental support for HUE Entertainment (see below).

## Use cases
- You or your family like to use the HUE app for control over ALL your lights, so even non-Zigbee/HUE lights...
- You've replaced the Official HUE bridge with ZHA/zigbee2mqtt and you miss some original HUE features.
- You'd like to sync your lights with your TV/game (e.g. HUE Sync, Ambilight+HUE).

## How to run/install/use this thing ?
- Add the custom repository to the Home Assistant supervisor's add-on store: 
  https://github.com/hass-emulated-hue/hassio-repo
- Install the Emulated HUE addon from the addon-store
- Start the newly installed addon and it will work instantly

Once started, it will be available as a HUE bridge on your network.

## How to connect to the virtual bridge ?
- From your app/device (for example the official HUE app) search for HUE bridges.
- Once the bridge is found by your app/device, there's a notification sent to Home Assistant if you want to enable pairing mode (same as pressing the physical button on the real bridge). It will show you a message in the notification area WITHIN Home Assistant.
- Once you enabled pairing mode, your app has 30 seconds to connect.

## Important notes
- This virtual bridge runs at HTTP port 80 and HTTPS port 443 on your local network. These ports can not be changed as the HUE infrastructure requires them to be at these defaults.
- If you're running the previous/legacy emulated HUE component in HASS, make sure to disable it first.
- Remote Connection support is not available. This thing is local only (which is actually a good thing perhaps?).

## Notes on Philips HUE Entertainment API support
The [Hue Entertainment API](https://developers.meethue.com/develop/hue-entertainment/philips-hue-entertainment-api/) supports a communication protocol which allows a light streaming functionality with the Philips Hue System. Using this protocol, it is possible to stream lighting effects to multiple lights in parallel with a high update rate. It's used for new Ambilight+HUE TV's and the HUE Sync app on PC and Mac.

We've created a (highly experimental!) python implementation of this streaming protocol that actually works pretty well altough not as good as it's original. While packets are indeed live streamed (at a rate between 25-50 messages per second) to our virtual bridge, we unpack them and convert them to commands the light implementations can understand at a more sane rate level (throttling). We choose some settings which result in a nice effect with not too much delay without completely overloading a platform. This means that the Entertainment mode will work with **any light** connected to Home Assistant. Cool! 

The next step we have in mind is, if you own official HUE lights connected to ZHA, to forward the special Entertainment packets into the Zigbee mesh, resulting in the real streaming experience (realtime effects with no delay). 


## Backlog / TODO / Ideas:
- Support other device types, like switches ?
- Forward Entertainment UDP packages to Zigbee mesh for Official HUE lights that natively support the feature.
- Read HASS scenes to HUE ?
- Create HUE scenes, push to HASS scenes ?
- Support for routines / automations ?

Please use the Github issue tracker for feature requests (including motivation) and off course for reporting any issues you may find!


## FAQ


#### I do not want to have all my Home Assistant lights imported to HUE
By default all your Home Assistant lights and areas will be imported to get you started quickly but you can customize this.
In your Home Assistant config directory you'll find a folder for emulated_hue witha file called emulated_hue.json.
In that file you can disable lights or groups by setting enabled to false.
You can also delete a light in the HUE app. That will also mark the light as disabled.



#### When I enable Entertainment mode my light/platform gets overwhelmed with commands

Entertainment mode is heavy. It will send multiple commands per second to each light. If you hardware can't cope up with this we have an advanced little setting hidden in the above mentioned emulated_hue.json config file called "entertainment_throttle". Set a value (in milliseconds) to throttle requests to this light. A good value to start with is 500. Remember to stop the addon before you start editing this file.



#### I run Home Assistant manually without all the supervisor stuff, can I still run this thing ?
Sure, just run the docker image manually. We'll provide you with some sample run commands soon.
