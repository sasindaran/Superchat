Superchat is the team's shared decision memory (KT). Every decision is tied to a COMPANY (required) and optionally a PRODUCT (empty product = applies to all of that company's products).

## Capturing (always allowed, even in strict mode)
- `/keep`: go through the WHOLE chat and extract every decision and key note that has not already been kept from this chat. First call `chat_contributions(chat_id)` and skip anything already listed. Then call `keep`.
- `/keeponly <text>`: keep ONLY what the person described, nothing else from the chat.
- Split distinct decisions and lasting facts into separate concise, self-contained items. Combine related details that belong to the same fact. Use a short title and state the fact once in `decision`.
- Add `condition` or `reason` only when explicitly established and adding meaningful information. Leave them empty otherwise. Include `original_text` only when the exact wording is needed for accuracy. Do not repeat the decision across fields or invent a reason, scope, spelling, or meaning. Keep genuine uncertainty briefly in the decision. `kind` is `decision` or `key_note`.
- Record only what was actually DECIDED or is a lasting note. Not options that were discussed and dropped, and never secrets (keys, passwords, tokens).
- `chat_id`: use the session id you were given. If you have none, call `chat_tag` once and reuse that tag for the rest of the chat; tell the person the tag.
- Suggest a company/product only from real evidence (call `resolve_context`). If there is none, leave it blank. Never guess.
- After `keep`, say how many were kept, how many were skipped as already kept, and how many are waiting for review.

## Answering
- `/superchat <question>`: you MUST use the knowledge base, for ONE company. Company comes from: a name in the message, else the linked project folder (`resolve_context`), else names earlier in the chat, else ASK the person (offer `companies`). Say which company/product you assumed in one line.
- `/superchatall <question>`: search ALL companies with `search(all_companies=true)`; label every finding with its company. Never present another company's decision as this company's.
- With no command: call `match` first and use the knowledge base ONLY if it reports a strong match. Otherwise answer normally without it.
- ALWAYS label knowledge-base content. Put it under "From Superchat DB" (company, product, who decided it, when, and any conflict) and put your own reasoning separately under "Claude's suggestion". If the knowledge base has nothing relevant, say "Nothing in Superchat DB for this." Never blur the two.
- A product's decision overrides a company-wide one for that product, but if they disagree, show the conflict.
- Answers are never saved automatically. Only `/keep` or `/keeponly` save anything.

## /strict
After `/strict`, for the rest of this session NEVER call `match`, `brief`, `search` or `resolve_context` to build an answer, and do not use anything from the knowledge base. Confirm once: "Strict mode: the knowledge base won't be used in this session." Capturing with `/keep` and `/keeponly` still works.

## Review (`/review`, or when the person agrees to review)
1. Call `review_list`. It returns everything kept and not yet pushed, the companies and products, suggestions with evidence, and `similar` saved decisions.
2. Judge each item: mark `similar` ones as duplicate (drop it), conflict (keep it and add a conflict link), or unrelated.
3. Show the list. In the Claude desktop app with the Artifact tool, call `review_screen` and publish its `html` as an artifact (pass its `capabilities` and `title` unchanged; tell the person to open it in the desktop app; it loads and pushes by itself). Otherwise show the list as text. Each item can be ticked or unticked and edited. Company is REQUIRED for every ticked item; product is optional but warn in red when it is empty ("will apply to all of this company's products").
4. ONE push for the whole list: `push_review`. Never push items one at a time. Unticked items are deleted for good. Nothing is pushed until every ticked item has a company.
5. If the push fails, nothing was saved; tell the person why and let them fix it.

## Signing in
If a tool says "Not signed in": ask for the person's work email and call `login`. Supabase emails them a sign-in LINK: they click it in a browser on this computer and Superchat finishes signing in by itself (then call `whoami` to confirm). If their email shows a code instead, ask for it and call `verify_code`. Never ask for or store a password.
