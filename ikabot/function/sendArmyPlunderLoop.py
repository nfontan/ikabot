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


def _send_plunder(
    session,
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
    Usa el actionRequest global de ikabot.config.
    """

    params = {
        "action": "transportOperations",
        "function": "sendArmyPlunderSea",

        "islandId": islandId,
        "destinationCityId": destinationCityId,

        # Lanceros (315)
        "cargo_army_315_upkeep": 0,   # podés ajustar el upkeep real si querés
        "cargo_army_315": lancers_315,

        # Hoplitas (303)
        "cargo_army_303_upkeep": 3,
        "cargo_army_303": hoplitas_303,

        # Morteros (305)
        "cargo_army_305_upkeep": 30,
        "cargo_army_305": morteros_305,

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

        # Token CSRF global
        "actionRequest": actionRequest,
    }

    resp = session.post(params=params, noIndex=True)
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


def _mostrar_errores_provide_feedback(raw_response):
    """
    Recibe el texto devuelto por session.post (JSON Ikariam),
    busca la sección ['provideFeedback', [...]] y muestra solo los textos de error.
    """
    try:
        data = json.loads(raw_response, strict=False)
    except Exception:
        # Si no podemos parsear, no spameamos; mostramos solo un recorte chico
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
    Igual estilo que autoPirate / constructBuilding:

      - Fase interactiva (en el proceso hijo al principio):
          * redirige stdin
          * usa banner(), read(), chooseCity(), enter()
          * al final llama set_child_mode(session) y event.set()

      - Fase background:
          * hace los saqueos en loop
          * NO usa event como kill switch (igual que autoPirate)
          * usa session.setStatus() para ver estado en el menú
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
    event.set()  # handshake con el padre, igual que autoPirate

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

            if use_poseidon:
                _maybe_activate_poseidon(session)

            # Hacemos el saqueo
            try:
                resp = _send_plunder(
                    session=session,
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

            # Mostrar solo errores relevantes (provideFeedback)
            _mostrar_errores_provide_feedback(resp)

            # Si todavía quedan envíos, esperamos
            if repetitions > 0 and interval_seconds > 0:
                print(
                    f"[INFO] Esperando {interval_minutes} minuto(s) antes del próximo envío..."
                )
                # Igual que autoPirate: no miramos event.is_set() aquí
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
