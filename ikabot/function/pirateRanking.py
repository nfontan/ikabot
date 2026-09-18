#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# =============================================================================
# pirateRanking.py - Multi-Account Pastebin Architecture
# =============================================================================
# Multiple ikabot accounts share one Pastebin (registered) account to post
# ranking reports to a single paste. All accounts use the same paste title
# to locate and append to the same document.
#
# Flow per account:
#   1. Generate ranking report
#   2. Login to Pastebin (api_login.php) with shared credentials
#   3. List pastes by title, find the latest one
#   4. Fetch raw content of existing paste
#   5. Append new report content at the end
#   6. Create NEW paste with combined content and SAME title
#      (Pastebin API does not support editing; a new paste is created)
#   7. If configured (send_pastebin_telegram=True), send the new paste URL
#      to Telegram so the last account broadcasts the final link
#
# Scheduling:
#   All accounts can be scheduled at the SAME time (e.g. everyone at 13:00).
#   Right before touching the shared paste, each account acquires a small
#   distributed lock (itself a dedicated Pastebin paste titled
#   "<title> -- LOCK") so the read-append-create-delete cycle never overlaps
#   between accounts; whoever gets there first holds the lock while it
#   updates the paste, the rest wait their turn and retry. Manual staggering
#   is no longer required.
#
# Configuration per account:
#   pastebin_dev_key        API developer key (get it at https://pastebin.com/doc_api)
#   pastebin_user_name      Pastebin account username (shared across instances)
#   pastebin_user_key       User API key (get via api_login.php, never expires)
#   paste_title             Fixed title used to identify the shared paste
#   send_pastebin_telegram  True only for the last/stagger account to broadcast URL
# =============================================================================

import re
import sys
import json
import os
import random
import time
import hashlib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from ikabot.config import *
from ikabot.helpers.getJson import *
from ikabot.helpers.gui import *
from ikabot.helpers.pedirInfo import getIdsOfCities, read, enter
from ikabot.helpers.process import run, set_child_mode
from ikabot.helpers.botComm import sendToBot, checkTelegramData


def get_saved_pastebin_config(session):
    """Load saved Pastebin config from session data, or return None."""
    try:
        sessionData = session.getSessionData()
        return sessionData["shared"].get("pastebin")
    except Exception:
        return None


def ranking_fingerprint(ranking):
    """Stable fingerprint of a ranking's (position, name, points) triples, used
    to detect a fetch that came back suspiciously identical to a previous
    successful run (usually a sign the response was stale/cached rather than
    the ranking genuinely not moving)."""
    key = "|".join(
        "{}:{}:{}".format(e["position"], e["name"], e["points"]) for e in ranking
    )
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def get_last_ranking_snapshot(session):
    """Load this account's last successfully published ranking fingerprint/date."""
    try:
        sessionData = session.getSessionData()
        return sessionData.get("pirateRankingSnapshot")
    except Exception:
        return None


def save_ranking_snapshot(session, fingerprint):
    """Persist this account's ranking fingerprint so the next run can detect a stale repeat."""
    try:
        sessionData = session.getSessionData()
        sessionData["pirateRankingSnapshot"] = {
            "fingerprint": fingerprint,
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
        session.setSessionData(sessionData)
    except Exception:
        pass


def pirateRanking(session, event, stdin_fd, predetermined_input):
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
        print("=== Pirate Ranking Configuration ===\n")

        print("Output options:")
        print("(1) Save to file only")
        print("(2) Send to Telegram")
        print("(3) Send to Pastebin")
        print("(4) File + Telegram")
        print("(5) File + Pastebin")
        print("(6) Telegram + Pastebin")
        print("(7) All (File + Telegram + Pastebin)")
        output_option = read(min=1, max=7, digit=True)

        send_telegram = output_option in [2, 4, 6, 7]
        if send_telegram and checkTelegramData(session) is False:
            print("Telegram is not configured. Disabling Telegram output.")
            send_telegram = False
            if output_option == 2:
                output_option = 1
            elif output_option == 4:
                output_option = 1
            elif output_option == 6:
                output_option = 3
            elif output_option == 7:
                output_option = 1

        send_pastebin = output_option in [3, 5, 6, 7]
        save_file = output_option in [1, 4, 5, 7]

        pastebin_config = None
        if send_pastebin:
            saved = get_saved_pastebin_config(session)
            if saved:
                print("Pastebin configuration found. Press Enter to use saved data, or 'r' to reconfigure:")
                reconf = read()
                if reconf.lower() == 'r':
                    saved = None
                else:
                    print("Using saved Pastebin configuration.")
                    pastebin_config = saved
            if not saved:
                print("\n--- Pastebin Configuration ---")
                print("Get your API developer key at: https://pastebin.com/doc_api (login required)")
                print("Pastebin Developer API Key:")
                pastebin_dev_key = read()
                print("\nAPI User Key options:")
                print("(1) Use existing api_user_key (recommended)")
                print("(2) Generate new api_user_key (one-time setup with user/pass)")
                key_option = read(min=1, max=2, digit=True)
                if key_option == 1:
                    print("Pastebin User Key (does not expire):")
                    pastebin_user_key = read()
                    if not pastebin_user_key:
                        print("No key entered. Switching to generate mode...")
                        key_option = 2
                if key_option == 2:
                    print("Pastebin username:")
                    pastebin_user_name = read()
                    print("Pastebin password (will be visible):")
                    pastebin_user_password = read()
                    print("Logging in to Pastebin...")
                    try:
                        pastebin_user_key = pastebin_login(pastebin_dev_key, pastebin_user_name, pastebin_user_password)
                        print("Generated api_user_key: {}".format(pastebin_user_key))
                        print("Save this key for future use (does not expire).")
                    except Exception as e:
                        print("Login failed: {}".format(e))
                        pastebin_user_key = None
                if pastebin_user_key:
                    print("Paste title (e.g. 'Pirate Fortress Ranking'):")
                    paste_title = read()
                    print("\nPaste visibility:")
                    print("(0) Public - anyone can find it on Pastebin archive")
                    print("(1) Unlisted - anyone with the link can view (default)")
                    print("(2) Private - only logged in to the Pastebin account can view")
                    paste_private = read(min=0, max=2, digit=True)
                    print("Send final paste URL to Telegram after update? (y/n)")
                    send_pastebin_telegram = read().lower() == 'y'
                    pastebin_config = {
                        'dev_key': pastebin_dev_key,
                        'user_key': pastebin_user_key,
                        'title': paste_title,
                        'private': paste_private,
                        'send_telegram': send_pastebin_telegram,
                    }
                    session.setSessionData({"pastebin": pastebin_config}, shared=True)
                    print("Pastebin configuration saved.")
                else:
                    print("Pastebin configuration failed. Disabling Pastebin output.")

        print("\nExecution options:")
        print("(1) Run ranking now")
        print("(2) Schedule daily at HH:MM (24h format)")
        execution_option = read(min=1, max=2, digit=True)

        scheduled_time = None
        if execution_option == 2:
            print("\nEnter time to run daily (HH:MM, 24h format, e.g. 18:00):")
            while True:
                time_str = read()
                try:
                    parts = time_str.split(':')
                    hour = int(parts[0])
                    minute = int(parts[1])
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        scheduled_time = (hour, minute)
                        break
                    else:
                        print("Invalid time. Use HH:MM format (e.g. 18:00)")
                except (ValueError, IndexError):
                    print("Invalid format. Use HH:MM (e.g. 18:00)")

        print("\n=== Configuration Summary ===")
        print("Output: ", end="")
        outputs = []
        if save_file:
            outputs.append("File")
        if send_telegram:
            outputs.append("Telegram")
        if send_pastebin:
            outputs.append("Pastebin")
        print(", ".join(outputs))
        if send_pastebin:
            print("Pastebin title: {}".format(pastebin_config['title']))
        if execution_option == 1:
            print("Execution: Run once now")
        else:
            print("Execution: Daily at {:02d}:{:02d}".format(scheduled_time[0], scheduled_time[1]))
        print("=" * 30 + "\n")

        read()
    except KeyboardInterrupt:
        event.set()
        return

    set_child_mode(session)
    event.set()

    if execution_option == 2:
        # Rewrite our own processList entry so the main menu's running-task
        # table shows the scheduled time instead of just "pirateRanking",
        # same approach loadCustomModule.py uses to show its module name.
        try:
            sd = session.getSessionData()
            plist = sd.get("processList", [])
            my_pid = os.getpid()
            for p in plist:
                if p.get("pid") == my_pid:
                    p["action"] = "pirateRanking (daily {:02d}:{:02d})".format(
                        scheduled_time[0], scheduled_time[1]
                    )
                    break
            sd["processList"] = plist
            session.setSessionData(sd)
        except Exception:
            pass

    if execution_option == 1:
        try:
            do_it(session, save_file, send_telegram, send_pastebin, pastebin_config)
        except Exception as e:
            print("Error: {}".format(e))
        finally:
            session.logout()
    else:
        now = datetime.now()
        target = now.replace(hour=scheduled_time[0], minute=scheduled_time[1], second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        sleep_seconds = (target - now).total_seconds()
        print("Scheduled daily at {:02d}:{:02d}".format(scheduled_time[0], scheduled_time[1]))
        print("Next run in {:.1f} hours".format(sleep_seconds / 3600))
        print("Press Ctrl+C to stop")
        while True:
            try:
                time.sleep(sleep_seconds)
                do_it(session, save_file, send_telegram, send_pastebin, pastebin_config)
                sleep_seconds = 86400
            except KeyboardInterrupt:
                print("\nScheduler stopped.")
                break
            except Exception as e:
                print("Error in scheduled run: {}".format(e))
                time.sleep(60)
        session.logout()


def do_it(session, save_file=True, send_telegram=False, send_pastebin=False, pastebin_config=None):
    # Get all cities
    cities_ids = getIdsOfCities(session)[0]
    
    # Find the city with the highest level pirate fortress
    max_level = -1
    city_with_max = None
    
    for city_id in cities_ids:
        html = session.get(city_url + city_id)
        city = getCity(html)
        for pos, building in enumerate(city["position"]):
            if building["building"] == "pirateFortress":
                level = building.get("level", 0)
                if level > max_level:
                    max_level = level
                    city_with_max = city
                break
    
    if city_with_max is None:
        print("No pirate fortress found in any city")
        return
    
    city_id = city_with_max["id"]
    
    # Open pirate fortress and view ranking
    path = "view=pirateFortress&cityId={}&position=17&activeTab=tabRanking&backgroundView=city&currentCityId={}&actionRequest={}&ajax=1".format(
        city_id, city_id, actionRequest
    )
    html = session.post(path)
    
    # Parse ranking data from the response
    ranking_data = parse_ranking(html)

    # Detect a fetch that came back byte-identical to the last successful run
    # on a different day - almost always means we got a stale/cached response
    # rather than the ranking genuinely freezing (real Puntos de rapiña move
    # a lot day to day). If detected, we still write the local file below for
    # debugging, but we skip publishing it (Telegram/Pastebin) so a stale
    # report never overwrites good data on the shared paste.
    stale_detected = False
    new_fingerprint = None
    if ranking_data and "ranking" in ranking_data:
        new_fingerprint = ranking_fingerprint(ranking_data["ranking"])
        last_snapshot = get_last_ranking_snapshot(session)
        today_str = datetime.now().strftime("%Y-%m-%d")
        if (
            last_snapshot
            and last_snapshot.get("fingerprint") == new_fingerprint
            and last_snapshot.get("date") != today_str
        ):
            stale_detected = True
            print(
                "WARNING: ranking data is identical to the last successful run "
                "on {} - looks stale/cached, not a fresh fetch. Skipping "
                "Telegram/Pastebin publish for this run.".format(last_snapshot.get("date"))
            )

    # Check if ranking data is valid
    skip_coordinates = stale_detected
    if ranking_data and "ranking" in ranking_data and not stale_detected:
        ranking = ranking_data["ranking"]
        own_username = session.username if hasattr(session, 'username') else None

        # Check if own account has 0 points
        if own_username:
            for entry in ranking:
                if entry['name'] == own_username and entry['points'] == 0:
                    print("Account {} is in ranking with 0 points. Skipping coordinate collection.".format(own_username))
                    skip_coordinates = True
                    break
        
        # If no own account found but all players have 0 points, skip too
        if not skip_coordinates:
            all_zero = all(entry['points'] == 0 for entry in ranking)
            if all_zero and len(ranking) > 0:
                print("All players in ranking have 0 points. Skipping coordinate collection.")
                skip_coordinates = True
    elif not stale_detected:
        # If no ranking data or parsing failed, skip coordinates
        print("Ranking data could not be parsed or is invalid. Skipping coordinate collection.")
        skip_coordinates = True

    # Get coordinates for each player (skip if ranking seems invalid)
    if ranking_data and "ranking" in ranking_data and not skip_coordinates:
        ranking = ranking_data["ranking"]
        
        # For each player with cityId, get their island coordinates
        for entry in ranking:
            if 'cityId' in entry:
                # Random delay between 2-5 seconds to simulate human behavior
                delay = random.uniform(2, 5)
                time.sleep(delay)
                
                # Visit the player's island to get coordinates
                island_path = "view=island&cityId={}".format(entry['cityId'])
                try:
                    island_html = session.get(island_path)
                    coords = parse_island_coordinates(island_html)
                    if coords:
                        entry['x'] = coords['x']
                        entry['y'] = coords['y']
                        entry['island'] = coords.get('island_name', 'Unknown')
                except Exception as e:
                    print("Error getting coordinates for {}: {}".format(entry['name'], e))
    
    # Generate report content
    report_lines = []
    report_lines.append("Pirate Fortress Ranking Report")
    report_lines.append("Generated: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    report_lines.append("City: {} (ID: {})".format(city_with_max["name"], city_id))
    report_lines.append("Fortress Level: {}".format(max_level))
    # Add account name if available
    if hasattr(session, 'username') and session.username:
        report_lines.append("Account: {}".format(session.username))
    report_lines.append("=" * 50)
    report_lines.append("")
    
    if ranking_data and "ranking" in ranking_data:
        ranking = ranking_data["ranking"]
        report_lines.append("Ranking (showing {} players):".format(len(ranking)))
        report_lines.append("")
        report_lines.append("{:<6} {:<35} {:<12} {:<8} {:<8} {}".format("Pos", "Player Name", "Points", "X", "Y", "Island"))
        report_lines.append("-" * 85)
        for entry in ranking:
            x = entry.get('x', '?')
            y = entry.get('y', '?')
            island = entry.get('island', '?')
            name = entry['name']
            if entry.get('bold'):
                name = name + " (*)"
            report_lines.append("{:<6} {:<35} {:<12} {:<8} {:<8} {}".format(
                entry['position'],
                name,
                entry['points'],
                x,
                y,
                island
            ))
    else:
        report_lines.append("Ranking data is not available or could not be parsed.")
        if ranking_data and "error" in ranking_data:
            report_lines.append("Reason: {}".format(ranking_data["error"]))
        report_lines.append("Note: This may happen when your account has 0 points in ranking.")
    
    if stale_detected:
        report_lines.insert(
            0,
            "*** WARNING: this fetch is identical to a previous day's report - "
            "looks stale/cached, NOT published to Telegram/Pastebin. ***\n",
        )

    report_content = "\n".join(report_lines) + "\n"

    # Save to file. Named per account + timestamp (used to be a single fixed
    # path shared by every account, so whichever ran last silently overwrote
    # everyone else's local copy).
    if save_file:
        account_label = session.username if hasattr(session, 'username') and session.username else "account"
        safe_label = re.sub(r'[^A-Za-z0-9_-]+', '_', account_label)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = "/tmp/pirate_ranking_report_{}_{}.txt".format(safe_label, timestamp)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        print("Report saved to: {}".format(report_path))

    if stale_detected:
        # Don't touch Telegram or the shared Pastebin with data we don't
        # trust; the local file above still has it for debugging.
        print("Ranking update skipped (stale data).")
        return

    # Send to Telegram
    if send_telegram:
        try:
            sendToBot(session, report_content)
            print("Report sent to Telegram")
        except Exception as e:
            print("Error sending to Telegram: {}".format(e))

    # Send to Pastebin
    if send_pastebin and pastebin_config:
        try:
            paste_url = pastebin_append_or_create(
                pastebin_config['dev_key'],
                pastebin_config['user_key'],
                pastebin_config['title'],
                report_content,
                pastebin_config['private'],
            )
            print("Pastebin updated: {}".format(paste_url))
            if pastebin_config['send_telegram']:
                sendToBot(session, "Pirate Ranking updated on Pastebin: {}".format(paste_url))
        except Exception as e:
            print("Error sending to Pastebin: {}".format(e))

    if new_fingerprint:
        save_ranking_snapshot(session, new_fingerprint)

    print("Ranking update completed.")


# =============================================================================
# Pastebin API helpers
# =============================================================================

def pastebin_login(api_dev_key, api_user_name, api_user_password):
    """Login to Pastebin and return api_user_key."""
    url = 'https://pastebin.com/api/api_login.php'
    data = {
        'api_dev_key': api_dev_key,
        'api_user_name': api_user_name,
        'api_user_password': api_user_password,
    }
    resp = requests.post(url, data=data)
    if resp.text.startswith('Bad API request'):
        raise Exception("Pastebin login failed: {}".format(resp.text))
    return resp.text.strip()


def pastebin_list_pastes(api_dev_key, api_user_key):
    """List pastes for a Pastebin user, returns list of dicts sorted by date desc."""
    url = 'https://pastebin.com/api/api_post.php'
    data = {
        'api_dev_key': api_dev_key,
        'api_user_key': api_user_key,
        'api_option': 'list',
        'api_results_limit': 100,
    }
    resp = requests.post(url, data=data)
    if resp.text.startswith('Bad API request') or resp.text.startswith('No pastes found'):
        return []
    root = ET.fromstring('<pastes>' + resp.text + '</pastes>')
    pastes = []
    for paste_elem in root.findall('paste'):
        pastes.append({
            'key': paste_elem.findtext('paste_key', ''),
            'title': paste_elem.findtext('paste_title', ''),
            'date': int(paste_elem.findtext('paste_date', '0')),
            'url': paste_elem.findtext('paste_url', ''),
        })
    pastes.sort(key=lambda p: p['date'], reverse=True)
    return pastes


def pastebin_fetch_raw(api_dev_key, api_user_key, paste_key):
    """Fetch raw content of a paste by its key using the authenticated API (works for private pastes too)."""
    url = 'https://pastebin.com/api/api_raw.php'
    data = {
        'api_dev_key': api_dev_key,
        'api_user_key': api_user_key,
        'api_option': 'show_paste',
        'api_paste_key': paste_key,
    }
    resp = requests.post(url, data=data)
    if resp.text.startswith('Bad API request'):
        raise Exception("Pastebin fetch failed: {}".format(resp.text))
    return resp.text


def pastebin_create(api_dev_key, api_user_key, title, content, private=1):
    """Create a new paste, returns the paste URL."""
    url = 'https://pastebin.com/api/api_post.php'
    data = {
        'api_dev_key': api_dev_key,
        'api_user_key': api_user_key,
        'api_option': 'paste',
        'api_paste_code': content,
        'api_paste_name': title,
        'api_paste_private': str(private),
        'api_paste_expire_date': 'N',
        'api_paste_format': 'text',
    }
    resp = requests.post(url, data=data)
    if resp.text.startswith('Bad API request'):
        raise Exception("Pastebin create failed: {}".format(resp.text))
    return resp.text.strip()


def pastebin_delete(api_dev_key, api_user_key, paste_key):
    """Delete a paste by its key."""
    url = 'https://pastebin.com/api/api_post.php'
    data = {
        'api_dev_key': api_dev_key,
        'api_user_key': api_user_key,
        'api_option': 'delete',
        'api_paste_key': paste_key,
    }
    resp = requests.post(url, data=data)
    if resp.text.startswith('Bad API request'):
        raise Exception("Pastebin delete failed: {}".format(resp.text))
    return resp.text.strip()


def pastebin_acquire_lock(api_dev_key, api_user_key, title, timeout=900, poll_interval=(5, 15)):
    """
    Acquire a simple distributed lock so several accounts scheduled at the
    same time don't race each other's read-append-create-delete cycle on the
    shared paste. The lock itself is a dedicated Pastebin paste titled
    "<title> -- LOCK": whoever manages to be the sole/oldest holder of that
    paste owns the lock; everyone else polls and retries.

    Pastebin's API gives no atomic "create if not exists", so two accounts
    can still both create a lock paste in the same instant - if that happens,
    only the older one (by paste_date, tie-broken by paste_key) keeps it and
    the other deletes its own attempt and retries.

    Returns True once acquired, False if `timeout` seconds passed without it.
    """
    lock_title = title + " -- LOCK"
    holder_id = "{}-{}".format(os.getpid(), int(time.time() * 1000))
    deadline = time.time() + timeout
    while time.time() < deadline:
        pastes = pastebin_list_pastes(api_dev_key, api_user_key)
        locks = [p for p in pastes if p['title'] == lock_title]

        # A lock older than 10 minutes means its holder almost certainly
        # crashed mid-update instead of releasing it; clear it out so we
        # don't wait on a dead process forever.
        stale_cutoff = time.time() - 600
        stale_locks = [p for p in locks if p['date'] < stale_cutoff]
        active_locks = [p for p in locks if p['date'] >= stale_cutoff]
        for p in stale_locks:
            try:
                pastebin_delete(api_dev_key, api_user_key, p['key'])
            except Exception:
                pass

        if not active_locks:
            try:
                new_url = pastebin_create(api_dev_key, api_user_key, lock_title, holder_id, private=1)
                our_key = new_url.rstrip('/').rsplit('/', 1)[-1]
            except Exception:
                time.sleep(random.uniform(*poll_interval))
                continue

            # Give Pastebin's listing a moment to catch up, then check
            # whether anyone else grabbed the lock in the same instant.
            time.sleep(1.5)
            pastes = pastebin_list_pastes(api_dev_key, api_user_key)
            locks = [p for p in pastes if p['title'] == lock_title]
            locks.sort(key=lambda p: (p['date'], p['key']))
            if locks and locks[0]['key'] == our_key:
                return True
            # We lost the race - remove our attempt and retry.
            try:
                pastebin_delete(api_dev_key, api_user_key, our_key)
            except Exception:
                pass

        time.sleep(random.uniform(*poll_interval))

    return False


def pastebin_release_lock(api_dev_key, api_user_key, title):
    """Release the lock paste created by pastebin_acquire_lock."""
    lock_title = title + " -- LOCK"
    try:
        pastes = pastebin_list_pastes(api_dev_key, api_user_key)
        for p in pastes:
            if p['title'] == lock_title:
                pastebin_delete(api_dev_key, api_user_key, p['key'])
    except Exception:
        pass


def pastebin_append_or_create(api_dev_key, api_user_key, title, new_content, private=1):
    """
    Append new_content to the existing paste matching `title`, or create a new one.
    Deletes the old paste after successful creation.
    Returns the new paste URL.

    Guarded by pastebin_acquire_lock/pastebin_release_lock so several accounts
    scheduled at the same time queue up instead of racing each other.
    """
    if not pastebin_acquire_lock(api_dev_key, api_user_key, title):
        raise Exception(
            "Timed out waiting for the shared Pastebin lock ('{} -- LOCK'); "
            "another account may be stuck mid-update.".format(title)
        )

    try:
        pastes = pastebin_list_pastes(api_dev_key, api_user_key)

        existing = None
        for p in pastes:
            if p['title'] == title:
                existing = p
                break

        full_content = new_content
        if existing:
            try:
                old_content = pastebin_fetch_raw(api_dev_key, api_user_key, existing['key'])
                full_content = old_content.rstrip('\n') + '\n\n--- New Report ---\n\n' + new_content
            except Exception:
                pass

        new_url = pastebin_create(api_dev_key, api_user_key, title, full_content, private)

        if existing:
            try:
                pastebin_delete(api_dev_key, api_user_key, existing['key'])
            except Exception:
                pass

        return new_url
    finally:
        pastebin_release_lock(api_dev_key, api_user_key, title)


def parse_ranking_from_html(html):
    """Parse the ranking HTML to extract player positions, names, points, cityId, and bold status"""
    ranking = []
    
    # The HTML might be escaped in JSON - replace escaped characters
    html_decoded = html.replace('\\"', '"').replace('\\n', '\n').replace('\\/', '/')
    
    # Find the pirateHighscore UL element
    pattern = r'<ul id="pirateHighscore"[^>]*>(.*?)</ul>'
    match = re.search(pattern, html_decoded, re.DOTALL)
    
    if not match:
        # Try without decoding
        match = re.search(pattern, html, re.DOTALL)
        if match:
            html_decoded = html
        else:
            return None
    
    ul_content = match.group(1)
    
    # Find all LI elements with their full tag (including attributes)
    li_full_pattern = r'<li([^>]*)>(.*?)</li>'
    li_matches = re.findall(li_full_pattern, ul_content, re.DOTALL)
    
    for li_attrs, li_content in li_matches:
        # Check if this LI has ranking data
        if 'class="place"' not in li_content and 'class="place"' not in ul_content:
            continue
        
        # Extract position
        pos_match = re.search(r'<span class="place"[^>]*>(\d+)\s*\.</span>', li_content)
        if not pos_match:
            pos_match = re.search(r'class="place"[^>]*>(\d+)\s*\.', li_content)
        if not pos_match:
            continue
        
        # Extract points
        points_match = re.search(r'<span class="pirateBooty"[^>]*>([\d\s,]+?)\s*&nbsp;', li_content)
        if not points_match:
            continue
        
        # Check if bold (has "bold" in class attribute)
        is_bold = 'bold' in li_attrs
        
        # Extract player name and cityId
        name = "Unknown"
        city_id = None
        
        # Try to extract from <a> tag with onclick that contains cityId
        city_id_match = re.search(r'view=island&cityId=(\d+)', li_content)
        if city_id_match:
            city_id = int(city_id_match.group(1))
        
        # Extract player name
        name_match = re.search(r'<span[^>]*class="[^"]*userName[^"]*"[^>]*title="([^"]*)"', li_content)
        if not name_match:
            name_match = re.search(r'<a[^>]*class="[^"]*userName[^"]*"[^>]*title="([^"]*)"', li_content)
        if not name_match:
            name_match = re.search(r'<a[^>]*class="[^"]*userName[^"]*"[^>]*>([^<]+)</a>', li_content)
        if name_match:
            name = name_match.group(1).strip()
        
        if pos_match and points_match:
            position = int(pos_match.group(1))
            points_str = points_match.group(1).replace(' ', '').replace('\xa0', '').replace('\u00a0', '').replace(',', '')
            try:
                points = int(points_str)
                entry = {
                    'position': position,
                    'name': name,
                    'points': points,
                    'bold': is_bold
                }
                if city_id:
                    entry['cityId'] = city_id
                ranking.append(entry)
            except ValueError:
                pass
    
    return ranking if ranking else None


def parse_island_coordinates(html):
    """Parse island coordinates from the HTML response"""
    try:
        # First try to parse as JSON (AJAX response)
        try:
            data = json.loads(html)
            # Search for coordinates in the JSON structure
            def find_coords(obj):
                if isinstance(obj, dict):
                    if 'islandXCoord' in obj and 'islandYCoord' in obj:
                        return {
                            'x': obj['islandXCoord'],
                            'y': obj['islandYCoord'],
                            'island_name': obj.get('islandName', 'Unknown')
                        }
                    for v in obj.values():
                        result = find_coords(v)
                        if result:
                            return result
                elif isinstance(obj, list):
                    for item in obj:
                        result = find_coords(item)
                        if result:
                            return result
                return None
            
            result = find_coords(data)
            if result:
                return result
        except json.JSONDecodeError:
            pass
        
        # If not JSON, try to extract from HTML
        # Pattern: "islandXCoord":"41","islandYCoord":"11"
        x_match = re.search(r'"islandXCoord"\s*:\s*"(\d+)"', html)
        y_match = re.search(r'"islandYCoord"\s*:\s*"(\d+)"', html)
        name_match = re.search(r'"islandName"\s*:\s*"([^"]+)"', html)
        
        if x_match and y_match:
            return {
                'x': x_match.group(1),
                'y': y_match.group(1),
                'island_name': name_match.group(1) if name_match else 'Unknown'
            }
        
        return None
    except Exception as e:
        return None


def parse_ranking(html):
    """Parse the ranking data from the pirate fortress response"""
    try:
        # The response is a JSON array like: [["updateGlobalData", {...}], ["changeView", ["pirateFortress", "<html>", ...]]]
        data = json.loads(html)
        
        # Get the HTML from the response - try multiple strategies
        html_content = None
        
        # Strategy 1: look for ["changeView", ["pirateFortress", "<html>", ...]]
        for item in data:
            if isinstance(item, list) and len(item) >= 2:
                if item[0] == "changeView":
                    if isinstance(item[1], list) and len(item[1]) > 1:
                        html_content = item[1][1] if isinstance(item[1][1], str) else None
                        break
                    # Try other positions
                    for pos in range(1, len(item)):
                        if isinstance(item[pos], str) and len(item[pos]) > 100:
                            html_content = item[pos]
                            break
        
        # Strategy 2: look for any item with "pirateFortress" or "pirateHighscore" in it
        if not html_content:
            for item in data:
                if isinstance(item, list):
                    for sub in item:
                        if isinstance(sub, str) and ("pirateFortress" in sub or "pirateHighscore" in sub):
                            html_content = sub
                            break
        
        # Strategy 3: look for the longest string in the response
        if not html_content:
            candidates = []
            def find_strings(obj, depth=0):
                if depth > 5:
                    return
                if isinstance(obj, str) and len(obj) > 200:
                    candidates.append(obj)
                elif isinstance(obj, list):
                    for item in obj:
                        find_strings(item, depth+1)
                elif isinstance(obj, dict):
                    for v in obj.values():
                        find_strings(v, depth+1)
            find_strings(data)
            if candidates:
                candidates.sort(key=len, reverse=True)
                html_content = candidates[0]
                print(
                    "WARNING: ranking view not found via the primary/secondary "
                    "strategies; falling back to 'longest string in response' "
                    "heuristic. Parsed data may be unreliable."
                )
        
        if html_content:
            # Parse the HTML to extract ranking
            ranking = parse_ranking_from_html(html_content)
            if ranking:
                return {"ranking": ranking}

        # If we couldn't parse, return the raw HTML for debugging
        return {"error": "Could not parse ranking", "html_preview": html[:2000]}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e), "raw": html[:2000]}
