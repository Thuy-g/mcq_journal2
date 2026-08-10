# Answer-leakage design audit — which rule Phase B must preserve

**Date** 2026-08-10 · **Branch** `journal2-phase-b0-albert-readiness-audit-20260810`
**Scope** read-only. No production file was modified.
**Companions** `docs/audits/ALBERT_EINSTEIN_PHASE_B_READINESS.md`,
`docs/context/PHASE_B_INPUT_CONTRACT.md`

Every verdict in this document was **executed**, not reasoned about. The three
implementations were imported read-only and run over the same inputs on
2026-08-10 in `mcq-journal2` (Python 3.11.15).

---

## 1. The three implementations, and the two different problems

| Tag | Function | File | Input | Models used |
|---|---|---|---|---|
| **R1** | `detect_answer_leakage(answer_uri, counterpart_uri, policy)` | `src/rationale_v3/quality.py` (`sha256 4622755938…`) | **URIs** | none |
| **v4** | `detect_leak(answer_label, category_label, *, nlp=None, synonym_expander=None)` | `src/category_extractor_ClaudeWeb_v4.py` (`sha256 921ff6d407…`) | **labels** | optional spaCy + optional WordNet |
| **v2** | `leaks_answer(answer_label, category_label, nlp=None)` | `src/category_extractor_ClaudeWeb_v2.py` (`sha256 cc594ef1fc…`) | **labels** | optional spaCy + **mandatory** WordNet |

v4 is newer than v2; both descend from the author's original
`src/category_extractor.py`, which contains no leak function of its own — the
original only carries the commented probe list. So v2 and v4 are two independent
re-derivations of the same idea rather than a refactor chain.

**The two problems are related but not the same.**

* **Class-name leakage** (v2, v4) asks: *does the name of the candidate class
  hand the learner the Answer?* It runs once per Answer × class, on **labels**,
  during class selection.
* **Rationale-counterpart leakage** (R1) asks: *does the counterpart entity of a
  rationale fact hand the learner the Answer?* It runs once per Answer fact, on
  **URIs**, and its `hard_leak` output is one of the three conjuncts of
  `FactQuality.eligible` — a hard filter that removes the fact from every policy
  and every rationale.

They share a mechanism and differ in consequence. A class-name miss costs a bad
candidate pool; a counterpart miss puts the Answer's own name inside the
rationale shown to the student. Phase B needs the second.

---

## 2. Measured comparison A — the six named regression cases

Run with `nlp=None` and no synonym expander for v4, which is exactly the
configuration the frozen batch-34 run used (`run_manifest.json`:
`sbert_enabled: false`, no NLP supplied).

| Answer | Counterpart / class | Required | **R1** | **v4** | **v2** |
|---|---|---|---|---|---|
| Carbon | Carbonado | **must be HARD** | **HARD** `LONG_PREFIX` (`carbon`→`carbonado`, 6 chars) | `no_leak` ❌ | HARD, bare substring |
| Carbon | Boron carbide | **must not be an unjustified HARD** | **soft** only (`SHORT_PREFIX`, shared prefix `carb` = 4) ✅ | `no_leak` ✅ | `None` ✅ |
| Iron(II) chloride | Iron(III) chloride | display must stay distinct | HARD (shared whole tokens `iron`, `chloride`) — and **display preserved** ✅ | `hard_leak` with reason *"class label is identical to the answer label"* ⚠️ | HARD *"substring overlap ('iron chloride' vs 'iron chloride')"* ⚠️ |
| Phosphorus(V) oxide | Phosphorus pentoxide | display must not be corrupted | HARD (`phosphorus` whole token); display `Phosphorus(V) oxide` intact ✅ | `no_leak` ❌ | HARD via WordNet: `['atomic number 15','daystar','lucifer']` ❌ |
| Adam Smith | Smithsonian Institution | should be HARD | **HARD** `LONG_PREFIX` (`smith`→`smithsonian`) | `no_leak` ❌ | `None` ❌ |
| Plato | Platonists | should be HARD | **HARD** `LONG_PREFIX` | `no_leak` ❌ | HARD, bare substring |
| Silicon | Boron | must stay clean | `-` ✅ | `no_leak` ✅ | `None` ✅ |
| Carbon | Diamond | must stay clean | `-` ✅ | `no_leak` ✅ | `None` ✅ |

### What the ⚠️ rows mean

Both v4 and v2 report the two iron chlorides as *identical labels*. They are not
identical — the oxidation state is the only thing distinguishing them. The cause
is that both strip parentheticals **before** comparing:

```
v4  _normalize_for_matching('Iron(II) chloride')  -> 'iron chloride'
v4  _normalize_for_matching('Iron(III) chloride') -> 'iron chloride'
v2  remove_parenthetical('Iron(II)_chloride')     -> 'Iron chloride'
v2  remove_parenthetical('Iron(III)_chloride')    -> 'Iron chloride'
```

For a **class-name** check this is mostly harmless and both files confine the
lossy form to comparison. v4 is explicit about it — `_normalize_for_matching`'s
docstring says it *"may discard information (including parentheticals) because
its output is never shown to anybody"* — and `format_display_label()` correctly
returns `'Iron(II) chloride'`, `'Iron(III) chloride'`, `'Phosphorus(V) oxide'`.
v2 has no display formatter at all; `remove_parenthetical` is a free-standing
helper and would corrupt any label it were reused for.

**Constraint for Phase B.** Reuse of `remove_parenthetical()` or of
`_normalize_for_matching()` as a display or identity helper is forbidden. The
display path is `rationale_v3.quality.display_label()`, which preserves the
Roman numerals exactly (verified above and in `PHASE_B_INPUT_CONTRACT.md` §4).

---

## 3. Measured comparison B — the real Albert Einstein counterpart set

The strongest available test, because Albert Einstein is the most leak-prone
Answer in the corpus: sixty distinct one-hop counterparts drawn from the pinned
local KG (`data/infobox.pickle_EnglishVersion_EntityType`, node index 417144).

**HARD verdicts over the same 60 counterparts:**

| Implementation | HARD | Missed | Note |
|---|---:|---:|---|
| **R1** `detect_answer_leakage` | **11** | 0 | deterministic, no models |
| **v4** `detect_leak` (nlp=None) | 4 | **7** | token-boundary containment only |
| **v2** `leaks_answer` (WordNet loaded) | 9 | 2 | 6 of the 9 reached only by a WordNet coincidence |

### The seven counterparts v4 misses

| Counterpart | R1 | v4 | why v4 misses it |
|---|---|---|---|
| `Einstein family` | HARD `WHOLE_TOKEN einstein` | `no_leak` | `" albert einstein "` is not a phrase inside `" einstein family "` |
| `Einstein: His Life and Universe` | HARD | `no_leak` | same |
| `Einstein Gargoyle` | HARD | `no_leak` | same |
| `Einstein for Beginners` | HARD | `no_leak` | same |
| `Einstein–Szilard letter` | HARD | `no_leak` | same |
| `Elsa Einstein` | HARD | `no_leak` | same |
| `Lieserl Einstein` | HARD | `no_leak` | same |

v4's `_contains_phrase()` requires the **complete** Answer name to occur inside
the class name, at token boundaries. A shared *surname* is invisible to it
without spaCy, and spaCy was not supplied in the frozen run. This is exactly the
mechanism by which the batch-34 class selector accepted
`dbc:Einstein_family` as Albert Einstein's automatic top-1 class with
`leak_level: "no_leak"` — recorded verbatim in
`outputs/category_selector_v4_batch34_2026-07-28/B_final_warm/results.jsonl`.
The same run **did** hard-reject `dbc:Albert_Einstein` (*"class label is
identical to the answer label"*), so the rule fires only at the top of its range.

### Why v2's extra hits do not rescue it

v2 reaches `Einstein family`, `Einstein Gargoyle`, `Einstein for Beginners`,
`Elsa Einstein`, `Lieserl Einstein` and `Einstein: His Life and Universe`
**only** through WordNet, with evidence
`shared lemma/synonym ['albert einstein', 'brain', 'brainiac']` — because
WordNet happens to record *einstein* as a common noun meaning *genius*. A right
answer produced by an unrelated lexical coincidence is not a rule; the same
mechanism produces
`Phosphorus(V) oxide` vs `Phosphorus oxoacids` → `['atomic number 15',
'daystar', 'lucifer']`, where *phosphorus* is matched to the morning star. And
v2 still misses `Adam Smith` / `Smithsonian Institution` entirely.

v2 also uses **bare substring containment** (`a in c or c in a`) with no token
boundary and no minimum length. That is the "ordinary short common prefixes
become a broad hard rule" failure mode the task warns about: any Answer whose
name is a short substring of a counterpart is hard-rejected with no length
guard.

---

## 4. Why the R1 rule is the one to preserve

```python
# src/rationale_v3/quality.py, detect_answer_leakage(), with the frozen policy
minimum_token_length  = 4     # tokens shorter than 4 chars are dropped entirely
minimum_prefix_length = 5     # HARD threshold
soft_prefix_length    = 4     # SOFT threshold
strip_suffixes        = ["s", "es"]   # ONE light plural strip, never below 4 chars
```

For each Answer token `a` and counterpart token `b`:

| Test | Verdict |
|---|---|
| `a == b` | HARD `WHOLE_TOKEN` |
| `plural_stem(a) == plural_stem(b)` | HARD `PLURAL_STEM` |
| `shared_prefix(a,b) >= 5` **and** one token is a complete prefix of the other | HARD `LONG_PREFIX` |
| `shared_prefix(a,b) >= 4` | SOFT `SHORT_PREFIX` |
| otherwise | no leak |

Five properties earn it the job:

1. **It separates the two cases the task names.** `carbon` is a complete 6-char
   prefix of `carbonado` → HARD; `carbon` and `carbide` share only `carb` (4) and
   neither is a prefix of the other → SOFT at most. The policy file states this
   reasoning in its own `why_two_thresholds` note.
2. **It is a prefix rule, not a "share n characters" rule.** The HARD branch
   additionally requires `a.startswith(b) or b.startswith(a)`, so an incidental
   five-character overlap in the middle of two words cannot trigger it. Short
   common prefixes therefore cannot become a broad hard rule.
3. **Tokens under four characters are discarded before comparison**, so a
   two- or three-character coincidence is structurally incapable of producing a
   verdict.
4. **It is deliberately not a stemmer.** `_plural_stem` strips one light plural
   suffix and never below four characters. The docstring records why: Porter-style
   stemming folds `carbonate` and `carbonated` onto `carbon` and would reject
   facts sharing nothing but a chemical root — the over-sensitivity AUDIT item
   CE-11 documents.
5. **It needs no model.** Unicode NFKC, percent decoding, casefolding and string
   comparison only. It is already covered by `tests/test_rationale_v3.py` and its
   thresholds live in a versioned, SHA-256-pinned policy file.

### Measured cost on the hardest real Answer

Applying the frozen R1 quality layer to Albert Einstein's 66 one-hop facts:

```
raw distinct one-hop facts     66
ELIGIBLE after the hard filter 48
REJECTED                       18
  ANSWER_LEXICAL_LEAK          15
  PREDICATE_RAW_LAYOUT_SLOT     2
  PREDICATE_EXTERNAL_URL_FIELD  2
  OBJECT_EXTERNAL_URL           1
  OBJECT_WEB_ARCHIVE_URL        1
```

All fifteen leak rejections are correct and each one would otherwise put
"Einstein" into the rationale: `children → Einstein_family`,
`children → Hans_Albert_Einstein`, `children → Lieserl_Einstein`,
`spouse (IN) → Elsa_Einstein`, `eponym (IN) → Einstein_(crater)`,
`dedicatedTo (IN) → Albert_Einstein_Memorial`,
`subject (IN) → Bust_of_Albert_Einstein`, and so on. Forty-eight eligible facts
across seventeen distinct `κ` keys survive, forty-one of them with a registered
template — an ample rationale supply, so the filter is not over-aggressive here.

The same run also reproduces the two Prompt-8E motivating failures on a new
Answer without any special-casing: `dbp:url → web.archive.org/…` is rejected
`OBJECT_WEB_ARCHIVE_URL` and `dbp:thesisUrl → …eth-30378-01.pdf` is rejected
`OBJECT_EXTERNAL_URL`.

---

## 5. Recommendation for minimal Phase B

**Preserve the R1 semantics exactly. Do not import a category extractor into the kernel.**

1. **`src/mcq_core.py` stays the selection kernel.** It must not gain a leakage
   function, a policy loader, a tokenizer or any new import. It already declares
   that it "never detects lexical leakage", and a Phase-A2 test asserts the
   kernel source contains neither `rationale_v3` nor `spec_freeze_audit`.

2. **The leakage check belongs to the Phase-B adapter**, alongside the other
   hard eligibility filters, because `eligible` is an *upstream* obligation of
   `PHASE_B_INPUT_CONTRACT.md` §3.2.

3. **Smallest correct implementation, in preference order.**
   * **Preferred — reuse.** Call `rationale_v3.quality.assess_fact_quality()`
     with the frozen `predicate_policy.json`. It is already tested, already
     produces every one of the eleven `FactQuality` fields, and pulls in no
     model: `quality.py` imports only `hashlib`, `json`, `unicodedata`,
     `dataclasses`, `pathlib`, `typing`, `urllib.parse` and
     `rationale_v3.contracts`. Reusing it means Phase B inherits the semantics
     **and** the regression tests instead of re-deriving both.
   * **Fallback — extract.** If the dependency on the `rationale_v3` package is
     judged undesirable, copy `local_name`, `display_label`, `leakage_tokens`,
     `_plural_stem`, `_shared_prefix_length` and `detect_answer_leakage`
     verbatim (~90 lines including comments) into the adapter, keep the policy
     file as the source of the four thresholds, and port the corresponding
     tests. Do not paraphrase the rule; a paraphrase is a new rule that has never
     been measured.

4. **Forbidden in the minimal rationale-leakage check.** WordNet, spaCy,
   embeddings and any LLM. The audit above is the evidence: WordNet **produced
   two demonstrable false-positive mechanisms** (`einstein → brainiac`,
   `phosphorus → lucifer`) and spaCy was absent from the frozen production run
   anyway. Nothing in the measurements shows a leak that the deterministic rule
   misses and a model would catch, so no model is scientifically necessary.

5. **Carry the four thresholds and the two reason codes onto the record**
   (`ANSWER_LEXICAL_LEAK`, `ANSWER_LEXICAL_LEAK_SOFT`, plus
   `leakage_matches`), so a reader can see which token pair caused a rejection
   without re-running the pipeline. R1 already emits exactly this.

6. **Class-name leakage is a separate, later decision.** The batch-34
   `dbc:Einstein_family` acceptance shows v4's rule is too weak for a surname,
   but tightening it changes *class selection*, which is a different stage with
   a different acceptance test and its own approval path. Recording the finding
   here is in scope; changing v4 is not, and this audit does not authorise it.
   As a stopgap, note that running the **R1** rule over the candidate class label
   would have rejected `Category:Einstein_family` (`WHOLE_TOKEN einstein`,
   verified above), so the same deterministic rule is available to that stage
   when it is revisited.

---

## 6. Regression cases any Phase-B leakage test must contain

| # | Answer | Counterpart | Expected | Guards against |
|---:|---|---|---|---|
| 1 | `Carbon` | `Carbonado` | **hard** | the v4 token-boundary miss |
| 2 | `Carbon` | `Boron_carbide` | **not hard** (soft allowed) | an over-broad prefix rule |
| 3 | `Albert_Einstein` | `Einstein_family` | **hard** | the batch-34 class-selection miss |
| 4 | `Albert_Einstein` | `Mileva_Marić` | **not hard** | over-rejection of a legitimate counterpart |
| 5 | `Adam_Smith` | `Smithsonian_Institution` | **hard** | the v2 miss |
| 6 | `Iron(II)_chloride` | display label | `'Iron(II) chloride'` | parenthetical destruction |
| 7 | `Iron(III)_chloride` | display label | `'Iron(III) chloride'`, `!=` case 6 | the CE-10 two-choices-one-label collapse |
| 8 | `Phosphorus(V)_oxide` | display label | `'Phosphorus(V) oxide'` | oxidation-state destruction |
| 9 | `Silicon` | `Boron` | **no leak** | a short-prefix false positive |
| 10 | any | any | `nltk`, `spacy`, `sentence_transformers` absent from `sys.modules` | model creep into the deterministic check |

---

## 7. Reproducing every measurement in this document

```bash
conda activate mcq-journal2
cd /home/thuy/projects/mcq_journal2

# R1 rule, the named cases and the display labels
PYTHONPATH=src python - <<'PY'
from rationale_v3.quality import load_quality_policy, detect_answer_leakage, display_label
pol = load_quality_policy('src/rationale_v3/policies/predicate_policy.json')
R = "http://dbpedia.org/resource/"
for a, c in [("Carbon","Carbonado"), ("Carbon","Boron_carbide"),
             ("Albert_Einstein","Einstein_family"), ("Adam_Smith","Smithsonian_Institution"),
             ("Plato","Platonists"), ("Silicon","Boron")]:
    r = detect_answer_leakage(R+a, R+c, pol)
    print(f"{a:<18}{c:<26}hard={r.hard_leak} soft={r.soft_leak} {r.reason_code} {r.matches[:2]}")
for x in ["Iron(II)_chloride","Iron(III)_chloride","Phosphorus(V)_oxide"]:
    print(x, "->", repr(display_label(R+x)))
PY

# v4 and v2, in the frozen batch-34 configuration
PYTHONPATH=src python - <<'PY'
import importlib
v4 = importlib.import_module("category_extractor_ClaudeWeb_v4")
v2 = importlib.import_module("category_extractor_ClaudeWeb_v2")
for a, c in [("Albert Einstein","Einstein family"), ("Carbon","Carbonado"),
             ("Carbon","Boron carbide"), ("Adam Smith","Smithsonian Institution")]:
    print(f"{a:<18}{c:<26}v4={v4.detect_leak(a,c).level.value:<10}v2={v2.leaks_answer(a,c)}")
PY

# the batch-34 record that accepted dbc:Einstein_family
python - <<'PY'
import json
p = "outputs/category_selector_v4_batch34_2026-07-28/B_final_warm/results.jsonl"
for line in open(p, encoding="utf-8"):
    r = json.loads(line)
    if r.get("original_uri","").endswith("Albert_Einstein"):
        print("selected_class:", r["selected_class"])
        for c in r["evaluated_classes"]:
            if "Einstein" in c["category_short"]:
                print(f"  {c['category_short']:<26} leak={c['leak_level']} "
                      f"reason={c['leak_reason']} rejected={c['rejected_code']}")
PY
```

The Albert Einstein 60-counterpart sweep and the 66-fact eligibility census
additionally require loading the pinned 1.2 GB pickle; the probe scripts used for
this audit are throw-away and were kept out of the repository deliberately —
they are reproduced in
`docs/audits/ALBERT_EINSTEIN_PHASE_B_READINESS.md` §10.
