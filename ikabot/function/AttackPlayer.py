#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import os
import sys
import random
import traceback
import time
from decimal import Decimal, getcontext

from ikabot import config
from ikabot.config import *
from ikabot.helpers.botComm import sendToBot
from ikabot.helpers.getJson import getIsland, getCity
from ikabot.helpers.gui import banner, enter
from ikabot.helpers.naval import getAvailableShips
from ikabot.helpers.pedirInfo import read, chooseCity
from ikabot.helpers.process import set_child_mode
from ikabot.helpers.signals import setInfoSignal
from ikabot.helpers.varios import decodeUnicodeEscape, addThousandSeparator, wait

getcontext().prec = 30

# Constants
TRANSPORT_SHIP_CAPACITY = 600
UNIT_UPKEEP = {
    '301': 1, '302': 3, '303': 15, '304': 1, '305': 15, '306': 25, '307': 15, '308': 10,
    '309': 45, '310': 4, '311': 4, '312': 15, '313': 10, '314': 20, '315': 1, '316': 2
}
ALL_POSSIBLE_ARMY_UNIT_GAME_IDS = list(UNIT_UPKEEP.keys())

# =========================
# LOG FILE
# =========================
ATTACK_LOG_FILE = "/home/pi/log-attack-player"


def attack_log(msg, level="INFO"):
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        line = f"[{ts}] [{level}] {msg}"
        folder = os.path.dirname(ATTACK_LOG_FILE)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(ATTACK_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def read_yes_no(msg, default='y'):
    choice = read(msg=f"{msg} [Y/n]: ", values=['y', 'Y', 'n', 'N', ''], default=default).lower()
    return choice == 'y' or choice == ''


def _force_origin_city_context(session, origin_city_id):
    """
    Force server-side current city to origin before any wave/selection request.
    """
    try:
        session.get(
            f"view=city&cityId={origin_city_id}&currentCityId={origin_city_id}",
            noIndex=True
        )
    except Exception:
        pass


def get_units(session, city):
    _force_origin_city_context(session, city["id"])
    params = {"view": "cityMilitary", "cityId": city["id"], "ajax": "1"}
    
    try:
        resp_text = session.post(params=params)
        resp = json.loads(resp_text, strict=False)
        
        html = ""
        for update in resp:
            if update[0] == "changeView":
                html = update[1][1]
                break

        if not html:
            return {}

        units = {}
        # Separamos la sección de tierra de la de barcos para evitar conflictos [cite: 98]
        html_units = html.split('<div class="fleet')[0]
        
        # Localizamos todas las tablas de unidades terrestres 
        tables = re.findall(r'<table[^>]*class="[^"]*militaryList[^"]*"[^>]*>(.*?)</table>', html_units, re.DOTALL)
        
        for table_html in tables:
            # 1. Extraemos IDs de las unidades (s301, s303, etc.) [cite: 37, 39, 41]
            ids = re.findall(r'class="army (s\d+)"', table_html)
            # 2. Extraemos nombres de los tooltips [cite: 37, 39, 42]
            names = re.findall(r'<div class="tooltip">([^<]+)</div>', table_html)
            # 3. Extraemos todos los valores de la fila de conteo [cite: 55, 82]
            # Usamos una regex que capture el contenido de los TD, incluyendo el espacio de miles \u00a0 
            amounts_row = re.search(r'<tr class="count">.*?<td>.*?</td>(.*?)</tr>', table_html, re.DOTALL)
            if not amounts_row:
                continue
                
            raw_amounts = re.findall(r'<td>\s*([\d\u00a0,.-]+)\s*</td>', amounts_row.group(1))

            # Sincronizamos los datos de la tabla actual por índice
            for i in range(min(len(ids), len(raw_amounts))):
                u_id = ids[i].replace('s', '')
                u_name = decodeUnicodeEscape(names[i])
                
                # Limpieza absoluta de caracteres de formato y espacios de miles 
                amount_str = raw_amounts[i].replace('\u00a0', '').replace('.', '').replace(',', '').replace('-', '0').strip()
                
                try:
                    amount = int(amount_str)
                    if amount > 0:
                        units[u_id] = {"name": u_name, "amount": amount}
                except ValueError:
                    continue
        
        return units
    except Exception as e:
        print(f"[DEBUG] Error en get_units: {str(e)}")
        return {}

def choose_target_island_and_city(session):
    """
    ?????? ????? ????? + ????? ?????.
    ?????? ????? ?????? ??? ??? ???????? ??????? ??? Vacation.
    """
    while True:
        banner()
        print("Enter target island coordinates to attack:")
        try:
            x_coord = read(msg="X coordinate (or 'exit' to cancel): ", digit=True, additionalValues=["exit"])
            if x_coord == "exit":
                return None
            y_coord = read(msg="Y coordinate (or 'exit' to cancel): ", digit=True, additionalValues=["exit"])
            if y_coord == "exit":
                return None

            x = str(x_coord)
            y = str(y_coord)

            html = session.get(f"view=worldmap_iso&islandX={x}&islandY={y}")

            m = re.search(r"jsonData\s*=\s*'(.*?)';", html, flags=re.DOTALL)
            if not m:
                print(f"[ERROR] Can't find jsonData for [{x}:{y}].")
                enter()
                continue

            raw = m.group(1).replace("\\'", "'")

            try:
                islands_data = json.loads(raw, strict=False)
            except Exception as je:
                print(f"[ERROR] JSON parse failed for [{x}:{y}] -> {je}")
                enter()
                continue

            data = islands_data.get("data", {})
            if x not in data or y not in data.get(x, {}):
                print(f"[ERROR] No island data at [{x}:{y}] (invalid coords / not visible).")
                enter()
                continue

            island_id = data[x][y][0]
            html_island = session.get(island_url + str(island_id))
            island = getIsland(html_island)

            player_cities = [
                c for c in island.get('cities', [])
                if c.get('type') == 'city'
                and c.get('state') != 'vacation'
                and c.get('Name') != session.username
            ]

            if not player_cities:
                print("No attackable (non-vacation) foreign cities found on this island.")
                enter()
                continue

            print(f"\nPlayer cities on {island['name']} [{island['x']}:{island['y']}]:")
            print("(0) Choose a different island")
            for i, c in enumerate(player_cities):
                print(f"({i+1}) {decodeUnicodeEscape(c['name'])} ({decodeUnicodeEscape(c['Name'])})")

            choice = read(min=0, max=len(player_cities))
            if choice == 0:
                continue

            target_city = player_cities[choice - 1]
            target_city['island_id'] = island['id']
            target_city['ownerName'] = target_city['Name']
            target_city['x'] = island['x']
            target_city['y'] = island['y']
            return target_city

        except Exception as e:
            print(f"[ERROR] choose_target_island_and_city failed: {e}")
            enter()
            continue


# Dummy functions for compatibility
def get_barbarians_lv(*args, **kwargs): pass
def get_barbarians_info(*args, **kwargs): pass
def get_movements(*args, **kwargs): return []
def get_current_attacks(*args, **kwargs): return []
def wait_for_arrival(*args, **kwargs): pass
def wait_until_attack_is_over(*args, **kwargs): pass
def get_unit_data(*args, **kwargs): return {}
def load_troops(*args, **kwargs): return {}, 0, 0
def wait_for_round(*args, **kwargs): pass
def filter_loading(attacks): return []
def filter_traveling(attacks, onlyCanAbort=True): return []
def filter_fighting(attacks): return []


def _wait_until_ships_full(session, origin_city_id, required_ships):
    while True:
        try:
            current = int(getAvailableShips(session))
        except Exception:
            current = 0

        if current >= int(required_ships):
            return

        wait(random.randint(10, 30))


def _is_inactive_grey(state):
    return state in ("inactive", "inactiveLonger")


def _get_city_state(session, target_city):
    """
    ???? ??? state ??????? ????? (inactive / active / vacation ...).
    ????? ??? islandId + city id ?? getIsland.
    """
    try:
        island_id = target_city.get("island_id") or target_city.get("islandId")
        if not island_id:
            return None

        html_island = session.get(island_url + str(island_id))
        isl = getIsland(html_island)
        cities = isl.get("cities", []) or []

        wanted_id = str(target_city.get("id"))
        for c in cities:
            if str(c.get("id")) != wanted_id:
                continue
            state_city = (c.get("state") or "").strip()
            return state_city
    except Exception:
        return None
    return None


def AttackPlayer(session, event, stdin_fd, predetermined_input):
    sys.stdin = os.fdopen(stdin_fd)
    config.predetermined_input = predetermined_input

    try:
        target_city = choose_target_island_and_city(session)
        if not target_city:
            return

        banner()
        print("Choose origin city")
        origin_city = chooseCity(session,foreign=True)
        if not origin_city:
            return

        _force_origin_city_context(session, origin_city["id"])

        units_in_origin = get_units(session, origin_city)
        if not units_in_origin:
            print(f"You don't have any land troops in {decodeUnicodeEscape(origin_city['name'])}!")
            enter()
            return

        banner()
        print(f"Planning attack from {decodeUnicodeEscape(origin_city['name'])}")

        selected_units_payload = {}
        for unit_id, unit_data in sorted(units_in_origin.items()):
            unit_name = unit_data['name']
            max_amount = unit_data['amount']
            amount_to_send = int(read(
                msg=f"  Send {unit_name} (available: {addThousandSeparator(max_amount)}): ",
                min=0, max=max_amount, default=0
            ))
            if amount_to_send > 0:
                selected_units_payload[unit_id] = amount_to_send

        if not selected_units_payload:
            print("No units selected. Attack cancelled.")
            return

        banner()
        print("Attack Summary:")
        print(f"  Origin: {decodeUnicodeEscape(origin_city['name'])}")
        print(f"  Target: {decodeUnicodeEscape(target_city['name'])} ({decodeUnicodeEscape(target_city['ownerName'])})")
        for unit_id, qty in selected_units_payload.items():
            unit_name = units_in_origin.get(unit_id, {}).get('name', unit_id)
            print(f"    - {unit_name}: {addThousandSeparator(qty)}")
        # Obtenemos el total disponible para mostrarlo en la pregunta
        try:
            available_ships = int(getAvailableShips(session))
        except Exception:
            available_ships = 0

        # Reasignamos la variable preguntando al usuario
        ATTACK_SHIPS = int(read(
            msg=f"\nHow many transport ships to use per wave? (available: {available_ships}): ",
            min=0, max=999, default=available_ships
        ))
        #print(f"\nTransport ships to use per wave: {ATTACK_SHIPS}")

        number_of_waves = read(
            msg="\nHow many times do you want to attack this city? (1 for a single attack): ",
            min=1, default=1
        )

        if not read_yes_no("\nProceed with this attack plan?"):
            print("Attack aborted.")
            return
        send_notifications = read_yes_no(
            "\nDo you want to receive Telegram notifications for this attack?"
        )


    except KeyboardInterrupt:
        return
    finally:
        event.set()

    set_child_mode(session)
    info = (
        f"\n?? Attacking {decodeUnicodeEscape(target_city['name'])} "
        f"{number_of_waves} times from {decodeUnicodeEscape(origin_city['name'])}"
    )
    setInfoSignal(session, info)

    try:
        attack_log(
            f"START AttackPlayer origin={decodeUnicodeEscape(origin_city['name'])}({origin_city['id']}) "
            f"target={decodeUnicodeEscape(target_city['name'])}({target_city['id']}) "
            f"waves={number_of_waves} ships_per_wave={ATTACK_SHIPS}"
        )

        same_island = str(origin_city.get('islandId', '')) == str(target_city.get('island_id', ''))
        attack_function = 'plunder' if same_island else 'sendArmyPlunderSea'

        # ?? ???? ????? ????? ??? ?? ???? ????? ATTACK_SHIPS ????? ??? ?????
        if attack_function != 'plunder':
            _wait_until_ships_full(session, origin_city["id"], ATTACK_SHIPS)

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
            "templateView": "plunder",
            "ajax": "1"
        }

        if attack_function != 'plunder':
            # ??? ????? ?????? ???? ????? ?????
            payload_base["transporter"] = str(ATTACK_SHIPS)

        for unit_id in ALL_POSSIBLE_ARMY_UNIT_GAME_IDS:
            payload_base[f"cargo_army_{unit_id}"] = str(selected_units_payload.get(unit_id, 0))
            if unit_id in UNIT_UPKEEP:
                payload_base[f"cargo_army_{unit_id}_upkeep"] = UNIT_UPKEEP[unit_id]

        last_delay = 0

        for i in range(number_of_waves):
            wave_number = i + 1
            attack_log(f"WAVE {wave_number}/{number_of_waves} started")

            if wave_number > 1:
                state_city = _get_city_state(session, target_city)
                if state_city is not None and not _is_inactive_grey(state_city):
                    msg_stop = (
                        f"Attack stopped before wave {wave_number}. "
                        f"Target city {decodeUnicodeEscape(target_city['name'])} "
                        f"({decodeUnicodeEscape(target_city['ownerName'])}) is no longer inactive "
                        f"(state={state_city})."
                    )
                    try:
                        if send_notifications:
                            sendToBot(session, msg_stop)
                    except Exception:
                        pass
                    attack_log(msg_stop, level="WARN")
                    break

            _force_origin_city_context(session, origin_city["id"])

            if attack_function != 'plunder':
                _wait_until_ships_full(session, origin_city["id"], ATTACK_SHIPS)
            # FORZAR CIUDAD SOLO ACA
            _force_origin_city_context(session, origin_city["id"])

            payload = dict(payload_base)
            response_data = session.post(params=payload)
            response_json = json.loads(response_data, strict=False)

            success = True
            server_msg = ""
            for item in response_json:
                if item[0] == 'provideFeedback' and item[1] and item[1][0].get('type') == 11:
                    server_msg = re.sub('<[^<]+?>', ' ', item[1][0]['text']).strip()
                    success = False
                    break

            attack_log(
                f"WAVE {wave_number}: status={'SUCCESS' if success else 'FAILED'} "
                f"server_msg={server_msg!r}"
            )

            try:
                status_text = "Success" if success else f"Failed ({server_msg})"
                delay_info = f"{last_delay} seconds" if wave_number > 1 else "N/A"
                session.setStatus(f"Attack wave {wave_number} of {number_of_waves}")
                if send_notifications:
                    sendToBot(
                        session,
                        (
                            f"Attack wave {wave_number} of {number_of_waves}\n"
                            f"Origin city: {decodeUnicodeEscape(origin_city['name'])}\n"
                            f"Target city: {decodeUnicodeEscape(target_city['name'])}\n"
                            f"Units sent: {sum(selected_units_payload.values())}\n"
                            f"Ships used: {ATTACK_SHIPS}\n"
                            f"Wave status: {status_text}\n"
                            f"Delay before this wave: {delay_info}"
                        )
                    )
            except Exception:
                pass

            if wave_number < number_of_waves:
                last_delay = random.randint(1, 20)
                wait(last_delay)

            if not success:
                break

        attack_log("END AttackPlayer: all waves dispatched")

    except Exception:
        msg = f"Error during attack execution:\n{info}\nCause:\n{traceback.format_exc()}"
        attack_log(f"EXCEPTION: {msg}", level="ERROR")
        try:
            sendToBot(session, msg)
        except Exception:
            pass
    finally:
        try:
            session.logout()
        except Exception:
            pass
