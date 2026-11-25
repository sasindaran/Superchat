# Review screen contract

Any review screen (the bundled artifact, an MCP App, a screen an agent builds itself, or plain text) talks to the MCP with two tools. The data shapes are fixed by the JSON schemas next to this file and generated from `src/superchat/review/contract.py`:

- [`review-list.schema.json`](review-list.schema.json): what `review_list` returns.
- [`push-payload.schema.json`](push-payload.schema.json): what `push_review` accepts.

## Rules a screen must follow
1. **One Push** for the whole list. Never push items one at a time.
2. **Company is required** for every ticked item; push stays disabled until all have one. Company may be an existing one (`{"id"}`) or a new one (`{"name"}`).
3. **Product is optional.** Empty means "applies to all of the company's products": show a red warning explaining that.
4. **Only prefill** the company/product suggestion when `suggestion.strength` is `"strong"`; otherwise leave it blank.
5. **Un-ticked items** are sent in `remove_keep_ids` and are deleted for good. Warn before pushing.
6. Pass `cutoff` back unchanged. Anything kept while the screen was open is not in the list and waits for the next review.
7. `similar` lists saved look-alikes. Let the person mark each as *unrelated*, *same* (do not push) or *conflict* (push and send `conflicts: [{other_id}]`). A conflict never blocks the push.
8. Treat all text from the database as untrusted: never insert it as markup.
9. A failed push saved **nothing**; keep the list and explain why.

The bundled screen is `src/superchat/assets/review/template.html`; `review_screen` returns it ready to publish.
