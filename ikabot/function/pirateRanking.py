#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import sys
import json
import os
from datetime import datetime

from ikabot.config import *
from ikabot.helpers.getJson import *
from ikabot.helpers.gui import *
from ikabot.helpers.pedirInfo import getIdsOfCities
from ikabot.helpers.process import run, set_child_mode


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

    set_child_mode(session)
    event.set()

    try:
        do_it(session)
    except Exception as e:
        print("Error in pirateRanking: {}".format(e))
    finally:
        session.logout()


def do_it(session):
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
    # Use session.get() with the path - it appends to urlBase automatically
    path = "view=pirateFortress&cityId={}&position=17&activeTab=tabRanking&backgroundView=city&currentCityId={}&actionRequest={}&ajax=1".format(
        city_id, city_id, actionRequest
    )
    html = session.get(path)
    
    # Parse ranking data from the response
    ranking_data = parse_ranking(html)
    
    # Write to file
    report_path = "/tmp/pirate_ranking_report.txt"
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("Pirate Fortress Ranking Report\n")
        f.write("Generated: {}\n".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        f.write("City: {} (ID: {})\n".format(city_with_max["name"], city_id))
        f.write("Fortress Level: {}\n".format(max_level))
        f.write("=" * 50 + "\n\n")
        
        if ranking_data and "ranking" in ranking_data:
            ranking = ranking_data["ranking"]
            f.write("Ranking (showing {} players):\n\n".format(len(ranking)))
            f.write("{:<6} {:<30} {}\n".format("Pos", "Player Name", "Points"))
            f.write("-" * 50 + "\n")
            for entry in ranking:
                f.write("{:<6} {:<30} {}\n".format(
                    entry['position'],
                    entry['name'],
                    entry['points']
                ))
        elif ranking_data:
            f.write("Could not parse ranking data.\n")
            f.write(json.dumps(ranking_data, indent=2, ensure_ascii=False))
        else:
            f.write("Could not parse ranking data.\n")
            f.write("Raw HTML (first 10000 chars):\n")
            f.write(html[:10000])
    
    print("Report saved to: {}".format(report_path))


def parse_ranking_from_html(html):
    """Parse the ranking HTML to extract player positions, names, and points"""
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
    
    # Find all LI elements that contain ranking data
    # Each LI should have class="..." and contain place, pirateBooty, and userName
    li_pattern = r'<li[^>]*class="[^"]*"[^>]*>(.*?)</li>'
    li_matches = re.findall(li_pattern, ul_content, re.DOTALL)
    
    for li_content in li_matches:
        # Check if this LI has ranking data
        if 'class="place"' not in li_content and 'class="place"' not in ul_content:
            # Try to find place and pirateBooty in this LI or its context
            pass
        
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
        
        # Extract player name
        name = "Unknown"
        # Pattern 1: <span ... class="userName" title="...">
        name_match = re.search(r'<span[^>]*class="[^"]*userName[^"]*"[^>]*title="([^"]*)"', li_content)
        if not name_match:
            # Pattern 2: <a class="userName" ... title="...">
            name_match = re.search(r'<a[^>]*class="[^"]*userName[^"]*"[^>]*title="([^"]*)"', li_content)
        if not name_match:
            # Pattern 3: <a class="userName" ...>name</a>
            name_match = re.search(r'<a[^>]*class="[^"]*userName[^"]*"[^>]*>([^<]+)</a>', li_content)
        if name_match:
            name = name_match.group(1).strip()
        
        if pos_match and points_match:
            position = int(pos_match.group(1))
            points_str = points_match.group(1).replace(' ', '').replace('\xa0', '').replace(' ', '')
            try:
                points = int(points_str)
                ranking.append({
                    'position': position,
                    'name': name,
                    'points': points
                })
            except ValueError:
                pass
    
    return ranking if ranking else None


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
