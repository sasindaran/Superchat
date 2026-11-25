---
name: superchatall
description: Answer a question using the team knowledge base across ALL companies (Superchat). Use when the user types /superchatall.
disable-model-invocation: true
---
<!-- superchat -->
Run Superchat **/superchatall**. Question: $ARGUMENTS

Search every company with `mcp__superchat__search` (`all_companies` = true). Label every finding with its company and product; never present another company's decision as this company's. Answer in two parts: **From Superchat DB** and **Claude's suggestion**. If nothing is relevant, say "Nothing in Superchat DB for this." If strict mode is on, say so and do not use the knowledge base. Do not save anything.
