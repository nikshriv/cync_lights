Cync Lights Custom Integration
============
Control and monitor the state of your Cync Light switches. This integration no longer requires the Cync Lights Addon. Follow the installation instructions below. 

With this integration, I use Google Assistant to control the switches, so you will need to link your Cync account to Google Home.  

## Installation
1. Navigate to HACS and add a custom repository. 
   URL: https://github.com/nikshriv/cync_lights 
   Category: Integration
2. Install and restart HA
3. Create a Google account or use your own (I recommend creating a new account)
4. Download and install the Google Home app on your mobile device and link your Cync account to Google Home. No need to add these switches to a room. 
5. Create a Google assistant developer project by following the instructions at this link: https://developers.google.com/assistant/sdk/guides/service/python/embed/config-dev-project-and-account
6. Be sure to add your Google account email address under the "Test Users" section
7. Make sure that once when you configure the "Oauth Consent Screen: that you select "Publish App" under Publishing status
8. At the end of the Developer Project configuration page, click "Register the Device Model" and enter model information (it doesn't matter what you enter here)
9. Go to the "Manage User Acess" link from the upper right corner setting menu.
10. From your Google Cloud console, go to the Dashboard for your project
11. From the upper right menu, select APIs and Services
12. Select Credentials from the upper right menu
13. Select the "Web client" that was created for you by Google with the same client ID as your project and edit the credentials.
14. Add your home assistant address to "redirect uris" with path /googleauth and save
15. Download the credentials file from the "Web client" and save it somewhere safe.
16. Install the Cync Room Lights integration
17. When prompted for your client secret, copy and paste the entire contents of your previously saved Oauth2.0 credentials
18. Follow the instructions from Google to authorize.
19. The integration should now work.

