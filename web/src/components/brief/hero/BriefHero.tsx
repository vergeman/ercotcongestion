import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { BriefHero as BriefHeroModel, HeroSegment } from "../../../api/types";
import MiniMap from "../../map/MiniMap";

function Segments({ segments }: { segments: HeroSegment[] }) {
  return (
    <>
      {segments.map((segment, index) => (
        <span key={`${segment.ref}-${index}`}>{segment.text}</span>
      ))}
    </>
  );
}

interface Props {
  hero: BriefHeroModel;
  settled: boolean;
  mobile: boolean;
  watchHref: string | null;
  evidence: ReactNode;
  evidenceLoading: boolean;
}

/** The progressive Brief shell; evidence can resolve after the hero narrative. */
export default function BriefHero({
  hero,
  settled,
  mobile,
  watchHref,
  evidence,
  evidenceLoading,
}: Props) {
  const title = hero.segments?.headline ?? [];
  return (
    <section className="an-hero" aria-labelledby="brief-title">
      <div className="an-hero__frame">
        {!mobile && hero.cursor && (
          <MiniMap
            mode="lmp"
            cursor={hero.cursor}
            basis={settled ? "settled" : "forecast"}
          />
        )}
        {watchHref && (
          <Link to={watchHref} className="an-hero__watch">
            {settled ? (
              <>
                <span>Watch prices</span>
                <span>move across the day →</span>
              </>
            ) : (
              <span>Watch the latest price forecast →</span>
            )}
          </Link>
        )}
        <div className="an-hero__body">
          <p className="an-eyebrow">Daily congestion brief</p>
          <h1 id="brief-title">
            <Segments segments={title} />
          </h1>
          <p className="an-lede">
            <Segments segments={hero.segments?.lede ?? []} />
          </p>
          <div className="an-facts-slot" aria-busy={evidenceLoading}>
            {evidenceLoading && (
              <div
                className="an-facts-loading"
                aria-label="Loading brief evidence"
              >
                <span className="an-loading-indicator" aria-hidden="true" />
              </div>
            )}
            {evidence}
          </div>
          {watchHref && (
            <div className="an-hero__meta">
              <Link to={watchHref} className="an-hero__watch-inline">
                Watch prices move across the day →
              </Link>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
