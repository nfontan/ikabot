#! /usr/bin/env python3
# -*- coding: utf-8 -*-
print(">>> USING NEW attackNavy SCRIPT WITH MODES & LOG <<<")

import json
import math
import re
import os
import sys
import time
import random
import traceback
from decimal import *

from ikabot.config import *
from ikabot import config
from ikabot.helpers.botComm import *
from ikabot.helpers.getJson import getCity, getIsland
from ikabot.helpers.gui import *
from ikabot.helpers.naval import *
from ikabot.helpers.pedirInfo import *
from ikabot.helpers.process import set_child_mode
from ikabot.helpers.signals import setInfoSignal
from ikabot.helpers.varios import *

getcontext().prec = 30

TRANSPORT_SHIP_CAPACITY = 500

UNIT_UPKEEP = {
    '301': 1, '302': 3, '303': 15, '304': 1, '305': 15, '306': 25, '307': 15, '308': 10,
    '309': 45, '310': 4, '311': 4, '312': 15, '313': 10, '314': 20, '315': 1, '316': 2,
}
ALL_POSSIBLE_ARMY_UNIT_GAME_IDS = list(UNIT_UPKEEP.keys())

ALL_POSSIBLE_FLEET_IDS = ["210", "211", "212", "213", "214", "215", "216", "217", "218", "219", "220"]

# =========================
# logging helpers
# =========================
NAVY_LOG_FILE = "/home/pi/log-attack-navy"

def navy_log(msg, level="INFO"):
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        line = f"[{ts}] [{level}] {msg}"
        folder = os.path.dirname(NAVY_LOG_FILE)
        
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(NAVY_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# =========================
# interval parser
# =========================
def parse_interval_to_seconds(s: str) -> int:
    """
    Accepts:
      - "3600"  -> 3600 seconds
      - "10s"   -> 10 seconds
      - "10m"   -> 10 minutes
      - "2h"    -> 2 hours
    """
    s = (s or "").strip().lower()
    if not s:
        raise ValueError("Empty interval")
    if s.isdigit():
        return int(s)

    m = re.match(r"^(\d+)\s*s$", s)
    if m:
        return int(m.group(1))

    m = re.match(r"^(\d+)\s*m$", s)
    if m:
        return int(m.group(1)) * 60

    m = re.match(r"^(\d+)\s*h$", s)
    if m:
        return int(m.group(1)) * 3600

    raise ValueError(f"Invalid interval format: {s}")

# =========================
# ORIGINAL HELPERS
# =========================
def _force_origin_city_context(session, origin_city_id):
    """
    Critical fix:
    Force server-side current city to origin before any wave/selection request.
    """
    try:
        if hasattr(session, "get_city_view"):
            try:
                session.get_city_view(origin_city_id, current_city_id=origin_city_id)
            except TypeError:
                session.get_city_view(origin_city_id)
        else:
            session.get(f"view=city&cityId={origin_city_id}&currentCityId={origin_city_id}", noIndex=True)
    except Exception:
        pass

def read_yes_no(msg, default='y'):
    choice = read(msg=f"{msg} [Y/n]: ", values=['y', 'Y', 'n', 'N', ''], default=default).lower()
    return choice == 'y' or choice == ''

def get_units(session, city):
    _force_origin_city_context(session, city["id"])
    params = {
        "view": "cityMilitary", "activeTab": "tabUnits", "cityId": city["id"],
        "backgroundView": "city", "currentCityId": city["id"], "templateView": "cityMilitary",
        "actionRequest": actionRequest, "ajax": "1",
    }
    try:
        resp_text = session.post(params=params)
        resp = json.loads(resp_text, strict=False)
        html = resp[1][1][1]
        html = html.split('<div class="fleet')[0]
        unit_id_names = re.findall(r'<div class="army (s\d+)">\s*<div class="tooltip">(.*?)</div>', html)
        unit_amounts = re.findall(r"<td>(.*?)\s*</td>", html)
        units = {}
        for i in range(len(unit_id_names)):
            amount = int(unit_amounts[i].replace(",", "").replace("-", "0"))
            if amount > 0:
                unit_id = unit_id_names[i][0].replace('s', '')
                unit_name = unit_id_names[i][1]
                units[unit_id] = {"name": decodeUnicodeEscape(unit_name), "amount": amount}
        return units
    except Exception:
        return {}

def get_ships_from_city(session, city):
    """
    Reads warships from tabShips in cityMilitary.
    """
    _force_origin_city_context(session, city["id"])
    params = {
        "view": "cityMilitary",
        "activeTab": "tabShips",
        "currentTab": "tabShips",
        "backgroundView": "city",
        "currentCityId": city["id"],
        "cityId": city["id"],
        "templateView": "cityMilitary",
        "actionRequest": actionRequest,
        "ajax": "1",
    }
    try:
        resp_text = session.post(params=params)
        resp = json.loads(resp_text, strict=False)
        html = resp[1][1][1]

        ships = {}

        tables = re.findall(
            r'<table class="table01 center militaryList fixed">(.*?)</table>',
            html,
            flags=re.DOTALL
        )

        for table_html in tables:
            title_row_match = re.search(
                r'<tr class="title_img_row">(.*?)</tr>',
                table_html,
                flags=re.DOTALL
            )
            count_row_match = re.search(
                r'<tr class="count">(.*?)</tr>',
                table_html,
                flags=re.DOTALL
            )
            if not title_row_match or not count_row_match:
                continue

            title_row = title_row_match.group(1)
            count_row = count_row_match.group(1)

            count_cells = re.findall(
                r'<td>(.*?)</td>',
                count_row,
                flags=re.DOTALL
            )

            if len(count_cells) <= 1:
                continue

            title_fleets = re.findall(
                r'<div class="fleet (s\d+)">\s*<div class="tooltip">(.*?)</div>',
                title_row,
                flags=re.DOTALL
            )

            for idx, (sid, sname) in enumerate(title_fleets):
                if idx + 1 >= len(count_cells):
                    break
                raw_amount = count_cells[idx + 1]
                amount = int(
                    raw_amount.replace(",", "")
                              .replace("-", "0")
                              .strip()
                )
                ship_id = sid.replace("s", "")
                ship_name = decodeUnicodeEscape(sname)

                if amount > 0:
                    ships[ship_id] = {
                        "name": ship_name,
                        "amount": amount
                    }

        return ships
    except Exception:
        return {}

def get_available_ships_in_city(session, city):
    ships = get_ships_from_city(session, city)
    total = 0
    for ship_id, data in ships.items():
        if ship_id in ALL_POSSIBLE_FLEET_IDS:
            total += data["amount"]
    return total

def choose_target_island_and_city(session):
    while True:
        banner()
        print("Enter target island coordinates to attack:")
        try:
            x_coord = read(msg="X coordinate (or 'exit' to cancel): ", digit=True, additionalValues=['exit'])
            if x_coord == 'exit':
                return None
            y_coord = read(msg="Y coordinate (or 'exit' to cancel): ", digit=True, additionalValues=['exit'])
            if y_coord == 'exit':
                return None

            html = session.get(f'view=worldmap_iso&islandX={x_coord}&islandY={y_coord}')
            islands_json_match = re.search(r"jsonData = '(.*?)';", html)
            if not islands_json_match:
                print(f"Could not find island data for [{x_coord}:{y_coord}]. Please try again.")
                enter()
                continue

            islands_data = json.loads(islands_json_match.group(1), strict=False)
            island_id = islands_data["data"][str(x_coord)][str(y_coord)][0]
            html_island = session.get(island_url + str(island_id))
            island = getIsland(html_island)

            player_cities = [
                city for city in island['cities']
                if city.get('type') == 'city'
                and city.get('state') != 'vacation'
                and city.get('Name') != session.username
            ]

            if not player_cities:
                print("No attackable (non-vacation) foreign cities found on this island.")
                enter()
                continue

            print(f"\nPlayer cities on {island['name']} [{island['x']}:{island['y']}]:")

            print("(0) Choose a different island")
            for i, city in enumerate(player_cities):
                print(f"({i+1}) {decodeUnicodeEscape(city['name'])} ({decodeUnicodeEscape(city['Name'])})")

            choice = read(min=0, max=len(player_cities))
            if choice == 0:
                continue

            target_city = player_cities[choice - 1]
            target_city['island_id'] = island['id']
            target_city['ownerName'] = target_city['Name']
            target_city['x'] = island['x']
            target_city['y'] = island['y']
            return target_city
        except Exception:
            print("An error occurred. Please try again.")
            enter()
            continue

def attackNavy(session, event, stdin_fd, predetermined_input):
    sys.stdin = os.fdopen(stdin_fd)
    config.predetermined_input = predetermined_input

    try:
        target_city = choose_target_island_and_city(session)
        if not target_city:
            return

        banner()
        print("Select city of origin")
        origin_city = chooseCity(session)
        if not origin_city:
            return

        _force_origin_city_context(session, origin_city["id"])

        ships_in_origin = get_ships_from_city(session, origin_city)
        if not ships_in_origin:
            print(f"You don't have any warships in {decodeUnicodeEscape(origin_city['name'])}!")
            enter()
            return

        banner()
        print(f"Planning naval blockade from {decodeUnicodeEscape(origin_city['name'])}")
        print(f"Target: {decodeUnicodeEscape(target_city['name'])} ({decodeUnicodeEscape(target_city['ownerName'])})")

        target_ships_per_type = {}
        for ship_id, ship_data in sorted(ships_in_origin.items()):
            ship_name = ship_data['name']
            max_amount = ship_data['amount']
            amount_to_send = int(read(
                msg=f"  Send {ship_name} (available: {addThousandSeparator(max_amount)}): ",
                min=0, max=max_amount, default=0
            ))
            if amount_to_send > 0:
                target_ships_per_type[ship_id] = amount_to_send

        if not target_ships_per_type:
            print("No ships selected. Naval attack cancelled.")
            return

        banner()
        print("Naval Attack Summary:")
        print(f"  Origin: {decodeUnicodeEscape(origin_city['name'])}")
        print(f"  Target: {decodeUnicodeEscape(target_city['name'])} ({decodeUnicodeEscape(target_city['ownerName'])})")
        for ship_id, qty in target_ships_per_type.items():
            ship_name = ships_in_origin.get(ship_id, {}).get('name', ship_id)
            print(f"    - {ship_name}: {addThousandSeparator(qty)}")

        print("\nChoose navy attack mode:")
        print("  (1) Wait until fleet returns (AttackPlayer-style)")
        print("  (2) Fixed interval (time-based, regardless of return)")
        mode = read(
            msg="Mode [1/2]: ",
            values=['1', '2'],
            default='1'
        )

        number_of_waves = read(
            msg='\nHow many blockade waves do you want to send? (1 for a single blockade): ',
            min=1, default=1
        )
        # --- NUEVO: Pregunta de notificaciones ---
        send_notifications = read_yes_no(
            "\nDo you want to receive Telegram notifications for this attack?"
        )
        # -----------------------------------------
        interval_seconds = 0
        if mode == '2' and number_of_waves > 1:
            while True:
                try:
                    interval_str = read(
                        msg="Interval between attacks (e.g. 3600 / 10m / 2h): ",
                        values=None
                    )
                    interval_seconds = parse_interval_to_seconds(interval_str)
                    break
                except Exception as e:
                    print(f"Invalid interval: {e}. Try again.")

        if not read_yes_no("\nProceed with this naval attack plan?"):
            print("Naval attack aborted.")
            return

    except KeyboardInterrupt:
        return
    finally:
        event.set()

    set_child_mode(session)
    info = (
        f"\nNaval blockade on {decodeUnicodeEscape(target_city['name'])} "
        f"{number_of_waves} times from {decodeUnicodeEscape(origin_city['name'])}"
    )
    setInfoSignal(session, info)

    try:
        navy_log(
            f"START attackNavy origin={decodeUnicodeEscape(origin_city['name'])}({origin_city['id']}) "
            f"target={decodeUnicodeEscape(target_city['name'])}({target_city['id']}) "
            f"mode={mode} waves={number_of_waves}"
        )
        if mode == '2' and interval_seconds > 0:
            navy_log(f"Mode 2 interval={interval_seconds} seconds")
    except Exception:
        pass

    try:
        attack_function = 'sendFleetOnBlockade'

        payload_base = {
            "action": "transportOperations",
            "function": attack_function,
            "actionRequest": actionRequest,
            "islandId": str(target_city['island_id']),
            "destinationCityId": str(target_city['id']),
            "barbarianVillage": "0",
            "backgroundView": "island",
            "currentCityId": str(origin_city['id']),
            "cityId": str(origin_city['id']),
            "currentIslandId": str(origin_city['islandId']),
            "templateView": "blockade",
            "ajax": "1"
        }

        estimated_round_trip_seconds = None

        for i in range(number_of_waves):
            wave_number = i + 1
            navy_log(f"DISPATCH wave {wave_number}/{number_of_waves} started")

            _force_origin_city_context(session, origin_city["id"])

            delay = 0

            if wave_number > 1:
                if mode == '1':
                    if estimated_round_trip_seconds is not None:
                        navy_log(
                            f"WAVE {wave_number}: waiting {estimated_round_trip_seconds}s "
                            f"for fleet to return (mode=1)"
                        )
                        wait(estimated_round_trip_seconds)
                    else:
                        navy_log(
                            f"WAVE {wave_number}: no estimated travel time yet, "
                            f"fallback to availability check (legacy)."
                        )
                        while True:
                            _force_origin_city_context(session, origin_city["id"])
                            current_total = get_available_ships_in_city(session, origin_city)
                            if current_total >= 1:
                                break
                            wait(30)
                else:
                    if interval_seconds > 0:
                        navy_log(
                            f"WAVE {wave_number}: waiting fixed interval {interval_seconds}s (mode=2)"
                        )
                        wait(interval_seconds)

                # random delay 1�20 seconds added on top of base wait in both modes
                delay = random.randint(1, 20)
                wait(delay)
                navy_log(f"WAVE {wave_number}: random delay before send = {delay}s")

            current_ships_dict = get_ships_from_city(session, origin_city)
            wave_ships_payload = {}
            total_ships_this_wave = 0

            for ship_id, wanted in target_ships_per_type.items():
                available = int(current_ships_dict.get(ship_id, {}).get("amount", 0))
                if available <= 0:
                    continue
                send_qty = min(wanted, available)
                wave_ships_payload[ship_id] = send_qty
                total_ships_this_wave += send_qty

            if total_ships_this_wave == 0:
                print("No warships available for this wave. Stopping remaining waves.")
                navy_log(
                    f"WAVE {wave_number}: no ships available, stopping further waves.",
                    level="ERROR"
                )
                break

            navy_log(
                f"WAVE {wave_number}: ships={wave_ships_payload} total={total_ships_this_wave}"
            )

            payload = dict(payload_base)

            for fleet_id in ALL_POSSIBLE_FLEET_IDS:
                payload[f"cargo_fleet_{fleet_id}"] = "0"
                payload[f"cargo_fleet_{fleet_id}_upkeep"] = "0"

            for ship_id, qty in wave_ships_payload.items():
                payload[f"cargo_fleet_{ship_id}"] = str(qty)

            response_data = session.post(params=payload)
            response_json = json.loads(response_data, strict=False)

            success = True
            server_msg = ""
            for item in response_json:
                if item[0] == 'provideFeedback' and item[1] and item[1][0].get('type') == 11:
                    server_msg = re.sub('<[^<]+?>', ' ', item[1][0]['text']).strip()
                    success = False
                    break

            navy_log(
                f"WAVE {wave_number}: status={'SUCCESS' if success else 'FAILED'} "
                f"server_msg={server_msg!r}"
            )

            if success and estimated_round_trip_seconds is None:
                try:
                    txt = json.dumps(response_json)
                    m = re.search(r"(\d+)\s*minutes", txt)
                    if m:
                        minutes = int(m.group(1))
                        estimated_round_trip_seconds = (minutes * 60) * 2 + 60
                        navy_log(
                            f"Estimated round trip from response: "
                            f"{estimated_round_trip_seconds}s",
                            level="INFO"
                        )
                except Exception:
                    pass

            try:
                if send_notifications: # <--- Cambio aquí
                    status_text = "Success" if success else f"Failed ({server_msg})"
                    sendToBot(
                        session,
                        (
                            f"Navy wave {wave_number} of {number_of_waves}\n"
                            f"Origin city: {decodeUnicodeEscape(origin_city['name'])}\n"
                            f"Target city: {decodeUnicodeEscape(target_city['name'])}\n"
                            f"Ships sent in this wave: {total_ships_this_wave}\n"
                            f"Wave status: {status_text}\n"
                            f"Random delay before this wave: {delay} seconds\n"
                            f"Mode: {mode}"
                        )
                    )
            except Exception:
                pass

            if not success:
                break

        print("\nAll naval attack waves have been dispatched.")
        navy_log("END attackNavy: all waves dispatched")

    except Exception:
        msg = f"Error during naval attack execution:\n{info}\nCause:\n{traceback.format_exc()}"
        navy_log(f"EXCEPTION: {msg}", level="ERROR")
        sendToBot(session, msg)
    finally:
        try:
            session.logout()
        except Exception:
            pass
