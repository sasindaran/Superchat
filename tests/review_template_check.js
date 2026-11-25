// Drives review/template.html in jsdom with a fake `host:superchat` MCP. Run by tests/test_review_template.py.
const { JSDOM } = require('jsdom');
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const results = [];
const check = (name, ok, extra) => results.push({ name, ok: !!ok, extra: ok ? undefined : extra });

const LIST = {
  cutoff: '2026-11-25T12:00:00+00:00', built_at: '2026-11-25T12:00:00+00:00',
  companies: [{ id: 'c1', name: 'Acme', aliases: [], products: [{ id: 'p1', name: 'Billing' }] }],
  items: [
    { keep_id: 'A', source: 'queue', chat_id: 'chat-1', kind: 'decision', title: 'Retry payments', decision: 'Retry three times', condition: 'declined', reason: null,
      kept_at: '2026-11-25T10:00:00Z', source_agent: 'claude-code', folder_key: 'github.com/acme/billing',
      suggestion: { strength: 'strong', evidence: 'this project folder is linked to it', company: { id: 'c1', name: 'Acme' }, product: { id: 'p1', name: 'Billing' } }, similar: [] },
    { keep_id: 'B', source: 'queue', kind: 'key_note', title: 'Standup time', decision: 'Standup is at 10', kept_at: '2026-11-25T11:00:00Z',
      suggestion: { strength: 'none', evidence: 'no known company is mentioned', company: null, product: null }, similar: [] },
    { keep_id: 'C', source: 'draft', kind: 'decision', title: 'Retry policy', decision: 'Retry 3 times then mail', kept_at: '2026-11-25T11:30:00Z',
      suggestion: { strength: 'strong', evidence: 'x', company: { id: 'c1', name: 'Acme' }, product: null },
      similar: [{ id: 'S1', title: 'Never retry', decision: 'No retries', company: 'Acme', product: null, similarity: 0.9 }] },
  ],
};

function boot(callTool) {
  const dom = new JSDOM('<!doctype html><html><body>' + html + '</body></html>', {
    runScripts: 'dangerously', pretendToBeVisual: true,
    beforeParse(w) { w.claude = { use: async (n) => (n === 'mcp' ? { callTool } : null) }; },
  });
  return dom.window;
}
const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));
const text = (w) => w.document.body.textContent;
function type(w, el, value) { el.value = value; el.dispatchEvent(new w.Event('change', { bubbles: true })); }

(async () => {
  // ---- happy path ----------------------------------------------------------------------------
  const calls = [];
  let w = boot(async (server, tool, input) => {
    calls.push({ server, tool, input });
    if (tool === 'review_list') return { payload: LIST };
    if (tool === 'push_review') return { payload: { saved: 2, skipped: 0, removed: 1, conflicts: 1 } };
  });
  await tick();
  const d = w.document;
  check('loads the real list from host:superchat', calls[0] && calls[0].server === 'host:superchat' && calls[0].tool === 'review_list');
  check('three cards', d.querySelectorAll('.card').length === 3);
  const push = d.getElementById('push');
  check('push disabled while an item has no company', push.disabled && /1 item needs a company/.test(text(w)));
  check('strong suggestion is prefilled, weak one is blank',
    d.querySelectorAll('input[aria-label=Company]')[0].value === 'Acme' && d.querySelectorAll('input[aria-label=Company]')[1].value === '');
  check('red warning when product is empty', /apply to ALL of Acme's products/.test(text(w)) && !!d.querySelector('.field.empty-product'));

  type(w, d.querySelectorAll('input[aria-label=Company]')[1], 'New Co');
  await tick();
  check('push enabled once every ticked item has a company', !d.getElementById('push').disabled);
  check('new company is labelled new', /new company/.test(text(w)));

  // similar hit: mark as conflict (stays ticked), then un-tick C instead
  const sel = d.querySelector('.similar select');
  sel.value = 'conflict'; sel.dispatchEvent(new w.Event('change', { bubbles: true }));
  await tick();
  check('conflict keeps the item ticked', d.querySelectorAll('.head input[type=checkbox]')[2].checked);
  const cbC = d.querySelectorAll('.head input[type=checkbox]')[2];
  const sel2 = d.querySelector('.similar select');
  sel2.value = 'duplicate'; sel2.dispatchEvent(new w.Event('change', { bubbles: true }));
  await tick();
  check('marking a duplicate un-ticks it', !d.querySelectorAll('.head input[type=checkbox]')[2].checked);
  const fresh = d.querySelector('.similar select');                         // the page re-rendered: use the new element
  fresh.value = 'conflict'; fresh.dispatchEvent(new w.Event('change', { bubbles: true }));
  await tick();
  d.querySelectorAll('.head input[type=checkbox]')[2].click();            // re-tick, conflict stays marked
  await tick();
  d.querySelectorAll('.head input[type=checkbox]')[1].click();             // now un-tick B
  await tick();
  const btn = d.getElementById('push');
  check('un-ticking asks for confirmation first', btn.textContent === 'Push…' && /removed completely/.test(text(w)));
  btn.click(); await tick();
  check('second step names what will be deleted', /Confirm: push and delete 1/.test(d.getElementById('push').textContent));
  d.getElementById('push').click(); await tick(60);

  const sent = calls.find((c) => c.tool === 'push_review');
  check('one single push call', calls.filter((c) => c.tool === 'push_review').length === 1);
  check('cutoff passed back unchanged', sent && sent.input.cutoff === LIST.cutoff);
  check('un-ticked item is sent for deletion', sent && JSON.stringify(sent.input.remove_keep_ids) === '["B"]');
  const a = sent && sent.input.items.find((i) => i.keep_id === 'A');
  const c = sent && sent.input.items.find((i) => i.keep_id === 'C');
  check('existing company/product sent by id', a && a.company.id === 'c1' && a.product.id === 'p1', JSON.stringify(a));
  check('empty product sent as null (company-wide)', c && c.product === null && c.company.id === 'c1', JSON.stringify(c));
  check('conflict link sent', c && c.conflicts.length === 1 && c.conflicts[0].other_id === 'S1', JSON.stringify(c));
  check('source details preserved', a && a.chat_id === 'chat-1' && a.folder_key === 'github.com/acme/billing' && a.source_agent === 'claude-code');
  check('result summary shown', /Pushed/.test(text(w)) && /2 saved/.test(text(w)) && /1 deleted/.test(text(w)));
  check('page is finished after a push', d.getElementById('push').disabled);

  // ---- new company by name -------------------------------------------------------------------
  const calls2 = [];
  w = boot(async (s, t, i) => { calls2.push({ t, i }); return t === 'review_list' ? { payload: LIST } : { payload: { saved: 3 } }; });
  await tick();
  type(w, w.document.querySelectorAll('input[aria-label=Company]')[1], 'New Co');
  await tick();
  w.document.getElementById('push').click(); await tick(60);
  const items2 = calls2.find((x) => x.t === 'push_review').i.items;
  const b = items2.find((i) => i.keep_id === 'B');
  check('a new company is sent by name, with no product', b && b.company.name === 'New Co' && !b.company.id && b.product === null, JSON.stringify(b));
  check('all ticked items pushed without confirmation when nothing is deleted', items2.length === 3);

  // ---- failures ------------------------------------------------------------------------------
  w = boot(async (s, t) => { if (t === 'review_list') return { payload: LIST }; const e = new Error('x'); e.code = 'tool_error'; e.message = 'company is required'; throw e; });
  await tick();
  type(w, w.document.querySelectorAll('input[aria-label=Company]')[1], 'New Co'); await tick();
  w.document.getElementById('push').click(); await tick(60);
  check('a refused push says nothing was pushed and keeps the list', /Nothing was pushed/.test(text(w)) && w.document.querySelectorAll('.card').length === 3);

  w = boot(async () => { const e = new Error('x'); e.code = 'server_not_connected'; throw e; });
  await tick();
  check('not-connected explains how to fix it', /Superchat is not connected/.test(text(w)) && /superchat setup/.test(text(w)));

  w = boot(async (s, t) => { if (t === 'review_list') return { payload: LIST }; const e = new Error('x'); e.code = 'approval_required'; throw e; });
  await tick();
  type(w, w.document.querySelectorAll('input[aria-label=Company]')[1], 'Acme'); await tick();
  w.document.getElementById('push').click(); await tick(60);
  check('approval needed is explained and push stays available', /Needs your approval/.test(text(w)) && !w.document.getElementById('push').disabled);

  // ---- empty and no-host ---------------------------------------------------------------------
  w = boot(async () => ({ payload: { cutoff: 'x', built_at: 'x', companies: [], items: [] } }));
  await tick();
  check('empty state explains /keep', /Use \/keep/.test(text(w)) && w.document.getElementById('push').disabled);

  const dom = new JSDOM('<!doctype html><html><body>' + html + '</body></html>', { runScripts: 'dangerously', pretendToBeVisual: true,
    beforeParse(win) { win.claude = { use: async () => null }; } });
  await tick();
  check('no host: shows clearly-marked example data and cannot push',
    /Example data/.test(dom.window.document.body.textContent) && dom.window.document.getElementById('push').disabled);

  // ---- safety: values from the database are never treated as markup -----------------------------
  const evil = JSON.parse(JSON.stringify(LIST));
  evil.items[0].title = '<img src=x onerror=window.__pwned=1>';
  evil.items[0].decision = '<script>window.__pwned=1</script>';
  evil.companies[0].name = '"><b id=boom>';
  w = boot(async () => ({ payload: evil }));
  await tick();
  check('markup in data stays text', !w.__pwned && !w.document.getElementById('boom') && !w.document.querySelector('.card img'));

  const failed = results.filter((r) => !r.ok);
  results.forEach((r) => console.log((r.ok ? 'PASS ' : 'FAIL ') + r.name + (r.extra ? '  -> ' + r.extra : '')));
  console.log(failed.length ? `FAILED ${failed.length}/${results.length}` : `ALL ${results.length} PASSED`);
  process.exit(failed.length ? 1 : 0);
})();
