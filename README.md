# princess-maker-2-ai
*Discord* chatbot with a tamagotchi style girlfriend stat system, narrated by an LLM. *Princess Maker 2* was pretty damn creepy, so this is about a stepsister moving in with her older stepbrother. If you dislike this, take it up with the rest of the mature streaming video industry. All characters portrayed are 18, those accessing this repository need legal age of 18+ or 21+ (depending on jurisdiction)

### Preamble

- Heavily inspired by llmcord. <https://github.com/jakobdylanc/llmcord>
- Partially vibe-coded with *Claude Code* (caco-bot ver.) <https://code.claude.com/docs/en/overview>
- Hand checked for bugs, logic errors and hallucinations. (I had a little *Python* in community college, and I've spent hours staring at llmcord)
- Consult llmcord docs for configuration.

### Usage

- `/princess new` starts a new stepsister with an LLM generated introduction.
- `/princess stats` shows the stepsisters' stats, and narrates a brief description.
- `/princess train` selects from a series of training events to raise one stat by +1 point.
- `/princess activity` and type a two word activity of your choice raises two LLM-chosen stats by +1.
- Replying to the bot in the manner one would any *Discord* participant is a "freeform" activity.
- "Freeform" activities are judged by the LLM and change the most relevant stat from -3 to +3.
-`/princess reset` casts your stepsister into the fires of oblivion.

### Notes

- Per-user memory system is included.
- Bot has a identifying characteristics, a brief history of itself and an event log.
- Data is in a `json` sorted by *Discord* ID.
- Multiple users are supported, but only one stepsister at a time.
- "Secret" endings are unlocked at 50 "turns", or when certain stat gates are met.
- Examine the code if you want spoilers.

