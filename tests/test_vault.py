"""The Obsidian copy: layout, links, read-only banner, and that it only removes its own files."""
import pytest

from superchat import vault
from superchat.config import Settings


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERCHAT_HOME", str(tmp_path / "sc"))


def row(i, title, company="Acme", product=None, **kw):
    return {"id": f"{i:06d}-aaaa", "kind": "decision", "title": title, "decision": f"decision {title}",
            "condition": kw.get("condition"), "reason": kw.get("reason"), "original_text": None,
            "kept_at": kw.get("kept_at", "2026-11-24T10:00:00+00:00"), "source_agent": "claude-code", "author_id": "u1",
            "company": {"id": "c1", "name": company}, "product": {"id": "p1", "name": product} if product else None}


def data(rows, conflicts=()):
    return {"rows": rows, "people": {"u1": "Ravi"}, "conflicts": list(conflicts)}


def test_layout_guidelines_vs_product_and_index():
    files = vault.render(data([row(1, "Always UTC"), row(2, "Retry payments", product="Billing", reason="temporary declines")]))
    assert set(files) == {"Acme/Guidelines/2026-11-24 Always UTC.md", "Acme/Billing/2026-11-24 Retry payments.md", "Acme/Acme.md"}
    f = files["Acme/Billing/2026-11-24 Retry payments.md"]
    assert f.startswith("---\n") and 'company: "Acme"' in f and 'product: "Billing"' in f and 'scope: "product"' in f
    assert 'author: "Ravi"' in f and "Read-only copy of Superchat" in f and "**Why:** temporary declines" in f
    assert 'scope: "company-wide"' in files["Acme/Guidelines/2026-11-24 Always UTC.md"]
    idx = files["Acme/Acme.md"]
    assert "## Guidelines (all products)" in idx and "## Billing" in idx
    assert "[[Acme/Billing/2026-11-24 Retry payments|Retry payments]]" in idx


def test_conflicts_link_both_ways():
    files = vault.render(data([row(1, "Never retry"), row(2, "Retry thrice", product="Billing")],
                              [{"decision_id": "000002-aaaa", "other_id": "000001-aaaa", "note": "contradicts"}]))
    a, b = files["Acme/Guidelines/2026-11-24 Never retry.md"], files["Acme/Billing/2026-11-24 Retry thrice.md"]
    assert "## Conflicts" in a and "Retry thrice" in a and "(contradicts)" in a
    assert "Never retry" in b


def test_unsafe_names_and_same_day_duplicates_cannot_collide_or_escape():
    files = vault.render(data([row(1, 'a/b\\c:d*e?"<>|f', company="../Evil Co"), row(2, "Same", ), row(3, "Same")]))
    assert all(".." not in p.split("/")[0] and not p.startswith("/") for p in files)
    same = [p for p in files if "Same" in p]
    assert len(same) == 2 and len(set(same)) == 2


def test_write_is_incremental_and_only_removes_its_own_files(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "my own note.md").write_text("mine")
    (root / "Acme").mkdir()
    (root / "Acme" / "hand-written.md").write_text("mine too")

    first = vault.write(root, vault.render(data([row(1, "One"), row(2, "Two")])))
    assert first["written"] == 3 and first["removed"] == 0
    again = vault.write(root, vault.render(data([row(1, "One"), row(2, "Two")])))
    assert again["written"] == 0

    gone = vault.write(root, vault.render(data([row(1, "One")])))        # "Two" was hidden in Supabase
    assert gone["removed"] == 1 and not (root / "Acme/Guidelines/2026-11-24 Two.md").exists()
    assert (root / "my own note.md").read_text() == "mine" and (root / "Acme/hand-written.md").read_text() == "mine too"

    empty = vault.write(root, {})
    assert empty["removed"] == 2 and (root / "my own note.md").exists()
    assert (root / "Acme" / "hand-written.md").exists()


def test_edits_made_in_obsidian_are_overwritten_on_next_sync(tmp_path):
    root = tmp_path / "v"
    files = vault.render(data([row(1, "One")]))
    vault.write(root, files)
    path = root / "Acme/Guidelines/2026-11-24 One.md"
    path.write_text("someone edited this")
    assert vault.write(root, files)["written"] == 1 and "Read-only copy" in path.read_text(encoding="utf-8")


def test_vault_location_defaults_and_overrides(tmp_path):
    assert vault.vault_dir(Settings()).name == "Superchat Vault"
    assert vault.vault_dir(Settings(vault_dir=str(tmp_path / "x"))) == tmp_path / "x"


def test_sync_through_the_api_with_a_fake_database(tmp_path):
    class FakeApi:
        def select(self, table, **q):
            return {"decisions": [row(1, "One")], "members": [{"user_id": "u1", "email": "r@x.test", "display_name": None}],
                    "decision_conflicts": []}[table]
    out = vault.sync(FakeApi(), Settings(vault_dir=str(tmp_path / "v")))
    assert out["files"] == 2 and (tmp_path / "v/Acme/Acme.md").exists()
    assert 'author: "r@x.test"' in (tmp_path / "v/Acme/Guidelines/2026-11-24 One.md").read_text(encoding="utf-8")
