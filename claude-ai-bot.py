import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import json
import os
from datetime import datetime, timedelta
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StravaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
        # Configuration - Set these as environment variables
        self.strava_client_id = os.getenv('STRAVA_CLIENT_ID')
        self.strava_client_secret = os.getenv('STRAVA_CLIENT_SECRET')
        self.discord_channel_id = int(os.getenv('DISCORD_CHANNEL_ID', 0))
        self.discord_bot_token = os.getenv('DISCORD_BOT_TOKEN')
        
        # Storage for athlete access tokens and last checked timestamps
        self.athlete_tokens = {}
        self.last_checked = {}
        
        # Load saved data on startup
        self.load_data()

        # Register Commands
        self.add_command(self.add_athlete)

        
    def load_data(self):
        """Load athlete tokens and timestamps from file"""
        try:
            with open('C:\\Users\\alex\\OneDrive\\Documents\\Scatch\\Stava-Discord-Int\\bot_data.json', 'r') as f:
                data = json.load(f)
                self.athlete_tokens = data.get('athlete_tokens', {})
                self.last_checked = data.get('last_checked', {})
        except FileNotFoundError:
            logger.info("No saved data found, starting fresh")
    
    def save_data(self):
        """Save athlete tokens and timestamps to file"""
        data = {
            'athlete_tokens': self.athlete_tokens,
            'last_checked': self.last_checked
        }
        with open('bot_data.json', 'w') as f:
            json.dump(data, f, indent=2)
    
    async def on_ready(self):
        logger.info(f'{self.user} has connected to Discord!')
        if not self.check_activities.is_running():
            self.check_activities.start()

    @commands.command(name='add_athlete')
    async def add_athlete(self, ctx):
        """Add an athlete to monitor. Requires manual token setup."""
        await ctx.send(f"To add athlete , you need to complete OAuth flow manually.")
        await ctx.send("Visit: https://www.strava.com/oauth/authorize?client_id={}&response_type=code&redirect_uri=http://localhost&scope=read,activity:read_all".format(self.strava_client_id))
        await ctx.send("After authorization, use `!set_token <athlete_id> <access_token>` to set the token")
    
    @commands.command(name='set_token')
    async def set_token(self, ctx, athlete_id: str, access_token: str):
        """Set access token for an athlete"""
        self.athlete_tokens[athlete_id] = access_token
        self.last_checked[athlete_id] = datetime.now().isoformat()
        self.save_data()
        await ctx.send(f"Token set for athlete {athlete_id}")
    
    @commands.command(name='remove_athlete')
    async def remove_athlete(self, ctx, athlete_id: str):
        """Remove an athlete from monitoring"""
        if athlete_id in self.athlete_tokens:
            del self.athlete_tokens[athlete_id]
            del self.last_checked[athlete_id]
            self.save_data()
            await ctx.send(f"Removed athlete {athlete_id}")
        else:
            await ctx.send(f"Athlete {athlete_id} not found")
    
    @commands.command(name='list_athletes')
    async def list_athletes(self, ctx):
        """List all monitored athletes"""
        if self.athlete_tokens:
            athletes = list(self.athlete_tokens.keys())
            await ctx.send(f"Monitoring athletes: {', '.join(athletes)}")
        else:
            await ctx.send("No athletes being monitored")
    
    @tasks.loop(minutes=15)  # Check every 15 minutes
    async def check_activities(self):
        """Check for new activities from monitored athletes"""
        if not self.athlete_tokens:
            return
            
        channel = self.get_channel(self.discord_channel_id)
        if not channel:
            logger.error(f"Could not find channel with ID {self.discord_channel_id}")
            return
        
        for athlete_id, access_token in self.athlete_tokens.items():
            try:
                activities = await self.get_recent_activities(athlete_id, access_token)
                for activity in activities:
                    await self.post_activity(channel, activity, athlete_id)
                    
                # Update last checked time
                self.last_checked[athlete_id] = datetime.now().isoformat()
                
            except Exception as e:
                logger.error(f"Error checking activities for athlete {athlete_id}: {e}")
        
        self.save_data()
    
    async def get_recent_activities(self, athlete_id, access_token):
        """Fetch recent activities from Strava API"""
        headers = {'Authorization': f'Bearer {access_token}'}
        
        # Calculate time window (since last check or last 24 hours)
        last_check = self.last_checked.get(athlete_id)
        if last_check:
            after_timestamp = int(datetime.fromisoformat(last_check).timestamp())
        else:
            after_timestamp = int((datetime.now() - timedelta(hours=24)).timestamp())
        
        url = f"https://www.strava.com/api/v3/athlete/activities"
        params = {
            'after': after_timestamp,
            'per_page': 10
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    activities = await response.json()
                    return activities
                else:
                    logger.error(f"Failed to fetch activities: {response.status}")
                    return []
    
    async def post_activity(self, channel, activity, athlete_id):
        """Post activity to Discord channel"""
        # Create embed for the activity
        embed = discord.Embed(
            title=f"🏃 New Activity: {activity['name']}",
            color=0xFC4C02  # Strava orange
        )
        
        # Add athlete info
        embed.add_field(
            name="Athlete",
            value=f"{activity.get('athlete', {}).get('firstname', 'Unknown')} {activity.get('athlete', {}).get('lastname', '')}".strip() or f"Athlete {athlete_id}",
            inline=True
        )
        
        # Add activity type and date
        embed.add_field(
            name="Type",
            value=activity['type'],
            inline=True
        )
        
        activity_date = datetime.fromisoformat(activity['start_date_local'].replace('Z', '+00:00'))
        embed.add_field(
            name="Date",
            value=activity_date.strftime("%Y-%m-%d %H:%M"),
            inline=True
        )
        
        # Add distance and duration if available
        if activity.get('distance'):
            distance_km = activity['distance'] / 1000
            embed.add_field(
                name="Distance",
                value=f"{distance_km:.2f} km",
                inline=True
            )
        
        if activity.get('moving_time'):
            hours, remainder = divmod(activity['moving_time'], 3600)
            minutes, seconds = divmod(remainder, 60)
            time_str = f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
            embed.add_field(
                name="Time",
                value=time_str,
                inline=True
            )
        
        # Add elevation gain if available
        if activity.get('total_elevation_gain'):
            embed.add_field(
                name="Elevation Gain",
                value=f"{activity['total_elevation_gain']:.0f} m",
                inline=True
            )
        
        # Add description if available
        if activity.get('description'):
            embed.add_field(
                name="Description",
                value=activity['description'][:1024],  # Discord embed field limit
                inline=False
            )
        
        # Add Strava link
        embed.add_field(
            name="View on Strava",
            value=f"[Open Activity](https://www.strava.com/activities/{activity['id']})",
            inline=False
        )
        
        embed.set_footer(text="Powered by Strava API")
        
        await channel.send(embed=embed)
        logger.info(f"Posted activity {activity['id']} for athlete {athlete_id}")

# Create and run the bot
if __name__ == "__main__":
    # Check for required environment variables
    required_vars = ['DISCORD_BOT_TOKEN', 'STRAVA_CLIENT_ID', 'STRAVA_CLIENT_SECRET', 'DISCORD_CHANNEL_ID']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        exit(1)
    
    print(os.getenv('DISCORD_BOT_TOKEN'))

    bot = StravaBot()

    bot.run(os.getenv('DISCORD_BOT_TOKEN'))