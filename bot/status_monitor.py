"""
Status monitoring utilities for the Discord bot.
This provides helpful debugging information and health checks.
"""
import os
import time
import json
import discord
import psutil
import platform
from datetime import datetime, timedelta

class StatusMonitor:
    """Monitor and report on the bot's status and health"""
    
    def __init__(self, bot):
        """Initialize the status monitor"""
        self.bot = bot
        self.start_time = time.time()
        self.command_usage = {}  # Command usage statistics
        self.rate_limit_events = []  # Track rate limit events
        self.voice_connections = {}  # Track voice connection status
        
    def get_uptime(self):
        """Get bot uptime in a readable format"""
        uptime_seconds = time.time() - self.start_time
        uptime = timedelta(seconds=int(uptime_seconds))
        return str(uptime)
    
    def get_memory_usage(self):
        """Get current memory usage"""
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        return {
            "rss_mb": memory_info.rss / (1024 * 1024),  # Convert to MB
            "vms_mb": memory_info.vms / (1024 * 1024),
            "percent": process.memory_percent()
        }
    
    def get_cpu_usage(self):
        """Get current CPU usage"""
        return psutil.cpu_percent(interval=0.5)
    
    def record_command_usage(self, command_name):
        """Record usage of a command"""
        if command_name not in self.command_usage:
            self.command_usage[command_name] = 0
        self.command_usage[command_name] += 1
    
    def record_rate_limit(self, endpoint, retry_after):
        """Record a rate limit event"""
        self.rate_limit_events.append({
            "time": time.time(),
            "endpoint": endpoint,
            "retry_after": retry_after
        })
        
        # Keep only the last 50 rate limit events
        if len(self.rate_limit_events) > 50:
            self.rate_limit_events = self.rate_limit_events[-50:]
    
    def update_voice_connection(self, guild_id, status, details=None):
        """Update status of a voice connection"""
        self.voice_connections[guild_id] = {
            "status": status,
            "updated_at": time.time(),
            "details": details
        }
    
    def get_full_status(self):
        """Get full status report for the bot"""
        # Get guild count and user count
        guild_count = len(self.bot.guilds)
        user_count = sum(guild.member_count for guild in self.bot.guilds)
        
        # Get command count
        command_count = len(self.bot.commands)
        
        # Get active voice connections
        voice_connections = sum(1 for vc in self.bot.voice_clients if vc.is_connected())
        
        status = {
            "bot": {
                "name": self.bot.user.name if self.bot.user else "Unknown",
                "id": str(self.bot.user.id) if self.bot.user else "Unknown",
                "uptime": self.get_uptime(),
                "latency_ms": round(self.bot.latency * 1000, 2),
            },
            "stats": {
                "guilds": guild_count,
                "users": user_count,
                "commands": command_count,
                "voice_connections": voice_connections,
                "command_usage": self.command_usage
            },
            "system": {
                "memory": self.get_memory_usage(),
                "cpu_percent": self.get_cpu_usage(),
                "python_version": platform.python_version(),
                "discord_py_version": discord.__version__,
                "platform": platform.platform()
            },
            "rate_limiting": {
                "recent_events": len(self.rate_limit_events),
                "last_event": self.rate_limit_events[-1] if self.rate_limit_events else None
            }
        }
        
        return status
    
    async def send_status_to_channel(self, channel):
        """Send a status embed to a Discord channel"""
        status = self.get_full_status()
        
        # Create an embed with the status information
        embed = discord.Embed(
            title="Bot Status Report",
            description=f"Status report for {status['bot']['name']}",
            color=0x00ff00  # Green color
        )
        
        # Add bot info
        embed.add_field(
            name="Bot Info", 
            value=(f"**Name:** {status['bot']['name']}\n"
                   f"**ID:** {status['bot']['id']}\n"
                   f"**Uptime:** {status['bot']['uptime']}\n"
                   f"**Latency:** {status['bot']['latency_ms']} ms"), 
            inline=False
        )
        
        # Add stats
        embed.add_field(
            name="Stats", 
            value=(f"**Guilds:** {status['stats']['guilds']}\n"
                   f"**Users:** {status['stats']['users']}\n"
                   f"**Commands:** {status['stats']['commands']}\n"
                   f"**Voice Connections:** {status['stats']['voice_connections']}"), 
            inline=False
        )
        
        # Add system info
        mem_info = status['system']['memory']
        embed.add_field(
            name="System", 
            value=(f"**Memory:** {mem_info['rss_mb']:.1f} MB ({mem_info['percent']:.1f}%)\n"
                   f"**CPU:** {status['system']['cpu_percent']}%\n"
                   f"**Platform:** {status['system']['platform']}\n"
                   f"**Discord.py:** {status['system']['discord_py_version']}"), 
            inline=False
        )
        
        # Add most used commands if available
        if status['stats']['command_usage']:
            # Get top 5 commands
            top_commands = sorted(status['stats']['command_usage'].items(), 
                                 key=lambda x: x[1], reverse=True)[:5]
            
            cmd_str = "\n".join([f"**{cmd}:** {count} uses" for cmd, count in top_commands])
            embed.add_field(name="Top Commands", value=cmd_str, inline=False)
        
        # Add rate limiting info
        if status['rate_limiting']['last_event']:
            last_event = status['rate_limiting']['last_event']
            time_ago = time.time() - last_event['time']
            minutes_ago = int(time_ago / 60)
            
            embed.add_field(
                name="Rate Limiting", 
                value=(f"**Recent Events:** {status['rate_limiting']['recent_events']}\n"
                       f"**Last Event:** {minutes_ago} minutes ago\n"
                       f"**Endpoint:** {last_event['endpoint']}\n"
                       f"**Retry After:** {last_event['retry_after']} seconds"), 
                inline=False
            )
        
        embed.set_footer(text=f"Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        await channel.send(embed=embed)
        return True