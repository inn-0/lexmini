// extension/governance-guide.js
// Enlarge real SVG dimensions so the full diagram remains scrollable.
document.body.classList.add('guide');
const nav=document.createElement('nav');
nav.className='guide-nav';nav.setAttribute('aria-label','Guide sections');
const brand=document.createElement('a');
brand.className='guide-brand';brand.href='#';brand.setAttribute('aria-label','Lexmini - back to top');
brand.innerHTML='<span class="guide-mark" aria-hidden="true">L</span><strong>lexmini</strong>';
brand.onclick=event=>{event.preventDefault();window.scrollTo({top:0});};
nav.append(brand);

const labels=['Use case','Review process','Three tiers','Approved labels','Controlled reveal','Governance','Processing','Challenge'];
const headings=[...document.querySelectorAll('h2')];
headings.forEach((heading,index)=>{
  const link=document.createElement('a');
  link.href=`#${heading.id}`;link.textContent=labels[index] || heading.textContent;
  nav.append(link);
});
document.body.prepend(nav);
new ResizeObserver(()=>{
  document.documentElement.style.setProperty('--guide-nav-height',`${nav.getBoundingClientRect().height+20}px`);
}).observe(nav);
document.querySelectorAll('figure svg:not(svg svg)').forEach(svg=>{
  const frame=document.createElement('div');frame.className='diagram-frame';frame.tabIndex=0;
  svg.parentNode.insertBefore(frame,svg);frame.append(svg);
  const base=svg.viewBox.baseVal.width || 1000;let zoom=1;
  const controls=document.createElement('div');controls.className='diagram-controls';
  for(const [label,factor] of [['Fit',0],['Zoom in',1.3],['Zoom out',1/1.3]]){
    const button=document.createElement('button');button.textContent=label;
    button.onclick=()=>{zoom=factor ? Math.min(4,Math.max(.3,zoom*factor)) : Math.min(1,(frame.clientWidth-24)/base);svg.style.width=`${base*zoom}px`;svg.style.height='auto';};controls.append(button);
  }
  frame.before(controls);controls.firstChild.click();
});
