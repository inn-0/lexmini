// extension/review-groups.js
// Group review candidates without changing their selections or detector scores.
'use strict';
const ReviewGroups = (() => {
  const categories = [
    ['credentials', 'Passwords and access', ['credential']],
    ['names', 'People and companies', ['person_name', 'organisation_name']],
    ['contact', 'Contact and identifiers', ['address', 'email', 'phone', 'personal_identifier', 'private_url']],
    ['dates', 'Dates', ['date', 'birth_date']],
    ['money', 'Money and accounts', ['amount', 'account_number']],
    ['topics', 'Confidential topics', ['medical_information', 'belief', 'criminal_record', 'legal_content', 'business_secret', 'confidential_term']],
    ['references', 'Legal references', ['case_reference']],
    ['other', 'Other information', []],
  ];
  function category(f) { return categories.find(c => c[2].includes(f.field_type)) || categories.at(-1); }
  function priority(f) {
    if (['credential','medical_information','belief','criminal_record','business_secret','confidential_term'].includes(f.field_type)) return ['1', '1. Review first - secrets and sensitive topics'];
    if (['date','amount','case_reference','legal_content','firm_record'].includes(f.field_type)) return ['3', '3. Check context - dates, amounts and case details'];
    return ['2', '2. Review identities and contact details'];
  }
  function tier(f) {
    if (f.sensitivity_levels.length > 1) return ['0', 'Personal-private + professional-secrecy'];
    const level = f.sensitivity_levels[0];
    return [level === 'professional-secrecy' ? '1' : level === 'personal-private' ? '2' : '3', level];
  }
  function group(findings, mode = 'category') {
    const groups = new Map();
    for (const f of findings) {
      const cat = category(f);
      const signals = {priority:['0','▲ Review first'],approved:['1','■ Approved terms'],candidate:['2','● Candidates'],weak:['3','◇ Weak / layout']};
      const parent = mode === 'signal' ? signals[f.review_signal || 'candidate'] : mode === 'priority' ? priority(f) : mode === 'sensitivity' ? tier(f) : ['', ''];
      const order = categories.indexOf(cat);
      const key = `${parent[0]}:${order}`;
      if (!groups.has(key)) groups.set(key, {key, label: parent[1] ? `${parent[1]} / ${cat[1]}` : cat[1], findings: [], entities: new Map()});
      const g = groups.get(key); g.findings.push(f);
      const entity = f.entity_id || `${f.field_type}:${f.original_text.toLocaleLowerCase()}`;
      if (!g.entities.has(entity)) g.entities.set(entity, []);
      g.entities.get(entity).push(f);
    }
    return [...groups.values()].sort((a,b) => a.key.localeCompare(b.key));
  }
  return {group, category, priority};
})();
if (typeof module !== 'undefined') module.exports = ReviewGroups;
