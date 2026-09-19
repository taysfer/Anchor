from app.services.alignment import calculate_alignment


intention = "Find a laptop for programming"

pages = [
    (
        "https://kubernetes.io/docs/concepts/services-networking/ingress/",
        "Ingress | Kubernetes",
        "An API object that manages external access to services in a cluster, typically HTTP."
    ),

    (
        "https://docs.docker.com/network/",
        "Docker Networking",
        "Learn about container networking, drivers, ports, and communication between containers."
    ),

    (
        "https://aws.amazon.com/elasticloadbalancing/",
        "Elastic Load Balancing",
        "Automatically distribute incoming application traffic across multiple targets."
    ),

    (
        "https://example.com/macbook",
        "Best MacBook for Developers",
        "Comparing MacBook Pro models for software development and programming."
    ),

    (
        "https://example.com/minecraft",
        "Top 10 Minecraft Builds",
        "Here are ten Minecraft houses you should build in your survival world."
    )
]


for url, title, content in pages:

    score = calculate_alignment(
        intention,
        url,
        title,
        content
    )

    print(title)
    print(f"Alignment: {score:.3f}")
    print()