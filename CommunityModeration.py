from __future__  import annotations

import asyncio
import datetime
import os

import discord
from discord.ext import commands


COMMUNITY_MODERATION_VOTE_TYPES = {
    "TIMEOUT": 0,
    "BAN": 1,
    "VC_MUTE": 2,
    "VC_DEAFEN": 3,
}

VOTE_EXPIRATION_DURATION = 10 * 60 # 10 minutes

def convert_duration_to_seconds(value: int, unit: str) -> int:
    if unit == 's': 
        return value
    elif unit == 'm': 
        return value * 60
    elif unit == 'h': 
        return value * (60 * 60) # 3600
    elif unit == 'd': 
        return value * (24 * (60 * 60)) # 86400
    else: 
        return 0

def is_user_mod_or_other_important(member: discord.Member) -> bool:
    permissions = member.guild_permissions
    mod_perms = [
        permissions.administrator,
        permissions.manage_guild,
        permissions.ban_members,
        permissions.kick_members,
        permissions.manage_channels,
        permissions.manage_roles,
        permissions.moderate_members
    ]
    return any(mod_perms)

def calculate_vote_standing_thingie_ig(member: MemberModerationData) -> str:
    votes = member.moderation_votes_types_values
    #random thought dumping
    #im thinking there should be 15 votes minimum for an automated ban, but if the user being banned has higher roles than the users it will prevent that to prevent accidentally banning mods or other important people
    #if the ban threshold isnt reached, the ban votes should be added to the timeout votes
    #if the user gets deafened then they should also get muted, but if the votes dont reach the deafen threshold then they should be added to mute but decreased by a certain percentage to keep it even
    
    # for timeouts and bans
    is_mod = is_user_mod_or_other_important(member.member)
    later_timeout_votes_amount = votes["TIMEOUT"] + int(votes["BAN"] / 2) if votes["BAN"] >= 2 else votes["TIMEOUT"] + votes["BAN"]
    if votes["BAN"] >= 15:
        if is_mod:
            return "TIMEOUT:6h"
        return "BAN"
    elif later_timeout_votes_amount >= 5:
        excess_votes = later_timeout_votes_amount - 5
        moderation_time = 1 + excess_votes
        return f"TIMEOUT:{moderation_time}h"
    
    later_vc_mute_votes_amount = votes["VC_MUTE"] + int(votes["VC_DEAFEN"] / 2) if votes["VC_DEAFEN"] >= 2 else votes["VC_MUTE"] + votes["VC_DEAFEN"]
    if votes["VC_DEAFEN"] >= 7:
        return "VC_DEAFEN"
    elif later_vc_mute_votes_amount >= 7:
        return "VC_MUTE"
    
    return "NONE"

class CommunityModerationVote:
    def __init__(self, against: MemberModerationData, by: MemberModerationData, type: str) -> None:
        self.against: MemberModerationData = against
        self.by: MemberModerationData = by
        self.moderation_type = type

    async def _run_vote(self) -> None:
        self.against.votes_against_self += 1
        self.by.votes_against_others += 1
        self.against.members_voted_against_self.append(self)
        self.by.members_voted_against_others.append(self)
        self.against.moderation_votes_types_values[self.moderation_type] += 1
        await self.against._run_community_moderation_check()
        await asyncio.sleep(VOTE_EXPIRATION_DURATION)
        self.against.votes_against_self -= 1
        self.by.votes_against_others -= 1
        self.against.members_voted_against_self.remove(self)
        self.by.members_voted_against_others.remove(self)
        self.against.moderation_votes_types_values[self.moderation_type] -= 1

class MemberModerationData:
    _instances = {}
    
    def __new__(cls, id: str, *args, **kwargs): # random note but i wanna make the `id` a string thats literally just "{guild.id}{member.id}" so uh im putting this here so i dont forget later lmao
        if id not in cls._instances:
            instance = super(MemberModerationData, cls).__new__(cls)
            cls._instances[id] = instance
        return cls._instances[id]

    def __init__(self, id: str, member: discord.Member):
        if not hasattr(self, 'initialized'):
            self.member: discord.Member = member
        
            self.votes_against_self: int = 0
            """
            The amount of votes against this user
            """
            self.votes_against_others: int = 0
            """
            The amount of votes this user made against other users
            """
            self.members_voted_against_self: list[CommunityModerationVote] = []
            """
            The members that voted against this user
            """
            self.members_voted_against_others: list[CommunityModerationVote] = []
            """
            The members that this user voted against
            """
            
            self.moderation_votes_types_values: dict[str, int] = {
                "TIMEOUT": 0,
                "BAN": 0,
                "VC_MUTE": 0,
                "VC_DEAFEN": 0
            }
    
            self.id = id
            self.initialized = True

    async def _run_community_moderation_check(self): # idk maybe i'll make this return an embed or something
        moderation_result: str = calculate_vote_standing_thingie_ig(self)
        if moderation_result != "NONE":
            if "TIMEOUT" in moderation_result:
                time_str = moderation_result.split(":")[1]
                value = int(time_str[:-1])
                unit = time_str[-1]
                timeout_seconds = convert_duration_to_seconds(value, unit)
                timeout_timedelta = datetime.timedelta(seconds = timeout_seconds)
                await self.member.timeout(until = timeout_timedelta, reason = "Community Vote")
            elif moderation_result == "BAN":
                await self.member.ban(delete_message_days = 7, reason = "Community Vote")
            elif moderation_result == "VC_MUTE":
                await self.member.edit(mute = True, reason = "Community Vote")
            elif moderation_result == "VC_DEAFEN":
                await self.member.edit(mute = True, deafen = True, reason = "Community Vote")


class CommunityModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        self.loop = self.bot.loop

