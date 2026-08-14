from __future__ import annotations
import csv,json
from pathlib import Path

HARD=r"security clearance|habilitation.*secret|classified information|medical licen[cs]e|architect registration|chartered engineer|armed guard|clinical services"
LOCAL=r"local presence|required.*onsite|on[- ]site presence|presence sur site|vor ort|sur place"
REFS=r"minimum.*references?|at least.*references?|minimum.*r[eé]f[eé]rences?|vergleichbare referenzen"
CERT=r"iso\s*9001|iso\s*27001|iso\s*14001|certification required|certificat.*obligatoire|zertifizierung erforderlich"
TURN=r"minimum turnover|annual turnover|chiffre d.affaires minimum|umsatz.*mindestens|minimum.*omzet"
SUBBAN=r"subcontracting.*(not permitted|prohibited|forbidden)|sous[- ]traitance.*interdite|unterauftrag.*nicht zulässig"

def esc(s): return s.replace("'","''")
def copy(con,sql,p): con.execute(f"COPY ({sql}) TO '{Path(p).as_posix()}' (HEADER, DELIMITER ',')")

def build(con, core:Path, out:Path, rules_path:Path):
    t=(core/'historical_tenders.parquet').as_posix(); a=(core/'awards.parquet').as_posix(); b=(core/'award_suppliers.parquet').as_posix()
    rules=json.loads(rules_path.read_text(encoding='utf-8'))
    with (out/'taxonomy_rules.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rules[0])); w.writeheader(); w.writerows(rules)
    case='CASE '+' '.join(f"WHEN regexp_matches(txt,'{esc(r['pattern'])}','i') THEN {r['id']}" for r in rules)+' ELSE 0 END'
    con.execute(f"""CREATE TEMP TABLE tc AS WITH x AS (
      SELECT *,lower(strip_accents(concat_ws(' ',coalesce(Title,''),coalesce(Scope_Summary,''),coalesce(Raw_CPV_Description,''),coalesce(Raw_Spend_Category,''),coalesce(CPV_NAICS_or_Local_Code,''),coalesce(Category,''),coalesce(Subcategory,'')))) txt
      FROM read_parquet('{t}')) SELECT *,{case} rule_id FROM x""")
    con.execute(f"CREATE TEMP TABLE rules AS SELECT * FROM read_csv_auto('{(out/'taxonomy_rules.csv').as_posix()}',header=true)")
    con.execute("""CREATE TEMP TABLE c AS SELECT tc.*,r.macro Macro,r.niche Niche,r.micro Micro_Niche,r.ai AI_Prior,r.sub Subcontractability_Prior,r.remote Remote_Prior,r.margin_low Margin_Low_Pct,r.margin_high Margin_High_Pct,r.novelty Novelty_Prior FROM tc JOIN rules r ON tc.rule_id=r.id WHERE tc.rule_id>0""")
    con.execute(f"""CREATE TEMP TABLE cb AS SELECT *,
      regexp_matches(txt,'{esc(HARD)}','i')::INT Hard_Regulated_Text,
      regexp_matches(txt,'{esc(LOCAL)}','i')::INT Local_Presence_Text,
      regexp_matches(txt,'{esc(REFS)}','i')::INT References_Text,
      regexp_matches(txt,'{esc(CERT)}','i')::INT Certification_Text,
      regexp_matches(txt,'{esc(TURN)}','i')::INT Turnover_Text,
      regexp_matches(txt,'{esc(SUBBAN)}','i')::INT Subcontract_Ban_Text,
      CASE WHEN nullif(Onsite_Requirement,'') IS NOT NULL AND upper(Onsite_Requirement) NOT IN ('UNKNOWN','NO','FALSE','NONE','REMOTE','NOT REQUIRED') THEN 1 ELSE 0 END Onsite_Field_Risk,
      CASE WHEN nullif(Subcontracting_Status,'') IS NOT NULL AND regexp_matches(lower(Subcontracting_Status),'not permitted|prohibit|forbid|interdit|nicht zul','i') THEN 1 ELSE 0 END Subcontract_Field_Ban,
      CASE WHEN nullif(Minimum_Turnover,'') IS NOT NULL AND upper(Minimum_Turnover)<>'UNKNOWN' THEN 1 ELSE 0 END Turnover_Field_Known,
      CASE WHEN nullif(References_Required,'') IS NOT NULL AND upper(References_Required)<>'UNKNOWN' THEN 1 ELSE 0 END References_Field_Known,
      CASE WHEN nullif(Required_Certifications,'') IS NOT NULL AND upper(Required_Certifications)<>'UNKNOWN' THEN 1 ELSE 0 END Cert_Field_Known
      FROM c""")
    con.execute(f"""CREATE TEMP TABLE at AS SELECT Warehouse_Source,Historical_Tender_ID,count(distinct Award_ID) Award_Count,
      median(try_cast(nullif(Award_Value,'') AS DOUBLE)) Median_Award_Value,median(try_cast(nullif(Bidder_Count,'') AS DOUBLE)) Median_Bidder_Count,
      avg((try_cast(nullif(Bidder_Count,'') AS DOUBLE) IS NOT NULL)::INT)*100 Bidder_Coverage_Pct,
      avg(CASE WHEN try_cast(nullif(Bidder_Count,'') AS DOUBLE) IS NOT NULL THEN (try_cast(Bidder_Count AS DOUBLE)=1)::INT ELSE NULL END)*100 Single_Bid_Pct_Known
      FROM read_parquet('{a}') GROUP BY 1,2""")
    copy(con,f"""SELECT Warehouse_Source,count(*) Tender_Count,count(distinct Buyer_ID) Buyer_Count,min(try_cast(Publication_Date AS DATE)) Min_Date,max(try_cast(Publication_Date AS DATE)) Max_Date,
      avg((nullif(Title,'') IS NOT NULL AND Title<>'UNKNOWN')::INT)*100 Title_Coverage_Pct,avg((nullif(Scope_Summary,'') IS NOT NULL AND Scope_Summary<>'UNKNOWN')::INT)*100 Scope_Coverage_Pct,
      avg((try_cast(nullif(Official_Estimated_Value,'') AS DOUBLE) IS NOT NULL)::INT)*100 Estimate_Coverage_Pct,avg((nullif(Deadline,'') IS NOT NULL AND Deadline<>'UNKNOWN')::INT)*100 Deadline_Coverage_Pct,
      avg((nullif(Minimum_Turnover,'') IS NOT NULL AND upper(Minimum_Turnover)<>'UNKNOWN')::INT)*100 Turnover_Field_Coverage_Pct,
      avg((nullif(References_Required,'') IS NOT NULL AND upper(References_Required)<>'UNKNOWN')::INT)*100 References_Field_Coverage_Pct,
      avg((nullif(Required_Certifications,'') IS NOT NULL AND upper(Required_Certifications)<>'UNKNOWN')::INT)*100 Cert_Field_Coverage_Pct,
      avg((nullif(Onsite_Requirement,'') IS NOT NULL AND upper(Onsite_Requirement)<>'UNKNOWN')::INT)*100 Onsite_Field_Coverage_Pct,
      avg((nullif(Subcontracting_Status,'') IS NOT NULL AND upper(Subcontracting_Status)<>'UNKNOWN')::INT)*100 Subcontract_Field_Coverage_Pct
      FROM read_parquet('{t}') GROUP BY 1 ORDER BY Tender_Count DESC""",out/'source_profile.csv')
    copy(con,f"SELECT coalesce(nullif(Category,''),'UNKNOWN') Category,coalesce(nullif(Subcategory,''),'UNKNOWN') Subcategory,count(*) Tender_Count,count(distinct Buyer_ID) Buyer_Count FROM read_parquet('{t}') GROUP BY 1,2 ORDER BY Tender_Count DESC",out/'canonical_taxonomy.csv')
    copy(con,f"SELECT (SELECT count(*) FROM cb) Classified_Tenders,(SELECT count(*) FROM read_parquet('{t}')) Total_Tenders,round(100.0*(SELECT count(*) FROM cb)/(SELECT count(*) FROM read_parquet('{t}')),2) Classified_Pct,count(distinct Micro_Niche) Micro_Niches,count(distinct Buyer_ID) Classified_Buyers FROM cb",out/'classification_coverage.csv')
    micro="""WITH br AS (SELECT Micro_Niche,Buyer_ID,count(*) n FROM cb WHERE nullif(Buyer_ID,'') IS NOT NULL GROUP BY 1,2), rs AS (
      SELECT Micro_Niche,sum((n>=2)::INT) Repeat_Buyers_2plus,sum((n>=3)::INT) Repeat_Buyers_3plus,avg((n>=2)::INT)*100 Repeat_Buyer_Share_Pct FROM br GROUP BY 1), x AS (
      SELECT b.Micro_Niche,any_value(b.Macro) Macro,any_value(b.Niche) Niche,count(*) Tender_Count,count(distinct b.Buyer_ID) Buyer_Count,count(distinct b.Warehouse_Source) Source_Count,
      min(try_cast(b.Publication_Date AS DATE)) First_Date,max(try_cast(b.Publication_Date AS DATE)) Last_Date,median(try_cast(nullif(b.Lean_Fit,'') AS DOUBLE)) Median_Canonical_Lean_Fit,
      avg(b.AI_Prior) AI_Prior,avg(b.Subcontractability_Prior) Subcontractability_Prior,avg(b.Remote_Prior) Remote_Prior,avg(b.Margin_Low_Pct) Margin_Low_Pct,avg(b.Margin_High_Pct) Margin_High_Pct,avg(b.Novelty_Prior) Novelty_Prior,
      sum((a.Award_Count>0)::INT) Tenders_With_Award,median(a.Median_Bidder_Count) Median_Bidder_Count,avg(a.Bidder_Coverage_Pct) Avg_Bidder_Coverage_Pct,avg(a.Single_Bid_Pct_Known) Avg_Single_Bid_Pct_Known,
      avg(b.Hard_Regulated_Text)*100 Hard_Regulated_Text_Pct,avg(greatest(b.Local_Presence_Text,b.Onsite_Field_Risk))*100 Onsite_or_Local_Signal_Pct,
      avg(greatest(b.References_Text,b.References_Field_Known))*100 Reference_Signal_Pct,avg(greatest(b.Certification_Text,b.Cert_Field_Known))*100 Certification_Signal_Pct,
      avg(greatest(b.Turnover_Text,b.Turnover_Field_Known))*100 Turnover_Signal_Pct,avg(greatest(b.Subcontract_Ban_Text,b.Subcontract_Field_Ban))*100 Subcontract_Ban_Signal_Pct
      FROM cb b LEFT JOIN at a USING(Warehouse_Source,Historical_Tender_ID) GROUP BY 1)
      SELECT x.*,coalesce(rs.Repeat_Buyers_2plus,0) Repeat_Buyers_2plus,coalesce(rs.Repeat_Buyers_3plus,0) Repeat_Buyers_3plus,rs.Repeat_Buyer_Share_Pct FROM x LEFT JOIN rs USING(Micro_Niche) ORDER BY Tender_Count DESC"""
    copy(con,micro,out/'micro_niche_facts_raw.csv')
    copy(con,f"""SELECT b.Micro_Niche,b.Warehouse_Source,coalesce(nullif(a.Currency,''),nullif(b.Currency,''),'UNKNOWN') Currency,count(*) Award_Rows_With_Value,
      quantile_cont(try_cast(a.Award_Value AS DOUBLE),.10) P10,quantile_cont(try_cast(a.Award_Value AS DOUBLE),.25) P25,median(try_cast(a.Award_Value AS DOUBLE)) Median,quantile_cont(try_cast(a.Award_Value AS DOUBLE),.75) P75,quantile_cont(try_cast(a.Award_Value AS DOUBLE),.90) P90
      FROM cb b JOIN read_parquet('{a}') a USING(Warehouse_Source,Historical_Tender_ID) WHERE try_cast(nullif(a.Award_Value,'') AS DOUBLE)>0 GROUP BY 1,2,3 HAVING count(*)>=5 ORDER BY 1,2,3""",out/'price_quantiles_by_currency.csv')
    copy(con,f"""SELECT b.Micro_Niche,b.Warehouse_Source,count(*) Award_Rows,sum((try_cast(nullif(a.Bidder_Count,'') AS DOUBLE) IS NOT NULL)::INT) Bidder_Known_Rows,
      avg((try_cast(nullif(a.Bidder_Count,'') AS DOUBLE) IS NOT NULL)::INT)*100 Bidder_Coverage_Pct,quantile_cont(try_cast(nullif(a.Bidder_Count,'') AS DOUBLE),.25) Bidder_P25,median(try_cast(nullif(a.Bidder_Count,'') AS DOUBLE)) Bidder_Median,quantile_cont(try_cast(nullif(a.Bidder_Count,'') AS DOUBLE),.75) Bidder_P75,
      avg(CASE WHEN try_cast(nullif(a.Bidder_Count,'') AS DOUBLE) IS NOT NULL THEN (try_cast(a.Bidder_Count AS DOUBLE)=1)::INT ELSE NULL END)*100 Single_Bid_Pct_Among_Known
      FROM cb b JOIN read_parquet('{a}') a USING(Warehouse_Source,Historical_Tender_ID) GROUP BY 1,2 HAVING count(*)>=5 ORDER BY 1,2""",out/'competition_by_source.csv')
    copy(con,f"""WITH bb AS (SELECT Warehouse_Source,Award_ID,Supplier_ID,1.0/count(*) OVER(PARTITION BY Warehouse_Source,Award_ID) frac FROM read_parquet('{b}') WHERE nullif(Supplier_ID,'') IS NOT NULL), sx AS (
      SELECT c.Micro_Niche,c.Warehouse_Source,bb.Supplier_ID,sum(bb.frac) wins FROM cb c JOIN read_parquet('{a}') a USING(Warehouse_Source,Historical_Tender_ID) JOIN bb USING(Warehouse_Source,Award_ID) GROUP BY 1,2,3), sh AS (
      SELECT *,wins/sum(wins) OVER(PARTITION BY Micro_Niche,Warehouse_Source) share FROM sx)
      SELECT Micro_Niche,Warehouse_Source,count(*) Supplier_Count,max(share)*100 Top_Supplier_Share_Pct,sum(share*share)*10000 Supplier_HHI,
      CASE WHEN sum(share*share)*10000<1500 THEN 'FRAGMENTED' WHEN sum(share*share)*10000<2500 THEN 'MODERATE' ELSE 'CONCENTRATED' END Concentration FROM sh GROUP BY 1,2 HAVING count(*)>=3 ORDER BY 1,2""",out/'supplier_fragmentation.csv')
    copy(con,"""WITH x AS (SELECT Micro_Niche,Warehouse_Source,Buyer_ID,any_value(Buyer_Name) Buyer_Name,count(*) Tender_Count,min(try_cast(Publication_Date AS DATE)) First_Date,max(try_cast(Publication_Date AS DATE)) Last_Date,count(distinct year(try_cast(Publication_Date AS DATE))) Active_Years,mode(month(try_cast(Publication_Date AS DATE))) Modal_Month,count(distinct month(try_cast(Publication_Date AS DATE))) Distinct_Months FROM cb WHERE nullif(Buyer_ID,'') IS NOT NULL GROUP BY 1,2,3) SELECT *,CASE WHEN Tender_Count>=8 AND Active_Years>=2 THEN 'VERY_HIGH_REPEAT' WHEN Tender_Count>=5 THEN 'HIGH_REPEAT' WHEN Tender_Count>=3 THEN 'REPEAT' ELSE 'LOW_REPEAT' END Repeat_Band,CASE WHEN Active_Years>=2 AND Distinct_Months<=greatest(2,Active_Years+1) THEN 'POTENTIALLY_SEASONAL' ELSE 'NO_STRONG_SEASON_SIGNAL' END Seasonality_Signal FROM x WHERE Tender_Count>=2 ORDER BY Tender_Count DESC,Active_Years DESC""",out/'buyer_niche_recurrence.csv')
    copy(con,"SELECT Micro_Niche,Warehouse_Source,month(try_cast(Publication_Date AS DATE)) Month,count(*) Tender_Count,count(distinct Buyer_ID) Buyer_Count FROM cb WHERE try_cast(Publication_Date AS DATE) IS NOT NULL GROUP BY 1,2,3 ORDER BY 1,2,3",out/'seasonality_monthly.csv')
    copy(con,f"""WITH w AS (SELECT a.Warehouse_Source,a.Historical_Tender_ID,arg_max(a.Award_ID,try_cast(nullif(a.Award_Value,'') AS DOUBLE)) Award_ID,max(try_cast(nullif(a.Award_Value,'') AS DOUBLE)) Award_Value,arg_max(a.Currency,try_cast(nullif(a.Award_Value,'') AS DOUBLE)) Award_Currency,arg_max(try_cast(nullif(a.Bidder_Count,'') AS DOUBLE),try_cast(nullif(a.Award_Value,'') AS DOUBLE)) Bidder_Count FROM read_parquet('{a}') a GROUP BY 1,2), n AS (SELECT a.Warehouse_Source,a.Historical_Tender_ID,string_agg(distinct b.Supplier_Name,' | ' ORDER BY b.Supplier_Name) Winner_Names FROM read_parquet('{a}') a JOIN read_parquet('{b}') b USING(Warehouse_Source,Award_ID) WHERE nullif(b.Supplier_Name,'') IS NOT NULL GROUP BY 1,2), r AS (
      SELECT c.Micro_Niche,c.Historical_Tender_ID,c.Title,c.Buyer_Name,c.Country,c.Publication_Date,c.Deadline,c.CPV_NAICS_or_Local_Code,c.Official_Estimated_Value,c.Currency,c.Primary_Source_URL,c.Warehouse_Source,w.Award_ID,w.Award_Value,w.Award_Currency,w.Bidder_Count,n.Winner_Names,
      row_number() OVER(PARTITION BY c.Micro_Niche ORDER BY ((w.Award_Value IS NOT NULL)::INT*3+(w.Bidder_Count IS NOT NULL)::INT*2+(nullif(c.Primary_Source_URL,'') IS NOT NULL)::INT*2+(nullif(c.Deadline,'') IS NOT NULL)::INT) DESC,try_cast(c.Publication_Date AS DATE) DESC nulls last) rn FROM cb c LEFT JOIN w USING(Warehouse_Source,Historical_Tender_ID) LEFT JOIN n USING(Warehouse_Source,Historical_Tender_ID)) SELECT * EXCLUDE(rn) FROM r WHERE rn<=5""",out/'representative_tenders.csv')
    copy(con,"""SELECT Warehouse_Source,Country,Micro_Niche,count(*) Tender_Count,count(distinct Buyer_ID) Buyer_Count,median(try_cast(nullif(Lean_Fit,'') AS DOUBLE)) Median_Lean_Fit,median(at.Median_Bidder_Count) Median_Bidders,avg(at.Bidder_Coverage_Pct) Avg_Bidder_Coverage_Pct,avg(greatest(Hard_Regulated_Text,Local_Presence_Text,Onsite_Field_Risk,Certification_Text,Subcontract_Ban_Text))*100 Explicit_Hardish_Risk_Pct FROM cb LEFT JOIN at USING(Warehouse_Source,Historical_Tender_ID) GROUP BY 1,2,3 HAVING count(*)>=3 ORDER BY Tender_Count DESC""",out/'country_micro_niche.csv')
    return {'t':t,'a':a,'b':b,'rules':rules}
