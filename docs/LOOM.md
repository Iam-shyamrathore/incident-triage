# Loom walkthrough · Incident Triage

Target length **2 minutes 30 seconds**. Start on the live replay page. Briefly run the app before recording so a cold start fits the walkthrough.

## 0:00–0:20 · The problem

**Show** The demo home with Checkout 5xx selected.

> Checkout is throwing errors. If you’re on call, you have to work out whether to inspect Checkout, Payments, Shipping, or something further upstream. Incident Triage gives that engineer a first diagnostic action and the evidence behind it. This is our HydraDB Track 2 build.

## 0:20–0:55 · Run the replay

**Show** Select **HydraDB with feedback** and click **Run triage**. Point to the tool finding before expanding the raw result.

> We resolve Checkout in HydraDB and traverse Checkout, Payments and the payment gateway. The traversal also retrieves the gateway’s runbook, diagnostic skill and registered MCP tool. The selected action checks failed gateway traces. The replay tool reports that the upstream span ended with UNAVAILABLE.

**Show** Scroll down the evidence path and open **Agent context** and **MCP result**.

> This path comes from live HydraDB queries. The tool was called through MCP with the service and observation window already bound. You can see which schemas were supplied and inspect the actual response.

## 0:55–1:20 · Show a different route

**Show** Choose **Cart connection timeouts** and run it.

> The alerted service is still Checkout, but the observations are different. The graph traversal and evidence lead to Cart Redis and a dependency health check. The MCP response shows unavailable connections. The incident observations and tool responses in this sandbox are synthetic.

## 1:20–1:55 · Benchmark and learning

**Show** Scroll to **Benchmark** and highlight the routing table and learning checkpoints.

> We evaluated the exact first diagnostic action, its service and arguments, and whether the tool actually returned evidence. On 12 synthetic holdouts, all-tools prompting got 2 correct, flat search got 5, and the frozen HydraDB graph got 9. We wrote earlier verified outcomes into HydraDB. Across three rounds on the same holdout, the result went from 9 to 9, then 10, then 12. The learned context supplied a median of one schema versus six when preloading. These are results on this replay fixture, whose cases share scenario families.

**Show** Briefly open **View raw benchmark JSON** if time allows.

## 1:55–2:30 · Deployment and buyer

**Show** Return to the demo or GitHub README.

> The public app runs the HydraDB engine inside a Vercel container. Each new instance seeds the same graph and loads the verified feedback. The product would sit alongside an SRE team’s on-call tooling. Our first pilot would use a team’s sanitized incidents to test whether we cut time to the first correct check. The live demo, source and raw results are linked in the submission.

Point to **Routing** after the replay.

> The live demo uses Gemini 3.5 Flash-Lite. The benchmark used Qwen 2.5 1.5B for all four compared strategies.
