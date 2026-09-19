from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim


model = SentenceTransformer("all-MiniLM-L6-v2")

# removes n ewlines and extra spaces from the content, and truncates it to 3000 characters
def build_page_context(
    url: str,
    title: str,
    content: str
) -> str:

    cleaned_content = " ".join(content.split())

    page_context = f"""
URL: {url}

Title: {title}

Content: {cleaned_content[:3000]}
"""

    return page_context

# calulates the semantic similarity between the intention and the page context (title + content) using sentence embeddings
def calculate_alignment(
    intention: str,
    url: str,
    title: str,
    page_content: str
) -> float:

    page_context = build_page_context(
        url,
        title,
        page_content
    )

    intention_embedding = model.encode(
        intention,
        convert_to_tensor=True
    )

    page_embedding = model.encode(
        page_context,
        convert_to_tensor=True
    )

    similarity = cos_sim(
        intention_embedding,
        page_embedding
    )

    return float(similarity.item())