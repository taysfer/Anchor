# Minimum number of pages a session must contain
# before DoomEye begins checking for drift
MIN_SESSION_PAGES = 4

# Number of recent pages used to analyze browsing behavior
RECENT_WINDOW = 3

# Experimental thresholds based on early prototype testing
LOW_ALIGNMENT = 0.25
RECENT_AVERAGE_THRESHOLD = 0.30

# Amount alignment must decrease before we consider
# the recent browsing pattern to have a meaningful downward trend
TREND_DROP_THRESHOLD = 0.20


def is_declining(scores: list[float]) -> bool:
    """
    Checks whether alignment has meaningfully decreased
    across the recent browsing history.
    """

    # Do not analyze trends until enough session history exists
    if len(scores) < MIN_SESSION_PAGES:
        return False

    # Only analyze the most recent pages
    recent_scores = scores[-RECENT_WINDOW:]

    first_score = recent_scores[0]
    last_score = recent_scores[-1]

    # Measure how much alignment decreased
    drop = first_score - last_score

    return drop >= TREND_DROP_THRESHOLD


def is_recovering(scores: list[float]) -> bool:
    """
    Checks whether alignment is currently moving back
    toward the user's original intention.
    """

    # Do not analyze recovery until enough session history exists
    if len(scores) < MIN_SESSION_PAGES:
        return False

    recent_scores = scores[-RECENT_WINDOW:]

    # Each recent page must be more aligned
    # than the page before it
    return all(
        recent_scores[i] < recent_scores[i + 1]
        for i in range(len(recent_scores) - 1)
    )


def detect_drift(scores: list[float]) -> bool:
    """
    Determines whether recent alignment scores suggest
    sustained movement away from the user's intention.
    """

    # Wait until enough pages have been visited before
    # making any drift decision
    if len(scores) < MIN_SESSION_PAGES:
        return False

    # Analyze only the recent browsing window
    recent_scores = scores[-RECENT_WINDOW:]

    # Calculate average alignment across recent pages
    recent_average = sum(recent_scores) / len(recent_scores)

    # Most recent page represents the user's current position
    current_score = scores[-1]

    current_is_low = current_score < LOW_ALIGNMENT
    recent_is_low = recent_average < RECENT_AVERAGE_THRESHOLD

    declining = is_declining(scores)
    recovering = is_recovering(scores)

    # Recent browsing has remained poorly aligned
    # without showing signs of recovery
    sustained_low = (
        current_is_low
        and recent_is_low
        and not recovering
    )

    # Alignment has meaningfully decreased and
    # the current page has low alignment
    downward_drift = (
        current_is_low
        and declining
    )

    return sustained_low or downward_drift