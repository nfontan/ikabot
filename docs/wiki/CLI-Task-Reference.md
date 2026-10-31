# CLI task reference

The settings each task accepts when it is started from the command line. See [Command-line tasks](https://github.com/Ikabot-Collective/ikabot/wiki/Command-Line-Tasks) for how to start them.

Settings without a default are required. The examples use bash quoting; on Windows PowerShell put the config in a file and use `--config=@file.json`.

| Task | Menu entry | Needs a config |
|---|---|---|
| [`alertAttacks`](#alertattacks) | Alerts / Notifications > Alert attacks | no |
| [`alertLowWine`](#alertlowwine) | Alerts / Notifications > Alert wine running out | yes |
| [`activateShrine`](#activateshrine) | Activate Shrine | yes |
| [`consolidateResources`](#consolidateresources) | Consolidate resources | yes |
| [`searchForIslandSpaces`](#searchforislandspaces) | Dump / Monitor world > Monitor islands | yes |
| [`webServer`](#webserver) | Ikabot Web Server | no |

The other tasks are being adapted. Until then they can be started with the config saved from **Manage running tasks**, but they do not check it before starting.

---

## alertAttacks

Checks for incoming attacks and sends an alert to Telegram/Discord for each new one. From Telegram, answering `<pid>:1` to the alert puts the account in vacation mode.

| Setting | Type | Default | Values |
|---|---|---|---|
| `minutes` | number | `20` | How often to check, in minutes. At least `3`. |

Needs a Telegram or Discord bot set up (Options / Settings > Notifications).

```bash
ikabot --task=alertAttacks
ikabot --task=alertAttacks --config='{"minutes": 10}'
```

Status in Manage running tasks: `Every 20 min, last check 14:32`, or `Every 20 min, check failed at 14:32`.

## alertLowWine

Alerts when a city with a tavern will run out of wine in less than the given hours, and can send wine to it from the wine-producing city with the most wine. Checks every 60 minutes.

| Setting | Type | Default | Values |
|---|---|---|---|
| `hours` | number | — | Alert when the wine lasts less than this many hours. At least `1`. |
| `auto_transfer` | yes/no | `false` | Send wine automatically to the city that is running out. Accepts `true`/`false` or `"y"`/`"n"`. |
| `transfer_amount` | number | `0` | Wine to send each time. At least `1` when `auto_transfer` is on. |

Needs a Telegram or Discord bot set up.

```bash
ikabot --task=alertLowWine --config='{"hours": 6}'
ikabot --task=alertLowWine --config='{"hours": 6, "auto_transfer": true, "transfer_amount": 5000}'
```

Status: `Every 60 min, last check 14:32`.

## activateShrine

Activates gods at the Shrine of Olympus. Each god costs 100 favor; when there is not enough favor, the task waits and tries again every 3 hours.

| Setting | Type | Default | Values |
|---|---|---|---|
| `godids` | list of numbers | — | The gods to activate: `1` Pan (wood), `2` Dionysus (wine), `3` Tyche (marble), `4` Plutus (gold), `5` Theia (crystal), `6` Hephaestus (sulfur). |
| `mode` | number | — | `1` activate them a number of times in a row, `2` activate them again every 72 hours, `3` both: a number of times in a row, then every 72 hours. |
| `times` | number | `0` | How many times in a row, from `1` to `10`. Not used in mode `2`. |

One of your cities must have the Shrine of Olympus.

```bash
# Dionysus and Plutus, once
ikabot --task=activateShrine --config='{"godids": [2, 4], "mode": 1, "times": 1}'
# Pan, every 72 hours
ikabot --task=activateShrine --config='{"godids": [1], "mode": 2}'
```

Status: `Activated Dionysus, Plutus @2026-10-31_14-32-05, current favor: 340`, or `Not enough favor @..., re-trying in 3h.`

## consolidateResources

Every few hours, sends the resources above a limit from the source cities to a destination city.

| Setting | Type | Default | Values |
|---|---|---|---|
| `sourceCityIds` | list of city ids | — | The cities to send resources from. Must be your cities. The destination is removed from this list. |
| `destinationCityId` | city id | — | The city that receives the resources. Must be one of your cities. |
| `limits` | list of 5 numbers | — | How much wood, wine, marble, crystal and sulfur to keep in each source city. `-1` keeps all of that resource (nothing is sent). |
| `intervalInHours` | number | `1` | Hours between shipments. At least `1`. |
| `shipType` | number | `1` | `1` trade ships, `2` freighters, `3` both. |

If a city id is not yours, the error lists your cities with their ids:
`destinationCityId 1 is not one of your cities. Your cities: 1111 (Alpha), 2222 (Beta), ...`

```bash
# keep 100,000 wood and 50,000 marble in each source city, send everything above, every 2 hours
ikabot --task=consolidateResources --config='{"sourceCityIds": [1111, 2222], "destinationCityId": 3333, "limits": [100000, -1, 50000, -1, -1], "intervalInHours": 2}'
```

Status: `Sent 120,000 resources from Alpha, Beta -> Gamma | Total sent: 480,000 | Next shipment at ...`

## searchForIslandSpaces

Watches islands and sends a Telegram/Discord message when a city appears or disappears on them, and optionally when a fight starts or stops in a city. The first search only records how the islands are; messages are sent from the second search on, when something changed.

| Setting | Type | Default | Values |
|---|---|---|---|
| `time` | number | — | Minutes between two searches. At least `3`. |
| `islandList` | list | all islands with one of your cities | Island ids or `"X:Y"` coordinates. |
| `fights` | yes/no | `false` | Also report fights. Accepts `true`/`false` or `"y"`/`"n"`. |

Needs a Telegram or Discord bot set up.

```bash
# all your islands, every 30 minutes
ikabot --task=searchForIslandSpaces --config='{"time": 30}'
# two islands by coordinates, every 3 minutes, with fights
ikabot --task=searchForIslandSpaces --config='{"time": 3, "islandList": ["50:60", "51:62"], "fights": true}'
```

Status: `Checked islands [50:60,51:62] @ 14-32-05`.

## webServer

Starts the Ikabot web server, to play through Ikabot's session from a browser.

| Setting | Type | Default | Values |
|---|---|---|---|
| `port` | number | see below | The port to listen on, from `1` to `65535`. |
| `local_network_ip` | text | detected | The local network address shown in the status, for opening the server from another device. |

Without a `port`, the server uses `IKABOT_WEB_PORT` when it holds a free port, otherwise a port derived from the account (between 43000 and 44999, the same one the menu uses). `IKABOT_WEB_PORT=ask` cannot ask from a task, so it also uses the derived port.

The task needs `flask`, and the port must be free.

```bash
ikabot --task=webServer
ikabot --task=webServer --config='{"port": 8080}'
# {"status": "error", "error": "port 8080 is already in use", "task": "webServer"}
```

Status: `running on http://127.0.0.1:43280 and http://192.168.0.10:43280`.
