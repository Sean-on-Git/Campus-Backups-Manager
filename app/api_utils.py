import os
import sys
import shutil
import re
import requests
from datetime import datetime, timedelta
import pytz
import json
import platform
import logging

# Set up logging for errors
# logging.basicConfig(filename='errors.log', level=logging.ERROR,
#                    format='%(asctime)s %(levelname)s %(message)s')
error_handler = logging.FileHandler('error.log')
error_handler.setLevel(logging.ERROR)
error_formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
error_handler.setFormatter(error_formatter)

# Adding debug handler to error logger
error_logger = logging.getLogger()
error_logger.setLevel(logging.ERROR)
error_logger.addHandler(error_handler)
error_logger.debug("Error logging setup completed.")

# Set up logging for debug logs
debug_handler = logging.FileHandler('debug.log')
debug_handler.setLevel(logging.DEBUG)
debug_formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
debug_handler.setFormatter(debug_formatter)

# Adding debug handler to the debug logger
debug_logger = logging.getLogger()
debug_logger.setLevel(logging.DEBUG)
debug_logger.addHandler(debug_handler)
debug_logger.debug("Logging setup completed.")


# Get the directory of the executable
if getattr(sys, 'frozen', False):
     # If the application is frozen (i.e., packaged with PyInstaller)
    APPLICATION_PATH = os.path.dirname(sys.executable)
else:
    # If the application is not frozen
    APPLICATION_PATH = os.path.dirname(__file__)


def adjust_path(path):
    """
    Adjusts slashes to the appropriate type for the current OS

    Args:
        path (str): A filesystem path. Ex: '/home/user/Documents', 'C:\\Users\\me\\Documents'

    Returns:
        str: With appropriate slashes. Ex: "../MyBackups/here" -> "..\\MyBackups\\here"
    """
    if platform.system() == "Windows":
        return path.replace("/", "\\")
    else:
        return path.replace("\\", "/")

def load_config():
    """
    Load the configuration from the config.json file.

    Returns:
        dict: Configuration dictionary if the file is found and valid, otherwise None.
    """
    try:
        with open(APPLICATION_PATH + 'config.json') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        error_logger.error("Error: config.json file not found.")
        return None
    except json.JSONDecodeError:
        error_logger.error("Error: config.json file is not a valid JSON file.")
        return None

config = load_config()

if config:
    INSTANCE = config['instance']
    BACKUPS_LOCATION = config['backups_location']
    DELETION_LOCATION = config['deletion_location']
else:
    error_logger.error("Error: unable to load configuration.\nA 'config.json' needs to be in the same directory as this app.")
    exit()
    # you can exit the program here or handle it in some other way

def scan_directory_for_tickets(directory):
    """
    Scan the specified directory for folders containing "TKTXXXXXXX".

    Args:
        directory (str): The directory to scan.

    Returns:
        list: A list of ticket numbers found in the directory.
    """
    ticket_pattern = re.compile(r'TKT\d{7}')
    ticket_numbers = []
    for folder_name in os.listdir(directory):
        if os.path.isdir(os.path.join(directory, folder_name)):
            match = ticket_pattern.search(folder_name)
            if match:
                ticket_numbers.append(match.group())
    return ticket_numbers

def move_to_deletion_folder(ticket_numbers):
    """
    Move folders containing the specified ticket numbers to the DELETION_LOCATION.

    Args:
        ticket_numbers (list): A list of ticket numbers (e.g., "TKTXXXXXXX").
    """
    for ticket_number in ticket_numbers:
        for folder_name in os.listdir(BACKUPS_LOCATION):
            if os.path.isdir(os.path.join(BACKUPS_LOCATION, folder_name)):
                if ticket_number in folder_name:
                    folder_path = os.path.join(BACKUPS_LOCATION, folder_name)
                    deletion_path = os.path.join(DELETION_LOCATION, folder_name)
                    try:
                        shutil.move(folder_path, deletion_path)
                        # debug_logger.debug(f"Moved {folder_name} to {DELETION_LOCATION}")
                    except Exception as e:
                        error_logger.error(f"Error moving {folder_name}: {e}")

def fetch_username_info(instance, username, password, closed_by_id):
    """
    Fetch the username of the user who closed the ticket.

    Args:
        instance (str): ServiceNow instance.
        username (str): Username for authentication.
        password (str): Password for authentication.
        closed_by_id (str): sys_id of the user who closed the ticket.

    Returns:
        str: The username of the user who closed the ticket.
    """
    url_user = f"https://{instance}/api/now/table/sys_user?sysparm_query=sys_id={closed_by_id}"
    response_user = requests.get(url_user, auth=(username, password))
    if response_user.status_code == 200:
        data_user = response_user.json()
        if data_user['result']:
            closed_by_username = data_user['result'][0].get('user_name', 'N/A')
        else:
            closed_by_username = 'N/A'
    else:
        error_logger.error(f"Error fetching user info: {response_user.status_code} - {response_user.text}")
        closed_by_username = 'N/A'
    return closed_by_username

def fetch_label_info(instance, username, password, ticket_number):
    """
    Fetch the label info of a ticket to determine if it has the "Ready for Pickup" tag.

    Args:
        instance (str): ServiceNow instance.
        username (str): Username for authentication.
        password (str): Password for authentication.
        ticket_number (str): Ticket number.

    Returns:
        bool: True if the ticket has the "Ready for Pickup" tag, otherwise False.
    """
    url_label_entry = f"https://{instance}/api/now/table/label_entry?sysparm_query=id_display={ticket_number}"
    response_label_entry = requests.get(url_label_entry, auth=(username, password))
    has_ready_for_pickup_tag = False
    if response_label_entry.status_code == 200:
        data_label_entry = response_label_entry.json()
        if data_label_entry['result']:
            for entry in data_label_entry['result']:
                if len(entry.keys()) > 0:
                    if entry['label']['value'] == "0874ad561b6b9d147881db13dd4bcb96":
                        has_ready_for_pickup_tag = True
                        break
    else:
        error_logger.error(f"Error fetching label info: {response_label_entry.status_code} - {response_label_entry.text}")
    return has_ready_for_pickup_tag

def find_matching_folders(backups_location, ticket_number) -> str:
    # List all folders in the specified backups location
    all_folders = os.listdir(backups_location)

    # Filter folders that contain the search pattern
    matching_folders = [folder for folder in all_folders if ticket_number in folder]

    error_logger.error(f"MATCHING FOLDERS: {matching_folders}")

    return matching_folders[0]

def get_folder_size(folder_path):
    """
    Calculate the total size of a folder in bytes.

    Args:
        folder_path (str): The path of the folder.

    Returns:
        int: Total size of the folder in bytes.
    """
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(folder_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total_size += os.path.getsize(fp)
                debug_logger.debug(f"os.path is '{fp}'\n\tSize is {os.path.getsize(fp)}")
            except Exception as e:
                error_logger.error(f"Error getting size for file {fp}:\n\t{e}")
    return total_size

def human_readable_size(size):
    """
    Convert a size in bytes to a human-readable format with the appropriate unit.

    Args:
        size (int): Size in bytes.

    Returns:
        str: Human-readable size with the appropriate unit.
    """
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

def fetch_ticket_info(instance, username, password, ticket_number):
    """
    Fetch the information of a ticket from the ServiceNow instance.

    Args:
        instance (str): ServiceNow instance.
        username (str): Username for authentication.
        password (str): Password for authentication.
        ticket_number (str): Ticket number.

    Returns:
        dict: Dictionary containing the ticket information.
    """
    debug_logger.debug(f"Loading data for ticket: {ticket_number}")
    url_item = f"https://{instance}/api/now/table/sc_req_item?sysparm_query=number={ticket_number}"
    response_item = requests.get(url_item, auth=(username, password))
    if response_item.status_code == 200:
        data_item = response_item.json()
        if data_item['result']:
            item = data_item['result'][0]
            sys_id = item['sys_id']
            closed_at_utc = item.get('closed_at', 'N/A')
            has_ready_for_pickup_tag = fetch_label_info(instance, username, password, ticket_number)
            if item.get('active') == "false":
                closed_by_id = item.get('closed_by', {}).get('value', 'N/A')
            else:
                closed_by_id = 'N/A'
            if closed_at_utc != 'N/A' and closed_at_utc != '':
                utc_time = datetime.strptime(closed_at_utc, '%Y-%m-%d %H:%M:%S')
                local_tz = pytz.timezone('America/New_York')
                local_time = utc_time.replace(tzinfo=pytz.utc).astimezone(local_tz)
                closed_at_local = local_time.strftime('%Y-%m-%d %H:%M:%S %Z%z')
                ready_for_deletion = (datetime.now(pytz.timezone('America/New_York')) - local_time > timedelta(weeks=2)) and not has_ready_for_pickup_tag
            else:
                closed_at_local = 'N/A'
                ready_for_deletion = False
            closed_by_username = fetch_username_info(instance, username, password, closed_by_id)
            debug_logger.debug(f"Scanning file size for {ticket_number}")
            folder_size = human_readable_size(get_folder_size(os.path.join(BACKUPS_LOCATION, find_matching_folders(BACKUPS_LOCATION, ticket_number))))
            return {
                'ticket_number': ticket_number,
                'sys_id': sys_id,
                'closed_at_local': closed_at_local,
                'closed_by_username': closed_by_username,
                'has_ready_for_pickup_tag': has_ready_for_pickup_tag,
                'ready_for_deletion': ready_for_deletion,
                'folder_size': folder_size,
                'url': f"https://{instance}/nav_to.do?uri=sc_req_item.do?sys_id={sys_id}"
            }
    else:
        error_logger.error(f"Error fetching ticket info: {response_item.status_code} - {response_item.text}")
    return None
