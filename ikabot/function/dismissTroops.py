#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import random
import re
import sys

from ikabot.config import *
from ikabot.helpers.gui import *
from ikabot.helpers.pedirInfo import getIdsOfCities, read
from ikabot.helpers.varios import (
    addThousandSeparator,
    decodeUnicodeEscape,
    wait,
)


CONFIRMATION_WORDS = [
    "anchor",
    "apple",
    "barracks",
    "captain",
    "cargo",
    "citizen",
    "column",
    "compass",
    "copper",
    "coral",
    "galley",
    "harbor",
    "island",
    "lantern",
    "marble",
    "olive",
    "palace",
    "pearl",
    "phalanx",
    "sailor",
    "shipyard",
    "silver",
    "sulfur",
    "temple",
    "victory",
]


def humanWait():
    """Random delay between server requests to simulate human behaviour"""
    wait(1, maxrandom=2)


def getGarrisonEditHtml(session, city_id, activeTab=None):
    """
    Parameters
    ----------
    session : ikabot.web.session.Session
    city_id : int
    activeTab : str | None

    Returns
    -------
    html : str
    """
    params = {
        "view": "garrisonEdit",
        "cityId": str(city_id),
        "backgroundView": "city",
        "currentCityId": str(city_id),
        "actionRequest": actionRequest,
        "ajax": "1",
    }
    if activeTab is not None:
        params["activeTab"] = activeTab
    data = session.post(params=params)
    data = json.loads(data, strict=False)
    return data[1][1][1]


def getGarrisonTabs(html):
    """
    Parameters
    ----------
    html : str

    Returns
    -------
    tabs : list[str]
    """
    tabs = []
    for tab in re.findall(r"\?view=garrisonEdit&activeTab=(\w+)", html):
        if tab not in tabs:
            tabs.append(tab)
    return tabs


def parseDismissableUnits(html):
    """
    Parameters
    ----------
    html : str

    Returns
    -------
    units : list[dict]
    """
    units = []
    blocks = html.split('<li class="unit ')[1:]
    for block in blocks:
        identifier = block.split(">", 1)[0].replace('"', "").strip()
        match = re.search(r"<h4>([^<]+)</h4>", block)
        if match is None:
            continue
        name = decodeUnicodeEscape(match.group(1).strip())
        match = re.search(r"maxValue:\s*(\d+)", block)
        if match is None:
            continue
        available = int(match.group(1))
        match = re.search(r'name="(\d+)"', block)
        if match is None:
            continue
        unit_id = match.group(1)
        units.append(
            {
                "id": unit_id,
                "name": name,
                "identifier": identifier,
                "available": available,
            }
        )
    return units


def getCategoryUnits(session, city_id, troops):
    """
    Parameters
    ----------
    session : ikabot.web.session.Session
    city_id : int
    troops : bool

    Returns
    -------
    (tab, units) : tuple
    """
    html = getGarrisonEditHtml(session, city_id)
    tabs = getGarrisonTabs(html)
    army_tabs = [tab for tab in tabs if "army" in tab.lower()]
    fleet_tabs = [tab for tab in tabs if "army" not in tab.lower()]
    if troops:
        if not army_tabs:
            return "army", parseDismissableUnits(html)
        tab = army_tabs[0]
        if tab != tabs[0]:
            html = getGarrisonEditHtml(session, city_id, activeTab=tab)
        return tab, parseDismissableUnits(html)
    else:
        if not fleet_tabs:
            return None, []
        tab = fleet_tabs[0]
        if tab != tabs[0]:
            html = getGarrisonEditHtml(session, city_id, activeTab=tab)
        return tab, parseDismissableUnits(html)


def readMultiSelection(total):
    """
    Reads a comma separated selection of numbers between 1 and total.
    'a' or 'all' selects every option.

    Parameters
    ----------
    total : int

    Returns
    -------
    selection : list[int]
    """
    while True:
        raw = str(read()).strip().lower()
        tokens = [token for token in re.split(r"[,\s]+", raw) if token]
        if not tokens:
            print("Invalid option")
            continue
        if "a" in tokens or "all" in tokens:
            return list(range(1, total + 1))
        try:
            numbers = {int(token) for token in tokens}
        except ValueError:
            print("Invalid option")
            continue
        if numbers and min(numbers) >= 1 and max(numbers) <= total:
            return sorted(numbers)
        print("Invalid option")


def dismissTroops(session, event, stdin_fd, predetermined_input):
    """
    Fires (dismisses) troops and/or ships from the user's cities

    Parameters
    ----------
    session : ikabot.web.session.Session
    event : multiprocessing.Event
    stdin_fd: int
    predetermined_input : multiprocessing.managers.SyncManager.List
    """
    sys.stdin = os.fdopen(stdin_fd)
    config.predetermined_input = predetermined_input
    try:
        banner()

        ids, cities = getIdsOfCities(session)

        print("Choose which cities you want to dismiss troops/ships in:")
        resources_abbreviations = {"1": "(W)", "2": "(M)", "3": "(C)", "4": "(S)"}
        longest_city_name_length = max(
            len(decodeUnicodeEscape(cities[city_id]["name"])) for city_id in ids
        )
        for i, city_id in enumerate(ids, start=1):
            city_name = decodeUnicodeEscape(cities[city_id]["name"])
            abbreviation = resources_abbreviations[
                str(cities[city_id]["tradegood"])
            ]
            padding = " " * (longest_city_name_length - len(city_name) + 2)
            print("({}) {}{}{}".format(i, city_name, padding, abbreviation))
        print("(a) All cities")
        print(
            "\nEnter numbers separated by comma or space (e.g.: 1,3), or 'a' to pick every city:"
        )
        selection = readMultiSelection(len(ids))
        selected_ids = [ids[index - 1] for index in selection]

        banner()
        print("(1) Troops")
        print("(2) Ships")
        troops = read(min=1, max=2, digit=True) == 1
        category = "troops" if troops else "ships"

        banner()
        print("Reading garrisons...\n")
        garrisons = {}
        for city_id in selected_ids:
            city_name = decodeUnicodeEscape(cities[city_id]["name"])
            print("  Reading {}...".format(city_name))
            session.get(city_url + str(city_id))
            humanWait()
            tab, units = getCategoryUnits(session, city_id, troops)
            garrisons[city_id] = {"city_name": city_name, "tab": tab, "units": units}
            humanWait()

        if all(len(garrison["units"]) == 0 for garrison in garrisons.values()):
            banner()
            print("No {} found in the selected cities.".format(category))
            enter()
            event.set()
            return

        types_by_identifier = {}
        for garrison in garrisons.values():
            for unit in garrison["units"]:
                types_by_identifier.setdefault(unit["identifier"], unit["name"])
        identifiers = list(types_by_identifier)

        banner()
        print(
            "Choose which {} to dismiss, comma separated lets you choose multiple:".format(
                category
            )
        )
        for i, identifier in enumerate(identifiers, start=1):
            print("({}) {}".format(i, types_by_identifier[identifier]))
        print("(a) All")
        selection = readMultiSelection(len(identifiers))
        chosen_identifiers = [identifiers[index - 1] for index in selection]

        banner()
        print("How many do you want to dismiss?\n")
        plan = []
        for city_id in selected_ids:
            garrison = garrisons[city_id]
            present_units = [
                unit
                for unit in garrison["units"]
                if unit["identifier"] in chosen_identifiers
            ]
            if not present_units:
                continue
            print("{}:".format(garrison["city_name"]))
            city_units = []
            for unit in present_units:
                amount = read(
                    msg="{} ({} available): ".format(
                        unit["name"], addThousandSeparator(unit["available"])
                    ),
                    min=0,
                    max=unit["available"],
                    digit=True,
                    empty=True,
                    default=0,
                    additionalValues=["all", "half"],
                )
                if amount == "all":
                    amount = unit["available"]
                elif amount == "half":
                    amount = unit["available"] // 2
                if amount > 0:
                    unit = dict(unit)
                    unit["amount"] = amount
                    city_units.append(unit)
            print("")
            if city_units:
                plan.append(
                    {
                        "city_id": city_id,
                        "city_name": garrison["city_name"],
                        "tab": garrison["tab"],
                        "units": city_units,
                    }
                )

        if not plan:
            banner()
            print("Nothing to dismiss.")
            enter()
            event.set()
            return

        banner()
        print("You are about to dismiss the following {}:\n".format(category))
        total = 0
        for entry in plan:
            print("{}:".format(entry["city_name"]))
            for unit in entry["units"]:
                print(
                    "  {}: {} (of {} available)".format(
                        unit["name"],
                        addThousandSeparator(unit["amount"]),
                        addThousandSeparator(unit["available"]),
                    )
                )
                total += unit["amount"]
        print("\nTotal {} to dismiss: {}".format(category, addThousandSeparator(total)))

        total_wipe = all(
            unit["amount"] == unit["available"]
            for entry in plan
            for unit in entry["units"]
        )

        if total_wipe:
            word = random.choice(CONFIRMATION_WORDS)
            print(
                "\nWARNING: this will dismiss ALL the selected {}. This cannot be undone.".format(
                    category
                )
            )
            confirmed = False
            while not confirmed:
                typed = read(msg='Type "{}" to confirm: '.format(word))
                if typed == word:
                    confirmed = True
                    continue
                retry = read(msg='Confirmation does not match. Try again? [y/N]')
                if retry.lower() != "y":
                    event.set()
                    return

        print("\nProceed? [y/N]")
        response = read(values=["y", "Y", "n", "N", ""])
        if response.lower() == "n":
            event.set()
            return

        print("")
        for entry in plan:
            print("Dismissing {} in {}...".format(category, entry["city_name"]))
            session.get(city_url + str(entry["city_id"]))
            humanWait()
            params = {
                "action": "CityScreen",
                "function": "fireUnits" if troops else "fireShips",
                "cityId": str(entry["city_id"]),
                "activeTab": entry["tab"],
                "backgroundView": "city",
                "currentCityId": str(entry["city_id"]),
                "templateView": "garrisonEdit",
                "actionRequest": actionRequest,
                "ajax": "1",
            }
            for unit in entry["units"]:
                params[unit["id"]] = unit["amount"]
            session.post(params=params)
            humanWait()

        print("\n{} were dismissed.".format(category.capitalize()))
        enter()
        event.set()
    except KeyboardInterrupt:
        event.set()
        return
