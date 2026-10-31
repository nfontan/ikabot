# Features

Ikabot provides automation tools for account maintenance, city management, resource logistics, alerts, military actions, piracy, world tools, and utility tasks.

## Account & Session

| Feature | Description |
|---|---|
| Daily login | Logs into the account regularly and collects daily bonuses when available, including ambrosia fountain rewards. |
| Vacation mode | Enables vacation mode and closes Ikabot. |
| Ikabot Web Server | Starts a local web interface so you can use Ikariam through Ikabot's active session. |
| Import / export cookie | Lets you reuse Ikabot cookies in your browser or another Ikabot instance. |
| Manage running tasks | Lists the running Ikabot tasks, stops them, and shows or saves their config to start them again from the [command line](https://github.com/Ikabot-Collective/ikabot/wiki/Command-Line-Tasks). |
| Logs | Shows Ikabot logs and can upload them for troubleshooting. |
| Update Ikabot | Shows how to update Ikabot. |
| Exit | Closes the main menu while configured background tasks continue running. |

## City & Resources

| Feature | Description |
|---|---|
| Account status | Shows city information such as buildings, resources, wine duration, and other account data. |
| Construction list | Plans building upgrades and can move resources automatically from selected cities when needed. |
| Construct building | Builds or upgrades a selected building. |
| Send resources | Sends resources from one city to another, including repeated trips when needed. |
| Distribute resources | Distributes resources between cities, either evenly or from producer cities to non-producer cities. |
| Consolidate resources | Moves excess resources from selected source cities into a destination city while keeping configured limits. |
| Marketplace | Buys resources from the cheapest offers first, or sells resources and keeps offers updated. |
| Donate | Donates wood manually or automatically to forests and luxury resource mines. |
| Research | Starts an available research. |

## Workers & City Layout

| Feature | Description |
|---|---|
| Set production workers | Adjusts wood and/or luxury resource workers across selected cities. |
| Set academy workers | Adjusts academy workers across selected cities. |
| Tavern manager | Adjusts tavern wine consumption to manage city satisfaction. |
| Reorganize city buildings | Reorders city buildings to match a selected template city layout. |

## Monitoring & Alerts

| Feature | Description |
|---|---|
| Attack alerts | Sends Telegram alerts when incoming attacks are detected. |
| Wine alerts | Sends Telegram alerts when a city is close to running out of wine. |
| Monitor islands | Sends alerts when cities appear or disappear on monitored islands. |
| See movements | Shows incoming and outgoing movements such as attacks and transports. |

## Military

| Feature | Description |
|---|---|
| Train army | Trains troops or fleets, including large queues and multi-step training plans. |
| Send troops / ships | Moves troops or ships between cities or gathers them in one place. |
| Upgrade army | Starts workshop upgrades for troops or ships when available. |
| Attack barbarians | Runs a single barbarian attack flow. |
| Auto grind barbarians | Automates repeated barbarian attacks and can collect the resulting resources. |
| Activate miracle | Activates available miracles repeatedly when configured. |
| Activate Shrine | Manages Shrine of Olympus favor and god activation/donation flows. |

## Piracy & Captcha

| Feature | Description |
|---|---|
| Auto-Pirate | Runs piracy missions automatically and attempts captcha resolution when needed. |
| Captcha resolver configuration | Lets you choose the captcha resolver used by Auto-Pirate, such as default, custom, 9kw.eu, or Telegram. |

## World Tools

| Feature | Description |
|---|---|
| Dump & search world | Creates a world dump and lets you search it later for players, cities, islands, miracles, and resource levels. |
| Monitor islands | Watches selected islands and reports city changes. |
| Configure proxy | Configures a proxy for Ikabot requests, except lobby login requests. |

## Telegram & Utilities

| Feature | Description |
|---|---|
| Telegram data | Sets or updates Telegram notification settings. |
| Message Telegram Bot | Sends a test message to the configured Telegram bot. |
| Load custom Ikabot module | Adds, removes, or runs custom Python modules from local files or URLs. |
| Developer Data | Displays troubleshooting information such as install path, API address, host, URL base, and cookies. |