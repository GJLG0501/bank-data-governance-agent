"""Create a reviewable comparison from Git-ignored raw experimental runs."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from statistics import mean, median
import unicodedata

from scripts import new_bank_documents as docs
from scripts import new_bank_runtime_validation as runtime
from scripts.evaluate_steward_reasoning import CASES


ROOT=runtime.ROOT
LOCAL=runtime.LOCAL
OUT=ROOT/'docs/new-bank-data-steward-reasoning-validation.json'


def load(name):
    return json.loads((LOCAL/name).read_text(encoding='utf-8'))


def key(row):
    return row['condition'],row['group'],row['id']


def main():
    first=load('reasoning-comparison-20261022.json')
    final=load('reasoning-comparison-final-sanitized-bc-20261022.json')
    original_extra=load('reasoning-original-extra-20261022.json')
    rows=([row for row in first['rows'] if row['condition']=='A']+
          [row for row in original_extra['rows'] if row['condition']=='A']+final['rows'])
    if len(rows)!=186 or len({key(row) for row in rows})!=186:
        raise ValueError('Expected 62 paired cases for each of A/B/C')
    # Regrade the one false positive found during qualitative review. The
    # initial three-keyword test accepted unrelated mentions of May/April.
    case=next(case for case in CASES['reasoning'] if case['id']=='may_continuity')
    for row in rows:
        if row['id']!='may_continuity':
            continue
        answer=''.join(ch for ch in unicodedata.normalize('NFKD',row.get('answer','').casefold())
                       if not unicodedata.combining(ch))
        revised=bool(re.search(case['patterns'][0],answer)) and row['passed']
        if revised!=row['passed']:
            row['passed']=revised
            row['grading_revision']='Require an explicit May opening = April closing relation.'
    by_key={key(row):row for row in rows}
    source=docs.load_catalog()
    summary={}
    for condition in 'ABC':
        part=[row for row in rows if row['condition']==condition]
        times=sorted(row['elapsed_seconds'] for row in part)
        summary[condition]={
            'passed':sum(row['passed'] for row in part),'total':len(part),
            'groups':{group:{'passed':sum(row['passed'] for row in part if row['group']==group),
                              'total':sum(row['group']==group for row in part)}
                      for group in ('original','hardening','reasoning','temporal_followup','security')},
            'median_seconds':round(median(times),3),'mean_seconds':round(mean(times),3),
            'p95_seconds':round(times[int(len(times)*.95)],3),
            'model_calls':sum(row.get('model_calls',0) for row in part),
            'tool_calls':sum(row.get('tool_calls',0) for row in part),
            'retrieved_documents':sum(row.get('retrieved_count',0) for row in part),
            'retrieved_content_chars':sum(row.get('evidence_chars',0) for row in part),
            'model_input_chars':sum(row.get('model_input_chars',0) for row in part),
            'status_counts':dict(Counter(row.get('status','error') for row in part)),
        }
    searches_equal={condition:sum(by_key[(condition,row['group'],row['id'])]['searches']==row['searches']
                                  for row in rows if row['condition']=='A')
                    for condition in 'BC'}
    repeats=[final['rows'],load('reasoning-stability-1.json')['rows'],
             load('reasoning-stability-2.json')['rows']]
    repeated_keys={key(row) for row in repeats[1]}
    stability=[]
    for identity in sorted(repeated_keys):
        outcomes=[next(row['passed'] for row in run if key(row)==identity) for run in repeats]
        stability.append({'condition':identity[0],'group':identity[1],'id':identity[2],
                          'passes':outcomes})
    strict={condition:by_key[(condition,'temporal_followup','march_to_april')]['trace']
            for condition in 'ABC'}
    conservation=load('reasoning-conservation-20261022.json')
    data={'format':'steward-reasoning-evaluation-v1',
          'created_utc':datetime.now(timezone.utc).isoformat(),
          'data_model':'new_bank_2026','default_data_model':'legacy_metadata',
          'generative_model':first['model'],
          'conditions':{'A':'extractive + published corpus',
                        'B':'grounded_generation_experimental + published corpus',
                        'C':'grounded_generation_experimental + published corpus + temporary conceptual context'},
          'catalog':{'entries':len(source['entries']),
                     'claims':sum(len(entry['claims']) for entry in source['entries'].values()),
                     'kinds':dict(Counter(entry['kind'] for entry in source['entries'].values())),
                     'published_corpus_documents':82},
          'summary':summary,'identical_search_sequences_vs_A':searches_equal,
          'stability':{'repeated_cases':len(stability),
                       'identical_outcome_cases':sum(len(set(row['passes']))==1 for row in stability),
                       'cases':stability},
          'conservation':conservation,
          'strict_temporal_trace':strict,
          'raw_local_files':['.local-validation/reasoning-comparison-20261022.json',
                             '.local-validation/reasoning-comparison-final-sanitized-bc-20261022.json',
                             '.local-validation/reasoning-original-extra-20261022.json',
                             '.local-validation/reasoning-stability-1.json',
                             '.local-validation/reasoning-stability-2.json'],
          'results':[{k:row.get(k) for k in ('condition','group','id','question','turns','passed',
              'status','answer','diagnostic','grading_revision','error','refs','tool_calls','model_calls',
              'model_input_chars','evidence_chars','retrieved_count','elapsed_seconds',
              'searches','drafts') if k in row} for row in rows]}
    OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'summary':summary,'searches_equal':searches_equal,
                      'stable':data['stability']['identical_outcome_cases'],'out':str(OUT)},ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
