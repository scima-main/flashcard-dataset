# Flashcard SFT corpus — build state

## Locked decisions (from user)
- **200 main rows**, quality-first, fully hand-authored cards.
- **Strictly real verbatim sources** — no synthetic text. Canonical publisher URLs only, never proxies.
- **Max sequence length 4096 tokens.**
- **70% English / 30% other languages**; cards in the source language.
- **Negative/robustness rows live in a SEPARATE file** (`negatives.jsonl`), excluded from train/val/test.
- N = ceiling (budget-feasible rule), LoRA/QLoRA assumed.

## Layout
- `harvest/{docid}.txt` — exact shipped source text (verbatim; trimmed excerpt where noted)
- `harvest/{docid}.json` — url, licence, origin, title, fetch date, extraction mode
- `cards/{docid}.json` — authored cards + row config (N, discipline, provenance, difficulty, lang, tier, flags, kind)
- `scripts/harvest.py` — fetchers + HTML→text (stdlib only)
- `scripts/build.py` — assemble splits + meta + stats
- `scripts/validate.py` — required validator

## Card file schema
```json
{"docid":"...","N":14,"lang":"en","discipline":"biology","provenance":"encyclopedic",
 "difficulty":"undergraduate","tier":"medium","flags":[],"kind":"main",
 "cards":[{"q":"...","a":"...","type":"def"}]}
```
`type` ∈ def | mech | quant | contrast  (bookkeeping only; stripped at build → schema stays {q,a})
Target mix: 35% def, 30% mech, 20% quant, 15% contrast.

## Row budget targets (200 main rows)
- N bands: 3–8 → 30 rows (15%); 9–20 → 110 rows (55%); 21–40 → 60 rows (30%)
- under-budget rows (k<N): ~20 (10%); triage rows (source ≫ N): ~20 (10%)
- length tiers: short ~40, medium ~90, long ~50, very long ~20
- languages: en 140; zh 10, de 8, fr 7, es 7, ja 6, ru 5, pt 5, ar 4, hi 3, it 2, ko 2, sw 1
- disciplines: ≤40 rows each (16 disciplines, ~12 avg)
- negatives: ~14 rows in negatives.jsonl (7% of 200)

## Working hosts (verified, canonical)
{lang}.wikipedia.org · who.int (+/fr /es /zh /ar /ru) · sqlite.org (PD) ·
science.nasa.gov (PD) · developer.mozilla.org + raw.githubusercontent.com/mdn (CC-BY-SA) ·
api.stackexchange.com (CC-BY-SA) · doaj.org (CC) · gutenberg.org (PD) ·
cnx.org/openstax (CC-BY) · law.cornell.edu (PD) · openwetware.org (CC-BY-SA) ·
d2l.ai (CC-BY-SA) · collectionapi.metmuseum.org (CC0) · ocw.mit.edu ·
{lang}.wikisource.org · {lang}.wikibooks.org · {lang}.wikiversity.org
BLOCKED: openstax.org direct, libretexts, oyc.yale.edu, ted.com, open.edu, eur-lex,
legislation.gov.uk, loc.gov, protocols.io, PMC web, archive.org (429).

## Progress log
- [x] infra + 37 documents harvested (batch A)
- [ ] authoring batches 1..N
