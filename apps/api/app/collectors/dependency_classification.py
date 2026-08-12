"""Explainable heuristics for classifying third-party request domains.

Deliberately simple substring matching against well-known hostnames — no
vendor API calls, no unsupported claims. Anything unmatched is reported as
"uncategorized" rather than guessed.
"""

CATEGORY_PATTERNS: dict[str, list[str]] = {
    "analytics": [
        "google-analytics.com", "analytics.google.com", "googletagmanager.com/gtag",
        "segment.io", "segment.com", "mixpanel.com", "amplitude.com", "hotjar.com",
        "plausible.io", "matomo",
    ],
    "tag_manager": ["googletagmanager.com"],
    "advertising": [
        "doubleclick.net", "googlesyndication.com", "googleadservices.com",
        "facebook.net", "connect.facebook.net", "ads-twitter.com", "bing.com/bat",
        "criteo.com", "taboola.com", "outbrain.com",
    ],
    "payment": ["stripe.com", "js.stripe.com", "paypal.com", "paypalobjects.com", "squareup.com"],
    "customer_support_chat": [
        "intercom.io", "widget.intercom.io", "drift.com", "zendesk.com", "zdassets.com",
        "livechatinc.com", "crisp.chat", "tawk.to", "helpscout",
    ],
    "cdn": [
        "cloudflare.com", "cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com",
        "akamai", "fastly.net", "cloudfront.net",
    ],
    "social_embeds": [
        "platform.twitter.com", "connect.facebook.net", "instagram.com/embed",
        "youtube.com/embed", "player.vimeo.com", "linkedin.com/embed",
    ],
    "tag_hosting_ecommerce": ["shopify.com", "cdn.shopify.com"],
    "forms_marketing": ["hubspot.com", "hs-scripts.com", "hsforms.com", "mailchimp.com"],
}


def classify_hostname(hostname: str) -> tuple[str, str]:
    """Returns (category, detection_method)."""
    lowered = hostname.lower()
    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if pattern in lowered:
                return category, f"hostname matched known pattern {pattern!r}"
    return "uncategorized", "no known third-party pattern matched"
