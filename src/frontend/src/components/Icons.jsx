// A few line icons (24px grid), drawn with the current text colour.
const PATHS = {
  upload: ["M12 15V4", "M7.5 8.5 12 4l4.5 4.5", "M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"],
  download: ["M12 4v11", "M7.5 10.5 12 15l4.5-4.5", "M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"],
  logout: ["M9 20H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h3", "M15 16.5 19.5 12 15 7.5", "M19.5 12H9"],
  alert: ["M12 3.5 21.5 20h-19z", "M12 10v4", "M12 17h.01"],
  close: ["M6 6l12 12", "M18 6 6 18"],
};

export function Icon({ name, size = 18 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

// Two overlapping pages: policy A and policy B.
export function Logo({ size = 28 }) {
  return (
    <svg className="logo" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect x="3" y="3" width="17" height="22" rx="3" fill="var(--a)" />
      <rect x="12" y="7" width="17" height="22" rx="3" fill="var(--b)" />
      <path d="M12 10v12a3 3 0 0 0 3 3h5V10a3 3 0 0 0-3-3h-2a3 3 0 0 0-3 3z" fill="var(--overlap)" />
    </svg>
  );
}

// Decorative pair of policy pages with a few highlighted lines.
export function DocsArt() {
  const lines = [
    [90, ""], [70, ""], [82, "a"], [60, ""], [88, ""], [74, "a"], [52, ""],
  ];
  const linesB = [
    [86, ""], [64, "b"], [78, ""], [90, ""], [58, "b"], [80, ""], [66, ""],
  ];
  return (
    <div className="docs-art" aria-hidden="true">
      {[["A", lines], ["B", linesB]].map(([tag, rows]) => (
        <div key={tag} className={`doc doc-${tag.toLowerCase()}`}>
          <span className={`letter tone-${tag.toLowerCase()}`}>{tag}</span>
          {rows.map(([width, tone], i) => (
            <span key={i} className={tone ? `line hl-${tone}` : "line"} style={{ width: `${width}%` }} />
          ))}
        </div>
      ))}
    </div>
  );
}
