/** Original, decorative bridge geometry rendered entirely with HTML and CSS. */
export function WelcomeVisual() {
  return (
    <div className="welcome-visual" aria-hidden="true">
      <span className="welcome-visual-halo welcome-visual-halo-outer" />
      <span className="welcome-visual-halo welcome-visual-halo-inner" />
      <span className="welcome-visual-arch" />
      <span className="welcome-visual-light" />
      <span className="welcome-visual-baseline" />
      <span className="welcome-visual-endpoint welcome-visual-endpoint-left" />
      <span className="welcome-visual-endpoint welcome-visual-endpoint-right" />
    </div>
  );
}
