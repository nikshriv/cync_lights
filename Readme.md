Cync Lights Custom Integration
============
Control and monitor the state of your Cync Light switches, bulbs, and plugs. This integration is no longer dependent on Google Home. The integration requires that you have at least one Wifi connected switch, bulb or plug in your system to allow for control (including bluetooth only devices). I have also included access to the built in motion sensors and ambient light sensors which should enable you to automate your lights better than with the Cync app. I have not been able to find a way to support bluetooth Wireless motion sensors. If anyone has devices that don't work with this integration (aside from thermostats and cameras which I don't plan to support), let me know by starting an issue and use this python program to download your device information and post it:  https://github.com/nikshriv/cync_data 

## Installation
1. Navigate to HACS and add a custom repository. 
   URL: https://github.com/nikshriv/cync_lights 
   Category: Integration
2. Install and restart HA
3. Close your browser and reopen it, then Navigate back to your HA instance. (This is an issue with HACs)
4. Go to the HA Integrations page and add the Cync integration by pushing the "Add Integration" button. Sign in with your Cync email and password.
5. Select the rooms, individual switches, motion sensors, and ambient light sensors you would like to include
