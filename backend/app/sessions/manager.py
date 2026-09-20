sessions = {}


def add_page_to_session(
    session_id: str,
    intention: str,
    url: str,
    title: str,
    alignment: float
):

    if session_id not in sessions:
        sessions[session_id] = {
            "intention": intention,
            "pages": []
        }

    page = {
        "url": url,
        "title": title,
        "alignment": alignment
    }

    sessions[session_id]["pages"].append(page)


def get_session(session_id: str):
    return sessions.get(session_id)

def get_alignment_scores(session_id: str) -> list[float]:
    """
    Returns the alignment scores for every page
    visited during a session.
    """

    session = get_session(session_id)

    # Return an empty list if the session does not exist
    if session is None:
        return []

    # Extract only the alignment value from each stored page
    return [
        page["alignment"]
        for page in session["pages"]
    ]