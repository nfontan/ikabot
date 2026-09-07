#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
from decimal import *

from ikabot.config import *
from ikabot.function.autoPirate import getPirateFortressPoints
from ikabot.helpers.getJson import getCity
from ikabot.helpers.gui import *
from ikabot.helpers.market import getGold
from ikabot.helpers.naval import *
from ikabot.helpers.pedirInfo import *
from ikabot.helpers.resources import *
from ikabot.helpers.varios import *

getcontext().prec = 30

resources_abbr = {"1": "(W)", "2": "(M)", "3": "(C)", "4": "(S)"}

CACHE_FILE = os.path.join(os.path.expanduser("~"), ".ikabot_getstatus_cache.json")


def parseCityProduction(html, typeGood):
    resource_search_pool = {
        1: "js_GlobalMenu_production_wine",
        2: "js_GlobalMenu_production_marble",
        3: "js_GlobalMenu_production_crystal",
        4: "js_GlobalMenu_production_sulfur",
    }
    production_pattern = r'<td id="{}"[^>]*>\s*([\d.,\s]+)\s*</td>'

    def clean_number(num_str):
        return re.sub(r'[^\d]', '', num_str)

    wood_match = re.search(
        production_pattern.format("js_GlobalMenu_resourceProduction"), html
    )
    luxury_match = re.search(
        production_pattern.format(resource_search_pool[typeGood]), html
    )
    if not wood_match or not luxury_match:
        return None, None
    return int(clean_number(wood_match.group(1))), int(
        clean_number(luxury_match.group(1))
    )


def formatBuildingLevel(level, isBusy):
    lvl = str(level)
    if level < 10:
        lvl = " " + lvl
    if isBusy:
        lvl += "+"
    return lvl


def displayBuildingTable(city_names, ids, city_buildings):
    by_name = {}
    for cid in ids:
        for (name, level, isBusy, pos) in city_buildings[cid]:
            by_name.setdefault(name, {}).setdefault(cid, []).append((level, isBusy, pos))
    building_names = sorted(by_name)
    if not building_names:
        print("No buildings found.")
        return

    cells = {}
    for name in building_names:
        name_cells = {}
        for cid in ids:
            entries = by_name[name].get(cid)
            if entries is None:
                name_cells[cid] = "-"
            else:
                name_cells[cid] = ",".join(
                    formatBuildingLevel(level, isBusy).strip()
                    for (level, isBusy, pos) in entries
                )
        cells[name] = name_cells

    def city_width(cid):
        width = max(15, len(city_names[cid]))
        for name in building_names:
            width = max(width, len(cells[name][cid]))
        return width

    widths = {cid: city_width(cid) for cid in ids}

    try:
        term_width = os.get_terminal_size().columns
    except OSError:
        term_width = 120

    label_fixed = 26
    available = term_width - label_fixed
    chunks = []
    chunk = []
    used = 0
    for cid in ids:
        w = widths[cid] + 1
        if chunk and used + w > available:
            chunks.append(chunk)
            chunk = []
            used = 0
        chunk.append(cid)
        used += w
    if chunk:
        chunks.append(chunk)

    for idx, page in enumerate(chunks, 1):
        col_width = max(widths[cid] for cid in page)
        header = "{:<25}".format("Building")
        for cid in page:
            header += "|{:>{}}".format(city_names[cid], col_width)
        print(header)
        print("-" * len(header))

        for name in building_names:
            row = "{:<25}".format(decodeUnicodeEscape(name)[:25])
            for cid in page:
                row += "|{:>{}}".format(cells[name][cid], col_width)
            print(row)

        print("-" * len(header))

        if idx < len(chunks):
            print(
                "\n({}/{}) Building levels - press Enter to continue".format(
                    idx, len(chunks)
                )
            )
            enter()


def displayBuildingList(city_names, ids, city_buildings, city_tradegoods):
    any_data = False
    for cid in ids:
        buildings = city_buildings[cid]
        if not buildings:
            continue
        any_data = True
        abbr = resources_abbr.get(str(city_tradegoods[cid]), "")
        print("{} {}:".format(city_names[cid], abbr))
        for (name, level, isBusy, pos) in buildings:
            print(
                "  {}: Lv{} (pos {})".format(
                    decodeUnicodeEscape(name),
                    formatBuildingLevel(level, isBusy).strip(),
                    pos + 1,
                )
            )
        print()

    if not any_data:
        print("No buildings found.")


def showCityDetail(city, city_header, wood_prod, good_prod, color_arr):
    banner()
    print(
        "\033[1m{}{}{}".format(
            color_arr[int(city_header["producedTradegood"])],
            city["cityName"],
            color_arr[0],
        )
    )

    resources = city["availableResources"]
    storageCapacity = city["storageCapacity"]
    citizens = city["freeCitizens"]
    housing_space = int(city_header["currentResources"]["population"])

    color_resources = []
    for i in range(len(materials_names)):
        if resources[i] == storageCapacity:
            color_resources.append(bcolors.RED)
        else:
            color_resources.append(bcolors.ENDC)

    print("Population:")
    print(
        "{}: {} {}: {}".format(
            "Housing space",
            addThousandSeparator(housing_space),
            "Citizens",
            addThousandSeparator(citizens),
        )
    )
    print("Storage: {}".format(addThousandSeparator(storageCapacity)))
    print("Resources:")
    for i in range(len(materials_names)):
        print(
            "{} {}{}{} ".format(
                materials_names[i],
                color_resources[i],
                addThousandSeparator(resources[i]),
                bcolors.ENDC,
            ),
            end="",
        )
    print("")

    typeGood = int(city_header["producedTradegood"])
    print("Production:")
    print(
        "{}: {} {}: {}".format(
            materials_names[0],
            addThousandSeparator(wood_prod),
            materials_names[typeGood],
            addThousandSeparator(good_prod),
        )
    )

    hasTavern = "tavern" in [building["building"] for building in city["position"]]
    if hasTavern:
        consumption_per_hour = city["wineConsumptionPerHour"]
        if consumption_per_hour == 0:
            print(
                "{}{}Does not consume wine!{}".format(
                    bcolors.RED, bcolors.BOLD, bcolors.ENDC
                )
            )
        else:
            if typeGood == 1 and (good_prod * 3600) > consumption_per_hour:
                elapsed_time_run_out = "∞"
            else:
                consumption_per_second = Decimal(consumption_per_hour) / Decimal(3600)
                remaining_resources_to_consume = Decimal(resources[1]) / Decimal(
                    consumption_per_second
                )
                elapsed_time_run_out = daysHoursMinutes(remaining_resources_to_consume)
            print("There is wine for: {}".format(elapsed_time_run_out))

    for building in city["position"]:
        if building["name"] in ("", "empty"):
            continue
        if building["isMaxLevel"] is True:
            color = bcolors.BLACK
        elif building["canUpgrade"] is True:
            color = bcolors.GREEN
        else:
            color = bcolors.RED

        print(
            "lv:{}\t{}{}{}".format(
                formatBuildingLevel(building["level"], building["isBusy"]),
                color,
                building["name"],
                bcolors.ENDC,
            )
        )


def displayAccountSummary(data):
    print(
        "Ships {:d}/{:d}".format(int(data["available_ships"]), int(data["total_ships"]))
    )
    pirate_points = data.get("pirate_points")
    if pirate_points is not None:
        print(pirate_points)
    print("\nTotal:")
    print("{:>10}".format(" "), end="|")
    for i in range(len(materials_names)):
        print("{:>12}".format(materials_names_english[i]), end="|")
    print()
    print("{:>10}".format("Available"), end="|")
    for i in range(len(materials_names)):
        print("{:>12}".format(addThousandSeparator(data["total_resources"][i])), end="|")
    print()
    print("{:>10}".format("Production"), end="|")
    for i in range(len(materials_names)):
        print("{:>12}".format(addThousandSeparator(data["total_production"][i])), end="|")
    print()
    print()
    print(
        "Housing Space: {}, Citizens: {}".format(
            addThousandSeparator(data["total_housing_space"]),
            addThousandSeparator(data["total_citizens"]),
        )
    )
    print(
        "Gold: {}, Gold production: {}".format(
            addThousandSeparator(data["total_gold"]),
            addThousandSeparator(data["total_gold_production"]),
        )
    )
    print(
        "Wine consumption: {}".format(
            addThousandSeparator(data["total_wine_consumption"])
        )
    )


def saveCache(data):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass


def loadCache():
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def collectData(session):
    (ids, __) = getIdsOfCities(session)
    total_resources = [0] * len(materials_names)
    total_production = [0] * len(materials_names)
    total_wine_consumption = 0
    total_housing_space = 0
    total_citizens = 0
    available_ships = 0
    total_ships = 0
    total_gold = 0
    total_gold_production = 0
    pirate_city_id = None

    city_info = {}
    city_headers = {}
    city_names = {}
    city_tradegoods = {}
    city_productions = {}
    city_buildings = {}

    for id in ids:
        html = session.get("view=city&cityId={}".format(id), noIndex=True)
        data = session.get("view=updateGlobalData&ajax=1", noIndex=True)
        wait(0.5)
        json_data = json.loads(data, strict=False)
        json_data = json_data[0][1]["headerData"]
        if json_data["relatedCity"]["owncity"] != 1:
            continue

        cid = str(id)
        city = getCity(html)
        city_info[cid] = city
        city_headers[cid] = json_data
        city_names[cid] = city["cityName"]
        city_tradegoods[cid] = json_data["producedTradegood"]
        typeGood = int(json_data["producedTradegood"])
        city_productions[cid] = parseCityProduction(html, typeGood)
        city_buildings[cid] = [
            (building["name"], building["level"], building["isBusy"], building["position"])
            for building in city["position"]
            if building["name"] not in ("", "empty")
        ]

        if pirate_city_id is None:
            for building in city["position"]:
                if building["building"] == "pirateFortress":
                    pirate_city_id = cid
                    break

        total_production[0] += int(Decimal(json_data["resourceProduction"]) * 3600)
        total_production[typeGood] += int(
            Decimal(json_data["tradegoodProduction"]) * 3600
        )
        total_wine_consumption += json_data["wineSpendings"]
        total_housing_space += int(json_data["currentResources"]["population"])
        total_citizens += int(json_data["currentResources"]["citizens"])
        total_resources[0] += json_data["currentResources"]["resource"]
        total_resources[1] += json_data["currentResources"]["1"]
        total_resources[2] += json_data["currentResources"]["2"]
        total_resources[3] += json_data["currentResources"]["3"]
        total_resources[4] += json_data["currentResources"]["4"]
        available_ships = json_data["freeTransporters"]
        total_ships = json_data["maxTransporters"]
        total_gold = int(Decimal(json_data["gold"]))
        total_gold_production = int(
            Decimal(
                json_data["income"]
                + json_data["godGoldResult"]
                + json_data["badTaxAccountant"]
                + json_data["upkeep"]
                + json_data["scientistsUpkeep"]
            )
        )

    pirate_points = None
    if pirate_city_id is not None:
        points = getPirateFortressPoints(session, int(pirate_city_id))
        if points is not None:
            (capture_points, crew_points) = points
            pirate_points = "Pirate fortress: {} capture points, {} crew strength".format(
                addThousandSeparator(capture_points),
                addThousandSeparator(crew_points),
            )

    return {
        "own_ids": [cid for cid in city_info],
        "city_info": city_info,
        "city_headers": city_headers,
        "city_names": city_names,
        "city_tradegoods": city_tradegoods,
        "city_productions": city_productions,
        "city_buildings": city_buildings,
        "total_resources": total_resources,
        "total_production": total_production,
        "total_wine_consumption": total_wine_consumption,
        "total_housing_space": total_housing_space,
        "total_citizens": total_citizens,
        "available_ships": available_ships,
        "total_ships": total_ships,
        "total_gold": total_gold,
        "total_gold_production": total_gold_production,
        "pirate_points": pirate_points,
    }


def getStatus(session, event, stdin_fd, predetermined_input):
    """
    Parameters
    ----------
    session : ikabot.web.session.Session
    event : multiprocessing.Event
    stdin_fd: int
    predetermined_input : multiprocessing.managers.SyncManager.list
    """
    sys.stdin = os.fdopen(stdin_fd)
    config.predetermined_input = predetermined_input
    try:
        banner()
        color_arr = [
            bcolors.ENDC,
            bcolors.HEADER,
            bcolors.STONE,
            bcolors.BLUE,
            bcolors.WARNING,
        ]

        data = loadCache()
        if data is None:
            data = collectData(session)
            saveCache(data)
        else:
            print("Using cached data - select (3) to refresh data")
            print()

        own_ids = data["own_ids"]
        if not own_ids:
            event.set()
            return

        while True:
            banner()
            displayAccountSummary(data)
            print()
            print("(1) Building levels")
            print("(2) City details")
            print("(3) Refresh data")
            print("(0) Exit")
            print()
            selected = read(min=0, max=3, digit=True)

            if selected == 0:
                event.set()
                return

            if selected == 3:
                banner()
                print("Refreshing data...")
                data = collectData(session)
                saveCache(data)
                own_ids = data["own_ids"]
                continue

            if selected == 1:
                table_format = True
                while True:
                    banner()
                    print("Building levels\n")
                    if table_format:
                        displayBuildingTable(
                            data["city_names"], own_ids, data["city_buildings"]
                        )
                    else:
                        displayBuildingList(
                            data["city_names"],
                            own_ids,
                            data["city_buildings"],
                            data["city_tradegoods"],
                        )
                    print()
                    print("(0) Back")
                    print("(1) View as table")
                    print("(2) View as list")
                    print()
                    sub = read(min=0, max=2, digit=True)
                    if sub == 0:
                        break
                    table_format = sub == 1

            else:
                while True:
                    banner()
                    print("City details\n")
                    print("(0) Back")
                    for i, cid in enumerate(own_ids):
                        print(
                            "({}) {} {}".format(
                                i + 1,
                                data["city_names"][cid],
                                resources_abbr.get(str(data["city_tradegoods"][cid]), ""),
                            )
                        )
                    print()
                    city_sel = read(min=0, max=len(own_ids), digit=True)
                    if city_sel == 0:
                        break
                    cid = own_ids[city_sel - 1]
                    wood_prod, good_prod = data["city_productions"][cid]
                    if wood_prod is None or good_prod is None:
                        wood_prod = int(
                            Decimal(data["city_headers"][cid]["resourceProduction"]) * 3600
                        )
                        good_prod = int(
                            Decimal(data["city_headers"][cid]["tradegoodProduction"]) * 3600
                        )
                    showCityDetail(
                        data["city_info"][cid],
                        data["city_headers"][cid],
                        wood_prod,
                        good_prod,
                        color_arr,
                    )
                    enter()
                    print("")

    except KeyboardInterrupt:
        event.set()
        return