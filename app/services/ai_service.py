from app.rag.crag_service import run_crag_pipeline
from app.rag.query_rewriter import HELP_MESSAGE, is_help_request, rewrite_query
from app.services.conversation_memory import add_turn, get_history


def ask_ai(user_message: str, user_id: str | None = None) -> str:
    """
    Answer user query using Corrective RAG (CRAG) pipeline:
    0. Help requests get a static usage guide; other messages are rewritten into a
       standalone, spelling-corrected question using the user's recent turns
    1. Local knowledge base retrieval & relevance grading
    2. Web fallback (Tavily & official sources) if insufficient
    3. Designated CAAT UAS portal routing for Air Law/Air Space
    4. Abstain path if unverified (zero hallucination)
    """
    if is_help_request(user_message):
        return HELP_MESSAGE

    query = rewrite_query(user_message, get_history(user_id)) if user_message.strip() else user_message
    response = run_crag_pipeline(query)
    add_turn(user_id, query, response.answer)
    return response.answer
