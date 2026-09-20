from app.services.drift import detect_drift


test_cases = [
    # BASIC CASES

    (
        "Still aligned",
        [0.705, 0.650, 0.610]
    ),

    (
        "One unrelated page then recovery",
        [0.705, 0.135, 0.690]
    ),

    (
        "Gradual drift",
        [0.705, 0.295, 0.190, 0.132]
    ),

    (
        "Sustained low alignment",
        [0.190, 0.132, 0.135, 0.140]
    ),

    (
        "Not enough history",
        [0.705, 0.135]
    ),


    # RECOVERY CASES

    (
        "Drifts but returns to goal",
        [0.705, 0.295, 0.150, 0.650]
    ),

    (
        "Two unrelated pages then recovery",
        [0.705, 0.150, 0.120, 0.700]
    ),

    (
        "Temporary unrelated page in long session",
        [0.700, 0.680, 0.720, 0.130, 0.690]
    ),


    # SLOW DRIFT
    (
        "Slow decline",
        [0.700, 0.600, 0.500, 0.400, 0.300, 0.200]
    ),

    (
        "Slow decline but still somewhat related",
        [0.700, 0.620, 0.550, 0.480, 0.410]
    ),

    (
        "Eventually becomes unrelated",
        [0.700, 0.550, 0.400, 0.280, 0.180, 0.120]
    ),


    # LOW BUT STABLE
    (
        "Always low",
        [0.180, 0.190, 0.170, 0.160]
    ),

    (
        "Low but slightly increasing",
        [0.100, 0.150, 0.200]
    ),

    (
        "Low scores with small fluctuations",
        [0.180, 0.220, 0.190, 0.210, 0.170]
    ),


    # BORDERLINE THRESHOLDS

    (
        "Current score exactly low threshold",
        [0.200, 0.200, 0.250]
    ),

    (
        "Current score barely below threshold",
        [0.200, 0.200, 0.249]
    ),

    (
        "Recent average near threshold",
        [0.290, 0.300, 0.290]
    ),


    # ERRATIC BROWSING
    (
        "Alternating related and unrelated",
        [0.700, 0.100, 0.700, 0.100, 0.700]
    ),

    (
        "Alternating but ends unrelated",
        [0.700, 0.100, 0.700, 0.100]
    ),

    (
        "Chaotic browsing",
        [0.650, 0.120, 0.500, 0.180, 0.600, 0.140]
    ),


    # EDGE CASES
    (
        "Empty history",
        []
    ),

    (
        "Only one page",
        [0.100]
    ),

    (
        "Exactly three aligned pages",
        [0.600, 0.600, 0.600]
    ),

    (
        "Exactly three unrelated pages, still not enough history",
        [0.100, 0.100, 0.100]
    ),

    (
        "Negative similarity scores",
        [-0.050, -0.100, -0.080, -0.120]
    ),
]


for name, scores in test_cases:

    drifted = detect_drift(scores)

    print(name)
    print(f"Scores: {scores}")
    print(f"Drift detected: {drifted}")
    print("-" * 50)