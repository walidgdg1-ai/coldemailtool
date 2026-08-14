#!/usr/bin/env python3
from pathlib import Path

p=Path('tools/build_spm_deep_intelligence_v1.py')
s=p.read_text(encoding='utf-8')

start=s.find("    # Native-currency value bands. We aggregate dimensionless within-currency shares, never monetary sums across currencies.\n")
if start<0:
    raise SystemExit('VALUE_FIT_START_NOT_FOUND')
# After the general runtime patch, detailed pricing starts at price_pairs.
end=s.find('    price_pairs=con.execute(',start)
if end<0:
    # Fallback for the unpatched source form.
    end=s.find('    con.execute(f"""COPY (',start)
if end<0:
    raise SystemExit('VALUE_FIT_END_NOT_FOUND')

replacement=r'''    # Native-currency value bands. Full-corpus counts are accumulated by
    # Warehouse_Source × Niche to bound join state; this is mathematically
    # equivalent to the prior weighted native-currency share calculation.
    con.execute("""
      CREATE TEMP TABLE niche_value_fit_parts(
        Niche VARCHAR,
        Known_Value_Awards BIGINT,
        C_1k_100k BIGINT,
        C_20k_100k BIGINT,
        C_1k_5k BIGINT,
        C_5k_20k BIGINT
      )
    """)
    value_pairs=con.execute(f"SELECT DISTINCT Warehouse_Source,Niche FROM read_parquet({q(matched.as_posix())}) ORDER BY 1,2").fetchall()
    for src,niche in value_pairs:
        con.execute(f"""
          INSERT INTO niche_value_fit_parts
          WITH x AS (
            SELECT n.Niche,
                   coalesce(nullif(a.Award_Currency,''),nullif(n.Currency,''),'UNKNOWN') Currency,
                   a.Award_Value
            FROM (
              SELECT Warehouse_Source,Historical_Tender_ID,Niche,Currency
              FROM read_parquet({q(matched.as_posix())})
              WHERE Warehouse_Source={q(src)} AND Niche={q(niche)}
            ) n
            JOIN (
              SELECT Warehouse_Source,Historical_Tender_ID,Award_Value,Award_Currency
              FROM award_base WHERE Warehouse_Source={q(src)}
            ) a USING(Warehouse_Source,Historical_Tender_ID)
            WHERE a.Award_Value IS NOT NULL
          )
          SELECT Niche,
                 count(*)::BIGINT Known_Value_Awards,
                 sum(CASE WHEN Award_Value>=1000 AND Award_Value<100000 THEN 1 ELSE 0 END)::BIGINT C_1k_100k,
                 sum(CASE WHEN Award_Value>=20000 AND Award_Value<100000 THEN 1 ELSE 0 END)::BIGINT C_20k_100k,
                 sum(CASE WHEN Award_Value>=1000 AND Award_Value<5000 THEN 1 ELSE 0 END)::BIGINT C_1k_5k,
                 sum(CASE WHEN Award_Value>=5000 AND Award_Value<20000 THEN 1 ELSE 0 END)::BIGINT C_5k_20k
          FROM x WHERE Currency<>'UNKNOWN' GROUP BY Niche
        """)
    con.execute("""
      CREATE TEMP VIEW niche_value_fit AS
      SELECT Niche,
             sum(Known_Value_Awards) Known_Value_Awards,
             100.0*sum(C_1k_100k)/nullif(sum(Known_Value_Awards),0) Native_Currency_1k_100k_Share_Pct,
             100.0*sum(C_20k_100k)/nullif(sum(Known_Value_Awards),0) Native_Currency_20k_100k_Share_Pct,
             100.0*sum(C_1k_5k)/nullif(sum(Known_Value_Awards),0) Native_Currency_1k_5k_Share_Pct,
             100.0*sum(C_5k_20k)/nullif(sum(Known_Value_Awards),0) Native_Currency_5k_20k_Share_Pct
      FROM niche_value_fit_parts GROUP BY Niche
    """)

'''

s=s[:start]+replacement+s[end:]
p.write_text(s,encoding='utf-8')
print('SPM_VALUE_FIT_SHARDED_PATCH_PASS')
