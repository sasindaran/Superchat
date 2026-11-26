---
name: superchat
description: Answer a question using the team knowledge base (Superchat), for one company. Use when the user types /superchat with a question.
disable-model-invocation: true
---
<!-- superchat -->
Run Superchat **/superchat**. Question: $ARGUMENTS

You MUST use the knowledge base for ONE company.
1. Find the company: a name in the message, else `mcp__plugin_superchat_superchat__resolve_context` (text = the chat so far, folder = the `superchat folder:` value), else ask the user and offer `mcp__plugin_superchat_superchat__companies`. If strict mode is on, say so and do not use the knowledge base.
2. Say in one line which company/product you assumed.
3. Call `mcp__plugin_superchat_superchat__brief` and `mcp__plugin_superchat_superchat__search` for that company.
4. Answer in two clearly separate parts: **From Superchat DB** (each point with company, product, who decided it and when; show any conflict) and **Claude's suggestion** (your own reasoning). If nothing relevant is stored, say "Nothing in Superchat DB for this."
Do not save anything; only /keep saves.
