# Incident Triage · HydraDB Track 2

- **Live demo** [hydradb-incident-triage.vercel.app](https://hydradb-incident-triage.vercel.app)
- **Open-source repo** [Iam-shyamrathore/incident-triage](https://github.com/Iam-shyamrathore/incident-triage)
- **Loom** Paste the recording URL after following the [recording script](LOOM.md).
- **Benchmark evidence** [Raw replay and load results](https://hydradb-incident-triage.vercel.app/api/benchmark)

## Submission description

An on-call engineer can replay an ambiguous alert and get the first useful diagnostic check. Incident Triage runs self-hosted HydraDB inside the Vercel container. It resolves the alerted service and traverses dependencies, runbooks, skills and tool definitions. The agent receives only eligible diagnostics with resolved argument values. It executes a read-only MCP tool and shows the graph path, arguments and observed result.

We compared full-catalog prompting, flat BM25, a frozen graph and feedback-enabled retrieval using Qwen 2.5 1.5B on 12 synthetic holdouts. Correct first actions rose from 2/12 with the full catalog and 5/12 with flat search to 9/12 with the frozen graph and 12/12 after three rounds of verified feedback. The latter supplied a median of one tool schema versus six when preloading. A second run reproduced the accuracy curve. The held-out replays share scenario families. The Vercel demo rebuilds its graph and loads the verified replay feedback on cold start.

## Go-to-market

**Buyer** Platform engineering teams with on-call coverage, dependency catalogs and runbooks. The first product would be a read-only diagnostic add-on alongside their existing incident tooling. A pilot would replay a team’s sanitized incidents and measure time to the first correct check, false starts and evidence coverage.

Teams already pay for incident coordination and diagnostic context. Rootly’s catalog and Clay case study show adoption in this category. Interest in this specific prototype remains to be validated. [Rootly Catalog](https://rootly.com/catalog) · [Clay case study](https://rootly.com/customers/clay)

## Social drafts

**X**

> Built Incident Triage for @hydra_db. One checkout alert, a real dependency path, and a read-only MCP call. On 12 synthetic replays, the frozen graph scored 9/12 and reached 12/12 after feedback.
> Demo https://hydradb-incident-triage.vercel.app

**LinkedIn**

> A checkout alert tells the on-call engineer where the symptom showed up. It rarely tells them what to check first.
>
> For the HydraDB hackathon, I built Incident Triage. It follows dependencies from the alerted service, retrieves the relevant runbook and tool, and shows the evidence behind a read-only diagnostic call.
>
> On 12 synthetic holdout replays, a frozen HydraDB graph got 9 first checks right. Three rounds of verified feedback brought that to 12, with a median of one tool schema supplied to the model.
>
> If you work on an on-call team, I’d like to know which alert you’d replay first.
>
> Live demo https://hydradb-incident-triage.vercel.app
>
> Source https://github.com/Iam-shyamrathore/incident-triage

Tag the official HydraDB company page when posting on LinkedIn. Add the social post URLs to the submission if the form requests them.

## Final checklist

- Open the production URL in a signed-out browser and run Checkout 5xx.
- Verify the public GitHub repo and benchmark JSON open without authentication.
- Record the Loom and paste its viewable URL into the form.
- Publish the social posts and tag HydraDB.
- Submit the live URL, source URL and Loom URL through the organizer’s form.
