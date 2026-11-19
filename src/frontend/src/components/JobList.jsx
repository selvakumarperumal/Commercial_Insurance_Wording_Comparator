import { displayName, relativeTime } from "../format.js";
import StatusBadge from "./StatusBadge.jsx";

export default function JobList({ jobs, selectedId, onSelect }) {
  return (
    <section className="panel jobs">
      <div className="panel-head">
        <h2 className="panel-title">Comparisons</h2>
        {jobs.length > 0 && <span className="count-pill">{jobs.length}</span>}
      </div>

      {jobs.length === 0 ? (
        <p className="muted small">Your comparisons will appear here.</p>
      ) : (
        <ul>
          {jobs.map((job) => (
            <li key={job.job_id}>
              <button
                data-job={job.job_id}
                className={job.job_id === selectedId ? "job selected" : "job"}
                onClick={() => onSelect(job.job_id)}
              >
                <span className="job-name">{displayName(job.pdf_a)}</span>
                <span className="job-name job-vs">
                  <span className="muted">vs</span> {displayName(job.pdf_b)}
                </span>
                <span className="job-meta">
                  <StatusBadge status={job.status} />
                  <span className="muted">{relativeTime(job.created_at)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
