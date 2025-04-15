from datetime import datetime
import io
import logging
import os
import configparser
import threading
import discord
from discord import app_commands
from discord.ext import commands
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gbx import Gbx2020
from google.api_core import retry

# Configuration
logging.basicConfig(level=logging.CRITICAL)
dir_path = os.path.dirname(os.path.realpath(__file__))
secrets = os.path.join(dir_path, "secrets")
config = configparser.ConfigParser(allow_unnamed_section=True)
config.read(os.path.join(secrets, "secrets.ini"))
DISCORD_TOKEN = config.get(configparser.UNNAMED_SECTION, 'discord')
GOOGLE_SECRET = config.get(configparser.UNNAMED_SECTION, 'google')
GOOGLE_SHEET_ID = config.get(configparser.UNNAMED_SECTION, 'sheet_id')
GOOGLE_CREDS_FILE = os.path.join(secrets, GOOGLE_SECRET)
MIN_MAP_LENGTH = 15
MAX_MAP_LENGTH = 60

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Initialize Google Drive service
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS_FILE, SCOPES)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet("Uploads")
sheet_lock = threading.Lock()

@retry.Retry()
def add_sheet_row(row):
    with sheet_lock:
        sheet.append_row(row, value_input_option='USER_ENTERED')

@retry.Retry()
def find_map_row(username, map_uid=None, map_name=None):
    with sheet_lock:
        records = sheet.get_all_records()
        for i, row in enumerate(records, start=2):  # Rows start at 2 (1=header)
            if row['User'] == username and (row['Map Name'] == map_name or row['UID'] == map_uid):
                return i
        return None

@retry.Retry()
def delete_sheet_row(row_num):
    with sheet_lock:
        sheet.delete_rows(row_num)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} commands")
    except Exception as e:
        logging.error(e)

@bot.tree.command(name="invia", description="Invia la tua mappa")
@app_commands.describe(
    file="La tua mappa",
    descrizione="[Opzionale] Breve descrizione della tua mappa"
)
async def submit(interaction: discord.Interaction, 
                file: discord.Attachment, 
                descrizione: str = None):
    if not file.filename.lower().endswith('.map.gbx'):
        await interaction.response.send_message("❌ Errore: Il file deve avere estensione .Map.Gbx.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:        
        file_content = await file.read()
        filename = file.filename[:-8]
        gbx = Gbx2020(io.BytesIO(file_content))
        at = gbx.get_at_seconds()
        if at < 0:
            await interaction.followup.send(f"❌ Il file della mappa non è valido.", ephemeral=True)
            return
        elif at < MIN_MAP_LENGTH:
            await interaction.followup.send(f"❌ Mappa troppo corta (min {MIN_MAP_LENGTH} secondi).", ephemeral=True)
            return
        elif at > MAX_MAP_LENGTH:
            await interaction.followup.send(f"❌ Mappa troppo lunga (max {MAX_MAP_LENGTH} secondi).", ephemeral=True)
            return
        elif not gbx.get_map_uid():
            await interaction.followup.send(f"❌ Map UID non trovato, assicurati di aver fatto validation e shadows calculation.", ephemeral=True)
            return
        elif find_map_row(interaction.user.name, map_uid=gbx.get_map_uid()):
            await interaction.followup.send(f"❌ La mappa '{filename}' esiste già tra i tuoi caricamenti. Usa /lista per vedere le mappe che hai caricato.", ephemeral=True)
            return
        row = [
            interaction.user.name,
            gbx.get_map_author_login(),
            filename,
            str(gbx.get_at_seconds()),
            descrizione or "",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            gbx.get_map_uid(),
            f'=HYPERLINK("https://trackmania.io/#/leaderboard/{gbx.get_map_uid()}", "Link")',
            "CARICATA"
        ]
        add_sheet_row(row)
        await interaction.followup.send(f"✅ La mappa '{filename}' è stata aggiunta con successo! Ricorda di caricarla sui servizi Nadeo.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Errore nel caricamento della mappa.", ephemeral=True)
        logging.error(f"Error processing submission: {e}")

@bot.tree.command(name="lista", description="Lista delle tue mappe caricate")
async def list_maps(interaction: discord.Interaction):    
    await interaction.response.defer(ephemeral=True)

    username = interaction.user.name
    with sheet_lock:
        records = sheet.get_all_records()
    user_maps = [row for row in records if row['User'] == username]
    if not user_maps:
        await interaction.followup.send("Nessuna mappa caricata a tuo nome in coda.", ephemeral=True)
        return
    maplist = "\n".join(
        f"• **{row['Map Name']}** | AT: {row['AT']}s | " + (f"Desc: {row['Description']} | " if row['Description'] else '') + f"Status: {row['Status']}"
        for row in user_maps
    )
    response = f"**Le tue mappe:**\n{maplist}"
    await interaction.followup.send(response, ephemeral=True)

@bot.tree.command(name="rimuovi", description="Rimuovi una delle tue mappe")
@app_commands.describe(
    nome="Nome della mappa da rimuovere"
)
async def remove_map(interaction: discord.Interaction, nome: str):    
    await interaction.response.defer(ephemeral=True)
    username = interaction.user.name
    row_num = find_map_row(username, map_name=nome)
    
    if not row_num:
        await interaction.followup.send(f"❌ La mappa '{nome}' non esiste. Usa /lista per vedere quelle che hai caricato.", ephemeral=True)
        return
    try:
        delete_sheet_row(row_num)
        await interaction.followup.send(f"✅ La mappa '{nome}' è stata rimossa con successo.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Errore nella rimozione della mappa.", ephemeral=True)
        logging.error(f"Error removing map: {e}")

bot.run(DISCORD_TOKEN)
