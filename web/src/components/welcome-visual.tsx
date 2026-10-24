/** Original decorative dental still life, drawn with CSS instead of photographs. */
export function WelcomeVisual() {
  return (
    <div className="welcome-visual" aria-hidden="true">
      <span className="welcome-window" />
      <span className="welcome-light" />
      <span className="welcome-surface" />
      <span className="welcome-shadow" />
      <span className="welcome-mirror">
        <span className="welcome-mirror-handle" />
      </span>
      <span className="welcome-tooth">
        <span className="welcome-root welcome-root-left" />
        <span className="welcome-root welcome-root-right" />
        <span className="welcome-crown-lobe welcome-crown-lobe-left" />
        <span className="welcome-crown-lobe welcome-crown-lobe-right" />
        <span className="welcome-crown" />
        <span className="welcome-enamel" />
      </span>
    </div>
  );
}
