# Loom walkthrough · Incident Triage

Target length **2 minutes 30 seconds**. Start on the [live workbench](https://hydradb-incident-triage.vercel.app). Run the demo once before recording so a cold start fits the walkthrough.

## 0:00–0:20 · The problem

**Show** The editable alert and evidence in **Your incident**.

> Checkout is throwing errors. The on-call engineer has to pick which service to inspect first. This workbench uses a dependency graph to find the relevant diagnostic and show the evidence behind it.

## 0:20–1:05 · Change the graph scope

**Show** Edit the failed-trace value. For example, enter **Gateway returned SAMPLE-503 after handshake**. Set **Dependency depth** to **1 hop** and click **Run triage**. Expand **Services HydraDB reached**.

> I entered my own measurement from the payment gateway. At one hop the gateway is outside the reachable set, so the app abstains.

**Show** Change to **2 hops**, run again, and expand **MCP result**.

> Now the real HydraDB traversal reaches Checkout → Payments → Payment gateway. The graph provides the diagnostic skill and its tool definition. Gemini selects it, and the read-only MCP result contains the exact text I supplied.

## 1:05–1:30 · Change the evidence

**Show** Keep Checkout as the alerted service. Set the evidence service to **Cart Redis**, the measurement to **Dependency health**, and the value to **Unavailable**. Run again at two hops.

> The alert is still from Checkout. Changing the evidence changes which service and tool the agent checks. This graph is seeded from an Online Boutique topology. These are test measurements supplied in the workbench.

## 1:30–2:05 · Show the learning evaluation

**Show** Scroll to **Benchmark**. Highlight the scoring table and learning checkpoints.

> We evaluated the exact first action, its service and arguments, and whether the tool returned evidence. On 12 synthetic holdouts, all-tools prompting got 2 correct, flat search got 5, and the frozen graph got 9. Writing earlier verified outcomes into HydraDB increased that from 9 to 9, then 10, then 12 over three rounds. The learned context supplied a median of one tool schema versus six when preloading.

> The workbench runs Gemini 3.5 Flash-Lite. That benchmark used Qwen 2.5 1.5B across all strategies, and its synthetic holdouts share scenario families.

## 2:05–2:30 · Buyer and deployment

**Show** The live URL or the repository.

> Vercel hosts both the workbench and the self-hosted HydraDB engine. The first customer would be a platform engineering team with an on-call rotation. We’d replay their sanitized incidents to see whether this cuts time to the first correct diagnostic. The live URL, source, and raw benchmark are linked in the submission.
