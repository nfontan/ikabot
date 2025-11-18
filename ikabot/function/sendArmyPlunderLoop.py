#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import time
import json
import traceback

from ikabot.config import *  # incluye config, actionRequest, etc.
from ikabot.helpers.gui import *
from ikabot.helpers.pedirInfo import *
from ikabot.helpers.process import set_child_mode
from ikabot.helpers.botComm import sendToBot


def _send_plunder(
    session,
    islandId,
    destinationCityId,
    transporter,
    frontline_units,
    mortars,
    lancers,
):
    """
    Hace UNA llamada a sendArmyPlunderSea (equivalente al curl original).
    Usa el actionRequest global de ikabot.config.
    """

    params = {
        "action": "transportOperations",
        "function": "sendArmyPlunderSea",

        "islandId": islandId,
        "destinationCityId": destinationCityId,

        # Unidades de primera línea (303)
        "cargo_army_303_upkeep": 3,
        "cargo_army_303": frontline_units,

        # Morteros (305)
        "cargo_army_305_upkeep": 30,
        "cargo_army_305": mortars,

        # Lanceros (315) – upkeep aproximado 0, si hace falta luego se ajusta
        "cargo_army_315_upkeep": 0,
        "cargo_army_315": lancers,

        # Otro slot que venía en tu curl, lo dejamos en 0
        "cargo_army_309_upkeep": 45,
        "cargo_army_309": 0,

        # Barcos mercantes
        "transporter": transporter,

        # Siempre NO aldea bárbara
        "barbarianVillage": 0,

        # Datos de vista
        "backgroundView": "island",
        "currentIslandId": islandId,
        "templateView": "plunder",
        "ajax": 1,

        # Token CSRF de ikabot (global)
        "actionRequest": actionRequest,
    }

    # DEBUG opcional, si querés ver lo que se manda:
    # print("[DEBUG] Params a enviar:")
    # for k, v in params.items():
    #     print("   ", k, "=", repr(v))

    resp = session.post(params=params)
    return resp


def _maybe_activate_poseidon(session):
    """
    Intenta activar el milagro de Poseidón usando el módulo oficial de ikabot.
    Si no existe o cambia la firma, simplemente loguea y sigue.
    """
    try:
        from ikabot.function.activateMiracle import activateMiracle
    except Exception as e:
        print(f"[INFO] No se pudo importar activateMiracle, se omite Poseidón. Detalle: {e}")
        return

    try:
        session.setStatus("Activando milagro de Poseidón")
        activateMiracle(session)
        print("[OK] Milagro de Poseidón activado (si estaba disponible).")
    except Exception as e:
        print(f"[WARN] Error al activar Poseidón: {e}")


def sendArmyPlunderLoop(session, event, stdin_fd, predetermined_input):
    """
    Igual estilo que autoPirate:

      - Fase 1 (interactiva):
          * redirige stdin
          * usa read()/enter() para pedir parámetros
          * al final llama set_child_mode(session) y event.set()

      - Fase 2 (background):
          * while envíos > 0: hace saqueos, espera X minutos, respeta event
          * usa session.setStatus() para que se vea el estado en el menú
    """

    # --- Redirigir stdin y predetermined_input, igual que autoPirate ---
    sys.stdin = os.fdopen(stdin_fd)
    config.predetermined_input = predetermined_input

    banner()
    try:
        print("=== Saqueos automáticos por mar (sendArmyPlunderSea) ===\n")

        # Pedimos parámetros usando read(), igual que autoPirate
        print("Ingrese el ID de la isla (islandId):")
        islandId = read(min=1, digit=True)

        print("Ingrese el ID de la ciudad destino (destinationCityId):")
        destinationCityId = read(min=1, digit=True)

        print("Barcos mercantes a enviar (transporter):")
        transporter = read(min=1, digit=True)

        print("Unidades de primera línea a enviar (cargo_army_303):")
        frontline_units = read(min=0, digit=True)

        print("Morteros a enviar (cargo_army_305):")
        mortars = read(min=0, digit=True)

        print("Lanceros a enviar (cargo_army_315):")
        lancers = read(min=0, digit=True)

        print("¿Activar milagro Poseidón antes de cada envío? (Y|N)")
        poseidonAnswer = read(values=["y", "Y", "n", "N"])
        use_poseidon = poseidonAnswer.lower() == "y"

        print("¿Cuántas veces querés repetir el envío? (min = 1)")
        repetitions = read(min=1, digit=True)

        print("¿Cada cuántos minutos entre envíos? (min = 0)")
        interval_minutes = read(min=0, digit=True)
        interval_seconds = interval_minutes * 60

        print("\n=== RESUMEN CONFIGURACIÓN ===")
        print(f"islandId          = {islandId}")
        print(f"destinationCityId = {destinationCityId}")
        print(f"Mercantes         = {transporter}")
        print(f"1ª línea (303)    = {frontline_units}")
        print(f"Morteros (305)    = {mortars}")
        print(f"Lanceros (315)    = {lancers}")
        print(f"Aldea bárbara     = 0")
        print(f"Repeticiones      = {repetitions}")
        print(f"Intervalo (min)   = {interval_minutes}")
        print(f"Poseidón          = {'Sí' if use_poseidon else 'No'}")

        enter()  # “Press enter to continue”, igual que en otras funciones

    except KeyboardInterrupt:
        # Si el usuario corta con Ctrl+C en la fase interactiva
        event.set()
        return

    # --- A partir de acá, modo hijo (segundo plano), igual que autoPirate ---
    set_child_mode(session)
    event.set()  # avisar al padre que ya terminamos la parte interactiva

    try:
        current_run = 0

        while repetitions > 0:
            current_run += 1
            repetitions -= 1

            status_text = f"Saqueo automático {current_run} restante(s): {repetitions}"
            session.setStatus(status_text)
            print(f"\n=== Envío {current_run} ===")
            print(status_text)

            if use_poseidon:
                _maybe_activate_poseidon(session)

            # Hacemos el saqueo
            try:
                resp = _send_plunder(
                    session=session,
                    islandId=islandId,
                    destinationCityId=destinationCityId,
                    transporter=transporter,
                    frontline_units=frontline_units,
                    mortars=mortars,
                    lancers=lancers,
                )
            except Exception:
                info = "Error al hacer la request de saqueo"
                msg = "Error in:\n{}\nCause:\n{}".format(
                    info, traceback.format_exc()
                )
                print(msg)
                try:
                    sendToBot(session, msg)
                except Exception:
                    pass
                break

            # Mostrar algo de la respuesta para debug
            try:
                data = json.loads(resp)
                print("[DEBUG] Respuesta JSON:")
                print(data)
            except Exception:
                try:
                    txt = resp.decode("utf-8", errors="ignore")
                except Exception:
                    txt = str(resp)
                print("[DEBUG] Respuesta cruda del servidor (primeros 500 chars):")
                print(txt[:500])

            # Si todavía quedan envíos, esperamos
            if repetitions > 0 and interval_seconds > 0:
                print(
                    f"[INFO] Esperando {interval_minutes} minuto(s) antes del próximo envío..."
                )
                remaining = int(interval_seconds)
                # Espera troceada para poder cortar con event
                while remaining > 0:
                    if event.is_set():
                        print("[INFO] Tarea de saqueo cancelada (event set).")
                        return
                    time.sleep(1)
                    remaining -= 1

        session.setStatus("Saqueos automáticos finalizados")
        print("\n=== Saqueos automáticos finalizados ===")

    except Exception:
        info = ""
        msg = "Error in:\n{}\nCause:\n{}".format(info, traceback.format_exc())
        print(msg)
        try:
            sendToBot(session, msg)
        except Exception:
            pass
        event.set()
        return
