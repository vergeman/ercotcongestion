import Tooltip from "../../components/ui/Tooltip";

// An inline defined term: a dotted-underlined word whose definition rides the
// shared app-wide Tooltip. `.sb-term` supplies only the underline; the popover,
// positioning, and hover/focus behavior all come from Tooltip. Opens below to
// stay clear of the rail's top scroll edge.
function Term({
  children,
  def,
}: {
  children: React.ReactNode;
  def: React.ReactNode;
}) {
  return (
    <Tooltip as="span" className="sb-term" placement="bottom" tip={def}>
      {children}
    </Tooltip>
  );
}

// Right-rail glossary: plain-language notes on the sources and metrics, so a
// figure never has to be decoded from memory.
export function Glossary() {
  return (
    <aside className="sb-guide">
      <div className="sb-guide__block">
        <div className="sb-guide__h">What the model predicts</div>
        <p className="sb-guide__p">
          A node's congestion price is a linear combination of every binding
          constraint's shadow price, weighted by that node's shift factor to
          each constraint:
        </p>
        <p className="sb-guide__eq">congestion = −Σ SF · μ</p>
        <p className="sb-guide__where">
          <b>μ:</b> a constraint's shadow price (≥ 0) — its $/MWh cost when{" "}
          <Term def="A constraint binds when its transmission line hits a physical limit; at that instant its shadow price μ rises above $0.">
            binding
          </Term>
          .
        </p>
        <p className="sb-guide__where">
          <b>SF:</b> the shift factor — the node's marginal sensitivity to that
          constraint. Recovered offline by ridge regression on the price
          identity, then treated as known — so the model only forecasts μ.
        </p>
        <p className="sb-guide__p">
          <Term def="A constraint binds when its transmission line hits a physical limit; at that instant its shadow price μ rises above $0.">
            Binding
          </Term>{" "}
          is rare (~3% of hours), so μ is split into two{" "}
          <Term def="A 'head' is one sub-model output. The forecast trains two and multiplies them together.">
            heads
          </Term>
          , multiplied:
        </p>
        <p className="sb-guide__eq">E[μ] = P(bind) · E[μ | bind]</p>
        <dl className="sb-guide__dl">
          <dt>Head 1: P(bind)</dt>
          <dd>
            Probability of binding: the chance the constraint binds this hour.
            Fit with a gradient-boosted classifier.
          </dd>
          <dt>Head 2: E[μ | bind]</dt>
          <dd>
            Expected shadow price given binding: how severe μ is when it does.
            Fit with a gradient-boosted regressor on log(μ), over binding hours
            only.
          </dd>
        </dl>
        <p className="sb-guide__p">
          Splitting matters: a single head (“regressor”) over all hours would
          just learn to say “about zero” — right on average, useless when it
          counts.
        </p>
        <p className="sb-guide__eg">
          <b>Example.</b> At 5pm the model sees a 10% chance a line binds —
          P(bind) = 0.10, Head&nbsp;1 — and a $200 shadow price if it does — E[μ
          | bind] = $200, Head&nbsp;2. Multiply: E[μ] = 0.10 × $200 = $20. A
          node with SF = −0.3 to that line then carries −SF · μ = −(−0.3) × $20
          = +$6 of congestion.
        </p>
      </div>

      <div className="sb-guide__block">
        <div className="sb-guide__h">Model Comparison Graph</div>
        <dl className="sb-guide__dl">
          <dt>Model Forecast</dt>
          <dd>The offline forecast construction, projected to nodal congestion.</dd>
          <dt>Prior-day (Persistence)</dt>
          <dd>
            Naïve baseline: tomorrow repeats yesterday. Each node's congestion
            is set to its actual value at the same hour on the prior day.
          </dd>
          <dt>Trailing-window Average (Baseline)</dt>
          <dd>
            Historical-average baseline, computed per hour-of-day: how often a
            node has congested at this hour × its typical severity when it does.
            No day-to-day signal — just the long-run norm. Example: a node that
            binds at 8pm on 6 of the past 100 days, averaging $150 when it does,
            gets an 8pm climatology of 0.06 × $150 ≈ $9.
          </dd>
          <dt>Settled-μ Ceiling (Oracle)</dt>
          <dd>
            If you already knew the answer: the score you'd get ranking nodes by
            their realized congestion. A ceiling to measure against, not a
            rival.
          </dd>
        </dl>
      </div>

      <div className="sb-guide__block">
        <div className="sb-guide__h">Pre / Post-RTC+B</div>
        <p className="sb-guide__p">
          RTC+B was ERCOT's real-time co-optimization + batteries market change
          on 2025-12-11. We split the record there to check if the model's edge
          held through the redesign; post-RTC+B includes live final grades.
        </p>
      </div>

      <div className="sb-guide__block">
        <div className="sb-guide__h">
          Scoring: does it rank the right nodes?
        </div>
        <dl className="sb-guide__dl">
          <dt>Top-Decile Hit</dt>
          <dd>
            Of the nodes we predict in the worst 10%, the fraction that were
            actually in the realized worst 10%. 1 = every flagged node truly
            belonged there; ~0.1 = chance.
          </dd>
          <dt>Rank ρ (Spearman)</dt>
          <dd>
            How well the predicted ordering of nodes matches the actual order. 1
            = identical, 0 = unrelated.
          </dd>
          <dt>Sign Agreement</dt>
          <dd>
            How often the direction is right (import vs export). 0.5 = coin
            flip.
          </dd>
        </dl>
      </div>
    </aside>
  );
}
