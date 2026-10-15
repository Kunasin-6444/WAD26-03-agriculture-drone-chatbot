# Project Requirements

## Project

Agriculture Drone LINE Chatbot

## Objective

Create a Thai-language LINE chatbot for agricultural-drone knowledge.

The chatbot should answer using the project's approved knowledge sources.

The chatbot must avoid hallucination.

---

# Functional Requirements

## R1 — Knowledge Base and Source Policy

The chatbot must use the project's provided knowledge-base files
as the primary source for answering questions.

### Approved Knowledge Sources

All provided agricultural-drone knowledge files in the project's
knowledge-base/data set must be used as sources for the chatbot,
including information contained in:

- PDF text
- native PDF tables
- image-only tables
- diagrams
- charts
- meaningful images and visual information

The ingestion pipeline should extract and normalize these sources
into Knowledge Units before chunking and embedding.

Each knowledge record must preserve:

- document filename
- document identifier
- page number
- source type

---

### Source Exceptions

The following two files are EXCLUDED from the normal PDF knowledge-base
answering pipeline:

1. `UAV01 Air Law.pdf`
2. `UA03 AIR SPACE.pdf`

The chatbot must NOT use the contents of these two files as the
authoritative knowledge source.

For information covered by these two documents, the chatbot must use:

https://uasportal.caat.or.th/infographic

as the designated source instead.

This source replacement rule applies whenever the user's question
requires information that would normally be obtained from:

- `UAV01 Air Law.pdf`
- `UA03 AIR SPACE.pdf`

The system must preserve the source/reference used for the answer.

---

### Source Priority

When answering a question:

1. Use the approved project knowledge-base files when they contain
   sufficient information.

2. For topics belonging specifically to `UAV01 Air Law.pdf` or
   `UA03 AIR SPACE.pdf`, use the CAAT UAS Portal infographic source:

   https://uasportal.caat.or.th/infographic

3. If the required information is not available from the applicable
   knowledge source, continue through the CRAG fallback process.

4. Never invent information to fill missing knowledge.

---

## R2 — Retrieval

The system must:

1. normalize the user question (repair Thai typos / wrong-keyboard text)
2. embed the question and search Chroma (dense retrieval)
3. also score candidates by exact-term matching (BM25 over Thai n-grams) and
   fuse both rankings (hybrid retrieval)
4. rerank the fused results by domain / crop / topic relevance and select a
   topic-diverse top-k (reranking)
5. keep the text and image chunks on the same page as a retrieved table or
   diagram, so units and caveats are not lost
6. provide those chunks to the LLM

Hybrid retrieval and reranking are part of the project scope. Dense search alone
misses exact terms such as nozzle names, numbers and units, which are central to
this knowledge base.

---

## R3 — Grounded Answer

The LLM must answer using retrieved evidence.

The answer must not invent facts that are not supported by
the retrieved context.

The response should provide source/reference information.

---

## R4 — CRAG

After retrieval, the system must determine whether the retrieved
content is sufficient to answer the question.

If sufficient:

    answer from the applicable knowledge source

If insufficient:

    perform web fallback

If both fail:

    abstain

---

## R5 — Web Fallback

Web fallback uses Tavily.

Prefer official sources where appropriate.

Web-derived answers must include a URL/reference.

---

## R6 — Abstain

When reliable information cannot be found:

The chatbot must explicitly say that the information could not be verified.

It must not guess.

---

## R7 — LINE

The backend must:

- receive LINE webhook
- verify signature
- parse message
- execute RAG/CRAG
- reply using LINE Reply API

---

# Out of Scope

Do not implement unless explicitly requested:

- weather
- image hosting
- image retrieval to LINE
- conversation memory
- PostgreSQL
- Redis
- LangChain
- LangGraph
- LlamaIndex

---

# Quality Requirements

The system should:

- support Thai questions
- preserve source traceability
- tolerate temporary API failures
- not crash the entire ingestion job because one page fails
- have automated regression tests
- have a reproducible ingestion process