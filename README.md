# DoomEye
# Anchor

Anchor is a browser extension that helps people stay aware of why they went online in the first place.

A lot of apps and websites are built around keeping users engaged. Features like infinite scrolling, autoplay, recommendations, and short-form content make it really easy to open an app for one thing and end up spending way more time on something completely different.

Most tools that try to solve this problem focus on screen time. They tell you how long you spent on an app, set a timer, or block the app after a certain amount of time.

We wanted to approach the problem differently.

Instead of asking **"How long have you been online?"**, Anchor asks:

> **"Are you still doing what you came here to do?"**

## The Idea

When starting a browsing session, the user gives Anchor a reason for what they're doing.

For example:

> Learn how Kubernetes ingress works

As the user browses, Anchor looks at the context of the pages they're visiting and compares it to their original goal.

A session could look something like this:

```text
Goal: Learn Kubernetes ingress

Kubernetes Tutorial        94%
        ↓
Docker Networking          81%
        ↓
Developer Setup            58%
        ↓
MacBook Review             27%
        ↓
YouTube Shorts             11%
```

The goal isn't to interrupt someone as soon as they look at something unrelated. People naturally jump between topics when researching.

Instead, Anchor looks for a pattern where someone's browsing continues moving further away from what they originally wanted to do.

If that happens, Anchor gives the user a simple reminder:

> **Still what you came here for?**
>
> You originally wanted to learn about Kubernetes ingress, but your recent browsing has moved away from that.

The user can:

* Return to what they were doing
* Keep browsing
* Change their original goal

We're not trying to decide what someone should or shouldn't be doing. If someone wants to spend an hour watching TikTok or YouTube, that's completely fine. The problem we're interested in is when someone **didn't intend to spend that time doing it.**

## Why We're Building This

We've all had the experience of opening TikTok, Instagram, YouTube, Reddit, or another app to do one thing and somehow ending up somewhere completely different.

Current screen-time tools don't really capture that.

Spending an hour watching a movie you wanted to watch isn't the same as opening Instagram to respond to a message and realizing 45 minutes later that you've been scrolling Reels.

Both count as an hour of screen time.

We think the more interesting problem is the difference between **intentional and unintentional use**.

## How It Works

```text
User enters their goal
        ↓
User browses normally
        ↓
Anchor reads the context of the current page
        ↓
Current page is compared to the user's goal
        ↓
Anchor tracks how that changes throughout the session
        ↓
If the user continues drifting away from their goal,
Anchor checks in
```

We're calling this **Intent Alignment**.

A high alignment means what you're looking at is closely related to what you originally wanted to do.

A low alignment doesn't automatically mean you're distracted. Anchor looks at multiple pages before deciding whether to step in.

## Example

Say I open YouTube because I need to understand Kubernetes for a project.

I tell Anchor:

> "Learn Kubernetes ingress"

I watch a Kubernetes tutorial.

Then I watch something about Docker networking.

That's still pretty related.

Then I click a developer setup video.

Then a MacBook review.

Then a gaming setup.

Then Shorts.

At that point, Anchor could recognize that my browsing has slowly moved away from Kubernetes and ask whether I still want to continue.

If I do, I can keep going.

If I don't, Anchor can take me back to one of the pages that was related to my original goal.

## What We're Building

For the hackathon, we're keeping the first version pretty simple.

* Chrome extension
* Set a goal before browsing
* Read basic webpage context
* Compare the page to the user's goal
* Track intent alignment throughout the session
* Detect continued drift
* Give the user a reminder
* Let the user return to their original task
* Show a basic summary when the session ends

## Tech Stack

* JavaScript
* HTML/CSS
* Chrome Extension Manifest V3
* Python
* Flask/FastAPI
* Embeddings / LLM API
* Chrome Local Storage

## Privacy

Anchor needs some information about what the user is browsing in order to compare it to their goal, so privacy is something we want to be careful about.

We don't want Anchor to become another service collecting people's browsing history.

For the prototype, we're trying to keep the information we collect to what is actually needed for the current session and avoid permanently storing browsing history.

Long term, we'd like as much of the analysis as possible to happen locally.

## Research

Before building Anchor, we looked into research surrounding:

* Digital well-being
* Problematic social media use
* Normative dissociation
* Dark patterns
* Infinite scrolling
* Persuasive design
* Digital self-control tools
* Design friction
* Human agency
* Intentional technology use

One of the main things we found was that simply measuring screen time doesn't tell the whole story.

That led us to the question we're exploring with Anchor:

> **Can we recognize when someone's online activity starts moving away from what they actually intended to do?**

We're not claiming that our prototype can perfectly identify when someone is distracted or mindlessly scrolling. Right now, we're testing whether the context of someone's browsing can be used as one signal for recognizing that change.

## Future Ideas

There are a lot of things we won't be able to build in 48 hours that we'd like to explore later.

Some of those include:

* Looking at scrolling behavior
* Detecting recommendation chains
* Learning what types of reminders work for different users
* Automatically understanding a user's goal
* Running more of the system locally
* Supporting mobile apps
* Comparing intentional browsing with passive browsing
* Testing whether users actually feel more in control while using the tool

Eventually, the idea could go beyond a browser extension.

Social media, video platforms, shopping apps, games, news sites, and other digital products all compete for people's attention.

We're interested in whether users can have tools that help them stay in control of that attention too.

## Status

Currently being built for a 36-hour hackathon.

### MVP Progress

* [x] Chrome extension
* [x] Set user intention
* [x] Extract webpage context
* [x] Compare webpage to intention *(stub similarity, pending real embeddings)*
* [x] Track intent alignment
* [x] Detect drift
* [x] Intervention popup
* [x] Return to goal
* [x] Session summary

## Development

This is a plain Manifest V3 extension, no build step required. Extension code lives in [extension/](extension/).

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** and select the `extension/` folder
4. Click the Anchor icon, enter a goal, and start browsing

### Structure

* `extension/manifest.json` — MV3 manifest
* `extension/shared.js` — constants, storage helpers, and the drift-score stub (loaded by all three contexts below)
* `extension/background.js` — service worker; owns session state and the drift check on each page report
* `extension/content.js` — injected on every page; extracts page context, tracks SPA navigation, renders the intervention modal
* `extension/popup.html` / `popup.js` / `popup.css` — intention input, live session status, and the end-of-session summary

### Integration point for drift logic

`computeDriftScoreStub` in `shared.js` is a placeholder keyword-overlap scorer so the
full session → tracking → intervention → summary pipeline works end-to-end today.
Swap its body for a call to the real embeddings/similarity API — the signature
(`goal, pageContext) -> Promise<number in [0, 1]>`) and `classifyScore` thresholds
are the integration seam.

### Planned: attention detection

A follow-up feature will use the webcam (processed locally, nothing uploaded) to
detect when the user looks away from the screen for an extended period, as a
complement to the semantic drift signal above.

## Team

Jachamfuor 
Taysfer

Built at VTHacks.

