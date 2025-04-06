import requests
import json
import os
import re
import csv
from datetime import datetime
from collections import defaultdict

# Constants
BOOTSTRAP_API_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
GAMEWEEK_API_URL = "https://fantasy.premierleague.com/api/event/{}/live/"
PHASES = {
    1: range(1, 12),  # 1-11
    2: range(12, 21),  # 12-20
    3: range(21, 25),  # 21-24
    4: range(25, 30),  # 25-29
    5: range(30, 39),  # 30-38
}
TEAM_MAPPING = {
    1: "ARS", 2: "AVL", 3: "BOU", 4: "BRE", 5: "BHA",
    6: "CHE", 7: "CRY", 8: "EVE", 9: "FUL", 10: "IPS",
    11: "LEI", 12: "LIV", 13: "MCI", 14: "MUN", 15: "NEW",
    16: "NFO", 17: "SOU", 18: "TOT", 19: "WHU", 20: "WOL"
}
POSITION_MAPPING = {
    1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"
}

# Point corrections - format: (player_id, phase, adjustment)
POINT_CORRECTIONS = [
    (218, 4, 8),   # Add 8 points to player ID 218 in Phase 4
    (324, 3, -1),  # Subtract 1 point from player ID 324 in Phase 3
    (450, 4, 1)    # Add 1 point to player ID 450 in Phase 4
]

# Cache settings
CACHE_DIR = "cache"
CACHE_EXPIRY_HOURS = 24  # Cache expiry time in hours
STANDINGS_FILE = os.path.join(CACHE_DIR, "previous_standings.json")  # File to store previous gameweek standings

# Data storage
player_data = {}
teams_data = {}
manager_squads = {}
gameweek_data = {}
current_gameweek = 0
previous_standings = {}  # Store previous gameweek standings

# Ensure cache directory exists
def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

# Cache management functions
def get_cached_data(cache_key):
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
    
    if os.path.exists(cache_file):
        # Check if cache is expired
        file_time = os.path.getmtime(cache_file)
        current_time = datetime.now().timestamp()
        cache_age_hours = (current_time - file_time) / 3600
        
        if cache_age_hours < CACHE_EXPIRY_HOURS:
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                print(f"Warning: Cache file {cache_file} is corrupted, will fetch fresh data")
    
    return None

def save_to_cache(cache_key, data):
    ensure_cache_dir()
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
    
    try:
        with open(cache_file, 'w') as f:
            json.dump(data, f)
    except IOError as e:
        print(f"Warning: Failed to write to cache: {e}")

# Parse CSV squads file
def parse_csv_squads_file(filename):
    """Parse a CSV file containing squad data for each manager in each phase."""
    squads = {}
    current_phase = None
    
    try:
        print(f"Reading squad data from {filename}...")
        with open(filename, 'r') as file:
            reader = csv.reader(file)
            for row in reader:
                if not row or all(cell.strip() == '' for cell in row):  # Skip empty rows
                    continue
                    
                # Check if this is a phase header row
                if len(row) == 1 and "phase" in row[0].lower():
                    try:
                        current_phase = int(row[0].strip().split()[1])
                        print(f"Found Phase {current_phase}")
                    except (IndexError, ValueError):
                        print(f"Warning: Invalid phase row: {row}")
                        continue
                
                # If we have a manager row (manager name and squad)
                elif len(row) >= 2 and current_phase is not None:
                    manager_name = row[0].strip()
                    if manager_name.endswith(':'):
                        manager_name = manager_name[:-1]
                    
                    # Join all the remaining columns to handle cases where player IDs might be in separate columns
                    player_ids_text = ','.join([cell.strip() for cell in row[1:] if cell.strip()])
                    try:
                        # Split by commas and convert to integers
                        player_ids = [int(pid.strip()) for pid in player_ids_text.split(',') if pid.strip()]
                        if player_ids:
                            # Create manager entry if not exists
                            if manager_name not in squads:
                                squads[manager_name] = {}
                            
                            # Store player IDs for this phase
                            squads[manager_name][current_phase] = player_ids
                            print(f"Added {len(player_ids)} players for {manager_name} in Phase {current_phase}")
                    except ValueError as e:
                        print(f"Warning: Invalid player IDs for manager {manager_name}: {player_ids_text} - {str(e)}")
        
        if not squads:
            print("WARNING: No manager squads were parsed from the CSV file!")
            print("Please ensure your file is in the correct format with Phase headers and manager data.")
            print("For guidance, see the example_squads.csv file.")
            # DO NOT create an example file here - just provide guidance
            
    except FileNotFoundError:
        print(f"Warning: Squad file '{filename}' not found.")
        # Only create an example if it's not Squads.csv (don't overwrite user's file)
        if filename != "Squads.csv":
            create_example_csv() 
        else:
            print("Please create a Squads.csv file or use the example_squads.csv as a template.")
    except Exception as e:
        print(f"Error parsing squad file: {e}")
        print("Please check your file format. See example_squads.csv for the correct format.")
        
    return squads

# Parses the Squads.txt file to extract manager squad data (legacy support)
def parse_squads_file(file_path):
    squads = {}
    current_phase = None
    
    try:
        # Read the file and parse content
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                
                if not line:
                    continue
                
                # Check if this is a phase header
                phase_match = re.match(r'Phase (\d+)', line)
                if phase_match:
                    current_phase = int(phase_match.group(1))
                    print(f"Found Phase {current_phase}")
                    continue
                
                # Parse manager and squad
                manager_match = re.match(r'([^:]+):\s*(.+)', line)
                if manager_match and current_phase:
                    manager_name = manager_match.group(1).strip()
                    player_ids_text = manager_match.group(2).strip()
                    try:
                        player_ids = [int(pid.strip()) for pid in player_ids_text.split(',') if pid.strip()]
                        
                        if manager_name not in squads:
                            squads[manager_name] = {}
                        
                        squads[manager_name][current_phase] = player_ids
                        print(f"Added {len(player_ids)} players for {manager_name} in Phase {current_phase}")
                    except ValueError as e:
                        print(f"Warning: Invalid player IDs for manager {manager_name}: {player_ids_text} - {str(e)}")
    
        if not squads:
            print("WARNING: No manager squads were parsed from the file!")
    except FileNotFoundError:
        print(f"Warning: Squad file '{file_path}' not found.")
    except Exception as e:
        print(f"Error parsing squad file: {e}")
    
    return squads

# Create an example CSV file to help users understand the format
def create_example_csv():
    example_file = "example_squads.csv"
    # Never overwrite Squads.csv, only create the example file
    if not os.path.exists(example_file):
        try:
            with open(example_file, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["Phase 1"])
                writer.writerow(["Manager1", "1,2,3,4,5,6,7,8,9,10,11"])
                writer.writerow(["Manager2", "20,21,22,23,24,25,26,27,28,29,30"])
                writer.writerow([])  # Empty row
                writer.writerow(["Phase 2"])
                writer.writerow(["Manager1", "5,6,7,8,9,10,11,12,13,14,15"])
                writer.writerow(["Manager2", "25,26,27,28,29,30,31,32,33,34,35"])
            
            print(f"Created example CSV file '{example_file}'. You can use this as a template.")
            print("You can use 'python player_lookup.py' to find valid player IDs.")
        except Exception as e:
            print(f"Error creating example CSV file: {e}")
    else:
        print(f"Example file '{example_file}' already exists. You can use this as a template.")

# Fetch data from the Premier League API
def fetch_bootstrap_data():
    # Always fetch fresh bootstrap data to ensure current gameweek is accurate
    print("🔄 FRESH DATA: Fetching bootstrap data from API...")
    try:
        response = requests.get(BOOTSTRAP_API_URL)
        data = response.json()
        
        # Save to cache for fallback
        save_to_cache("bootstrap", data)
        
        return data
    except Exception as e:
        print(f"❌ ERROR: Failed to fetch fresh bootstrap data: {e}")
        print("⚠️ WARNING: Attempting to use cached data as fallback...")
        
        # Use cache as fallback
        cached_data = get_cached_data("bootstrap")
        if cached_data:
            print("📋 CACHED: Using cached bootstrap data")
            return cached_data
        else:
            print("❌ ERROR: No cached data available. Cannot proceed.")
            raise e

def fetch_gameweek_data(gameweek):
    # For the two most recent gameweeks, always fetch fresh data
    if current_gameweek > 0 and gameweek >= current_gameweek - 1:
        print(f"🔄 FRESH DATA: Fetching gameweek {gameweek} directly from API (recent gameweek)")
        url = GAMEWEEK_API_URL.format(gameweek)
        response = requests.get(url)
        data = response.json()
        
        # Still save to cache for future use
        save_to_cache(f"gameweek_{gameweek}", data)
        
        return data
    
    # For older gameweeks, check cache first
    cached_data = get_cached_data(f"gameweek_{gameweek}")
    if cached_data:
        print(f"📋 CACHED: Using cached data for gameweek {gameweek}")
        return cached_data
    
    print(f"🔄 FRESH DATA: Fetching gameweek {gameweek} from API (no cache available)")
    url = GAMEWEEK_API_URL.format(gameweek)
    response = requests.get(url)
    data = response.json()
    
    # Save to cache
    save_to_cache(f"gameweek_{gameweek}", data)
    
    return data

# Process player data from bootstrap API
def process_player_data(bootstrap_data):
    players = {}
    
    for player in bootstrap_data['elements']:
        player_id = player['id']  # Ensure we use the correct ID format
        players[player_id] = {
            'id': player_id,
            'name': player['web_name'],
            'position': POSITION_MAPPING.get(player['element_type'], 'Unknown'),
            'team': TEAM_MAPPING.get(player['team'], 'Unknown'),
            'points_by_gameweek': {}
        }
    
    if not players:
        print("WARNING: No player data was processed from the API!")
    
    return players

# Process gameweek data from API
def process_gameweek_data(gw_data):
    points = {}
    
    if 'elements' not in gw_data:
        print(f"WARNING: Gameweek data doesn't contain 'elements' key")
        print(f"Available keys: {list(gw_data.keys())}")
        return points
    
    for player in gw_data['elements']:
        player_id = player['id']
        
        # Ensure the stats key exists and contains total_points
        if 'stats' in player and 'total_points' in player['stats']:
            total_points = player['stats']['total_points']
            points[player_id] = total_points
            
            # Update player data
            if player_id in player_data:
                player_data[player_id]['points_by_gameweek'][current_gameweek] = total_points
    
    if not points:
        print(f"WARNING: No player points data found for gameweek {current_gameweek}")
    
    return points

# Calculate points for each manager for each phase and total
def calculate_manager_points():
    """Calculate points for each manager based on their squad and gameweek data."""
    manager_points = {}
    phase_points = {}
    highest_gameweek_manager = None
    highest_gameweek_points = 0
    
    if not manager_squads:
        print("Warning: No manager squad data available.")
        return {}, {}, None, 0
    
    if not gameweek_data:
        print("Warning: No gameweek data available.")
        return {}, {}, None, 0
    
    # Calculate raw points for each manager and phase
    for manager, phases in manager_squads.items():
        manager_points[manager] = {'total': 0}
        phase_points[manager] = {}
        
        for phase_num, player_ids in phases.items():
            phase_points[manager][phase_num] = 0
            
            for gw in PHASES[phase_num]:
                if gw in gameweek_data:
                    gw_points = 0
                    
                    for player_id in player_ids:
                        if player_id in gameweek_data[gw]:
                            gw_points += gameweek_data[gw][player_id]
                        else:
                            # Debug info for missing player points
                            if gw == current_gameweek:
                                player_name = player_data.get(player_id, {}).get('name', f"Unknown (ID: {player_id})")
                                print(f"Player {player_name} (ID: {player_id}) has no points for gameweek {gw}")
                    
                    phase_points[manager][phase_num] += gw_points
                    
                    # Check if this is the most recent gameweek
                    if gw == current_gameweek:
                        if gw_points > highest_gameweek_points:
                            highest_gameweek_points = gw_points
                            highest_gameweek_manager = manager
    
    # Apply point corrections
    for player_id, phase, adjustment in POINT_CORRECTIONS:
        for manager, phases in manager_squads.items():
            if phase in phases and player_id in phases[phase]:
                # Apply the correction to this manager's phase points
                phase_points[manager][phase] += adjustment
    
    # Calculate total points
    for manager, phases in phase_points.items():
        manager_points[manager]['total'] = sum(phases.values())
        for phase, points in phases.items():
            manager_points[manager][f'phase_{phase}'] = points
    
    return manager_points, phase_points, highest_gameweek_manager, highest_gameweek_points

# Load previous gameweek standings
def load_previous_standings():
    """Load previous gameweek standings from cache file."""
    if os.path.exists(STANDINGS_FILE):
        try:
            with open(STANDINGS_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            print(f"Warning: Previous standings file {STANDINGS_FILE} is corrupted")
    return {}

# Save current standings for future comparison
def save_current_standings(manager_points):
    """
    Save current standings for comparison in the next update.
    
    This function creates a JSON file with the current gameweek standings,
    which will be used in the next run to determine position changes (up/down arrows).
    Each manager's position is stored based on their total points.
    """
    ensure_cache_dir()
    
    standings = {
        "gameweek": current_gameweek,
        "standings": {}
    }
    
    # Sort managers by total points (highest first)
    sorted_managers = sorted(manager_points.items(), key=lambda x: x[1]['total'], reverse=True)
    
    # Store position for each manager
    for position, (manager, _) in enumerate(sorted_managers, 1):
        standings["standings"][manager] = position
    
    try:
        with open(STANDINGS_FILE, 'w') as f:
            json.dump(standings, f)
    except IOError as e:
        print(f"Warning: Failed to write standings to cache: {e}")

# Calculate recent gameweek points for a manager
def calculate_recent_gameweek_points(manager, phase_points):
    """Calculate points for the most recent gameweek for a manager."""
    if current_gameweek == 0:
        return 0
    
    # Find the phase that contains the current gameweek
    current_phase = None
    for phase, gameweeks in PHASES.items():
        if current_gameweek in gameweeks:
            current_phase = phase
            break
    
    if not current_phase or current_phase not in phase_points.get(manager, {}):
        print(f"WARNING: Could not determine phase for gameweek {current_gameweek}")
        return 0
    
    recent_points = 0
    
    # Get the current manager's squad
    if manager in manager_squads and current_phase in manager_squads[manager]:
        players = manager_squads[manager][current_phase]
        
        # Calculate points for these players in the current gameweek
        for player_id in players:
            if current_gameweek in gameweek_data and player_id in gameweek_data[current_gameweek]:
                recent_points += gameweek_data[current_gameweek][player_id]
            else:
                # Debug info for missing player points
                player_name = player_data.get(player_id, {}).get('name', f"Unknown (ID: {player_id})")
                print(f"Player {player_name} (ID: {player_id}) has no points for gameweek {current_gameweek}")
        
        # Apply any point corrections for the current phase
        for player_id, phase, adjustment in POINT_CORRECTIONS:
            if phase == current_phase and player_id in players:
                recent_points += adjustment
    
    return recent_points

# Generate HTML for the main league table
def generate_league_table(manager_points, phase_points, debug_mode=False):
    # Use the global previous_standings that was calculated or loaded in test mode
    global previous_standings
    
    prev_positions = previous_standings.get("standings", {})
    prev_gameweek = previous_standings.get("gameweek", 0)
    
    if debug_mode:
        print(f"Previous standings from gameweek {prev_gameweek}: {len(prev_positions)} managers")
    
    # Sort managers by total points (highest first)
    sorted_managers = sorted(manager_points.items(), key=lambda x: x[1]['total'], reverse=True)
    
    if not sorted_managers:
        return "<p>No manager data available to generate league table.</p>"
    
    # Calculate phase 1 diffs for all managers to determine the rank
    phase1_diffs = {}
    for manager, points in manager_points.items():
        # Calculate difference from Phase 1 squad performance
        phase1_squad_performance = 0
        for gw in range(1, current_gameweek + 1):
            if gw in gameweek_data:
                for player_id in manager_squads[manager].get(1, []):  # Phase 1 squad
                    if player_id in gameweek_data[gw]:
                        phase1_squad_performance += gameweek_data[gw][player_id]
        
        diff_from_phase1 = points['total'] - phase1_squad_performance
        phase1_diffs[manager] = diff_from_phase1
    
    # Sort managers by their phase 1 diff (highest first) to get the rankings
    diff_rankings = {manager: rank for rank, (manager, _) in 
                     enumerate(sorted(phase1_diffs.items(), key=lambda x: x[1], reverse=True), 1)}
    
    html = """
    <table class="league-table">
        <thead>
            <tr>
                <th>Position</th>
                <th>Manager</th>
                <th>Total Points</th>
                <th>Weekly Points</th>
                <th>Gap to Above</th>
                <th>Gap to Top</th>
                <th>WD Points</th>
                <th>WD Pos</th>
            </tr>
        </thead>
        <tbody>
    """
    
    # Get the manager with the highest weekly points
    # First, calculate weekly points for all managers
    weekly_points = {}
    highest_weekly_points = 0
    weekly_points_manager = None
    
    for manager in manager_points:
        recent_gw_points = calculate_recent_gameweek_points(manager, phase_points)
        weekly_points[manager] = recent_gw_points
        
        # Track manager with highest weekly points
        if recent_gw_points > highest_weekly_points:
            highest_weekly_points = recent_gw_points
            weekly_points_manager = manager
    
    # Get the top manager (highest total points) - will be the first in sorted_managers
    top_manager = sorted_managers[0][0] if sorted_managers else None
    top_points = sorted_managers[0][1]['total'] if sorted_managers else 0
    previous_points = top_points
    
    # Create a current standings dictionary for comparison
    current_standings = {}
    for position, (manager, _) in enumerate(sorted_managers, 1):
        current_standings[manager] = position
    
    for position, (manager, points) in enumerate(sorted_managers, 1):
        # Calculate position change since last gameweek
        position_change = ""
        
        if manager in prev_positions:
            prev_pos = prev_positions[manager]
            
            if debug_mode:
                print(f"Manager {manager}: Current pos = {position}, Prev pos = {prev_pos}")
            
            # Position 1 is best (top of table), so:
            # - Moving UP means going from a higher position number to a lower one
            # - Moving DOWN means going from a lower position number to a higher one
            if prev_pos > position:
                # Moved up (from higher position number to lower position number is better)
                position_change = f'<span class="position-up">▲</span>'
                if debug_mode:
                    print(f"  {manager} moved UP from {prev_pos} to {position}")
            elif prev_pos < position:
                # Moved down (from lower position number to higher position number is worse)
                position_change = f'<span class="position-down">▼</span>'
                if debug_mode:
                    print(f"  {manager} moved DOWN from {prev_pos} to {position}")
            else:
                # Same position
                position_change = '<span class="position-same">–</span>'
                if debug_mode:
                    print(f"  {manager} stayed at position {position}")
        else:
            position_change = '<span class="position-new">NEW</span>'
            if debug_mode:
                print(f"  {manager} is NEW (no previous position)")
        
        # Get most recent gameweek points
        recent_gw_points = weekly_points[manager]
        
        gap_to_above = previous_points - points['total']
        gap_to_top = top_points - points['total']
        
        # Calculate difference from Phase 1 squad performance
        phase1_squad_performance = 0
        for gw in range(1, current_gameweek + 1):
            if gw in gameweek_data:
                for player_id in manager_squads[manager].get(1, []):  # Phase 1 squad
                    if player_id in gameweek_data[gw]:
                        phase1_squad_performance += gameweek_data[gw][player_id]
        
        diff_from_phase1 = points['total'] - phase1_squad_performance
        diff_rank = diff_rankings[manager]
        
        # Add styling class for diff rank
        diff_rank_class = ""
        if diff_rank == 1:
            diff_rank_class = "class='position-up'"
        elif diff_rank <= 3:
            diff_rank_class = "class='diff-top3'"
        
        # Check if this is the manager with the highest weekly points and add the class if it is
        row_class = "highest-points" if manager == weekly_points_manager else ""
        
        html += f"""
        <tr class="{row_class}">
            <td>{position}</td>
            <td>{position_change} {manager}</td>
            <td>{points['total']}</td>
            <td>{recent_gw_points}</td>
            <td>{gap_to_above if position > 1 else '-'}</td>
            <td>{gap_to_top if position > 1 else '-'}</td>
            <td>{diff_from_phase1:+d}</td>
            <td {diff_rank_class}>{diff_rank}</td>
        </tr>
        """
        
        previous_points = points['total']
    
    html += """
        </tbody>
    </table>
    """
    
    return html

# Generate HTML for each manager's squad
def generate_squad_details(manager_squad_data, player_data, gameweek_data, past_gameweek_data, manager_points):
    """Generate HTML for each manager's squad."""
    if not manager_squad_data:
        return "No manager squad data available."
    
    html = ""
    
    # Sort managers by total points descending
    sorted_managers = sorted(manager_points.items(), key=lambda x: x[1]['total'], reverse=True)
    
    for manager, points_info in sorted_managers:
        if manager not in manager_squad_data:
            continue
        
        # Create a unique ID for each manager div for JavaScript selection
        manager_id = f'manager-{manager.replace(" ", "-").replace("/", "-").replace("(", "").replace(")", "")}'
        
        html += f"""
        <div id="{manager_id}" class="manager-squad">
            <h2>{manager} - {points_info['total']} Points</h2>
            <table class="squad-table">
                <tr>
                    <th>Player</th>
                    <th>Team</th>
                    <th>Position</th>
                    <th>Phase 1</th>
                    <th>Phase 2</th>
                    <th>Phase 3</th>
                    <th>Phase 4</th>
                    <th>Phase 5</th>
                    <th>Total Points</th>
                </tr>
        """
        
        # Extract the phases for this manager
        phases = manager_squad_data[manager]
        
        # Get current phase (5 or the highest available)
        current_phase = 5
        while current_phase > 0 and current_phase not in phases:
            current_phase -= 1
            
        if current_phase == 0:
            html += "<tr><td colspan='9'>No squad data available for this manager</td></tr>"
            html += "</table></div>"
            continue
            
        # Get current squad (Phase 5 or highest)
        current_squad_ids = set(phases.get(current_phase, []))
        
        # Identify previous players (players in earlier phases but not in current phase)
        previous_players = set()
        for phase_num, player_list in phases.items():
            if phase_num < current_phase:
                for player_id in player_list:
                    if player_id not in current_squad_ids:
                        previous_players.add(player_id)
        
        # Dictionary to map position IDs to position names for sorting
        position_order = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}
        
        # Collect current squad players
        current_players_data = []
        for player_id in current_squad_ids:
            # Skip if player data is not available
            if player_id not in player_data:
                print(f"Warning: Player data not available for ID {player_id}.")
                continue
            
            player = player_data[player_id]
            position = player['position']
            
            current_players_data.append({
                "id": player_id,
                "name": player['name'],
                "team": player['team'],
                "position": position,
                "position_order": position_order.get(position, 99)
            })
        
        # Collect past players data
        past_players_data = []
        for player_id in previous_players:
            # Skip if player data is not available
            if player_id not in player_data:
                print(f"Warning: Player data not available for ID {player_id}.")
                continue
            
            player = player_data[player_id]
            position = player['position']
            
            past_players_data.append({
                "id": player_id,
                "name": player['name'],
                "team": player['team'],
                "position": position,
                "position_order": position_order.get(position, 99)
            })
        
        # Sort both lists by position
        current_players_data.sort(key=lambda x: x["position_order"])
        past_players_data.sort(key=lambda x: x["position_order"])
        
        # Process current squad
        if current_players_data:
            html += f"""
            <tr class="current-players-header">
                <td colspan="9">
                    <strong>Current Squad (Phase {current_phase})</strong>
                </td>
            </tr>
            """
            
            for player_info in current_players_data:
                player_id = player_info["id"]
                player_name = player_info["name"]
                team = player_info["team"]
                position = player_info["position"]
                
                # Add position class directly to the first cell for color-coding
                html += f'<tr><td class="position-{position}">{player_name}</td><td>{team}</td><td>{position}</td>'
                
                # Calculate points for each phase the player was in this manager's squad
                player_total_points = 0
                for phase in range(1, 6):
                    if phase in phases and player_id in phases[phase]:
                        # Calculate points for this player in this phase
                        player_phase_points = 0
                        for gw in PHASES[phase]:
                            if gw in gameweek_data and player_id in gameweek_data[gw]:
                                player_phase_points += gameweek_data[gw][player_id]
                        
                        # Apply any point corrections (silently)
                        for correction_player_id, correction_phase, adjustment in POINT_CORRECTIONS:
                            if player_id == correction_player_id and phase == correction_phase:
                                player_phase_points += adjustment
                        
                        player_total_points += player_phase_points
                        
                        # Show the points in the HTML
                        html += f"<td>{player_phase_points}</td>"
                    else:
                        html += "<td>-</td>"
                
                # Add the total points cell
                html += f"<td>{player_total_points}</td></tr>"
        
        # Process past players
        if past_players_data:
            html += f"""
            <tr class="past-players-header">
                <td colspan="9">
                    <strong>Previous Players (No Longer in Current Squad)</strong>
                </td>
            </tr>
            """
            
            for player_info in past_players_data:
                player_id = player_info["id"]
                player_name = player_info["name"]
                team = player_info["team"]
                position = player_info["position"]
                
                # Start the row for this player - add position class to first cell and past-player class to row
                html += f'<tr class="past-player"><td class="position-{position}">{player_name}</td><td>{team}</td><td>{position}</td>'
                
                # Calculate points for each phase the player was in this manager's squad
                player_total_points = 0
                for phase in range(1, 6):
                    if phase in phases and player_id in phases[phase]:
                        # Calculate points for this player in this phase
                        player_phase_points = 0
                        for gw in PHASES[phase]:
                            if gw in gameweek_data and player_id in gameweek_data[gw]:
                                player_phase_points += gameweek_data[gw][player_id]
                        
                        # Apply any point corrections (silently)
                        for correction_player_id, correction_phase, adjustment in POINT_CORRECTIONS:
                            if player_id == correction_player_id and phase == correction_phase:
                                player_phase_points += adjustment
                        
                        player_total_points += player_phase_points
                        
                        # Show the points in the HTML
                        html += f"<td>{player_phase_points}</td>"
                    else:
                        html += "<td>-</td>"
                
                # Add the total points cell
                html += f"<td>{player_total_points}</td></tr>"
        
        html += """
            </table>
        </div>
        """
    
    return html

# Generate HTML for all players in the game
def generate_all_players_table(bootstrap_data, manager_squad_data):
    """Generate HTML for a table of all players in the game with filters."""
    
    # Create position and player data dictionaries
    position_order = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}
    
    all_players = []
    
    # Find the manager for each player (in current phase)
    player_manager_map = {}
    
    # Find the current phase for each manager (highest available)
    manager_current_phase = {}
    for manager, phases in manager_squad_data.items():
        current_phase = 5
        while current_phase > 0 and current_phase not in phases:
            current_phase -= 1
        
        if current_phase > 0:
            manager_current_phase[manager] = current_phase
            # Add all players from this manager's current phase to the map
            for player_id in phases.get(current_phase, []):
                if player_id not in player_manager_map:
                    player_manager_map[player_id] = []
                player_manager_map[player_id].append(manager)
    
    # Process all players
    for player in bootstrap_data['elements']:
        player_id = player['id']
        element_type = player['element_type']
        position = POSITION_MAPPING.get(element_type, 'Unknown')
        
        # Convert cost to millions and round up to nearest 0.5
        raw_cost = player['now_cost'] / 10  # Convert to millions
        # Ceiling to nearest 0.5 (e.g., 5.6 -> 6.0, 5.2 -> 5.5)
        decimal_part = raw_cost % 1
        if decimal_part == 0:
            now_cost = raw_cost  # Already a whole number
        elif decimal_part <= 0.5:
            now_cost = int(raw_cost) + 0.5  # Round up to next 0.5
        else:
            now_cost = int(raw_cost) + 1.0  # Round up to next whole number
        
        team = TEAM_MAPPING.get(player['team'], 'Unknown')
        
        # Find manager(s) who have this player
        managers = player_manager_map.get(player_id, [])
        manager_str = ", ".join(managers) if managers else "None"
        
        all_players.append({
            'id': player_id,
            'web_name': player['web_name'],
            'team': team,
            'element_type': position,
            'position_order': position_order.get(position, 99),
            'now_cost': now_cost,
            'total_points': player['total_points'],
            'manager': manager_str,
            'manager_count': len(managers)
        })
    
    # Sort players by position, then by cost (highest to lowest)
    all_players.sort(key=lambda x: (x['position_order'], -x['now_cost'], -x['total_points']))
    
    # Get unique managers for filter
    unique_managers = set()
    for manager in manager_squad_data.keys():
        unique_managers.add(manager)
    
    # Generate HTML
    html = """
    <div class="all-players-container">
        <div class="filters">
            <div class="filter-group">
                <label for="position-filter"><strong>Position:</strong></label>
                <select id="position-filter" class="filter-dropdown" onchange="filterPlayers()">
                    <option value="all">All Positions</option>
                    <option value="GKP">Goalkeepers</option>
                    <option value="DEF">Defenders</option>
                    <option value="MID">Midfielders</option>
                    <option value="FWD">Forwards</option>
                </select>
            </div>
            <div class="filter-group">
                <label for="manager-filter"><strong>Manager:</strong></label>
                <select id="manager-filter" class="filter-dropdown" onchange="filterPlayers()">
                    <option value="all">All Managers</option>
                    <option value="None">No Manager</option>
    """
    
    # Add all managers to the filter dropdown
    for manager in sorted(unique_managers):
        html += f'<option value="{manager}">{manager}</option>'
    
    html += """
                </select>
            </div>
            <div class="filter-group">
                <label for="player-search"><strong>Search:</strong></label>
                <input type="text" id="player-search" class="search-input" placeholder="Player name..." oninput="filterPlayers()">
            </div>
        </div>
        
        <div class="results-info">
            <p id="players-count">Showing all players</p>
        </div>
        
        <table id="all-players-table" class="all-players-table">
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Player</th>
                    <th>Team</th>
                    <th>Position</th>
                    <th>Cost</th>
                    <th>Points</th>
                    <th>Manager</th>
                </tr>
            </thead>
            <tbody>
    """
    
    # Add players to the table
    for player in all_players:
        position_class = f"position-{player['element_type']}"
        
        html += f"""
        <tr class="player-row" 
            data-position="{player['element_type']}" 
            data-manager="{player['manager']}"
            data-id="{player['id']}"
            data-name="{player['web_name'].lower()}"
        >
            <td>{player['id']}</td>
            <td class="{position_class}">{player['web_name']}</td>
            <td>{player['team']}</td>
            <td>{player['element_type']}</td>
            <td>£{player['now_cost']:.1f} mill</td>
            <td>{player['total_points']}</td>
            <td>{player['manager']}</td>
        </tr>
        """
    
    html += """
            </tbody>
        </table>
    </div>
    
    <script>
        function filterPlayers() {
            const positionFilter = document.getElementById('position-filter').value;
            const managerFilter = document.getElementById('manager-filter').value;
            const searchTerm = document.getElementById('player-search').value.toLowerCase();
            
            const rows = document.querySelectorAll('#all-players-table tbody tr');
            let visibleCount = 0;
            
            rows.forEach(row => {
                const position = row.getAttribute('data-position');
                const manager = row.getAttribute('data-manager');
                const name = row.getAttribute('data-name');
                
                // Check if row matches all filters
                const matchesPosition = positionFilter === 'all' || position === positionFilter;
                const matchesManager = managerFilter === 'all' || 
                                      (managerFilter === 'None' && manager === 'None') ||
                                      (managerFilter !== 'None' && manager.includes(managerFilter));
                const matchesSearch = searchTerm === '' || name.includes(searchTerm);
                
                // Show/hide based on filter matches
                if (matchesPosition && matchesManager && matchesSearch) {
                    row.style.display = '';
                    visibleCount++;
                } else {
                    row.style.display = 'none';
                }
            });
            
            // Update count display
            document.getElementById('players-count').textContent = `Showing ${visibleCount} players`;
        }
    </script>
    """
    
    return html

# Generate complete HTML output
def generate_html(manager_points, phase_points, highest_gameweek_manager, highest_gameweek_points, debug_mode=False):
    """Generate the main HTML content for the fantasy football tracker."""
    
    # Fetch the bootstrap data for all players tab
    bootstrap_data = None
    try:
        bootstrap_data = get_cached_data("bootstrap")
        if not bootstrap_data:
            bootstrap_data = fetch_bootstrap_data()
    except Exception as e:
        print(f"Error fetching bootstrap data for all players tab: {e}")
        bootstrap_data = {"elements": []}  # Empty fallback
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Fantasy Football Tracker</title>
        <style>
            /* Base styles */
            body {{
                font-family: 'Segoe UI', Roboto, Arial, sans-serif;
                margin: 0;
                padding: 20px;
                color: #333;
                line-height: 1.6;
                background-color: #f5f8fa;
                opacity: 0;
                animation: fadeInPage 0.8s ease-in forwards;
            }}
            
            @keyframes fadeInPage {{
                from {{ opacity: 0; }}
                to {{ opacity: 1; }}
            }}
            
            h1, h2, h3 {{
                color: #2c3e50;
                font-weight: 600;
                letter-spacing: -0.5px;
            }}
            
            h1 {{
                font-size: 2.2em;
                text-align: center;
                margin-bottom: 25px;
                position: relative;
                padding-bottom: 15px;
            }}
            
            h1:after {{
                content: '';
                position: absolute;
                bottom: 0;
                left: 50%;
                transform: translateX(-50%);
                width: 80px;
                height: 4px;
                background: linear-gradient(to right, #3498db, #2c3e50);
                border-radius: 2px;
            }}
            
            /* Base table styles */
            table {{
                border-collapse: separate;
                border-spacing: 0;
                width: 100%;
                margin-bottom: 25px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                background-color: white;
                font-size: 14px;
                border-radius: 8px;
                overflow: hidden;
                opacity: 0;
                animation: fadeIn 0.5s ease-out 0.3s forwards;
            }}
            
            @keyframes fadeIn {{
                from {{ opacity: 0; transform: translateY(20px); }}
                to {{ opacity: 1; transform: translateY(0); }}
            }}
            
            th, td {{
                padding: 12px 15px;
                text-align: left;
                border-bottom: 1px solid #eee;
            }}
            
            th {{
                background: linear-gradient(to right, #3498db, #2980b9);
                color: white;
                font-weight: 600;
                position: sticky;
                top: 0;
                z-index: 10;
                text-transform: uppercase;
                font-size: 12px;
                letter-spacing: 0.5px;
            }}
            
            /* Alternating row colors for better readability */
            tr:nth-child(even) {{
                background-color: #f9f9f9;
            }}
            
            tr:hover {{
                background-color: #f0f7ff;
                transition: background-color 0.2s ease;
            }}
            
            /* Row-by-row animation for league table */
            .league-table tbody tr {{
                opacity: 0;
                transform: translateX(-10px);
                animation: slideInRow 0.5s ease forwards;
            }}
            
            @keyframes slideInRow {{
                from {{ opacity: 0; transform: translateX(-10px); }}
                to {{ opacity: 1; transform: translateX(0); }}
            }}
            
            /* Mobile table adjustments */
            @media (max-width: 768px) {{
                .league-table, .squad-table, .all-players-table {{
                    display: block;
                    overflow-x: auto;
                    white-space: nowrap;
                }}
                
                th, td {{
                    padding: 10px 12px;
                    font-size: 13px;
                }}
                
                h1 {{
                    font-size: 1.8em;
                }}
                
                h2 {{
                    font-size: 1.5em;
                }}
                
                .tab {{
                    padding: 10px 15px;
                    font-size: 14px;
                }}
                
                .filter-group {{
                    margin-bottom: 15px;
                }}
            }}
            
            .past-player {{
                font-style: italic;
                color: #777;
                background-color: #f9f9f9;
            }}
            
            /* Position coloring - applied directly to cells */
            td.position-GKP {{
                border-left: 4px solid #fdcb6e;
            }}
            
            td.position-DEF {{
                border-left: 4px solid #00cec9;
            }}
            
            td.position-MID {{
                border-left: 4px solid #6c5ce7;
            }}
            
            td.position-FWD {{
                border-left: 4px solid #e17055;
            }}
            
            /* Past players header */
            .past-players-header td {{
                text-align: center;
                color: #555;
                background-color: #f0f0f0;
                font-style: italic;
                font-weight: bold;
                padding: 12px;
                border-top: 1px dashed #ccc;
                border-bottom: 1px dashed #ccc;
                margin-top: 20px;
            }}
            
            /* Current squad header */
            .current-players-header td {{
                text-align: center;
                color: #333;
                background-color: #e8f5e9;
                font-weight: bold;
                padding: 12px;
                border-top: 1px solid #4CAF50;
                border-bottom: 1px solid #4CAF50;
            }}
            
            .league-table {{
                max-width: 100%;
                margin: 0 auto;
            }}
            
            .league-table th:first-child,
            .league-table td:first-child {{
                width: 50px;
                text-align: center;
                font-weight: bold;
            }}
            
            .league-table th:nth-child(2),
            .league-table td:nth-child(2) {{
                min-width: 180px;
            }}
            
            /* Position change indicators */
            .position-up {{
                color: #2ecc71;
                font-weight: bold;
                display: inline-block;
                margin-right: 5px;
                animation: pulse 2s infinite;
            }}
            
            @keyframes pulse {{
                0% {{ transform: scale(1); }}
                50% {{ transform: scale(1.2); }}
                100% {{ transform: scale(1); }}
            }}
            
            .position-down {{
                color: #e74c3c;
                font-weight: bold;
                display: inline-block;
                margin-right: 5px;
            }}
            
            .position-same {{
                color: #7f8c8d;
                display: inline-block;
                margin-right: 5px;
            }}
            
            .position-new {{
                color: #3498db;
                font-style: italic;
                display: inline-block;
                margin-right: 5px;
                animation: glow 1.5s infinite alternate;
            }}
            
            @keyframes glow {{
                from {{ text-shadow: 0 0 0px #3498db; }}
                to {{ text-shadow: 0 0 5px #3498db, 0 0 10px #3498db; }}
            }}
            
            /* Diff Rank styling */
            .diff-top3 {{
                color: #f39c12;
                font-weight: bold;
            }}
            
            /* Tab styling */
            .tabs-container {{
                display: flex;
                justify-content: center;
                margin-bottom: 20px;
                opacity: 0;
                animation: fadeIn 0.5s ease forwards;
            }}
            
            .tabs {{
                display: flex;
                flex-wrap: wrap;
                justify-content: center;
                width: 100%;
                max-width: 700px;
                background: white;
                border-radius: 50px;
                padding: 8px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            }}
            
            .tab {{
                display: inline-block;
                padding: 12px 20px;
                background-color: transparent;
                cursor: pointer;
                border-radius: 25px;
                margin: 0 5px;
                border: none;
                transition: all 0.3s ease;
                text-align: center;
                flex-grow: 1;
                font-weight: 600;
                color: #555;
            }}
            
            .tab.active {{
                background: linear-gradient(to right, #3498db, #2980b9);
                color: white;
                box-shadow: 0 5px 10px rgba(52, 152, 219, 0.3);
            }}
            
            .tab-content {{
                display: none;
                padding: 25px;
                border-radius: 12px;
                margin-top: 20px;
                background-color: white;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                opacity: 0;
                transform: translateY(10px);
                transition: opacity 0.4s ease, transform 0.4s ease;
            }}
            
            .tab-content.active {{
                display: block;
                opacity: 1;
                transform: translateY(0);
            }}
            
            .squad-table td:nth-child(n+5):not(:last-child) {{
                position: relative;
            }}
            
            .squad-info {{
                margin-bottom: 25px;
                padding: 15px 20px;
                background-color: white;
                border-left: 5px solid #2196f3;
                border-radius: 8px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                opacity: 0;
                animation: fadeIn 0.5s ease 0.2s forwards;
            }}
            
            .highlight {{
                background-color: #ffffd0;
            }}
            
            .manager-squad {{
                display: none;
                margin-bottom: 25px;
                border-radius: 10px;
                overflow: hidden;
                background-color: white;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                animation: fadeIn 0.5s ease;
            }}
            
            .manager-squad.active {{
                display: block;
            }}
            
            .manager-squad h2 {{
                margin: 0;
                padding: 15px 20px;
                background: linear-gradient(to right, #3498db, #2980b9);
                color: white;
                border-radius: 10px 10px 0 0;
            }}
            
            .highest-gameweek {{
                background-color: white;
                padding: 15px 20px;
                margin-bottom: 25px;
                border-left: 5px solid #4CAF50;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                border-radius: 8px;
                opacity: 0;
                animation: fadeIn 0.5s ease 0.1s forwards;
            }}
            
            .warning {{
                background-color: #fff3cd;
                padding: 15px 20px;
                margin-bottom: 25px;
                border-left: 5px solid #ffc107;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                border-radius: 8px;
                opacity: 0;
                animation: fadeIn 0.5s ease forwards;
            }}
            
            /* Styling for the total points column */
            .squad-table th:last-child,
            .squad-table td:last-child {{
                background-color: #e8f5e9;
                font-weight: bold;
                border-left: 2px solid #4CAF50;
                text-align: center;
                position: sticky;
                right: 0;
                z-index: 5;
            }}
            
            /* Preserve styling for past players' total points */
            tr.past-player td:last-child {{
                background-color: rgba(232, 245, 233, 0.7);
                font-weight: bold;
                font-style: italic;
                color: #777;
                border-left: 2px solid rgba(76, 175, 80, 0.5);
                text-align: center;
                position: sticky;
                right: 0;
            }}
            
            /* Header for total points */
            .squad-table th:last-child {{
                background-color: #4CAF50;
                color: white;
                position: sticky;
                right: 0;
                z-index: 15;
            }}
            
            /* Manager dropdown styling */
            .manager-selector {{
                margin-bottom: 25px;
                width: 100%;
                background-color: white;
                padding: 20px;
                border-radius: 10px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                opacity: 0;
                animation: fadeIn 0.5s ease 0.3s forwards;
            }}
            
            .manager-dropdown {{
                padding: 12px 15px;
                font-size: 16px;
                border: 1px solid #ddd;
                border-radius: 8px;
                width: 100%;
                margin-top: 10px;
                background-color: white;
                transition: all 0.3s ease;
            }}
            
            .manager-dropdown:focus {{
                border-color: #3498db;
                outline: none;
                box-shadow: 0 0 0 3px rgba(52, 152, 219, 0.25);
            }}
            
            /* Hover effects for rows to improve readability */
            .squad-table tr:hover td, .all-players-table tr:hover td {{
                background-color: rgba(245, 245, 245, 0.6);
            }}
            
            .squad-table tr.past-player:hover td {{
                background-color: rgba(245, 245, 245, 0.4);
            }}
            
            /* Status info styling */
            .status-info {{
                display: flex;
                flex-wrap: wrap;
                justify-content: space-between;
                text-align: center;
                font-size: 0.9em;
                background: white;
                padding: 15px 20px;
                border-radius: 10px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                margin-bottom: 25px;
                opacity: 0;
                animation: fadeIn 0.5s ease forwards;
            }}
            
            .status-info p {{
                margin: 5px;
                flex: 1;
                min-width: 200px;
                font-weight: 500;
            }}
            
            /* Loading indicator */
            #loading {{
                display: none;
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(255, 255, 255, 0.9);
                z-index: 999;
                justify-content: center;
                align-items: center;
            }}
            
            .loading-spinner {{
                width: 60px;
                height: 60px;
                border: 6px solid #f3f3f3;
                border-top: 6px solid #3498db;
                border-radius: 50%;
                animation: spin 1s linear infinite;
            }}
            
            @keyframes spin {{
                0% {{ transform: rotate(0deg); }}
                100% {{ transform: rotate(360deg); }}
            }}
            
            /* Filter styles for All Players tab */
            .filters {{
                display: flex;
                flex-wrap: wrap;
                gap: 20px;
                margin-bottom: 25px;
                background-color: white;
                padding: 20px;
                border-radius: 10px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                opacity: 0;
                animation: fadeIn 0.5s ease 0.3s forwards;
            }}
            
            .filter-group {{
                flex: 1;
                min-width: 200px;
            }}
            
            .filter-dropdown, .search-input {{
                width: 100%;
                padding: 12px 15px;
                margin-top: 8px;
                border: 1px solid #ddd;
                border-radius: 8px;
                font-size: 14px;
                transition: all 0.3s ease;
            }}
            
            .filter-dropdown:focus, .search-input:focus {{
                border-color: #3498db;
                outline: none;
                box-shadow: 0 0 0 3px rgba(52, 152, 219, 0.25);
            }}
            
            .results-info {{
                margin-bottom: 15px;
                font-size: 14px;
                color: #666;
                padding: 10px;
                background-color: #f8f9fa;
                border-radius: 5px;
                opacity: 0;
                animation: fadeIn 0.5s ease 0.4s forwards;
            }}
            
            /* Make the All Players table more compact */
            .all-players-table th, .all-players-table td {{
                padding: 10px 12px;
            }}
            
            /* Preserve alternating row colors even when filtering */
            .all-players-table tr:nth-child(even) {{
                background-color: rgba(0, 0, 0, 0.02);
            }}
            
            /* Highest scoring manager highlight */
            .highest-points {{
                background-color: rgba(46, 204, 113, 0.15);
                font-weight: bold;
            }}
            
            .highest-points td {{
                animation: highlightPulse 2.5s infinite alternate;
            }}
            
            @keyframes highlightPulse {{
                from {{ background-color: rgba(46, 204, 113, 0.1); }}
                to {{ background-color: rgba(46, 204, 113, 0.25); }}
            }}
        </style>
    </head>
    <body>
        <h1>Fantasy Football Tracker</h1>
        <div class="status-info">
            <p>Last updated: """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</p>
            <p>Last Gameweek: """ + str(current_gameweek) + """</p>
        </div>
        
        <div id="loading">
            <div class="loading-spinner"></div>
        </div>
        
        """
    
    # Add warnings if needed
    if not manager_points:
        html += """
        <div class="warning">
            <h3>⚠️ No Manager Points Calculated</h3>
            <p>This may be due to:</p>
            <ul>
                <li>The season hasn't started yet or the current gameweek has no points</li>
                <li>Player IDs in squad files don't match current season player IDs</li>
                <li>Issues with parsing the squad file</li>
            </ul>
            <p>Run the debug_fantasy.py script for more detailed troubleshooting.</p>
        </div>
        """
    
    html += """
        <div class="tabs-container">
            <div class="tabs">
                <div class="tab active" onclick="showTab('league-tab')">League Table</div>
                <div class="tab" onclick="showTab('squads-tab')">Manager Squads</div>
                <div class="tab" onclick="showTab('all-players-tab')">All Players</div>
            </div>
        </div>
        
        <div id="league-tab" class="tab-content active">
            <h2>League Table</h2>
            """ + generate_league_table(manager_points, phase_points, debug_mode) + """
        </div>
        
        <div id="squads-tab" class="tab-content">
            <h2>Manager Squads</h2>
            <div class="squad-info">
                <p>Players are grouped by position through color-coding on the left border. Swipe horizontally to see all phases. <strong>Total Points</strong> column is fixed on the right.</p>
                <p>The <strong>Current Squad</strong> shows the latest phase, while <strong>Previous Players</strong> shows players no longer in the current squad.</p>
            </div>
            
            <div class="manager-selector">
                <label for="manager-dropdown"><strong>Select Manager:</strong></label><br>
                <select id="manager-dropdown" class="manager-dropdown" onchange="showManager(this.value)">
                    <option value="">Select a manager...</option>
                    """ + ''.join([f'<option value="{manager}">{manager} ({points["total"]} pts)</option>' for manager, points in sorted(manager_points.items(), key=lambda x: x[1]["total"], reverse=True)]) + """
                </select>
            </div>
            
            """ + generate_squad_details(manager_squads, player_data, gameweek_data, gameweek_data, manager_points) + """
        </div>
        
        <div id="all-players-tab" class="tab-content">
            <h2>All Premier League Players</h2>
            <div class="squad-info">
                <p>This table shows all players in the FPL game. Use the filters to search by position, manager, or player name.</p>
                <p>Players are ordered by position and then by cost (highest to lowest).</p>
            </div>
            
            """ + generate_all_players_table(bootstrap_data, manager_squads) + """
        </div>
        
        <script>
            // Apply animations to the league table rows
            function animateLeagueTable() {
                const rows = document.querySelectorAll('.league-table tbody tr');
                rows.forEach((row, index) => {
                    // Set animation delay for each row to create the sequential effect
                    row.style.animationDelay = (0.05 * index) + 's';
                });
            }
            
            function showTab(tabId) {
                // Show loading spinner
                document.getElementById('loading').style.display = 'flex';
                
                // Hide all tabs
                const tabContents = document.getElementsByClassName('tab-content');
                for (let i = 0; i < tabContents.length; i++) {
                    tabContents[i].classList.remove('active');
                }
                
                // Show selected tab
                document.getElementById(tabId).classList.add('active');
                
                // Update tab buttons
                const tabs = document.getElementsByClassName('tab');
                for (let i = 0; i < tabs.length; i++) {
                    tabs[i].classList.remove('active');
                }
                
                // Highlight selected tab button
                event.currentTarget.classList.add('active');
                
                // Reset manager dropdown if switching to squad tab
                if (tabId === 'squads-tab') {
                    document.getElementById('manager-dropdown').selectedIndex = 0;
                    hideAllManagers();
                }
                
                // Re-apply animations if showing league table
                if (tabId === 'league-tab') {
                    animateLeagueTable();
                }
                
                // Hide loading spinner after a short delay
                setTimeout(function() {
                    document.getElementById('loading').style.display = 'none';
                }, 300);
            }
            
            function showManager(managerName) {
                // Show loading spinner
                document.getElementById('loading').style.display = 'flex';
                
                // Hide all manager squads
                hideAllManagers();
                
                // Show the selected manager if a value is selected
                if (managerName) {
                    const managerElement = document.getElementById('manager-' + managerName.replace(/[^a-zA-Z0-9]/g, '-'));
                    if (managerElement) {
                        managerElement.classList.add('active');
                        
                        // Scroll to the manager's squad
                        setTimeout(function() {
                            managerElement.scrollIntoView({behavior: 'smooth', block: 'start'});
                        }, 100);
                    }
                }
                
                // Hide loading spinner after a short delay
                setTimeout(function() {
                    document.getElementById('loading').style.display = 'none';
                }, 300);
            }
            
            function hideAllManagers() {
                const managerSquads = document.getElementsByClassName('manager-squad');
                for (let i = 0; i < managerSquads.length; i++) {
                    managerSquads[i].classList.remove('active');
                }
            }
            
            // Initialize by hiding all managers when page loads
            document.addEventListener('DOMContentLoaded', function() {
                hideAllManagers();
                document.getElementById('loading').style.display = 'none';
                
                // Apply animations to the league table rows on load
                animateLeagueTable();
                
                // Add touchstart event listener for faster mobile response
                const tabs = document.getElementsByClassName('tab');
                for (let i = 0; i < tabs.length; i++) {
                    tabs[i].addEventListener('touchstart', function(e) {
                        e.target.click();
                    }, { passive: true });
                }
                
                // Initialize filters for All Players tab
                if (document.getElementById('all-players-tab')) {
                    filterPlayers();
                }
            });
        </script>
    </body>
    </html>
    """
    
    return html

# Main function to run the tracker
def main():
    global player_data, manager_squads, gameweek_data, current_gameweek, previous_standings
    
    # Check for command line arguments
    import sys
    test_mode = "--test-movement" in sys.argv
    debug_mode = "--debug" in sys.argv
    
    # Try to find and parse a squads file
    squad_files = ["Squads.csv", "Squads.txt"]
    manager_squads = None
    
    for filename in squad_files:
        if os.path.exists(filename):
            print(f"Found squad file: {filename}")
            if filename.endswith('.csv'):
                manager_squads = parse_csv_squads_file(filename)
                break
            elif filename.endswith('.txt'):
                manager_squads = parse_squads_file(filename)
                break
    
    # If no squad files found, create an example but NEVER touch Squads.csv
    if manager_squads is None:
        print("No squad files found.")
        create_example_csv()  # This will only create example_squads.csv, not Squads.csv
        print("Please create a Squads.csv file based on the example_squads.csv template and run the program again.")
        return
    
    # Check if we found any manager data
    if not manager_squads:
        print("ERROR: Could not parse any manager squads from the available files.")
        print("Please ensure your file is properly formatted. See example_squads.csv for reference.")
        print("Try running debug_fantasy.py for more detailed diagnostics.")
        return
    
    # Only use the saved standings file for test mode, otherwise we'll calculate both current and previous
    if test_mode:
        # Load previous standings for position change tracking
        previous_standings = load_previous_standings()
        
        # If in test mode, modify the previous standings to create movement
        if previous_standings and "standings" in previous_standings:
            print("TEST MODE: Creating artificial position changes for testing")
            # Create a backup copy of the original standings
            import random
            # Get a list of managers
            managers = list(previous_standings["standings"].keys())
            if len(managers) >= 4:
                # Swap some positions to create movement
                # Swap positions of two random managers
                manager1, manager2 = random.sample(managers, 2)
                pos1 = previous_standings["standings"][manager1]
                pos2 = previous_standings["standings"][manager2]
                previous_standings["standings"][manager1] = pos2
                previous_standings["standings"][manager2] = pos1
                print(f"TEST: Swapped positions between {manager1} (now {pos2}) and {manager2} (now {pos1})")
                
                # Move another manager up
                if len(managers) >= 5:
                    manager3 = random.choice([m for m in managers if m not in [manager1, manager2]])
                    pos3 = previous_standings["standings"][manager3]
                    if pos3 > 1:  # Can move up
                        previous_standings["standings"][manager3] = pos3 - 1
                        # Find and adjust the manager who was in that position
                        for m, p in previous_standings["standings"].items():
                            if m != manager3 and p == pos3 - 1:
                                previous_standings["standings"][m] = pos3
                                print(f"TEST: Moved {manager3} up from {pos3} to {pos3-1}, {m} moved down to {pos3}")
                                break
            
            print("Modified previous standings for testing movement indicators")
    
    # Fetch bootstrap data (player info)
    print("Fetching player data from Premier League API...")
    bootstrap_data = fetch_bootstrap_data()
    player_data = process_player_data(bootstrap_data)
    
    # Determine current gameweek from API data
    current_gameweek = 0
    if 'events' in bootstrap_data:
        for event in bootstrap_data['events']:
            if event.get('is_current'):
                current_gameweek = event['id']
                break
        
        if current_gameweek == 0:
            # If no current gameweek is found, find the most recent finished gameweek
            for event in bootstrap_data['events']:
                if event.get('finished'):
                    current_gameweek = max(current_gameweek, event['id'])
    else:
        print("WARNING: Could not determine current gameweek from API data.")
        print("API response may be missing 'events' data.")
    
    if current_gameweek == 0:
        print("WARNING: No current gameweek found. The season may not have started yet.")
        print("Using gameweek 1 as fallback for testing.")
        current_gameweek = 1
    
    print(f"Current/latest gameweek: {current_gameweek}")
    
    # Fetch data for all gameweeks up to current
    for gw in range(1, current_gameweek + 1):
        print(f"Fetching data for gameweek {gw}...")
        gw_data = fetch_gameweek_data(gw)
        gameweek_data[gw] = process_gameweek_data(gw_data)
    
    # Calculate manager points
    print("Calculating points for all managers...")
    manager_points, phase_points, highest_gw_manager, highest_gw_points = calculate_manager_points()
    
    # If not in test mode, calculate standings for both current and previous gameweek
    if not test_mode:
        if current_gameweek > 1:
            print(f"Calculating standings for current gameweek {current_gameweek} and previous gameweek {current_gameweek-1}...")
            current_standings, previous_standings = calculate_position_changes(current_gameweek)
            if debug_mode:
                print(f"Calculated position changes between gameweeks {current_gameweek-1} and {current_gameweek}")
                for manager in current_standings["standings"]:
                    current_pos = current_standings["standings"][manager]
                    prev_pos = previous_standings["standings"].get(manager, "NEW")
                    if prev_pos != "NEW" and prev_pos != current_pos:
                        movement = "UP" if prev_pos > current_pos else "DOWN"
                        print(f"  {manager}: {prev_pos} → {current_pos} ({movement})")
        else:
            # For gameweek 1, there's no previous gameweek
            previous_standings = {"gameweek": 0, "standings": {}}
    
    # Save current standings for future reference (but we don't rely on this for position changes)
    save_current_standings(manager_points)
    
    # Generate HTML
    print("Generating HTML report...")
    html = generate_html(manager_points, phase_points, highest_gw_manager, highest_gw_points, debug_mode)
    
    # Write to file
    output_file = "fantasy_football.html"
    with open(output_file, "w") as f:
        f.write(html)
    
    print(f"Output written to {output_file}")
    print(f"Open {output_file} in your web browser to view the results")
    
    # Provide hints if no data was generated
    if not manager_points:
        print("\nWARNING: No manager points were calculated. This may be because:")
        print("1. The season hasn't started yet or the current gameweek has no points")
        print("2. Player IDs in squad files don't match current season player IDs")
        print("3. There were issues parsing your Squads.csv file")
        print("\nFor more detailed diagnostics, run: python debug_fantasy.py")

# Calculate the position changes between current and previous gameweek
def calculate_position_changes(current_gw):
    """
    Calculate the standings for both current and previous gameweek to determine position changes.
    
    This is more reliable than using a saved file from previous runs since it calculates both
    standings from the same dataset in a single run.
    
    Args:
        current_gw (int): The current gameweek number
        
    Returns:
        tuple: (current_standings, previous_standings) dictionaries with position info
    """
    if current_gw <= 1:
        # No previous gameweek to compare with
        return (
            {"gameweek": current_gw, "standings": {}},
            {"gameweek": 0, "standings": {}}
        )
    
    # Calculate points up to current gameweek
    current_manager_points = calculate_points_up_to_gameweek(current_gw)
    
    # Calculate points up to previous gameweek
    previous_manager_points = calculate_points_up_to_gameweek(current_gw - 1)
    
    # Get standings for current gameweek
    current_standings = {
        "gameweek": current_gw,
        "standings": {}
    }
    
    # Sort managers by total points for current gameweek
    sorted_current = sorted(current_manager_points.items(), key=lambda x: x[1]['total'], reverse=True)
    for position, (manager, _) in enumerate(sorted_current, 1):
        current_standings["standings"][manager] = position
    
    # Get standings for previous gameweek
    previous_standings = {
        "gameweek": current_gw - 1,
        "standings": {}
    }
    
    # Sort managers by total points for previous gameweek
    sorted_previous = sorted(previous_manager_points.items(), key=lambda x: x[1]['total'], reverse=True)
    for position, (manager, _) in enumerate(sorted_previous, 1):
        previous_standings["standings"][manager] = position
    
    return (current_standings, previous_standings)

# Calculate points up to a specific gameweek
def calculate_points_up_to_gameweek(gameweek):
    """
    Calculate points for all managers up to a specific gameweek.
    
    This is used to determine standings at any point in the season.
    
    Args:
        gameweek (int): The gameweek up to which to calculate points
        
    Returns:
        dict: Manager points dictionary
    """
    manager_points = {}
    
    # For each manager and their phases
    for manager, phases in manager_squads.items():
        manager_points[manager] = {'total': 0}
        
        # For each phase this manager has
        for phase_num, player_ids in phases.items():
            phase_points = 0
            
            # Only count gameweeks up to specified gameweek
            for gw in [gw for gw in PHASES[phase_num] if gw <= gameweek]:
                if gw in gameweek_data:
                    for player_id in player_ids:
                        if player_id in gameweek_data[gw]:
                            phase_points += gameweek_data[gw][player_id]
            
            # Apply any point corrections for this phase
            for player_id, phase, adjustment in POINT_CORRECTIONS:
                if phase == phase_num and player_id in player_ids:
                    phase_points += adjustment
            
            manager_points[manager][f'phase_{phase_num}'] = phase_points
            manager_points[manager]['total'] += phase_points
    
    return manager_points

if __name__ == "__main__":
    main() 