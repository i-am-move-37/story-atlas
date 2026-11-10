# Walkthrough notes: the study, one step at a time

A word-for-word record of the slow walkthrough of the research plan (`research-plan.md`), kept so Scott can revisit any step. Each section holds Claude's description of the step, Scott's questions, and the answers. The plan itself is the authority; these notes explain it.

Started 2026-11-10. Steps recorded so far: 1 of 8.

---

## The map

**Claude:**

We'll go one step at a time, and I'll follow one film through the whole pipeline so each step has something concrete to hang on. Brick is the obvious choice, with one twist worth knowing up front: Brick came out in 2005, so it sits on the **test** side. The model never sees it in training. It's the kind of thing we hope the model points toward.

1. **Gather and clean the stories.** One entry per work, with a year and genre labels.
2. **Set aside the exam material.** Decide which works the model learns from and which are held back to test it.
3. **Turn each story into atoms.** Ten building blocks per story.
4. **Build the vocabulary.** Group similar atoms so "a high school" in one film and "a suburban secondary school" in another count as the same block.
5. **Train the model.** It learns which blocks go together, in general and within each genre.
6. **Rank the gaps.** Find combinations that hang together but that a genre hasn't done. The rivals do the same their own way.
7. **Rehearse, then test once.** Set every dial on old data, then run the real test a single time (H1, H2).
8. **Write premises and have people judge them** (H3, H3b).

---

## Step 1: Gather and clean the stories

*Plan sections: 2.1, 2.3. Walked through 2026-11-10.*

### The description

**Claude:**

**What we start with.** About 67k plot summaries of 300+ words, from four Wikipedia-based collections. They're messy in three ways, and step 1 fixes each.

**Chore 1: one entry per work.** The same film often appears three or four times across collections. Brick shows up in several. We merge the copies, keep the longest summary, and end up with roughly 25.6k films and 8.7k novels.

> **Correction (2026-11-10, after doing the step):** Brick has only one long summary in our sources (the CMU collection's, 642 words); "shows up in several" was wrong. And the real dedupe gives **26,681 films and 10,894 novels**, more than the rough count, because about 15k untagged WikiPlots summaries could now be identified as films or novels.

**Chore 2: a year for each work.** Most have one. About 2.4k films and 3.4k novels don't. Undated works can still be used in the test that doesn't involve time (step 2 explains), so nothing gets thrown away.

**Chore 3: genre labels.** This is the hard one. The collections' own labels are unusable: three different schemes, and badly incomplete (only 185 films labeled gangster). So we relabel everything against our own list: 7 families, 44 genres, 217 subgenres. Brick should come out as noir and teen/high school, both marked *core*.

We don't know yet which labeling method is best, so we **run a small contest first**, called the labeling pilot:

- Take 200 works. You label them by hand. That's the answer key.
- Three methods label the same 200: Wikidata's genre field, an LLM that sees only title, year and creator, and an LLM that reads the plot.
- Whichever matches your answer key best labels the whole corpus.

One wrinkle in the contest rules: if two methods are nearly tied, we prefer the one that *didn't* read the plot. The atoms come from the plot too, and if labels and atoms share a source, the model can look smart by rediscovering the labeler's reasoning.

**What you personally do in this step:** label the 200 works. For 50 you start from a blank page; for 150 you correct a draft.

**The "proposed" numbers in this step.** Three values in step 1 are mine and need your eye:

- **90% coverage.** A method only qualifies if it can label at least 90% of works. Wikidata, for instance, has no genre for many obscure novels.
- **A 2-point tie.** Two methods count as "nearly tied" if their accuracy scores are within 2 points of each other.
- **Merging fuzzy subgenres.** If you and the winning method disagree too often about a subgenre, it folds into its parent genre. The cutoff I proposed is an agreement score (kappa) below 0.4, which is the conventional line between "fair" and "moderate" agreement.

### Questions and answers

#### Q1. Should we merge the summaries?

**Scott** (on "We merge the copies, keep the longest summary"):

> Random thought: should we merge the summaries in case one has a detail the others lack so that we create the longest possible summary given our data?

**Claude:**

It's a reasonable idea, but I'd keep the longest one, for three reasons:

- **The copies are mostly the same text.** They're snapshots of one Wikipedia article at different dates, so the longest usually already contains the others.
- **Merging needs an LLM to stitch them**, which is a new place for invented or garbled details to enter, right at the foundation.
- **The extra length gets squeezed out anyway.** Step 3 starts by rewriting every summary to a standard length, precisely so that works with more text don't get more atoms. Famous films have more copies, so merging would give them richer inputs than obscure ones.

The summary-stability check from section 6 also needs the versions kept separate. And it gives us the evidence: if two versions of the same film often produce different atoms, that's the signal to revisit merging.

#### Q2. Do I label from the plot summary?

**Scott** (on "Take 200 works. You label them by hand. That's the answer key."):

> we do this based on the plot summary for the work, yes?

**Claude:**

No, and I'm glad you asked, because the plan doesn't say. You should label **the work itself**: the summary as a reminder, plus what you know, plus a quick lookup for works you haven't seen. If the answer key came only from the summary, it would favor the method that also reads only the summary, and the contest would be rigged toward the plot-reading LLM. The answer key is meant to be the truth about the work, from the best information available.

#### Q3. What does "correct a draft" mean?

**Scott** (on "For 50 you start from a blank page; for 150 you correct a draft."):

> What does this mean? "Correct a draft?"

**Claude:**

For those 150 works, you'd see a list of candidate labels and fix it: delete the wrong ones, add missing ones, mark each as core or borderline. That's much faster than a blank page with 217 subgenres to remember. The plan should say where the draft comes from, and my proposal is: the labels from all three methods pooled together, with no indication of which method suggested which. That way the draft can't tilt you toward one contestant.

The cost of a draft is anchoring: people tend to accept what's in front of them. That's why the other 50 are done from a blank page. They measure accuracy without that pull, and comparing the two sets shows how strong the pull was.

#### Q4. How is a kappa calculated?

**Scott** (on "an agreement score (kappa) below 0.4"):

> how is a kappa calculated?

**Claude:**

It's agreement corrected for the agreement you'd get by chance:

κ = (observed agreement − chance agreement) / (1 − chance agreement)

Take one subgenre, say neo-noir, across the 200 works. You say yes to 10 of them, the method says yes to 12, and you both say yes to 6.

- **Observed agreement:** you agree on those 6, and on the 184 you both said no to. That's 190 of 200, or 95%.
- **Chance agreement:** two raters saying yes 5% and 6% of the time independently would agree 0.05 × 0.06 + 0.95 × 0.94 ≈ 89.6% of the time.
- **κ** = (0.95 − 0.896) / (1 − 0.896) ≈ 0.52.

So 95% raw agreement is only moderate real agreement, because for a rare label almost all of it is the easy "no."

**Working that example exposed a hole in the plan.** With 200 works and 217 subgenres, most subgenres will have zero to three examples in the pilot. Kappa on three examples is noise. The merging rule as written can't do its job for most of the list.

My proposed fix is a two-part rule:

- **Against your answer key**, measure agreement only where there's enough data: all 44 genres, plus any subgenre with at least 5 examples in the pilot.
- **For the remaining subgenres**, measure agreement between the two best automatic methods across the whole corpus, where even rare subgenres have dozens of examples. A subgenre they can't agree on (κ below 0.4) merges into its parent.

The second part has no human in it, so it measures consistency rather than correctness. But it matches the principle you set earlier: split until labelers stop agreeing.

### What changed in the plan because of this step

**Scott:** "Okay. I feel good about step 1."

Written into `research-plan.md` on 2026-11-10:

1. **Summaries are not merged** (2.1). The longest version is kept, for the three reasons in Q1.
2. **The answer key labels the work itself**, not just its summary (2.3).
3. **The draft for the 150 works** is the three methods' labels pooled, with no sign of which method suggested which (2.3).
4. **The subgenre merging rule has two parts** (2.3): against the answer key where there are at least 5 examples; between the two best automatic methods across the whole corpus for the rest.
5. The three proposed numbers (90% coverage, the 2-point tie, κ below 0.4) were reviewed and stand.

### Doing the step (2026-11-10)

Scott chose to do step 1 before walking through the rest, so the ideas get reinforced in practice. What happened:

- **The project went public first.** It's at `github.com/i-am-move-37/story-atlas`. The first commit holds the plan as it stood, so the pilot's rules are timestamped before its results.
- **Matching.** Every long summary was matched to its Wikipedia page and its Wikidata entry (the structured database behind Wikipedia). 67,756 page lookups; about 530 pages no longer exist.
- **The dedupe took four tries.** Merging "everything that points to the same Wikidata entry" was too simple:
  - Some old pages now redirect to a list or a series page. 290 Tom and Jerry shorts became one "work," because all their pages now point to the filmography. *Fix:* an entry only identifies a work if Wikidata says it is itself a film or a novel.
  - A novel's page sometimes redirects to its film adaptation. *Fix:* the entry must be the same medium as the summary.
  - Several different titles from one source landing on one page means that page is a series (11 Judge Dredd storylines). *Fix:* those rows are split off again.
  - A plain programming bug lumped all unmatched rows together. *Fix:* found by reading the report, which claimed "100% matched."
- **Result:** 72,577 summaries became 37,575 works: 26,681 films and 10,894 novels. 98% of films and 88% of novels have a year (novels were 60% before). From 2005 on: 9.9k films and 2.1k novels.
- **The lesson for later steps:** the report after each run is what caught every one of these. None showed up as an error.

---

## Step 2: Set aside the exam material

*Not yet walked through.*
