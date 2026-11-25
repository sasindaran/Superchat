---
name: review
description: Review everything kept so far and push it to the team knowledge base in one go (Superchat). Use when the user types /review.
disable-model-invocation: true
---
<!-- superchat -->
Run Superchat **/review**.
1. Call `mcp__superchat__review_screen` to open the interactive MCP App. If it opens, let the user review and push there. If the client cannot display it, explain that and call `mcp__superchat__review_list` for a text review.
2. For each item look at `similar`: duplicate (drop it), conflict (keep it and add `conflicts: [{other_id, note}]`), or unrelated.
3. Show every item with a checkbox, editable text, company (REQUIRED; dropdown from `companies`, or a new name) and product (optional; if empty show a RED warning: "will apply to all of this company's products"). Pre-fill the suggestion only when `suggestion.strength` is `strong`; otherwise leave company blank and ask.
4. Nothing is pushed until every ticked item has a company. Then ONE call to `mcp__superchat__push_review` with `cutoff` (unchanged from the list), the ticked `items`, and `remove_keep_ids` for the unticked ones (they are deleted for good).
5. If it fails, nothing was saved: explain why and let the user fix it.
If the tools say "Not signed in", ask for their work email, call `login`, ask for the emailed 6-digit code, call `verify_code`.
