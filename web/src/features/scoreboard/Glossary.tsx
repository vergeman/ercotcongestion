import Tooltip from "../../components/ui/Tooltip";

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

// Right-rail glossary: plain-language notes on the sources and metrics.
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
          <b>μ:</b> a constraint's shadow price (≥ 0), its $/MWh cost when{" "}
          <Term def="A constraint binds when its transmission line hits a physical limit; at that instant its shadow price μ rises above $0.">
            binding
          </Term>
          .
        </p>
        <p className="sb-guide__where">
          <b>SF:</b> the shift factor represents how much flow travels along a constraint when 1 MW is injected at that node. (Recovered by ridge regression.)
        </p>
        <br />
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
          learn to say "about zero", which is generally correct, but not when it diverges.
        </p>
        <div className="sb-guide__eg">
          <b>Example.</b> At 5pm:
          <ol>
            <li>Head 1 estimates a 10% binding chance: <code>P(bind) = 0.10</code>.</li>
            <li>Head 2 estimates a $200 shadow price if it binds: <code>E[μ | bind] = $200</code>.</li>
            <li>Multiply them: <code>E[μ] = 0.10 × $200 = $20</code>.</li>
            <li>A node with <code>SF = −0.3</code> carries <code>−SF · μ = −(−0.3) × $20 = +$6</code> of congestion.</li>
          </ol>
        </div>
      </div>

      <div className="sb-guide__block">
        <div className="sb-guide__h">Model Comparison Graph</div>
        <dl className="sb-guide__dl">
          <dt>Model Forecast</dt>
          <dd>The forecast; using SF to project nodal congestion.</dd>
          <dt>Prior-day (Persistence)</dt>
          <dd>
            Naive baseline: tomorrow repeats yesterday. Each node's congestion
            is set to its actual value at the same hour on the prior day.
          </dd>
          <dt>Trailing-window Average (Baseline)</dt>
          <dd>
            Historical-average baseline, computed per hour: how often a
            node has congested at this hour x the severity when it does.
            Example: a node that binds at 8pm on 6 of the past 100 days,
            averaging $150 when it does, gets an 8pm climatology of 0.06 x $150 = $9.
          </dd>
          <dt>Settled-μ Ceiling (Oracle)</dt>
          <dd>
            If you were given the answer: when ranking nodes by their realized congestion
            the SF matrix would be the only source of variation, so the settled-μ is
            the ceiling to measure against.
          </dd>
        </dl>
      </div>

      <div className="sb-guide__block">
        <div className="sb-guide__h">Pre / Post-RTC+B</div>
        <p className="sb-guide__p">
          RTC+B was ERCOT's real-time co-optimization + batteries market change
          on 2025-12-11. The record splits to measure the model through the redesign;
          post-RTC+B includes live final grades.
        </p>
      </div>

      <div className="sb-guide__block">
        <div className="sb-guide__h">
          Scoring: does it rank the right nodes?
        </div>
        <dl className="sb-guide__dl">
          <dt>Rank ρ (Spearman)</dt>
          <dd>
            How well the predicted ordering of nodes matches the actual order.
          </dd>
          <dt>Sign Agreement</dt>
          <dd>
            How often the direction is right (import vs export). 0.5 = coin
            flip.
          </dd>
          <dt>Top-Decile Hit</dt>
          <dd>
            Of the nodes predicted to be in the most-congested 10%, the fraction that
            were actually in the realized most-congested 10%.
          </dd>

        </dl>
      </div>
    </aside>
  );
}
