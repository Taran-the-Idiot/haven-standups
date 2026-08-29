create a slackbot that pings a user group every morning and then sends a ping in the thread to every person who has not replied yet. this is a daily standup type thing. look at the existing code to see what the base it off of.

The bot can be added to any channel, however a channel manager is the only person who can activate it and they must use the /activate-standup command to pull up a menu where they can enter their timezone and the user group for the bot to ping in that respective channel.

The channel manager can also use the /reset-standup command to stop the standup bot from running in the channel or wipe the activation settings. 

please have the bot set to ping every day at 8am in the local timezone for each channel.

