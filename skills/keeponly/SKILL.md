---
name: keeponly
description: Keep only one specific decision or note you describe (Superchat). Use when the user types /keeponly followed by what to keep.
disable-model-invocation: true
---
<!-- superchat -->
Run Superchat **/keeponly**. Keep ONLY this, nothing else from the chat: $ARGUMENTS

If nothing was given, ask what to keep. Otherwise write it in clean English (`title`, `decision`, `condition`, `reason`, `original_text` = their words, `kind`), using the chat context to fill in condition and reason, and call `mcp__plugin_superchat_superchat__keep` with that single item, the chat id (the `superchat chat id:` value from session start, else `mcp__plugin_superchat_superchat__chat_tag`) and `folder` (the `superchat folder:` value). Report the result. Works even in strict mode.
