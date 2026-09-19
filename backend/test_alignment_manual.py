from app.services.alignment import calculate_alignment


intention = "Learn Kubernetes ingress"


pages = [
    (
        "Kubernetes Ingress Tutorial",
        "Learn how Kubernetes ingress handles routing and services."
    ),
    (
        "Docker Networking Guide",
        "Learn how Docker containers communicate with each other."
    ),
    (
        "Developer Desk Setup",
        "Here are some productivity tools for your desk."
    ),
    (
        "M4 MacBook Pro Review",
        "A review of Apple's MacBook Pro performance."
    ),
    (
        "Top 10 Minecraft Builds",
        "Here are ten awesome Minecraft houses you can build."
    )
]


for title, content in pages:

    score = calculate_alignment(
        intention,
        title,
        content
    )

    print(title)
    print(f"Alignment: {score:.3f}")
    print()