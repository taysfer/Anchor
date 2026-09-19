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