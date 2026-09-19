from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim


# Load the embedding model once when the backend starts
# instead of loading it again for every webpage
model = SentenceTransformer("all-MiniLM-L6-v2")

# removes n ewlines and extra spaces from the content, and truncates it to 3000 characters
def build_page_context(
    url: str,
    title: str,
    content: str
) -> str:
    # Remove extra spaces and line breaks from webpage text
    cleaned_content = " ".join(content.split())

    # Combine useful page information and limit content length so extremely large webpages are not fully embedded
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

    # Prepare the webpage text for the embedding model
    page_context = build_page_context(
        url,
        title,
        page_content
    )

    # Convert the user's intention into a semantic embedding
    intention_embedding = model.encode(
        intention,
        convert_to_tensor=True
    )

     # Convert the webpage context into a semantic embedding
    page_embedding = model.encode(
        page_context,
        convert_to_tensor=True
    )

    # Compare the two embeddings using cosine similarity
    similarity = cos_sim(
        intention_embedding,
        page_embedding
    )

    # Convert the result from a tensor into a normal Python float
    return float(similarity.item())