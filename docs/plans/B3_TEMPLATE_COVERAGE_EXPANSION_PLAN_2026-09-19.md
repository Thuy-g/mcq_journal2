# B3 template-coverage expansion plan

**Prompt** 8H-B3-ARCH-3R · **Date** 2026-09-19
**Status** PROPOSAL for human review. The production template registry
(`src/rationale_v3/policies/predicate_policy_v2.json`, 73 templates) is **not
modified** by this task. Every candidate below is a KEY-level template over the
whole pinned KG; no Answer-specific template exists or is allowed.
**Evidence** `outputs/journal2_b3_pre_freeze_resolution_2026-09-19/`:
`template_candidate_census.json` (corpus census), `template_candidate_key_sources.json`
(why each key was looked at), `template_candidates_v1.json` / `.csv` (the versioned
candidate file, `template_candidates/1.0.0-proposal-not-production`),
`template_coverage_T0_T1_T2.csv` and `template_coverage_rollup.json` (the counterfactual).
**Companion** `B3_PRE_FREEZE_BLOCKER_RESOLUTION_2026-09-19.md` §2–§3.

---

## 1. Why this plan exists

ARCH-3 measured that template coverage, not the evidence model, is the
dominant bottleneck behind two human decisions: 176/396 development items
carry a selected `R*` with a template-less fact (H5), and 127,987 of 142,598
optional context groups have no template (H14). Five predicate-direction keys
explained 101 of the 176 items. This plan audits those five keys and every
other key that (a) occurs in a selected `R*` without a template, (b) blocks a
material share of shared verbalizable-candidate context, or (c) would unlock
arm-C pre-answer context in at least two items — 91 keys in all — and
measures what generic deterministic templates would repair **without changing
any selected distractor or `R*`**.

## 2. How the audit was done

1. **Key sources** (`template_candidate_key_sources.json`): from the 396 ARCH-3
   universes, the template-less `R*` keys, the shared (support ≥ 2, not
   Answer-only) unverbalizable optional groups by key, and the "arm-C-clean
   except for the template" groups by key with the number of items each key
   would unlock.
2. **Corpus census** (`template_candidate_census.json`): one read-only scan of
   every subject's out-edges in the pinned KG (SHA-256 verified) for the 82
   predicates behind the 91 keys: edges, distinct subjects and objects, the
   twelve most frequent objects (to tell VALUES from LAYOUT LABELS or
   placeholders), the share of resource-valued objects, and deterministic
   example triples (lowest subject indices, spread over distinct objects — not
   cherry-picked). IN keys are read from the same edges with the roles
   reversed.
3. **Verdicts** (`template_candidates_v1.json`), one per key, each with the raw
   predicate, direction, triple pattern, intended semantic reading, proposed
   English template, whether subject/object roles reverse for IN, ambiguity
   risks, eligibility and the scientific reason:
   * `SAFE_TO_TEMPLATE` — a fixed English template renders every observed
     triple of the key faithfully; the slot holds values of one kind and the
     reading does not depend on the subject's infobox family. Where the
     precise relation wording varies by family, a **neutral** reading is
     proposed ("The location of X is Y", "X lists Y among its products") that
     is true of the record in every family.
   * `NEEDS_HUMAN_REVIEW` — the slot is polysemous across infobox families
     (`house`: royal house vs legislative house; `field`: discipline vs
     ballpark), mixes values with list pages or placeholders (`succession`,
     `titleLeader`, `after`/`before` with `Incumbent`), or the reading would
     be wrong for a material share of triples.
   * `REJECT` — layout metadata (`subdivisionType`, `postalCodeType`,
     `blankNameSec`, `posthumousName`), alias or name slots (`name`,
     `othernames`), navigation slots (`northeast`), external references
     (`source`), generic classification (`type`), or a slot the B2-G audit
     already refused (`honorificPrefix`).
4. **Counterfactual coverage** on the frozen selections: T0 = production
   templates; T1 = the SAFE candidates among the five high-impact keys; T2 =
   every SAFE candidate. Applied in memory to the `R*` facts and the optional
   groups; nothing upstream re-selected.


**Verdict counts.** SAFE_TO_TEMPLATE 48, NEEDS_HUMAN_REVIEW 29, REJECT 14 (91 keys, 82 predicates).

## 3. The five high-impact keys

| key | verdict | proposed template | reading | pinned-KG edges | R* facts blocked (dev) | arm-C items unlocked | main ambiguity risk |
|---|---|---|---|---:|---:|---:|---|
| `dbp:birthPlace` / IN | SAFE_TO_TEMPLATE | <subject> was born in <answer>. | the subject person's birthplace is the Answer place | 956439 | 38 | 1 | mixed granularity of the place value (country vs city) is a grounding matter, not a template matter |
| `dbp:products` / IN | SAFE_TO_TEMPLATE | <subject> lists <answer> among its products. | the Answer is a product of the subject organisation | 27213 | 26 | 2 | a few subjects are advertisements or labels (2.13.61 -> Record company); the neutral wording stays faithful |
| `dbp:battles` / IN | SAFE_TO_TEMPLATE | <subject> took part in <answer>. | the subject (person or military unit) fought in the Answer battle/war | 115410 | 18 | 1 | a ship or unit as subject reads naturally with 'took part in'; 'fought in' would not |
| `dbp:deathPlace` / IN | SAFE_TO_TEMPLATE | <subject> died in <answer>. | the subject person's death place is the Answer place | 258812 | 13 | 2 | — |
| `dbp:settlementType` / OUT | SAFE_TO_TEMPLATE | <answer> has the settlement type <object>. | the Answer place's settlement type as recorded in its infobox | 145055 | 6 | 10 | some values are list pages rather than type names; the reading remains true of the record |

Representative pinned-KG triples (deterministic sample; subject → object):

* `dbp:birthPlace` / IN: 03 Greedo → U.S.; 03 Greedo → California; 03 Greedo → Los Angeles; -minu → Switzerland; -minu → Basel; 'Matšepo Ramakoae → Morija
* `dbp:products` / IN: 2.13.61 → Record company; 2.13.61 → Publisher; 24 Frames Factory → Films; 1worldspace → Satellite Radio; 1 Maja Coal Mine → Coal; 2 Minute Medicine → News agency
* `dbp:battles` / IN: 38 National Guard Command → Great Offensive; 38 National Guard Command → Battle of Bizani; 38 National Guard Command → Greco-Turkish War (1919–1922); 38 National Guard Command → Battle of Sarantaporo; 38 National Guard Command → Battle of Kresna Gorge; 38 National Guard Command → Battle of Yenidje
* `dbp:deathPlace` / IN: 'Mamohato Bereng Seeiso → Thaba-Tseka District; 'Mamohato Bereng Seeiso → Mantsonyane; 16 Martyrs of Japan → Japan; 16 Martyrs of Japan → Nagasaki; 'Abd al-Ilah → Baghdad; 'Abd al-Ilah → Arab Federation
* `dbp:settlementType` / OUT: 2nd arrondissement of Parakou → Arrondissements of Benin; 24 de Diciembre → Corregimientos of Panama; 1e Exloërmond → Village; 11th ward, Chicago → Chicago City Council; 27 de Noviembre District → Districts of Peru; 15th of May (city) → List of cities and towns in Egypt

## 4. Every other SAFE_TO_TEMPLATE candidate (T2 minus T1)

| key | proposed template | edges | R* facts blocked | arm-C items unlocked | scientific reason |
|---|---|---:|---:|---:|---|
| `dbp:leader` / OUT | <object> is recorded as a leader of <answer>. | 38273 | 3 | 1 | 38,273 edges; subjects are legislatures/parties/polities, objects are persons; neutral wording covers head-of-state and party-leader uses. |
| `dbp:combatant` / OUT | <object> was a combatant in <answer>. | 8786 | 3 | 0 | 8,786 edges; subjects are conflicts, objects are polities/forces; one reading. |
| `dbp:partof` / IN | <subject> was part of <answer>. | 10434 | 3 | 0 | 10,434 edges; values are larger events or structures; 'was part of' is faithful for both. |
| `dbp:subdivisionName` / OUT | <answer> is part of <object>. | 1155813 | 2 | 13 | 1,155,813 edges; the containing unit at any level; the same slot the semantic policy already uses for place containment. |
| `dbp:leader` / IN | <answer> is recorded as a leader of <subject>. | 38273 | 2 | 7 | as leader/OUT. |
| `dbp:monarch` / IN | <answer> was the reigning monarch for <subject>. | 13249 | 2 | 4 | 13,249 edges; subjects are parliaments, legislatures and year pages; the neutral wording is faithful for all of them. |
| `dbp:location` / OUT | The location of <answer> is <object>. | 739763 | 2 | 1 | 739,763 edges over sites, buildings and events; the neutral wording is true for every family (a building is located in, an event took place in). |
| `dbp:cultCenter` / IN | <answer> was a cult centre of <subject>. | 299 | 2 | 0 | 299 edges; deities -> cities; unambiguous. |
| `dbp:dedication` / IN | <subject> is dedicated to <answer>. | 4933 | 2 | 0 | 4,933 edges; identical semantics to the existing dedicatedTo/IN template. |
| `dbp:timezone` / OUT | <answer> is in the <object> time zone. | 314303 | 1 | 22 | 314,303 edges; values are time zones; a non-discriminating context fact (support 4 is typical). |
| `dbp:dynasty` / OUT | <answer> belonged to the dynasty <object>. | 3119 | 1 | 8 | 3,119 edges; values are dynasties (Abbadid, Umayyad, Timurid); the neutral wording tolerates the rare polity value (Kingdom of Jimma). |
| `dbp:combatant` / IN | <answer> was a combatant in <subject>. | 8786 | 1 | 7 | as combatant/OUT. |
| `dbp:candidate` / IN | <answer> was a candidate in <subject>. | 170019 | 1 | 4 | 170,019 edges; elections -> candidates; 'None of the above' is a genuine ballot option, not a placeholder. |
| `dbp:country` / IN | The country recorded for <subject> is <answer>. | 142785 | 1 | 2 | 142,785 edges over works, buildings, events and organisations; only the neutral wording is faithful across families (a film's country of production, a building's country). |
| `dbp:allegiance` / IN | The allegiance of <subject> was to <answer>. | 17016 | 1 | 1 | 17,016 edges; units/persons -> nations; one reading. |
| `dbp:issue` / OUT | <object> was a child of <answer>. | 17689 | 1 | 1 | 17,689 edges; royalty/nobility children; one reading. |
| `dbp:affiliation` / IN | <subject> is affiliated with <answer>. | 13445 | 1 | 0 | 13,445 edges; one reading. |
| `dbp:builder` / IN | <subject> was built by <answer>. | 9413 | 1 | 0 | 9,413 edges; unambiguous. |
| `dbp:canonizedBy` / OUT | <answer> was canonized by <object>. | 765 | 1 | 0 | 765 edges; unambiguous. |
| `dbp:deity` / IN | <subject> is dedicated to the deity <answer>. | 1933 | 1 | 0 | 1,933 edges; temples -> deities; unambiguous. |
| `dbp:disease` / OUT | <answer> was an outbreak of <object>. | 593 | 1 | 0 | 593 edges; epidemics -> diseases; unambiguous. |
| `dbp:father` / IN | <answer> was the father of <subject>. | 25442 | 1 | 0 | 25,442 edges; mirrors the existing father/OUT template. |
| `dbp:ideology` / IN | <answer> is an ideology of <subject>. | 29171 | 1 | 0 | 29,171 edges; parties/movements -> ideologies; unambiguous. |
| `dbp:place` / OUT | <answer> took place in <object>. | 49999 | 1 | 0 | 49,999 edges; events, protests, plays -> places/theatres; 'took place in' is faithful. |
| `dbp:presidentCandidate` / IN | <answer> was a presidential candidate in <subject>. | 113 | 1 | 0 | 113 edges; unambiguous. |
| `dbp:spouse` / IN | <subject> was married to <answer>. | 57650 | 1 | 0 | 57,650 edges; mirrors the existing spouse/OUT template. |
| `dbp:treatment` / IN | <subject> is treated with <answer>. | 637 | 1 | 0 | 637 edges; diseases -> treatments; unambiguous. |
| `dbp:location` / IN | The location of <subject> is <answer>. | 739763 | 0 | 27 | as location/OUT. |
| `dbp:primeminister` / IN | <answer> was prime minister during the term of <subject>. | 26863 | 0 | 8 | 26,863 edges; subjects are ministers, presidents and other office holders; the neutral wording is faithful for all (Kalam -> Vajpayee). |
| `dbp:cities` / IN | <answer> is listed among the cities of <subject>. | 11635 | 0 | 6 | 11,635 edges; the neutral wording is true for summits (host city) and areas (member city). |
| `dbp:place` / IN | <subject> took place in <answer>. | 49999 | 0 | 6 | as place/OUT. |
| `dbp:governmentType` / OUT | <answer> has the form of government <object>. | 19453 | 0 | 5 | 19,453 edges; values are government forms (Panchayati raj, Mayor–council, Monarchy); neutral wording. |
| `dbp:subdivisionName` / IN | <subject> is part of <answer>. | 1155813 | 0 | 4 | as subdivisionName/OUT. |
| `dbp:today` / OUT | The territory of <answer> is today part of <object>. | 4434 | 0 | 4 | 4,434 edges; unambiguous. |
| `dbp:venue` / IN | <subject> was held in <answer>. | 88531 | 0 | 4 | 88,531 edges; values mix venues, cities and countries; 'held in' is faithful for all three. |
| `dbp:capital` / IN | <answer> was the capital of <subject>. | 6304 | 0 | 3 | 6,304 edges; unambiguous. |
| `dbp:commonLanguages` / OUT | <object> was a common language of <answer>. | 4523 | 0 | 3 | 4,523 edges; polities -> languages; unambiguous. |
| `dbp:capital` / OUT | <object> was the capital of <answer>. | 6304 | 0 | 2 | as capital/IN. |
| `dbp:material` / IN | <subject> is made of <answer>. | 2992 | 0 | 2 | 2,992 edges; unambiguous. |
| `dbp:popplace` / IN | <subject> has a significant population in <answer>. | 5236 | 0 | 2 | 5,236 edges; the ethnic-group infobox slot means exactly this. |
| `dbp:royalHouse` / OUT | <answer> belonged to the royal house <object>. | 1234 | 0 | 2 | 1,234 edges; unambiguous. |
| `dbp:epochs` / IN | <subject> is dated to the epoch <answer>. | 2122 | 0 | 1 | 2,122 edges; sites -> periods; neutral wording also covers a polity used as a period value (Roman Empire 81). |
| `dbp:nominee` / IN | <answer> was a nominee in <subject>. | 11835 | 0 | 1 | 11,835 edges; elections -> nominees; unambiguous. |

## 5. NEEDS_HUMAN_REVIEW — a template is proposed, the human decides

| key | proposed template (if adopted) | edges | R* facts blocked | arm-C items unlocked | why it is not admitted blind |
|---|---|---:|---:|---:|---|
| `dbp:regent` / IN | <answer> is recorded as regent for <subject>. | 3298 | 5 | 1 | 3,298 edges; the slot mixes monarch-regent pairs with deputy lists on politician infoboxes (Abdul Ghani Baradar -> five deputies); direction of the relation is not uniform. |
| `dbp:leaderName` / OUT | <object> is recorded as a leader of <answer>. | 25097 | 4 | 0 | 25,097 edges; 1.5% non-resource values and frequent council/body values (Edmonton City Council 324, Indonesia) mixed with persons. |
| `dbp:after` / IN | <subject> was followed by <answer>. | 183863 | 3 | 6 | 183,863 edges across offices, buildings and expeditions; 'followed by' is faithful, but the placeholder value 'Incumbent' (262 edges) would render as a person; needs an object-level exclusion first. |
| `dbp:before` / OUT | <answer> was preceded by <object>. | 182601 | 3 | 5 | as before/IN. |
| `dbp:wars` / IN | <subject> is associated with <answer>. | 7665 | 3 | 1 | 7,665 edges; subjects are cartridges and units (.45-70 -> Indian Wars); 'took part in' is wrong for an object, and the neutral wording is weak. |
| `dbp:titleLeader` / OUT | The leader of <answer> held the title <object>. | 1847 | 3 | 0 | 1,847 edges; values mix titles (Sultan, King) with list pages (List of Governors of Alabama, Monarchy of Greece). |
| `dbp:after` / OUT | <answer> was followed by <object>. | 183863 | 2 | 3 | as after/IN (Incumbent placeholder). |
| `dbp:event` / IN | <subject> belongs to the event <answer>. | 18462 | 2 | 0 | 18,462 edges; mixes competition editions (1911 FA Charity Shield -> FA Community Shield) with athletes' disciplines (Marathon 644). |
| `dbp:school` / OUT | <answer> is associated with the school <object>. | 13684 | 2 | 0 | 13,684 edges; polysemous: Buddhist schools (Theravada 141), high schools, and draft-pick schools on team-season pages. |
| `dbp:before` / IN | <subject> was preceded by <answer>. | 182601 | 1 | 2 | 182,601 edges; same placeholder risk as after (Incumbent 19); otherwise faithful. |
| `dbp:regent` / OUT | <object> is recorded as regent for <answer>. | 3298 | 1 | 1 | same slot as regent/IN; same polysemy. |
| `dbp:commander` / OUT | <object> commanded <answer>. | 22230 | 1 | 0 | 22,230 edges; values include rank labels (Admiral 66, General 36, Major General 32) that would render as persons. |
| `dbp:constituency` / OUT | <answer> represented the constituency <object>. | 29954 | 1 | 0 | 29,954 edges; subjects include elections whose `constituency` lists ALL constituencies (1999 National Assembly for Wales election -> 40 values); wrong for those. |
| `dbp:establishedEvent` / IN | <subject> was established through <answer>. | 964 | 1 | 0 | 964 edges; values mix events, documents and polities (Albania -> Principality of Albania); the reading is not uniform. |
| `dbp:eventStart` / OUT | <answer> began with <object>. | 792 | 1 | 0 | 792 edges; the placeholder 'Wikt:establishment' (21) would render as an event. |
| `dbp:field` / IN | <subject> worked in the field of <answer>. | 31049 | 1 | 0 | 31,049 edges; mostly disciplines (Painting 2,864, Mathematics 850) but the same slot is the BALLPARK on baseball-season pages (2019 Tohoku Rakuten Golden Eagles season -> Rakuten Seimei Park); the fields/IN reading would be wrong there. The alias family admits the pair for evidence lookup; a template needs the same polysemy audit. |
| `dbp:language` / OUT | The language of <answer> is <object>. | 74024 | 1 | 0 | 74,024 edges; 'Silent film' (3,248) is used as a language value on film pages; needs an exclusion before a template. |
| `dbp:product` / IN | <subject> lists <answer> among its products. | 170 | 1 | 0 | 170 edges only; subjects include advertisements and processes (Alberta Taciuk process -> Shale oil); too small and mixed to admit blind. |
| `dbp:stadium` / IN | <answer> appears as a match venue of <subject>. | 577960 | 0 | 22 | 577,960 edges from 90,432 season/competition subjects; values mix stadiums (Croke Park) and cities (Dublin 1,649); the subject is a season article, so the learner-facing content ('a match of the 2010–11 season was played in A') is weak; needs the human's pedagogical call. |
| `dbp:city` / IN | <subject> is based in <answer>. | 142299 | 0 | 12 | 142,299 edges; values include countries and states (United States, Ontario) and subjects include songs; the slot is used loosely. |
| `dbp:succession` / OUT | <answer> held the title <object>. | 9635 | 0 | 10 | 9,635 edges; values mix titles (Emperor of Japan, Queen consort, Regent) with list pages (List of Burmese monarchs) and places (Lesotho). |
| `dbp:house` / OUT | <answer> belonged to the house <object>. | 11767 | 0 | 8 | 11,767 edges; royal houses on person pages but LEGISLATIVE houses on election pages (1896 Queensland colonial election -> Legislative Assembly); polysemous. |
| `dbp:officeholder` / IN | <answer> is recorded as an office holder of <subject>. | 13133 | 0 | 3 | 13,133 edges from 943 subjects (army pages listing commanders); the relation is 'commanded' for armies and 'held' for offices. |
| `dbp:president` / IN | <answer> was president during <subject>. | 34831 | 0 | 3 | 34,831 edges; national presidents on officeholder pages and CLUB presidents on team-season pages (1883 Brooklyn Grays season -> Charlie Byrne); the neutral wording holds but the pedagogical content differs sharply. |
| `dbp:ground` / IN | <answer> is the home ground of <subject>. | 30948 | 0 | 2 | 30,948 edges; values include countries (Italy 435, Brazil 360) where 'home ground' is wrong. |
| `dbp:nominator` / IN | <subject> was nominated by <answer>. | 3113 | 0 | 2 | 3,113 edges; elections list institutions as nominators (Local government in the Republic of Ireland); mixed. |
| `dbp:premier` / IN | <answer> was the premier for <subject>. | 3696 | 0 | 2 | 3,696 edges; cabinets and lieutenant-governors as subjects; the wording differs by family. |
| `dbp:areaServed` / IN | <subject> serves <answer>. | 13394 | 0 | 1 | 13,394 edges; subjects include postcode districts (01527 -> Catshill) where 'serves' is wrong. |
| `dbp:observedby` / IN | <subject> is observed by <answer>. | 876 | 0 | 0 | 876 edges; values mix countries, religions and 'UN Members'; 'observed by' misreads a country value. |

## 6. REJECT

| key | edges | R* facts blocked | reason |
|---|---:|---:|---|
| `dbp:name` / IN | 811971 | 2 | 811,971 edges with 35,028 subjects: squad lists, award lists and other layout uses of the `name` slot; no relation semantics. |
| `dbp:honorificPrefix` / OUT | 35120 | 2 | Prompt 8H-B2-G §4 decision: a form of address, not a fact; no template and no tier. |
| `dbp:subdivisionType` / OUT | 1316726 | 1 | 1,316,726 edges; the LABEL of the subdivisionName slot (List of sovereign states, U.S. state, Voivodeships of Poland); renders as nonsense ('A's subdivision type is List of sovereign states'). Candidate for an upstream layout-slot rejection, outside this task. |
| `dbp:postalCodeType` / OUT | 88309 | 1 | 88,309 edges; the LABEL of the postal-code slot (ZIP code, Postal Index Number); layout metadata. |
| `dbp:examples` / IN | 21 | 1 | 21 edges; a list slot without relation semantics. |
| `dbp:including` / IN | 104 | 1 | 104 edges; a vague 'including' list of a period page. |
| `dbp:northeast` / OUT | 14513 | 1 | 14,513 edges; a compass-navigation slot of the settlement infobox, not a fact about the entity. |
| `dbp:othernames` / OUT | 98 | 1 | 98 edges; an alias/name slot; rendering it would print another name of the Answer. |
| `dbp:type` / IN | 227969 | 1 | 227,969 edges of a generic classification slot (Album, Public company); no relation between two entities. |
| `dbp:with` / IN | 16074 | 1 | 16,074 edges; 'with' = fellow member of a multi-member seat; no expressible relation. |
| `dbp:posthumousName` / OUT | 129 | 0 | 129 edges of which 128 point at the page 'Posthumous name' itself: a placeholder, not a value. |
| `dbp:source` / OUT | 23394 | 0 | 23,394 edges; 49.6% non-resource values (URLs, book ids); an external-reference slot. |
| `dbp:blankNameSec` / OUT | 12552 | 0 | 12,552 edges; a blank-section label slot (Human Development Index, Köppen climate classification). |
| `dbp:timezoneDst` / OUT | 130738 | 0 | 130,738 edges; a technical duplicate of timezone with no additional learner content. |

## 7. What the templates would repair (Measured, frozen selections)

| group | items | T0 `R*` fully verbalizable | T1 | T2 | recovered by T1 | recovered by T2 | still unresolved under T2 | arm-C ≥1 pre clue: T0 | T1 | T2 | arm-C mandatory-only: T0 | T2 | arm-C ≥3: T0 | T2 |
|---|---:|---|---|---|---|---|---|---|---|---|---|---|---|---|
| POOLED | 396 | 220/396 (55.56%) | 316/396 (79.8%) | 350/396 (88.38%) | 96/396 (24.24%) | 130/396 (32.83%) | 46/396 (11.62%) | 132/396 (33.33%) | 147/396 (37.12%) | 193/396 (48.74%) | 264/396 (66.67%) | 203/396 (51.26%) | 61/396 (15.4%) | 109/396 (27.53%) |
| GROUP:CHEMISTRY | 40 | 10/40 (25.0%) | 35/40 (87.5%) | 36/40 (90.0%) | 25/40 (62.5%) | 26/40 (65.0%) | 4/40 (10.0%) | 5/40 (12.5%) | 7/40 (17.5%) | 8/40 (20.0%) | 35/40 (87.5%) | 32/40 (80.0%) | 2/40 (5.0%) | 4/40 (10.0%) |
| GROUP:EVENT | 34 | 1/34 (2.94%) | 19/34 (55.88%) | 26/34 (76.47%) | 18/34 (52.94%) | 25/34 (73.53%) | 8/34 (23.53%) | 0/34 (0.0%) | 1/34 (2.94%) | 1/34 (2.94%) | 34/34 (100.0%) | 33/34 (97.06%) | 0/34 (0.0%) | 1/34 (2.94%) |
| GROUP:PERSON | 240 | 207/240 (86.25%) | 207/240 (86.25%) | 220/240 (91.67%) | 0/240 (0.0%) | 13/240 (5.42%) | 20/240 (8.33%) | 118/240 (49.17%) | 118/240 (49.17%) | 125/240 (52.08%) | 122/240 (50.83%) | 115/240 (47.92%) | 57/240 (23.75%) | 66/240 (27.5%) |
| GROUP:PLACE | 47 | 0/47 (0.0%) | 31/47 (65.96%) | 38/47 (80.85%) | 31/47 (65.96%) | 38/47 (80.85%) | 9/47 (19.15%) | 0/47 (0.0%) | 10/47 (21.28%) | 39/47 (82.98%) | 47/47 (100.0%) | 8/47 (17.02%) | 0/47 (0.0%) | 28/47 (59.57%) |
| GROUP:POLITY | 35 | 2/35 (5.71%) | 24/35 (68.57%) | 30/35 (85.71%) | 22/35 (62.86%) | 28/35 (80.0%) | 5/35 (14.29%) | 9/35 (25.71%) | 11/35 (31.43%) | 20/35 (57.14%) | 26/35 (74.29%) | 15/35 (42.86%) | 2/35 (5.71%) | 10/35 (28.57%) |
| BATCH:answers | 280 | 217/280 (77.5%) | 242/280 (86.43%) | 256/280 (91.43%) | 25/280 (8.93%) | 39/280 (13.93%) | 24/280 (8.57%) | 123/280 (43.93%) | 125/280 (44.64%) | 133/280 (47.5%) | 157/280 (56.07%) | 147/280 (52.5%) | 59/280 (21.07%) | 70/280 (25.0%) |
| BATCH:hist | 116 | 3/116 (2.59%) | 74/116 (63.79%) | 94/116 (81.03%) | 71/116 (61.21%) | 91/116 (78.45%) | 22/116 (18.97%) | 9/116 (7.76%) | 22/116 (18.97%) | 60/116 (51.72%) | 107/116 (92.24%) | 56/116 (48.28%) | 2/116 (1.72%) | 39/116 (33.62%) |

Keys of the `R*` facts that stay template-less under T2 (48 facts in 46/396 (11.62%) items): `regent/IN` 5, `leaderName/OUT` 4, `after/IN` 3, `before/OUT` 3, `titleLeader/OUT` 3, `wars/IN` 3, `after/OUT` 2, `event/IN` 2, `honorificPrefix/OUT` 2, `name/IN` 2, `school/OUT` 2, `before/IN` 1, `commander/OUT` 1, `constituency/OUT` 1, `establishedEvent/IN` 1, `eventStart/OUT` 1, `examples/IN` 1, `field/IN` 1, `including/IN` 1, `language/OUT` 1, `northeast/OUT` 1, `othernames/OUT` 1, `postalCodeType/OUT` 1, `product/IN` 1, `regent/OUT` 1, `subdivisionType/OUT` 1, `type/IN` 1, `with/IN` 1. All of them are NEEDS_HUMAN_REVIEW or REJECT keys by construction.

**Reading.** Five templates (T1) recover 96 of the 176 template-less items
(persons unchanged, chemistry 25/40, places 31/47, polities 22/35, events
18/34); the 48 SAFE templates (T2) recover 130 and leave 46 items (11.6 %)
with a template-less `R*` fact, all on keys that need a human call or are
rejected. For pre-answer context the effect is concentrated where the loss
was: places go from 0/47 to 39/47 items with an admissible arm-C clue, the
historical batch from 9/116 to 60/116, while persons move only from 118/240
to 125/240 because their loss is grounding (`ABSENCE_ONLY`), not templates.
Arm B and arm C coincide at every level here (the A-excluding support-3 rule
removes no last group).

## 8. Proposed expansion protocol (nothing here is executed by this task)

1. **Phase 1 — the five high-impact keys** (all SAFE): add the five templates
   to a NEW versioned policy file (`predicate_policy_v3.json`, `supersedes`
   v2 with its SHA-256), never by editing v2; add one unit test per template
   rendering the deterministic census examples; record the census digest in
   the policy notes.
2. **Phase 2 — the remaining 43 SAFE keys**, in the impact order of §4, same
   discipline. Neutral readings are deliberately stilted where a family-specific
   verb would be unsafe; that is a presentation cost the human may prefer to
   pay for faithfulness.
3. **Phase 3 — the 29 NEEDS_HUMAN_REVIEW keys**: the human decides key by key.
   Several need an object-level exclusion before any template (`after`/`before`
   with `Incumbent`, `language` with `Silent film`, `commander` with rank
   labels, `eventStart` with `Wikt:establishment`); `field/IN` needs the same
   polysemy audit the alias family should have had (ballpark vs discipline);
   `stadium/IN` and `president/IN` are a pedagogical call, not a fidelity one.
4. **Never**: a template added to rescue one Answer; a template on a REJECT key;
   an unrestricted predicate-label verbalizer.
5. **After adoption**: the ARCH-3 and ARCH-3R sweeps must be re-run on the new
   policy version (the manifest records `quality_policy_sha256`), because
   verbalizability enters pre-answer admissibility.

## 9. What remains human

Whether to adopt Phase 1 alone or Phases 1–2, the 29 review verdicts, whether
neutral readings are acceptable prose for the human study, and whether
`subdivisionType`/`postalCodeType`/`blankNameSec` should become upstream
layout-slot rejections (outside this task).
