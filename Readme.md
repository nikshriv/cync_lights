Cync Lights Custom Integration
============
Control and monitor the state of your Cync Light switches, bulbs, fan switches and plugs. This integration is no longer dependent on Google Home. The integration requires that you have at least one Wifi connected light switch, bulb, fan switch, or plug in your system to allow for control (including bluetooth only devices). The integration will not work if you have only bluetooth devices without a WiFi connected device in your system. 

I have also included access to the built in motion sensors and ambient light sensors for 4-wire switches ONLY. Unfortunately, it appears that the 3-Wire (no neutral wire) motion and light sensors do not report state information to the Cync server, so motion and light sensors are not supported for this particular device type. I also cannot find a way to support the Wireless Motion Sensor as it seems to only comminucate on the bluetooth mesh network created by these devices and not over Wifi. 

If anyone has devices that don't work with this integration (aside from thermostats and cameras which I don't plan to support), let me know by starting an issue and use this python program to download your device information and post it (after redacting any sensitive information):  https://github.com/nikshriv/cync_data 

## Installation
1. Navigate to HACS and add a custom repository. 
   URL: https://github.com/nikshriv/cync_lights 
   Category: Integration
2. Install and restart HA
3. Close your browser and reopen it, then Navigate back to your HA instance. (This is an issue with HACs)
4. Go to the HA Integrations page and add the Cync integration by pushing the "Add Integration" button. Sign in with your Cync email and password. Make sure to use the primary account as the integration does not work with secondary Cync accounts.
5. Select the rooms, individual switches, motion sensors, and ambient light sensors you would like to include

https://www.buymeacoffee.com/nikshriv
