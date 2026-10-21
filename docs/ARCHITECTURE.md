# Architecture

## High Level

                User
                 |
                 v
              LINE
                 |
                 v
          FastAPI Webhook
                 |
                 v
       Speculative CRAG Flow
                 |
         +-------+-------+
         |               |
         v               v
    Chroma RAG       Web Search
         |               |
         +-------+-------+
                 |
                 v
               LLM
                 |
                 v
              Answer

---

# Knowledge Pipeline

PDF
 |
 +--> text extraction
 |
 +--> native table extraction
 |
 +--> Vision extraction (Selective heuristic + Disk Cache)
 |
 v
Knowledge Units
 |
 v
Chunks (800 chars, 120 overlap)
 |
 v
Gemini Embedding 2 (3072 dim)
 |
 v
Chroma (`drone_knowledge`)

---

# Query Pipeline (Speculative Parallel CRAG)

User Question
 |
 v
Query Embedding (Gemini Embedding 2) (~0.7s)
 |
 v
Chroma Search (Top-12 Chunks) (~0.05s)
 |
 +-----------------------------------+-----------------------------------+
 | (Thread 1 - Grader)               | (Thread 2 - Generator)            |
 v                                   v                                   |
CRAG Relevance Grader                Grounded LLM Generator              |
(gemini-3.5-flash-lite, max_tokens=150) (gemini-3.5-flash-lite, max_tokens=300)|
(~2.1s)                             (~2.7s)                             |
 |                                   |                                   |
 +-----------------+-----------------+                                   |
                   |                                                     |
          [Gatekeeper Decision]                                          |
                   |                                                     |
            +------+------+                                              |
            |             |                                              |
        [CORRECT]    [INCORRECT / CAAT Topic]                            |
            |             |                                              |
            v             +----------------------------------------------+
     Accept Speculative   Discard Speculative Answer
     Answer (~2.8s)       |
            |             v
            |         Rule R1 CAAT Check
            |             |
            |             +---- CAAT Topic ----> Direct CAAT UAS Portal Infographic
            |             |                      (Bypass Tavily, ~1.6s total)
            |             |
            |             +---- Other Topic ---> Tavily Search (Top-3 Trusted)
            |                                    |
            |                                    v
            |                                  Web Grounded LLM (max_tokens=300)
            |                                    |
            v                                    v
      Final Answer                         Web Answer / Abstain (~6.2s)

If both knowledge base and web search
cannot provide reliable evidence:

    -> Clear Abstain (Zero Hallucination)