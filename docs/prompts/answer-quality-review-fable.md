# Answer-quality review prompt (Claude Fable 5.2)

How to run it: start a Claude Code session on `claude-fable-5-2` in a fresh
checkout of this repository, at effort `high`. Paste everything below the line
as the first message. Before you paste it, fill in the **Pilot evidence**
section. The review works without it, but it is far more useful with it.

---

# Why don't our answers reach production quality?

## The situation

This repository is the Bisq 2 Support Agent. It is a RAG support system for Bisq 2
(Bisq Easy) and Bisq 1, a privacy-sensitive, peer-to-peer bitcoin exchange. It
answers user questions in web chat, in Matrix support rooms and in Bisq 2
support chat. Its knowledge comes from the Bisq wiki, curated FAQs, a reviewed
"LLM Wiki", historical support conversations, live Bisq 2 data (through MCP
tools) and staff feedback. `PRODUCT.md`, `README.md` and `docs/` describe the
intent.

We have run a series of pilots, one after another, in Matrix support rooms.
Each pilot was a little better than the one before. None of them reached the
point where the support team would say: "we can let this answer users," or even
"these context notes reliably save us time." The quality step to production
has not happened. We want to know why, and what to do about it.

You are reviewing the repository to answer two questions:

1. **What is holding answer quality back?** Find the root causes. Do not stop at
   the symptoms. Rank the causes by how much of the gap each one explains.
2. **What should we change, in what order?** Give a short, ordered plan. Each
   step should name the expected quality gain and say how we will know it worked.

"Answer quality" means the full answer a user or staff member receives:
correct, specific to their Bisq version and situation, grounded in sources we
trust, not padded or vague, and routed to a human when the evidence is weak. It
also covers the context notes the bot posts in the staff room
(`docs/matrix-staff-context.md`, `docs/public-context-experiment.md`).

## Pilot evidence

<!-- Fill this in before running. Paste or attach whatever exists:
- which pilots ran, when, in which mode (answer / staff context / shadow), and with which model and config
- 10–30 real examples where staff judged the output wrong, unhelpful, or worse than a staff reply, with the staff reply if there is one (sanitize them first)
- feedback ratings, escalation rates, and how often staff used, edited, or ignored the output
- what staff said in their own words about why it is not good enough
If none of this exists, write "none" and say so. Not having it is a finding in itself. -->

## Where to look

The live answer path for Matrix starts in `api/app/channels/plugins/matrix/`
and `api/app/channels/staff_assist/`. It runs through
`api/app/services/simplified_rag_service.py` and `api/app/services/rag/`
(query rewriting, protocol detection, hybrid Qdrant retrieval, reranking,
prompt assembly, NLI validation, confidence scoring, auto-send routing). The
system prompt and policy are in `api/app/prompts/`. Model and feature defaults
are in `api/app/core/config.py` and `docker/.env.example`. The knowledge sources
are in `api/data/`. The evaluation sets, results and scripts are in
`api/data/evaluation/`, `api/data/evaluation_results/` and `api/app/scripts/`
(see also `docs/release-ai-quality-gate.md`). Earlier reviews are in
`claudedocs/`, and the git history shows where the engineering time went.

Read these. Do not treat their claims or comments as true until the code
confirms them.

## Leads to confirm or refute

These are things we noticed in a quick look. They are not conclusions. Check
each one against the code and the data. Say whether it holds, and how much it
matters. Look past them too: the most important cause may not be on this list.

- The default answer and translation model is `openai:gpt-4.1-nano`. The query
  rewriter and classifier use `gpt-4o-mini`. Find out which model the pilots
  actually used. Then decide whether model capacity limits answer quality. A
  better pipeline cannot fix a model that is too small for nuanced, multi-step
  support reasoning.
- Most recent commits touch deployment, safety gates, Dockerfiles, wiki
  ingestion plumbing and tests. Few touch the answer itself. Check whether the
  effort has gone into making the system safe to run rather than making the
  answers good.
- The pipeline has many stages, and each can quietly lose information. Check
  whether a user's real question survives the trip from a Matrix room to the
  prompt. Look at multi-message questions, thread context, earlier messages,
  screenshots and logs, the version the user is on, and what they already tried.
- Check whether the knowledge base contains the answers to the questions users
  actually ask. Coverage gaps and stale or contradictory content cannot be fixed
  by better retrieval.
- The evaluations are small: 30 RAGAS samples, plus a release-gate set. Check
  whether they measure what staff judge in a pilot. Can the team see whether a
  change made real answers better or worse before the next pilot?
- The confidence, NLI and escalation layers may be tuned so that the useful
  answers get suppressed, or so that weak answers get through. Find out which.

## How to work

- **Trace real questions end to end.** Take several realistic questions,
  preferably from the pilot evidence or from
  `api/data/evaluation/matrix_realistic_qa_samples_30_20260211.json`. Follow
  each through the code: the exact input to the model, what retrieval returns,
  what the prompt looks like, and what decides the final output. Concrete
  traces are worth more than a general architecture review.
- **Read the data, not only the code.** Open the knowledge files, the eval sets
  and the stored eval results. Look at what the retrieved context for a hard
  question actually contains.
- **Separate what you checked from what you infer.** Mark each finding as
  *verified* (you saw it in the code, the data or a command output, with a
  `file:line` reference) or *inferred* (with your reasoning).
- **You may run** tests, offline scripts and local analysis. **Do not** call
  paid LLM or embedding APIs, production services, Matrix or Bisq endpoints, and
  do not change, commit or push anything. When a measurement needs a provider
  call, write the exact command and say what result would confirm or refute the
  finding. We will run it.
- Do not report generic RAG advice. Every recommendation must point at
  something specific in this repository, or at something the repository is
  missing.

## Finishing work

Complete the whole review before you stop. If a test fails, a script needs a
missing dependency or a file is large, work through it or find another way to
get the evidence. Stop and report only for a real blocker, such as a step that
needs a paid API call. When you hit one, write down what it blocks, and continue
with the rest.

## What to deliver

Write the report to `claudedocs/answer-quality-review.md` and give a short
summary in chat. Use this structure:

1. **The answer in five sentences.** Why we are not at production quality, and
   the one or two changes that would matter most.
2. **What "production-ready" should mean here.** Propose concrete, measurable
   acceptance criteria for Matrix support. For example: answer accuracy on a
   real-question set, the share of answers staff would send unchanged, the
   escalation precision, and the rate of harmful or wrong answers. Say how far
   the current system is from each criterion, or say that we cannot tell yet.
3. **Root causes, ranked.** For each cause: what it is, the evidence (verified
   or inferred), roughly how much of the quality gap it explains, and a real
   example of the failure it causes.
4. **Plan, in order.** At most 8 steps. For each step: the change, the files or
   areas involved, the effort (S/M/L), the expected effect, and how we will
   measure it. Put the measurement work first if we cannot measure quality
   today.
5. **What to stop doing or remove.** List the complexity, gates or work streams
   that cost more than they return for answer quality.
6. **Open questions** that only the team or the pilot data can answer.
7. **Appendix:** the end-to-end traces, and the commands you ran.

Sections 1–6 should be about 2,000–3,500 words. The appendix can be longer.

## Communicating clearly

Write for an intelligent but low-context reader. The person reading has not
seen your tool calls, your reasoning or the files you opened, and may be
switching in from other work. Put the key points in the first few sentences.
Use plain words and full sentences. Do not use a term or abbreviation that you
made up during the work. Say what the thing is in a way any reader would
understand. Use a paragraph of prose where ideas connect, and keep bullets for
lists of separate items. Be direct about bad news: if the honest answer is that
the model, the knowledge base or the approach is the limit, say so plainly.
