# Public Tender Intelligence — Canonical Schema v1.1

## Design rules

1. Source facts and derived intelligence are separate.
2. `UNKNOWN` is never silently converted to `NO`, zero, or an estimate.
3. A tender and an award are different entities.
4. One award may have many awarded suppliers. Never multiply a group-level award value across suppliers.
5. Stable IDs are deterministic hashes of jurisdiction + strongest available official identifier/natural key.
6. Raw source identifiers, URLs, retrieval metadata and confidence must remain recoverable.

## Core fact tables

### Historical_Tenders
One canonical procurement opportunity / tender entity.

Core fields follow the project `SCHEMA.md`, plus:
- `Source_Record_Count`
- `Source_Platform`
- raw procedure / directive / threshold fields where available
- `Evidence_Confidence`

### Awards
One award/result group linked to a tender where evidence permits.

Additional fields:
- `Award_Group_ID`
- `Award_Value_Scope`
  - `TENDER_OR_AWARD_TOTAL`
  - `GROUP_TOTAL_NOT_ALLOCATED`
  - `SUPPLIER_ALLOCATED`
  - `UNKNOWN`
- `Supplier_Count`
- `Source_Record_Count`

If several suppliers share one published total, `Award_Value` is stored once on the award group. It must not be copied into supplier rows.

### Award_Suppliers
Many-to-many bridge:
- `Award_ID`
- `Supplier_ID`
- `Supplier_Name`
- `Relationship`
- `Award_Value_Allocated`

`Award_Value_Allocated` stays null unless the source explicitly allocates value to that supplier or the award has exactly one unambiguous supplier.

### Buyers
Entity profile aggregated from canonical tenders/awards.

### Suppliers
Entity profile aggregated from `Award_Suppliers` and awards. Group totals are excluded from supplier revenue/value aggregates unless explicitly allocated.

## Derived intelligence tables

These are not primary-source facts and must be labeled derived:

### Market_Rank
Segment-level metrics and attractiveness score.

### Historical_Anomalies
High-value / low-competition / high-lean-fit historical examples.

### Repeat_Buyers
Buyers with recurring demand in lean categories.

### Supplier_Concentration
Supplier win concentration by category/subcategory.

## Current scoring v1

`Market_Attractiveness_Score` is derived from:
- 30% median Lean Fit
- 25% log-scaled median award value
- 20% observed competition
- 15% observed volume
- 10% evidence coverage

Missing bidder count receives a conservative neutral-low score; it is never estimated.

This scoring model is intentionally replaceable without changing canonical fact tables.
