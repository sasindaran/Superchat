---
name: keep
description: Keep every decision and key note from this chat for the team knowledge base (Superchat). Use when the user types /keep.
disable-model-invocation: true
---
<!-- superchat -->
Run Superchat **/keep** for this chat.

1. Chat id: use the `superchat chat id:` value from this session's start context. If there is none, call `mcp__superchat__chat_tag` once and reuse that tag for the rest of the chat (tell the user the tag).
2. Call `mcp__superchat__chat_contributions` with that chat id, so you can skip anything already kept.
3. Go through the WHOLE chat and extract every decision and lasting key note that is not already kept. Only what was actually decided, never dropped options, never secrets.
4. Create one concise item per distinct decision or lasting fact. Use a short title and state the fact once in `decision`. Add `condition`, `reason`, or `original_text` only when each adds necessary information grounded in the chat. Leave optional fields empty otherwise. Preserve uncertainty without guessing, and use `kind` (`decision` or `key_note`).
5. Call `mcp__superchat__keep` with the items, the chat id, and `folder` = the `superchat folder:` value from the session start (or the current directory).
6. Report: how many kept, how many skipped as already kept, how many are waiting for review. Do not ask for a company now; that happens in /review.
Works even in strict mode.
