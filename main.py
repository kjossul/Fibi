import io
import os
import discord
from discord import app_commands
from discord.ext import commands
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import tempfile
from pathlib import Path
import configparser
import requests
from googleapiclient.http import MediaIoBaseUpload

# Configuration
dir_path = os.path.dirname(os.path.realpath(__file__))
secrets = os.path.join(dir_path, "secrets")
config = configparser.ConfigParser(allow_unnamed_section=True)
config.read(os.path.join(secrets, "secrets.ini"))
DISCORD_TOKEN = config.get(configparser.UNNAMED_SECTION, 'discord')
GOOGLE_DRIVE_ROOT_FOLDER_ID = config.get(configparser.UNNAMED_SECTION, 'drive_root_id')
GOOGLE_SECRET = config.get(configparser.UNNAMED_SECTION, 'google')
GOOGLE_CREDS_FILE = os.path.join(secrets, GOOGLE_SECRET)

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Initialize Google Drive service
SCOPES = ['https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_file(
    GOOGLE_CREDS_FILE, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=creds)

def get_user_folder_id(user_name):
    """Get or create user-specific folder in Google Drive"""
    query = f"'{GOOGLE_DRIVE_ROOT_FOLDER_ID}' in parents and name='TMITA' and mimeType='application/vnd.google-apps.folder'"
    result = drive_service.files().list(q=query, fields="files(id)").execute()
    tmita_folder_id = result['files'][0]['id'] if result['files'] else None
    
    if not tmita_folder_id:
        file_metadata = {
            'name': 'TMITA',
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [GOOGLE_DRIVE_ROOT_FOLDER_ID]
        }
        tmita_folder = drive_service.files().create(body=file_metadata, fields='id').execute()
        tmita_folder_id = tmita_folder['id']
    
    query = f"'{tmita_folder_id}' in parents and name='{user_name}' and mimeType='application/vnd.google-apps.folder'"
    result = drive_service.files().list(q=query, fields="files(id)").execute()
    user_folder_id = result['files'][0]['id'] if result['files'] else None
    
    if not user_folder_id:
        file_metadata = {
            'name': user_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [tmita_folder_id]
        }
        user_folder = drive_service.files().create(body=file_metadata, fields='id').execute()
        user_folder_id = user_folder['id']
    
    return user_folder_id

def file_exists_in_folder(folder_id, file_name):
    """Check if a file already exists in the specified folder"""
    query = f"'{folder_id}' in parents and name='{file_name}'"
    result = drive_service.files().list(q=query, fields="files(id)").execute()
    return len(result['files']) > 0

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(e)

@bot.tree.command(name="submit", description="Submit a map for consideration")
@app_commands.describe(
    map_file="The map file (.Map.Gbx)",
    length="Map length in seconds",
    tags="Comma-separated tags for the map",
    description="Optional description of the map"
)
async def submit(interaction: discord.Interaction, 
                map_file: discord.Attachment, 
                length: int, 
                tags: str, 
                description: str = None):
    if not map_file.filename.lower().endswith('.map.gbx'):
        await interaction.response.send_message("Error: File must have .Map.Gbx extension.", ephemeral=True)
        return
    
    if length <= 0:
        await interaction.response.send_message("Error: Length must be a positive number.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        user_folder_id = get_user_folder_id(interaction.user.name)
        
        if file_exists_in_folder(user_folder_id, map_file.filename):
            await interaction.followup.send(f"❌ A file with name '{map_file.filename}' already exists in your folder. Please rename your file and try again.", ephemeral=True)
            return
        
        # File metadata with custom properties
        file_metadata = {
            'name': map_file.filename,
            'parents': [user_folder_id],
            'properties': {
                'length': str(length),
                'tags': tags,
                'description': description if description else '',
                'discord_user_id': str(interaction.user.id),
                'discord_username': interaction.user.name
            }
        }

        file_content = await map_file.read() 
        file_stream = io.BytesIO(file_content)
        media = MediaIoBaseUpload(file_stream, mimetype='application/octet-stream', resumable=True)
        drive_service.files().create(body=file_metadata, media_body=media).execute()

        await interaction.followup.send(f"✅ Your map '{map_file.filename}' has been successfully submitted!", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)
        print(f"Error processing submission: {e}")

@bot.tree.command(name="list", description="List all your submitted maps")
async def list_maps(interaction: discord.Interaction):    
    await interaction.response.defer(ephemeral=True)
    
    try:
        user_folder_id = get_user_folder_id(interaction.user.name)
        query = f"'{user_folder_id}' in parents"
        results = drive_service.files().list(q=query, fields="files(name,properties)").execute()
        files = results.get('files', [])
        
        if not files:
            await interaction.followup.send("You haven't submitted any maps yet.", ephemeral=True)
            return
        
        response = "**Your submitted maps:**\n"
        for file in files:
            props = file.get('properties', {})
            response += f"- **{file['name']}**\n"
            response += f"  Length: {props.get('length', 'N/A')}s\n"
            response += f"  Tags: {props.get('tags', 'None')}\n"
            if props.get('description'):
                response += f"  Description: {props['description']}\n"
            response += "\n"
        
        await interaction.followup.send(response, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)
        print(f"Error listing maps: {e}")

@bot.tree.command(name="remove", description="Remove one of your submitted maps")
@app_commands.describe(
    map_name="Name of the map to remove"
)
async def remove_map(interaction: discord.Interaction, map_name: str):    
    await interaction.response.defer(ephemeral=True)
    
    try:
        user_folder_id = get_user_folder_id(interaction.user.name)
        query = f"'{user_folder_id}' in parents and name='{map_name}'"
        results = drive_service.files().list(q=query, fields="files(id)").execute()
        files = results.get('files', [])
        
        if not files:
            await interaction.followup.send(f"❌ No map named '{map_name}' found in your submissions.", ephemeral=True)
            return
        
        file_id = files[0]['id']
        drive_service.files().delete(fileId=file_id).execute()
        await interaction.followup.send(f"✅ Map '{map_name}' has been successfully removed.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)
        print(f"Error removing map: {e}")

bot.run(DISCORD_TOKEN)