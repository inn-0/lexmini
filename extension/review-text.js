// extension/review-text.js
// Select exact source characters; selection alone never saves or approves a term.
'use strict';
let textObserver = null;
let selectedDraft = null;
let layerGeneration = 0;

function documentTextMode() {
  document.body.dataset.documentMode = $('documentMode').value;
}
$('documentMode').onchange = documentTextMode;
documentTextMode();

document.addEventListener('lexmini:pages', () => {
  const generation = ++layerGeneration;
  textObserver?.disconnect();
  selectedDraft = null; $('selectionNotice').hidden = true;
  const documentId = review?.document_id;
  document.querySelectorAll('.text-layer,.layout-layer,.raw-debug').forEach(node=>node.remove());
  if (!documentId) return;
  textObserver = new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) {
      textObserver.unobserve(entry.target);
      addTextLayer(entry.target, documentId, generation).catch(error=>status(error.message, 'error'));
    }
  }, {root:$('documentScroll'), rootMargin:'500px'});
  document.querySelectorAll('.page').forEach(page=>textObserver.observe(page));
});

async function addTextLayer(page, documentId, generation) {
  const number = Number(page.dataset.page);
  const data = await (await request(`/api/documents/${documentId}/pages/${number}/text`)).json();
  if (review?.document_id !== documentId || !page.isConnected || generation !== layerGeneration) return;
  const info = review.pages[number-1];
  const layer = element('div', 'text-layer');
  layer.dataset.page = number; layer.sourceText = Array.from(data.text);
  const fragment = document.createDocumentFragment();
  layer.sourceText.forEach((character, index) => {
    const span = element('span', 'source-char', character);
    span.dataset.index = index;
    const box = data.boxes[index];
    if (box) {
      const [x0,y0,x1,y1] = box;
      span.style.left = `${100*x0/info.width}%`; span.style.top = `${100*y0/info.height}%`;
      span.style.width = `${100*(x1-x0)/info.width}%`; span.style.height = `${100*(y1-y0)/info.height}%`;
      span.style.fontSize = `${100*(y1-y0)/info.width}cqw`;
    } else span.classList.add('source-break');
    fragment.append(span);
  });
  layer.append(fragment); page.append(layer);
  const layoutLayer = element('div', 'layout-layer');
  for (const region of data.regions) {
    const box = element('div', 'layout-region');
    const [x0,y0,x1,y1] = region.box;
    box.style.left = `${100*x0/info.width}%`; box.style.top = `${100*y0/info.height}%`;
    box.style.width = `${100*(x1-x0)/info.width}%`; box.style.height = `${100*(y1-y0)/info.height}%`;
    box.append(element('span', '', region.label)); layoutLayer.append(box);
  }
  page.append(layoutLayer);
  const debug = element('details', 'raw-debug');
  debug.append(element('summary', '', `Page ${number} - exact text and ${data.regions.length} Docling regions`));
  const raw = element('pre', 'raw-text', data.text); raw.dataset.page = number; raw.sourceText = Array.from(data.text);
  debug.append(raw);
  const grouped=element('details','paragraph-debug');
  grouped.append(element('summary','',`Paragraph detection input (${(data.paragraphs || []).length} blocks)`));
  for (const paragraph of data.paragraphs || []) {
    grouped.append(element('p','',`${paragraph.source} · ${paragraph.label}`), element('pre','paragraph-text',paragraph.text));
  }
  debug.append(grouped);page.parentElement.append(debug);
}

document.addEventListener('selectionchange', () => {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !selection.rangeCount) return;
  const range = selection.getRangeAt(0);
  const start = range.startContainer.parentElement;
  const end = range.endContainer.parentElement;
  const layer = start?.closest('.text-layer,.raw-text');
  if (!layer || layer !== end?.closest('.text-layer,.raw-text')) return;
  const codepointOffset = (node, offset) => Array.from(node.textContent.slice(0, offset)).length;
  const a = Number(start.dataset.index || 0) + codepointOffset(range.startContainer, range.startOffset);
  const b = Number(end.dataset.index || 0) + codepointOffset(range.endContainer, range.endOffset);
  const text = layer.sourceText.slice(a,b).join('').trim();
  if (!text) return;
  selectedDraft = {text, page:Number(layer.dataset.page)};
  $('selectedTextLabel').textContent = `Page ${selectedDraft.page}: ${text.length > 100 ? text.slice(0,100)+'…' : text}`;
  $('selectionNotice').hidden = false;
  $('useSelection').disabled = text.length < 2 || text.length > 200;
});
$('useSelection').onclick = () => {
  if (!selectedDraft || busy) return;
  $('manualTerm').value = selectedDraft.text;
  document.querySelector('.learning').open = true;
  $('manualTerm').focus();
  status('Selected text copied to the review form. Apply it here, or explicitly save it as an approved term.');
};
