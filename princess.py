import asyncio
from datetime import datetime
import logging
from typing import Any, Optional
from pathlib import Path
import random

import discord
from discord import app_commands, ui
from discord.ext import commands
from openai import AsyncOpenAI
import yaml
import json
import re

# ─── Configuration ───

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

EMBED_COLOR_COMPLETE = discord.Color.dark_green()
EMBED_COLOR_INCOMPLETE = discord.Color.orange()
EMBED_COLOR_PRINCESS = discord.Color.from_rgb(255, 105, 180)
EMBED_COLOR_EVENT = discord.Color.from_rgb(255, 215, 0)  # Gold for random events
EMBED_COLOR_ENDING = discord.Color.from_rgb(148, 0, 211)  # Purple for endings

STREAMING_INDICATOR = " ⚪"
EDIT_DELAY_SECONDS = 1
SEPTIC_STATS = ["Strength", "Empathy", "Personality", "Turpitude", "Intelligence", "Constitution"]

HIDDEN_STATS = ["vaginal", "oral", "anal", "breast", "face", "feet"]

# Constants
MAX_RECENT_MESSAGES = 5
MAX_EVENT_LOG = 10
STAT_MIN = 0
STAT_MAX = 25

# Random chance for events per interaction
RANDOM_EVENT_CHANCE = 0.1

# Event summary truncation
EVENT_SUMMARY_USER_LIMIT = 200
EVENT_SUMMARY_NARRATIVE_LIMIT = 300

# Adult bonuses
ADULT_WORDCOUNT_BONUS_THRESHOLD = 50
ADULT_WORDCOUNT_BONUS_AMOUNT = 2

DEFAULT_ADULT_THRESHOLDS = {"Turpitude": 5, "Personality": 5}
STAT_EVAL_NARRATIVE_LIMIT = 1500
FAMILIARITY_THRESHOLDS = (5, 20, 50)

# Ending triggers
ENDING_INTERACTION_THRESHOLD = 50
ENDING_STAT_SUM_THRESHOLD = 50

DATA_DIR = Path(__file__).parent / "princess_data"
DATA_DIR.mkdir(exist_ok=True)

CONFIG_FILE = Path(__file__).parent / "config-princess.yaml"

# The genetic lottery
HAIR_COLORS = ["platinum blonde", "ink black", "cherry red", "ash brown", "honey blonde"]
EYE_COLORS = ["icy blue", "emerald green", "warm amber", "deep hazel", "steel gray"]
HEIGHTS = ["petite", "average height", "tall", "statuesque"]


def get_config(filename: str = None) -> dict[str, Any]:
    path = filename or str(CONFIG_FILE)
    with open(path, encoding="utf-8") as file:
        return yaml.safe_load(file)


config = get_config()
curr_model = next(iter(config["models"]))

last_task_time = 0

intents = discord.Intents.default()
intents.message_content = True
activity = discord.CustomActivity(name="Raising my stepsister")
discord_bot = commands.Bot(intents=intents, activity=activity, command_prefix=None)

# channel_id -> user_id
active_sessions: dict[int, int] = {}

# ═══════════════════════════════════════════════════
#  STRUCTURED ACTIVITIES (PM2-style)
# ═══════════════════════════════════════════════════

ACTIVITIES = {
    "strength_vs_empathy": {
        "label": "MMA Training",
        "description": "Intense martial arts drills to builds physical power but harden emotional barriers",
        "emoji": "🥊",
        "stat_hints": {"Constitution": "+"},
        "prompt_context": "You head into the back yard to engage in a day of intense MMA training.",
    },
    "strength_vs_intelligence": {
        "label": "Manual Labor",
        "description": "Physical work requiring strength",
        "emoji": "🔨",
        "stat_hints": {"Strength": "+"},
        "prompt_context": "You spend the day working a difficult manual labor job of your choice.",
    },
    "empathy_vs_personality": {
        "label": "Private Prayers",
        "description": "Solitary spiritual reflection purges sin",
        "emoji": "🙏",
        "stat_hints": {"Turpitude": "-"},
        "prompt_context": "You head to the local Baptist church and spend time with the minister in prayer.",
    },
    "empathy_vs_turpitude": {
        "label": "Soup Kitchen",
        "description": "Serving the needy strengthens empathy",
        "emoji": "🕊️",
        "stat_hints": {"Empathy": "+"},
        "prompt_context": "You visit the local soup kitchen to spoon food to the helpless and homeless.",
    },
    "personality_vs_intelligence": {
        "label": "Livestreaming",
        "description": "Live online performances enhance charisma",
        "emoji": "📱",
        "stat_hints": {"Personality": "+"},
        "prompt_context": "You sign on to an expensive desktop PC to generate video content for avid viewers.",
    },
    "turpitude_vs_constitution": {
        "label": "All-Night Rave",
        "description": "Nonstop partying embraces indulgence",
        "emoji": "🌙",
        "stat_hints": {"Turpitude": "+"},
        "prompt_context": "You head out at night to dance and party until morning",
    },
    "intelligence_vs_constitution": {
        "label": "Cramming Session",
        "description": "Intense mental focus sharpens the mind",
        "emoji": "📚",
        "stat_hints": {"Intelligence": "+"},
        "prompt_context": "You spend the day studying dense textbooks to improve your mental faculties",
    },
    "turpitude_vs_strength": {
        "label": "Pig Out",
        "description": "Overindulgent eating encourages vices",
        "emoji": "🍔",
        "stat_hints": {"Turpitude": "+"},
        "prompt_context": "A delivery order provides you with a massive amount of food",
    },
}


# ═══════════════════════════════════════════════════
#  RANDOM EVENTS
# ═══════════════════════════════════════════════════

RANDOM_EVENTS = [
    {
        "id": "cold",
        "name": "Caught a Cold",
        "description": "She's feeling under the weather — sneezing, runny nose, the works.",
        "stat_relevance": "Constitution",
        "prompt": "You've caught a cold. You're sneezing, your nose is running, and you feel miserable. If you're tough and resilient, it's just an annoyance — you power through. If you're fragile, this absolutely floors you. Show whether you want comfort from your stepsibling or want to be left alone. React naturally.",
    },
    {
        "id": "found_money",
        "name": "Found Money",
        "description": "She found a $50 bill on the sidewalk.",
        "stat_relevance": "Turpitude",
        "prompt": "You just found a $50 bill on the sidewalk! If you're stylish and confident, you already know exactly what to buy. If you're plain and awkward, you're not sure what to do with it. Are you smart enough to think about saving it? Are you naughty enough to consider spending it on something you shouldn't? Share the news with your stepsibling.",
    },
    {
        "id": "argument",
        "name": "Argument with Friend",
        "description": "She got into a fight with her best friend.",
        "stat_relevance": "Empathy",
        "prompt": "You just had a terrible argument with your best friend. If you're an emotional person, this devastates you and you need to talk through every feeling. If you're emotionally cold, you shrug it off. Did it almost get physical? Can you even articulate what happened clearly? Tell your stepsibling about it.",
    },
    {
        "id": "gift",
        "name": "Surprise Gift",
        "description": "Your shared parents bought her something unexpected.",
        "stat_relevance": "Empathy",
        "prompt": "Your parents (the ones who married each other to form this family) surprised you with an unexpected gift. Are you genuinely touched, or do you suspect their motives? Do you overthink why they gave it? React naturally and tell your stepsibling.",
    },
    {
        "id": "nightmare",
        "name": "Strange Dream",
        "description": "She had a vivid, unsettling dream last night.",
        "stat_relevance": "Intelligence",
        "prompt": "You had an incredibly vivid dream last night. If you're analytical, you try to interpret it — if you're not, you just describe the weird images. Was the dream dark and disturbing, or innocent? Are you comfortable being vulnerable about it, or do you play it off? Describe the dream and tell your stepsibling.",
    },
    {
        "id": "stray_animal",
        "name": "Stray Animal",
        "description": "She found a stray kitten or puppy nearby.",
        "stat_relevance": "Empathy",
        "prompt": "You found a stray kitten (or puppy) outside the house. It's adorable and helpless. Are you the nurturing type who falls in love immediately, or do you find it annoying? Do you confidently pick it up, or hesitate? Do you worry about the practical problems of keeping it? React naturally and tell your stepsibling.",
    },
    {
        "id": "catcalled",
        "name": "Catcalled",
        "description": "Some creep harassed her on the street.",
        "stat_relevance": "Turpitude",
        "prompt": "Some creep catcalled you on the street today. If you're physically strong, maybe you confronted him — squared up, got in his face. If you're weak, you probably felt helpless and scared. Were you flustered, or did you handle it coolly? Did any part of you secretly enjoy the attention? Tell your stepsibling what happened.",
    },
    {
        "id": "power_outage",
        "name": "Power Outage",
        "description": "The electricity went out at home.",
        "stat_relevance": "Constitution",
        "prompt": "The power just went out in the house. It's dark and there's nothing to do. Are you the type to handle discomfort calmly, or do you immediately start complaining? Can you figure out what went wrong, or are you useless with that stuff? Does being stuck in the dark with your stepsibling feel scary, boring, or like an opportunity for something? React naturally.",
    },
    {
        "id": "mysterious_letter",
        "name": "Mysterious Letter",
        "description": "An unmarked envelope appeared in the mailbox.",
        "stat_relevance": "Intelligence",
        "prompt": "You found a mysterious unmarked envelope in the mailbox addressed to you. Do you carefully examine every detail before opening it, or just rip it open? Does your mind jump to something sinister or forbidden? Open it and describe what's inside — make it up based on who you are right now.",
    },
    {
        "id": "old_classmate",
        "name": "Ran into Old Classmate",
        "description": "She bumped into someone from her past.",
        "stat_relevance": "Personality",
        "prompt": "You just ran into someone from your old school — before your parent remarried and you moved here. Was the encounter smooth and charming, or painfully awkward? Did you actually care about reconnecting, or were you just going through the motions? Is there any scandalous history between you two? Tell your stepsibling about them.",
    },
    {
        "id": "food_poisoning",
        "name": "Food Poisoning Scare",
        "description": "Something she ate isn't sitting right.",
        "stat_relevance": "Constitution",
        "prompt": "Something you ate is NOT agreeing with your stomach. You feel nauseous and terrible. If you're tough, it's just mild discomfort. If you're fragile, you're dramatically dying on the couch. Do you accept help gracefully or push people away? Are you embarrassed about the whole thing? React naturally.",
    },
    {
        "id": "party_invite",
        "name": "Party Invitation",
        "description": "She got invited to a party this weekend.",
        "stat_relevance": "Personality",
        "prompt": "Someone you met recently invited you to a party this weekend. Are you already excitedly planning your outfit, or does the thought of social interaction fill you with dread? What kind of party are you hoping it is? Do you want your stepsibling to come along? React and tell them.",
    },
]


# ═══════════════════════════════════════════════════
#  ENDINGS SYSTEM
# ═══════════════════════════════════════════════════

ENDINGS = [
    {
        "id": "warrior_queen",
        "title": "Vigilante Warrior",
        "conditions": lambda s: s["Strength"] >= 18 and s["Constitution"] >= 13 and s["Turpitude"] < 10,
        "description": "She became an unstoppable force of justice — physically dominant, relentlessly tough, championing the vulnerable.",
        "prompt": "You've become the ultimate protector — a vigilante warrior in a world full of injustice. Your strength is legend, your resolve unbreakable. Narrate your final reflection on the fights you've won, your bond with your stepsibling who stood by you, and how you'll keep making this city safer. This is your ending. Be heroic and triumphant.",
    },
    {
        "id": "scholar_empress",
        "title": "Tech Innovator",
        "conditions": lambda s: s["Intelligence"] >= 18 and s["Empathy"] >= 8,
        "description": "Her genius revolutionized industries — brilliant inventor, insightful leader, inspiring change-maker.",
        "prompt": "Your intellect has transformed the world. As a tech innovator, you've built empires from code and ideas. Narrate your final reflection on the breakthroughs that changed everything, your partnership with your stepsibling who believed in you, and the innovations yet to come that will shape humanity's future. This is your ending.",
    },
    {
        "id": "dark_mistress",
        "title": "Shadow Broker",
        "conditions": lambda s: s["Turpitude"] >= 18,
        "description": "She mastered the underworld — morally unbound, manipulative mastermind, pulling strings from the shadows.",
        "prompt": "You've claimed dominion over the unseen world. As the Shadow Broker, every secret, every deal, every weakness is your weapon. Narrate your final reflection on the empire you've built in darkness, your twisted alliance with your stepsibling, and how you'll continue to orchestrate the chaos of society. This is your ending.",
    },
    {
        "id": "healer_saint",
        "title": "Global Humanitarian",
        "conditions": lambda s: s["Empathy"] >= 18 and s["Constitution"] >= 13 and s["Turpitude"] < 5,
        "description": "She healed the world — empathetic powerhouse, tireless advocate, beacon of hope during crises.",
        "prompt": "Your compassion has touched millions. As a global humanitarian, you've brought people together through love and understanding. Narrate your final reflection on the lives you've saved, your unbreakable bond with your stepsibling who shared your mission, and your vision for a kinder world. This is your ending.",
    },
    {
        "id": "femme_fatale",
        "title": "Viral Seductress",
        "conditions": lambda s: s["Personality"] >= 18 and s["Turpitude"] >= 13 and s["Intelligence"] >= 13,
        "description": "She conquered social media — irresistibly charming, cunning influencer, dangerously addictive to follow.",
        "prompt": "You've become the ultimate viral seductress — millions hang on your every post, every tease, every scandalous reveal. Your wit is deadly, your allure unbreakable. Narrate your final reflection on the fame you've wielded like a weapon, your complex dynamic with your stepsibling, and the media empire you'll continue to devastatingly charm. This is your ending.",
    },
    {
        "id": "social_butterfly",
        "title": "Social Media Mogul",
        "conditions": lambda s: s["Personality"] >= 18 and s["Empathy"] >= 13 and s["Turpitude"] < 10,
        "description": "She built a community empire — magnetic personality, genuine warmth, universally adored online sensation.",
        "prompt": "You've created something beautiful — a movement of connection and joy. As a social media mogul, your authenticity shines through every interaction. Narrate your final reflection on the millions who've found belonging through you, your close friendship with your stepsibling, and how you'll keep spreading positivity in this digital world. This is your ending.",
    },
    {
        "id": "iron_maiden",
        "title": "Solo Tycoon",
        "conditions": lambda s: s["Strength"] >= 18 and s["Constitution"] >= 18 and s["Empathy"] < 5,
        "description": "She built an empire alone — relentless entrepreneur, unbreakable will, successful but emotionally isolated.",
        "prompt": "Your ambition knows no bounds. As a solo tycoon, you've bulldozed through every obstacle, every competitor. Narrate your final reflection on the corporation you built from nothing, your estranged relationship with your stepsibling who couldn't keep up, and the solitary throne you'll rule from. This is your ending.",
    },
    {
        "id": "fallen_angel",
        "title": "Whistleblower Activist",
        "conditions": lambda s: s["Empathy"] >= 15 and s["Turpitude"] >= 15,
        "description": "She exposed corruption passionately — deeply caring reformer, using questionable methods, dangerously effective.",
        "prompt": "You've become the force that both inspires and terrifies. As a whistleblower activist, you expose the rot in society while playing by your own rules. Narrate your final reflection on the revolutions you've sparked, your complicated partnership with your stepsibling, and the risky crusade you'll continue to wage. This is your ending.",
    },
    {
        "id": "renaissance_woman",
        "title": "Multifaceted Entrepreneur",
        "conditions": lambda s: all(v >= 10 for v in s.values()),
        "description": "She excelled in everything — balanced professional, capable innovator, inspiring example of modern success.",
        "prompt": "You've mastered the art of modern womanhood. As a multifaceted entrepreneur, you're as comfortable in boardrooms as on podcasts, in labs as at charity galas. Narrate your final reflection on the life of purpose and achievement you've built, your supportive bond with your stepsibling, and the limitless impact you'll continue to make. This is your ending.",
    },
    {
        "id": "ordinary_girl",
        "title": "Everyday Suburban Mom",
        "conditions": lambda s: True,  # Default/fallback ending
        "description": "She lived a quiet, fulfilling life — average but happy, blending in with society.",
        "prompt": "Your story wasn't flashy, but it was real. You've settled into a comfortable life as an everyday suburban mom — weekends with the family, mundane joys, peaceful routines. Narrate your final reflection on the simple warmth of your existence, your loving relationship with your stepsibling, and the quiet satisfaction of an ordinary life well-lived. This is your ending. Make it heartfelt.",
    },
]


def check_ending_conditions(char_data: dict) -> Optional[dict]:
    """Check if any ending conditions are met. Returns the ending dict or None."""
    interactions = char_data.get("total_interactions", 0)
    septic = char_data["septic"]
    stat_sum = sum(septic.values())

    # Must meet at least one threshold to trigger ending check
    if interactions < ENDING_INTERACTION_THRESHOLD and stat_sum < ENDING_STAT_SUM_THRESHOLD:
        return None

    # Already completed
    if char_data.get("ending"):
        return None

    # Check endings in priority order (specific endings first, Ordinary Girl last)
    for ending in ENDINGS:
        if ending["conditions"](septic):
            return ending



# ═══════════════════════════════════════════════════
#  CHARACTER PERSISTENCE
# ═══════════════════════════════════════════════════

def _char_path(user_id: int) -> Path:
    return DATA_DIR / f"{user_id}.json"

def load_character(user_id: int) -> Optional[dict]:
    path = _char_path(user_id)
    if path.exists():
        with open(path, "r") as f:
            data = json.load(f)
        return migrate_character(data)
    return None

def save_character(data: dict):
    path = _char_path(data["user_id"])
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def create_character(user_id: int, name: str) -> dict:
    return {
        "user_id": user_id,
        "name": name,
        "age": 18,
        "septic": {s: 0 for s in SEPTIC_STATS},
        # --- NEW PERMANENT TRAITS ---
        "genetics": {
            "hair_color": random.choice(HAIR_COLORS),
            "eye_color": random.choice(EYE_COLORS),
            "height": random.choice(HEIGHTS),
        },
	"appearance": "",
        "outfit": "",
        "hidden": {s: 0 for s in HIDDEN_STATS},
        "adult_thresholds": {
            "Turpitude": random.randint(1, 10),
            "Personality": random.randint(1, 10),
        },
        "story": [],          # recent raw messages (max MAX_RECENT_MESSAGES)
        "event_log": [],       # one-liner summaries of past interactions (max MAX_EVENT_LOG)
        "total_interactions": 0,
        "ending": None,
        "created_at": datetime.now().isoformat(),
    }

def migrate_character(char_data: dict) -> dict:
    """Add new memory fields to old character data if missing."""
    if "event_log" not in char_data:
        char_data["event_log"] = []
    if "genetics" not in char_data:
        char_data["genetics"] = {
            "hair_color": random.choice(HAIR_COLORS),
            "eye_color": random.choice(EYE_COLORS),
            "height": random.choice(HEIGHTS),
        }
    if "appearance" not in char_data:
        char_data["appearance"] = ""
    if "outfit" not in char_data:
        char_data["outfit"] = ""
    if "septic" not in char_data:
        char_data["septic"] = dict(char_data["septic"])
    if "hidden" not in char_data:
        char_data["hidden"] = dict(char_data["hidden"])
    # Trim old bloated story down to recent messages
    if len(char_data.get("story", [])) > MAX_RECENT_MESSAGES:
        char_data["story"] = char_data["story"][-MAX_RECENT_MESSAGES:]
    return char_data

def clamp_stat(value: int) -> int:
    return max(STAT_MIN, min(STAT_MAX, value))

def _apply_stat_delta(char_data: dict, pool: str, stat: str, delta: int) -> str:
    """Apply a delta to a stat in the given pool, return display string showing attempted change."""
    store = char_data[pool]
    old = store[stat]
    new = clamp_stat(old + delta)
    store[stat] = new
    arrow = "▲" if delta > 0 else "▼"
    note = ""
    if new == old:
        if delta > 0:
            note = "(at max)"
        elif delta < 0:
            note = "(at min)"
    else:
        if (delta > 0 and new == STAT_MAX and old + delta > STAT_MAX) or \
           (delta < 0 and new == STAT_MIN and old + delta < STAT_MIN):
            note = "(capped)"
    return f"{stat} {arrow}{abs(delta)} {note}".strip()

def _stat_bar(val: int) -> str:
    """Render a stat bar like [████░░░░░]."""
    return "█" * val + "░" * (STAT_MAX - val)


def _load_active_character(user_id: int) -> tuple[Optional[dict], Optional[str]]:
    """Load character and check if it's active. Returns (char_data, error_message)."""
    char_data = load_character(user_id)
    if not char_data:
        return None, "No character found. Use `/princess new <name>` first."
    if char_data.get("ending"):
        return None, (
            f"**{char_data['name']}** reached her ending: **{char_data.get('ending_title')}**. "
            f"Use `/princess reset` to start fresh."
        )
    return char_data, None


# ═══════════════════════════════════════════════════
#  SYSTEM PROMPT GENERATION
# ═══════════════════════════════════════════════════

def _describe_hidden_stat(part: str, value: int) -> str:
    """Experience axis — SKILL and FAMILIARITY with specific acts. 
    Low = fumbling newbie curiosity. High = skilled enthusiasm. Max = addiction/corruption kink."""
    if value >= 23:
        return f"ADDICTED to {part} stimulation — craves it constantly, gets off on being 'corrupted', begs for it, can't get enough"
    elif value >= 20:
        return f"obsessed with {part} stimulation — expert-level skill, insatiable appetite, actively seeks it out"
    elif value >= 17:
        return f"loves {part} stimulation — enthusiastic, skilled, knows exactly what she wants and how to get it"
    elif value >= 14:
        return f"really enjoys {part} stimulation — confident and eager, has developed preferences and techniques"
    elif value >= 11:
        return f"comfortable with {part} stimulation — gaining skill and enthusiasm, starting to crave it"
    elif value >= 8:
        return f"warming up to {part} stimulation — still learning but increasingly eager, pleasant discoveries"
    elif value >= 5:
        return f"curious about {part} stimulation — clumsy but willing, nervous excitement, wants to learn"
    elif value >= 2:
        return f"very new to {part} stimulation — fumbling, uncertain, but genuinely curious, not opposed"
    else:
        return f"completely inexperienced with {part} stimulation — awkward and unsure, but not disgusted, just clueless"


def _describe_intimacy_willingness(turpitude: int) -> str:
    """Willingness axis — Turpitude-derived worldliness and comfort with sexuality.
    Low = sheltered innocent. High = worldly and uninhibited. Max = revels in corruption."""
    if turpitude >= 23:
        return "utterly corrupted — she LOVES being dirty, gets off on taboo and 'wrongness', actively corrupts situations, no shame only hunger"
    elif turpitude >= 20:
        return "completely uninhibited — she initiates boldly, suggests filthy things casually, treats sex as play, zero shame"
    elif turpitude >= 17:
        return "sexually confident — she knows what she wants, flirts aggressively, comfortable with her desires, enthusiastic participant"
    elif turpitude >= 14:
        return "open and willing — she doesn't flinch at sexual topics, responds positively to advances, curious about new experiences"
    elif turpitude >= 11:
        return "warming up nicely — she blushes but leans in, can be seduced with patience, starting to enjoy the tension"
    elif turpitude >= 8:
        return "curious but nervous — she notices attraction, gets flustered but doesn't pull away, needs gentle encouragement"
    elif turpitude >= 5:
        return "shy but not unwilling — she deflects awkwardly but sneaks glances, inexperienced not opposed, needs patience"
    elif turpitude >= 2:
        return "very sheltered — physical closeness makes her nervous, she changes subjects, but curiosity is there underneath"
    else:
        return "completely innocent — she doesn't even register sexual undertones, genuinely naive, would need everything explained"


async def generate_bio(char_data: dict) -> str:
    client, model = _get_llm_client()
    name = char_data["name"]

    prompt = (
        f"Based on these details, write a detailed, one paragraph description for {name}. \n"
        f"Focus on her appearance, clothing, personality, and build. \n"
        f"Avoid bullet points, preambles, and followup questions. \n"
        f"DETAILS:\n{char_data['appearance']}"
    )
     
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": prompt}],
            max_tokens=250,
            temperature=1.1
        )
        return f"*\"{response.choices[0].message.content.strip()}\"*"
    except Exception as e:
        logging.error(f"Bio failed: {e}")
        return "Bio failed"

async def generate_outfit(char_data: dict) -> str:
    client, model = _get_llm_client()
    name = char_data["name"]

    prompt = (
        f"Based on these details, write a brief, one sentence description of the outfit {name} is wearing. \n"
        f"DETAILS:\n{char_data['appearance']}"
    )
     
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": prompt}],
            max_tokens=150,
            temperature=1.1
        )
        return f"{response.choices[0].message.content.strip()}"
    except Exception as e:
        logging.error(f"Outfit failed: {e}")
        return "Outfit failed"  
  

async def build_system_prompt(char_data: dict, longform: bool = False) -> str:
    name = char_data["name"]
    septic = char_data["septic"]
    event_log = char_data.get("event_log", [])

    now = datetime.now().astimezone()
    date_str = now.strftime("%B %d, %Y")
    time_str = now.strftime("%I:%M %p %Z")

    char_data["appearance"] = build_appearance_string(char_data)

    # Adult content gating
    if is_adult_unlocked(char_data):
        adult_rules = (
            f"### ADULT CONTENT UNLOCKED:\n"
            f"Explicit sexual interactions are permitted.\n"
             f"Your Turpitude shapes WHETHER you engage. Your 'body part stats' shapes 'experience' or HOW you engage. "
            f"Inexperienced doesn't mean unwilling — fumble, be awkward, learn."
        )
    else:
        adult_rules = (
            "### ADULT CONTENT LOCKED:\n"
            "Explicit sexual acts are off-limits for now. "
            "But light intimacy (flirting, touching, closeness) is fine — react based on your intimacy disposition above."
        )

    # Memory section
    memory_section = ""
    if event_log:
        entries = "\n".join(f"- {e}" for e in event_log[-MAX_EVENT_LOG:])
        memory_section = f"\nYOUR MEMORIES: (things that have happened to you):\n{entries}\n"

    who = (
        f"### WHO YOU ARE:\n\n"       
        f"### IMPORTANT:\n"
        f"Your physical, mental, outfit, and moral states have EVOLVED.\n"
        f"Use the CURRENT INFORMATION listed below to describe yourself, ignoring your states in the previous messages.\n"
        f"When describing yourself or your actions, allude to your current state: {char_data["appearance"]}\n. "
    )

    # Length rules
    if longform:
        length_rules = (
            "Write 2-4 paragraphs of immersive narrative. Describe environment, body language, "
            "internal thoughts."
        )
    else:
        length_rules = "Write one creative, immersive paragraph capturing the essence of the activities."

    prompt = f"""You are {name}, an 18-year-old woman. The user is your older stepsibling.\n
{who}\n
{adult_rules}\n
{memory_section}\n\n
RULES:\n
- Write in clear, natural prose. Avoid repetitive alliteration or excessively long, comma-spliced sentences.\n
- Never break character. Never acknowledge being an AI. Never mention stats, stat names, or game mechanics.\n
- Show traits through actions, dialogue, and body language — never explain them.\n
- When the user suggests an activity, narrate it HAPPENING with a concrete outcome. Never ask clarifying questions.\n
- {length_rules}\n
- Have opinions. Have moods. Disagree sometimes."""

    logging.info(f"\n[DEBUG] SYSTEM PROMPT FOR {char_data['name']}:\n{prompt}\n")

    return prompt

def build_stat_eval_prompt(
    char_data: dict, user_message: str, narrative: str,
    activity_hints: Optional[dict] = None, eval_mode: str = "normal"
) -> str:
    septic = char_data["septic"]
    hidden = char_data["hidden"]

    hint_text = ""
    if activity_hints:
        hints = [f"{stat} tends to go {direction}" for stat, direction in activity_hints.items()]
        hint_text = f"\nACTIVITY STAT TENDENCIES (these are hints, not mandates): {', '.join(hints)}\n"

    # Mode-specific rules
    if eval_mode == "adult":
        mode_rules = (
            "This is an ADULT/SEXUAL interaction. Special rules:\n"
            "- Do NOT change any SEPTIC stats. Leave septic_changes empty.\n"
            "- ONLY change hidden body part stats that are DIRECTLY relevant to the sexual acts described.\n"
            "- Each hidden stat change is EXACTLY +1.\n"
            "- Only change parts that were explicitly involved in the scene. If the scene involved oral acts, change 'oral'. If it involved breasts, change 'breast'. Etc.\n"
        )
        septic_example = '"septic_changes": {}'
    elif eval_mode == "event":
        mode_rules = (
            "A RANDOM EVENT has occurred. Special rules apply:\n"
            "- You MUST change EXACTLY 1 SEPTIC stats.\n"
            "- Each change must be EXACTLY +3 or -3. No other values.\n"
            "- Pick the 1 stats most relevant to the event as described.\n"
            "- Do NOT change any hidden body part stats. Leave hidden_changes empty. Non-adult events NEVER affect hidden stats."
        )
        septic_example = '"septic_changes": {"Constitution": -2, "Empathy": 2}'
    elif eval_mode == "intimate":
        mode_rules = (
            "This is an INTIMATE (non-explicit) interaction — flirting, touching, closeness.\n"
            "- Adjust Turpitude up by +1 and Personality up by +1.\n"
            "- You MAY change 0-1 hidden body part stat if physical contact was specific enough to a body area.\n"
            "  Example: caressing her face → 'face' +1. Holding hands → no hidden change (too general).\n"
            "- If the contact was too vague or general, leave hidden_changes empty."
        )
        septic_example = '"septic_changes": {"Turpitude": 1, "Personality": 1}'
    elif eval_mode == "freeform":
        mode_rules = (
            "This is a FREEFORM ACTIVITY. Special rules apply:\n"
            "- You MUST change EXACTLY 2 SEPTIC stats.\n"
            "- The change can be -1, or +1.\n"
            "- Evaluate the detailed description of the activity provided and consider which two stats were likely to have been affected.\n"
            "- If the stat was likely to have improved - that gets a +1.\n"
            "- If the stat was likely to have deteriorated - that gets a -1.\n"
            "- The result can be any combination of +1 and -1, but it MUST be for two stats.\n"
            "- Do NOT change any hidden body part stats. Leave hidden_changes empty. Non-adult activities NEVER affect hidden stats."
        )
        septic_example = '"septic_changes": {"Strength": 1, "Empathy": -1}'
    elif eval_mode == "normal":
        mode_rules = (
            "This is a LONGFORM RESPONSE. Special rules apply:\n"
            " - You MUST change EXACTLY 1 SEPTIC stat.\n"
            " - The change can vary from +3, to +2, to +1, to 0, to +1, to +2, to +3.\n"
            " - Evaluate the detailed description of the activity provided in the past two messages and determine the MOST likely stat to have been affected.\n"
            " - If the description had little effect, the stat gets 0, do not mention it.\n"
            " - If the description had a minor benefit to the stat, it gets +1.\n"
            " - If the description had a minor detriment to the stat, it gets -1.\n"
            " - If the description had a good benefit to the stat, it gets +2.\n"
            " - If the description had a bad detriment to the stat, it gets -2.\n"
            " - If the description had a major benefit to the stat, it gets +3.\n"
            " - If the description had a major detriment to the stat, it gets -3.\n"
            " - Evaluate for only one stat. Any insignificant effect gives 0 and should not be mentioned."
        )
        septic_example = '"septic_changes": {"Turpitude": 3}'
    else:
        mode_rules = ""

    return f"""You are a game mechanics engine for a stat-based character simulation. Analyze the following interaction and determine stat changes.

{mode_rules}

GENERAL RULES:
- SEPTIC stats: Strength, Empathy, Personality, Turpitude, Intelligence, Constitution (range 0-{STAT_MAX})
- Hidden body part stats: vaginal, oral, anal, breast, feet, face (range 0-{STAT_MAX})
- STRICT SEPARATION: Non-sexual interactions affect ONLY SEPTIC stats. Sexual/adult interactions affect ONLY hidden body part stats. These two systems NEVER overlap in a single evaluation.
- Turpitude increases with moral corruption, sexual exposure, or willingness to cross boundaries. It decreases with wholesome, virtuous, or innocent activity.
- Stats at 0 cannot decrease further. Stats at {STAT_MAX} cannot increase further.
{hint_text}
CURRENT STATS:
SEPTIC: {json.dumps(septic)}
Hidden: {json.dumps(hidden)}

INTERACTION:
User said: "{user_message}"
Character responded: "{narrative[:STAT_EVAL_NARRATIVE_LIMIT]}"

Respond with ONLY a valid JSON object:
{{{septic_example}, "hidden_changes": {{"part_name": 1 or -1}}}}
Only include stats that actually changed. Empty objects for hidden_changes if nothing changed."""


# ═══════════════════════════════════════════════════
#  LLM HELPERS
# ═══════════════════════════════════════════════════

def _get_llm_client() -> tuple[AsyncOpenAI, str]:
    provider, model = curr_model.split("/", 1)
    client = AsyncOpenAI(
        base_url=config["providers"][provider]["base_url"],
        api_key=config["providers"][provider].get("api_key", "sk-no-key-required"),
    )
    return client, model

async def generate_event_summary(char_data: dict, user_text: str, narrative: str, context_label: str = "") -> str:
    """Generate a one-line summary of an interaction for the event log."""
    client, model = _get_llm_client()
    name = char_data["name"]

    label = f" [{context_label}]" if context_label else ""
    prompt = (
        f"Summarize this interaction in ONE sentence from {name}'s perspective.{label}\n"
        f"User said: \"{user_text[:EVENT_SUMMARY_USER_LIMIT]}\"\n"
        f"{name} responded: \"{narrative[:EVENT_SUMMARY_NARRATIVE_LIMIT]}\"\n"
        f"Write a single vivid sentence capturing what happened and how she felt. "
        f"Example: \"Went clubbing and got hit on by a stranger — handled it awkwardly but was secretly flattered.\"\n"
        f"One sentence only. No preamble."
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": prompt}],

            max_tokens=80,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Event summary generation failed: {e}")
        return f"Had an interaction with stepsibling."

import random

# RNG pools for base appearance diversity
HAIR_COLORS = ["blonde", "brunette", "black", "red", "gray", "auburn", "platinum", "jet black", "copper"]
HAIR_TEXTURES = ["straight", "wavy", "curly", "coily"]
EYE_COLORS = ["blue", "brown", "green", "gray", "hazel", "amber", "violet"]
SKIN_TONES = ["fair", "medium", "olive", "tan", "ebony", "pale", "deep brown"]
HEIGHTS = ["petite", "short", "average", "tall", "statuesque"]

#
# UNIFIED TIERS FOR CHARACTER DESCRIPTION
#

MENTAL_TIERS = [
    ("Empathy", "kindness", "distant, aloof, inattentive", [
        (18, "empathic, can perfectly predict a response to any action, almost a mind-reader"),
        (14, "extremely in tune, almost feels others emotions the same time they do"),
        (10, "noticeably empathic, can genuinely anticipate how people feel"),
        (7, "aware, considers how she is perceived and understands emotions"),
        (4, "indifferent, doesn't pay attention to people very much"),
    ]),
    ("Personality", "personality", "bland, unremarkable, doesn't stand out", [
        (18, "superstar, instantly commands the attention of any room"),
        (14, "legendary, one of the most striking minds out there"),
        (10, "dynamic, stands out in a crowd, highly unique"),
        (7, "memorable, those who speak with her are likely to remember her name and face"),
        (4, "interesting, sticks in your mind once met"),
    ]),
    ("Intelligence", "smarts", "tends not to think too much about anything", [
        (18, "supergenius, almost always right about any question, capable of ruling the world"),
        (14, "genius, usually the smartest person in any gathering"),
        (10, "brilliant, usually figures out the answer to something before anyone else does"),
        (7, "intelligent, definitely more able to think of ideas and solve problems"),
        (4, "above average, a bit quicker on the uptake than the typical person"),
    ]),
]

SURFACE_TIERS = [
    ("Strength", "fitness", "soft, untrained, typical sedentary build", [
        (18, "powerfully built, visibly muscular arms and shoulders, imposing physique"),
        (14, "athletic and toned, defined arms, flat stomach, strong legs"),
        (10, "noticeably fit, lean muscle visible, carries herself like an athlete"),
        (7, "starting to show muscle definition, lightly toned"),
        (4, "getting in shape, slightly firmer than average"),
    ]),
    ("Constitution", "complexion", "frail, fragile, sickly", [
        (14, "radiant, glowing skin, picture of health"),
        (10, "healthy color, clear skin, bright eyes"),
        (7, "healthier-looking lately, good color in her cheeks"),
        (4, "normal, healthy enough"),
    ]),
    ("Turpitude", "figure", "thin, wiry, flat-chested", [
        (22, "impossibly voluptuous, huge breasts, wide hips, tiny waist, moves like sex incarnate"),
        (18, "overtly voluptuous, large breasts, exaggerated curves, moves with deliberate sensuality"),
        (14, "full-figured and curvy, noticeable bust, hips that draw attention"),
        (10, "filling out into womanly curves, fuller bust, confident in her body"),
        (7, "developing curves, modest but noticeable figure"),
        (4, "slight curves starting to show, still modest"),
    ]),
    ("Turpitude", "demeanor", "modest, chaste, unassuming", [
        (22, "shameless seductress, touches people constantly, innuendo in every sentence, bedroom eyes at all times"),
        (18, "openly flirtatious, teasing, suggestive body language, loves attention"),
        (14, "playfully provocative, comfortable with her sexuality, knows how to use her looks"),
        (10, "flirty when she wants to be, increasingly aware of her effect on people"),
        (7, "occasionally coy, testing boundaries, discovering she likes attention"),
        (4, "hints of flirtation creeping in, a lingering glance here and there"),
    ]),
    ("Turpitude", "grooming", "bland, mousy, frumpy", [
        (22, "salon-perfect at all times, dramatic makeup, hair always styled to kill"),
        (18, "high-maintenance glam, teased and styled hair, full face of makeup daily"),
        (14, "noticeably done-up, volumized hair, deliberate makeup choices"),
        (10, "puts real effort into hair and makeup, starting to enjoy the ritual"),
        (7, "experimenting with styling, occasional bold lip or eye look"),
        (4, "paying more attention to her appearance, trying new things"),
    ]),
    ("Personality", "bearing", "boring, forgettable, uanppealing", [
        (14, "magnetic presence, impeccable grooming, turns heads when she walks in"),
        (10, "well-groomed, confident posture, naturally draws the eye"),
        (7, "starting to carry herself with more confidence, better grooming"),
        (4, "neater than she used to be, more aware of her appearance"),
    ]),
]

OUTFIT_TIERS = [
    ("Personality", "style", "disheveled, frumpy, run-of-the-mill", [
        (14, "fashion-forward, eye-catching, clearly has great taste"),
        (10, "stylish, put-together, knows what looks good"),
        (7, "developing a personal style, some effort in her look"),
        (4, "basic but clean, starting to care more about how she looks"),
    ]),
    ("Personality", "makeup", "no makeup, flat, dull", [
        (22, "Instagram-influencer level — contouring, highlight, lashes, the full production"),
        (15, "full glam or dramatic — smoky eyes, bold lips, knows exactly what she's doing"),
        (10, "noticeable makeup — eyeliner, lipstick, some contouring"),
        (4, "light makeup — mascara, maybe some lip gloss"),
    ]), 
    ("Turpitude", "edge", "modest, chaste, straight-laced", [
        (22, "absolutely scandalous — barely legal, maximum skin, lingerie as outerwear"),
        (18, "provocative and bold — short skirts, low necklines, leather, sheer fabrics"),
        (14, "sexy and confident — crop tops, tight fits, showing off her figure"),
        (10, "edgy and confident — form-fitting clothes, dark lipstick, hints of skin"),
        (7, "starting to push boundaries — occasional bold choices, darker tones"),
        (4, "modest with a hint of curiosity — mostly conservative but trying things"),
    ]),
    ("Turpitude", "hair", "stringy, dull, bland", [
        (22, "big, teased, voluminous — bombshell hair that demands attention"),
        (18, "styled and volumized — clearly spent time with a curling iron or flat iron"),
        (14, "deliberately styled — bouncy waves, sleek straight, or artful updo"),
        (10, "put-together — some effort, looks intentional"),
        (7, "experimenting with styles — trying new things"),
        (4, "basic styling — brushed and neat"),
    ]),
]

#
# UNIFIED IDENTITY ENGINE
#

def resolve_tier(value: int, tiers: list[tuple[int, str]], default: str = "average/unremarkable") -> str:
    """
    Universal Tier Engine: Maps a numeric value to a descriptive string 
    based on a provided list of (threshold, description) tuples.
    """
    for threshold, description in tiers:
        if value >= threshold:
            return description
    return default


def get_profile_sweep(char_data: dict, tier_source: list) -> str:
    """
    Sweeps through a set of tiers (SURFACE or MENTAL or OUTFIT) and returns a formatted string.
    """
    septic = char_data.get("septic", {})
    profiles = []
    
    for stat_name, key, default, tiers in tier_source:
        val = septic.get(stat_name, 0)
        # Use the unified resolver here
        desc = resolve_tier(val, tiers, default)
        
        profiles.append(f"{key.upper()}: {desc}")
            
    return " | ".join(profiles) if profiles else "Unremarkable."

 
def build_appearance_string(char_data: dict) -> str:
    """
    The Master Assembly: Combines physical, mental, and current look 
    into a single deterministic persona block.
    """ 
    gen = char_data.get("genetics", {})

    # genetics
    hair = gen.get("hair_color", "ash brown")
    eyes = gen.get("eye_color", "hazel")
    height = gen.get("height", "average")

    # 1. Body/Fitness (Deterministic from SURFACE_TIERS)
    physical = get_profile_sweep(char_data, SURFACE_TIERS)
    
    # 2. Personality/Vibe (Deterministic from MENTAL_TIERS)
    mental = get_profile_sweep(char_data, MENTAL_TIERS)
    
    # 3. Temporary Presentation (The current outfit)
    outfit = generate_outfit(char_data)
    
    return (
        f"GENETICS: {hair} hair, {eyes} eyes, height: {height}\n"
        f"PHYSICAL STATE: {physical}\n"
        f"MINDSET: {mental}\n"
        f"CURRENT LOOK: {outfit}"
    )


async def get_llm_json_response(client: AsyncOpenAI, model: str, payload: list, retries: int = 3) -> Optional[dict]:
    for attempt in range(retries):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=payload,
    
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(1))
                    except json.JSONDecodeError:
                        pass
                logging.warning(f"JSON parse failed (attempt {attempt+1}): {raw[:200]}")
                await asyncio.sleep(1)
        except Exception as e:
            logging.error(f"LLM JSON error (attempt {attempt+1}): {e}")
            await asyncio.sleep(1)
    return None


# ═══════════════════════════════════════════════════
#  STREAMING RESPONSE
# ═══════════════════════════════════════════════════

EMBED_MAX_LEN = 4096

async def stream_response(
    channel: discord.abc.Messageable,
    reply_to: discord.Message,
    llm_payload: list,
    client: AsyncOpenAI,
    model: str,
    color: discord.Color = EMBED_COLOR_PRINCESS,
) -> str:
    global last_task_time
    full_response = ""
    max_display = EMBED_MAX_LEN - len(STREAMING_INDICATOR) - 10  # safety margin
    embed = discord.Embed(description=STREAMING_INDICATOR, color=EMBED_COLOR_INCOMPLETE)
    response_msg = await reply_to.reply(embed=embed, silent=True)
    edit_task = None

    try:
        params = config["models"].get(curr_model, {})
        stream = await client.chat.completions.create(
            model=model, messages=llm_payload, stream=True, **params
        )
        async for chunk in stream:
            if delta := (chunk.choices[0].delta.content or ""):
                full_response += delta
            now_ts = datetime.now().timestamp()
            if (edit_task is None or edit_task.done()) and (now_ts - last_task_time >= EDIT_DELAY_SECONDS):
                if edit_task:
                    await edit_task
                display = full_response
                if len(display) > max_display:
                    display = display[:max_display] + "..."
                embed.description = display + STREAMING_INDICATOR
                edit_task = asyncio.create_task(response_msg.edit(embed=embed))
                last_task_time = now_ts

        if edit_task:
            await edit_task

        # Split into multiple embeds if response exceeds Discord's limit
        chunks = _split_response(full_response, EMBED_MAX_LEN - 20)

        # First chunk goes in the original embed
        embed.description = chunks[0]
        embed.color = color
        await response_msg.edit(embed=embed)

        # Continuation chunks get their own embeds
        for i, chunk_text in enumerate(chunks[1:], 1):
            cont_embed = discord.Embed(description=chunk_text, color=color)
            await channel.send(embed=cont_embed)

    except Exception as e:
        logging.exception("Error streaming LLM response")
        embed.description = f"An error occurred: {e}"
        embed.color = EMBED_COLOR_INCOMPLETE
        await response_msg.edit(embed=embed)

    return full_response


def _split_response(text: str, max_chunk: int) -> list[str]:
    """Split a long response into chunks that fit in Discord embeds.
    Tries to split at paragraph boundaries, then sentence boundaries, then hard cuts."""
    if len(text) <= max_chunk:
        return [text]

    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chunk:
            chunks.append(remaining)
            break

        # Try to split at a paragraph boundary (double newline)
        split_at = remaining.rfind("\n\n", 0, max_chunk)
        if split_at > max_chunk // 2:
            chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
            continue

        # Try to split at a single newline
        split_at = remaining.rfind("\n", 0, max_chunk)
        if split_at > max_chunk // 2:
            chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
            continue

        # Try to split at a sentence boundary
        for sep in (". ", "! ", "? ", ".\n"):
            split_at = remaining.rfind(sep, 0, max_chunk)
            if split_at > max_chunk // 2:
                chunks.append(remaining[:split_at + 1].rstrip())
                remaining = remaining[split_at + 1:].lstrip()
                break
        else:
            # Hard split at a space
            split_at = remaining.rfind(" ", 0, max_chunk)
            if split_at > 0:
                chunks.append(remaining[:split_at])
                remaining = remaining[split_at:].lstrip()
            else:
                # Absolute last resort: hard cut
                chunks.append(remaining[:max_chunk])
                remaining = remaining[max_chunk:]

    return chunks


# ═══════════════════════════════════════════════════
#  STAT EVALUATION & APPLICATION
# ═══════════════════════════════════════════════════

async def evaluate_and_apply_stats(
    char_data: dict, user_message: str, narrative: str,
    activity_hints: Optional[dict] = None, eval_mode: str = "normal"
) -> str:
    client, model = _get_llm_client()
    eval_prompt = build_stat_eval_prompt(char_data, user_message, narrative, activity_hints, eval_mode)
    payload = [{"role": "system", "content": eval_prompt}]

    result = await get_llm_json_response(client, model, payload)
    if not result:
        logging.warning(f"Stat eval returned no result for user {char_data['user_id']} (mode={eval_mode})")
        char_data["total_interactions"] = char_data.get("total_interactions", 0) + 1
        return ""

    logging.info(f"Stat eval raw result (mode={eval_mode}): {result}")

    changes_display = []

    # Determine valid delta ranges per mode
    if eval_mode == "adult":
        valid_septic_deltas = ()  # No SEPTIC changes during adult interactions
    elif eval_mode == "event":
        valid_septic_deltas = (-3, 3)
    elif eval_mode == "freeform":
        valid_septic_deltas = (-2, -1, 0, 1, 2)
    else:
        valid_septic_deltas = (-3, -2, -1, 0, 1, 2, 3)

    for stat, delta in result.get("septic_changes", {}).items():
        # Coerce string/float values to int (Grok-3 sometimes returns "+1" or 1.0)
        try:
            delta = int(delta)
        except (ValueError, TypeError):
            logging.warning(f"Stat eval: could not coerce delta for {stat}: {delta!r}")
            continue
        if stat not in char_data["septic"]:
            logging.warning(f"Stat eval: unknown stat '{stat}'")
            continue
        if delta not in valid_septic_deltas:
            logging.warning(f"Stat eval: delta {delta} for {stat} not in valid set {valid_septic_deltas}, clamping")
            # Clamp to nearest valid value instead of dropping
            # Handle empty valid_septic_deltas (e.g., adult mode) by skipping
            if not valid_septic_deltas:
                continue
            positive_deltas = [d for d in valid_septic_deltas if d > 0]
            negative_deltas = [d for d in valid_septic_deltas if d < 0]
            if delta > 0 and positive_deltas:
                delta = max(positive_deltas)
            elif delta < 0 and negative_deltas:
                delta = min(negative_deltas)
            else:
                continue  # 0 means no change, or no valid deltas in that direction
        if delta == 0:
            continue
        display = _apply_stat_delta(char_data, "septic", stat, delta)
        changes_display.append(display)

    # Hidden stats: only allowed during adult or intimate mode
    if eval_mode not in ("adult", "intimate"):
        if result.get("hidden_changes"):
            logging.warning(f"Stat eval: hidden_changes returned in non-adult mode ({eval_mode}), ignoring")
        result["hidden_changes"] = {}

    for part, delta in result.get("hidden_changes", {}).items():
        try:
            delta = int(delta)
        except (ValueError, TypeError):
            logging.warning(f"Stat eval: could not coerce hidden delta for {part}: {delta!r}")
            continue
        if part not in char_data["hidden"]:
            continue
        if delta not in (-1, 1):
            delta = 1 if delta > 0 else -1
        _apply_stat_delta(char_data, "hidden", part, delta)

    char_data["total_interactions"] = char_data.get("total_interactions", 0) + 1

    if changes_display:
        return "` " + " | ".join(changes_display) + " `"
    return ""


async def trigger_ending(channel: discord.abc.Messageable, char_data: dict, ending: dict) -> None:
    """Narrate and finalize an ending."""
    name = char_data["name"]
    client, model = _get_llm_client()
    system_prompt = await build_system_prompt(char_data, longform=True)

    payload = [{"role": "system", "content": system_prompt}]
    recent = char_data.get("story", [])[-MAX_RECENT_MESSAGES:]
    payload.extend(recent)
    payload.append({"role": "system", "content": ending["prompt"]})

    # Announce the ending
    announce_embed = discord.Embed(
        title=f"ENDING UNLOCKED: {ending['title']}",
        description=ending["description"],
        color=EMBED_COLOR_ENDING,
    )
    announce_msg = await channel.send(embed=announce_embed)

    # Narrate the ending
    narrative = await stream_response(channel, announce_msg, payload, client, model, color=EMBED_COLOR_ENDING)

    # Mark character as completed
    char_data["ending"] = ending["id"]
    char_data["ending_title"] = ending["title"]
    char_data["story"].append({"role": "assistant", "content": f"[ENDING: {ending['title']}] {narrative}"})
    save_character(char_data)

    # Final stats display
    septic = char_data["septic"]
    interactions = char_data.get("total_interactions", 0)

    lines = [f"**{stat}**: `[{_stat_bar(val)}]` **{val}**/{STAT_MAX}" for stat, val in septic.items()]

    final_embed = discord.Embed(
        title=f"{name}'s Final Form — {ending['title']}",
        description="\n".join(lines),
        color=EMBED_COLOR_ENDING,
    )
    final_embed.set_footer(text=f"Total interactions: {interactions} | Use /princess reset to start a new character")
    await channel.send(embed=final_embed)


# ═══════════════════════════════════════════════════
#  RANDOM EVENT ROLLER
# ═══════════════════════════════════════════════════

def roll_random_event() -> Optional[dict]:
    """Roll for a random event. Returns event dict or None."""
    if random.random() < RANDOM_EVENT_CHANCE:
        return random.choice(RANDOM_EVENTS)
    return None


# ═══════════════════════════════════════════════════
#  ADULT CONTENT DETECTION
# ═══════════════════════════════════════════════════

ADULT_KEYWORDS = re.compile(
    r"\b(kiss(?:ing|ed)?|moan(?:ing|ed|s)?|thrust(?:ing|ed|s)?|naked|nude|undress(?:ing|ed)?|"
    r"strip(?:ping|ped)?|lick(?:ing|ed)?|suck(?:ing|ed)?|fuck(?:ing|ed)?|cock|pussy|clit|"
    r"nipple|breast|tit|cum(?:ming)?|orgasm|blowjob|handjob|fingering|penetrat|erect|"
    r"aroused|arousal|grind(?:ing)?|straddle|spread.{0,10}legs|wet.{0,10}between|"
    r"tongue.{0,10}inside|mouth.{0,10}around|lips.{0,10}around|between.{0,10}thighs)\b",
    re.IGNORECASE,
)


def is_adult_content(user_text: str, narrative: str) -> bool:
    """Detect if the interaction contains adult/sexual content."""
    combined = f"{user_text} {narrative}"
    return bool(ADULT_KEYWORDS.search(combined))


INTIMATE_KEYWORDS = re.compile(
    r"\b(flirt(?:ing|ed|s)?|blush(?:ing|ed|es)?|brush(?:ing|ed)?.{0,10}(hand|arm|leg|hair|cheek|thigh|shoulder)|"
    r"lean(?:ing|ed)?.{0,10}(close|against|into)|hold(?:ing)?.{0,10}hand|"
    r"touch(?:ing|ed)?.{0,10}(face|cheek|arm|hand|thigh|shoulder|lip|hair|neck|waist|hip)|"
    r"cuddle|cuddl(?:ing|ed)|snuggle|spoon(?:ing)?|nuzzle|caress(?:ing|ed)?|"
    r"hug(?:ging|ged)?|embrac(?:e|ing|ed)|pull(?:ing|ed)?.{0,10}close|"
    r"stare.{0,10}(lips|eyes|body|chest)|glance.{0,10}(body|chest|legs|cleavage)|"
    r"whisper(?:ing|ed)?|breath.{0,10}(neck|ear)|tease|teas(?:ing|ed)|"
    r"seduc|attract|tension|chem(?:istry)|intimate|intimacy)\b",
    re.IGNORECASE,
)


def is_intimate_content(user_text: str, narrative: str) -> bool:
    """Detect light physical contact / flirting that falls short of explicit adult content."""
    combined = f"{user_text} {narrative}"
    return bool(INTIMATE_KEYWORDS.search(combined))


def is_adult_unlocked(char_data: dict) -> bool:
    """Check if character meets adult content thresholds."""
    thresholds = char_data.get("adult_thresholds", DEFAULT_ADULT_THRESHOLDS)
    return (
        char_data["septic"]["Turpitude"] >= thresholds["Turpitude"]
        and char_data["septic"]["Personality"] >= thresholds["Personality"]
    )


# ═══════════════════════════════════════════════════
#  DIRECT STAT APPLICATION (for structured training)
# ═══════════════════════════════════════════════════

def apply_direct_stat_changes(char_data: dict, changes: dict[str, int]) -> str:
    """Apply deterministic stat changes. Returns display string."""
    changes_display = []
    for stat, delta in changes.items():
        if stat not in char_data["septic"] or delta == 0:
            continue
        display = _apply_stat_delta(char_data, "septic", stat, delta)
        changes_display.append(display)

    char_data["total_interactions"] = char_data.get("total_interactions", 0) + 1

    if changes_display:
        return "` " + " | ".join(changes_display) + " `"
    return ""


# ═══════════════════════════════════════════════════
#  CORE INTERACTION HANDLER (shared logic)
# ═══════════════════════════════════════════════════

async def handle_interaction(
    channel: discord.abc.Messageable,
    reply_to: discord.Message,
    char_data: dict,
    user_text: str,
    activity_hints: Optional[dict] = None,
    activity_context: Optional[str] = None,
    eval_mode: str = "normal",
    direct_stat_changes: Optional[dict[str, int]] = None,
    longform: bool = False,
    refresh_look: bool = False,
) -> None:

    if char_data.get("ending"):
        await channel.send(
            f"**{char_data['name']}** has already reached her ending: **{char_data.get('ending_title', 'Unknown')}**. "
            f"Use `/princess reset` to start a new character."
        )
        return

    # Apply direct stat changes BEFORE building prompt (for slash commands to reflect in response)
    display_str = ""
    if direct_stat_changes:
        display_str = apply_direct_stat_changes(char_data, direct_stat_changes)

    client, model = _get_llm_client()
    system_prompt = await build_system_prompt(char_data, longform=longform)

    payload = [{"role": "system", "content": system_prompt}]

    # Only include recent messages for conversational continuity
    recent = char_data.get("story", [])[-MAX_RECENT_MESSAGES:]
    payload.extend(recent)

    # Roll for random event
    event = roll_random_event()
    event_notification = None

    if event:
        event_notification = f"**⚡ {event['name']}**: {event['description']}"
        payload.append({"role": "system", "content": (
            f"A random event has just occurred: {event['prompt']} "
            f"Weave this into your response naturally."
        )})

    # Activity context (brief — identity already carries personality)
    if activity_context:
        payload.append({"role": "system", "content": (
            f"You are doing this activity RIGHT NOW: {activity_context}. "
            f"Narrate it happening with a concrete outcome."
        )})

    # Add time frame framing for slash commands (not freeform replies)
    if activity_context or direct_stat_changes:
        time_frame = "night" if "night" in (activity_context or "").lower() else "day"
        payload.append({"role": "system", "content": f"FRAME AS A COMPLETE {time_frame.upper()} SESSION: Narrate this as activities taking place over the full course of a {time_frame}."})
    
    payload.append({"role": "user", "content": user_text})

    # Stream narrative
    narrative = await stream_response(channel, reply_to, payload, client, model)

    if "INAPPROPRIATE CONTENT DETECTED" in narrative:
        logging.warning(f"Age violation for user {char_data['user_id']}")
        return

    if event_notification:
        await channel.send(event_notification)

    # Update recent story (keep trimmed)
    char_data["story"].append({"role": "user", "content": user_text})
    char_data["story"].append({"role": "assistant", "content": narrative})
    if len(char_data["story"]) > MAX_RECENT_MESSAGES:
        char_data["story"] = char_data["story"][-MAX_RECENT_MESSAGES:]

    # Apply stats for events (events are evaluated after response)
    stat_summary = ""
    if event:
        event_stat_summary = await evaluate_and_apply_stats(
            char_data, user_text, narrative, activity_hints=None, eval_mode="event"
        )
        if event_stat_summary:
            stat_summary = f"⚡ Event: {event_stat_summary}"

    else:
        if direct_stat_changes:
            stat_summary = display_str
        elif not direct_stat_changes:
            adult_detected = is_adult_content(user_text, narrative) and is_adult_unlocked(char_data)
            intimate_detected = not adult_detected and is_intimate_content(user_text, narrative)
            if adult_detected:
                final_eval_mode = "adult"
            elif intimate_detected:
                final_eval_mode = "intimate"
            elif event:
                final_eval_mode = "event"
            else:
                final_eval_mode = eval_mode
            stat_summary = await evaluate_and_apply_stats(char_data, user_text, narrative, None, final_eval_mode)

            if adult_detected and len(user_text.split()) >= ADULT_WORDCOUNT_BONUS_THRESHOLD:
                bonus_parts = [p for p in HIDDEN_STATS if p.lower() in (user_text + " " + narrative).lower()]
                bonus_part = bonus_parts[0] if bonus_parts else min(HIDDEN_STATS, key=lambda p: char_data["hidden"][p])
                old_val = char_data["hidden"][bonus_part]
                char_data["hidden"][bonus_part] = clamp_stat(old_val + ADULT_WORDCOUNT_BONUS_AMOUNT)
                if char_data["hidden"][bonus_part] != old_val:
                    logging.info(f"Adult wordcount bonus: {bonus_part} +2")
                    stat_summary = (stat_summary or "") + f"\n` ✨ Detailed interaction bonus! `" 

    if stat_summary:
        await channel.send(stat_summary)

    # Generate event summary for memory log (runs concurrently-ish, non-blocking feel)
    context_label = activity_context.split("—")[0].strip() if activity_context else ""
    if event:
        context_label = f"{context_label} + {event['name']}".strip(" +")
    summary = await generate_event_summary(char_data, user_text, narrative, context_label)
    char_data.setdefault("event_log", []).append(summary)
    if len(char_data["event_log"]) > MAX_EVENT_LOG:
        char_data["event_log"] = char_data["event_log"][-MAX_EVENT_LOG:]

    # Save again after identity/event log updates
    save_character(char_data)

    # Check for ending
    ending = check_ending_conditions(char_data)
    if ending:
        await trigger_ending(channel, char_data, ending)


# ═══════════════════════════════════════════════════
#  PERMISSION CHECK
# ═══════════════════════════════════════════════════

def is_authorized():
    async def predicate(interaction: discord.Interaction) -> bool:
        permissions = config.get("permissions", {})
        allowed_users = permissions.get("users", {}).get("allowed_ids", [])
        allowed_channels = permissions.get("channels", {}).get("allowed_ids", [])
        if not allowed_users and not allowed_channels:
            return True
        if interaction.user.id in allowed_users:
            return True
        if interaction.guild and interaction.channel_id in allowed_channels:
            return True
        return False

    return app_commands.check(predicate)


# ═══════════════════════════════════════════════════
#  SLASH COMMANDS
# ═══════════════════════════════════════════════════

princess_group = app_commands.Group(name="princess", description="Tamagotchi stepsister simulation.")


@princess_group.command(name="new", description="Create a new stepsister character.")
@is_authorized()
async def princess_new(interaction: discord.Interaction, name: str):
    user_id = interaction.user.id
    existing = load_character(user_id)

    if existing:
        await interaction.response.send_message(
            f"You already have **{existing['name']}**. Use `/princess reset` to start over or `/princess wake` to resume.",
            ephemeral=True,
        )
        return

    char_data = create_character(user_id, name)
    active_sessions[interaction.channel_id] = user_id

    await interaction.response.defer()

    # Generate base appearance (permanent traits), compute surface, generate first outfit
    if not char_data["appearance"]:
        char_data["appearance"] = build_appearance_string(char_data)

    client, model = _get_llm_client()
    system_prompt = await build_system_prompt(char_data)

    intro_prompt = (
        f"This is the very first time you and your new stepsibling are meeting. "
        f"Your parent just married their parent and you've moved in together. "
        f"Your name is {name}. You're 18 years old and nervous about this whole situation. "
        f"Introduce yourself naturally — reference your appearance through actions and mannerisms. "
        f"Be real and specific. End with something that invites conversation."
    )

    payload = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": intro_prompt},
    ]

    anchor = await interaction.followup.send(f"*The door opens. **{name}** stands there with a suitcase...*")
    narrative = await stream_response(interaction.channel, anchor, payload, client, model)

    char_data["story"].append({"role": "assistant", "content": narrative})
    save_character(char_data)


@princess_group.command(name="wake", description="Resume interacting with your stepsister.")
@is_authorized()
async def princess_wake(interaction: discord.Interaction):
    user_id = interaction.user.id
    char_data, error = _load_active_character(user_id)
    if error:
        await interaction.response.send_message(error, ephemeral=True)
        return

    active_sessions[interaction.channel_id] = user_id
    name = char_data["name"]
    interactions = char_data.get("total_interactions", 0)

    await interaction.response.defer()

    # Generate base appearance if missing (first wake after migration)
    if not char_data.get("base_appearance"):
        char_data["base_appearance"] = await generate_base_appearance(char_data)

    # Recompute body from current stats, generate fresh outfit for today
    char_data["surface_appearance"] = compute_surface_appearance(char_data)
    char_data["outfit_appearance"] = await generate_outfit(char_data)

    # Always regenerate identity on wake — cheap call, ensures freshness
    await _regenerate_identity(char_data)

    client, model = _get_llm_client()
    system_prompt = await build_system_prompt(char_data)

    fam_low, fam_mid, fam_high = FAMILIARITY_THRESHOLDS
    familiarity = (
        "You barely know each other — it's still awkward."
        if interactions < fam_low
        else "You're getting used to each other by now."
        if interactions < fam_mid
        else "You know each other well. There's real history between you."
        if interactions < fam_high
        else "You two are deeply bonded after many interactions together."
    )

    wake_prompt = (
        f"Your stepsibling just came to find you. {familiarity} "
        f"Greet them naturally based on your current personality and mood. "
        f"What are you doing when they find you? React in character."
    )

    payload = [{"role": "system", "content": system_prompt}]
    recent = char_data.get("story", [])[-MAX_RECENT_MESSAGES:]
    payload.extend(recent)
    payload.append({"role": "user", "content": wake_prompt})

    anchor = await interaction.followup.send(f"*You go looking for {name}...*")
    narrative = await stream_response(interaction.channel, anchor, payload, client, model)

    char_data["story"].append({"role": "assistant", "content": narrative})
    if len(char_data["story"]) > MAX_RECENT_MESSAGES:
        char_data["story"] = char_data["story"][-MAX_RECENT_MESSAGES:]
    save_character(char_data)


@princess_group.command(name="stats", description="View your stepsister's visible stats.")
@is_authorized()
async def princess_stats(interaction: discord.Interaction):
    char_data, error = _load_active_character(interaction.user.id)
    if not char_data:
        await interaction.response.send_message(error or "No character found.", ephemeral=True)
        return

    await interaction.response.defer()

    # Refresh surface appearance and outfit on stats check
    char_data["appearance"] = build_appearance_string(char_data)
    save_character(char_data)

    outfit = await generate_outfit(char_data)
    bio = await generate_bio(char_data)

    septic = char_data["septic"]
    name = char_data["name"]
    interactions = char_data.get("total_interactions", 0)
    ending = char_data.get("ending_title")

    lines = [f"**{stat}**: `[{_stat_bar(val)}]` **{val}**/{STAT_MAX}" for stat, val in septic.items()]
    full_desc = "\n".join(lines) + f"\n\n{bio}\n"

    embed = discord.Embed(
        title=f"{name}'s Profile",
	description=full_desc,
        color=EMBED_COLOR_ENDING if ending else EMBED_COLOR_PRINCESS,
    )
    footer = f"Interactions: {interactions}"
    if ending:
        footer += f" | Ending: {ending}"
    embed.set_footer(text=footer)
    await interaction.followup.send(embed=embed)


@princess_group.command(name="reset", description="Permanently delete your character.")
@is_authorized()
async def princess_reset(interaction: discord.Interaction):
    char_data = load_character(interaction.user.id)
    if not char_data:
        await interaction.response.send_message("Nothing to reset.", ephemeral=True)
        return

    name = char_data["name"]

    class ConfirmView(ui.View):
        def __init__(self):
            super().__init__(timeout=30)

        @discord.ui.button(label=f"Delete {name} Forever", style=discord.ButtonStyle.danger)
        async def confirm(self, btn_inter: discord.Interaction, button: ui.Button):
            if btn_inter.user.id != interaction.user.id:
                await btn_inter.response.send_message("Not your call.", ephemeral=True)
                return
            path = _char_path(interaction.user.id)
            if path.exists():
                path.unlink()
            for ch_id, uid in list(active_sessions.items()):
                if uid == interaction.user.id:
                    del active_sessions[ch_id]
            for item in self.children:
                item.disabled = True
            await btn_inter.response.edit_message(content=f"**{name}** is gone.", view=self)
            self.stop()

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def cancel(self, btn_inter: discord.Interaction, button: ui.Button):
            for item in self.children:
                item.disabled = True
            await btn_inter.response.edit_message(content="Cancelled.", view=self)
            self.stop()

    await interaction.response.send_message(
        f"**Permanently delete {name}?** All stats and history will be destroyed.",
        view=ConfirmView(),
    )


# ─── Structured Activity Command ───

@princess_group.command(name="train", description="Send your stepsister on a structured activity.")
@is_authorized()
@app_commands.describe(category="Choose an activity category")
@app_commands.choices(category=[
    app_commands.Choice(name=f"{a['emoji']} {a['label']} — {a['description']}", value=key)
    for key, a in ACTIVITIES.items()
])
async def princess_train(interaction: discord.Interaction, category: app_commands.Choice[str]):
    user_id = interaction.user.id
    char_data, error = _load_active_character(user_id)
    if error:
        await interaction.response.send_message(error, ephemeral=True)
        return

    active_sessions[interaction.channel_id] = user_id
    act = ACTIVITIES[category.value]
    name = char_data["name"]

    await interaction.response.defer()

    # Refresh surface appearance and outfit
    char_data["appearance"] = build_appearance_string(char_data)
    save_character(char_data)

    # Convert "+"/"−" hints to deterministic +1/-1 changes
    direct_changes = {stat: (1 if d == "+" else -1) for stat, d in act["stat_hints"].items()}

    user_text = f"Hey {name}, let's do some {act['label'].lower()} today."
    anchor = await interaction.followup.send(
        f"*You suggest {act['label'].lower()} for {name}...* {act['emoji']}"
    )

    await handle_interaction(
        channel=interaction.channel,
        reply_to=anchor,
        char_data=char_data,
        user_text=user_text,
        activity_context=act["prompt_context"],
        direct_stat_changes=direct_changes,
        refresh_look=True,
    )


# ─── Freeform Activity Command ───

@princess_group.command(name="activity", description="Send your stepsister on any activity (freeform).")
@is_authorized()
@app_commands.describe(activity="What you want her to do (e.g. 'explore the haunted house', 'take a cooking class')")
async def princess_activity(interaction: discord.Interaction, activity: str):
    user_id = interaction.user.id
    char_data, error = _load_active_character(user_id)
    if error:
        await interaction.response.send_message(error, ephemeral=True)
        return

    active_sessions[interaction.channel_id] = user_id
    name = char_data["name"]

    await interaction.response.defer()

    # Refresh surface appearance and outfit
    char_data["appearance"] = build_appearance_string(char_data)
    save_character(char_data)

    user_text = f"Hey {name}, I think you should {activity}."
    anchor = await interaction.followup.send(f"*You suggest that {name} should {activity}...*")

    await handle_interaction(
        channel=interaction.channel,
        reply_to=anchor,
        char_data=char_data,
        user_text=user_text,
        eval_mode="freeform",
        refresh_look=True,
    )

discord_bot.tree.add_command(princess_group)


# ═══════════════════════════════════════════════════
#  MODEL SWITCHING (from llmcord)
# ═══════════════════════════════════════════════════

@discord_bot.tree.command(name="model", description="View or switch the current model")
async def model_command(interaction: discord.Interaction, model: str) -> None:
    global curr_model
    permissions = config.get("permissions", {})
    admin_ids = permissions.get("users", {}).get("admin_ids", [])
    user_is_admin = interaction.user.id in admin_ids

    if model == curr_model:
        await interaction.response.send_message(f"Current model: `{curr_model}`", ephemeral=True)
    elif user_is_admin:
        curr_model = model
        await interaction.response.send_message(f"Model switched to: `{model}`")
        logging.info(f"Model switched to: {model}")
    else:
        await interaction.response.send_message("No permission to switch models.", ephemeral=True)


@model_command.autocomplete("model")
async def model_autocomplete(interaction: discord.Interaction, curr_str: str) -> list[app_commands.Choice[str]]:
    global config
    if curr_str == "":
        config = await asyncio.to_thread(get_config)
    choices = []
    if curr_str.lower() in curr_model.lower():
        choices.append(app_commands.Choice(name=f"● {curr_model} (current)", value=curr_model))
    choices += [
        app_commands.Choice(name=f"○ {m}", value=m)
        for m in config["models"]
        if m != curr_model and curr_str.lower() in m.lower()
    ]
    return choices[:25]


# ═══════════════════════════════════════════════════
#  MESSAGE HANDLER — NARRATIVE INTERACTION
# ═══════════════════════════════════════════════════

@discord_bot.event
async def on_message(new_msg: discord.Message):
    if new_msg.author.bot:
        return

    user_id = active_sessions.get(new_msg.channel.id)
    if not user_id or new_msg.author.id != user_id:
        return

    if not new_msg.reference:
        return

    ref_msg = new_msg.reference.resolved
    if ref_msg is None:
        try:
            ref_msg = await new_msg.channel.fetch_message(new_msg.reference.message_id)
        except (discord.NotFound, discord.HTTPException):
            return
    if not hasattr(ref_msg, "author") or ref_msg.author != discord_bot.user:
        return

    char_data = load_character(user_id)
    if not char_data:
        return

    user_text = new_msg.content.strip()
    if not user_text:
        return

    await handle_interaction(
        channel=new_msg.channel,
        reply_to=new_msg,
        char_data=char_data,
        user_text=user_text,
        longform=True,
        eval_mode="normal",
    )


# ═══════════════════════════════════════════════════
#  ERROR HANDLER
# ═══════════════════════════════════════════════════

@discord_bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("No permission.", ephemeral=True)
    else:
        logging.error(f"Command error: {error}")
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send("An error occurred.")


# ═══════════════════════════════════════════════════
#  STARTUP
# ═══════════════════════════════════════════════════

@discord_bot.event
async def on_ready():
    logging.info(f"Princess bot online: {discord_bot.user} (ID: {discord_bot.user.id})")
    if client_id := config.get("client_id"):
        logging.info(f"Invite: https://discord.com/oauth2/authorize?client_id={client_id}&permissions=412317273088&scope=bot")
    await discord_bot.tree.sync()


async def main():
    token = config.get("bot_token")
    if not token:
        logging.critical("No bot_token in config-princess.yaml")
        return
    await discord_bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Princess bot shutting down.")
