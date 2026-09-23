from app.rag.rag_service import generate_grounded_answer, retrieve_context


def ask_ai(user_message: str) -> str:
    """
    Answer user query grounded in agricultural drone knowledge base.
    """
    context = retrieve_context(user_message)
    return generate_grounded_answer(user_message, context)