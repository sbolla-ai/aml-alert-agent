# Portfolio text for sbolla.dev

**Card**

> **AML Alert Investigation Agent** · Side project · Finance
> An AI investigator for a bank's AML team: it works each alert, recommends escalate or close, and drafts the SAR narrative. Every number is checked against the evidence, code decides what may be closed, and a person makes every final call.
> Stack: Python, Claude API, sanctions screening (OFAC SDN format), hash-chained audit log, pytest gates, GitHub Actions
> Result: a scripted bad model made 9 realistic mistakes and all 9 were caught, with 0 laundering cases closed. The ablation shows why: with the risk floor off, one well-cited but wrong closure gets through.

**Full case study**

- **Problem:** Most of a bank's AML cost is analysts reviewing alerts that turn out to be legitimate. A model can help, but only if it can't close a real case, invent a fact, or obey instructions hidden in transaction data.
- **What I built:**
  - Monitoring rules raise alerts, and read-only tools gather the evidence.
  - Code computes every number and a risk score.
  - The investigator (Claude, or a rules baseline) recommends escalate or close and drafts the SAR.
  - A verifier removes anything not supported by the evidence, and a safety floor decides what may be closed.
  - A governance pack for model risk is regenerated on every CI run.
- **Key finding:** supported isn't the same as right. A closure where every sentence was true and cited was still wrong. The verifier can't catch that, so closures are limited to low-risk cases scored in code.
- **Screening:** fuzzy matching caught 18/18 spelling variants of listed names vs. 1/18 for literal matching. Decoys still go to a person, with the evidence to clear them.
- **Honest limits:** synthetic bank I designed; the rules baseline is an upper bound; the risk threshold was set on this data with a one-point margin; real OFAC and AMLworld loaders are tested on fixtures only.

**Interview story (30 seconds)**
"I built an AML alert investigator and then tried to break it. A verifier caught the obvious failures: invented numbers, fake transaction IDs, a prompt injection in a wire memo. Then I planted a closure where every sentence was true and cited, and the judgment was simply wrong. The verifier passed it. That taught me the most important control: the model can say what the evidence supports, but code decides which cases it's allowed to recommend closing, and a person signs off. I ship the ablation in CI so the bank can see why that control exists."
