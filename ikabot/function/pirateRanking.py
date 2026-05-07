#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import sys
import json
import os
import random
import time
from datetime import datetime

from ikabot.config import *
from ikabot.helpers.getJson import *
from ikabot.helpers.gui import *
from ikabot.helpers.pedirInfo import getIdsOfCities, read, enter
from ikabot.helpers.process import run, set_child_mode
from ikabot.helpers.botComm import sendToBot, checkTelegramData


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
        print("(3) Send to Pastebin (TODO)")
        print("(4) File + Telegram")
        print("(5) File + Pastebin (TODO)")
        print("(6) Telegram + Pastebin (TODO)")
        print("(7) All (File + Telegram + Pastebin) (TODO)")
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

        print("\nExecution options:")
        print("(1) Run ranking now")
        print("(2) Schedule ranking every X hours")
        execution_option = read(min=1, max=2, digit=True)

        interval_hours = None
        if execution_option == 2:
            print("\nRun every how many hours? (minimum 1)")
            interval_hours = read(min=1, digit=True)

        print("\n=== Configuration Summary ===")
        print("Output: ", end="")
        outputs = []
        if save_file:
            outputs.append("File")
        if send_telegram:
            outputs.append("Telegram")
        if send_pastebin:
            outputs.append("Pastebin (TODO)")
        print(", ".join(outputs))
        if execution_option == 1:
            print("Execution: Run once now")
        else:
            print("Execution: Every {} hour(s)".format(interval_hours))
        print("=" * 30 + "\n")

        enter()

        set_child_mode(session)
        event.set()

        if execution_option == 1:
            do_it(session, save_file, send_telegram, send_pastebin)
        else:
            print("Scheduling pirate ranking every {} hour(s)".format(interval_hours))
            print("Press Ctrl+C to stop")
            while True:
                try:
                    do_it(session, save_file, send_telegram, send_pastebin)
                    print("\nWaiting {} hour(s) for next run...".format(interval_hours))
                    time.sleep(interval_hours * 3600)
                except KeyboardInterrupt:
                    print("\nScheduler stopped.")
                    break
                except Exception as e:
                    print("Error in scheduled run: {}".format(e))
                    time.sleep(60)

    except KeyboardInterrupt:
        event.set()
        return
    except Exception as e:
        print("Error in pirateRanking: {}".format(e))
    finally:
        session.logout()


def do_it(session, save_file=True, send_telegram=False, send_pastebin=False):
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
    html = session.get(path)
    
    # Parse ranking data from the response
    ranking_data = parse_ranking(html)

    # Check if ranking data is valid
    skip_coordinates = False
    if ranking_data and "ranking" in ranking_data:
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
    else:
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
        # Simplified error message (no HTML/JSON dump)
        report_lines.append("Ranking data is not available or could not be parsed.")
        if ranking_data and "error" in ranking_data:
            report_lines.append("Reason: {}".format(ranking_data["error"]))
        report_lines.append("Note: This may happen when your account has 0 points in ranking.")
    
    report_content = "\n".join(report_lines) + "\n"
    
    # Save to file
    if save_file:
        report_path = "/tmp/pirate_ranking_report.txt"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        print("Report saved to: {}".format(report_path))
    
    # Send to Telegram
    if send_telegram:
        try:
            sendToBot(session, report_content)
            print("Report sent to Telegram")
        except Exception as e:
            print("Error sending to Telegram: {}".format(e))
    
    # Send to Pastebin (TODO)
    if send_pastebin:
        print("Pastebin support not implemented yet")
    
    print("Ranking update completed.")


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
    # Pattern to capture the entire LI tag with attributes and content
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
        points_match = re.search(r'<span class="pirateBooty"[^>]*>([\d\s]+?)\s*&nbsp;', li_content)
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
            points_str = points_match.group(1).replace(' ', '').replace('\xa0', '').replace(' ', '')
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
        
        # Get the HTML from the response - it's in ["changeView"][1][1]
        html_content = None
        for item in data:
            if isinstance(item, list) and len(item) == 2:
                if item[0] == "changeView" and isinstance(item[1], list) and len(item[1]) > 1:
                    html_content = item[1][1] if isinstance(item[1][1], str) else None
                    break
        
        if html_content:
            # Parse the HTML to extract ranking
            ranking = parse_ranking_from_html(html_content)
            if ranking:
                return {"ranking": ranking}
        
        # If we couldn't parse, return the raw HTML for debugging
        return {"error": "Could not parse ranking", "html_preview": html[:2000]}
    except Exception as e:
        return {"error": str(e), "raw": html[:2000]}
