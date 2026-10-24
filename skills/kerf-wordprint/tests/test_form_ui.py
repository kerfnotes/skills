"""Synthetic DOM/XHR interaction tests. No browser, recordings, or network access."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).parents[1]
HARNESS = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const code = INPUT.code, html = INPUT.html;
class El {
  constructor(tag) { this.tagName=tag; this.children=[]; this.dataset={}; this.attrs={}; this.events={}; this.value=''; this.defaultValue=''; this.checked=false; this.disabled=false; this.hidden=false; this._text=''; this.classList={add(){},remove(){}}; }
  append(...items) { for(const item of items) {item.parent=this; this.children.push(item);} }
  replaceChildren(...items) { this.children.forEach(x=>x.parent=null); this.children=[]; this.append(...items); }
  set textContent(v) {this._text=String(v); this.replaceChildren();}
  get textContent() {return this._text+this.children.map(x=>x.textContent).join('');}
  setAttribute(k,v) {this.attrs[k]=String(v);}
  addEventListener(name,fn) {(this.events[name]??=[]).push(fn);}
  async fire(name,extra={}) {for(const fn of this.events[name]||[]) await fn({preventDefault(){},target:this,...extra});}
  focus() {this.doc.activeElement=this;}
  click() {return this.disabled ? Promise.resolve() : this.fire('click');}
  matches(sel) {
    sel=sel.trim(); if(sel.startsWith('#')) return this.id===sel.slice(1);
    if(sel.endsWith(':checked')) return this.checked&&this.matches(sel.slice(0,-8));
    const m=sel.match(/^(\w+)?\[([^=\]]+)(?:=([^\]]+))?\]$/);
    if(m) {if(m[1]&&this.tagName!==m[1])return false; const key=m[2];
      const val=key.startsWith('data-')?this.dataset[key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]:this[key];
      return m[3]===undefined?val!==undefined:String(val)===m[3];}
    return this.tagName===sel;
  }
  querySelectorAll(sel) {return this.children.flatMap(x=>[x,...x.querySelectorAll('*')]).filter(x=>sel==='*'||sel.split(',').some(s=>x.matches(s)));}
  querySelector(sel) {return this.querySelectorAll(sel)[0]||null;}
  closest(sel) {return this.matches(sel)?this:this.parent?.closest(sel);}
}
function boot(state={},options={}) {
  const doc=new El('document'); doc.doc=doc; doc.createElement=(tag)=>{const el=new El(tag);el.doc=doc;return el;};
  doc.getElementById=(id)=>doc.querySelector('#'+id);
  for(const match of html.matchAll(/<([a-z][a-z0-9-]*)\b([^>]*)>/g)) {
    const tag=match[1], raw=match[2]; if(!/\bid=|data-browse=/.test(raw))continue;
    const el=doc.createElement(tag);
    for(const a of raw.matchAll(/([\w-]+)="([^"]*)"/g)) {
      const k=a[1],v=a[2]; if(k.startsWith('data-'))el.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=v;else el[k]=v;
    }
    el.hidden=/\bhidden\b/.test(raw); doc.append(el);
  }
  for(const [name,values] of [['engine',['qwen-0.6b','qwen-1.7b','gemini-3.5-transcribe','colab']],['summary',['meeting','none','custom']]]) {
    for(const value of values){const el=doc.createElement('input');el.name=name;el.value=value;el.checked=value===values[0];doc.append(el);}
  }
  const get=id=>doc.getElementById(id);
  get('initial-state').textContent=JSON.stringify({sources:[],memos:[],settings:{engine:'qwen-0.6b',summary:'meeting',roster:[],recipients:[],mail:false,merge:false},...state});
  const responses=[],requests=[],uploads=[];
  const storage=options.storage||new Map(), win=new El('window');
  win.location={origin:'http://127.0.0.1:12345',pathname:options.path||'/token-one/',search:''};
  Object.defineProperty(win,'sessionStorage',{get(){
    if(options.blockStorage)throw new Error('storage blocked');
    return {getItem:key=>storage.get(key)??null,setItem:(key,value)=>{if(options.fullStorage)throw new Error('quota');storage.set(key,value);},removeItem:key=>storage.delete(key)};
  }});
  class File {constructor(name,size=64,type='audio/wav'){this.name=name;this.size=size;this.type=type;}}
  class XHR {
    constructor(){this.upload={};this.headers={};}
    open(method,url){this.method=method;this.url=url;}
    setRequestHeader(k,v){this.headers[k]=v;}
    send(file){this.file=file;uploads.push(this);}
    respond(status,result){this.status=status;this.responseText=JSON.stringify(result);this.onload();}
  }
  vm.runInNewContext(code,{document:doc,File,XMLHttpRequest:XHR,...(options.noWindow?{}:{window:win}),fetch:async(url,options)=>{
    requests.push({url,body:JSON.parse(options.body)});const response=responses.shift();
    if(response instanceof Error)throw response;
    if(typeof response==='function')return response();
    return {ok:true,json:async()=>response||{ok:true}};
  }});
  const tick=()=>new Promise(resolve=>setImmediate(resolve));
  const sourceAction=async(index,action)=>{const row=get('source-list').children[index];const button=row.querySelectorAll('[data-source-action]').find(x=>x.dataset.sourceAction===action);assert.ok(button);await get('source-list').fire('click',{target:button});await tick();};
  const checkbox=id=>doc.querySelectorAll('[data-memo-id]').find(x=>x.tagName==='input'&&x.dataset.memoId===id);
  return {doc,get,responses,requests,uploads,File,tick,sourceAction,checkbox,storage,win};
}
const memo=(id,availability='local')=>({id,title:'合成訪談 '+id,path:'/synthetic/'+id+'.m4a',recorded_at:'2026-10-24T09:11:00+08:00',duration:67,byte_count:64,availability});
const done=(id)=>({id,title:'合成上傳 '+id,byte_count:64,sha256:'a'.repeat(64)});
'''


@unittest.skipUnless(shutil.which('node'), 'Node is required for synthetic UI tests')
class FormUITests(unittest.TestCase):
    def run_js(self, scenario):
        data = {'code': (ROOT / 'scripts/form.js').read_text(),
                'html': (ROOT / 'scripts/form.html').read_text()}
        program = 'const INPUT=' + json.dumps(data) + ';\n' + HARNESS
        program += '\n(async()=>{\n' + scenario + '\n})().catch(e=>{console.error(e);process.exitCode=1;});'
        result = subprocess.run(['node'], input=program, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_add_remove_readd_progressively_shows_output_without_resetting_choices(self):
        self.run_js(r'''
const e=boot();
assert.equal(e.get('selected-sources').hidden,true);
assert.equal(e.get('output-settings').hidden,true);
e.get('paths').value='/synthetic/one.wav';await e.get('add-paths').click();
assert.equal(e.get('selected-sources').hidden,false);
assert.equal(e.get('output-settings').hidden,false);
assert.equal(e.get('current-output').textContent,'逐字稿＋會議摘要');
for(const input of e.doc.querySelectorAll('input[name=summary]'))input.checked=input.value==='none';
for(const input of e.doc.querySelectorAll('input[name=engine]'))input.checked=input.value==='qwen-1.7b';
await e.doc.fire('change');await e.sourceAction(0,'remove');
assert.equal(e.get('output-settings').hidden,true);assert.equal(e.doc.activeElement,e.get('choose-files'));
e.get('paths').value='/synthetic/two.wav';await e.get('add-paths').click();
assert.equal(e.get('current-output').textContent,'逐字稿');
await e.get('form').fire('submit');
assert.equal(e.requests[0].body.engine,'qwen-1.7b');assert.equal(e.requests[0].body.summary,'none');
assert.equal('mode' in e.requests[0].body,false);assert.equal(e.storage.size,0);
assert.equal(e.get('form').hidden,true);assert.equal(e.get('success').hidden,false);
''')

    def test_mode_names_the_action_and_colab_remains_a_handoff(self):
        self.run_js(r'''
const collect=boot();assert.equal(collect.get('submit').textContent,'送出設定');
const run=boot({mode:'run',sources:[{kind:'path',path:'/synthetic/a.wav',title:'A'}]});
assert.equal(run.get('submit').textContent,'開始整理');
for(const input of run.doc.querySelectorAll('input[name=engine]'))input.checked=input.value==='colab';
await run.doc.fire('change');assert.equal(run.get('submit').textContent,'準備 Colab');
await run.get('form').fire('submit');assert.equal(run.requests[0].body.engine,'colab');
assert.equal('mode' in run.requests[0].body,false);
''')

    def test_memo_refresh_selection_unavailable_and_mixed_order(self):
        self.run_js(r'''
const e=boot({sources:[{kind:'path',path:'/synthetic/folder',title:'合成資料夾'}],memos:[memo('a'),memo('b','missing'),memo('c','unreadable')]});
assert.equal(e.get('merge-row').hidden,false);
assert.equal(e.checkbox('a').checked,false);assert.equal(e.checkbox('b').disabled,true);assert.equal(e.checkbox('c').disabled,true);
e.checkbox('a').checked=true;await e.checkbox('a').fire('change');
e.responses.push({memos:[memo('c','unreadable'),memo('a'),memo('b','missing')],total:23});await e.get('read-memos').click();
assert.equal(e.checkbox('a').checked,true);
await e.get('add-memos').click();assert.equal(e.get('source-count').textContent,'2');
await e.sourceAction(1,'up');await e.get('form').fire('submit');
const result=e.requests.at(-1).body;assert.deepEqual(result.sources,[{memo_id:'a'},{kind:'path',path:'/synthetic/folder',title:'合成資料夾'}]);
assert.equal('memos' in result,false);assert.equal('paths' in result,false);assert.equal(e.get('success').hidden,false);
''')

    def test_serial_upload_partial_failure_retry_and_submit_guard(self):
        self.run_js(r'''
const e=boot(), first=new e.File('很長的合成中文錄音名稱.wav'), second=new e.File('第二段.wav');
e.get('files').files=[first,second];await e.get('files').fire('change');
assert.equal(e.uploads.length,1);assert.equal(e.uploads[0].file,first);assert.equal(e.uploads[0].headers['X-File-Name'],encodeURIComponent(first.name));
assert.equal(e.get('submit').disabled,true);assert.equal(e.get('read-memos').disabled,true);
e.uploads[0].upload.onprogress({lengthComputable:true,loaded:32,total:64});assert.equal(e.doc.querySelector('progress').value,50);
await e.get('form').fire('submit');assert.equal(e.requests.length,0);
e.uploads[0].respond(200,done('up-a'));await e.tick();assert.equal(e.uploads.length,2);
e.uploads[1].respond(500,{error:'合成失敗'});await e.tick();assert.equal(e.get('submit').disabled,true);
const retry=e.get('source-list').children[1].querySelectorAll('[data-source-action]').find(x=>x.dataset.sourceAction==='retry');assert.equal(retry.disabled,false);
await e.get('form').fire('submit');assert.equal(e.requests.length,0);assert.match(e.get('sources-error').textContent,/重試/);
await e.sourceAction(1,'retry');assert.equal(e.uploads.length,3);assert.equal(e.uploads[2].file,second);
e.uploads[2].respond(200,done('up-b'));await e.tick();await e.sourceAction(1,'up');
await e.get('form').fire('submit');assert.deepEqual(e.requests[0].body.sources,[{upload_id:'up-b'},{upload_id:'up-a'}]);
assert.equal(e.uploads.filter(x=>x.file===first).length,1);
''')

    def test_failed_upload_remove_and_missing_file_drops(self):
        self.run_js(r'''
const e=boot();await e.get('drop-zone').fire('drop',{dataTransfer:{files:[],items:[]}});assert.match(e.get('upload-error').textContent,/匯出/);
await e.get('drop-zone').fire('drop',{dataTransfer:{files:[],items:[{webkitGetAsEntry:()=>({isDirectory:true})}]}});assert.match(e.get('upload-error').textContent,/資料夾/);
e.get('files').files=[new e.File('oversize.wav',1024**3+1),new e.File('note.txt',25,'text/plain')];await e.get('files').fire('change');assert.equal(e.uploads.length,0);
e.get('files').files=[new e.File('ok.wav'),new e.File('fail.wav')];await e.get('files').fire('change');
e.uploads[0].respond(200,done('ok'));await e.tick();e.uploads[1].onerror();await e.tick();
await e.sourceAction(1,'remove');await e.get('form').fire('submit');assert.deepEqual(e.requests.at(-1).body.sources,[{upload_id:'ok'}]);
''')

    def test_native_picker_cancel_error_preserves_sources(self):
        self.run_js(r'''
const e=boot();const picker=e.doc.querySelectorAll('[data-browse]').find(x=>x.dataset.browse==='folder');
e.responses.push({paths:['/synthetic/B','/synthetic/A']});await picker.click();assert.equal(e.get('source-count').textContent,'2');
e.responses.push({paths:[]});await picker.click();assert.equal(e.get('source-count').textContent,'2');
e.responses.push(new Error('合成讀取失敗'));await picker.click();assert.match(e.get('browse-error').textContent,/讀取失敗/);assert.equal(e.get('source-count').textContent,'2');
e.responses.push(new Error('合成備忘錄失敗'));await e.get('read-memos').click();assert.match(e.get('memo-error').textContent,/保留/);
await e.get('form').fire('submit');assert.deepEqual(e.requests.at(-1).body.sources.map(x=>x.path),['/synthetic/B','/synthetic/A']);
''')

    def test_validation_focus_and_duplicate_submit(self):
        self.run_js(r'''
const e=boot({sources:[{kind:'path',path:'/synthetic/a.wav',title:'A'}]});
e.get('recipients').value='bad';await e.get('form').fire('submit');assert.equal(e.get('optional-settings').open,true);assert.equal(e.doc.activeElement,e.get('recipients'));
e.get('recipients').value='';e.get('paths').value='/synthetic/unadded.wav';await e.get('form').fire('submit');assert.equal(e.get('more-sources').open,true);assert.equal(e.requests.length,0);
e.get('paths').value='';let finish;e.responses.push(()=>new Promise(resolve=>{finish=resolve;}));
const submitting=e.get('form').fire('submit');await e.tick();await e.get('form').fire('submit');assert.equal(e.requests.length,1);
finish({ok:true,json:async()=>({ok:true})});await submitting;assert.equal(e.get('form').hidden,true);assert.equal(e.get('submit').disabled,true);
''')

    def test_reload_restores_completed_sources_order_settings_and_clears_on_success(self):
        self.run_js(r'''
const initial={sources:[{kind:'path',path:'/synthetic/folder',title:'資料夾'}],memos:[memo('a')]};
const e=boot(initial);e.checkbox('a').checked=true;await e.checkbox('a').fire('change');await e.get('add-memos').click();
e.get('files').files=[new e.File('one.wav')];await e.get('files').fire('change');e.uploads[0].respond(200,done('up-one'));await e.tick();
await e.sourceAction(2,'up');await e.sourceAction(1,'up');
for(const input of e.doc.querySelectorAll('input[name=summary]'))input.checked=input.value==='custom';
e.get('summary_custom').value='保留待辦';e.get('roster').value='甲、乙';e.get('recipients').value='person@example.com';
e.get('merge').checked=true;e.get('mail').checked=true;await e.doc.fire('change');
const saved=JSON.parse([...e.storage.values()][0]);assert.equal(saved.sources[0].payload.upload_id,'up-one');assert.equal(JSON.stringify(saved).includes('"file"'),false);
const r=boot(initial,{storage:e.storage});assert.match(r.get('draft-status').textContent,/已恢復/);assert.equal(r.get('source-count').textContent,'3');
assert.equal(r.uploads.length,0);assert.equal(r.get('summary_custom').value,'保留待辦');assert.equal(r.get('custom-row').hidden,false);
assert.equal(r.get('roster').value,'甲、乙');assert.equal(r.get('recipients').value,'person@example.com');assert.equal(r.get('mail').checked,true);
await r.get('form').fire('submit');assert.deepEqual(r.requests[0].body.sources,[{upload_id:'up-one'},initial.sources[0],{memo_id:'a'}]);
assert.equal(r.requests[0].body.merge,true);assert.equal(r.requests[0].body.engine,'qwen-0.6b');assert.equal(r.storage.size,0);
''')

    def test_reload_pending_requires_reselection_and_preserves_slot(self):
        self.run_js(r'''
const e=boot();e.get('files').files=[new e.File('done.wav'),new e.File('pending.wav')];await e.get('files').fire('change');
e.uploads[0].respond(200,done('complete'));await e.tick();
let warned=false;await e.win.fire('beforeunload',{preventDefault(){warned=true;}});assert.equal(warned,true);
const r=boot({}, {storage:e.storage});assert.equal(r.uploads.length,0);assert.equal(r.get('source-list').children[1].dataset.status,'needs-selection');
assert.match(r.get('draft-status').textContent,/重新選取/);await r.get('form').fire('submit');assert.equal(r.requests.length,0);
await r.sourceAction(1,'reselect');await r.get('files').fire('cancel');assert.equal(r.get('source-count').textContent,'2');
await r.sourceAction(1,'reselect');r.get('files').files=[new r.File('pending.wav')];await r.get('files').fire('change');
assert.equal(r.get('source-count').textContent,'2');r.uploads[0].respond(200,done('replacement'));await r.tick();
assert.doesNotMatch(r.get('draft-status').textContent,/須重新選取/);
assert.equal(r.get('sources-error').textContent,'');assert.equal(r.get('source-list').attrs['aria-invalid'],'false');
warned=false;await r.win.fire('beforeunload',{preventDefault(){warned=true;}});assert.equal(warned,false);
await r.get('form').fire('submit');assert.deepEqual(r.requests[0].body.sources,[{upload_id:'complete'},{upload_id:'replacement'}]);
''')

    def test_explicit_large_model_draft_survives_small_default(self):
        self.run_js(r'''
const e=boot({settings:{engine:'qwen-1.7b',summary:'custom',summary_custom:'保留決議',roster:[],recipients:[],mail:false,merge:false}});
e.get('paths').value='/synthetic/custom.wav';await e.get('add-paths').click();
const r=boot({}, {storage:e.storage});
assert.equal(r.doc.querySelector('input[name=engine]:checked').value,'qwen-1.7b');
assert.equal(r.doc.querySelector('input[name=summary]:checked').value,'custom');
assert.equal(r.get('summary_custom').value,'保留決議');
await r.get('form').fire('submit');
assert.equal(r.requests[0].body.engine,'qwen-1.7b');
assert.equal(r.requests[0].body.sources[0].path,'/synthetic/custom.wav');
''')

    def test_draft_scope_invalid_structures_and_storage_failures(self):
        self.run_js(r'''
const e=boot();e.get('paths').value='/synthetic/a.wav';await e.get('add-paths').click();
const other=boot({}, {storage:e.storage,path:'/token-two/'});assert.equal(other.get('source-count').textContent,'');
const key=[...e.storage.keys()].find(key=>key.endsWith('/token-one/')), valid=JSON.parse(e.storage.get(key));
for(const corrupt of ['{',JSON.stringify({...valid,version:2}),JSON.stringify({...valid,settings:{...valid.settings,engine:'unrequested-cloud'}}),JSON.stringify({...valid,sources:[{title:'fake',detail:'',payload:{upload_id:'x',memo_id:'y'}}]}),JSON.stringify({...valid,sources:[{title:'fake',detail:'',needs_selection:'yes',payload:{upload_id:'x'}}]})]){
 const storage=new Map([[key,corrupt]]),r=boot({}, {storage});assert.equal(r.get('source-count').textContent,'');assert.match(r.get('draft-status').textContent,/無法恢復/);
 assert.equal(r.doc.querySelector('input[name=engine]:checked').value,'qwen-0.6b');
}
for(const options of [{blockStorage:true},{fullStorage:true},{noWindow:true}]){
 const r=boot({},options);r.get('paths').value='/synthetic/a.wav';await r.get('add-paths').click();await r.get('form').fire('submit');assert.equal(r.get('success').hidden,false);
}
''')

    def test_errors_resolve_and_extension_validation_precedes_upload(self):
        self.run_js(r'''
const e=boot();await e.get('form').fire('submit');assert.match(e.get('sources-error').textContent,/至少/);assert.equal(e.get('source-list').attrs['aria-invalid'],'true');
await e.get('add-paths').click();assert.equal(e.get('paths').attrs['aria-invalid'],'true');
e.get('paths').value='/synthetic/new.wav';await e.doc.fire('input');assert.equal(e.get('paths-error').textContent,'');assert.equal(e.get('paths').attrs['aria-invalid'],'false');
e.get('paths').value='';await e.doc.fire('input');
e.get('files').files=[new e.File('bad.webm',64,'audio/webm')];await e.get('files').fire('change');assert.equal(e.uploads.length,0);assert.match(e.get('upload-error').textContent,/副檔名/);
e.get('files').files=[new e.File('ok.WAV')];await e.get('files').fire('change');assert.match(e.get('source-list').textContent,/64 B/);
e.uploads[0].respond(200,done('ok'));await e.tick();assert.equal(e.get('sources-error').textContent,'');assert.equal(e.get('source-list').attrs['aria-invalid'],'false');
for(const input of e.doc.querySelectorAll('input[name=summary]'))input.checked=input.value==='custom';
await e.get('form').fire('submit');assert.equal(e.get('summary_custom').attrs['aria-invalid'],'true');
e.get('summary_custom').value='待辦';await e.doc.fire('input');assert.equal(e.get('custom-error').textContent,'');assert.equal(e.get('summary_custom').attrs['aria-invalid'],'false');
e.get('recipients').value='bad';await e.get('form').fire('submit');assert.equal(e.get('recipients').attrs['aria-invalid'],'true');
e.get('recipients').value='ok@example.com';await e.doc.fire('input');assert.equal(e.get('recipients-error').textContent,'');assert.equal(e.get('recipients').attrs['aria-invalid'],'false');
''')

    def test_submit_failure_keeps_draft_and_prevents_blind_retry(self):
        self.run_js(r'''
const e=boot({sources:[{kind:'path',path:'/synthetic/a.wav',title:'A'}]});
let finish;e.responses.push(()=>new Promise(resolve=>{finish=resolve;}));const first=e.get('form').fire('submit');await e.tick();
let warned=false;await e.win.fire('beforeunload',{preventDefault(){warned=true;}});assert.equal(warned,true);
finish({ok:false,json:async()=>({error:'合成失敗'})});await first;assert.equal(e.get('submit').disabled,true);assert.equal(e.storage.size,2);
assert.match(e.get('error').textContent,/合成失敗/);await e.get('form').fire('submit');assert.equal(e.requests.length,1);
assert.match(e.get('submit-status').textContent,/核對任務/);
warned=false;await e.win.fire('beforeunload',{preventDefault(){warned=true;}});assert.equal(warned,false);
''')

    def test_source_rejection_preserves_state_and_upload_then_recovers(self):
        self.run_js(r'''
const e=boot({sources:[{kind:'path',path:'/synthetic/missing.wav',title:'Missing'}]});
for(const input of e.doc.querySelectorAll('input[name=engine]'))input.checked=input.value==='qwen-1.7b';
for(const input of e.doc.querySelectorAll('input[name=summary]'))input.checked=input.value==='custom';
e.get('summary_custom').value='保留決議';e.get('merge').checked=true;e.get('roster').value='甲、乙';
e.get('recipients').value='person@example.com';e.get('mail').checked=true;
e.get('files').files=[new e.File('done.wav')];await e.get('files').fire('change');
e.uploads[0].respond(200,done('complete'));await e.tick();await e.sourceAction(1,'up');
const before=JSON.parse([...e.storage.values()][0]);
e.responses.push(()=>({ok:false,status:400,json:async()=>({error:'第 2 個來源：無法讀取',code:'invalid_source',saved:false,source_index:1})}));
await e.get('form').fire('submit');
assert.equal(e.get('form').hidden,false);assert.equal(e.get('success').hidden,true);
assert.match(e.get('sources-error').textContent,/第 2 個來源/);assert.match(e.get('submit-status').textContent,/尚未儲存/);
assert.equal(e.doc.activeElement.dataset.sourceAction,'remove');assert.equal(e.doc.activeElement.dataset.key,'source-1');assert.equal(e.get('source-list').attrs['aria-invalid'],'true');
assert.equal(e.get('error').textContent,'');assert.equal(e.get('submit').disabled,false);
assert.deepEqual(JSON.parse([...e.storage.values()][0]),before);assert.equal(e.uploads.length,1);
await e.doc.fire('change');assert.match(e.get('sources-error').textContent,/無法讀取/);
await e.sourceAction(1,'remove');e.get('paths').value='/synthetic/fixed.wav';await e.get('add-paths').click();
assert.equal(e.get('sources-error').textContent,'');await e.get('form').fire('submit');
assert.equal(e.get('success').hidden,false);assert.equal(e.uploads.length,1);
const sent=e.requests[1].body, first=e.requests[0].body;
assert.deepEqual(sent.sources,[{upload_id:'complete'},{kind:'path',path:'/synthetic/fixed.wav',title:'fixed.wav'}]);
for(const key of ['engine','merge','summary','summary_custom','roster','recipients','mail'])assert.deepEqual(sent[key],first[key]);
assert.equal(sent.engine,'qwen-1.7b');assert.equal(sent.merge,true);assert.equal(e.storage.size,0);
''')

    def test_uncertain_submit_never_claims_safe_source_retry(self):
        self.run_js(r'''
for(const response of [new Error('network'),()=>({ok:false,status:500,json:async()=>({error:'save failed',code:'invalid_source',saved:false,source_index:0})}),()=>({ok:false,status:400,json:async()=>({error:'legacy error'})})]){
 const e=boot({sources:[{kind:'path',path:'/synthetic/a.wav',title:'A'}]});
 e.responses.push(response);await e.get('form').fire('submit');
 assert.match(e.get('error').textContent,/先查看 agent/);assert.match(e.get('submit-status').textContent,/尚未確認/);
 assert.equal(e.get('sources-error').textContent,'');assert.equal(e.storage.size,2);assert.equal(e.requests.length,1);
 assert.equal(e.get('form').hidden,false);assert.equal(e.get('success').hidden,true);
}
''')

    def test_canonical_memo_duplicates_blocked_after_refresh_and_reload(self):
        self.run_js(r'''
const canonical={kind:'voice_memo',path:'/synthetic/a.m4a',title:'A'};
const e=boot({sources:[canonical]});e.responses.push({memos:[memo('a')],total:1});await e.get('read-memos').click();
assert.equal(e.checkbox('a').checked,true);assert.equal(e.checkbox('a').disabled,true);assert.equal(e.get('add-memos').disabled,true);
const r=boot({sources:[canonical]}, {storage:e.storage});r.responses.push({memos:[memo('a')],total:1});await r.get('read-memos').click();
assert.equal(r.checkbox('a').disabled,true);assert.equal(r.get('source-count').textContent,'1');
await r.get('form').fire('submit');assert.deepEqual(r.requests.at(-1).body.sources,[canonical]);
const p=boot({sources:[{...canonical,kind:'path'}],memos:[memo('a')]});assert.equal(p.checkbox('a').disabled,false);
p.checkbox('a').checked=true;await p.checkbox('a').fire('change');await p.get('add-memos').click();assert.equal(p.get('source-count').textContent,'2');
''')


if __name__ == '__main__':
    unittest.main()
