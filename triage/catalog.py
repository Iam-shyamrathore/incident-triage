import hashlib
import json

from .config import ROOT

SOURCE = (
    "https://github.com/GoogleCloudPlatform/microservices-demo/tree/"
    "c7cb6d5bfd6ea3aed768634ebbcb98cb7a523712/kubernetes-manifests"
)

# Only payment gateway is synthetic. Other dependency edges are a subset curated
# from the pinned Online Boutique deployment manifests.
SERVICES = {
    "frontend": ("Storefront", "Web", ("front end", "storefront")),
    "checkoutservice": ("Checkout", "Commerce", ("checkout", "checkout api")),
    "paymentservice": ("Payments", "Payments", ("payments", "payment service")),
    "payment-gateway": (
        "Payment gateway",
        "Payments",
        ("payment gateway", "card gateway"),
    ),
    "shippingservice": ("Shipping", "Fulfillment", ("shipping",)),
    "cartservice": ("Cart", "Commerce", ("cart",)),
    "redis-cart": ("Cart Redis", "Platform", ("cart redis", "redis")),
    "productcatalogservice": (
        "Product catalog",
        "Catalog",
        ("catalog", "product catalog"),
    ),
    "currencyservice": ("Currency", "Commerce", ("currency",)),
    "recommendationservice": ("Recommendations", "Discovery", ("recommendations",)),
    "emailservice": ("Email", "Fulfillment", ("email",)),
    "adservice": ("Ads", "Discovery", ("ads",)),
}

DEPENDENCIES = {
    "frontend": (
        "checkoutservice",
        "shippingservice",
        "cartservice",
        "productcatalogservice",
        "currencyservice",
        "recommendationservice",
        "adservice",
    ),
    "checkoutservice": (
        "productcatalogservice",
        "shippingservice",
        "paymentservice",
        "emailservice",
        "currencyservice",
        "cartservice",
    ),
    "cartservice": ("redis-cart",),
    "recommendationservice": ("productcatalogservice",),
    "paymentservice": ("payment-gateway",),
}

# Skill metadata supplies the ranking hints. Tool schemas come from MCP.
SKILLS = {
    "inspect_errors": (
        "Check service error rates",
        "Compare failed requests in the replay window.",
        "errors failure 5xx",
        2,
    ),
    "trace_failures": (
        "Inspect failed traces",
        "Find which upstream span failed and what deployment handled it.",
        "errors failure timeout 5xx traces",
        1,
    ),
    "list_deployments": (
        "Inspect deployment history",
        "Check recent releases and the versions serving traffic.",
        "deploy release change rollout",
        0,
    ),
    "inspect_latency": (
        "Check service latency",
        "Compare tail latency in the active replay window.",
        "slow latency timeout performance",
        2,
    ),
    "dependency_health": (
        "Check dependency health",
        "Read dependency availability and response state.",
        "unavailable connection health timeout",
        1,
    ),
    "sample_logs": (
        "Read error samples",
        "Sample recent service logs for an actionable error.",
        "logs errors failure exception",
        0,
    ),
}

TOOLS_BY_SERVICE = {
    "checkoutservice": ("inspect_errors", "trace_failures", "list_deployments"),
    "paymentservice": ("inspect_errors", "list_deployments"),
    "payment-gateway": ("trace_failures", "inspect_latency", "dependency_health"),
    "cartservice": ("inspect_errors", "sample_logs"),
    "redis-cart": ("dependency_health", "inspect_latency", "sample_logs"),
    "shippingservice": ("inspect_errors", "trace_failures", "inspect_latency"),
    "productcatalogservice": ("inspect_errors", "list_deployments", "inspect_latency"),
    "recommendationservice": ("inspect_errors", "trace_failures"),
}
DEFAULT_TOOLS = ("inspect_errors", "sample_logs")


def stable_id(*parts: str) -> int:
    value = hashlib.blake2b("\0".join(parts).encode(), digest_size=8).digest()
    return int.from_bytes(value, "big") & ((1 << 62) - 1)


def normalized(text: str) -> str:
    return "".join(char for char in text.lower() if char.isalnum())


def label(service):
    return SERVICES[service][0]


def load_replays():
    records = json.loads((ROOT / "data" / "replays.json").read_text())
    replays = {record["id"]: record for record in records}
    if len(replays) != len(records):
        raise ValueError("Replay IDs must be unique")
    return replays


REPLAYS = load_replays()


def visible_signals(replay):
    return [
        signal
        for signal in replay["signals"]
        if signal["environment"] == replay["environment"]
        and 0 <= replay["at"] - signal["observed"] <= 30
    ]
