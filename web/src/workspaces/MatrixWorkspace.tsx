export default function MatrixWorkspace() {
  return (
    <main className="matrix-workspace" aria-labelledby="matrix-title">
      <section className="matrix-workspace__placeholder">
        <span className="label">Explorer</span>
        <h1 id="matrix-title">Matrix</h1>
        <p>
          The Matrix workspace will appear here. Its frames will use the shared
          forecast window and playback cursor below.
        </p>
      </section>

      <style>{`
        .matrix-workspace {
          flex: 1;
          min-height: 0;
          display: grid;
          place-items: center;
          padding: 24px;
          background: var(--bg-base);
        }
        .matrix-workspace__placeholder {
          width: min(520px, 100%);
          padding: 28px;
          border: 1px solid var(--border);
          border-radius: 6px;
          background: var(--bg-panel);
          box-shadow: var(--shadow-panel);
        }
        .matrix-workspace__placeholder > .label { color: var(--accent); }
        .matrix-workspace h1 {
          margin: 6px 0 10px;
          font-size: var(--fs-display);
          font-family: var(--font-label);
          color: var(--text-primary);
        }
        .matrix-workspace p {
          color: var(--text-secondary);
          line-height: 1.5;
        }
      `}</style>
    </main>
  );
}
