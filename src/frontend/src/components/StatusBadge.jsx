const LABELS = {
  queued: "Queued",
  processing: "Comparing",
  retrying: "Retrying",
  done: "Done",
  failed: "Failed",
};

export default function StatusBadge({ status }) {
  return (
    <span className={`status status-${status}`}>
      <span className="dot" aria-hidden="true" />
      {LABELS[status] ?? status}
    </span>
  );
}
