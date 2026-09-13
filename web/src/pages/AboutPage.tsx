import { Link } from "react-router-dom";
import HeaderNav from "../components/layout/HeaderNav";
import "./about-page.css";

const introVideo = "/screenshots/ercot-congestion-intro.mp4";

function Formula({ children }: { children: string }) {
  return <pre className="about-page__formula"><code>{children}</code></pre>;
}

export default function AboutPage() {
  return (
    <div className="about-page">
      <header className="about-page__topbar">
        <HeaderNav active="about" />
      </header>

      <main className="about-page__main">
        <section className="about-page__hero" aria-labelledby="about-title">
          <div>
            <p className="about-page__eyebrow label">Grid structure explorer</p>
            <h1 id="about-title">ERCOT Stress</h1>
            <p className="about-page__lede">
              ERCOT Stress maps where congestion is priced across ERCOT, then recovers the hidden shift factors behind it.
              It uses that structure to forecast tomorrow’s congestion and evaluates its track record after settlement.
            </p>
            <a className="about-page__github" href="https://github.com/vergeman/ercotstress">View on GitHub</a>
          </div>
          <video className="about-page__video" controls playsInline preload="metadata" aria-label="ERCOT Stress congestion explorer demonstration">
            <source src={introVideo} type="video/mp4" />
            Your browser does not support embedded video.
          </video>
        </section>

        <section aria-labelledby="four-pages">
          <h2 id="four-pages">The Four Pages of ERCOT Stress</h2>
          <div className="about-page__page-grid">
            <article><h3><Link to="/">Homepage Brief</Link></h3><p>A daily scan of nodal congestion and constraint shadow prices of interest, typically outside their recent p10–p90 30-day range.</p></article>
            <article><h3><Link to="/map">Map</Link></h3><p>Displays nodal congestion, LMPs, and each constraint’s electrical footprint. Toggle between forecast and settlement data; hourly playback shows when and where congestion occurs.</p></article>
            <article><h3><Link to="/matrix">Matrix</Link></h3><p>Explore recovered shift factors and each constraint’s congestion contribution to a node; it shows why a node prices the way it does.</p></article>
            <article><h3><Link to="/scoreboard">Scoreboard</Link></h3><p>Evaluates the forecast over time and against baselines.</p></article>
          </div>
          <p>Each page presents a distinct lens on ERCOT’s network topology, congestion, shift factors, and an attempt at price forecasting.</p>
        </section>

        <section aria-labelledby="system-price">
          <h2 id="system-price">System Price and Congestion</h2>
          <p>Most retail consumers pay a fixed price from one utility, but wholesale power operates as a nodal market, with variable prices at different points throughout the grid. In Texas, <a href="https://www.ercot.com/">ERCOT</a> operates the electrical grid and related market operations.</p>
          <p>Imagine an electrical grid without delivery restrictions and with unlimited transmission capacity. Wind in the south could power Houston and daytime eastern solar could reach Dallas. With no transmission limitations, power could flow freely and the marginal cost of serving the next MW would be the same throughout the grid. This base price is the <strong>system price (λ)</strong>.</p>
          <p>In reality, transmission paths have finite capacity and operating limits. Once a path is saturated, generation must be dispatched differently and cheaper distant generation is replaced by more expensive local generation. The resulting location-specific cost is <strong>nodal congestion</strong>; together with the system price, it sets the <strong>LMP</strong> (Locational Marginal Price).</p>
          <Formula>{"LMP = System Price (λ) + congestion"}</Formula>
        </section>

        <section aria-labelledby="constraints">
          <h2 id="constraints">Constraints: the Hidden Layer</h2>
          <p>Transmission limitations are called <strong>constraints</strong>. A constraint is not a node: it is an imposed restriction or operating rule. It can reduce flow for maintenance, preserve operating limits and stability, or enact export restrictions across a region. Operators keep margin below physical limits so the grid operates reliably and with redundancy.</p>
          <p>ERCOT writes constraints as <code>Monitored Element | Contingency</code>. The monitored element may be a line, transformer, regional shorthand, or opaque identifier such as <code>6437</code>. Names use a contracted station and voltage naming scheme, so topology knowledge is usually needed to interpret them.</p>
          <div className="about-page__columns">
            <div><h3>Types of constraints</h3><ul><li><strong>Transmission:</strong> a line or transformer corridor, e.g. <code>6830__C | SGRMGRS8</code>.</li><li><strong>Radial:</strong> serves a pocket and can create sharp local spikes, e.g. <code>OLINGR_FMR1 | BASE CASE</code>.</li><li><strong>GTC:</strong> an operator-defined stabilization or voltage restriction spanning a region, e.g. <code>WESTEX | BASE_CASE</code> or <code>NELRIO | BASE_CASE</code>.</li></ul></div>
            <div><h3>Types of contingencies</h3><ul><li>Single (<code>S</code>) or double (<code>D</code>) outage.</li><li>Transformer (<code>X</code>) or multi-element (<code>M</code>) outage.</li><li><code>BASE CASE</code>: no failure, but a restriction during normal operation.</li></ul></div>
          </div>

          <h3>Constraint Limits and Shadow Prices</h3>
          <p>Once flow reaches a limit, a constraint <em>binds</em>: the limit is active but not violated. Its <strong>shadow price (μ)</strong> measures the economic pressure at the bottleneck—what it would cost if the limit could be relaxed by one additional MW. It is the system-wide cost of preserving the limit, not simply the fuel cost of another generator.</p>
          <p>ERCOT publishes hourly binding constraints and shadow prices, but their effect on nodal prices is not apparent from a name alone. A ridge regression on public prices recovers an estimated shift-factor matrix, making each constraint’s electrical footprint visible and geographically locatable.</p>

          <h4>Always-on constraints</h4>
          <p>A handful of constraints appear almost daily and shape regional flow patterns. <code>LPLMK_LPLNE_1</code>, a 115 kV West Texas line, appeared in 95.9% of the trailing 365 days. <code>HARGRO_TWINBU1_1</code>, <code>6437__F</code>, <code>NELRIO</code>, and <code>E_PASP</code> also appeared on more than 90% of days in a six-month window.</p>
          <p>Always-on does not mean expensive. Frequency and cost are different axes: <code>DIESEL_FMR1</code> appeared in 82.3% of trailing days with a shadow near $0, while <code>LAKENA_SAMATH1_1</code> appeared 79.6% of the time with a daily shadow-price total of $1,558.</p>
        </section>

        <section aria-labelledby="shift-factors">
          <h2 id="shift-factors">Shift Factors, Shadow Prices, and Congestion</h2>
          <p>A shadow price says how costly a constraint is, not which nodes become expensive or cheap. A <strong>shift factor</strong> supplies that relationship: a value in <code>[-1, 1]</code> representing how much additional flow travels along a constraint when one MW is injected at a node.</p>
          <Formula>{"congestion = −Σ SF·μ"}</Formula>
          <p>The shift-factor matrix has constraint rows and node columns. An <code>SF</code> of −0.4 means a one-MW injection at that node reduces flow along the constraint by 0.4 MW. With a positive shadow price, negative shift factors produce positive congestion and raise price; positive shift factors lower price.</p>
          <ul><li><code>SF &lt; 0</code> — the red, import side: a receiving load pocket, where congestion increases the price to attract generation.</li><li><code>SF &gt; 0</code> — the blue, export side: generation is trapped behind a limit, so congestion lowers price, sometimes below zero.</li></ul>
          <p>This two-sided footprint often follows the seam between a load pocket and a generation pocket. Because congestion is a sum, different constraints can cancel: a node may have large exposure to several constraints while its net congestion is near zero.</p>
        </section>

        <section aria-labelledby="recovery">
          <h2 id="recovery">Recovering the Shift Factors Matrix</h2>
          <p>ERCOT does not publish shift factors to the general public; they are considered Critical Energy Infrastructure Information because they can reveal topology and contingency responses. The other terms in the congestion equation—settled shadow prices, system price, and LMPs—are public, so shift factors are the remaining unknowns.</p>
          <ol><li><code>LMP = System Price (λ) + congestion</code></li><li><code>congestion = LMP − System Price (λ)</code></li><li><code>congestion = −Σ SF·μ</code></li></ol>
          <Formula>{"C = −M · SFᵀ"}</Formula>
          <ul><li><strong>C</strong>: congestion, hours × settlement points.</li><li><strong>M</strong>: shadow prices, hours × constraints.</li><li><strong>SF</strong>: shift factors, constraints × settlement points.</li></ul>
          <p>ERCOT provides <code>M</code> and <code>C</code>. ERCOT Stress solves for <code>SF</code> with ridge regression on a trailing 240-day window, refit weekly, with no load, weather, or other covariates. The recovered values are checked against settlement data: combined with settled shadow prices, they reproduce observed congestion with a residual measured on every refit.</p>
          <p>As an independent check, ERCOT’s Electrically Similar Settlement Points (ESSP) list identifies nodes that should share shift-factor signatures. Across 20 published ESSP groups, the recovered map matched every group. Public EIA-860 location data then attaches latitude and longitude to settlement points so footprints can be displayed on the map.</p>
          <p>See <a href="https://github.com/vergeman/ercotstress/blob/master/docs/MODELS.md">model details</a> and the <a href="https://github.com/vergeman/ercotstress/tree/master/compute/evaluation">ESSP evaluation</a>.</p>
        </section>

        <section aria-labelledby="forecast">
          <h2 id="forecast">Forecast</h2>
          <p>Once market-implied shift factors are recovered, the remaining task is to forecast tomorrow’s day-ahead shadow prices. For each constraint and hour, the model asks: will it bind, <code>P(bind)</code>; and if it does, how large will the shadow price be, <code>E[μ | bind]</code>?</p>
          <Formula>{"E[μ] = P(bind) × E[μ | bind]"}</Formula>
          <p>The probability model handles quiet zero-shadow-price hours; the magnitude model learns from non-zero settled hours. Both use expected load, wind, solar, outages, calendar effects, recent constraint history, and recovered location. Predicted μ values are projected through <code>−Σ SF·μ</code> to make tomorrow’s nodal map.</p>
        </section>

        <section aria-labelledby="evaluation">
          <h2 id="evaluation">Evaluation</h2>
          <p>The forecast is evaluated after settlement with three measures:</p>
          <ul><li><strong>Rank ρ (Spearman):</strong> whether forecast and settled congestion order the grid similarly.</li><li><strong>Top-Decile Hit:</strong> whether it found the most-congested tenth of nodes.</li><li><strong>Sign Agreement:</strong> whether it got the up-versus-down direction right relative to system price.</li></ul>
          <p>Those metrics are compared with honesty rails: <strong>persistence</strong> (repeat yesterday), <strong>climatology</strong> (a trailing historical average), and an <strong>oracle</strong> using realized shadow prices to isolate error in the shadow-price forecast from error in the recovered shift-factor map.</p>
        </section>

        <section aria-labelledby="case-studies">
          <h2 id="case-studies">Case Studies</h2>
          <p>Explore how the map and forecasts behaved during specific moments in ERCOT history.</p>
          <article><h3>Far West Sign Flip: June 20–21, 2025</h3><p>Overnight, the Permian imported power with congestion around <strong>+$34/MWh</strong>. By midday, <strong>5.6 GW</strong> of local solar saturated export paths and the area reached about <strong>−$24/MWh</strong>, turning into an export hub. The nodal map flips from an expensive receiving side to a cheap exporting side; a constraint footprint reveals the mechanism beneath both views.</p><div className="about-page__image-pair"><img src="/screenshots/far-west-1.png" alt="Far West congestion map during the overnight import period" /><img src="/screenshots/far-west-2.png" alt="Far West congestion map during the midday solar export period" /></div></article>
          <article><h3>Rabbit Hill: February 19–21, 2025</h3><p>A winter morning radial overload in an Austin suburb pushed local congestion to <strong>+$5,977/MWh</strong> at 6 a.m. on February 20, then down to <strong>+$242 by noon</strong>. The constraint peaked at <strong>$7,577</strong> on the 20th versus <strong>$323</strong> the prior day.</p><figure className="about-page__figure"><img src="/screenshots/rabbit-hill.png" alt="Rabbit Hill case-study congestion map" /></figure></article>
          <article><h3>Winter Storm Fern: January 24–26, 2026</h3><p>A winter storm created system-wide extremes in which scarcity and congestion coincided. The widest congestion spread was <strong>$1,618/MWh</strong> while system λ peaked near <strong>$1,915</strong>. Rio Grande Valley wind was bottled at <strong>−$1,454</strong>, while <code>PALACIOS_RN</code> reached <strong>$20,941</strong> at 0600.</p><div className="about-page__image-pair"><img src="/screenshots/winter-fern-lmp.png" alt="Winter Storm Fern locational marginal price map" /><img src="/screenshots/winter-fern-congestion.png" alt="Winter Storm Fern congestion map" /></div></article>
        </section>

        <section aria-labelledby="limitations">
          <h2 id="limitations">Limitations</h2>
          <ul><li>Persistence can outperform the forecast when weather and demand resemble the prior day.</li><li>The shift-factor matrix can drift because it is fit weekly from market-implied values, not official ERCOT values.</li><li>Binding is rare over a full day; most off-peak hours have no binding and no congestion.</li><li>Recovered shift factors are price-implied estimates, not ERCOT’s official PTDFs or market-network model.</li></ul>
        </section>
      </main>
    </div>
  );
}
