// extension/review.js
// Document data stays in this tab and the local service; never use browser storage for findings.
'use strict';
const API = location.protocol === 'chrome-extension:' ? 'http://127.0.0.1:8766' : location.origin;
const $ = id => document.getElementById(id);
let review = null;
let busy = false;
let focused = null;
let sourceFile = null;

async function request(path, options = {}) {
  const response = await fetch(API + path, {...options, headers: {'X-Lexmini-Client': 'review', ...options.headers}});
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); detail = typeof body.detail === 'string' ? body.detail : 'Check the entered values.'; } catch (_) {}
    const error = new Error(detail); error.status = response.status; throw error;
  }
  return response;
}

function status(message, type = '') { $('status').textContent = message; $('status').className = type; }
function updateControls() {
  const ready = review?.analysed && review.pages.every(page => page.readable) && !busy;
  for (const id of ['pdf', 'text', 'keys']) $(id).disabled = !ready;
  for (const id of ['replacementStyle', 'pdfLayout']) $(id).disabled = busy;
  $('qualityCheck').disabled = !review?.analysed || busy;
  $('analyse').disabled = !review || busy;
  $('close').disabled = !review || busy;
  $('demo').disabled = busy;
  $('samples').disabled = busy;
  $('qualitySamples').disabled = busy;
  $('file').disabled = busy;
  for (const id of ['selectAll', 'keepAll']) $(id).disabled = !review?.analysed || busy;
  $('addExample').disabled = !review?.analysed || busy;
  $('approveExample').disabled = !review?.analysed || busy || !['person_name','organisation_name'].includes($('manualType').value);
  $('issueShare').disabled = !review?.analysed || busy;
  for (const id of ['reviewSet','manualTerm','manualType','manualLevel','memoryScope']) $(id).disabled = busy;
  $('reviewSet').disabled = busy || Boolean(review?.analysed);
  $('documentLanguage').disabled = busy || Boolean(review?.analysed);
  for (const id of ['role', 'terms']) $(id).disabled = busy;
  document.querySelectorAll('.finding input, .finding .remember, .group-actions button').forEach(input => { input.disabled = busy; });
}
async function task(action) {
  if (busy) return;
  busy = true; updateControls();
  try { await action(); } catch (error) { status(error.message || 'The local service is unavailable.', 'error'); }
  finally { busy = false; updateControls(); }
}

async function openFile(file) {
  if (review && !confirm('Open another PDF? This will discard the current review.')) return;
  await task(async () => {
    status('Reading the PDF…', 'busy');
    const next = await (await request('/api/documents?filename=' + encodeURIComponent(file.name), {
      method: 'POST', headers: {'Content-Type': 'application/pdf'}, body: file
    })).json();
    if (review) await request(`/api/documents/${review.document_id}`, {method: 'DELETE'}).catch(() => {});
    sourceFile = file;
    review = next; focused = null;
    $('filename').textContent = review.filename;
    $('fileDetails').textContent = `${review.page_count} pages · ${review.metadata_fields.length} file metadata fields · held in local memory`;
    $('empty').hidden = true;
    $('warnings').replaceChildren();
    for (const message of review.warnings) { const p = document.createElement('p'); p.textContent = message; $('warnings').append(p); }
    $('warnings').hidden = !review.warnings.length;
    renderPages(); renderFindings();
    status('Document open. Run screening to find private information.');
  });
}

function renderPages() {
  document.title = `${review.filename} | Lexmini review`;
  $('pages').replaceChildren();
  for (const info of review.pages) {
    const wrapper = document.createElement('section'); wrapper.className = 'page-wrap'; wrapper.id = `page-${info.number}`;
    const label = document.createElement('p'); label.className = 'page-label'; label.textContent = `Page ${info.number}`;
    const page = document.createElement('div'); page.className = 'page'; page.dataset.page = info.number;
    const image = document.createElement('img'); image.alt = `Original document, page ${info.number}`;
    image.width = info.width; image.height = info.height;
    image.src = `${API}/api/documents/${review.document_id}/pages/${info.number}`;
    image.onerror = () => status('A page preview failed to load. Reopen the document if the session expired.', 'error');
    page.append(image); wrapper.append(label, page); $('pages').append(wrapper);
  }
  renderOverlays();
  document.dispatchEvent(new Event('lexmini:pages'));
}

function renderOverlays() {
  document.querySelectorAll('.overlay').forEach(node => node.remove());
  if (!review) return;
  for (const finding of review.findings) {
    const number = finding.location.page_number;
    const page = document.querySelector(`.page[data-page="${number}"]`);
    const info = review.pages[number - 1];
    if (!page || !info) continue;
    for (const [x0,y0,x1,y1] of finding.location.boxes) {
      const button = document.createElement('button');
      button.className = `overlay signal-${finding.review_signal || 'candidate'}${finding.selected ? '' : ' kept'}${finding.finding_id === focused ? ' focused' : ''}`;
      button.dataset.finding = finding.finding_id;
      button.style.left = `${100*x0/info.width}%`; button.style.top = `${100*y0/info.height}%`;
      button.style.width = `${100*(x1-x0)/info.width}%`; button.style.height = `${100*(y1-y0)/info.height}%`;
      button.title = `${finding.selected ? 'Remove' : 'Keep'}: ${finding.original_text} · ${finding.review_signal || 'candidate'} · ${finding.signal_reason || ''}`;
      button.setAttribute('aria-label', `Toggle removal of ${finding.original_text}`);
      button.setAttribute('aria-pressed', String(finding.selected));
      button.onclick = () => { if (!busy) { toggle(finding); focusFinding(finding, false); } };
      page.append(button);
    }
  }
}

function equivalentKey(text) {
  const value=text.normalize('NFKC').toLocaleLowerCase();
  return value.replace(/[\p{P}\p{S}]+/gu,/\d/.test(value)?' ':'').replace(/\s+/g,' ').trim();
}
function toggle(finding, selected = !finding.selected) {
  if (busy) return;
  const equivalent = equivalentKey;
  const target=equivalent(finding.original_text);
  for(const item of review.findings) if(equivalent(item.original_text)===target) {
    item.selected=selected;item.review_status=selected?'confirmed_remove':'confirmed_keep';
  }
  focused = finding.finding_id;
  renderFindings(); renderOverlays();
}

function focusFinding(finding, scrollPage = true) {
  focused = finding.finding_id;
  document.querySelectorAll('[data-finding]').forEach(node => node.classList.toggle('focused', node.dataset.finding === focused));
  if (scrollPage) document.querySelector(`.overlay[data-finding="${focused}"]`)?.scrollIntoView({behavior:'smooth', block:'center'});
  else {
    const row = document.querySelector(`.mention[data-finding="${focused}"]`);
    if (row) {
      row.closest('.mentions').open = true;
      row.closest('.finding-group').open = true;
      row.scrollIntoView({behavior:'smooth', block:'nearest'});
    }
  }
}

const groupState = new Map();
function changeSelection(items, selected) {
  if (busy) return;
  const keys=new Set(items.map(f=>equivalentKey(f.original_text)));
  for (const item of review.findings.filter(f=>keys.has(equivalentKey(f.original_text)))) {
    item.selected = selected;
    item.review_status = selected ? 'confirmed_remove' : 'confirmed_keep';
  }
  renderFindings(); renderOverlays();
}
function element(tag, className, text) {
  const node = document.createElement(tag); node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function screeningContext() {
  return {role:$('role').value, goal:review?.quality_check?.suggested_goal || 'Identify the document purpose and conceal private parties and sensitive case information. Keep ordinary dates and public legal citations.',
    confidential_terms:$('terms').value.split('\n').map(s=>s.trim()).filter(Boolean),
    review_set:$('reviewSet').value.trim() || 'demo', fuzzy_matching:true,
    languages:$('documentLanguage').value.split(','), use_layout:true, use_privacy_filter:true, use_llm_review:true};
}
async function learnExample(example, saveApproved = false) {
  await task(async () => {
    const scope = $('memoryScope').value;
    status('Checking every page against the example…', 'busy');
    review = await (await request(`/api/documents/${review.document_id}/learn`, {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
        ...example, revision:review.revision, remember:saveApproved, workspace_wide:scope === 'workspace',
        kept_ids:review.findings.filter(f=>!f.selected).map(f=>f.finding_id)
      })
    })).json();
    renderFindings(); renderOverlays();
    status(saveApproved ? 'Approved term saved for the chosen organisation scope. Close spellings still need review.' : 'Applied to this document only. Nothing was added to shared screening memory.');
  });
}
function findingCard(items) {
  const first = items[0];
  const selected = items.filter(f => f.selected).length;
  const card = element('article', `finding signal-${first.review_signal || 'candidate'}${selected ? '' : ' kept'}`);
  card.dataset.finding = first.finding_id;
  card.dataset.members = items.map(f=>f.finding_id).join(' ');
  const head = element('div', 'finding-head');
  const check = document.createElement('input'); check.type = 'checkbox';
  check.checked = selected === items.length; check.indeterminate = selected > 0 && selected < items.length;
  check.disabled = busy; check.setAttribute('aria-label', `Remove all ${items.length} visible mentions of ${first.original_text}`);
  check.onchange = () => changeSelection(items, check.checked);
  const title = element('div', 'finding-title');
  const name = element('button', 'finding-name', first.original_text);
  name.onclick = () => focusFinding(first);
  title.append(name, element('span', 'badge', `${first.field_type.replaceAll('_', ' ')} · ${items.length} mention${items.length === 1 ? '' : 's'} · ${selected} selected`));
  head.append(check, title); card.append(head);
  const signals = {approved:'■ Approved term', priority:'▲ Review first', candidate:'● Candidate', weak:'◇ Weak / layout'};
  card.append(element('p', 'signal-label', [...new Set(items.map(f=>signals[f.review_signal || 'candidate']))].join(' · ')));
  const prompt = ['date','birth_date'].includes(first.field_type)
    ? 'Check what this date refers to: birth, case event or cited law. A date match alone does not establish sensitivity.'
    : first.field_type === 'amount' ? 'Check whether this amount reveals the client or matter, or is needed in the output.'
    : first.field_type === 'organisation_name' ? 'Check whether this is a client or party, or an organisation named in a citation.'
    : first.reason;
  card.append(element('p', 'reason', prompt));
  const preview = element('p', 'excerpt first-excerpt');
  preview.append(document.createTextNode(first.excerpt_before || ''), element('mark', '', first.original_text), document.createTextNode(first.excerpt_after || ''));
  card.append(preview);
  const mentions = element('details', 'mentions');
  mentions.open = items.some(f=>f.finding_id === focused);
  mentions.append(element('summary', '', `Context and mentions · ${[...new Set(items.map(f=>f.location.page_number))].map(n=>`p. ${n}`).join(', ')}`));
  for (const finding of items) {
    const row = element('div', 'mention'); row.dataset.finding = finding.finding_id;
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = finding.selected; checkbox.disabled = busy;
    checkbox.setAttribute('aria-label', `Remove mention on page ${finding.location.page_number}: ${finding.original_text}`);
    checkbox.onchange = () => toggle(finding, checkbox.checked);
    const jump = element('button', 'quiet', `Page ${finding.location.page_number} - ${finding.selected ? 'remove' : 'keep'}`);
    jump.onclick = () => focusFinding(finding);
    const excerpt = element('p', 'excerpt');
    excerpt.append(document.createTextNode(finding.excerpt_before || ''), element('mark', '', finding.original_text), document.createTextNode(finding.excerpt_after || ''));
    row.append(checkbox, jump, excerpt); mentions.append(row);
  }
  card.append(mentions);
  const scope = $('memoryScope').value;
  const remember = element('button', 'quiet remember', scope === 'workspace' ? 'Save approved term for this organisation' : `Save approved term in ${review.review_set}`);
  remember.disabled = busy;
  remember.title = 'Explicitly approve and save this value for future screening in the selected scope.';
  remember.onclick = () => learnExample({finding_id:first.finding_id}, true);
  if (["person_name","organisation_name"].includes(first.field_type)) card.append(remember);
  if (items.some(f=>f.detector.includes('fuzzy'))) card.append(element('p', 'suggestion', 'Contains approximate matches - check the spelling and context.'));
  const detail = element('details', 'evidence'); detail.append(element('summary', '', 'Detection details'));
  const sources = [...new Set(items.flatMap(f=>f.detector.split(' + ')))].join(', ');
  detail.append(element('p', '', `Source: ${sources}. Suggested sensitivity: ${[...new Set(items.flatMap(f=>f.sensitivity_levels))].join(', ')}.`));
  detail.append(element('p', '', `Replacement: ${$('replacementStyle').value === 'x' ? '[X]' : first.replacement}`));
  for (const reason of new Set(items.map(f=>f.signal_reason).filter(Boolean))) detail.append(element('p', '', reason));
  detail.append(element('p', '', `Layout: ${[...new Set(items.map(f=>f.layout_label || 'not identified'))].join(', ')}. Confidence: not calibrated.`));
  const confidence = items.map(f=>f.detection_confidence).filter(c=>c!==null && c!==undefined);
  if (confidence.length) detail.append(element('p', '', `Detector scores: ${confidence.map(c=>c.toFixed(2)).join(', ')}`));
  if (first.context_reason) detail.append(element('p', '', first.context_reason));
  card.append(detail);
  return card;
}
function renderFindings() {
  const q=review?.quality_check;
  $('contextSuggestion').textContent=q?.suggested_goal ? `Document purpose: ${q.suggested_goal}` : '';
  renderReferences();
  const findings = review?.findings || [];
  const count = findings.filter(f => f.selected).length;
  $('total').textContent = findings.length;
  $('selectedCount').textContent = `${count} selected · ${findings.length - count} kept · ${findings.filter(f=>f.review_status === 'unreviewed').length} unreviewed`;
  document.querySelectorAll('.finding-group').forEach(node=>groupState.set(node.dataset.groupKey, node.open));
  $('findings').replaceChildren();
  const search = $('search').value.toLocaleLowerCase();
  const filter = $('filter').value;
  const visible = findings.filter(f => `${f.original_text} ${f.field_type} ${f.reason} ${f.excerpt_before || ''} ${f.excerpt_after || ''}`.toLocaleLowerCase().includes(search))
    .filter(f => filter === 'all' || filter === `signal:${f.review_signal}` || (filter === 'selected' && f.selected) || (filter === 'kept' && !f.selected) || (filter === 'date-backup' && f.detector === 'date-rule') || f.sensitivity_levels.includes(filter));
  const mode = $('groupBy').value;
  $('groupHint').textContent = mode === 'priority'
    ? 'Priority is a review order based on field type, not a confidence score or legal decision.'
    : 'Repeated values share a card. Changing a value changes all equivalent mentions in the document.';
  if (!visible.length) $('findings').append(element('p', 'list-empty', review?.analysed ? 'No matching findings. Check the document for anything the detector missed.' : 'Categories and their counts will appear after detection.'));
  for (const group of ReviewGroups.group(visible, mode)) {
    const section = element('details', 'finding-group');
    const stateKey = `${mode}:${group.key}`;
    section.dataset.groupKey = stateKey;
    section.open = groupState.get(stateKey) ?? false;
    section.ontoggle = () => groupState.set(stateKey, section.open);
    const remaining = group.findings.filter(f=>f.review_status === 'unreviewed').length;
    section.append(element('summary', '', `${group.label} · ${group.entities.size} values / ${group.findings.length} mentions · ${remaining} unreviewed`));
    const actions = element('div', 'group-actions');
    for (const [label, selected] of [['Remove visible group', true], ['Keep visible group', false]]) {
      const button = element('button', 'quiet', label); button.disabled = busy;
      button.onclick = () => changeSelection(group.findings, selected); actions.append(button);
    }
    section.append(actions);
    for (const items of group.entities.values()) section.append(findingCard(items));
    $('findings').append(section);
  }
}

$('file').onchange = event => { if (event.target.files[0]) openFile(event.target.files[0]); event.target.value = ''; };
$('emptyOpen').onclick = () => $('file').click();
$('demo').onclick = async () => {
  try { const response = await request('/api/demo'); await openFile(new File([await response.blob()], 'TEST_legal_demo.pdf', {type:'application/pdf'})); }
  catch (error) { status(error.message, 'error'); }
};
$('analyse').onclick = async () => {
  if (review?.analysed && !confirm('Run detection again? This resets your selections.')) return;
  await task(async () => {
    status('Running document layout, language detection and privacy screening, followed by the quality check… The first run can take a few minutes.', 'busy');
    const context = screeningContext();
    review = await (await request(`/api/documents/${review.document_id}/analyse`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(context)})).json();
    focused = null; renderFindings(); renderOverlays();
    document.dispatchEvent(new Event('lexmini:pages'));
    document.querySelector('.context').open = false;
    status(`Found ${review.findings.length} candidates. Review the highlights and deselect anything to keep.`);
  });
};
for (const id of ['search','filter','groupBy']) $(id).addEventListener('input', renderFindings);
for (const [id,selected] of [['selectAll',true],['keepAll',false]]) $(id).onclick = () => {
  if (busy || !review) return;
  for (const f of review.findings) { f.selected = selected; f.review_status = selected ? 'confirmed_remove' : 'confirmed_keep'; }
  renderFindings(); renderOverlays();
};
for (const format of ['pdf','text']) $(format).onclick = () => task(async () => {
  await ensureSession();
  status('Preparing the reviewed download…', 'busy');
    const payload = {selected_ids:review.findings.filter(f=>f.selected).map(f=>f.finding_id), revision:review.revision, format,
      replacement_style:$('replacementStyle').value, pdf_layout:$('pdfLayout').value};
  const response = await request(`/api/documents/${review.document_id}/export`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  saveDownload(await response.blob(), downloadName(format==='pdf'?'pdf':'txt'));
  status('Download ready. Check the result before sharing.');
});
$('keys').onclick = () => task(async () => {
  await ensureSession();
  const response = await request(`/api/documents/${review.document_id}/keys`);
  saveDownload(new Blob([JSON.stringify(await response.json(), null, 2)], {type:'application/json'}), downloadName('json'));
  status('Private key map downloaded. Keep it separate from the document you share.');
});
$('pdfLayout').onchange = () => {
  $('layoutNote').textContent = $('pdfLayout').value === 'original'
    ? 'PDF: original layout, colour-coded redactions, flattened pages. Replacement choice applies to text download.'
    : 'Token PDF: new text layout. Repeated values share a token. Keys stay separate.';
};
$('replacementStyle').onchange = renderFindings;
$('close').onclick = () => task(async () => {
  await request(`/api/documents/${review.document_id}`, {method:'DELETE'});
  review = null; sourceFile = null; focused = null; $('pages').replaceChildren(); $('empty').hidden = false; $('warnings').hidden = true;
  $('filename').textContent = 'No document open'; $('fileDetails').textContent = 'PDF documents · up to 40 pages';
  renderFindings(); status('Document closed and removed from local memory.');
});
request('/health').then(() => { $('connection').textContent = 'Local service connected'; $('connection').classList.add('online'); })
  .catch(() => { $('connection').textContent = 'Local service offline'; status('Start the Lexmini local service, then reload this page.', 'error'); });
request('/api/samples').then(r=>r.json()).then(items => {
  for (const item of items) {
    const option = document.createElement('option'); option.value = item.id;
    option.textContent = `${item.language.toUpperCase()} · ${item.title} · ${item.pages} pages`;
    option.dataset.kind = item.kind; $('samples').append(option);
  }
}).catch(()=>{});
$('samples').onchange = async () => {
  const selected = $('samples').selectedOptions[0];
  if (!selected.value) return;
  try {
    const response = await request('/api/samples/' + encodeURIComponent(selected.value));
    await openFile(new File([await response.blob()], selected.value + '.pdf', {type:'application/pdf'}));
    if (review) status(`${selected.dataset.kind}. Run screening to find private information.`);
  } catch(error) { status(error.message, 'error'); }
  $('samples').value = '';
};

request('/api/quality').then(r=>r.json()).then(items => {
  for (const item of items) {
    const option = document.createElement('option'); option.value = item.id;
    option.textContent = `${item.title} · ${item.pages} pages`;
    $('qualitySamples').append(option);
  }
  const sample = new URLSearchParams(location.search).get('quality');
  if (sample && items.some(item=>item.id===sample)) {
    $('qualitySamples').value = sample;
    $('qualitySamples').dispatchEvent(new Event('change'));
  }
}).catch(()=>{});
$('qualitySamples').onchange = async () => {
  const id = $('qualitySamples').value;
  if (!id) return;
  if (review && !confirm('Load this cached public example? This discards your current review.')) { $('qualitySamples').value = ''; return; }
  await task(async () => {
    const context = screeningContext();
    const next = await (await request('/api/quality/' + encodeURIComponent(id), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(context)})).json();
    if (review) await request(`/api/documents/${review.document_id}`, {method:'DELETE'}).catch(()=>{});
    sourceFile = await (await request(`/api/documents/${next.document_id}/source`)).blob();
    review = next; focused = null; groupState.clear();
    $('documentLanguage').value = review.languages.join(',');
    $('filename').textContent = review.filename;
    $('fileDetails').textContent = `${review.page_count} pages`;
    $('empty').hidden = true; $('warnings').replaceChildren();
    for (const message of review.warnings) $('warnings').append(element('p', '', message));
    $('warnings').hidden = !review.warnings.length;
    renderPages(); renderFindings(); document.querySelector('.context').open = false;
    status(`${review.findings.length} findings ready to review.`);
  });
  $('qualitySamples').value = '';
};
$('addExample').onclick = () => {
  const text = $('manualTerm').value.trim();
  if (text.length < 2) { status('Copy at least two characters from the document.', 'error'); return; }
  const levels = $('manualLevel').value === 'both' ? ['personal-private','professional-secrecy'] : [$('manualLevel').value];
  learnExample({text,field_type:$('manualType').value,sensitivity_levels:levels});
};
$('memoryScope').onchange = renderFindings;
$('approveExample').onclick = () => {
  const text = $('manualTerm').value.trim();
  if (text.length < 2) { status('Select or enter at least two characters.', 'error'); return; }
  const levels = $('manualLevel').value === 'both' ? ['personal-private','professional-secrecy'] : [$('manualLevel').value];
  learnExample({text, field_type:$('manualType').value, sensitivity_levels:levels}, true);
};
$('colourBy').onchange = () => { document.body.dataset.colour = $('colourBy').value; renderOverlays(); };

// Keep the source only in this tab so a service restart cannot discard review work.
async function ensureSession() {
  try { await request(`/api/documents/${review.document_id}`); return; }
  catch(error) { if(error.status !== 404) throw error; }
  if (!sourceFile) throw new Error('This older tab has no recovery copy. Reopen the PDF or cached sample.');
  status('Restoring this review after the service restarted or the session expired…', 'busy');
  const old = review;
  const fresh = await (await request('/api/documents?filename='+encodeURIComponent(old.filename), {
    method:'POST', headers:{'Content-Type':'application/pdf'}, body:sourceFile})).json();
  review = await (await request(`/api/documents/${fresh.document_id}/restore`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({findings:old.findings, context:screeningContext()})})).json();
  focused=null; renderPages();renderFindings();
}
function downloadName(extension) {
  const name=(review?.filename || 'document.pdf').replace(/\\/g,'/').split('/').pop();
  const stem=name.replace(/\.pdf$/i,'').replace(/[\x00-\x1f\x7f<>:"/\\|?*]/g,'_').replace(/^[ .]+|[ .]+$/g,'') || 'document';
  return `lexmini_${stem.slice(0,180)}.${extension}`;
}
function saveDownload(blob, filename) {
  const url=URL.createObjectURL(blob), link=document.createElement('a');
  link.href=url;link.download=filename;link.hidden=true;document.body.append(link);
  link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
}

$('qualityCheck').onclick=()=>task(async()=>{
  await ensureSession();
  status('OpenAI is checking document text and findings in bounded batches. This can take a few minutes…','busy');
  review=await(await request(`/api/documents/${review.document_id}/quality`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:review.revision,decisions:review.findings.filter(f=>f.review_status!=='unreviewed').map(f=>({finding_id:f.finding_id,selected:f.selected,review_status:f.review_status}))})})).json();
  focused=null;renderFindings();renderOverlays();
  const q=review.quality_check;
  $('contextSuggestion').textContent=`Suggested role: ${q.suggested_role}. Suggested goal: ${q.suggested_goal}`;

  status(`OpenAI quality check: ${q.changed} changes, ${q.added} new candidates, ${q.protected} protected decisions left unchanged. Review the result.`);
});

function renderReferences() {
  const container=$('legalReferences');container.replaceChildren();
  const refs=(review?.findings || []).filter(f=>f.field_type==='case_reference');
  $('referenceSummary').textContent=`Legal references · ${refs.length} mentions`;
  for(const f of refs) {
    const row=element('div','reference-row');
    const jump=element('button','quiet',`${f.original_text} · page ${f.location.page_number}`);
    jump.onclick=()=>focusFinding(f);row.append(jump);
    row.append(element('small','',f.legal_reference?.status || 'Unresolved reference'));
    if(f.legal_reference?.url) {
      const link=element('a','','Open source search');link.href=f.legal_reference.url;link.target='_blank';link.rel='noopener noreferrer';row.append(link);
    }
    container.append(row);
  }
}

$('manualType').addEventListener('change',updateControls);
let activeShare=null;
$('issueShare').onclick=()=>task(async()=>{
  await ensureSession();
  const value=review.findings.find(f=>f.finding_id===focused);
  if($('shareReveal').checked&&!value)throw Error('Click a finding to choose the value to reveal.');
  const normal=equivalentKey;
  const reveal=$('shareReveal').checked?review.findings.filter(f=>normal(f.original_text)===normal(value.original_text)).map(f=>f.finding_id):[];
  activeShare=await(await request(`/api/documents/${review.document_id}/share`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:review.revision,recipient:$('shareRecipient').value,selected_ids:review.findings.filter(f=>f.selected).map(f=>f.finding_id),reveal_ids:reveal,expires_in:60})})).json();
  activeShare.documentId=review.document_id;
  $('shareLink').href=API+activeShare.url;$('shareLink').hidden=false;$('revokeShare').disabled=false;
  $('shareStatus').textContent='Recipient copy issued for 60 seconds. Earlier access for this recipient was revoked. Each download checks the permission again.';
});
$('revokeShare').onclick=()=>task(async()=>{
  if(!activeShare)return;
  await request(`/api/documents/${activeShare.documentId}/share/${activeShare.token}/revoke`,{method:'POST'});
  $('shareStatus').textContent='Access revoked. Future downloads are denied; earlier downloaded copies cannot be recalled.';
  $('revokeShare').disabled=true;
});
