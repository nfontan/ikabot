#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import re

import ikabot.config as config
from ikabot.config import *
from ikabot.helpers.decorators import configurator
from ikabot.helpers.getJson import getCity
from ikabot.helpers.gui import *
from ikabot.helpers.pedirInfo import read


def activateVacationMode(session):
    """
    Parameters
    ----------
    session : ikabot.web.session.Session
    """
    html = session.get()
    city = getCity(html)
    token = re.search(r'actionRequest"?:\s*"(.*?)"', html).group(1)

    data = {
        "action": "Options",
        "function": "activateVacationMode",
        "actionRequest": token,
        "backgroundView": "city",
        "currentCityId": city["id"],
        "templateView": "options_umod_confirm",
    }
    # Activating vacation mode ends the game session, so the server answers by
    # sending us back to the lobby. session.post() takes that as the session
    # being taken over and closes all of ikabot (menu and running tasks) before
    # returning, even with ignoreExpire=True. Send it through the underlying
    # requests session instead, without following the redirect.
    response = session.s.post(
        session.urlBase,
        params=data,
        verify=config.do_ssl_verify,
        timeout=300,
        allow_redirects=False,
    )
    session.logger.info(
        "activateVacationMode: status {} location {}".format(
            response.status_code, response.headers.get("Location", "")
        )
    )

    # the action used up the token, don't let other processes reuse it
    sessionData = session.getSessionData()
    if sessionData.pop("actionRequestToken", None) is not None:
        sessionData.pop("shared", None)
        session.setSessionData(sessionData)


@configurator
def vacationMode(session, event, stdin_fd, predetermined_input):
    """
    Parameters
    ----------
    session : ikabot.web.session.Session
    event : multiprocessing.Event
    stdin_fd: int
    predetermined_input : multiprocessing.managers.SyncManager.list
    """
    banner()
    print("Activate vacation mode? [Y/n]")
    rta = read(values=["y", "Y", "n", "N", ""])
    if rta.lower() == "n":
        return

    activateVacationMode(session)

    print("Vacation mode has been activated.")
    enter()
