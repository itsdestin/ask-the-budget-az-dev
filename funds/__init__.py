"""Fund catalog (Phase 1a Workstream 4).

Provides the canonical fund × agency × amount tuples that chunk-builder
D7 / entity_stamper need to stamp `fund_canonical_id` on chunks.

Public surface:
  - `funds.slug.slugify_fund_name` — fund-name → slug derivation
  - `funds.parser.parse_s18_table` — MinerU s18 ExtractedDocument → rows
  - `funds.catalog.build_fund_catalog` — rows → FundEntry list
  - `funds.catalog.write_catalog_yaml` — emit data/fund-catalog.yaml
"""
