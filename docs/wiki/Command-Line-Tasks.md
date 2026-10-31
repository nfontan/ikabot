# Command-line tasks

Ikabot tasks can be started from the command line, without going through the menu. This is useful for scripts, scheduled jobs (cron, Windows Task Scheduler) and Docker.

```bash
ikabot --task=alertAttacks --config='{"minutes": 20}'
```

The command answers with one line of JSON and returns right away. The task keeps running in the background, exactly like a task started from the menu.

The options and the values each task accepts are listed in [CLI Task Reference](https://github.com/Ikabot-Collective/ikabot/wiki/CLI-Task-Reference).

## Options

| Option | Description |
|---|---|
| `--task=NAME` | The task to start, e.g. `alertAttacks`. The name is not case sensitive. |
| `--config=JSON` | The task's settings, as a JSON object. Use `--config=@file.json` to read them from a file. Settings that are left out take their default value. |
| `--batch=JSON` | Starts several tasks at once, see [Starting several tasks](#starting-several-tasks). Cannot be combined with `--task` or `--config`. |
| `--email=EMAIL` | The saved account to use. Not needed when only one account is saved. |
| `--world=WORLD` | The world, e.g. `s301-en`, `s301` or the world name. Not needed when the account plays only one world. |
| `--player=NAME` | The in-game player name. Needed when the lobby has several accounts on the same world. |
| `--server=LANG` | The server language (e.g. `en`, `de`), when `--world` is ambiguous. |
| `--help` | Shows the options. |

The account must have been logged in interactively at least once, so that its session is saved. The CLI reuses the saved session and never asks for a password.

### Choosing the account

- With an ikabot menu open, a task with no `--email`, `--world` or `--player` runs on the menu's account. When several menus are open, this is the first one that was opened.
- Otherwise the account is picked from the saved session with the options above. If more than one account matches, the command answers with an error that lists them, e.g. `Please specify --world and/or --player (available: s301-en (Alpha) - PlayerOne, s301-en (Alpha) - PlayerTwo)`.

## The answer

The command prints one line of JSON:

```json
{"status": "ok", "pid": 1234, "task": "alertAttacks", "email": "", "world": "s301-en", "username": "PlayerOne", "host_pid": 5678}
```

or, when the task could not be started:

```json
{"status": "error", "error": "minutes must be at least 3, got 2", "task": "alertAttacks"}
```

The exit code is `0` when every task started and `1` otherwise, so scripts can check it.

Most tasks check their settings before they start (invalid values, cities that are not yours, a busy port, a missing Telegram/Discord bot...) and report the problem in the answer. Problems that appear once a task is already running are reported like for any other task: in the log and through the Telegram/Discord bot.

## Writing the config

- The config is a JSON object: keys in double quotes, `true`/`false` for yes/no, lists in `[ ]`.
- City and island ids can be written as numbers (`7665`) or as text (`"7665"`).
- **Windows PowerShell** removes the double quotes inside arguments. Put the config in a file and use `--config=@file.json`. To create the file:

```powershell
Set-Content -Encoding ascii alert.json '{"minutes": 20}'
ikabot --task=alertAttacks --config=@alert.json
```

  Use `-Encoding ascii`: with `utf8`, PowerShell 5.1 adds a marker at the start of the file that breaks the JSON.

## Saving the config of a running task

In the menu, **Options / Settings > Manage running tasks** lists the running tasks:

| Option | What it does |
|---|---|
| `(c)` → pick a task | Shows the task's config. `(s)` saves it as a `--config` file and prints the command to start it again. |
| `(a)` | Saves the configs of all running tasks as one `--batch` file and prints the command to start them all again. |

The files are saved in the `tasks` folder of the ikabot directory, named after the player, the world and the task:

- `~/.ikabot/tasks/` on Linux and macOS, `C:\Users\<user>\.ikabot\tasks\` on Windows;
- `PlayerOne_s301-en_alertAttacks.json` for one task, `PlayerOne_s301-en_all.json` for all of them.

Example of a command printed after saving one task:

```bash
ikabot --world=s301-en --player="PlayerOne" --task=alertAttacks --config="@/home/user/.ikabot/tasks/PlayerOne_s301-en_alertAttacks.json"
```

The same config can be used on another account of the lobby by changing `--player`.

## Starting several tasks

`--batch` takes a list of tasks, as JSON or as a file:

```json
[
  {"task": "alertAttacks", "player": "PlayerOne", "world": "s301-en", "config": {"minutes": 20}},
  {"task": "alertAttacks", "player": "PlayerTwo", "world": "s301-en", "config": {"minutes": 30}},
  {"task": "webServer", "player": "PlayerOne", "world": "s301-en"}
]
```

```bash
ikabot --batch=@tasks.json
```

- Each entry has a `task` and may have `config`, `email`, `world`, `server` and `player`.
- `--email`, `--world`, `--server` and `--player` given on the command line replace the values of every entry. For example, `ikabot --batch=@tasks.json --player=PlayerTwo` starts all the tasks on PlayerTwo.
- The answer is a list with one result per task.

## Where the tasks run

- **With an ikabot menu open**, the command hands the tasks to the menu (the first one opened, if there are several) and they run under it, like the ones started from the menu. They show up in **Manage running tasks**. A menu started with pre-defined input does not receive tasks.
- **Without a menu open**, the command starts the tasks itself, logs in with the saved session, and returns. The tasks keep running in the background.
- On Windows, tasks are tied to the console window they were started from: closing that window stops them. Scheduled tasks and Docker are not affected.
- After updating ikabot, restart the menus that are open: a menu that was opened before the update keeps running the old code for the tasks it receives.

## Pre-defined input

Starting ikabot with [pre-defined input](https://github.com/Ikabot-Collective/ikabot/wiki/Getting-Started#pre-defined-input) (the answers to the menu as arguments) still works as before. The options above are only used when an argument starts with `--`.
