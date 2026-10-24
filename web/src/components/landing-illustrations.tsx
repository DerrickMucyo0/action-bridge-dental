import {
  ArrowLeft,
  Camera,
  Check,
  ClipboardList,
  FileText,
  History,
  Home,
  Keyboard,
  Mic,
  Upload,
  UserRound,
} from 'lucide-react';
import type { ReactNode } from 'react';
import './landing-illustrations.css';

type IllustrationKind = 'listening' | 'document' | 'plan' | 'estimate';

/** Static promotional previews made from the application's visual language. */
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
      <div className="landing-illustration__screen">{children}</div>
      <div className="landing-illustration__home-indicator" />
    </div>
  );
}

function PreviewBrand() {
  return (
    <div className="landing-illustration__brand">
      <svg viewBox="0 0 40 40" fill="none">
        <path
          d="M19 24C11 24 5.5 18.5 5 9.5c8.5.2 14 5.2 14 14.5Z"
          fill="#69FFA5"
        />
        <path
          d="M21 24c0-9.3 5.5-14.3 14-14.5-.5 9-6 14.5-14 14.5Z"
          fill="#31E981"
        />
        <path
          d="M6 33.5c3.8-5 8.5-7.5 14-7.5s10.2 2.5 14 7.5"
          stroke="#31E981"
          strokeWidth="3"
          strokeLinecap="round"
        />
      </svg>
      <div>
        <strong>ActionBridge</strong>
        <span>Dental</span>
      </div>
    </div>
  );
}

function PreviewHeader({ back = false }: { back?: boolean }) {
  return (
    <div className="landing-illustration__header">
      {back ? (
        <ArrowLeft className="landing-illustration__back" />
      ) : (
        <PreviewBrand />
      )}
      <span className="landing-illustration__preview-label">UI PREVIEW</span>
    </div>
  );
}

function PreviewOrb() {
  return (
    <div className="landing-illustration__orb">
      <svg viewBox="0 0 200 200" fill="none">
        <circle cx="100" cy="100" r="96" stroke="#31E981" strokeOpacity=".1" />
        <circle cx="100" cy="100" r="80" stroke="#31E981" strokeOpacity=".12" />
        {[0, 60, 120].map((angle) => (
          <g key={angle} transform={`rotate(${angle} 100 100)`}>
            <ellipse
              cx="100"
              cy="100"
              rx="67"
              ry="39"
              stroke="#31E981"
              strokeOpacity=".09"
              strokeWidth="8"
            />
            <ellipse
              cx="100"
              cy="100"
              rx="67"
              ry="39"
              stroke="#84FFB6"
              strokeOpacity=".8"
              strokeWidth="1.4"
            />
          </g>
        ))}
        {[30, 90, 150].map((angle) => (
          <ellipse
            key={angle}
            transform={`rotate(${angle} 100 100)`}
            cx="100"
            cy="100"
            rx="55"
            ry="32"
            stroke="#31E981"
            strokeOpacity=".35"
          />
        ))}
      </svg>
    </div>
  );
}

const WAVE_HEIGHTS = [
  14, 26, 18, 44, 68, 46, 83, 100, 65, 39, 72, 48, 28, 37, 14,
];

export function ListeningIllustration() {
  return (
    <Illustration kind="listening">
      <PreviewHeader back />
      <div className="landing-illustration__intro">
        <span className="landing-illustration__eyebrow">TELL ME</span>
        <h3>Tell me about your treatment.</h3>
        <p>Speak naturally. Review your words before continuing.</p>
      </div>
      <PreviewOrb />
      <div className="landing-illustration__wave">
        {WAVE_HEIGHTS.map((height, index) => (
          <span key={index} style={{ height: `${height}%` }} />
        ))}
      </div>
      <p className="landing-illustration__quiet">Ready when you are</p>
      <div className="landing-illustration__microphone">
        <Mic />
      </div>
      <p className="landing-illustration__quiet">Tap to speak</p>
    </Illustration>
  );
}

export function DocumentIllustration() {
  return (
    <Illustration kind="document">
      <PreviewHeader back />
      <div className="landing-illustration__intro">
        <span className="landing-illustration__eyebrow">
          CHECK YOUR DETAILS
        </span>
        <h3>Review your document.</h3>
        <p>Your estimate and plan, one clear step at a time.</p>
      </div>
      <div className="landing-illustration__document">
        <FileText />
        <strong>TREATMENT ESTIMATE</strong>
        <span className="landing-illustration__document-rule" />
        <span className="landing-illustration__document-line" />
        <span className="landing-illustration__document-line landing-illustration__document-line--short" />
        <span className="landing-illustration__document-rule" />
        <span className="landing-illustration__document-line" />
        <span className="landing-illustration__document-line" />
        <span className="landing-illustration__document-line landing-illustration__document-line--short" />
      </div>
      <div className="landing-illustration__review-card">
        <Check />
        <div>
          <strong>You stay in control.</strong>
          <p>Confirm the details before calculating.</p>
        </div>
      </div>
      <div className="landing-illustration__cta">Review information</div>
    </Illustration>
  );
}

export function PlanIllustration() {
  return (
    <Illustration kind="plan">
      <PreviewHeader />
      <div className="landing-illustration__intro">
        <span className="landing-illustration__eyebrow">
          CLARITY BEFORE TREATMENT
        </span>
        <h3>Let's make sense of your dental costs.</h3>
        <p>Tell me about your treatment or add an estimate.</p>
      </div>
      <PreviewOrb />
      <div className="landing-illustration__methods">
        <div className="landing-illustration__cta">
          <Mic />
          Speak
        </div>
        <div className="landing-illustration__method-grid">
          {[
            { Icon: Upload, label: 'Upload' },
            { Icon: Camera, label: 'Photo' },
            { Icon: Keyboard, label: 'Type' },
          ].map(({ Icon, label }) => (
            <div key={label}>
              <Icon />
              <span>{label}</span>
            </div>
          ))}
        </div>
        <p>Enter details step by step</p>
      </div>
      <div className="landing-illustration__navigation">
        {[
          { Icon: Home, label: 'Home' },
          { Icon: ClipboardList, label: 'My plan' },
          { Icon: History, label: 'Activity' },
          { Icon: UserRound, label: 'Profile' },
        ].map(({ Icon, label }) => (
          <div key={label}>
            <Icon />
            <span>{label}</span>
          </div>
        ))}
      </div>
    </Illustration>
  );
}

export function EstimateIllustration() {
  return (
    <Illustration kind="estimate">
      <PreviewHeader back />
      <div className="landing-illustration__intro">
        <span className="landing-illustration__eyebrow">YOUR ESTIMATE</span>
        <h3>Making sense of your costs.</h3>
        <p>A clearer view of your treatment and benefits.</p>
      </div>
      <PreviewOrb />
      <div className="landing-illustration__steps">
        <div>
          <span>
            <Check />
          </span>
          <strong>Review treatment</strong>
        </div>
        <div>
          <span>
            <Check />
          </span>
          <strong>Check plan benefits</strong>
        </div>
        <div>
          <span className="landing-illustration__step-pending" />
          <strong>Compare permitted timing</strong>
        </div>
      </div>
      <p className="landing-illustration__quiet">
        Only confirmed details are used.
      </p>
    </Illustration>
  );
}
