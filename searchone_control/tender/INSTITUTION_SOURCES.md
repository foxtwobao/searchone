# School and hospital tender sources

`institution-source-domains.csv` is a curated discovery catalog for school and
hospital procurement searches. It is intentionally a ranking and trust catalog,
not a hard result allow-list.

## Coverage

- China Government Procurement Network and its official provincial,
  sub-provincial, and XPCC directory links.
- National Public Resource Trading Platform and its official provincial and
  XPCC directory links.
- China Tendering and Bidding Public Service Platform and the Central
  Government Procurement Network.
- Education and health discovery sources.
- Verified Qinghai institution seeds, including Qinghai Minzu University,
  Qinghai University, Qinghai Normal University, Qinghai Provincial People's
  Hospital, and Qinghai Red Cross Hospital.

The two official parent directories used for the nationwide portal rows are:

- <http://www.ccgp.gov.cn/> (`地方分网`)
- <https://www.ggzy.gov.cn/> (provincial platform directory)

## Search policy

1. Prefer exact catalog domains and give them a ranking bonus.
2. Do not discard a result only because its domain is absent from the catalog.
3. For an exact school or hospital name, also search trusted suffixes from
   `institution-domain-rules.json`.
4. Accept `.edu.cn`, `.gov.cn`, and `.ac.cn` results when the page contains the
   exact institution name and procurement intent.
5. Treat `.org.cn`, `.com.cn`, and other hospital domains as discovery leads
   until the page proves the institution's official identity.
6. Keep commercial bid aggregators only as mirrors or discovery evidence; the
   primary result should point to the purchaser, government procurement, public
   resource, or statutory announcement page.

## Maintenance

Official portal URLs change over time. Recheck the two parent directories and
institution seed homepages before a release that updates this catalog. Preserve
the `verification_source` and `verified_at` columns when replacing a URL.
