from app.rag.exclusive_pipeline import run_exclusive_pipeline as run_crag_pipeline
from app.services.rich_menu_service import MENU_ANSWER, get_rich_menu_preanswer, is_menu_request


def ask_ai(user_message: str, user_id: str | None = None) -> str:
    """Process every new question independently, including repeated/concurrent text.

    No answer cache or shared in-flight generation. LINE event redelivery is
    handled separately by the durable inbox, using event IDs, not question text.
    user_id remains accepted for LINE compatibility; no conversation is reused.
    """
    pre_answer = get_rich_menu_preanswer(user_message)
    if pre_answer:
        return pre_answer
    if is_menu_request(user_message):
        return MENU_ANSWER
    return run_crag_pipeline(user_message).answer
