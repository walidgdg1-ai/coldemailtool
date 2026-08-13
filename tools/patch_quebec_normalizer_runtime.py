#!/usr/bin/env python3
from pathlib import Path
p=Path('tools/tender_normalize_quebec.py')
s=p.read_text(encoding='utf-8')
old1="for rr in c.execute('SELECT * FROM tender ORDER BY release_date'):"
new1="for rr in con.execute('SELECT * FROM tender ORDER BY release_date'):"
old2="for rr in c.execute('SELECT * FROM award ORDER BY release_date'):"
new2="for rr in con.execute('SELECT * FROM award ORDER BY release_date'):"
if old1 not in s or old2 not in s:
    raise SystemExit('expected SQLite iteration blocks not found')
s=s.replace(old1,new1).replace(old2,new2)
p.write_text(s,encoding='utf-8')
print('Quebec SQLite cursor isolation patch applied')
