#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import time
import json
import traceback

from ikabot.config import *  # incluye config, actionRequest, etc.
from ikabot.helpers.gui import *
from ikabot.helpers.pedirInfo import *  # read, chooseCity, etc.
from ikabot.helpers.process import set_child_mode
from ikabot.helpers.botComm import sendToBot


def _select_origin_city(session, originCityId, islandId):
    """
    Cambia la ciudad actual en el servidor usando la acción oficial
    header / changeCurrentCity (igual que el dropdown de ciudades).
    """
    try:
        params = {
            "action": "header",
            "function": "changeCurrentCity",
            "oldView": "island",
            "cityId": originCityId,
            "islandId": islandId,
            "backgroundView": "island",
            "currentIslandId": islandId,
            "actionRequest": actionRequest,
            "ajax": 1,
        }
        session.post(params=params, noIndex=True)
    except Exception as e:
        print(f"[WARN] No se pudo cambiar la ciudad activa a {originCityId}: {e}")


def _send_plunder(
    session,
    originCityId,
    islandId,
    destinationCityId,
    transporter,
    lancers_315,
    hoplitas_303,
    morteros_305,
):
    """
    Hace UNA llamada a sendArmyPlunderSea.

    Orden de unidades:
      315 -> lanceros
      303 -> hoplitas
      305 -> morteros
    """

    params = {
        "action": "transportOperations",
        "function": "sendArmyPlunderSea",

        # ORIGEN (aunque Ikariam usa la ciudad activa, no molesta incluirlos)
        "cityId": originCityId,
        "currentCityId": originCityId,

        # DESTINO
        "islandId": islandId,
        "destinationCityId": destinationCityId,

        # Lanceros (315)
        "cargo_army_315_upkeep": 0,   # ajustar si querés el upkeep real
        "cargo_army_315": lancers_315,

        # Hoplitas (303)
        "cargo_army_303_upkeep": 3,
        "cargo_army_303": hoplitas_303,

        # Morteros (305)
        "cargo_army_305_upkeep": 30,
        "cargo_army_305": morteros_305,

        # Slot extra que venía en el curl original, lo dejamos en 0
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

        # Token CSRF global
        "actionRequest": actionRequest,
    }

    resp = session.post(params=params, noIndex=True)
    return resp


def _maybe_activate_poseidon(session):
    """
    Intenta activar el milagro de Poseidón usando el módulo oficial de ikabot.
    Si no existe o falla, solo loguea y sigue.
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


def _mostrar_errores_provide_feedback(raw_response):
    """
    Busca la sección ['provideFeedback', [...]] y muestra solo los textos.
    """
    try:
        data = json.loads(raw_response, strict=False)
    except Exception:
        try:
            txt = raw_response.decode("utf-8", errors="ignore")
        except Exception:
            txt = str(raw_response)
        print("[DEBUG] Respuesta no es JSON. (primeros 300 chars):")
        print(txt[:300])
        return

    errores = []
    for bloque in data:
        if not isinstance(bloque, list) or len(bloque) < 2:
            continue
        clave, contenido = bloque[0], bloque[1]
        if clave == "provideFeedback" and isinstance(contenido, list):
            for item in contenido:
                if not isinstance(item, dict):
                    continue
                texto = item.get("text")
                loc = item.get("location")
                if texto:
                    if loc is not None:
                        errores.append(f"[{loc}] {texto}")
                    else:
                        errores.append(texto)

    if errores:
        print("[INFO] Mensajes del servidor:")
        for e in errores:
            print("  -", e)


def sendArmyPlunderLoop(session, event, stdin_fd, predetermined_input):
    """
    Fase interactiva (al inicio del proceso hijo):

      - Pide:
          * ciudad de origen
          * islandId destino
          * cityId destino
          * barcos
          * lanceros (315), hoplitas (303), morteros (305)
          * Poseidón sí/no
          * repeticiones e intervalo (minutos)
      - Muestra resumen
      - Llama a set_child_mode(session) y event.set()

    Fase background:

      - En cada iteración:
          1) (opcional) activa Poseidón
          2) fuerza cambio de ciudad a la ciudad de origen (changeCurrentCity)
          3) llama a sendArmyPlunderSea con los mismos parámetros
          4) muestra solo provideFeedback
          5) duerme X minutos y repite
    """

    # Fase interactiva
    sys.stdin = os.fdopen(stdin_fd)
    config.predetermined_input = predetermined_input

    banner()
    try:
        print("=== Saqueos automáticos por mar (sendArmyPlunderSea) ===\n")

        # ---------- Ciudad de ORIGEN ----------
        print("Ciudad de ORIGEN (desde donde salen las tropas):")
        originCity = chooseCity(session)
        originCityId = originCity["id"]
        originCityName = originCity["name"]
        banner()

        # ---------- Parámetros de destino y tropas ----------
        print("Ingrese el ID de la isla destino (islandId):")
        islandId = read(min=1, digit=True)

        print("Ingrese el ID de la ciudad destino (destinationCityId):")
        destinationCityId = read(min=1, digit=True)

        print("Barcos mercantes a enviar (transporter):")
        transporter = read(min=1, digit=True)

        # Orden pedido: 315 (lanceros), 303 (hoplitas), 305 (morteros)
        print("Lanceros a enviar (cargo_army_315):")
        lancers_315 = read(min=0, digit=True)

        print("Hoplitas a enviar (cargo_army_303):")
        hoplitas_303 = read(min=0, digit=True)

        print("Morteros a enviar (cargo_army_305):")
        morteros_305 = read(min=0, digit=True)

        print("¿Activar milagro Poseidón antes de cada envío? (Y|N)")
        poseidonAnswer = read(values=["y", "Y", "n", "N"])
        use_poseidon = poseidonAnswer.lower() == "y"

        print("¿Cuántas veces querés repetir el envío? (min = 1)")
        repetitions = read(min=1, digit=True)

        print("¿Cada cuántos minutos entre envíos? (min = 0)")
        interval_minutes = read(min=0, digit=True)
        interval_seconds = interval_minutes * 60

        print("\n=== RESUMEN CONFIGURACIÓN ===")
        print(f"Ciudad origen     = {originCityName} (id={originCityId})")
        print(f"islandId destino  = {islandId}")
        print(f"cityId destino    = {destinationCityId}")
        print(f"Mercantes         = {transporter}")
        print(f"Lanceros (315)    = {lancers_315}")
        print(f"Hoplitas (303)    = {hoplitas_303}")
        print(f"Morteros (305)    = {morteros_305}")
        print(f"Aldea bárbara     = 0")
        print(f"Repeticiones      = {repetitions}")
        print(f"Intervalo (min)   = {interval_minutes}")
        print(f"Poseidón          = {'Sí' if use_poseidon else 'No'}")

        enter()  # “Press enter to continue”

    except KeyboardInterrupt:
        event.set()
        return

    # ---------- Modo hijo / segundo plano ----------
    set_child_mode(session)
    event.set()  # handshake con el padre

    try:
        current_run = 0

        while repetitions > 0:
            current_run += 1
            repetitions -= 1

            status_text = (
                f"Saqueo automático {current_run} (restantes: {repetitions}) "
                f"desde {originCityName} hacia ciudad {destinationCityId}"
            )
            session.setStatus(status_text)
            print(f"\n=== Envío {current_run} ===")
            print(status_text)

            # 1) (Opcional) activar Poseidón
            if use_poseidon:
                _maybe_activate_poseidon(session)

            # 2) Re-seleccionar la ciudad de origen en Ikariam
            _select_origin_city(session, originCityId, islandId)

            # 3) Hacer el saqueo desde esa ciudad
            try:
                resp = _send_plunder(
                    session=session,
                    originCityId=originCityId,
                    islandId=islandId,
                    destinationCityId=destinationCityId,
                    transporter=transporter,
                    lancers_315=lancers_315,
                    hoplitas_303=hoplitas_303,
                    morteros_305=morteros_305,
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

            # 4) Mostrar solo errores / mensajes relevantes (provideFeedback)
            _mostrar_errores_provide_feedback(resp)

            # 5) Esperar para el próximo envío
            if repetitions > 0 and interval_seconds > 0:
                print(
                    f"[INFO] Esperando {interval_minutes} minuto(s) antes del próximo envío..."
                )
                time.sleep(interval_seconds)

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
