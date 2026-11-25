"""Every access rule, as author / other member / admin / outsider / anonymous."""
import json
import uuid

import psycopg
import pytest

from conftest import item, push


def draft(conn, keep_id=None, title="Draft decision"):
    keep_id = keep_id or uuid.uuid4()
    conn.execute(
        "insert into public.decisions (keep_id, title, decision, status) values (%s, %s, 'do the thing', 'unsaved')",
        (keep_id, title),
    )
    return keep_id


def count(conn, sql="select count(*) from public.decisions", args=()):
    return conn.execute(sql, args).fetchone()[0]


def saved_id(su):
    return su.execute("select id from public.decisions where status='saved' limit 1").fetchone()[0]


# ---- anonymous and outsiders ---------------------------------------------------------------------

@pytest.mark.parametrize("table", [
    "members", "admin_emails", "companies", "products", "folder_links",
    "decisions", "decision_conflicts", "decision_history", "push_batches"])
def test_anonymous_cannot_read_anything(anon, table):
    with anon() as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(f"select * from public.{table}")


def test_anonymous_can_only_ask_the_schema_version(anon):
    with anon() as c:
        assert c.execute("select public.superchat_version()").fetchone()[0] == "1"
    with anon() as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            push(c, [item()])


def test_signed_in_outsider_sees_nothing(su, alice, make_person):
    with alice.session() as c:
        push(c, [item()])
    eve = make_person("eve")
    su.execute("delete from public.members where user_id = %s", (eve.id,))   # signed in, but not a member
    with eve.session() as c:
        assert count(c) == 0
        assert count(c, "select count(*) from public.companies") == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            push(c, [item()])


def test_new_auth_user_automatically_becomes_member(su, make_person):
    p = make_person("newbie")
    assert su.execute("select count(*) from public.members where user_id=%s", (p.id,)).fetchone()[0] == 1


# ---- drafts are private to the author -----------------------------------------------------------

def test_drafts_visible_only_to_author_not_even_admin(alice, bob, root):
    with alice.session() as c:
        draft(c)
    with alice.session() as c:
        assert count(c) == 1
    for other in (bob, root):
        with other.session() as c:
            assert count(c) == 0


def test_author_can_delete_own_draft_others_cannot(alice, bob):
    with alice.session() as c:
        k = draft(c)
    with bob.session() as c:
        assert c.execute("delete from public.decisions where keep_id=%s", (k,)).rowcount == 0
    with alice.session() as c:
        assert c.execute("delete from public.decisions where keep_id=%s", (k,)).rowcount == 1


def test_cannot_insert_saved_row_directly(alice):
    with alice.session() as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("insert into public.companies (name, name_key, created_by) values ('X','x',%s)", (alice.id,))
            cid = c.execute("select id from public.companies where name_key='x'").fetchone()[0]
            c.execute("insert into public.decisions (keep_id,title,decision,status,company_id) "
                      "values (gen_random_uuid(),'t','d','saved',%s)", (cid,))


def test_cannot_insert_draft_as_someone_else(alice, bob):
    with alice.session() as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("insert into public.decisions (keep_id,title,decision,status,author_id) "
                      "values (gen_random_uuid(),'t','d','unsaved',%s)", (bob.id,))


def test_saved_decision_needs_a_company(su, alice):
    with alice.session() as c:
        k = draft(c)
    with pytest.raises(psycopg.errors.CheckViolation):
        su.execute("update public.decisions set status='saved' where keep_id=%s", (k,))


# ---- saved decisions: read / edit / hide -------------------------------------------------------

def test_every_member_reads_saved_decisions(alice, bob, root):
    with alice.session() as c:
        push(c, [item()])
    for p in (alice, bob, root):
        with p.session() as c:
            assert count(c) == 1


def test_only_author_or_admin_can_edit_saved(su, alice, bob, root):
    with alice.session() as c:
        push(c, [item()])
    with bob.session() as c:
        assert c.execute("update public.decisions set title='hijack'").rowcount == 0
    with alice.session() as c:
        assert c.execute("update public.decisions set title='mine'").rowcount == 1
    with root.session() as c:
        assert c.execute("update public.decisions set title='admin edit'").rowcount == 1
    assert su.execute("select title from public.decisions").fetchone()[0] == "admin edit"


@pytest.mark.parametrize("column,value", [
    ("status", "'unsaved'"), ("author_id", "gen_random_uuid()"), ("hidden_at", "now()"),
    ("keep_id", "gen_random_uuid()"), ("pushed_at", "now()"), ("kept_at", "now()")])
def test_protected_columns_cannot_be_changed_even_by_author(alice, column, value):
    with alice.session() as c:
        push(c, [item()])
    with alice.session() as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(f"update public.decisions set {column} = {value}")


def test_saved_decisions_are_never_hard_deleted(alice, root):
    with alice.session() as c:
        push(c, [item()])
    for p in (alice, root):
        with p.session() as c:
            assert c.execute("delete from public.decisions").rowcount == 0


def test_hide_rules(su, alice, bob, root):
    with alice.session() as c:
        push(c, [item()])
    did = saved_id(su)
    with bob.session() as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("select public.hide_decision(%s)", (did,))
    with alice.session() as c:
        c.execute("select public.hide_decision(%s)", (did,))          # author may hide own
    with bob.session() as c:
        assert count(c) == 0                                           # gone for other members
    with alice.session() as c:
        assert count(c) == 1                                           # author still sees it
    with root.session() as c:
        assert count(c) == 1                                           # admin sees it


def test_restore_is_admin_only(su, alice, root):
    with alice.session() as c:
        push(c, [item()])
    did = saved_id(su)
    with alice.session() as c:
        c.execute("select public.hide_decision(%s)", (did,))
    with alice.session() as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("select public.restore_decision(%s)", (did,))
    with root.session() as c:
        c.execute("select public.restore_decision(%s)", (did,))
    assert su.execute("select hidden_at from public.decisions").fetchone()[0] is None


def test_admin_can_hide_anyones_decision(su, alice, root):
    with alice.session() as c:
        push(c, [item()])
    with root.session() as c:
        c.execute("select public.hide_decision(%s)", (saved_id(su),))
    assert su.execute("select hidden_by from public.decisions").fetchone()[0] == root.id


def test_a_draft_cannot_be_hidden(alice):
    with alice.session() as c:
        k = draft(c)
        did = c.execute("select id from public.decisions where keep_id=%s", (k,)).fetchone()[0]
        with pytest.raises(psycopg.errors.RaiseException):
            c.execute("select public.hide_decision(%s)", (did,))


# ---- admin list ---------------------------------------------------------------------------------

def test_admin_list_is_invisible_to_app_users(alice, root):
    for p in (alice, root):
        with p.session() as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("select * from public.admin_emails")


def test_is_admin_follows_email_case_insensitively(su, alice, make_person):
    su.execute("insert into public.admin_emails (email) values ('alice@acme.test')")
    with alice.session() as c:
        assert c.execute("select public.is_admin()").fetchone()[0] is True
    # JWT email in different case still counts
    with alice.session() as c:
        c.execute("select set_config('request.jwt.claims', %s, true)",
                  (json.dumps({"sub": str(alice.id), "email": "ALICE@Acme.Test"}),))
        assert c.execute("select public.is_admin()").fetchone()[0] is True
    bob = make_person("bob2")
    with bob.session() as c:
        assert c.execute("select public.is_admin()").fetchone()[0] is False


def test_admin_emails_must_be_lowercase(su):
    with pytest.raises(psycopg.errors.CheckViolation):
        su.execute("insert into public.admin_emails (email) values ('Boss@Acme.test')")


# ---- companies, products, folder links ----------------------------------------------------------

def test_only_admin_edits_or_hides_companies_and_products(su, alice, bob, root):
    with alice.session() as c:
        push(c, [item(company="Acme", product="Billing")])
    with bob.session() as c:
        assert c.execute("update public.companies set name='Nope'").rowcount == 0
        assert c.execute("update public.products set name='Nope'").rowcount == 0
        assert c.execute("delete from public.companies").rowcount == 0
    with root.session() as c:
        assert c.execute("update public.companies set name='Acme Inc'").rowcount == 1
        assert c.execute("update public.products set hidden_at = now()").rowcount == 1


def test_company_cannot_be_created_in_someone_elses_name(alice, bob):
    with alice.session() as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("insert into public.companies (name,name_key,created_by) values ('X','x',%s)", (bob.id,))


def test_folder_links_creator_or_admin_only(su, alice, bob, root):
    with alice.session() as c:
        push(c, [item()])
        cid = c.execute("select id from public.companies").fetchone()[0]
        c.execute("insert into public.folder_links (folder_key, company_id, created_by) values ('f1', %s, %s)", (cid, alice.id))
    for p in (alice, bob, root):
        with p.session() as c:
            assert count(c, "select count(*) from public.folder_links") == 1
    with bob.session() as c:
        assert c.execute("update public.folder_links set folder_key='x'").rowcount == 0
        assert c.execute("delete from public.folder_links").rowcount == 0
    with root.session() as c:
        assert c.execute("update public.folder_links set product_id=null").rowcount == 1
    with alice.session() as c:
        assert c.execute("delete from public.folder_links").rowcount == 1


# ---- history and batches ---------------------------------------------------------------------

def test_history_is_logged_and_admin_only(su, alice, bob, root):
    with alice.session() as c:
        push(c, [item()])
    with alice.session() as c:
        c.execute("update public.decisions set title='v2'")
    did = saved_id(su)
    with alice.session() as c:
        c.execute("select public.hide_decision(%s)", (did,))
    with root.session() as c:
        c.execute("select public.restore_decision(%s)", (did,))
    actions = [r[0] for r in su.execute("select action from public.decision_history order by id").fetchall()]
    assert actions == ["created", "edited", "hidden", "restored"]
    with root.session() as c:
        assert count(c, "select count(*) from public.decision_history") == 4
    for p in (alice, bob):
        with p.session() as c:
            assert count(c, "select count(*) from public.decision_history") == 0


def test_draft_activity_is_not_logged(su, alice):
    with alice.session() as c:
        k = draft(c)
    with alice.session() as c:
        c.execute("update public.decisions set title='edited draft'")
        c.execute("delete from public.decisions")
    assert su.execute("select count(*) from public.decision_history").fetchone()[0] == 0


def test_push_batches_are_private(alice, bob):
    with alice.session() as c:
        push(c, [item()], device="laptop")
    with alice.session() as c:
        assert count(c, "select count(*) from public.push_batches") == 1
    with bob.session() as c:
        assert count(c, "select count(*) from public.push_batches") == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("insert into public.push_batches (user_id, device_id, cutoff_at) values (%s,'x',now())", (alice.id,))


# ---- the migrations themselves -------------------------------------------------------------

def test_migrations_and_setup_sql_can_be_re_applied(dsn):
    """Running the whole thing again on a live project must change nothing and not fail."""
    from conftest import MIGRATIONS, ROOT
    with psycopg.connect(dsn, autocommit=True) as c:
        for m in MIGRATIONS:
            c.execute(m.read_text(encoding="utf-8"))
        c.execute((ROOT / "supabase" / "setup.sql").read_text(encoding="utf-8"))
