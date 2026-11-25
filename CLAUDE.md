To set this project up on this computer, follow [AGENTS.md](AGENTS.md).

When working on the code: tests are `pytest` (they need the Postgres container described in README.md and, for the review screen, Node). Regenerate `supabase/setup.sql` with `python supabase/build_setup.py` and the review schemas with `python review/build_schemas.py` after editing migrations or the contract. Do not add AI attribution to commits or files.
