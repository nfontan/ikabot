#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import traceback

from requests import get, post
from requests.exceptions import ConnectTimeout, ReadTimeout, RequestException

from ikabot.config import *
from ikabot.helpers.dns import getAddresses
from ikabot.helpers.logging import getLogger

logger = getLogger(__name__)

_lastWorkingAddress = None


def _requestWithFailover(path, send):
    """Calls send(url) with each configured API address until one answers.
    An address is skipped on connection errors, timeouts and 5xx responses.
    The last address that worked is tried first on the next calls.
    Parameters
    ----------
    path : str
        API path, e.g. /v1/token
    send : callable
        function that receives the full url and returns a requests response

    Returns
    -------
    response : requests.Response
    """
    global _lastWorkingAddress
    addresses = getAddresses(publicAPIServerDomain)
    if _lastWorkingAddress in addresses:
        addresses.remove(_lastWorkingAddress)
        addresses.insert(0, _lastWorkingAddress)
    last_response = None
    last_error = None
    for address in addresses:
        try:
            response = send(address + path)
        except RequestException as e:
            last_error = e
            logger.warning("API address %s failed: %s", address, e)
            continue
        if response.status_code >= 500:
            last_response = response
            logger.warning("API address %s returned %s", address, response.status_code)
            continue
        _lastWorkingAddress = address
        return response
    if last_response is not None:
        return last_response
    raise last_error


def getNewBlackBoxToken(session):
    """This function returns a newly generated blackbox token from the API
    Parameters
    ----------
    session : ikabot.web.session.Session
        Session object

    Returns
    -------
    token : str
        blackbox token
    """
    user_agent = getattr(session, "api_user_agent", None) or session.user_agent
    params = {
        "user_agent": user_agent,
        "locale": session.locale,
        "timezone_id": session.timezone_id,
    }

    def send(url):
        response = get(
            url, params=params, verify=do_ssl_verify, timeout=blackboxTokenTimeout
        )
        if response.status_code in [400, 422]:
            fallback_params = {"user_agent": user_agent}
            response = get(
                url,
                params=fallback_params,
                verify=do_ssl_verify,
                timeout=blackboxTokenTimeout,
            )
        return response

    try:
        response = _requestWithFailover("/v1/token", send)
    except ConnectTimeout as exc:
        raise Exception(
            "The connection to the token API timed out after {}s".format(
                blackboxTokenTimeout[0]
            )
        ) from exc
    except ReadTimeout as exc:
        raise Exception(
            "The token API did not respond within {}s".format(blackboxTokenTimeout[1])
        ) from exc
    assert response.status_code == 200, (
        "API response code is not OK: "
        + str(response.status_code)
        + "\n"
        + response.text
    )
    response = response.json()
    if isinstance(response, dict):
        if response.get("status") == "error":
            raise Exception(response["message"])
        raise Exception("Unexpected API response: " + str(response))
    return "tra:" + response.replace("tra:", "")


def getPiratesCaptchaSolution(session, image):
    """This function returns the solution of the pirates captcha
    Parameters
    ----------
    session : ikabot.web.session.Session
        Session object
    image : bytes
        the image to be solved

    Returns
    -------
    solution : str
        solution of the captcha
    """
    files = {"image": image}
    response = _requestWithFailover(
        "/v1/decaptcha/pirate",
        lambda url: post(url, files=files, verify=do_ssl_verify, timeout=900),
    )
    assert response.status_code == 200, (
        "API response code is not OK: "
        + str(response.status_code)
        + "\n"
        + response.text
    )
    response = response.json()
    if "status" in response and response["status"] == "error":
        raise Exception(response["message"])
    return response
