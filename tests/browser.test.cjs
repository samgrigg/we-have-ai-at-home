// Exercise browser state transitions without a browser or third-party test runtime.
const {readFileSync} = require('fs');
const vm = require('vm');
const assert = require('assert').strict;

class Element {
  constructor() { this.children = []; this.value = ''; this.disabled = false; this.textContent = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener() {}
  focus() {}
}
function storage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {getItem: k => map.get(k) || null, setItem: (k,v) => map.set(k,v), removeItem: k => map.delete(k)};
}
async function harness(pending = null) {
  const elements = new Map();
  let jobs = [{id:'job1', content:'Old message', response:'Old reply', status:'completed'}];
  const context = vm.createContext({
    document: {getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); }, createElement: () => new Element()},
    localStorage: storage({'household-conversation': 'c1'}),
    sessionStorage: storage(pending ? {'household-pending': JSON.stringify(pending)} : {}),
    crypto: require('crypto'),
    setInterval() {},
    fetch: async path => ({ok: true, json: async () => {
      if (path === '/api/conversations') return [{id:'c1', title:'First'}, {id:'c2', title:'Empty'}];
      if (path === '/api/shopping-list') return [];
      return path.includes('/c1/') ? jobs : [];
    }}),
  });
  vm.runInContext(readFileSync('src/household/static/app.js', 'utf8'), context);
  await new Promise(setImmediate);
  return {elements, context, setJobs(value) { jobs = value; }};
}

(async () => {
  const h = await harness();
  await h.elements.get('conversations').children[1].onclick();
  assert.equal(h.elements.get('messages').children.length, 0, 'empty chat must clear previous transcript');

  const p = await harness({cid:'c1', body:{request_id:'job1', content:'Old message'}});
  assert.equal(p.elements.get('retry-area').children.length, 2);
  p.setJobs([{id:'job1', content:'Old message', status:'processing'}]);
  await vm.runInContext('refresh()', p.context);
  assert.equal(p.elements.get('retry-area').children.length, 2, 'polling must preserve resend controls');
  p.setJobs([{id:'other-job', content:'Other tab request', status:'failed', error:'Please retry'}]);
  await vm.runInContext('refresh()', p.context);
  const controls = p.elements.get('retry-area').children.map(button => button.textContent);
  assert(controls.includes('Retry request'), 'pending message must not hide failed-job retry');
  assert(controls.includes('Keep editing message'), 'a conflicting pending submission needs an escape');
  console.log('3 browser recovery checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
