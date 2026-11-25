"""push_review (all-or-nothing, retry-safe), search, briefs, chat contributions."""
import json
import uuid

import psycopg
import pytest

from conftest import item, push, vec


def count(conn, sql, args=()):
    return conn.execute(sql, args).fetchone()[0]


# ---- push_review ----------------------------------------------------------------------------

def test_push_saves_and_returns_ids(alice):
    with alice.session() as c:
        r = push(c, [item(), item(title="Second")])
        assert r["saved"] == 2 and r["skipped"] == 0 and len(r["items"]) == 2
        assert count(c, "select count(*) from public.decisions where status='saved'") == 2


def test_push_is_all_or_nothing(su, alice):
    good = item(company="Brand New Co")
    bad = item(title="No company")
    bad["company"] = None
    with pytest.raises(psycopg.errors.RaiseException, match="company is required"):
        with alice.session() as c:
            push(c, [good, bad])
    assert su.execute("select count(*) from public.decisions").fetchone()[0] == 0
    assert su.execute("select count(*) from public.companies").fetchone()[0] == 0   # new company rolled back too
    assert su.execute("select count(*) from public.push_batches").fetchone()[0] == 0


def test_push_is_safe_to_retry(su, alice):
    payload = [item(), item(title="Other")]
    with alice.session() as c:
        first = push(c, payload)
    with alice.session() as c:
        again = push(c, payload)
    assert first["saved"] == 2 and again["saved"] == 0 and again["skipped"] == 2
    assert su.execute("select count(*) from public.decisions").fetchone()[0] == 2


def test_draft_is_promoted_in_place_and_unticked_drafts_are_removed(su, alice, bob):
    keep, drop, bobs = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with alice.session() as c:
        c.execute("insert into public.decisions (keep_id,title,decision,status) values (%s,'kept','x','unsaved'),(%s,'dropped','y','unsaved')", (keep, drop))
    with bob.session() as c:
        c.execute("insert into public.decisions (keep_id,title,decision,status) values (%s,'bobs','z','unsaved')", (bobs,))
    draft_id = su.execute("select id from public.decisions where keep_id=%s", (keep,)).fetchone()[0]

    with alice.session() as c:
        r = push(c, [item(keep_id=str(keep), title="kept (edited)")], remove=[drop, bobs])
    assert r["saved"] == 1 and r["removed"] == 1                      # bob's draft is NOT removable by alice
    row = su.execute("select id, status, title from public.decisions where keep_id=%s", (keep,)).fetchone()
    assert row == (draft_id, "saved", "kept (edited)")                # same row, promoted
    assert su.execute("select count(*) from public.decisions where keep_id=%s", (drop,)).fetchone()[0] == 0
    assert su.execute("select count(*) from public.decisions where keep_id=%s", (bobs,)).fetchone()[0] == 1


def test_cannot_push_someone_elses_draft(su, alice, bob):
    k = uuid.uuid4()
    with alice.session() as c:
        c.execute("insert into public.decisions (keep_id,title,decision,status) values (%s,'a','b','unsaved')", (k,))
    with pytest.raises(psycopg.errors.RaiseException, match="belongs to someone else"):
        with bob.session() as c:
            push(c, [item(keep_id=str(k))])


def test_company_and_product_are_matched_by_name_not_duplicated(su, alice, bob):
    with alice.session() as c:
        push(c, [item(company="Acme Corp", product="Billing")])
    with bob.session() as c:
        push(c, [item(title="b", company="  acme   CORP ", product="billing"),
                 item(title="c", company="Acme Corp", product="Checkout")])
    assert su.execute("select count(*) from public.companies").fetchone()[0] == 1
    assert su.execute("select count(*) from public.products").fetchone()[0] == 2


def test_aliases_resolve_to_existing_company(su, alice):
    with alice.session() as c:
        push(c, [item(company="Acme Corporation")])
    su.execute("update public.companies set aliases = array['ACME', 'acme corp']")
    with alice.session() as c:
        push(c, [item(title="via alias", company="Acme Corp")])
    assert su.execute("select count(*) from public.companies").fetchone()[0] == 1


def test_empty_product_means_company_wide(su, alice):
    with alice.session() as c:
        push(c, [item(product=None), item(title="blank name", product="   ")])
    assert su.execute("select count(*) from public.decisions where product_id is null").fetchone()[0] == 2


def test_product_must_belong_to_the_company(su, alice):
    with alice.session() as c:
        push(c, [item(company="A", product="P")])
        c.execute("select 1")
    pid = su.execute("select id from public.products").fetchone()[0]
    with pytest.raises(psycopg.errors.RaiseException, match="does not belong"):
        with alice.session() as c:
            wrong = item(company="B")
            wrong["product"] = {"id": str(pid)}      # belongs to company A, not B
            push(c, [wrong])


def test_hidden_company_cannot_be_pushed_into(su, alice):
    with alice.session() as c:
        push(c, [item(company="Old Co")])
    su.execute("update public.companies set hidden_at = now()")
    with pytest.raises(psycopg.errors.RaiseException, match="hidden"):
        with alice.session() as c:
            push(c, [item(company="Old Co")])


def test_conflicts_are_recorded_not_blocking(su, alice, bob):
    with alice.session() as c:
        r = push(c, [item(title="Never auto-retry payments")])
    old_id = r["items"][0]["id"]
    with bob.session() as c:
        r2 = push(c, [item(title="Retry 3 times", conflicts=[{"other_id": old_id, "note": "contradicts the no-retry rule"},
                                                              {"other_id": str(uuid.uuid4()), "note": "ghost"}])])
    assert r2["saved"] == 1 and r2["conflicts"] == 1                  # ghost target skipped, not an error
    assert su.execute("select count(*) from public.decision_conflicts").fetchone()[0] == 1


def test_push_records_the_cutoff_per_device(su, alice):
    with alice.session() as c:
        push(c, [item()], device="laptop", cutoff="2026-11-25T10:00:00+00:00")
    with alice.session() as c:
        push(c, [item(title="x")], device="desktop", cutoff="2026-11-25T11:00:00+00:00")
    rows = su.execute("select device_id, cutoff_at, item_count from public.push_batches order by device_id").fetchall()
    assert [r[0] for r in rows] == ["desktop", "laptop"] and all(r[2] == 1 for r in rows)


@pytest.mark.parametrize("bad", [None, "not an array", {"a": 1}])
def test_bad_payload_is_rejected(alice, bad):
    with pytest.raises(psycopg.errors.RaiseException):
        with alice.session() as c:
            c.execute("select public.push_review('d', now(), %s::jsonb, '{}')", (json.dumps(bad),))


def test_item_without_keep_id_is_rejected(alice):
    it = item()
    del it["keep_id"]
    with pytest.raises(psycopg.errors.RaiseException, match="keep_id"):
        with alice.session() as c:
            push(c, [it])


# ---- chat contributions -------------------------------------------------------------------------

def test_chat_contributions_lists_only_own_items_for_that_chat(alice, bob):
    with alice.session() as c:
        c.execute("insert into public.decisions (keep_id,chat_id,title,decision,status) values (gen_random_uuid(),'c1','draft in c1','x','unsaved')")
        push(c, [item(chat_id="c1", title="saved in c1"), item(chat_id="c2", title="saved in c2")])
    with bob.session() as c:
        push(c, [item(chat_id="c1", title="bobs c1")])
    with alice.session() as c:
        rows = c.execute("select title, status from public.chat_contributions('c1') order by title").fetchall()
    assert rows == [("draft in c1", "unsaved"), ("saved in c1", "saved")]


# ---- search -------------------------------------------------------------------------------------

def seed_for_search(alice):
    with alice.session() as c:
        push(c, [
            item(title="Retry failed payments", company="Acme", product="Billing",
                 decision="Retry card payments three times then email the client", embedding=vec(0, 1), embedding_model="m"),
            item(title="Invoice numbering", company="Acme", product="Billing",
                 decision="Invoices are numbered sequentially per year", embedding=vec(5, 6), embedding_model="m"),
            item(title="Always use UTC", company="Acme", product=None,
                 decision="Store all timestamps in UTC across every Acme product", embedding=vec(10, 11), embedding_model="m"),
            item(title="Checkout coupon limits", company="Acme", product="Checkout",
                 decision="Only one coupon per order", embedding=vec(20, 21), embedding_model="m"),
            item(title="Retry policy for Globex", company="Globex", product=None,
                 decision="Retry failed card payments five times for Globex", embedding=vec(0, 2), embedding_model="m"),
        ])


def search(conn, q, emb=None, **kw):
    cols = conn.execute(
        "select title, company, product, scope, keyword_rank, vector_rank "
        "from public.search_decisions(%s, %s::extensions.vector, %s, %s, %s, 20)",
        (q, json.dumps(emb) if emb else None, kw.get("company"), kw.get("product"), kw.get("all", False)),
    ).fetchall()
    return cols


def acme(su):
    return su.execute("select id from public.companies where name='Acme'").fetchone()[0]


def product(su, name):
    return su.execute("select id from public.products where name=%s", (name,)).fetchone()[0]


def test_search_requires_a_company_unless_all(su, alice):
    seed_for_search(alice)
    with pytest.raises(psycopg.errors.RaiseException, match="company is required"):
        with alice.session() as c:
            search(c, "retry")


def test_keyword_search_is_scoped_to_one_company(su, alice):
    seed_for_search(alice)
    with alice.session() as c:
        titles = [r[0] for r in search(c, "retry payments", company=str(acme(su)))]
    assert "Retry failed payments" in titles and "Retry policy for Globex" not in titles


def test_search_all_spans_companies_and_labels_them(su, alice):
    seed_for_search(alice)
    with alice.session() as c:
        rows = search(c, "retry card payments", all=True)
    assert {r[1] for r in rows} == {"Acme", "Globex"}


def test_product_search_includes_company_wide_and_excludes_other_products(su, alice):
    seed_for_search(alice)
    with alice.session() as c:
        rows = search(c, "UTC coupon invoices timestamps", company=str(acme(su)), product=str(product(su, "Billing")))
    scopes = {r[0]: r[3] for r in rows}
    assert scopes.get("Always use UTC") == "company"
    assert "Checkout coupon limits" not in scopes


def test_vector_search_finds_meaning_without_shared_words(su, alice):
    seed_for_search(alice)
    with alice.session() as c:
        rows = search(c, "zzz nothing matches this wording", emb=vec(5, 6), company=str(acme(su)))
    assert rows[0][0] == "Invoice numbering" and rows[0][4] is None and rows[0][5] == 1


def test_hybrid_ranks_decision_found_by_both_signals_first(su, alice):
    seed_for_search(alice)
    with alice.session() as c:
        rows = search(c, "retry payments", emb=vec(0, 1), company=str(acme(su)))
    assert rows[0][0] == "Retry failed payments" and rows[0][4] == 1 and rows[0][5] == 1


def test_missing_embedding_falls_back_to_keywords(su, alice):
    with alice.session() as c:
        push(c, [item(title="No vector", decision="keyword only decision", embedding=None)])
    with alice.session() as c:
        rows = search(c, "keyword", emb=vec(1), all=True)
    assert [r[0] for r in rows] == ["No vector"]


def test_search_skips_hidden_unsaved_and_other_peoples_drafts(su, alice, bob):
    with alice.session() as c:
        push(c, [item(title="visible one", decision="alpha topic"), item(title="hidden one", decision="alpha topic")])
        c.execute("insert into public.decisions (keep_id,title,decision,status) values (gen_random_uuid(),'my draft','alpha topic','unsaved')")
    hid = su.execute("select id from public.decisions where title='hidden one'").fetchone()[0]
    with alice.session() as c:
        c.execute("select public.hide_decision(%s)", (hid,))
    with bob.session() as c:
        assert [r[0] for r in search(c, "alpha", all=True)] == ["visible one"]
    with alice.session() as c:
        assert [r[0] for r in search(c, "alpha", all=True)] == ["visible one"]   # own hidden + own draft excluded too


def test_similar_decisions_orders_by_closeness_and_can_exclude(su, alice):
    seed_for_search(alice)
    cid = acme(su)
    with alice.session() as c:
        rows = c.execute("select title, similarity from public.similar_decisions(%s::extensions.vector, %s, 3)",
                         (json.dumps(vec(0, 1)), cid)).fetchall()
        assert rows[0][0] == "Retry failed payments" and rows[0][1] > 0.99
        first = c.execute("select id from public.decisions where title='Retry failed payments'").fetchone()[0]
        rows2 = c.execute("select title from public.similar_decisions(%s::extensions.vector, %s, 3, %s)",
                          (json.dumps(vec(0, 1)), cid, [first])).fetchall()
    assert "Retry failed payments" not in [r[0] for r in rows2]


# ---- company brief ------------------------------------------------------------------------------

def test_company_brief_shape_and_scoping(su, alice):
    seed_for_search(alice)
    with alice.session() as c:
        a = c.execute("select id from public.decisions where title='Retry failed payments'").fetchone()[0]
        b = c.execute("select id from public.decisions where title='Always use UTC'").fetchone()[0]
        c.execute("insert into public.decision_conflicts (decision_id, other_id, note, created_by) values (%s,%s,'differs',%s)", (a, b, alice.id))
        brief = c.execute("select public.company_brief(%s, %s)", (acme(su), product(su, "Billing"))).fetchone()[0]
    assert brief["company"]["name"] == "Acme"
    assert [g["title"] for g in brief["guidelines"]] == ["Always use UTC"]
    assert {p["title"] for p in brief["product_decisions"]} == {"Retry failed payments", "Invoice numbering"}
    assert len(brief["conflicts"]) == 1 and brief["conflicts"][0]["note"] == "differs"


def test_company_brief_without_product_has_no_product_section(su, alice):
    seed_for_search(alice)
    with alice.session() as c:
        brief = c.execute("select public.company_brief(%s)", (acme(su),)).fetchone()[0]
    assert brief["product_decisions"] == []


def test_unknown_company_brief_is_an_error(alice):
    with pytest.raises(psycopg.errors.RaiseException, match="company not found"):
        with alice.session() as c:
            c.execute("select public.company_brief(%s)", (uuid.uuid4(),))
