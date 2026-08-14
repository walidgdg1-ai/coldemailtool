#!/usr/bin/env python3
import argparse,json,hashlib
from pathlib import Path
import duckdb
from spm_deep_core import build
from spm_deep_score import run

def main():
    p=argparse.ArgumentParser();p.add_argument('--core',required=True);p.add_argument('--out',required=True);a=p.parse_args();core=Path(a.core);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    q=json.loads((core/'data_quality.json').read_text());assert q.get('status')=='PASS',q
    con=duckdb.connect();con.execute("SET preserve_insertion_order=false");con.execute("SET threads=4");con.execute("SET memory_limit='7GB'");(out/'ducktmp').mkdir(exist_ok=True);con.execute(f"SET temp_directory='{(out/'ducktmp').as_posix()}'");con.execute("SET max_temp_directory_size='24GB'")
    ctx=build(con,core,out,Path(__file__).with_name('spm_taxonomy_rules.json'));run(con,core,out,ctx,q)
    manifest={'files':{}}
    for x in out.iterdir():
        if x.is_file() and x.name!='run_manifest.json':manifest['files'][x.name]={'bytes':x.stat().st_size,'sha256':hashlib.sha256(x.read_bytes()).hexdigest()}
    (out/'run_manifest.json').write_text(json.dumps(manifest,indent=2))
    print('DERIVED_FILE_COUNT',len(manifest['files']))
if __name__=='__main__':main()
