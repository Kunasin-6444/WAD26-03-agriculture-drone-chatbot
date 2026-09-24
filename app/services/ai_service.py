from app.rag.crag_service import run_crag_pipeline


def ask_ai(user_message: str) -> str:
    """
    Answer user query using Corrective RAG (CRAG) pipeline:
    1. Local knowledge base retrieval & relevance grading
    2. Web fallback (Tavily & official sources) if insufficient
    3. Designated CAAT UAS portal routing for Air Law/Air Space
    4. Abstain path if unverified (zero hallucination)
    """
    response = run_crag_pipeline(user_message)
    return response.answer