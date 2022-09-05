Cync Lights Custom Integration
============
Control and monitor the state of your Cync Light switches. This integration is no longer dependent on Google Home. The integration requires that you have at least one Wifi connected switch or plug in your system to allow for control (including bluetooth only devices). I have also included access to the built in motion sensors on wired switches that include one. I have not been able to find a way to support bluetooth Wireless motion sensors. Finally, I have updated device numbers for the newest bulbs, but if anyone has switches or bulbs that don't work with this integration, let me know by starting an issue and use this python program to download your device information and post it:  https://github.com/nikshriv/cync_data 

## Installation
1. Navigate to HACS and add a custom repository. 
   URL: https://github.com/nikshriv/cync_lights 
   Category: Integration
2. Install and restart HA
3. Install the integration and sign in with your Cync credentials
4. Select the rooms, individual switches, and motion sensors you would like to include
