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
             CRAG Flow
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
 +--> Vision extraction
 |
 v
Knowledge Units
 |
 v
Chunks
 |
 v
Gemini Embedding 2
 |
 v
Chroma

---

# Query Pipeline

User Question
 |
 v
Query Embedding
 |
 v
Chroma Search
 |
 v
Top-K Chunks
 |
 v
CRAG Relevance Grader
 |
 +---- YES ----> LLM Answer
 |
 +---- NO -----> Tavily
                    |
                    v
                  LLM
                    |
                    v
                 Answer

If both knowledge base and web search
cannot provide reliable evidence:

    -> Abstain