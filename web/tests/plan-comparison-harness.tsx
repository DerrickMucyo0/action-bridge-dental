import React, { type ComponentProps } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import type {
  DentalCase,
  PlanComparisonRequest,
} from '@actionbridge/contracts';
import '@fontsource/plus-jakarta-sans/400.css';
import '@fontsource/plus-jakarta-sans/500.css';
import '@fontsource/plus-jakarta-sans/600.css';
import '@fontsource/plus-jakarta-sans/700.css';
import '../src/styles.css';
import { ComparisonResults } from '../src/features/plan-comparison/comparison-results';
import { ComparisonWorkspace } from '../src/features/plan-comparison/plan-comparison-page';

/** Component states stay in this test-only entry point, outside the application's routes. */
export type ComparisonTestProps = Omit<
  ComponentProps<typeof ComparisonResults>,
  'onRetry'
>;

declare global {
  interface Window {
    renderPlanComparisonTest: (props: ComparisonTestProps) => void;
    comparisonTestRetryCount: number;
    renderPlanComparisonFormTest: (record: DentalCase) => void;
    preparedComparisonTest: PlanComparisonRequest | null;
  }
}

const root = ReactDOM.createRoot(document.getElementById('root')!);
window.comparisonTestRetryCount = 0;
window.preparedComparisonTest = null;
window.renderPlanComparisonTest = (props) => {
  root.render(
    <React.StrictMode>
      <main className="page">
        <h1>Synthetic component test</h1>
        <p>Fictional test data only. These are not real insurance estimates.</p>
        <ComparisonResults
          {...props}
          onRetry={() => {
            window.comparisonTestRetryCount += 1;
          }}
        />
      </main>
    </React.StrictMode>,
  );
};
window.renderPlanComparisonFormTest = (record) => {
  window.preparedComparisonTest = null;
  root.render(
    <BrowserRouter>
      <main>
        <h1>Synthetic form component test</h1>
        <ComparisonWorkspace
          record={record}
          onCompare={(request) => {
            window.preparedComparisonTest = request;
          }}
        />
      </main>
    </BrowserRouter>,
  );
};
window.renderPlanComparisonTest({ request: null, state: { status: 'idle' } });
