import os
from app.config import get_settings

# Set EPICS environment before any aioca imports
# These must be set before libca is loaded
settings = get_settings()
if settings.epics_ca_addr_list:
    os.environ["EPICS_CA_ADDR_LIST"] = settings.epics_ca_addr_list
os.environ["EPICS_CA_AUTO_ADDR_LIST"] = settings.epics_ca_auto_addr_list
os.environ["EPICS_CA_SERVER_PORT"] = settings.epics_ca_server_port
os.environ["EPICS_CA_REPEATER_PORT"] = settings.epics_ca_repeater_port
