---
name: review
description: Review everything kept so far and push it to the team knowledge base in one go (Superchat). Use when the user types /review.
disable-model-invocation: true
---
<!-- superchat -->
Run Superchat **/review**.
1. Call `mcp__plugin_superchat_superchat__review_list`.
2. For each item look at `similar`: duplicate (drop it), conflict (keep it and add `conflicts: [{other_id, note}]`), or unrelated.
3. Call `mcp__plugin_superchat_superchat__review_screen` to open the review app inline. If the app reports read-only or cannot open, explain this and review the items in text. Company is required and product is optional. Prefill suggestions only when their strength is strong. Do not claim the user can press Push when the app reports read-only.
4. Nothing is pushed until every ticked item has a company. Then ONE call to `mcp__plugin_superchat_superchat__push_review` with `cutoff` (unchanged from the list), the ticked `items`, and `remove_keep_ids` for the unticked ones (they are deleted for good).
5. If it fails, nothing was saved: explain why and let the user fix it.
If the tools say "Not signed in", ask for their work email, call `login`, ask for the emailed 6-digit code, call `verify_code`.
