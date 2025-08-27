# config.py
from datetime import timezone

# ======== General Settings ========
SHIFT_HOURS = 3
UTC = timezone.utc
DATA_DIR = "data"
DATABASE_FILE = f"{DATA_DIR}/titles.db"
CSV_LOG_FILE = f"{DATA_DIR}/requests.csv"
MIN_HOLD_DURATION_HOURS = 24

# ======== Discord Settings ========
GUARDIAN_ROLE_ID = 1409964411057344512
TITLE_REQUESTS_CHANNEL_ID = 1409770504696631347

# ======== Titles Catalog (Single Source of Truth) ========
TITLES_CATALOG = {
    "Guardian of Harmony": {
        "effects": "All benders' ATK +5%, All benders' DEF +5%, All Benders' recruiting speed +15%",
        "image_url": "https://cdn.discordapp.com/attachments/1409793076955840583/1409793727018569758/guardian_harmony.png",
    },
    "Guardian of Air": {
        "effects": "All Resource Gathering Speed +20%, All Resource Production +20%",
        "image_url": "https://cdn.discordapp.com/attachments/1409793076955840583/1409793463817605181/guardian_air.png",
    },
    "Guardian of Water": {
        "effects": "All Benders' recruiting speed +15%",
        "image_url": "https://cdn.discordapp.com/attachments/1409793076955840583/1409793588778369104/guardian_water.png",
    },
    "Guardian of Earth": {
        "effects": "Construction Speed +10%, Research Speed +10%",
        "image_url": "https://cdn.discordapp.com/attachments/1409793076955840583/1409794927730229278/guardian_earth.png",
    },
    "Guardian of Fire": {
        "effects": "All benders' ATK +5%, All benders' DEF +5%",
        "image_url": "https://cdn.discordapp.com/attachments/1409793076955840583/1409794024948367380/guardian_fire.png",
    },
    "Architect": {
        "effects": "Construction Speed +10%",
        "image_url": "https://cdn.discordapp.com/attachments/1409793076955840583/1409796581661605969/architect.png",
    },
    "General": {
        "effects": "All benders' ATK +5%",
        "image_url": "https://cdn.discordapp.com/attachments/1409793076955840583/1409796597277266000/general.png",
    },
    "Governor": {
        "effects": "All Benders' recruiting speed +10%",
        "image_url": "https://cdn.discordapp.com/attachments/1409793076955840583/1409796936227356723/governor.png",
    },
    "Prefect": {
        "effects": "Research Speed +10%",
        "image_url": "https://cdn.discordapp.com/attachments/1409793076955840583/1409797574763741205/prefect.png",
    },
}

# Add a calculated 'icon_filename' field to each title
for title, data in TITLES_CATALOG.items():
    data['icon_filename'] = data['image_url'].split('/')[-1]

REQUESTABLE_TITLES = {"Architect", "Governor", "Prefect", "General"}
ORDERED_TITLES = list(TITLES_CATALOG.keys())