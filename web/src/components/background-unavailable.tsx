import { useNavigate } from 'react-router-dom';
import { useCase } from '../state/case-store';
import { Button, Notice, PageHeading } from './ui';

/** Core staging stays useful without accepting work that no worker can process. */
export function BackgroundUnavailable() {
  const { caseId } = useCase();
  const navigate = useNavigate();
  return (
    <div className="page narrow stack">
      <PageHeading title="Enter details manually" />
      <Notice>
        Assistant analysis, document uploads and voice are unavailable in this
        version. You can still enter treatment and plan details, compare costs
        and save a plan. Use made-up details in this demo.
      </Notice>
      <Button
        onClick={() =>
          navigate(
            caseId
              ? `/intake/manual?caseId=${encodeURIComponent(caseId)}`
              : '/intake/manual',
          )
        }
      >
        Enter details step by step
      </Button>
      <Button variant="secondary" onClick={() => navigate('/')}>
        Back to Home
      </Button>
    </div>
  );
}
