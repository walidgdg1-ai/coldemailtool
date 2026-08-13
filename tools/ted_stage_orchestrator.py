#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, os, pathlib, shutil, subprocess, sys
from datetime import datetime, timezone

VERSION='TED_CANONICAL_STAGE_V1'
MONTHS=[f'monthly-{y}-{m:02d}' for y in range(2023,2027) for m in range(1,13) if (y,m)>=(2023,8) and (y,m)<=(2026,7)]
DAILIES=[f'daily-2026-{n:05d}' for n in range(147,156)]
KEYS=MONTHS+DAILIES


def sh(cmd:list[str],check=True,capture=False):
    print('+',' '.join(cmd),flush=True)
    return subprocess.run(cmd,check=check,text=True,capture_output=capture)

def sha256(p:pathlib.Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def load_checkpoint(path:pathlib.Path):
    if not path.exists():
        return {'version':VERSION,'completed':{},'status':'IN_PROGRESS','created_at':datetime.now(timezone.utc).isoformat()}
    q=json.loads(path.read_text(encoding='utf-8'))
    if q.get('version')!=VERSION:raise RuntimeError(f'checkpoint version mismatch: {q.get("version")}')
    return q

def package_asset(key:str)->str:
    return f'ted-{key}.package.gz'

def upload(tag:str,*paths:pathlib.Path):
    for p in paths:sh(['gh','release','upload',tag,str(p),'--clobber'])

def run(args):
    work=pathlib.Path(args.work);work.mkdir(parents=True,exist_ok=True)
    cp_path=work/'ted-stage-checkpoint.json';cp=load_checkpoint(pathlib.Path(args.checkpoint) if args.checkpoint else cp_path)
    if args.checkpoint and pathlib.Path(args.checkpoint).exists() and pathlib.Path(args.checkpoint)!=cp_path:
        cp_path.write_text(json.dumps(cp,indent=2),encoding='utf-8')
    for key in KEYS:
        if key in cp.get('completed',{}):
            print('TED_STAGE_SKIP',key,cp['completed'][key].get('canonical_tenders'),flush=True);continue
        package=work/package_asset(key)
        stage_dir=work/f'stage-{key}'
        shutil.rmtree(stage_dir,ignore_errors=True);stage_dir.mkdir(parents=True)
        package.unlink(missing_ok=True)
        sh(['gh','release','download',args.raw_release,'--pattern',package.name,'--dir',str(work),'--clobber'])
        sh([sys.executable,args.normalizer,'--package',str(package),'--out',str(stage_dir)])
        q=json.loads((stage_dir/'data_quality.json').read_text(encoding='utf-8'))
        if not all(q.get('integrity',{}).values()):raise RuntimeError(f'{key}: integrity failure {q.get("integrity")}')
        if q.get('source_stats',{}).get('parse_errors',0)/max(q.get('source_stats',{}).get('raw_xml',1),1)>=0.01:
            raise RuntimeError(f'{key}: parse error rate too high {q}')
        outputs=[]
        for base in ('historical_tenders.csv.gz','awards.csv.gz','award_suppliers.csv.gz','data_quality.json'):
            src=stage_dir/base
            if not src.exists():raise RuntimeError(f'{key}: missing stage output {base}')
            suffix=base
            dst=work/f'ted-stage-{key}.{suffix}'
            dst.unlink(missing_ok=True);src.replace(dst);outputs.append(dst)
        manifest={
            'version':VERSION,'key':key,'raw_release':args.raw_release,'raw_asset':package.name,
            'canonical_tenders':q.get('canonical_tenders',0),'canonical_awards':q.get('canonical_awards',0),
            'award_supplier_links':q.get('award_supplier_links',0),'source_stats':q.get('source_stats',{}),
            'award_value_coverage_pct':q.get('award_value_coverage_pct'),'bidder_count_coverage_pct':q.get('bidder_count_coverage_pct'),
            'integrity':q.get('integrity',{}),'files':{},'created_at':datetime.now(timezone.utc).isoformat(),'status':'COMPLETE'
        }
        for p in outputs:manifest['files'][p.name]={'bytes':p.stat().st_size,'sha256':sha256(p)}
        mp=work/f'ted-stage-{key}.manifest.json';mp.write_text(json.dumps(manifest,indent=2),encoding='utf-8');outputs.append(mp)
        upload(args.stage_release,*outputs)
        cp.setdefault('completed',{})[key]={'canonical_tenders':manifest['canonical_tenders'],'canonical_awards':manifest['canonical_awards'],'award_supplier_links':manifest['award_supplier_links'],'raw_xml':manifest['source_stats'].get('raw_xml',0),'manifest':mp.name}
        cp['completed_packages']=len(cp['completed']);cp['expected_packages']=len(KEYS);cp['stage_tender_row_sum']=sum(int(x['canonical_tenders']) for x in cp['completed'].values());cp['stage_award_row_sum']=sum(int(x['canonical_awards']) for x in cp['completed'].values());cp['stage_bridge_row_sum']=sum(int(x['award_supplier_links']) for x in cp['completed'].values());cp['raw_xml_sum']=sum(int(x['raw_xml']) for x in cp['completed'].values());cp['last_completed']=key;cp['updated_at']=datetime.now(timezone.utc).isoformat();cp['status']='IN_PROGRESS';cp_path.write_text(json.dumps(cp,indent=2),encoding='utf-8');upload(args.stage_release,cp_path)
        print('TED_STAGE_COMMITTED',key,'tenders',manifest['canonical_tenders'],'awards',manifest['canonical_awards'],'bridges',manifest['award_supplier_links'],'raw_xml_sum',cp['raw_xml_sum'],flush=True)
        package.unlink(missing_ok=True);shutil.rmtree(stage_dir,ignore_errors=True)
        for p in outputs:p.unlink(missing_ok=True)
    cp['status']='STAGE_COMPLETE';cp['updated_at']=datetime.now(timezone.utc).isoformat();cp_path.write_text(json.dumps(cp,indent=2),encoding='utf-8');summary=work/'ted-stage-summary.json';summary.write_text(json.dumps(cp,indent=2),encoding='utf-8');upload(args.stage_release,cp_path,summary)
    if cp['completed_packages']!=len(KEYS):raise RuntimeError('stage package count mismatch')
    print('TED_STAGE_COMPLETE',json.dumps({k:cp[k] for k in ('completed_packages','raw_xml_sum','stage_tender_row_sum','stage_award_row_sum','stage_bridge_row_sum')}),flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--raw-release',default='tender-raw-ted-official-bulk-v1');ap.add_argument('--stage-release',required=True);ap.add_argument('--normalizer',default='tools/tender_normalize_ted_bulk.py');ap.add_argument('--work',default='ted_stage_work');ap.add_argument('--checkpoint');run(ap.parse_args())
if __name__=='__main__':main()
