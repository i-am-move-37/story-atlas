# Research plan: finding gaps in the space of stories

Status: **draft, not locked.** The plan gets locked when it's committed to git, before any atoms are extracted from the corpus. After that, any change is written in the deviation log with its date and reason.

Decisions still open are marked **▶ Decision**, each with options and Claude's lean. Settled choices name the date they were made.

---

## 1. Question and hypotheses

### The question
Can a model trained on the building blocks ("atoms") of existing films and novels find story premises that are **coherent** (they hang together as a story) and **unexplored** (unusual for the genre traditions they draw on), and are those premises **more interesting to human judges** than premises found by simpler methods?

This adapts Hernández et al., *The Alien Space of Science* (arXiv 2603.01092), from research papers to stories. Their availability context is *who* could have written it (author repertoires). Ours is *which tradition* it belongs to: genre × era.

### Terms
- **Atom:** a reusable story building block, e.g. "a hard-boiled detective investigates a death among teenagers," extracted from plot summaries by an LLM and clustered into a fixed vocabulary.
- **Coherence:** how likely a set of atoms is to occur together in a real story, according to a model trained on real stories.
- **Availability:** how expected a set of atoms is *within a given genre's history up to a given era*. A combination is **unavailable** when it's coherent in general but rare in that tradition's context, as high-school atoms were for noir before Brick.
- **Gap:** a combination that is high in coherence and low in availability.

### Hypotheses

**H1: The coherence model has learned what real stories look like.** *(Confirmatory.)*
On held-out works from the grouped random split, the model rates real atom combinations as more coherent than (a) shuffled combinations that match each work's atom count and genre mix, and (b) the coherence the pair-counting baseline assigns.
- Test: grouped random split (remakes, adaptations and franchise entries stay on one side).
- Why it matters: if H1 fails, the model can't tell a story from a jumble, and everything downstream is noise.

**H2: Gaps found before a cutoff tend to get filled after it.** *(Confirmatory.)*
Training only on works before 2005, and looking only at combinations never done in a genre before 2005, the ones the model ranks highest show up in 2005–2017 works more often than (a) random never-done combinations built from equally common atoms, (b) the ones the counting baseline ranks highest and (c) the ones trend extrapolation ranks highest. *(Reworded 2026-11-10; the floor was "random combinations of equal coherence." See the decision in section 5.)*
- Test: temporal split, 2005 cutoff, run once. Tuned only on the 1972, 1982 and 1992 rehearsals.
- Why it matters: it's the one test of "unexplored but promising" that doesn't depend on anyone's taste. It's evidence that the gaps are real places the culture was heading.

**H3: The model's premises are more interesting.** *(Confirmatory. **Primary**: the paper stands or falls on it. Decided by Scott, 2026-11-06.)*
Premises decoded from the model's top gaps are judged more interesting, in blind pairwise comparisons, than premises decoded from (a) the counting baseline's top gaps and (b) random coherent combinations. All premises are written by the same LLM decoder, in the same format and length.
- Test: the human-evaluation protocol, locked separately before any premises exist.
- **H3b** *(confirmatory, separate; added 2026-11-10):* the model's premises are also compared with those of a frontier LLM that picks atom combinations directly (section 4). It's reported whatever the outcome, but H3 doesn't depend on it.
- Why it matters: this is the success criterion Scott named. Does it produce exciting story ideas?

**H4: Unexplored stories have more variable reception.** *(Exploratory.)*
Among films released 2005–2017, the more unavailable a film's atoms were at release, the wider the spread of its reception (return on budget, audience ratings), more than any shift in the average. This would echo the finding that atypical combinations in science raise the chance of both hits and misses (Uzzi et al., *Science*, 2013).
- Data: TMDB budget and revenue need a re-pull; ratings are already in hand. Films only.
- Why exploratory: execution (the Rian Johnson problem), marketing and budget confound it, and the data isn't collected yet.

**Further exploratory questions** (reported as exploratory, no claims made):
- **The β sweet spot:** do judges prefer premises at a middle setting of the coherence–novelty trade-off rather than at either extreme?
- **Mash-ups:** are works surprising against *both* of their genres (as Brick is) rated or received differently from works surprising against only one?
- **Genre differences:** which genres have the most open space, and has that changed by decade?
- **Atoms that light each other up:** pairs that score higher together than either does alone.

### ▶ Decisions for Scott
1. ~~Which hypothesis is primary?~~ **Decided 2026-11-06: H3.** H1 and H2 are confirmatory supporting hypotheses.
2. ~~H4: confirmatory or exploratory?~~ **Decided 2026-11-06: exploratory.**
3. ~~What counts as "beats the baseline"?~~ **Decided 2026-11-06: confidence interval.** A win means the 95% confidence interval of the difference excludes zero; the effect size is always reported.
4. ~~Correcting for multiple tests.~~ **Decided 2026-11-06: Holm**, across the confirmatory tests (H1, H2, H3, and H3b since 2026-11-10), with the overall false-win rate held at 5%. The intervals reported for the confirmatory tests are adjusted to match, so an interval and its test always agree.

**Section 1 has no open decisions left.**

---

## 2. Corpus and temporal design
*Drafted 2026-11-06; decisions agreed with Scott.*

### 2.1 Corpus
- **Works:** films and novels whose plot summaries run 300+ words, from CMU Movie Summaries, Wikipedia Movie Plots, WikiPlots and CMU Book Summaries. TMDB overviews are too short to qualify.
- **Deduplication:** copies of the same work across sources merge into one work. The longest summary is kept as the source text, and the earliest reliable year becomes the work's year. **Versions are not merged into one longer summary** (considered 2026-11-10): the copies are mostly snapshots of the same Wikipedia article, stitching them would need an LLM at the foundation, and famous works have more copies, so merging would give them richer inputs. The summary-stability check (6.2) shows whether that should be revisited. A rough title-and-year dedupe gives about 25.6k films and 8.7k novels (2026-11-04); the real dedupe also uses Wikipedia/Wikidata IDs.
- **Scope: feature films and novels (added 2026-11-10, from the labeling pilot).** Scott's blank-page 50 turned up a Bugs Bunny short, a book of the Bible, a Shakespeare play and a work by Freud.
  - **Films are features only** (decided by Scott, 2026-11-10): 40 minutes or longer, the Academy's line. Shorts are identified by Wikidata's type, by runtime, and by pages that are filmographies of shorts. Reasons: a gag cartoon doesn't have the story shape the ten facets describe, and about a thousand shorts concentrated in the 1930s–50s would distort those decades' genre histories.
  - **"Novels" means narrative prose fiction** (decided by Scott, 2026-11-10): plays, poetry, comics, scripture, philosophy, non-fiction, series pages and short story collections are out. **Short stories stay** (Scott: they're the closest thing to feature-sized), as do novellas and tales. A non-fiction genre label puts a book out only when nothing else marks it as fiction, so philosophical and autobiographical novels stay.
  - **An untagged WikiPlots title takes its medium from Wikidata's type for that page**, not from a title match with another source. (*The Iceman Cometh* is the play, though a film shares its title.)
  - **Measured 2026-11-11:** 1,119 of 26,639 films are shorts, leaving 25,520; 1,064 of 10,948 books are out (508 plays, 237 non-fiction, 104 comics, 93 poetry, 49 collections, 42 series pages, 16 scripture, 13 philosophy, 2 other), leaving 9,884. Checked against Scott's 50 blank-page works: 8 were out of scope and the rules find 7. The miss is a non-fiction book with no telling metadata.
  - **Second check:** when the corpus is labeled, the labeling model is also asked whether each work is narrative fiction.
  - Works stay in the table with the reason they're out of scope, so the filter can be audited. Out-of-scope works in the pilot sample are left out of the scoring.
- **Dates:** WikiPlots years are recovered from title tags ("(1979 film)") and from matches to other sources. Undated works (about 2.4k films and 3.4k novels on the rough count) are used in the random split only.

### 2.2 Length drift
Film summaries grow longer by era (median about 465 words in the 1920s, 667 in the 2010s). Longer summaries would yield more atoms per work, which would inflate H2's hit rate and make later decades look denser.
- **Standard-length rewrite:** before extraction, an LLM rewrites every summary into a fixed-length account of the story's engine (premise, central conflict, how it turns), following Alien Space of Science's blog step.
- **Atom cap:** each work keeps at most *m* atoms per facet (section 3.2). *m* is tuned on the rehearsals; the procedure is fixed here, not the value.
- **Check:** in each rehearsal, atoms per work are plotted by decade. If the slope remains, it's logged as a deviation and length is added as a covariate.

### 2.3 Genre and era labels
- **Scheme:** `docs/genre-scheme-draft.md` (7 families → 44 genres → 217 subgenres; multi-label; shared across film and novel). Era bins are decades from 1910 (films) and 1900 (novels), with wider bins before that and backoff to neighboring decades and parent genres for thin cells.
- **Labeling pilot:** about 200 works, stratified by decade, medium, source and fame. Each is labeled three ways: Wikidata's genre field, an LLM given only title, year and creator, and an LLM given the plot. The gold set comes from Scott: 50 works labeled from scratch (to measure accuracy without anchoring) and 150 checked and corrected.
  - **Scott labels the work itself, not just its summary** (2026-11-10): the summary as a reminder, plus what he knows, plus a quick lookup for works he hasn't seen. A gold set made from the summary alone would favor the method that reads only the summary.
  - **The draft for the 150** is the labels from all three methods pooled, with no sign of which method suggested which, so it can't tilt him toward one of them. Comparing the 50 with the 150 shows how much the draft anchored him.
- **Selection rule (fixed before scoring):** pick the method, or a hybrid by availability, with the best accuracy (micro-F1 against the gold set) among those covering at least 90% of works. When two are within 2 points of F1, prefer the one farther from our plot text: Wikidata, then metadata-only LLM, then plot LLM.
  - **How the score is computed (fixed 2026-11-10, before the pilot):** the contest is scored on **genre-level labels** (the 44); a method's subgenre labels count as their parent genre. Subgenre accuracy is reported but doesn't pick the winner. **Borderline labels neither help nor hurt:** a method must find the gold set's core labels, and it isn't penalized for including or omitting a genre the gold set marks borderline. A work a method gives no label to counts as not covered. The 50 blank-page works and the 150 corrected works are scored together; each set's score is also reported separately.
  - **Details the rule left open (proposed 2026-11-11, written into `scripts/score_pilot.py` before any score was computed; Scott to confirm before it runs):**
    - **Candidates:** the three methods and four hybrids by availability (Wikidata then metadata; Wikidata then plot; metadata then plot; all three in that order). A hybrid takes the first source that gives any label.
    - **A method's own borderline labels count as its labels,** because the main analysis uses all labels. The score counting only the labels a method called core is reported beside it.
    - **An empty answer is not covered,** even when an LLM returns an empty list on purpose. The number of scored works with no gold label is reported, so we can see whether this matters.
    - **The 2-point tie for hybrids:** the tie goes to the candidate that takes the smallest share of works from the plot method, then the smallest share from the metadata method.
    - **κ for a label** leaves out the works where the gold set marks that label borderline, matching how the score treats borderline.
    - **Scored works:** the ones Scott labeled (not skipped) that the scope rules keep.
- **Core or borderline (added 2026-11-10):** each genre label on a work is marked *core* (the work plainly belongs to the tradition) or *borderline* (a defensible stretch, like calling Brick a neo-western). All labels are used in the main analysis; H2 is rerun with core labels only (section 6.2).
- **Subgenre reliability (two-part rule, 2026-11-10):** a label whose agreement is poor (Cohen's κ below 0.4) is merged into its parent. With 200 pilot works and 217 subgenres, most subgenres have too few pilot examples for κ to mean anything, so agreement is measured in two places:
  - **Against Scott's gold set**, for all 44 genres and for any subgenre with at least 5 gold examples in the pilot.
  - **Between the two best automatic methods across the whole corpus**, for every other subgenre. No human is involved, so this measures consistency rather than correctness; it applies Scott's principle of splitting until labelers stop agreeing.
- **Reviewed with Scott (2026-11-10), no longer "proposed":** 90% coverage, the 2-point tie and the κ cutoff of 0.4.

### 2.4 Splits
- **Grouped random split** (H1): works are linked into groups (remakes, matched by the same title in different years; adaptations, matched by the same title across film and novel; and Wikidata's based-on, series and remake links, with an LLM checking borderline cases). Each group goes entirely to one side. Proposed sizes: 80% train, 10% validation, 10% test. **Loose retellings** (*West Side Story* from *Romeo and Juliet*) are deliberately not grouped, since moving old stories into new genres is the phenomenon under study; they're listed as a threat.
- **Temporal split** (H2): test cutoff 2005, test years 2005–2017, run once. Rehearsal cutoffs 1972, 1982 and 1992, each with a 12-year window (1972–83, 1982–93, 1992–2003), used for all tuning. **Post-2005 works that are remakes, sequels or adaptations of pre-2005 works can't count as H2 hits.**
- **No leakage across the cutoff:** for each temporal run, the atom vocabulary, genre backoff statistics and every tuned setting come from pre-cutoff works only.

## 3. Atom vocabulary and what gets tuned
*Drafted 2026-11-09; decisions agreed with Scott.* It adapts the Alien Space of Science pipeline (summary → extraction → rate and repair → embed → cluster → name).

### 3.1 Typed atoms: ten facets
Atoms are extracted and clustered **separately for each facet** (not as one pool, as in the original). This keeps a setting from ever clustering with a plot twist, makes gaps readable ("noir conflict engine + high-school setting"), and gives every combination the shape of a pitch, which makes decoding easier.

| # | Facet | What it captures |
|---|---|---|
| 1 | Setting / world | Where and when, and the world's rules |
| 2 | Protagonist type | Who the story follows |
| 3 | Want | What the protagonist consciously pursues, **tagged internal or external** (a tag, not clustered) |
| 4 | Need | What the protagonist must learn or become; **"none / unclear" allowed** |
| 5 | Antagonist / opposing force | Who or what stands in the way |
| 6 | Inciting situation | What sets the story in motion |
| 7 | Central conflict engine | The mechanism that keeps generating conflict |
| 8 | Structural device | Unreliable narrator, ticking clock, parallel timelines, etc. |
| 9 | Tone | The register: fatalistic, whimsical, satirical... |
| 10 | Ending shape | How the story resolves, **including whether the need is met, refused or met too late** |

Accepted cost: the facet list imposes a theory of story structure. It's stated plainly in the write-up as a design choice.

### 3.2 Pipeline
1. **Engine summary** (section 2.2): a standard-length rewrite of each plot.
2. **Extraction:** an LLM extracts atoms per facet. Each atom must pass a **transfer test**: it makes sense without the title, and another story could use it ("Marty McFly" fails; "a teenager accidentally travels back to his parents' youth" passes). Each atom must **cite the passage of the summary that supports it**, which matters most for the need facet, since summaries rarely state it outright.
   - **Distilled extractor (Scott trains it; decided 2026-11-10).** A frontier LLM extracts atoms for a few thousand works (the teacher). Scott fine-tunes a small open model (e.g. an 8B Llama or Qwen with LoRA) on those outputs, and the student then extracts for the rest of the corpus. The teacher's sample comes from **pre-2005 works only**. **Acceptance rule (proposed):** the student is used only if, on held-out pre-2005 works and on Scott's gold set from the pilot (3.5), its agreement with the reference is within 5 points of the teacher's own. If not, the teacher does the whole corpus and the shortfall is reported.
3. **Rate and repair:** a second pass flags atoms that are too vague, too specific or tied to one story, and rewrites them.
4. **Cluster** each facet's atoms into vocabulary items: embedding, then dimensionality reduction and density clustering (the original used bge-large-en-v1.5, UMAP and HDBSCAN; that's the starting configuration). An LLM names each cluster.
5. **Map works to the vocabulary:** each work keeps at most *m* atoms per facet (default 1, tuned on rehearsals). That makes atom counts nearly independent of summary length.

### 3.3 Extract once, cluster per run
Extraction doesn't depend on the cutoff, so each work is extracted once. **Clustering is redone for each run** (rehearsals 1972, 1982, 1992; the 2005 test; the random split), using only that run's training works. Later works' atoms are matched to the nearest existing cluster.
- **New atoms:** a post-cutoff atom that matches no pre-cutoff cluster (beyond a similarity threshold tuned on rehearsals) is counted as a **genuinely new building block**. The model can't predict these by construction. They're reported separately, as the share of the future made of new pieces rather than new combinations.

### 3.4 How vocabulary size is chosen (fixed criterion, tuned value)
For each facet and each candidate clustering:
- **Random-intruder test** (catches clusters that are too broad): show a judge four atoms from a cluster plus one from a random other cluster; the judge must spot the intruder.
- **Nearest-neighbor intruder test** (catches over-splitting): the same, but the intruder comes from the most similar cluster.
- The judge is an LLM, spot-checked by Scott on a sample.
- **Rule:** among clusterings that pass both intruder tests (proposed floor: 80% correct on each; chance is 20%), choose the one whose coherence model scores best on the rehearsal validation data.

### 3.5 Extraction pilot
Before running at scale, prompts are tuned on about **100 works from before 1972 only** (none of them a future test case; no Brick). Scott reads the atoms for those works and judges whether they capture each story. **The need facet is checked explicitly:** if most extracted needs are judged unsupported by the story, the facet is dropped or restricted to works where it's grounded, and that's logged as a deviation.

### 3.6 What gets tuned on the rehearsals
Tuned (values chosen on the 1972, 1982 and 1992 rehearsals only): clustering settings per facet (hence vocabulary size), atoms per facet *m*, the threshold for "new atom," and the coherence model's settings (section 5). Fixed here: the facets, the extraction rules, the selection criterion in 3.4. The 2005 test sees none of the tuning.

## 4. Baselines and their tuning budget
*Drafted 2026-11-10; the choices of baselines were made by Scott on 2026-11-09.*

A baseline is what a hypothesis says the model beats. It has to be strong enough that winning means something, and tuned as hard as the model, so that winning doesn't just mean it got more attention.

### 4.1 The model being compared
The coherence model is a **small transformer trained from scratch** (by Scott) on works written as sets of atom tokens. Its objective is to predict a masked atom from the work's other atoms, the masked-token objective of BERT, with atoms in place of words. Architecture and settings are in section 5. Gaps are ranked by combining its coherence score with availability in the genre × era context. Each baseline below replaces either the coherence score or the whole gap ranking.

### 4.2 The ladder, weakest to strongest

| Method | What it is | Used in |
|---|---|---|
| Shuffled combinations | Real works' atoms reshuffled across works, matching each work's atom count and genre mix | H1 (control) |
| Random never-done combinations | Random draws from H2's candidate pool, **matched on atom frequency** to the model's picks, so the model can't win by favoring common atoms | H2 (floor) |
| Random coherent combinations | Random atom sets at the same coherence as the model's picks. In H3 this asks whether unexplored beats merely coherent. In H2 it's a secondary comparison only | H3 (floor); H2 (secondary) |
| **Pair counting** | Coherence = smoothed PMI summed over atom pairs. Availability = the same counts within a genre × decade cell, backing off to neighboring decades and the parent genre | H1, H2, H3 |
| **Linear learned model** | Logistic regression or a factorization machine over atoms, trained on the same works | H1, H2 (does the architecture matter?) |
| **Trend extrapolation** | Rank combinations by how fast their counts rose in the decade before the cutoff | H2 |
| **LLM direct, controlled** | A frontier LLM is given a genre and the facet vocabulary and asked to choose an atom set that's coherent and unexplored for that genre. The shared decoder writes the premise, so format and length match the other arms exactly | H3 |
| LLM direct, free-form | The LLM writes the premise itself | H3, **exploratory only** |

Notes:
- **The LLM arms don't enter H2.** The LLM has read post-2005 works, so its "predictions" of what came after 2005 would be contaminated (section 6).
- **H2's comparisons** are therefore: random (frequency-matched), pair counting and trend extrapolation. Beating trend extrapolation is what separates foresight from noticing momentum.
- **H1's comparisons:** shuffled and pair counting (confirmatory, as in section 1), plus the linear model.

### 4.3 Tuning budget
- **Equal number of configurations per method, about 30 each**, all evaluated on the 1972, 1982 and 1992 rehearsals only and chosen by the same metric. A method with few knobs (pair counting: smoothing, PMI vs raw counts, backoff weights) may use fewer.
- **What counts as one configuration:** one setting of a method's knobs. For trained models, each configuration is run with 3 random seeds and scored on their average. Seeds don't count against the budget, and the final reported numbers average the same 3 seeds.
- **Prompt variants count as configurations** for the LLM arms.
- **Same inputs:** every method sees the same training works, the same atom vocabulary (from that run's clustering) and the same genre and era labels.
- **Everything is logged:** every configuration tried for every method, losers included, with its rehearsal score, in a configuration log kept alongside the deviation log.
- **Selecting settings for the H3 arms** (proposed). Human interest can't be the tuning signal (the judges see only the one-shot evaluation), so each arm's free settings (β for the model; the prompt for the LLM arm) are chosen on rehearsal-era premises by **one fixed LLM-judge proxy for interest**, applied identically to every arm. The proxy is only a tuning aid; it's never reported as evidence for H3.

An **arm** is one source of premises in the human evaluation. H3 has four: the model, pair counting, random coherent combinations and LLM direct (controlled). All four go through the same decoder, so the only thing that differs between arms is which atom combination was chosen.

### ▶ Decisions for Scott
1. ~~How the LLM arm sits inside H3.~~ **Decided 2026-11-10:** H3 succeeds if the model beats **counting and random** (both must win). The comparison with LLM direct is a **separate pre-registered test, H3b**, inside the Holm family, which now has four tests (H1, H2, H3, H3b). It's run and reported whatever the outcome, but H3 doesn't depend on it.
2. ~~The linear model: confirmatory or secondary?~~ **Decided 2026-11-10: secondary.** It's trained, tuned on the same budget and reported with intervals for H1 and H2, outside Holm. A tie is reported as a finding (atoms combine in mostly pairwise ways), not as a failure.
3. ~~Tuning the H3 arms with the LLM-judge proxy.~~ **Decided 2026-11-10: yes, with two safeguards.** (i) The judge comes from a different model family than the LLM-direct arm, to avoid self-preference. (ii) Before any tuning, the judge's ratings are checked against human ratings on a small set of rehearsal-era premises (Scott may supply these, since this only validates the tool). If agreement is poor (threshold set in section 5), the free settings are fixed by hand instead, and that's logged.

**Section 4 has no open decisions left.**

## 5. Primary metric and the one-shot test
*Drafted 2026-11-10.* This section fixes the arithmetic for each test, so that no metric can be chosen after the results are seen.

### 5.1 What the model outputs: the gap score
For a set of atoms *S*, a genre *g* and a decade *t*, the model gives two scores:
- **Coherence C(S):** do these atoms hang together as a story at all?
- **Availability A(S | g, t):** would this genre's tradition, up to this decade, have produced this combination?

**Gap score = C(S) − β · A(S | g, t).** β is the "how adventurous" dial: at 0 the model just prefers coherent combinations; higher values favor combinations the genre hasn't done. β ≥ 0.

**One transformer, asked two ways (decided by Scott, 2026-11-10).** In training, each work is sometimes shown with a genre tag and a decade tag and sometimes without (the tags are dropped at random, starting at half the time). Afterward:
- asked **without tags**, its likelihood for the atoms is the coherence score;
- asked **with tags** (e.g. "noir, 1990s"), its likelihood is the availability score.

Details:
- A set's likelihood is the average, over its atoms, of the log-probability the model gives each atom when that atom is hidden and the others are shown. Averaging makes sets of different sizes comparable.
- A work with several genres is shown with one of its genre tags at a time, so each genre keeps its own history (section 2.3).
- The decade tag used for scoring candidates is the decade containing the cutoff.
- **Secondary comparison:** the same coherence score combined with availability from smoothed counts (the counting baseline's availability). It shows whether the learned availability adds anything.

### 5.2 H1: does the model know what a story looks like?
- **Data:** the held-out test fold of the grouped random split, used once.
- **Scrambled versions:** for each held-out work, 5 scrambled copies, each made by replacing **half** of its atoms with the same-facet atom from a random other work that shares a genre label. (Also reported: one atom replaced, and all replaced.)
- **The number:** how often the method scores the real work above its scrambled copy. 50% is a coin flip.
- **A win:** (a) the model's rate is above 50%, and (b) the model's rate minus pair counting's rate on the same pairs is above zero; both intervals must exclude the no-difference value.
- **Interval:** bootstrap over the split's groups (10,000 resamples), so a franchise counts once.
- **Secondary:** the same comparison against the linear model; and how well each method guesses a single hidden atom.

### 5.3 H2: do gaps get filled?
A full ten-atom combination will essentially never recur exactly, so a checkable gap has to be small.

- **The unit (decided by Scott, 2026-11-10): a genre plus a pair of atoms** from two different facets. Brick's would be roughly *noir + (high-school setting, hard-boiled detective protagonist)*.
- **The candidate pool:** every such unit where the pair **never appeared together in that genre before the cutoff**, and each atom appears in at least 20 pre-cutoff works overall (proposed), so that no candidate rests on a one-off atom. Genres are taken at the middle level (the 44).
- **Ranking:** each method ranks the whole pool and names its **top 1,000**. For trained models, scores are averaged over the 3 seeds before ranking. Ties are broken at random with a fixed seed.
- **A hit:** at least one work from the 12 years after the cutoff carries that genre label and both atoms. Remakes, sequels and adaptations of pre-cutoff works can't produce hits (section 2.4).
- **The number:** hits among the top 1,000.
- **Rivals:** pair counting, trend extrapolation and a random floor: random pool members matched on atom frequency to the model's picks. **A win** means the model's hit count beats each rival, with every interval excluding zero.
- **Interval:** bootstrap over the post-cutoff works, by group. The top-1,000 lists stay fixed; the future is resampled.
- **Checks (section 6.2):** a blind audit of 100 hits per method; a rerun with core genre labels only; films and novels reported separately.
- **Secondary:** the comparison with random pool members of equal coherence (does unavailability itself predict anything?); the full curve (hits in the top 100, 300, 3,000...); genre + single atom ("an atom new to this genre"); genre + triple; hits as a function of β.

### 5.4 H3 and H3b: are the premises more interesting?
- **The number:** the model's **win rate** in blind head-to-head comparisons against each other arm. A judge sees two premises from different arms, unlabeled, and picks the more interesting. 50% is a tie.
- **H3 wins** if the win rate is above 50% against both counting and random. **H3b** is the same number against LLM direct.
- **Which model writes the gaps:** after the one-shot test, the frozen configuration is retrained on the **whole dated corpus** (through 2017), so the premises are gaps relative to everything we have, not gaps as of 2005 (proposed).
- Who judges, how many premises per arm, how many comparisons, and the interval method (it must account for the same judge and the same premise appearing many times) are fixed in the human-evaluation section, locked before any premises exist.
- **Fixed now (section 6.2):** Scott is not a judge; every premise goes through a novelty screen against existing works, with the share that already exist reported per arm.
- **Check on the LLM-judge proxy (section 4.3):** the proxy is used for tuning only if, on 200 pairs of rehearsal-era premises, it picks the same premise as the human rater at least 60% of the time (chance is 50%; proposed). Otherwise the arms' free settings are fixed by hand.

### 5.5 Settings of the coherence model
A set transformer: each atom is an embedding plus an embedding for its facet; there's no word order, so no position signal. Starting ranges, tuned within the 30-configuration budget (section 4.3):

| Setting | Starting range |
|---|---|
| Layers | 2–6 |
| Width (embedding size) | 128–512 |
| Attention heads | 4–8 |
| Dropout | 0.1–0.3 |
| Share of atoms hidden per training example | 15%–50% |
| How often tags are dropped | 30%–70% |
| Learning rate | 1e-4 – 1e-3 |
| Training length | Early stopping on held-out loss |

- **How a configuration is scored:** the H2 number (hits in the top 1,000), averaged over the 1972, 1982 and 1992 rehearsals. The same score chooses every baseline's configuration and the vocabulary (section 3.4).
- **H1 uses the same configuration,** retrained on the random split's training fold. Its validation fold is used only for early stopping. Nothing is tuned for H1 separately.

### 5.6 The one-shot run
1. **Freeze.** Every tuned value (clustering settings, atoms per facet, new-atom threshold, model and baseline configurations, β for H2) is written into this plan, and the code is committed. The commit ID and a fingerprint of the data files are recorded here.
2. **No peeking before the freeze.** Atoms for post-2005 works exist (extraction happens once), but no statistic is computed on them, and the hit-counting code is exercised only on the rehearsals.
3. **Run once:** H1 on the random split's test fold, H2 on the 2005 split.
4. **Report whatever comes out,** including every secondary number listed above.
5. **Then** retrain on the whole corpus, generate the premises and run the human evaluation (H3, H3b).

**Rerun rule (decided by Scott, 2026-11-10).** A rerun is allowed only for a bug that can be demonstrated without reference to the results (a crash, a file read wrong, a split built incorrectly). The bug, the fix and both sets of numbers go in the deviation log. A disappointing number is never a bug.

### ▶ Decision for Scott
~~H2's random floor.~~ **Decided 2026-11-10: option (a), matched on atom frequency only.** Sections 1, 4.2 and 5.3 are updated. The reasoning is kept below.

Sections 1 and 4 said the floor was random combinations "of equal coherence." Writing out the arithmetic exposed a problem with that:
- Every candidate in the pool is already a gap in the hard sense (never done in that genre). The model's job in H2 is to say **which never-done combinations get done.**
- The availability term may well point the wrong way for that job. Combinations *close* to what a genre already does are probably the likeliest to appear next; the gap score, with β above zero, pushes away from those. If that's how it goes, the rehearsals will choose a β near zero, the model's picks will simply be the most coherent candidates, and a floor matched on coherence would tie with the model **by construction**. H2 could then not be won, for a reason that has nothing to do with whether the model is any good.
- **Options:** (a) the confirmatory floor becomes random candidates **matched on atom frequency only**, and the coherence-matched comparison is reported as secondary, as the measure of whether unavailability itself predicts anything; (b) keep the coherence-matched floor as confirmatory and accept that H2 fails if availability doesn't help prediction.
- *Lean: (a).* The far-out gaps are tested where they belong, in H3: are they more interesting? H2 then tests what it can honestly test: that the model knows which untried combinations are viable. "Near gaps fill, far gaps don't" would be reported as a finding either way (the hits-by-β curve).
- The H3 random arm stays matched on coherence, since there the question is whether unexplored beats merely coherent.

**Section 5 has no open decisions left.**

## 6. Known threats and how each is handled
*Drafted 2026-11-10; agreed with Scott.* Everything that could make a result wrong or misleading, in three groups: handled by the design, handled by a check added here, and accepted as a stated limit.

### 6.1 Handled by the design

| Threat | Fix | Where |
|---|---|---|
| The vocabulary is built with knowledge of the future | Clustering is redone for each run from pre-cutoff works only | 3.3 |
| Longer summaries in later decades yield more atoms | Standard-length rewrite, a cap on atoms per facet, a by-decade check | 2.2 |
| Remakes, adaptations and franchises leak across a split | Grouped split; they can't count as H2 hits | 2.4 |
| Genre labels are inferred from the same text as the atoms | Tie-break toward label sources farther from the plot text | 2.3 |
| The extractor invents "needs" | Citation requirement, "none" allowed, checked in the pilot | 3.2, 3.5 |
| The LLM arm has read the post-2005 works | Kept out of H2 | 4.2 |
| The model is tuned harder than its rivals | Equal budget; every configuration logged | 4.3 |
| The LLM judge favors its own family, or doesn't match human taste | Different family; checked against human ratings before use | 4.3, 5.4 |
| The model wins H2 by favoring common atoms | Random floor matched on atom frequency | 4.2, 5.3 |
| The model wins H2 by noticing momentum | Trend extrapolation is a rival | 4.2 |
| Metrics or hypotheses chosen after seeing results | Plan lock, one-shot run, rerun rule, deviation log | 5.6 |

### 6.2 Handled by a check added here

**1. False hits in H2.** A hit means a post-cutoff work was matched automatically to both atoms and carries the genre label. The matching is noisy, a remake can slip through, and a genre label can be a stretch.
- **Hit audit:** for every method, 100 of its hits (all of them if there are fewer) are read by a person who doesn't know which method produced them. The reader checks three things: the work really has both atoms; it really belongs to the genre; it isn't a remake, sequel or adaptation of a pre-cutoff work.
- The false-hit rate is reported per method. The main H2 number stays the automatic count; the audited estimate is reported beside it.

**2. Borderline genre labels** (raised by Scott: someone could call Brick a neo-western; defensible, not really correct). Before the cutoff, one stray label can erase a real gap from the pool, since the pool is pairs "never done in that genre." After the cutoff, a stray label creates a false hit.
- **Core or borderline:** the labeler marks each genre on a work as *core* or *borderline* (section 2.3).
- The main analysis uses all labels. **H2 is rerun with core labels only** as a secondary analysis. If the result holds both ways, borderline calls aren't driving it.

**3. Errors and odd choices in the summaries** (raised by Scott). The summaries are written by people; the atoms inherit their mistakes and their emphasis.
- **Summary-stability check:** many films have two or more versions of their summary in our sources (mostly snapshots of the same Wikipedia article from different years, so they aren't independent, but they differ where editors rewrote). On a sample of about 300 films whose versions differ, atoms are extracted from two versions and the agreement is reported per facet.
- That number says how much the atoms depend on who wrote the summary. It's reported next to the limit it measures: the study is about stories **as summarized.**

**4. "Gaps" that already exist.** The corpus ends in 2017 and holds only works with long Wikipedia plots. A premise may match a 2021 film or an obscure older novel.
- **Novelty screen:** every premise from every arm is checked against existing works by an LLM with web search. The share that already exist is reported per arm.
- Those premises stay in the evaluation; removing them afterward would be a judgment call.

**5. A film result presented as a general one.** After 2005 there are about 7.9k films and 1.1k novels. Every confirmatory number is also **reported separately for films and novels.**

**6. The designer as judge.** Scott designed the model and will have read many of its outputs. He validates the tuning tools (the gold labels, the pilot, the check on the LLM judge) and may read for the hit audit, which is blind to method. **He doesn't judge H3 or H3b.**

**7. The distilled extractor drifting on later works.** It learns from pre-2005 works only. Its agreement with the teacher is also measured on a small post-2005 sample. This is a check on extraction quality; no outcome statistic is computed (5.6).

### 6.3 Accepted, and stated in the write-up
- **"Never done" means "never done in our corpus."** Works with long English Wikipedia plots skew popular, Western and recent.
- **Hindsight in the tools.** The extraction LLM and the embedding model were trained on text written after 2005. Even seeing one old work at a time, they may describe it in terms that later works made familiar. The rehearsals share this flaw, so they can't detect it.
- **The ten facets are a theory of story.** A different list would give different gaps (3.1).
- **Summaries carry plot better than tone or structure.** The tone and structural-device facets may come out thin. The extraction pilot shows how thin, and the per-facet stability numbers show how reliable.
- **Loose retellings are not grouped** (2.4). An old story moved into a new genre can sit on both sides of the random split, which makes H1 slightly easier; in H2 it counts as a hit, by design.
- **The shared decoder knows recent works.** It may write a premise better when the gap resembles something it has seen. Every arm uses the same decoder, so this affects all of them, though not necessarily equally.
- **The execution confound** (was it the idea or the director?) touches only H4, which is exploratory. H3 compares premises, not finished works.
- **Coverage per year changes.** The 2005–2017 window holds more works per year than the rehearsal windows, so raw hit counts aren't comparable across runs. Comparisons are always between methods within one run.
