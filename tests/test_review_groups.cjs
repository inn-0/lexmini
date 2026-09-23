// tests/test_review_groups.cjs
// Review grouping must preserve every occurrence and never change selections.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const sandbox = {module:{exports:{}}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../extension/review-groups.js'),'utf8'), sandbox);
const {group} = sandbox.module.exports;
const findings = [
  {finding_id:'a', entity_id:'date1',field_type:'date',original_text:'21 février 2008',sensitivity_levels:['personal-private'],selected:true},
  {finding_id:'b', entity_id:'person1',field_type:'person_name',original_text:'Alice',sensitivity_levels:['personal-private'],selected:true},
  {finding_id:'c', entity_id:'date1',field_type:'date',original_text:'21 février 2008',sensitivity_levels:['personal-private'],selected:false},
  {finding_id:'d', entity_id:'secret1',field_type:'credential',original_text:'example',sensitivity_levels:['professional-secrecy'],selected:true},
];
const before = JSON.stringify(findings);
const dates = group(findings).find(g=>g.label==='Dates');
assert.equal(dates.entities.size,1);
assert.equal(dates.findings.length,2);
assert.equal(group(findings,'priority')[0].findings[0].field_type,'credential');
for (const mode of ['category','priority','sensitivity']) {
  assert.equal(JSON.stringify(group(findings,mode).flatMap(g=>g.findings.map(f=>f.finding_id)).sort()), JSON.stringify(['a','b','c','d']));
}
assert.equal(JSON.stringify(findings),before);
console.log('Grouping checks passed');
