# Before making this repository public

1. Remove the team's Supabase address and key from `src/superchat/defaults.json` (leave `supabase_url` and `supabase_key` empty). `superchat setup` then asks for them.
2. **Rotate the publishable key** in Supabase (Project Settings > API Keys). Git history keeps old files, so the old key stays visible in earlier commits. It is not a secret and the database rules protect the data, but rotating it makes the leaked one useless.
3. Search the history for anything else: `git log -p | grep -iE "sb_secret|service_role|password"`. Rewrite history only if something real turns up.
4. Add a LICENSE.
