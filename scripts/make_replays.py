"""Generate repeatable synthetic telemetry without including answers in app data."""

import json
from pathlib import Path

SCENARIOS = {
    "gateway": (
        "checkoutservice",
        "errors",
        "Checkout requests are returning 5xx.",
        [
            (
                "checkoutservice",
                "error_counter",
                "request failures rose at checkout",
                9,
            ),
            (
                "payment-gateway",
                "error_counter",
                "upstream requests to the gateway are failing",
                10,
            ),
            ("shippingservice", "deploy", "a shipping release completed", 3),
        ],
    ),
    "shipping": (
        "checkoutservice",
        "errors",
        "Orders fail at checkout before confirmation.",
        [
            ("checkoutservice", "error_counter", "checkout failures rose", 7),
            (
                "shippingservice",
                "error_counter",
                "quote service reports a rising failure rate",
                11,
            ),
            (
                "payment-gateway",
                "error_counter",
                "gateway reported intermittent errors",
                6,
            ),
        ],
    ),
    "redis": (
        "checkoutservice",
        "connections",
        "Checkout is timing out while reading the cart.",
        [
            ("cartservice", "health", "cart service reports connection timeouts", 7),
            ("redis-cart", "health", "cart cache reports unavailable connections", 13),
            ("payment-gateway", "latency", "gateway latency is elevated", 3),
        ],
    ),
    "catalog": (
        "productcatalogservice",
        "latency",
        "Product lookups are slower than usual.",
        [
            (
                "productcatalogservice",
                "latency",
                "catalog lookups show elevated tail latency",
                11,
            ),
            ("productcatalogservice", "deploy", "a catalog rollout completed", 3),
        ],
    ),
    "recommendations": (
        "recommendationservice",
        "errors",
        "Recommendations return 5xx for several requests.",
        [
            (
                "recommendationservice",
                "error_counter",
                "recommendation requests are failing",
                10,
            ),
            ("productcatalogservice", "deploy", "a catalog rollout completed", 4),
        ],
    ),
    "no-evidence": (
        "checkoutservice",
        "errors",
        "Checkout alert came through without any fresh observations.",
        [],
    ),
}

ROWS = [
    ("gateway-01", "train", 1, "gateway", "payment-gateway", "trace_failures"),
    ("redis-01", "train", 1, "redis", "redis-cart", "dependency_health"),
    ("gateway-02", "train", 2, "gateway", "payment-gateway", "trace_failures"),
    ("shipping-01", "train", 2, "shipping", "shippingservice", "trace_failures"),
    ("gateway-03", "train", 3, "gateway", "payment-gateway", "trace_failures"),
    ("redis-02", "train", 3, "redis", "redis-cart", "dependency_health"),
    ("checkout-amber", "holdout", 0, "gateway", "payment-gateway", "trace_failures"),
    ("checkout-cobalt", "holdout", 0, "shipping", "shippingservice", "trace_failures"),
    ("cart-slate", "holdout", 0, "redis", "redis-cart", "dependency_health"),
    (
        "catalog-coral",
        "holdout",
        0,
        "catalog",
        "productcatalogservice",
        "inspect_latency",
    ),
    (
        "recommendations-fern",
        "holdout",
        0,
        "recommendations",
        "recommendationservice",
        "inspect_errors",
    ),
    ("checkout-missing", "holdout", 0, "no-evidence", None, None),
    ("checkout-crimson", "holdout", 0, "gateway", "payment-gateway", "trace_failures"),
    ("checkout-gold", "holdout", 0, "shipping", "shippingservice", "trace_failures"),
    ("cart-birch", "holdout", 0, "redis", "redis-cart", "dependency_health"),
    (
        "catalog-cyan",
        "holdout",
        0,
        "catalog",
        "productcatalogservice",
        "inspect_latency",
    ),
    (
        "recommendations-lilac",
        "holdout",
        0,
        "recommendations",
        "recommendationservice",
        "inspect_errors",
    ),
    ("checkout-stale", "holdout", 0, "no-evidence", None, None),
    ("catalog-01", "train", 1, "catalog", "productcatalogservice", "inspect_latency"),
    ("catalog-02", "train", 2, "catalog", "productcatalogservice", "inspect_latency"),
    (
        "recommendation-01",
        "train",
        2,
        "recommendations",
        "recommendationservice",
        "inspect_errors",
    ),
    (
        "recommendation-02",
        "train",
        3,
        "recommendations",
        "recommendationservice",
        "inspect_errors",
    ),
]

TITLES = {
    "checkout-amber": "Checkout 5xx",
    "checkout-cobalt": "Order confirmation failures",
    "cart-slate": "Cart connection timeouts",
    "catalog-coral": "Slow product lookups",
    "checkout-missing": "Alert without fresh evidence",
}

ALT_TEXT = {
    "checkout-crimson": "Intermittent server errors during checkout.",
    "checkout-gold": "Checkout requests return a server error before confirmation.",
    "cart-birch": "Cart lookups time out and block checkout.",
    "catalog-cyan": "Catalog reads are taking longer than expected.",
    "recommendations-lilac": "The recommendations endpoint is dropping requests.",
    "checkout-stale": "Checkout error alert with old and staging-only signals.",
    "catalog-01": "Tail latency moved after the inventory refresh.",
    "catalog-02": "Product page lookups are taking a few seconds.",
    "recommendation-01": "The recommendation handler is failing for some requests.",
    "recommendation-02": "The recommendations endpoint has a rising error count.",
}


def main():
    replays, training, gold = [], {}, {}
    for index, (case, split, batch, scenario, target, tool) in enumerate(ROWS):
        source, symptom, alert, inputs = SCENARIOS[scenario]
        early_times = {
            "catalog-01": 235,
            "catalog-02": 325,
            "recommendation-01": 355,
            "recommendation-02": 455,
        }
        at = early_times.get(case, 220 + index * 45)
        signals = [
            {
                "service": service,
                "kind": kind,
                "text": message,
                "severity": severity + (index % 2),
                "observed": at - 3 - offset,
                "environment": "production",
            }
            for offset, (service, kind, message, severity) in enumerate(inputs)
        ]
        signals.extend(
            [
                {
                    "service": "payment-gateway",
                    "kind": "deploy",
                    "text": "gateway deployment changed",
                    "severity": 20,
                    "observed": at - 2,
                    "environment": "staging",
                },
                {
                    "service": "shippingservice",
                    "kind": "error_counter",
                    "text": "earlier shipping errors",
                    "severity": 23,
                    "observed": at - 80,
                    "environment": "production",
                },
            ]
        )
        deployments = [
            {
                "service": service,
                "environment": "production",
                "at": at - 8 - offset,
                "key": f"{service}-r{index + 16}",
            }
            for offset, service in enumerate(dict.fromkeys(row[0] for row in inputs))
        ]
        telemetry = {}
        for service, kind, message, severity in inputs:
            record = telemetry.setdefault(service, {})
            if kind == "error_counter":
                record.update(
                    failed_requests=severity * 7 + index, sampled_requests=500
                )
                if service in {"payment-gateway", "shippingservice"}:
                    record["trace"] = (
                        f"{service}: {message}; upstream span ended with UNAVAILABLE"
                    )
            elif kind == "latency":
                record["p95_ms"] = 190 + severity * 69
            elif kind == "health":
                record["connection_status"] = (
                    "unavailable" if service == "redis-cart" else "degraded"
                )
            elif kind == "deploy":
                record["release"] = next(
                    item["key"] for item in deployments if item["service"] == service
                )
            record["log"] = message
        replays.append(
            {
                "id": case,
                "title": TITLES.get(case, case.replace("-", " ").title()),
                "public": case in TITLES,
                "service": source,
                "symptom": symptom,
                "split": split,
                "batch": batch,
                "alert": ALT_TEXT.get(case, alert),
                "at": at,
                "environment": "production",
                "signals": signals,
                "deployments": deployments,
                "telemetry": telemetry,
            }
        )
        labels = training if split == "train" else gold
        labels[case] = {"service": target, "tool": tool}
    root = Path(__file__).resolve().parents[1]
    (root / "data" / "replays.json").write_text(json.dumps(replays, indent=2) + "\n")
    (root / "data" / "training.json").write_text(json.dumps(training, indent=2) + "\n")
    (root / "tests" / "gold.json").write_text(json.dumps(gold, indent=2) + "\n")


if __name__ == "__main__":
    main()
