Cync Lights Custom Integration (queueing fork)
============
This is a fork of [nikshriv/cync_lights](https://github.com/nikshriv/cync_lights) that paces the commands it sends to the Cync cloud. The stock integration sends every command the moment Home Assistant asks for it and resends unacknowledged commands every 0.5 s, so a scene or group that changes many lights at once can send dozens of packets in a few seconds. With a large setup that overloads the Cync server: commands are dropped, lights respond minutes late or not at all, and the connection resets.

## What this fork changes
All changes are in `custom_components/cync_lights/cync_hub.py`. The integration domain is still `cync_lights`, so switching from upstream keeps existing entities, automations and dashboards.

- **Send queue.** Every packet (commands, retries and pings) goes through one queue and leaves at least 0.25 s after the previous one. The gap is the `SEND_SPACING` constant at the top of the file.
- **Slower retries.** An unacknowledged command is resent every 1.5 s, for up to 6 s (4 attempts), instead of every 0.5 s for up to 5 s (10 attempts).
- **Retry timer starts after sending.** The wait for an acknowledgement includes the time a packet spends in the queue, so a backlog does not set off extra retries.

A scene that changes 11 lights now takes about 3 seconds to send instead of going out in one burst.

## Upstream description
Control and monitor the state of your Cync Light switches, bulbs, fan switches and plugs. This integration is no longer dependent on Google Home. The integration requires that you have at least one Wifi connected light switch, bulb, fan switch, or plug in your system to allow for control (including bluetooth only devices). The integration will not work if you have only bluetooth devices without a WiFi connected device in your system. 

I have also included access to the built in motion sensors and ambient light sensors for 4-wire switches ONLY. Unfortunately, it appears that the 3-Wire (no neutral wire) motion and light sensors do not report state information to the Cync server, so motion and light sensors are not supported for this particular device type. I also cannot find a way to support the Wireless Motion Sensor as it seems to only comminucate on the bluetooth mesh network created by these devices and not over Wifi. 

If anyone has devices that don't work with this integration (aside from thermostats and cameras which I don't plan to support), let me know by starting an issue and use this python program to download your device information and post it (after redacting any sensitive information):  https://github.com/nikshriv/cync_data 

## Installation
If the upstream integration is already installed, remove the upstream repository from HACS first (this leaves your configured integration in place), then:

1. Navigate to HACS and add a custom repository. 
   URL: https://github.com/Woodhead02/cync_lights_queueing 
   Category: Integration
2. Install and restart HA
3. Close your browser and reopen it, then Navigate back to your HA instance. (This is an issue with HACs)
4. Go to the HA Integrations page and add the Cync integration by pushing the "Add Integration" button. Sign in with your Cync email and password. Make sure to use the primary account as the integration does not work with secondary Cync accounts.
5. Select the rooms, individual switches, motion sensors, and ambient light sensors you would like to include

https://www.buymeacoffee.com/nikshriv
