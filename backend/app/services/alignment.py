from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim


model = SentenceTransformer("all-MiniLM-L6-v2")


def calculate_alignment(
    intention: str,
    title: str,
    page_content: str
) -> float:

    page_context = f"""
    Title: {title}

    Content: {page_content[:3000]}
    """

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