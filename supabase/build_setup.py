"""Regenerates supabase/setup.sql (all migrations in one paste-able file). Run after editing a migration."""
from pathlib import Path
root = Path(__file__).parent
parts = ["-- ================================================================\n"
         "-- Superchat: complete database setup for Supabase.\n"
         "-- Paste this whole file into Supabase > SQL Editor > New query > Run.\n"
         "-- Safe to run more than once.\n"
         "-- GENERATED from supabase/migrations/*.sql by build_setup.py. Do not edit by hand.\n"
         "-- ================================================================\n"]
for m in sorted((root / "migrations").glob("*.sql")):
    parts.append(f"\n-- ---------- {m.name} ----------\n" + m.read_text(encoding="utf-8"))
text = "".join(parts)
(root / "setup.sql").write_text(text, encoding="utf-8")
(root.parent / "src" / "superchat" / "assets" / "supabase" / "setup.sql").write_text(text, encoding="utf-8")
print("wrote setup.sql", sum(len(p) for p in parts), "chars")
