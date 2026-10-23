import type { ReactNode } from 'react';
import './landing-illustrations.css';

type IllustrationKind = 'listening' | 'document' | 'plan' | 'estimate';

/** Original, static compositions of CSS geometry, separate from application UI. */
function Illustration({
  kind,
  children,
}: {
  kind: IllustrationKind;
  children: ReactNode;
}) {
  return (
    <div
      className={`landing-illustration landing-illustration--${kind}`}
      aria-hidden="true"
    >
      {children}
    </div>
  );
}

const WAVE_HEIGHTS = [
  14, 26, 18, 44, 68, 46, 83, 100, 65, 39, 72, 48, 28, 37, 14,
];

export function ListeningIllustration() {
  return (
    <Illustration kind="listening">
      <span className="landing-illustration__sound-ring landing-illustration__sound-ring--outer" />
      <span className="landing-illustration__sound-ring landing-illustration__sound-ring--inner" />
      <div className="landing-illustration__wave">
        {WAVE_HEIGHTS.map((height, index) => (
          <span key={index} style={{ height: `${height}%` }} />
        ))}
      </div>
      <span className="landing-illustration__sound-surface landing-illustration__sound-surface--back" />
      <span className="landing-illustration__sound-surface landing-illustration__sound-surface--front" />
      <span className="landing-illustration__sound-light" />
    </Illustration>
  );
}

export function DocumentIllustration() {
  return (
    <Illustration kind="document">
      <span className="landing-illustration__paper-orbit" />
      <span className="landing-illustration__paper landing-illustration__paper--back" />
      <div className="landing-illustration__paper landing-illustration__paper--front">
        <span className="landing-illustration__paper-fold" />
        <span className="landing-illustration__paper-mark" />
        <span className="landing-illustration__paper-line landing-illustration__paper-line--first" />
        <span className="landing-illustration__paper-line landing-illustration__paper-line--second" />
        <span className="landing-illustration__paper-line landing-illustration__paper-line--third" />
        <span className="landing-illustration__paper-line landing-illustration__paper-line--fourth" />
      </div>
      <span className="landing-illustration__paper-dot" />
    </Illustration>
  );
}

export function PlanIllustration() {
  return (
    <Illustration kind="plan">
      <span className="landing-illustration__plan-halo" />
      <span className="landing-illustration__plan-path landing-illustration__plan-path--upper" />
      <span className="landing-illustration__plan-path landing-illustration__plan-path--lower" />
      <span className="landing-illustration__plan-shape landing-illustration__plan-shape--first" />
      <span className="landing-illustration__plan-shape landing-illustration__plan-shape--second" />
      <span className="landing-illustration__plan-shape landing-illustration__plan-shape--third" />
      <span className="landing-illustration__plan-spark" />
    </Illustration>
  );
}

export function EstimateIllustration() {
  return (
    <Illustration kind="estimate">
      <span className="landing-illustration__estimate-halo" />
      <span className="landing-illustration__estimate-axis" />
      <span className="landing-illustration__estimate-layer landing-illustration__estimate-layer--first" />
      <span className="landing-illustration__estimate-layer landing-illustration__estimate-layer--second" />
      <span className="landing-illustration__estimate-layer landing-illustration__estimate-layer--third" />
      <span className="landing-illustration__estimate-light" />
    </Illustration>
  );
}
